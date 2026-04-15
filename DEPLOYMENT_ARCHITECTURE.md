# On-Device LLM Tester — Phase 7: Cloud Deployment Architecture

## 1. High-Level Overview

> **Architecture change (Step 5):** Switched from Render single-deploy to
> **Vercel (frontend) + Render (API) + Turso (DB)** split.
> Original §18.2 "future option" is now the primary deployment plan.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    CLOUD DEPLOYMENT (Phase 7)                                │
│                                                                              │
│  ┌─────────────────────────────────┐                                         │
│  │  Self-hosted Runner (dev PC)    │                                         │
│  │                                  │                                         │
│  │  runner.py → sync_results.py     │                                         │
│  │       │                          │                                         │
│  │       ▼                          │                                         │
│  │  ingest.py (DB_MODE=turso)       │                                         │
│  │    ├─ JSON parse + normalize     │                                         │
│  │    ├─ Batch INSERT → Turso       │  ← libsql-client (HTTP API)            │
│  │    └─ runs table metadata        │                                         │
│  └──────────────┬──────────────────┘                                         │
│                 │ HTTPS (libsql://)                                           │
│                 ▼                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐     │
│  │  Turso (libSQL Cloud)                                                │     │
│  │                                                                      │     │
│  │  libsql://llm-tester-db.turso.io                                     │     │
│  │  ├─ devices, models, prompts, results, runs                          │     │
│  │  ├─ 100% SQLite schema compatible                                    │     │
│  │  └─ Free Tier: 5GB storage, 500M rows read/mo                        │     │
│  └──────────┬──────────────────────────────────────────────────────────┘     │
│             │ HTTPS (libsql://)                                              │
│             ▼                                                                │
│  ┌──────────────────────────────────────────────────────────────────────┐     │
│  │  Render — API only (llm-tester-api.onrender.com)                    │     │
│  │                                                                      │     │
│  │  FastAPI + Uvicorn                                                   │     │
│  │    ├─ /api/* → Turso reads (libsql-client async)                    │     │
│  │    ├─ TTLCache (in-memory, reduces aggregate query load)            │     │
│  │    └─ CORS: ALLOWED_ORIGINS includes Vercel domain                  │     │
│  │                                                                      │     │
│  │  Free Tier: 750 hrs/mo, 512MB RAM                                   │     │
│  │  ※ 15 min idle → spin-down → Cold Start 30~60s                      │     │
│  └──────────────────────────────────────────────────────────────────────┘     │
│                                           ▲ /api/* (CORS)                    │
│  ┌──────────────────────────────────────────────────────────────────────┐     │
│  │  Vercel — Frontend (llm-tester.vercel.app)                          │     │
│  │                                                                      │     │
│  │  Vite build (React 18 + TypeScript + Tailwind)                      │     │
│  │    ├─ VITE_API_URL=https://llm-tester-api.onrender.com              │     │
│  │    ├─ SPA fallback via vercel.json rewrites                         │     │
│  │    └─ Instant global CDN — no Cold Start on UI                      │     │
│  │                                                                      │     │
│  │  Free Tier: unlimited bandwidth, 100GB/mo                           │     │
│  └──────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  Local dev:  Vite dev server (:5173) → proxy → FastAPI (:8000) → SQLite     │
│  Production: Vercel (UI) + Render (API) + Turso (DB)                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 2. Why This Architecture

### Render 단독 배포 — 왜 프론트/백을 한 곳에?

- **관리 포인트 1개**: 서비스 1개, 도메인 1개, 환경변수 1곳. CORS 설정 불필요 (동일 origin)
- **배포 단순화**: `vite build` → FastAPI `StaticFiles`로 서빙. 별도 프론트 호스팅 불필요
- **기존 코드 변경 최소**: 로컬 개발과 동일한 구조 (FastAPI가 API + 정적 파일 모두 서빙)
- **Cold Start 수용**: 사용자 소수 (개인/소규모 팀), 접속 빈도 낮음. 30~60초 대기 허용 가능. 문제 시 Vercel 프론트 분리로 전환 (§18.2)

### 왜 Vercel/Render 분리를 나중으로 미루는가?

- Cold Start가 **실제 문제인지** 아직 모름. 사용 패턴에 따라 UptimeRobot keep-alive만으로 해결될 수도 있음
- 분리하면 CORS 설정, 환경변수 분산, 배포 파이프라인 2개 관리 등 복잡도가 올라감
- Render 단독으로 시작 → Cold Start가 실제 병목이 되면 → Vercel 분리 (§18.2에 전환 가이드 포함)

### DB 분리가 필수인 이유

- Render 무료 플랜은 **persistent disk 없음**. deploy마다 파일시스템 초기화 → SQLite 파일 날아감
- 외부 DB (Turso) 필수

### Turso (libSQL) — 왜 이 DB인가?

- **SQLite 호환**: 기존 DDL (`CREATE TABLE IF NOT EXISTS`, `INSERT OR IGNORE`, `datetime('now')`, `PRAGMA`) 그대로 동작. SQL dialect 변환 비용 제로
- **기존 스키마 보존**: devices, models, prompts, results, runs 5개 테이블 + Phase 4a~6 마이그레이션 컬럼 전부 그대로 사용 가능
- **Free Tier**: 5GB 스토리지, 500M rows read/월, 10M rows write/월 — 벤치마크 데이터 규모(수천~수만 건)에 충분
- **Python SDK**: `libsql-client` 패키지가 동기/비동기 모두 지원. `client.batch()` API로 Batch INSERT 가능
- **HTTP API 기반**: 별도 서버/컨테이너 불필요. SDK가 HTTPS로 Turso 엔드포인트와 통신

### 기각된 대안

| 대안 | 기각 사유 |
|------|----------|
| **Supabase (PostgreSQL)** | SQLite → PostgreSQL 마이그레이션 필요. `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING`, `datetime('now')` → `NOW()`, `AUTOINCREMENT` → `SERIAL`, `PRAGMA` 제거 등 수십 군데 수정. DB_MIGRATION_ARCHITECTURE.md §13에서도 "실제 병목이 생길 때" 전환하기로 이미 결정 |
| **Neon (PostgreSQL)** | Supabase와 동일한 dialect 변환 비용. Free Tier는 좋지만 현 단계에서 PG 전환 불필요 |
| **PlanetScale (MySQL)** | DB_MIGRATION_ARCHITECTURE.md §2.3에서 이미 기각. JSON 쿼리 열세, FK 미지원 |
| **Firebase Firestore** | DB_MIGRATION_ARCHITECTURE.md §2.3에서 이미 기각. 복합 필터 composite index, percentile 집계 불가 |
| **S3/R2 오브젝트 스토리지** | 관계형 쿼리 불가. `WHERE device=? AND model=? AND category=?` 같은 복합 필터 + `GROUP BY` 집계를 클라이언트에서 해야 함. 데이터가 커지면 파탄 |
| **Railway** | Free Tier 월 $5 크레딧 → 소진 시 중단. Render(750시간 무료)가 예측 가능 |
| **Fly.io** | 좋은 선택이지만 Render 대비 설정 복잡도 높음 (fly.toml, VM 관리). 현 단계에서 과도 |
| **Cloudflare Workers** | Python 지원이 2026년 초 출시. FastAPI 래핑 가능하나 아직 mature하지 않음. Turso와의 조합은 미래 옵션 |
| **Vercel + Render 분리** | Cold Start 시 프론트 즉시 로딩 장점. 하지만 관리 포인트 2개, CORS 필요. Cold Start가 실제 문제가 되면 전환 (§18.2) |

### Render — 왜 이 호스팅인가?

- **Python 네이티브**: `requirements.txt` 감지 → 자동 빌드. Dockerfile 없이도 배포 가능
- **Git 연동**: GitHub push 시 자동 재배포
- **Free Tier**: 750시간/월 (사실상 단일 서비스 상시 가동 가능), 512MB RAM
- **제약**: 15분 무활동 시 spin-down → Cold Start 30~60초

## 3. Service Configuration

### 3.1 Turso Database 셋업

```bash
# 1. Turso CLI 설치
brew install tursodatabase/tap/turso    # macOS
# 또는
curl -sSfL https://get.tur.so/install.sh | bash    # Linux

# 2. 로그인
turso auth login

# 3. Database 생성 (리전: 시애틀 근처)
turso db create llm-tester-db --location sea

# 4. DB URL 확인
turso db show llm-tester-db --url
# → libsql://llm-tester-db-<username>.turso.io

# 5. Auth Token 생성
turso db tokens create llm-tester-db
# → eyJhbGciOiJFZDI1NTE5... (이 값을 안전하게 보관)
```

### 3.2 환경변수 관리

```
# .env (로컬 개발용 — .gitignore에 반드시 포함)
TURSO_URL=libsql://llm-tester-db-<username>.turso.io
TURSO_AUTH_TOKEN=eyJhbGciOiJFZDI1NTE5...

# 로컬 개발 시 SQLite 폴백 (Turso 미연결)
DB_MODE=local
DB_PATH=./api/data/llm_tester.db

# 프로덕션 (Render 환경변수에 설정)
DB_MODE=turso
TURSO_URL=libsql://llm-tester-db-<username>.turso.io
TURSO_AUTH_TOKEN=<token>

# GitHub Secrets (CI Runner용)
# Settings → Secrets and variables → Actions
# TURSO_URL, TURSO_AUTH_TOKEN
```

### 3.3 .gitignore 추가

```gitignore
# ── 기존 항목 ──
api/data/*.db

# ── Phase 7 추가 ──
.env
.env.local
.env.production
```

## 4. Database Connection Layer 변경

### 4.1 Dual-mode 연결 전략

로컬 개발은 기존 SQLite (`aiosqlite`), 프로덕션은 Turso (`libsql-client`)를 사용한다.
`DB_MODE` 환경변수로 분기하여 `loader.py`, `stats.py`, `main.py`의 SQL 쿼리는 **변경하지 않는다**.

```python
# api/db.py — 변경

import os
from contextlib import asynccontextmanager

DB_MODE = os.getenv("DB_MODE", "local")  # "local" | "turso"


@asynccontextmanager
async def lifespan(app):
    if DB_MODE == "turso":
        import libsql_client
        db = libsql_client.create_client(
            url=os.getenv("TURSO_URL"),
            auth_token=os.getenv("TURSO_AUTH_TOKEN"),
        )
        # Turso는 서버 측에서 WAL/FK 관리 → PRAGMA 불필요
    else:
        import aiosqlite
        db = await aiosqlite.connect(os.getenv("DB_PATH", "./data/llm_tester.db"))
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("PRAGMA busy_timeout=5000")

    await _init_tables(db)
    await _cleanup_zombie_runs(db)
    app.state.db = db
    app.state.db_mode = DB_MODE
    yield

    if DB_MODE == "turso":
        await db.close()
    else:
        await db.close()
```

### 4.2 쿼리 어댑터 패턴

`aiosqlite`와 `libsql-client`의 인터페이스가 다르므로, 얇은 래퍼로 통일한다.

```python
# api/db_adapter.py — NEW

from typing import Any, Optional
import os

DB_MODE = os.getenv("DB_MODE", "local")


class DbAdapter:
    """aiosqlite와 libsql-client의 인터페이스 차이를 흡수하는 래퍼.

    Used by: loader.py, stats.py (모든 DB 쿼리)
    Depends on: aiosqlite (local), libsql-client (turso)
    """

    def __init__(self, db, mode: str):
        self._db = db
        self._mode = mode

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        """SELECT 쿼리 실행 → list[dict] 반환."""
        if self._mode == "turso":
            rs = await self._db.execute(sql, params)
            columns = rs.columns
            return [dict(zip(columns, row)) for row in rs.rows]
        else:
            cursor = await self._db.execute(sql, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        rows = await self.fetchall(sql, params)
        return rows[0] if rows else None

    async def execute(self, sql: str, params: tuple = ()) -> None:
        if self._mode == "turso":
            await self._db.execute(sql, params)
        else:
            await self._db.execute(sql, params)
            await self._db.commit()

    async def executescript(self, sql: str) -> None:
        if self._mode == "turso":
            # Turso batch로 여러 문장 실행
            statements = [s.strip() for s in sql.split(";") if s.strip()]
            await self._db.batch(statements)
        else:
            await self._db.executescript(sql)
```

### 4.3 기존 코드 영향 범위

| 파일 | 변경 내용 | 변경 규모 |
|------|----------|----------|
| `api/db.py` | Dual-mode lifespan | 중 (30줄) |
| `api/db_adapter.py` | **신규** — 쿼리 래퍼 | 신규 (50줄) |
| `api/loader.py` | `db.execute()` → `adapter.fetchall()` | 소 (import + 호출부 교체) |
| `api/stats.py` | `db.execute()` → `adapter.fetchall()` | 소 (import + 호출부 교체) |
| `api/main.py` | `request.app.state.db` → `DbAdapter` 감싸기, 정적 파일 서빙 추가 | 소 (10줄) |
| `scripts/ingest.py` | `sqlite3.connect()` → `libsql_client` + Batch | **중** (핵심 변경) |

**변경하지 않는 것**: SQL 쿼리 문자열, Pydantic 스키마, API 엔드포인트 시그니처, 프론트엔드 코드

## 5. Ingest Pipeline 마이그레이션

### 5.1 핵심 변경: sqlite3 → libsql-client + Batch INSERT

```python
# scripts/ingest.py — 변경 요약

# Before (Phase 2):
#   con = sqlite3.connect(DB_PATH)
#   con.execute("INSERT OR IGNORE INTO ...", params)
#   con.commit()

# After (Phase 7):
#   client = libsql_client.create_client_sync(url, auth_token)
#   statements = [
#       libsql_client.Statement("INSERT OR IGNORE INTO ...", [params1]),
#       libsql_client.Statement("INSERT OR IGNORE INTO ...", [params2]),
#       ...  # 수백 개의 INSERT를 하나의 배치로
#   ]
#   client.batch(statements)  # 네트워크 왕복 1회
```

### 5.2 Batch 전략

| 항목 | 설계 |
|------|------|
| 배치 크기 | 100 statements/batch (Turso 권장 상한) |
| 왕복 횟수 | `ceil(total_inserts / 100)` — 300건 INSERT → 3회 왕복 |
| 에러 처리 | 배치 내 1건 실패 → 전체 롤백 (Turso batch 기본 동작). 실패 시 배치 단위로 재시도 |
| 순서 | dimension upsert (devices, models, prompts) 먼저 → results INSERT 배치 |
| 타임아웃 | `TURSO_BATCH_TIMEOUT=30` 초 (환경변수, 기본 30초) |

```python
# scripts/ingest.py — Batch INSERT 구현 핵심부

import libsql_client

BATCH_SIZE = 100  # Turso 권장 배치 크기

def ingest_turso(client: libsql_client.ClientSync, run_pk: int | None) -> tuple[int, int, int]:
    """Turso용 Batch INSERT 적재.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §5
    Used by: main() (CLI entry point)
    Depends on: parse_result_file(), upsert helpers
    """
    inserted = skipped = errors = 0

    json_files = sorted(RESULTS_DIR.rglob("*.json"))
    if not json_files:
        logger.warning("No JSON files found in %s", RESULTS_DIR)
        return inserted, skipped, errors

    # Phase 1: Dimension upserts (devices, models, prompts)
    # — 이것들은 건수가 적으므로 개별 실행 OK
    dim_statements = []
    for path in json_files:
        rec = parse_result_file(path)
        if rec is None:
            skipped += 1
            continue
        dim_statements.extend(_build_dimension_stmts(rec))

    if dim_statements:
        client.batch(dim_statements)

    # Phase 2: Results INSERT (건수 많음 → BATCH_SIZE 단위로 분할)
    result_stmts = []
    for path in json_files:
        rec = parse_result_file(path)
        if rec is None:
            continue
        stmt = _build_result_insert_stmt(rec, run_pk)
        if stmt:
            result_stmts.append(stmt)

    # 배치 분할 실행
    for i in range(0, len(result_stmts), BATCH_SIZE):
        batch = result_stmts[i:i + BATCH_SIZE]
        try:
            results = client.batch(batch)
            inserted += sum(1 for r in results if r.rows_affected > 0)
            skipped += sum(1 for r in results if r.rows_affected == 0)
        except Exception as e:
            logger.error("Batch %d-%d failed: %s", i, i + len(batch), e)
            errors += len(batch)

    return inserted, skipped, errors
```

### 5.3 Dual-mode 지원 (로컬 SQLite / Turso)

```python
# scripts/ingest.py — main() 변경

def main():
    args = parse_args()
    db_mode = os.getenv("DB_MODE", "local")

    if db_mode == "turso":
        url = os.getenv("TURSO_URL")
        token = os.getenv("TURSO_AUTH_TOKEN")
        if not url or not token:
            logger.error("TURSO_URL and TURSO_AUTH_TOKEN must be set when DB_MODE=turso")
            sys.exit(1)

        client = libsql_client.create_client_sync(url=url, auth_token=token)
        # DDL 실행 (init_tables)
        init_tables_turso(client)
        run_pk = create_run_turso(client, args) if args.run_id else None
        inserted, skipped, errors = ingest_turso(client, run_pk)
        if run_pk:
            finalize_run_turso(client, run_pk, "success" if errors == 0 else "error")
        client.close()
    else:
        # 기존 로직 유지 (sqlite3.connect)
        con = get_connection()
        init_tables(con)
        run_pk = create_run(con, args) if args.run_id else None
        inserted, skipped, errors = ingest(con, run_pk)
        if run_pk:
            finalize_run(con, run_pk, "success" if errors == 0 else "error")
        con.close()

    logger.info("Ingest complete: %d inserted, %d skipped, %d errors", inserted, skipped, errors)
```

### 5.4 네트워크 레이턴시 벤치마크 (예상)

| 방식 | 300건 INSERT 예상 소요 | 네트워크 왕복 |
|------|----------------------|-------------|
| 개별 INSERT (안티패턴) | ~60초 (200ms × 300) | 300회 |
| Batch INSERT (100건/배치) | ~1초 (200ms × 3) | 3회 |
| 로컬 SQLite (기존) | ~0.1초 | 0회 |

## 6. GitHub Actions Workflow 변경

### 6.1 YAML 변경

```yaml
# .github/workflows/benchmark.yml — Phase 7 변경 사항

    steps:
      # ... (기존 steps: Checkout, Setup Python, Install deps, Verify ADB) ...

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install libsql-client    # ← Phase 7 추가

      # ... (기존: Run benchmark, Sync results) ...

      - name: Ingest results to Turso
        env:
          DB_MODE: turso
          TURSO_URL: ${{ secrets.TURSO_URL }}
          TURSO_AUTH_TOKEN: ${{ secrets.TURSO_AUTH_TOKEN }}
        run: |
          python scripts/ingest.py \
            --run-id ${{ github.run_id }} \
            --trigger manual \
            --commit-sha ${{ github.sha }} \
            --branch ${{ github.ref_name }}

      # Upload artifact 유지 (백업용 — 로컬 .db도 여전히 생성)
      - name: Upload DB artifact (backup)
        uses: actions/upload-artifact@v4
        continue-on-error: true
        with:
          name: llm-tester-db-${{ github.run_id }}
          path: api/data/llm_tester.db
          retention-days: 30             # 90일 → 30일로 축소 (Turso가 primary)
```

### 6.2 GitHub Secrets 설정

```
Repository → Settings → Secrets and variables → Actions → New repository secret

Name: TURSO_URL
Value: libsql://llm-tester-db-<username>.turso.io

Name: TURSO_AUTH_TOKEN
Value: eyJhbGciOiJFZDI1NTE5...
```

### 6.3 기존 Artifact와의 관계

| 항목 | Phase 2 (기존) | Phase 7 (변경 후) |
|------|---------------|-------------------|
| Primary 데이터 저장소 | Runner 로컬 SQLite | Turso Cloud |
| GitHub Artifact 역할 | 전달 수단 + 백업 | 백업 전용 (보존 30일) |
| 대시보드 데이터 소스 | 로컬 .db 파일 | Turso (실시간) |
| CI 완료 → 대시보드 반영 | Artifact 다운로드 필요 | 즉시 반영 (Turso 직접 적재) |

## 7. Deployment (Vercel + Render + Turso)

> **Primary plan** — Vercel hosts the React frontend, Render hosts FastAPI (API only),
> Turso is the database. Originally §18.2; promoted to primary in Step 5.

### 7.1 Vercel — Frontend

```json
// dashboard/vercel.json
{
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "framework": "vite",
  "rewrites": [
    { "source": "/((?!api/).*)", "destination": "/index.html" }
  ]
}
```

```
// dashboard/.env.production
VITE_API_URL=https://llm-tester-api.onrender.com   // update after first Render deploy
```

```ts
// dashboard/src/api/client.ts — baseURL change
// Empty string in local dev → Vite proxy handles /api/*
const API_BASE_URL = import.meta.env.VITE_API_URL ?? ''
const client = axios.create({ baseURL: `${API_BASE_URL}/api`, ... })
```

Vercel setup:
1. Import GitHub repo → set Root Directory to `dashboard`
2. Add env var `VITE_API_URL` (Render API URL)
3. Auto-deploy on push to `main`

### 7.2 Render — API only

```yaml
# render.yaml
services:
  - type: web
    name: llm-tester-api
    runtime: python
    buildCommand: pip install -r api/requirements.txt
    startCommand: cd api && uvicorn main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: DB_MODE
        value: turso
      - key: TURSO_URL
        fromSecret: TURSO_URL
      - key: TURSO_AUTH_TOKEN
        fromSecret: TURSO_AUTH_TOKEN
      - key: ALLOWED_ORIGINS
        fromSecret: ALLOWED_ORIGINS   # e.g. https://llm-tester.vercel.app,http://localhost:5173
      - key: PYTHON_VERSION
        value: "3.11"
    plan: free
    autoDeploy: true
    branch: main
```

No static file serving in `api/main.py` — Vercel handles the frontend entirely.

### 7.3 CORS

Vercel and Render are different origins → CORS **required**.
`api/main.py` already reads `ALLOWED_ORIGINS` from env var (no code change needed):

```python
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
```

Set Render secret `ALLOWED_ORIGINS=https://llm-tester.vercel.app,http://localhost:5173`.

### 7.4 Health Check

`GET /health` implemented in `api/main.py` (Step 3).
Returns `{"status": "ok", "db_mode": "turso"}` on success, 503 on DB failure.

### 7.5 requirements.txt

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
pydantic>=2.7.0
python-dotenv
aiosqlite>=0.20.0
libsql-client>=0.3.0
cachetools>=5.3.0
```

### 7.6 Why Vercel + Render over Render single-deploy

| Factor | Render single | Vercel + Render |
|--------|--------------|-----------------|
| UI Cold Start | 30~60s (server spin-down affects UI too) | None (Vercel CDN always on) |
| Management | 1 service | 2 services, 1 domain each |
| CORS | Not needed | Required (env var only) |
| Frontend deploy | Bundled with API build | Independent, instant CDN |

## 8. Caching Strategy

### 8.1 왜 캐싱이 필요한가?

- Turso Free Tier: 500M rows read/월. 대시보드 Overview의 집계 쿼리가 매 요청마다 전체 results 테이블 scan → rows read 급증
- Render Free Tier: 0.1 CPU. 복잡한 집계 쿼리를 매번 처리하면 응답 지연
- 벤치마크 데이터는 CI 실행 시에만 추가됨 (하루 수회). 캐시 무효화 빈도 극히 낮음

### 8.2 구현

```python
# api/cache.py — NEW

from cachetools import TTLCache
from functools import wraps
import hashlib
import json

# 캐시: 최대 100개 항목, 5분 TTL
_cache = TTLCache(maxsize=100, ttl=300)


def cached_query(ttl: int = 300):
    """SQL 쿼리 결과를 인메모리 캐시.

    Architecture: DEPLOYMENT_ARCHITECTURE.md §8
    Used by: stats.py의 집계 함수들
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 캐시 키: 함수명 + 인자 해시
            key_data = f"{func.__name__}:{args[1:]}:{sorted(kwargs.items())}"
            cache_key = hashlib.md5(key_data.encode()).hexdigest()

            if cache_key in _cache:
                return _cache[cache_key]

            result = await func(*args, **kwargs)
            _cache[cache_key] = result
            return result
        return wrapper
    return decorator


def invalidate_cache():
    """CI ingest 완료 후 캐시 전체 무효화."""
    _cache.clear()
```

### 8.3 적용 대상

| 엔드포인트 | 캐시 TTL | 사유 |
|-----------|---------|------|
| `GET /api/results/summary` | 5분 | 전체 집계 → full scan. 가장 비싼 쿼리 |
| `GET /api/results/by-model` | 5분 | GROUP BY 집계 |
| `GET /api/results/by-category` | 5분 | GROUP BY 집계 |
| `GET /api/results` | 캐시 안 함 | 필터 조합이 다양하고 페이지네이션 → 캐시 히트율 낮음 |
| `GET /api/runs` | 캐시 안 함 | 데이터 소량, 쿼리 가벼움 |

### 8.4 캐시 무효화

- **자동**: TTL 5분 경과 시 자동 만료
- **수동**: `POST /api/cache/invalidate` 엔드포인트 (API Key 보호). CI 완료 후 호출 가능
- **앱 재시작**: Render deploy 시 인메모리 캐시 자동 초기화

## 9. Cold Start 대응

### 9.1 문제

Render 무료 플랜: 15분 무활동 → 서버 spin-down → 다음 요청 시 30~60초 Cold Start.
Render 단독 배포에서는 프론트엔드 HTML/CSS/JS도 함께 지연된다.

### 9.2 대응 전략

| 전략 | 구현 | 효과 |
|------|------|------|
| **Keep-alive (권장)** | 외부 Cron (UptimeRobot 무료) → `/health` 14분마다 ping | Cold Start 자체 방지. **가장 효과적** |
| **Loading 상태 표시** | 이미 구현됨 (`LoadingSkeleton`) | 서버 깨어난 후 데이터 로딩 시 빈 화면 방지 |
| **Vercel 프론트 분리 (§18.2)** | Cold Start가 실제 UX 문제 시 전환 | UI 즉시 표시, 데이터만 지연 |

### 9.3 UptimeRobot 설정 (권장)

```
UptimeRobot (무료 플랜: 50 모니터)
  URL: https://llm-tester.onrender.com/health
  Monitor Type: HTTP(s)
  Monitoring Interval: 14분
  Alert: 이메일 (서비스 다운 시)
```

이렇게 하면 Render 서버가 spin-down되기 전에 항상 ping이 와서 Cold Start를 방지한다. Render 무료 플랜 750시간/월 = 31.25일 상시 가동이므로 단일 서비스면 한도 내.

## 10. Security

### 10.1 Secrets 관리

| Secret | 저장 위치 | 용도 |
|--------|----------|------|
| `TURSO_URL` | GitHub Secrets, Render env | DB 연결 URL |
| `TURSO_AUTH_TOKEN` | GitHub Secrets, Render env | DB 인증 토큰 |
| `API_KEY` | Render env (선택) | API 접근 제어 |

### 10.2 보안 체크리스트

- [ ] `.env` 파일이 `.gitignore`에 포함되어 있는지 확인
- [ ] GitHub Secrets에 TURSO_URL, TURSO_AUTH_TOKEN 등록
- [ ] Render 환경변수에 동일 값 등록
- [ ] Turso Auth Token 만료일 확인 (기본 무기한, 필요 시 갱신)
- [ ] API_KEY 설정 시 프론트엔드에서도 헤더 전송 설정

### 10.3 Turso 접근 제어

```bash
# Read-only 토큰 (FastAPI 백엔드용 — 대시보드는 읽기만)
turso db tokens create llm-tester-db --read-only

# Full access 토큰 (CI Runner용 — INSERT 필요)
turso db tokens create llm-tester-db
```

Render 백엔드에는 **read-only 토큰**을, CI Runner에는 **full access 토큰**을 사용하여 최소 권한 원칙 적용.

## 11. Data Flow (Before vs After)

### Phase 2 (기존)

```
Runner PC
  ├─ runner.py → sync_results.py → results/*.json
  │
  ├─ ingest.py → api/data/llm_tester.db (로컬 SQLite)
  │
  ├─ upload-artifact → GitHub Artifact (90일 보존)
  │
  └─ 로컬에서 FastAPI + Vite dev server 수동 실행
     └─ localhost:5173 + localhost:8000
        └─ 로컬 .db 파일 읽기
```

### Phase 7 (변경 후)

```
Runner PC
  ├─ runner.py → sync_results.py → results/*.json
  │
  ├─ ingest.py (DB_MODE=turso)
  │    └─ Batch INSERT → Turso Cloud (HTTPS)
  │
  └─ upload-artifact → GitHub Artifact (30일 백업)

Turso Cloud (llm-tester-db.turso.io)
  └─ devices, models, prompts, results, runs

Render (llm-tester.onrender.com)
  └─ FastAPI + Vite build (단일 서비스)
     ├─ /api/* → Turso 읽기 (libsql-client async)
     └─ /* → React SPA (정적 파일)
```

## 12. Error Handling

### 12.1 Ingest (CI Pipeline)

| 상황 | 처리 |
|------|------|
| Turso 연결 실패 | 로그 출력 + exit(1) → CI step 실패 |
| Batch INSERT 부분 실패 | 해당 배치 롤백 + 에러 카운트. 다음 배치 계속 |
| Turso rate limit | 지수 백오프 재시도 (1초, 2초, 4초) 최대 3회 |
| 네트워크 타임아웃 | 30초 후 재시도 1회 → 실패 시 에러 기록 |
| `TURSO_URL` 미설정 | 즉시 에러 로그 + exit(1) |

### 12.2 API (Render)

| 상황 | 처리 |
|------|------|
| Turso 연결 실패 | `/health` → 503. 쿼리 → 500 + `ApiError` |
| 쿼리 타임아웃 | Turso 기본 5초 타임아웃. 500 + `ApiError` |
| 캐시 실패 | 캐시 우회 → 직접 쿼리 (graceful degradation) |
| Cold Start 중 요청 | Uvicorn이 요청 큐잉 → 응답 지연 (에러 아님) |
| 정적 파일 누락 | SPA fallback → index.html 반환 |

## 13. Monitoring & Observability

### 13.1 무료 모니터링 스택

| 도구 | 용도 | Free Tier |
|------|------|-----------|
| **UptimeRobot** | Render 서버 가동 시간 + Cold Start 방지 | 50 모니터, 5분 간격 |
| **Turso Dashboard** | DB 스토리지, rows read/write, 커넥션 수 | 무료 포함 |
| **Render Dashboard** | 서버 로그, 배포 이력, 리소스 사용량 | 무료 포함 |

### 13.2 커스텀 로깅

```python
# api/main.py — 요청 로깅 미들웨어 (선택)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    import time
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start

    if duration > 2.0:  # 2초 이상 걸린 요청만 경고
        logger.warning(
            "Slow request: %s %s → %d (%.2fs)",
            request.method, request.url.path,
            response.status_code, duration,
        )
    return response
```

## 14. Migration Strategy

### 14.1 원칙

- **API 계약 불변**: 프론트엔드가 바라보는 `ApiSuccess<T>`, `ApiError`, `PaginationMeta` 스키마 변경 없음
- **점진 전환**: 로컬 SQLite → Turso를 `DB_MODE` 환경변수로 전환. 롤백 = 환경변수 변경
- **데이터 보존**: 기존 로컬 .db 데이터를 Turso로 마이그레이션 후 검증
- **하위 호환**: `DB_MODE=local` 시 기존 동작 100% 유지

### 14.2 데이터 마이그레이션 (로컬 → Turso)

```bash
# 기존 로컬 DB를 Turso로 일괄 마이그레이션
# 1. Turso CLI로 DB 생성 (§3.1)
# 2. 로컬 .db에서 SQL dump
sqlite3 api/data/llm_tester.db .dump > dump.sql

# 3. Turso CLI로 dump import
turso db shell llm-tester-db < dump.sql

# 4. 검증
turso db shell llm-tester-db "SELECT COUNT(*) FROM results"
turso db shell llm-tester-db "SELECT COUNT(*) FROM devices"
```

### 14.3 Rollback 계획

| 상황 | 롤백 방법 |
|------|----------|
| Turso 장애 | `DB_MODE=local` + 로컬 .db로 전환 (Render 환경변수 1개) |
| Render 장애 | 로컬 FastAPI 서버 직접 실행 (`uvicorn main:app`) |
| 전체 클라우드 장애 | `DB_MODE=local` + 로컬 전체 스택 (기존과 동일) |

## 15. Cost Analysis

### 15.1 Free Tier 한계 분석

| 서비스 | 무료 한도 | 예상 사용량 | 여유도 |
|--------|----------|-----------|--------|
| **Turso** 스토리지 | 5GB | ~50MB (수만 건 벤치마크 결과) | 100배+ |
| **Turso** rows read/월 | 500M | ~10M (Overview 집계 + 필터 쿼리 × 일 수십 회) | 50배 |
| **Turso** rows write/월 | 10M | ~1K (CI 실행 시 수백 건 INSERT × 월 수회) | 10000배 |
| **Render** 시간/월 | 750시간 | 744시간 (31일 상시 가동) | 거의 한계 |

### 15.2 유료 전환 트리거

- Turso: 데이터 500MB 초과 또는 rows read 500M 초과 → Developer $4.99/월
- Render: 2개 이상 서비스 또는 Cold Start 허용 불가 → Starter $7/월

### 15.3 현재 단계 예상 비용

**$0/월** — 모든 서비스 무료 플랜 내에서 운영 가능

## 16. Directory Structure Changes

```
on-device-llm-tester/
├── .github/
│   └── workflows/
│       └── benchmark.yml               # Phase 7: DB_MODE=turso 환경변수 추가
│
├── api/
│   ├── main.py                          # Phase 7: /health, 정적 파일 서빙 추가
│   ├── db.py                            # Phase 7: Dual-mode lifespan (local/turso)
│   ├── db_adapter.py                    # ✨ NEW — aiosqlite/libsql 인터페이스 통일
│   ├── cache.py                         # ✨ NEW — TTLCache 래퍼
│   ├── loader.py                        # Phase 7: DbAdapter 사용으로 호출부 변경
│   ├── stats.py                         # Phase 7: @cached_query 데코레이터 적용
│   ├── schemas.py                       # 변경 없음
│   └── requirements.txt                 # Phase 7: libsql-client, cachetools 추가
│
├── dashboard/
│   ├── src/                             # 변경 없음
│   ├── dist/                            # Render build 시 생성 → FastAPI가 서빙
│   └── vite.config.ts                   # 변경 없음
│
├── scripts/
│   └── ingest.py                        # Phase 7: Dual-mode (local/turso) + Batch INSERT
│
├── render.yaml                          # ✨ NEW — Render Blueprint
├── .env                                 # ✨ NEW — 로컬 환경변수 (.gitignore)
├── .gitignore                           # Phase 7: .env* 패턴 추가
└── DEPLOYMENT_ARCHITECTURE.md           # ✨ NEW — 이 문서
```

## 17. Implementation Order

```
Step 1: Turso 셋업
        → CLI 설치 + 로그인
        → DB 생성 (llm-tester-db, 리전 sea)
        → Auth Token 생성 (full + read-only)
        → 로컬 .db → Turso 데이터 마이그레이션 (dump + import)
        → 검증: turso db shell로 SELECT COUNT 확인

Step 2: ingest.py 마이그레이션
        → libsql-client 의존성 추가 (requirements.txt)
        → Dual-mode 분기 (DB_MODE 환경변수)
        → Batch INSERT 구현 (BATCH_SIZE=100)
        → 로컬 테스트: DB_MODE=turso 로 ingest 실행 → Turso에 데이터 적재 확인
        → CI 테스트: GitHub Secrets 등록 → workflow 실행 → Turso 데이터 확인

Step 3: FastAPI → Turso 연결
        → api/db.py Dual-mode lifespan 구현
        → api/db_adapter.py 쿼리 래퍼 구현
        → loader.py, stats.py 호출부 교체
        → /health 엔드포인트 추가
        → 로컬 테스트: DB_MODE=turso 로 FastAPI 실행 → Swagger에서 확인

Step 4: 캐싱
        → api/cache.py 구현
        → stats.py 집계 함수에 @cached_query 적용
        → 캐시 무효화 엔드포인트 추가

Step 5: Render 배포
        → render.yaml 작성 (빌드: npm build + pip install)
        → main.py에 정적 파일 서빙 + SPA fallback 추가
        → Render 대시보드에서 서비스 생성
        → 환경변수 설정 (TURSO_URL, TURSO_AUTH_TOKEN)
        → 배포 확인: https://...onrender.com/health
        → API 엔드포인트 검증: /api/results/summary
        → 대시보드 UI 검증: https://...onrender.com/

Step 6: 통합 테스트 + 정리
        → E2E: 대시보드 → API → Turso DB 전체 흐름 확인
        → CI 실행 → Turso 적재 → 대시보드 실시간 반영 확인
        → UptimeRobot 설정 (Cold Start 방지)
        → README.md 업데이트 (배포 URL, 환경변수 설명)
```

## 18. Future Extensions

### 18.1 Phase 7 이후 고려사항

| 확장 | 설명 | 트리거 |
|------|------|--------|
| **Vercel 프론트 분리** | Cold Start로 UX 불만 시, Vercel에 정적 파일 분리 배포 → UI 즉시 로딩 | Cold Start가 실제 문제로 제기될 때 |
| **Turso Embedded Replica** | Render 서버에 로컬 복제본 유지 → 읽기 레이턴시 0ms | 쿼리 응답 지연 체감 시 |
| **Cloudflare Workers 전환** | Python Workers 성숙 시 Render 대체 → Cold Start 완전 제거 | CF Python Workers GA 출시 시 |
| **커스텀 도메인** | `dashboard.llm-tester.dev` 같은 도메인 연결 | 외부 공유 필요 시 |
| **CI 완료 Webhook** | ingest 완료 → Render `/api/cache/invalidate` 자동 호출 | 캐시 실시간 무효화 필요 시 |
| **PostgreSQL 전환** | Turso → Supabase/Neon | 데이터 100만건+ 또는 10+ 동시 writer |

### 18.2 Vercel 프론트 분리 전환 가이드

Cold Start가 실제 UX 문제가 될 때, 다음 절차로 전환한다:

```
1. dashboard/vercel.json 생성
   {
     "buildCommand": "npm run build",
     "outputDirectory": "dist",
     "framework": "vite",
     "rewrites": [{ "source": "/((?!api/).*)", "destination": "/index.html" }]
   }

2. dashboard/.env.production 생성
   VITE_API_URL=https://llm-tester-api.onrender.com

3. dashboard/src/api/client.ts 수정
   const API_BASE_URL = import.meta.env.VITE_API_URL || '';

4. api/main.py에 CORS ALLOWED_ORIGINS 추가
   ALLOWED_ORIGINS=https://llm-tester.vercel.app,http://localhost:5173

5. Vercel 프로젝트 생성 (Root Directory: dashboard)

6. render.yaml 수정
   - buildCommand에서 npm build 제거 (프론트 빌드 불필요)
   - main.py에서 정적 파일 서빙 제거
   - 서비스명 llm-tester → llm-tester-api로 변경

7. Render 환경변수 ALLOWED_ORIGINS 추가
```

변경 포인트가 명확하므로 1~2시간 내 전환 가능. 기존 Render 배포를 유지하면서 Vercel을 추가하는 것이므로 다운타임 없음.

### 18.3 기존 아키텍처 문서와의 관계

```
DASHBOARD_ARCHITECTURE.md     §10 Tech Stack → Phase 7에서 배포 플랫폼 추가
DB_MIGRATION_ARCHITECTURE.md  §13 PostgreSQL 경로 → Phase 7 이후에도 유효
CICD_ARCHITECTURE.md          §6 Artifact → Phase 7에서 백업 전용으로 전환
                              §7 ingest.py → Phase 7에서 Turso 모드 추가
```

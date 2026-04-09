# On-Device LLM Tester — Phase 1.5: DB Migration Architecture

## 1. High-Level Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     DATA PIPELINE (Phase 1.5)                            │
│                                                                          │
│  Android App ──→ JSON files (앱 샌드박스)                                 │
│       │                                                                  │
│       ▼                                                                  │
│  sync_results.py (기존 유지)                                              │
│    ├─ ADB run-as로 앱 샌드박스에서 JSON 읽기                               │
│    ├─ device.model + model_name 기준 디렉토리 자동 분류                    │
│    └─ 결과: results/{device}/{model}/*.json                              │
│                │                                                         │
│                ▼                                                         │
│  ┌─────────────────────────┐                                             │
│  │  ingest.py (✨ NEW)      │   JSON → SQLite 적재                        │
│  │  - 파일 순회 + 파싱      │   중복 방지 (prompt_id + model + device)     │
│  │  - bulk INSERT           │   기존 JSON 파일 보존 (삭제 안 함)           │
│  │  - 적재 리포트 출력      │                                             │
│  └───────────┬─────────────┘                                             │
│              │                                                           │
│              ▼                                                           │
│  ┌──────────────────────────┐    ┌──────────────────────────────┐        │
│  │  SQLite DB               │    │  React Dashboard (변경 없음)  │        │
│  │  data/llm_tester.db      │    │  :5173                        │        │
│  │                          │    │                               │        │
│  │  Tables:                 │    │  Overview      (KPI cards)    │        │
│  │   - results              │    │  Performance   (charts)       │        │
│  │   - devices              │    │  Model Compare (side-by-side) │        │
│  │   - models               │    │  Response QA   (output viewer)│        │
│  │   - prompts              │    │  Raw Data      (table)        │        │
│  │                          │    │                               │        │
│  │  WAL mode (동시 R/W)     │    │  ※ API 응답 스키마 동일       │        │
│  └──────────┬───────────────┘    │  ※ 프론트엔드 수정 제로       │        │
│             │                    └──────────────────────────────┘        │
│             ▼                              ▲                             │
│  ┌──────────────────────────┐              │                             │
│  │  FastAPI (api/)           │──────────────┘                             │
│  │  :8000                    │                                            │
│  │                           │                                            │
│  │  ✨ CHANGED:              │                                            │
│  │  - db.py (NEW)            │  커넥션 풀 + async 쿼리                    │
│  │  - loader.py → DB 쿼리    │  파일시스템 순회 → SQL SELECT               │
│  │  - stats.py → SQL 집계    │  Python 루프 → SQL GROUP BY / percentile   │
│  │                           │                                            │
│  │  ✅ UNCHANGED:            │                                            │
│  │  - main.py (엔드포인트)   │  API 시그니처 동일                          │
│  │  - schemas.py             │  Pydantic 모델 동일                         │
│  └──────────────────────────┘                                            │
└──────────────────────────────────────────────────────────────────────────┘
```

## 2. Why SQLite

### 2.1 DB 후보 비교

| DB | 인프라 | 필터/집계 | Phase 2 CI | Phase 3 Multi-device | FastAPI 통합 | 판정 |
|----|--------|-----------|------------|---------------------|-------------|------|
| **SQLite** | Zero (파일 1개) | SQL native | artifact로 전달 | WAL mode | aiosqlite async | **✅ 1순위** |
| PostgreSQL | 서버 필요 | JSONB + 윈도우함수 | Docker compose | 동시성 완벽 | asyncpg | 스케일 대비용 |
| Supabase | 호스팅 PG | PG 동일 | REST API | 동시성 완벽 | REST/SDK | 팀 공유 시 |
| MySQL | 서버 필요 | 8.0+ 윈도우함수 | Docker compose | 동시성 OK | aiomysql | PG 하위호환 |
| Firebase | 호스팅 | 복합필터 제한 | REST API | realtime sync | REST 호출 | 미스매치 |
| DuckDB | Zero (파일 1개) | OLAP 최적화 | artifact로 전달 | OLTP 약함 | async 미성숙 | 분석 특화 |

### 2.2 SQLite를 선택한 이유

- **마이그레이션 비용 최소**: JSON 파일시스템 순회 → 단일 `.db` 파일. 별도 서버 프로세스 불필요. `pip install aiosqlite` 하나로 끝
- **현재 아키텍처와 핏**: API 레이어(main.py, schemas.py)가 이미 존재. loader.py/stats.py만 DB 쿼리로 교체하면 프론트엔드 수정 제로
- **SQL로 기존 Python 로직 대체**: `stats.py`의 percentile/group by/filter를 Python 루프 대신 SQL로 처리 → 코드량 대폭 감소, 성능 향상
- **Phase 로드맵 호환**: Phase 2 CI에서 `.db` 파일을 artifact로 넘기면 됨. Phase 3 멀티디바이스 동시 쓰기는 WAL 모드로 커버 (배치 쓰기 + 대시보드 읽기 패턴)
- **탈출 경로 확보**: SQL → SQL이라 PostgreSQL 마이그레이션 시 쿼리 90%+ 재사용 가능. 실제 병목이 생길 때 올리면 됨

### 2.3 기각 사유

- **Firebase Firestore**: `WHERE device=? AND model=? AND category=? AND backend=? AND status=?` 복합 필터에 composite index 필요. percentile 집계 불가 → 클라이언트 사이드 처리 필수. 읽기 횟수 기반 과금
- **MySQL**: PostgreSQL 대비 JSON 쿼리 능력 약함. 별도 서버 필요한 것은 PG와 동일한데 기능은 열세. 팀 내 MySQL DBA 부재 시 선택 이유 없음
- **Supabase**: 본질은 호스팅 PostgreSQL. 외부 의존성 + Docker(`supabase start`)이 현재 로컬 개발 단계에서는 불필요한 복잡도
- **DuckDB**: OLAP 분석에 강하지만 FastAPI용 async 드라이버 미성숙. 커뮤니티/레퍼런스 부족

## 3. Database Schema

### 3.1 ERD

```
┌─────────────┐       ┌──────────────┐       ┌──────────────┐
│   devices    │       │   results    │       │    models    │
├─────────────┤       ├──────────────┤       ├──────────────┤
│ PK id       │◄──┐   │ PK id        │   ┌──►│ PK id        │
│ manufacturer │   │   │ FK device_id │───┘   │ model_name   │
│ model        │   └───│ FK model_id  │       │ model_path   │
│ product      │       │ FK prompt_id │──┐    │ backend      │
│ soc          │       │ status       │  │    └──────────────┘
│ android_ver  │       │ latency_ms   │  │
│ sdk_int      │       │ init_time_ms │  │    ┌──────────────┐
│ cpu_cores    │       │ response     │  │    │   prompts    │
│ max_heap_mb  │       │ error        │  │    ├──────────────┤
│ created_at   │       │ timestamp    │  └───►│ PK id        │
└─────────────┘       │              │       │ prompt_id    │
                      │ ── metrics ──│       │ category     │
                      │ ttft_ms      │       │ lang         │
                      │ prefill_ms   │       │ prompt_text  │
                      │ decode_ms    │       └──────────────┘
                      │ input_tokens │
                      │ output_tokens│
                      │ prefill_tps  │
                      │ decode_tps   │
                      │ peak_java_mb │
                      │ peak_native  │
                      │ itl_p50_ms   │
                      │ itl_p95_ms   │
                      │ itl_p99_ms   │
                      │ created_at   │
                      └──────────────┘
```

### 3.2 테이블 정의 (DDL)

```sql
-- ── devices ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS devices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer  TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    product       TEXT NOT NULL DEFAULT '',
    soc           TEXT NOT NULL DEFAULT '',
    android_version TEXT NOT NULL DEFAULT '',
    sdk_int       INTEGER NOT NULL DEFAULT 0,
    cpu_cores     INTEGER NOT NULL DEFAULT 0,
    max_heap_mb   INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(manufacturer, model, product)  -- 동일 기기 중복 방지
);

-- ── models ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS models (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name  TEXT NOT NULL DEFAULT '',
    model_path  TEXT NOT NULL DEFAULT '',
    backend     TEXT NOT NULL DEFAULT '',    -- 'CPU' | 'GPU'
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(model_name, model_path, backend)
);

-- ── prompts ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prompts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id   TEXT NOT NULL UNIQUE,        -- test_config.json의 id (e.g. 'math_01')
    category    TEXT NOT NULL DEFAULT '',     -- 'math', 'reasoning', 'code', etc.
    lang        TEXT NOT NULL DEFAULT 'en',
    prompt_text TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── results (핵심 테이블) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     INTEGER NOT NULL REFERENCES devices(id),
    model_id      INTEGER NOT NULL REFERENCES models(id),
    prompt_id     INTEGER NOT NULL REFERENCES prompts(id),

    -- status & timing
    status        TEXT NOT NULL CHECK(status IN ('success', 'error')),
    latency_ms    REAL,
    init_time_ms  REAL,

    -- response content
    response      TEXT NOT NULL DEFAULT '',
    error         TEXT,

    -- metrics (success일 때만 값 존재, error일 때 NULL)
    ttft_ms             REAL,
    prefill_time_ms     REAL,
    decode_time_ms      REAL,
    input_token_count   INTEGER,
    output_token_count  INTEGER,
    prefill_tps         REAL,
    decode_tps          REAL,
    peak_java_memory_mb REAL,
    peak_native_memory_mb REAL,
    itl_p50_ms          REAL,
    itl_p95_ms          REAL,
    itl_p99_ms          REAL,

    -- metadata
    timestamp     INTEGER,                   -- Android epoch (밀리초)
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),

    -- 중복 방지: 동일 프롬프트 + 모델 + 디바이스 + 타임스탬프
    UNIQUE(device_id, model_id, prompt_id, timestamp)
);

-- ── Indexes (쿼리 패턴 기반) ────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_results_status     ON results(status);
CREATE INDEX IF NOT EXISTS idx_results_device     ON results(device_id);
CREATE INDEX IF NOT EXISTS idx_results_model      ON results(model_id);
CREATE INDEX IF NOT EXISTS idx_results_prompt     ON results(prompt_id);
CREATE INDEX IF NOT EXISTS idx_results_timestamp  ON results(timestamp DESC);

-- 복합 인덱스: 대시보드 필터 조합 최적화
CREATE INDEX IF NOT EXISTS idx_results_filter
    ON results(device_id, model_id, status);
```

### 3.3 정규화 설계 근거

| 결정 | 이유 |
|------|------|
| **metrics를 results 테이블에 flat으로 포함** | 별도 metrics 테이블로 분리하면 JOIN 비용 발생. metrics는 항상 result와 1:1이고 독립 쿼리 불필요. 컬럼 12개 추가가 JOIN보다 낫다 |
| **devices/models/prompts 정규화** | 동일 디바이스·모델·프롬프트가 수백 번 반복. TEXT 중복 저장 대비 FK INTEGER 참조가 저장 효율적이고 필터 성능 우수 |
| **UNIQUE 제약으로 중복 방지** | `ingest.py`를 여러 번 실행해도 동일 결과가 중복 INSERT 되지 않음. `INSERT OR IGNORE` 패턴 사용 |
| **response를 results에 포함** | Phase 4 AI Quality Eval에서 response 텍스트를 GPT API에 보내야 함. 별도 테이블 불필요 |

### 3.4 Phase 확장 대비 컬럼

```sql
-- Phase 4: AI Quality Eval 추가 시
ALTER TABLE results ADD COLUMN quality_score    REAL;
ALTER TABLE results ADD COLUMN quality_verdict  TEXT;     -- 'pass' | 'fail' | 'partial'
ALTER TABLE results ADD COLUMN quality_feedback TEXT;     -- GPT 피드백 원문

-- Phase 2: CI/CD Run 추적 시
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL UNIQUE,     -- GitHub Actions run ID
    trigger     TEXT NOT NULL DEFAULT '', -- 'manual' | 'push' | 'schedule'
    commit_sha  TEXT,
    branch      TEXT,
    started_at  TEXT,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running'
);
ALTER TABLE results ADD COLUMN run_id INTEGER REFERENCES runs(id);
```

## 4. Directory Structure (변경사항)

```
on-device-llm-tester/
├── api/
│   ├── main.py                 # ✅ 엔드포인트 시그니처 유지, 내부 호출만 변경
│   ├── db.py                   # ✨ NEW — DB 연결 + 초기화 + async 쿼리 헬퍼
│   ├── loader.py               # ✨ REWRITE — 파일 순회 → SQL SELECT
│   ├── stats.py                # ✨ REWRITE — Python 집계 → SQL 집계
│   ├── schemas.py              # ✅ 변경 없음
│   └── requirements.txt        # ✨ UPDATE — aiosqlite 추가
│
├── scripts/
│   ├── ingest.py               # ✨ NEW — JSON → SQLite 적재 스크립트
│   ├── sync_results.py         # ✅ 변경 없음 (JSON 수집은 그대로 유지)
│   ├── runner.py               # ✅ 변경 없음
│   ├── shuttle.py              # ✅ 변경 없음
│   └── setup.py                # ✨ UPDATE — data/ 디렉토리 생성 추가
│
├── data/                       # ✨ NEW — DB 파일 저장 위치
│   └── llm_tester.db           # SQLite DB (WAL mode)
│
├── results/                    # ✅ 유지 — JSON 원본 보존 (ingest 소스)
├── dashboard/                  # ✅ 변경 없음
├── report.py                   # ✅ 변경 없음 (CLI용, 독립)
└── test_config.json            # ✅ 변경 없음
```

## 5. Module 설계

### 5.1 `api/db.py` — DB 연결 및 초기화

```python
# 핵심 역할:
# 1. FastAPI lifespan에서 DB 초기화 (CREATE TABLE IF NOT EXISTS)
# 2. WAL 모드 활성화
# 3. aiosqlite 커넥션 관리 (앱 수명주기와 동일)
# 4. 쿼리 헬퍼: fetchall, fetchone, execute

import aiosqlite
from contextlib import asynccontextmanager

DB_PATH = os.getenv("DB_PATH", "./data/llm_tester.db")

# FastAPI lifespan으로 앱 시작 시 init, 종료 시 close
@asynccontextmanager
async def lifespan(app):
    app.state.db = await aiosqlite.connect(DB_PATH)
    app.state.db.row_factory = aiosqlite.Row
    await app.state.db.execute("PRAGMA journal_mode=WAL")
    await app.state.db.execute("PRAGMA foreign_keys=ON")
    await _init_tables(app.state.db)
    yield
    await app.state.db.close()
```

### 5.2 `api/loader.py` — REWRITE (파일 → SQL)

```python
# Before (Phase 1):
#   - os.listdir() 3중 루프로 JSON 파일 순회
#   - 파일마다 json.load() → Pydantic 변환
#   - 전체 결과를 메모리에 올린 후 Python 필터링
#
# After (Phase 1.5):
#   - SQL SELECT + WHERE 절로 필터링
#   - DB에서 필요한 행만 가져옴
#   - JOIN으로 device/model/prompt 정보 결합

async def load_all(
    db: aiosqlite.Connection,
    device: str | None,
    model: str | None,
    category: str | None,
    backend: str | None,
    status: str | None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ResultItem], int]:
    """
    Returns (rows, total_count).
    페이지네이션도 DB 레벨에서 처리 (LIMIT/OFFSET).
    """
    # WHERE 절 동적 빌드 (파라미터 바인딩)
    # JOIN devices, models, prompts
    # ORDER BY r.timestamp DESC
    # LIMIT ? OFFSET ?
```

### 5.3 `api/stats.py` — REWRITE (Python 집계 → SQL 집계)

```python
# Before (Phase 1):
#   - 전체 rows를 Python list로 받음
#   - sorted() + index 계산으로 percentile
#   - for 루프로 group by model/category
#
# After (Phase 1.5):
#   - SQL 집계 함수로 대체
#   - GROUP BY + 서브쿼리로 모델별/카테고리별 통계
#   - percentile은 SQLite 윈도우 함수 또는 서브쿼리로 처리

# Percentile 계산 (SQLite용)
PERCENTILE_QUERY = """
    SELECT latency_ms
    FROM results
    WHERE status = 'success' AND latency_ms IS NOT NULL
        {filters}
    ORDER BY latency_ms
    LIMIT 1
    OFFSET (
        SELECT CAST(COUNT(*) * ? AS INTEGER)
        FROM results
        WHERE status = 'success' AND latency_ms IS NOT NULL
            {filters}
    )
"""

# Summary 집계 쿼리
SUMMARY_QUERY = """
    SELECT
        COUNT(*)                                    AS total,
        SUM(CASE WHEN status='success' THEN 1 END) AS success,
        SUM(CASE WHEN status='error' THEN 1 END)   AS errors,
        AVG(CASE WHEN status='success' THEN latency_ms END)   AS avg_latency,
        MIN(CASE WHEN status='success' THEN latency_ms END)   AS min_latency,
        MAX(CASE WHEN status='success' THEN latency_ms END)   AS max_latency,
        AVG(ttft_ms)            AS avg_ttft_ms,
        AVG(decode_tps)         AS avg_decode_tps,
        AVG(prefill_tps)        AS avg_prefill_tps,
        AVG(init_time_ms)       AS avg_init_time_ms,
        AVG(peak_native_memory_mb) AS avg_peak_native_mem_mb,
        AVG(peak_java_memory_mb)   AS avg_peak_java_mem_mb,
        AVG(output_token_count)    AS avg_output_tokens
    FROM results r
    JOIN devices d ON r.device_id = d.id
    JOIN models  m ON r.model_id  = m.id
    JOIN prompts p ON r.prompt_id = p.id
    WHERE 1=1 {filters}
"""
```

### 5.4 `scripts/ingest.py` — JSON → SQLite 적재

```python
# 실행: python scripts/ingest.py [--results-dir ./results] [--db-path ./data/llm_tester.db]
#
# 동작:
# 1. results/ 디렉토리 순회 (기존 sync_results.py 출력 구조)
# 2. JSON 파싱 → devices/models/prompts 테이블에 INSERT OR IGNORE
# 3. results 테이블에 INSERT OR IGNORE (UNIQUE 제약으로 중복 방지)
# 4. 적재 리포트 출력: 신규 N건, 스킵 N건, 에러 N건
#
# 특징:
# - 멱등성 보장: 여러 번 실행해도 동일 결과
# - 기존 JSON 파일 삭제 안 함 (원본 보존)
# - sync_results.py → ingest.py 순서로 실행하는 파이프라인
```

### 5.5 `api/main.py` — 변경 최소화

```python
# 변경 포인트:
# 1. FastAPI 생성 시 lifespan 연결
#    app = FastAPI(lifespan=lifespan, ...)
#
# 2. 엔드포인트 내부에서 request.app.state.db 사용
#    async def get_results(..., request: Request):
#        db = request.app.state.db
#        rows, total = await load_all(db, device, model, ...)
#
# 3. 엔드포인트 시그니처 (URL, query params, response schema) 변경 없음
#    → 프론트엔드 수정 제로
```

## 6. Data Flow (Before vs After)

### Phase 1 (현재)

```
sync_results.py → results/{device}/{model}/*.json
                          │
                          ▼
                  loader.py: os.listdir() 3중 루프
                  → 전체 JSON 메모리 로드
                  → Python 필터링 (if 문)
                          │
                          ▼
                  stats.py: Python sorted() + 루프
                  → percentile, group by 수동 계산
                          │
                          ▼
                  main.py: API 응답 반환
```

### Phase 1.5 (목표)

```
sync_results.py → results/{device}/{model}/*.json  (변경 없음)
                          │
                          ▼
                  ingest.py: JSON → SQLite (✨ NEW)
                  → devices/models/prompts 정규화 적재
                  → results 테이블 bulk INSERT
                  → 중복 자동 스킵
                          │
                          ▼
                  data/llm_tester.db  (✨ NEW)
                          │
                          ▼
                  loader.py: SQL SELECT + JOIN + WHERE
                  → DB 레벨 필터링 + 페이지네이션
                          │
                          ▼
                  stats.py: SQL AVG/COUNT/GROUP BY
                  → DB 레벨 집계 (percentile 포함)
                          │
                          ▼
                  main.py: API 응답 반환 (스키마 동일)
```

## 7. Migration Strategy

### 7.1 원칙

- **API 계약 불변**: 프론트엔드가 바라보는 `ApiSuccess<T>`, `ApiError`, `PaginationMeta` 스키마 변경 없음
- **JSON 원본 보존**: `results/` 디렉토리의 JSON 파일은 삭제하지 않음. DB는 "뷰"이고 JSON이 "소스"
- **멱등 적재**: `ingest.py`를 여러 번 실행해도 안전 (UNIQUE 제약 + INSERT OR IGNORE)
- **점진 전환**: loader.py/stats.py를 하나씩 교체하며 API 응답 일치 검증

### 7.2 Rollback 계획

DB 마이그레이션 실패 시:
1. `api/loader.py`와 `api/stats.py`를 Phase 1 버전으로 revert
2. `main.py`에서 lifespan 제거
3. JSON 파일이 그대로 있으므로 즉시 원복 가능

## 8. Error Handling

### 8.1 Ingest (scripts/ingest.py)

| 상황 | 처리 |
|------|------|
| JSON 파싱 실패 | 해당 파일 스킵 + 경고 로그, 나머지 계속 |
| UNIQUE 제약 위반 | `INSERT OR IGNORE` → 자동 스킵 (정상) |
| DB 파일 잠금 | 재시도 3회 후 실패 리포트 |
| 필수 필드 누락 | 기본값 적용 (기존 loader.py 로직 유지) |

### 8.2 API (api/)

| 상황 | 처리 |
|------|------|
| DB 연결 실패 | 글로벌 exception handler → 500 + `ApiError` |
| 쿼리 타임아웃 | SQLite 기본 5초, `PRAGMA busy_timeout=5000` |
| 빈 결과 | 200 + `data: []` (기존과 동일, 404 아님) |
| 잘못된 필터 값 | 400 + `ApiError` (기존과 동일) |

## 9. Performance 비교

### 9.1 예상 개선

| 작업 | Phase 1 (JSON) | Phase 1.5 (SQLite) | 개선 |
|------|---------------|-------------------|------|
| 전체 결과 로드 (108건) | ~50ms (파일 I/O 108회) | ~2ms (단일 쿼리) | **25x** |
| 필터링 (device + model) | 전체 로드 후 Python 필터 | WHERE 절 (인덱스) | **10x+** |
| 페이지네이션 | 전체 로드 → 슬라이싱 | LIMIT/OFFSET | 메모리 절약 |
| Summary 집계 | Python sorted + 루프 | SQL AVG/COUNT | 코드량 50% ↓ |
| 1만건 이상 | O(n) 파일 오픈 | O(log n) 인덱스 | 스케일 가능 |

### 9.2 SQLite WAL 모드 동시성

```
Writer (ingest.py)     Reader (FastAPI)
      │                      │
      ├─ BEGIN               │
      ├─ INSERT ...          ├─ SELECT ... (WAL 스냅샷 읽기, 블로킹 없음)
      ├─ INSERT ...          ├─ SELECT ... (동시 가능)
      ├─ COMMIT              │
      │                      ├─ SELECT ... (새 데이터 반영)
```

- **읽기-쓰기 동시 가능** (WAL 모드)
- **쓰기-쓰기는 직렬** (배치 적재 패턴이므로 문제 없음)
- `PRAGMA busy_timeout=5000` 으로 잠금 대기

## 10. API 영향도 분석

### 10.1 엔드포인트별 변경

| Endpoint | URL 변경 | 파라미터 변경 | 응답 스키마 변경 | 내부 변경 |
|----------|---------|-------------|----------------|----------|
| `GET /api/results` | 없음 | 없음 | 없음 | loader.py → SQL |
| `GET /api/results/summary` | 없음 | 없음 | 없음 | stats.py → SQL |
| `GET /api/results/by-model` | 없음 | 없음 | 없음 | stats.py → SQL GROUP BY |
| `GET /api/results/by-category` | 없음 | 없음 | 없음 | stats.py → SQL GROUP BY |
| `GET /api/results/compare` | 없음 | 없음 | 없음 | stats.py → SQL |
| `GET /api/models` | 없음 | 없음 | 없음 | SELECT DISTINCT → models 테이블 |
| `GET /api/devices` | 없음 | 없음 | 없음 | SELECT DISTINCT → devices 테이블 |
| `GET /api/categories` | 없음 | 없음 | 없음 | SELECT DISTINCT → prompts 테이블 |
| `GET /api/export/csv` | 없음 | 없음 | 없음 | loader.py → SQL |

### 10.2 프론트엔드 영향

**변경 없음.** API 응답 스키마(`ApiSuccess<T>`, `ResultItem`, `SummaryStats` 등)가 동일하므로 `dashboard/src/` 코드 수정 불필요.

## 11. Tech Stack (Phase 1.5 추가분)

| Layer | Tech | Why |
|-------|------|-----|
| **DB** | SQLite 3.35+ | 서버리스, WAL 동시성, 윈도우함수 지원 |
| **Async Driver** | aiosqlite | FastAPI async 호환, sqlite3 래핑 |
| **Ingest** | sqlite3 (sync) | 스크립트는 동기 실행, async 불필요 |
| **Migration** | 수동 DDL | 현재 규모에서 Alembic은 오버스펙 |

## 12. Implementation Order

```
Step 1: DB 스키마 + 연결 모듈 (api/db.py)
        → CREATE TABLE DDL 작성
        → aiosqlite 커넥션 관리 (FastAPI lifespan)
        → WAL 모드 + foreign_keys 활성화
        → 단독 테스트: DB 파일 생성 확인

Step 2: Ingest 스크립트 (scripts/ingest.py)
        → results/ JSON → SQLite 적재
        → devices/models/prompts 정규화 INSERT
        → UNIQUE 제약 + INSERT OR IGNORE
        → 적재 리포트 출력
        → 검증: DB에 108건 정상 적재 확인

Step 3: loader.py 리라이트
        → 파일 순회 → SQL SELECT + JOIN
        → 필터 파라미터 → WHERE 절 동적 빌드
        → 페이지네이션 → LIMIT/OFFSET
        → 검증: API 응답이 Phase 1과 동일한지 diff

Step 4: stats.py 리라이트
        → compute_summary → SQL 집계 쿼리
        → compute_by_model → SQL GROUP BY model
        → compute_by_category → SQL GROUP BY category
        → compute_compare → SQL 서브쿼리
        → 검증: /api/results/summary 응답 비교

Step 5: main.py 통합
        → lifespan 연결
        → 엔드포인트에서 db 주입
        → 전체 엔드포인트 E2E 테스트
        → Swagger에서 기존과 동일 응답 확인

Step 6: 파이프라인 통합 + 문서
        → sync_results.py → ingest.py 순차 실행 검증
        → setup.py에 data/ 디렉토리 생성 추가
        → README.md 업데이트 (DB 관련 섹션)
        → .gitignore에 data/*.db 추가
```

## 13. Future: PostgreSQL 마이그레이션 경로

SQLite에서 병목이 발생하는 시점 (예상: Phase 3 멀티디바이스 동시 쓰기 10+ 또는 데이터 100만건 이상):

```
Phase 1.5 (현재)          Phase 3+ (필요 시)
SQLite + aiosqlite    →   PostgreSQL + asyncpg
                          │
                          ├─ DDL: SQLite → PG 문법 변환 (AUTOINCREMENT → SERIAL 등)
                          ├─ 쿼리: 90%+ 그대로 동작 (표준 SQL)
                          ├─ 드라이버: aiosqlite → asyncpg (인터페이스 유사)
                          ├─ 배포: Docker compose 추가
                          └─ 대안: Supabase (호스팅 PG) 사용 가능
```

변경 포인트가 `db.py` 한 파일에 집중되도록 설계. loader.py/stats.py의 SQL 쿼리는 표준 SQL이므로 대부분 재사용 가능.

# On-Device LLM Tester — Phase 2: CI/CD Architecture

## 1. High-Level Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                      CI/CD PIPELINE (Phase 2)                            │
│                                                                          │
│  ┌─────────────────────────────┐                                         │
│  │  GitHub Actions              │                                         │
│  │  Trigger: workflow_dispatch  │  ← GitHub UI에서 "Run workflow" 클릭    │
│  │  (수동 실행만 지원)           │                                         │
│  └──────────────┬──────────────┘                                         │
│                 │ dispatches job                                          │
│                 ▼                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  Self-hosted Runner (개발 PC — 폰이 USB로 연결된 물리 머신)       │    │
│  │                                                                   │    │
│  │  Step 1: runner.py                                                │    │
│  │    ├─ ADB로 연결된 디바이스에 테스트 명령 전송                     │    │
│  │    ├─ test_config.json 기반 설정 (모델, 프롬프트, backend 등)     │    │
│  │    └─ 추론 완료 대기 (Smart Polling)                              │    │
│  │                                                                   │    │
│  │  Step 2: sync_results.py                                          │    │
│  │    ├─ ADB run-as로 앱 샌드박스에서 JSON 읽기                      │    │
│  │    └─ results/{device}/{model}/*.json 저장                        │    │
│  │                                                                   │    │
│  │  Step 3: ingest.py                                                │    │
│  │    ├─ JSON → SQLite 적재 (INSERT OR IGNORE)                       │    │
│  │    ├─ runs 테이블에 CI 실행 메타데이터 기록                        │    │
│  │    └─ 적재 리포트 출력                                             │    │
│  │                                                                   │    │
│  │  Step 4: Upload .db as GitHub Artifact                            │    │
│  │    └─ actions/upload-artifact                                     │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌──────────────────────────────┐    ┌──────────────────────────────┐    │
│  │  GitHub Artifact              │    │  Dashboard (기존 유지)        │    │
│  │  llm_tester.db               │    │  :5173 + :8000               │    │
│  │  보존: 90일                   │    │                               │    │
│  │  ※ 전달 수단, 유일 저장소 X  │    │  /api/runs (✨ NEW)          │    │
│  │                              │    │  Run History 페이지 (✨ NEW)  │    │
│  └──────────────────────────────┘    └──────────────────────────────┘    │
│                                                                          │
│  ※ .db 원본은 Runner 로컬에 보존 — Artifact 만료와 무관하게 데이터 유지  │
└──────────────────────────────────────────────────────────────────────────┘
```

## 2. Why This Architecture

### Self-hosted Runner — 왜 클라우드 Runner가 아닌가?
- `runner.py`는 ADB로 물리적 폰(S25, S26 등)과 통신. USB 연결 필수
- GitHub-hosted Runner는 클라우드 VM이므로 물리 디바이스 접근 불가
- Self-hosted Runner는 개발 PC에서 직접 실행 → ADB 경로 그대로 사용
- 기존 `runner.py`, `sync_results.py`, `ingest.py`를 **수정 없이** 워크플로우에서 호출

### workflow_dispatch 전용 — 왜 push/schedule 트리거가 없는가?
- **push 제외**: LLM 벤치마크는 비용이 높음 (폰 점유 + 시간). 대시보드 CSS 수정이나 API 리팩토링 같은 벤치마크 무관 커밋에 트리거되면 자원 낭비
- **schedule 제외**: 새 모델/디바이스 출시가 불규칙. 매주/매월 cron으로 돌릴 실질적 이유 없음. 필요할 때 수동 실행이 현재 단계에 적합
- **나중에 추가 가능**: 프로젝트 성숙 후 schedule 트리거(`cron: '0 3 * * 1'` 등)나 path-filtered push 트리거 추가는 YAML 수정 한 줄

### test_config.json 기반 파라미터 — 왜 workflow_dispatch input을 안 쓰는가?
- `runner.py`가 이미 `test_config.json`에서 모든 설정(모델, 프롬프트, backend, max_tokens 등)을 읽음
- 워크플로우에서 별도 파라미터 파싱 로직을 만들면 `runner.py`와 config 이중 관리
- 설정 변경 시: `test_config.json` 수정 → commit → 워크플로우 수동 실행. 설정이 git history에 추적됨
- Phase 3 멀티디바이스 확장 시에도 config 파일에 device 목록만 추가하면 됨

### GitHub Artifact — 왜 이 전달 방식인가?
- DB 마이그레이션 아키텍처에서 이미 설계: "Phase 2 CI에서 `.db` 파일을 artifact로 넘기면 됨"
- `.db`는 바이너리 파일 → git commit으로 넣으면 히스토리 비대화 (안티패턴)
- 별도 서버/스토리지(S3 등)는 현재 PoC 단계에서 오버엔지니어링
- Artifact 90일 만료는 문제 아님: `.db`는 **누적형**이므로 최신 artifact에 과거 데이터 전부 포함. 원본은 Runner 로컬에 항상 보존

## 3. Trigger & Parameter Design

### 3.1 Trigger

```yaml
on:
  workflow_dispatch:  # GitHub UI에서 수동 실행만 지원
```

- GitHub 리포 → Actions 탭 → "Run workflow" 버튼으로 실행
- GitHub API / `gh` CLI로도 트리거 가능: `gh workflow run benchmark.yml`

### 3.2 파라미터 전략

| 항목 | 소스 | 설명 |
|------|------|------|
| 모델 목록 | `test_config.json` → `models` | 테스트할 SLM 모델명 + 경로 |
| 프롬프트 셋 | `test_config.json` → `prompts` | 카테고리별 프롬프트 |
| backend | `test_config.json` → `backend` | `CPU` / `GPU` |
| max_tokens | `test_config.json` → `max_tokens` | 최대 출력 토큰 수 |
| 디바이스 | ADB 자동 감지 | `runner.py`가 연결된 디바이스 감지 |

**설정 변경 워크플로우**:
```
test_config.json 수정 → git commit & push → GitHub UI에서 "Run workflow" 클릭
```

## 4. Self-hosted Runner 설정

### 4.1 전제 조건

| 항목 | 요구 |
|------|------|
| OS | Windows 10+ / macOS / Linux |
| Python | 3.10+ (runner.py, sync_results.py, ingest.py 실행) |
| ADB | Android SDK Platform-Tools (PATH에 등록) |
| 디바이스 | USB 디버깅 활성화된 Android 폰 연결 |
| 네트워크 | GitHub Actions 서비스와 통신 가능 (HTTPS outbound) |

### 4.2 Runner 등록 절차

```bash
# 1. GitHub 리포 → Settings → Actions → Runners → New self-hosted runner
# 2. OS 선택 후 안내에 따라 설치:

# 다운로드 (예: Linux x64)
mkdir actions-runner && cd actions-runner
curl -o actions-runner-linux-x64-2.XXX.X.tar.gz -L \
  https://github.com/actions/runner/releases/download/vX.X.X/actions-runner-linux-x64-X.X.X.tar.gz
tar xzf ./actions-runner-linux-x64-X.X.X.tar.gz

# 3. 등록
./config.sh --url https://github.com/tecace-soft/on-device-llm-tester \
            --token <REGISTRATION_TOKEN>

# 4. 라벨 설정: self-hosted, llm-bench
#    → workflow YAML에서 runs-on: [self-hosted, llm-bench]으로 매칭

# 5. 서비스로 실행 (백그라운드 상시 대기)
sudo ./svc.sh install
sudo ./svc.sh start
```

### 4.3 Runner 라벨

| 라벨 | 목적 |
|------|------|
| `self-hosted` | 기본 라벨 (GitHub-hosted와 구분) |
| `llm-bench` | 커스텀 라벨. 벤치마크 전용 Runner 식별. Phase 3 멀티디바이스 시 Runner별 라벨로 확장 가능 (`llm-bench-s25`, `llm-bench-s26`) |

## 5. Workflow 설계

### 5.1 YAML 구조

```yaml
# .github/workflows/benchmark.yml

name: LLM Benchmark

on:
  workflow_dispatch:

concurrency:
  group: llm-bench                    # 동일 디바이스에 ADB 명령 중복 방지
  cancel-in-progress: false           # 진행 중인 run은 취소하지 않고 대기

jobs:
  benchmark:
    runs-on: [self-hosted, llm-bench]
    timeout-minutes: 120              # 벤치마크 최대 2시간 제한

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Verify ADB connection
        run: |
          adb devices
          adb devices | grep -w "device" || (echo "No device connected" && exit 1)

      - name: Run benchmark
        run: python scripts/runner.py

      - name: Sync results from device
        run: python scripts/sync_results.py

      - name: Ingest results to DB
        run: |
          python scripts/ingest.py \
            --run-id ${{ github.run_id }} \
            --trigger manual \
            --commit-sha ${{ github.sha }} \
            --branch ${{ github.ref_name }}

      - name: Upload DB artifact
        uses: actions/upload-artifact@v4
        continue-on-error: true          # 업로드 실패해도 워크플로우는 성공 처리
        with:
          name: llm-tester-db-${{ github.run_id }}
          path: data/llm_tester.db
          retention-days: 90

      - name: Summary
        run: |
          echo "## Benchmark Complete" >> $GITHUB_STEP_SUMMARY
          echo "- Run ID: ${{ github.run_id }}" >> $GITHUB_STEP_SUMMARY
          echo "- Trigger: manual (workflow_dispatch)" >> $GITHUB_STEP_SUMMARY
          python scripts/ingest.py --summary-only >> $GITHUB_STEP_SUMMARY
```

### 5.2 Step 상세

| Step | 스크립트 | 역할 | 실패 시 |
|------|---------|------|---------|
| Verify ADB | `adb devices` | 폰 연결 확인 | 즉시 실패 (디바이스 없음 = 테스트 불가) |
| Run benchmark | `runner.py` | ADB로 테스트 실행 + 결과 대기 | step 실패 → 워크플로우 중단 |
| Sync results | `sync_results.py` | 폰 → PC로 JSON pull | step 실패 → 워크플로우 중단 |
| Ingest | `ingest.py` | JSON → SQLite + runs 기록 | step 실패 → DB 업로드 스킵 |
| Upload artifact | `upload-artifact` | `.db` 파일 업로드 | step 실패 → 경고만 (로컬 DB 보존) |
| Summary | `ingest.py --summary-only` | GitHub Actions Summary에 결과 요약 출력 | step 실패 → 무시 (리포트용) |

### 5.3 timeout 설계

| 구간 | 예상 소요 | 근거 |
|------|----------|------|
| Setup (checkout + pip) | ~1분 | self-hosted는 캐시 가능 |
| ADB verify | ~5초 | 디바이스 연결 확인만 |
| runner.py (벤치마크) | 10분~90분 | 모델 수 × 프롬프트 수 × 디바이스 수에 비례 |
| sync_results.py | ~30초 | JSON 파일 수 의존 |
| ingest.py | ~10초 | SQLite INSERT, 건수 비례 |
| Upload artifact | ~10초 | .db 파일 크기 수 MB |
| **전체 timeout** | **120분** | 여유 포함 |

`test_config.json`의 모델·프롬프트 조합이 많으면 120분을 초과할 수 있음. **timeout 초과 시 워크플로우가 강제 중단되며, 부분 결과는 Runner 로컬(`results/`)에만 남고 DB에는 적재되지 않음.** config 규모를 조절하거나, 필요 시 `timeout-minutes` 값을 상향.

### 5.4 동시 실행 방지 (concurrency)

실수로 "Run workflow"를 연속 클릭하거나, 이전 run이 끝나기 전에 새 run을 트리거하면 하나의 폰에 ADB 명령이 겹쳐 테스트가 깨짐.

```yaml
concurrency:
  group: llm-bench                    # 그룹명 동일 → 동시 실행 1개로 제한
  cancel-in-progress: false           # 진행 중인 run은 취소하지 않고, 새 run이 대기
```

- `cancel-in-progress: false`: 실행 중인 벤치마크를 중단하지 않음. 새로 트리거된 run은 큐에서 대기 후 순차 실행
- Phase 3 멀티디바이스 시: 그룹명을 디바이스별로 분리 (`llm-bench-s25`, `llm-bench-s26`) → 디바이스별 병렬, 같은 디바이스는 직렬

## 6. Data Flow

### Phase 1.5 (현재)

```
개발자가 수동 실행:
  runner.py → sync_results.py → ingest.py → data/llm_tester.db
                                                    │
                                                    ▼
                                             FastAPI → Dashboard
```

### Phase 2 (목표)

```
GitHub UI "Run workflow" 클릭
    │
    ▼
GitHub Actions → Self-hosted Runner (개발 PC)
    │
    ├─ runner.py        (ADB → 폰)
    ├─ sync_results.py  (폰 → PC JSON)
    ├─ ingest.py        (JSON → SQLite + runs 테이블 기록)
    │       │
    │       ▼
    │   data/llm_tester.db  ← 원본 (Runner 로컬 보존)
    │       │
    ├─ upload-artifact   (.db → GitHub Artifact, 90일 보존)
    └─ GITHUB_STEP_SUMMARY (결과 요약)
                │
                ▼
        FastAPI → Dashboard
        └─ /api/runs 엔드포인트로 CI 실행 이력 조회
        └─ Run History 페이지에서 시각화
```

## 7. DB 변경사항

### 7.1 runs 테이블 (DB_MIGRATION_ARCHITECTURE.md §3.4에서 설계 완료)

```sql
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL UNIQUE,     -- GitHub Actions run ID
    trigger     TEXT NOT NULL DEFAULT '', -- 'manual'
    commit_sha  TEXT,
    branch      TEXT,
    started_at  TEXT,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running'  -- 'running' | 'success' | 'error'
);

ALTER TABLE results ADD COLUMN run_id INTEGER REFERENCES runs(id);
```

### 7.2 ingest.py 변경

| 변경 | 내용 |
|------|------|
| `--run-id` 플래그 추가 | GitHub Actions `${{ github.run_id }}`를 받아 runs 테이블에 INSERT |
| `--trigger` 플래그 추가 | `manual` (현재). 향후 `schedule` 추가 가능 |
| `--commit-sha` 플래그 추가 | `${{ github.sha }}` → runs.commit_sha에 기록 |
| `--branch` 플래그 추가 | `${{ github.ref_name }}` → runs.branch에 기록 |
| `--summary-only` 플래그 추가 | DB 변경 없이 최근 run의 적재 통계만 stdout 출력 |
| run-result 연결 | 적재되는 results 행에 `run_id` FK 설정 |

```python
# scripts/ingest.py 변경 요약

# 기존: python scripts/ingest.py
# Phase 2: python scripts/ingest.py --run-id 12345678 --trigger manual --commit-sha abc123 --branch main

def create_run(db, run_id: str, trigger: str, commit_sha: str, branch: str):
    """runs 테이블에 CI 실행 메타데이터 기록"""
    db.execute("""
        INSERT OR IGNORE INTO runs (run_id, trigger, commit_sha, branch, started_at, status)
        VALUES (?, ?, ?, ?, datetime('now'), 'running')
    """, (run_id, trigger, commit_sha, branch))

def finalize_run(db, run_id: str, status: str):
    """run 완료 후 상태 업데이트"""
    db.execute("""
        UPDATE runs SET finished_at = datetime('now'), status = ?
        WHERE run_id = ?
    """, (status, run_id))
```

### 7.3 하위 호환

- `--run-id` 미지정 시: runs 테이블 미사용, results.run_id = NULL → 기존 수동 실행과 동일하게 동작
- 기존 데이터에 영향 없음: `ALTER TABLE ... ADD COLUMN`은 기존 행에 NULL 적용

## 8. API 확장

### 8.1 신규 엔드포인트

```
GET  /api/runs                       → CI 실행 이력 목록
     ?status=success                 # success | error | running | all
     &limit=20
     &offset=0

GET  /api/runs/{run_id}              → 특정 run 상세 (연결된 results 포함)

GET  /api/runs/{run_id}/summary      → 특정 run의 집계 통계
```

### 8.2 기존 엔드포인트 확장

```
GET  /api/results                    → 기존 필터에 run_id 추가
     ?run_id=12345678                # 특정 CI run의 결과만 필터링
     &device=...&model=...           # 기존 필터와 조합 가능
```

### 8.3 응답 스키마

```python
# api/schemas.py 추가

class RunItem(BaseModel):
    id: int
    run_id: str
    trigger: str                      # 'manual'
    commit_sha: Optional[str]
    branch: Optional[str]
    started_at: Optional[str]
    finished_at: Optional[str]
    status: str                       # 'running' | 'success' | 'error'
    result_count: Optional[int]       # 해당 run에 연결된 results 수

# 응답: ApiSuccess[list[RunItem]]
```

## 9. Dashboard 확장

### 9.1 Run History 페이지

| 요소 | 내용 |
|------|------|
| 테이블 | run_id, trigger, branch, commit_sha, started_at, finished_at, status, result_count |
| 상태 배지 | `running` (노란), `success` (초록), `error` (빨강) |
| 클릭 | run_id 클릭 → 해당 run의 results만 필터링된 Raw Data 페이지로 이동 |
| 링크 | commit_sha → GitHub commit 페이지 링크 |

### 9.2 기존 페이지 변경

| 페이지 | 변경 |
|--------|------|
| Overview | FilterBar에 "Run" 드롭다운 추가 (선택 시 해당 run 결과만 표시) |
| Raw Data | `run_id` 컬럼 추가 |
| Sidebar | "Run History" 메뉴 항목 추가 |

## 10. Error Handling

### 10.1 Workflow 레벨

| 상황 | 처리 |
|------|------|
| ADB 디바이스 미연결 | `Verify ADB` step에서 즉시 실패 → 워크플로우 중단 |
| runner.py 실행 에러 | step 실패 → 후속 step 스킵, 워크플로우 실패 표시 |
| runner.py 일부 테스트 실패 | 개별 테스트 에러는 JSON에 `status: "error"`로 기록 → 정상 진행 |
| sync_results.py 실패 | step 실패 → DB 미업데이트, 워크플로우 실패 |
| ingest.py 실패 | step 실패 → artifact 업로드 스킵 |
| upload-artifact 실패 | 경고만 → 로컬 DB는 보존 |
| timeout (120분 초과) | 워크플로우 강제 중단, 부분 결과는 로컬에 남음 |

### 10.2 runs 테이블 상태 관리

```
ingest.py 시작 → runs.status = 'running'
ingest.py 정상 완료 → runs.status = 'success'
ingest.py 에러 → runs.status = 'error'
워크플로우 timeout/중단 → runs.status = 'running' (그대로 남음)
```

### 10.3 좀비 run 처리

워크플로우가 비정상 종료(timeout, Runner 강제 종료 등)되면 `runs.status`가 `running`에 머무를 수 있음. 대시보드에 영구적으로 "실행 중" 표시가 남아 데이터를 오염시키므로, **FastAPI 앱 시작 시 자동 정리**한다.

```python
# api/db.py — lifespan 내에서 앱 시작 시 자동 실행
async def cleanup_zombie_runs(db: aiosqlite.Connection):
    """24시간 이상 'running' 상태인 run을 'error'로 전환"""
    await db.execute("""
        UPDATE runs SET status = 'error', finished_at = datetime('now')
        WHERE status = 'running' AND started_at < datetime('now', '-24 hours')
    """)
    await db.commit()

# lifespan에서 호출
@asynccontextmanager
async def lifespan(app):
    db = await aiosqlite.connect(DB_PATH)
    # ... WAL, foreign_keys, init_tables ...
    await cleanup_zombie_runs(db)      # ← 앱 시작마다 자동 정리
    app.state.db = db
    yield
    await db.close()
```

## 11. Security

### 11.1 Runner 보안

| 항목 | 조치 |
|------|------|
| Runner 토큰 | GitHub 등록 시 일회성 토큰 사용, 이후 자동 갱신 |
| 리포 접근 | Runner는 등록된 리포의 워크플로우만 실행 |
| 환경 변수 | 민감 값은 GitHub Secrets에 저장 (`Settings → Secrets → Actions`) |
| 네트워크 | Runner → GitHub HTTPS outbound만 필요. 인바운드 불필요 |

### 11.2 Artifact 접근

- GitHub Artifact는 리포 접근 권한이 있는 사용자만 다운로드 가능
- Public 리포라도 Actions Artifact는 인증된 사용자만 접근

## 12. Directory Structure (변경사항)

```
on-device-llm-tester/
├── .github/
│   └── workflows/
│       └── benchmark.yml           # ✨ NEW — 벤치마크 워크플로우
│
├── api/
│   ├── main.py                     # ✨ UPDATE — /api/runs 엔드포인트 추가
│   ├── db.py                       # ✨ UPDATE — runs 테이블 DDL 추가
│   ├── loader.py                   # ✨ UPDATE — run_id 필터 추가
│   ├── stats.py                    # ✅ 변경 없음
│   └── schemas.py                  # ✨ UPDATE — RunItem 스키마 추가
│
├── scripts/
│   ├── runner.py                   # ✅ 변경 없음
│   ├── sync_results.py             # ✅ 변경 없음
│   ├── ingest.py                   # ✨ UPDATE — --run-id, --trigger, --summary-only
│   ├── shuttle.py                  # ✅ 변경 없음
│   └── setup.py                    # ✅ 변경 없음
│
├── dashboard/src/
│   ├── pages/
│   │   └── RunHistory.tsx          # ✨ NEW — CI 실행 이력 페이지
│   ├── hooks/
│   │   └── useRuns.ts              # ✨ NEW — runs 데이터 훅
│   ├── types/
│   │   └── index.ts                # ✨ UPDATE — RunItem 타입 추가
│   └── components/
│       ├── layout/
│       │   └── Sidebar.tsx         # ✨ UPDATE — Run History 메뉴 추가
│       └── filters/
│           └── FilterBar.tsx       # ✨ UPDATE — Run 드롭다운 추가
│
├── data/
│   └── llm_tester.db              # ✅ 유지 — runs 테이블 추가됨
│
├── results/                        # ✅ 유지
├── test_config.json                # ✅ 유지 — 벤치마크 설정 소스
└── README.md                       # ✨ UPDATE — CI/CD 섹션 추가
```

## 13. Implementation Order

```
Step 1: DB 확장 + ingest.py 업데이트
        → runs 테이블 DDL 추가 (api/db.py)
        → results 테이블에 run_id 컬럼 추가
        → ingest.py에 --run-id, --trigger, --summary-only 플래그
        → 수동 실행으로 runs 기록 검증: python scripts/ingest.py --run-id test-001 --trigger manual
        → 기존 ingest 동작 (--run-id 없이)이 깨지지 않는지 확인

Step 2: GitHub Actions 워크플로우 작성
        → .github/workflows/benchmark.yml 작성
        → Self-hosted Runner 등록 + 라벨 설정
        → ADB 연결 검증 step 포함
        → GitHub UI에서 "Run workflow" → 전체 파이프라인 E2E 테스트
        → GITHUB_STEP_SUMMARY에 결과 요약 출력 확인

Step 3: API 확장
        → /api/runs, /api/runs/{run_id}, /api/runs/{run_id}/summary 엔드포인트
        → /api/results에 run_id 필터 파라미터 추가
        → RunItem Pydantic 스키마
        → Swagger에서 테스트

Step 4: Dashboard 확장
        → RunHistory.tsx 페이지 (테이블 + 상태 배지)
        → useRuns.ts 훅
        → Sidebar에 메뉴 추가
        → FilterBar에 Run 드롭다운
        → Raw Data에 run_id 컬럼

Step 5: 문서 + 정리
        → README.md에 CI/CD 사용법 섹션
        → Runner 설정 가이드
        → 좀비 run 정리 방법 문서화
```

## 14. Extension Points (Phase 연동)

```
Phase 3 (Multi-device)
  └─→ Runner 라벨 확장: llm-bench-s25, llm-bench-s26
  └─→ 디바이스별 Runner에서 병렬 실행 (matrix strategy)
  └─→ 또는 단일 Runner에서 ADB가 감지하는 모든 디바이스 순회

Phase 4 (AI Quality Eval)
  └─→ ingest.py 후 quality_eval.py step 추가
  └─→ GPT API 호출 → results 테이블에 quality_score 업데이트
  └─→ 워크플로우에 step 하나 추가로 구현

향후 확장 (필요 시):
  └─→ schedule 트리거 추가: cron: '0 3 * * 1' (매주 월요일 새벽)
  └─→ push 트리거 + path filter: android/**, scripts/**, test_config.json
  └─→ Slack/Discord 알림: workflow 완료 시 결과 요약 전송
  └─→ GitHub Pages로 Dashboard 배포 (정적 빌드 + Artifact DB)
```

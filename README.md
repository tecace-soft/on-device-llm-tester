# On-device LLM Inference Test Automation

> **Project Status:** Phase 4a — Response Validation ✅

Android 기기에서 구동되는 LLM(MediaPipe 기반)의 추론 성능 및 결과 품질을 자동으로 벤치마킹하는 파이프라인입니다. GitHub Actions self-hosted runner를 통해 ADB 연결된 복수의 실물 기기에서 CI 실행이 가능합니다.

---

## 1. Prerequisites

| 항목 | 요구사항 |
|------|---------|
| Python | 3.10+ |
| Node.js | 18+ (Dashboard) |
| ADB | Android SDK Platform-Tools (PATH 등록 필수) |
| Android 기기 | 개발자 옵션 활성화 + USB 디버깅 허용 (1대 이상) |

- [ADB Platform-Tools 다운로드](https://developer.android.com/studio/releases/platform-tools)

---

## 2. Installation & Setup

### 2.1 가상환경 생성 및 활성화

```bash
python -m venv .venv
.\.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Mac/Linux
```

### 2.2 Python 의존성 설치

```bash
pip install -r requirements.txt
pip install -r api/requirements.txt
```

### 2.3 환경변수 설정

프로젝트 루트에 `.env` 파일 생성:

```env
LOCAL_MODEL_DIR=./models
HF_TOKEN=your_token_here

# API 인증 (선택)
API_KEY=your_api_key_here
ALLOWED_ORIGINS=http://localhost:5173
```

> `DB_PATH`, `RESULTS_DIR`은 설정하지 마세요. 스크립트가 `__file__` 기준 절대경로를 자동 사용합니다.

### 2.4 초기 폴더 구조 생성

```bash
python scripts/setup.py
```

`models/`, `results/`, `logs/`, `api/data/` 디렉토리가 생성됩니다.

---

## 3. Project Structure

```
on-device-llm-tester/
├── .github/
│   └── workflows/
│       └── benchmark.yml          # CI/CD 워크플로우 (멀티디바이스 + validation)
│
├── android/                       # Android app (com.tecace.llmtester)
│
├── api/                           # FastAPI backend (:8000)
│   ├── main.py                    # 엔드포인트 + CORS + auth
│   ├── db.py                      # SQLite 연결 + 스키마 초기화 + Phase 4a 마이그레이션
│   ├── loader.py                  # SQL SELECT 기반 데이터 로드
│   ├── stats.py                   # SQL 집계 (summary, compare, device-compare, validation)
│   ├── schemas.py                 # Pydantic 스키마 (Validation* 포함)
│   ├── requirements.txt
│   └── data/
│       └── llm_tester.db          # SQLite DB (gitignore됨)
│
├── dashboard/                     # React + Vite + TypeScript (:5173)
│   └── src/
│       ├── pages/
│       │   ├── Overview.tsx
│       │   ├── Performance.tsx
│       │   ├── Compare.tsx
│       │   ├── DeviceCompare.tsx   # 디바이스 간 비교 (Phase 3)
│       │   ├── Responses.tsx
│       │   ├── RawData.tsx
│       │   └── RunHistory.tsx
│       ├── hooks/
│       │   ├── useResults.ts
│       │   └── useDeviceCompare.ts # Phase 3
│       └── ...
│
├── scripts/
│   ├── setup.py                   # 초기 폴더 구조 생성
│   ├── device_discovery.py        # ADB 디바이스 검색 + thermal guard (Phase 3)
│   ├── shuttle.py                 # 모델 파일 → 기기 전송 (멀티디바이스 지원)
│   ├── runner.py                  # ADB 추론 실행 (멀티디바이스 + 병렬 지원)
│   ├── sync_results.py            # 기기 → PC 결과 수집 (멀티디바이스 지원)
│   ├── ingest.py                  # JSON → SQLite 적재 + ground_truth 동기화
│   ├── response_validator.py      # 응답 검증 파이프라인 (Phase 4a)
│   └── validators/                # 검증 모듈 (Phase 4a)
│       ├── __init__.py
│       ├── sanity.py              # empty, truncation, gibberish 체크
│       ├── deterministic.py       # math exact match, keyword containment
│       └── structural.py          # JSON/Python/markdown 구조 검증
│
├── tests/
│   └── test_validators.py         # 검증 모듈 단위 테스트 (59 tests)
│
├── results/                       # Raw JSON 원본 (gitignore됨)
│   ├── SM-S931U/                  # 디바이스별 디렉토리
│   └── SM-S926U/
├── logs/                          # 병렬 모드 디바이스별 로그 (gitignore됨)
├── models/                        # 모델 파일 (gitignore됨)
├── test_config.json               # 테스트 설정 (모델, 프롬프트, ground_truth)
└── .env                           # 환경변수 (gitignore됨)
```

---

## 4. Data Pipeline

```
Android App → JSON (앱 샌드박스)
      │
      ▼
scripts/sync_results.py
(ADB → results/{device}/{model}/*.json)
      │
      ▼
scripts/ingest.py
(JSON → api/data/llm_tester.db + ground_truth 동기화)
      │
      ▼
scripts/response_validator.py          ← Phase 4a
(sanity check → deterministic eval → DB UPDATE)
      │
      ▼
api/ (FastAPI :8000)
      │
      ▼
dashboard/ (React :5173)
```

### 4.1 결과 수집

```bash
python scripts/sync_results.py          # 단일 디바이스
python scripts/sync_results.py --all-devices  # 모든 디바이스
```

### 4.2 DB 적재

```bash
python scripts/ingest.py
```

멱등 실행 가능 — 중복 데이터 자동 스킵. `test_config.json`에서 `ground_truth`와 `eval_strategy`를 prompts 테이블에 동기화합니다.

### 4.3 응답 검증 (Phase 4a)

```bash
python scripts/response_validator.py
```

상세 사용법은 [Section 8.5](#85-response-validation-phase-4a) 참조.

### 4.4 API 서버 실행

```bash
cd api && uvicorn main:app --reload
```

Swagger UI: http://localhost:8000/docs

### 4.5 Dashboard 실행

```bash
cd dashboard && npm install && npm run dev
```

http://localhost:5173

---

## 5. API Endpoints

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/results` | 전체 결과 (필터 + 페이지네이션) |
| GET | `/api/results/summary` | 집계 통계 (KPI) |
| GET | `/api/results/by-model` | 모델별 통계 |
| GET | `/api/results/by-category` | 카테고리별 통계 |
| GET | `/api/results/compare` | 모델 간 비교 |
| GET | `/api/results/compare-devices` | 디바이스 간 비교 (Phase 3) |
| GET | `/api/validation/summary` | **검증 결과 집계 (Phase 4a)** |
| GET | `/api/validation/by-category` | **카테고리별 검증 분포 (Phase 4a)** |
| GET | `/api/validation/by-model` | **모델별 검증 비교 (Phase 4a)** |
| GET | `/api/models` | 모델 목록 |
| GET | `/api/devices` | 디바이스 목록 |
| GET | `/api/categories` | 카테고리 목록 |
| GET | `/api/export/csv` | CSV 다운로드 |
| GET | `/api/runs` | CI 실행 이력 목록 |
| GET | `/api/runs/{run_id}` | 특정 run 상세 |
| GET | `/api/runs/{run_id}/summary` | 특정 run 집계 통계 |
| GET | `/api/run-ids` | run_id 목록 (드롭다운용) |
| GET | `/health` | 헬스체크 |

공통 필터 파라미터: `device`, `model`, `category`, `backend`, `status`, `run_id`, `limit`, `offset`

---

## 6. CI/CD

GitHub Actions self-hosted runner를 통해 ADB 연결된 물리 기기에서 벤치마크를 자동 실행합니다.

### 6.1 Runner 등록

```bash
# GitHub 리포 → Settings → Actions → Runners → New self-hosted runner
# 안내에 따라 설치 후:
./config.sh --url https://github.com/tecace-soft/on-device-llm-tester \
            --token <REGISTRATION_TOKEN>

# 라벨 설정: self-hosted, llm-bench
sudo ./svc.sh install && sudo ./svc.sh start
```

### 6.2 벤치마크 실행

GitHub UI → Actions 탭 → **LLM Benchmark** → **Run workflow**

워크플로우 입력 옵션:

| 입력 | 기본값 | 설명 |
|------|--------|------|
| `device_mode` | `all` | `all`: 연결된 모든 디바이스 / `single`: 첫 번째 디바이스만 |
| `parallel` | `false` | `true`: 디바이스 병렬 실행 (속도 우선, 결과 노이즈 가능) |

CLI:
```bash
gh workflow run benchmark.yml
gh workflow run benchmark.yml -f device_mode=all -f parallel=true
```

### 6.3 파이프라인 흐름

```
GitHub UI "Run workflow" (device_mode, parallel 선택)
      │
      ▼
Self-hosted Runner (ADB 연결된 개발 PC)
      ├─ discover devices        (디바이스 수 확인)
      ├─ shuttle.py --all-devices (모델 사전 배포)
      ├─ runner.py --all-devices  (순차 또는 병렬 벤치마크)
      ├─ sync_results.py          (결과 수집)
      ├─ ingest.py                (JSON → SQLite + runs 기록)
      ├─ response_validator.py    (응답 검증 — Phase 4a)
      ├─ upload-artifact          (.db → GitHub Artifact, 90일 보존)
      └─ upload logs              (병렬 모드 시 디바이스별 로그)
```

### 6.4 설정 변경

`test_config.json` 수정 → commit & push → Run workflow 실행.

---

## 7. Multi-Device 사용법 (Phase 3)

### 7.1 로컬 실행

```bash
# 1. 연결된 디바이스 확인
adb devices -l

# 2. 모든 디바이스에 모델 배포 (최초 또는 모델 변경 시)
python scripts/shuttle.py --all-devices

# 3. 모든 디바이스에서 순차 벤치마크 실행
python scripts/runner.py --all-devices

# 4. 병렬 실행 (속도 우선)
python scripts/runner.py --all-devices --parallel

# 5. 특정 디바이스만 실행
python scripts/runner.py --serial RFXXXXXXXX

# 6. DB 적재
python scripts/ingest.py
```

### 7.2 디바이스 순차 vs 병렬

| 모드 | 명령 | 특징 |
|------|------|------|
| 순차 (기본) | `--all-devices` | 디바이스별 thermal check → 테스트 → 즉시 sync. 공정한 비교 |
| 병렬 | `--all-devices --parallel` | subprocess로 동시 실행. 속도 빠름. 로그는 `logs/{serial}_runner.log`에 분리 |
| 단일 | `--serial XXXX` | 특정 디바이스만 타겟 |
| 기존 호환 | (플래그 없음) | USB에 1대 연결 시 기존과 동일 동작 |

### 7.3 Thermal Guard

멀티디바이스 순차 실행 시, 각 디바이스 테스트 시작 전에 배터리 온도를 체크합니다.

- 임계값: 35.0°C
- 초과 시: 30초 간격으로 최대 5분 대기
- 5분 후에도 고온: 경고 로그 출력 후 테스트 진행

### 7.4 Device Compare 대시보드

Dashboard → **Device Compare** 페이지에서 디바이스 간 성능 비교 가능:

- Device A / B 드롭다운으로 비교 대상 선택
- 모델 필터 (선택)
- KPI 비교: Avg Latency, Decode TPS, TTFT, Success Rate (최적값 녹색 강조)
- 카테고리별 Decode TPS 그룹드 바 차트
- 상세 테이블: 카테고리별 Latency / TPS / TTFT 나란히 비교

### 7.5 API

```
GET /api/results/compare-devices?devices=SM-S931U,SM-S926U&model=gemma3-1b-it-int4.task
```

응답: 디바이스별 집계 통계 + 디바이스 메타정보 (SoC, Android 버전 등) + 카테고리별 통계

---

## 8. test_config.json

벤치마크 설정 파일. 모델, 프롬프트, 정답(ground_truth), 평가 전략(eval_strategy)을 정의합니다.

```json
{
  "timeout_sec": 60,
  "models": [
    {
      "path": "/data/local/tmp/llm_test/models/gemma3-1b-it-int4.task",
      "max_tokens": 1024,
      "backend": "CPU"
    }
  ],
  "prompts": [
    {
      "id": "math_01",
      "category": "math",
      "lang": "en",
      "prompt": "What is 237 + 485?",
      "ground_truth": "722",
      "eval_strategy": "deterministic"
    },
    {
      "id": "factual_01",
      "category": "knowledge",
      "lang": "en",
      "prompt": "What is the capital of France?",
      "ground_truth": "Paris",
      "eval_strategy": "deterministic_with_fallback"
    },
    {
      "id": "code_01",
      "category": "code",
      "lang": "en",
      "prompt": "Write a Python function that returns the factorial of a number.",
      "ground_truth": null,
      "eval_strategy": "structural"
    },
    {
      "id": "creative_01",
      "category": "creative",
      "lang": "en",
      "prompt": "Write a short story about a robot discovering the ocean.",
      "ground_truth": null,
      "eval_strategy": "none"
    }
  ]
}
```

`ground_truth`와 `eval_strategy`는 optional — 미지정 시 기본값 `null` / `"none"`. 기존 `runner.py`, `sync_results.py`는 이 필드를 무시하므로 하위 호환됩니다.

---

## 8.5 Response Validation (Phase 4a)

벤치마크 응답의 정확성을 자동 검증합니다. 외부 API 의존 없이 표준 라이브러리만 사용합니다.

### 파이프라인

```
ingest.py (JSON → DB)
    │
    ▼
response_validator.py (DB → sanity check → eval → DB UPDATE)
    │
    ├─ Sanity: empty response, truncation, gibberish 감지
    ├─ Deterministic: math exact match, keyword containment
    ├─ Structural: JSON/Python syntax validation
    └─ Quant Diff: 양자화 간 응답 일치율 비교
```

### 실행

```bash
# 기본: 미검증 결과 전체 검증
python scripts/response_validator.py

# 특정 CI run만 검증
python scripts/response_validator.py --run-id 12345678

# dry-run (DB 변경 없이 결과만 확인)
python scripts/response_validator.py --dry-run

# 기존 결과 재검증
python scripts/response_validator.py --force

# 양자화 diff 리포트
python scripts/response_validator.py --quant-diff

# 검증 요약만 출력
python scripts/response_validator.py --summary-only
```

### Validation Status

| 값 | 의미 |
|---|------|
| `pass` | 모든 체크 통과 + deterministic eval 정답 |
| `fail` | empty response, 오답, invalid structure |
| `warn` | truncated 또는 gibberish 감지 |
| `uncertain` | containment 매칭 실패 — Phase 4b LLM judge 필요 |
| `skip` | error status 또는 eval_strategy=none |

### eval_strategy 설정

| eval_strategy | 용도 | ground_truth 예시 |
|--------------|------|------------------|
| `deterministic` | math, 단답형 | `"722"`, `"4"`, `"yes"` |
| `deterministic_with_fallback` | 지식, 추론 | `"Paris"`, `"A"` |
| `structural` | JSON, 코드 | `"name,age,city"` (기대 키) 또는 `null` |
| `none` | creative, 요약 | `null` |

### API 엔드포인트

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/validation/summary` | 검증 결과 집계 (pass_rate 포함) |
| GET | `/api/validation/by-category` | 카테고리별 pass/fail/warn 분포 |
| GET | `/api/validation/by-model` | 모델별 pass_rate + truncation_rate |

### ground_truth 작성 가이드

새 프롬프트를 `test_config.json`에 추가할 때:

1. **math / minimal_output**: 정확한 정답 숫자 또는 단답. `"eval_strategy": "deterministic"`
2. **knowledge / reasoning**: 정답에 반드시 포함되어야 하는 핵심 키워드. `"eval_strategy": "deterministic_with_fallback"`
3. **structured_output**: JSON일 경우 기대 키를 쉼표로 나열 (예: `"name,age,city"`). `"eval_strategy": "structural"`
4. **code**: `ground_truth: null`, `"eval_strategy": "structural"` (Python syntax 체크만)
5. **creative / summarization / long_generation**: `ground_truth: null`, `"eval_strategy": "none"` (sanity check만)

---

## 9. Architecture Documents

| 문서 | 내용 |
|------|------|
| `DASHBOARD_ARCHITECTURE.md` | Phase 1 Dashboard 설계 (FastAPI + React) |
| `DB_MIGRATION_ARCHITECTURE.md` | Phase 1.5 SQLite 마이그레이션 설계 |
| `CICD_ARCHITECTURE.md` | Phase 2 CI/CD 파이프라인 설계 |
| `MULTIDEVICE_ARCHITECTURE.md` | Phase 3 멀티디바이스 설계 |
| `RESPONSE_VALIDATION_ARCHITECTURE.md` | Phase 4a 응답 검증 설계 |
| `QUALITY_EVAL_ARCHITECTURE.md` | Phase 4b LLM Judge 설계 (예정) |

---

## 10. Roadmap

| Phase | 내용 | 상태 |
|-------|------|------|
| PoC | Android 앱 + ADB 파이프라인 | ✅ |
| 1 | Dashboard (FastAPI + React) | ✅ |
| 1.5 | SQLite DB 마이그레이션 | ✅ |
| 2 | CI/CD (GitHub Actions) | ✅ |
| 3 | Multi-Device 지원 | ✅ |
| 4a | Response Validation (Deterministic) | ✅ |
| 4b | AI Quality Eval (LLM Judge) | 🔜 |

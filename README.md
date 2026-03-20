# On-device LLM Inference Test Automation

> **Project Status:** Phase 3 — Multi-Device Support ✅

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
│       └── benchmark.yml          # CI/CD 워크플로우 (멀티디바이스 지원)
│
├── android/                       # Android app (com.tecace.llmtester)
│
├── api/                           # FastAPI backend (:8000)
│   ├── main.py                    # 엔드포인트 + CORS + auth
│   ├── db.py                      # SQLite 연결 + 스키마 초기화
│   ├── loader.py                  # SQL SELECT 기반 데이터 로드
│   ├── stats.py                   # SQL 집계 (summary, compare, device-compare)
│   ├── schemas.py                 # Pydantic 스키마
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
│   └── ingest.py                  # JSON → SQLite 적재
│
├── results/                       # Raw JSON 원본 (gitignore됨)
│   ├── SM-S931U/                  # 디바이스별 디렉토리
│   └── SM-S926U/
├── logs/                          # 병렬 모드 디바이스별 로그 (gitignore됨)
├── models/                        # 모델 파일 (gitignore됨)
├── test_config.json               # 테스트 설정 (모델, 프롬프트)
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
(JSON → api/data/llm_tester.db)
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

멱등 실행 가능 — 중복 데이터 자동 스킵.

### 4.3 API 서버 실행

```bash
cd api && uvicorn main:app --reload
```

Swagger UI: http://localhost:8000/docs

### 4.4 Dashboard 실행

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
| GET | `/api/results/compare-devices` | **디바이스 간 비교 (Phase 3)** |
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

벤치마크 설정 파일. 모델과 프롬프트를 정의합니다.

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
      "prompt": "What is 237 + 485?"
    }
  ]
}
```

---

## 9. Architecture Documents

| 문서 | 내용 |
|------|------|
| `DASHBOARD_ARCHITECTURE.md` | Phase 1 Dashboard 설계 (FastAPI + React) |
| `DB_MIGRATION_ARCHITECTURE.md` | Phase 1.5 SQLite 마이그레이션 설계 |
| `CICD_ARCHITECTURE.md` | Phase 2 CI/CD 파이프라인 설계 |
| `MULTIDEVICE_ARCHITECTURE.md` | Phase 3 멀티디바이스 설계 |

---

## 10. Roadmap

| Phase | 내용 | 상태 |
|-------|------|------|
| PoC | Android 앱 + ADB 파이프라인 | ✅ |
| 1 | Dashboard (FastAPI + React) | ✅ |
| 1.5 | SQLite DB 마이그레이션 | ✅ |
| 2 | CI/CD (GitHub Actions) | ✅ |
| 3 | Multi-Device 지원 | ✅ |
| 4 | AI Quality Eval (GPT 기반) | 🔜 |

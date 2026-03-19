# On-device LLM Inference Test Automation

> **Project Status:** Phase 2 — CI/CD Pipeline ✅

Android 기기에서 구동되는 LLM(MediaPipe 기반)의 추론 성능 및 결과 품질을 자동으로 벤치마킹하는 파이프라인입니다. GitHub Actions self-hosted runner를 통해 ADB 연결된 실물 기기에서 CI 실행이 가능합니다.

---

## 1. Prerequisites

| 항목 | 요구사항 |
|------|---------|
| Python | 3.10+ |
| Node.js | 18+ (Dashboard) |
| ADB | Android SDK Platform-Tools (PATH 등록 필수) |
| Android 기기 | 개발자 옵션 활성화 + USB 디버깅 허용 |

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
│       └── benchmark.yml       # CI/CD 워크플로우 (Phase 2)
│
├── android/                    # Android app (com.tecace.llmtester)
│
├── api/                        # FastAPI backend (:8000)
│   ├── main.py                 # 엔드포인트 + CORS + auth
│   ├── db.py                   # SQLite 연결 + 스키마 초기화
│   ├── loader.py               # SQL SELECT 기반 데이터 로드
│   ├── stats.py                # SQL 집계 (summary, by-model, compare)
│   ├── schemas.py              # Pydantic 스키마
│   ├── requirements.txt
│   └── data/
│       └── llm_tester.db       # SQLite DB (gitignore됨)
│
├── dashboard/                  # React + Vite + TypeScript (:5173)
│   └── src/
│       ├── pages/
│       │   ├── Overview.tsx
│       │   ├── Performance.tsx
│       │   ├── Compare.tsx
│       │   ├── Responses.tsx
│       │   ├── RawData.tsx
│       │   └── RunHistory.tsx  # CI 실행 이력 (Phase 2)
│       └── ...
│
├── scripts/
│   ├── setup.py                # 초기 폴더 구조 생성
│   ├── shuttle.py              # 모델 파일 → 기기 전송
│   ├── runner.py               # ADB 추론 실행 + Smart Polling
│   ├── sync_results.py         # 기기 → PC 결과 수집
│   └── ingest.py               # JSON → SQLite 적재
│
├── results/                    # Raw JSON 원본 (gitignore됨)
├── models/                     # 모델 파일 (gitignore됨)
├── report.py                   # CLI 리포트 생성
├── test_config.json            # 테스트 설정 (모델, 프롬프트)
└── .env                        # 환경변수 (gitignore됨)
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
python scripts/sync_results.py
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
| GET | `/api/models` | 모델 목록 |
| GET | `/api/devices` | 디바이스 목록 |
| GET | `/api/categories` | 카테고리 목록 |
| GET | `/api/export/csv` | CSV 다운로드 |
| GET | `/api/runs` | CI 실행 이력 목록 (Phase 2) |
| GET | `/api/runs/{run_id}` | 특정 run 상세 (Phase 2) |
| GET | `/api/runs/{run_id}/summary` | 특정 run 집계 통계 (Phase 2) |
| GET | `/api/run-ids` | run_id 목록 (드롭다운용) |
| GET | `/health` | 헬스체크 |

공통 필터 파라미터: `device`, `model`, `category`, `backend`, `status`, `run_id`, `limit`, `offset`

---

## 6. CI/CD (Phase 2)

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

또는 CLI:
```bash
gh workflow run benchmark.yml
```

### 6.3 파이프라인 흐름

```
GitHub UI "Run workflow"
      │
      ▼
Self-hosted Runner (ADB 연결된 개발 PC)
      ├─ runner.py         (ADB → 폰에서 추론 실행)
      ├─ sync_results.py   (폰 → PC로 JSON pull)
      ├─ ingest.py         (JSON → SQLite + runs 테이블 기록)
      └─ upload-artifact   (.db 파일 → GitHub Artifact, 90일 보존)
```

### 6.4 설정 변경

`test_config.json` 수정 → commit & push → Run workflow 실행.

파라미터(모델, 프롬프트, backend, max_tokens)는 모두 `test_config.json`에서 관리됩니다.

### 6.5 Run History 확인

Dashboard → **Run History** 페이지에서 CI 실행 이력 확인.  
행 클릭 시 해당 run의 results만 필터링된 Raw Data 페이지로 이동.

---

## 7. test_config.json

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

## 8. Troubleshooting

**`ModuleNotFoundError: No module named 'dotenv'`**
→ 가상환경 활성화 후 `pip install python-dotenv`

**`adb: command not found`**
→ ADB 설치 후 시스템 PATH 등록 확인

**`data: []` API 응답**
→ `python scripts/ingest.py` 실행 후 서버 재시작

**GPU 백엔드 설정**
→ `LlmRunner.kt`에서 `.setPreferredBackend(LlmInference.Backend.GPU)` 설정 필요

**내부 저장소 결과 직접 확인**
```bash
adb shell "run-as com.tecace.llmtester cat files/results/last_result.json"
```

**좀비 run (status=running 고착)**
→ FastAPI 앱 재시작 시 24시간 이상 `running` 상태인 run을 자동으로 `error` 처리

---

## 9. Roadmap

| Phase | 상태 | 내용 |
|-------|------|------|
| Phase 1 | ✅ 완료 | FastAPI + React Dashboard |
| Phase 1.5 | ✅ 완료 | SQLite DB 마이그레이션 |
| Phase 2 | ✅ 완료 | GitHub Actions CI/CD + Run History |
| Phase 3 | 🔜 예정 | 멀티 디바이스 병렬 벤치마크 |
| Phase 4 | 🔜 예정 | GPT API 기반 응답 품질 자동 평가 |

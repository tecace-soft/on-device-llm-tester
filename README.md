# On-device LLM Inference Test Automation

> **Project Status:** Phase 1.5 — SQLite DB Pipeline ✅

이 프로젝트는 Android 기기 내에서 구동되는 LLM(MediaPipe 기반)의 추론 성능 및 결과 품질을 자동으로 벤치마킹하기 위한 파이프라인입니다.

---

## 1. Prerequisites

- **Python 3.10+**
- **ADB (Android Debug Bridge)** 설치 및 시스템 경로(Path) 등록
  - [Platform-Tools 다운로드](https://developer.android.com/studio/releases/platform-tools) 후 환경 변수 등록 필수
- **Node.js 18+** (Dashboard)
- **안드로이드 기기**: 개발자 옵션 활성화 + USB 디버깅 허용

---

## 2. Installation & Setup

### 2.1 가상환경 생성 및 활성화

```bash
python -m venv .venv
.\.venv\Scripts\activate  # Windows
source .venv/bin/activate # Mac/Linux
```

### 2.2 Python 의존성 설치

```bash
pip install -r requirements.txt
pip install -r api/requirements.txt
```

### 2.3 환경변수 설정

`.env` 파일을 프로젝트 루트에 생성:

```env
LOCAL_MODEL_DIR=./models
HF_TOKEN=your_token_here

# API (선택)
API_KEY=your_api_key_here
ALLOWED_ORIGINS=http://localhost:5173
```

> `DB_PATH`, `RESULTS_DIR`은 설정하지 마세요. 스크립트가 `__file__` 기준 절대경로를 자동으로 사용합니다.

### 2.4 초기 폴더 구조 생성

```bash
python scripts/setup.py
```

`models/`, `results/`, `logs/`, `api/data/` 디렉토리가 생성됩니다.

---

## 3. Project Structure

```
on-device-llm-tester/
├── android/                    # Android app (com.tecace.llmtester)
├── api/                        # FastAPI backend
│   ├── main.py                 # App entry + CORS + auth
│   ├── db.py                   # SQLite 연결 + 스키마 초기화
│   ├── loader.py               # SQL SELECT 기반 데이터 로드
│   ├── stats.py                # SQL 집계 (summary, by-model, compare)
│   ├── schemas.py              # Pydantic 스키마
│   ├── requirements.txt
│   └── data/
│       └── llm_tester.db       # SQLite DB (gitignore됨)
├── dashboard/                  # React + Vite + TypeScript
├── scripts/
│   ├── setup.py                # 초기 폴더 구조 생성
│   ├── shuttle.py              # 모델 파일 → 기기 전송
│   ├── runner.py               # ADB 추론 실행 + 모니터링
│   ├── sync_results.py         # 기기 → PC 결과 수집
│   └── ingest.py               # JSON → SQLite 적재
├── results/                    # Raw JSON 원본 (gitignore됨)
├── models/                     # 모델 파일 (gitignore됨)
├── report.py                   # CLI 리포트 생성
├── test_config.json            # 프롬프트 설정
└── .env                        # 환경변수 (gitignore됨)
```

---

## 4. Data Pipeline

```
Android App → JSON files (앱 샌드박스)
                  │
                  ▼
         scripts/sync_results.py
         (ADB로 JSON 수집 → results/{device}/{model}/*.json)
                  │
                  ▼
         scripts/ingest.py
         (JSON → SQLite: api/data/llm_tester.db)
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
| GET | `/health` | 헬스체크 |

공통 필터 파라미터: `device`, `model`, `category`, `backend`, `status`, `limit`, `offset`

---

## 6. Troubleshooting

**`ModuleNotFoundError: No module named 'dotenv'`**
→ 가상환경 활성화 후 `pip install python-dotenv`

**`adb: command not found`**
→ ADB 설치 후 시스템 PATH 등록 확인

**`data: []` API 응답**
→ `python scripts/ingest.py` 실행 후 서버 재시작

**GPU 백엔드 설정**
→ `LlmRunner.kt`에서 `.setPreferredBackend(LlmInference.Backend.GPU)` 설정 필요
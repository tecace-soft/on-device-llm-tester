# On-device LLM Inference Test Automation

> **Project Status:** Phase 6.1 — Quantization Comparison ✅

Android 기기에서 구동되는 LLM(MediaPipe + llama.cpp 기반)의 추론 성능 및 결과 품질을 자동으로 벤치마킹하는 파이프라인입니다. GitHub Actions self-hosted runner를 통해 ADB 연결된 복수의 실물 기기에서 CI 실행이 가능합니다.

**Phase 6.1**에서는 같은 base model의 양자화 변형(Q3_K_M, Q4_K_M, Q8_0 등)을 **성능 + 품질 + 리소스** 3축으로 통합 비교하여 최적의 양자화 레벨을 찾는 파이프라인을 추가했습니다.

---

## 1. Prerequisitesz

| 항목 | 요구사항 |
|------|---------|
| Python | 3.10+ |
| Node.js | 18+ (Dashboard) |
| ADB | Android SDK Platform-Tools (PATH 등록 필수) |
| Android 기기 | 개발자 옵션 활성화 + USB 디버깅 허용 (1대 이상) |
| Android NDK | 27+ (llama.cpp 빌드 시 필요) |

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

### 2.5 llama.cpp submodule 초기화

```bash
git submodule update --init --recursive
```

APK 빌드 시 Android Studio가 자동으로 llama.cpp NDK 빌드를 수행합니다.

---

## 3. Project Structure

```
on-device-llm-tester/
├── .github/
│   └── workflows/
│       └── benchmark.yml          # CI/CD 워크플로우 (resource profiling 포함)
│
├── android/                       # Android app (com.tecace.llmtester)
│   └── app/src/main/
│       ├── java/.../
│       │   ├── MainActivity.kt        # 엔진 분기 + 결과 JSON 생성
│       │   ├── InferenceEngine.kt     # 엔진 인터페이스
│       │   ├── MediaPipeEngine.kt     # MediaPipe .task 추론
│       │   ├── LlamaCppEngine.kt      # llama.cpp GGUF 추론 (Phase 5)
│       │   ├── LlamaCpp.kt            # JNI 바인딩 선언 (Phase 5)
│       │   └── InferenceMetrics.kt    # 메트릭 데이터 클래스
│       └── cpp/
│           ├── CMakeLists.txt         # NDK 빌드 설정 (Phase 5)
│           ├── llama-jni.cpp          # JNI C++ 구현 (Phase 5)
│           └── llama.cpp/             # git submodule (Phase 5)
│
├── api/                           # FastAPI backend (:8000)
│   ├── main.py                    # 엔드포인트 + CORS + auth
│   ├── db.py                      # SQLite 연결 + 스키마 초기화 + 마이그레이션
│   ├── loader.py                  # SQL SELECT 기반 데이터 로드 (resource_profile 포함)
│   ├── stats.py                   # SQL 집계 (resource summary + quant comparison 포함)
│   ├── schemas.py                 # Pydantic 스키마 (Quant* 스키마 포함)
│   ├── utils.py                   # ✨ Phase 6.1: extract_base_and_quant, select_baseline, generate_insight
│   ├── requirements.txt
│   └── data/
│       └── llm_tester.db          # SQLite DB (gitignore됨)
│
├── dashboard/                     # React + Vite + TypeScript (:5173)
│   └── src/
│       ├── pages/
│       │   ├── Resource.tsx           # Phase 6: 리소스 프로파일링 대시보드
│       │   ├── QuantCompare.tsx       # ✨ Phase 6.1: 양자화 비교 대시보드
│       │   └── ...
│       ├── hooks/
│       │   └── useQuantCompare.ts     # ✨ Phase 6.1: comparison + similarity 병렬 호출
│       ├── types/
│       │   └── index.ts               # Quant* 타입 + QuantDiffItem 포함
│       └── components/
│           ├── layout/
│           │   └── Sidebar.tsx        # Quant Compare 메뉴 포함 (v6.1.0)
│           ├── quant/                 # ✨ Phase 6.1
│           │   ├── InsightCards.tsx
│           │   ├── ComparisonTable.tsx
│           │   ├── TradeoffRadar.tsx
│           │   ├── SimilarityMatrix.tsx
│           │   └── CategorySimilarity.tsx
│           └── validation/
│               └── QuantDiffTable.tsx  # ✨ Phase 6.1: Validation 페이지 응답 유사도
│
├── scripts/
│   ├── setup.py                   # 초기 폴더 구조 생성
│   ├── device_discovery.py        # ADB 디바이스 검색 + thermal guard
│   ├── resource_profiler.py       # ✨ Phase 6: 배터리/온도/메모리 프로파일링 모듈
│   ├── shuttle.py                 # 모델 파일 → 기기 전송
│   ├── runner.py                  # ADB 추론 실행 (resource profiling 통합 — Phase 6)
│   ├── sync_results.py            # 기기 → PC 결과 수집
│   ├── ingest.py                  # JSON → SQLite 적재 (profile 매칭 — Phase 6)
│   ├── response_validator.py      # 응답 검증 파이프라인
│   └── validators/
│
├── results/                       # Raw JSON 원본 + profile_*.json (gitignore됨)
├── logs/                          # 병렬 모드 디바이스별 로그 (gitignore됨)
├── models/                        # 모델 파일 (gitignore됨)
├── test_config.json               # 테스트 설정
└── .env                           # 환경변수 (gitignore됨)
```

---

## 4. Data Pipeline

```
Android App → JSON (앱 샌드박스)
      │
      ▼
scripts/runner.py
(추론 실행 + ✨ resource profiling: battery/thermal/voltage/current/meminfo)
      │
      ├─ result_*.json (앱 생성, ADB pull)
      └─ profile_*.json (runner.py 생성, PC-side)
      │
      ▼
scripts/sync_results.py
(ADB → results/{device}/{model}/*.json)
      │
      ▼
scripts/ingest.py
(result + profile 매칭 → api/data/llm_tester.db + ground_truth 동기화)
      │
      ▼
scripts/response_validator.py
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

멱등 실행 가능 — 중복 데이터 자동 스킵. `test_config.json`에서 `ground_truth`와 `eval_strategy`를 prompts 테이블에 동기화합니다. Phase 6의 `profile_*.json`은 자동 매칭됩니다.

### 4.3 응답 검증

```bash
python scripts/response_validator.py
```

상세 사용법은 [Section 8.5](#85-response-validation) 참조.

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

## 5. Supported Engines (Phase 5)

| 엔진 | 모델 포맷 | 설명 |
|------|----------|------|
| `mediapipe` | `.task` | Google MediaPipe LLM Inference. 기존 기본 엔진 |
| `llamacpp` | `.gguf` | llama.cpp JNI 바인딩. GGUF 양자화 모델 지원 |

### 5.1 GGUF 모델 사용법

```bash
# 1. GGUF 모델 다운로드 (HuggingFace)
# 예: https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF

# 2. models/ 폴더에 저장
cp SmolLM2-135M-Instruct-Q8_0.gguf models/

# 3. 디바이스에 배포
python scripts/shuttle.py --all-devices

# 4. test_config.json에 모델 추가 (engine + engine_params 명시)
```

### 5.2 test_config.json 모델 설정

```json
{
  "models": [
    {
      "path": "/data/local/tmp/llm_test/models/gemma3-1b-it-int4.task",
      "max_tokens": 1024,
      "backend": "CPU",
      "engine": "mediapipe"
    },
    {
      "path": "/data/local/tmp/llm_test/models/SmolLM2-135M-Instruct-Q8_0.gguf",
      "max_tokens": 1024,
      "backend": "CPU",
      "engine": "llamacpp",
      "engine_params": {
        "n_gpu_layers": "0",
        "n_threads": "4",
        "n_ctx": "2048"
      }
    }
  ]
}
```

### 5.3 engine_params (llama.cpp)

| 키 | 기본값 | 설명 |
|----|--------|------|
| `n_gpu_layers` | `"0"` | GPU 오프로드 레이어 수 (`"0"` = CPU only) |
| `n_threads` | `"4"` | 추론 스레드 수 |
| `n_ctx` | `"2048"` | 컨텍스트 윈도우 크기 |
| `temperature` | `"0.7"` | 샘플링 온도 |
| `top_p` | `"0.95"` | Nucleus sampling |
| `top_k` | `"40"` | Top-k sampling |
| `repeat_penalty` | `"1.1"` | 반복 페널티 |

### 5.4 엔진 자동 감지

`engine` 미지정 시 파일 확장자 기반 자동 추론:
- `.task` → `mediapipe`
- `.gguf` → `llamacpp`

명시적 `engine` 지정을 권장합니다.

### 5.5 수동 테스트

```bash
# MediaPipe
adb shell am start -n com.tecace.llmtester/.MainActivity \
  --es model_path "/data/local/tmp/llm_test/models/gemma3-1b-it-int4.task" \
  --es input_prompt "What is 2+2?" --ei max_tokens 32

# llama.cpp
adb shell am start -n com.tecace.llmtester/.MainActivity \
  --es model_path "/data/local/tmp/llm_test/models/SmolLM2-135M-Instruct-Q8_0.gguf" \
  --es input_prompt "What is 2+2?" --ei max_tokens 32 \
  --es engine "llamacpp"
```

### 5.6 APK 빌드

```bash
cd android
./gradlew assembleDebug
# APK: android/app/build/outputs/apk/debug/app-debug.apk
```

> llama.cpp submodule이 초기화되어 있어야 합니다 (`git submodule update --init --recursive`).

---

## 6. Resource Profiling (Phase 6)

추론 전후의 배터리, 온도, 전압, 전류, 시스템 메모리를 자동 수집합니다. **앱 변경 없이** `runner.py`에서 ADB 커맨드로 수집합니다.

### 6.1 수집 항목

| 메트릭 | 소스 | 수집 시점 | 단위 |
|--------|------|----------|------|
| Battery Level | `dumpsys battery` → `level` | 전/후 | % |
| Temperature | `dumpsys battery` → `temperature` | 전/후 | 10분의 1도 (310 = 31.0°C) |
| Voltage | `dumpsys battery` → `voltage` | 전/후 | mV |
| Current | `dumpsys battery` → `current now` | 전/후 | μA |
| System PSS | `dumpsys meminfo <pkg>` → `TOTAL` | 추론 후 | MB |

### 6.2 자동 수집 (기본 동작)

`runner.py`가 각 추론 테스트 전후에 자동으로 프로파일링을 수집합니다. 별도 설정이 필요 없습니다.

```bash
# 기존과 동일하게 실행 — 프로파일링이 자동 포함됨
python scripts/runner.py --all-devices
```

수집된 프로파일링 데이터는 `profile_*.json` 파일로 `results/{device}/{model}/` 디렉토리에 저장됩니다.

### 6.3 프로파일러 단독 테스트

```bash
# 디바이스 연결 상태에서 dumpsys 파싱 결과 확인
python scripts/resource_profiler.py

# 특정 디바이스 지정
python scripts/resource_profiler.py --serial RFXXXXXXXX
```

### 6.4 DB 적재

```bash
python scripts/ingest.py
```

`ingest.py`가 `result_*.json`과 같은 디렉토리의 `profile_*.json`을 타임스탬프(±5초) 기반으로 자동 매칭하여 results 테이블의 profiling 컬럼에 적재합니다.

### 6.5 Dashboard

Dashboard의 **Resource** 페이지에서 모델별 리소스 소비를 시각화합니다:

- **KPI 카드**: Avg Thermal Δ, Avg Voltage Δ, Avg Current Δ, Avg System PSS
- **차트**: Thermal Impact by Model, Voltage Drop by Model, Memory PSS vs Native 비교

Overview 페이지에도 프로파일링 데이터가 있으면 Resource KPI 카드가 자동 표시됩니다.

### 6.6 Thermal Guard

| 임계값 | 값 | 용도 |
|--------|------|------|
| 디바이스 시작 전 | 35.0°C | `device_discovery.py` — 테스트 시작 전 쿨다운 |
| 테스트 간 | 38.0°C | `runner.py` — 추론 후 온도 초과 시 다음 테스트 전 쿨다운 |

### 6.7 파생 지표

API에서 computed field로 제공되는 파생 지표:

| 지표 | 공식 | 의미 |
|------|------|------|
| `battery_delta` | `end - start` | 배터리 잔량 변화 (%) |
| `thermal_delta` | `end - start` | 온도 변화 (10분의 1도) |
| `voltage_delta_mv` | `end - start` | 전압 변화 (mV) |
| `current_delta_ua` | `after - before` | 전류 변화 (μA) |
| `thermal_*_celsius` | `raw / 10` | 섭씨 단위 변환 |

---

## 7. API Endpoints

| Method | Endpoint | 설명 |
|--------|----------|------|
| GET | `/api/results` | 전체 결과 (필터 + 페이지네이션, `resource_profile` 포함) |
| GET | `/api/results/summary` | 집계 통계 (KPI + `resource` summary) |
| GET | `/api/results/by-model` | 모델별 통계 (`resource` summary 포함) |
| GET | `/api/results/by-category` | 카테고리별 통계 |
| GET | `/api/results/compare` | 모델 간 비교 |
| GET | `/api/results/compare-devices` | 디바이스 간 비교 |
| GET | `/api/validation/summary` | 검증 결과 집계 |
| GET | `/api/validation/by-category` | 카테고리별 검증 분포 |
| GET | `/api/validation/by-model` | 모델별 검증 비교 |
| GET | `/api/validation/quant-diff` | ✨ 양자화 간 응답 유사도 (전체 모델 pair) |
| GET | `/api/quant/comparison` | ✨ 양자화별 성능+품질+리소스 통합 비교 |
| GET | `/api/quant/similarity` | ✨ Base model 내 양자화 pair 유사도 + 카테고리 집계 |
| GET | `/api/models` | 모델 목록 |
| GET | `/api/devices` | 디바이스 목록 |
| GET | `/api/categories` | 카테고리 목록 |
| GET | `/api/engines` | 엔진 목록 |
| GET | `/api/export/csv` | CSV 다운로드 |
| GET | `/api/runs` | CI 실행 이력 목록 |
| GET | `/api/runs/{run_id}` | 특정 run 상세 |
| GET | `/api/runs/{run_id}/summary` | 특정 run 집계 통계 |
| GET | `/api/run-ids` | run_id 목록 (드롭다운용) |
| GET | `/health` | 헬스체크 |

공통 필터 파라미터: `device`, `model`, `category`, `backend`, `engine`, `status`, `run_id`, `limit`, `offset`

---

## 8. CI/CD

GitHub Actions self-hosted runner를 통해 ADB 연결된 물리 기기에서 벤치마크를 자동 실행합니다.

### 8.1 Runner 등록

```bash
# GitHub 리포 → Settings → Actions → Runners → New self-hosted runner
# 안내에 따라 설치 후:
./config.sh --url https://github.com/tecace-soft/on-device-llm-tester \
            --token <REGISTRATION_TOKEN>

# 라벨 설정: self-hosted, llm-bench
sudo ./svc.sh install && sudo ./svc.sh start
```

### 8.2 벤치마크 실행

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

### 8.3 파이프라인 흐름

```
GitHub UI "Run workflow" (device_mode, parallel 선택)
      │
      ▼
Self-hosted Runner (ADB 연결된 개발 PC)
      ├─ checkout (with submodules)
      ├─ discover devices
      ├─ shuttle.py --all-devices     (모델 사전 배포)
      ├─ runner.py --all-devices      (벤치마크 + ✨ resource profiling)
      ├─ sync_results.py              (결과 수집)
      ├─ ingest.py                    (JSON + profile 매칭 → SQLite)
      ├─ response_validator.py        (응답 검증)
      ├─ upload-artifact              (.db → GitHub Artifact, 90일 보존)
      └─ Summary                      (DB Stats + Validation + ✨ Resource Stats)
```

### 8.4 설정 변경

`test_config.json` 수정 → commit & push → Run workflow 실행.

---

## 8.5 Multi-Device 사용법

### 로컬 실행

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

### 디바이스 순차 vs 병렬

| 모드 | 명령 | 특징 |
|------|------|------|
| 순차 (기본) | `--all-devices` | 디바이스별 thermal check → 테스트 → 즉시 sync. 공정한 비교 |
| 병렬 | `--all-devices --parallel` | subprocess로 동시 실행. 속도 빠름. 로그는 `logs/{serial}_runner.log`에 분리 |
| 단일 | `--serial XXXX` | 특정 디바이스만 타겟 |
| 기존 호환 | (플래그 없음) | USB에 1대 연결 시 기존과 동일 동작 |

---

## 8.6 Response Validation

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
python scripts/response_validator.py                    # 미검증 결과 전체
python scripts/response_validator.py --run-id 12345678  # 특정 CI run만
python scripts/response_validator.py --dry-run           # DB 변경 없이
python scripts/response_validator.py --force             # 기존 결과 재검증
python scripts/response_validator.py --quant-diff        # 양자화 diff 리포트
python scripts/response_validator.py --summary-only      # 검증 요약만
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

---

## 8.7 Quantization Comparison (Phase 6.1)

같은 base model의 양자화 변형(Q3_K_M, Q4_K_M, Q8_0 등) 간 **성능, 품질, 리소스 소비를 통합 비교**하여 최적의 양자화 레벨을 찾습니다. DB 스키마 변경 없이 기존 데이터를 활용합니다.

### 핵심 개념

- **Base Name 추출**: `gemma-4-E2B-it-Q4_K_M.gguf` → base: `gemma-4-E2B-it`, quant: `Q4_K_M`
- **Baseline 비교**: 가장 높은 정밀도(Q8_0)를 기준으로 상대 변화율(%) 계산
- **Insight 자동 생성**: trade-off 분석 기반 추천 (예: "Q4_K_M 추천: 품질 -5.6%, 속도 +3.0%")

### API

| Endpoint | 역할 | 필터 |
|----------|------|------|
| `GET /api/quant/comparison` | 성능+품질+리소스 통합 비교 (base model 그룹핑) | `device`, `base_model`, `run_id` |
| `GET /api/quant/similarity` | Base model 내 양자화 pair 유사도 + 카테고리 집계 | `device`, `base_model` |
| `GET /api/validation/quant-diff` | 전체 모델 pair 응답 유사도 (Validation 페이지용) | `device`, `base_model` |

### Dashboard — Quant Compare 페이지

독립 페이지 (`/quant-compare`)에서 양자화 trade-off를 시각적으로 분석합니다:

- **Insight Cards**: 자동 생성된 추천 인사이트
- **Comparison Table**: Baseline(Q8_0) 대비 delta 색상 표시 (↑ 초록 / ↓ 빨강 / 5% 이내 회색)
- **Trade-off Radar**: Quality / Speed / Efficiency 3축 레이더 차트
- **Similarity Matrix**: 양자화 pair 간 응답 유사도 N×N 히트맵
- **Category Similarity**: 카테고리별 평균 유사도 바 차트

### Dashboard — Validation 페이지 연동

Validation 페이지 하단의 **Response Similarity** 섹션에서 전체 모델 pair의 prompt-level 응답 유사도를 표시합니다. Quant Compare 페이지와의 차이: 같은 base model 제약 없이 **모든 모델 pair**를 비교합니다.

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
| `LLMCPP_ARCHITECTURE.md` | Phase 5 llama.cpp 멀티엔진 설계 |
| `RESOURCE_PROFILING_ARCHITECTURE.md` | **Phase 6 리소스 프로파일링 설계** |
| `QUANT_COMPARISON_ARCHITECTURE.md` | **Phase 6.1 양자화 비교 파이프라인 설계** |

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
| 5 | llama.cpp Multi-Engine | ✅ |
| 6 | Resource Profiling (Battery/Thermal/Memory) | ✅ |
| 6.1 | Quantization Comparison Pipeline | ✅ |

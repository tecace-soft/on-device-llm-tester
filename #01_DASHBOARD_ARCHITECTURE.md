# On-Device LLM Tester — Dashboard Architecture

## 1. High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          DATA PIPELINE                              │
│                                                                     │
│  Android App ──→ JSON files (앱 샌드박스)                            │
│       │                                                             │
│       ▼                                                             │
│  sync_results.py                                                    │
│    ├─ ADB run-as로 앱 샌드박스에서 JSON 읽기                          │
│    ├─ device.model + model_name 기준 디렉토리 자동 분류               │
│    ├─ JSON 파싱 실패 시 _unclassified/에 fallback 저장               │
│    └─ 결과: results/{device}/{model}/*.json                         │
│                │                                                    │
│                ▼                                                    │
│  ┌──────────────────────────┐    ┌──────────────────────────────┐   │
│  │  Python API (FastAPI)     │◄──►│  React Dashboard (Vite + TS) │   │
│  │  :8000                    │    │  :5173                        │   │
│  │                           │    │                               │   │
│  │  Auth: Optional API Key   │    │  Overview      (KPI cards)    │   │
│  │  CORS: Configurable       │    │  Performance   (charts)       │   │
│  │                           │    │  Model Compare (side-by-side) │   │
│  │  /api/results             │    │  Response QA   (output viewer)│   │
│  │  /api/results/summary     │    │  Raw Data      (table)        │   │
│  │  /api/results/compare     │    │                               │   │
│  │  /api/models              │    │  Global: ErrorBoundary        │   │
│  │  /api/devices             │    │  Global: API error handler    │   │
│  │  /api/export              │    │  Global: Loading states       │   │
│  └──────────────────────────┘    └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## 2. Why This Architecture

### Python API (FastAPI) — 왜 별도 백엔드인가?
- `report.py`의 파싱/통계 로직을 **재사용**. 이미 검증된 코드를 API로 감싸는 것
- Phase 4 AI Quality Eval 연동 시 백엔드에서 GPT API 호출 → 프론트는 결과만 받음
- 멀티 디바이스(Phase 3) 때 실시간 결과 수집 API로 확장 가능
- JSON 파일 직접 serve하면 나중에 DB 전환 시 프론트 전부 수정해야 함. API 레이어가 있으면 백엔드만 바꾸면 됨

### React + TypeScript + Vite — 왜 이 스택인가?
- **Vite**: CRA 대비 10x 빠른 HMR. 2024-25 사실상 표준
- **TypeScript**: JSON 데이터 구조가 복잡함 (metrics 중첩). 타입 안전성 필수
- **Recharts**: React 네이티브 차트 라이브러리. D3 대비 러닝커브 극히 낮음
- **Tailwind CSS**: 클래스 기반 스타일링. CSS 파일 관리 불필요
- **shadcn/ui**: 복붙형 컴포넌트. 의존성 가볍고 커스터마이징 자유도 높음

## 3. Security & Access Control

### 현재 단계 (PoC — 로컬 개발)
- API는 `localhost:8000`에서만 실행, 외부 노출 없음
- CORS는 `http://localhost:5173` (Vite dev server)만 허용

### Phase 2+ (CI/팀 공유 환경)
- 환경변수 `API_KEY`가 설정되면 `X-API-Key` 헤더 검증 활성화
- 미설정 시 인증 없이 동작 (로컬 개발 편의)
- CORS `allowed_origins`를 `.env`에서 설정 가능

```python
# api/main.py 인증 미들웨어 (옵셔널)
API_KEY = os.getenv("API_KEY")  # 없으면 인증 스킵

@app.middleware("http")
async def auth_middleware(request, call_next):
    if API_KEY and request.url.path.startswith("/api"):
        if request.headers.get("X-API-Key") != API_KEY:
            return JSONResponse(status_code=401, content={"error": "Invalid API key"})
    return await call_next(request)
```

## 4. Directory Structure

```
on-device-llm-tester/
├── android/                          # (기존) Android app
├── scripts/                          # (기존) Python automation
│   ├── runner.py                     # ADB 통한 추론 실행 + 모니터링
│   ├── shuttle.py                    # 모델 파일 → 기기 전송
│   ├── setup.py                      # 초기 폴더 구조 생성
│   └── sync_results.py              # 기기 → PC 결과 수집 + 분류
├── results/                          # (기존) Raw JSON data
│   └── SM-S931U/
│       ├── gemma3-1b-it-int4.task/
│       └── Qwen2.5-1.5B-Instruct_.../
│
├── api/                              # ✨ NEW — FastAPI backend
│   ├── main.py                       # App entry + CORS + auth middleware
│   ├── loader.py                     # JSON file loader (report.py 로직 추출)
│   ├── stats.py                      # 통계 계산 (report.py에서 분리)
│   ├── schemas.py                    # Pydantic schemas (success + error)
│   └── requirements.txt              # fastapi, uvicorn
│
├── dashboard/                        # ✨ NEW — React frontend
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── main.tsx                  # Entry point
│       ├── App.tsx                   # Router + Layout + ErrorBoundary
│       ├── api/
│       │   └── client.ts            # Axios wrapper + global error handler
│       ├── types/
│       │   └── index.ts             # TypeScript interfaces
│       ├── hooks/
│       │   ├── useResults.ts        # Data fetching + error/loading states
│       │   └── useFilters.ts        # Filter state management
│       ├── components/
│       │   ├── layout/
│       │   │   ├── Sidebar.tsx
│       │   │   └── Header.tsx
│       │   ├── charts/
│       │   │   ├── LatencyDistribution.tsx
│       │   │   ├── TpsComparison.tsx
│       │   │   ├── CategoryHeatmap.tsx
│       │   │   └── MemoryUsage.tsx
│       │   ├── cards/
│       │   │   └── KpiCard.tsx
│       │   ├── filters/
│       │   │   └── FilterBar.tsx
│       │   ├── tables/
│       │   │   └── ResultTable.tsx
│       │   └── feedback/
│       │       ├── ErrorFallback.tsx  # Error boundary UI
│       │       ├── EmptyState.tsx     # No data / no results
│       │       └── LoadingSkeleton.tsx # Skeleton loading
│       └── pages/
│           ├── Overview.tsx
│           ├── Performance.tsx
│           ├── Compare.tsx
│           ├── Responses.tsx
│           └── RawData.tsx
│
├── report.py                         # (기존 유지 — CLI용)
├── test_config.json
├── requirements.txt
└── README.md
```

## 5. Data Types & Error Handling

### 5.1 Core Data Shape (from Android JSON)

```typescript
// 성공 케이스
interface Metrics {
  ttft_ms: number
  prefill_time_ms: number
  decode_time_ms: number
  input_token_count: number
  output_token_count: number
  prefill_tps: number
  decode_tps: number
  peak_java_memory_mb: number
  peak_native_memory_mb: number
  itl_p50_ms: number
  itl_p95_ms: number
  itl_p99_ms: number
}

interface DeviceInfo {
  manufacturer: string
  model: string
  product: string
  soc: string
  android_version: string
  sdk_int: number
  cpu_cores: number
  max_heap_mb: number
}

// status에 따라 metrics 존재 여부가 달라짐
interface ResultSuccess {
  status: "success"
  prompt_id: string
  prompt_category: string
  prompt_lang: string
  model_name: string
  model_path: string
  backend: "CPU" | "GPU"
  device: DeviceInfo
  prompt: string
  response: string
  latency_ms: number
  init_time_ms: number
  metrics: Metrics          // success일 때 항상 존재
  timestamp: number
}

interface ResultError {
  status: "error"
  device: DeviceInfo
  prompt: string
  error: string
  metrics?: null             // error일 때 null 또는 미존재
  timestamp: number
}

type ResultJSON = ResultSuccess | ResultError
```

### 5.2 API Response Schemas (Pydantic)

```python
# api/schemas.py

class ApiSuccess(BaseModel, Generic[T]):
    status: Literal["ok"] = "ok"
    data: T
    meta: Optional[PaginationMeta] = None

class ApiError(BaseModel):
    status: Literal["error"] = "error"
    error: str
    detail: Optional[str] = None

class PaginationMeta(BaseModel):
    total: int
    limit: int
    offset: int
    has_more: bool

# 모든 API 응답은 ApiSuccess[T] | ApiError
# 프론트에서 status 필드로 분기
```

### 5.3 HTTP Error Responses

| Status | When | Response Body |
|--------|------|---------------|
| 200 | 정상 | `{ status: "ok", data: [...], meta: {...} }` |
| 400 | 잘못된 query param | `{ status: "error", error: "Invalid filter", detail: "..." }` |
| 404 | 모델/디바이스 미존재 | `{ status: "error", error: "Not found", detail: "..." }` |
| 401 | API key 불일치 | `{ status: "error", error: "Invalid API key" }` |
| 500 | JSON 파싱 실패 등 | `{ status: "error", error: "Internal error", detail: "..." }` |

## 6. API Endpoints

```
GET  /api/results                    → 전체 결과 (필터 + 페이지네이션)
     ?device=SM-S931U
     &model=gemma3-1b-it-int4.task
     &category=math
     &backend=CPU
     &status=success                 # success | error | all (default: all)
     &limit=50                       # default: 50, max: 500
     &offset=0

GET  /api/results/summary            → 집계 통계 (KPI cards용)
     ?device=...&model=...           # 동일 필터 지원

GET  /api/results/compare            → 모델 간 비교 데이터
     ?models=gemma3,qwen2.5

GET  /api/models                     → 사용 가능한 모델 목록
GET  /api/devices                    → 사용 가능한 디바이스 목록
GET  /api/categories                 → 프롬프트 카테고리 목록

GET  /api/export/csv                 → CSV 다운로드
     ?device=...&model=...           # 동일 필터 지원
```

## 7. Dashboard Pages

### 7.1 Overview (랜딩 페이지)
- **KPI Cards**: Total tests, Success rate, Avg latency, Avg decode TPS
- **Charts**: 모델별 latency 박스플롯, 카테고리별 성공률 바 차트
- **Purpose**: 한 눈에 전체 상태 파악

### 7.2 Performance
- **Latency Distribution**: 히스토그램 + p50/p95/p99 마커
- **TPS Over Categories**: 카테고리별 decode TPS 그룹드 바 차트
- **TTFT Analysis**: 모델별 Time-to-First-Token 비교
- **Memory Footprint**: 네이티브/자바 메모리 사용량 비교

### 7.3 Compare (모델 비교)
- 드롭다운 2개로 Model A, Model B 선택
- 동일 프롬프트에 대한 latency/TPS/response 나란히 비교
- Radar chart로 카테고리별 강약점 시각화

### 7.4 Responses (응답 품질)
- 프롬프트별 실제 응답 텍스트 뷰어
- Phase 4 AI Quality Eval 점수 표시 영역 (미래 확장)
- 카테고리 필터 + 검색

### 7.5 Raw Data
- 전체 데이터 테이블 (정렬/필터/검색)
- CSV export 버튼
- 페이지네이션 UI (limit/offset 기반)

## 8. Error Handling Strategy

### 8.1 API (Backend)
- 글로벌 exception handler로 모든 unhandled 에러 → 500 + `ApiError` 응답
- JSON 파싱 실패 → 해당 파일 스킵 + 로그, 나머지 정상 반환
- 빈 결과 → 200 + 빈 배열 (`data: []`), 404 아님

### 8.2 React (Frontend) — Step 2에서 구축
- **API Client**: Axios 인터셉터에서 401/500 등 글로벌 에러 처리
- **ErrorBoundary**: 렌더링 크래시 catch → fallback UI
- **Hook 레벨**: `useResults`에서 `{ data, loading, error }` 패턴 통일
- **컴포넌트 레벨**: 각 페이지에서 loading → skeleton, error → fallback, empty → empty state

```typescript
// hooks/useResults.ts — 모든 데이터 훅의 기본 패턴
function useResults(filters: Filters) {
  const [state, setState] = useState<{
    data: ResultJSON[] | null
    loading: boolean
    error: string | null
  }>({ data: null, loading: true, error: null })

  // ...fetch logic with try/catch
  return state
}
```

## 9. Extension Points (Phase 연동)

```
Phase 2 (GitHub Actions)
  └─→ API에 /api/runs endpoint 추가
  └─→ Dashboard에 "Run History" 페이지 추가

Phase 3 (Multi-device)
  └─→ Device selector 필터 → 이미 API에 device 파라미터 존재
  └─→ 페이지네이션 → 이미 API spec에 limit/offset 정의됨
  └─→ Device comparison 페이지 추가

Phase 4 (AI Quality Eval)
  └─→ API에서 GPT API 호출 → quality_score 필드 추가
  └─→ Responses 페이지에 점수/판정 표시
  └─→ Overview KPI에 "Avg Quality Score" 카드 추가
```

## 10. Tech Stack Summary

| Layer      | Tech                    | Why                                      |
|------------|-------------------------|------------------------------------------|
| API        | FastAPI + Uvicorn       | async, 자동 Swagger docs, Pydantic 통합   |
| Frontend   | React 18 + TypeScript   | 타입 안전, 업계 표준                        |
| Build      | Vite                    | 빠른 HMR, ESM 네이티브                    |
| Charts     | Recharts                | React 네이티브, 선언적 API                  |
| Styling    | Tailwind CSS            | 유틸리티 기반, 빠른 프로토타이핑             |
| Components | shadcn/ui               | 복붙형, 커스터마이징 자유                    |
| HTTP       | Axios                   | 인터셉터, 글로벌 에러 핸들링                 |
| Routing    | React Router v6         | 표준 SPA 라우팅                            |

## 11. Implementation Order

```
Step 1: API 서버 (api/main.py, loader.py, stats.py, schemas.py)
        → report.py 로직 추출 + FastAPI 감싸기
        → CORS + optional API key middleware
        → 에러 응답 스키마 + global exception handler
        → 페이지네이션 파라미터 정의 (구현은 간단하게)
        → Swagger에서 바로 테스트 가능

Step 2: React 프로젝트 초기 세팅 + 에러 핸들링 기반
        → Vite + TS + Tailwind + shadcn/ui
        → Layout (Sidebar + Header)
        → API client + Axios error interceptor
        → ErrorBoundary + ErrorFallback + LoadingSkeleton
        → useResults hook (data/loading/error 패턴)
        → TypeScript types (ResultSuccess | ResultError 분리)

Step 3: Overview 페이지
        → KPI cards + 기본 차트 2개
        → 여기서 React 기본기 익힘

Step 4: Performance 페이지
        → Recharts 심화 (히스토그램, 그룹드 바)
        → FilterBar 컴포넌트

Step 5: Compare + Responses + RawData
        → 나머지 페이지 순차 구현

Step 6: Polish
        → 반응형, 다크모드
        → (에러 핸들링은 이미 Step 2에서 완료)
```

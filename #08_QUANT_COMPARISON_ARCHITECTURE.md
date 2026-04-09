# On-Device LLM Tester — Quantization Comparison Pipeline Architecture

## 1. High-Level Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│             QUANTIZATION COMPARISON PIPELINE                                  │
│                                                                              │
│  기존 데이터 (변경 없음)                                                       │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  results + models + prompts 테이블                                    │   │
│  │  - 75 results (3 quant × 25 prompts)                                 │   │
│  │  - gemma-4-E2B-it: Q3_K_M / Q4_K_M / Q8_0                          │   │
│  │  - profiling: battery, thermal, decode_tps, latency 전부 채워짐       │   │
│  │  - validation: pass/fail/warn/uncertain 전부 채워짐                   │   │
│  └───────────────────────┬───────────────────────────────────────────────┘   │
│                          │                                                   │
│                          ▼                                                   │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  API Layer (✨ NEW endpoints)                                         │   │
│  │                                                                       │   │
│  │  GET /api/validation/quant-diff                                       │   │
│  │    └─ prompt-level 응답 유사도 (SequenceMatcher ratio)                 │   │
│  │                                                                       │   │
│  │  GET /api/quant/comparison                                            │   │
│  │    └─ 성능 + 품질 + 리소스 통합 비교 (핵심 엔드포인트)                    │   │
│  │                                                                       │   │
│  │  ※ DB 스키마 변경 없음. SELECT JOIN만으로 구현                          │   │
│  │  ※ compute_all_quant_diffs() 로직을 API 레이어로 이식                   │   │
│  └───────────────────────┬───────────────────────────────────────────────┘   │
│                          │                                                   │
│                          ▼                                                   │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  Dashboard — Quant Compare 탭 (✨ NEW)                                │   │
│  │                                                                       │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │   │
│  │  │ Insight Card │  │ Insight Card │  │ Insight Card │                  │   │
│  │  │ "Q3→Q8 품질  │  │ "Q4 is best │  │ "Q8 배터리   │                  │   │
│  │  │  -14% 하락"  │  │  trade-off" │  │  2x 소비"    │                  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                  │   │
│  │                                                                       │   │
│  │  ┌────────────────────────────────────────────────────────────────┐  │   │
│  │  │  Quantization Comparison Table                                  │  │   │
│  │  │  (Performance + Quality + Resource — side by side)              │  │   │
│  │  └────────────────────────────────────────────────────────────────┘  │   │
│  │                                                                       │   │
│  │  ┌──────────────────────┐  ┌──────────────────────────────────────┐  │   │
│  │  │ Radar Chart           │  │ Response Similarity Heatmap          │  │   │
│  │  │ (Quality/Speed/Power) │  │ (prompt × model pair → match ratio)  │  │   │
│  │  └──────────────────────┘  └──────────────────────────────────────┘  │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 2. Why This Architecture

### 별도 문서를 분리하는 이유

RESPONSE_VALIDATION_ARCHITECTURE.md에 `GET /api/validation/quant-diff`가 정의되어 있지만, 양자화 비교는 validation만의 문제가 아니다. **성능(TPS, latency) + 품질(validation pass rate, response similarity) + 리소스(battery, thermal)**를 통합해서 봐야 의사결정이 가능하다. 이 통합 뷰는 validation 도메인을 넘어서므로 독립 문서로 분리한다.

### SequenceMatcher를 API 레이어로 이식하는 이유

현재 `compute_all_quant_diffs()`는 `scripts/response_validator.py`에 있고 CLI stdout으로만 출력된다. 두 가지 선택지가 있었다:

| 선택지 | 장점 | 단점 |
|--------|------|------|
| **A. 스크립트에서 DB에 저장** | API가 단순 SELECT만 하면 됨 | 새 테이블 or 컬럼 필요, DB 스키마 변경 발생 |
| **B. API에서 실시간 계산** | DB 변경 zero, 항상 최신 데이터 | API 응답 시 SequenceMatcher 연산 비용 |

**B를 선택한다.** 이유:

1. **DB 스키마 변경 없음** — 핸드오버 제약조건 충족
2. **현재 데이터 규모에서 연산 비용 무시 가능** — 75개 결과의 모든 pair 비교해도 < 100ms
3. **확장 시에도 문제없음** — prompt × quant pair 수는 선형 증가. 1000개 결과까지 < 1초. 그 이상이 되면 그때 캐싱/사전 계산 고려
4. **이미 검증된 로직** — `compute_all_quant_diffs()`의 SequenceMatcher 코드를 async로 래핑하면 끝

### 대시보드를 별도 탭으로 만드는 이유

기존 Validation 페이지의 QuantDiff 섹션은 "응답 유사도 테이블"뿐이다. 양자화 비교는 성능/품질/리소스를 **통합**해서 인사이트를 도출하는 게 핵심이므로, Validation 하위가 아닌 독립 탭으로 만든다. Sidebar에 `Quant Compare` 항목 추가.

## 3. Model Base Name 추출 로직

### 3.1 문제

현재 model_name 예시:
```
gemma-4-E2B-it-Q3_K_M.gguf
gemma-4-E2B-it-Q4_K_M.gguf
gemma-4-E2B-it-Q8_0.gguf
```

이들이 "같은 base model의 다른 양자화"라는 것을 프로그래밍적으로 판별해야 한다.

### 3.2 양자화 패턴 정규식

```python
import re

# GGUF 양자화 레벨 패턴 (llama.cpp 표준)
# 참조: https://github.com/ggerganov/llama.cpp/blob/master/examples/quantize/quantize.cpp
QUANT_PATTERN = re.compile(
    r'[-_]('
    r'Q[1-8]_[0-9A-Z_]+'     # Q2_K, Q3_K_M, Q4_K_S, Q5_K_M, Q6_K, Q8_0 등
    r'|IQ[1-4]_[A-Z0-9_]+'   # IQ1_S, IQ2_XXS, IQ3_M, IQ4_NL 등
    r'|F16|F32|BF16'          # 비양자화 풀정밀도
    r')'
    r'(?:\.gguf)?$',          # optional .gguf suffix
    re.IGNORECASE
)

# MediaPipe 양자화 패턴 (기존 .task 모델 호환)
MEDIAPIPE_QUANT_PATTERN = re.compile(
    r'[-_](int[48]|fp16|fp32)'
    r'(?:\.task)?$',
    re.IGNORECASE
)


def extract_base_and_quant(model_name: str) -> tuple[str, str]:
    """모델명에서 base name과 양자화 레벨을 분리.

    Returns:
        (base_name, quant_level)
        매칭 실패 시 (model_name, "unknown")

    Examples:
        "gemma-4-E2B-it-Q3_K_M.gguf"  → ("gemma-4-E2B-it", "Q3_K_M")
        "gemma-4-E2B-it-Q8_0.gguf"    → ("gemma-4-E2B-it", "Q8_0")
        "gemma3-1b-it-int4.task"       → ("gemma3-1b-it", "int4")
        "some-unknown-model"           → ("some-unknown-model", "unknown")
    """
    # GGUF 패턴 먼저
    m = QUANT_PATTERN.search(model_name)
    if m:
        quant = m.group(1)
        base = model_name[:m.start()]
        return base, quant

    # MediaPipe 패턴
    m = MEDIAPIPE_QUANT_PATTERN.search(model_name)
    if m:
        quant = m.group(1)
        base = model_name[:m.start()]
        return base, quant

    return model_name, "unknown"
```

### 3.3 확장성

향후 다른 모델 베이스 추가 시:
- `extract_base_and_quant()`는 패턴 매칭 기반이므로 **모든 GGUF/MediaPipe 모델에 범용 적용**
- 새로운 양자화 포맷 등장 시 `QUANT_PATTERN`에 패턴 추가만 하면 됨
- API 쿼리에서 `GROUP BY base_name` 하면 자동으로 다른 모델 베이스도 분리

### 3.4 배치

`api/utils.py` 신규 파일에 배치. `scripts/response_validator.py`에서도 import하여 기존 `compute_all_quant_diffs()`의 하드코딩된 그룹핑을 대체.

## 4. API Endpoints

### 4.1 기존 엔드포인트 (RESPONSE_VALIDATION_ARCHITECTURE.md 정의)

```
GET /api/validation/quant-diff
```

이 엔드포인트는 RESPONSE_VALIDATION_ARCHITECTURE.md §9.2에 이미 정의됨. **응답 유사도(SequenceMatcher ratio)**에 집중하는 prompt-level diff 데이터를 반환.

### 4.2 신규 엔드포인트

```
GET /api/quant/comparison
    ?device=SM-S942U                      # optional: 디바이스 필터
    &base_model=gemma-4-E2B-it            # optional: 특정 모델 베이스만
    &run_id=...                           # optional: 특정 CI run
```

**핵심 엔드포인트.** 성능 + 품질 + 리소스를 통합한 양자화별 비교 데이터 반환.

내부 로직:
1. models 테이블에서 `extract_base_and_quant(model_name)` 적용
2. 같은 base_name을 가진 모델들을 그룹핑
3. 각 양자화 레벨별로:
   - 성능 집계: avg decode_tps, avg latency_ms, avg ttft_ms
   - 품질 집계: validation pass/fail/warn/uncertain 카운트 + pass_rate
   - 리소스 집계: avg battery_delta, avg thermal_end, avg system_pss_mb
4. **기준 양자화(가장 높은 정밀도, 즉 Q8_0)를 baseline으로** 상대 변화율 계산

```
GET /api/quant/similarity
    ?device=SM-S942U
    &base_model=gemma-4-E2B-it
```

prompt-level 유사도 매트릭스. `compute_all_quant_diffs()` 로직의 async 이식. 기존 `GET /api/validation/quant-diff`와의 차이: **같은 base model 내의 양자화 pair만** 필터링하고, 카테고리별 평균 유사도를 추가 집계.

### 4.3 엔드포인트 정리 (전체 목록)

| Endpoint | Source | 상태 | 역할 |
|----------|--------|------|------|
| `GET /api/validation/quant-diff` | RESPONSE_VALIDATION §9.2 | ❌ 미구현 | prompt-level 응답 유사도 (모든 모델 pair) |
| `GET /api/quant/comparison` | **이 문서** | ❌ 미구현 | 성능+품질+리소스 통합 비교 (base model 그룹핑) |
| `GET /api/quant/similarity` | **이 문서** | ❌ 미구현 | base model 내 양자화 pair 유사도 + 카테고리 집계 |

## 5. Response Schemas

### 5.1 QuantComparisonItem — 양자화 레벨별 통합 메트릭

```python
# api/schemas.py 추가

class QuantPerformance(BaseModel):
    avg_decode_tps: Optional[float] = None
    avg_latency_ms: Optional[float] = None
    avg_ttft_ms: Optional[float] = None
    avg_prefill_tps: Optional[float] = None
    avg_output_tokens: Optional[float] = None


class QuantQuality(BaseModel):
    total: int
    pass_count: int
    fail_count: int
    warn_count: int
    uncertain_count: int
    pass_rate: float                       # pass / (total - skip)


class QuantResource(BaseModel):
    avg_battery_delta: Optional[float] = None      # % (음수 = 소비)
    avg_thermal_end_celsius: Optional[float] = None
    avg_thermal_delta_celsius: Optional[float] = None
    avg_system_pss_mb: Optional[float] = None


class QuantComparisonItem(BaseModel):
    """단일 양자화 레벨의 통합 메트릭."""
    model_name: str                        # 전체 모델명 (gemma-4-E2B-it-Q4_K_M.gguf)
    quant_level: str                       # 추출된 양자화 (Q4_K_M)
    result_count: int                      # 이 양자화의 결과 수
    performance: QuantPerformance
    quality: QuantQuality
    resource: QuantResource


class QuantBaseline(BaseModel):
    """기준 양자화 대비 상대 변화율 (%)."""
    baseline_quant: str                    # 기준이 된 양자화 (Q8_0)
    tps_change_pct: Optional[float] = None       # 양수 = 빨라짐
    latency_change_pct: Optional[float] = None   # 음수 = 빨라짐
    pass_rate_change_pct: Optional[float] = None # 음수 = 품질 하락
    battery_change_pct: Optional[float] = None   # 음수 = 절약


class QuantComparisonGroup(BaseModel):
    """하나의 모델 베이스에 대한 전체 양자화 비교."""
    base_model: str                        # gemma-4-E2B-it
    device: Optional[str] = None
    quants: list[QuantComparisonItem]
    deltas: list[QuantBaseline]            # 각 quant의 baseline 대비 변화율
    insight: str                           # 자동 생성된 한줄 인사이트


class QuantComparisonResponse(BaseModel):
    """GET /api/quant/comparison 응답 최상위."""
    groups: list[QuantComparisonGroup]
```

### 5.2 QuantSimilarityItem — 응답 유사도

```python
class QuantSimilarityItem(BaseModel):
    """prompt-level 양자화 간 응답 유사도."""
    prompt_id: str
    prompt_text: str                       # 80자 truncate
    category: str
    model_a: str                           # 전체 모델명
    model_b: str
    quant_a: str                           # 추출된 양자화 레벨
    quant_b: str
    match_ratio: float                     # 0.0 ~ 1.0
    a_length: int                          # 응답 길이 (chars)
    b_length: int
    validation_a: Optional[str] = None     # pass/fail/warn/uncertain
    validation_b: Optional[str] = None


class QuantSimilaritySummary(BaseModel):
    """카테고리별 평균 유사도."""
    category: str
    avg_match_ratio: float
    pair_count: int


class QuantSimilarityResponse(BaseModel):
    """GET /api/quant/similarity 응답."""
    base_model: str
    pairs: list[QuantSimilarityItem]
    by_category: list[QuantSimilaritySummary]
    overall_avg_ratio: float
```

### 5.3 QuantDiffItem 업데이트 (기존 스키마 확장)

기존 RESPONSE_VALIDATION에 정의된 `QuantDiffItem`에 `category` 필드만 추가:

```python
class QuantDiffItem(BaseModel):
    prompt_id: str
    prompt_text: str
    category: str                          # ✨ 추가 — 카테고리별 필터/집계용
    model_a: str
    model_b: str
    match_ratio: float
    a_length: int
    b_length: int
```

## 6. Insight 자동 생성 로직

### 6.1 의사결정 시나리오

on-device LLM 배포에서 양자화 선택은 **trade-off 분석**이다:
- 낮은 양자화 (Q3) → 모델 작음, 메모리 적음, 배터리 절약 → 품질 하락 리스크
- 높은 양자화 (Q8) → 품질 우수 → 느림, 메모리 많음, 배터리 많이 씀

**"Q3까지 낮춰도 품질 저하 X% 이내, 속도는 Y% 향상, 배터리는 Z% 절약"** 형태의 인사이트를 자동 생성한다.

### 6.2 생성 규칙

```python
def generate_insight(quants: list[QuantComparisonItem], deltas: list[QuantBaseline]) -> str:
    """양자화 비교 결과에서 한줄 인사이트 생성.

    규칙:
    1. baseline(최고 양자화) 대비 가장 효율적인 양자화를 추천
    2. "효율적" = pass_rate 하락 5% 이내 + TPS 향상 or 배터리 절약
    3. 모든 양자화가 5%+ 하락 → 최고 양자화 유지 추천
    4. 실측 데이터가 부족하면 (result_count < 10) → "데이터 부족" 표시
    """
```

예시 출력:
```
"Q4_K_M 추천: Q8_0 대비 품질 -5.6%, 속도 +3.0%, 배터리 -25.0% — 최적 trade-off"
"Q3_K_M 주의: Q8_0 대비 품질 -16.7% 하락. Q4_K_M이 더 안전한 선택"
"데이터 부족: 양자화당 10개 이상의 결과가 필요합니다 (현재 Q3_K_M: 5개)"
```

### 6.3 Baseline 선택 로직

```python
def select_baseline(quants: list[QuantComparisonItem]) -> QuantComparisonItem:
    """가장 높은 정밀도의 양자화를 baseline으로 선택.

    우선순위: F32 > F16 > BF16 > Q8_0 > Q6_K > Q5_K_M > Q5_K_S > Q4_K_M > Q4_K_S > Q3_K_M > ...
    """
    QUANT_RANK = {
        "F32": 100, "F16": 90, "BF16": 85,
        "Q8_0": 80,
        "Q6_K": 70,
        "Q5_K_M": 65, "Q5_K_S": 63,
        "Q4_K_M": 55, "Q4_K_S": 53, "Q4_0": 50,
        "Q3_K_M": 45, "Q3_K_S": 43, "Q3_K_L": 44,
        "Q2_K": 30,
        "IQ4_NL": 54, "IQ4_XS": 52,
        "IQ3_M": 42, "IQ3_XXS": 40,
        "IQ2_XXS": 25, "IQ2_XS": 26,
        "IQ1_S": 10,
        # MediaPipe
        "int8": 80, "int4": 50, "fp16": 90, "fp32": 100,
    }
    return max(quants, key=lambda q: QUANT_RANK.get(q.quant_level.upper(), 0))
```

## 7. API 구현 상세

### 7.1 GET /api/quant/comparison

```python
# api/main.py 추가

@app.get("/api/quant/comparison", response_model=ApiSuccess[QuantComparisonResponse])
async def get_quant_comparison(
    request: Request,
    device: Optional[str] = Query(None),
    base_model: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
):
    data = await compute_quant_comparison(
        _db(request), device=device, base_model=base_model, run_id=run_id,
    )
    return ApiSuccess(data=data)
```

### 7.2 핵심 쿼리 — 양자화별 통합 집계

```sql
-- Step 1: 양자화별 성능+리소스 집계
SELECT
    m.model_name,
    COUNT(*)                                        AS result_count,
    AVG(r.decode_tps)                               AS avg_decode_tps,
    AVG(r.latency_ms)                               AS avg_latency_ms,
    AVG(r.ttft_ms)                                  AS avg_ttft_ms,
    AVG(r.prefill_tps)                              AS avg_prefill_tps,
    AVG(r.output_token_count)                       AS avg_output_tokens,
    -- 리소스
    AVG(r.battery_level_end - r.battery_level_start)  AS avg_battery_delta,
    AVG(r.thermal_end / 10.0)                         AS avg_thermal_end_celsius,
    AVG((r.thermal_end - r.thermal_start) / 10.0)     AS avg_thermal_delta_celsius,
    AVG(r.system_pss_mb)                              AS avg_system_pss_mb,
    -- 품질
    SUM(CASE WHEN r.validation_status = 'pass'      THEN 1 ELSE 0 END) AS v_pass,
    SUM(CASE WHEN r.validation_status = 'fail'      THEN 1 ELSE 0 END) AS v_fail,
    SUM(CASE WHEN r.validation_status = 'warn'      THEN 1 ELSE 0 END) AS v_warn,
    SUM(CASE WHEN r.validation_status = 'uncertain' THEN 1 ELSE 0 END) AS v_uncertain,
    SUM(CASE WHEN r.validation_status = 'skip'      THEN 1 ELSE 0 END) AS v_skip
FROM results r
JOIN models  m ON r.model_id  = m.id
JOIN devices d ON r.device_id = d.id
WHERE r.status = 'success'
GROUP BY m.model_name
```

Python 레이어에서 `extract_base_and_quant()`로 base name을 추출한 뒤, `itertools.groupby`로 그룹핑:

```python
from itertools import groupby
from operator import itemgetter

async def compute_quant_comparison(
    db: aiosqlite.Connection,
    device: Optional[str] = None,
    base_model: Optional[str] = None,
    run_id: Optional[str] = None,
) -> QuantComparisonResponse:
    rows = await db.execute_fetchall(SQL_QUANT_AGG, params)  # 위 SQL

    # 1) base_name, quant_level 태깅
    tagged = []
    for row in rows:
        base, quant = extract_base_and_quant(row["model_name"])
        if quant == "unknown":
            continue
        if base_model and base != base_model:
            continue
        tagged.append({"base": base, "quant": quant, **dict(row)})

    # 2) itertools.groupby로 base_model별 그룹핑
    tagged.sort(key=itemgetter("base"))
    groups = []
    for base, items in groupby(tagged, key=itemgetter("base")):
        quant_items = list(items)
        if len(quant_items) < 2:
            continue  # 비교 대상이 1개뿐이면 스킵

        quants = [_build_quant_item(q) for q in quant_items]
        baseline = select_baseline(quants)
        deltas = [_compute_delta(q, baseline) for q in quants
                  if q.quant_level != baseline.quant_level]
        insight = generate_insight(quants, deltas)

        groups.append(QuantComparisonGroup(
            base_model=base,
            device=device,
            quants=quants,
            deltas=deltas,
            insight=insight,
        ))

    return QuantComparisonResponse(groups=groups)
```

**`itertools.groupby` 선택 이유**: Pandas는 추가 pip 의존성이므로 배제. `groupby`는 표준 라이브러리이고, SQL에서 이미 `GROUP BY model_name`으로 행 수가 양자화 레벨 수(3~5개)로 축소되어 있어 성능 충분. `sorted` + `groupby`는 `defaultdict(list)` 수동 그룹핑보다 의도가 명확하고, 중첩 루프를 피할 수 있다.

### 7.3 GET /api/validation/quant-diff 구현

기존 `compute_all_quant_diffs()` 로직을 async로 이식:

```python
# api/stats.py 추가

async def compute_quant_diff(
    db: aiosqlite.Connection,
    device: Optional[str] = None,
    base_model: Optional[str] = None,
) -> list["QuantDiffItem"]:
    """prompt-level 양자화 간 응답 유사도 계산.

    scripts/response_validator.py의 compute_all_quant_diffs()를
    async + base_model 필터링 + category 추가하여 이식.
    """
    from utils import extract_base_and_quant

    where_parts = ["r.status = 'success'", "r.response != ''"]
    params = []
    if device:
        where_parts.append("d.model = ?")
        params.append(device)

    where = "WHERE " + " AND ".join(where_parts)

    q = f"""
        SELECT p.prompt_id, p.prompt_text, p.category,
               m.model_name, r.response, r.validation_status
        FROM results r
        JOIN prompts p ON r.prompt_id = p.id
        JOIN models  m ON r.model_id  = m.id
        JOIN devices d ON r.device_id = d.id
        {where}
        ORDER BY p.prompt_id, m.model_name
    """
    rows = await db.execute_fetchall(q, params)

    # Group by (prompt_id, base_model)
    groups = {}
    for row in rows:
        base, quant = extract_base_and_quant(row["model_name"])
        if base_model and base != base_model:
            continue
        key = (row["prompt_id"], base)
        if key not in groups:
            groups[key] = []
        groups[key].append(row)

    # Compute pairwise similarity
    diffs = []
    for (pid, _base), entries in groups.items():
        if len(entries) < 2:
            continue
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                a, b = entries[i], entries[j]
                a_norm = re.sub(r'\s+', ' ', a["response"].lower().strip())
                b_norm = re.sub(r'\s+', ' ', b["response"].lower().strip())
                ratio = SequenceMatcher(None, a_norm.split(), b_norm.split()).ratio()
                a_base, a_quant = extract_base_and_quant(a["model_name"])
                b_base, b_quant = extract_base_and_quant(b["model_name"])
                diffs.append(QuantDiffItem(
                    prompt_id=pid,
                    prompt_text=a["prompt_text"][:80],
                    category=a["category"],
                    model_a=a["model_name"],
                    model_b=b["model_name"],
                    match_ratio=round(ratio, 3),
                    a_length=len(a["response"]),
                    b_length=len(b["response"]),
                ))
    return diffs
```

### 7.4 GET /api/quant/similarity 구현

`/api/validation/quant-diff`의 결과를 가공하여 카테고리별 집계 + overall 평균을 추가:

```python
async def compute_quant_similarity(
    db: aiosqlite.Connection,
    device: Optional[str] = None,
    base_model: Optional[str] = None,
) -> "QuantSimilarityResponse":
    diffs = await compute_quant_diff(db, device=device, base_model=base_model)

    # Category averages
    cat_map = {}
    for d in diffs:
        cat = d.category
        if cat not in cat_map:
            cat_map[cat] = {"total": 0.0, "count": 0}
        cat_map[cat]["total"] += d.match_ratio
        cat_map[cat]["count"] += 1

    by_category = [
        QuantSimilaritySummary(
            category=cat,
            avg_match_ratio=round(v["total"] / v["count"], 3),
            pair_count=v["count"],
        )
        for cat, v in sorted(cat_map.items())
    ]

    overall = round(sum(d.match_ratio for d in diffs) / len(diffs), 3) if diffs else 0.0

    # QuantDiffItem → QuantSimilarityItem 변환 (quant_a/b, validation_a/b 추가)
    similarity_items = []
    for d in diffs:
        _, qa = extract_base_and_quant(d.model_a)
        _, qb = extract_base_and_quant(d.model_b)
        similarity_items.append(QuantSimilarityItem(
            prompt_id=d.prompt_id,
            prompt_text=d.prompt_text,
            category=d.category,
            model_a=d.model_a,
            model_b=d.model_b,
            quant_a=qa,
            quant_b=qb,
            match_ratio=d.match_ratio,
            a_length=d.a_length,
            b_length=d.b_length,
        ))

    return QuantSimilarityResponse(
        base_model=base_model or "all",
        pairs=similarity_items,
        by_category=by_category,
        overall_avg_ratio=overall,
    )
```

## 8. Dashboard — Quant Compare 페이지

### 8.1 Sidebar 통합

```typescript
// Sidebar.tsx NAV_ITEMS에 추가
{ to: '/quant-compare', label: 'Quant Compare', icon: FlaskConical },
```

위치: `Resource`와 `Validation` 사이. 양자화 비교는 성능과 품질의 교차 영역이므로 이 위치가 자연스럽다.

```
Overview
Performance
Compare
Device Compare
Resource
Quant Compare     ← ✨ NEW
Validation
Responses
Raw Data
Run History
```

### 8.2 페이지 레이아웃

```
┌─────────────────────────────────────────────────────────────────┐
│  Header: "Quant Compare"                                         │
│  Subtitle: "Quantization trade-off analysis"                     │
│  [Device ▼] [Model Base ▼] [Refresh ↻]                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │ 📊 Insight   │  │ 📊 Insight   │  │ 📊 Insight   │           │
│  │ "Q4_K_M is   │  │ "Q3 quality  │  │ "Q8 draws    │           │
│  │  the sweet   │  │  drops 17%"  │  │  2x battery" │           │
│  │  spot"       │  │              │  │              │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│                                                                   │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │  Quantization Comparison Table                             │   │
│  │                                                            │   │
│  │  Quant   │ Decode TPS │ Latency │ Pass Rate │ Battery │ …  │   │
│  │  ────────┼────────────┼─────────┼───────────┼─────────┼──  │   │
│  │  Q8_0    │ 16.7       │ 24,208  │ 72.0%     │ -0.32%  │    │   │
│  │  Q4_K_M  │ 17.2 ↑3%  │ 26,254  │ 64.0% ↓8% │ -0.24%  │    │   │
│  │  Q3_K_M  │ 13.2 ↓21% │ 26,170  │ 60.0% ↓12%│ -0.16%  │    │   │
│  │                                                            │   │
│  │  ※ baseline: Q8_0 (가장 높은 정밀도)                       │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────┐  ┌──────────────────────────────┐   │
│  │  Trade-off Radar Chart  │  │  Response Similarity Matrix   │   │
│  │                         │  │                               │   │
│  │     Quality             │  │       Q3   Q4   Q8            │   │
│  │      ╱    ╲             │  │  Q3   --  0.72  0.68          │   │
│  │  Speed ── Power         │  │  Q4  0.72  --   0.81          │   │
│  │                         │  │  Q8  0.68  0.81  --           │   │
│  │  ● Q3  ● Q4  ● Q8      │  │                               │   │
│  └────────────────────────┘  └──────────────────────────────┘   │
│                                                                   │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │  Category Similarity Breakdown                             │   │
│  │                                                            │   │
│  │  카테고리별 양자화 pair 평균 유사도 바 차트                   │   │
│  │  (math: 0.85, code: 0.62, creative: 0.45, ...)            │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 8.3 컴포넌트 구조

```
dashboard/src/
├── pages/
│   └── QuantCompare.tsx                    # ✨ NEW — 페이지 진입점
├── hooks/
│   └── useQuantCompare.ts                  # ✨ NEW — API 훅
├── types/
│   └── index.ts                            # ✨ UPDATE — Quant* 타입 추가
└── components/
    └── quant/                              # ✨ NEW
        ├── InsightCards.tsx                 # 자동 인사이트 카드 3개
        ├── ComparisonTable.tsx             # 통합 비교 테이블 (baseline 대비 delta 표시)
        ├── TradeoffRadar.tsx               # Recharts RadarChart (Quality/Speed/Power 축)
        ├── SimilarityMatrix.tsx            # 양자화 pair 유사도 히트맵
        └── CategorySimilarity.tsx          # 카테고리별 유사도 바 차트
```

### 8.4 useQuantCompare 훅 설계

두 API(`/api/quant/comparison`, `/api/quant/similarity`)를 병렬 호출하되, `base_model` 파라미터가 변경될 때만 refetch한다. 불필요한 네트워크 호출을 방지하기 위한 의존성 설계가 핵심.

```typescript
// hooks/useQuantCompare.ts

interface UseQuantCompareParams {
  device?: string
  baseModel?: string
}

interface UseQuantCompareResult {
  comparison: QuantComparisonResponse | null
  similarity: QuantSimilarityResponse | null
  loading: boolean
  error: string | null
  refresh: () => void
}

export function useQuantCompare({ device, baseModel }: UseQuantCompareParams): UseQuantCompareResult {
  const [comparison, setComparison] = useState<QuantComparisonResponse | null>(null)
  const [similarity, setSimilarity] = useState<QuantSimilarityResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // fetchKey가 바뀔 때만 refetch — device/baseModel 변경 감지
  const fetchKey = useMemo(() => `${device ?? ''}|${baseModel ?? ''}`, [device, baseModel])

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (device) params.set('device', device)
      if (baseModel) params.set('base_model', baseModel)
      const qs = params.toString()

      // 두 API 병렬 호출 — 하나가 실패해도 다른 하나는 표시
      const [compRes, simRes] = await Promise.allSettled([
        apiClient.get<ApiSuccess<QuantComparisonResponse>>(`/api/quant/comparison?${qs}`),
        apiClient.get<ApiSuccess<QuantSimilarityResponse>>(`/api/quant/similarity?${qs}`),
      ])

      if (compRes.status === 'fulfilled') setComparison(compRes.value.data.data)
      if (simRes.status === 'fulfilled') setSimilarity(simRes.value.data.data)

      // 둘 다 실패한 경우만 에러
      if (compRes.status === 'rejected' && simRes.status === 'rejected') {
        setError(compRes.reason?.message ?? 'Failed to load data')
      }
    } catch (e: any) {
      setError(e.message ?? 'Unknown error')
    } finally {
      setLoading(false)
    }
  }, [fetchKey])  // fetchKey 변경 시에만 새로운 함수 생성

  useEffect(() => { fetchData() }, [fetchData])

  return { comparison, similarity, loading, error, refresh: fetchData }
}
```

**설계 포인트:**
- `useMemo`로 `fetchKey`를 구성하여 `device`/`baseModel` 조합이 동일하면 refetch 방지
- `Promise.allSettled`로 병렬 호출 — comparison과 similarity는 독립적이므로 하나가 실패해도 다른 하나는 정상 렌더링
- `useCallback` + `fetchKey` 의존성으로 `useEffect` 재실행 최소화
- 프로젝트 기존 패턴(`useResults`, `useValidation`)과 동일한 `{ data, loading, error, refresh }` 인터페이스 유지

### 8.5 TypeScript 타입 추가

```typescript
// dashboard/src/types/index.ts 추가

// ── Quant Compare ───────────────────────────────────────────────

export interface QuantPerformance {
  avg_decode_tps: number | null
  avg_latency_ms: number | null
  avg_ttft_ms: number | null
  avg_prefill_tps: number | null
  avg_output_tokens: number | null
}

export interface QuantQuality {
  total: number
  pass_count: number
  fail_count: number
  warn_count: number
  uncertain_count: number
  pass_rate: number
}

export interface QuantResource {
  avg_battery_delta: number | null
  avg_thermal_end_celsius: number | null
  avg_thermal_delta_celsius: number | null
  avg_system_pss_mb: number | null
}

export interface QuantComparisonItem {
  model_name: string
  quant_level: string
  result_count: number
  performance: QuantPerformance
  quality: QuantQuality
  resource: QuantResource
}

export interface QuantBaseline {
  baseline_quant: string
  tps_change_pct: number | null
  latency_change_pct: number | null
  pass_rate_change_pct: number | null
  battery_change_pct: number | null
}

export interface QuantComparisonGroup {
  base_model: string
  device: string | null
  quants: QuantComparisonItem[]
  deltas: QuantBaseline[]
  insight: string
}

export interface QuantComparisonResponse {
  groups: QuantComparisonGroup[]
}

export interface QuantSimilarityItem {
  prompt_id: string
  prompt_text: string
  category: string
  model_a: string
  model_b: string
  quant_a: string
  quant_b: string
  match_ratio: number
  a_length: number
  b_length: number
  validation_a: string | null
  validation_b: string | null
}

export interface QuantSimilaritySummary {
  category: string
  avg_match_ratio: number
  pair_count: number
}

export interface QuantSimilarityResponse {
  base_model: string
  pairs: QuantSimilarityItem[]
  by_category: QuantSimilaritySummary[]
  overall_avg_ratio: number
}
```

### 8.6 Comparison Table UX 상세

테이블의 핵심은 **baseline 대비 delta를 시각적으로 표시**하는 것:

| 규칙 | 표시 |
|------|------|
| baseline (Q8_0) | 값만 표시, 배경 회색 |
| delta 양수이고 좋은 방향 (TPS ↑, Battery 절약 ↑) | 초록 텍스트 `↑ +3.0%` |
| delta 음수이고 좋은 방향 (Latency ↓) | 초록 텍스트 `↓ -5.2%` |
| delta 나쁜 방향 (Pass rate ↓, TPS ↓) | 빨간 텍스트 `↓ -16.7%` |
| delta 5% 이내 | 회색 텍스트 (무의미한 차이) |

### 8.7 Trade-off Radar Chart

3축 Radar (Recharts `RadarChart`):
- **Quality**: pass_rate (0~1 → 0~100)
- **Speed**: decode_tps를 그룹 내 최고값 대비 정규화 (0~100)
- **Efficiency**: battery_delta 역수 정규화 (소비 적을수록 높음, 0~100)

각 양자화가 별도 Radar polygon으로 겹쳐서 표시. "Q4_K_M이 삼각형이 가장 균형적"처럼 시각적으로 trade-off 확인 가능.

### 8.8 Similarity Matrix

N×N 히트맵 (N = 양자화 수). 현재 3개이면 3×3. 셀 색상:
- 0.8+ : 진한 초록 (거의 동일)
- 0.6~0.8 : 연한 초록 (유사)
- 0.4~0.6 : 노란색 (상이)
- <0.4 : 빨간색 (크게 다름)

## 9. Error Handling

| 상황 | 처리 |
|------|------|
| 같은 base model의 양자화가 1개뿐 | `groups` 배열에서 제외, 비교 불가 메시지 |
| validation_status가 전부 NULL | quality 섹션에 "Validation 미실행" 표시, 성능/리소스만 비교 |
| profiling 데이터 없음 (Phase 6 이전 데이터) | resource 섹션에 "프로파일링 데이터 없음" 표시 |
| base model 추출 실패 (unknown) | 해당 모델은 그룹핑에서 제외 |
| SequenceMatcher 빈 응답 | ratio = 0.0, 정상 처리 |
| 결과 0건 | EmptyState 컴포넌트 표시 ("벤치마크 실행 후 양자화 비교가 가능합니다") |

## 10. Directory Structure (변경사항)

```
on-device-llm-tester/
├── api/
│   ├── main.py                          # ✨ UPDATE — /api/quant/* + /api/validation/quant-diff 추가
│   ├── schemas.py                       # ✨ UPDATE — Quant* 스키마 추가
│   ├── stats.py                         # ✨ UPDATE — compute_quant_comparison, compute_quant_diff 추가
│   ├── utils.py                         # ✨ NEW — extract_base_and_quant()
│   ├── db.py                            # ✅ 변경 없음
│   ├── loader.py                        # ✅ 변경 없음
│   └── requirements.txt                 # ✅ 변경 없음 (추가 의존성 없음!)
│
├── scripts/
│   └── response_validator.py            # ✨ UPDATE — extract_base_and_quant() import로 교체
│
├── dashboard/src/
│   ├── App.tsx                          # ✨ UPDATE — /quant-compare 라우트 추가
│   ├── pages/
│   │   └── QuantCompare.tsx             # ✨ NEW
│   ├── hooks/
│   │   └── useQuantCompare.ts           # ✨ NEW
│   ├── types/
│   │   └── index.ts                     # ✨ UPDATE — Quant* 타입 추가
│   └── components/
│       ├── layout/
│       │   └── Sidebar.tsx              # ✨ UPDATE — Quant Compare 메뉴 추가
│       └── quant/                       # ✨ NEW
│           ├── InsightCards.tsx
│           ├── ComparisonTable.tsx
│           ├── TradeoffRadar.tsx
│           ├── SimilarityMatrix.tsx
│           └── CategorySimilarity.tsx
│
├── data/
│   └── llm_tester.db                   # ✅ 유지 — 스키마 변경 없음
│
├── QUANT_COMPARISON_ARCHITECTURE.md     # ✨ NEW — 이 문서
└── RESPONSE_VALIDATION_ARCHITECTURE.md  # ✅ 보존 — quant-diff 엔드포인트 원본 정의
```

## 11. Implementation Order

```
Step 1: api/utils.py — extract_base_and_quant()
        → QUANT_PATTERN + MEDIAPIPE_QUANT_PATTERN 정규식
        → select_baseline() + generate_insight() 유틸리티
        → 단위 테스트: 다양한 모델명 패턴에 대한 추출 검증
        → 검증: "gemma-4-E2B-it-Q3_K_M.gguf" → ("gemma-4-E2B-it", "Q3_K_M")

Step 2: scripts/response_validator.py 리팩터링
        → 기존 compute_all_quant_diffs()에서 하드코딩된 그룹핑을
          extract_base_and_quant() 호출로 교체
        → 기존 --quant-diff CLI 출력 동작 유지 확인
        → 기능 변경 없음, import 교체만

Step 3: API — GET /api/validation/quant-diff
        → api/stats.py에 compute_quant_diff() async 이식
        → api/main.py에 엔드포인트 등록
        → api/schemas.py에 QuantDiffItem(category 추가) 확정
        → Swagger 테스트

Step 4: API — GET /api/quant/comparison
        → api/stats.py에 compute_quant_comparison() 구현
        → 통합 SQL 집계 + extract_base_and_quant() 그룹핑
        → baseline delta 계산 + insight 생성
        → api/schemas.py에 Quant* 스키마 전부 추가
        → Swagger 테스트

Step 5: API — GET /api/quant/similarity
        → compute_quant_similarity() 구현 (compute_quant_diff 재사용)
        → 카테고리별 집계 + overall 평균
        → Swagger 테스트

Step 6: Dashboard — QuantCompare 페이지 기본 구조
        → App.tsx 라우트 추가
        → Sidebar.tsx 메뉴 추가 (FlaskConical 아이콘)
        → QuantCompare.tsx 페이지 프레임
        → useQuantCompare.ts 훅 (comparison + similarity 두 API 호출)
        → types/index.ts 타입 추가

Step 7: Dashboard — 컴포넌트 구현
        → InsightCards.tsx (insight 문자열 렌더링)
        → ComparisonTable.tsx (baseline delta 색상 표시)
        → TradeoffRadar.tsx (Recharts RadarChart)
        → SimilarityMatrix.tsx (N×N 히트맵)
        → CategorySimilarity.tsx (바 차트)

Step 8: Dashboard — Validation 페이지 연동
        → 기존 Validation 페이지의 QuantDiff 섹션이
          GET /api/validation/quant-diff를 호출하도록 연결
        → 이 섹션은 "전체 모델 pair" 유사도 (Quant Compare는 "같은 base model" 필터링)

Step 9: 문서 + 정리
        → README.md에 Quant Compare 섹션 추가
        → Sidebar 버전 v6.1.0 · quant compare
```

## 12. Extension Points

```
향후 확장 (필요 시):
  └─→ 자동 추천 강화: 모델 크기(파일 사이즈), 로딩 시간까지 포함한 종합 추천
  └─→ 카테고리별 양자화 추천: "math는 Q4 이상 필요, creative는 Q3도 OK"
  └─→ Cross-device 양자화 비교: 같은 모델·같은 양자화를 디바이스 간 비교
  └─→ Regression 알림: 새 run에서 양자화 간 pass_rate 차이가 확대되면 알림
  └─→ Export: 양자화 비교 결과를 PDF/CSV로 다운로드 (보고서 자동 생성)
  └─→ Phase 4b 연동: LLM judge 점수가 추가되면 quality 축에 quality_score 반영
```

## 13. Tech Stack (추가분)

| Layer | Tech | Why |
|-------|------|-----|
| **Base Name 추출** | Python `re` | 표준 라이브러리, 의존성 zero |
| **응답 유사도** | Python `difflib.SequenceMatcher` | 기존 로직 재사용, 의존성 zero |
| **Radar Chart** | Recharts `RadarChart` | 이미 dashboard 의존성에 포함 |
| **Heatmap** | Recharts `ScatterChart` or CSS Grid + inline style | 별도 라이브러리 불필요 |

※ **추가 pip/npm 의존성 없음.** 기존 스택으로 전부 구현 가능.

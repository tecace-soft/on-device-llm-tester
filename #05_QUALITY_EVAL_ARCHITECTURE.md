# On-Device LLM Tester — Phase 4: Quality Eval Architecture

## 1. High-Level Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    QUALITY EVAL PIPELINE (Phase 4)                        │
│                                                                          │
│  test_config.json (✨ UPDATED)                                           │
│    └─ ground_truth 필드 추가 (프롬프트별 정답/평가 기준)                    │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  기존 파이프라인 (변경 없음)                                       │    │
│  │  runner.py → sync_results.py → ingest.py → data/llm_tester.db   │    │
│  └──────────────────────────────┬───────────────────────────────────┘    │
│                                 │                                        │
│                                 ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  quality_eval.py (✨ NEW)                                         │    │
│  │                                                                   │    │
│  │  Step 1: DB에서 quality_score IS NULL인 results 조회               │    │
│  │                                                                   │    │
│  │  Step 2: 카테고리별 평가 전략 분기                                  │    │
│  │    ├─ math / factoid → Deterministic Eval (EM + 정규식)           │    │
│  │    └─ reasoning / long_context / general → LLM-as-a-Judge        │    │
│  │                                                                   │    │
│  │  Step 3: LLM Judge API 호출 (Claude Sonnet 기본, GPT-4o 대체)     │    │
│  │    ├─ 카테고리별 rubric 프롬프트 적용                               │    │
│  │    ├─ Binary scoring (0/1 per criterion) → weighted aggregate     │    │
│  │    └─ Hallucination claim-level feedback 수집                     │    │
│  │                                                                   │    │
│  │  Step 4: DB UPDATE (quality_score, quality_verdict, quality_feedback)│  │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌──────────────────────────────┐    ┌──────────────────────────────┐    │
│  │  SQLite DB (기존)             │    │  Dashboard                    │    │
│  │  data/llm_tester.db          │    │  :5173 + :8000               │    │
│  │                               │    │                               │    │
│  │  results 테이블:              │    │  Responses 페이지 점수 표시    │    │
│  │   + quality_score     REAL   │    │  Overview KPI 추가            │    │
│  │   + quality_verdict   TEXT   │    │  Quality 페이지 (✨ NEW)      │    │
│  │   + quality_feedback  TEXT   │    │                               │    │
│  │                               │    │                               │    │
│  │  eval_configs 테이블 (✨ NEW)│    │                               │    │
│  │   → 프롬프트별 ground_truth  │    │                               │    │
│  │   → eval_strategy 매핑       │    │                               │    │
│  └──────────────────────────────┘    └──────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

## 2. Why This Architecture

### 하이브리드 평가 (EM + LLM Judge) — 왜 이 조합인가?
- **math/factoid은 정답이 결정적**: "237 + 485 = ?" 의 정답은 `722`. LLM judge를 호출하면 API 비용만 낭비. Exact Match + 정규식 파싱이 더 정확하고 무료
- **reasoning/long_context는 open-ended**: "Explain special relativity" 의 정답은 하나가 아님. 핵심 개념 포함 여부 + hallucination 체크에는 LLM judge가 필수
- **ROUGE/BLEU/BERTScore를 뺀 이유**: SLM(1B~1.5B)은 응답 길이와 표현이 불안정. "Beijing"과 "The capital was Beijing, also known as Peking"을 ROUGE-L은 전혀 다른 점수로 매김. BERTScore는 의미적으로 낫지만 sentence-transformers 모델 로드가 CI 환경에서 무거움. LLM judge가 이 둘이 잡는 영역을 더 정확하게 커버
- **업계 트렌드**: ROUGE/BLEU는 번역/요약 벤치마크 논문에서나 쓰이고, 프로덕션 eval 파이프라인은 LLM-as-a-Judge로 수렴 중

### Claude Sonnet 기본 + GPT-4o 대체 — 왜 이 구조인가?
- **환경변수 하나로 전환**: `JUDGE_PROVIDER=anthropic|openai`. 둘 다 OpenAI-compatible 아닌 네이티브 SDK 사용
- **Claude Sonnet 우선 이유**: Anthropic API가 이미 사내 인프라에 있을 가능성 높음. 비용도 GPT-4o와 유사
- **GPT-4o 대체 이유**: Judge 모델 다양성 확보. Claude가 Claude 응답을 평가하는 self-preference 회피 가능

### Binary Scoring (0/1) — 왜 Likert 스케일이 아닌가?
- **1-5 스케일의 문제**: LLM judge는 3에 몰리는 central tendency bias가 있음. 점수 6이랑 7의 차이를 일관성 있게 매기기 어려움
- **Binary의 장점**: 재현성 높음. "맞다/틀리다"는 명확. 가중합으로 최종 0.0~1.0 스코어 산출
- **해상도 걱정**: 기준 4개 × binary = 16단계 (0.0, 0.1, 0.2, ..., 1.0). SLM 벤치마크에 충분

### quality_eval.py를 독립 스크립트로 — 왜 API 엔드포인트가 아닌가?
- **CI 파이프라인 호환**: `ingest.py` 다음 step으로 `quality_eval.py` 추가하면 끝. API 서버 실행 불필요
- **배치 처리에 적합**: 전체 미평가 결과를 한 번에 처리. API 요청-응답 패턴보다 효율적
- **재실행 안전**: `quality_score IS NULL` 조건으로 미평가분만 처리. 멱등성 보장

## 3. Evaluation Methodology

### 3.1 카테고리별 평가 전략 매핑

| category | eval_strategy | ground_truth 형태 | API 호출 | 비용/eval |
|----------|--------------|-------------------|---------|----------|
| `math` | `deterministic` | 정확한 숫자값 (`"722"`, `"0.79"`) | 없음 | $0 |
| `factoid` | `deterministic_with_fallback` | 짧은 텍스트 (`"Beijing"`) | EM 실패 시만 | ~$0 |
| `reasoning` | `llm_judge` | 핵심 포인트 리스트 또는 모범 답안 | 항상 | ~$0.002 |
| `long_context` | `llm_judge` | 모범 답안 + 평가 기준 | 항상 | ~$0.003 |
| `creative` | `llm_judge` | 없음 (rubric만 사용) | 항상 | ~$0.002 |
| `code` | `deterministic_with_fallback` | 예상 출력 또는 핵심 패턴 | EM 실패 시만 | ~$0 |

### 3.2 Deterministic Eval (math / factoid)

```python
# scripts/evaluators/deterministic.py

import math
import re
from typing import Optional


def eval_math(response: str, ground_truth: str) -> tuple[float, str]:
    """수학 응답 평가. Returns (score, feedback)."""
    try:
        expected = float(ground_truth)
    except ValueError:
        return 0.0, f"Invalid ground_truth for math: {ground_truth}"

    # 응답에서 숫자 추출 (음수, 소수점 포함)
    numbers = re.findall(r'-?\d+\.?\d*', response)
    if not numbers:
        return 0.0, "No numeric value found in response"

    # 전략: 마지막 숫자가 최종 답인 경우가 대부분
    # "237 + 485 = 722" → [237, 485, 722] → 722 매칭
    # "The answer is approximately 722" → [722] → 매칭
    for num_str in reversed(numbers):
        num = float(num_str)
        if math.isclose(num, expected, rel_tol=1e-3, abs_tol=1e-9):
            return 1.0, f"Correct: {num_str} matches expected {ground_truth}"

    # 가장 가까운 숫자 리포트 (디버깅용)
    closest = min(numbers, key=lambda n: abs(float(n) - expected))
    return 0.0, f"Incorrect: closest value {closest}, expected {ground_truth}"


def eval_factoid(response: str, ground_truth: str) -> tuple[float, str, bool]:
    """Factoid 응답 평가. Returns (score, feedback, needs_llm_fallback)."""
    # 정규화: 소문자, 공백 정리, 관사 제거
    def normalize(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r'\b(the|a|an)\b', '', text)
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    norm_truth = normalize(ground_truth)
    norm_response = normalize(response)

    # 1. Exact match (정규화 후)
    if norm_truth == norm_response:
        return 1.0, f"Exact match: {ground_truth}", False

    # 2. Containment match: 정답이 응답에 포함
    if norm_truth in norm_response:
        return 1.0, f"Ground truth '{ground_truth}' found in response", False

    # 3. 응답이 정답에 포함 (응답이 더 짧은 경우)
    if norm_response in norm_truth and len(norm_response) > 2:
        return 0.8, f"Partial match: response '{response.strip()}' is subset of ground truth", False

    # 4. EM 실패 → LLM judge fallback 필요
    return 0.0, "No deterministic match found", True
```

**Deterministic Eval의 한계와 fallback**:
- math: SLM이 "약 720 정도" 같은 근사치를 답하면 tolerance로 잡을지 strict 0점 줄지 → `rel_tol=1e-3`으로 0.1% 오차 허용 (720 vs 722 = 0.28% → 허용)
- factoid: "Beijing"과 "Peking" 같은 동의어는 EM으로 안 잡힘 → `needs_llm_fallback=True` 반환 후 LLM judge로 재평가

### 3.3 LLM-as-a-Judge

#### 평가 기준 (Criteria)

| 기준 | 정의 | 가중치 |
|------|------|--------|
| **Correctness** | 응답이 ground truth와 의미적으로 일치하는가 | 0.4 |
| **Faithfulness** | 응답에 prompt/ground truth에 없는 사실을 지어내지 않았는가 (anti-hallucination) | 0.3 |
| **Relevance** | 질문에 대한 답변으로 적절한가 | 0.2 |
| **Completeness** | ground truth의 핵심 요소를 빠뜨리지 않았는가 | 0.1 |

```
quality_score = correctness × 0.4 + faithfulness × 0.3 + relevance × 0.2 + completeness × 0.1
```

#### Verdict 결정 로직

```
score >= 0.7 → "pass"
0.3 <= score < 0.7 → "partial"
score < 0.3 → "fail"
```

#### 카테고리별 Rubric 프롬프트

**reasoning / long_context / general**:
```
You are an expert evaluator for on-device Small Language Model (SLM) outputs.
The model being evaluated is a 1B-1.5B parameter model running on a mobile phone.
Evaluate with appropriate expectations for this model size.

[Question]: {prompt}
[Ground Truth]: {ground_truth}
[Model Response]: {response}

Score each criterion as 0 (fail) or 1 (pass):

1. Correctness: Does the response convey the same core meaning as the ground truth?
   - For SLMs, accept simplified but accurate explanations.
   - Minor omissions are acceptable if the main point is correct.

2. Faithfulness: Does the response contain ONLY verifiable facts?
   - Score 0 if the response includes any fabricated dates, names, statistics, or claims
     not supported by the question or ground truth.
   - If hallucination is detected, list each fabricated claim in your feedback.

3. Relevance: Does the response directly address the question asked?
   - Score 0 if the response is off-topic or answers a different question.

4. Completeness: Does the response cover the key points from the ground truth?
   - For SLMs, covering 60%+ of key points is sufficient for a score of 1.

IMPORTANT:
- Response length does NOT affect quality. A short correct answer scores higher than a long incorrect one.
- Evaluate the substance, not the style or verbosity.

Respond ONLY with this JSON (no markdown, no explanation outside JSON):
{
  "correctness": 0 or 1,
  "faithfulness": 0 or 1,
  "relevance": 0 or 1,
  "completeness": 0 or 1,
  "hallucinated_claims": ["claim1", "claim2"] or [],
  "feedback": "one sentence summary of evaluation"
}
```

**creative (ground_truth 없음)**:
```
You are an expert evaluator for on-device Small Language Model (SLM) outputs.

[Question]: {prompt}
[Model Response]: {response}

This is a creative/open-ended task. There is no ground truth.
Score each criterion as 0 (fail) or 1 (pass):

1. Correctness: Is the content factually accurate (if facts are involved)?
   - For purely creative tasks (jokes, stories), score based on coherence instead.

2. Faithfulness: Does the response avoid fabricating real-world facts?
   - Fictional elements in creative writing are acceptable.
   - Fabricating real dates, people, or events scores 0.

3. Relevance: Does the response address the creative prompt?

4. Completeness: Does the response feel complete, not cut off mid-sentence?

IMPORTANT:
- Response length does NOT affect quality.
- Evaluate substance, not style or verbosity.

Respond ONLY with this JSON (no markdown, no explanation outside JSON):
{
  "correctness": 0 or 1,
  "faithfulness": 0 or 1,
  "relevance": 0 or 1,
  "completeness": 0 or 1,
  "hallucinated_claims": ["claim1", "claim2"] or [],
  "feedback": "one sentence summary of evaluation"
}
```

**factoid (LLM fallback 시)**:
```
You are an expert evaluator for on-device Small Language Model (SLM) outputs.

[Question]: {prompt}
[Ground Truth]: {ground_truth}
[Model Response]: {response}

This is a factoid question with a known short answer.
The deterministic matcher could not confirm a match, so semantic evaluation is needed.

Score each criterion as 0 (fail) or 1 (pass):

1. Correctness: Does the response contain or imply the same answer as the ground truth?
   - Accept synonyms, alternative names, or transliterations.
   - e.g., "Beijing" and "Peking" are both correct for the same city.

2. Faithfulness: Does the response avoid adding fabricated facts beyond the answer?

3. Relevance: Does it answer the question asked?

4. Completeness: Does it provide the requested information?

IMPORTANT: Response length does NOT affect quality.

Respond ONLY with this JSON (no markdown, no explanation outside JSON):
{
  "correctness": 0 or 1,
  "faithfulness": 0 or 1,
  "relevance": 0 or 1,
  "completeness": 0 or 1,
  "hallucinated_claims": ["claim1", "claim2"] or [],
  "feedback": "one sentence summary of evaluation"
}
```

#### Judge Bias 완화 전략

| Bias | 설명 | 완화 방법 |
|------|------|----------|
| **Verbosity bias** | 긴 응답에 높은 점수를 주는 경향. SLM 응답은 짧으므로 불리 | 프롬프트에 "length does NOT affect quality" 명시 |
| **Position bias** | ground truth를 먼저 보여주면 점수가 올라감 | Ground truth → Response 순서 고정 (일관성 우선) |
| **Self-preference** | Claude judge가 Claude 스타일 응답에 후한 경향 | 평가 대상이 on-device SLM이므로 해당 없음. 필요 시 `JUDGE_PROVIDER` 전환 |
| **Central tendency** | 중간 점수로 모이는 경향 | Binary scoring (0/1)으로 원천 차단 |

## 4. Database Schema Changes

### 4.1 results 테이블 확장 (기존 설계 반영)

```sql
-- DB_MIGRATION_ARCHITECTURE.md §3.4에서 이미 예약된 컬럼
ALTER TABLE results ADD COLUMN quality_score    REAL;
ALTER TABLE results ADD COLUMN quality_verdict  TEXT;     -- 'pass' | 'fail' | 'partial'
ALTER TABLE results ADD COLUMN quality_feedback TEXT;     -- JSON string (judge 전체 응답)
```

### 4.2 prompts 테이블 확장

```sql
-- ground_truth + eval_strategy를 prompts 테이블에 추가
-- test_config.json의 prompt 정의와 1:1 매핑
ALTER TABLE prompts ADD COLUMN ground_truth    TEXT;     -- 정답 또는 평가 기준
ALTER TABLE prompts ADD COLUMN eval_strategy   TEXT NOT NULL DEFAULT 'llm_judge';
    -- 'deterministic' | 'deterministic_with_fallback' | 'llm_judge'
```

### 4.3 설계 근거

| 결정 | 이유 |
|------|------|
| **quality_feedback에 JSON string 저장** | judge 응답 원문(개별 점수, hallucinated_claims, feedback)을 보존. 나중에 대시보드에서 파싱하여 상세 표시 가능 |
| **quality_score는 REAL (0.0~1.0)** | 가중합 결과. deterministic eval도 동일 스케일 (1.0 = 정답, 0.0 = 오답) |
| **eval_strategy를 prompts에** | 카테고리와 eval 전략은 1:1이 아닐 수 있음. e.g., 같은 factoid이라도 정답 길이에 따라 전략이 다를 수 있음 |
| **ground_truth를 prompts에** | result가 아닌 prompt의 속성. 동일 prompt의 여러 result가 같은 ground_truth를 공유 |

### 4.4 quality_feedback JSON 구조

```json
{
  "eval_type": "llm_judge",
  "judge_model": "claude-sonnet-4-20250514",
  "criteria": {
    "correctness": 1,
    "faithfulness": 0,
    "relevance": 1,
    "completeness": 1
  },
  "hallucinated_claims": [
    "The model claimed Einstein published relativity in 1903, but it was 1905"
  ],
  "feedback": "Response is mostly correct but contains a fabricated date",
  "raw_score": 0.7,
  "weights": {
    "correctness": 0.4,
    "faithfulness": 0.3,
    "relevance": 0.2,
    "completeness": 0.1
  }
}
```

Deterministic eval의 경우:
```json
{
  "eval_type": "deterministic",
  "method": "exact_match_math",
  "feedback": "Correct: 722 matches expected 722",
  "criteria": {
    "correctness": 1,
    "faithfulness": 1,
    "relevance": 1,
    "completeness": 1
  }
}
```

## 5. test_config.json 변경

### 5.1 ground_truth 필드 추가

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
      "id": "math_02",
      "category": "math",
      "lang": "en",
      "prompt": "What is 9.9 - 9.11?",
      "ground_truth": "0.79",
      "eval_strategy": "deterministic"
    },
    {
      "id": "factoid_01",
      "category": "factoid",
      "lang": "en",
      "prompt": "What's the capital of Qing Dynasty?",
      "ground_truth": "Beijing",
      "eval_strategy": "deterministic_with_fallback"
    },
    {
      "id": "reasoning_01",
      "category": "reasoning",
      "lang": "en",
      "prompt": "Explain special relativity",
      "ground_truth": "Special relativity, published by Einstein in 1905, is based on two postulates: (1) the laws of physics are the same in all inertial reference frames, and (2) the speed of light in a vacuum is constant regardless of the observer's motion. Key consequences include time dilation, length contraction, and mass-energy equivalence (E=mc²).",
      "eval_strategy": "llm_judge"
    },
    {
      "id": "long_context_01",
      "category": "long_context",
      "lang": "en",
      "prompt": "Explain the significance of 'Attention is all you need'",
      "ground_truth": "The 2017 paper by Vaswani et al. introduced the Transformer architecture, which replaced recurrent and convolutional layers with self-attention mechanisms. Key contributions: (1) multi-head attention allowing parallel processing, (2) positional encoding for sequence order, (3) dramatically improved training efficiency. It became the foundation for BERT, GPT, and virtually all modern LLMs.",
      "eval_strategy": "llm_judge"
    },
    {
      "id": "creative_01",
      "category": "creative",
      "lang": "en",
      "prompt": "Tell me a joke.",
      "ground_truth": null,
      "eval_strategy": "llm_judge"
    }
  ]
}
```

### 5.2 하위 호환

- `ground_truth`와 `eval_strategy`는 optional 필드
- 미지정 시 기본값: `ground_truth=null`, `eval_strategy="llm_judge"`
- 기존 `runner.py`, `sync_results.py`는 이 필드를 무시 → 영향 없음
- `ingest.py`에서 prompts 테이블에 적재 시 새 필드 반영

## 6. LLM Judge Client

### 6.1 Provider 추상화

```python
# scripts/evaluators/judge_client.py

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class JudgeResponse:
    correctness: int        # 0 or 1
    faithfulness: int       # 0 or 1
    relevance: int          # 0 or 1
    completeness: int       # 0 or 1
    hallucinated_claims: list[str]
    feedback: str
    raw_json: dict          # judge 원본 응답 보존


class JudgeProvider(ABC):
    @abstractmethod
    def evaluate(self, system_prompt: str, user_prompt: str) -> JudgeResponse:
        ...


class AnthropicJudge(JudgeProvider):
    def __init__(self):
        import anthropic
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = os.getenv("JUDGE_MODEL", "claude-sonnet-4-20250514")

    def evaluate(self, system_prompt: str, user_prompt: str) -> JudgeResponse:
        message = self.client.messages.create(
            model=self.model,
            max_tokens=512,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return self._parse_response(message.content[0].text)

    def _parse_response(self, text: str) -> JudgeResponse:
        # JSON 파싱 (markdown fence 제거)
        clean = text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(clean)
        return JudgeResponse(
            correctness=int(data.get("correctness", 0)),
            faithfulness=int(data.get("faithfulness", 0)),
            relevance=int(data.get("relevance", 0)),
            completeness=int(data.get("completeness", 0)),
            hallucinated_claims=data.get("hallucinated_claims", []),
            feedback=data.get("feedback", ""),
            raw_json=data,
        )


class OpenAIJudge(JudgeProvider):
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = os.getenv("JUDGE_MODEL", "gpt-4o")

    def evaluate(self, system_prompt: str, user_prompt: str) -> JudgeResponse:
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=512,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return self._parse_response(response.choices[0].message.content)

    def _parse_response(self, text: str) -> JudgeResponse:
        clean = text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(clean)
        return JudgeResponse(
            correctness=int(data.get("correctness", 0)),
            faithfulness=int(data.get("faithfulness", 0)),
            relevance=int(data.get("relevance", 0)),
            completeness=int(data.get("completeness", 0)),
            hallucinated_claims=data.get("hallucinated_claims", []),
            feedback=data.get("feedback", ""),
            raw_json=data,
        )


def create_judge() -> JudgeProvider:
    """환경변수 JUDGE_PROVIDER에 따라 Judge 인스턴스 생성."""
    provider = os.getenv("JUDGE_PROVIDER", "anthropic").lower()
    if provider == "anthropic":
        return AnthropicJudge()
    elif provider == "openai":
        return OpenAIJudge()
    else:
        raise ValueError(f"Unknown JUDGE_PROVIDER: {provider}. Use 'anthropic' or 'openai'.")
```

### 6.2 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `JUDGE_PROVIDER` | `anthropic` | `anthropic` 또는 `openai` |
| `JUDGE_MODEL` | provider별 상이 | Anthropic: `claude-sonnet-4-20250514`, OpenAI: `gpt-4o` |
| `ANTHROPIC_API_KEY` | (필수, provider=anthropic 시) | Anthropic API 키 |
| `OPENAI_API_KEY` | (필수, provider=openai 시) | OpenAI API 키 |

## 7. Core Script: quality_eval.py

### 7.1 실행 모드

```bash
# 기본: 미평가 결과 전체 평가
python scripts/quality_eval.py

# 특정 run만 평가
python scripts/quality_eval.py --run-id 12345678

# dry-run: DB 업데이트 없이 결과만 출력
python scripts/quality_eval.py --dry-run

# 재평가: 기존 점수 덮어쓰기
python scripts/quality_eval.py --force

# 요약만 출력 (CI summary용)
python scripts/quality_eval.py --summary-only
```

### 7.2 핵심 로직 흐름

```python
# scripts/quality_eval.py (구조 개요)

def main():
    args = parse_args()
    db = connect_db()
    judge = create_judge() if needs_llm_judge(db, args) else None

    # 1. 평가 대상 조회
    rows = fetch_pending_results(db, args)
    # SELECT r.id, r.response, r.status,
    #        p.prompt_text, p.category, p.ground_truth, p.eval_strategy
    # FROM results r
    # JOIN prompts p ON r.prompt_id = p.id
    # WHERE r.quality_score IS NULL    (--force 시 이 조건 제거)
    #   AND r.status = 'success'       (error 결과는 평가 불가)

    # 2. 카테고리별 분기 평가
    results = []
    for row in rows:
        if row.eval_strategy == "deterministic":
            result = eval_deterministic(row)
        elif row.eval_strategy == "deterministic_with_fallback":
            result = eval_deterministic_with_fallback(row, judge)
        else:  # llm_judge
            result = eval_with_judge(row, judge)
        results.append(result)

    # 3. DB 업데이트 (배치)
    if not args.dry_run:
        update_quality_scores(db, results)

    # 4. 리포트 출력
    print_summary(results)


def eval_deterministic(row) -> EvalResult:
    """math / factoid 전용 deterministic 평가."""
    if row.category == "math":
        score, feedback = eval_math(row.response, row.ground_truth)
    else:
        score, feedback, _ = eval_factoid(row.response, row.ground_truth)

    # deterministic은 정답이면 모든 기준 1, 오답이면 correctness만 0
    criteria = {
        "correctness": 1 if score >= 0.8 else 0,
        "faithfulness": 1,  # deterministic 답변은 hallucination 개념 없음
        "relevance": 1,
        "completeness": 1 if score >= 0.8 else 0,
    }
    final_score = compute_weighted_score(criteria)
    verdict = determine_verdict(final_score)

    return EvalResult(
        result_id=row.id,
        quality_score=final_score,
        quality_verdict=verdict,
        quality_feedback=json.dumps({
            "eval_type": "deterministic",
            "method": f"exact_match_{row.category}",
            "feedback": feedback,
            "criteria": criteria,
        }),
    )


def eval_with_judge(row, judge: JudgeProvider) -> EvalResult:
    """LLM-as-a-Judge 평가."""
    rubric = get_rubric(row.category)
    user_prompt = format_user_prompt(row)

    try:
        judge_response = judge.evaluate(rubric, user_prompt)
    except (json.JSONDecodeError, KeyError) as e:
        # Judge 응답 파싱 실패 → 재시도 1회
        judge_response = judge.evaluate(rubric, user_prompt)

    criteria = {
        "correctness": judge_response.correctness,
        "faithfulness": judge_response.faithfulness,
        "relevance": judge_response.relevance,
        "completeness": judge_response.completeness,
    }
    final_score = compute_weighted_score(criteria)
    verdict = determine_verdict(final_score)

    return EvalResult(
        result_id=row.id,
        quality_score=final_score,
        quality_verdict=verdict,
        quality_feedback=json.dumps({
            "eval_type": "llm_judge",
            "judge_model": os.getenv("JUDGE_MODEL", "claude-sonnet-4-20250514"),
            "criteria": criteria,
            "hallucinated_claims": judge_response.hallucinated_claims,
            "feedback": judge_response.feedback,
            "raw_score": final_score,
            "weights": CRITERIA_WEIGHTS,
        }),
    )


def compute_weighted_score(criteria: dict[str, int]) -> float:
    """Binary criteria → 가중합 0.0~1.0."""
    weights = {"correctness": 0.4, "faithfulness": 0.3, "relevance": 0.2, "completeness": 0.1}
    return sum(criteria[k] * weights[k] for k in weights)


def determine_verdict(score: float) -> str:
    if score >= 0.7:
        return "pass"
    elif score >= 0.3:
        return "partial"
    else:
        return "fail"
```

### 7.3 Rate Limiting & Error Handling

```python
# Judge API 호출 rate limiting
JUDGE_RATE_LIMIT_SEC = 0.5  # 호출 간 최소 대기 (초)
JUDGE_MAX_RETRIES = 2       # 파싱 실패 시 재시도 횟수

# 에러 처리 원칙:
# - Judge API 호출 실패 → 해당 result 스킵, quality_score = NULL 유지
# - JSON 파싱 실패 → 1회 재시도, 재실패 시 스킵
# - DB 업데이트 실패 → 전체 배치 롤백 후 에러 리포트
# - 전체 성공/실패 통계를 마지막에 출력
```

## 8. CI/CD 통합

### 8.1 Workflow 변경

```yaml
# .github/workflows/benchmark.yml — Phase 4 step 추가

      - name: Ingest results to DB
        run: |
          python scripts/ingest.py \
            --run-id ${{ github.run_id }} \
            --trigger manual \
            --commit-sha ${{ github.sha }} \
            --branch ${{ github.ref_name }}

      # ✨ NEW — Phase 4 Quality Eval step
      - name: Evaluate response quality
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          JUDGE_PROVIDER: anthropic
        run: python scripts/quality_eval.py --run-id ${{ github.run_id }}

      - name: Upload DB artifact
        uses: actions/upload-artifact@v4
        # ... 기존과 동일
```

### 8.2 GitHub Secrets 추가

| Secret | 설명 |
|--------|------|
| `ANTHROPIC_API_KEY` | Anthropic API 키 (Claude Sonnet 호출용) |
| `OPENAI_API_KEY` | OpenAI API 키 (GPT-4o 대체 시, 옵셔널) |

### 8.3 비용 추정

| 항목 | 값 |
|------|---|
| 프롬프트 수 | ~7개 (현재 test_config.json) |
| 디바이스 × 모델 조합 | 2 × 5 = 10 |
| 총 eval/run | 최대 70건 |
| Deterministic 비율 | ~30% (math, factoid) → API 호출 불필요 |
| LLM judge 호출 수/run | ~50건 |
| 토큰/호출 | ~600 (input 500 + output 100) |
| 총 토큰/run | ~30K |
| 비용/run | **~$0.10** (Claude Sonnet 기준) |
| 월간 비용 (일 1회) | **~$3.00** |

## 9. API 확장

### 9.1 기존 엔드포인트 변경

```
GET  /api/results                    → 응답에 quality 필드 추가
     ?quality_verdict=pass           # ✨ NEW 필터: pass | fail | partial | null
     &min_quality_score=0.7          # ✨ NEW 필터: 최소 점수
```

### 9.2 신규 엔드포인트

```
GET  /api/quality/summary            → 품질 평가 집계
     ?device=...&model=...           # 기존 필터 호환

GET  /api/quality/hallucinations     → Hallucination 발생 목록
     ?model=...                      # 모델별 필터
     &limit=50

GET  /api/quality/by-category        → 카테고리별 품질 점수 분포
GET  /api/quality/by-model           → 모델별 품질 점수 비교
```

### 9.3 응답 스키마

```python
# api/schemas.py 추가

class QualityDetail(BaseModel):
    quality_score: Optional[float]
    quality_verdict: Optional[str]        # 'pass' | 'fail' | 'partial' | None
    quality_feedback: Optional[dict]       # 파싱된 JSON

class QualitySummary(BaseModel):
    total_evaluated: int
    pass_count: int
    partial_count: int
    fail_count: int
    not_evaluated: int
    avg_quality_score: Optional[float]
    pass_rate: float                       # pass_count / total_evaluated
    hallucination_count: int               # faithfulness=0인 결과 수

class HallucinationItem(BaseModel):
    result_id: int
    prompt: str
    model_name: str
    device_model: str
    response: str
    hallucinated_claims: list[str]
    quality_score: float

class CategoryQuality(BaseModel):
    category: str
    avg_score: float
    pass_rate: float
    eval_count: int

class ModelQuality(BaseModel):
    model_name: str
    avg_score: float
    pass_rate: float
    hallucination_rate: float
    eval_count: int

# 응답: ApiSuccess[QualitySummary], ApiSuccess[list[HallucinationItem]], etc.
```

## 10. Dashboard 확장

### 10.1 Overview 페이지 변경

- **KPI Cards 추가**: Avg Quality Score, Pass Rate, Hallucination Count
- 기존 4개 KPI (Total tests, Success rate, Avg latency, Avg TPS) 옆에 배치

### 10.2 Responses 페이지 변경

- 각 응답 카드에 `quality_verdict` 배지 표시 (초록=pass, 노랑=partial, 빨강=fail)
- `quality_score` 수치 표시
- 클릭 시 `quality_feedback` 상세 표시 (criteria별 점수, hallucinated_claims, feedback)

### 10.3 Quality 페이지 (✨ NEW)

| 섹션 | 내용 |
|------|------|
| **Quality KPI** | Pass rate, Avg score, Hallucination rate |
| **Score Distribution** | 히스토그램 (0.0~1.0 구간별 결과 수) |
| **By Category** | 카테고리별 avg score + pass rate 바 차트 |
| **By Model** | 모델별 avg score + hallucination rate 비교 |
| **Hallucination Log** | hallucinated_claims 목록 테이블 (모델, 프롬프트, 지어낸 내용) |

## 11. Error Handling

### 11.1 quality_eval.py

| 상황 | 처리 |
|------|------|
| API 키 미설정 | 즉시 실패 + 에러 메시지 (deterministic eval은 계속 실행) |
| Judge API 호출 실패 (네트워크) | 3회 재시도 (exponential backoff) 후 해당 result 스킵 |
| Judge 응답 JSON 파싱 실패 | 1회 재시도 후 스킵 |
| Judge 응답에 필수 필드 누락 | 누락 필드 0으로 처리 + 경고 로그 |
| ground_truth 미설정 (null) | `llm_judge` 전략으로 fallback (creative rubric 사용) |
| DB 업데이트 실패 | 전체 배치 롤백 + 에러 리포트 |
| 평가 대상 0건 | 정상 종료 (이미 전부 평가됨) |

### 11.2 API

| 상황 | 처리 |
|------|------|
| quality_score IS NULL인 결과 조회 | 정상 반환 (`quality_score: null`). 404 아님 |
| quality_verdict 필터에 잘못된 값 | 400 + `ApiError` |

## 12. Directory Structure (변경사항)

```
on-device-llm-tester/
├── .github/
│   └── workflows/
│       └── benchmark.yml               # ✨ UPDATE — quality_eval.py step 추가
│
├── api/
│   ├── main.py                         # ✨ UPDATE — /api/quality/* 엔드포인트 추가
│   ├── db.py                           # ✨ UPDATE — ALTER TABLE DDL 추가
│   ├── loader.py                       # ✨ UPDATE — quality 필터 추가
│   ├── stats.py                        # ✨ UPDATE — quality 집계 함수 추가
│   ├── schemas.py                      # ✨ UPDATE — Quality* 스키마 추가
│   └── requirements.txt                # ✅ 변경 없음
│
├── scripts/
│   ├── quality_eval.py                 # ✨ NEW — 품질 평가 메인 스크립트
│   ├── evaluators/                     # ✨ NEW — 평가 모듈 디렉토리
│   │   ├── __init__.py
│   │   ├── deterministic.py            # EM + 정규식 기반 평가
│   │   ├── judge_client.py             # LLM Judge provider 추상화
│   │   └── rubrics.py                  # 카테고리별 rubric 프롬프트
│   ├── runner.py                       # ✅ 변경 없음
│   ├── sync_results.py                 # ✅ 변경 없음
│   ├── ingest.py                       # ✨ UPDATE — prompts에 ground_truth/eval_strategy 적재
│   ├── shuttle.py                      # ✅ 변경 없음
│   └── setup.py                        # ✅ 변경 없음
│
├── dashboard/src/
│   ├── pages/
│   │   └── Quality.tsx                 # ✨ NEW — 품질 평가 전용 페이지
│   ├── hooks/
│   │   └── useQuality.ts               # ✨ NEW — quality 데이터 훅
│   ├── types/
│   │   └── index.ts                    # ✨ UPDATE — Quality* 타입 추가
│   └── components/
│       ├── layout/
│       │   └── Sidebar.tsx             # ✨ UPDATE — Quality 메뉴 추가
│       ├── cards/
│       │   └── KpiCard.tsx             # ✅ 변경 없음 (재사용)
│       └── quality/                    # ✨ NEW
│           ├── VerdictBadge.tsx         # pass/partial/fail 배지 컴포넌트
│           ├── ScoreDistribution.tsx    # 점수 분포 히스토그램
│           ├── CategoryQuality.tsx      # 카테고리별 품질 차트
│           ├── ModelQuality.tsx         # 모델별 품질 비교
│           └── HallucinationLog.tsx     # Hallucination 목록 테이블
│
├── data/
│   └── llm_tester.db                  # ✅ 유지 — quality 컬럼 추가됨
│
├── results/                            # ✅ 유지
├── test_config.json                    # ✨ UPDATE — ground_truth, eval_strategy 추가
└── README.md                           # ✨ UPDATE — Quality Eval 섹션 추가
```

## 13. Implementation Order

```
Step 1: test_config.json + DB 스키마 확장
        → test_config.json에 ground_truth, eval_strategy 필드 추가
        → prompts 테이블에 ground_truth, eval_strategy 컬럼 ALTER TABLE
        → results 테이블에 quality_score, quality_verdict, quality_feedback ALTER TABLE
        → ingest.py에서 새 필드 적재 로직 추가
        → 검증: ingest.py 실행 후 prompts.ground_truth에 값 확인

Step 2: Deterministic evaluator
        → scripts/evaluators/deterministic.py 작성 (eval_math, eval_factoid)
        → 단위 테스트: 다양한 응답 형태에 대한 정확도 검증
        → edge case: "approximately 720", "720-ish", 빈 응답, 한국어 숫자

Step 3: LLM Judge client + rubrics
        → scripts/evaluators/judge_client.py 작성 (Anthropic/OpenAI provider)
        → scripts/evaluators/rubrics.py 작성 (카테고리별 프롬프트)
        → 단독 테스트: API 키 설정 후 단일 평가 실행
        → 검증: JSON 응답 파싱 정상 동작

Step 4: quality_eval.py 메인 스크립트
        → DB 조회 → 카테고리 분기 → 평가 → DB 업데이트 파이프라인
        → --dry-run, --force, --run-id, --summary-only 플래그
        → rate limiting + retry 로직
        → 전체 파이프라인 테스트: ingest.py → quality_eval.py
        → 검증: results.quality_score, quality_verdict, quality_feedback 채워짐

Step 5: CI/CD 통합
        → benchmark.yml에 quality_eval.py step 추가
        → GitHub Secrets에 ANTHROPIC_API_KEY 등록
        → GitHub UI에서 "Run workflow" → E2E 테스트
        → GITHUB_STEP_SUMMARY에 품질 평가 요약 출력

Step 6: API 확장
        → /api/quality/* 엔드포인트 추가
        → /api/results에 quality 필터 추가
        → Quality* Pydantic 스키마
        → Swagger에서 테스트

Step 7: Dashboard — Quality 페이지
        → Quality.tsx 페이지 작성
        → useQuality.ts 훅
        → VerdictBadge, ScoreDistribution, CategoryQuality, ModelQuality, HallucinationLog 컴포넌트
        → Sidebar에 메뉴 추가
        → Overview KPI에 Quality 카드 추가
        → Responses 페이지에 verdict 배지 표시

Step 8: 문서 + 정리
        → README.md에 Quality Eval 섹션 추가
        → 환경변수 설정 가이드 (.env.example)
        → ground_truth 작성 가이드 (새 프롬프트 추가 시)
```

## 14. Extension Points (향후 확장)

```
향후 확장 (필요 시):
  └─→ Judge 모델 A/B 테스트: 동일 결과를 Claude/GPT로 각각 평가하여 일치도 측정
  └─→ Human-in-the-loop: 대시보드에서 수동 verdict override → judge 정확도 캘리브레이션
  └─→ Claim-level decomposition: 응답을 개별 claim으로 분해 → 각 claim 독립 검증
  └─→ SelfCheckGPT: 동일 프롬프트 N회 샘플링 → 응답 간 일관성으로 hallucination 탐지
  └─→ 자동 회귀 감지: 동일 모델의 과거 quality_score 대비 하락 시 알림
  └─→ ground_truth 자동 생성: 강한 모델(GPT-4o)로 reference answer 생성 → 수동 검수 후 적용
  └─→ 한국어 eval: 한국어 프롬프트 추가 시 rubric도 한국어 버전 작성
  └─→ 멀티디바이스 품질 비교: Device Compare 페이지에 quality_score 오버레이
```

## 15. Tech Stack (Phase 4 추가분)

| Layer | Tech | Why |
|-------|------|-----|
| **LLM Judge (기본)** | Anthropic SDK + Claude Sonnet | 네이티브 SDK, 높은 추론 품질, 사내 인프라 활용 가능 |
| **LLM Judge (대체)** | OpenAI SDK + GPT-4o | Provider 다양성, self-preference 회피 |
| **Deterministic Eval** | Python `re` + `math` | 표준 라이브러리, 추가 의존성 없음 |
| **DB** | SQLite (기존) | ALTER TABLE로 컬럼 추가만, 스키마 호환 |

※ API, Dashboard 스택은 Phase 1/1.5/2/3과 동일. 추가 pip 의존성: `anthropic` (또는 `openai`).

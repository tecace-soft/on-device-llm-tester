# On-Device LLM Tester

Android 기기에서 on-device LLM 추론을 자동 실행하고, 결과를 수집·분석·시각화하는 벤치마킹 플랫폼.

## Architecture

이 프로젝트는 아키텍처 문서가 곧 설계의 source of truth다. **코드 수정 전에 반드시 해당 아키텍처 문서를 먼저 읽을 것.**

| 문서 | 범위 |
|------|------|
| `DASHBOARD_ARCHITECTURE.md` | React dashboard + FastAPI backend |
| `DB_MIGRATION_ARCHITECTURE.md` | SQLite schema, loader.py, stats.py |
| `CICD_ARCHITECTURE.md` | GitHub Actions, self-hosted runner |
| `DEPLOYMENT_ARCHITECTURE.md` | Vercel (UI + Serverless API) + Turso 클라우드 배포 |
| `MULTIDEVICE_ARCHITECTURE.md` | 멀티디바이스 병렬 테스트 |
| `RESPONSE_VALIDATION_ARCHITECTURE.md` | Phase 4a 응답 검증 |
| `QUALITY_EVAL_ARCHITECTURE.md` | Phase 4b AI 품질 평가 |
| `RESOURCE_PROFILING_ARCHITECTURE.md` | Phase 6 배터리/메모리 프로파일링 |
| `QUANT_COMPARISON_ARCHITECTURE.md` | 양자화 비교 분석 |
| `LLMCPP_ARCHITECTURE.md` | llama.cpp 엔진 통합 |

## Project Structure

```
on-device-llm-tester/
├── android/          # Kotlin + Jetpack Compose (package: com.tecace.llmtester)
├── api/              # FastAPI backend (Python)
│   ├── main.py       # 엔드포인트 + CORS + lifespan
│   ├── db.py         # aiosqlite 연결 + DDL
│   ├── loader.py     # SQL SELECT → API 응답
│   ├── stats.py      # SQL 집계 쿼리
│   └── schemas.py    # Pydantic 모델
├── dashboard/        # React 18 + Vite + TypeScript + Tailwind
├── scripts/          # Python 자동화 (runner, ingest, sync, validators)
├── .github/workflows/ # CI/CD (benchmark.yml)
└── test_config.json  # 프롬프트 + ground_truth 정의
```

## Tech Stack

- **Android**: Kotlin, Jetpack Compose, Material 3, MediaPipe LLM Inference API
- **Backend**: FastAPI, aiosqlite, Pydantic v2
- **Frontend**: React 18, Vite, TypeScript, Tailwind CSS, Recharts, TanStack Table
- **DB**: SQLite (로컬) / Turso libSQL (클라우드) — `DB_MODE` 환경변수로 전환
- **CI/CD**: GitHub Actions + Windows self-hosted runner
- **Deploy**: Vercel (React UI + FastAPI Python Serverless) + Turso (libSQL HTTP v2)

## Code Conventions

### Kotlin (Android)
- 모든 파일에 `package com.tecace.llmtester` (또는 하위 패키지) 필수
- Jetpack Compose + Material 3 사용

### Python
- PEP 8 준수, type hints 필수 (`from typing import Any, Optional`)
- `_float(v: Any)`, `_int(v: Any)` 패턴 — `object` 대신 `Any` 사용 (Pylance 호환)

### TypeScript
- strict mode, 절대 `any` 금지
- API 호출은 `dashboard/src/api/client.ts` 통해서만

### Comments
- Module docstring: `Architecture: *_ARCHITECTURE.md §N`
- Function/Class: `Used by:`, `Depends on:`
- "Why" 주석만 — "What" 주석 금지

## Commands

```bash
# Backend
cd api && uvicorn main:app --reload --port 8000

# Frontend
cd dashboard && npm run dev

# Ingest (local)
python scripts/ingest.py --run-id <id> --trigger manual --branch main

# Ingest (Turso)
DB_MODE=turso python scripts/ingest.py --run-id <id> --trigger manual --branch main

# Validation
python scripts/response_validator.py --run-id <id>

# Tests
cd api && python -m pytest tests/ -v
```

## Critical Rules

1. **아키텍처 문서가 있으면 반드시 따를 것.** 임의로 구조를 변경하지 않는다.
2. **기존 코드 삭제 금지.** 모든 변경은 additive (if/else 분기). 특히 `DB_MODE` dual-mode 패턴.
3. **SQL 쿼리 문자열은 변경하지 않는다.** 표준 SQL로 작성되어 SQLite/Turso 모두 호환.
4. **DDL은 `scripts/ingest.py`와 `api/db.py` 두 곳에 중복.** 스키마 변경 시 양쪽 모두 업데이트.
5. **새 라이브러리 추가 시** `api/requirements.txt` 또는 `dashboard/package.json` 즉시 반영.
6. **Full file output.** 새 파일은 전체 내용, `// existing code...` 같은 placeholder 금지.
7. **30줄 미만 수정은 anchor + delta로 제시.** 전체 파일 재출력 불필요.

## Current Work

Phase 7 Cloud Deployment 구현 중. 진행 상황:
- ✅ Step 1: Turso 셋업 완료
- ✅ Step 2: `scripts/ingest.py` Turso dual-mode + batch INSERT 완료
- ✅ Step 3: `api/db.py` dual-mode lifespan + `api/db_adapter.py` 신규
- ✅ Step 4: `api/cache.py` TTLCache
- ✅ Step 5a: Vercel + Render + Turso 구성 (구버전, 롤백용으로만 유지)
- ✅ Step 5b: **Vercel + Turso only** 전환 완료 — Render 제거
  - `api/turso_client.py` 신규 — aiohttp → Turso HTTP v2/pipeline
    (deprecated `libsql-client` WS SDK가 Render에서 505 반환 → 교체)
  - `api/db.py` — `libsql_client` import → `from turso_client import TursoClient`
  - `api/requirements.txt` — `libsql-client` 제거, `aiohttp>=3.9.0` 추가
  - `api/index.py` 신규 — Vercel Python Serverless entry (`from main import app`)
  - `vercel.json` 루트 추가 — monorepo build(dashboard/dist) + `api/index.py` function + rewrites
  - `DEPLOYMENT_ARCHITECTURE.md` §1·§7 업데이트 (Vercel+Turso primary, Render legacy)
- 🔲 Step 6: 통합 테스트 + README 업데이트

Deployment stack: **Vercel** (React UI + FastAPI Serverless) + **Turso** (libSQL HTTP v2)
See `DEPLOYMENT_ARCHITECTURE.md` for full plan.

# On-Device LLM Tester — Phase 5: llama.cpp Multi-Engine Architecture

## 1. High-Level Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                   MULTI-ENGINE PIPELINE (Phase 5)                        │
│                                                                          │
│  test_config.json (✨ UPDATED)                                           │
│    └─ engine 필드 추가: "mediapipe" | "llamacpp"                          │
│    └─ engine_params 추가: llama.cpp 전용 파라미터 (n_gpu_layers 등)       │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  Android App (com.tecace.llmtester)                               │    │
│  │                                                                   │    │
│  │  MainActivity.kt (✨ UPDATED)                                     │    │
│  │    ├─ Intent extra: engine ("mediapipe" | "llamacpp")             │    │
│  │    ├─ engine 값에 따라 Runner 분기                                 │    │
│  │    └─ 결과 JSON 포맷 통일 (engine 필드 추가)                       │    │
│  │                                                                   │    │
│  │  ┌─────────────────────┐   ┌─────────────────────┐               │    │
│  │  │  InferenceEngine    │   │  InferenceEngine    │               │    │
│  │  │  (interface) ✨ NEW │   │  (interface) ✨ NEW │               │    │
│  │  └────────┬────────────┘   └────────┬────────────┘               │    │
│  │           │                          │                            │    │
│  │  ┌────────▼────────────┐   ┌────────▼────────────┐               │    │
│  │  │  MediaPipeEngine    │   │  LlamaCppEngine     │               │    │
│  │  │  (기존 LlmRunner     │   │  (✨ NEW)           │               │    │
│  │  │   리팩토링)          │   │  JNI → llama.cpp    │               │    │
│  │  │  .task 포맷          │   │  .gguf 포맷          │               │    │
│  │  └─────────────────────┘   └─────────────────────┘               │    │
│  │                                                                   │    │
│  │  InferenceMetrics.kt (변경 없음)                                   │    │
│  │    └─ 동일 메트릭 구조 유지 (latency, TPS, TTFT, memory 등)        │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  기존 파이프라인 (변경 최소화)                                      │    │
│  │  runner.py → sync_results.py → ingest.py → response_validator.py │    │
│  │                                                                   │    │
│  │  runner.py (✨ UPDATED)                                           │    │
│  │    └─ Intent extra에 engine, engine_params 전달                    │    │
│  │                                                                   │    │
│  │  ingest.py (✨ UPDATED)                                           │    │
│  │    └─ models 테이블에 engine 컬럼 추가                              │    │
│  │                                                                   │    │
│  │  나머지 스크립트 변경 없음                                          │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  Dashboard + API (변경 최소화)                                            │
│    └─ engine 필터 추가 (필요 시)                                          │
│    └─ 모델명에 엔진 구분이 자연스럽게 반영됨                               │
└──────────────────────────────────────────────────────────────────────────┘
```

## 2. Why This Architecture

### 2.1 llama.cpp Android 통합 전략 — 왜 JNI 바인딩인가?

llama.cpp를 Android 앱에 통합하는 방식은 3가지:

| 방식 | 장점 | 단점 | 판정 |
|------|------|------|------|
| **A. llama.android 참조 구현** | Google 공식 예제 패턴, JNI 바인딩 검증됨 | 예제 수준이라 프로덕션 코드 직접 작성 필요 | ✅ **채택** |
| B. llama.cpp HTTP 서버 모드 | 앱 변경 최소화, localhost:8080 호출 | 별도 프로세스 관리, 포트 충돌, ADB 포워딩 복잡 | ❌ |
| C. Termux + llama-cli | 가장 쉬운 PoC | 앱 외부 의존성, CI 자동화 불가, 메트릭 수집 불가 | ❌ |

**채택 이유**: llama.android (https://github.com/ggml-org/llama.cpp/tree/master/examples/llama.android) 패턴을 참조하되, 우리 앱의 `InferenceMetrics` 수집 구조에 맞게 JNI 레이어를 커스텀 작성한다. 이렇게 하면:
- TTFT, decode TPS, ITL 등 기존 메트릭을 동일하게 수집 가능
- 앱 내에서 엔진 선택이 Intent extra 하나로 분기
- 별도 프로세스/서버 관리 불필요

### 2.2 엔진 추상화 — 왜 인터페이스를 도입하는가?

현재 `LlmRunner.kt`가 MediaPipe `LlmInference` API에 하드코딩되어 있다. llama.cpp 추가 시 if-else 분기로 때우면 코드가 지저분해지고, 향후 3번째 엔진(예: MLC LLM, ExecuTorch) 추가 시 감당 불가.

`InferenceEngine` 인터페이스를 도입하고, `MediaPipeEngine`과 `LlamaCppEngine`이 이를 구현하는 Strategy 패턴을 사용한다. `MainActivity`는 엔진 타입에 따라 적절한 구현체를 선택.

### 2.3 결과 JSON 통일 — 왜 포맷을 바꾸지 않는가?

기존 downstream 파이프라인(sync_results.py → ingest.py → response_validator.py → dashboard)이 결과 JSON의 특정 필드 구조에 의존한다. 새 엔진의 결과도 **동일한 JSON 스키마**로 출력하면 downstream 변경이 `engine` 필드 하나 추가로 끝난다.

### 2.4 모델 포맷 자동 감지 — 왜 지원하되 config 명시를 권장하는가?

파일 확장자 기반 자동 감지(`.task` → MediaPipe, `.gguf` → llama.cpp)는 편의 기능으로 제공하되, `test_config.json`에 `engine` 필드를 **명시적으로** 적는 것을 표준으로 한다. 이유:
- 확장자가 없거나 비표준인 경우 대응
- 동일 GGUF를 다른 엔진 파라미터로 테스트하는 시나리오 지원
- 설정의 명시성 = 재현성

## 3. Android App Architecture

### 3.1 InferenceEngine Interface (✨ NEW)

```kotlin
// android/app/src/main/java/com/tecace/llmtester/InferenceEngine.kt
package com.tecace.llmtester

interface InferenceEngine {
    val engineName: String           // "mediapipe" | "llamacpp"
    val initTimeMs: Long

    suspend fun init(
        modelPath: String,
        maxTokens: Int = 1024,
        params: Map<String, String> = emptyMap()
    )

    suspend fun generate(prompt: String, inputTokenCount: Int): InferenceMetrics

    fun close()
}
```

**설계 결정**:
- `params: Map<String, String>` — 엔진별 파라미터를 유연하게 전달. MediaPipe는 `backend` 키, llama.cpp는 `n_gpu_layers`, `temperature` 등
- `close()` — llama.cpp는 네이티브 메모리 해제가 필요
- `InferenceMetrics` 반환 — 기존 데이터 클래스 그대로 재사용

### 3.2 MediaPipeEngine (기존 LlmRunner 리팩토링)

```kotlin
// android/app/src/main/java/com/tecace/llmtester/MediaPipeEngine.kt
package com.tecace.llmtester
```

기존 `LlmRunner.kt`의 로직을 `InferenceEngine` 인터페이스 구현체로 이동. 핵심 변경:
- `init()` 시그니처: `preferredBackend: LlmInference.Backend` → `params["backend"]`에서 파싱
- `generate()` 로직: 기존과 100% 동일
- `close()`: `llmInference?.close()` 추가 (현재는 없음, 리소스 누수 방지)

### 3.3 LlamaCppEngine (✨ NEW)

```kotlin
// android/app/src/main/java/com/tecace/llmtester/LlamaCppEngine.kt
package com.tecace.llmtester
```

JNI를 통해 llama.cpp 네이티브 라이브러리를 호출하는 엔진 구현체.

**JNI 레이어 설계**:

```kotlin
// android/app/src/main/java/com/tecace/llmtester/LlamaCpp.kt
package com.tecace.llmtester

object LlamaCpp {
    init {
        System.loadLibrary("llama-android")
    }

    // Model lifecycle
    external fun loadModel(
        modelPath: String,
        nGpuLayers: Int = 0,
        nCtx: Int = 2048,
        nThreads: Int = 4
    ): Long  // returns model pointer

    external fun freeModel(modelPtr: Long)

    // Inference (streaming via callback)
    external fun generate(
        modelPtr: Long,
        prompt: String,
        maxTokens: Int,
        temperature: Float = 0.7f,
        topP: Float = 0.95f,
        topK: Int = 40,
        repeatPenalty: Float = 1.1f,
        callback: TokenCallback
    ): Int  // returns total tokens generated

    // Token callback interface for streaming
    interface TokenCallback {
        fun onToken(token: String): Boolean  // return false to stop
    }
}
```

**C++ JNI 구현** (`android/app/src/main/cpp/llama-jni.cpp`):

llama.cpp를 CMake로 빌드하여 `.so`를 생성. JNI 함수에서:
1. `loadModel` → `llama_model_load_from_file()` + `llama_init_from_model()`
2. `generate` → `llama_decode()` 루프, 각 토큰마다 Java callback 호출
3. `freeModel` → `llama_free()` + `llama_model_free()`

**LlamaCppEngine의 generate() 메트릭 수집**:

```kotlin
override suspend fun generate(prompt: String, inputTokenCount: Int): InferenceMetrics =
    withContext(Dispatchers.IO) {
        val tokenTimestamps = mutableListOf<Long>()
        val chunks = mutableListOf<String>()
        val genStartTime = System.currentTimeMillis()

        var peakJavaMem = currentJavaMemMb()
        var peakNativeMem = currentNativeMemMb()

        LlamaCpp.generate(
            modelPtr = modelPtr,
            prompt = prompt,
            maxTokens = maxTokens,
            temperature = temperature,
            topP = topP,
            topK = topK,
            repeatPenalty = repeatPenalty,
            callback = object : LlamaCpp.TokenCallback {
                override fun onToken(token: String): Boolean {
                    val now = System.currentTimeMillis()
                    tokenTimestamps.add(now)
                    chunks.add(token)

                    // Peak memory tracking (동일 패턴)
                    trackPeakMemory(...)
                    return true
                }
            }
        )

        // InferenceMetrics 계산 — 기존 LlmRunner와 동일 로직
        buildInferenceMetrics(genStartTime, tokenTimestamps, chunks, ...)
    }
```

핵심: **메트릭 계산 로직은 MediaPipeEngine과 동일**. 스트리밍 콜백에서 토큰 타임스탬프를 수집하고, TTFT/decode TPS/ITL을 동일 공식으로 계산.

### 3.4 MainActivity 변경

```kotlin
// 변경 포인트만 표시

// 1. engine Intent extra 파싱
val engineType = intent.getStringExtra("engine") ?: "mediapipe"  // 하위 호환

// 2. engine_params JSON 파싱
val engineParamsJson = intent.getStringExtra("engine_params") ?: "{}"
val engineParams: Map<String, String> = JSONObject(engineParamsJson).let { json ->
    json.keys().asSequence().associateWith { json.getString(it) }
}

// 3. 엔진 선택
val engine: InferenceEngine = when (engineType.lowercase()) {
    "llamacpp" -> LlamaCppEngine(this)
    else -> MediaPipeEngine(this)
}

// 4. 엔진 초기화 + 추론 (통일된 인터페이스)
engine.init(modelPath, maxTokens, engineParams)
val metrics = engine.generate(prompt, inputTokenCount)
engine.close()

// 5. 결과 JSON에 engine 필드 추가
json.put("engine", engine.engineName)
```

### 3.5 결과 JSON 포맷 (확장)

```json
{
  "status": "success",
  "engine": "llamacpp",
  "prompt_id": "math_01",
  "prompt_category": "math",
  "prompt_lang": "en",
  "model_path": "/data/local/tmp/llm_test/models/qwen2.5-1.5b-q4_k_m.gguf",
  "model_name": "qwen2.5-1.5b-q4_k_m.gguf",
  "backend": "CPU",
  "device": { ... },
  "prompt": "What is 237 + 485?",
  "response": "722",
  "latency_ms": 1234,
  "init_time_ms": 890,
  "metrics": {
    "total_latency_ms": 1234,
    "ttft_ms": 120,
    "prefill_time_ms": 120,
    "decode_time_ms": 1114,
    "input_token_count": 12,
    "output_token_count": 5,
    "prefill_tps": 100.0,
    "decode_tps": 4.49,
    "peak_java_memory_mb": 45,
    "peak_native_memory_mb": 890,
    "itl_p50_ms": 220,
    "itl_p95_ms": 280,
    "itl_p99_ms": 310
  },
  "timestamp": 1711000000000
}
```

**기존 대비 변경**: `"engine"` 필드 1개 추가. 나머지 구조 동일.
- `engine` 미지정 시 기존 결과는 `"mediapipe"`로 간주 (하위 호환)
- `backend`: MediaPipe에서는 "CPU"/"GPU", llama.cpp에서는 "CPU" (n_gpu_layers=0) 또는 "GPU" (n_gpu_layers>0)

## 4. NDK Build Configuration

### 4.1 CMakeLists.txt

```
android/app/src/main/cpp/
├── CMakeLists.txt
├── llama-jni.cpp           # JNI 바인딩 코드
└── llama.cpp/              # git submodule
    ├── include/
    │   └── llama.h
    ├── src/
    │   ├── llama.cpp
    │   ├── llama-grammar.cpp
    │   └── ...
    ├── ggml/
    │   ├── include/
    │   │   └── ggml.h
    │   └── src/
    │       ├── ggml.c
    │       ├── ggml-cpu/
    │       ├── ggml-vulkan/    # Vulkan GPU 가속 (선택)
    │       └── ...
    └── common/
        ├── common.h
        ├── common.cpp
        ├── sampling.h
        └── sampling.cpp
```

```cmake
# android/app/src/main/cpp/CMakeLists.txt

cmake_minimum_required(VERSION 3.22.1)
project(llama-android)

# llama.cpp 빌드 옵션
set(LLAMA_BUILD_TESTS OFF)
set(LLAMA_BUILD_EXAMPLES OFF)
set(LLAMA_BUILD_SERVER OFF)
set(BUILD_SHARED_LIBS OFF)

# Android NDK 최적화
set(GGML_NATIVE OFF)           # Cross-compile이므로 -march=native 비활성
set(GGML_OPENMP ON)            # ARM multi-thread

# Vulkan GPU 가속 (선택, 별도 Step에서 활성화)
# set(GGML_VULKAN ON)

add_subdirectory(llama.cpp)

# JNI 바인딩 라이브러리
add_library(llama-android SHARED llama-jni.cpp)

target_link_libraries(llama-android
    llama
    common
    ggml
    android
    log
)
```

### 4.2 build.gradle.kts 변경

```kotlin
android {
    // 기존 설정 유지...

    defaultConfig {
        // 기존...

        ndk {
            abiFilters += listOf("arm64-v8a")  // 64bit ARM만 (S25/S26)
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.22.1"
        }
    }

    // 기존 packaging 설정 유지
}

dependencies {
    // 기존 의존성 유지...
    // MediaPipe: implementation("com.google.mediapipe:tasks-genai:0.10.32")
    // llama.cpp: NDK 빌드로 포함 (별도 dependency 없음)
}
```

### 4.3 llama.cpp 소스 관리

```bash
# git submodule로 llama.cpp 추가
cd android/app/src/main/cpp
git submodule add https://github.com/ggml-org/llama.cpp.git

# 특정 태그/커밋 고정 (재현성)
cd llama.cpp
git checkout b5460    # 안정 릴리스 태그
```

`.gitmodules`:
```
[submodule "android/app/src/main/cpp/llama.cpp"]
    path = android/app/src/main/cpp/llama.cpp
    url = https://github.com/ggml-org/llama.cpp.git
```

## 5. test_config.json 스키마 확장

### 5.1 models 배열 변경

```json
{
  "timeout_sec": 120,
  "models": [
    {
      "path": "/data/local/tmp/llm_test/models/gemma-3-270m-it-int8.task",
      "max_tokens": 1024,
      "backend": "CPU",
      "engine": "mediapipe"
    },
    {
      "path": "/data/local/tmp/llm_test/models/qwen2.5-1.5b-instruct-q4_k_m.gguf",
      "max_tokens": 1024,
      "backend": "CPU",
      "engine": "llamacpp",
      "engine_params": {
        "n_gpu_layers": "0",
        "n_threads": "4",
        "n_ctx": "2048",
        "temperature": "0.7",
        "top_p": "0.95",
        "top_k": "40",
        "repeat_penalty": "1.1"
      }
    },
    {
      "path": "/data/local/tmp/llm_test/models/qwen2.5-1.5b-instruct-q4_k_m.gguf",
      "max_tokens": 1024,
      "backend": "GPU",
      "engine": "llamacpp",
      "engine_params": {
        "n_gpu_layers": "99",
        "n_threads": "4",
        "n_ctx": "2048"
      }
    }
  ],
  "prompts": [
    // ... 기존 프롬프트 배열 (변경 없음)
  ]
}
```

### 5.2 새 필드 정의

| 필드 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `engine` | string | `"mediapipe"` | 추론 엔진. `"mediapipe"` \| `"llamacpp"` |
| `engine_params` | object | `{}` | 엔진별 추가 파라미터 (key-value string map) |

### 5.3 engine_params 키 정의 (llama.cpp)

| 키 | 타입 | 기본값 | 설명 |
|----|------|--------|------|
| `n_gpu_layers` | string(int) | `"0"` | GPU 오프로드 레이어 수. `"0"` = CPU only, `"99"` = 전체 GPU |
| `n_threads` | string(int) | `"4"` | 추론 스레드 수 |
| `n_ctx` | string(int) | `"2048"` | 컨텍스트 윈도우 크기 |
| `temperature` | string(float) | `"0.7"` | 샘플링 온도 |
| `top_p` | string(float) | `"0.95"` | nucleus sampling |
| `top_k` | string(int) | `"40"` | top-k sampling |
| `repeat_penalty` | string(float) | `"1.1"` | 반복 페널티 |

### 5.4 engine_params 키 정의 (mediapipe)

| 키 | 타입 | 기본값 | 설명 |
|----|------|--------|------|
| (없음) | - | - | MediaPipe는 `backend` 필드로 CPU/GPU 선택. 추가 파라미터 없음 |

### 5.5 하위 호환

- `engine` 미지정 → `"mediapipe"` (기존 config 그대로 동작)
- `engine_params` 미지정 → `{}` (기본값 사용)
- 기존 `backend` 필드 유지 — 두 엔진 모두 `"CPU"` / `"GPU"` 구분에 사용

### 5.6 엔진 자동 감지 (fallback)

`engine` 미지정 + 파일 확장자 기반 추론:
- `.task` → `"mediapipe"`
- `.gguf` → `"llamacpp"`
- 그 외 → 에러 로그 + 스킵

이 로직은 `runner.py`에서 config 파싱 시 적용. 앱에는 항상 명시적 `engine` 값을 전달.

## 6. Python Scripts 변경

### 6.1 runner.py 변경

```python
# 변경 포인트

# 1. config에서 engine 파싱
engine = model.get("engine", "").lower()
if not engine:
    # 자동 감지 fallback
    if model_path.endswith(".task"):
        engine = "mediapipe"
    elif model_path.endswith(".gguf"):
        engine = "llamacpp"
    else:
        logger.error("[SKIP] Unknown model format and no engine specified: %s", model_path)
        continue

# 2. engine_params를 JSON 문자열로 직렬화
engine_params = model.get("engine_params", {})
engine_params_json = json.dumps(engine_params) if engine_params else "{}"

# 3. am start에 engine + engine_params Intent extra 추가
am_cmd = (
    f"am start -W -S"
    f" -n {PACKAGE_NAME}/.MainActivity"
    f" --es model_path {_escape_for_adb_shell(model_path)}"
    f" --es input_prompt {_escape_for_adb_shell(prompt_text)}"
    f" --ei max_tokens {max_tokens}"
    f" --es backend {_escape_for_adb_shell(backend)}"
    f" --es engine {_escape_for_adb_shell(engine)}"
    f" --es engine_params {_escape_for_adb_shell(engine_params_json)}"
    f" --es prompt_id {_escape_for_adb_shell(prompt_id)}"
    f" --es prompt_category {_escape_for_adb_shell(category)}"
    f" --es prompt_lang {_escape_for_adb_shell(lang)}"
)
```

### 6.2 ingest.py 변경

```python
# models 테이블 DDL 확장
# models 테이블의 UNIQUE 제약에 engine 추가

CREATE TABLE IF NOT EXISTS models (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name  TEXT NOT NULL DEFAULT '',
    model_path  TEXT NOT NULL DEFAULT '',
    backend     TEXT NOT NULL DEFAULT '',
    engine      TEXT NOT NULL DEFAULT 'mediapipe',   -- ✨ NEW
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(model_name, model_path, backend, engine)  -- ✨ UPDATED
);

# upsert_model 함수 확장
def upsert_model(con, model_name, model_path, backend, engine="mediapipe"):
    con.execute("""
        INSERT OR IGNORE INTO models (model_name, model_path, backend, engine)
        VALUES (?, ?, ?, ?)
    """, (model_name, model_path, backend, engine))
    row = con.execute(
        "SELECT id FROM models WHERE model_name=? AND model_path=? AND backend=? AND engine=?",
        (model_name, model_path, backend, engine),
    ).fetchone()
    return row[0]

# JSON 파싱 시 engine 필드 읽기
engine = data.get("engine", "mediapipe")
model_id = upsert_model(con, model_name, model_path, backend, engine)
```

### 6.3 DB 마이그레이션

```sql
-- Phase 5 migration
ALTER TABLE models ADD COLUMN engine TEXT NOT NULL DEFAULT 'mediapipe';

-- UNIQUE 제약 재생성 (SQLite는 ALTER로 UNIQUE 변경 불가 → 테이블 재생성)
-- ingest.py의 DDL이 CREATE IF NOT EXISTS이므로, 기존 테이블 drop 없이
-- 새 컬럼만 추가하면 기존 데이터는 'mediapipe'로 채워짐
```

기존 `ingest.py`의 `_ensure_columns()` 패턴을 확장:

```python
def _ensure_columns(con: sqlite3.Connection) -> None:
    """기존 테이블에 Phase 5 컬럼이 없으면 추가."""
    # 기존 Phase 4a 마이그레이션 로직...

    # Phase 5: models.engine
    cols = {row[1] for row in con.execute("PRAGMA table_info(models)").fetchall()}
    if "engine" not in cols:
        con.execute("ALTER TABLE models ADD COLUMN engine TEXT NOT NULL DEFAULT 'mediapipe'")
        logger.info("Added 'engine' column to models table")
```

### 6.4 sync_results.py — 변경 없음

결과 JSON 구조가 동일하므로 sync 로직에 영향 없음.

### 6.5 response_validator.py — 변경 없음

검증 로직은 응답 텍스트 기반. 엔진 종류와 무관.

### 6.6 shuttle.py — 변경 없음

`adb push`는 파일 확장자에 무관. `.gguf` 파일도 동일하게 push.

## 7. Dashboard / API 변경

### 7.1 models 테이블 확장 반영

```python
# api/schemas.py — ResultItem 확장 (선택)
class ResultItem(BaseModel):
    # ... 기존 필드
    engine: str = "mediapipe"  # ✨ NEW (optional, 하위 호환)
```

### 7.2 API 필터 확장 (선택)

```
GET /api/results?engine=llamacpp        # llama.cpp 결과만
GET /api/results?engine=mediapipe       # MediaPipe 결과만
GET /api/results                         # 전체 (기존 호환)
```

### 7.3 Dashboard 변경 (최소)

- Overview KPI: 엔진 구분 없이 전체 통계 (기존 동작)
- FilterBar: `engine` 드롭다운 추가 (선택, Phase 5 완료 후)
- Raw Data: `engine` 컬럼 자동 표시 (API 응답에 포함되면)
- Compare: 모델명에 `.task`/`.gguf` 확장자가 자연스럽게 구분됨

## 8. GGUF 모델의 Chat Template 처리

### 8.1 문제

MediaPipe `.task` 모델은 chat template이 모델 내부에 포함. 프롬프트를 raw text로 넘기면 모델이 알아서 처리한다.

GGUF 모델은 **chat template 적용이 호출자 책임**. 모델마다 다른 포맷:
- Gemma: `<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n`
- Qwen: `<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n`
- Phi: `<|user|>\n{prompt}<|end|>\n<|assistant|>\n`
- Llama: `<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n`

### 8.2 해결책: llama.cpp 내장 chat template 활용

llama.cpp의 `llama_chat_apply_template()` API를 사용하면 GGUF 메타데이터에 포함된 chat template을 자동 적용할 수 있다. JNI에서 이 함수를 호출하여 프롬프트를 변환 후 추론에 넘긴다.

```c
// llama-jni.cpp 내부
// 1. 모델 로드 후 chat template 가져오기
const char* tmpl = llama_model_chat_template(model, nullptr);

// 2. 프롬프트에 chat template 적용
std::vector<llama_chat_message> messages = {
    {"user", prompt_cstr}
};
char buf[4096];
int len = llama_chat_apply_template(
    tmpl, messages.data(), messages.size(),
    true,  // add_generation_prompt
    buf, sizeof(buf)
);
std::string formatted_prompt(buf, len);

// 3. formatted_prompt로 추론 실행
```

**fallback**: chat template이 GGUF에 없는 경우 → raw prompt 그대로 사용 + 로그 경고.

### 8.3 test_config.json에서 chat_template 오버라이드 (선택)

```json
{
  "engine_params": {
    "chat_template": "chatml",
    // 또는 커스텀:
    "chat_template_str": "<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
  }
}
```

MVP에서는 llama.cpp 내장 자동 감지만 구현. 오버라이드는 필요 시 추가.

## 9. Error Handling

### 9.1 엔진 레벨 에러

| 상황 | 처리 |
|------|------|
| GGUF 로드 실패 (호환 불가/손상) | `saveError()` → JSON에 에러 기록. 다음 테스트 계속 |
| OOM (모델이 디바이스 메모리 초과) | try-catch → 에러 JSON. llama.cpp는 mmap으로 부분 로드 시도 |
| JNI 크래시 (SIGSEGV 등) | UncaughtExceptionHandler에서 catch 시도. 못 잡으면 앱 재시작, runner.py의 timeout이 failsafe |
| 엔진 타입 미인식 | MainActivity에서 fallback → 에러 JSON + 로그 |
| chat template 미지원 모델 | 경고 로그 + raw prompt로 추론 (결과 품질은 낮을 수 있음) |

### 9.2 runner.py 에러

| 상황 | 처리 |
|------|------|
| engine 미지정 + 확장자 미인식 | 해당 모델 스킵 + 에러 로그 |
| engine_params JSON 파싱 실패 | 기본값 사용 + 경고 로그 |
| llama.cpp 엔진인데 앱에 NDK 빌드 안 됨 | 앱 크래시 → runner.py timeout → 에러 JSON |

## 10. Implementation Order

```
Step 1: InferenceEngine 인터페이스 + MediaPipeEngine 리팩토링
        → InferenceEngine.kt 작성
        → LlmRunner.kt → MediaPipeEngine.kt로 리팩토링
        → MainActivity.kt에서 엔진 선택 로직 추가 (mediapipe만)
        → 기존 테스트 통과 확인 (회귀 없음)

Step 2: llama.cpp submodule + NDK 빌드 설정
        → git submodule add llama.cpp
        → CMakeLists.txt 작성
        → build.gradle.kts에 externalNativeBuild 추가
        → 빌드 성공 확인 (arm64-v8a .so 생성)

Step 3: JNI 바인딩 + LlamaCpp.kt
        → llama-jni.cpp 작성 (loadModel, freeModel, generate)
        → LlamaCpp.kt (object + external fun 선언)
        → 간단한 GGUF 모델로 JNI 호출 테스트

Step 4: LlamaCppEngine 구현
        → LlamaCppEngine.kt 작성 (InferenceEngine 구현)
        → chat template 자동 적용 (llama_chat_apply_template)
        → InferenceMetrics 수집 로직 구현
        → ADB 수동 테스트: GGUF 모델 push → am start → 결과 JSON 확인

Step 5: test_config.json 스키마 확장 + runner.py 수정
        → test_config.json에 engine, engine_params 필드 추가
        → runner.py에서 engine/engine_params 파싱 + Intent extra 전달
        → 자동 감지 fallback 구현
        → E2E 테스트: 동일 config에 .task + .gguf 모델 혼합 → 파이프라인 전체 실행

Step 6: ingest.py + DB 마이그레이션
        → models 테이블에 engine 컬럼 추가
        → upsert_model 확장
        → _ensure_columns()에 Phase 5 마이그레이션 추가
        → ingest → DB 확인

Step 7: API/Dashboard 최소 변경
        → ResultItem에 engine 필드 추가
        → FilterBar에 engine 드롭다운 추가 (선택)

Step 8: CI/CD + 문서
        → benchmark.yml: git submodule checkout step 추가
        → README.md 업데이트 (GGUF 모델 사용법)
        → APK 빌드 + 배포 테스트
```

## 11. Risk Assessment

| 리스크 | 영향 | 대응 |
|--------|------|------|
| llama.cpp NDK 빌드 실패 | 높음 | llama.android 예제가 검증됨. ABI 필터를 arm64-v8a로 제한하여 복잡도 낮춤 |
| JNI 크래시 (메모리 관련) | 중간 | UncaughtExceptionHandler + runner.py timeout failsafe. 모델 크기 제한 권장 |
| APK 크기 증가 | 낮음 | llama.cpp .so는 ~10MB. 앱 전체 크기 크게 증가하지 않음 |
| 기존 MediaPipe 엔진 회귀 | 중간 | Step 1에서 리팩토링 후 기존 테스트 전체 통과 확인 필수 |
| GGUF 모델 호환성 문제 | 중간 | llama.cpp 버전을 태그로 고정. 지원 양자화 목록 문서화 |
| Vulkan GPU 가속 불안정 | 낮음 | MVP는 CPU only. Vulkan은 별도 Step에서 테스트 후 활성화 |
| 빌드 시간 증가 | 낮음 | llama.cpp C++ 컴파일에 2~5분 추가. CI에서는 캐시 활용 |

## 12. Extension Points

```
Phase 5.1 (Vulkan GPU 가속)
  └─→ CMakeLists.txt에 GGML_VULKAN=ON
  └─→ engine_params.n_gpu_layers > 0 시 Vulkan 오프로드
  └─→ S25/S26의 Adreno/Mali GPU 벤치마크

Phase 5.2 (추가 엔진)
  └─→ InferenceEngine 구현체 추가로 확장 가능:
      - MlcLlmEngine (MLC LLM)
      - ExecuTorchEngine (Meta ExecuTorch)
      - QnnEngine (Qualcomm QNN SDK)

Phase 5.3 (양자화 비교 강화)
  └─→ 동일 GGUF 모델의 Q4_K_M vs Q5_K_M vs Q8_0 비교
  └─→ response_validator의 quant_diff 로직 자동 활용
  └─→ engine_params 차이에 따른 성능 비교

향후 확장:
  └─→ chat_template 오버라이드 (test_config.json)
  └─→ KV cache 양자화 (llama.cpp flash attention)
  └─→ 멀티모달 GGUF 지원 (llava 등)
```

## 13. Tech Stack (Phase 5 추가분)

| Layer | Tech | Why |
|-------|------|-----|
| **Native Engine** | llama.cpp (C/C++) | 업계 표준 GGUF 추론 엔진. 활발한 개발, ARM 최적화 우수 |
| **JNI Binding** | Android NDK + CMake | llama.android 참조 구현 검증됨. 별도 빌드 시스템 불필요 |
| **소스 관리** | git submodule | 버전 고정 + 업데이트 용이. 별도 빌드 아티팩트 관리 불필요 |
| **GPU 가속** | Vulkan (Phase 5.1) | OpenCL 대비 Android 지원 안정적. Adreno/Mali 호환 |

※ DB, API, Dashboard, CI/CD 스택은 Phase 1~4와 동일. 추가 Python 의존성 없음.

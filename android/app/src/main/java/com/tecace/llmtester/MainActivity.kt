package com.tecace.llmtester

import android.os.Build
import android.os.Bundle
import android.util.Log
import androidx.annotation.RequiresApi
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import org.json.JSONObject

class MainActivity : AppCompatActivity() {
    private val TAG = "LLM_TESTER"
    private var engine: InferenceEngine? = null

    @RequiresApi(Build.VERSION_CODES.S)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            Log.e(TAG, "UNCAUGHT on thread [${thread.name}]: ${throwable.message}")
            saveError("UNCAUGHT", throwable.stackTraceToString())
        }

        if (!intent.hasExtra("input_prompt") || !intent.hasExtra("model_path")) {
            Log.w(TAG, ">>> No test intent extras found. Skipping (likely -S restart ghost launch).")
            finishAffinity()
            return
        }

        val prompt = intent.getStringExtra("input_prompt")!!
        val modelPath = intent.getStringExtra("model_path")!!
        val maxTokens = intent.getIntExtra("max_tokens", 1024)
        val backendStr = intent.getStringExtra("backend") ?: "CPU"
        val engineType = intent.getStringExtra("engine") ?: autoDetectEngine(modelPath)
        val engineParamsJson = intent.getStringExtra("engine_params") ?: "{}"

        val engineParams = parseEngineParams(engineParamsJson).toMutableMap()
        engineParams.putIfAbsent("backend", backendStr)

        val promptId = intent.getStringExtra("prompt_id") ?: ""
        val promptCategory = intent.getStringExtra("prompt_category") ?: ""
        val promptLang = intent.getStringExtra("prompt_lang") ?: ""

        Log.d(TAG, "==== Test Start ====")
        Log.d(TAG, "Device: ${Build.MANUFACTURER} ${Build.MODEL} (${Build.PRODUCT})")
        Log.d(TAG, "SOC: ${Build.SOC_MANUFACTURER} ${Build.SOC_MODEL}")
        Log.d(TAG, "Android: ${Build.VERSION.RELEASE} (SDK ${Build.VERSION.SDK_INT})")
        Log.d(TAG, "Engine: $engineType")
        Log.d(TAG, "PromptID: $promptId | Category: $promptCategory | Lang: $promptLang")
        Log.d(TAG, "Prompt: $prompt")
        Log.d(TAG, "ModelPath: $modelPath")
        Log.d(TAG, "MaxTokens: $maxTokens")
        Log.d(TAG, "Backend: $backendStr")
        Log.d(TAG, "EngineParams: $engineParamsJson")
        Log.d(TAG, "Available processors: ${Runtime.getRuntime().availableProcessors()}")
        Log.d(TAG, "Max heap: ${Runtime.getRuntime().maxMemory() / 1024 / 1024} MB")

        engine = createEngine(engineType)

        lifecycleScope.launch {
            try {
                val modelFile = File(modelPath)
                Log.d(TAG, "Model file exists: ${modelFile.exists()}")
                Log.d(TAG, "Model file size: ${modelFile.length() / 1024 / 1024} MB")

                val activeEngine = engine!!

                Log.d(TAG, ">>> ${activeEngine.engineName}.init() START")
                activeEngine.init(modelPath, maxTokens, engineParams)
                Log.d(TAG, ">>> ${activeEngine.engineName}.init() DONE — ${activeEngine.initTimeMs}ms")

                val inputTokenCount = estimateTokenCount(prompt)
                Log.d(TAG, ">>> Estimated input tokens: $inputTokenCount")

                Log.d(TAG, ">>> ${activeEngine.engineName}.generate() START")
                val metrics = activeEngine.generate(prompt, inputTokenCount)
                Log.d(TAG, ">>> ${activeEngine.engineName}.generate() DONE — ${metrics.totalLatencyMs}ms")

                saveResult(prompt, metrics, modelPath, backendStr, promptId, promptCategory,
                    promptLang, activeEngine.engineName, activeEngine.initTimeMs)
            } catch (e: Exception) {
                Log.e(TAG, "CAUGHT EXCEPTION: ${e::class.java.name}: ${e.message}")
                Log.e(TAG, "Stacktrace:\n${e.stackTraceToString()}")
                saveError(prompt, "${e::class.java.name}: ${e.message}\n${e.stackTraceToString()}")
            } finally {
                engine?.close()
                Log.d(TAG, "==== Test Finished ====")
                finishAffinity()
            }
        }
    }

    private fun createEngine(engineType: String): InferenceEngine {
        return when (engineType.lowercase()) {
            "mediapipe" -> MediaPipeEngine(this)
            "llamacpp" -> LlamaCppEngine(this)
            else -> {
                Log.w(TAG, ">>> Unknown engine '$engineType', falling back to mediapipe")
                MediaPipeEngine(this)
            }
        }
    }

    private fun autoDetectEngine(modelPath: String): String {
        return when {
            modelPath.endsWith(".task") -> "mediapipe"
            modelPath.endsWith(".gguf") -> "llamacpp"
            else -> {
                Log.w(TAG, ">>> Cannot auto-detect engine for: $modelPath, defaulting to mediapipe")
                "mediapipe"
            }
        }
    }

    private fun parseEngineParams(json: String): Map<String, String> {
        return try {
            val obj = JSONObject(json)
            obj.keys().asSequence().associateWith { obj.getString(it) }
        } catch (e: Exception) {
            Log.w(TAG, ">>> Failed to parse engine_params: ${e.message}")
            emptyMap()
        }
    }

    private fun estimateTokenCount(text: String): Int {
        val wordCount = text.trim().split(Regex("\\s+")).size
        val cjkCount = text.count { it.code in 0x4E00..0x9FFF || it.code in 0xAC00..0xD7AF || it.code in 0x3040..0x30FF }
        return if (cjkCount > text.length / 3) {
            (text.length * 0.7).toInt().coerceAtLeast(1)
        } else {
            (wordCount * 1.3).toInt().coerceAtLeast(1)
        }
    }

    @RequiresApi(Build.VERSION_CODES.S)
    private fun getDeviceInfo(): JSONObject {
        return JSONObject().apply {
            put("manufacturer", Build.MANUFACTURER)
            put("model", Build.MODEL)
            put("product", Build.PRODUCT)
            put("soc", "${Build.SOC_MANUFACTURER} ${Build.SOC_MODEL}")
            put("android_version", Build.VERSION.RELEASE)
            put("sdk_int", Build.VERSION.SDK_INT)
            put("cpu_cores", Runtime.getRuntime().availableProcessors())
            put("max_heap_mb", Runtime.getRuntime().maxMemory() / 1024 / 1024)
        }
    }

    private fun getResultFile(): File {
        val resultDir = File(filesDir, "results")
        if (!resultDir.exists()) resultDir.mkdirs()
        val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.getDefault()).format(Date())
        return File(resultDir, "result_$timestamp.json")
    }

    @RequiresApi(Build.VERSION_CODES.S)
    private fun saveResult(
        prompt: String,
        metrics: InferenceMetrics,
        modelPath: String,
        backend: String,
        promptId: String,
        promptCategory: String,
        promptLang: String,
        engineName: String,
        initTimeMs: Long
    ) {
        val json = JSONObject().apply {
            put("status", "success")
            put("engine", engineName)
            put("prompt_id", promptId)
            put("prompt_category", promptCategory)
            put("prompt_lang", promptLang)
            put("model_path", modelPath)
            put("model_name", File(modelPath).name)
            put("backend", backend)
            put("device", getDeviceInfo())
            put("prompt", prompt)
            put("response", metrics.response)
            put("latency_ms", metrics.totalLatencyMs)
            put("init_time_ms", initTimeMs)
            put("metrics", metrics.toJson())
            put("timestamp", System.currentTimeMillis())
        }
        val file = getResultFile()
        file.writeText(json.toString(2))
        Log.d(TAG, ">>> Result saved: ${file.absolutePath}")
    }

    @RequiresApi(Build.VERSION_CODES.S)
    private fun saveError(prompt: String, error: String) {
        val json = JSONObject().apply {
            put("status", "error")
            put("engine", engine?.engineName ?: "unknown")
            put("device", getDeviceInfo())
            put("prompt", prompt)
            put("error", error)
            put("timestamp", System.currentTimeMillis())
        }
        getResultFile().writeText(json.toString(2))
    }
}
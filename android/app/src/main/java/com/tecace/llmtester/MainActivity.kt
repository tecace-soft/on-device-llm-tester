package com.tecace.llmtester

import android.os.Build
import android.os.Bundle
import android.util.Log
import androidx.annotation.RequiresApi
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.google.mediapipe.tasks.genai.llminference.LlmInference
import kotlinx.coroutines.launch
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import org.json.JSONObject

class MainActivity : AppCompatActivity() {
    private val TAG = "LLM_TESTER"
    private lateinit var llmRunner: LlmRunner

    @RequiresApi(Build.VERSION_CODES.S)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            Log.e(TAG, "UNCAUGHT on thread [${thread.name}]: ${throwable.message}")
            saveError("UNCAUGHT", throwable.stackTraceToString())
        }

        llmRunner = LlmRunner(this)

        if (!intent.hasExtra("input_prompt") || !intent.hasExtra("model_path")) {
            Log.w(TAG, ">>> No test intent extras found. Skipping (likely -S restart ghost launch).")
            finishAffinity()
            return
        }

        val prompt = intent.getStringExtra("input_prompt")!!
        val modelPath = intent.getStringExtra("model_path")!!
        val maxTokens = intent.getIntExtra("max_tokens", 1024)
        val backendStr = intent.getStringExtra("backend") ?: "CPU"
        val backend = when (backendStr.uppercase()) {
            "GPU" -> LlmInference.Backend.GPU
            else  -> LlmInference.Backend.CPU
        }

        val promptId = intent.getStringExtra("prompt_id") ?: ""
        val promptCategory = intent.getStringExtra("prompt_category") ?: ""
        val promptLang = intent.getStringExtra("prompt_lang") ?: ""

        Log.d(TAG, "==== Test Start ====")
        Log.d(TAG, "Device: ${Build.MANUFACTURER} ${Build.MODEL} (${Build.PRODUCT})")
        Log.d(TAG, "SOC: ${Build.SOC_MANUFACTURER} ${Build.SOC_MODEL}")
        Log.d(TAG, "Android: ${Build.VERSION.RELEASE} (SDK ${Build.VERSION.SDK_INT})")
        Log.d(TAG, "PromptID: $promptId | Category: $promptCategory | Lang: $promptLang")
        Log.d(TAG, "Prompt: $prompt")
        Log.d(TAG, "ModelPath: $modelPath")
        Log.d(TAG, "MaxTokens: $maxTokens")
        Log.d(TAG, "Backend: $backendStr")
        Log.d(TAG, "Available processors: ${Runtime.getRuntime().availableProcessors()}")
        Log.d(TAG, "Max heap: ${Runtime.getRuntime().maxMemory() / 1024 / 1024} MB")

        lifecycleScope.launch {
            try {
                val modelFile = File(modelPath)
                Log.d(TAG, "Model file exists: ${modelFile.exists()}")
                Log.d(TAG, "Model file size: ${modelFile.length() / 1024 / 1024} MB")

                Log.d(TAG, ">>> LlmRunner.init() START")
                llmRunner.init(modelPath, maxTokens, backend)
                Log.d(TAG, ">>> LlmRunner.init() DONE — ${llmRunner.initTimeMs}ms")

                val inputTokenCount = estimateTokenCount(prompt)
                Log.d(TAG, ">>> Estimated input tokens: $inputTokenCount")

                Log.d(TAG, ">>> LlmRunner.generate() START")
                val metrics = llmRunner.generate(prompt, inputTokenCount)
                Log.d(TAG, ">>> LlmRunner.generate() DONE — ${metrics.totalLatencyMs}ms")

                saveResult(prompt, metrics, modelPath, backendStr, promptId, promptCategory, promptLang)
            } catch (e: Exception) {
                Log.e(TAG, "CAUGHT EXCEPTION: ${e::class.java.name}: ${e.message}")
                Log.e(TAG, "Stacktrace:\n${e.stackTraceToString()}")
                saveError(prompt, "${e::class.java.name}: ${e.message}\n${e.stackTraceToString()}")
            } finally {
                Log.d(TAG, "==== Test Finished ====")
                finishAffinity()
            }
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
        promptLang: String
    ) {
        val json = JSONObject().apply {
            put("status", "success")
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
            put("init_time_ms", llmRunner.initTimeMs)
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
            put("device", getDeviceInfo())
            put("prompt", prompt)
            put("error", error)
            put("timestamp", System.currentTimeMillis())
        }
        getResultFile().writeText(json.toString(2))
    }
}
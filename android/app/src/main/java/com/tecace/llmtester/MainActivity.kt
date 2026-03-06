package com.tecace.llmtester

import android.os.Build
import android.os.Bundle
import android.util.Log
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

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            Log.e(TAG, "UNCAUGHT on thread [${thread.name}]: ${throwable.message}")
            saveError("UNCAUGHT", throwable.stackTraceToString())
        }

        llmRunner = LlmRunner(this)

        val prompt = intent.getStringExtra("input_prompt") ?: "Hello"
        val modelPath = intent.getStringExtra("model_path")
            ?: "/data/local/tmp/llm_test/models/gemma3-1b-it-int4.task"
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
                Log.d(TAG, ">>> LlmRunner.init() DONE")

                Log.d(TAG, ">>> LlmRunner.generate() START")
                val startTime = System.currentTimeMillis()
                val response = llmRunner.generate(prompt)
                val latency = System.currentTimeMillis() - startTime
                Log.d(TAG, ">>> LlmRunner.generate() DONE — ${latency}ms")

                saveResult(prompt, response, latency, modelPath, backendStr, promptId, promptCategory, promptLang)
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
        val timestamp = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.getDefault()).format(Date())
        return File(resultDir, "result_$timestamp.json")
    }

    private fun saveResult(
        prompt: String,
        response: String,
        latency: Long,
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
            put("response", response)
            put("latency_ms", latency)
            put("timestamp", System.currentTimeMillis())
        }
        getResultFile().writeText(json.toString(2))
    }

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
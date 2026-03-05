package com.tecace.llmtester

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

        Log.d(TAG, "==== Test Start ====")
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

                saveResult(prompt, response, latency, modelPath, backendStr)
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
        backend: String
    ) {
        val json = JSONObject().apply {
            put("status", "success")
            put("model_path", modelPath)
            put("backend", backend)
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
            put("prompt", prompt)
            put("error", error)
            put("timestamp", System.currentTimeMillis())
        }
        getResultFile().writeText(json.toString(2))
    }
}
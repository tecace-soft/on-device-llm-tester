package com.tecace.llmtester

import com.google.mediapipe.tasks.genai.llminference.LlmInference
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import android.util.Log
import java.io.File

class LlmRunner(private val context: android.content.Context) {
    private val TAG = "LLM_TESTER"
    private var llmInference: LlmInference? = null
    private var activeBackend: LlmInference.Backend? = null

    suspend fun init(
        modelPath: String,
        maxTokens: Int = 1024,
        preferredBackend: LlmInference.Backend = LlmInference.Backend.CPU
    ) = withContext(Dispatchers.IO) {
        if (llmInference != null) return@withContext

        val modelName = File(modelPath).name
        val cacheFile = File(context.cacheDir, "$modelName.xnnpack_cache")
        if (cacheFile.exists()) {
            cacheFile.delete()
            Log.d(TAG, ">>> Deleted stale cache: ${cacheFile.name}")
        }

        Log.d(TAG, ">>> Trying backend: $preferredBackend")
        val options = LlmInference.LlmInferenceOptions.builder()
            .setModelPath(modelPath)
            .setPreferredBackend(preferredBackend)
            .setMaxTokens(maxTokens)
            .build()

        llmInference = LlmInference.createFromOptions(context, options)
        activeBackend = preferredBackend
        Log.d(TAG, ">>> Backend $preferredBackend: INIT SUCCESS")
    }

    suspend fun generate(prompt: String): String = withContext(Dispatchers.IO) {
        val engine = llmInference ?: return@withContext "Error: Engine not initialized"
        Log.d(TAG, "generate() start | backend=$activeBackend | prompt_len=${prompt.length}")

        val startTime = System.currentTimeMillis()
        val heartbeat = Thread {
            var tick = 0
            while (!Thread.currentThread().isInterrupted) {
                try {
                    Thread.sleep(5000)
                    tick++
                    Log.d(TAG, ">>> generate() still running... ${tick * 5}s elapsed")
                } catch (e: InterruptedException) {
                    break
                }
            }
        }.also { it.isDaemon = true; it.start() }

        return@withContext try {
            val result = engine.generateResponse(prompt)
            val elapsed = System.currentTimeMillis() - startTime
            Log.d(TAG, ">>> generate() DONE | ${elapsed}ms | response_len=${result.length}")
            result
        } finally {
            heartbeat.interrupt()
        }
    }
}
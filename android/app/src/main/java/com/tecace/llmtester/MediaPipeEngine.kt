package com.tecace.llmtester

import com.google.mediapipe.tasks.genai.llminference.LlmInference
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import android.os.Debug
import android.util.Log
import java.io.File
import kotlin.coroutines.resume

class MediaPipeEngine(private val context: android.content.Context) : InferenceEngine {
    private val TAG = "LLM_TESTER"
    private var llmInference: LlmInference? = null
    private var activeBackend: LlmInference.Backend? = null

    override val engineName: String = "mediapipe"
    override var initTimeMs: Long = 0L
        private set

    override suspend fun init(
        modelPath: String,
        maxTokens: Int,
        params: Map<String, String>
    ) = withContext(Dispatchers.IO) {
        if (llmInference != null) return@withContext

        val backendStr = params["backend"] ?: "CPU"
        val preferredBackend = when (backendStr.uppercase()) {
            "GPU" -> LlmInference.Backend.GPU
            else -> LlmInference.Backend.CPU
        }

        val modelName = File(modelPath).name
        val cacheFile = File(context.cacheDir, "$modelName.xnnpack_cache")
        if (cacheFile.exists()) {
            cacheFile.delete()
            Log.d(TAG, ">>> Deleted stale cache: ${cacheFile.name}")
        }

        Log.d(TAG, ">>> [MediaPipe] Trying backend: $preferredBackend")
        val options = LlmInference.LlmInferenceOptions.builder()
            .setModelPath(modelPath)
            .setPreferredBackend(preferredBackend)
            .setMaxTokens(maxTokens)
            .build()

        val start = System.currentTimeMillis()
        llmInference = LlmInference.createFromOptions(context, options)
        initTimeMs = System.currentTimeMillis() - start

        activeBackend = preferredBackend
        Log.d(TAG, ">>> [MediaPipe] Backend $preferredBackend: INIT SUCCESS (${initTimeMs}ms)")
    }

    override suspend fun generate(prompt: String, inputTokenCount: Int): InferenceMetrics =
        withContext(Dispatchers.IO) {
            val engine = llmInference
                ?: throw IllegalStateException("Engine not initialized")
            Log.d(TAG, "generate() start | engine=mediapipe | backend=$activeBackend | prompt_len=${prompt.length}")

            val runtime = Runtime.getRuntime()
            var peakJavaMem = (runtime.totalMemory() - runtime.freeMemory()) / 1024 / 1024
            var peakNativeMem = Debug.getNativeHeapAllocatedSize() / 1024 / 1024

            val tokenTimestamps = mutableListOf<Long>()
            val chunks = mutableListOf<String>()
            val genStartTime = System.currentTimeMillis()

            suspendCancellableCoroutine { cont ->
                engine.generateResponseAsync(prompt) { partialResult, done ->
                    val now = System.currentTimeMillis()

                    val currentJavaMem = (runtime.totalMemory() - runtime.freeMemory()) / 1024 / 1024
                    if (currentJavaMem > peakJavaMem) peakJavaMem = currentJavaMem
                    val currentNativeMem = Debug.getNativeHeapAllocatedSize() / 1024 / 1024
                    if (currentNativeMem > peakNativeMem) peakNativeMem = currentNativeMem

                    if (partialResult.isNotEmpty()) {
                        tokenTimestamps.add(now)
                        chunks.add(partialResult)
                    }

                    if (done) {
                        val totalLatency = now - genStartTime
                        val response = chunks.joinToString("")
                        val outputTokenCount = tokenTimestamps.size

                        val ttft = if (tokenTimestamps.isNotEmpty()) {
                            tokenTimestamps.first() - genStartTime
                        } else 0L

                        val decodeTime = if (tokenTimestamps.size > 1) {
                            tokenTimestamps.last() - tokenTimestamps.first()
                        } else 0L

                        val prefillTime = ttft

                        val prefillTps = if (prefillTime > 0) {
                            inputTokenCount.toDouble() / (prefillTime / 1000.0)
                        } else 0.0

                        val decodeTps = if (decodeTime > 0 && outputTokenCount > 1) {
                            (outputTokenCount - 1).toDouble() / (decodeTime / 1000.0)
                        } else 0.0

                        val interTokenLatencies = mutableListOf<Long>()
                        for (i in 1 until tokenTimestamps.size) {
                            interTokenLatencies.add(tokenTimestamps[i] - tokenTimestamps[i - 1])
                        }

                        Log.d(TAG, ">>> generate() DONE | total=${totalLatency}ms | ttft=${ttft}ms | decode=${decodeTime}ms | out_tokens=$outputTokenCount | decode_tps=${"%.1f".format(decodeTps)}")

                        val metrics = InferenceMetrics(
                            response = response,
                            totalLatencyMs = totalLatency,
                            ttftMs = ttft,
                            prefillTimeMs = prefillTime,
                            decodeTimeMs = decodeTime,
                            inputTokenCount = inputTokenCount,
                            outputTokenCount = outputTokenCount,
                            prefillTps = prefillTps,
                            decodeTps = decodeTps,
                            interTokenLatenciesMs = interTokenLatencies,
                            peakJavaMemoryMb = peakJavaMem,
                            peakNativeMemoryMb = peakNativeMem
                        )
                        cont.resume(metrics)
                    }
                }
            }
        }

    override fun close() {
        try {
            llmInference?.close()
        } catch (e: Exception) {
            Log.w(TAG, ">>> [MediaPipe] close() error: ${e.message}")
        }
        llmInference = null
        activeBackend = null
    }
}
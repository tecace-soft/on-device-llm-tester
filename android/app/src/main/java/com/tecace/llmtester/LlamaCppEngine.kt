package com.tecace.llmtester

import android.os.Debug
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class LlamaCppEngine(private val context: android.content.Context) : InferenceEngine {
    private val TAG = "LLM_TESTER"
    private var sessionPtr: Long = 0L
    private var maxTokens: Int = 1024
    private var temperature: Float = 0.7f
    private var topP: Float = 0.95f
    private var topK: Int = 40
    private var repeatPenalty: Float = 1.1f

    override val engineName: String = "llamacpp"
    override var initTimeMs: Long = 0L
        private set

    override suspend fun init(
        modelPath: String,
        maxTokens: Int,
        params: Map<String, String>
    ) = withContext(Dispatchers.IO) {
        if (sessionPtr != 0L) return@withContext

        this@LlamaCppEngine.maxTokens = maxTokens

        val nGpuLayers = params["n_gpu_layers"]?.toIntOrNull() ?: 0
        val nCtx = params["n_ctx"]?.toIntOrNull() ?: 2048
        val nThreads = params["n_threads"]?.toIntOrNull()
            ?: Runtime.getRuntime().availableProcessors().coerceAtMost(4)

        temperature = params["temperature"]?.toFloatOrNull() ?: 0.7f
        topP = params["top_p"]?.toFloatOrNull() ?: 0.95f
        topK = params["top_k"]?.toIntOrNull() ?: 40
        repeatPenalty = params["repeat_penalty"]?.toFloatOrNull() ?: 1.1f

        Log.d(TAG, ">>> [llama.cpp] Loading model: $modelPath")
        Log.d(TAG, ">>> [llama.cpp] nGpuLayers=$nGpuLayers nCtx=$nCtx nThreads=$nThreads")

        val start = System.currentTimeMillis()
        sessionPtr = LlamaCpp.loadModel(modelPath, nGpuLayers, nCtx, nThreads)
        initTimeMs = System.currentTimeMillis() - start

        if (sessionPtr == 0L) {
            throw IllegalStateException("Failed to load GGUF model: $modelPath")
        }

        Log.d(TAG, ">>> [llama.cpp] INIT SUCCESS (${initTimeMs}ms)")
    }

    override suspend fun generate(prompt: String, inputTokenCount: Int): InferenceMetrics =
        withContext(Dispatchers.IO) {
            if (sessionPtr == 0L) {
                throw IllegalStateException("Engine not initialized")
            }

            Log.d(TAG, "generate() start | engine=llamacpp | prompt_len=${prompt.length}")

            // Apply chat template
            val formattedPrompt = LlamaCpp.applyChat(sessionPtr, prompt)
            Log.d(TAG, ">>> [llama.cpp] formatted prompt len=${formattedPrompt.length}")

            val runtime = Runtime.getRuntime()
            var peakJavaMem = (runtime.totalMemory() - runtime.freeMemory()) / 1024 / 1024
            var peakNativeMem = Debug.getNativeHeapAllocatedSize() / 1024 / 1024

            val tokenTimestamps = mutableListOf<Long>()
            val chunks = mutableListOf<String>()
            val genStartTime = System.currentTimeMillis()

            LlamaCpp.generate(
                sessionPtr = sessionPtr,
                prompt = formattedPrompt,
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

                        val currentJavaMem = (runtime.totalMemory() - runtime.freeMemory()) / 1024 / 1024
                        if (currentJavaMem > peakJavaMem) peakJavaMem = currentJavaMem
                        val currentNativeMem = Debug.getNativeHeapAllocatedSize() / 1024 / 1024
                        if (currentNativeMem > peakNativeMem) peakNativeMem = currentNativeMem

                        return true
                    }
                }
            )

            val response = chunks.joinToString("")
            val outputTokenCount = tokenTimestamps.size
            val now = System.currentTimeMillis()
            val totalLatency = now - genStartTime

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

            InferenceMetrics(
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
        }

    override fun close() {
        if (sessionPtr != 0L) {
            LlamaCpp.freeModel(sessionPtr)
            sessionPtr = 0L
            Log.d(TAG, ">>> [llama.cpp] session freed")
        }
    }
}
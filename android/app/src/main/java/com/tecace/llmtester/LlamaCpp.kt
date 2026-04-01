package com.tecace.llmtester

object LlamaCpp {
    init {
        System.loadLibrary("llama-android")
    }

    external fun loadModel(modelPath: String, nGpuLayers: Int = 0, nCtx: Int = 2048, nThreads: Int = 4): Long

    external fun freeModel(sessionPtr: Long)

    external fun applyChat(sessionPtr: Long, prompt: String): String

    external fun generate(
        sessionPtr: Long,
        prompt: String,
        maxTokens: Int,
        temperature: Float = 0.7f,
        topP: Float = 0.95f,
        topK: Int = 40,
        repeatPenalty: Float = 1.1f,
        callback: TokenCallback
    ): Int

    interface TokenCallback {
        fun onToken(token: String): Boolean
    }
}
package com.tecace.llmtester

interface InferenceEngine {
    val engineName: String
    val initTimeMs: Long

    suspend fun init(
        modelPath: String,
        maxTokens: Int = 1024,
        params: Map<String, String> = emptyMap()
    )

    suspend fun generate(prompt: String, inputTokenCount: Int): InferenceMetrics

    fun close()
}
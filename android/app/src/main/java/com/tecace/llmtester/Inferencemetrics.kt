package com.tecace.llmtester

import org.json.JSONArray
import org.json.JSONObject

data class InferenceMetrics(
    val response: String,
    val totalLatencyMs: Long,
    val ttftMs: Long,
    val prefillTimeMs: Long,
    val decodeTimeMs: Long,
    val inputTokenCount: Int,
    val outputTokenCount: Int,
    val prefillTps: Double,
    val decodeTps: Double,
    val interTokenLatenciesMs: List<Long>,
    val peakJavaMemoryMb: Long,
    val peakNativeMemoryMb: Long
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("total_latency_ms", totalLatencyMs)
        put("ttft_ms", ttftMs)
        put("prefill_time_ms", prefillTimeMs)
        put("decode_time_ms", decodeTimeMs)
        put("input_token_count", inputTokenCount)
        put("output_token_count", outputTokenCount)
        put("prefill_tps", "%.2f".format(prefillTps).toDouble())
        put("decode_tps", "%.2f".format(decodeTps).toDouble())
        put("peak_java_memory_mb", peakJavaMemoryMb)
        put("peak_native_memory_mb", peakNativeMemoryMb)

        if (interTokenLatenciesMs.isNotEmpty()) {
            val sorted = interTokenLatenciesMs.sorted()
            put("itl_p50_ms", percentile(sorted, 50))
            put("itl_p95_ms", percentile(sorted, 95))
            put("itl_p99_ms", percentile(sorted, 99))
            put("itl_min_ms", sorted.first())
            put("itl_max_ms", sorted.last())
            put("itl_all_ms", JSONArray(interTokenLatenciesMs))
        }
    }

    companion object {
        fun percentile(sorted: List<Long>, p: Int): Long {
            if (sorted.isEmpty()) return 0
            val idx = (p / 100.0 * (sorted.size - 1)).toInt().coerceIn(0, sorted.size - 1)
            return sorted[idx]
        }
    }
}
#include <jni.h>
#include <android/log.h>
#include <string>
#include <vector>
#include <chrono>

#include "llama.h"

#define TAG "LLM_TESTER_JNI"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,  TAG, __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN,  TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

// ── Helpers ──────────────────────────────────────────────────────────────────

static std::string jstring_to_string(JNIEnv *env, jstring jstr) {
    if (!jstr) return "";
    const char *chars = env->GetStringUTFChars(jstr, nullptr);
    std::string result(chars);
    env->ReleaseStringUTFChars(jstr, chars);
    return result;
}

static int64_t now_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
}

// ── JNI Exports ──────────────────────────────────────────────────────────────

extern "C" {

struct LlamaSession {
    llama_model *model;
    llama_context *ctx;
    llama_sampler *smpl;
    int n_ctx;
};

JNIEXPORT jlong JNICALL
Java_com_tecace_llmtester_LlamaCpp_loadModel(
        JNIEnv *env, jobject /* this */,
        jstring jModelPath, jint nGpuLayers, jint nCtx, jint nThreads) {

    std::string model_path = jstring_to_string(env, jModelPath);
    LOGI("loadModel: path=%s  nGpuLayers=%d  nCtx=%d  nThreads=%d",
         model_path.c_str(), nGpuLayers, nCtx, nThreads);

    // ── Redirect llama.cpp logs to Android logcat ──
    llama_log_set([](enum ggml_log_level level, const char *text, void * /*user_data*/) {
        switch (level) {
            case GGML_LOG_LEVEL_ERROR:
                LOGE("%s", text);
                break;
            case GGML_LOG_LEVEL_WARN:
                LOGW("%s", text);
                break;
            default:
                LOGI("%s", text);
                break;
        }
    }, nullptr);

    // ── Backend init (once per process) ──
    LOGI("loadModel: calling ggml_backend_load_all...");
    ggml_backend_load_all();
    LOGI("loadModel: ggml_backend_load_all done");

    // ── Model params ──
    llama_model_params model_params = llama_model_default_params();
    model_params.n_gpu_layers = nGpuLayers;

    LOGI("loadModel: calling llama_model_load_from_file...");
    llama_model *model = llama_model_load_from_file(model_path.c_str(), model_params);
    if (!model) {
        LOGE("loadModel: failed to load %s (llama_model_load_from_file returned null)",
             model_path.c_str());
        return 0;
    }

    // ── Context params ──
    llama_context_params ctx_params = llama_context_default_params();
    ctx_params.n_ctx = nCtx;
    ctx_params.n_threads = nThreads;
    ctx_params.n_threads_batch = nThreads;
    ctx_params.no_perf = false;
    // Note: flash_attn is auto-managed by llama.cpp internally.
    // For models with head_size != 64/128 (e.g. Gemma 3 head_size=256),
    // CPU FA may cause hangs. We disable it via CMake (GGML_CPU_HAS_AVX=OFF won't help).
    // If still hanging, try a non-Gemma3 model or update llama.cpp submodule.

    LOGI("loadModel: creating context...");
    llama_context *ctx = llama_init_from_model(model, ctx_params);
    if (!ctx) {
        LOGE("loadModel: failed to create context");
        llama_model_free(model);
        return 0;
    }

    // ── Sampler (greedy for benchmarking — deterministic) ──
    llama_sampler *smpl = llama_sampler_chain_init(llama_sampler_chain_default_params());
    llama_sampler_chain_add(smpl, llama_sampler_init_greedy());

    auto *session = new LlamaSession{model, ctx, smpl, nCtx};
    const llama_vocab *vocab = llama_model_get_vocab(model);
    LOGI("loadModel: OK  vocab=%d  ctx=%d", llama_vocab_n_tokens(vocab), nCtx);
    return reinterpret_cast<jlong>(session);
}

JNIEXPORT void JNICALL
Java_com_tecace_llmtester_LlamaCpp_freeModel(
        JNIEnv *env, jobject /* this */, jlong sessionPtr) {
    if (sessionPtr == 0) return;
    auto *session = reinterpret_cast<LlamaSession *>(sessionPtr);

    llama_sampler_free(session->smpl);
    llama_free(session->ctx);
    llama_model_free(session->model);
    delete session;
    LOGI("freeModel: released");
}

JNIEXPORT jstring JNICALL
Java_com_tecace_llmtester_LlamaCpp_applyChat(
        JNIEnv *env, jobject /* this */, jlong sessionPtr, jstring jPrompt) {

    if (sessionPtr == 0) return env->NewStringUTF("");
    auto *session = reinterpret_cast<LlamaSession *>(sessionPtr);
    std::string prompt = jstring_to_string(env, jPrompt);

    const char *tmpl = llama_model_chat_template(session->model, nullptr);

    if (tmpl) {
        LOGI("applyChat: using built-in template");
        std::vector<llama_chat_message> messages;
        messages.push_back({"user", prompt.c_str()});

        int len = llama_chat_apply_template(tmpl, messages.data(), messages.size(),
                                            true, nullptr, 0);
        if (len > 0) {
            std::vector<char> buf(len + 1);
            llama_chat_apply_template(tmpl, messages.data(), messages.size(),
                                      true, buf.data(), buf.size());
            buf[len] = '\0';
            LOGI("applyChat: formatted len=%d", len);
            return env->NewStringUTF(buf.data());
        }
        LOGW("applyChat: template returned len=%d, using raw prompt", len);
    } else {
        LOGW("applyChat: no built-in template, using raw prompt");
    }

    return env->NewStringUTF(prompt.c_str());
}

JNIEXPORT jint JNICALL
Java_com_tecace_llmtester_LlamaCpp_generate(
        JNIEnv *env, jobject /* this */,
        jlong sessionPtr, jstring jPrompt, jint maxTokens,
        jfloat temperature, jfloat topP, jint topK, jfloat repeatPenalty,
        jobject callback) {

    if (sessionPtr == 0) return -1;
    auto *session = reinterpret_cast<LlamaSession *>(sessionPtr);
    std::string prompt = jstring_to_string(env, jPrompt);

    LOGI("generate: prompt_len=%zu  max_new=%d", prompt.size(), maxTokens);

    // ── Get callback method ──
    jclass cbClass = env->GetObjectClass(callback);
    jmethodID onTokenMethod = env->GetMethodID(cbClass, "onToken", "(Ljava/lang/String;)Z");
    if (!onTokenMethod) {
        LOGE("generate: onToken method not found");
        return -1;
    }

    // ── Tokenize ──
    const llama_vocab *vocab = llama_model_get_vocab(session->model);
    int n_prompt_tokens = -llama_tokenize(vocab, prompt.c_str(), prompt.size(),
                                          nullptr, 0, true, true);
    if (n_prompt_tokens <= 0) {
        LOGE("generate: tokenization failed, got %d", n_prompt_tokens);
        return -1;
    }

    std::vector<llama_token> tokens(n_prompt_tokens);
    int actual = llama_tokenize(vocab, prompt.c_str(), prompt.size(),
                                tokens.data(), tokens.size(), true, true);

    LOGI("generate: tokenized prompt_tokens=%d (actual=%d)", n_prompt_tokens, actual);

    // Log first few token IDs for debugging
    int log_count = n_prompt_tokens < 10 ? n_prompt_tokens : 10;
    for (int i = 0; i < log_count; i++) {
        LOGI("generate: token[%d] = %d", i, tokens[i]);
    }

    if (n_prompt_tokens >= session->n_ctx) {
        LOGE("generate: prompt (%d tokens) exceeds context (%d)", n_prompt_tokens, session->n_ctx);
        return -1;
    }

    // ── Reset context state ──
    LOGI("generate: clearing KV cache...");
    llama_memory_clear(llama_get_memory(session->ctx), true);
    LOGI("generate: KV cache cleared");

    // ── Reset sampler state ──
    llama_sampler_reset(session->smpl);
    LOGI("generate: sampler reset");

    // ── Prompt eval (prefill) ──
    LOGI("generate: === PREFILL START === (%d tokens)", n_prompt_tokens);
    int64_t t0 = now_ms();

    llama_batch batch = llama_batch_get_one(tokens.data(), tokens.size());
    LOGI("generate: batch created, calling llama_decode for prefill...");
    int rc = llama_decode(session->ctx, batch);
    int64_t t1 = now_ms();
    LOGI("generate: === PREFILL DONE === rc=%d  elapsed=%lldms", rc, (long long)(t1 - t0));

    if (rc != 0) {
        LOGE("generate: prefill decode failed (rc=%d)", rc);
        return -1;
    }

    // ── Decode loop ──
    int n_decoded = 0;
    LOGI("generate: === DECODE LOOP START === max=%d", maxTokens);

    for (int i = 0; i < maxTokens; i++) {
        // Sample next token
        llama_token new_token = llama_sampler_sample(session->smpl, session->ctx, -1);

        // Accept the token in the sampler (critical for state tracking)
        llama_sampler_accept(session->smpl, new_token);

        // Check end of generation
        if (llama_vocab_is_eog(vocab, new_token)) {
            LOGI("generate: EOG token=%d at step %d (decoded %d tokens)", new_token, i, n_decoded);
            break;
        }

        // Convert token to text
        char buf[256];
        int len = llama_token_to_piece(vocab, new_token, buf, sizeof(buf), 0, true);
        if (len < 0) {
            int needed = -len;
            std::vector<char> big_buf(needed + 1);
            llama_token_to_piece(vocab, new_token, big_buf.data(), big_buf.size(), 0, true);
            big_buf[needed] = '\0';
            jstring jToken = env->NewStringUTF(big_buf.data());
            jboolean cont = env->CallBooleanMethod(callback, onTokenMethod, jToken);
            env->DeleteLocalRef(jToken);
            if (!cont) {
                LOGI("generate: callback stop at step %d", i);
                break;
            }
        } else {
            buf[len] = '\0';
            jstring jToken = env->NewStringUTF(buf);
            jboolean cont = env->CallBooleanMethod(callback, onTokenMethod, jToken);
            env->DeleteLocalRef(jToken);
            if (!cont) {
                LOGI("generate: callback stop at step %d", i);
                break;
            }
        }

        n_decoded++;

        // Log first 5 tokens and every 20 after
        if (n_decoded <= 5 || n_decoded % 20 == 0) {
            LOGI("generate: decoded token %d (id=%d)", n_decoded, new_token);
        }

        // Decode the new token for next sampling
        llama_batch next_batch = llama_batch_get_one(&new_token, 1);
        rc = llama_decode(session->ctx, next_batch);
        if (rc != 0) {
            LOGE("generate: decode failed at step %d (rc=%d)", i, rc);
            break;
        }
    }

    int64_t t2 = now_ms();
    LOGI("generate: === COMPLETE === decoded=%d  decode_elapsed=%lldms  total=%lldms",
         n_decoded, (long long)(t2 - t1), (long long)(t2 - t0));
    return n_decoded;
}

} // extern "C"
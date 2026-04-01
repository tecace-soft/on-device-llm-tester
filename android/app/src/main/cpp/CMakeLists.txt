cmake_minimum_required(VERSION 3.22.1)
project(llama-android)

# ── llama.cpp build options ───────────────────────────────────────────────────
# Disable unneeded targets to speed up build
set(LLAMA_BUILD_TESTS    OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER   OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TOOLS    OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_COMMON   OFF CACHE BOOL "" FORCE)
set(BUILD_SHARED_LIBS    OFF CACHE BOOL "" FORCE)

# Android NDK cross-compile: disable host-specific optimizations
set(GGML_NATIVE    OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP    OFF CACHE BOOL "" FORCE)   # NDK OpenMP requires extra setup
set(GGML_LLAMAFILE OFF CACHE BOOL "" FORCE)   # llamafile doesn't support Android

# Vulkan GPU acceleration (disabled for MVP — enable in Phase 5.1)
# set(GGML_VULKAN ON CACHE BOOL "" FORCE)

add_subdirectory(llama.cpp)

# ── JNI bridge library ────────────────────────────────────────────────────────
add_library(llama-android SHARED llama-jni.cpp)

target_include_directories(llama-android PRIVATE
        llama.cpp/include
        llama.cpp/ggml/include
)

target_link_libraries(llama-android
        llama
        ggml
        android
        log
)
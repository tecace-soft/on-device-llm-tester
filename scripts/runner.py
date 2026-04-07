import subprocess
import time
import json
import logging
import os
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

PACKAGE_NAME = "com.tecace.llmtester"
RESULTS_DIR = "files/results"
MAX_ADB_RETRIES = 3
ADB_RETRY_DELAY = 2

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_RESULTS_DIR = os.path.join(_PROJECT_ROOT, "results")

# ── Phase 6: Inter-test thermal guard ─────────────────────────────────────────
INTER_TEST_THERMAL_THRESHOLD = 380  # 38.0°C — 개별 테스트 간 쿨다운 임계값


# ── ADB helpers with retry ────────────────────────────────────────────────────

def adb_run(
    args: list[str],
    serial: str | None = None,
    capture: bool = False,
    retries: int = MAX_ADB_RETRIES,
) -> subprocess.CompletedProcess:
    """Run an ADB command with retry on failure. Avoids shell=True.

    When serial is provided, injects `-s <serial>` after `adb`.
    """
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    tail = args[1:] if args and args[0] == "adb" else args
    cmd.extend(tail)

    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(
                cmd,
                capture_output=capture,
                text=True if capture else False,
                timeout=30,
            )
            return result
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("ADB command failed (attempt %d/%d): %s — %s", attempt, retries, cmd[:5], e)
            if attempt == retries:
                raise
            time.sleep(ADB_RETRY_DELAY)
    raise RuntimeError("Unreachable")


def adb_shell(cmd: str, serial: str | None = None, capture: bool = True) -> subprocess.CompletedProcess:
    """Run `adb [-s serial] shell <cmd>` without shell=True."""
    return adb_run(["adb", "shell", cmd], serial=serial, capture=capture)


def wake_device(serial: str | None = None) -> None:
    result = adb_shell("dumpsys power | grep mWakefulness", serial=serial)
    if "Awake" not in (result.stdout or ""):
        adb_shell("input keyevent 224", serial=serial)
        time.sleep(0.5)
        logger.info("Screen powered on")

    adb_shell("input keyevent 82", serial=serial)
    time.sleep(0.5)
    adb_shell("settings put global low_power 0", serial=serial)
    adb_shell("settings put system screen_off_timeout 600000", serial=serial)
    logger.info("Device awake and timeout extended")


def clear_device_results(serial: str | None = None) -> None:
    """FIX(J): Clear previous results on device before starting new run."""
    adb_shell(f"run-as {PACKAGE_NAME} rm -rf {RESULTS_DIR}", serial=serial)
    adb_shell(f"run-as {PACKAGE_NAME} mkdir -p {RESULTS_DIR}", serial=serial)
    logger.info("Cleared device results directory")


def check_model_exists(remote_path: str, serial: str | None = None) -> bool:
    res = adb_shell(f"ls {remote_path}", serial=serial)
    return res.returncode == 0


def get_file_count(serial: str | None = None) -> int:
    """Get file count with error handling for ADB disconnection."""
    try:
        res = adb_shell(f"run-as {PACKAGE_NAME} ls {RESULTS_DIR} | wc -l", serial=serial)
        val = (res.stdout or "").strip()
        return int(val) if val.isdigit() else 0
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        logger.warning("get_file_count failed: %s", e)
        return -1  # Signal ADB failure


def _escape_for_adb_shell(text: str) -> str:
    """Escape a string for safe passage through `adb shell` → device shell.

    `adb shell <args>` concatenates all args with spaces and passes them to
    the device's /bin/sh.  To protect spaces, quotes, and special chars inside
    a value we single-quote the whole thing and escape any embedded single
    quotes with the '\\'' idiom (end quote, literal quote, reopen quote).
    """
    escaped = text.replace("'", "'\\''")
    return f"'{escaped}'"


def _auto_detect_engine(model_path: str) -> str:
    """Auto-detect engine from file extension. Returns engine string or empty."""
    if model_path.endswith(".task"):
        return "mediapipe"
    elif model_path.endswith(".gguf"):
        return "llamacpp"
    return ""


# ── PC-side error JSON generation ─────────────────────────────────────────────

def _get_device_info(serial: str | None = None) -> dict:
    """Fetch device info via ADB for error JSON. Returns partial info on failure."""
    info = {
        "manufacturer": "", "model": "", "product": "",
        "soc": "", "android_version": "", "sdk_int": 0,
        "cpu_cores": 0, "max_heap_mb": 0,
    }
    try:
        for key, prop in [
            ("manufacturer", "ro.product.manufacturer"),
            ("model", "ro.product.model"),
            ("product", "ro.product.name"),
            ("soc", "ro.hardware.chipname"),
            ("android_version", "ro.build.version.release"),
            ("sdk_int", "ro.build.version.sdk"),
        ]:
            res = adb_shell(f"getprop {prop}", serial=serial)
            val = (res.stdout or "").strip()
            if key == "sdk_int":
                info[key] = int(val) if val.isdigit() else 0
            else:
                info[key] = val
    except Exception as e:
        logger.warning("Failed to fetch device info: %s", e)
    return info


def save_pc_error_json(
    serial: str | None,
    model_path: str,
    model_name: str,
    backend: str,
    engine: str,
    prompt_id: str,
    category: str,
    lang: str,
    prompt_text: str,
    error_reason: str,
    profile_data: dict | None = None,
) -> None:
    """Write an error JSON on PC side when device fails to produce a result.

    Saved to results/{device_model}/{model_name}/ so ingest.py picks it up
    automatically. This ensures timeout/crash failures are tracked in DB
    and reflected in validation stats.

    Phase 6: profile_data가 제공되면 에러 JSON에 리소스 프로파일링 데이터를 포함.
    """
    device_info = _get_device_info(serial)
    device_model = (device_info.get("model") or "unknown_device").replace("/", "_")
    safe_model = model_name.replace("/", "_")

    target_dir = os.path.join(LOCAL_RESULTS_DIR, device_model, safe_model)
    os.makedirs(target_dir, exist_ok=True)

    timestamp = int(datetime.now().timestamp() * 1000)
    filename = f"error_{prompt_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    data = {
        "status": "error",
        "engine": engine,
        "prompt_id": prompt_id,
        "prompt_category": category,
        "prompt_lang": lang,
        "model_path": model_path,
        "model_name": model_name,
        "backend": backend,
        "device": device_info,
        "prompt": prompt_text,
        "response": "",
        "error": error_reason,
        "timestamp": timestamp,
    }

    if profile_data:
        data.update(profile_data)

    filepath = os.path.join(target_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("[ERROR JSON] %s → %s", prompt_id, filepath)


# ── Phase 6: Profile JSON generation ─────────────────────────────────────────

def save_profile_json(
    serial: str | None,
    model_name: str,
    prompt_id: str,
    timestamp: int,
    profile_data: dict,
) -> None:
    """Write a resource profile JSON on PC side for successful inferences.

    Profile JSON은 ingest.py에서 result JSON과 타임스탬프 기반으로 매칭하여 merge.
    같은 디렉토리(results/{device}/{model}/)에 저장하여 ingest.py가 자동 발견.
    """
    device_info = _get_device_info(serial)
    device_model = (device_info.get("model") or "unknown_device").replace("/", "_")
    safe_model = model_name.replace("/", "_")

    target_dir = os.path.join(LOCAL_RESULTS_DIR, device_model, safe_model)
    os.makedirs(target_dir, exist_ok=True)

    filename = f"profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    data = {
        "type": "resource_profile",
        "timestamp": timestamp,
        "prompt_id": prompt_id,
        "model_name": model_name,
    }
    data.update(profile_data)

    filepath = os.path.join(target_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("[PROFILE JSON] %s → %s", prompt_id, filepath)


# ── Core Test Batch ───────────────────────────────────────────────────────────

def run_test_batch(config_path: str = "test_config.json", serial: str | None = None) -> int:
    """Run all tests on a single device. Returns exit code: 0=all success, 1=some failures, 2=total failure."""
    from resource_profiler import ResourceProfiler

    if not os.path.exists(config_path):
        logger.error("Config file not found: %s", config_path)
        return 2

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    models = config.get("models", [])
    prompts = config.get("prompts", [])
    timeout_sec = config.get("timeout_sec", 60)

    if not models or not prompts:
        logger.error("No models or prompts defined in config")
        return 2

    # FIX(J): Clear device results before starting
    clear_device_results(serial=serial)

    logger.info("=== Batch Testing Start ===")
    wake_device(serial=serial)

    total = len(models) * len(prompts)
    current = 0
    success_count = 0
    fail_count = 0
    adb_failure_streak = 0
    MAX_ADB_FAILURES = 5

    profiler = ResourceProfiler(serial=serial)

    for model in models:
        model_path = model["path"]
        max_tokens = model.get("max_tokens", 1024)
        backend = model.get("backend", "CPU").upper()
        model_name = os.path.basename(model_path)

        # ── Engine detection (Phase 5) ──
        engine = model.get("engine", "").lower()
        if not engine:
            engine = _auto_detect_engine(model_path)
            if not engine:
                logger.error("[SKIP] Unknown model format and no engine specified: %s", model_path)
                fail_count += len(prompts)
                current += len(prompts)
                continue
            logger.info("[AUTO-DETECT] %s → engine=%s", model_name, engine)

        engine_params = model.get("engine_params", {})
        engine_params_json = json.dumps(engine_params) if engine_params else "{}"

        if not check_model_exists(model_path, serial=serial):
            logger.error("[SKIP] Model not found: %s", model_path)
            fail_count += len(prompts)
            current += len(prompts)
            continue

        logger.info("[Model: %s] [Engine: %s] [Backend: %s] Starting tests", model_name, engine, backend)

        for prompt_entry in prompts:
            current += 1
            prompt_id = prompt_entry["id"]
            category = prompt_entry.get("category", "unknown")
            lang = prompt_entry.get("lang", "en")
            prompt_text = prompt_entry["prompt"]

            profiler.reset()

            logger.info("Initializing device...")
            adb_run(["adb", "shell", "am", "force-stop", PACKAGE_NAME], serial=serial)
            adb_run(["adb", "logcat", "-c"], serial=serial)
            wake_device(serial=serial)
            time.sleep(1)

            initial_count = get_file_count(serial=serial)
            if initial_count < 0:
                adb_failure_streak += 1
                if adb_failure_streak >= MAX_ADB_FAILURES:
                    logger.error("ADB disconnected — %d consecutive failures. Aborting.", MAX_ADB_FAILURES)
                    return 2
                save_pc_error_json(
                    serial, model_path, model_name, backend, engine,
                    prompt_id, category, lang, prompt_text,
                    "ADB connection failure — could not check device status",
                )
                fail_count += 1
                continue

            adb_failure_streak = 0

            logger.info("[%d/%d] [%s] [%s] [%s] [%s] %s...",
                        current, total, prompt_id, engine, category, lang, prompt_text[:40])

            # ── Phase 6: Pre-inference profiling ──
            profiler.collect_pre()

            am_cmd = (
                f"am start -W -S"
                f" -n {PACKAGE_NAME}/.MainActivity"
                f" --es model_path {_escape_for_adb_shell(model_path)}"
                f" --es input_prompt {_escape_for_adb_shell(prompt_text)}"
                f" --ei max_tokens {max_tokens}"
                f" --es backend {_escape_for_adb_shell(backend)}"
                f" --es engine {_escape_for_adb_shell(engine)}"
                f" --es engine_params {_escape_for_adb_shell(engine_params_json)}"
                f" --es prompt_id {_escape_for_adb_shell(prompt_id)}"
                f" --es prompt_category {_escape_for_adb_shell(category)}"
                f" --es prompt_lang {_escape_for_adb_shell(lang)}"
            )
            adb_run(["adb", "shell", am_cmd], serial=serial, capture=True)

            start_time = time.time()
            success = False

            while time.time() - start_time < timeout_sec:
                error_check = adb_run(
                    ["adb", "logcat", "-d", "-s", "LLM_TESTER:E"],
                    serial=serial,
                    capture=True,
                )
                if (error_check.stdout or "").strip():
                    logger.warning("[APP ERROR] [%s] App internal error detected", prompt_id)
                    break

                count = get_file_count(serial=serial)
                if count < 0:
                    adb_failure_streak += 1
                    break

                adb_failure_streak = 0
                if count > initial_count:
                    logger.info("[SUCCESS] [%s]", prompt_id)
                    success = True
                    break

                print(".", end="", flush=True)
                time.sleep(2)

            # ── Phase 6: Post-inference profiling ──
            profiler.collect_post(package=PACKAGE_NAME)
            profile_data = profiler.get_profile().to_flat_dict()

            if success:
                success_count += 1
                # 성공 시: profile JSON을 별도 저장 → ingest.py에서 result와 매칭
                inference_timestamp = int(datetime.now().timestamp() * 1000)
                save_profile_json(
                    serial, model_name, prompt_id,
                    inference_timestamp, profile_data,
                )
            else:
                elapsed = time.time() - start_time
                if elapsed >= timeout_sec:
                    reason = f"Timeout after {timeout_sec}s — no response from device"
                elif adb_failure_streak > 0:
                    reason = "ADB connection lost during test"
                else:
                    reason = "App error or crash — no result file generated"
                logger.warning("[FAILED] [%s] %s — %s", prompt_id, model_name, reason)
                # 실패 시: error JSON에 프로파일링 데이터 포함
                save_pc_error_json(
                    serial, model_path, model_name, backend, engine,
                    prompt_id, category, lang, prompt_text, reason,
                    profile_data=profile_data,
                )
                fail_count += 1

            # ── Phase 6: Inter-test thermal guard ──
            _inter_test_thermal_check(profiler, serial, model_name)

            time.sleep(5)

    logger.info("=== Batch Testing Complete (%d/%d) — success: %d, failed: %d ===",
                current, total, success_count, fail_count)

    # FIX(H): Return non-zero exit code on total failure
    if success_count == 0 and total > 0:
        return 2  # Total failure
    if fail_count > 0:
        return 1  # Partial failure (still continue pipeline)
    return 0


# ── Phase 6: Inter-test thermal check ─────────────────────────────────────────

def _inter_test_thermal_check(profiler, serial: str | None, model_name: str) -> None:
    """추론 후 온도가 임계값 초과 시 쿨다운 대기.

    profiler의 post-inference 온도를 확인하여, INTER_TEST_THERMAL_THRESHOLD를
    초과하면 device_discovery.wait_for_cool_down()으로 쿨다운 대기.
    이를 통해 연속 테스트 간 벤치마크 공정성을 유지.
    """
    profile = profiler.get_profile()
    if not profile.battery_after or not profile.battery_after.temperature:
        return

    temp = profile.battery_after.temperature
    if temp > INTER_TEST_THERMAL_THRESHOLD:
        logger.warning(
            "[THERMAL:INTER] Post-inference temp %.1f°C > %.1f°C — cooling down before next test",
            temp / 10, INTER_TEST_THERMAL_THRESHOLD / 10,
        )
        try:
            from device_discovery import wait_for_cool_down
            wait_for_cool_down(serial or "", model_name)
        except ImportError:
            logger.warning("[THERMAL:INTER] device_discovery not available — skipping cooldown")


# ── Multi-Device Orchestration ────────────────────────────────────────────────

def run_all_devices(config_path: str, parallel: bool = False) -> dict[str, int]:
    """모든 연결 디바이스에서 벤치마크 실행.

    순차 모드 (기본): per-device (thermal check → test → sync) 파이프라인.
    병렬 모드 (--parallel): subprocess로 디바이스별 동시 실행 + 로그 파일 분리.

    Returns: {serial: exit_code}
    """
    from device_discovery import discover_devices, wait_for_cool_down

    devices = discover_devices()
    if not devices:
        logger.error("No devices found")
        return {}

    logger.info("=== Multi-Device Benchmark: %d devices ===", len(devices))
    for d in devices:
        logger.info("  %s (%s)", d["serial"], d["model"])

    results = {}

    if parallel:
        os.makedirs("logs", exist_ok=True)
        procs = {}
        log_files = {}
        for d in devices:
            log_path = f"logs/{d['serial']}_runner.log"
            log_f = open(log_path, "w")
            proc = subprocess.Popen(
                [sys.executable, "scripts/runner.py", "--serial", d["serial"], "--config", config_path],
                stdout=log_f, stderr=subprocess.STDOUT, text=True,
            )
            procs[d["serial"]] = proc
            log_files[d["serial"]] = log_f
            logger.info("[PARALLEL] Started %s (%s) → %s", d["serial"], d["model"], log_path)

        for serial, proc in procs.items():
            proc.wait()
            log_files[serial].close()
            results[serial] = proc.returncode
            status = "SUCCESS" if proc.returncode == 0 else "FAILED"
            logger.info("[PARALLEL] %s %s (exit=%d, log=logs/%s_runner.log)",
                        serial, status, proc.returncode, serial)
    else:
        for d in devices:
            logger.info("=== Device: %s (%s) ===", d["serial"], d["model"])

            wait_for_cool_down(d["serial"], d["model"])

            exit_code = run_test_batch(config_path, serial=d["serial"])
            results[d["serial"]] = exit_code
            status = "SUCCESS" if exit_code == 0 else "FAILED"
            logger.info("[SEQ] %s %s (exit=%d)", d["serial"], status, exit_code)

            if exit_code != 2:
                logger.info("[SEQ] Syncing results from %s...", d["serial"])
                subprocess.run(
                    [sys.executable, "scripts/sync_results.py", "--serial", d["serial"]],
                    check=False,
                )

    success = sum(1 for v in results.values() if v == 0)
    logger.info("=== Multi-Device Summary: %d/%d succeeded ===", success, len(results))
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="On-Device LLM Benchmark Runner")
    parser.add_argument("--serial", "-s", help="Target device serial (ADB serial number)")
    parser.add_argument("--all-devices", action="store_true", help="Run on all connected devices")
    parser.add_argument("--parallel", action="store_true", help="Run devices in parallel (with --all-devices)")
    parser.add_argument("--config", default="test_config.json", help="Path to test config JSON")
    args = parser.parse_args()

    if args.all_devices:
        device_results = run_all_devices(args.config, parallel=args.parallel)
        if not device_results:
            logger.error("No devices found — exiting")
            sys.exit(1)
        all_success = all(v == 0 for v in device_results.values())
        all_failed = all(v == 2 for v in device_results.values())
        if all_failed:
            logger.error("All devices failed — exiting with error")
            sys.exit(1)
        elif not all_success:
            logger.warning("Some devices/tests failed — continuing pipeline")
            sys.exit(0)
        else:
            sys.exit(0)
    else:
        exit_code = run_test_batch(args.config, serial=args.serial)
        if exit_code == 2:
            logger.error("All tests failed — exiting with error")
            sys.exit(1)
        elif exit_code == 1:
            logger.warning("Some tests failed — continuing pipeline")
            sys.exit(0)
        else:
            sys.exit(0)
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


# ── ADB helpers with retry ────────────────────────────────────────────────────

def adb_run(args: list[str], capture: bool = False, retries: int = MAX_ADB_RETRIES) -> subprocess.CompletedProcess:
    """Run an ADB command with retry on failure. Avoids shell=True."""
    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(
                args,
                capture_output=capture,
                text=True if capture else False,
                timeout=30,
            )
            return result
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("ADB command failed (attempt %d/%d): %s — %s", attempt, retries, args[:4], e)
            if attempt == retries:
                raise
            time.sleep(ADB_RETRY_DELAY)
    raise RuntimeError("Unreachable")


def adb_shell(cmd: str, capture: bool = True) -> subprocess.CompletedProcess:
    """Run `adb shell <cmd>` without shell=True."""
    return adb_run(["adb", "shell", cmd], capture=capture)


def wake_device() -> None:
    result = adb_shell("dumpsys power | grep mWakefulness")
    if "Awake" not in (result.stdout or ""):
        adb_shell("input keyevent 224")
        time.sleep(0.5)
        logger.info("Screen powered on")

    adb_shell("input keyevent 82")
    time.sleep(0.5)
    adb_shell("settings put global low_power 0")
    adb_shell("settings put system screen_off_timeout 600000")
    logger.info("Device awake and timeout extended")


def clear_device_results() -> None:
    """FIX(J): Clear previous results on device before starting new run."""
    adb_shell(f"run-as {PACKAGE_NAME} rm -rf {RESULTS_DIR}")
    adb_shell(f"run-as {PACKAGE_NAME} mkdir -p {RESULTS_DIR}")
    logger.info("Cleared device results directory")


def check_model_exists(remote_path: str) -> bool:
    res = adb_shell(f"ls {remote_path}")
    return res.returncode == 0


def get_file_count() -> int:
    """Get file count with error handling for ADB disconnection."""
    try:
        res = adb_shell(f"run-as {PACKAGE_NAME} ls {RESULTS_DIR} | wc -l")
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


def run_test_batch(config_path: str = "test_config.json") -> int:
    """Run all tests. Returns exit code: 0=all success, 1=some failures, 2=total failure."""
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
    clear_device_results()

    logger.info("=== Batch Testing Start ===")
    wake_device()

    total = len(models) * len(prompts)
    current = 0
    success_count = 0
    fail_count = 0
    adb_failure_streak = 0
    MAX_ADB_FAILURES = 5

    for model in models:
        model_path = model["path"]
        max_tokens = model.get("max_tokens", 1024)
        backend = model.get("backend", "CPU").upper()
        model_name = os.path.basename(model_path)

        if not check_model_exists(model_path):
            logger.error("[SKIP] Model not found: %s", model_path)
            fail_count += len(prompts)
            current += len(prompts)
            continue

        logger.info("[Model: %s] [Backend: %s] Starting tests", model_name, backend)

        for prompt_entry in prompts:
            current += 1
            prompt_id = prompt_entry["id"]
            category = prompt_entry.get("category", "unknown")
            lang = prompt_entry.get("lang", "en")
            prompt_text = prompt_entry["prompt"]

            logger.info("Initializing device...")
            adb_run(["adb", "shell", "am", "force-stop", PACKAGE_NAME])
            adb_run(["adb", "logcat", "-c"])
            wake_device()
            time.sleep(1)

            initial_count = get_file_count()
            if initial_count < 0:
                adb_failure_streak += 1
                if adb_failure_streak >= MAX_ADB_FAILURES:
                    logger.error("ADB disconnected — %d consecutive failures. Aborting.", MAX_ADB_FAILURES)
                    return 2
                fail_count += 1
                continue

            adb_failure_streak = 0

            logger.info("[%d/%d] [%s] [%s] [%s] %s...",
                        current, total, prompt_id, category, lang, prompt_text[:40])

            # FIX(P1): Build the entire `am start` command as a single string
            # passed to `adb shell` so that spaces in prompt_text are preserved.
            # Previously, subprocess list-args caused the device shell to split
            # prompt_text on whitespace, delivering only the first word.
            am_cmd = (
                f"am start -W -S"
                f" -n {PACKAGE_NAME}/.MainActivity"
                f" --es model_path {_escape_for_adb_shell(model_path)}"
                f" --es input_prompt {_escape_for_adb_shell(prompt_text)}"
                f" --ei max_tokens {max_tokens}"
                f" --es backend {_escape_for_adb_shell(backend)}"
                f" --es prompt_id {_escape_for_adb_shell(prompt_id)}"
                f" --es prompt_category {_escape_for_adb_shell(category)}"
                f" --es prompt_lang {_escape_for_adb_shell(lang)}"
            )
            adb_run(["adb", "shell", am_cmd], capture=True)

            start_time = time.time()
            success = False

            while time.time() - start_time < timeout_sec:
                error_check = adb_run(
                    ["adb", "logcat", "-d", "-s", "LLM_TESTER:E"],
                    capture=True,
                )
                if (error_check.stdout or "").strip():
                    logger.warning("[APP ERROR] [%s] App internal error detected", prompt_id)
                    break

                count = get_file_count()
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

            if success:
                success_count += 1
            else:
                logger.warning("[FAILED] [%s] %s — no response or error", prompt_id, model_name)
                fail_count += 1

            time.sleep(5)

    logger.info("=== Batch Testing Complete (%d/%d) — success: %d, failed: %d ===",
                current, total, success_count, fail_count)

    # FIX(H): Return non-zero exit code on total failure
    if success_count == 0 and total > 0:
        return 2  # Total failure
    if fail_count > 0:
        return 1  # Partial failure (still continue pipeline)
    return 0


if __name__ == "__main__":
    exit_code = run_test_batch()
    if exit_code == 2:
        logger.error("All tests failed — exiting with error")
        sys.exit(1)
    elif exit_code == 1:
        logger.warning("Some tests failed — continuing pipeline")
        sys.exit(0)  # Partial success is OK for CI pipeline
    else:
        sys.exit(0)
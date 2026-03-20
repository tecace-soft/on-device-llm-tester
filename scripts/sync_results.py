import json
import logging
import os
import subprocess
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

PACKAGE_NAME = "com.tecace.llmtester"
REMOTE_DIR = "files/results"
LOCAL_DIR = "./results"


def sanitize_dirname(name: str) -> str:
    return name.replace("/", "_").replace("\\", "_").replace(":", "_").replace(" ", "_")


def _adb_prefix(serial: str | None = None) -> str:
    """ADB command prefix with optional -s serial."""
    if serial:
        return f"adb -s {serial}"
    return "adb"


def read_remote_file(file_name: str, serial: str | None = None) -> Optional[str]:
    """Read a file from the app sandbox via ADB run-as."""
    remote_path = f"{REMOTE_DIR}/{file_name}"
    prefix = _adb_prefix(serial)
    cat_cmd = f'{prefix} shell "run-as {PACKAGE_NAME} cat {remote_path}"'
    content = subprocess.run(cat_cmd, shell=True, capture_output=True)

    if content.returncode != 0 or not content.stdout:
        return None

    return content.stdout.decode("utf-8", errors="replace")


def sync_results(serial: str | None = None) -> None:
    prefix = _adb_prefix(serial)
    list_cmd = f'{prefix} shell "run-as {PACKAGE_NAME} ls {REMOTE_DIR}"'
    res = subprocess.run(list_cmd, shell=True, capture_output=True)

    file_list_raw: str = res.stdout.decode("utf-8", errors="ignore").strip()

    if not file_list_raw:
        logger.info("No result files to collect.")
        return

    files = file_list_raw.split()
    logger.info("Collecting %d files...", len(files))

    synced: int = 0
    errors: int = 0

    for file_name in files:
        file_name = file_name.strip()
        if not file_name.endswith(".json"):
            continue

        decoded_text = read_remote_file(file_name, serial=serial)
        if decoded_text is None:
            logger.error("%s read failed (no data)", file_name)
            errors += 1
            continue

        try:
            data = json.loads(decoded_text)

            device = data.get("device", {})
            device_model: str = device.get("model", "unknown_device")
            model_name: str = data.get("model_name", "unknown_model")

            device_model = sanitize_dirname(device_model)
            model_name = sanitize_dirname(model_name)

            target_dir = os.path.join(LOCAL_DIR, device_model, model_name)
            os.makedirs(target_dir, exist_ok=True)

            target_path = os.path.join(target_dir, file_name)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(decoded_text)

            logger.info("%s -> %s/%s/", file_name, device_model, model_name)
            synced += 1

        except json.JSONDecodeError:
            fallback_dir = os.path.join(LOCAL_DIR, "_unclassified")
            os.makedirs(fallback_dir, exist_ok=True)
            fallback_path = os.path.join(fallback_dir, file_name)
            with open(fallback_path, "w", encoding="utf-8") as f:
                f.write(decoded_text)
            logger.warning("%s JSON parse failed, saved to _unclassified/", file_name)
            errors += 1

        except Exception as e:
            logger.error("%s processing error: %s", file_name, e)
            errors += 1

    logger.info("Sync complete (success: %d, errors: %d)", synced, errors)
    logger.info("Results location: %s", os.path.abspath(LOCAL_DIR))


def sync_all_devices() -> None:
    """모든 연결 디바이스에서 결과 수집."""
    from device_discovery import discover_devices

    devices = discover_devices()
    if not devices:
        logger.info("No devices connected.")
        return

    for d in devices:
        logger.info("=== Syncing from %s (%s) ===", d["serial"], d["model"])
        sync_results(serial=d["serial"])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sync benchmark results from device(s)")
    parser.add_argument("--serial", "-s", help="Target device serial")
    parser.add_argument("--all-devices", action="store_true", help="Sync from all connected devices")
    args = parser.parse_args()

    if args.all_devices:
        sync_all_devices()
    else:
        sync_results(serial=args.serial)
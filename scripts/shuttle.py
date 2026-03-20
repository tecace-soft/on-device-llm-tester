import os
import subprocess
import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def sync_models_to_phone(serial: str | None = None) -> bool:
    """Sync local models to a single device.

    Args:
        serial: ADB device serial. None = default ADB device.

    Returns:
        True if sync succeeded.
    """
    local_dir = os.getenv("LOCAL_MODEL_DIR")
    remote_dir = os.getenv("PHONE_MODEL_PATH")

    if not os.path.exists(local_dir):
        logger.error("Local directory '%s' not found.", local_dir)
        return False

    local_files = os.listdir(local_dir)
    if not local_files:
        logger.warning("No files found in '%s'. Nothing to sync.", local_dir)
        return False

    adb = ["adb"]
    if serial:
        adb.extend(["-s", serial])

    device_label = serial or "default"
    logger.info("[%s] Found %d files in %s. Starting sync...", device_label, len(local_files), local_dir)

    subprocess.run([*adb, "shell", f"mkdir -p {remote_dir}"], check=True)

    push_result = subprocess.run(
        [*adb, "push", f"{local_dir}/.", remote_dir],
        capture_output=True,
        text=True,
    )

    if push_result.returncode == 0:
        logger.info("[%s] Sync complete.", device_label)
        verify_result = subprocess.run(
            [*adb, "shell", f"ls -1 {remote_dir}"],
            capture_output=True,
            text=True,
        )
        logger.info("[%s] Models on phone:\n%s", device_label, verify_result.stdout.strip())
        return True
    else:
        logger.error("[%s] Sync failed: %s", device_label, push_result.stderr)
        return False


def sync_all_devices() -> None:
    """Sync models to all connected devices (순차 push — 대역폭 경합 방지)."""
    from device_discovery import discover_devices

    devices = discover_devices()
    if not devices:
        logger.info("No devices connected.")
        return

    logger.info("Syncing models to %d device(s)...", len(devices))
    for d in devices:
        logger.info("=== Pushing to %s (%s) ===", d["serial"], d["model"])
        success = sync_models_to_phone(serial=d["serial"])
        if not success:
            logger.warning("Failed to sync to %s (%s) — continuing with next device", d["serial"], d["model"])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Sync model files to device(s)")
    parser.add_argument("--serial", "-s", help="Target device serial")
    parser.add_argument("--all-devices", action="store_true", help="Sync to all connected devices")
    args = parser.parse_args()

    if args.all_devices:
        sync_all_devices()
    else:
        sync_models_to_phone(serial=args.serial)
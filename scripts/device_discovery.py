"""
device_discovery.py — ADB 디바이스 검색 공유 유틸리티

Phase 3 멀티디바이스 지원을 위한 공통 모듈.
runner.py, sync_results.py, shuttle.py에서 import하여 사용.

Usage (standalone test):
    python scripts/device_discovery.py
"""

import logging
import subprocess
import time
from typing import Optional

logger = logging.getLogger(__name__)

THERMAL_THRESHOLD = 400    # 40.0°C (Android battery temperature: 10분의 1도 단위)
THERMAL_WAIT_SEC = 30      # 대기 간격 (초)
THERMAL_MAX_WAIT = 300     # 최대 대기 시간 (5분)


# ── Device Discovery ──────────────────────────────────────────────────────────

def discover_devices() -> list[dict]:
    """연결된 ADB 디바이스 목록을 serial + model 정보와 함께 반환.

    Returns:
        serial 기준 정렬된 디바이스 목록.
        [{"serial": "RF...", "model": "SM-S931U", "product": "e3q"}, ...]

    `adb devices -l` 출력 예시:
        List of devices attached
        RFXXXXXXXX  device usb:1-1 product:dm3q model:SM_S926U device:dm3q transport_id:1
        R5XXXXXXXX  device usb:1-2 product:e3q model:SM_S931U device:e3q transport_id:2
    """
    try:
        result = subprocess.run(
            ["adb", "devices", "-l"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.error("adb devices failed: %s", e)
        return []

    devices = []
    for line in result.stdout.strip().split("\n")[1:]:
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        serial = parts[0]
        state = parts[1]

        if state != "device":
            logger.warning("Device %s in state '%s' — skipping", serial, state)
            continue

        props = {}
        for p in parts[2:]:
            if ":" in p:
                k, v = p.split(":", 1)
                props[k] = v

        devices.append({
            "serial": serial,
            "model": props.get("model", "unknown").replace("_", "-"),
            "product": props.get("product", "unknown"),
        })

    # 결정론적 순서 보장: serial 기준 정렬
    # USB 포트 변경 시에도 동일 실행 순서를 유지하여
    # 순차 모드에서 "어떤 디바이스가 먼저 돌았는가"가 재현 가능
    devices.sort(key=lambda d: d["serial"])
    return devices


# ── Device Validation ─────────────────────────────────────────────────────────

def validate_device(serial: str, package_name: str) -> bool:
    """디바이스 상태 검증: 연결 상태 + 앱 설치 여부.

    Returns:
        True if device is ready for benchmarking.
    """
    try:
        res = subprocess.run(
            ["adb", "-s", serial, "shell", "pm", "list", "packages", package_name],
            capture_output=True, text=True, timeout=10,
        )
        if package_name not in (res.stdout or ""):
            logger.warning("Package %s not installed on %s", package_name, serial)
            return False
        return True
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("validate_device failed for %s: %s", serial, e)
        return False


def get_single_device() -> Optional[str]:
    """단일 연결 디바이스의 serial 반환. 0대 또는 2대 이상이면 None."""
    devices = discover_devices()
    if len(devices) == 1:
        return devices[0]["serial"]
    return None


# ── Thermal Guard ─────────────────────────────────────────────────────────────

def check_thermal(serial: str) -> int:
    """디바이스 배터리 온도 반환 (10분의 1도 단위). e.g. 310 = 31.0°C

    Uses `adb shell dumpsys battery` output:
        ...
        temperature: 310
        ...
    """
    try:
        result = subprocess.run(
            ["adb", "-s", serial, "shell", "dumpsys", "battery"],
            capture_output=True, text=True, timeout=10,
        )
        for line in (result.stdout or "").split("\n"):
            if "temperature" in line:
                try:
                    return int(line.split(":")[1].strip())
                except (ValueError, IndexError):
                    pass
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("check_thermal failed for %s: %s", serial, e)
    return 0


def wait_for_cool_down(serial: str, model: str) -> bool:
    """온도가 임계값 이하로 내려갈 때까지 대기.

    Args:
        serial: ADB device serial.
        model: Device model name (for logging).

    Returns:
        True if temperature dropped below threshold.
        False if still hot after max wait (proceeds anyway with warning).
    """
    temp = check_thermal(serial)
    if temp <= THERMAL_THRESHOLD:
        logger.info("[THERMAL] %s (%s) temperature %.1f°C — OK", serial, model, temp / 10)
        return True

    elapsed = 0
    while elapsed < THERMAL_MAX_WAIT:
        logger.warning(
            "[THERMAL] %s (%s) temperature %.1f°C > %.1f°C — waiting %ds...",
            serial, model, temp / 10, THERMAL_THRESHOLD / 10, THERMAL_WAIT_SEC,
        )
        time.sleep(THERMAL_WAIT_SEC)
        elapsed += THERMAL_WAIT_SEC
        temp = check_thermal(serial)
        if temp <= THERMAL_THRESHOLD:
            logger.info("[THERMAL] %s (%s) cooled down to %.1f°C — OK", serial, model, temp / 10)
            return True

    logger.warning(
        "[THERMAL] %s (%s) still %.1f°C after %ds — proceeding anyway",
        serial, model, temp / 10, THERMAL_MAX_WAIT,
    )
    return False


# ── Standalone Test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    devices = discover_devices()
    if not devices:
        print("No devices connected.")
    else:
        print(f"Found {len(devices)} device(s):\n")
        for d in devices:
            temp = check_thermal(d["serial"])
            print(f"  Serial: {d['serial']}")
            print(f"  Model:  {d['model']}")
            print(f"  Product: {d['product']}")
            print(f"  Temperature: {temp / 10:.1f}°C")
            print()
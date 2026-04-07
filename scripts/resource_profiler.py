"""
resource_profiler.py — 추론 전후 리소스 프로파일링 수집 모듈 (Phase 6)

ADB를 통해 배터리(level, temperature, voltage, current), 시스템 메모리(PSS)를
수집한다. runner.py에서 추론 전후에 호출하여 delta 데이터를 생성.

Usage (standalone test):
    python scripts/resource_profiler.py
    python scripts/resource_profiler.py --serial RFXXXXXXXX
"""

import logging
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# current_now 단위 표준화 임계값
# 대부분의 Android 기기는 μA 단위를 사용하지만, 일부 OEM은 mA를 반환.
# |current_now| < 10000 이면 mA로 판단하여 * 1000 변환.
_CURRENT_MA_THRESHOLD = 10000


@dataclass
class BatterySnapshot:
    """dumpsys battery에서 파싱한 배터리 상태 스냅샷."""
    level: Optional[int] = None            # % (0~100)
    temperature: Optional[int] = None      # 10분의 1도 (310 = 31.0°C)
    voltage_mv: Optional[int] = None       # mV
    current_ua: Optional[int] = None       # μA (음수 = 방전, 양수 = 충전)


@dataclass
class ResourceProfile:
    """추론 전후 리소스 프로파일 데이터."""
    battery_before: Optional[BatterySnapshot] = None
    battery_after: Optional[BatterySnapshot] = None
    system_pss_mb: Optional[float] = None
    profiling_error: Optional[str] = None

    def to_flat_dict(self) -> dict:
        """결과 JSON / DB 적재용 flat dictionary 반환.

        Returns:
            프로파일링 컬럼 10개에 대응하는 dict.
            값이 없는 필드는 None.
        """
        d: dict = {
            "battery_level_start": None,
            "battery_level_end": None,
            "thermal_start": None,
            "thermal_end": None,
            "voltage_start_mv": None,
            "voltage_end_mv": None,
            "current_before_ua": None,
            "current_after_ua": None,
            "system_pss_mb": self.system_pss_mb,
            "profiling_error": self.profiling_error,
        }
        if self.battery_before:
            d["battery_level_start"] = self.battery_before.level
            d["thermal_start"] = self.battery_before.temperature
            d["voltage_start_mv"] = self.battery_before.voltage_mv
            d["current_before_ua"] = self.battery_before.current_ua
        if self.battery_after:
            d["battery_level_end"] = self.battery_after.level
            d["thermal_end"] = self.battery_after.temperature
            d["voltage_end_mv"] = self.battery_after.voltage_mv
            d["current_after_ua"] = self.battery_after.current_ua
        return d


class ResourceProfiler:
    """추론 전후 리소스 프로파일링 수집기.

    Usage:
        profiler = ResourceProfiler(serial="RFXXXXXXXX")
        profiler.collect_pre()
        # ... 추론 실행 ...
        profiler.collect_post(package="com.tecace.llmtester")
        profile_data = profiler.get_profile().to_flat_dict()
        profiler.reset()  # 다음 테스트를 위해 초기화
    """

    def __init__(self, serial: Optional[str] = None):
        self._serial = serial
        self._profile = ResourceProfile()

    def collect_pre(self) -> None:
        """추론 시작 전 호출. battery snapshot 수집."""
        try:
            self._profile.battery_before = self._parse_battery()
            snap = self._profile.battery_before
            logger.info(
                "[PROFILE:PRE] level=%s%% temp=%s voltage=%smV current=%sμA",
                snap.level,
                f"{snap.temperature / 10:.1f}°C" if snap.temperature else "N/A",
                snap.voltage_mv,
                snap.current_ua,
            )
        except Exception as e:
            self._append_error(f"pre-battery: {e}")
            logger.warning("[PROFILE:PRE] Battery collection failed: %s", e)

    def collect_post(self, package: str = "com.tecace.llmtester") -> None:
        """추론 완료 후 호출. battery snapshot + meminfo 수집."""
        try:
            self._profile.battery_after = self._parse_battery()
            snap = self._profile.battery_after
            logger.info(
                "[PROFILE:POST] level=%s%% temp=%s voltage=%smV current=%sμA",
                snap.level,
                f"{snap.temperature / 10:.1f}°C" if snap.temperature else "N/A",
                snap.voltage_mv,
                snap.current_ua,
            )
        except Exception as e:
            self._append_error(f"post-battery: {e}")
            logger.warning("[PROFILE:POST] Battery collection failed: %s", e)

        try:
            self._profile.system_pss_mb = self._parse_meminfo(package)
            logger.info("[PROFILE:MEM] system_pss=%.1fMB", self._profile.system_pss_mb or 0)
        except Exception as e:
            self._append_error(f"meminfo: {e}")
            logger.warning("[PROFILE:MEM] Meminfo collection failed: %s", e)

        self._log_deltas()

    def get_profile(self) -> ResourceProfile:
        """수집된 프로파일 반환."""
        return self._profile

    def reset(self) -> None:
        """다음 테스트를 위해 프로파일 초기화."""
        self._profile = ResourceProfile()

    # ── Internal parsers ──────────────────────────────────────────────────────

    def _parse_battery(self) -> BatterySnapshot:
        """adb shell dumpsys battery 출력 파싱.

        파싱 대상:
            level: 85
            temperature: 310
            voltage: 4150
            current now: -285000

        Returns:
            BatterySnapshot. 파싱 실패한 필드는 None.
        """
        output = self._adb_shell("dumpsys battery")
        snap = BatterySnapshot()
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("level:"):
                snap.level = _safe_int(line.split(":", 1)[1])
            elif line.startswith("temperature:"):
                snap.temperature = _safe_int(line.split(":", 1)[1])
            elif line.startswith("voltage:"):
                snap.voltage_mv = _safe_int(line.split(":", 1)[1])
            elif line.startswith("current now:"):
                raw_current = _safe_int(line.split(":", 1)[1])
                snap.current_ua = _normalize_current(raw_current)
        return snap

    def _parse_meminfo(self, package: str) -> Optional[float]:
        """adb shell dumpsys meminfo <package> 출력에서 TOTAL PSS 파싱.

        dumpsys meminfo 출력 예시:
            ...
                    TOTAL   123456   110000     5000     2000   ...
            ...

        "TOTAL" 행의 첫 번째 숫자가 TOTAL PSS (KB).

        Returns:
            TOTAL PSS in MB. 파싱 실패 시 None.
        """
        output = self._adb_shell(f"dumpsys meminfo {package}")
        for line in output.split("\n"):
            stripped = line.strip()
            if stripped.startswith("TOTAL") and "PSS" not in stripped:
                parts = stripped.split()
                if len(parts) >= 2:
                    pss_kb = _safe_int(parts[1])
                    if pss_kb is not None:
                        return round(pss_kb / 1024, 1)
        return None

    def _adb_shell(self, cmd: str) -> str:
        """ADB shell 명령 실행.

        runner.py의 adb_run()과 독립적으로 구현하여 모듈 단독 테스트 가능.
        runner.py에 통합 시에도 이 내부 메서드를 사용 (dumpsys 전용이므로 retry 불필요).
        """
        adb_cmd = ["adb"]
        if self._serial:
            adb_cmd.extend(["-s", self._serial])
        adb_cmd.extend(["shell", cmd])

        try:
            result = subprocess.run(
                adb_cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout or ""
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"ADB shell timeout: {cmd}")
        except OSError as e:
            raise RuntimeError(f"ADB shell error: {cmd} — {e}")

    def _append_error(self, msg: str) -> None:
        """에러 메시지 누적. 여러 수집 단계에서 각각 실패 가능."""
        if self._profile.profiling_error:
            self._profile.profiling_error += f"; {msg}"
        else:
            self._profile.profiling_error = msg

    def _log_deltas(self) -> None:
        """before/after delta 로깅 (디버깅용)."""
        before = self._profile.battery_before
        after = self._profile.battery_after
        if not before or not after:
            return

        def _delta(a: Optional[int], b: Optional[int]) -> str:
            if a is not None and b is not None:
                d = b - a
                return f"{d:+d}"
            return "N/A"

        logger.info(
            "[PROFILE:DELTA] battery=%s%% temp=%s voltage=%smV current=%sμA pss=%.1fMB",
            _delta(before.level, after.level),
            _delta(before.temperature, after.temperature),
            _delta(before.voltage_mv, after.voltage_mv),
            _delta(before.current_ua, after.current_ua),
            self._profile.system_pss_mb or 0,
        )


# ── Utility functions ─────────────────────────────────────────────────────────

def _safe_int(s: Optional[str]) -> Optional[int]:
    """문자열 → int 변환. 실패 시 None."""
    if s is None:
        return None
    try:
        return int(s.strip())
    except (ValueError, AttributeError):
        return None


def _normalize_current(raw: Optional[int]) -> Optional[int]:
    """current_now 단위 표준화 (μA).

    Android 기기마다 current now의 단위가 다를 수 있다:
    - 대부분: μA (예: -285000)
    - 일부 OEM: mA (예: -285)

    |raw| < 10000 이면 mA로 판단하여 × 1000 변환.
    이 휴리스틱은 on-device LLM 추론 시 일반적인 전류 범위
    (100mA ~ 5000mA = 100000μA ~ 5000000μA)에 기반.
    """
    if raw is None:
        return None
    if abs(raw) < _CURRENT_MA_THRESHOLD:
        return raw * 1000
    return raw


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Resource Profiler — standalone test")
    parser.add_argument("--serial", "-s", help="Target device serial")
    parser.add_argument("--package", default="com.tecace.llmtester", help="App package name")
    args = parser.parse_args()

    print("=" * 60)
    print("  Resource Profiler — Standalone Test")
    print("=" * 60)

    profiler = ResourceProfiler(serial=args.serial)

    print("\n[1] Collecting battery snapshot (pre)...")
    profiler.collect_pre()

    print("\n[2] Collecting battery snapshot (post) + meminfo...")
    profiler.collect_post(package=args.package)

    profile = profiler.get_profile()
    flat = profile.to_flat_dict()

    print("\n[3] Profile result:")
    print(json.dumps(flat, indent=2, ensure_ascii=False))

    if profile.profiling_error:
        print(f"\n⚠️  Profiling errors: {profile.profiling_error}")
    else:
        print("\n✅ All profiling data collected successfully")

    print("\n[4] Delta analysis:")
    if profile.battery_before and profile.battery_after:
        b = profile.battery_before
        a = profile.battery_after

        if b.temperature and a.temperature:
            print(f"  Temperature: {b.temperature / 10:.1f}°C → {a.temperature / 10:.1f}°C "
                  f"(Δ{(a.temperature - b.temperature) / 10:+.1f}°C)")
        if b.voltage_mv and a.voltage_mv:
            print(f"  Voltage: {b.voltage_mv}mV → {a.voltage_mv}mV "
                  f"(Δ{a.voltage_mv - b.voltage_mv:+d}mV)")
        if b.current_ua and a.current_ua:
            print(f"  Current: {b.current_ua}μA → {a.current_ua}μA "
                  f"(Δ{a.current_ua - b.current_ua:+d}μA)")
        if b.level is not None and a.level is not None:
            print(f"  Battery: {b.level}% → {a.level}% "
                  f"(Δ{a.level - b.level:+d}%)")

    if profile.system_pss_mb:
        print(f"  System PSS: {profile.system_pss_mb:.1f} MB")

    print()
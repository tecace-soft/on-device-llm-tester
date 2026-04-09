# On-Device LLM Tester — Phase 6: Resource Profiling Architecture

## 1. High-Level Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                   RESOURCE PROFILING PIPELINE (Phase 6)                   │
│                                                                          │
│  Android App (변경 없음)                                                  │
│    └─ 기존 InferenceEngine → InferenceMetrics 수집 동일                   │
│    └─ peak_java_memory_mb, peak_native_memory_mb 계속 앱 내 수집          │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  runner.py (✨ UPDATED)                                          │    │
│  │                                                                   │    │
│  │  ┌─────────────────────────────────────────────────────────┐     │    │
│  │  │  ResourceProfiler (✨ NEW)                               │     │    │
│  │  │                                                          │     │    │
│  │  │  ┌─────────────┐   ┌──────────────┐   ┌────────────┐   │     │    │
│  │  │  │ BatteryInfo  │   │ ThermalInfo  │   │ MemoryInfo │   │     │    │
│  │  │  │ level (%)    │   │ temp (1/10°C)│   │ PSS (MB)   │   │     │    │
│  │  │  │ voltage (mV) │   │              │   │            │   │     │    │
│  │  │  │ current (μA) │   │              │   │            │   │     │    │
│  │  │  └─────────────┘   └──────────────┘   └────────────┘   │     │    │
│  │  │                                                          │     │    │
│  │  │  collect_pre()  → 추론 전 snapshot                       │     │    │
│  │  │  collect_post() → 추론 후 snapshot + meminfo             │     │    │
│  │  │  to_dict()      → 결과 JSON에 삽입할 flat dict            │     │    │
│  │  └─────────────────────────────────────────────────────────┘     │    │
│  │                                                                   │    │
│  │  run_test_batch() 흐름:                                           │    │
│  │    profiler.collect_pre()                                         │    │
│  │    → am start (추론 실행)                                          │    │
│  │    → polling (기존 동일)                                           │    │
│  │    profiler.collect_post()                                        │    │
│  │    → profiling 데이터를 결과 JSON에 merge                          │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  기존 파이프라인 (변경 최소화)                                      │    │
│  │                                                                   │    │
│  │  sync_results.py (변경 없음)                                      │    │
│  │    └─ JSON 파일 그대로 pull                                        │    │
│  │                                                                   │    │
│  │  ingest.py (✨ UPDATED)                                           │    │
│  │    └─ results 테이블에 profiling 컬럼 10개 추가                     │    │
│  │    └─ _ensure_columns()에 Phase 6 마이그레이션 추가                 │    │
│  │                                                                   │    │
│  │  response_validator.py (변경 없음)                                 │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  Dashboard + API (✨ UPDATED)                                            │
│    └─ ResultItem에 resource_profile 필드 추가                             │
│    └─ /api/results/summary에 avg resource metrics 추가                   │
│    └─ Dashboard: Resource 탭/섹션 추가 (Model Compare, Device Compare)    │
└──────────────────────────────────────────────────────────────────────────┘
```

## 2. Why This Architecture

### 2.1 왜 runner.py에서 수집하는가 (앱 변경 없이)

리소스 프로파일링 데이터(배터리, 온도, 시스템 메모리)는 **ADB 커맨드로 외부에서 수집 가능**하다. 앱 내부에서 수집하면 추론 성능에 영향을 주고(observer effect), 앱 코드 변경 → 빌드 → 배포 사이클이 필요하다.

`runner.py`는 이미 추론 전후 시점이 명확하다 (`am start` → polling → success/fail). 이 구간 전후에 `adb shell dumpsys battery`와 `adb shell dumpsys meminfo`를 한 번씩 호출하면 **zero app change**로 리소스 프로파일링이 가능하다.

### 2.2 왜 before/after delta 방식인가 (시계열 아닌)

on-device LLM 추론 시간은 보통 10~120초. 이 짧은 구간에서:
- 시계열 샘플링(매 5초)은 데이터는 많지만, 분석 시 결국 "총 소비량"으로 집계됨
- before/after delta는 단순하고 통계 처리가 쉬움 (모델 간 비교, 디바이스 간 비교)
- DB 스키마도 results 테이블 컬럼 추가로 끝남 (별도 시계열 테이블 불필요)

시계열 샘플링이 필요해지면 Phase 6.1에서 별도 `resource_samples` 테이블로 확장 가능.

### 2.3 왜 voltage와 current를 같이 수집하는가

`dumpsys battery`의 `level`은 정수 %라서, 1분 이내 추론에서는 delta가 0인 경우가 빈번하다. 이를 보완하기 위해:
- **voltage (mV)**: 배터리 전압은 소모에 따라 수 mV~수십 mV 단위로 떨어짐. `level`보다 민감
- **current_now (μA)**: 순간 소모 전류. 추론 전후 차이로 추론이 전류 소비에 미친 영향을 볼 수 있음

세 가지를 모두 `dumpsys battery` **한 번 호출**로 파싱하므로 추가 비용이 없다.

### 2.4 왜 delta를 DB에 저장하지 않는가

`battery_delta = battery_level_end - battery_level_start` 같은 계산값은 SQL에서 `(end - start) AS delta`로 즉시 계산 가능. DB에 redundant 컬럼을 넣으면:
- start/end 중 하나가 수정될 때 delta 불일치 위험
- 컬럼 3개(battery, thermal, voltage delta) 추가로 스키마가 불필요하게 비대해짐

API response에서 computed field로 내려주는 것이 single source of truth를 유지하는 방법이다.

### 2.5 프로파일링 실패와 추론 결과의 독립성

프로파일링은 추론의 **부가 데이터**다. ADB `dumpsys` 타임아웃이나 파싱 실패가 발생해도 추론 결과(`status: success`)는 정상이어야 한다. 이를 위해:
- 프로파일링 실패 시 해당 컬럼은 null, `profiling_error`에 에러 메시지 기록
- 추론 `status` 필드에는 영향 없음
- Phase 6 이전 데이터(profiling 컬럼 전부 null + profiling_error도 null)와 수집 실패(profiling 컬럼 null + profiling_error에 메시지)를 구분 가능

## 3. Data Collection

### 3.1 `dumpsys battery` 파싱 대상

```
$ adb shell dumpsys battery
Current Battery Service state:
  AC powered: false
  USB powered: true
  ...
  status: 2
  health: 2
  present: true
  level: 85
  ...
  temperature: 310
  voltage: 4150
  ...
  current now: -285000
```

| 필드 | 파싱 키 | 타입 | 단위 | 설명 |
|------|---------|------|------|------|
| `level` | `level:` | int | % | 배터리 잔량 |
| `temperature` | `temperature:` | int | 10분의 1도 | 310 = 31.0°C |
| `voltage` | `voltage:` | int | mV | 배터리 전압 |
| `current now` | `current now:` | int | μA | 순간 전류 (음수 = 방전) |

**수집 시점**: 추론 전 1회, 추론 후 1회 → 총 `dumpsys battery` 2회 호출.

**주의**: `current now`는 기기마다 지원 여부가 다름. 미지원 시 null.

### 3.2 `dumpsys meminfo` 파싱 대상

```
$ adb shell dumpsys meminfo com.tecace.llmtester
Applications Memory Usage (in Kilobytes):
Uptime: 123456 Realtime: 789012

** MEMINFO in pid 12345 [com.tecace.llmtester] **
                   Pss  Private  Private  SwapPss   ...
                 Total    Dirty    Clean    Dirty   ...
                ------   ------   ------   ------   ...
  Native Heap    45678    45000      200      100   ...
  ...
        TOTAL   123456   110000     5000     2000   ...
```

| 필드 | 파싱 대상 | 타입 | 단위 | 설명 |
|------|----------|------|------|------|
| TOTAL PSS | `TOTAL` 행의 첫 번째 숫자 | int → float | KB → MB | 시스템 관점 전체 메모리 사용량 |

**수집 시점**: 추론 **후** 1회만. 이유:
- 추론 전은 앱이 아직 모델을 로드하지 않은 상태라 PSS가 작음 (의미 없음)
- 추론 후 PSS가 피크 메모리를 반영 (모델 로드 + 추론 버퍼 포함)
- 앱 내부의 `peak_native_memory_mb`와 교차 검증 용도

### 3.3 기기 호환성

| 필드 | Galaxy S25 (Snapdragon 8 Elite) | Galaxy S24 (Snapdragon 8 Gen 3) | Pixel 9 | 비고 |
|------|------|------|------|------|
| `level` | ✅ | ✅ | ✅ | 모든 Android 기기 지원 |
| `temperature` | ✅ | ✅ | ✅ | 모든 Android 기기 지원 |
| `voltage` | ✅ | ✅ | ✅ | 모든 Android 기기 지원 |
| `current now` | ✅ | ✅ | ⚠️ 일부 | OEM에 따라 0 반환 가능 |
| `dumpsys meminfo <pkg>` | ✅ | ✅ | ✅ | 모든 Android 기기 지원 |

## 4. ResourceProfiler Module

### 4.1 모듈 위치

```
scripts/
├── runner.py              # ✨ UPDATED — ResourceProfiler 호출
├── resource_profiler.py   # ✨ NEW — 프로파일링 수집/파싱 모듈
├── device_discovery.py    # 기존 (check_thermal 등)
├── sync_results.py        # 변경 없음
├── ingest.py              # ✨ UPDATED — 새 컬럼 적재
└── response_validator.py  # 변경 없음
```

### 4.2 핵심 인터페이스

```python
# scripts/resource_profiler.py

from dataclasses import dataclass, field
from typing import Optional

@dataclass
class BatterySnapshot:
    level: Optional[int] = None           # % (0~100)
    temperature: Optional[int] = None     # 10분의 1도 (310 = 31.0°C)
    voltage_mv: Optional[int] = None      # mV
    current_ua: Optional[int] = None      # μA (음수 = 방전)

@dataclass
class ResourceProfile:
    battery_before: Optional[BatterySnapshot] = None
    battery_after: Optional[BatterySnapshot] = None
    system_pss_mb: Optional[float] = None          # 추론 후 TOTAL PSS
    profiling_error: Optional[str] = None           # 수집 실패 시 에러 메시지

    def to_flat_dict(self) -> dict:
        """결과 JSON / DB 적재용 flat dictionary 반환."""
        d = {
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
    """추론 전후 리소스 프로파일링 수집기."""

    def __init__(self, serial: Optional[str] = None):
        self._serial = serial
        self._profile = ResourceProfile()

    def collect_pre(self) -> None:
        """추론 시작 전 호출. battery snapshot 수집."""
        try:
            self._profile.battery_before = self._parse_battery()
        except Exception as e:
            self._append_error(f"pre-battery: {e}")

    def collect_post(self, package: str = "com.tecace.llmtester") -> None:
        """추론 완료 후 호출. battery snapshot + meminfo 수집."""
        try:
            self._profile.battery_after = self._parse_battery()
        except Exception as e:
            self._append_error(f"post-battery: {e}")

        try:
            self._profile.system_pss_mb = self._parse_meminfo(package)
        except Exception as e:
            self._append_error(f"meminfo: {e}")

    def get_profile(self) -> ResourceProfile:
        """수집된 프로파일 반환."""
        return self._profile

    def reset(self) -> None:
        """다음 테스트를 위해 프로파일 초기화."""
        self._profile = ResourceProfile()

    # ── Internal parsers ──────────────────────────────────────────────

    def _parse_battery(self) -> BatterySnapshot:
        """adb shell dumpsys battery 출력 파싱."""
        output = self._adb_shell("dumpsys battery")
        snap = BatterySnapshot()
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("level:"):
                snap.level = _safe_int(line.split(":")[1])
            elif line.startswith("temperature:"):
                snap.temperature = _safe_int(line.split(":")[1])
            elif line.startswith("voltage:"):
                snap.voltage_mv = _safe_int(line.split(":")[1])
            elif line.startswith("current now:"):
                snap.current_ua = _safe_int(line.split(":")[1])
        return snap

    def _parse_meminfo(self, package: str) -> Optional[float]:
        """adb shell dumpsys meminfo <package> 출력에서 TOTAL PSS 파싱."""
        output = self._adb_shell(f"dumpsys meminfo {package}")
        for line in output.split("\n"):
            if "TOTAL" in line and "PSS" not in line:
                # "        TOTAL   123456   110000 ..." 형태
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        pss_kb = int(parts[1])
                        return round(pss_kb / 1024, 1)  # KB → MB
                    except ValueError:
                        pass
        return None

    def _adb_shell(self, cmd: str) -> str:
        """ADB shell 명령 실행. runner.py의 adb_run()을 재사용."""
        import subprocess
        adb_cmd = ["adb"]
        if self._serial:
            adb_cmd.extend(["-s", self._serial])
        adb_cmd.extend(["shell", cmd])
        result = subprocess.run(
            adb_cmd, capture_output=True, text=True, timeout=10,
        )
        return result.stdout or ""

    def _append_error(self, msg: str) -> None:
        """에러 메시지 누적 (여러 단계에서 실패 가능)."""
        if self._profile.profiling_error:
            self._profile.profiling_error += f"; {msg}"
        else:
            self._profile.profiling_error = msg


def _safe_int(s: str) -> Optional[int]:
    """문자열 → int 변환. 실패 시 None."""
    try:
        return int(s.strip())
    except (ValueError, AttributeError):
        return None
```

### 4.3 runner.py 통합 포인트

```python
# runner.py — run_test_batch() 내부, 각 prompt 테스트 루프

from resource_profiler import ResourceProfiler

# ... (기존 모델/프롬프트 루프 내부)

profiler = ResourceProfiler(serial=serial)

for prompt_entry in prompts:
    profiler.reset()

    # ── 1. 추론 전 프로파일링 ──
    profiler.collect_pre()

    # ── 2. 추론 실행 (기존 로직 동일) ──
    adb_run(["adb", "shell", am_cmd], serial=serial, capture=True)

    # ... polling loop (기존 동일) ...

    # ── 3. 추론 후 프로파일링 ──
    if success:
        profiler.collect_post(package=PACKAGE_NAME)

    # ── 4. PC-side error JSON에도 프로파일링 데이터 포함 ──
    if not success:
        profiler.collect_post(package=PACKAGE_NAME)  # 실패해도 수집 시도

    # ── 5. 프로파일링 데이터를 결과에 merge ──
    profile_data = profiler.get_profile().to_flat_dict()
    # → 성공 시: sync된 JSON에는 프로파일링 미포함 (앱이 생성하므로)
    #   → save_pc_profiling_json()으로 별도 저장 후 ingest에서 merge
    # → 실패 시: save_pc_error_json()에 profile_data 포함
```

### 4.4 프로파일링 데이터 저장 전략

**핵심 문제**: 앱이 생성하는 결과 JSON(`last_result.json`)에는 프로파일링 데이터가 없다. 프로파일링은 `runner.py`(PC 사이드)에서 수집하기 때문이다.

**해결책**: 프로파일링 데이터를 **PC 사이드에 별도 JSON으로 저장** → `ingest.py`에서 결과 JSON과 매칭하여 merge.

```
results/
  SM-S931U/
    qwen2.5-1.5b-q4_k_m.gguf/
      result_20260402_143047.json          ← 앱에서 sync된 원본
      profile_20260402_143047.json         ← runner.py가 생성한 프로파일링
      result_20260402_143058.json
      profile_20260402_143058.json
      error_math_01_20260402_143120.json   ← 에러 JSON (프로파일링 포함)
```

**매칭 방식**: 타임스탬프 기반. 결과 JSON의 `timestamp`와 프로파일 JSON의 `timestamp`가 ±5초 이내면 매칭.

**프로파일 JSON 포맷**:

```json
{
  "type": "resource_profile",
  "timestamp": 1711000000000,
  "prompt_id": "math_01",
  "model_name": "qwen2.5-1.5b-q4_k_m.gguf",
  "battery_level_start": 85,
  "battery_level_end": 85,
  "thermal_start": 310,
  "thermal_end": 325,
  "voltage_start_mv": 4150,
  "voltage_end_mv": 4130,
  "current_before_ua": -285000,
  "current_after_ua": -450000,
  "system_pss_mb": 892.3,
  "profiling_error": null
}
```

**대안 검토 후 기각한 방식들**:

| 방식 | 장점 | 단점 | 판정 |
|------|------|------|------|
| **A. 별도 profile JSON + ingest merge** | 앱 변경 없음, 기존 sync 파이프라인 유지 | ingest에서 매칭 로직 필요 | ✅ **채택** |
| B. 앱 결과 JSON을 runner.py가 수정 | 단일 파일로 관리 | sync 후 파일 수정 → 원본 보존 안 됨 | ❌ |
| C. runner.py가 앱 결과 pull 후 merge하여 새 파일 생성 | 깔끔한 단일 파일 | sync_results.py 로직 중복, 타이밍 복잡 | ❌ |

## 5. Database Schema Changes

### 5.1 results 테이블 확장 (컬럼 10개 추가)

```sql
-- Phase 6 migration: resource profiling columns
ALTER TABLE results ADD COLUMN battery_level_start  INTEGER;
ALTER TABLE results ADD COLUMN battery_level_end    INTEGER;
ALTER TABLE results ADD COLUMN thermal_start        INTEGER;   -- 10분의 1도 단위
ALTER TABLE results ADD COLUMN thermal_end          INTEGER;   -- 10분의 1도 단위
ALTER TABLE results ADD COLUMN voltage_start_mv     INTEGER;
ALTER TABLE results ADD COLUMN voltage_end_mv       INTEGER;
ALTER TABLE results ADD COLUMN current_before_ua    INTEGER;   -- 순간 전류 (μA)
ALTER TABLE results ADD COLUMN current_after_ua     INTEGER;   -- 순간 전류 (μA)
ALTER TABLE results ADD COLUMN system_pss_mb        REAL;      -- TOTAL PSS (MB)
ALTER TABLE results ADD COLUMN profiling_error      TEXT;      -- 프로파일링 에러 메시지
```

### 5.2 하위 호환

- 모든 새 컬럼은 nullable (DEFAULT 없음)
- Phase 6 이전 데이터: 전부 null → `profiling_error`도 null이므로 "미수집" 상태로 구분
- Phase 6 이후 데이터: 수집 성공 시 값 채워짐, 수집 실패 시 `profiling_error`에 메시지

### 5.3 ingest.py DDL 변경

```python
# ingest.py의 _DDL 내 results 테이블 정의에 추가

    battery_level_start   INTEGER,
    battery_level_end     INTEGER,
    thermal_start         INTEGER,
    thermal_end           INTEGER,
    voltage_start_mv      INTEGER,
    voltage_end_mv        INTEGER,
    current_before_ua     INTEGER,
    current_after_ua      INTEGER,
    system_pss_mb         REAL,
    profiling_error       TEXT,
```

### 5.4 ingest.py 마이그레이션 로직

```python
def init_tables(con: sqlite3.Connection) -> None:
    # ... 기존 마이그레이션 ...

    # Phase 6 migration: resource profiling columns
    result_cols = {row[1] for row in con.execute("PRAGMA table_info(results)")}
    phase6_cols = {
        "battery_level_start": "INTEGER",
        "battery_level_end": "INTEGER",
        "thermal_start": "INTEGER",
        "thermal_end": "INTEGER",
        "voltage_start_mv": "INTEGER",
        "voltage_end_mv": "INTEGER",
        "current_before_ua": "INTEGER",
        "current_after_ua": "INTEGER",
        "system_pss_mb": "REAL",
        "profiling_error": "TEXT",
    }
    for col_name, col_type in phase6_cols.items():
        if col_name not in result_cols:
            con.execute(f"ALTER TABLE results ADD COLUMN {col_name} {col_type}")
    logger.info("Phase 6 migration: resource profiling columns ensured")

    con.commit()
```

### 5.5 ingest.py 적재 로직 — 프로파일 매칭

```python
def _find_matching_profile(result_path: Path, timestamp: int) -> Optional[dict]:
    """결과 JSON과 매칭되는 프로파일 JSON 검색.

    같은 디렉토리에서 profile_*.json 파일 중 timestamp가 ±5초 이내인 것을 찾음.
    """
    result_dir = result_path.parent
    for profile_path in result_dir.glob("profile_*.json"):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                profile = json.load(f)
            if profile.get("type") != "resource_profile":
                continue
            p_ts = profile.get("timestamp", 0)
            if abs(p_ts - timestamp) <= 5000:  # 5초 이내
                return profile
        except (json.JSONDecodeError, OSError):
            continue
    return None
```

## 6. Result JSON Schema Extension

### 6.1 앱 생성 JSON (변경 없음)

앱이 생성하는 `last_result.json` 포맷은 기존과 100% 동일. Phase 6 필드 없음.

### 6.2 PC-side Profile JSON (✨ NEW)

```json
{
  "type": "resource_profile",
  "timestamp": 1711000000000,
  "prompt_id": "math_01",
  "model_name": "qwen2.5-1.5b-q4_k_m.gguf",
  "battery_level_start": 85,
  "battery_level_end": 85,
  "thermal_start": 310,
  "thermal_end": 325,
  "voltage_start_mv": 4150,
  "voltage_end_mv": 4130,
  "current_before_ua": -285000,
  "current_after_ua": -450000,
  "system_pss_mb": 892.3,
  "profiling_error": null
}
```

### 6.3 PC-side Error JSON (확장)

기존 `save_pc_error_json()`에 프로파일링 데이터 추가:

```json
{
  "status": "error",
  "engine": "llamacpp",
  "prompt_id": "math_01",
  "error": "Timeout after 120s",
  "battery_level_start": 85,
  "battery_level_end": 84,
  "thermal_start": 310,
  "thermal_end": 380,
  "voltage_start_mv": 4150,
  "voltage_end_mv": 4050,
  "current_before_ua": -285000,
  "current_after_ua": -520000,
  "system_pss_mb": null,
  "profiling_error": null,
  "timestamp": 1711000000000
}
```

에러 케이스에서도 프로파일링 데이터가 있으면 "이 모델이 타임아웃되기 전에 온도가 얼마나 올랐는지" 같은 분석이 가능하다.

## 7. API Changes

### 7.1 ResultItem 확장

```python
# api/schemas.py

class ResourceProfile(BaseModel):
    battery_level_start: Optional[int] = None
    battery_level_end: Optional[int] = None
    battery_delta: Optional[int] = None            # computed: end - start
    thermal_start: Optional[int] = None
    thermal_end: Optional[int] = None
    thermal_delta: Optional[int] = None            # computed: end - start
    thermal_start_celsius: Optional[float] = None  # computed: start / 10
    thermal_end_celsius: Optional[float] = None    # computed: end / 10
    voltage_start_mv: Optional[int] = None
    voltage_end_mv: Optional[int] = None
    voltage_delta_mv: Optional[int] = None         # computed: end - start
    current_before_ua: Optional[int] = None
    current_after_ua: Optional[int] = None
    current_delta_ua: Optional[int] = None         # computed: after - before
    system_pss_mb: Optional[float] = None
    profiling_error: Optional[str] = None

class ResultItem(BaseModel):
    # ... 기존 필드 전부 유지
    resource_profile: Optional[ResourceProfile] = None  # ✨ NEW
```

**computed fields**: DB에는 raw 값만 저장. API 레이어에서 delta와 단위 변환을 계산하여 내려줌.

### 7.2 SummaryStats 확장

```python
class ResourceSummary(BaseModel):
    avg_thermal_delta: Optional[float] = None      # 평균 온도 변화 (°C)
    avg_voltage_delta_mv: Optional[float] = None   # 평균 전압 변화 (mV)
    avg_current_delta_ua: Optional[float] = None   # 평균 전류 변화 (μA)
    avg_system_pss_mb: Optional[float] = None      # 평균 시스템 PSS (MB)
    profiling_coverage: Optional[float] = None     # 프로파일링 수집률 (%)

class SummaryStats(BaseModel):
    # ... 기존 필드 전부 유지
    resource: Optional[ResourceSummary] = None     # ✨ NEW
```

### 7.3 새 Endpoint (선택)

```
GET /api/results/resource-summary     → 리소스 프로파일링 집계
    ?device=SM-S931U
    &model=qwen2.5-1.5b-q4_k_m.gguf
    &engine=llamacpp
```

기존 `/api/results/summary`에 `ResourceSummary`를 포함시키는 것으로 충분할 수 있으므로, 별도 엔드포인트는 **필요 시 추가**.

### 7.4 loader.py SELECT 확장

```sql
-- 기존 _SELECT에 Phase 6 컬럼 추가
SELECT
    ...
    r.battery_level_start,
    r.battery_level_end,
    r.thermal_start,
    r.thermal_end,
    r.voltage_start_mv,
    r.voltage_end_mv,
    r.current_before_ua,
    r.current_after_ua,
    r.system_pss_mb,
    r.profiling_error,
    ru.run_id AS ci_run_id
FROM results r
    ...
```

## 8. Dashboard Changes

### 8.1 TypeScript 타입 확장

```typescript
// dashboard/src/types/index.ts

export interface ResourceProfile {
  battery_level_start: number | null
  battery_level_end: number | null
  battery_delta: number | null
  thermal_start: number | null
  thermal_end: number | null
  thermal_delta: number | null
  thermal_start_celsius: number | null
  thermal_end_celsius: number | null
  voltage_start_mv: number | null
  voltage_end_mv: number | null
  voltage_delta_mv: number | null
  current_before_ua: number | null
  current_after_ua: number | null
  current_delta_ua: number | null
  system_pss_mb: number | null
  profiling_error: string | null
}

export interface ResultItem {
  // ... 기존 필드
  resource_profile: ResourceProfile | null   // ✨ NEW
}

export interface ResourceSummary {
  avg_thermal_delta: number | null
  avg_voltage_delta_mv: number | null
  avg_current_delta_ua: number | null
  avg_system_pss_mb: number | null
  profiling_coverage: number | null
}

export interface SummaryStats {
  // ... 기존 필드
  resource: ResourceSummary | null   // ✨ NEW
}
```

### 8.2 Dashboard UI 추가 사항

**Model Compare 페이지**:
- 기존 Performance 섹션 아래에 "Resource" 섹션 추가
- KPI 카드: Avg Thermal Δ (°C), Avg Voltage Δ (mV), Avg System PSS (MB)
- 바 차트: 모델별 온도 변화량 비교

**Device Compare 페이지**:
- 동일 모델의 디바이스별 리소스 소비 비교
- 레이더 차트에 thermal_delta, voltage_delta 축 추가

**Raw Data 테이블**:
- resource_profile 컬럼 자동 표시 (expandable row detail)

### 8.3 파생 지표 (Dashboard에서 계산)

| 지표 | 공식 | 의미 |
|------|------|------|
| **Energy Efficiency** | `output_token_count / abs(voltage_delta_mv)` | mV당 생성 토큰 수. 높을수록 전성비 우수 |
| **Thermal Efficiency** | `output_token_count / thermal_delta` | 온도 상승 1단위당 생성 토큰 수 |
| **Memory Overhead** | `system_pss_mb - peak_native_memory_mb` | 시스템 PSS와 앱 내부 메모리 차이. 공유 라이브러리 점유율 |

## 9. Thermal Guard 연동

### 9.1 기존 thermal guard 활용

`device_discovery.py`의 `wait_for_cool_down()`은 현재 디바이스 단위로 동작 (모든 테스트 시작 전 1회). Phase 6에서는 **개별 테스트 간** thermal guard를 추가한다.

### 9.2 테스트 간 thermal check

```python
# runner.py — 프롬프트 루프 내부

INTER_TEST_THERMAL_THRESHOLD = 380  # 38.0°C

for prompt_entry in prompts:
    # 프로파일링 수집 후, 다음 테스트 전에 온도 확인
    if profiler.get_profile().battery_after:
        temp = profiler.get_profile().battery_after.temperature or 0
        if temp > INTER_TEST_THERMAL_THRESHOLD:
            logger.warning(
                "[THERMAL] Post-inference temp %.1f°C > %.1f°C — cooling down",
                temp / 10, INTER_TEST_THERMAL_THRESHOLD / 10,
            )
            wait_for_cool_down(serial, model_name)
```

이렇게 하면 추론 후 온도가 임계값을 넘으면 자동으로 쿨다운 대기 → 다음 테스트의 벤치마크 공정성 유지.

### 9.3 Thermal guard 임계값 정리

| 임계값 | 값 | 용도 | 위치 |
|--------|------|------|------|
| `THERMAL_THRESHOLD` | 350 (35.0°C) | 디바이스 단위 쿨다운 (기존) | `device_discovery.py` |
| `INTER_TEST_THERMAL_THRESHOLD` | 380 (38.0°C) | 테스트 간 쿨다운 (Phase 6) | `runner.py` |

35°C vs 38°C 차이: 디바이스 시작 시에는 완전히 냉각된 상태에서 출발, 개별 테스트 간에는 약간의 열은 허용하되 throttling 구간(보통 40°C+)에는 진입하지 않도록.

## 10. Error Handling

| 상황 | 처리 | 영향 |
|------|------|------|
| `dumpsys battery` 타임아웃 | `profiling_error`에 기록, 추론 진행 | profiling 컬럼 null |
| `dumpsys meminfo` 파싱 실패 | `profiling_error`에 기록, 추론 진행 | `system_pss_mb` null |
| `current now` 미지원 기기 | `current_before_ua`, `current_after_ua` = null | 정상 동작, 해당 필드만 null |
| 프로파일 JSON 매칭 실패 (ingest) | profiling 컬럼 null, 로그 경고 | 결과 자체는 정상 적재 |
| Phase 6 이전 기존 데이터 | 모든 profiling 컬럼 null + `profiling_error` null | "미수집"으로 구분 |
| 추론 실패 + 프로파일링 성공 | `status: error` + profiling 데이터 존재 | 실패 시에도 리소스 소비 분석 가능 |

## 11. Implementation Order

```
Step 1: resource_profiler.py 작성
        → BatterySnapshot, ResourceProfile, ResourceProfiler 클래스
        → _parse_battery(), _parse_meminfo() 구현
        → 단독 테스트: python -c "from resource_profiler import ..."
        → ADB 연결 상태에서 dumpsys 파싱 결과 확인

Step 2: runner.py에 ResourceProfiler 통합
        → import resource_profiler
        → run_test_batch() 루프 내에 collect_pre() / collect_post() 삽입
        → 프로파일 JSON 저장 로직 (save_profile_json)
        → save_pc_error_json()에 프로파일링 데이터 포함
        → 테스트 간 thermal check 로직 추가
        → E2E 테스트: runner.py 실행 → results/ 하위에 profile_*.json 생성 확인

Step 3: ingest.py DB 마이그레이션 + 적재
        → DDL에 Phase 6 컬럼 추가
        → init_tables()에 마이그레이션 로직 추가
        → _find_matching_profile() 구현
        → insert_result() 확장 (프로파일 데이터 매핑)
        → 테스트: ingest.py 실행 → DB에 profiling 컬럼 확인

Step 4: API 확장
        → schemas.py: ResourceProfile, ResourceSummary 스키마 추가
        → loader.py: _SELECT에 Phase 6 컬럼 추가, _row_to_item() 확장
        → stats.py: compute_summary()에 ResourceSummary 계산 추가
        → Swagger에서 확인

Step 5: Dashboard 확장
        → types/index.ts: ResourceProfile, ResourceSummary 타입 추가
        → Model Compare: Resource 섹션 + KPI 카드 + 바 차트
        → Device Compare: 리소스 비교 추가
        → Raw Data: resource_profile 컬럼 표시

Step 6: CI/CD + 문서
        → benchmark.yml 변경 없음 (runner.py가 자동으로 프로파일링)
        → README.md에 Resource Profiling 사용법 섹션
        → GITHUB_STEP_SUMMARY에 resource metrics 요약 추가
```

## 12. Risk Assessment

| 리스크 | 영향 | 대응 |
|--------|------|------|
| `dumpsys battery` 출력 포맷 변경 (Android 버전) | 중간 | 파싱 로직을 방어적으로 작성 (키 미발견 시 null) |
| `current now` 기기 미지원 | 낮음 | nullable 처리. 다른 메트릭(voltage)으로 보완 |
| 프로파일 JSON 매칭 실패 (타임스탬프 불일치) | 중간 | 매칭 윈도우 5초 → 필요 시 확장. prompt_id + model_name 추가 매칭 |
| ADB dumpsys 호출이 추론 타이밍에 영향 | 낮음 | dumpsys는 10ms 미만. 추론 전후에만 호출하므로 추론 자체에 영향 없음 |
| DB 마이그레이션 시 기존 데이터 깨짐 | 낮음 | ALTER TABLE ADD COLUMN은 기존 행에 null 채움. 비파괴적 |
| Dashboard 렌더링 시 null 값 처리 | 낮음 | Phase 6 이전 데이터는 "N/A" 표시 |

## 13. Extension Points

```
Phase 6.1 (시계열 샘플링)
  └─→ 추론 중 매 N초 간격으로 temperature/current 수집
  └─→ resource_samples 테이블: (result_id, elapsed_sec, temp, current_ua)
  └─→ Dashboard: 추론 중 온도/전류 그래프

Phase 6.2 (GPU Frequency 모니터링)
  └─→ adb shell cat /sys/class/kgsl/kgsl-3d0/gpuclk (Adreno)
  └─→ GPU 클럭 변화로 thermal throttling 직접 감지

Phase 6.3 (배터리 드레인 장기 테스트)
  └─→ 동일 모델로 N회 반복 추론 → 누적 battery level 감소 추적
  └─→ "이 모델 10분 돌리면 배터리 X% 소모" 지표

Phase 6.4 (Energy Efficiency 리더보드)
  └─→ Dashboard에 "Tokens per mV" 랭킹 페이지
  └─→ 모델 × 양자화 × 디바이스 조합별 전성비 비교
```

## 14. Tech Stack (Phase 6 추가분)

| Layer | Tech | Why |
|-------|------|-----|
| **Battery/Thermal 수집** | `adb shell dumpsys battery` | 표준 Android 디버깅 인터페이스. 모든 기기 지원 |
| **Memory 수집** | `adb shell dumpsys meminfo <pkg>` | PSS 기반 정확한 메모리 측정. root 불필요 |
| **프로파일러 모듈** | Python dataclass + subprocess | 추가 의존성 없음. runner.py와 동일 스택 |
| **DB 저장** | SQLite ALTER TABLE | 기존 마이그레이션 패턴 그대로. 비파괴적 |

※ Android 앱, sync_results.py, response_validator.py, CI/CD 워크플로우 변경 없음.

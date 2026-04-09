# On-Device LLM Tester — Phase 3: Multi-Device Architecture

## 1. High-Level Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    MULTI-DEVICE PIPELINE (Phase 3)                       │
│                                                                          │
│  ┌─────────────────────────────┐                                         │
│  │  GitHub Actions              │                                         │
│  │  workflow_dispatch           │                                         │
│  │  + matrix strategy (✨ NEW) │                                         │
│  └──────────────┬──────────────┘                                         │
│                 │                                                         │
│                 ▼                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐    │
│  │  Self-hosted Runner (개발 PC — 폰 N대 USB 연결)                   │    │
│  │                                                                   │    │
│  │  Step 0: Discover devices (✨ NEW)                                │    │
│  │    └─ adb devices → serial 목록 수집                              │    │
│  │                                                                   │    │
│  │  Step 1: runner.py --serial <SERIAL> (✨ UPDATED)                 │    │
│  │    ├─ -s <SERIAL>로 특정 디바이스 타겟팅                           │    │
│  │    ├─ 순차 모드: 디바이스 1대씩 전체 테스트 실행                    │    │
│  │    └─ 병렬 모드: subprocess로 디바이스별 동시 실행 (옵션)           │    │
│  │                                                                   │    │
│  │  Step 2: sync_results.py --serial <SERIAL> (✨ UPDATED)           │    │
│  │    ├─ -s <SERIAL>로 특정 디바이스에서 결과 수집                     │    │
│  │    └─ results/{device_model}/{model}/*.json (기존 구조 유지)       │    │
│  │                                                                   │    │
│  │  Step 3: ingest.py (변경 없음)                                    │    │
│  │    └─ JSON → SQLite (디바이스 정보는 JSON에 이미 포함)             │    │
│  │                                                                   │    │
│  │  Step 4: Upload .db artifact                                      │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  ┌──────────────────────────────┐    ┌──────────────────────────────┐    │
│  │  SQLite DB (기존)             │    │  Dashboard                    │    │
│  │  data/llm_tester.db          │    │  :5173 + :8000               │    │
│  │                               │    │                               │    │
│  │  devices 테이블에 여러 기기    │    │  Device Compare (✨ NEW)     │    │
│  │  results에 다양한 device_id   │    │  Overview 필터 강화           │    │
│  │                               │    │  Performance 디바이스 오버레이 │    │
│  └──────────────────────────────┘    └──────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────┘
```

## 2. Why This Architecture

### 순차 실행 기본 + 병렬 옵션 — 왜 이 구조인가?

- **현재 runner.py는 단일 디바이스 전용**: `adb shell`이 `-s` 없이 실행되므로 USB에 1대만 연결된 상태를 가정. 2대 이상이면 `error: more than one device/emulator` 발생
- **순차 실행이 기본인 이유**: 같은 PC에서 여러 폰을 동시에 벤치마크하면 USB 대역폭, CPU 리소스(ADB 프로세스)가 경합. 벤치마크 결과의 재현성이 떨어짐. 1대씩 테스트해야 공정한 비교 가능
- **병렬은 "속도 우선" 옵션**: 대량 모델/프롬프트 조합에서 총 실행 시간 단축이 필요할 때만 `--parallel` 플래그로 활성화. 이 경우 디바이스 간 결과는 환경 노이즈가 더 클 수 있음을 인지
- **ADB serial 기반 타겟팅**: `adb -s <serial>` 패턴은 ADB의 표준 멀티디바이스 접근법. 모든 기존 adb 명령에 `-s` prefix만 추가하면 되므로 변경 최소화

### 단일 Runner 유지 — 왜 디바이스별 Runner를 안 두는가?

- **현재 구조**: 1대의 개발 PC에 폰 N대 USB 연결. Self-hosted Runner 1개로 모든 디바이스 커버
- **디바이스별 Runner**: 각 폰마다 별도 PC + Runner가 필요. 현재 단계에서는 오버엔지니어링
- **확장 경로**: 나중에 PC가 여러 대로 늘면 Runner 라벨(`llm-bench-pc1`, `llm-bench-pc2`)로 분리 가능. 지금은 단일 Runner에서 디바이스 순회가 최적

### DB/API 변경 최소 — 왜 스키마를 안 바꾸는가?

- **devices 테이블이 이미 존재**: Phase 1.5에서 정규화 완료. 새 디바이스는 `INSERT OR IGNORE`로 자동 등록
- **API에 device 필터가 이미 존재**: `/api/results?device=SM-S931U` 파라미터가 Phase 1부터 정의됨
- **추가 필요한 것**: 디바이스 간 비교 API (`/api/results/compare-devices`) + Dashboard의 Device Compare 페이지

## 3. Device Discovery

### 3.1 ADB 디바이스 목록 수집

```python
# scripts/device_discovery.py (✨ NEW — 또는 runner.py 내 함수로 통합)

def discover_devices() -> list[dict]:
    """연결된 ADB 디바이스 목록을 serial + model 정보와 함께 반환."""
    result = subprocess.run(
        ["adb", "devices", "-l"],
        capture_output=True, text=True, timeout=10,
    )
    # 출력 예시:
    # List of devices attached
    # RFXXXXXXXX       device usb:1-1 product:dm3q model:SM_S926U device:dm3q transport_id:1
    # R5XXXXXXXX       device usb:1-2 product:e3q model:SM_S931U device:e3q transport_id:2

    devices = []
    for line in result.stdout.strip().split("\n")[1:]:
        if not line.strip() or "device" not in line:
            continue
        parts = line.split()
        serial = parts[0]
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
```

### 3.2 디바이스 검증

| 검증 항목 | 방법 | 실패 시 |
|----------|------|---------|
| USB 연결 | `adb devices -l` 출력에 `device` 상태 | `unauthorized`/`offline` → 해당 디바이스 스킵 + 경고 |
| 앱 설치 | `adb -s {serial} shell pm list packages \| grep {PACKAGE_NAME}` | 미설치 → 해당 디바이스 스킵 |
| 모델 존재 | `adb -s {serial} shell ls {model_path}` (기존 `check_model_exists`) | 미존재 → 해당 모델 스킵 |
| 화면 상태 | `adb -s {serial} shell dumpsys power` (기존 `wake_device`) | 슬립 → 자동 깨우기 |
| **배터리 온도** | `adb -s {serial} shell dumpsys battery \| grep temperature` | **임계값 초과 → 쿨다운 대기** |

### 3.3 Thermal Guard (✨ NEW)

멀티디바이스 순차 실행 시, 대기 중인 디바이스가 USB 충전 상태로 온도가 상승할 수 있음. Snapdragon 8 Elite 등 고성능 SoC는 thermal throttling이 벤치마크 결과에 직접 영향을 미치므로, 테스트 시작 전 온도 체크가 필수.

```python
# scripts/device_discovery.py

THERMAL_THRESHOLD = 350   # 35.0°C (Android battery temperature는 10분의 1도 단위)
THERMAL_WAIT_SEC = 30     # 대기 간격
THERMAL_MAX_WAIT = 300    # 최대 대기 시간 (5분)

def check_thermal(serial: str) -> int:
    """디바이스 배터리 온도 반환 (10분의 1도 단위). e.g. 310 = 31.0°C"""
    result = subprocess.run(
        ["adb", "-s", serial, "shell", "dumpsys", "battery"],
        capture_output=True, text=True, timeout=10,
    )
    for line in (result.stdout or "").split("\n"):
        if "temperature" in line:
            try:
                return int(line.split(":")[1].strip())
            except (ValueError, IndexError):
                return 0
    return 0

def wait_for_cool_down(serial: str, model: str) -> bool:
    """온도가 임계값 이하로 내려갈 때까지 대기. Returns True if cooled down."""
    elapsed = 0
    while elapsed < THERMAL_MAX_WAIT:
        temp = check_thermal(serial)
        if temp <= THERMAL_THRESHOLD:
            return True
        logger.warning(
            "[THERMAL] %s (%s) temperature %.1f°C > %.1f°C — waiting %ds...",
            serial, model, temp / 10, THERMAL_THRESHOLD / 10, THERMAL_WAIT_SEC,
        )
        time.sleep(THERMAL_WAIT_SEC)
        elapsed += THERMAL_WAIT_SEC
    logger.warning("[THERMAL] %s (%s) still hot after %ds — proceeding anyway", serial, model, THERMAL_MAX_WAIT)
    return False
```

**사용 위치**: `runner.py`의 `run_all_devices()` 순차 모드에서 각 디바이스 테스트 시작 전에 호출.

## 4. Script 변경사항

### 4.1 `scripts/runner.py` — 멀티디바이스 지원

**변경 원칙**: 기존 단일 디바이스 로직은 그대로 유지. `--serial` 플래그로 디바이스 지정, 미지정 시 연결된 모든 디바이스 순회.

```
# 실행 모드

# 1. 기존 호환 (단일 디바이스, 기존과 동일 동작)
python scripts/runner.py

# 2. 특정 디바이스 지정
python scripts/runner.py --serial RFXXXXXXXX

# 3. 전체 디바이스 순차 실행 (기본 멀티디바이스 모드)
python scripts/runner.py --all-devices

# 4. 전체 디바이스 병렬 실행 (속도 우선)
python scripts/runner.py --all-devices --parallel
```

**핵심 변경 포인트**:

```python
# 1. 모든 ADB 함수에 serial 파라미터 추가
def adb_run(args: list[str], serial: str | None = None, ...) -> subprocess.CompletedProcess:
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args[1:] if args[0] == "adb" else args)
    # ... 기존 retry 로직 동일

def adb_shell(cmd: str, serial: str | None = None, ...) -> subprocess.CompletedProcess:
    return adb_run(["adb", "shell", cmd], serial=serial, ...)

# 2. run_test_batch에 serial 파라미터 추가
def run_test_batch(config_path: str = "test_config.json", serial: str | None = None) -> int:
    # 기존 로직 동일, 모든 adb_* 호출에 serial 전달

# 3. 멀티디바이스 오케스트레이션 (NEW)
def run_all_devices(config_path: str, parallel: bool = False) -> dict[str, int]:
    """모든 연결 디바이스에서 벤치마크 실행. Returns {serial: exit_code}."""
    devices = discover_devices()
    if not devices:
        logger.error("No devices found")
        return {}

    logger.info("=== Multi-Device Benchmark: %d devices ===", len(devices))
    for d in devices:
        logger.info("  %s (%s)", d["serial"], d["model"])

    results = {}

    if parallel:
        # subprocess로 디바이스별 runner.py 병렬 실행
        # ⚠️ 병렬 모드는 로그가 혼합되므로 디바이스별 로그 파일 분리 필수
        os.makedirs("logs", exist_ok=True)
        procs = {}
        log_files = {}
        for d in devices:
            log_path = f"logs/{d['serial']}_runner.log"
            log_f = open(log_path, "w")
            proc = subprocess.Popen(
                [sys.executable, "scripts/runner.py", "--serial", d["serial"]],
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
        # 순차 실행: per-device (test → sync) 파이프라인
        # 디바이스 A 테스트 완료 → 즉시 A에서 결과 sync → 디바이스 B 테스트
        # 이유: B 테스트 중 A의 앱 샌드박스 결과가 유실될 위험 방지
        for d in devices:
            logger.info("=== Device: %s (%s) ===", d["serial"], d["model"])

            # Thermal guard: 온도가 임계값 이하인지 확인
            wait_for_cool_down(d["serial"], d["model"])

            exit_code = run_test_batch(config_path, serial=d["serial"])
            results[d["serial"]] = exit_code
            status = "SUCCESS" if exit_code == 0 else "FAILED"
            logger.info("[SEQ] %s %s (exit=%d)", d["serial"], status, exit_code)

            # 즉시 sync: 이 디바이스 결과를 PC로 가져옴
            if exit_code != 2:  # 전체 실패가 아닌 경우만 sync
                logger.info("[SEQ] Syncing results from %s...", d["serial"])
                subprocess.run(
                    [sys.executable, "scripts/sync_results.py", "--serial", d["serial"]],
                    check=False,
                )

    # 요약 출력
    success = sum(1 for v in results.values() if v == 0)
    logger.info("=== Multi-Device Summary: %d/%d succeeded ===", success, len(results))
    return results

# 4. CLI 엔트리포인트
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", "-s", help="Target device serial")
    parser.add_argument("--all-devices", action="store_true", help="Run on all connected devices")
    parser.add_argument("--parallel", action="store_true", help="Run devices in parallel")
    parser.add_argument("--config", default="test_config.json")
    args = parser.parse_args()

    if args.all_devices:
        results = run_all_devices(args.config, parallel=args.parallel)
        sys.exit(0 if all(v == 0 for v in results.values()) else 1)
    else:
        sys.exit(run_test_batch(args.config, serial=args.serial))
```

### 4.2 `scripts/sync_results.py` — 멀티디바이스 지원

**변경 원칙**: `--serial` 추가. 미지정 시 모든 디바이스에서 수집.

```python
# 변경 포인트

# 1. ADB 명령에 serial 주입
def adb_cmd(base_cmd: str, serial: str | None = None) -> str:
    """ADB 명령에 -s serial을 주입."""
    if serial:
        return base_cmd.replace("adb ", f"adb -s {serial} ", 1)
    return base_cmd

# 2. read_remote_file에 serial 파라미터 추가
def read_remote_file(file_name: str, serial: str | None = None) -> Optional[str]:
    remote_path = f"{REMOTE_DIR}/{file_name}"
    cat_cmd = adb_cmd(f'adb shell "run-as {PACKAGE_NAME} cat {remote_path}"', serial)
    # ... 나머지 동일

# 3. sync_results에 serial 파라미터 추가
def sync_results(serial: str | None = None) -> None:
    list_cmd = adb_cmd(f'adb shell "run-as {PACKAGE_NAME} ls {REMOTE_DIR}"', serial)
    # ... 나머지 동일

# 4. 멀티디바이스 수집
def sync_all_devices() -> None:
    """모든 연결 디바이스에서 결과 수집."""
    devices = discover_devices()  # runner.py와 동일 함수 재사용
    for d in devices:
        logger.info("=== Syncing from %s (%s) ===", d["serial"], d["model"])
        sync_results(serial=d["serial"])

# 5. CLI
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", "-s")
    parser.add_argument("--all-devices", action="store_true")
    args = parser.parse_args()

    if args.all_devices:
        sync_all_devices()
    else:
        sync_results(serial=args.serial)
```

### 4.3 `scripts/shuttle.py` — 멀티디바이스 지원

**변경 원칙**: 모델을 모든 디바이스에 동시 전송.

```
# 실행 모드

# 기존 (단일)
python scripts/shuttle.py

# 특정 디바이스
python scripts/shuttle.py --serial RFXXXXXXXX

# 모든 디바이스 (순차 push — 대역폭 경합 방지)
python scripts/shuttle.py --all-devices
```

### 4.4 `scripts/device_discovery.py` — 공유 유틸리티 (✨ NEW)

runner.py, sync_results.py, shuttle.py에서 공통으로 사용하는 디바이스 검색 로직을 별도 모듈로 분리.

```python
# scripts/device_discovery.py

import subprocess
import logging
import time

logger = logging.getLogger(__name__)

THERMAL_THRESHOLD = 350   # 35.0°C
THERMAL_WAIT_SEC = 30
THERMAL_MAX_WAIT = 300    # 5분

def discover_devices() -> list[dict]:
    """연결된 ADB 디바이스 목록 반환 (serial 기준 정렬).
    Returns: [{"serial": "RF...", "model": "SM-S931U", "product": "e3q"}, ...]
    """
    # ... (§3.1 구현 — serial 정렬 포함)

def validate_device(serial: str, package_name: str) -> bool:
    """디바이스 상태 검증 (연결, 앱 설치 여부)."""
    # ... (§3.2 구현)

def check_thermal(serial: str) -> int:
    """디바이스 배터리 온도 반환 (10분의 1도 단위)."""
    # ... (§3.3 구현)

def wait_for_cool_down(serial: str, model: str) -> bool:
    """온도가 임계값 이하로 내려갈 때까지 대기."""
    # ... (§3.3 구현)

def get_single_device() -> str | None:
    """단일 연결 디바이스의 serial 반환. 0대 또는 2대 이상이면 None."""
    devices = discover_devices()
    if len(devices) == 1:
        return devices[0]["serial"]
    return None
```

### 4.5 모델 파일 사전 동기화 (✨ 파이프라인 필수 단계)

멀티디바이스 벤치마크의 전제 조건: **모든 디바이스에 동일한 모델 파일이 존재해야 함.**

디바이스 A에는 gemma3가 있고 B에는 없으면, B의 해당 모델 테스트가 전부 스킵되어 비교 데이터가 불완전해짐. 이를 방지하기 위해 `shuttle.py --all-devices`를 파이프라인 필수 단계로 명시.

**CI/CD 파이프라인 순서**:
```
shuttle.py --all-devices    ← 모든 디바이스에 모델 배포 (사전 조건)
    ↓
runner.py --all-devices     ← 벤치마크 실행
    ↓
sync_results.py --all-devices (또는 순차 모드에서 per-device sync)
    ↓
ingest.py
```

**로컬 실행 시 체크리스트**:
```bash
# 1. 모든 디바이스에 모델 배포 (최초 1회 또는 모델 변경 시)
python scripts/shuttle.py --all-devices

# 2. 배포 확인 (선택 — shuttle.py가 각 디바이스의 모델 목록 출력)
# 출력 예: SM-S931U: gemma3-1b-it-int4.task, Qwen2.5-1.5B-Instruct
#          SM-S926U: gemma3-1b-it-int4.task, Qwen2.5-1.5B-Instruct

# 3. 벤치마크 실행
python scripts/runner.py --all-devices
```

**runner.py 내 방어 로직**: `check_model_exists()`가 디바이스별로 실행되어 모델 미존재 시 해당 모델만 스킵. 하지만 스킵된 테스트는 비교 데이터 결측으로 이어지므로, **사전 동기화가 훨씬 중요**.

### 4.6 `scripts/ingest.py` — 변경 없음

ingest.py는 `results/` 디렉토리의 JSON 파일을 순회하며 적재. JSON 파일 내에 `device.model`, `device.manufacturer` 등이 이미 포함되어 있으므로 devices 테이블에 자동 정규화 적재됨. 멀티디바이스 결과도 기존 파이프라인 그대로 동작.

## 5. CI/CD Workflow 확장

### 5.1 디바이스 Discovery Step 추가

```yaml
# .github/workflows/benchmark.yml (✨ UPDATED)

name: LLM Benchmark

on:
  workflow_dispatch:
    inputs:
      device_mode:
        description: 'Device selection mode'
        required: false
        default: 'all'
        type: choice
        options:
          - all           # 연결된 모든 디바이스
          - single        # 첫 번째 디바이스만
      parallel:
        description: 'Run devices in parallel'
        required: false
        default: false
        type: boolean

concurrency:
  group: llm-bench
  cancel-in-progress: false

jobs:
  benchmark:
    runs-on: [self-hosted, llm-bench]
    timeout-minutes: 240              # 멀티디바이스: 디바이스 수 × 기존 timeout

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Verify ADB & discover devices
        id: discover
        run: |
          adb devices -l
          DEVICE_COUNT=$(adb devices | grep -w "device" | wc -l)
          echo "device_count=$DEVICE_COUNT" >> $GITHUB_OUTPUT
          if [ "$DEVICE_COUNT" -eq 0 ]; then
            echo "No devices connected"
            exit 1
          fi
          echo "Found $DEVICE_COUNT device(s)"

      - name: Sync models to all devices
        if: ${{ inputs.device_mode == 'all' }}
        run: python scripts/shuttle.py --all-devices

      - name: Run benchmark (multi-device)
        run: |
          if [ "${{ inputs.device_mode }}" = "single" ]; then
            python scripts/runner.py
          elif [ "${{ inputs.parallel }}" = "true" ]; then
            python scripts/runner.py --all-devices --parallel
          else
            python scripts/runner.py --all-devices
          fi

      - name: Sync results from all devices
        run: |
          if [ "${{ inputs.device_mode }}" = "single" ]; then
            python scripts/sync_results.py
          elif [ "${{ inputs.parallel }}" = "true" ]; then
            # 병렬 모드: runner.py가 sync 안 했으므로 여기서 일괄 수집
            python scripts/sync_results.py --all-devices
          fi
          # 순차 모드: runner.py가 per-device sync를 이미 수행했으므로 스킵

      - name: Ingest results to DB
        run: |
          python scripts/ingest.py \
            --run-id ${{ github.run_id }} \
            --trigger manual \
            --commit-sha ${{ github.sha }} \
            --branch ${{ github.ref_name }}

      - name: Upload DB artifact
        uses: actions/upload-artifact@v4
        continue-on-error: true
        with:
          name: llm-tester-db-${{ github.run_id }}
          path: data/llm_tester.db
          retention-days: 90

      - name: Upload runner logs (parallel mode)
        if: ${{ inputs.parallel == 'true' }}
        uses: actions/upload-artifact@v4
        continue-on-error: true
        with:
          name: runner-logs-${{ github.run_id }}
          path: logs/*.log
          retention-days: 30

      - name: Summary
        run: |
          echo "## Benchmark Complete" >> $GITHUB_STEP_SUMMARY
          echo "- Run ID: ${{ github.run_id }}" >> $GITHUB_STEP_SUMMARY
          echo "- Devices: ${{ steps.discover.outputs.device_count }}" >> $GITHUB_STEP_SUMMARY
          echo "- Mode: ${{ inputs.device_mode }}" >> $GITHUB_STEP_SUMMARY
          echo "- Parallel: ${{ inputs.parallel }}" >> $GITHUB_STEP_SUMMARY
          python scripts/ingest.py --summary-only >> $GITHUB_STEP_SUMMARY
```

### 5.2 timeout 설계 (멀티디바이스)

| 시나리오 | 디바이스 수 | 모드 | 예상 소요 | timeout |
|---------|-----------|------|----------|---------|
| 단일 | 1 | - | 10~90분 | 120분 (기존) |
| 멀티 순차 | 2 | sequential | 20~180분 | 240분 |
| 멀티 순차 | 3+ | sequential | 30~270분 | 360분 |
| 멀티 병렬 | 2~3 | parallel | 10~90분 (최장 디바이스 기준) | 120분 |

기본 timeout을 **240분**으로 상향. `--parallel` 사용 시 실질적 소요는 기존과 비슷.

### 5.3 동시 실행 방지 (concurrency)

현재 `concurrency.group: llm-bench`은 유지. 같은 PC에 연결된 디바이스들이므로 워크플로우 동시 실행은 여전히 위험. Phase 3에서도 **직렬 큐잉** 유지.

향후 PC가 여러 대로 늘면:
```yaml
concurrency:
  group: llm-bench-${{ runner.name }}  # Runner별 독립 큐
```

## 6. API 확장

### 6.1 신규 엔드포인트

```
GET  /api/results/compare-devices     → 디바이스 간 비교 데이터
     ?devices=SM-S931U,SM-S926U       # 비교할 디바이스 목록 (콤마 구분)
     &model=gemma3-1b-it-int4.task    # 특정 모델 기준 비교 (필수)
     &backend=CPU                     # 선택
```

### 6.2 응답 스키마

```python
# api/schemas.py 추가

class DeviceCompareResult(BaseModel):
    device_model: str                   # e.g. "SM-S931U"
    device_info: dict                   # manufacturer, soc, android_version 등
    stats: SummaryStats                 # 해당 디바이스의 집계 통계
    by_category: list[CategorySummary]  # 카테고리별 통계

# 응답: ApiSuccess[list[DeviceCompareResult]]
```

### 6.3 `api/stats.py` 추가 함수

```python
async def compute_compare_devices(
    db: aiosqlite.Connection,
    device_models: list[str],
    model: str | None = None,
    backend: str | None = None,
) -> list[DeviceCompareResult]:
    """디바이스 간 동일 모델 성능 비교."""
    results = []
    for device_model in device_models:
        where, params = _build_where(device_model, model, None, backend, None)
        stats = await _build_summary(db, where, params)

        # 디바이스 메타정보 조회
        async with db.execute(
            "SELECT * FROM devices WHERE model = ?", (device_model,)
        ) as cur:
            dev_row = await cur.fetchone()

        by_cat = await compute_by_category(db, device=device_model, model=model, backend=backend)

        results.append(DeviceCompareResult(
            device_model=device_model,
            device_info=dict(dev_row) if dev_row else {},
            stats=stats,
            by_category=by_cat,
        ))
    return results
```

### 6.4 기존 엔드포인트 영향

| Endpoint | 변경 | 이유 |
|----------|------|------|
| `GET /api/results` | 없음 | `?device=` 필터 이미 존재 |
| `GET /api/results/summary` | 없음 | `?device=` 필터 이미 존재 |
| `GET /api/results/compare` | 없음 | 모델 비교용, 디바이스 비교는 별도 |
| `GET /api/devices` | 없음 | 이미 모든 디바이스 반환 |
| `GET /api/results/compare-devices` | **✨ NEW** | 디바이스 간 비교 전용 |

## 7. Dashboard 확장

### 7.1 Device Compare 페이지 (✨ NEW)

| 요소 | 내용 |
|------|------|
| 디바이스 선택 | 드롭다운 2~3개로 Device A, B, C 선택 |
| 모델 선택 | 비교 기준 모델 드롭다운 (필수) |
| KPI 비교 카드 | Avg Latency, Decode TPS, TTFT를 나란히 표시 (색상 강조: 더 좋은 쪽 녹색) |
| **바 차트 (Primary)** | 카테고리별 Decode TPS 비교 (그룹드 바). 가장 직관적인 비교 수단 |
| Radar 차트 (Secondary) | Latency/TPS/TTFT/Memory 정규화 비교. 보조 시각화 — 바 차트 아래 배치, MVP에서는 생략 가능 |
| SoC 정보 | 선택된 디바이스의 SoC, RAM, Android 버전 표시 |
| 상세 테이블 | 동일 프롬프트에 대한 양쪽 결과 나란히 표시 |

### 7.2 기존 페이지 변경

| 페이지 | 변경 |
|--------|------|
| Overview | FilterBar의 device 드롭다운이 이미 존재. 멀티디바이스 데이터가 들어오면 자동으로 필터링 가능. 변경 없음 |
| Performance | 차트에 device별 색상 오버레이 옵션 추가 (토글) |
| Compare | 기존: 모델 간 비교. 변경 없음 (디바이스 비교는 별도 페이지) |
| Raw Data | `device` 컬럼이 이미 존재. 변경 없음 |
| Sidebar | "Device Compare" 메뉴 항목 추가 |

### 7.3 React 추가 컴포넌트

```
dashboard/src/
├── pages/
│   └── DeviceCompare.tsx           # ✨ NEW
├── hooks/
│   └── useDeviceCompare.ts         # ✨ NEW — /api/results/compare-devices 호출
├── types/
│   └── index.ts                    # ✨ UPDATE — DeviceCompareResult 타입
└── components/
    ├── layout/
    │   └── Sidebar.tsx             # ✨ UPDATE — Device Compare 메뉴
    └── charts/
        └── DeviceRadar.tsx         # ✨ NEW — 디바이스 비교 레이더 차트 (secondary, MVP에서 생략 가능)
```

## 8. Data Flow

### Phase 2 (현재)

```
runner.py (단일 디바이스)
    ↓
sync_results.py (단일 디바이스)
    ↓
results/SM-S931U/{model}/*.json
    ↓
ingest.py → data/llm_tester.db
    ↓
FastAPI → Dashboard
```

### Phase 3 (목표)

**사전 조건**: `shuttle.py --all-devices`로 모든 디바이스에 모델 배포 완료

**순차 모드 (기본)** — per-device test→sync 파이프라인:
```
runner.py --all-devices
    │
    ├─ Device 1 (SM-S931U):
    │   ├─ thermal check → 온도 OK → 테스트 실행
    │   └─ sync_results.py --serial RF... → results/SM-S931U/{model}/*.json
    │
    ├─ Device 2 (SM-S926U):
    │   ├─ thermal check → 35°C 초과 → 30초 대기 → 재측정 → OK → 테스트 실행
    │   └─ sync_results.py --serial R5... → results/SM-S926U/{model}/*.json
    │
    └─ (디바이스 N: 동일 패턴)
        ↓
ingest.py (변경 없음 — 전체 results/ 순회, JSON 내 device 정보로 자동 분류)
    ↓
data/llm_tester.db (devices 테이블에 N개 디바이스)
    ↓
FastAPI (/api/results/compare-devices)
    ↓
Dashboard (Device Compare 페이지)
```

**병렬 모드** (`--parallel`) — 별도 로그 파일:
```
runner.py --all-devices --parallel
    │
    ├─ subprocess 1: runner.py --serial RF... → logs/RF..._runner.log
    ├─ subprocess 2: runner.py --serial R5... → logs/R5..._runner.log
    │
    └─ 모든 subprocess 완료 후:
        sync_results.py --all-devices → results/{device}/{model}/*.json
            ↓
        ingest.py → data/llm_tester.db
```

## 9. Error Handling

### 9.1 디바이스 레벨

| 상황 | 처리 |
|------|------|
| 디바이스 0대 연결 | runner.py 즉시 실패 (exit 2). CI 워크플로우 중단 |
| 일부 디바이스 unauthorized | 해당 디바이스 스킵 + 경고 로그, 나머지 계속 |
| 일부 디바이스에서 벤치마크 실패 | 해당 디바이스 결과를 exit code 1로 기록, 나머지 계속 |
| USB 연결 끊김 (벤치마크 중) | ADB failure streak → 해당 디바이스 중단 (기존 로직), 나머지 디바이스 계속 |
| 모든 디바이스 실패 | runner.py exit 2. CI 워크플로우 실패 |
| 디바이스 온도 초과 (35°C+) | 최대 5분 대기 후 재측정. 5분 후에도 고온이면 경고 로그 출력 후 테스트 진행 (결과에 thermal throttling 가능성 표시) |
| 모델 파일 미존재 (일부 디바이스) | 해당 디바이스의 해당 모델만 스킵. 비교 데이터 결측 경고 로그 |

### 9.2 병렬 모드 에러

| 상황 | 처리 |
|------|------|
| subprocess 크래시 | `proc.wait()` 후 returncode 체크. 실패 디바이스 로그 파일 참조 |
| 모든 subprocess 실패 | 전체 exit 2 |
| 일부만 실패 | 성공한 디바이스 결과는 정상 sync/ingest. exit 1 (partial failure) |
| 로그 혼합 방지 | 각 subprocess의 stdout/stderr → `logs/{serial}_runner.log` 파일로 분리. 터미널에는 시작/완료 요약만 출력 |

**병렬 모드 로그 구조**:
```
logs/
├── RFXXXXXXXX_runner.log    # Device 1 (SM-S926U) 전체 로그
├── R5XXXXXXXX_runner.log    # Device 2 (SM-S931U) 전체 로그
└── ...
```
CI에서는 `logs/` 디렉토리를 artifact로 함께 업로드하여 실패 원인 추적 가능.

### 9.3 Exit Code 규약

| Code | 의미 | CI 반응 |
|------|------|---------|
| 0 | 모든 디바이스 성공 | 워크플로우 성공 |
| 1 | 일부 디바이스/테스트 실패 | 워크플로우 성공 (partial results ingest) |
| 2 | 전체 실패 (디바이스 없음, 설정 오류 등) | 워크플로우 실패 |

## 10. Backward Compatibility

### 10.1 단일 디바이스 호환

| 시나리오 | 동작 |
|---------|------|
| `python scripts/runner.py` (기존 그대로) | USB에 1대 연결 시 기존과 동일하게 동작. `-s` 미지정이면 ADB 기본 동작 |
| `python scripts/runner.py` (2대 이상) | ADB `error: more than one device` → 에러 메시지와 함께 `--serial` 또는 `--all-devices` 사용 안내 |
| `python scripts/sync_results.py` (기존 그대로) | 1대 시 기존 동일. 2대 이상 시 위와 동일 에러 |

### 10.2 기존 데이터 호환

- 기존 `results/SM-S931U/` 디렉토리의 JSON 파일 그대로 유지
- 새 디바이스 결과가 `results/SM-S926U/` 등으로 추가될 뿐
- `ingest.py`는 전체 `results/` 순회하므로 자동 적재

### 10.3 API 호환

- 기존 API 엔드포인트 시그니처 변경 없음
- `?device=` 필터 없이 호출하면 모든 디바이스 결과 반환 (기존 동작)
- 새로 추가되는 `/api/results/compare-devices`만 신규

## 11. Directory Structure (변경사항)

```
on-device-llm-tester/
├── .github/
│   └── workflows/
│       └── benchmark.yml               # ✨ UPDATE — device_mode, parallel 입력 추가
│
├── api/
│   ├── main.py                         # ✨ UPDATE — /api/results/compare-devices 추가
│   ├── db.py                           # ✅ 변경 없음
│   ├── loader.py                       # ✅ 변경 없음
│   ├── stats.py                        # ✨ UPDATE — compute_compare_devices 추가
│   ├── schemas.py                      # ✨ UPDATE — DeviceCompareResult 추가
│   └── requirements.txt                # ✅ 변경 없음
│
├── scripts/
│   ├── device_discovery.py             # ✨ NEW — ADB 디바이스 검색 공유 유틸
│   ├── runner.py                       # ✨ UPDATE — --serial, --all-devices, --parallel
│   ├── sync_results.py                 # ✨ UPDATE — --serial, --all-devices
│   ├── shuttle.py                      # ✨ UPDATE — --serial, --all-devices
│   ├── ingest.py                       # ✅ 변경 없음
│   └── setup.py                        # ✅ 변경 없음
│
├── dashboard/src/
│   ├── pages/
│   │   └── DeviceCompare.tsx           # ✨ NEW
│   ├── hooks/
│   │   └── useDeviceCompare.ts         # ✨ NEW
│   ├── types/
│   │   └── index.ts                    # ✨ UPDATE — DeviceCompareResult
│   └── components/
│       ├── layout/
│       │   └── Sidebar.tsx             # ✨ UPDATE — Device Compare 메뉴
│       └── charts/
│           └── DeviceRadar.tsx         # ✨ NEW
│
├── data/
│   └── llm_tester.db                  # ✅ 유지 — 멀티디바이스 결과 자동 적재
│
├── logs/                               # ✨ NEW — 병렬 모드 디바이스별 로그
│   ├── RFXXXXXXXX_runner.log           # (병렬 실행 시 자동 생성)
│   └── R5XXXXXXXX_runner.log
│
├── results/                            # ✅ 유지
│   ├── SM-S931U/                       # 기존 디바이스
│   │   └── gemma3-1b-it-int4.task/
│   └── SM-S926U/                       # ✨ 추가 디바이스 (자동 생성)
│       └── gemma3-1b-it-int4.task/
│
└── test_config.json                    # ✅ 변경 없음
```

## 12. Implementation Order

```
Step 1: device_discovery.py + thermal guard
        → scripts/device_discovery.py 작성 (discover_devices, validate_device, check_thermal, wait_for_cool_down)
        → discover_devices()에 serial 기준 정렬 포함
        → 단독 테스트: 연결 디바이스 목록 + 온도 출력 확인

Step 2: runner.py 멀티디바이스 지원 (순차 모드)
        → 모든 adb_* 함수에 serial 파라미터 추가
        → --serial, --all-devices CLI 플래그 추가
        → 순차 모드: per-device (thermal check → test → sync) 파이프라인
        → 단일 디바이스 호환 테스트: python scripts/runner.py (기존 동작 유지)
        → 멀티디바이스 테스트: python scripts/runner.py --all-devices (2대 연결)
        → 검증: results/ 하위에 디바이스별 디렉토리 생성 확인

Step 3: sync_results.py + shuttle.py 멀티디바이스 지원
        → sync_results.py에 --serial, --all-devices 추가
        → shuttle.py에 --serial, --all-devices 추가 (순차 push)
        → 파이프라인 테스트: shuttle.py --all-devices → runner.py --all-devices → ingest.py
        → 검증: 두 디바이스의 결과가 DB에 모두 적재됨

Step 4: runner.py 병렬 모드 (옵션)
        → --parallel 플래그 추가
        → subprocess.Popen + logs/{serial}_runner.log 파일 분리
        → 테스트: python scripts/runner.py --all-devices --parallel
        → 검증: 총 실행 시간이 순차 대비 단축됨 + 로그 파일 정상 분리

Step 5: CI/CD 워크플로우 업데이트
        → benchmark.yml에 device_mode, parallel 입력 추가
        → shuttle.py --all-devices step 추가 (모델 사전 배포)
        → Verify ADB step에 device_count 출력 추가
        → 병렬 모드 시 logs/ artifact 업로드 추가
        → GitHub UI에서 "Run workflow" → 전체 파이프라인 E2E 테스트

Step 6: API 확장
        → /api/results/compare-devices 엔드포인트 추가
        → DeviceCompareResult Pydantic 스키마
        → compute_compare_devices 함수 (stats.py)
        → Swagger에서 테스트

Step 7: Dashboard — Device Compare 페이지
        → DeviceCompare.tsx 페이지 작성
        → useDeviceCompare.ts 훅
        → Sidebar에 메뉴 추가
        → KPI 비교 카드 + 그룹드 바 차트 (Primary) + 상세 테이블
        → DeviceRadar.tsx (Secondary, 시간 여유 있을 때)

Step 8: 문서 + 정리
        → README.md에 멀티디바이스 사용법 섹션
        → GITHUB_STEP_SUMMARY에 디바이스별 결과 요약
        → .gitignore에 logs/*.log 추가
        → 기존 단일 디바이스 가이드와의 호환성 안내
```

## 13. Extension Points (Phase 연동)

```
Phase 4 (AI Quality Eval)
  └─→ 디바이스별 응답 품질 비교 가능 (동일 프롬프트, 동일 모델, 다른 디바이스)
  └─→ Device Compare 페이지에 quality_score 컬럼 추가

향후 확장 (필요 시):
  └─→ 디바이스별 Runner 분리: Runner 라벨 llm-bench-pc1, llm-bench-pc2
  └─→ GitHub Actions matrix strategy: 디바이스 목록을 discover step에서 JSON 출력 → matrix로 전달
  └─→ 원격 디바이스 지원: ADB over TCP/IP (WiFi 연결)
  └─→ 디바이스 프로파일링: thermal throttling, battery drain 모니터링 추가
  └─→ 자동 회귀 감지: 동일 디바이스의 과거 run과 현재 run 비교 → 성능 하락 알림
```

## 14. Tech Stack (Phase 3 추가분)

| Layer | Tech | Why |
|-------|------|-----|
| **Device Discovery** | `adb devices -l` 파싱 | 표준 ADB CLI, 추가 의존성 없음 |
| **Thermal Guard** | `adb shell dumpsys battery` | 온도 체크 + 쿨다운 대기. 벤치마크 재현성 보장 |
| **병렬 실행** | `subprocess.Popen` + 파일 로그 | 디바이스별 독립 프로세스 + `logs/{serial}_runner.log` 분리 |
| **CLI 파싱** | `argparse` | 표준 라이브러리, 기존 스크립트 패턴 유지 |
| **CI 입력** | `workflow_dispatch.inputs` | GitHub UI에서 모드 선택 가능 |

※ DB, API, Dashboard 스택은 Phase 1/1.5/2와 동일. 추가 의존성 없음.

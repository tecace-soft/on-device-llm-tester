import subprocess
import time
import json
import os
from datetime import datetime

def wake_device():
    result = subprocess.check_output(
        'adb shell "dumpsys power | grep mWakefulness"',
        shell=True
    ).decode()

    if "Awake" not in result:
        subprocess.run("adb shell input keyevent 224", shell=True)
        time.sleep(0.5)
        print("📱 Screen powered on")

    subprocess.run("adb shell input keyevent 82", shell=True)
    time.sleep(0.5)
    subprocess.run("adb shell settings put global low_power 0", shell=True)
    subprocess.run("adb shell settings put system screen_off_timeout 600000", shell=True)
    print("✅ Device awake and timeout extended")

def run_test_batch(config_path="test_config.json"):
    package_name = "com.tecace.llmtester"
    results_dir = "files/results"

    if not os.path.exists(config_path):
        print(f"❌ 설정 파일({config_path})을 찾을 수 없습니다.")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    models = config.get("models", [])
    prompts = config.get("prompts", [])
    timeout_sec = config.get("timeout_sec", 60)

    def Log(msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def check_model_exists(remote_path):
        res = subprocess.run(
            f'adb shell "ls {remote_path}"',
            shell=True, capture_output=True, text=True
        )
        return res.returncode == 0

    def get_file_count():
        res = subprocess.run(
            f'adb shell "run-as {package_name} ls {results_dir} | wc -l"',
            shell=True, capture_output=True, text=True
        )
        return int(res.stdout.strip()) if res.stdout.strip().isdigit() else 0

    print("=== Batch Testing 시작 ===")
    wake_device()

    for model in models:
        model_path = model["path"]
        max_tokens = model.get("max_tokens", 1024)
        backend = model.get("backend", "CPU").upper()
        model_name = os.path.basename(model_path)

        if not check_model_exists(model_path):
            Log(f"❌ [SKIP] 모델을 찾을 수 없음: {model_path}")
            continue

        Log(f"[Model: {model_name}] [Backend: {backend}] 테스트 시작")

        for prompt in prompts:
            Log("기기 초기화...")
            subprocess.run(f"adb shell am force-stop {package_name}", shell=True)
            subprocess.run("adb logcat -c", shell=True)
            wake_device()
            time.sleep(1)

            initial_count = get_file_count()

            Log(f"Testing: {prompt[:30]}...")
            cmd = [
                "adb", "shell", "am", "start", "-W", "-S",
                "-n", f"{package_name}/.MainActivity",
                "--es", "model_path", model_path,
                "--es", "input_prompt", f"\"{prompt}\"",
                "--ei", "max_tokens", str(max_tokens),
                "--es", "backend", backend
            ]
            subprocess.run(cmd, capture_output=True)

            start_time = time.time()
            success = False

            while time.time() - start_time < timeout_sec:
                error_check = subprocess.run(
                    "adb logcat -d -s LLM_TESTER:E",
                    shell=True, capture_output=True, text=True
                )
                if error_check.stdout.strip():
                    Log("⚠️ [APP ERROR] 앱 내부 오류 발생")
                    break

                if get_file_count() > initial_count:
                    Log("✅ [SUCCESS]")
                    success = True
                    break

                print(".", end="", flush=True)
                time.sleep(2)

            if not success:
                Log(f"❌ [FAILED] {model_name} 응답 없음 또는 오류 발생")

            time.sleep(5)

    print("\n=== 모든 배치 테스트 완료 ===")

if __name__ == "__main__":
    run_test_batch()
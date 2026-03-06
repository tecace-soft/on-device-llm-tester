import subprocess
import os
import json

def sync_results():
    package_name = "com.tecace.llmtester"
    remote_dir = "files/results"
    local_dir = "./results"

    list_cmd = f'adb shell "run-as {package_name} ls {remote_dir}"'
    res = subprocess.run(list_cmd, shell=True, capture_output=True)

    file_list_raw = res.stdout.decode('utf-8', errors='ignore').strip()

    if not file_list_raw:
        print("📭 수집할 새로운 결과 파일이 없습니다.")
        return

    files = file_list_raw.split()
    print(f"📦 총 {len(files)}개의 파일 수집 시작...")

    synced = 0
    errors = 0

    for file_name in files:
        file_name = file_name.strip()
        if not file_name.endswith(".json"):
            continue

        remote_path = f"{remote_dir}/{file_name}"

        cat_cmd = f'adb shell "run-as {package_name} cat {remote_path}"'
        content = subprocess.run(cat_cmd, shell=True, capture_output=True)

        if content.returncode != 0 or not content.stdout:
            print(f"❌ {file_name} 읽기 실패 (데이터 없음)")
            errors += 1
            continue

        try:
            decoded_text = content.stdout.decode('utf-8', errors='replace')
            data = json.loads(decoded_text)

            device = data.get("device", {})
            device_model = device.get("model", "unknown_device")
            model_name = data.get("model_name", "unknown_model")

            device_model = sanitize_dirname(device_model)
            model_name = sanitize_dirname(model_name)

            target_dir = os.path.join(local_dir, device_model, model_name)
            os.makedirs(target_dir, exist_ok=True)

            target_path = os.path.join(target_dir, file_name)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(decoded_text)

            print(f"✅ {file_name} → {device_model}/{model_name}/")
            synced += 1

        except json.JSONDecodeError:
            fallback_dir = os.path.join(local_dir, "_unclassified")
            os.makedirs(fallback_dir, exist_ok=True)
            fallback_path = os.path.join(fallback_dir, file_name)
            with open(fallback_path, "w", encoding="utf-8") as f:
                f.write(decoded_text)
            print(f"⚠️ {file_name} → JSON 파싱 실패, _unclassified/에 저장")
            errors += 1

        except Exception as e:
            print(f"❌ {file_name} 처리 중 에러: {e}")
            errors += 1

    print(f"\n🏁 동기화 완료! (성공: {synced}, 실패: {errors})")
    print(f"📂 결과 위치: {os.path.abspath(local_dir)}")

def sanitize_dirname(name):
    return name.replace("/", "_").replace("\\", "_").replace(":", "_").replace(" ", "_")

if __name__ == "__main__":
    sync_results()
import os
import subprocess
from dotenv import load_dotenv

load_dotenv()

def sync_models_to_phone():
    """
    LOCAL_MODEL_DIR 내의 모든 파일을 PHONE_MODEL_PATH로 동기화합니다.
    """
    local_dir = os.getenv("LOCAL_MODEL_DIR")
    remote_dir = os.getenv("PHONE_MODEL_PATH")

    # 1. 로컬 폴더 존재 확인
    if not os.path.exists(local_dir):
        print(f"❌ Error: Local directory '{local_dir}' not found.")
        return

    # 2. 로컬에 파일이 있는지 확인
    local_files = os.listdir(local_dir)
    if not local_files:
        print(f"⚠️ Warning: No files found in '{local_dir}'. Nothing to sync.")
        return

    print(f"📂 Found {len(local_files)} files in {local_dir}. Starting sync...")

    # 3. 폰 내 목적지 폴더 생성
    subprocess.run(["adb", "shell", f"mkdir -p {remote_dir}"], check=True)

    # 4. 폴더 통째로 Push
    # 폴더 경로 끝에 '/.'를 붙이면 폴더 자체가 아닌 '내용물'만 복사됩니다.
    print(f"🚀 Syncing models to {remote_dir}...")
    push_result = subprocess.run(
        ["adb", "push", f"{local_dir}/.", remote_dir], 
        capture_output=True, 
        text=True
    )

    if push_result.returncode == 0:
        print("✅ Sync complete.")
        # 5. 폰에 있는 파일 리스트 출력 (검증)
        print("\n📱 [Current Models on Phone]")
        verify_result = subprocess.run(
            ["adb", "shell", f"ls -1 {remote_dir}"], 
            capture_output=True, 
            text=True
        )
        print(verify_result.stdout)
    else:
        print(f"❌ Sync failed: {push_result.stderr}")

if __name__ == "__main__":
    sync_models_to_phone()
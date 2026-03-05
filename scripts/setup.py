import os
from dotenv import load_dotenv

def init_project():
    load_dotenv()

    local_model_dir = os.getenv("LOCAL_MODEL_DIR")
    if not local_model_dir:
        print("❌ .env에 LOCAL_MODEL_DIR이 설정되지 않았습니다.")
        return

    dirs = [local_model_dir, "./results", "./logs"]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        print(f"📁 Created local directory: {d}")

    print("\n✅ Project environment is ready.")

if __name__ == "__main__":
    init_project()
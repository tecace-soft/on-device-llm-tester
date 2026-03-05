# import subprocess
# import os
# import tarfile

# def sync_results():
#     package_name = "com.tecace.llmtester"
#     local_dir = "./results"
#     remote_tmp_tar = "/data/local/tmp/results_sync.tar"
#     local_tar_path = os.path.join(local_dir, "results_sync.tar")

#     # 1. 수집할 파일이 있는지 먼저 확인
#     res = subprocess.run(f'adb shell "run-as {package_name} ls files/results | wc -l"', 
#                          shell=True, capture_output=True, text=True)
#     count = int(res.stdout.strip()) if res.stdout.strip().isdigit() else 0
    
#     if count == 0:
#         print("📭 수집할 새로운 결과 파일이 없습니다.")
#         return

#     print(f"📦 총 {count}개의 결과를 가져옵니다...")

#     # 2. 압축 및 Pull
#     subprocess.run(f'adb shell "run-as {package_name} tar -cvf {remote_tmp_tar} -C files/results ."', shell=True)
#     subprocess.run(f"adb pull {remote_tmp_tar} {local_tar_path}", shell=True)

#     # 3. 압축 해제 및 정리
#     if os.path.exists(local_tar_path):
#         with tarfile.open(local_tar_path) as tar:
#             tar.extractall(path=local_dir)
#         os.remove(local_tar_path)
#         print(f"✅ 동기화 완료! '{local_dir}' 폴더를 확인하세요.")
        
#         # (선택) 수집 완료 후 기기 데이터 청소 - 다음 자동화 테스트를 위해 깨끗하게 유지
#         # subprocess.run(f'adb shell "run-as {package_name} rm -rf files/results/*"', shell=True)

# if __name__ == "__main__":
#     sync_results()

# import subprocess
# import os

# def sync_results():
#     package_name = "com.tecace.llmtester"
#     remote_dir = "files/results"
#     local_dir = "./results"

#     # 1. 파일 목록 가져오기
#     list_cmd = f'adb shell "run-as {package_name} ls {remote_dir}"'
#     res = subprocess.run(list_cmd, shell=True, capture_output=True, text=True)
    
#     if res.returncode != 0 or not res.stdout.strip():
#         print("📭 수집할 파일이 없습니다.")
#         return

#     files = res.stdout.split()
#     print(f"📦 총 {len(files)}개의 파일을 발견했습니다. 수집을 시작합니다...")

#     for file_name in files:
#         file_name = file_name.strip()
#         if not file_name.endswith(".json"): continue

#         # 2. 각 파일의 내용을 cat으로 읽어서 로컬에 쓰기
#         remote_path = f"{remote_dir}/{file_name}"
#         local_path = os.path.join(local_dir, file_name)
        
#         # run-as로 읽은 내용을 파이썬이 받아 파일로 저장
#         cat_cmd = f'adb shell "run-as {package_name} cat {remote_path}"'
#         content = subprocess.run(cat_cmd, shell=True, capture_output=True, text=True)
        
#         if content.returncode == 0:
#             with open(local_path, "w", encoding="utf-8") as f:
#                 f.write(content.stdout)
#             print(f"✅ 가져옴: {file_name}")
#         else:
#             print(f"❌ 실패: {file_name}")

#     print(f"\n🏁 동기화 완료! '{local_dir}' 폴더를 확인해 보세요.")

# if __name__ == "__main__":
#     sync_results()

import subprocess
import os

def sync_results():
    package_name = "com.tecace.llmtester"
    remote_dir = "files/results"
    local_dir = "./results"

    # 1. 파일 목록 가져오기 (바이너리로 받아 디코딩)
    list_cmd = f'adb shell "run-as {package_name} ls {remote_dir}"'
    res = subprocess.run(list_cmd, shell=True, capture_output=True)
    
    # 리스트를 가져올 때도 utf-8로 디코딩 (에러 무시 옵션 포함)
    file_list_raw = res.stdout.decode('utf-8', errors='ignore').strip()
    
    if not file_list_raw:
        print("📭 수집할 새로운 결과 파일이 없습니다.")
        return

    files = file_list_raw.split()
    print(f"📦 총 {len(files)}개의 파일 수집 시작...")

    for file_name in files:
        file_name = file_name.strip()
        if not file_name.endswith(".json"): continue

        remote_path = f"{remote_dir}/{file_name}"
        local_path = os.path.join(local_dir, file_name)
        
        # 2. 핵심 수정: text=True를 빼고 바이너리(bytes)로 가져오기
        cat_cmd = f'adb shell "run-as {package_name} cat {remote_path}"'
        content = subprocess.run(cat_cmd, shell=True, capture_output=True)
        
        # content.stdout은 이제 bytes 타입입니다.
        if content.returncode == 0 and content.stdout:
            try:
                # 3. 명시적으로 utf-8 디코딩 (혹시 모를 깨진 문자는 대체)
                decoded_text = content.stdout.decode('utf-8', errors='replace')
                
                # 4. 저장할 때도 반드시 utf-8 명시
                with open(local_path, "w", encoding="utf-8") as f:
                    f.write(decoded_text)
                print(f"✅ 수집 성공: {file_name}")
                
            except Exception as e:
                print(f"❌ {file_name} 처리 중 에러: {e}")
        else:
            print(f"❌ {file_name} 읽기 실패 (데이터 없음)")

    print(f"\n🏁 동기화 완료! '{local_dir}' 폴더를 확인해 보세요.")

if __name__ == "__main__":
    sync_results()
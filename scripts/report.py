# import json
# import os
# import csv
# from datetime import datetime

# def generate_report():
#     local_results_dir = "./results"
#     output_csv = f"llm_performance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
#     all_data = []
    
#     # 1. 로컬 폴더의 모든 JSON 읽기
#     if not os.path.exists(local_results_dir):
#         print(f"❌ '{local_results_dir}' 폴더가 없습니다.")
#         return

#     print(f"📝 결과 분석 시작 (위치: {local_results_dir})")
    
#     for file_name in os.listdir(local_results_dir):
#         if file_name.endswith(".json"):
#             file_path = os.path.join(local_results_dir, file_name)
#             try:
#                 with open(file_path, "r", encoding="utf-8") as f:
#                     data = json.load(f)
#                     all_data.append(data)
#             except Exception as e:
#                 print(f"⚠️ {file_name} 읽기 실패: {e}")

#     if not all_data:
#         print("📭 분석할 데이터가 없습니다.")
#         return

#     # 2. 통계 계산
#     latencies = [d['latency_ms'] for d in all_data if 'latency_ms' in d]
#     avg_latency = sum(latencies) / len(latencies) if latencies else 0
#     max_latency = max(latencies) if latencies else 0
#     min_latency = min(latencies) if latencies else 0

#     # 3. 터미널 요약 출력 (미팅용)
#     print("\n" + "="*40)
#     print("       LLM Performance Summary")
#     print("="*40)
#     print(f"🔹 총 테스트 횟수: {len(all_data)}회")
#     print(f"🔹 평균 지연 시간: {avg_latency:.2f} ms")
#     print(f"🔹 최소 지연 시간: {min_latency} ms")
#     print(f"🔹 최대 지연 시간: {max_latency} ms")
#     print("="*40)

#     # 4. CSV 저장 (Excel용)
#     # keys = all_data[0].keys()
#     # with open(output_csv, 'w', newline='', encoding='utf-8') as f:
#     #     dict_writer = csv.DictWriter(f, fieldnames=keys)
#     #     dict_writer.writeheader()
#     #     dict_writer.writerows(all_data)

#     # print(f"\n✅ 보고서 생성 완료: {output_csv}")
# # 4. CSV 저장 (Metadata 요약 섹션 + 상세 데이터)
#     keys = all_data[0].keys()
#     with open(output_csv, 'w', newline='', encoding='utf-8') as f:
#         # --- [상단 요약 섹션 추가] ---
#         f.write(f"# --- LLM PERFORMANCE SUMMARY ---\n")
#         f.write(f"# Total Tests,{len(all_data)}\n")
#         f.write(f"# Avg Latency,{avg_latency:.2f} ms\n")
#         f.write(f"# Min Latency,{min_latency} ms\n")
#         f.write(f"# Max Latency,{max_latency} ms\n")
#         f.write(f"# Generated At,{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
#         f.write(f"# -------------------------------\n\n") # 가독성을 위해 한 줄 띄움
        
#         # --- [실제 데이터 섹션] ---
#         dict_writer = csv.DictWriter(f, fieldnames=keys)
#         dict_writer.writeheader()
#         dict_writer.writerows(all_data)

#     print(f"\n✅ 보고서 생성 완료 (요약 정보 포함): {output_csv}")


    
# if __name__ == "__main__":
#     generate_report()

import json
import os
import pandas as pd
from datetime import datetime

def generate_report():
    local_results_dir = "./results"
    # 확장자를 .xlsx로 변경
    output_excel = f"llm_performance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    all_data = []
    
    # 1. 로컬 폴더의 모든 JSON 읽기
    if not os.path.exists(local_results_dir):
        print(f"❌ '{local_results_dir}' 폴더가 없습니다.")
        return

    print(f"📝 결과 분석 시작 (위치: {local_results_dir})")
    
    for file_name in os.listdir(local_results_dir):
        if file_name.endswith(".json"):
            file_path = os.path.join(local_results_dir, file_name)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    all_data.append(data)
            except Exception as e:
                print(f"⚠️ {file_name} 읽기 실패: {e}")

    if not all_data:
        print("📭 분석할 데이터가 없습니다.")
        return

    # 2. Pandas 데이터프레임 생성
    df = pd.DataFrame(all_data)

    # 3. 통계 계산
    avg_latency = df['latency_ms'].mean() if 'latency_ms' in df.columns else 0
    max_latency = df['latency_ms'].max() if 'latency_ms' in df.columns else 0
    min_latency = df['latency_ms'].min() if 'latency_ms' in df.columns else 0

    # 요약 정보용 데이터프레임
    summary_data = {
        "Metric": ["Total Tests", "Avg Latency (ms)", "Min Latency (ms)", "Max Latency (ms)", "Generated At"],
        "Value": [len(df), round(avg_latency, 2), min_latency, max_latency, datetime.now().strftime('%Y-%m-%d %H:%M:%S')]
    }
    summary_df = pd.DataFrame(summary_data)

    # 4. 엑셀 저장 (시트 분리형)
    try:
        with pd.ExcelWriter(output_excel, engine='openpyxl') as writer:
            # 첫 번째 시트: 요약 리포트
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            # 두 번째 시트: 상세 로우 데이터
            df.to_excel(writer, sheet_name='Raw_Data', index=False)
            
            # 시트 너비 자동 조정 등 추가 스타일링이 가능하지만 우선 기본 저장
        
        print("\n" + "="*40)
        print("       LLM Performance Summary")
        print("="*40)
        print(f"🔹 총 테스트 횟수: {len(df)}회")
        print(f"🔹 평균 지연 시간: {avg_latency:.2f} ms")
        print(f"🔹 최소 지연 시간: {min_latency} ms")
        print(f"🔹 최대 지연 시간: {max_latency} ms")
        print("="*40)
        print(f"\n✅ 엑셀 보고서 생성 완료: {output_excel}")
        
    except Exception as e:
        print(f"❌ 엑셀 저장 중 오류 발생: {e}")

if __name__ == "__main__":
    generate_report()
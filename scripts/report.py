import json
import os
import csv
from datetime import datetime

def generate_report():
    local_results_dir = "./results"
    output_csv = f"llm_performance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    all_data = []

    if not os.path.exists(local_results_dir):
        print(f"❌ '{local_results_dir}' 폴더가 없습니다.")
        return

    print(f"📝 결과 분석 시작 (위치: {local_results_dir})")

    for file_name in sorted(os.listdir(local_results_dir)):
        if not file_name.endswith(".json"):
            continue
        file_path = os.path.join(local_results_dir, file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"⚠️ {file_name} 읽기 실패: {e}")
            continue

        device = data.get("device", {})
        row = {
            "status": data.get("status", ""),
            "prompt_id": data.get("prompt_id", ""),
            "prompt_category": data.get("prompt_category", ""),
            "prompt_lang": data.get("prompt_lang", ""),
            "model_name": data.get("model_name", ""),
            "backend": data.get("backend", ""),
            "device_manufacturer": device.get("manufacturer", ""),
            "device_model": device.get("model", ""),
            "device_product": device.get("product", ""),
            "device_soc": device.get("soc", ""),
            "android_version": device.get("android_version", ""),
            "sdk_int": device.get("sdk_int", ""),
            "cpu_cores": device.get("cpu_cores", ""),
            "max_heap_mb": device.get("max_heap_mb", ""),
            "prompt": data.get("prompt", ""),
            "response": data.get("response", ""),
            "latency_ms": data.get("latency_ms", ""),
            "timestamp": data.get("timestamp", ""),
        }
        all_data.append(row)

    if not all_data:
        print("📭 분석할 데이터가 없습니다.")
        return

    success_data = [d for d in all_data if d["status"] == "success" and d["latency_ms"] != ""]
    latencies = [d["latency_ms"] for d in success_data]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    min_latency = min(latencies) if latencies else 0
    max_latency = max(latencies) if latencies else 0
    error_count = sum(1 for d in all_data if d["status"] == "error")

    print("\n" + "=" * 50)
    print("         LLM Performance Summary")
    print("=" * 50)
    print(f"  Total Tests : {len(all_data)}")
    print(f"  Success     : {len(success_data)}")
    print(f"  Errors      : {error_count}")
    print(f"  Avg Latency : {avg_latency:,.2f} ms")
    print(f"  Min Latency : {min_latency:,} ms")
    print(f"  Max Latency : {max_latency:,} ms")
    print("=" * 50)

    fieldnames = list(all_data[0].keys())
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_data)

    print(f"\n✅ CSV 보고서 생성 완료: {output_csv}")

if __name__ == "__main__":
    generate_report()
import json
import os
import csv
from datetime import datetime

RESULTS_DIR = "./results"
REPORTS_DIR = "./reports"

def load_json_files(directory):
    rows = []
    for file_name in sorted(os.listdir(directory)):
        if not file_name.endswith(".json"):
            continue
        file_path = os.path.join(directory, file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"  ⚠️ {file_name} 읽기 실패: {e}")
            continue

        device = data.get("device", {})
        rows.append({
            "status": data.get("status", ""),
            "prompt_id": data.get("prompt_id", ""),
            "prompt_category": data.get("prompt_category", ""),
            "prompt_lang": data.get("prompt_lang", ""),
            "model_name": data.get("model_name", ""),
            "backend": data.get("backend", ""),
            "device_manufacturer": device.get("manufacturer", ""),
            "device_model": device.get("model", ""),
            "device_soc": device.get("soc", ""),
            "android_version": device.get("android_version", ""),
            "cpu_cores": device.get("cpu_cores", ""),
            "max_heap_mb": device.get("max_heap_mb", ""),
            "prompt": data.get("prompt", ""),
            "response": data.get("response", ""),
            "latency_ms": data.get("latency_ms", ""),
            "timestamp": data.get("timestamp", ""),
        })
    return rows

def compute_stats(rows):
    success = [r for r in rows if r["status"] == "success" and r["latency_ms"] != ""]
    if not success:
        return None
    latencies = [r["latency_ms"] for r in success]
    return {
        "total": len(rows),
        "success": len(success),
        "errors": len(rows) - len(success),
        "avg": sum(latencies) / len(latencies),
        "min": min(latencies),
        "max": max(latencies),
    }

def write_csv(rows, output_path):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

class ReportWriter:
    def __init__(self, txt_path):
        self.txt_file = open(txt_path, "w", encoding="utf-8")

    def write(self, line=""):
        print(line)
        self.txt_file.write(line + "\n")

    def close(self):
        self.txt_file.close()

    def write_stats(self, label, stats):
        if not stats:
            self.write(f"  {label}: no data")
            return
        self.write(f"  {label}")
        self.write(f"    Tests: {stats['success']}/{stats['total']} (errors: {stats['errors']})")
        self.write(f"    Avg: {stats['avg']:,.2f} ms | Min: {stats['min']:,} ms | Max: {stats['max']:,} ms")

def generate_report():
    if not os.path.exists(RESULTS_DIR):
        print(f"❌ '{RESULTS_DIR}' 폴더가 없습니다.")
        return

    os.makedirs(REPORTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    summary_path = os.path.join(REPORTS_DIR, f"summary_{timestamp}.txt")
    out = ReportWriter(summary_path)

    all_rows = []

    out.write("=" * 60)
    out.write("         LLM Performance Report")
    out.write(f"         Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    out.write("=" * 60)

    for device_dir in sorted(os.listdir(RESULTS_DIR)):
        device_path = os.path.join(RESULTS_DIR, device_dir)
        if not os.path.isdir(device_path) or device_dir.startswith("_"):
            continue

        out.write(f"\nDevice: {device_dir}")
        out.write("-" * 50)

        for model_dir in sorted(os.listdir(device_path)):
            model_path = os.path.join(device_path, model_dir)
            if not os.path.isdir(model_path):
                continue

            rows = load_json_files(model_path)
            if not rows:
                continue

            all_rows.extend(rows)

            stats = compute_stats(rows)
            out.write_stats(model_dir, stats)

            csv_name = f"{device_dir}_{model_dir}_{timestamp}.csv"
            write_csv(rows, os.path.join(REPORTS_DIR, csv_name))

    if not all_rows:
        out.write("No data to analyze.")
        out.close()
        return

    master_csv = os.path.join(REPORTS_DIR, f"all_results_{timestamp}.csv")
    write_csv(all_rows, master_csv)

    overall = compute_stats(all_rows)
    out.write("")
    out.write("=" * 60)
    out.write_stats("Overall", overall)
    out.write("=" * 60)

    out.close()
    print(f"\n✅ Summary saved: {os.path.abspath(summary_path)}")
    print(f"✅ CSVs saved: {os.path.abspath(REPORTS_DIR)}")

if __name__ == "__main__":
    generate_report()
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
        metrics = data.get("metrics", {})

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
            "init_time_ms": data.get("init_time_ms", ""),
            "ttft_ms": metrics.get("ttft_ms", ""),
            "prefill_time_ms": metrics.get("prefill_time_ms", ""),
            "decode_time_ms": metrics.get("decode_time_ms", ""),
            "input_token_count": metrics.get("input_token_count", ""),
            "output_token_count": metrics.get("output_token_count", ""),
            "prefill_tps": metrics.get("prefill_tps", ""),
            "decode_tps": metrics.get("decode_tps", ""),
            "peak_java_memory_mb": metrics.get("peak_java_memory_mb", ""),
            "peak_native_memory_mb": metrics.get("peak_native_memory_mb", ""),
            "itl_p50_ms": metrics.get("itl_p50_ms", ""),
            "itl_p95_ms": metrics.get("itl_p95_ms", ""),
            "itl_p99_ms": metrics.get("itl_p99_ms", ""),
            "timestamp": data.get("timestamp", ""),
        })
    return rows

def percentile(sorted_vals, p):
    if not sorted_vals:
        return 0
    idx = int(p / 100.0 * (len(sorted_vals) - 1))
    return sorted_vals[min(idx, len(sorted_vals) - 1)]

def compute_stats(rows):
    success = [r for r in rows if r["status"] == "success" and r["latency_ms"] != ""]
    if not success:
        return None

    def safe_vals(key):
        return [r[key] for r in success if r[key] != "" and r[key] is not None]

    latencies = sorted(safe_vals("latency_ms"))
    ttfts = safe_vals("ttft_ms")
    decode_tps_vals = safe_vals("decode_tps")
    prefill_tps_vals = safe_vals("prefill_tps")
    init_times = safe_vals("init_time_ms")
    peak_java_mems = safe_vals("peak_java_memory_mb")
    peak_native_mems = safe_vals("peak_native_memory_mb")
    output_tokens = safe_vals("output_token_count")

    def avg(vals):
        return sum(vals) / len(vals) if vals else 0

    return {
        "total": len(rows),
        "success": len(success),
        "errors": len(rows) - len(success),
        "avg_latency": avg(latencies),
        "min_latency": min(latencies) if latencies else 0,
        "max_latency": max(latencies) if latencies else 0,
        "p50_latency": percentile(latencies, 50),
        "p95_latency": percentile(latencies, 95),
        "p99_latency": percentile(latencies, 99),
        "avg_ttft": avg(ttfts),
        "avg_decode_tps": avg(decode_tps_vals),
        "avg_prefill_tps": avg(prefill_tps_vals),
        "avg_init_time": avg(init_times),
        "avg_peak_java_mem": avg(peak_java_mems),
        "avg_peak_native_mem": avg(peak_native_mems),
        "avg_output_tokens": avg(output_tokens),
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
        self.write(f"    Latency (p50|p95|p99) — {stats['p50_latency']:,.0f} | {stats['p95_latency']:,.0f} | {stats['p99_latency']:,.0f} ms  (Avg: {stats['avg_latency']:,.0f} | Min: {stats['min_latency']:,} | Max: {stats['max_latency']:,} ms)")
        if stats["avg_ttft"]:
            self.write(f"    TTFT         — Avg: {stats['avg_ttft']:,.0f} ms")
        if stats["avg_decode_tps"]:
            self.write(f"    Decode TPS   — Avg: {stats['avg_decode_tps']:,.1f} tok/s")
        if stats["avg_prefill_tps"]:
            self.write(f"    Prefill TPS  — Avg: {stats['avg_prefill_tps']:,.1f} tok/s")
        if stats["avg_init_time"]:
            self.write(f"    Init Time    — Avg: {stats['avg_init_time']:,.0f} ms")
        if stats["avg_peak_native_mem"]:
            self.write(f"    Peak Memory  — Native: {stats['avg_peak_native_mem']:,.0f} MB | Java: {stats['avg_peak_java_mem']:,.0f} MB")
        if stats["avg_output_tokens"]:
            self.write(f"    Output Tokens— Avg: {stats['avg_output_tokens']:,.0f}")

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
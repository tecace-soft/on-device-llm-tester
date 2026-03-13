from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

from schemas import DeviceInfo, Metrics, ResultItem

logger = logging.getLogger(__name__)

RESULTS_DIR = os.getenv("RESULTS_DIR", "./results")


def _parse_file(file_path: str) -> Optional[ResultItem]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"Skip {file_path}: {e}")
        return None

    device_raw = data.get("device", {})
    metrics_raw = data.get("metrics")

    try:
        device = DeviceInfo(**{k: device_raw.get(k, v) for k, v in DeviceInfo().model_fields.items()
                               if k in device_raw} if device_raw else {})
        device = DeviceInfo(
            manufacturer=device_raw.get("manufacturer", ""),
            model=device_raw.get("model", ""),
            product=device_raw.get("product", ""),
            soc=device_raw.get("soc", ""),
            android_version=device_raw.get("android_version", ""),
            sdk_int=device_raw.get("sdk_int", 0),
            cpu_cores=device_raw.get("cpu_cores", 0),
            max_heap_mb=device_raw.get("max_heap_mb", 0),
        )
    except Exception:
        device = DeviceInfo()

    metrics = None
    if metrics_raw and isinstance(metrics_raw, dict):
        try:
            metrics = Metrics(
                ttft_ms=metrics_raw.get("ttft_ms"),
                prefill_time_ms=metrics_raw.get("prefill_time_ms"),
                decode_time_ms=metrics_raw.get("decode_time_ms"),
                input_token_count=metrics_raw.get("input_token_count"),
                output_token_count=metrics_raw.get("output_token_count"),
                prefill_tps=metrics_raw.get("prefill_tps"),
                decode_tps=metrics_raw.get("decode_tps"),
                peak_java_memory_mb=metrics_raw.get("peak_java_memory_mb"),
                peak_native_memory_mb=metrics_raw.get("peak_native_memory_mb"),
                itl_p50_ms=metrics_raw.get("itl_p50_ms"),
                itl_p95_ms=metrics_raw.get("itl_p95_ms"),
                itl_p99_ms=metrics_raw.get("itl_p99_ms"),
            )
        except Exception:
            pass

    return ResultItem(
        status=data.get("status", ""),
        prompt_id=data.get("prompt_id", ""),
        prompt_category=data.get("prompt_category", ""),
        prompt_lang=data.get("prompt_lang", ""),
        model_name=data.get("model_name", ""),
        model_path=data.get("model_path", ""),
        backend=data.get("backend", ""),
        device=device,
        prompt=data.get("prompt", ""),
        response=data.get("response", ""),
        latency_ms=data.get("latency_ms") if data.get("latency_ms") != "" else None,
        init_time_ms=data.get("init_time_ms") if data.get("init_time_ms") != "" else None,
        metrics=metrics,
        error=data.get("error"),
        timestamp=data.get("timestamp"),
    )


def load_all(
    results_dir: str = RESULTS_DIR,
    device: Optional[str] = None,
    model: Optional[str] = None,
    category: Optional[str] = None,
    backend: Optional[str] = None,
    status: Optional[str] = None,  # "success" | "error" | None (all)
) -> List[ResultItem]:
    rows: List[ResultItem] = []

    if not os.path.isdir(results_dir):
        return rows

    for device_dir in sorted(os.listdir(results_dir)):
        device_path = os.path.join(results_dir, device_dir)
        if not os.path.isdir(device_path) or device_dir.startswith("_"):
            continue

        if device and device_dir != device:
            continue

        for model_dir in sorted(os.listdir(device_path)):
            model_path = os.path.join(device_path, model_dir)
            if not os.path.isdir(model_path):
                continue

            if model and model_dir != model:
                continue

            for file_name in sorted(os.listdir(model_path)):
                if not file_name.endswith(".json"):
                    continue

                item = _parse_file(os.path.join(model_path, file_name))
                if item is None:
                    continue

                if category and item.prompt_category != category:
                    continue
                if backend and item.backend.upper() != backend.upper():
                    continue
                if status and status != "all" and item.status != status:
                    continue

                rows.append(item)

    return rows


def list_devices(results_dir: str = RESULTS_DIR) -> List[str]:
    if not os.path.isdir(results_dir):
        return []
    return sorted(
        d for d in os.listdir(results_dir)
        if os.path.isdir(os.path.join(results_dir, d)) and not d.startswith("_")
    )


def list_models(results_dir: str = RESULTS_DIR, device: Optional[str] = None) -> List[str]:
    models = set()
    if not os.path.isdir(results_dir):
        return []
    for device_dir in os.listdir(results_dir):
        device_path = os.path.join(results_dir, device_dir)
        if not os.path.isdir(device_path) or device_dir.startswith("_"):
            continue
        if device and device_dir != device:
            continue
        for model_dir in os.listdir(device_path):
            if os.path.isdir(os.path.join(device_path, model_dir)):
                models.add(model_dir)
    return sorted(models)


def list_categories(results_dir: str = RESULTS_DIR) -> List[str]:
    cats = set()
    for item in load_all(results_dir):
        if item.prompt_category:
            cats.add(item.prompt_category)
    return sorted(cats)

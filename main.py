import requests
import cv2
import numpy as np
import pandas as pd
import sys
import time
import os
from pathlib import Path
from datetime import datetime

ESP32_IP  = "192.168.1.9"
BASE_URL  = f"http://{ESP32_IP}"
IMG_SIZE  = 32
LABEL_CSV = "labels.csv"
TEST_DIR  = "offline_test"

def preprocess(image_path: str) -> bytes:
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Không đọc được: {image_path}")
    img = cv2.resize(img, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return img.astype(np.uint8).tobytes()

def ping() -> bool:
    try:
        r = requests.get(f"{BASE_URL}/ping", timeout=3)
        return r.status_code == 200
    except Exception:
        return False

def infer_one(image_path: str):
    raw = preprocess(image_path)
    t0  = time.perf_counter()
    resp = requests.post(
        f"{BASE_URL}/infer",
        data=raw,
        headers={"Content-Type": "application/octet-stream"},
        timeout=15,
    )
    rtt_ms = (time.perf_counter() - t0) * 1000
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
    r = resp.json()
    r["rtt_ms"] = rtt_ms
    return r

def main():
    df_label = pd.read_csv(LABEL_CSV, dtype={"Id": str})
    df_label["Id"] = df_label["Id"].str.zfill(5)
    label_map = dict(zip(df_label["Id"], df_label["Label"]))

    png_files = sorted(Path(TEST_DIR).glob("*.png"))
    if not png_files:
        print(f"[LỖI] Không tìm thấy file PNG trong '{TEST_DIR}/'")
        sys.exit(1)

    print(f"[*] Kiểm tra kết nối {BASE_URL} ...")
    if not ping():
        print("[LỖI] Không ping được ESP32.")
        sys.exit(1)
    print(f"[*] ESP32 online ✓")
    print(f"[*] Tổng ảnh: {len(png_files)} | Có label: {len(label_map)}\n")
    results = []
    t_bench_start = time.perf_counter()

    for idx, png_path in enumerate(png_files):
        file_id = png_path.stem.zfill(5)
        true_label = label_map.get(file_id, None)
        try:
            r = infer_one(str(png_path))
            pred  = r["class"]
            score = r["score"]
            correct = (pred == true_label) if true_label is not None else None

            results.append({
                "id"        : file_id,
                "file"      : png_path.name,
                "true_label": true_label,
                "pred"      : pred,
                "correct"   : correct,
                "score"     : score,
                "recv_ms"   : r["recv_ms"],
                "infer_ms"  : r["infer_ms"],
                "total_ms"  : r["total_ms"],
                "rtt_ms"    : r["rtt_ms"],
                "error"     : None,
            })

            status = "✓" if correct else ("✗" if correct is False else "?")
            print(f"  [{idx+1:>4}/{len(png_files)}] {status} {png_path.name}"
                  f" | pred={pred} true={true_label}"
                  f" | infer={r['infer_ms']:.1f}ms rtt={r['rtt_ms']:.0f}ms")

        except Exception as e:
            results.append({
                "id": file_id, "file": png_path.name,
                "true_label": true_label, "pred": None, "correct": None,
                "score": None, "recv_ms": None, "infer_ms": None,
                "total_ms": None, "rtt_ms": None, "error": str(e),
            })
            print(f"  [{idx+1:>4}/{len(png_files)}] ✗ {png_path.name} | LỖI: {e}")

    t_bench_total = (time.perf_counter() - t_bench_start) * 1000
    
    df = pd.DataFrame(results)

    has_label   = df[df["true_label"].notna() & df["error"].isna()]
    no_error    = df[df["error"].isna()]

    total       = len(df)
    n_labeled   = len(has_label)
    n_correct   = int(has_label["correct"].sum())
    n_error     = int(df["error"].notna().sum())
    accuracy    = n_correct / n_labeled * 100 if n_labeled > 0 else 0

    infer_mean  = no_error["infer_ms"].mean()
    infer_min   = no_error["infer_ms"].min()
    infer_max   = no_error["infer_ms"].max()
    infer_std   = no_error["infer_ms"].std()
    rtt_mean    = no_error["rtt_ms"].mean()
    throughput  = 1000 / rtt_mean if rtt_mean > 0 else 0
    class_stats = {}
    for cls in sorted(has_label["true_label"].unique()):
        sub = has_label[has_label["true_label"] == cls]
        acc = sub["correct"].sum() / len(sub) * 100
        class_stats[int(cls)] = {"total": len(sub), "correct": int(sub["correct"].sum()), "acc": acc}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep = "═" * 55

    report = f"""
{sep}
  BENCHMARK REPORT — ESP32-S3 TFLite Inference
  {now}
{sep}

  Thiết bị   : ESP32-S3 ({BASE_URL})
  Model      : traffic_sign_int8 (INT8 quantized)
  Input      : 32×32×3 uint8 RGB
  Test dir   : {TEST_DIR}/
  Label file : {LABEL_CSV}

{sep}
  KẾT QUẢ TỔNG QUAN
{sep}
  Tổng ảnh gửi      : {total}
  Có nhãn (label)   : {n_labeled}
  Dự đoán đúng      : {n_correct}
  Accuracy          : {accuracy:.2f}%
  Lỗi kết nối       : {n_error}

{sep}
  THỜI GIAN (chỉ tính ảnh không lỗi)
{sep}
  Inference ESP32
    Mean  : {infer_mean:.2f} ms
    Min   : {infer_min:.2f} ms
    Max   : {infer_max:.2f} ms
    Std   : {infer_std:.2f} ms

  Round-trip Python→ESP32→Python
    Mean  : {rtt_mean:.1f} ms

  Throughput (RTT-based) : {throughput:.2f} ảnh/giây
  Tổng thời gian bench   : {t_bench_total/1000:.1f} giây

{sep}
  ACCURACY THEO TỪNG CLASS
{sep}"""

    for cls, st in class_stats.items():
        bar = "█" * int(st["acc"] / 5)
        report += f"\n  Class {cls:>2} : {st['correct']:>3}/{st['total']:>3} = {st['acc']:>6.2f}%  {bar}"

    report += f"\n\n{sep}\n  SAI (predict sai label)\n{sep}"
    wrong = has_label[has_label["correct"] == False]
    if len(wrong) == 0:
        report += "\n  (Không có ảnh nào sai)"
    else:
        for _, row in wrong.iterrows():
            report += f"\n  {row['file']:>12} | true={int(row['true_label'])} pred={int(row['pred'])} score={int(row['score'])}"

    if n_error > 0:
        report += f"\n\n{sep}\n  LỖI KẾT NỐI\n{sep}"
        for _, row in df[df["error"].notna()].iterrows():
            report += f"\n  {row['file']:>12} | {row['error']}"

    report += f"\n\n{sep}\n"

    print(report)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"benchmark_report_{ts}.txt"
    csv_path    = f"benchmark_detail_{ts}.csv"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    print(f"[*] Đã lưu report : {report_path}")
    print(f"[*] Đã lưu chi tiết: {csv_path}")

if __name__ == "__main__":
    main()
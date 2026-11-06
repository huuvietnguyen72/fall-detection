"""Đánh giá model Edge Impulse trên dữ liệu SisFall bằng ĐÚNG mã C++ chạy trên ESP32 (biên dịch cho PC).

    python tinyml/evaluate_ei.py                                   # cả 2 model, tập testing
    python tinyml/evaluate_ei.py --split training --threshold 0.8

Dữ liệu: data/ei_sisfall/{training,testing}/{Fall,Normal}/*.json (định dạng Edge Impulse JSON).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "firmware" / "ei_models"
DATA_DIR = ROOT / "data" / "ei_sisfall"
WINDOW = 100  # 2 giây @ 50 Hz


def load_split(split: str) -> tuple[list[np.ndarray], list[int], list[str]]:
    xs, ys, names = [], [], []
    for label, y in (("Fall", 1), ("Normal", 0)):
        for f in sorted((DATA_DIR / split / label).glob("*.json")):
            payload = json.loads(f.read_text())["payload"]
            xs.append(np.asarray(payload["values"], dtype=np.float32))
            ys.append(y)
            names.append(payload.get("device_name", f.stem))
    return xs, ys, names


def run_model(runner: Path, windows: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Trả về (xác suất Fall, thời gian DSP+NN micro giây) cho từng cửa sổ 100x6."""
    lines = "\n".join(" ".join(f"{v:.6f}" for v in w[:WINDOW].ravel()) for w in windows) + "\n"
    out = subprocess.run([str(runner)], input=lines, capture_output=True, text=True, check=True).stdout.split("\n")
    probs, times = [], []
    for line in out:
        if not line:
            continue
        if line.startswith("ERR"):
            raise RuntimeError(line)
        p, dsp, nn = line.split()
        probs.append(float(p))
        times.append(int(dsp) + int(nn))
    return np.asarray(probs), np.asarray(times)


def report(name: str, probs: np.ndarray, ys: np.ndarray, thr: float) -> dict:
    pred = probs >= thr
    tp = int(np.sum(pred & (ys == 1)))
    tn = int(np.sum(~pred & (ys == 0)))
    fp = int(np.sum(pred & (ys == 0)))
    fn = int(np.sum(~pred & (ys == 1)))
    n = len(ys)
    res = {
        "accuracy": (tp + tn) / n,
        "recall_fall": tp / max(tp + fn, 1),
        "specificity": tn / max(tn + fp, 1),
        "precision_fall": tp / max(tp + fp, 1),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
    }
    print(
        f"  ngưỡng {thr:.2f}: accuracy={res['accuracy']:.1%}  recall(Fall)={res['recall_fall']:.1%}  "
        f"specificity={res['specificity']:.1%}  | TP={tp} FN={fn} FP={fp} TN={tn}"
    )
    return res


def main() -> None:
    import sys

    sys.path.insert(0, str(ROOT / "tools" / "ei_host"))
    from build import build

    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="testing", choices=["training", "testing"])
    ap.add_argument("--threshold", type=float, nargs="*", default=[0.5, 0.8])
    ap.add_argument("--model", nargs="*", help="đường dẫn .zip (mặc định: mọi model trong firmware/ei_models)")
    args = ap.parse_args()

    xs, ys, names = load_split(args.split)
    ys = np.asarray(ys)
    print(f"Tập {args.split}: {len(ys)} cửa sổ (Fall={int(ys.sum())}, Normal={int((ys == 0).sum())})")
    for zip_path in [Path(m) for m in args.model] if args.model else sorted(MODELS_DIR.glob("*.zip")):
        runner = build(zip_path.resolve())
        probs, times = run_model(runner, xs)
        print(f"\n{zip_path.stem}   (DSP+NN trên PC: trung bình {times.mean() / 1000:.2f} ms)")
        for thr in args.threshold:
            report(zip_path.stem, probs, ys, thr)
        wrong = [(names[i], ys[i], probs[i]) for i in range(len(ys)) if (probs[i] >= 0.5) != ys[i]]
        for n, y, p in wrong[:8]:
            print(f"    sai: {n:40s} thực tế={'Fall' if y else 'Normal'}  P(Fall)={p:.3f}")


if __name__ == "__main__":
    main()

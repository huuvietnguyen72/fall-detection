"""Chuyển SisFall gốc -> CSV cho Edge Impulse, GIỐNG HỆT cách tạo dữ liệu của model Fall-Detection-SisFall.

  - ADXL345 -> m/s², ITG3200 -> rad/s;  200 Hz -> 50 Hz bằng scipy.signal.resample_poly(1, 4)
    (đã đối chiếu: sai số 0.0 so với dữ liệu JSON của nhóm)
  - Cửa sổ 2 s (100 mẫu), cột ax,ay,az,gx,gy,gz
  - Fall  : đỉnh |a| của bản ghi đặt tại mẫu 50 (giống firmware kích hoạt theo đỉnh)
  - Normal: cửa sổ ngẫu nhiên trong bản ghi ADL
  - --hard-negatives: thêm cửa sổ ADL căn đỉnh tại mẫu 50 cho mọi va chạm > 2 g (chạy bộ, nhảy, ngồi phịch...)
    — đúng loại dữ liệu đai gặp khi chạy thật -> nên dùng khi train lại để giảm báo nhầm
  - Chia train/test THEO NGƯỜI

    python tinyml/sisfall_to_ei.py --sisfall-dir data/sisfall_raw --out data/sisfall_ei_csv --hard-negatives

Tên file "Fall.xxx.csv" / "Normal.xxx.csv": Edge Impulse tự lấy nhãn từ phần trước dấu chấm đầu tiên.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stream_eval import G, HZ, NAME_RE, load_recording  # noqa: E402

WINDOW, HALF = 100, 50
AXES = ("ax", "ay", "az", "gx", "gy", "gz")


def peak_window(x: np.ndarray, peak: int) -> np.ndarray:
    """Cửa sổ 100 mẫu có `peak` tại mẫu 50; thiếu dữ liệu ở biên thì lặp mẫu biên."""
    idx = np.clip(np.arange(peak - HALF, peak + HALF), 0, len(x) - 1)
    return x[idx]


def impact_peaks(x: np.ndarray, trigger_g: float = 2.0, gap: int = 25) -> list[int]:
    """Các đỉnh va chạm > trigger_g, cách nhau tối thiểu `gap` mẫu (giống cách firmware bắt đỉnh)."""
    mag = np.linalg.norm(x[:, :3], axis=1) / G
    peaks, i = [], 0
    while i < len(x):
        if mag[i] > trigger_g:
            j = i + int(np.argmax(mag[i : i + gap]))
            peaks.append(j)
            i = j + gap
        else:
            i += 1
    return peaks


def write_csv(path: Path, win: np.ndarray) -> None:
    lines = ["timestamp," + ",".join(AXES)]
    lines += [f"{i * 1000 // HZ}," + ",".join(f"{v:.5f}" for v in row) for i, row in enumerate(win)]
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sisfall-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("data/sisfall_ei_csv"))
    ap.add_argument("--test-ratio", type=float, default=0.2, help="tỉ lệ NGƯỜI đưa vào tập test")
    ap.add_argument("--normal-per-file", type=int, default=1, help="số cửa sổ ngẫu nhiên mỗi bản ghi ADL")
    ap.add_argument("--hard-negatives", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    files = sorted(p for p in args.sisfall_dir.rglob("*.txt") if NAME_RE.match(p.stem))
    if not files:
        raise SystemExit(f"Không tìm thấy file SisFall (D##_SA01_R01.txt...) trong {args.sisfall_dir}")
    rnd = random.Random(args.seed)
    subjects = sorted({NAME_RE.match(p.stem).group(3) for p in files})
    test_subjects = set(rnd.sample(subjects, max(1, round(len(subjects) * args.test_ratio))))
    for split in ("training", "testing"):
        (args.out / split).mkdir(parents=True, exist_ok=True)

    counts: Counter = Counter()
    for p in files:
        kind, _, subj, _ = NAME_RE.match(p.stem).groups()
        x = load_recording(p)
        if len(x) < WINDOW:
            continue
        split = "testing" if subj in test_subjects else "training"
        out = args.out / split
        if kind == "F":
            peak = int(np.argmax(np.linalg.norm(x[:, :3], axis=1)))
            write_csv(out / f"Fall.{p.stem}.csv", peak_window(x, peak))
            counts[(split, "Fall")] += 1
            continue
        for k in range(args.normal_per_file):
            s = rnd.randrange(0, len(x) - WINDOW + 1)
            write_csv(out / f"Normal.{p.stem}_r{k}.csv", x[s : s + WINDOW])
            counts[(split, "Normal")] += 1
        if args.hard_negatives:
            for k, peak in enumerate(impact_peaks(x)):
                write_csv(out / f"Normal.{p.stem}_p{k}.csv", peak_window(x, peak))
                counts[(split, "Normal")] += 1

    print(f"Đã ghi vào {args.out}/")
    for split in ("training", "testing"):
        print(f"  {split:9s}: Fall={counts[(split, 'Fall')]:5d}  Normal={counts[(split, 'Normal')]:5d}")
    print(f"  Người trong tập test: {', '.join(sorted(test_subjects))}")


if __name__ == "__main__":
    main()

"""Mô phỏng đai lưng chạy LIÊN TỤC trên toàn bộ bản ghi SisFall gốc bằng ĐÚNG mã C++ của firmware.

Bộ phát hiện (firmware/fall_belt/detector.cpp) + model Edge Impulse được biên dịch cho PC
(tools/ei_host/stream.cpp), rồi cho "nghe" từng bản ghi SisFall như cảm biến thật ở 50 Hz.

Chỉ số:
  recall      : % bản ghi té ngã có báo động
  báo nhầm    : % bản ghi sinh hoạt thường (ADL) bị báo động, và số lần / giờ
  "người mới" : chỉ tính những người KHÔNG có trong dữ liệu train của model

    python tinyml/stream_eval.py                      # cấu hình mặc định của firmware
    python tinyml/stream_eval.py --grid               # thử nhiều ngưỡng + so với cách trượt cửa sổ
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "ei_host"))
from build import build  # noqa: E402

G = 9.80665
HZ = 50
NAME_RE = re.compile(r"^([DF])(\d{2})_(S[AE]\d{2})_R(\d{2})$")
DEFAULT_MODEL = ROOT / "firmware" / "ei_models" / "Fall-Detection-SisFall_inferencing.zip"


def load_recording(path: Path) -> np.ndarray:
    """File SisFall 200 Hz -> (N, 6) ở 50 Hz: ax,ay,az [m/s²], gx,gy,gz [rad/s] — giống hệt dữ liệu train."""
    rows = [r.strip().rstrip(";") for r in path.read_text().splitlines() if r.strip()]
    raw = np.array([[int(v) for v in r.split(",")[:6]] for r in rows], dtype=np.float64)
    acc = raw[:, 0:3] * (32 / 2**13) * G  # ADXL345 ±16g, 13 bit
    gyr = raw[:, 3:6] * (4000 / 2**16) * np.pi / 180  # ITG3200 ±2000°/s, 16 bit
    return resample_poly(np.hstack([acc, gyr]), 1, 4, axis=0).astype(np.float32)


def load_dataset(sisfall_dir: Path, cache: Path = ROOT / "build" / "sisfall_50hz.npz") -> dict[str, np.ndarray]:
    if cache.exists():
        return dict(np.load(cache))
    files = sorted(p for p in sisfall_dir.rglob("*.txt") if NAME_RE.match(p.stem))
    if not files:
        raise SystemExit(f"Không thấy bản ghi SisFall trong {sisfall_dir}")
    data = {p.stem: load_recording(p) for p in files}
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, **data)
    return data


def run_firmware_detector(
    exe: Path,
    data: dict[str, np.ndarray],
    trigger_g: float,
    ai_thr: float,
    tilt: float,
    pre_tilt: float,
    use_ai: bool = True,
) -> dict[str, list[dict]]:
    names = sorted(data)
    payload = b"".join(struct.pack("<i", len(data[n])) + data[n].astype("<f4").tobytes() for n in names)
    args = [str(exe), str(trigger_g), str(ai_thr), str(tilt), str(pre_tilt)] + ([] if use_ai else ["no-ai"])
    out = subprocess.run(args, input=payload, capture_output=True, check=True).stdout.decode().splitlines()
    result, i = {}, 0
    for n in names:
        events = []
        while out[i] != "END":
            peak, score, tilt_deg, pre_tilt_deg, peak_g, is_fall = out[i].split()
            events.append(
                {
                    "peak": int(peak),
                    "ai": float(score),
                    "tilt": float(tilt_deg),
                    "pre_tilt": float(pre_tilt_deg),
                    "peak_g": float(peak_g),
                    "fall": is_fall == "1",
                }
            )
            i += 1
        result[n] = events
        i += 1
    return result


def held_out_subjects() -> set[str]:
    """Người chỉ có trong tập testing của Edge Impulse (model chưa từng thấy khi train)."""

    def subjects(split):
        out = set()
        for f in (ROOT / "data" / "ei_sisfall" / split).rglob("*.json"):
            name = json.loads(f.read_text())["payload"]["device_name"].split("-")[-1]
            out.add(NAME_RE.match(name).group(3))
        return out

    return subjects("testing") - subjects("training")


def metrics(alarms: dict[str, int], data, subjects: set[str] | None = None) -> dict:
    keep = [n for n in alarms if not subjects or NAME_RE.match(n).group(3) in subjects]
    falls = [n for n in keep if n[0] == "F"]
    adls = [n for n in keep if n[0] == "D"]
    hours = max(sum(len(data[n]) for n in adls) / HZ / 3600, 1e-9)
    return {
        "recall": float(np.mean([alarms[n] > 0 for n in falls])),
        "fa_recordings": float(np.mean([alarms[n] > 0 for n in adls])),
        "fa_per_hour": sum(alarms[n] for n in adls) / hours,
        "n_falls": len(falls),
        "n_adl": len(adls),
    }


def print_row(label: str, m_all: dict, m_new: dict) -> None:
    print(
        f"{label:44s} | recall {m_all['recall']:6.1%}  báo nhầm {m_all['fa_recordings']:5.1%} "
        f"({m_all['fa_per_hour']:4.1f}/h) | người mới: recall {m_new['recall']:6.1%}  "
        f"báo nhầm {m_new['fa_recordings']:5.1%} ({m_new['fa_per_hour']:4.1f}/h)"
    )


def sliding_baseline(runner: Path, data, thr=0.8, consecutive=2, stride=25) -> dict[str, int]:
    """Cách của sketch bàn giao: model mỗi 0.5 s, báo khi `consecutive` cửa sổ liên tiếp >= thr."""
    names = sorted(data)
    starts = {n: range(0, len(data[n]) - 100 + 1, stride) for n in names}
    windows = np.stack([data[n][s : s + 100].ravel() for n in names for s in starts[n]]).astype(np.float32)
    probs = np.frombuffer(
        subprocess.run([str(runner), "--binary"], input=windows.tobytes(), capture_output=True, check=True).stdout,
        dtype=np.float32,
    )
    alarms, k = {}, 0
    for n in names:
        count, run, last = 0, 0, -(10**9)
        for s in starts[n]:
            run = run + 1 if probs[k] >= thr else 0
            k += 1
            if run >= consecutive and s - last >= 10 * HZ:
                count, last, run = count + 1, s, 0
        alarms[n] = count
    return alarms


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sisfall-dir", type=Path, default=ROOT / "data" / "sisfall_raw")
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--trigger", type=float, default=2.0)
    ap.add_argument("--ai", type=float, default=0.5)
    ap.add_argument("--tilt", type=float, default=30.0)
    ap.add_argument("--pre-tilt", type=float, default=65.0)
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--json", type=Path, help="ghi kết quả cấu hình mặc định ra file JSON")
    args = ap.parse_args()

    exe = build(args.model, "stream")
    data = load_dataset(args.sisfall_dir)
    new = held_out_subjects()
    print(
        f"{len(data)} bản ghi SisFall ({sum(len(v) for v in data.values()) / HZ / 3600:.1f} giờ). "
        f"Người mới (không có trong train): {', '.join(sorted(new)) or '(thiếu data/ei_sisfall -> tính trên tất cả)'}\n"
    )

    def evaluate(trigger, ai, tilt, pre_tilt, use_ai=True):
        ev = run_firmware_detector(exe, data, trigger, ai, tilt, pre_tilt, use_ai)
        alarms = {n: sum(e["fall"] for e in es) for n, es in ev.items()}
        return ev, alarms, metrics(alarms, data), metrics(alarms, data, new)

    ev, alarms, m_all, m_new = evaluate(args.trigger, args.ai, args.tilt, args.pre_tilt)
    print_row(f"FIRMWARE: ≥{args.trigger}g AI≥{args.ai} nghiêng≥{args.tilt}° trước≤{args.pre_tilt}°", m_all, m_new)

    if args.grid:
        a = sliding_baseline(build(args.model, "runner"), data)
        print_row("sketch bàn giao: trượt 0.5s, 0.8 x2", metrics(a, data), metrics(a, data, new))
        for trig, ai, tilt, pre, use_ai in [
            (2.0, 0.5, 0, 180, True),
            (2.0, 0.5, 30, 180, True),
            (2.0, 0.0, 30, 65, False),
            (2.0, 0.0, 45, 65, False),
            (1.8, 0.5, 30, 65, True),
            (2.0, 0.3, 30, 65, True),
            (2.0, 0.8, 30, 65, True),
            (2.0, 0.5, 45, 65, True),
            (2.5, 0.5, 30, 65, True),
        ]:
            _, al, ma, mn = evaluate(trig, ai, tilt, pre, use_ai)
            ai_txt = f"AI≥{ai}" if use_ai else "không AI"
            print_row(f"≥{trig}g {ai_txt} nghiêng≥{tilt}° trước≤{pre}°", ma, mn)

    missed = Counter(n[:3] for n in alarms if n[0] == "F" and alarms[n] == 0)
    false = Counter(n[:3] for n in alarms if n[0] == "D" and alarms[n] > 0)
    print(f"\nNgã bị bỏ sót theo loại: {dict(missed.most_common())}")
    print(f"Báo nhầm theo hoạt động: {dict(false.most_common())}")
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "all": m_all,
                    "new_subjects": m_new,
                    "config": {"trigger_g": args.trigger, "ai": args.ai, "tilt": args.tilt},
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()

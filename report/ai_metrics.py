"""Ma trận nhầm lẫn + Accuracy / Precision / Recall / Specificity / F1 cho phần AI trên đai lưng.

Tất cả đều chạy ĐÚNG mã C++ của firmware và model Edge Impulse (int8) biên dịch cho PC, nên kết quả
là của chính thuật toán chạy trên ESP32, không phải một bản Python viết lại.

Ba mức đánh giá (mục nào thiếu dữ liệu thì tự bỏ qua):
  1. Model AI trên dữ liệu đai thật  : data/belt/ei/*.csv  (cửa sổ 2 s căn đỉnh va chạm, model CHƯA từng thấy)
  2. Hệ thống trên đai thật           : data/belt/raw/*.csv (mỗi lần thử = 1 mẫu; kích hoạt + AI + tư thế)
  3. Hệ thống trên SisFall (công khai) : data/sisfall_raw    (4500 bản ghi, 38 người; mỗi bản ghi = 1 mẫu)

    python report/ai_metrics.py
    python report/ai_metrics.py --trigger 1.8 --ai 0.5 --tilt 30 --pre-tilt 65   # = config.h

Kết quả: docs/figures/cm_*.png|svg, docs/results/ai_metrics.json, docs/results/ai_metrics.md
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np

from shared import RES_DIR, ROOT, binary_metrics, metrics_table, plot_confusion, write_json

from evaluate_ei import run_model  # noqa: E402  (tinyml/)
from stream_eval import DEFAULT_MODEL, HZ, build, load_dataset, run_firmware_detector  # noqa: E402

BELT = ROOT / "data" / "belt"
SISFALL = ROOT / "data" / "sisfall_raw"
LABELS = ["Bình thường", "Ngã"]

# Mã hoạt động SisFall -> mô tả (theo data/sisfall_raw/Readme.txt), để báo cáo ca sai theo loại
SISFALL_ACT = {
    **{
        f"D{i:02d}": d
        for i, d in enumerate(
            [
                "Đi chậm",
                "Đi nhanh",
                "Chạy chậm",
                "Chạy nhanh",
                "Lên xuống cầu thang chậm",
                "Lên xuống cầu thang nhanh",
                "Ngồi ghế nửa cao chậm, đứng dậy",
                "Ngồi ghế nửa cao nhanh, đứng dậy",
                "Ngồi ghế thấp chậm, đứng dậy",
                "Ngồi ghế thấp nhanh, đứng dậy",
                "Ngồi, cố đứng dậy rồi ngã ngồi lại ghế",
                "Ngồi rồi nằm xuống chậm",
                "Ngồi rồi nằm xuống nhanh",
                "Nằm ngửa trở mình sang nghiêng",
                "Khuỵu gối cúi xuống rồi đứng lên",
                "Cúi gập người (không khuỵu gối) rồi đứng lên",
                "Lên ô tô, ngồi, xuống xe",
                "Vấp khi đi (không ngã)",
                "Nhảy nhẹ với lấy đồ trên cao",
            ],
            start=1,
        )
    },
    **{
        f"F{i:02d}": d
        for i, d in enumerate(
            [
                "Ngã trước khi đi (trượt)",
                "Ngã ngửa khi đi (trượt)",
                "Ngã nghiêng khi đi (trượt)",
                "Ngã trước khi đi (vấp)",
                "Ngã trước khi chạy (vấp)",
                "Khuỵu thẳng xuống khi đi (ngất)",
                "Ngã khi đi, tay chống bàn (ngất)",
                "Ngã trước khi cố đứng dậy",
                "Ngã nghiêng khi cố đứng dậy",
                "Ngã trước khi ngồi xuống",
                "Ngã ngửa khi ngồi xuống",
                "Ngã nghiêng khi ngồi xuống",
                "Ngã trước khi đang ngồi (ngất/ngủ gật)",
                "Ngã ngửa khi đang ngồi (ngất/ngủ gật)",
                "Ngã nghiêng khi đang ngồi (ngất/ngủ gật)",
            ],
            start=1,
        )
    },
}


def load_csv(path: Path, skip_timestamp: bool) -> np.ndarray:
    x = np.loadtxt(path, delimiter=",", skiprows=1, dtype=np.float32, ndmin=2)
    return x[:, 1:7] if skip_timestamp else x[:, :6]


def model_level(model: Path, thr: float) -> tuple[dict, dict] | None:
    files = sorted((BELT / "ei").glob("*.csv"))
    if not files:
        print("- Bỏ qua mức 1: chưa có data/belt/ei/")
        return None
    windows = [load_csv(f, skip_timestamp=True) for f in files]
    y = np.array([f.name.startswith("Fall.") for f in files])
    probs, us = run_model(build(model, "runner"), windows)
    m = binary_metrics(y, probs >= thr)
    print(f"1. Model AI, đai thật: {len(files)} cửa sổ ({y.sum()} Ngã / {(~y).sum()} Bình thường)")
    plot_confusion(
        np.array([[m["tn"], m["fp"]], [m["fn"], m["tp"]]]),
        LABELS,
        "Model TinyML trên dữ liệu đai thật",
        "cm_model_belt",
        f"{len(files)} cửa sổ 2 s, ngưỡng P(Ngã) ≥ {thr}",
    )
    timing = {"pc_infer_us_mean": float(us.mean()), "pc_infer_us_p95": float(np.percentile(us, 95))}
    wrong = [f.stem for f, yi, p in zip(files, y, probs, strict=True) if (p >= thr) != yi]
    return m, {
        "threshold": thr,
        "wrong": wrong,
        **timing,
        "probs": {f.stem: float(p) for f, p in zip(files, probs, strict=True)},
    }


def system_level_belt(exe: Path, a) -> tuple[dict, dict] | None:
    files = sorted((BELT / "raw").glob("*.csv"))
    if not files:
        print("- Bỏ qua mức 2: chưa có data/belt/raw/")
        return None
    data = {f.stem: load_csv(f, skip_timestamp=False) for f in files}
    ev = run_firmware_detector(exe, data, a.trigger, a.ai, a.tilt, a.pre_tilt)
    names = sorted(data)
    y = np.array([n.startswith("Fall.") for n in names])
    pred = np.array([any(e["fall"] for e in ev[n]) for n in names])
    m = binary_metrics(y, pred)
    print(f"2. Hệ thống, đai thật: {len(names)} lần thử ({y.sum()} Ngã / {(~y).sum()} Bình thường)")
    plot_confusion(
        np.array([[m["tn"], m["fp"]], [m["fn"], m["tp"]]]),
        LABELS,
        "Bộ phát hiện trên đai (dữ liệu thật)",
        "cm_system_belt",
        f"{len(names)} lần thử · ≥{a.trigger} g, AI ≥ {a.ai}, nghiêng ≥ {a.tilt:.0f}°",
    )
    detail = {
        n: {
            "label": "Fall" if yi else "Normal",
            "pred_fall": bool(pi),
            "events": ev[n],
        }
        for n, yi, pi in zip(names, y, pred, strict=True)
    }
    return m, {"trials": detail}


def system_level_sisfall(exe: Path, a) -> tuple[dict, dict] | None:
    if not SISFALL.exists():
        print(
            "- Bỏ qua mức 3: chưa có data/sisfall_raw "
            "(git clone --depth 1 https://github.com/Fall-Prevention-Team/sisfallData data/sisfall_raw)"
        )
        return None
    data = load_dataset(SISFALL)
    ev = run_firmware_detector(exe, data, a.trigger, a.ai, a.tilt, a.pre_tilt)
    names = sorted(data)
    y = np.array([n[0] == "F" for n in names])
    pred = np.array([any(e["fall"] for e in ev[n]) for n in names])
    m = binary_metrics(y, pred)
    adl_hours = sum(len(data[n]) for n, yi in zip(names, y, strict=True) if not yi) / HZ / 3600
    alarms_adl = sum(sum(e["fall"] for e in ev[n]) for n, yi in zip(names, y, strict=True) if not yi)
    hours = sum(len(v) for v in data.values()) / HZ / 3600
    print(f"3. Hệ thống, SisFall: {len(names)} bản ghi ({y.sum()} Ngã / {(~y).sum()} ADL, {hours:.1f} giờ)")
    plot_confusion(
        np.array([[m["tn"], m["fp"]], [m["fn"], m["tp"]]]),
        LABELS,
        "Bộ phát hiện trên SisFall",
        "cm_system_sisfall",
        f"{len(names)} bản ghi, 38 người · ≥{a.trigger} g, AI ≥ {a.ai}",
    )
    missed = Counter(n[:3] for n, yi, pi in zip(names, y, pred, strict=True) if yi and not pi)
    false = Counter(n[:3] for n, yi, pi in zip(names, y, pred, strict=True) if not yi and pi)
    return m, {
        "hours": hours,
        "false_alarms_per_hour_adl": alarms_adl / adl_hours,
        "missed_by_type": {f"{k} {SISFALL_ACT.get(k, '')}": v for k, v in missed.most_common()},
        "false_by_activity": {f"{k} {SISFALL_ACT.get(k, '')}": v for k, v in false.most_common()},
        "note": "Model được train trên một phần SisFall -> số liệu này lạc quan hơn dữ liệu chưa thấy.",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--trigger", type=float, default=1.8)
    ap.add_argument("--ai", type=float, default=0.5)
    ap.add_argument("--tilt", type=float, default=30.0)
    ap.add_argument("--pre-tilt", type=float, default=65.0)
    a = ap.parse_args()

    exe = build(a.model, "stream")
    results, rows = {"config": vars(a) | {"model": a.model.name}}, []
    for key, title, fn in [
        ("model_belt", "Model TinyML · đai thật (cửa sổ 2 s)", lambda: model_level(a.model, a.ai)),
        ("system_belt", "Hệ thống trên đai · đai thật (lần thử)", lambda: system_level_belt(exe, a)),
        ("system_sisfall", "Hệ thống trên đai · SisFall (bản ghi)", lambda: system_level_sisfall(exe, a)),
    ]:
        r = fn()
        if r:
            m, extra = r
            results[key] = {"metrics": m, **extra}
            rows.append((title, m))
            print(
                f"   Accuracy {m['accuracy']:.1%} · Precision {m['precision']:.1%} · Recall {m['recall']:.1%} · "
                f"Specificity {m['specificity']:.1%} · F1 {m['f1']:.1%}"
            )

    write_json("ai_metrics", results)
    md = RES_DIR / "ai_metrics.md"
    md.write_text(
        "# Chỉ số đánh giá AI (tự sinh bởi `report/ai_metrics.py`)\n\n"
        f"Cấu hình: kích hoạt ≥ {a.trigger} g · P(Ngã) ≥ {a.ai} · nghiêng thêm ≥ {a.tilt:.0f}° · "
        f"trước va chạm ≤ {a.pre_tilt:.0f}° · model `{a.model.name}`\n\n"
        "Lớp dương = **Ngã**. Recall = tỉ lệ ca ngã được phát hiện; "
        "Specificity = tỉ lệ sinh hoạt không bị báo nhầm.\n\n"
        + metrics_table(rows),
        encoding="utf-8",
    )
    print(f"  bảng: {md.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

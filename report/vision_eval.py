"""Đánh giá độ chính xác của thị giác máy tính (nhận diện NẰM / KHÔNG NẰM) trong nhiều điều kiện.

Dữ liệu: UR Fall Detection Dataset (URFD, Kwolek & Kepski 2014) — 30 video ngã + 40 video sinh hoạt,
mỗi khung hình có nhãn: -1 = không nằm, 1 = nằm trên sàn, 0 = đang ngã (bỏ qua, giống bài báo gốc).
Video cam0 gồm 2 nửa (ảnh độ sâu | ảnh RGB 320x240): chỉ dùng nửa RGB, đúng như camera thường.

Pipeline đánh giá = ĐÚNG pipeline đang chạy: MediaPipe Pose -> vision/posture.classify -> PostureSmoother.
Điều kiện được mô phỏng bằng biến đổi ảnh có kiểm soát (cùng video, chỉ khác điều kiện):
  goc        ảnh gốc
  thieu_sang giảm độ sáng còn 25% + nhiễu cảm biến (phòng tối, đèn ngủ)
  nhieu      nhiễu Gauss sigma=20 (camera rẻ, ISO cao)
  mo         nhòe chuyển động 15 px (người ngã nhanh, camera tốc độ màn trập thấp)
  xa         giảm độ phân giải còn 40% (người ở xa camera / camera độ phân giải thấp)
  che_khuat  che nửa dưới khung hình (bàn ghế, giường che chân người)

    python report/vision_eval.py                 # tải URFD (~100 MB, lần đầu) rồi đánh giá
    python report/vision_eval.py --stride 1      # dùng mọi khung hình (chậm gấp đôi)

Kết quả: docs/figures/cm_vision.png, vision_conditions.png, vision_examples.png, vision_conditions_examples.png
         docs/results/vision_metrics.json, docs/results/vision_metrics.md
"""

from __future__ import annotations

import argparse
import csv
import json
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from shared import (
    AQUA,
    BLUE,
    GRID,
    INK,
    INK2,
    ORANGE,
    RES_DIR,
    ROOT,
    binary_metrics,
    fmt_pct,
    plot_confusion,
    save,
    setup_matplotlib,
    write_json,
)

URFD = ROOT / "data" / "urfd"
BASE_URL = "https://fenix.ur.edu.pl/~mkepski/ds/data/"
CONDITIONS = {
    "goc": "Gốc",
    "thieu_sang": "Thiếu sáng",
    "nhieu": "Nhiễu ảnh",
    "mo": "Nhòe chuyển động",
    "xa": "Xa / độ phân giải thấp",
    "che_khuat": "Che khuất nửa dưới",
}
FPS = 30


# ----------------------------------------------------------------------------- dữ liệu
def fetch(url: str, path: Path) -> None:
    from vision.backends import download  # HTTPS bằng chứng chỉ certifi (chạy được cả trên macOS)

    download(url, path)


def download() -> dict[str, dict[int, int]]:
    """Tải video + nhãn URFD (bỏ qua file đã có). Trả về {chuỗi: {số khung: nhãn}}."""
    URFD.mkdir(parents=True, exist_ok=True)
    labels: dict[str, dict[int, int]] = {}
    for f in ("urfall-cam0-falls.csv", "urfall-cam0-adls.csv"):
        path = URFD / f
        if not path.exists():
            fetch(BASE_URL + f, path)
        for row in csv.reader(path.open()):
            labels.setdefault(row[0], {})[int(row[1])] = int(row[2])
    missing = [s for s in labels if not (URFD / f"{s}-cam0.mp4").exists()]
    for i, s in enumerate(missing, 1):
        print(f"\r  tải video URFD {i}/{len(missing)}: {s}   ", end="", flush=True)
        fetch(f"{BASE_URL}{s}-cam0.mp4", URFD / f"{s}-cam0.mp4")
    if missing:
        print()
    return labels


def read_rgb_frames(seq: str) -> list[np.ndarray]:
    import cv2

    cap = cv2.VideoCapture(str(URFD / f"{seq}-cam0.mp4"))
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(np.ascontiguousarray(f[:, f.shape[1] // 2 :]))  # nửa phải = RGB
    return frames


# ----------------------------------------------------------------------------- điều kiện
def apply_condition(img: np.ndarray, cond: str, rng: np.random.Generator) -> np.ndarray:
    import cv2

    if cond == "goc":
        return img
    x = img.astype(np.float32)
    if cond == "thieu_sang":
        x = x * 0.25 + rng.normal(0, 4, x.shape)
    elif cond == "nhieu":
        x = x + rng.normal(0, 20, x.shape)
    elif cond == "mo":
        k = np.zeros((15, 15), np.float32)
        k[7, :] = 1 / 15
        return cv2.filter2D(img, -1, k)
    elif cond == "xa":
        h, w = img.shape[:2]
        small = cv2.resize(img, (int(w * 0.4), int(h * 0.4)), interpolation=cv2.INTER_AREA)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    elif cond == "che_khuat":
        out = img.copy()
        out[img.shape[0] // 2 :, :] = (90, 90, 90)
        return out
    return np.clip(x, 0, 255).astype(np.uint8)


# ----------------------------------------------------------------------------- chạy pipeline
class LegacySmoother:
    """Bộ làm mượt CŨ (trước 11/2026) — giữ lại chỉ để so sánh trong báo cáo.

    Đổi tư thế khi tư thế mới xuất hiện LIÊN TỤC đủ lâu; một khung khác (kể cả mất dấu) là đếm lại.
    """

    def __init__(self, hold_s=0.6, lying_hold_s=1.0, no_person_hold_s=1.5):
        from common.protocol import LYING, NO_PERSON

        self.hold = {LYING: lying_hold_s, NO_PERSON: no_person_hold_s}
        self.default_hold, self.current, self._cand, self._since = hold_s, None, None, 0.0

    def update(self, t, posture, conf):
        if self.current is None or posture == self.current:
            self.current, self._cand = posture, None
            return self.current, conf
        if posture != self._cand:
            self._cand, self._since = posture, t
        if t - self._since >= self.hold.get(posture, self.default_hold):
            self.current, self._cand = posture, None
        return self.current, conf


def run_condition(args: tuple[str, list[str], int]) -> dict:
    """Chạy pipeline thị giác trên mọi chuỗi cho 1 điều kiện (1 tiến trình)."""
    from vision.backends import MediaPipeBackend
    from vision.posture import PostureParams, PostureSmoother, classify

    cond, seqs, stride = args
    params = PostureParams()
    out = {}
    for seq in seqs:
        rng = np.random.default_rng(zlib.crc32(f"{seq}/{cond}".encode()))  # tái lập được
        backend = MediaPipeBackend("full")  # mỗi chuỗi một bộ theo dõi mới
        smoother, legacy = PostureSmoother(), LegacySmoother()
        rows = []
        for i, frame in enumerate(read_rgb_frames(seq)):
            if i % stride:
                continue
            img = apply_condition(frame, cond, rng)
            t0 = time.perf_counter()
            kps = backend.detect(img)
            raw, conf, _ = classify(kps, params)
            ms = (time.perf_counter() - t0) * 1000
            smooth, _ = smoother.update(i / FPS, raw, conf)
            old, _ = legacy.update(i / FPS, raw, conf)
            rows.append((i + 1, raw, smooth, ms, old))  # số khung trong nhãn URFD đếm từ 1
        backend.landmarker.close()
        out[seq] = rows
    return {"cond": cond, "seqs": out}


def evaluate(labels, results) -> dict:
    from common.protocol import LYING, NO_PERSON

    summary = {}
    for cond, seqs in results.items():
        y, pred_raw, pred_smooth, pred_old, detected, ms = [], [], [], [], [], []
        seq_hits = {"fall_confirmed": 0, "fall_total": 0, "adl_false": 0, "adl_total": 0}
        for seq, rows in seqs.items():
            lab = labels[seq]
            lying_frames, lying_pred = 0, 0
            for n, raw, smooth, t, old in rows:
                ms.append(t)
                detected.append(raw != NO_PERSON)
                if lab.get(n, 0) == 0:
                    continue
                y.append(lab[n] == 1)
                pred_raw.append(raw == LYING)
                pred_smooth.append(smooth == LYING)
                pred_old.append(old == LYING)
                if lab[n] == 1:
                    lying_frames += 1
                    lying_pred += smooth == LYING
            any_lying = any(r[2] == LYING for r in rows)
            if seq.startswith("fall"):
                # chuỗi ngã được xác nhận nếu camera báo NẰM ở ≥ 50% khung người nằm trên sàn
                seq_hits["fall_total"] += 1
                seq_hits["fall_confirmed"] += lying_frames > 0 and lying_pred / lying_frames >= 0.5
            elif not any(lab.get(n, -1) == 1 for n, *_ in rows):
                # sinh hoạt không có lúc nằm thật: báo NẰM bất kỳ lúc nào = báo nhầm
                seq_hits["adl_total"] += 1
                seq_hits["adl_false"] += any_lying
        ms = np.asarray(ms)
        summary[cond] = {
            "frame_raw": binary_metrics(y, pred_raw),
            "frame_smoothed": binary_metrics(y, pred_smooth),
            "frame_smoothed_legacy": binary_metrics(y, pred_old),
            "person_detected_rate": float(np.mean(detected)),
            "ms_per_frame_mean": float(ms.mean()),
            "ms_per_frame_p95": float(np.percentile(ms, 95)),
            "sequence": seq_hits,
        }
    return summary


# ----------------------------------------------------------------------------- hình
def plot_conditions(summary: dict):
    plt = setup_matplotlib()
    conds = list(CONDITIONS)
    metrics = [("accuracy", "Accuracy", BLUE), ("precision", "Precision", ORANGE), ("recall", "Recall", AQUA)]
    x = np.arange(len(conds))
    w = 0.26
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for k, (key, name, color) in enumerate(metrics):
        vals = [summary[c]["frame_smoothed"][key] * 100 for c in conds]
        bars = ax.bar(x + (k - 1) * w, vals, w - 0.03, color=color, label=name, zorder=2)
        for b, v in zip(bars, vals, strict=True):
            ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.0f}", ha="center", va="bottom", fontsize=8, color=INK2)
    ax.set_xticks(
        x, [CONDITIONS[c].replace(" / ", " /\n").replace(" nửa", "\nnửa").replace(" chuyển", "\nchuyển") for c in conds]
    )
    ax.set_ylim(0, 108)
    ax.set_ylabel("%")
    ax.yaxis.grid(True, color=GRID, lw=0.8, zorder=0)
    ax.set_title("Nhận diện tư thế NẰM theo điều kiện (URFD, từng khung hình)", loc="left", pad=30)
    ax.legend(frameon=False, ncol=3, loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=10)
    fig.tight_layout()
    save(fig, "vision_conditions")
    plt.close(fig)


def example_frames(labels, seq: str, picks: list[int], conds: list[str], name: str, title: str):
    """Lưới ảnh minh họa: mỗi ô = 1 khung hình đã chạy pipeline, có khung xương + tư thế dự đoán."""
    import cv2

    from vision.backends import SKELETON, MediaPipeBackend
    from vision.main import COLORS
    from vision.posture import PostureParams, PostureSmoother, classify

    plt = setup_matplotlib()
    frames = read_rgb_frames(seq)
    truth_txt = {-1: "Không nằm", 0: "Đang ngã", 1: "Nằm"}
    cells = []
    for cond in conds:
        rng = np.random.default_rng(0)
        backend, smoother, params = MediaPipeBackend("full"), PostureSmoother(), PostureParams()
        wanted = set(picks)
        for i in range(max(picks)):  # chạy tuần tự để bộ theo dõi + bộ làm mượt giống lúc chạy thật
            img = apply_condition(frames[i], cond, rng)
            kps = backend.detect(img)
            raw, conf, _ = classify(kps, params)
            post, conf = smoother.update(i / FPS, raw, conf)
            if i + 1 not in wanted:
                continue
            big = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
            if kps:
                pts = {k: (int(v[0] * 2), int(v[1] * 2)) for k, v in kps.items() if v[2] >= params.min_score}
                for a, b in SKELETON:
                    if a in pts and b in pts:
                        cv2.line(big, pts[a], pts[b], (255, 255, 255), 3)
                for p in pts.values():
                    cv2.circle(big, p, 5, (0, 220, 255), -1)
            color = COLORS.get(post, (200, 200, 200))
            cv2.rectangle(big, (0, 0), (big.shape[1], 40), (0, 0, 0), -1)
            cv2.putText(
                big, f"{post} {conf * 100:.0f}%", (10, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA
            )
            cells.append((big[:, :, ::-1], cond, i + 1, truth_txt[labels[seq].get(i + 1, 0)]))
        backend.landmarker.close()

    cols = len(picks) if len(conds) == 1 else 3
    rows = int(np.ceil(len(cells) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(3.2 * cols, 2.75 * rows + 0.7), squeeze=False, layout="constrained")
    for ax, (img, cond, n, truth) in zip(np.ravel(axes), cells, strict=True):
        ax.imshow(img)
        cap = f"khung {n} · thực tế: {truth}" if len(conds) == 1 else f"{CONDITIONS[cond]}"
        ax.set_title(cap, fontsize=9, fontweight="normal", color=INK)
        ax.axis("off")
    for ax in np.ravel(axes)[len(cells) :]:
        ax.axis("off")
    fig.suptitle(
        title + "\n(nhãn trên ảnh = tư thế hệ thống xuất ra sau làm mượt; khung xương vẽ khi phát hiện được người)",
        fontsize=11,
        fontweight="bold",
        color=INK,
        x=0.01,
        ha="left",
    )
    save(fig, name, exts=("png",))
    plt.close(fig)


# ----------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stride", type=int, default=2, help="lấy 1 khung trong N (2 = 15 FPS, gần tốc độ chạy thật)")
    ap.add_argument("--workers", type=int, default=len(CONDITIONS))
    ap.add_argument("--skip-examples", action="store_true")
    ap.add_argument("--plots-only", action="store_true", help="chỉ vẽ lại hình từ docs/results/vision_metrics.json")
    a = ap.parse_args()

    if a.plots_only:
        labels = download()
        plot_conditions(json.loads((RES_DIR / "vision_metrics.json").read_text())["summary"])
        examples(labels)
        return

    labels = download()
    seqs = sorted(labels)
    print(
        f"URFD: {sum(s.startswith('fall') for s in seqs)} chuỗi ngã + {sum(s.startswith('adl') for s in seqs)} "
        f"chuỗi sinh hoạt; {len(CONDITIONS)} điều kiện, 1/{a.stride} khung hình"
    )
    t0 = time.time()
    with ProcessPoolExecutor(a.workers) as pool:
        results = {}
        for r in pool.map(run_condition, [(c, seqs, a.stride) for c in CONDITIONS]):
            results[r["cond"]] = r["seqs"]
            print(f"  xong điều kiện: {CONDITIONS[r['cond']]} ({time.time() - t0:.0f} s)")

    summary = evaluate(labels, results)
    g = summary["goc"]["frame_smoothed"]
    plot_confusion(
        np.array([[g["tn"], g["fp"]], [g["fn"], g["tp"]]]),
        ["Không nằm", "Nằm"],
        "Camera: nhận diện tư thế NẰM",
        "cm_vision",
        f"URFD, {g['n']} khung hình, ảnh gốc",
    )
    plot_conditions(summary)

    rows = (
        "| Điều kiện | Accuracy | Precision | Recall | F1 | Phát hiện người | Chuỗi ngã được xác nhận "
        "| ADL báo nhầm NẰM | ms/khung (TB · p95) |\n"
    )
    rows += "|---|---|---|---|---|---|---|---|---|\n"
    for c, name in CONDITIONS.items():
        s, m, q = summary[c], summary[c]["frame_smoothed"], summary[c]["sequence"]
        rows += (
            f"| {name} | {fmt_pct(m['accuracy'])} | {fmt_pct(m['precision'])} | {fmt_pct(m['recall'])} | "
            f"{fmt_pct(m['f1'])} | {fmt_pct(s['person_detected_rate'])} | "
            f"{q['fall_confirmed']}/{q['fall_total']} | {q['adl_false']}/{q['adl_total']} | "
            f"{s['ms_per_frame_mean']:.1f} · {s['ms_per_frame_p95']:.1f} |\n"
        )
    raw, old = summary["goc"]["frame_raw"], summary["goc"]["frame_smoothed_legacy"]
    md = RES_DIR / "vision_metrics.md"
    md.write_text(
        "# Đánh giá thị giác máy tính (tự sinh bởi `report/vision_eval.py`)\n\n"
        "Dữ liệu URFD, nửa RGB 320×240 của camera cam0; lớp dương = **NẰM**; khung nhãn 0 (đang ngã) bị bỏ qua.\n"
        "Chỉ số theo từng khung hình, sau bộ làm mượt (đúng đầu ra hệ thống gửi cho fusion).\n"
        f"Không làm mượt (ảnh gốc): Accuracy {fmt_pct(raw['accuracy'])}, Precision {fmt_pct(raw['precision'])}, "
        f"Recall {fmt_pct(raw['recall'])}.\n"
        f"Bộ làm mượt CŨ (đếm lại khi mất dấu 1 khung, ảnh gốc): Accuracy {fmt_pct(old['accuracy'])}, "
        f"Precision {fmt_pct(old['precision'])}, Recall {fmt_pct(old['recall'])}.\n\n"
        + rows
        + "\n*Chuỗi ngã được xác nhận*: camera báo NẰM ở ≥ 50% số khung người thật sự nằm trên sàn.\n"
        "*ADL báo nhầm NẰM*: trong các video sinh hoạt không có lúc nằm, camera báo NẰM ít nhất một lần.\n"
        "Thời gian/khung đo trên máy chạy script (MediaPipe Pose Full, CPU).\n",
        encoding="utf-8",
    )
    write_json("vision_metrics", {"stride": a.stride, "conditions": CONDITIONS, "summary": summary})
    print(f"  bảng: {md.relative_to(ROOT)}")
    for c, name in CONDITIONS.items():
        m = summary[c]["frame_smoothed"]
        print(f"  {name:24} Acc {m['accuracy']:.1%}  Prec {m['precision']:.1%}  Rec {m['recall']:.1%}")

    if not a.skip_examples:
        examples(labels)


def examples(labels) -> None:
    example_frames(
        labels,
        "fall-01",
        [40, 95, 120, 150],
        ["goc"],
        "vision_examples",
        "Quá trình nhận diện tư thế trong một cú ngã (URFD fall-01)",
    )
    example_frames(
        labels,
        "fall-01",
        [150],
        list(CONDITIONS),
        "vision_conditions_examples",
        "Cùng một khung hình (người nằm trên sàn) trong 6 điều kiện",
    )


if __name__ == "__main__":
    main()

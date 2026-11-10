"""Phần dùng chung cho các script báo cáo: đường dẫn, chỉ số đánh giá, kiểu hình (matplotlib).

Hình xuất cả PNG (300 dpi, dán vào Word/poster) lẫn SVG (vector, phóng to không vỡ).
Bảng màu: bộ màu phân loại đã kiểm tra an toàn cho người mù màu (xem docs/BAO_CAO_KY_THUAT.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FIG_DIR = ROOT / "docs" / "figures"
RES_DIR = ROOT / "docs" / "results"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tinyml"))

# Màu (nền sáng): xanh dương, cam, xanh ngọc, vàng; chữ dùng mực trung tính, không dùng màu series
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
# Thang tuần tự một màu (xanh dương, sáng -> đậm) cho ma trận nhầm lẫn
BLUE_RAMP = ["#f0efec", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def binary_metrics(y_true, y_pred) -> dict:
    """Chỉ số cho bài toán 2 lớp, lớp dương = Ngã (1)."""
    y_true, y_pred = np.asarray(y_true, bool), np.asarray(y_pred, bool)
    tp = int(np.sum(y_true & y_pred))
    tn = int(np.sum(~y_true & ~y_pred))
    fp = int(np.sum(~y_true & y_pred))
    fn = int(np.sum(y_true & ~y_pred))
    n = tp + tn + fp + fn

    def div(a, b):
        return a / b if b else float("nan")

    precision, recall = div(tp, tp + fp), div(tp, tp + fn)
    return {
        "n": n,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "accuracy": div(tp + tn, n),
        "precision": precision,
        "recall": recall,
        "specificity": div(tn, tn + fp),
        "f1": div(2 * precision * recall, precision + recall),
    }


def setup_matplotlib():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": ["Arial", "Helvetica", "DejaVu Sans"],
            "font.size": 11,
            "axes.edgecolor": AXIS,
            "axes.labelcolor": INK2,
            "axes.titlecolor": INK,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "xtick.color": INK2,
            "ytick.color": INK2,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "svg.fonttype": "none",  # giữ chữ dạng text trong SVG để sửa được
        }
    )
    return plt


def save(fig, name: str, exts: tuple[str, ...] = ("png", "svg")) -> list[Path]:
    """Lưu hình. Ảnh chụp chỉ cần PNG (SVG sẽ nhúng lại ảnh, nặng gấp đôi mà không nét hơn)."""
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for ext in exts:
        p = FIG_DIR / f"{name}.{ext}"
        fig.savefig(p, dpi=300, bbox_inches="tight")
        out.append(p)
    extra = "".join(f" (+ .{e})" for e in exts[1:])
    print(f"  hình: {out[0].relative_to(ROOT)}{extra}")
    return out


def plot_confusion(cm: np.ndarray, labels: list[str], title: str, name: str, subtitle: str = ""):
    """Ma trận nhầm lẫn 2x2: hàng = thực tế, cột = dự đoán; mỗi ô ghi số lượng và % theo hàng."""
    plt = setup_matplotlib()
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("blue", BLUE_RAMP)
    row_pct = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=(4.4, 4.0))
    ax.imshow(row_pct, cmap=cmap, vmin=0, vmax=1)
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            dark = row_pct[i, j] > 0.55
            ax.text(
                j,
                i,
                f"{cm[i, j]}\n({row_pct[i, j]:.1%})",
                ha="center",
                va="center",
                fontsize=13,
                fontweight="bold",
                color="white" if dark else INK,
            )
    ax.set_xticks(range(len(labels)), labels)
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("Dự đoán")
    ax.set_ylabel("Thực tế")
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(title + (f"\n{subtitle}" if subtitle else ""), fontsize=11)
    fig.tight_layout()
    save(fig, name)
    plt.close(fig)


def write_json(name: str, data) -> Path:
    RES_DIR.mkdir(parents=True, exist_ok=True)
    p = RES_DIR / f"{name}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print(f"  số liệu: {p.relative_to(ROOT)}")
    return p


def fmt_pct(x: float) -> str:
    return "—" if x != x else f"{x * 100:.1f}%"


def metrics_table(rows: list[tuple[str, dict]]) -> str:
    """Bảng Markdown: Accuracy, Precision, Recall, Specificity, F1 + TP/FP/FN/TN."""
    head = "| Đánh giá | N | Accuracy | Precision | Recall (Sensitivity) | Specificity | F1 | TP | FP | FN | TN |\n"
    head += "|---|---|---|---|---|---|---|---|---|---|---|\n"
    for name, m in rows:
        head += (
            f"| {name} | {m['n']} | {fmt_pct(m['accuracy'])} | {fmt_pct(m['precision'])} | {fmt_pct(m['recall'])} | "
            f"{fmt_pct(m['specificity'])} | {fmt_pct(m['f1'])} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} |\n"
        )
    return head

"""Xuất sơ đồ khối docs/diagrams/*.svg -> docs/figures/diagram_*.png (độ phân giải cao, dán Word / in poster).

SVG là bản gốc (vector, sửa được bằng Inkscape / Figma / draw.io / trình soạn thảo văn bản).
PNG được chụp bằng Chrome/Edge chạy ẩn (headless) nên không cần cài thêm thư viện.

    python report/render_diagrams.py              # mặc định phóng 3x (~4800 px chiều ngang)
    python report/render_diagrams.py --scale 4    # in poster khổ lớn
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from shared import FIG_DIR, ROOT

SRC = ROOT / "docs" / "diagrams"
BROWSERS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "google-chrome",
    "chromium",
    "chromium-browser",
]


def find_browser() -> str:
    for b in BROWSERS:
        if Path(b).exists() or shutil.which(b):
            return b
    sys.exit("Không tìm thấy Chrome/Edge để xuất PNG (SVG trong docs/diagrams vẫn dùng trực tiếp được).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", type=float, default=3)
    a = ap.parse_args()
    browser = find_browser()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    for svg in sorted(SRC.glob("*.svg")):
        head = svg.read_text(encoding="utf-8")[:400]
        w, h = (int(float(v)) for v in re.search(r'width="([\d.]+)"\s+height="([\d.]+)"', head).groups())
        out = FIG_DIR / f"diagram_{svg.stem}.png"
        with tempfile.TemporaryDirectory() as profile:
            subprocess.run(
                [
                    browser,
                    "--headless=new",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    f"--user-data-dir={profile}",
                    f"--window-size={w},{h}",
                    f"--force-device-scale-factor={a.scale}",
                    f"--screenshot={out}",
                    svg.resolve().as_uri(),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
        print(f"  {out.relative_to(ROOT)}  ({int(w * a.scale)}x{int(h * a.scale)})")


if __name__ == "__main__":
    main()

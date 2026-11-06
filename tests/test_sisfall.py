"""Kiểm thử chuyển đổi SisFall: đơn vị, tần số, cửa sổ — và khớp dữ liệu train thật nếu có."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from tinyml.sisfall_to_ei import impact_peaks, peak_window
from tinyml.stream_eval import G, load_recording

ROOT = Path(__file__).resolve().parent.parent


def fake_file(path: Path, n: int, peak_at: int | None, peak_g: float = 5.0):
    """ADXL345 raw: 1 g = 2^13/32 = 256 đơn vị. Đứng yên: y = -1 g."""
    lines = []
    for i in range(n):
        y = -256 if peak_at is None or abs(i - peak_at) >= 4 else int(-256 * peak_g)
        lines.append(f"  0,{y},0,10,20,30,0,{y * 2},0;")
    path.write_text("\n".join(lines) + "\n")


def test_units_and_resampling(tmp_path):
    f = tmp_path / "D01_SA01_R01.txt"
    fake_file(f, 800, None)
    x = load_recording(f)
    assert x.shape == (200, 6)  # 200 Hz -> 50 Hz, 6 trục
    assert np.allclose(x[50, :3], [0, -G, 0], atol=1e-3)  # m/s²
    assert np.isclose(x[50, 3], 10 * 4000 / 2**16 * np.pi / 180, atol=1e-4)  # rad/s


def test_peak_window_centering():
    x = np.zeros((500, 6), dtype=np.float32)
    x[300, 1] = 50.0
    win = peak_window(x, 300)
    assert win.shape == (100, 6)
    assert int(np.argmax(np.abs(win[:, 1]))) == 50
    assert peak_window(x, 490).shape == (100, 6)  # gần cuối bản ghi vẫn đủ 100 mẫu


def test_impact_peaks():
    x = np.zeros((400, 6), dtype=np.float32)
    x[:, 1] = -G
    x[100, 0] = 3 * G
    x[103, 0] = 4 * G  # cùng một va chạm -> lấy đỉnh cao hơn
    x[300, 0] = 3 * G
    assert impact_peaks(x) == [103, 300]


def test_cli_end_to_end(tmp_path):
    src = tmp_path / "SisFall_dataset"
    for subj in ["SA01", "SA02", "SA03", "SA04", "SA05"]:
        (src / subj).mkdir(parents=True)
        fake_file(src / subj / f"F01_{subj}_R01.txt", 3000, 1500, peak_g=6)
        fake_file(src / subj / f"D05_{subj}_R01.txt", 3000, 1200, peak_g=3)
    out = tmp_path / "out"
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tinyml" / "sisfall_to_ei.py"),
            "--sisfall-dir",
            str(src),
            "--out",
            str(out),
            "--hard-negatives",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert r.returncode == 0, r.stderr
    csvs = sorted(out.rglob("*.csv"))
    assert len(csvs) == 15  # 5 Fall + 5 Normal ngẫu nhiên + 5 Normal căn đỉnh
    assert len(list((out / "testing").glob("*.csv"))) == 3
    lines = next(p for p in csvs if p.name.startswith("Fall.")).read_text().splitlines()
    assert lines[0] == "timestamp,ax,ay,az,gx,gy,gz"
    assert len(lines) == 101 and lines[2].startswith("20,")


EI_JSON = ROOT / "data" / "ei_sisfall" / "training" / "Fall" / "Fall.001.json"
RAW = ROOT / "data" / "sisfall_raw"


@pytest.mark.skipif(not (EI_JSON.exists() and RAW.exists()), reason="cần dữ liệu SisFall gốc + JSON của nhóm")
def test_matches_team_training_data_exactly():
    """Cửa sổ Fall tạo từ bản ghi gốc phải TRÙNG dữ liệu đã dùng train model Edge Impulse."""
    payload = json.loads(EI_JSON.read_text())["payload"]
    target = np.asarray(payload["values"], dtype=np.float32)
    name = payload["device_name"].split("-")[-1]
    x = load_recording(RAW / name.split("_")[1] / f"{name}.txt")
    win = peak_window(x, int(np.argmax(np.linalg.norm(x[:, :3], axis=1))))
    assert np.abs(win - target).max() < 1e-3

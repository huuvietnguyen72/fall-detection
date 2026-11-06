"""Biên dịch và chạy kiểm thử C++ cho lõi firmware + kiểm tra hiệu năng trên SisFall (nếu có dữ liệu)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FW = ROOT / "firmware" / "fall_belt"


@pytest.mark.skipif(shutil.which("c++") is None, reason="cần trình biên dịch C++")
def test_firmware_core_cpp(tmp_path):
    exe = tmp_path / "test_firmware"
    srcs = [
        ROOT / "tests" / "firmware" / "test_firmware.cpp",
        FW / "detector.cpp",
        FW / "belt_logic.cpp",
        FW / "orientation.cpp",
    ]
    subprocess.run(
        ["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", f"-I{FW}", *map(str, srcs), "-o", str(exe)],
        check=True,
        capture_output=True,
        text=True,
    )
    r = subprocess.run([str(exe)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    assert "ALL PASSED" in r.stdout


SISFALL = ROOT / "data" / "sisfall_raw"
MODEL = ROOT / "firmware" / "ei_models" / "Fall-Detection-SisFall_inferencing.zip"


@pytest.mark.skipif(not (SISFALL.exists() and MODEL.exists()), reason="cần data/sisfall_raw + model Edge Impulse")
def test_detector_on_sisfall_meets_targets(tmp_path):
    """Hồi quy chất lượng: firmware detector + model thật trên 4500 bản ghi SisFall."""
    out = tmp_path / "metrics.json"
    subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "tinyml" / "stream_eval.py"), "--json", str(out)],
        check=True,
        capture_output=True,
        text=True,
    )
    m = json.loads(out.read_text())
    assert m["all"]["recall"] >= 0.94
    assert m["all"]["fa_recordings"] <= 0.01
    assert m["new_subjects"]["recall"] >= 0.95

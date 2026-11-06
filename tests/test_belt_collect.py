"""Công cụ thu dữ liệu từ đai: tách dòng CSV và cắt cửa sổ Edge Impulse đúng như dữ liệu train."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tinyml"))
import belt_collect as bc  # noqa: E402
from stream_eval import G  # noqa: E402


def trial(spike_at: int | None, n: int = 400) -> np.ndarray:
    x = np.zeros((n, 6), np.float32)
    x[:, 1] = -G
    if spike_at is not None:
        x[spike_at, 1] = -4 * G
    return x


def test_parse_ignores_log_lines():
    assert bc.parse(b"0.1,-9.8,0.2,0,0,0.5\n") == [0.1, -9.8, 0.2, 0.0, 0.0, 0.5]
    assert bc.parse(b"[NET] MQTT da ket noi 192.168.1.2:1883\n") is None
    assert bc.parse(b"1,2,3\n") is None


def read_windows(folder: Path) -> list[np.ndarray]:
    return [np.loadtxt(f, delimiter=",", skiprows=1)[:, 1:] for f in sorted(folder.glob("*.csv"))]


def test_fall_window_has_peak_at_sample_50(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "OUT", tmp_path)
    bc.save_trial("Fall", trial(spike_at=230))
    (win,) = read_windows(tmp_path / "ei")
    assert win.shape == (100, 6)
    assert int(np.argmax(np.linalg.norm(win[:, :3], axis=1))) == 50


def test_fall_without_impact_exports_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "OUT", tmp_path)
    bc.save_trial("Fall", trial(spike_at=None))
    assert read_windows(tmp_path / "ei") == []
    assert len(list((tmp_path / "raw").glob("Fall.*.csv"))) == 1  # vẫn giữ bản ghi gốc để `eval`


def test_normal_exports_hard_negative_plus_random(tmp_path, monkeypatch):
    monkeypatch.setattr(bc, "OUT", tmp_path)
    bc.save_trial("Normal", trial(spike_at=200))
    assert len(read_windows(tmp_path / "ei")) == 2

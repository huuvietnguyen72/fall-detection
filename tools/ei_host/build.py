"""Biên dịch model Edge Impulse (thư viện Arduino .zip) + bộ phát hiện của firmware thành chương trình chạy trên PC.

    python tools/ei_host/build.py firmware/ei_models/Fall-Detection-SisFall_inferencing.zip

Tạo trong build/ei_host/<tên model>/:
  runner : chạy model trên từng cửa sổ (xem runner.cpp)
  stream : chạy ĐÚNG detector.cpp + ei_glue.cpp của firmware trên bản ghi liên tục (xem stream.cpp)
Dùng đúng mã C++ (DSP + mạng nơ-ron int8) sẽ chạy trên ESP32.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FIRMWARE = ROOT / "firmware" / "fall_belt"
SKIP = ("/CMSIS/", "/porting/", "/arc_mli/", "esp-nn", "/tests/")
TARGETS = {
    "runner": [HERE / "runner.cpp"],
    "stream": [HERE / "stream.cpp", FIRMWARE / "detector.cpp", FIRMWARE / "ei_glue.cpp"],
}


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"Lỗi biên dịch:\n{r.stderr[-3000:]}")


def _flags(src: Path) -> list[str]:
    return [
        "-std=c++17",
        "-O2",
        f"-I{src}",
        f"-I{FIRMWARE}",
        "-DEI_PORTING_POSIX=1",
        "-DEI_PORTING_ARDUINO=0",
        "-DTF_LITE_STATIC_MEMORY",
        "-DFALL_HOST_BUILD",
        "-w",
    ]


def _compile_library(zip_path: Path, out: Path) -> Path:
    """Giải nén + biên dịch SDK/model một lần (có cache)."""
    lib_obj = out / "lib_obj"
    stamp = lib_obj / ".done"
    if stamp.exists() and stamp.stat().st_mtime > zip_path.stat().st_mtime:
        return next((out / "lib").glob("*/src"))
    shutil.rmtree(out, ignore_errors=True)
    lib_obj.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(out / "lib")
    src = next((out / "lib").glob("*/src"))
    sources = [p for ext in ("*.cpp", "*.cc", "*.c") for p in src.rglob(ext) if not any(s in str(p) for s in SKIP)]
    sources.append(HERE / "porting.cpp")

    def compile_one(item):
        i, path = item
        cmd = ["cc", "-O2", f"-I{src}", "-w"] if path.suffix == ".c" else ["c++", *_flags(src)]
        _run([*cmd, "-c", str(path), "-o", str(lib_obj / f"{i:04d}.o")])

    with ThreadPoolExecutor(os.cpu_count()) as ex:
        list(ex.map(compile_one, enumerate(sources)))
    stamp.touch()
    return src


def build(zip_path: Path, target: str = "runner") -> Path:
    zip_path = zip_path.resolve()
    out = ROOT / "build" / "ei_host" / zip_path.stem
    src = _compile_library(zip_path, out)
    exe = out / target
    inputs = TARGETS[target]
    deps = [*inputs, *FIRMWARE.glob("*.h"), out / "lib_obj" / ".done"]
    if exe.exists() and exe.stat().st_mtime > max(p.stat().st_mtime for p in deps):
        return exe
    objs = []
    for path in inputs:
        obj = out / f"{target}_{path.stem}.o"
        _run(["c++", *_flags(src), "-c", str(path), "-o", str(obj)])
        objs.append(str(obj))
    _run(["c++", *objs, *map(str, sorted((out / "lib_obj").glob("*.o"))), "-o", str(exe)])
    return exe


if __name__ == "__main__":
    for t in TARGETS:
        print(build(Path(sys.argv[1]), t))

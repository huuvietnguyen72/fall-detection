"""Nạp firmware đai lưng bằng một lệnh (dùng arduino-cli).

    python firmware/flash.py                 # cài thư viện + biên dịch + tự tìm cổng USB + nạp
    python firmware/flash.py --monitor       # nạp xong mở Serial Monitor (115200)
    python firmware/flash.py --compile-only  # chỉ kiểm tra biên dịch (không cần cắm ESP32)
    python firmware/flash.py --port /dev/cu.usbserial-0001   # Windows: --port COM3

Không dùng arduino-cli? Mở firmware/fall_belt/fall_belt.ino bằng Arduino IDE (xem README).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SKETCH = HERE / "fall_belt"
MODEL_ZIP = HERE / "ei_models" / "Fall-Detection-SisFall_inferencing.zip"
LIB_DIR = ROOT / "build" / "arduino_libs"
FQBN = "esp32:esp32:esp32:PartitionScheme=huge_app"
ESP32_INDEX = "https://espressif.github.io/arduino-esp32/package_esp32_index.json"
LIBRARIES = ["Adafruit MPU6050", "Adafruit SSD1306", "Adafruit GFX Library", "PubSubClient", "WiFiManager"]


def cli(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["arduino-cli", *args], check=check, text=True, capture_output=capture)


def ensure_toolchain() -> None:
    if not shutil.which("arduino-cli"):
        sys.exit(
            "Chưa có arduino-cli: `brew install arduino-cli` (macOS) / `winget install ArduinoSA.CLI` (Windows),"
            " mở lại terminal rồi chạy lại — hoặc dùng Arduino IDE (xem README)."
        )
    cores = cli("core", "list", "--format", "json", capture=True).stdout
    if '"esp32:esp32"' not in cores:
        print("Cài bộ công cụ ESP32 (lần đầu, ~vài phút)...")
        cli("core", "update-index", "--additional-urls", ESP32_INDEX)
        cli("core", "install", "esp32:esp32", "--additional-urls", ESP32_INDEX)
    installed = cli("lib", "list", "--format", "json", capture=True).stdout
    missing = [lib for lib in LIBRARIES if f'"{lib}"' not in installed]
    if missing:
        print("Cài thư viện:", ", ".join(missing))
        cli("lib", "install", *missing)


def model_library() -> Path | None:
    """Giải nén thư viện model Edge Impulse (không cài vào máy, chỉ dùng khi biên dịch)."""
    if not MODEL_ZIP.exists():
        return None
    with zipfile.ZipFile(MODEL_ZIP) as z:
        name = z.namelist()[0].split("/")[0]
        target = LIB_DIR / name
        if not target.exists() or target.stat().st_mtime < MODEL_ZIP.stat().st_mtime:
            shutil.rmtree(target, ignore_errors=True)
            LIB_DIR.mkdir(parents=True, exist_ok=True)
            z.extractall(LIB_DIR)
    return target


def find_port() -> str | None:
    boards = json.loads(cli("board", "list", "--format", "json", capture=True).stdout or "{}")
    ports = [
        b["port"]["address"] for b in boards.get("detected_ports", []) if b.get("port", {}).get("protocol") == "serial"
    ]
    usb = [
        p for p in ports if any(k in p.lower() for k in ("usbserial", "usbmodem", "slab", "wchusb", "ttyusb", "ttyacm"))
    ]
    usb += [p for p in ports if p.upper().startswith("COM") and p.upper() != "COM1"]  # Windows (COM1 = cổng onboard)
    return (usb or [None])[0]


def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--compile-only", action="store_true")
    ap.add_argument("--monitor", action="store_true")
    args = ap.parse_args()

    ensure_toolchain()
    lib = model_library()
    if lib is None:
        print(f"Không thấy {MODEL_ZIP.name} -> cần USE_EDGE_IMPULSE 0 trong config.h (chỉ dùng luật tư thế)")
    compile_args = ["compile", "--fqbn", FQBN, "--build-path", str(ROOT / "build" / "fw"), str(SKETCH)]
    if lib:
        compile_args[1:1] = ["--library", str(lib)]
    print("Biên dịch firmware (lần đầu ~2 phút)...")
    r = cli(*compile_args, check=False, capture=True)
    if r.returncode != 0:
        sys.exit(r.stdout[-3000:] + r.stderr[-3000:])
    print(next((ln for ln in r.stdout.splitlines() if "Sketch uses" in ln), "Biên dịch xong"))
    if args.compile_only:
        return

    port = args.port or find_port()
    if not port:
        sys.exit("Không thấy ESP32. Cắm cáp USB (loại có dây dữ liệu), cài driver CP210x/CH340 nếu cần, rồi chạy lại.")
    print(f"Nạp vào {port}... (nếu kẹt ở 'Connecting...', giữ nút BOOT trên ESP32)")
    cli("upload", "--fqbn", FQBN, "--port", port, "--input-dir", str(ROOT / "build" / "fw"), str(SKETCH))
    print("Nạp xong!")
    if args.monitor:
        cli("monitor", "--port", port, "--config", "baudrate=115200", check=False)


if __name__ == "__main__":
    main()

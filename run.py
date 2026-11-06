"""Khởi động cả hệ thống bằng một lệnh: MQTT broker + Server/Dashboard + Camera.

    python run.py                         # webcam laptop
    python run.py --camera http://192.168.1.5:8080/video   # camera điện thoại
    python run.py --no-camera             # chỉ broker + server (vd. camera chạy máy khác)
    python run.py --camera-sim            # camera giả lập (không cần webcam)

Đai lưng thật tự kết nối qua WiFi. Chưa có đai thì mở thêm terminal:  python -m simulator.belt_sim
Ctrl+C để tắt tất cả.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import settings as S  # noqa: E402

COLORS = {"broker": "\033[90m", "server": "\033[96m", "camera": "\033[95m"}
NOISE = ("W0000 ", "I0000 ", "INFO: Created TensorFlow")  # log nội bộ của MediaPipe/TFLite
RESET = "\033[0m"


def port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def find_mosquitto() -> str | None:
    for c in (
        shutil.which("mosquitto"),
        "/opt/homebrew/opt/mosquitto/sbin/mosquitto",
        "/usr/local/opt/mosquitto/sbin/mosquitto",
        "/usr/sbin/mosquitto",
    ):
        if c and Path(c).exists():
            return c
    return None


def pipe(name: str, proc: subprocess.Popen) -> None:
    color = COLORS.get(name, "")
    for line in iter(proc.stdout.readline, ""):
        if not line.startswith(NOISE):
            print(f"{color}[{name}]{RESET} {line}", end="", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cam = ap.add_mutually_exclusive_group()
    cam.add_argument("--camera", default=S.env("CAMERA_SOURCE", "0"), help="0 = webcam, hoặc URL camera")
    cam.add_argument("--no-camera", action="store_true")
    cam.add_argument("--camera-sim", action="store_true")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    py = sys.executable
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    procs: list[tuple[str, subprocess.Popen]] = []

    def start(name: str, cmd: list[str], **kw) -> None:
        p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kw)
        procs.append((name, p))
        threading.Thread(target=pipe, args=(name, p), daemon=True).start()

    if S.MQTT_HOST in ("localhost", "127.0.0.1") and not port_open("127.0.0.1", S.MQTT_PORT):
        exe = find_mosquitto()
        if not exe:
            sys.exit("Chưa cài Mosquitto: chạy `brew install mosquitto` (macOS) hoặc `docker compose up -d`")
        start("broker", [exe, "-c", str(ROOT / "mosquitto" / "mosquitto.conf")])
        for _ in range(30):
            if port_open("127.0.0.1", S.MQTT_PORT):
                break
            time.sleep(0.1)
    else:
        print(f"[broker] dùng broker có sẵn tại {S.MQTT_HOST}:{S.MQTT_PORT}")

    start("server", [py, "-m", "server.main"])
    if args.camera_sim:
        start("camera", [py, "-m", "simulator.vision_sim"], stdin=subprocess.PIPE)
    elif not args.no_camera:
        start("camera", [py, "-m", "vision.main", "--source", args.camera])

    url = f"http://localhost:{S.DASHBOARD_PORT}"
    for _ in range(50):
        if port_open("127.0.0.1", S.DASHBOARD_PORT):
            break
        time.sleep(0.2)
    print(f"\n  Dashboard: {url}\n  Chưa có đai lưng? Mở terminal khác: {py} -m simulator.belt_sim\n  Ctrl+C để tắt.\n")
    if not args.no_browser:
        webbrowser.open(url)

    def stop(*_):
        for _, p in reversed(procs):
            p.terminate()
        for _, p in procs:
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while True:
        for name, p in procs:
            if p.poll() is not None and name != "camera":
                print(f"[{name}] đã dừng (mã {p.returncode}) — tắt hệ thống")
                stop()
        time.sleep(1)


if __name__ == "__main__":
    main()

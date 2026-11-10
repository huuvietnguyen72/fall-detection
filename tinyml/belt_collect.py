"""Fine-tune bằng chính đai lưng: thu dữ liệu qua USB hoặc WiFi -> CSV Edge Impulse -> chấm ngưỡng firmware.

    python tinyml/belt_collect.py record --label Fall      # mỗi lần Enter = 1 lần thử (mặc định 8 s)
    python tinyml/belt_collect.py record --label Fall --port 192.168.1.20   # qua WiFi (IP đai, hoặc belt01.local)
    python tinyml/belt_collect.py record --label Normal    # đi, ngồi phịch, cúi, nhảy, đặt đai xuống bàn...
    python tinyml/belt_collect.py eval                     # chạy ĐÚNG mã firmware trên các lần thử đã ghi
    python tinyml/belt_collect.py eval --grid              # so sánh nhiều bộ ngưỡng

Mỗi lần thử: đứng yên ~2 s -> thực hiện động tác -> giữ yên (nằm/đứng) đến khi hết giờ.
  data/belt/raw/<Nhãn>.<thời điểm>.csv : toàn bộ lần thử (dùng cho `eval`)
  data/belt/ei/<Nhãn>.<thời điểm>[.k].csv : cửa sổ 2 s căn đỉnh va chạm vào giữa -> upload lên Edge Impulse
Dữ liệu là đầu ra lệnh `data` của firmware: đã quy về hệ trục + đơn vị của model (m/s², rad/s, 50 Hz).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sisfall_to_ei import AXES, impact_peaks, peak_window, write_csv  # noqa: E402
from stream_eval import DEFAULT_MODEL, HZ, G, build, run_firmware_detector  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "belt"
ESP_USB_VIDS = {0x10C4, 0x1A86, 0x0403, 0x303A}  # CP210x, CH340, FTDI, Espressif
DATA_TCP_PORT = 2323  # khớp DATA_TCP_PORT trong firmware/fall_belt/config.h


# ----------------------------------------------------------------------------- thu dữ liệu
def wifi_url(port: str | None) -> str | None:
    """`192.168.1.20` / `belt01.local` / `socket://...` -> URL TCP của đai; cổng COM / thiết bị USB -> None."""
    if not port:
        return None
    if "://" in port:
        return port
    if port.upper().startswith("COM") or port.startswith("/dev/"):
        return None
    return f"socket://{port}" if ":" in port else f"socket://{port}:{DATA_TCP_PORT}"


def open_serial(port: str | None):
    import serial
    from serial.tools import list_ports

    url = wifi_url(port)
    if url:  # thu qua WiFi: firmware mở cổng TCP DATA_TCP_PORT, giao thức y hệt Serial
        try:
            ser = serial.serial_for_url(url, timeout=0.2)
        except serial.SerialException as e:
            sys.exit(f"Không kết nối được đai qua WiFi ({url}): {e}\n"
                     "Kiểm tra đai đã vào WiFi (gõ `info` qua USB để xem IP), máy tính cùng mạng.")
        print(f"Đã kết nối đai qua WiFi: {url}")
        return ser

    if not port:
        found = [p.device for p in list_ports.comports() if p.vid in ESP_USB_VIDS]
        if not found:
            sys.exit("Không thấy ESP32 qua USB. Cắm cáp dữ liệu / cài driver, hoặc chỉ định --port (vd COM3).")
        port = found[0]
    ser = serial.Serial()
    ser.port, ser.baudrate, ser.timeout = port, 115200, 0.2
    ser.dtr = ser.rts = False  # không reset ESP32 khi mở cổng
    ser.open()
    print(f"Đã mở {port}")
    return ser


def parse(line: bytes) -> list[float] | None:
    parts = line.decode(errors="ignore").strip().split(",")
    if len(parts) != 6:
        return None
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None


def streaming(ser, seconds: float = 1.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if parse(ser.readline()):
            return True
    return False


def start_data_mode(ser) -> None:
    print("Đang bật luồng dữ liệu của đai (vài giây)...", flush=True)
    if streaming(ser):
        return
    ser.write(b"data\n")  # lệnh `data` bật/tắt luồng CSV của firmware
    if not streaming(ser, 2):
        sys.exit("Đai không gửi dữ liệu. Kiểm tra Serial Monitor khác đã đóng chưa, và firmware đã nạp đúng (bản có thu qua WiFi nếu dùng IP).")


def record_trial(ser, seconds: float) -> np.ndarray:
    """Ghi đúng `seconds` giây dữ liệu (đếm theo mẫu 50 Hz của đai, không theo đồng hồ máy tính)."""
    ser.reset_input_buffer()
    need, rows, deadline = int(seconds * HZ), [], time.time() + seconds * 1.5
    while len(rows) < need and time.time() < deadline:
        row = parse(ser.readline())
        if row:
            rows.append(row)
    return np.asarray(rows, dtype=np.float32)


def save_trial(label: str, x: np.ndarray) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    (OUT / "ei").mkdir(parents=True, exist_ok=True)
    np.savetxt(OUT / "raw" / f"{label}.{stamp}.csv", x, delimiter=",", header=",".join(AXES), comments="", fmt="%.5f")

    peaks = impact_peaks(x)
    mag = np.linalg.norm(x[:, :3], axis=1) / G
    if label == "Fall":
        early = int(np.argmax(mag)) / HZ
        if peaks and early < 2.0:  # bộ phát hiện cần [-2 s, -1 s] trước đỉnh để so tư thế
            print(f"  ! Ngã sớm quá (va chạm ở {early:.1f} s, cần >= 2 s): `eval` sẽ không chấm được lần này."
                  " Lần sau đứng yên 2-3 s sau chữ GHI rồi mới ngã.")
        if not peaks:
            print(f"  ! Không có va chạm > 2 g (đỉnh {mag.max():.2f} g): đai sẽ không xét lần này -> không xuất cửa sổ")
            return
        windows = [peak_window(x, int(np.argmax(mag)))]  # đúng như dữ liệu train: đỉnh tại mẫu 50
    else:  # Normal: mọi va chạm > 2 g (mẫu khó) + 1 cửa sổ ngẫu nhiên
        windows = [peak_window(x, p) for p in peaks]
        start = np.random.randint(0, max(1, len(x) - 100))
        windows.append(x[start : start + 100] if len(x) >= 100 else peak_window(x, len(x) // 2))
    for k, w in enumerate(windows):
        write_csv(OUT / "ei" / f"{label}.{stamp}{f'.{k}' if k else ''}.csv", w)
    print(f"  Đã lưu: {len(x)} mẫu, đỉnh {mag.max():.2f} g, {len(windows)} cửa sổ Edge Impulse")


def cmd_record(args) -> None:
    ser = open_serial(args.port)
    start_data_mode(ser)
    # Qua WiFi: chỉ bật luồng trong lúc ghi. Nếu để chạy khi đang chờ Enter, TCP bị nghẽn và đai giữ lại
    # ~2 s mẫu CŨ trong bộ đệm gửi -> lần ghi sau bắt đầu bằng dữ liệu cũ + một khoảng hụt.
    # (Qua USB không bị vì phần thừa bị bỏ, nên giữ luồng chạy liên tục như cũ.)
    pause_between = wifi_url(args.port) is not None
    on = True

    def stream(want: bool) -> None:
        nonlocal on
        if on != want:
            ser.write(b"data\n")  # lệnh `data` bật/tắt luồng CSV
            on = want

    n = 0
    try:
        while True:
            if pause_between:
                stream(False)
            k = input(f"\n[{args.label} #{n + 1}] Enter = ghi {args.seconds:.0f} s, q = thoát: ").strip().lower()
            if k == "q":
                break
            stream(True)
            for i in (3, 2, 1):
                print(f"  {i}...", flush=True)
                time.sleep(1)
            print("  GHI - đứng yên 2 s rồi thực hiện động tác", flush=True)
            x = record_trial(ser, args.seconds)  # tự xóa phần nhận trong lúc đếm ngược
            if len(x) < int(HZ * args.seconds):
                print(f"  ! Chỉ nhận {len(x)}/{HZ * args.seconds:.0f} mẫu: đai gửi thiếu (dây USB / WiFi yếu?) -> bỏ lần này")
                continue
            save_trial(args.label, x)
            n += 1
    finally:
        stream(False)  # tắt luồng CSV
        ser.close()
    print(f"\nXong {n} lần thử. Upload thư mục {OUT / 'ei'} lên Edge Impulse (Data acquisition -> Upload data).")


# ----------------------------------------------------------------------------- chấm ngưỡng
def cmd_eval(args) -> None:
    files = sorted((OUT / "raw").glob("*.csv"))
    if not files:
        sys.exit("Chưa có dữ liệu: chạy `belt_collect.py record` trước.")
    data = {f.stem: np.loadtxt(f, delimiter=",", skiprows=1, dtype=np.float32, ndmin=2) for f in files}
    exe = build(args.model, "stream")

    def score(trigger, ai, tilt, pre, verbose=False):
        ev = run_firmware_detector(exe, data, trigger, ai, tilt, pre)
        hit = {n: any(e["fall"] for e in es) for n, es in ev.items()}
        falls = [n for n in data if n.startswith("Fall.")]
        normals = [n for n in data if not n.startswith("Fall.")]
        if verbose:
            print(f"{'Lần thử':32} {'đỉnh g':>7} {'AI':>5} {'nghiêng':>8} {'trước':>6}  kết luận")
            for n, es in ev.items():
                # va chạm đã kích hoạt báo ngã, nếu không có thì va chạm mạnh nhất
                e = next((e for e in es if e["fall"]), None) or max(es, key=lambda e: e["peak_g"], default=None)
                ok = hit[n] == n.startswith("Fall.")
                cols = f"{e['peak_g']:7.2f} {e['ai']:5.2f} {e['tilt']:7.0f}° {e['pre_tilt']:5.0f}°" if e else " " * 30
                print(f"{n:32} {cols}  {'NGÃ' if hit[n] else '-':4} {'' if ok else '<- SAI'}")
        recall = sum(hit[n] for n in falls) / len(falls) if falls else float("nan")
        false = sum(hit[n] for n in normals) / len(normals) if normals else float("nan")
        return recall, false, len(falls), len(normals)

    r, f, nf, nn = score(args.trigger, args.ai, args.tilt, args.pre_tilt, verbose=True)
    print(f"\nNgưỡng hiện tại: bắt được {r:.0%} của {nf} lần ngã · báo nhầm {f:.0%} của {nn} lần sinh hoạt")
    if args.grid:
        print("\nTRIGGER_G  AI_THRESHOLD  MIN_TILT  MAX_PRE_TILT   bắt ngã  báo nhầm")
        for trig in (1.8, 2.0, 2.5):
            for ai in (0.3, 0.5, 0.8):
                for tilt in (20, 30, 45):  # 27 tổ hợp
                    r, f, _, _ = score(trig, ai, tilt, args.pre_tilt)
                    print(f"{trig:9.1f}  {ai:12.1f}  {tilt:8d}  {args.pre_tilt:12.0f}   {r:7.0%}  {f:8.0%}")
        print("\nChọn bộ ngưỡng ưng ý rồi sửa trong firmware/fall_belt/config.h và nạp lại.")


def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="thu dữ liệu từ đai")
    rec.add_argument("--label", required=True, choices=["Fall", "Normal"])
    rec.add_argument("--seconds", type=float, default=8.0)
    rec.add_argument("--port", help="COMx / /dev/... (USB) hoặc IP / belt01.local (WiFi); bỏ trống = tự tìm USB")
    ev = sub.add_parser("eval", help="chấm ngưỡng firmware trên dữ liệu đã thu")
    ev.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    ev.add_argument("--trigger", type=float, default=1.8)
    ev.add_argument("--ai", type=float, default=0.5)
    ev.add_argument("--tilt", type=float, default=30.0)
    ev.add_argument("--pre-tilt", type=float, default=65.0)
    ev.add_argument("--grid", action="store_true")
    args = ap.parse_args()
    cmd_record(args) if args.cmd == "record" else cmd_eval(args)


if __name__ == "__main__":
    main()

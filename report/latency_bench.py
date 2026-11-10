"""Đo độ trễ (latency) của hệ thống xử lý song song: đai lưng ‖ camera -> MQTT -> server fusion -> Telegram.

Hai chế độ, chạy được độc lập:

  python report/latency_bench.py              # BENCH: dựng hệ thống riêng (broker cổng khác + server thật
                                              # + đai/camera giả lập) rồi đo từng chặng, KHÔNG đụng hệ thống đang chạy
  python report/latency_bench.py --live       # LIVE: nghe hệ thống thật đang chạy (đai + camera + server)
                                              # 30 s: thời gian suy luận trên ESP32, WiFi, độ trễ camera
  python report/latency_bench.py --telegram   # thêm: đo thời gian gọi API Telegram (getMe, không gửi tin)

Chặng đo trong BENCH (lặp --trials lần):
  belt->server   : đai publish sự kiện va chạm -> server xử lý xong bản tin (MQTT + phân tích JSON)
  cam->server    : camera publish tư thế -> server cập nhật fusion
  tick           : hết đếm ngược -> server ra quyết định SOS (vòng fusion chạy mỗi 100 ms)
  server->belt   : quyết định SOS -> lệnh "sos" tới đai (còi, LED)
  snapshot       : yêu cầu ảnh hiện trường -> camera trả ảnh -> sẵn sàng gửi Telegram
  fusion_step    : thời gian CPU của một lần FusionEngine.tick()

Kết quả: docs/results/latency.json, docs/results/latency.md, docs/figures/latency_*.png|svg
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from shared import AQUA, BLUE, GRID, INK, INK2, ORANGE, RES_DIR, ROOT, YELLOW, save, setup_matplotlib, write_json

from common import protocol as P  # noqa: E402
from common import settings as S  # noqa: E402

# Hằng số thuật toán (firmware/fall_belt/detector.h, config.h)
SAMPLE_HZ = 50
DECISION_AFTER_PEAK_S = 125 / SAMPLE_HZ  # kTiltPost = 125 mẫu -> 2.5 s sau đỉnh mới đủ dữ liệu kết luận
REFINE_S = 25 / SAMPLE_HZ  # tìm đỉnh trong 0.5 s sau khi vượt ngưỡng (nằm trong 2.5 s ở trên)


def stats(xs) -> dict:
    a = np.asarray(xs, float)
    if not len(a):
        return {"n": 0}
    return {
        "n": int(len(a)),
        "mean": float(a.mean()),
        "median": float(np.median(a)),
        "p95": float(np.percentile(a, 95)),
        "min": float(a.min()),
        "max": float(a.max()),
        "std": float(a.std()),
    }


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_mosquitto() -> str:
    for p in (
        shutil.which("mosquitto"),
        "/opt/homebrew/opt/mosquitto/sbin/mosquitto",
        "/usr/local/opt/mosquitto/sbin/mosquitto",
        "/usr/sbin/mosquitto",
        r"C:\Program Files\mosquitto\mosquitto.exe",
    ):
        if p and Path(p).exists():
            return p
    sys.exit("Không tìm thấy mosquitto (cần cho chế độ BENCH).")


# ============================================================================= BENCH
def bench(trials: int, countdown: float) -> dict:
    port = free_port()
    conf = Path(tempfile.mkdtemp()) / "mosquitto.conf"
    conf.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\n")
    broker = subprocess.Popen([find_mosquitto(), "-c", str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)

    # Server thật, nhưng nối vào broker riêng, Telegram DRY-RUN, không quảng bá mDNS
    S.MQTT_HOST, S.MQTT_PORT, S.TELEGRAM_BOT_TOKEN, S.TELEGRAM_CHAT_ID = "127.0.0.1", port, "", ""
    S.LOG_DIR = ROOT / "build" / "latency_logs"
    from server.fusion import FusionConfig
    from server.main import FallServer

    server = FallServer(FusionConfig(countdown_s=countdown))
    server.advertiser.start = lambda: None
    server.telegram.send = lambda text, photo=None: marks.setdefault("telegram", time.perf_counter()) or True
    marks: dict[str, float] = {}
    rec: dict[str, list[float]] = {k: [] for k in ("belt_server", "cam_server", "tick", "server_belt", "snapshot")}

    orig_belt, orig_vision, orig_handle = server._on_belt, server._on_vision, server._handle

    def on_belt(belt_id, kind, data, now):
        orig_belt(belt_id, kind, data, now)
        if data.get("type") == "impact" and "t0" in data:
            rec["belt_server"].append((time.perf_counter() - data["t0"]) * 1000)
            marks["deadline"] = time.perf_counter() + countdown

    def on_vision(cam_id, data, now):
        orig_vision(cam_id, data, now)
        if "t0" in data:
            rec["cam_server"].append((time.perf_counter() - data["t0"]) * 1000)

    def handle(actions):
        for a in actions:
            if a.kind == "sos" and "deadline" in marks:
                marks["sos"] = time.perf_counter()
                rec["tick"].append((marks["sos"] - marks["deadline"]) * 1000)
        orig_handle(actions)

    server._on_belt, server._on_vision, server._handle = on_belt, on_vision, handle
    server.start()

    # Đai + camera giả lập dùng chung một client (đồng hồ perf_counter chung -> đo chính xác)
    sim = S.mqtt_client(f"bench-{port}")
    got_cmd = threading.Event()

    def on_msg(c, u, m):
        if m.topic.endswith("/cmd") and json.loads(m.payload).get("cmd") == "sos" and "sos" in marks:
            rec["server_belt"].append((time.perf_counter() - marks["sos"]) * 1000)
            got_cmd.set()
        elif m.topic.endswith("/snapshot/request"):
            c.publish(P.VISION_SNAPSHOT.format(cam_id=S.CAM_ID), b"\xff\xd8" + os.urandom(30_000), qos=1)

    sim.on_message = on_msg
    sim.connect(S.MQTT_HOST, port)
    sim.subscribe([(P.BELT_CMD.format(belt_id=S.BELT_ID), 1), (P.VISION_SNAPSHOT_REQ.format(cam_id=S.CAM_ID), 1)])
    sim.loop_start()
    stop = threading.Event()

    def pump():  # đai gửi trạng thái 1 Hz, camera gửi tư thế ~15 Hz (như hệ thống thật)
        k = 0
        while not stop.is_set():
            sim.publish(
                P.VISION_POSTURE.format(cam_id=S.CAM_ID),
                json.dumps({"posture": P.LYING, "confidence": 0.9, "ts": time.time(), "t0": time.perf_counter()}),
            )
            if k % 15 == 0:
                sim.publish(P.BELT_STATUS.format(belt_id=S.BELT_ID), json.dumps({"state": "IDLE"}))
            k += 1
            time.sleep(1 / 15)

    threading.Thread(target=pump, daemon=True).start()
    time.sleep(1.5)
    snapshot_rt = []
    for i in range(trials):
        marks.clear()
        got_cmd.clear()
        sim.publish(
            P.BELT_EVENT.format(belt_id=S.BELT_ID),
            json.dumps({"type": "impact", "score": 0.95, "peak_g": 3.1, "tilt": 80, "t0": time.perf_counter()}),
            qos=1,
        )
        t_end = time.perf_counter() + countdown + 5
        while "telegram" not in marks and time.perf_counter() < t_end:
            time.sleep(0.005)
        if "telegram" in marks and "sos" in marks:
            snapshot_rt.append((marks["telegram"] - marks["sos"]) * 1000)
        got_cmd.wait(2)
        sim.publish(P.BELT_EVENT.format(belt_id=S.BELT_ID), json.dumps({"type": "cancel"}), qos=1)
        time.sleep(0.4)
        print(f"\r  lần đo {i + 1}/{trials}", end="", flush=True)
    print()
    rec["snapshot"] = snapshot_rt
    stop.set()

    # Thời gian CPU của một bước fusion
    from server.fusion import FusionEngine

    eng = FusionEngine(FusionConfig(countdown_s=countdown))
    eng.on_belt_status(0.0)
    eng.on_posture(0.0, P.LYING)
    t0 = time.perf_counter()
    n = 20000
    for k in range(n):
        eng.tick(k * 1e-4)
    fusion_us = (time.perf_counter() - t0) / n * 1e6

    sim.loop_stop()
    server.mqtt.loop_stop()
    broker.terminate()
    return {
        "countdown_s": countdown,
        "trials": trials,
        **{k: stats(v) for k, v in rec.items()},
        "fusion_step_us": fusion_us,
        "samples_ms": rec,
    }


# ============================================================================= LIVE
def live(seconds: float) -> dict:
    status, cam_lat, infer = [], [], []
    c = S.mqtt_client(f"latency-live-{int(time.time())}")

    def on_msg(cl, u, m):
        now = time.time()
        try:
            d = json.loads(m.payload)
        except ValueError:
            return
        if m.topic.endswith("/status") and "/belt/" in m.topic:
            status.append({**d, "_t": now})
            if d.get("infer_ms"):
                infer.append(float(d["infer_ms"]))
        elif m.topic.endswith("/posture") and "ts" in d:
            cam_lat.append((now - float(d["ts"])) * 1000)

    c.on_message = on_msg
    c.connect(S.MQTT_HOST, S.MQTT_PORT)
    c.subscribe([(P.BELT_STATUS.format(belt_id="+"), 0), (P.VISION_POSTURE.format(cam_id="+"), 0)])
    c.loop_start()
    print(f"  nghe hệ thống thật {seconds:.0f} s ...")
    time.sleep(seconds)
    c.loop_stop()

    out: dict = {"seconds": seconds}
    if status:
        last = status[-1]
        gaps = np.diff([s["_t"] for s in status]) * 1000
        out["belt"] = {
            "status_msgs": len(status),
            "status_interval_ms": stats(gaps),
            "esp32_infer_ms_last_detection": stats(infer),
            "rssi_dbm": stats([s.get("rssi") for s in status if s.get("rssi") is not None]),
            "free_heap_kb": last.get("heap_kb"),
            "missed_samples_total": last.get("missed"),
            "uptime_s": last.get("uptime_s"),
            "model": last.get("model"),
            "fw": last.get("fw"),
        }
        ip = last.get("ip")
        if ip:
            flag = "-n" if sys.platform == "win32" else "-c"
            r = subprocess.run(["ping", flag, "20", ip], capture_output=True, text=True)
            # macOS/Linux: "time=3.89 ms", Windows: "time=3ms" / "time<1ms"
            rtts = [float(v) for v in re.findall(r"time[=<]([\d.]+)", r.stdout)]
            out["belt"]["wifi_ping_rtt_ms"] = stats(rtts)
    else:
        print("  (không nhận được trạng thái đai — đai có đang bật và kết nối server?)")
    if cam_lat:
        out["camera_frame_to_server_ms"] = stats(cam_lat)
    else:
        print("  (không nhận được tư thế từ camera)")
    return out


def telegram_rtt(token: str, n: int = 10) -> dict | None:
    import requests

    if not token:
        print("  (chưa cấu hình TELEGRAM_BOT_TOKEN -> bỏ qua đo Telegram)")
        return None
    url = f"https://api.telegram.org/bot{token}/getMe"
    rtts = []
    with requests.Session() as s:
        for _ in range(n):
            t0 = time.perf_counter()
            s.get(url, timeout=15).raise_for_status()
            rtts.append((time.perf_counter() - t0) * 1000)
    return {
        "getMe_rtt_ms": stats(rtts),
        "note": "1 lần gọi HTTPS tới API Telegram (giữ kết nối); sendPhoto thêm thời gian tải ảnh lên",
    }


# ============================================================================= báo cáo
def plot_components(b: dict):
    plt = setup_matplotlib()
    rows = [
        ("belt_server", "Đai → server (MQTT)", BLUE),
        ("cam_server", "Camera → server (MQTT)", BLUE),
        ("tick", "Hết đếm ngược → quyết định", ORANGE),
        ("server_belt", "Server → đai (lệnh SOS)", BLUE),
        ("snapshot", "Lấy ảnh hiện trường", AQUA),
    ]
    rows = [r for r in rows if b[r[0]].get("n")]
    fig, ax = plt.subplots(figsize=(8, 3.4))
    data = [b["samples_ms"][k] for k, *_ in rows]
    bp = ax.boxplot(
        data,
        orientation="horizontal",
        widths=0.5,
        patch_artist=True,
        showfliers=True,
        medianprops={"color": "white", "lw": 2},
        flierprops={"markersize": 4, "markerfacecolor": INK2},
    )
    for patch, (_, _, color) in zip(bp["boxes"], rows, strict=True):
        patch.set(facecolor=color, edgecolor=color)
    for k, (key, _, _) in enumerate(rows, 1):
        ax.text(
            max(b["samples_ms"][key]) * 1.15,
            k,
            f"trung vị {b[key]['median']:.1f} ms",
            va="center",
            fontsize=9,
            color=INK2,
        )
    ax.set_yticks(range(1, len(rows) + 1), [r[1] for r in rows])
    ax.set_xscale("log")
    from matplotlib.ticker import FuncFormatter

    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.set_xlabel("Độ trễ (ms, thang log)")
    ax.xaxis.grid(True, color=GRID, lw=0.8)
    ax.set_title(f"Độ trễ từng chặng truyền tin ({b['trials']} lần đo)", loc="left")
    fig.tight_layout()
    save(fig, "latency_components")
    plt.close(fig)


def plot_timeline(budget: list[tuple[str, float, str]]):
    """Dòng thời gian từ lúc ngã đến khi người thân nhận tin (thanh ngang xếp chồng, đơn vị giây)."""
    plt = setup_matplotlib()
    fig, ax = plt.subplots(figsize=(9, 2.3))
    left = 0.0
    for name, sec, color in budget:
        ax.barh(0, sec, left=left, color=color, height=0.5, edgecolor="white", linewidth=2)
        if sec >= 1.0:
            ink = INK if color == YELLOW else "white"  # chữ tối trên nền vàng cho đủ tương phản
            ax.text(left + sec / 2, 0, f"{name}\n{sec:.1f} s", ha="center", va="center", fontsize=9, color=ink)
        left += sec
    small = [f"{n} {s * 1000:.0f} ms" for n, s, _ in budget if s < 1.0]
    ax.set_xlim(0, left * 1.02)
    ax.set_yticks([])
    ax.set_xlabel("Thời gian kể từ lúc va chạm (s)")
    ax.spines["left"].set_visible(False)
    ax.set_title(f"Từ lúc ngã đến khi gửi cảnh báo: ≈ {left:.1f} s", loc="left", pad=18)
    if small:  # các chặng quá ngắn để thấy trên trục: ghi thành dòng phụ dưới tiêu đề
        ax.text(0, 1.02, "Chặng nhỏ: " + " · ".join(small), transform=ax.transAxes, fontsize=8.5, color=INK2)
    fig.tight_layout()
    save(fig, "latency_timeline")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trials", type=int, default=30)
    ap.add_argument("--live", action="store_true", help="đo trên hệ thống thật đang chạy")
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--telegram", action="store_true", help="đo thời gian gọi API Telegram (getMe)")
    a = ap.parse_args()

    token = S.TELEGRAM_BOT_TOKEN  # BENCH tắt Telegram của server giả -> giữ lại token thật trước
    out_path = RES_DIR / "latency.json"
    result = json.loads(out_path.read_text()) if out_path.exists() else {}
    if a.live:
        result["live"] = live(a.seconds)
    else:
        print(f"BENCH: {a.trials} lần, broker + server riêng (không ảnh hưởng hệ thống đang chạy)")
        result["bench"] = bench(a.trials, countdown=1.0)
    if a.telegram:
        t = telegram_rtt(token)
        if t:
            result["telegram"] = t
    write_json("latency", result)

    b = result.get("bench")
    if b:
        plot_components(b)
    countdown_real = S.env_float("COUNTDOWN_S", 15)
    esp_infer = (result.get("live", {}).get("belt", {}).get("esp32_infer_ms_last_detection", {}) or {}).get("median")
    tg = (result.get("telegram", {}).get("getMe_rtt_ms", {}) or {}).get("median")
    budget = [
        ("Đai xét va chạm", DECISION_AFTER_PEAK_S, BLUE),
        ("Đếm ngược cho phép hủy", countdown_real, YELLOW),
    ]
    if b:
        budget[1:1] = [("Đai → server", b["belt_server"]["median"] / 1000, BLUE)]
        budget += [("quyết định", b["tick"]["median"] / 1000, ORANGE), ("ảnh", b["snapshot"]["median"] / 1000, AQUA)]
    if esp_infer:
        budget.insert(1, ("AI trên ESP32", esp_infer / 1000, BLUE))
    if tg:
        budget.append(("Telegram API", tg / 1000, AQUA))
    plot_timeline(budget)

    lines = ["# Độ trễ hệ thống (tự sinh bởi `report/latency_bench.py`)\n"]
    if b:
        lines += [
            f"## Truyền tin và xử lý (BENCH, {b['trials']} lần, cùng máy)\n",
            "| Chặng | Trung vị (ms) | TB (ms) | p95 (ms) | Min–Max (ms) |",
            "|---|---|---|---|---|",
        ]
        names = {
            "belt_server": "Đai → server (MQTT QoS1 + xử lý)",
            "cam_server": "Camera → server (MQTT QoS0 + xử lý)",
            "tick": "Hết đếm ngược → quyết định SOS",
            "server_belt": "Quyết định → lệnh SOS tới đai",
            "snapshot": "Yêu cầu → nhận ảnh hiện trường (30 KB)",
        }
        for k, name in names.items():
            s = b[k]
            if s.get("n"):
                lines.append(
                    f"| {name} | {s['median']:.2f} | {s['mean']:.2f} | {s['p95']:.2f} | {s['min']:.2f}–{s['max']:.2f} |"
                )
        lines.append(f"\nMột bước `FusionEngine.tick()`: **{b['fusion_step_us']:.1f} µs** CPU.\n")
    if "live" in result:
        lines.append("## Hệ thống thật\n")
        lines.append("```json\n" + json.dumps(result["live"], ensure_ascii=False, indent=2) + "\n```\n")
    if "telegram" in result:
        s = result["telegram"]["getMe_rtt_ms"]
        lines.append(
            f"## Telegram API\n\ngetMe: trung vị **{s['median']:.0f} ms**, p95 {s['p95']:.0f} ms ({s['n']} lần).\n"
        )
    lines.append("## Ngân sách thời gian từ lúc ngã đến khi gửi cảnh báo\n")
    lines += ["| Giai đoạn | Thời gian |", "|---|---|"]
    lines += [f"| {n} | {s * 1000:.1f} ms |" if s < 1 else f"| {n} | {s:.2f} s |" for n, s, _ in budget]
    lines.append(f"| **Tổng** | **{sum(s for _, s, _ in budget):.2f} s** |\n")
    lines.append("Đếm ngược 15 s là thời gian CỐ Ý chờ người dùng bấm hủy (giảm báo nhầm), không phải độ trễ xử lý.")
    md = RES_DIR / "latency.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  bảng: {md.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

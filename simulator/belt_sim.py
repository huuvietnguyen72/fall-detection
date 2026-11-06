"""Giả lập đai lưng ESP32 khi chưa có phần cứng — gửi ĐÚNG các bản tin MQTT như firmware thật.

Chạy:  python -m simulator.belt_sim
Gõ phím rồi Enter:
  f = té ngã (AI + tư thế xác nhận)    d = rơi thiết bị (đai tưởng là ngã)
  j = nhảy / chạy (va chạm nhưng bị bỏ qua)
  c = bấm nút hủy                       o = bật/tắt mất kết nối (giả lập đai hỏng)
  q = thoát
"""

from __future__ import annotations

import argparse
import json
import random
import threading
import time

from common import protocol as P
from common import settings as S


class BeltSim:
    def __init__(self, belt_id: str, countdown: int, server_timeout: int = 20):
        self.belt_id = belt_id
        self.countdown = countdown
        self.server_timeout = server_timeout
        self.state = "IDLE"  # IDLE | ALARM | WAIT_SERVER | SOS  (giống BeltController của firmware)
        self.since = time.time()
        self.offline = False
        self.tilt = 5.0
        self.t0 = time.time()
        self.client = S.mqtt_client(f"belt-sim-{belt_id}-{int(time.time())}")
        self.client.on_connect = lambda c, u, f, rc, p: c.subscribe(P.BELT_CMD.format(belt_id=belt_id), qos=1)
        self.client.on_message = self._on_cmd
        self.client.connect_async(S.MQTT_HOST, S.MQTT_PORT, keepalive=30)
        self.client.loop_start()

    def _pub(self, topic: str, data: dict, qos: int = 0) -> None:
        if not self.offline:
            self.client.publish(topic.format(belt_id=self.belt_id), json.dumps(data), qos=qos)

    def _hw(self, msg: str) -> None:
        print(f"  [ĐAI {self.belt_id}] {msg}", flush=True)

    def _enter(self, state: str) -> None:
        self.state, self.since = state, time.time()

    def _on_cmd(self, c, u, msg) -> None:
        if self.offline:
            return
        cmd = json.loads(msg.payload or b"{}").get("cmd")
        if cmd == "dismiss" and self.state in ("ALARM", "WAIT_SERVER"):
            self._enter("IDLE")
            self.tilt = 5.0
            self._hw("Server: báo động giả -> tắt còi")
        elif cmd == "sos":
            self._enter("SOS")
            self._hw("Server xác nhận té ngã -> còi hú, LED đỏ, OLED 'SOS!'")
        elif cmd == "reset":
            self._enter("IDLE")
            self.tilt = 5.0
            self._hw("Reset")

    def detection(self, fall: bool, peak_g: float, ai: float, tilt: float) -> None:
        self._pub(
            P.BELT_EVENT,
            {
                "type": "detection",
                "fall": fall,
                "ai": round(ai, 3),
                "ai_used": True,
                "tilt": round(tilt),
                "pre_tilt": random.randint(3, 20),
                "peak_g": round(peak_g, 2),
                "infer_ms": round(random.uniform(9, 14), 1),
            },
            qos=1,
        )
        verdict = "TÉ NGÃ" if fall else "bỏ qua"
        self._hw(f"Va chạm {peak_g:.1f}g | AI {ai:.2f} | nghiêng +{tilt:.0f}° -> {verdict}")
        if not fall:
            return
        if self.state != "IDLE":
            return
        self._enter("ALARM")
        self.tilt = tilt
        self._hw(f"Còi bíp, LED đỏ nháy, OLED đếm ngược {self.countdown}s")
        self._pub(
            P.BELT_EVENT,
            {
                "type": "impact",
                "score": round(ai, 3),
                "peak_g": round(peak_g, 2),
                "tilt": round(tilt),
                "countdown_s": self.countdown,
            },
            qos=1,
        )

    def cancel(self) -> None:
        if self.state == "IDLE":
            self._hw("Nút bấm (không có sự cố)")
            return
        self._enter("IDLE")
        self.tilt = 5.0
        self._hw("Nút hủy -> tắt còi")
        self._pub(P.BELT_EVENT, {"type": "cancel"}, qos=1)

    def loop(self) -> None:
        last_status, last_tick = 0.0, -1
        while True:
            now = time.time()
            if now - last_status >= 1:
                last_status = now
                remaining = max(0, int(self.countdown - (now - self.since) + 0.999)) if self.state == "ALARM" else 0
                self._pub(
                    P.BELT_STATUS,
                    {
                        "state": self.state,
                        "rssi": random.randint(-62, -50),
                        "ip": "192.168.1.77",
                        "uptime_s": int(now - self.t0),
                        "fw": "sim",
                        "model": "Fall-Detection-SisFall",
                        "calibrated": True,
                        "acc_max_g": round(random.uniform(1.0, 1.25), 2),
                        "tilt": round(self.tilt + random.uniform(-2, 2)),
                        "infer_ms": 11.4,
                        "missed": 0,
                        "sensor_err": 0,
                        "heap_kb": 182,
                        "remaining_s": remaining,
                    },
                )
            elapsed = now - self.since
            if self.state == "ALARM":
                remain = int(self.countdown - elapsed + 0.999)
                if remain != last_tick and remain > 0:
                    self._hw(f"OLED: {remain:2d}s")
                    last_tick = remain
                if elapsed >= self.countdown:
                    self._enter("SOS" if self.offline else "WAIT_SERVER")
                    self._hw("Hết giờ -> " + ("OFFLINE: hú còi SOS tại chỗ" if self.offline else "chờ server"))
            elif self.state == "WAIT_SERVER" and elapsed >= self.server_timeout:
                self._enter("SOS")
                self._hw("Server không phản hồi -> SOS tại chỗ")
            time.sleep(0.1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--belt-id", default=S.BELT_ID)
    ap.add_argument("--countdown", type=int, default=int(S.env_float("COUNTDOWN_S", 15)))
    args = ap.parse_args()
    sim = BeltSim(args.belt_id, args.countdown)
    threading.Thread(target=sim.loop, daemon=True).start()
    print(__doc__.split("Gõ phím rồi Enter:")[1])
    try:
        while True:
            k = input("> ").strip().lower()
            if k == "f":
                sim.detection(True, random.uniform(3.5, 6.0), random.uniform(0.85, 0.99), random.uniform(70, 95))
            elif k == "d":
                sim.detection(True, random.uniform(6.0, 9.0), random.uniform(0.6, 0.9), random.uniform(60, 90))
            elif k == "j":
                sim.detection(False, random.uniform(2.2, 3.5), random.uniform(0.05, 0.6), random.uniform(1, 12))
            elif k == "c":
                sim.cancel()
            elif k == "o":
                sim.offline = not sim.offline
                print("  -> Đai", "MẤT KẾT NỐI" if sim.offline else "kết nối lại")
            elif k == "q":
                break
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()

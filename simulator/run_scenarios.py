"""Tự động chạy 3 kịch bản demo trong tài liệu qua MQTT thật (cần broker + server đang chạy).

Chạy:  python -m simulator.run_scenarios          (mất khoảng 45 giây)
Dùng để kiểm tra toàn hệ thống trước buổi bảo vệ, khi chưa có phần cứng/camera.
"""

from __future__ import annotations

import json
import threading
import time

import requests

from common import protocol as P
from common import settings as S
from simulator.vision_sim import fake_snapshot

BELT, CAM = "belt-test", "cam-test"


class Harness:
    def __init__(self):
        self.posture = P.STANDING
        self.cmds: list[str] = []
        self.state: dict = {}
        self.c = S.mqtt_client(f"scenario-{int(time.time())}")
        self.c.on_connect = self._on_connect
        self.c.on_message = self._on_msg
        self.connected = threading.Event()
        self.c.connect_async(S.MQTT_HOST, S.MQTT_PORT)
        self.c.loop_start()
        if not self.connected.wait(5):
            raise SystemExit("Không kết nối được MQTT broker. Đã chạy Mosquitto chưa?")
        threading.Thread(target=self._pump, daemon=True).start()

    def _on_connect(self, c, u, f, rc, p):
        c.subscribe(
            [(P.BELT_CMD.format(belt_id=BELT), 1), (P.SERVER_STATE, 0), (P.VISION_SNAPSHOT_REQ.format(cam_id=CAM), 1)]
        )
        self.connected.set()

    def _on_msg(self, c, u, m):
        if m.topic == P.SERVER_STATE:
            self.state = json.loads(m.payload)
        elif m.topic.endswith("/cmd"):
            self.cmds.append(json.loads(m.payload)["cmd"])
        elif m.topic.endswith("/request"):
            c.publish(P.VISION_SNAPSHOT.format(cam_id=CAM), fake_snapshot(self.posture), qos=1)

    def _pump(self):
        while True:
            self.c.publish(
                P.VISION_POSTURE.format(cam_id=CAM), json.dumps({"posture": self.posture, "confidence": 0.9})
            )
            self.c.publish(P.BELT_STATUS.format(belt_id=BELT), json.dumps({"rssi": -55, "state": "SIM"}))
            time.sleep(0.3)

    def impact(self):
        self.c.publish(
            P.BELT_EVENT.format(belt_id=BELT), json.dumps({"type": "impact", "score": 0.95, "peak_g": 5.2}), qos=1
        )

    def cancel(self):
        self.c.publish(P.BELT_EVENT.format(belt_id=BELT), json.dumps({"type": "cancel"}), qos=1)

    def wait_decision(self, after: float, timeout: float):
        end = time.time() + timeout
        while time.time() < end:
            d = (self.state or {}).get("last_decision")
            if d and d["t"] > after:
                return d
            time.sleep(0.2)
        return None


def main() -> None:
    url = f"http://localhost:{S.DASHBOARD_PORT}"
    requests.post(url + "/api/reset", timeout=5)
    h = Harness()
    time.sleep(2)
    results = []

    def check(name, ok, detail):
        results.append(ok)
        print(f"{'✅ PASS' if ok else '❌ FAIL'}  {name}: {detail}", flush=True)

    print("\n=== Tình huống 1: Rơi thiết bị, người vẫn đứng ===")
    h.posture, h.cmds = P.STANDING, []
    t0 = time.time()
    h.impact()
    d = h.wait_decision(t0, 10)
    check(
        "Loại trừ báo động giả",
        bool(d and d["result"] == "IGNORED" and "dismiss" in h.cmds),
        d["message"] if d else "không có quyết định",
    )

    print("\n=== Tình huống 2: Ngã nhẹ, bấm nút hủy ở giây thứ 5 ===")
    time.sleep(2)
    h.cmds = []
    t0 = time.time()
    h.impact()
    time.sleep(1)
    h.posture = P.SITTING
    time.sleep(4)
    h.cancel()
    d = h.wait_decision(t0, 5)
    time.sleep(2)
    check(
        "Hủy báo động",
        bool(d and d["result"] == "CANCELLED" and h.state.get("state") == "IDLE"),
        d["message"] if d else "không có quyết định",
    )

    print("\n=== Tình huống 3: Ngã thật, nằm bất động (đợi hết 15 giây) ===")
    time.sleep(2)
    h.posture, h.cmds = P.STANDING, []
    t0 = time.time()
    h.impact()
    time.sleep(1)
    h.posture = P.LYING
    d = h.wait_decision(t0, S.env_float("COUNTDOWN_S", 15) + 8)
    elapsed = (d["t"] - t0) if d else 0
    check(
        "Kích hoạt SOS",
        bool(d and d["result"] == "SOS" and "sos" in h.cmds),
        (d["message"] + f"  (sau {elapsed:.1f}s)") if d else "không có quyết định",
    )
    time.sleep(4)
    snap = requests.get(url + "/snapshot.jpg", timeout=5)
    check("Ảnh hiện trường", snap.ok and snap.content[:2] == b"\xff\xd8", f"{len(snap.content)} bytes JPEG")
    requests.post(url + "/api/reset", timeout=5)

    print(f"\nKết quả: {sum(results)}/{len(results)} đạt")
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    main()

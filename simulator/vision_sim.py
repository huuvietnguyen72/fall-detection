"""Giả lập camera (khi không muốn bật webcam). Gửi tư thế qua MQTT và trả ảnh giả khi server yêu cầu.

Chạy:  python -m simulator.vision_sim
Gõ phím rồi Enter:  s = đứng   i = ngồi   b = cúi   l = nằm   n = không thấy người   x = tắt camera   q = thoát
"""

from __future__ import annotations

import argparse
import json
import threading
import time

import cv2
import numpy as np

from common import protocol as P
from common import settings as S

KEYS = {"s": P.STANDING, "i": P.SITTING, "b": P.BENDING, "l": P.LYING, "n": P.NO_PERSON}


def fake_snapshot(posture: str) -> bytes:
    img = np.full((360, 640, 3), 40, np.uint8)
    cv2.putText(img, "SIMULATED CAMERA", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (200, 200, 200), 2)
    cv2.putText(
        img,
        f"Posture: {posture}",
        (20, 100),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (60, 60, 240) if posture == P.LYING else (80, 200, 80),
        3,
    )
    cv2.putText(img, time.strftime("%H:%M:%S %d/%m/%Y"), (20, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)
    if posture == P.LYING:
        cv2.line(img, (200, 260), (480, 270), (255, 255, 255), 6)
        cv2.circle(img, (180, 258), 18, (255, 255, 255), -1)
    else:
        cv2.line(img, (320, 160), (320, 280), (255, 255, 255), 6)
        cv2.circle(img, (320, 140), 18, (255, 255, 255), -1)
    return cv2.imencode(".jpg", img)[1].tobytes()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam-id", default=S.CAM_ID)
    ap.add_argument("--posture", default=P.STANDING)
    args = ap.parse_args()
    state = {"posture": args.posture, "on": True}
    client = S.mqtt_client(f"vision-sim-{int(time.time())}")
    client.on_connect = lambda c, u, f, rc, p: c.subscribe(P.VISION_SNAPSHOT_REQ.format(cam_id=args.cam_id), qos=1)

    def on_msg(c, u, m):
        if state["on"]:
            c.publish(P.VISION_SNAPSHOT.format(cam_id=args.cam_id), fake_snapshot(state["posture"]), qos=1)

    client.on_message = on_msg
    client.connect_async(S.MQTT_HOST, S.MQTT_PORT)
    client.loop_start()

    def pump():
        while True:
            if state["on"]:
                client.publish(
                    P.VISION_POSTURE.format(cam_id=args.cam_id),
                    json.dumps({"posture": state["posture"], "confidence": 0.9, "ts": time.time()}),
                )
            time.sleep(0.5)

    threading.Thread(target=pump, daemon=True).start()
    print(__doc__.split("Gõ phím rồi Enter:")[1])
    try:
        while True:
            k = input(f"[{state['posture'] if state['on'] else 'OFF'}] > ").strip().lower()
            if k in KEYS:
                state["posture"], state["on"] = KEYS[k], True
            elif k == "x":
                state["on"] = not state["on"]
            elif k == "q":
                break
    except (KeyboardInterrupt, EOFError):
        pass


if __name__ == "__main__":
    main()

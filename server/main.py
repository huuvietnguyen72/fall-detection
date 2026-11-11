"""Server trung tâm ("Bộ não"): MQTT <-> Decision Fusion <-> Telegram + Dashboard web.

Chạy:  python -m server.main          Dashboard: http://localhost:8088
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from collections import deque
from pathlib import Path

from flask import Flask, Response, jsonify, send_from_directory

from common import protocol as P
from common import settings as S
from server.discovery import HOSTNAME, Advertiser
from server.fusion import FusionConfig, FusionEngine
from server.telegram import TelegramNotifier

log = logging.getLogger("server")

RED, YELLOW, GREEN, CYAN, RESET = "\033[91m", "\033[93m", "\033[92m", "\033[96m", "\033[0m"
_COLOR = {"SOS": RED, "WARN": YELLOW, "IGNORED": GREEN, "CANCELLED": GREEN, "RESOLVED": CYAN}
SOS_TEXT = "🚨 CẢNH BÁO: Phát hiện người cao tuổi bị ngã tại phòng, không có phản hồi!"
HISTORY_S = 120  # số giây lịch sử gia tốc / góc thân hiển thị trên dashboard


def num(value, default: float = 0.0) -> float:
    """Số từ payload MQTT (có thể thiếu / null / chuỗi) -> float an toàn."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class FallServer:
    def __init__(self, cfg: FusionConfig):
        self.engine = FusionEngine(cfg)
        self.lock = threading.RLock()
        self.mqtt_ok = False
        self.belts: set[str] = {S.BELT_ID}
        self.cams: set[str] = {S.CAM_ID}
        self.events: deque[dict] = deque(maxlen=60)
        self.belt_status: dict = {}
        self.belt_history: deque[list] = deque(maxlen=HISTORY_S)  # [t, acc_max_g, tilt]
        self.detections: deque[dict] = deque(maxlen=12)
        self.camera: dict = {}
        self.preview: bytes | None = None
        self.preview_t = 0.0
        self.preview_cond = threading.Condition()
        self.snapshot: bytes | None = None
        self.snapshot_t = 0.0
        self.snapshot_event = threading.Event()
        self.telegram = TelegramNotifier(S.TELEGRAM_BOT_TOKEN, S.TELEGRAM_CHAT_ID, S.LOG_DIR)
        self.advertiser = Advertiser(S.MQTT_PORT)
        self.mqtt = S.mqtt_client(f"fall-server-{int(time.time())}")
        self.mqtt.on_connect = self._on_connect
        self.mqtt.on_message = self._on_message
        self.mqtt.on_disconnect = self._on_disconnect

    # ------------------------------------------------------------ MQTT
    def start(self) -> None:
        self.advertiser.start()
        self.mqtt.connect_async(S.MQTT_HOST, S.MQTT_PORT, keepalive=30)
        self.mqtt.loop_start()
        threading.Thread(target=self._ticker, daemon=True).start()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.mqtt_ok = True
        log.info("Đã kết nối MQTT %s:%s", S.MQTT_HOST, S.MQTT_PORT)
        client.subscribe(
            [
                (P.BELT_STATUS.format(belt_id="+"), 0),
                (P.BELT_EVENT.format(belt_id="+"), 1),
                (P.VISION_POSTURE.format(cam_id="+"), 0),
                (P.VISION_PREVIEW.format(cam_id="+"), 0),
                (P.VISION_SNAPSHOT.format(cam_id="+"), 0),
            ]
        )

    def _on_disconnect(self, *args):
        self.mqtt_ok = False
        log.warning("Mất kết nối MQTT, đang thử lại...")

    def _on_message(self, client, userdata, msg):
        parts = msg.topic.split("/")
        now = time.time()
        if parts[-1] == "preview":
            with self.preview_cond:
                self.preview, self.preview_t = bytes(msg.payload), now
                self.preview_cond.notify_all()
            return
        if parts[-1] == "snapshot":
            self.snapshot, self.snapshot_t = bytes(msg.payload), now
            self.snapshot_event.set()
            return
        try:
            data = json.loads(msg.payload or b"{}")
            if not isinstance(data, dict):
                raise ValueError("không phải object JSON")
            with self.lock:
                if parts[1] == "belt" and len(parts) >= 4:
                    self._on_belt(parts[2], parts[3], data, now)
                elif parts[1] == "vision" and len(parts) >= 3:
                    self._on_vision(parts[2], data, now)
        except Exception:  # một bản tin lỗi không được làm chết luồng MQTT
            log.exception("Bỏ qua bản tin lỗi trên %s: %.200r", msg.topic, msg.payload)

    def _on_belt(self, belt_id: str, kind: str, data: dict, now: float) -> None:
        self.belts.add(belt_id)
        if kind == "status":
            self.belt_status = {**data, "id": belt_id}
            if "acc_max_g" in data:
                self.belt_history.append([round(now, 1), data.get("acc_max_g"), data.get("tilt")])
            self._handle(self.engine.on_belt_status(now))
            return
        etype = data.get("type")
        if etype == "detection":
            self.detections.appendleft({**data, "t": now})
            verdict = "TÉ NGÃ" if data.get("fall") else "bỏ qua"
            self._log_event(
                "detect",
                f"Đai: va chạm {num(data.get('peak_g')):.1f}g · AI {num(data.get('ai')):.2f} · "
                f"nghiêng +{num(data.get('tilt')):.0f}° → {verdict}",
            )
            self._handle(self.engine.on_belt_status(now))
        elif etype == "impact":
            score = num(data.get("score"), 1.0)
            sim = " (giả lập)" if data.get("simulated") else ""
            self._log_event("impact", f"Đai {belt_id}: CẢNH BÁO TÉ NGÃ{sim} — bắt đầu đếm ngược", result="WARN")
            print(f"{YELLOW}[BELT] Fall Warning  score={score:.2f} peak_g={data.get('peak_g')}{RESET}", flush=True)
            self._handle(self.engine.on_belt_impact(now, score, data.get("peak_g")))
        elif etype == "cancel":
            self._log_event("cancel", f"Đai {belt_id}: người dùng bấm nút hủy")
            self._handle(self.engine.on_belt_cancel(now))

    def _on_vision(self, cam_id: str, data: dict, now: float) -> None:
        self.cams.add(cam_id)
        posture = data.get("posture")
        if posture not in P.POSTURES:
            posture = P.UNKNOWN
        prev = self.engine.effective_posture(now)
        self.camera = {"id": cam_id, "fps": data.get("fps"), "backend": data.get("backend"), "seen": now}
        self._handle(self.engine.on_posture(now, posture, num(data.get("confidence"))))
        if posture != prev:
            self._log_event("posture", f"Camera: {prev} → {posture}")

    def _ticker(self) -> None:
        last_pub = 0.0
        while True:
            now = time.time()
            try:
                with self.lock:
                    self._handle(self.engine.tick(now))
                    if now - last_pub >= 0.5 and self.mqtt_ok:
                        self.mqtt.publish(P.SERVER_STATE, json.dumps(self.engine.snapshot(now)), qos=0, retain=True)
                        last_pub = now
            except Exception:  # đồng hồ đếm ngược phải luôn chạy
                log.exception("Lỗi trong vòng xử lý chính")
            time.sleep(0.1)

    # ------------------------------------------------------------ actions
    def _handle(self, actions) -> None:
        for a in actions:
            if a.kind == "belt_cmd":
                for belt_id in self.belts:
                    self.mqtt.publish(P.BELT_CMD.format(belt_id=belt_id), json.dumps(a.data), qos=1)
            elif a.kind == "decision":
                d = a.data
                print(f"{_COLOR.get(d['result'], '')}[FUSION] {d['message']}{RESET}", flush=True)
                self._log_event("decision", d["message"], result=d["result"])
            elif a.kind == "sos":
                threading.Thread(target=self._send_sos, args=(a.data,), daemon=True).start()
            elif a.kind == "warn":
                threading.Thread(target=self._send_warn, args=(a.data,), daemon=True).start()
            elif a.kind == "resolved":
                by = "người dùng bấm nút trên đai" if a.data.get("by") == "belt_button" else "xác nhận trên dashboard"
                text = f"✅ Đã hủy cảnh báo ({by}) lúc {time.strftime('%H:%M:%S')}."
                threading.Thread(target=self.telegram.send, args=(text,), daemon=True).start()

    def request_snapshot(self, timeout: float = 2.5) -> bytes | None:
        self.snapshot_event.clear()
        for cam in self.cams:
            self.mqtt.publish(P.VISION_SNAPSHOT_REQ.format(cam_id=cam), "{}", qos=1)
        if self.snapshot_event.wait(timeout):
            return self.snapshot
        log.warning("Camera không trả ảnh trong %.1fs", timeout)
        return self.snapshot if time.time() - self.snapshot_t < 30 else None

    def _send_sos(self, info: dict) -> None:
        photo = self.request_snapshot()
        reason = {
            "fusion": "Đai lưng phát hiện té ngã + camera xác nhận nằm trên sàn",
            "belt_only": "Đai lưng phát hiện té ngã (camera không quan sát được)",
            "vision_only": "Camera thấy nằm bất động lâu (đai lưng mất kết nối)",
        }.get(info.get("reason"), info.get("reason"))
        impact = info.get("impact") or {}
        lines = [SOS_TEXT, "", f"⏰ Thời gian: {time.strftime('%H:%M:%S %d/%m/%Y')}", f"📌 Căn cứ: {reason}"]
        if impact.get("peak_g"):
            lines.append(f"📈 Gia tốc đỉnh: {impact['peak_g']} g · AI: {impact.get('score', 0):.0%}")
        ok = self.telegram.send("\n".join(lines), photo)
        self._log_event("telegram", "Đã gửi SOS qua Telegram" if ok else "GỬI SOS THẤT BẠI", result="SOS")

    def _send_warn(self, info: dict) -> None:
        photo = self.request_snapshot()
        text = (
            "⚠️ Cảnh báo mức thấp: đai lưng phát hiện té ngã nhưng camera không xác nhận được "
            f"(camera: {info.get('posture')}). Vui lòng kiểm tra.\n⏰ {time.strftime('%H:%M:%S %d/%m/%Y')}"
        )
        self.telegram.send(text, photo)

    # ------------------------------------------------------------ view
    def _log_event(self, kind: str, text: str, **extra) -> None:
        self.events.appendleft({"t": time.time(), "kind": kind, "text": text, **extra})

    def state(self) -> dict:
        now = time.time()
        with self.lock:
            fusion = self.engine.snapshot(now)
            cam_online = fusion["posture"] != P.UNKNOWN
            return {
                "now": now,
                "fusion": fusion,
                "belt": {
                    "online": fusion["belt_online"],
                    "last_seen_ago": fusion["belt_last_seen_ago"],
                    "status": self.belt_status,
                    "history": list(self.belt_history),
                    "detections": list(self.detections),
                },
                "camera": {
                    "online": cam_online,
                    "posture": fusion["posture"],
                    "confidence": fusion["posture_confidence"],
                    "for_s": fusion["posture_for_s"],
                    **self.camera,
                    "preview_t": self.preview_t if now - self.preview_t < 5 else None,
                },
                "snapshot_t": self.snapshot_t or None,
                "events": list(self.events)[:25],
                "system": {
                    "mqtt": self.mqtt_ok,
                    "telegram": self.telegram.enabled,
                    "ips": self.advertiser.ips,
                    "hostname": f"{HOSTNAME}.local",
                    "mqtt_port": S.MQTT_PORT,
                    "countdown_s": self.engine.cfg.countdown_s,
                },
            }

    def reset(self) -> None:
        with self.lock:
            self._log_event("reset", "Reset từ dashboard")
            self._handle(self.engine.reset(time.time()))


def create_app(server: FallServer) -> Flask:
    static = Path(__file__).parent / "static"
    app = Flask(__name__, static_folder=str(static))

    def jpeg(data: bytes | None) -> Response:
        if not data:
            return Response(status=404)
        return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/")
    def index():
        return send_from_directory(static, "index.html")

    @app.get("/api/state")
    def api_state():
        return jsonify(server.state())

    @app.get("/events")
    def events():
        def stream():
            while True:
                yield f"data: {json.dumps(server.state())}\n\n"
                time.sleep(0.5)

        return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/reset")
    def api_reset():
        server.reset()
        return jsonify(ok=True)

    @app.post("/api/snapshot")
    def api_snapshot():
        return jsonify(ok=server.request_snapshot() is not None)

    @app.get("/snapshot.jpg")
    def snapshot():
        return jpeg(server.snapshot)

    @app.get("/preview.jpg")
    def preview():
        return jpeg(server.preview)

    @app.get("/stream.mjpg")
    def stream_mjpg():
        """Luồng MJPEG: trình duyệt hiển thị như video, mỗi ảnh preview mới từ camera đẩy ngay xuống."""

        def frames():
            last_t = 0.0
            while True:
                with server.preview_cond:
                    if not server.preview_cond.wait_for(lambda t=last_t: server.preview_t != t, timeout=5):
                        return  # camera ngừng gửi -> đóng luồng; dashboard mở lại khi có hình
                    data, last_t = server.preview, server.preview_t
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(data)).encode()
                    + b"\r\n\r\n"
                    + data
                    + b"\r\n"
                )

        return Response(
            frames(), mimetype="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store"}
        )

    @app.post("/api/test-telegram")
    def test_telegram():
        ok = server.telegram.send(f"🔔 Tin nhắn thử từ hệ thống giám sát té ngã ({time.strftime('%H:%M:%S')})")
        return jsonify(ok=ok, enabled=server.telegram.enabled)

    return app


def main() -> None:
    ap = argparse.ArgumentParser(description="Server Decision Fusion")
    ap.add_argument("--countdown", type=float, default=S.env_float("COUNTDOWN_S", 15))
    ap.add_argument("--no-vision-policy", choices=["warn", "sos", "ignore"], default=S.env("NO_VISION_POLICY", "warn"))
    ap.add_argument("--port", type=int, default=S.DASHBOARD_PORT)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    cfg = FusionConfig(
        countdown_s=args.countdown,
        no_vision_policy=args.no_vision_policy,
        standing_confirm_s=S.env_float("STANDING_CONFIRM_S", 3),
        vision_only_lying_s=S.env_float("VISION_ONLY_LYING_S", 20),
        min_impact_score=S.env_float("MIN_IMPACT_SCORE", 0.5),
    )
    server = FallServer(cfg)
    server.start()
    log.info("Dashboard: http://localhost:%d", args.port)
    try:
        create_app(server).run(host="0.0.0.0", port=args.port, threaded=True, debug=False, use_reloader=False)
    finally:
        server.advertiser.stop()


if __name__ == "__main__":
    main()

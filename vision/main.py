"""Vision Node: đọc camera -> nhận diện khung xương -> phân loại tư thế -> gửi MQTT.

Ví dụ:
  python -m vision.main                               # webcam 0, MediaPipe Pose, có cửa sổ xem trước
  python -m vision.main --backend yolo        # tùy chọn: cần cài thêm ultralytics
  python -m vision.main --source http://192.168.1.5:8080/video   # điện thoại (IP Webcam)
  python -m vision.main --source demo.mp4 --no-show
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time

import cv2

from common import protocol as P
from common import settings as S
from vision.backends import SKELETON, create_backend
from vision.posture import PostureParams, PostureSmoother, classify

COLORS = {  # BGR
    P.STANDING: (80, 200, 80),
    P.SITTING: (200, 180, 60),
    P.BENDING: (60, 200, 230),
    P.LYING: (60, 60, 240),
    P.NO_PERSON: (160, 160, 160),
}


def draw(frame, kps, posture, conf, dbg, fps, min_score):
    if kps:
        pts = {k: (int(v[0]), int(v[1])) for k, v in kps.items() if v[2] >= min_score}
        for a, b in SKELETON:
            if a in pts and b in pts:
                cv2.line(frame, pts[a], pts[b], (255, 255, 255), 2)
        for p in pts.values():
            cv2.circle(frame, p, 4, (0, 220, 255), -1)
    color = COLORS.get(posture, (200, 200, 200))
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 42), (0, 0, 0), -1)
    text = f"{posture}  {conf * 100:.0f}%   {' '.join(f'{k}={v}' for k, v in dbg.items())}   {fps:.0f} FPS"
    cv2.putText(frame, text, (10, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2, cv2.LINE_AA)
    cv2.putText(
        frame,
        time.strftime("%H:%M:%S %d/%m/%Y"),
        (10, frame.shape[0] - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return frame


def open_source(src: str, wait_s: float = 60):
    cap = cv2.VideoCapture(int(src) if src.isdigit() else src)
    if not cap.isOpened() and src.isdigit() and sys.platform == "darwin":
        # Lần đầu macOS hiện hộp thoại xin quyền Camera: chờ người dùng bấm Allow rồi thử lại
        print("Đang chờ quyền Camera: bấm Allow nếu macOS hỏi...", flush=True)
        deadline = time.time() + wait_s
        while not cap.isOpened() and time.time() < deadline:
            time.sleep(1)
            cap = cv2.VideoCapture(int(src))
    if not cap.isOpened() and src.startswith(("http", "rtsp")):
        # Camera mạng (app trên điện thoại) có thể chưa bật: chờ thay vì thoát ngay
        print("Chưa kết nối được camera mạng, đang thử lại (mở app camera trên điện thoại)...", flush=True)
        deadline = time.time() + wait_s * 5
        while not cap.isOpened() and time.time() < deadline:
            time.sleep(3)
            cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise SystemExit(
            f"Không mở được camera '{mask_url(src)}'. Trên macOS: cấp quyền Camera cho Terminal "
            "(System Settings > Privacy & Security > Camera) rồi chạy lại."
        )
    return cap


class LatestFrameReader:
    """Đọc camera trực tiếp ở luồng riêng, chỉ giữ khung hình MỚI NHẤT.

    Camera mạng (iPhone, IP cam) phát ~30 FPS trong khi nhận diện chỉ ~13 FPS: đọc tuần tự thì
    khung hình dồn trong bộ đệm và hình trễ dần so với thực tế. Ở đây khung cũ bị bỏ qua.
    """

    def __init__(self, cap, src: str):
        self._cap, self._src = cap, src
        self._cond = threading.Condition()
        self._frame = None
        self._seq = 0
        self._read_seq = 0
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        fails = 0
        while True:
            ok, frame = self._cap.read()
            if not ok:
                fails += 1
                if fails == 25 and not self._src.isdigit():  # ~5 s mất hình: mở lại camera mạng
                    print("Mất hình từ camera mạng, đang kết nối lại...", flush=True)
                    self._cap.release()
                    self._cap = cv2.VideoCapture(self._src)
                    fails = 0
                time.sleep(0.2)
                continue
            fails = 0
            with self._cond:
                self._frame, self._seq = frame, self._seq + 1
                self._cond.notify_all()

    def read(self, timeout: float = 2.0):
        with self._cond:
            if not self._cond.wait_for(lambda: self._seq != self._read_seq, timeout):
                return False, None
            self._read_seq = self._seq
            return True, self._frame

    def set(self, *args):  # tương thích cv2.VideoCapture (chỉ dùng cho file video)
        return False


def mask_url(src: str) -> str:
    """Ẩn mật khẩu trong URL camera trước khi in ra log: http://user:pass@host -> http://user:***@host."""
    return re.sub(r"(//[^:/@]+):[^@/]+@", r"\1:***@", src)


def is_live(src: str) -> bool:
    return src.isdigit() or src.startswith(("http", "rtsp"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Vision Node – phát hiện tư thế")
    ap.add_argument("--source", default=S.env("CAMERA_SOURCE", "0"), help="0 = webcam, hoặc URL/đường dẫn video")
    ap.add_argument("--backend", choices=["yolo", "mediapipe"], default=S.env("VISION_BACKEND", "mediapipe"))
    ap.add_argument("--model", default=S.env("YOLO_MODEL", "yolov8n-pose.pt"))
    ap.add_argument("--imgsz", type=int, default=480)
    ap.add_argument("--device", default=S.env("YOLO_DEVICE") or None, help="cpu | mps (Apple GPU)")
    ap.add_argument("--mp-variant", default="full", choices=["lite", "full", "heavy"])
    ap.add_argument("--cam-id", default=S.CAM_ID)
    ap.add_argument("--max-fps", type=float, default=15)
    ap.add_argument(
        "--preview-fps", type=float, default=S.env_float("PREVIEW_FPS", 12), help="số ảnh/giây gửi lên dashboard"
    )
    ap.add_argument("--preview-width", type=int, default=S.env_int("PREVIEW_WIDTH", 640))
    ap.add_argument("--no-show", action="store_true", help="không mở cửa sổ xem trước")
    ap.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=0)
    ap.add_argument("--loop", action="store_true", help="phát lại video từ đầu khi hết (để tập dượt)")
    args = ap.parse_args()

    backend = create_backend(
        args.backend, model=args.model, imgsz=args.imgsz, device=args.device, variant=args.mp_variant
    )
    params = PostureParams()
    smoother = PostureSmoother()
    print(f"Backend: {backend.name} | Nguồn: {mask_url(args.source)} | MQTT: {S.MQTT_HOST}:{S.MQTT_PORT}")

    snap_req = threading.Event()
    client = S.mqtt_client(f"vision-{args.cam_id}-{int(time.time())}")
    topic_posture = P.VISION_POSTURE.format(cam_id=args.cam_id)
    topic_snap = P.VISION_SNAPSHOT.format(cam_id=args.cam_id)
    topic_req = P.VISION_SNAPSHOT_REQ.format(cam_id=args.cam_id)
    topic_preview = P.VISION_PREVIEW.format(cam_id=args.cam_id)

    def on_connect(c, u, f, rc, props):
        print("Đã kết nối MQTT")
        c.subscribe(topic_req, qos=1)

    client.on_connect = on_connect
    client.on_message = lambda c, u, m: snap_req.set()
    client.connect_async(S.MQTT_HOST, S.MQTT_PORT, keepalive=30)
    client.loop_start()

    cap = open_source(args.source)
    if is_live(args.source):
        cap = LatestFrameReader(cap, args.source)
    preview_dt = 1.0 / args.preview_fps if args.preview_fps > 0 else float("inf")
    rot = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(args.rotate)
    last_pub, last_sent, last_preview, fps, t_prev = 0.0, None, 0.0, 0.0, time.time()
    min_dt = 1.0 / args.max_fps if args.max_fps > 0 else 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                if not is_live(args.source):
                    if not args.loop:
                        print("Hết video.")
                        break
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                time.sleep(0.2)
                continue
            if rot is not None:
                frame = cv2.rotate(frame, rot)
            now = time.time()
            kps = backend.detect(frame)
            raw, raw_conf, dbg = classify(kps, params)
            posture, conf = smoother.update(now, raw, raw_conf)

            if posture != last_sent or now - last_pub >= 0.5:
                client.publish(
                    topic_posture,
                    json.dumps(
                        {
                            "posture": posture,
                            "confidence": round(conf, 3),
                            "ts": now,
                            "fps": round(fps, 1),
                            "backend": backend.name,
                        }
                    ),
                )
                if posture != last_sent:
                    print(f"[VISION] {time.strftime('%H:%M:%S')} {posture} ({conf * 100:.0f}%) {dbg}", flush=True)
                last_sent, last_pub = posture, now

            dt = now - t_prev
            fps = 0.9 * fps + 0.1 * (1 / dt) if dt > 0 else fps
            t_prev = now
            annotated = draw(frame, kps, posture, conf, dbg, fps, params.min_score)

            # luồng xem trước cho dashboard (MJPEG); trừ hao 30% để nhịp khung hình lệch chút không bị bỏ nửa số ảnh
            if now - last_preview >= preview_dt * 0.7:
                last_preview = now
                h, w = annotated.shape[:2]
                pw = min(args.preview_width, w)
                small = cv2.resize(annotated, (pw, int(h * pw / w))) if pw != w else annotated
                client.publish(topic_preview, cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes())

            if snap_req.is_set():
                snap_req.clear()
                ok_jpg, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if ok_jpg:
                    client.publish(topic_snap, buf.tobytes(), qos=1)
                    print("[VISION] Đã gửi ảnh hiện trường")

            if not args.no_show:
                cv2.imshow(f"Vision Node ({backend.name}) - nhan q de thoat", annotated)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            spent = time.time() - now
            if spent < min_dt:
                time.sleep(min_dt - spent)
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        cv2.destroyAllWindows()
        client.loop_stop()


if __name__ == "__main__":
    main()

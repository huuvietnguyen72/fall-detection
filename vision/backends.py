"""Hai backend nhận diện khung xương, đổi qua lại bằng --backend yolo|mediapipe.

Cả hai trả về cùng định dạng: dict tên khớp -> (x_px, y_px, score), hoặc None nếu không thấy người.
"""

from __future__ import annotations

import time
import urllib.request
from pathlib import Path

import numpy as np

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"

# Chỉ số khớp trong từng bộ khung xương
COCO_IDX = {  # YOLO-Pose (17 điểm COCO)
    "nose": 0,
    "left_shoulder": 5,
    "right_shoulder": 6,
    "left_hip": 11,
    "right_hip": 12,
    "left_knee": 13,
    "right_knee": 14,
    "left_ankle": 15,
    "right_ankle": 16,
}
MP_IDX = {  # MediaPipe Pose (33 điểm)
    "nose": 0,
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_ankle": 27,
    "right_ankle": 28,
}

SKELETON = [
    ("left_shoulder", "right_shoulder"),
    ("left_hip", "right_hip"),
    ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"),
    ("left_hip", "left_knee"),
    ("left_knee", "left_ankle"),
    ("right_hip", "right_knee"),
    ("right_knee", "right_ankle"),
]


class YoloBackend:
    name = "yolo"

    def __init__(self, model: str = "yolov8n-pose.pt", imgsz: int = 480, device: str | None = None):
        from ultralytics import YOLO

        MODELS_DIR.mkdir(exist_ok=True)
        path = Path(model)
        if not path.exists():
            path = MODELS_DIR / Path(model).name
        if not path.exists():
            YOLO(Path(model).name)  # ultralytics tự tải trọng số về thư mục hiện tại
            downloaded = Path(Path(model).name)
            if downloaded.exists():
                downloaded.rename(path)
        self.model = YOLO(str(path))
        self.imgsz = imgsz
        self.device = device

    def detect(self, frame_bgr: np.ndarray):
        res = self.model(frame_bgr, imgsz=self.imgsz, verbose=False, device=self.device)[0]
        if res.keypoints is None or res.boxes is None or len(res.boxes) == 0:
            return None
        boxes = res.boxes.xyxy.cpu().numpy()
        areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
        i = int(np.argmax(areas))  # người lớn nhất trong khung hình
        xy = res.keypoints.xy[i].cpu().numpy()
        conf = res.keypoints.conf
        conf = conf[i].cpu().numpy() if conf is not None else np.ones(len(xy))
        return {name: (float(xy[j][0]), float(xy[j][1]), float(conf[j])) for name, j in COCO_IDX.items()}


class MediaPipeBackend:
    name = "mediapipe"
    URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_{v}/float16/latest/pose_landmarker_{v}.task"

    def __init__(self, variant: str = "full"):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        MODELS_DIR.mkdir(exist_ok=True)
        path = MODELS_DIR / f"pose_landmarker_{variant}.task"
        if not path.exists():
            print(f"Đang tải model MediaPipe ({variant})...")
            urllib.request.urlretrieve(self.URL.format(v=variant), path)
        self._mp = mp
        opts = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(path)),
            running_mode=vision.RunningMode.VIDEO,
            num_poses=1,
        )
        self.landmarker = vision.PoseLandmarker.create_from_options(opts)
        self._t0 = time.monotonic()
        self._last_ts = -1

    def detect(self, frame_bgr: np.ndarray):
        h, w = frame_bgr.shape[:2]
        rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        ts = int((time.monotonic() - self._t0) * 1000)
        ts = max(ts, self._last_ts + 1)  # timestamp phải tăng dần
        self._last_ts = ts
        res = self.landmarker.detect_for_video(image, ts)
        if not res.pose_landmarks:
            return None
        lm = res.pose_landmarks[0]
        out = {}
        for name, j in MP_IDX.items():
            p = lm[j]
            score = p.visibility if p.visibility is not None else 1.0
            out[name] = (float(p.x * w), float(p.y * h), float(score))
        return out


def create_backend(name: str, **kw):
    if name == "yolo":
        return YoloBackend(**{k: v for k, v in kw.items() if k in ("model", "imgsz", "device")})
    if name == "mediapipe":
        return MediaPipeBackend(**{k: v for k, v in kw.items() if k in ("variant",)})
    raise ValueError(f"Backend không hợp lệ: {name}")

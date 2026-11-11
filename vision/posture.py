"""Phân loại tư thế từ khung xương (dùng chung cho YOLO-Pose và MediaPipe).

Đầu vào: dict tên khớp -> (x_px, y_px, score) theo TỌA ĐỘ PIXEL (y hướng xuống).
Đầu ra: STANDING / SITTING / BENDING / LYING / NO_PERSON + độ tin cậy.

Luật hình học:
  - Góc thân (vai -> hông) so với phương thẳng đứng:  ~0° = thẳng,  ~90° = nằm ngang
  - Tỉ lệ khung bao rộng/cao của cơ thể
  - Góc đùi (hông -> gối) để phân biệt đứng / ngồi
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from common.protocol import BENDING, LYING, NO_PERSON, SITTING, STANDING

KEYPOINTS = (
    "nose",
    "left_shoulder",
    "right_shoulder",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)


@dataclass
class PostureParams:
    min_score: float = 0.3
    lying_torso_deg: float = 60.0  # thân nghiêng hơn mức này -> nằm
    lying_torso_soft_deg: float = 45.0  # nghiêng vừa + khung bao bè ngang -> nằm
    lying_aspect_soft: float = 1.2
    lying_aspect_hard: float = 1.8  # khung bao rộng gấp 1.8 lần cao -> nằm
    upright_torso_deg: float = 35.0  # thân thẳng hơn mức này -> đứng/ngồi
    sitting_thigh_deg: float = 55.0  # đùi nghiêng hơn mức này -> ngồi


def _mid(a, b):
    if a and b:
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return a or b


def _angle_from_vertical(p_top, p_bottom) -> float:
    dx = p_bottom[0] - p_top[0]
    dy = p_bottom[1] - p_top[1]
    return math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6))


def classify(kps: dict[str, tuple[float, float, float]] | None, params: PostureParams | None = None):
    """Trả về (posture, confidence, debug_dict)."""
    p = params or PostureParams()
    if not kps:
        return NO_PERSON, 0.0, {}
    vis = {k: (v[0], v[1]) for k, v in kps.items() if v[2] >= p.min_score}
    scores = [v[2] for v in kps.values() if v[2] >= p.min_score]
    if len(vis) < 3:
        return NO_PERSON, 0.0, {}
    conf = sum(scores) / len(scores)

    xs = [v[0] for v in vis.values()]
    ys = [v[1] for v in vis.values()]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    aspect = w / (h + 1e-6)

    shoulder = _mid(vis.get("left_shoulder"), vis.get("right_shoulder"))
    hip = _mid(vis.get("left_hip"), vis.get("right_hip"))
    dbg = {"aspect": round(aspect, 2)}

    if not (shoulder and hip):
        # Không đủ khớp thân: chỉ dựa vào khung bao
        if aspect >= p.lying_aspect_hard:
            return LYING, conf * 0.6, dbg
        return STANDING, conf * 0.4, dbg

    torso = _angle_from_vertical(shoulder, hip)
    dbg["torso_deg"] = round(torso, 1)

    if torso >= p.lying_torso_deg or aspect >= p.lying_aspect_hard:
        return LYING, conf, dbg
    if torso >= p.lying_torso_soft_deg and aspect >= p.lying_aspect_soft:
        return LYING, conf * 0.85, dbg

    if torso <= p.upright_torso_deg:
        knee = _mid(vis.get("left_knee"), vis.get("right_knee"))
        if knee:
            thigh = _angle_from_vertical(hip, knee)
            dbg["thigh_deg"] = round(thigh, 1)
            if thigh >= p.sitting_thigh_deg:
                return SITTING, conf, dbg
        return STANDING, conf, dbg

    return BENDING, conf, dbg


class PostureSmoother:
    """Chống nhiễu bằng bỏ phiếu theo cửa sổ thời gian.

    Đổi sang tư thế P khi, trong `hold(P)` giây gần nhất, P chiếm >= `majority` số khung CÓ thấy người.
    Khung "không thấy người" không bỏ phiếu: người nằm trên sàn thường bị mất dấu vài khung xen kẽ
    (đánh giá trên URFD: ~30% khung nằm), nếu để chúng cắt chuỗi thì tư thế NẰM không bao giờ được
    xác nhận và hệ thống giữ nguyên ĐỨNG — fusion sẽ hiểu nhầm thành "đã đứng dậy".
    Chỉ chuyển sang NO_PERSON khi mọi khung trong `no_person_hold_s` giây đều không thấy người.
    """

    def __init__(
        self,
        hold_s: float = 0.6,
        lying_hold_s: float = 1.0,
        no_person_hold_s: float = 1.5,
        majority: float = 0.6,
    ):
        self.hold = {LYING: lying_hold_s, NO_PERSON: no_person_hold_s}
        self.default_hold = hold_s
        self.majority = majority
        self.current: str | None = None
        self.confidence = 0.0
        self._t0 = 0.0
        self._hist: deque[tuple[float, str]] = deque()
        self._keep_s = max(hold_s, lying_hold_s, no_person_hold_s)

    def update(self, t: float, posture: str, confidence: float) -> tuple[str, float]:
        self._hist.append((t, posture))
        while self._hist and self._hist[0][0] < t - self._keep_s:
            self._hist.popleft()
        if self.current is None:
            self.current, self.confidence, self._t0 = posture, confidence, t
            return self.current, self.confidence
        if posture == self.current:
            self.confidence = 0.7 * self.confidence + 0.3 * confidence
            return self.current, self.confidence

        hold = self.hold.get(posture, self.default_hold)
        if t - self._t0 < hold:  # chưa đủ dữ liệu cho cả cửa sổ
            return self.current, self.confidence
        window = [p for ti, p in self._hist if ti > t - hold]
        if posture == NO_PERSON:
            switch = all(p == NO_PERSON for p in window)
        else:
            seen = [p for p in window if p != NO_PERSON]
            switch = len(seen) >= 2 and seen.count(posture) >= self.majority * len(seen)
        if switch:
            self.current, self.confidence = posture, confidence
        return self.current, self.confidence

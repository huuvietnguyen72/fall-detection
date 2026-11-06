"""Decision Fusion: máy trạng thái hợp nhất quyết định từ đai lưng + camera.

Module này KHÔNG phụ thuộc MQTT/mạng: mọi hàm nhận thời gian `t` (giây) từ
bên ngoài và trả về danh sách Action. Nhờ vậy có thể kiểm thử chính xác
từng kịch bản (xem tests/test_fusion.py).

Luật chính:
  1. Đai báo va chạm  -> COUNTDOWN (mặc định 15 giây).
  2. Trong COUNTDOWN:
       - Người dùng bấm nút hủy                      -> CANCELLED
       - Camera thấy người ĐỨNG liên tục >= 3 giây   -> IGNORED (rơi thiết bị)
  3. Hết COUNTDOWN:
       - Camera xác nhận NẰM                         -> SOS
       - Camera không thấy / mất tín hiệu            -> theo no_vision_policy
       - Tư thế khác (ngồi, cúi...)                  -> IGNORED
  4. Chịu lỗi: đai mất kết nối nhưng camera thấy NẰM liên tục
     >= vision_only_lying_s                          -> SOS (chỉ dựa vào camera)
  5. Trong SOS: chờ reset từ dashboard hoặc người dùng bấm nút trên đai.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from common.protocol import LYING, NO_PERSON, STANDING, UNKNOWN

IDLE = "IDLE"
COUNTDOWN = "COUNTDOWN"
SOS = "SOS"

_CAMERA_LABEL = {
    "STANDING": "Standing",
    "SITTING": "Sitting",
    "BENDING": "Bending",
    "LYING": "Lying",
    "NO_PERSON": "No person",
    "UNKNOWN": "No signal",
}


@dataclass
class FusionConfig:
    countdown_s: float = 15.0
    # Đứng liên tục bao lâu sau va chạm thì kết luận là báo động giả
    standing_confirm_s: float = 3.0
    # Dữ liệu camera cũ hơn mức này coi như mất tín hiệu
    vision_stale_s: float = 3.0
    # Không nhận được gì từ đai trong khoảng này coi như đai offline
    belt_offline_s: float = 10.0
    # Đai offline + camera thấy nằm liên tục bao lâu thì SOS
    vision_only_lying_s: float = 20.0
    # Hết đếm ngược mà camera không thấy người: "warn" | "sos" | "ignore"
    no_vision_policy: str = "warn"
    # Điểm tin cậy tối thiểu của TinyML để mở sự cố
    min_impact_score: float = 0.5
    # Những tư thế được coi là xác nhận té ngã
    confirm_postures: tuple[str, ...] = (LYING,)


@dataclass
class Action:
    kind: str  # "belt_cmd" | "sos" | "warn" | "resolved" | "decision"
    data: dict[str, Any] = field(default_factory=dict)


class FusionEngine:
    def __init__(self, config: FusionConfig | None = None):
        self.cfg = config or FusionConfig()
        self.state = IDLE
        self.impact_t: float | None = None
        self.deadline: float | None = None
        self.impact_info: dict[str, Any] = {}
        self.sos_reason: str | None = None
        self.last_belt_seen: float | None = None
        self.posture = UNKNOWN
        self.posture_conf = 0.0
        self.posture_since = 0.0
        self.posture_seen: float | None = None
        self.last_decision: dict[str, Any] | None = None

    # ------------------------------------------------------------ helpers
    def effective_posture(self, t: float) -> str:
        if self.posture_seen is None or t - self.posture_seen > self.cfg.vision_stale_s:
            return UNKNOWN
        return self.posture

    def belt_online(self, t: float) -> bool:
        return self.last_belt_seen is not None and t - self.last_belt_seen <= self.cfg.belt_offline_s

    def _decide(self, t: float, result: str, belt: str, text: str, **extra) -> Action:
        cam = _CAMERA_LABEL.get(self.effective_posture(t), self.effective_posture(t))
        decision = {
            "t": t,
            "result": result,
            "belt": belt,
            "camera": cam,
            "message": f"Belt: {belt} | Camera: {cam} -> System Action: {text}",
            **extra,
        }
        self.last_decision = decision
        return Action("decision", decision)

    def _to_idle(self) -> None:
        self.state = IDLE
        self.impact_t = None
        self.deadline = None
        self.impact_info = {}

    def _enter_sos(self, t: float, reason: str, belt_label: str) -> list[Action]:
        self.state = SOS
        self.sos_reason = reason
        posture = self.effective_posture(t)
        return [
            Action("belt_cmd", {"cmd": "sos"}),
            Action("sos", {"reason": reason, "posture": posture, "impact": dict(self.impact_info)}),
            self._decide(t, "SOS", belt_label, "SOS SENT (Fall Confirmed)", reason=reason),
        ]

    # ------------------------------------------------------------ inputs
    def on_belt_status(self, t: float) -> list[Action]:
        self.last_belt_seen = t
        return []

    def on_belt_impact(self, t: float, score: float = 1.0, peak_g: float | None = None) -> list[Action]:
        self.last_belt_seen = t
        if self.state != IDLE or score < self.cfg.min_impact_score:
            return []
        self.state = COUNTDOWN
        self.impact_t = t
        self.deadline = t + self.cfg.countdown_s
        self.impact_info = {"score": score, "peak_g": peak_g, "t": t}
        return []

    def on_belt_cancel(self, t: float) -> list[Action]:
        self.last_belt_seen = t
        if self.state == COUNTDOWN:
            self._to_idle()
            return [self._decide(t, "CANCELLED", "Fall Warning", "CANCELLED (User pressed cancel)")]
        if self.state == SOS:
            self._to_idle()
            self.sos_reason = None
            return [
                Action("belt_cmd", {"cmd": "reset"}),
                Action("resolved", {"by": "belt_button"}),
                self._decide(t, "RESOLVED", "Cancel pressed", "SOS RESOLVED (User is OK)"),
            ]
        return []

    def on_posture(self, t: float, posture: str, confidence: float = 1.0) -> list[Action]:
        if posture != self.posture or self.effective_posture(t) == UNKNOWN:
            self.posture_since = t
        self.posture = posture
        self.posture_conf = confidence
        self.posture_seen = t
        return []

    def reset(self, t: float) -> list[Action]:
        """Reset thủ công từ dashboard."""
        was = self.state
        self._to_idle()
        self.sos_reason = None
        if was == IDLE:
            return []
        return [Action("belt_cmd", {"cmd": "reset"}), Action("resolved", {"by": "dashboard"})]

    # ------------------------------------------------------------ clock
    def tick(self, t: float) -> list[Action]:
        posture = self.effective_posture(t)

        if self.state == COUNTDOWN:
            assert self.impact_t is not None and self.deadline is not None
            standing_for = t - max(self.posture_since, self.impact_t)
            if posture == STANDING and standing_for >= self.cfg.standing_confirm_s:
                self._to_idle()
                return [
                    Action("belt_cmd", {"cmd": "dismiss"}),
                    self._decide(t, "IGNORED", "Fall Warning", "IGNORED (False Alarm Dismissed)"),
                ]
            if t >= self.deadline:
                if posture in self.cfg.confirm_postures:
                    return self._enter_sos(t, "fusion", "Fall Warning")
                if posture in (UNKNOWN, NO_PERSON):
                    policy = self.cfg.no_vision_policy
                    if policy == "sos":
                        return self._enter_sos(t, "belt_only", "Fall Warning")
                    impact = dict(self.impact_info)
                    self._to_idle()
                    if policy == "warn":
                        return [
                            Action("belt_cmd", {"cmd": "dismiss"}),
                            Action("warn", {"reason": "camera_unconfirmed", "posture": posture, "impact": impact}),
                            self._decide(t, "WARN", "Fall Warning", "WARNING SENT (Camera cannot confirm)"),
                        ]
                    return [
                        Action("belt_cmd", {"cmd": "dismiss"}),
                        self._decide(t, "IGNORED", "Fall Warning", "IGNORED (Camera cannot confirm)"),
                    ]
                self._to_idle()
                return [
                    Action("belt_cmd", {"cmd": "dismiss"}),
                    self._decide(t, "IGNORED", "Fall Warning", "IGNORED (Not lying down)"),
                ]
            return []

        belt_lost_lying = (
            not self.belt_online(t) and posture == LYING and t - self.posture_since >= self.cfg.vision_only_lying_s
        )
        if self.state == IDLE and belt_lost_lying:
            return self._enter_sos(t, "vision_only", "Offline")
        return []

    # ------------------------------------------------------------ view
    def snapshot(self, t: float) -> dict[str, Any]:
        remaining = None
        if self.state == COUNTDOWN and self.deadline is not None:
            remaining = max(0.0, self.deadline - t)
        return {
            "state": self.state,
            "remaining_s": remaining,
            "countdown_s": self.cfg.countdown_s,
            "sos_reason": self.sos_reason,
            "belt_online": self.belt_online(t),
            "belt_last_seen_ago": None if self.last_belt_seen is None else t - self.last_belt_seen,
            "posture": self.effective_posture(t),
            "posture_confidence": self.posture_conf,
            "posture_for_s": t - self.posture_since if self.posture_seen else None,
            "last_decision": self.last_decision,
        }

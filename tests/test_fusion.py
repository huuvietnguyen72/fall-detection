"""Kiểm thử Decision Fusion theo đúng 3 kịch bản demo trong tài liệu + các trường hợp biên."""

from common.protocol import LYING, NO_PERSON, SITTING, STANDING
from server.fusion import COUNTDOWN, IDLE, SOS, FusionConfig, FusionEngine


def kinds(actions):
    return [a.kind for a in actions]


def decision(actions):
    for a in actions:
        if a.kind == "decision":
            return a.data
    return None


def run(engine, start, end, posture=None, step=0.5):
    """Chạy đồng hồ từ start->end, camera gửi posture mỗi bước (nếu có). Trả về mọi action."""
    out = []
    t = start
    while t <= end + 1e-9:
        if posture is not None:
            engine.on_posture(t, posture, 0.9)
        engine.on_belt_status(t)
        out += engine.tick(t)
        t += step
    return out


def test_scenario1_device_dropped_person_standing_is_ignored():
    e = FusionEngine()
    run(e, 0, 5, STANDING)
    e.on_belt_impact(5.0, score=0.95, peak_g=6.0)
    assert e.state == COUNTDOWN
    actions = run(e, 5.5, 20, STANDING)
    d = decision(actions)
    assert d["result"] == "IGNORED"
    assert d["message"] == "Belt: Fall Warning | Camera: Standing -> System Action: IGNORED (False Alarm Dismissed)"
    assert {"cmd": "dismiss"} in [a.data for a in actions if a.kind == "belt_cmd"]
    assert "sos" not in kinds(actions)
    assert e.state == IDLE
    # Bỏ qua khoảng 3 giây sau va chạm, không phải đợi hết 15 giây
    assert d["t"] <= 5 + 3.5


def test_scenario2_user_cancels_during_countdown():
    e = FusionEngine()
    run(e, 0, 2, STANDING)
    e.on_belt_impact(2.0)
    run(e, 2.5, 7, SITTING)  # ngã xuống sofa
    actions = e.on_belt_cancel(7.0)  # bấm nút ở giây thứ 5
    assert decision(actions)["result"] == "CANCELLED"
    assert e.state == IDLE
    later = run(e, 7.5, 30, SITTING)
    assert "sos" not in kinds(later)


def test_scenario3_real_fall_triggers_sos_after_countdown():
    e = FusionEngine()
    run(e, 0, 2, STANDING)
    e.on_belt_impact(2.0, score=0.97)
    before = run(e, 2.5, 16.5, LYING)  # đang đếm ngược: chưa được gửi SOS
    assert "sos" not in kinds(before)
    actions = run(e, 17.0, 17.0, LYING)
    assert "sos" in kinds(actions)
    assert {"cmd": "sos"} in [a.data for a in actions if a.kind == "belt_cmd"]
    assert decision(actions)["result"] == "SOS"
    assert e.state == SOS
    # Không gửi SOS lặp lại
    assert "sos" not in kinds(run(e, 17.5, 60, LYING))


def test_camera_lag_during_real_fall_does_not_dismiss():
    """Camera còn báo ĐỨNG ~1.5s sau va chạm (độ trễ) rồi mới thấy NẰM -> vẫn SOS."""
    e = FusionEngine()
    run(e, 0, 2, STANDING)
    e.on_belt_impact(2.0)
    a1 = run(e, 2.5, 3.5, STANDING)
    a2 = run(e, 4.0, 17.5, LYING)
    assert "decision" not in kinds(a1)
    assert "sos" in kinds(a2)


def test_sitting_at_deadline_is_ignored():
    e = FusionEngine()
    e.on_belt_impact(0.0)
    actions = run(e, 0.5, 16, SITTING)
    assert decision(actions)["result"] == "IGNORED"
    assert "sos" not in kinds(actions)


def test_no_camera_default_policy_warns():
    e = FusionEngine()
    e.on_belt_impact(0.0)
    actions = run(e, 0.5, 16)  # camera không gửi gì
    assert "warn" in kinds(actions)
    assert "sos" not in kinds(actions)


def test_no_camera_sos_policy():
    e = FusionEngine(FusionConfig(no_vision_policy="sos"))
    e.on_belt_impact(0.0)
    actions = run(e, 0.5, 16, NO_PERSON)
    assert "sos" in kinds(actions)


def test_low_confidence_impact_is_ignored():
    e = FusionEngine()
    assert e.on_belt_impact(0.0, score=0.2) == []
    assert e.state == IDLE


def test_belt_offline_vision_only_sos():
    """Đai hỏng/mất kết nối: camera thấy nằm liên tục 20 giây -> SOS."""
    e = FusionEngine()
    actions = []
    t = 0.0
    while t <= 25:
        e.on_posture(t, LYING, 0.9)
        actions += e.tick(t)
        t += 0.5
    assert "sos" in kinds(actions)
    sos = [a for a in actions if a.kind == "sos"][0]
    assert sos.data["reason"] == "vision_only"


def test_belt_online_lying_without_impact_no_sos():
    """Đai vẫn online, không có va chạm (vd. nằm nghỉ trên sàn) -> không SOS."""
    e = FusionEngine()
    actions = run(e, 0, 60, LYING)
    assert "sos" not in kinds(actions)


def test_cancel_after_sos_resolves():
    e = FusionEngine()
    e.on_belt_impact(0.0)
    run(e, 0.5, 16, LYING)
    assert e.state == SOS
    actions = e.on_belt_cancel(20.0)
    assert "resolved" in kinds(actions)
    assert e.state == IDLE


def test_dashboard_reset():
    e = FusionEngine()
    e.on_belt_impact(0.0)
    run(e, 0.5, 16, LYING)
    actions = e.reset(20.0)
    assert e.state == IDLE
    assert {"cmd": "reset"} in [a.data for a in actions if a.kind == "belt_cmd"]


def test_snapshot_countdown_remaining():
    e = FusionEngine()
    e.on_belt_impact(10.0)
    snap = e.snapshot(14.0)
    assert snap["state"] == COUNTDOWN
    assert abs(snap["remaining_s"] - 11.0) < 1e-6

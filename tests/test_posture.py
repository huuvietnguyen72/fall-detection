from common.protocol import BENDING, LYING, NO_PERSON, SITTING, STANDING
from vision.posture import PostureSmoother, classify


def body(points, score=0.9):
    return {k: (x, y, score) for k, (x, y) in points.items()}


STAND = body(
    {
        "nose": (100, 20),
        "left_shoulder": (90, 60),
        "right_shoulder": (110, 60),
        "left_hip": (92, 150),
        "right_hip": (108, 150),
        "left_knee": (92, 220),
        "right_knee": (108, 220),
        "left_ankle": (92, 290),
        "right_ankle": (108, 290),
    }
)
SIT = body(
    {
        "nose": (100, 20),
        "left_shoulder": (90, 60),
        "right_shoulder": (110, 60),
        "left_hip": (92, 150),
        "right_hip": (108, 150),
        "left_knee": (162, 160),
        "right_knee": (178, 160),
        "left_ankle": (162, 230),
        "right_ankle": (178, 230),
    }
)
LIE = body(
    {
        "nose": (20, 300),
        "left_shoulder": (60, 290),
        "right_shoulder": (60, 310),
        "left_hip": (150, 292),
        "right_hip": (150, 308),
        "left_knee": (220, 292),
        "right_knee": (220, 308),
        "left_ankle": (290, 292),
        "right_ankle": (290, 308),
    }
)
BEND = body(
    {
        "nose": (40, 120),
        "left_shoulder": (60, 110),
        "right_shoulder": (62, 115),
        "left_hip": (110, 170),
        "right_hip": (112, 172),
        "left_knee": (110, 240),
        "right_knee": (112, 240),
        "left_ankle": (110, 310),
        "right_ankle": (112, 310),
    }
)


def test_standing():
    assert classify(STAND)[0] == STANDING


def test_sitting():
    assert classify(SIT)[0] == SITTING


def test_lying():
    assert classify(LIE)[0] == LYING


def test_bending():
    assert classify(BEND)[0] == BENDING


def test_no_person():
    assert classify(None)[0] == NO_PERSON
    assert classify(body({"nose": (1, 1)}, score=0.1))[0] == NO_PERSON


def test_smoother_requires_hold_time():
    s = PostureSmoother(hold_s=0.6, lying_hold_s=1.0)
    assert s.update(0.0, STANDING, 0.9)[0] == STANDING
    assert s.update(0.2, LYING, 0.9)[0] == STANDING  # nhiễu 1 khung -> chưa đổi
    assert s.update(0.8, LYING, 0.9)[0] == STANDING
    assert s.update(1.3, LYING, 0.9)[0] == LYING  # nằm liên tục >= 1s -> đổi


def run(s, seq, fps=15, t0=0.0):
    """Đưa chuỗi tư thế vào bộ làm mượt ở `fps` khung/giây, trả về tư thế cuối."""
    out = None
    for i, p in enumerate(seq):
        out = s.update(t0 + i / fps, p, 0.9)[0]
    return out


def test_smoother_lying_survives_detection_dropouts():
    # Người nằm trên sàn hay bị mất dấu xen kẽ (URFD: ~30% khung) -> vẫn phải xác nhận NẰM
    s = PostureSmoother()
    assert run(s, [STANDING] * 30) == STANDING
    lying_with_gaps = [LYING, NO_PERSON, LYING, LYING, NO_PERSON, BENDING, LYING, NO_PERSON] * 3
    assert run(s, lying_with_gaps, t0=2.0) == LYING


def test_smoother_ignores_isolated_glitches_and_needs_full_dropout_for_no_person():
    s = PostureSmoother()
    run(s, [STANDING] * 30)
    assert run(s, [STANDING, LYING, STANDING, STANDING] * 6, t0=2.0) == STANDING  # 25% NẰM: không đổi
    assert run(s, [NO_PERSON, STANDING] * 15, t0=4.0) == STANDING  # mất dấu chập chờn: vẫn có người
    assert run(s, [NO_PERSON] * 30, t0=6.0) == NO_PERSON  # mất hẳn >= 1.5 s

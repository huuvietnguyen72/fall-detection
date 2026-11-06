"""Giao thức MQTT dùng chung cho mọi thành phần.

Mọi payload là JSON (trừ ảnh snapshot là JPEG thô).
Firmware ESP32 dùng đúng các topic này (xem firmware/fall_belt/config.h).
"""

PREFIX = "fall"

# --- Đai lưng (ESP32) -> Server ---
# Mỗi giây: {"state","rssi","ip","uptime_s","fw","model","calibrated","acc_max_g","tilt",
#            "infer_ms","missed","sensor_err","heap_kb","remaining_s"}
BELT_STATUS = PREFIX + "/belt/{belt_id}/status"
# Mỗi lần xét va chạm: {"type":"detection","fall":false,"ai":0.12,"ai_used":true,"tilt":4,"pre_tilt":8,
#                       "peak_g":2.6,"infer_ms":11.2}
# Khi kết luận té ngã: {"type":"impact","score":0.93,"peak_g":4.1,"tilt":85,"countdown_s":15}
# Người dùng bấm nút:  {"type":"cancel"}
BELT_EVENT = PREFIX + "/belt/{belt_id}/event"
# Server -> Đai lưng: {"cmd": "dismiss" | "sos" | "reset"}
BELT_CMD = PREFIX + "/belt/{belt_id}/cmd"

# --- Camera -> Server ---
# {"posture": "STANDING", "confidence": 0.81, "ts": 1730000000.1, "fps": 14.8, "backend": "mediapipe"}
VISION_POSTURE = PREFIX + "/vision/{cam_id}/posture"
# Ảnh xem trước nhỏ (JPEG ~320px, 1 lần/giây) cho dashboard
VISION_PREVIEW = PREFIX + "/vision/{cam_id}/preview"
# Server -> Camera: {} ; Camera -> Server: JPEG bytes
VISION_SNAPSHOT_REQ = PREFIX + "/vision/{cam_id}/snapshot/request"
VISION_SNAPSHOT = PREFIX + "/vision/{cam_id}/snapshot"

# --- Server -> Dashboard / mọi người ---
SERVER_STATE = PREFIX + "/server/state"

# Tư thế camera có thể báo
STANDING = "STANDING"
SITTING = "SITTING"
BENDING = "BENDING"
LYING = "LYING"
NO_PERSON = "NO_PERSON"
UNKNOWN = "UNKNOWN"  # camera mất tín hiệu / dữ liệu quá cũ

POSTURES = (STANDING, SITTING, BENDING, LYING, NO_PERSON, UNKNOWN)

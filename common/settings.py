"""Đọc cấu hình từ file .env (xem .env.example)."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_float(name: str, default: float) -> float:
    v = env(name)
    return float(v) if v else default


def env_int(name: str, default: int) -> int:
    v = env(name)
    return int(v) if v else default


MQTT_HOST = env("MQTT_HOST", "localhost")
MQTT_PORT = env_int("MQTT_PORT", 1883)
MQTT_USER = env("MQTT_USER")
MQTT_PASSWORD = env("MQTT_PASSWORD")

BELT_ID = env("BELT_ID", "belt01")
CAM_ID = env("CAM_ID", "cam01")

TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")

DASHBOARD_PORT = env_int("DASHBOARD_PORT", 8088)
LOG_DIR = ROOT / "logs"


def mqtt_client(client_id: str):
    """Tạo client paho-mqtt v2 đã cấu hình user/password nếu có."""
    import paho.mqtt.client as mqtt

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    if MQTT_USER:
        c.username_pw_set(MQTT_USER, MQTT_PASSWORD or None)
    c.reconnect_delay_set(min_delay=1, max_delay=10)
    return c

"""Gửi tin nhắn Telegram. Nếu chưa cấu hình token -> chế độ DRY-RUN (chỉ ghi log + lưu ảnh)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

log = logging.getLogger("telegram")


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, log_dir: Path):
        self.token = token
        self.chat_ids = [c.strip() for c in chat_id.split(",") if c.strip()]
        self.log_dir = log_dir
        self.enabled = bool(token and self.chat_ids)
        if not self.enabled:
            log.warning("Chưa cấu hình TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID -> chạy DRY-RUN (không gửi thật)")

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def send(self, text: str, photo: bytes | None = None) -> bool:
        if not self.enabled:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            (self.log_dir / f"telegram-{stamp}.txt").write_text(text, encoding="utf-8")
            if photo:
                (self.log_dir / f"telegram-{stamp}.jpg").write_bytes(photo)
            log.info("[DRY-RUN] Telegram:\n%s%s", text, " (+ ảnh)" if photo else "")
            return True
        ok = True
        for chat_id in self.chat_ids:
            try:
                if photo:
                    r = requests.post(
                        self._url("sendPhoto"),
                        data={"chat_id": chat_id, "caption": text[:1024]},
                        files={"photo": ("snapshot.jpg", photo, "image/jpeg")},
                        timeout=15,
                    )
                else:
                    r = requests.post(self._url("sendMessage"), data={"chat_id": chat_id, "text": text}, timeout=15)
                if not r.ok:
                    ok = False
                    log.error("Telegram lỗi %s: %s", r.status_code, r.text[:300])
            except requests.RequestException as exc:
                ok = False
                log.error("Không gửi được Telegram: %s", exc)
        return ok

"""Quảng bá server qua mDNS để đai lưng tự tìm thấy: tên "fallserver.local" + dịch vụ _mqtt._tcp.

Nhờ vậy firmware không cần biết IP máy tính (IP có thể đổi khi đổi WiFi).
  - macOS: nhờ dịch vụ hệ thống mDNSResponder (`dns-sd -P`) — không cần cấp quyền mạng cục bộ cho Python
  - Linux/Windows: thư viện python-zeroconf
"""

from __future__ import annotations

import logging
import shutil
import socket
import subprocess
import sys

log = logging.getLogger("discovery")

HOSTNAME = "fallserver"


def lan_ips() -> list[str]:
    """Các địa chỉ IPv4 trong mạng LAN của máy; IP dùng để ra Internet đứng đầu."""
    primary = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            primary = s.getsockname()[0]
    except OSError:
        pass
    others: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            others.add(info[4][0])
    except OSError:
        pass
    ordered = ([primary] if primary else []) + sorted(others - {primary})
    return [ip for ip in ordered if not ip.startswith("127.")]


class Advertiser:
    def __init__(self, mqtt_port: int):
        self.mqtt_port = mqtt_port
        self.ips: list[str] = []
        self._proc: subprocess.Popen | None = None
        self._zc = None
        self._info = None

    def start(self) -> None:
        self.ips = lan_ips()
        if not self.ips:
            log.warning("Không tìm thấy IP LAN, bỏ qua mDNS")
            return
        try:
            if sys.platform == "darwin" and shutil.which("dns-sd"):
                self._start_dns_sd()
            else:
                self._start_zeroconf()
            log.info("mDNS: %s.local -> %s (MQTT %d)", HOSTNAME, self.ips[0], self.mqtt_port)
        except Exception as exc:  # mạng không hỗ trợ multicast, thiếu thư viện...
            log.warning("Không quảng bá được mDNS (%s) -> nhập IP server thủ công trên đai", exc)

    def _start_dns_sd(self) -> None:
        self._proc = subprocess.Popen(
            ["dns-sd", "-P", HOSTNAME, "_mqtt._tcp", "local", str(self.mqtt_port), f"{HOSTNAME}.local", self.ips[0]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _start_zeroconf(self) -> None:
        from zeroconf import ServiceInfo, Zeroconf

        self._info = ServiceInfo(
            "_mqtt._tcp.local.",
            f"{HOSTNAME}._mqtt._tcp.local.",
            addresses=[socket.inet_aton(self.ips[0])],
            port=self.mqtt_port,
            server=f"{HOSTNAME}.local.",
            properties={"app": "fall-detection"},
        )
        self._zc = Zeroconf()
        self._zc.register_service(self._info, allow_name_change=True)

    def stop(self) -> None:
        if self._proc:
            self._proc.terminate()
        if self._zc and self._info:
            self._zc.unregister_service(self._info)
            self._zc.close()

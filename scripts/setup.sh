#!/usr/bin/env bash
# Cài đặt một lệnh cho macOS / Linux:   bash scripts/setup.sh
# Tạo .venv, cài thư viện Python, tạo .env từ mẫu, tải sẵn model MediaPipe, kiểm tra Mosquitto.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PYTHON:-python3}
if ! command -v "$PY" >/dev/null; then
    echo "Chưa có Python 3. macOS: brew install python  |  Ubuntu: sudo apt install python3 python3-venv"
    exit 1
fi
"$PY" - <<'EOF' || exit 1
import sys
if sys.version_info < (3, 10):
    sys.exit(f"Cần Python >= 3.10 (đang có {sys.version.split()[0]})")
EOF

echo "==> Tạo môi trường ảo .venv"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
echo "==> Cài thư viện (lần đầu mất vài phút)"
.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo "==> Đã tạo .env từ .env.example (mở ra điền Telegram, camera nếu cần)"
fi

echo "==> Tải model MediaPipe Pose"
.venv/bin/python -c "from vision.backends import MediaPipeBackend; MediaPipeBackend()" >/dev/null

if command -v mosquitto >/dev/null || [ -x /opt/homebrew/opt/mosquitto/sbin/mosquitto ] || [ -x /usr/local/opt/mosquitto/sbin/mosquitto ] || [ -x /usr/sbin/mosquitto ]; then
    echo "==> Mosquitto: OK"
else
    echo "!!  Chưa có Mosquitto (MQTT broker). macOS: brew install mosquitto  |  Ubuntu: sudo apt install mosquitto"
fi

echo "==> Chạy kiểm thử"
.venv/bin/python -m pytest -q 2>&1 | tail -1

cat <<'EOF'

Xong. Chạy hệ thống:
    .venv/bin/python run.py                 # broker + server + camera + dashboard
    .venv/bin/python run.py --camera-sim    # chưa có webcam: camera giả lập
EOF

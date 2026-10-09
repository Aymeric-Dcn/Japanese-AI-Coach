#!/bin/sh
# Installs Japanese Coach as a service on a Raspberry Pi (or any Linux with systemd).
#   sh deploy/install-pi.sh                 the app on http://127.0.0.1:8000 (reach it with « tailscale serve »)
#   PORT=8080 sh deploy/install-pi.sh       another port
# The service starts with the Pi and restarts if it stops. Logs: journalctl -u japanese-coach -f
set -e
DIR=$(cd "$(dirname "$0")/.." && pwd)
PORT=${PORT:-8000}
PYTHON=$(command -v python3 || true)
if [ -z "$PYTHON" ] || ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 8))'; then
    echo "Python 3.8 or newer is needed (python3 --version). On an old Raspberry Pi OS, install a recent one." >&2
    exit 1
fi
mkdir -p "$DIR/data"
sudo tee /etc/systemd/system/japanese-coach.service >/dev/null <<UNIT
[Unit]
Description=Japanese Coach
After=network-online.target
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$DIR
ExecStart=$PYTHON $DIR/server.py --port $PORT
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now japanese-coach
sleep 2
systemctl --no-pager --lines=5 status japanese-coach || true
echo
echo "Japanese Coach runs on http://127.0.0.1:$PORT"
echo "To open it from your phone and PC (HTTPS, inside your tailnet only):  sudo tailscale serve --bg $PORT"

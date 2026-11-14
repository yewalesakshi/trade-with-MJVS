#!/usr/bin/env bash
# Install a newer MJVS_project.zip on the server. Your data and settings are kept.
#     sudo bash update_app.sh
set -euo pipefail
ZIP="${1:-/home/ubuntu/MJVS_project.zip}"
APP=/opt/mjvs
if [ "$(id -u)" != "0" ]; then echo "Please run with sudo:  sudo bash update_app.sh"; exit 1; fi
[ -f "$ZIP" ] || { echo "Upload the new MJVS_project.zip to /home/ubuntu first."; exit 1; }
cp "$APP/data/mjvs.db" "$APP/data/backups/before-update-$(date +%Y%m%d-%H%M).db" 2>/dev/null || true
TMP=$(mktemp -d); unzip -q -o "$ZIP" -d "$TMP"
SRC=$(dirname "$(find "$TMP" -maxdepth 4 -name backend.py | head -n 1)")
[ -f "$SRC/backend.py" ] || { echo "backend.py not found in the zip."; exit 1; }
rm -f "$SRC/mjvs.db"
rm -rf "$APP/code.new"; cp -r "$SRC" "$APP/code.new"; rm -rf "$APP/code"; mv "$APP/code.new" "$APP/code"; rm -rf "$TMP"
"$APP/venv/bin/pip" install -q -r "$APP/code/requirements.txt"
chown -R mjvs:mjvs "$APP"
systemctl restart mjvs
sleep 4
curl -s http://127.0.0.1:8000/health | grep -q '"ok"' && echo "Updated and running." || echo "Not running: sudo journalctl -u mjvs -n 50"

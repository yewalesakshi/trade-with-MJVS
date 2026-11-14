#!/usr/bin/env bash
# MJVS server setup for Ubuntu 22.04 / 24.04 (AWS Lightsail, Oracle Cloud ...).
# Install from a GitHub copy (recommended):
#     git clone https://github.com/yewalesakshi/Trade-with-MJVS.git && cd Trade-with-MJVS
#     sudo bash deploy/setup_server.sh
# or from an uploaded MJVS_project.zip:   sudo bash setup_server.sh
# Safe to run again (also to update): it keeps your data, settings and keys.
set -euo pipefail

SELF_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=""
[ -f "$SELF_DIR/../backend.py" ] && REPO_DIR=$(cd "$SELF_DIR/.." && pwd)
ZIP="${1:-$HOME/MJVS_project.zip}"
[ -f "$ZIP" ] || ZIP="/home/ubuntu/MJVS_project.zip"
APP=/opt/mjvs
DATA=$APP/data
ENVF=$APP/mjvs.env

if [ "$(id -u)" != "0" ]; then echo "Please run with sudo:  sudo bash $0"; exit 1; fi
if [ -z "$REPO_DIR" ] && [ ! -f "$ZIP" ]; then echo "Run this from the cloned Trade-with-MJVS folder, or upload MJVS_project.zip to /home/ubuntu."; exit 1; fi

echo "== 1/7  Time zone: India"
timedatectl set-timezone Asia/Kolkata || true

echo "== 2/7  Installing system packages (a few minutes)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip unzip curl git ca-certificates gnupg
if ! apt-get install -y caddy; then
  # Ubuntu 22.04 has no caddy package: use Caddy's official package source
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
fi

echo "== 3/7  Copying the app"
id -u mjvs >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin mjvs
mkdir -p "$APP" "$DATA/backups"
TMP=$(mktemp -d)
if [ -n "$REPO_DIR" ]; then
  echo "   From the GitHub copy in $REPO_DIR"
  cp -r "$REPO_DIR" "$TMP/mjvs_app"; rm -rf "$TMP/mjvs_app/.git"
else
  echo "   From $ZIP"
  unzip -q -o "$ZIP" -d "$TMP"
fi
# the app folder is the one holding backend.py, whatever the zip calls it
SRC=$(dirname "$(find "$TMP" -maxdepth 4 -name backend.py -path '*/backend.py' | head -n 1)")
if [ ! -f "$SRC/backend.py" ]; then echo "backend.py not found in the zip. Is it the MJVS project zip?"; exit 1; fi
rm -rf "$APP/code.new"; cp -r "$SRC" "$APP/code.new"
rm -rf "$APP/code"; mv "$APP/code.new" "$APP/code"
# Bring your PC's database across once, if it was uploaded next to the zip
if [ ! -f "$DATA/mjvs.db" ]; then
  for f in /home/ubuntu/mjvs.db "$SRC/mjvs.db"; do
    if [ -f "$f" ]; then cp "$f" "$DATA/mjvs.db"; echo "   Copied your existing database from $f"; break; fi
  done
fi
rm -rf "$TMP"

echo "== 4/7  Python packages (a few minutes)"
[ -d "$APP/venv" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q -r "$APP/code/requirements.txt"

echo "== 5/7  Settings and secret keys"
IP=$(curl -4 -s https://checkip.amazonaws.com | tr -d '[:space:]')
HOST="${IP//./-}.sslip.io"          # free web address that always points to this server's IP
if [ ! -f "$ENVF" ]; then
  # New secret keys for this server (a database copied from a PC: re-enter the Kite keys in Admin)
  FERNET=$("$APP/venv/bin/python" -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
  cat > "$ENVF" <<ENV
FRONTEND_URL=https://$HOST
BACKEND_URL=https://$HOST
PUBLIC_URL=https://$HOST
JWT_SECRET=$("$APP/venv/bin/python" -c "import secrets;print(secrets.token_hex(32))")
FERNET_KEY=$FERNET
CHARTINK_KEY=$("$APP/venv/bin/python" -c "import secrets;print(secrets.token_urlsafe(18))")
DATABASE_URL=sqlite:///$DATA/mjvs.db
BACKUP_DIR=$DATA/backups
CAPTCHA_MODE=builtin
ALLOW_LIVE=0
ADMIN_EMAILS=
KITE_API_KEY=
KITE_API_SECRET=
TZ=Asia/Kolkata
ENV
  echo "   Created $ENVF"
else
  echo "   Keeping existing settings in $ENVF"
  OLD_HOST=$(grep -oP '^BACKEND_URL=https://\K\S+' "$ENVF" || true)
  if [ -n "$OLD_HOST" ] && [ "$OLD_HOST" != "$HOST" ] && [[ "$OLD_HOST" == *.sslip.io ]]; then
    # the server has a new IP (e.g. a new Elastic IP): move the web address to it
    sed -i "s#https://$OLD_HOST#https://$HOST#g" "$ENVF"
    echo "   The IP changed: web address moved from $OLD_HOST to $HOST"
    echo "   Put the NEW Redirect URL and IP in Zerodha (shown below)."
  elif [ -n "$OLD_HOST" ]; then
    HOST=$OLD_HOST
  fi
fi
chmod 600 "$ENVF"
chown -R mjvs:mjvs "$APP"

echo "== 6/7  Run the app 24x7 (restarts by itself)"
cat > /etc/systemd/system/mjvs.service <<UNIT
[Unit]
Description=MJVS trading app
After=network-online.target
Wants=network-online.target

[Service]
User=mjvs
WorkingDirectory=$APP/code
EnvironmentFile=$ENVF
ExecStart=$APP/venv/bin/uvicorn backend:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now mjvs
systemctl restart mjvs

echo "== 7/7  HTTPS web address"
cat > /etc/caddy/Caddyfile <<CADDY
$HOST {
    reverse_proxy 127.0.0.1:8000
}
CADDY
systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy

sleep 4
if curl -s http://127.0.0.1:8000/health | grep -q '"ok"'; then OK="running"; else OK="NOT running yet (see: sudo journalctl -u mjvs -n 50)"; fi
cat <<DONE

================================================================
 MJVS is $OK
 Your website:      https://$HOST
 Fixed IP to whitelist in Zerodha:  $IP
 Kite Redirect URL:  https://$HOST/kite/callback
----------------------------------------------------------------
 Next: developers.kite.trade -> your app -> Redirect URL (above)
       developers.kite.trade -> Profile -> IP Whitelist -> $IP
 Useful commands:
   sudo systemctl status mjvs        (is it running?)
   sudo journalctl -u mjvs -n 100    (last log lines)
   sudo systemctl restart mjvs       (restart)
================================================================
DONE

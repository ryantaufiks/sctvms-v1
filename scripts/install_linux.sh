#!/usr/bin/env bash
# Visitor Management System (VMS) - Linux installer
# This script installs system deps, sets up a Python venv, installs Python requirements,
# prepares environment, runs migrations/collectstatic, and optionally configures systemd+gunicorn.
set -euo pipefail

# --- Configurable defaults ---
MODE="dev"                 # dev or prod
PORT="8004"               # bind port (gunicorn or runserver)
DOMAIN="localhost"         # used for ALLOWED_HOSTS in .env when prod
SERVICE_NAME="vms"         # systemd service name
RUN_USER="$(whoami)"       # user to run service (prod)
PYTHON_BIN="python3"        # python binary
PROJECT_DIR="$(cd "$(dirname "$0")"/.. && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
ENV_FILE="$PROJECT_DIR/.env"

usage() {
  cat <<EOF
Usage: bash scripts/install_linux.sh [--prod] [--port PORT] [--domain DOMAIN] [--user USER]

Options:
  --prod            Install as a production service using gunicorn + systemd (default: dev)
  --port PORT       Port to bind (default: 8004)
  --domain DOMAIN   Domain or host for ALLOWED_HOSTS in prod (default: localhost)
  --user USER       System user to run the service (default: current user)
  -h, --help        Show this help

Examples:
  bash scripts/install_linux.sh                      # dev install, runserver
  bash scripts/install_linux.sh --prod --domain my.domain --port 8004 --user vms
EOF
}

# --- Parse args ---
while [[ "${1:-}" != "" ]]; do
  case "$1" in
    --prod) MODE="prod" ;;

    --domain) DOMAIN="${2:-}"; shift ;;
    --user) RUN_USER="${2:-}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
  shift
done

echo "[VMS] Mode: $MODE | Port: $PORT | Domain: $DOMAIN | User: $RUN_USER"

echo "[VMS] Detecting package manager..."
PKG=""
UPDATE_CMD=""
INSTALL_CMD=""
if command -v apt >/dev/null 2>&1; then
  PKG="apt"
  UPDATE_CMD="sudo apt update -y"
  INSTALL_CMD="sudo apt install -y"
elif command -v dnf >/dev/null 2>&1; then
  PKG="dnf"
  UPDATE_CMD="sudo dnf makecache -y"
  INSTALL_CMD="sudo dnf install -y"
elif command -v yum >/dev/null 2>&1; then
  PKG="yum"
  UPDATE_CMD="sudo yum makecache -y"
  INSTALL_CMD="sudo yum install -y"
else
  echo "Unsupported distribution (need apt, dnf, or yum)." >&2
  exit 1
fi

echo "[VMS] Updating package index..."
$UPDATE_CMD

echo "[VMS] Installing system dependencies..."
if [[ "$PKG" == "apt" ]]; then
  $INSTALL_CMD build-essential $PYTHON_BIN python3-venv python3-pip \
    libjpeg-dev zlib1g-dev libfreetype6-dev liblcms2-dev libwebp-dev \
    tcl-dev tk-dev libharfbuzz-dev libfribidi-dev ghostscript
else
  # dnf/yum packages
  $INSTALL_CMD $PYTHON_BIN python3-venv python3-pip gcc gcc-c++ make \
    libjpeg-turbo-devel zlib-devel freetype-devel lcms2-devel libwebp-devel \
    tcl-devel tk-devel harfbuzz-devel fribidi-devel ghostscript
fi

# --- Python virtual environment ---
if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

pip install --upgrade pip
pip install -r "$PROJECT_DIR/requirements.txt"

# --- Environment file ---
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<ENV
DJANGO_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(50))')
DJANGO_DEBUG=$( [[ "$MODE" == "prod" ]] && echo False || echo True )
DJANGO_ALLOWED_HOSTS=$DOMAIN,localhost,127.0.0.1,::1
ENV
fi

# --- Django setup ---
python manage.py migrate
python manage.py collectstatic --noinput

if [[ "$MODE" == "dev" ]]; then
  echo "[VMS] Development setup complete. To run the dev server:"
  echo "  source $VENV_DIR/bin/activate && python manage.py runserver 0.0.0.0:$PORT"
  exit 0
fi

# --- Production: systemd + gunicorn ---
# Create systemd unit that loads env vars from $ENV_FILE and runs gunicorn from venv
GUNICORN_BIN="$VENV_DIR/bin/gunicorn"
if [[ ! -x "$GUNICORN_BIN" ]]; then
  echo "[VMS] gunicorn not found at $GUNICORN_BIN. Ensure requirements installed correctly." >&2
  exit 1
fi

UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
echo "[VMS] Writing systemd unit to $UNIT_FILE (sudo required)"

sudo bash -c "cat > '$UNIT_FILE'" <<SYSTEMD
[Unit]
Description=VMS Django (gunicorn)
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$GUNICORN_BIN vms.wsgi:application --bind 0.0.0.0:$PORT --workers 3
Restart=on-failure
RestartSec=5
TimeoutStartSec=30

[Install]
WantedBy=multi-user.target
SYSTEMD

echo "[VMS] Enabling and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

set +e
sleep 1
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true
set -e

echo "[VMS] Production setup complete. Service: $SERVICE_NAME"
echo "- Logs: journalctl -u $SERVICE_NAME -f"
echo "- App:  http://<your-server-ip>:$PORT/  (ALLOWED_HOSTS: $DOMAIN)"
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="signomat"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
LEGACY_SERVICE_PATH="/etc/systemd/system/signomat-legacy.service"
ENV_FILE_PATH="/etc/default/signomat"
TARGET_USER="${SUDO_USER:-${USER}}"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this installer with sudo:"
    echo "  sudo bash ${SCRIPT_DIR}/install_signomat_service.sh"
    exit 1
fi

if ! id "${TARGET_USER}" >/dev/null 2>&1; then
    echo "User '${TARGET_USER}' does not exist."
    exit 1
fi

TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"
DATA_DIR="/data/signomat"

if [[ ! -x "${PYTHON_BIN}" ]]; then
    echo "Missing virtualenv python at ${PYTHON_BIN}"
    echo "Run ./scripts/bootstrap_pi.sh first."
    exit 1
fi

if [[ ! -d "${SCRIPT_DIR}/pi/src/signomat_pi" ]]; then
    echo "Missing packaged runtime at ${SCRIPT_DIR}/pi/src/signomat_pi"
    exit 1
fi

if [[ ! -f "${ENV_FILE_PATH}" ]]; then
    cat > "${ENV_FILE_PATH}" <<'EOF'
# Optional Signomat runtime overrides.
# SIGNOMAT_BASE_DATA_DIR=/data/signomat
#
# Optional Signomat camera overrides used by the packaged runtime.
# For USB cameras:
# SIGNOMAT_CAMERA_BACKEND=opencv
# SIGNOMAT_CAMERA_DEVICE=/dev/video0
# SIGNOMAT_CAMERA_FOURCC=MJPG
#
# For Pi cameras:
# SIGNOMAT_CAMERA_BACKEND=picamera2
# SIGNOMAT_CAMERA_INDEX=0
#
# Shared tuning:
# SIGNOMAT_CAMERA_WIDTH=1280
# SIGNOMAT_CAMERA_HEIGHT=720
# SIGNOMAT_CAMERA_FPS=30
# SIGNOMAT_CAMERA_WARMUP_SECONDS=2
#
# Exposure tuning for dim scenes:
# SIGNOMAT_CAMERA_AUTO_EXPOSURE=true
# SIGNOMAT_CAMERA_EXPOSURE_COMPENSATION=0.8
# SIGNOMAT_CAMERA_BRIGHTNESS=0.1
# SIGNOMAT_CAMERA_CONTRAST=1.1
# SIGNOMAT_CAMERA_EXPOSURE_TIME_US=12000
# SIGNOMAT_CAMERA_ANALOGUE_GAIN=2.0
EOF
    chmod 0644 "${ENV_FILE_PATH}"
fi

if grep -Eq '^[[:space:]]*SIGNOMAT_BASE_DATA_DIR=' "${ENV_FILE_PATH}"; then
    DATA_DIR="$(grep -E '^[[:space:]]*SIGNOMAT_BASE_DATA_DIR=' "${ENV_FILE_PATH}" | tail -n 1 | cut -d= -f2- | xargs)"
fi

if [[ -z "${DATA_DIR}" ]]; then
    DATA_DIR="${TARGET_HOME}/signomat-data"
fi

install -d -o "${TARGET_USER}" -g "${TARGET_USER}" "${DATA_DIR}"

if [[ -f "${SERVICE_PATH}" ]] && grep -q '/app.py' "${SERVICE_PATH}"; then
    cp "${SERVICE_PATH}" "${LEGACY_SERVICE_PATH}"
    echo "Backed up the previous legacy boot unit to ${LEGACY_SERVICE_PATH}"
fi

cat > "${SERVICE_PATH}" <<EOF
[Unit]
Description=Signomat Pi Runtime
After=local-fs.target
Wants=local-fs.target

[Service]
Type=simple
User=${TARGET_USER}
Group=${TARGET_USER}
WorkingDirectory=${SCRIPT_DIR}
Environment=HOME=${TARGET_HOME}
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=${SCRIPT_DIR}/pi/src
EnvironmentFile=-${ENV_FILE_PATH}
ExecStart=${PYTHON_BIN} -m signomat_pi.cli.main --config ${SCRIPT_DIR}/pi/config/default.yaml serve
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"
systemctl restart "${SERVICE_NAME}.service"

echo
echo "Installed ${SERVICE_NAME}.service for the packaged runtime."
echo "Data directory: ${DATA_DIR}"
echo "Camera settings file: ${ENV_FILE_PATH}"
echo "Status:"
systemctl status "${SERVICE_NAME}.service" --no-pager

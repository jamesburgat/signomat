#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run this helper with sudo:"
    echo "  sudo bash scripts/disable_legacy_service.sh"
    exit 1
fi

if systemctl list-unit-files | grep -q '^signomat\.service'; then
    systemctl disable --now signomat.service || true
fi

if [[ -f /etc/systemd/system/signomat.service ]] && grep -q '/app.py' /etc/systemd/system/signomat.service; then
    mv /etc/systemd/system/signomat.service /etc/systemd/system/signomat-legacy.service
    systemctl daemon-reload
    echo "Renamed the installed legacy unit to /etc/systemd/system/signomat-legacy.service"
fi

echo "Legacy auto-start disabled."
echo "Install the packaged runtime with:"
echo "  sudo bash install_signomat_service.sh"

#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m venv --system-site-packages .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e '.[dev,ble]'

echo "Signomat environment bootstrapped with system site packages enabled."

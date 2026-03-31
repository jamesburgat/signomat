#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
. .venv/bin/activate

PYTHONPATH=pi/src signomat --config pi/config/mock.yaml serve


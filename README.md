# Signomat

Signomat is an offline-first vehicle sign-detection system built around a Raspberry Pi, local storage, a modular inference pipeline, BLE-based control, and a public archive path that can sync later when connectivity returns.

## Repo Layout

- `pi/`: Raspberry Pi services, CLI, config, migrations, tests, and systemd units.
- `ios_app/`: SwiftUI + CoreBluetooth control app scaffold.
- `archive/`: Cloudflare-backed archive scaffolding for the public site and ingest API.
- `docs/`: architecture, schema, BLE, taxonomy, and event-flow docs.
- `scripts/`: helper setup and maintenance scripts.

## Phase Status

- Phase 1: local trip recording, chunked video, GPS breadcrumb logging, modular detection persistence, screenshots, FastAPI admin/debug API, mock mode.
- Phase 2 scaffold: BLE protocol and Pi/iPhone skeletons.
- Phase 3+: queued sync and public archive scaffolding documented for later build-out.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,ble]'
PYTHONPATH=pi/src python -m signomat_pi.cli.main --config pi/config/mock.yaml serve
```

Then open `http://127.0.0.1:8080/docs` for the local API when running in mock mode.

## Core Design Rules

- Detection never depends on internet connectivity.
- BLE is for control and status only, never media transport.
- Continuous video, screenshots, GPS, and metadata are stored locally first.
- Detection localization, classification, and taxonomy mapping are separate stages.
- Taxonomy mapping is configuration-driven so archives can evolve without retraining the whole stack.

## Training Direction

- The current Pi runtime still uses heuristic detection and classification.
- The learned detector path is now a one-class `sign` model trained on `Mapillary + GLARE`.
- The learned classifier path is separate and crop-based so it can run later or on-demand without sitting in the Pi's hot path.
- Dataset and label-planning details live in `docs/training-data.md`.

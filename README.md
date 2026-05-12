# Signomat

Signomat is an offline-first vehicle sign-detection system built around a Raspberry Pi, local storage, a modular inference pipeline, BLE-based control, and a Cloudflare-hosted archive path for public browsing and review workflows.

## Repo Layout

- `pi/`: Raspberry Pi services, CLI, config, migrations, tests, and systemd units.
- `ios_app/`: SwiftUI + CoreBluetooth control app work-in-progress.
- `archive/`: current Cloudflare archive frontend, Worker API, and shared TypeScript contracts.
- `docs/`: architecture, schema, BLE, taxonomy, and event-flow docs.
- `scripts/`: helper setup and maintenance scripts.

## Phase Status

- Phase 1: local trip recording, chunked video, GPS breadcrumb logging, modular detection persistence, screenshots, FastAPI admin/debug API, mock mode, and learned-model runtime wiring.
- Phase 2: BLE protocol, shared control surface, and iOS control app structure are in place, but this path is still less mature than the Pi runtime and archive flow.
- Phase 3: the Cloudflare archive is implemented as a Worker-served SPA plus API with D1/R2 bindings, public map/detail browsing, protected review/training routes, and repo config targeting `signs.jamesburgat.com`.
- Still in progress: end-to-end sync hardening from the Pi upload queue into the hosted archive, plus broader polish around the mobile/control experience.

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,ble]'
PYTHONPATH=pi/src python -m signomat_pi.cli.main --config pi/config/mock.yaml serve
```

Then open `http://127.0.0.1:8080/docs` for the local API when running in mock mode.

For the hosted archive and Cloudflare deployment path, see `docs/cloudflare-setup.md`.

## Core Design Rules

- Detection never depends on internet connectivity.
- BLE is for control and status only, never media transport.
- Continuous video, screenshots, GPS, and metadata are stored locally first.
- Detection localization, classification, and taxonomy mapping are separate stages.
- Taxonomy mapping is configuration-driven so archives can evolve without retraining the whole stack.

## Training Direction

- The default Pi runtime uses one recall-first live profile: the learned one-class `sign` detector runs while driving and crop classification stays off the hot path.
- The default Pi runtime expects the learned model files to load; mock/dev configs can still opt into the mock detector/classifier explicitly.
- The learned classifier remains available for replay, archive review, and training workflows instead of always-on driving inference.
- The learned detector is trained on `Mapillary + GLARE`; the learned classifier is trained on data-driven raw-label crops.
- Dataset and label-planning details live in `docs/training-data.md`.

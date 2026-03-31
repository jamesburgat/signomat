# Architecture

## Monorepo Structure

```text
signomat/
  pyproject.toml
  README.md
  pi/
    config/
      default.yaml
      mock.yaml
      taxonomy.yaml
    migrations/
      0001_initial.sql
    src/signomat_pi/
      ble_control_service/
      capture_service/
      cli/
      common/
      gps_service/
      inference_service/
      local_api/
      sync_service/
    systemd/
      signomat.service
      signomat-api.service
    tests/
  ios_app/
    project.yml
    SignomatControl/
      Sources/
  archive/
    frontend/
    worker_api/
    shared/
  docs/
  scripts/
```

## Pi Runtime

The Pi runtime is a single-process orchestrator with dedicated worker threads:

- `capture_service`: owns camera access, the latest frame cache, and chunked video writing.
- `gps_service`: samples GPS continuously during active trips and keeps a recent ring buffer.
- `inference_service`: runs a modular pipeline over the latest frame, deduplicates, saves assets, and persists events.
- `sync_service`: persists an upload queue now and becomes the network sync worker in Phase 3.
- `local_api`: exposes FastAPI status, debugging, and control endpoints.
- `ble_control_service`: uses the same control surface as the local API, but over BLE.

## Why This Split

- Camera capture is isolated from inference so a detector swap does not change recording reliability.
- Taxonomy mapping is isolated from classification so the archive can be re-grouped later.
- The local database is the source of truth, while files hold media assets.
- The upload queue is local and durable so networking is never on the critical path for capture.

## Archive Direction

- `archive/frontend`: public browsing UI and later protected admin/review mode.
- `archive/worker_api`: Cloudflare Worker ingest API, admin mutations, and public read endpoints.
- `archive/shared`: TypeScript schema contracts shared between front end and worker.


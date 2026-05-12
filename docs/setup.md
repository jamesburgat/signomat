# Setup

## Pi Development

```bash
./scripts/bootstrap_pi.sh
. .venv/bin/activate
PYTHONPATH=pi/src python -m signomat_pi.cli.main --config pi/config/mock.yaml serve
```

## Useful Commands

```bash
PYTHONPATH=pi/src python -m signomat_pi.cli.main --config pi/config/mock.yaml start-trip
PYTHONPATH=pi/src python -m signomat_pi.cli.main --config pi/config/mock.yaml status
PYTHONPATH=pi/src python -m signomat_pi.cli.main --config pi/config/mock.yaml save-snapshot
PYTHONPATH=pi/src python -m signomat_pi.cli.main --config pi/config/mock.yaml health-check
PYTHONPATH=pi/src python -m signomat_pi.cli.main --config pi/config/default.yaml gps-diagnose
```

## Archive Notes

- The hosted archive/frontend + Worker deployment path is documented in `docs/cloudflare-setup.md`.
- The archive frontend is no longer just a design stub; it now expects to run either as static files locally or as Worker-served assets in Cloudflare.
- Local frontend/Worker development for the archive requires a machine with Node/Wrangler installed. This repo does not vendor a JS runtime.

## Notes

- Use `pi/config/mock.yaml` for development without camera or GPS hardware.
- The local API provides Swagger docs at `/docs`.
- BLE control exists, but media transfer is intentionally unsupported.
- The supported boot/install path is `install_signomat_service.sh`.

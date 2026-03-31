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
```

## Notes

- Use `pi/config/mock.yaml` for development without camera or GPS hardware.
- The local API provides Swagger docs at `/docs`.
- BLE is scaffolded but media transfer is intentionally unsupported.
- The supported boot/install path is `install_signomat_service.sh`.

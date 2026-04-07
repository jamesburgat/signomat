from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib import request

import uvicorn

from signomat_pi.common.config import load_config, repo_root
from signomat_pi.common.logging import configure_logging
from signomat_pi.common.runtime import SignomatRuntime
from signomat_pi.gps_service.diagnostics import diagnose_gps
from signomat_pi.local_api.app import create_app


def _http_call(method: str, url: str) -> dict:
    req = request.Request(url, method=method)
    with request.urlopen(req) as response:  # nosec - localhost helper
        payload = response.read().decode("utf-8")
        return json.loads(payload) if payload else {"ok": True}


def serve(args) -> int:
    config = load_config(args.config)
    configure_logging(config.app.log_level)
    runtime = SignomatRuntime(config)
    runtime.start()
    app = create_app(runtime)
    try:
        uvicorn.run(app, host=config.api.host, port=config.api.port, log_level="info")
    finally:
        runtime.stop()
    return 0


def local_command(args, path: str) -> int:
    response = _http_call("POST", f"http://{args.host}:{args.port}{path}")
    print(json.dumps(response, indent=2))
    return 0 if response.get("ok", True) else 1


def show_status(args) -> int:
    response = _http_call("GET", f"http://{args.host}:{args.port}/status")
    print(json.dumps(response, indent=2))
    return 0


def health_check(args) -> int:
    response = _http_call("GET", f"http://{args.host}:{args.port}/health")
    print(json.dumps(response, indent=2))
    return 0 if response.get("ok") else 1


def gps_diagnose(args) -> int:
    config = load_config(args.config)
    response = diagnose_gps(config, host=args.host, port=args.port)
    print(json.dumps(response, indent=2))
    return 0 if response.get("ready") else 1


def export_local_data(args) -> int:
    config = load_config(args.config)
    base_dir = Path(config.app.base_data_dir)
    if not base_dir.is_absolute():
        base_dir = repo_root() / base_dir
    print(json.dumps({"base_data_dir": str(base_dir), "note": "Phase 1 export points at the local data root"}, indent=2))
    return 0


def prune_old_media(args) -> int:
    config = load_config(args.config)
    trips_dir = Path(config.app.base_data_dir)
    if not trips_dir.is_absolute():
        trips_dir = repo_root() / trips_dir
    trips_dir = trips_dir / "trips"
    pruned = []
    if trips_dir.exists():
        cutoff_seconds = args.days * 86400
        now = time.time()
        for path in trips_dir.iterdir():
            if not path.is_dir():
                continue
            age = now - path.stat().st_mtime
            if age > cutoff_seconds:
                pruned.append(path.name)
    print(json.dumps({"candidate_prunes": pruned}, indent=2))
    return 0


def replay_trip(args) -> int:
    print(json.dumps({"ok": True, "message": "trip replay scaffolding reserved for Phase 5", "trip_id": args.trip_id}, indent=2))
    return 0


def force_sync(args) -> int:
    if args.snapshot:
        response = _http_call("POST", f"http://{args.host}:{args.port}/snapshot")
    else:
        response = _http_call("POST", f"http://{args.host}:{args.port}/sync/force")
    print(json.dumps(response, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="signomat")
    parser.add_argument("--config", default="pi/config/default.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve")
    serve_parser.set_defaults(func=serve)

    for name, path in (
        ("start-trip", "/session/start"),
        ("stop-trip", "/session/stop"),
        ("start-recording", "/recording/start"),
        ("stop-recording", "/recording/stop"),
        ("enable-inference", "/inference/enable"),
        ("disable-inference", "/inference/disable"),
        ("save-snapshot", "/snapshot"),
    ):
        cmd = subparsers.add_parser(name)
        cmd.add_argument("--host", default="127.0.0.1")
        cmd.add_argument("--port", default=8080, type=int)
        cmd.set_defaults(func=lambda args, _path=path: local_command(args, _path))

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--host", default="127.0.0.1")
    status_parser.add_argument("--port", default=8080, type=int)
    status_parser.set_defaults(func=show_status)

    health_parser = subparsers.add_parser("health-check")
    health_parser.add_argument("--host", default="127.0.0.1")
    health_parser.add_argument("--port", default=8080, type=int)
    health_parser.set_defaults(func=health_check)

    gps_parser = subparsers.add_parser("gps-diagnose")
    gps_parser.add_argument("--host", default="127.0.0.1")
    gps_parser.add_argument("--port", default=2947, type=int)
    gps_parser.set_defaults(func=gps_diagnose)

    replay_parser = subparsers.add_parser("replay-trip")
    replay_parser.add_argument("trip_id")
    replay_parser.set_defaults(func=replay_trip)

    force_sync_parser = subparsers.add_parser("force-sync")
    force_sync_parser.add_argument("--host", default="127.0.0.1")
    force_sync_parser.add_argument("--port", default=8080, type=int)
    force_sync_parser.add_argument("--snapshot", action="store_true")
    force_sync_parser.set_defaults(func=force_sync)

    export_parser = subparsers.add_parser("export-local-data")
    export_parser.set_defaults(func=export_local_data)

    prune_parser = subparsers.add_parser("prune-old-media")
    prune_parser.add_argument("--days", type=int, default=14)
    prune_parser.set_defaults(func=prune_old_media)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

from __future__ import annotations

import json

from signomat_pi.cli import main as cli_main
from signomat_pi.common.config import SignomatConfig
from signomat_pi.gps_service.diagnostics import build_gps_diagnosis, parse_gpsd_report


def test_parse_gpsd_report_extracts_fix_and_satellites():
    report = parse_gpsd_report(
        [
            '{"class":"DEVICES","devices":[{"path":"/dev/ttyACM0","driver":"u-blox","subtype":"GPS 7"}]}',
            '{"class":"TPV","device":"/dev/ttyACM0","mode":3,"time":"2026-04-02T21:30:00Z","lat":41.8,"lon":-71.4,"track":93.0,"alt":5.0,"speed":12.4}',
            '{"class":"SKY","device":"/dev/ttyACM0","nSat":12,"uSat":8}',
        ]
    )

    assert report["device"] == "/dev/ttyACM0"
    assert report["fix_quality"] == "3d"
    assert report["lat"] == 41.8
    assert report["lon"] == -71.4
    assert report["satellites_visible"] == 12
    assert report["satellites_used"] == 8


def test_build_gps_diagnosis_reports_detected_but_no_fix():
    config = SignomatConfig()
    diagnosis = build_gps_diagnosis(
        config,
        detected_devices=[{"path": "/dev/ttyACM0", "resolved_path": "/dev/ttyACM0", "kind": "usb-acm"}],
        gpsd_report={
            "reachable": True,
            "device": "/dev/ttyACM0",
            "devices": [{"path": "/dev/ttyACM0", "driver": "u-blox", "subtype": "GPS 7"}],
            "driver": "u-blox",
            "subtype": "GPS 7",
            "mode": 1,
            "fix_quality": "no_fix",
            "timestamp_utc": None,
            "lat": None,
            "lon": None,
            "speed": None,
            "heading": None,
            "altitude": None,
            "satellites_visible": 2,
            "satellites_used": 0,
            "host": "127.0.0.1",
            "port": 2947,
            "error": None,
        },
    )

    assert diagnosis["status"] == "no_fix"
    assert diagnosis["ready"] is False
    assert "does not have a usable fix yet" in diagnosis["summary"]
    assert any("gpspipe -w -n 10" in item for item in diagnosis["recommendations"])


def test_gps_diagnose_command_returns_nonzero_without_fix(monkeypatch, capsys):
    monkeypatch.setattr(
        cli_main,
        "diagnose_gps",
        lambda config, host, port: {
            "ok": True,
            "ready": False,
            "status": "no_fix",
            "summary": "GPS detected on /dev/ttyACM0, but it does not have a usable fix yet.",
        },
    )

    exit_code = cli_main.main(["--config", "pi/config/default.yaml", "gps-diagnose"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["status"] == "no_fix"

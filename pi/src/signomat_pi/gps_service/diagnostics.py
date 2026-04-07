from __future__ import annotations

import glob
import json
import os
import socket
from typing import Any, Callable, Iterable

from signomat_pi.common.config import SignomatConfig


GPSD_HOST = "127.0.0.1"
GPSD_PORT = 2947
GPS_DEVICE_PATTERNS = (
    "/dev/ttyACM*",
    "/dev/ttyUSB*",
    "/dev/serial0",
    "/dev/serial1",
    "/dev/ttyAMA*",
    "/dev/ttyS*",
)


def _device_kind(path: str) -> str:
    if path.startswith("/dev/ttyACM"):
        return "usb-acm"
    if path.startswith("/dev/ttyUSB"):
        return "usb-serial"
    if path.startswith("/dev/serial"):
        return "serial-alias"
    if path.startswith("/dev/ttyAMA") or path.startswith("/dev/ttyS"):
        return "uart"
    return "serial"


def detect_candidate_devices(
    patterns: Iterable[str] = GPS_DEVICE_PATTERNS,
    glob_fn: Callable[[str], list[str]] = glob.glob,
    realpath_fn: Callable[[str], str] = os.path.realpath,
) -> list[dict[str, str]]:
    devices: dict[str, dict[str, str]] = {}
    for pattern in patterns:
        for path in sorted(glob_fn(pattern)):
            devices[path] = {
                "path": path,
                "resolved_path": realpath_fn(path),
                "kind": _device_kind(path),
            }
    return [devices[path] for path in sorted(devices)]


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _safe_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _fix_quality(mode: int) -> str:
    if mode >= 3:
        return "3d"
    if mode == 2:
        return "2d"
    if mode == 1:
        return "no_fix"
    return "unavailable"


def parse_gpsd_report(lines: Iterable[str]) -> dict[str, Any]:
    devices: list[dict[str, Any]] = []
    tpv: dict[str, Any] = {}
    sky: dict[str, Any] = {}

    for raw_line in lines:
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload_class = payload.get("class")
        if payload_class == "DEVICES":
            devices = payload.get("devices") or []
        elif payload_class == "TPV":
            tpv = payload
        elif payload_class == "SKY":
            sky = payload

    mode = _safe_int(tpv.get("mode")) or 0
    has_fix = mode >= 2
    device = tpv.get("device") or (devices[0].get("path") if devices else None)
    return {
        "reachable": True,
        "device": device,
        "devices": devices,
        "driver": devices[0].get("driver") if devices else None,
        "subtype": devices[0].get("subtype") if devices else None,
        "mode": mode,
        "fix_quality": _fix_quality(mode),
        "timestamp_utc": tpv.get("time"),
        "lat": _safe_number(tpv.get("lat")) if has_fix else None,
        "lon": _safe_number(tpv.get("lon")) if has_fix else None,
        "speed": _safe_number(tpv.get("speed") if "speed" in tpv else tpv.get("hspeed")) if has_fix else None,
        "heading": _safe_number(tpv.get("track")) if has_fix else None,
        "altitude": _safe_number(tpv.get("alt")) if has_fix else None,
        "satellites_visible": _safe_int(sky.get("nSat")),
        "satellites_used": _safe_int(sky.get("uSat")),
    }


def query_gpsd(
    host: str = GPSD_HOST,
    port: int = GPSD_PORT,
    timeout_seconds: float = 3.0,
    max_lines: int = 12,
    connection_factory: Callable[..., socket.socket] = socket.create_connection,
) -> dict[str, Any]:
    try:
        with connection_factory((host, port), timeout_seconds) as sock:
            sock.settimeout(timeout_seconds)
            stream = sock.makefile("rwb")
            lines: list[str] = []
            banner = stream.readline().decode("utf-8", errors="replace").strip()
            if banner:
                lines.append(banner)
            stream.write(b'?WATCH={"enable":true,"json":true}\n')
            stream.flush()

            for _ in range(max_lines):
                line = stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                lines.append(text)
                report = parse_gpsd_report(lines)
                if report["device"] and (report["mode"] >= 2 or report["satellites_visible"] is not None):
                    break
    except OSError as exc:
        return {
            "reachable": False,
            "host": host,
            "port": port,
            "device": None,
            "devices": [],
            "driver": None,
            "subtype": None,
            "mode": 0,
            "fix_quality": "unavailable",
            "timestamp_utc": None,
            "lat": None,
            "lon": None,
            "speed": None,
            "heading": None,
            "altitude": None,
            "satellites_visible": None,
            "satellites_used": None,
            "error": str(exc),
        }

    report = parse_gpsd_report(lines)
    report.update(
        {
            "host": host,
            "port": port,
            "error": None,
        }
    )
    return report


def _effective_provider(config: SignomatConfig) -> str:
    configured_provider = config.gps.provider.lower()
    if config.mock.enabled or configured_provider == "mock":
        return "mock"
    if configured_provider == "none":
        return "none"
    return "gpsd"


def _recommendations(
    status: str,
    devices: list[dict[str, str]],
    gpsd_report: dict[str, Any],
) -> list[str]:
    recommendations: list[str] = []
    if status == "mock_configured":
        recommendations.append("Disable mock mode in the active config before testing real GPS hardware.")
        recommendations.append("Use the default config or set SIGNOMAT_GPS_PROVIDER=auto for live GPS input.")
    elif status == "provider_disabled":
        recommendations.append("Set gps.provider to auto or export SIGNOMAT_GPS_PROVIDER=auto before starting Signomat.")
    elif status == "no_device":
        recommendations.append("Re-seat the GPS, confirm USB or UART wiring, and recheck /dev/ttyACM*, /dev/ttyUSB*, or /dev/serial0.")
        recommendations.append("If this is a UART GPS on GPIO pins, enable the Pi UART in /boot/firmware/config.txt and reboot.")
    elif status == "gpsd_unreachable":
        recommendations.append("Start gpsd and confirm it is attached to the correct device, for example /dev/ttyACM0.")
        recommendations.append("Check /etc/default/gpsd and systemctl status gpsd.service for device and startup errors.")
    elif status == "no_fix":
        recommendations.append("Move the receiver outdoors or to a clear window and give it 10-20 minutes for a cold start.")
        recommendations.append("Check the GPS antenna connection and confirm the module has a clear sky view.")
        if gpsd_report.get("device"):
            recommendations.append(f"Watch live status with gpspipe -w -n 10 and wait for mode 2 or 3 on {gpsd_report['device']}.")
    elif status in {"fix_2d", "fix_3d"}:
        recommendations.append("GPS is producing a live fix; Signomat should now report gps_health as fix.")

    if devices and status in {"gpsd_unreachable", "no_fix"}:
        recommendations.append("Detected device paths: " + ", ".join(device["path"] for device in devices))
    return recommendations


def build_gps_diagnosis(
    config: SignomatConfig,
    detected_devices: list[dict[str, str]],
    gpsd_report: dict[str, Any],
) -> dict[str, Any]:
    configured_provider = config.gps.provider.lower()
    effective_provider = _effective_provider(config)
    device_path = gpsd_report.get("device") or (detected_devices[0]["path"] if detected_devices else None)
    sats_used = gpsd_report.get("satellites_used")
    sats_visible = gpsd_report.get("satellites_visible")

    if effective_provider == "mock":
        status = "mock_configured"
        summary = "Mock GPS is enabled in config, so Signomat is not using real GPS hardware."
    elif effective_provider == "none":
        status = "provider_disabled"
        summary = "GPS is disabled in config, so Signomat will not read real GPS hardware."
    elif gpsd_report.get("reachable"):
        mode = gpsd_report.get("mode", 0)
        if mode >= 3:
            status = "fix_3d"
            summary = f"GPS detected on {device_path} with a 3D fix."
        elif mode == 2:
            status = "fix_2d"
            summary = f"GPS detected on {device_path} with a 2D fix."
        else:
            status = "no_fix"
            if sats_visible is None:
                summary = f"GPS detected on {device_path}, but it does not have a usable fix yet."
            else:
                summary = (
                    f"GPS detected on {device_path}, but it does not have a usable fix yet "
                    f"({sats_used or 0}/{sats_visible} satellites used)."
                )
    elif detected_devices:
        status = "gpsd_unreachable"
        summary = "GPS hardware is present, but gpsd is not reachable."
    else:
        status = "no_device"
        summary = "No GPS hardware was detected, and gpsd is not reachable."

    return {
        "ok": True,
        "ready": status in {"fix_2d", "fix_3d"},
        "status": status,
        "configured_provider": configured_provider,
        "effective_provider": effective_provider,
        "summary": summary,
        "detected_devices": detected_devices,
        "gpsd": gpsd_report,
        "recommendations": _recommendations(status, detected_devices, gpsd_report),
    }


def diagnose_gps(
    config: SignomatConfig,
    host: str = GPSD_HOST,
    port: int = GPSD_PORT,
) -> dict[str, Any]:
    detected_devices = detect_candidate_devices()
    gpsd_report = query_gpsd(host=host, port=port)
    return build_gps_diagnosis(config, detected_devices, gpsd_report)

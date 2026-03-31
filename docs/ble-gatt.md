# BLE GATT Design

## Service UUIDs

Base UUID namespace: `7b1e0000-5d1f-4aa0-9a7d-6f5c0b6c1000`

- Device Service: `7b1e0001-5d1f-4aa0-9a7d-6f5c0b6c1000`
- Session Service: `7b1e0002-5d1f-4aa0-9a7d-6f5c0b6c1000`
- Diagnostics Service: `7b1e0003-5d1f-4aa0-9a7d-6f5c0b6c1000`

## Characteristics

- Device Status: `7b1e1001-5d1f-4aa0-9a7d-6f5c0b6c1000` (`read`, `notify`)
- Session State: `7b1e1002-5d1f-4aa0-9a7d-6f5c0b6c1000` (`read`, `notify`)
- Command Write: `7b1e1003-5d1f-4aa0-9a7d-6f5c0b6c1000` (`write`, `write-without-response`)
- Detection Summary: `7b1e1004-5d1f-4aa0-9a7d-6f5c0b6c1000` (`read`, `notify`)
- Upload Summary: `7b1e1005-5d1f-4aa0-9a7d-6f5c0b6c1000` (`read`, `notify`)
- Storage Status: `7b1e1006-5d1f-4aa0-9a7d-6f5c0b6c1000` (`read`, `notify`)
- GPS Status: `7b1e1007-5d1f-4aa0-9a7d-6f5c0b6c1000` (`read`, `notify`)

## Commands

Commands are tiny UTF-8 JSON payloads written to `Command Write`.

```json
{"cmd":"start_trip"}
{"cmd":"stop_trip"}
{"cmd":"start_recording"}
{"cmd":"stop_recording"}
{"cmd":"enable_inference"}
{"cmd":"disable_inference"}
{"cmd":"save_diagnostic_snapshot"}
```

## Payload Shape

Each characteristic carries its own compact JSON payload with short, stable keys:

Device Status:

```json
{"ble":true,"inf":true,"sync":"idle","temp_c":60.6}
```

Session State:

```json
{"trip":true,"rec":true,"trip_id":"2026-03-30_trip_001","det":14}
```

Detection Summary:

```json
{"det":14,"last":"stop","last_ts":"2026-03-30T14:12:03Z"}
```

Upload Summary:

```json
{"queue":29,"sync":"idle"}
```

Storage Status:

```json
{"free_mb":41823,"used_mb":10240,"total_mb":52163}
```

GPS Status:

```json
{"gps":"fix","fix":true,"lat":41.824,"lon":-71.4128,"spd":12.4,"head":93.0}
```

For local debugging before the GATT server is fully wired up, the Pi API exposes
these payloads at `/ble/payloads`.

Media transfer is intentionally excluded from the protocol.

## Pi Enablement

The packaged runtime now supports a real BlueZ-backed GATT server through
`dbus-fast`. Keep BLE disabled by default for safety, then enable it on the Pi
with either config or environment overrides:

```bash
SIGNOMAT_BLE_ENABLED=true
SIGNOMAT_BLE_MODE=bluez
SIGNOMAT_BLE_ADAPTER=hci0
SIGNOMAT_BLE_ADVERTISE_NAME=signomat-pi
```

For debugging without an iPhone client yet, the local API exposes the exact
characteristic payloads at `/ble/payloads`.

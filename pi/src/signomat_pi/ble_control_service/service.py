from __future__ import annotations

import logging

from signomat_pi.ble_control_service.bluez_backend import BlueZBackend
from signomat_pi.ble_control_service.protocol import CommandEnvelope, characteristic_payload_bytes, characteristic_payloads


LOGGER = logging.getLogger(__name__)


class BLEControlService:
    def __init__(self, config, runtime):
        self.config = config
        self.runtime = runtime
        self.connected = False
        self.mode = config.ble.mode
        self.backend = None

    def start(self) -> None:
        if not self.config.ble.enabled:
            return
        if self.mode == "bluez":
            self.backend = BlueZBackend(self)
            self.backend.start()
            if self.backend.running:
                LOGGER.info("BLE BlueZ server started")
            return
        LOGGER.info("BLE scaffold started in %s mode", self.mode)

    def stop(self) -> None:
        if self.backend:
            self.backend.stop()
            self.backend = None
        LOGGER.info("BLE scaffold stopped")

    def handle_command(self, raw: bytes) -> dict:
        envelope = CommandEnvelope.parse(raw)
        return self.runtime.dispatch_command(envelope.cmd)

    def status_payload(self) -> bytes:
        from signomat_pi.ble_control_service.protocol import compact_status

        return compact_status(self.runtime.status_snapshot(), self.runtime.gps_service.latest_sample())

    def characteristic_payloads(self) -> dict[str, dict]:
        return characteristic_payloads(self.runtime.status_snapshot(), self.runtime.gps_service.latest_sample())

    def characteristic_payload_bytes(self) -> dict[str, bytes]:
        return characteristic_payload_bytes(self.runtime.status_snapshot(), self.runtime.gps_service.latest_sample())

    def refresh(self) -> None:
        if self.backend:
            self.backend.refresh()

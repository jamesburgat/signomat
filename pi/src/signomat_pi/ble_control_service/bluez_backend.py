from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

from dbus_fast import BusType, DBusError, ErrorType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import PropertyAccess
from dbus_fast.service import ServiceInterface, dbus_method, dbus_property

from signomat_pi.ble_control_service.protocol import (
    COMMAND_CHAR_UUID,
    DETECTION_SUMMARY_CHAR_UUID,
    DEVICE_SERVICE_UUID,
    DEVICE_STATUS_CHAR_UUID,
    DIAGNOSTICS_SERVICE_UUID,
    GPS_STATUS_CHAR_UUID,
    SESSION_SERVICE_UUID,
    SESSION_STATE_CHAR_UUID,
    STORAGE_STATUS_CHAR_UUID,
    UPLOAD_SUMMARY_CHAR_UUID,
)


LOGGER = logging.getLogger(__name__)
BLUEZ_SERVICE = "org.bluez"
DBUS_PROPERTIES = "org.freedesktop.DBus.Properties"
DBUS_OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
ADAPTER_INTERFACE = "org.bluez.Adapter1"
GATT_MANAGER_INTERFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_INTERFACE = "org.bluez.LEAdvertisingManager1"
ADVERTISEMENT_INTERFACE = "org.bluez.LEAdvertisement1"

APP_ROOT_PATH = "/org/signomat"
DEVICE_SERVICE_PATH = f"{APP_ROOT_PATH}/device"
SESSION_SERVICE_PATH = f"{APP_ROOT_PATH}/session"
DIAGNOSTICS_SERVICE_PATH = f"{APP_ROOT_PATH}/diagnostics"
ADVERTISEMENT_PATH = f"{APP_ROOT_PATH}/advertisement0"


def _bluez_error(name: str, text: str) -> DBusError:
    return DBusError(f"org.bluez.Error.{name}", text)


def _dbus_bytes_to_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    return bytes(value)


class ApplicationObjectManager(ServiceInterface):
    def __init__(self, managed_objects_provider: Callable[[], dict[str, dict[str, dict[str, Variant]]]]):
        super().__init__(DBUS_OBJECT_MANAGER)
        self._managed_objects_provider = managed_objects_provider

    @dbus_method(name="GetManagedObjects")
    def get_managed_objects(self) -> "a{oa{sa{sv}}}":
        return self._managed_objects_provider()


class GattService(ServiceInterface):
    def __init__(self, path: str, uuid: str, primary: bool = True):
        super().__init__("org.bluez.GattService1")
        self.path = path
        self.uuid = uuid
        self.primary = primary

    @dbus_property(access=PropertyAccess.READ, name="UUID")
    def uuid_prop(self) -> "s":
        return self.uuid

    @dbus_property(access=PropertyAccess.READ, name="Primary")
    def primary_prop(self) -> "b":
        return self.primary


class GattCharacteristic(ServiceInterface):
    def __init__(
        self,
        path: str,
        uuid: str,
        service_path: str,
        flags: list[str],
        initial_value: bytes = b"",
    ):
        super().__init__("org.bluez.GattCharacteristic1")
        self.path = path
        self.uuid = uuid
        self.service_path = service_path
        self.flags = flags
        self._value = initial_value
        self._notifying_sessions = 0

    @dbus_property(access=PropertyAccess.READ, name="UUID")
    def uuid_prop(self) -> "s":
        return self.uuid

    @dbus_property(access=PropertyAccess.READ, name="Service")
    def service_prop(self) -> "o":
        return self.service_path

    @dbus_property(access=PropertyAccess.READ, name="Flags")
    def flags_prop(self) -> "as":
        return self.flags

    @dbus_property(access=PropertyAccess.READ, name="Notifying")
    def notifying_prop(self) -> "b":
        return self._notifying_sessions > 0

    @dbus_property(access=PropertyAccess.READ, name="Value")
    def value_prop(self) -> "ay":
        return self._value

    @dbus_method(name="ReadValue")
    def read_value(self, options: "a{sv}") -> "ay":
        if "read" not in self.flags:
            raise _bluez_error("NotSupported", "characteristic is not readable")
        return self._value

    @dbus_method(name="WriteValue")
    def write_value(self, value: "ay", options: "a{sv}") -> "":
        raise _bluez_error("NotSupported", "characteristic is not writable")

    @dbus_method(name="StartNotify")
    def start_notify(self) -> "":
        if "notify" not in self.flags:
            raise _bluez_error("NotSupported", "characteristic does not support notify")
        was_notifying = self._notifying_sessions > 0
        self._notifying_sessions += 1
        if not was_notifying:
            self.emit_properties_changed({"Notifying": True})

    @dbus_method(name="StopNotify")
    def stop_notify(self) -> "":
        if "notify" not in self.flags:
            raise _bluez_error("NotSupported", "characteristic does not support notify")
        if self._notifying_sessions == 0:
            return
        self._notifying_sessions -= 1
        if self._notifying_sessions == 0:
            self.emit_properties_changed({"Notifying": False})

    def set_value(self, value: bytes) -> None:
        if value == self._value:
            return
        self._value = value
        self.emit_properties_changed({"Value": self._value})

    def is_notifying(self) -> bool:
        return self._notifying_sessions > 0

    def object_properties(self) -> dict[str, Variant]:
        props = {
            "UUID": Variant("s", self.uuid),
            "Service": Variant("o", self.service_path),
            "Flags": Variant("as", self.flags),
            "Value": Variant("ay", self._value),
            "Notifying": Variant("b", self.is_notifying()),
        }
        return props


class StatusCharacteristic(GattCharacteristic):
    pass


class CommandCharacteristic(GattCharacteristic):
    def __init__(self, path: str, service_path: str, command_handler: Callable[[bytes], dict]):
        super().__init__(
            path=path,
            uuid=COMMAND_CHAR_UUID,
            service_path=service_path,
            flags=["write", "write-without-response"],
        )
        self._command_handler = command_handler

    @dbus_method(name="WriteValue")
    def write_value(self, value: "ay", options: "a{sv}") -> "":
        try:
            self._command_handler(_dbus_bytes_to_bytes(value))
        except Exception as exc:  # pragma: no cover - exercised through BLE writes on device
            raise _bluez_error("Failed", str(exc)) from exc

    def object_properties(self) -> dict[str, Variant]:
        return {
            "UUID": Variant("s", self.uuid),
            "Service": Variant("o", self.service_path),
            "Flags": Variant("as", self.flags),
        }


class Advertisement(ServiceInterface):
    def __init__(self, path: str, local_name: str, service_uuids: list[str]):
        super().__init__(ADVERTISEMENT_INTERFACE)
        self.path = path
        self.local_name = local_name[:11]
        self.service_uuids = service_uuids
        self.ad_type = "peripheral"

    @dbus_method(name="Release")
    def release(self) -> "":
        LOGGER.info("BLE advertisement released by BlueZ")

    @dbus_property(access=PropertyAccess.READ, name="Type")
    def type_prop(self) -> "s":
        return self.ad_type

    @dbus_property(access=PropertyAccess.READ, name="ServiceUUIDs")
    def service_uuids_prop(self) -> "as":
        return self.service_uuids

    @dbus_property(access=PropertyAccess.READ, name="LocalName")
    def local_name_prop(self) -> "s":
        return self.local_name

    @dbus_property(access=PropertyAccess.READ, name="Includes")
    def includes_prop(self) -> "as":
        return []


@dataclass
class BlueZApplication:
    parent: Any
    local_name: str

    def __post_init__(self) -> None:
        self.object_manager = ApplicationObjectManager(self.managed_objects)
        self.device_service = GattService(DEVICE_SERVICE_PATH, DEVICE_SERVICE_UUID)
        self.session_service = GattService(SESSION_SERVICE_PATH, SESSION_SERVICE_UUID)
        self.diagnostics_service = GattService(DIAGNOSTICS_SERVICE_PATH, DIAGNOSTICS_SERVICE_UUID)
        self.device_status = StatusCharacteristic(
            f"{DEVICE_SERVICE_PATH}/status",
            DEVICE_STATUS_CHAR_UUID,
            DEVICE_SERVICE_PATH,
            ["read", "notify"],
        )
        self.session_state = StatusCharacteristic(
            f"{SESSION_SERVICE_PATH}/state",
            SESSION_STATE_CHAR_UUID,
            SESSION_SERVICE_PATH,
            ["read", "notify"],
        )
        self.command = CommandCharacteristic(
            f"{SESSION_SERVICE_PATH}/command",
            SESSION_SERVICE_PATH,
            self.parent.handle_command,
        )
        self.detection_summary = StatusCharacteristic(
            f"{DIAGNOSTICS_SERVICE_PATH}/detection",
            DETECTION_SUMMARY_CHAR_UUID,
            DIAGNOSTICS_SERVICE_PATH,
            ["read", "notify"],
        )
        self.upload_summary = StatusCharacteristic(
            f"{DIAGNOSTICS_SERVICE_PATH}/upload",
            UPLOAD_SUMMARY_CHAR_UUID,
            DIAGNOSTICS_SERVICE_PATH,
            ["read", "notify"],
        )
        self.storage_status = StatusCharacteristic(
            f"{DIAGNOSTICS_SERVICE_PATH}/storage",
            STORAGE_STATUS_CHAR_UUID,
            DIAGNOSTICS_SERVICE_PATH,
            ["read", "notify"],
        )
        self.gps_status = StatusCharacteristic(
            f"{DIAGNOSTICS_SERVICE_PATH}/gps",
            GPS_STATUS_CHAR_UUID,
            DIAGNOSTICS_SERVICE_PATH,
            ["read", "notify"],
        )
        self.advertisement = Advertisement(
            ADVERTISEMENT_PATH,
            local_name=self.local_name,
            service_uuids=[DEVICE_SERVICE_UUID],
        )
        self.services = [
            self.device_service,
            self.session_service,
            self.diagnostics_service,
        ]
        self.characteristics = [
            self.device_status,
            self.session_state,
            self.command,
            self.detection_summary,
            self.upload_summary,
            self.storage_status,
            self.gps_status,
        ]

    def export_map(self) -> dict[str, ServiceInterface]:
        mapping: dict[str, ServiceInterface] = {APP_ROOT_PATH: self.object_manager}
        for service in self.services:
            mapping[service.path] = service
        for char in self.characteristics:
            mapping[char.path] = char
        mapping[self.advertisement.path] = self.advertisement
        return mapping

    def managed_objects(self) -> dict[str, dict[str, dict[str, Variant]]]:
        managed: dict[str, dict[str, dict[str, Variant]]] = {}
        for service in self.services:
            managed[service.path] = {
                "org.bluez.GattService1": {
                    "UUID": Variant("s", service.uuid),
                    "Primary": Variant("b", service.primary),
                }
            }
        for char in self.characteristics:
            managed[char.path] = {"org.bluez.GattCharacteristic1": char.object_properties()}
        return managed

    def refresh(self) -> None:
        payloads = self.parent.characteristic_payload_bytes()
        self.device_status.set_value(payloads[DEVICE_STATUS_CHAR_UUID])
        self.session_state.set_value(payloads[SESSION_STATE_CHAR_UUID])
        self.detection_summary.set_value(payloads[DETECTION_SUMMARY_CHAR_UUID])
        self.upload_summary.set_value(payloads[UPLOAD_SUMMARY_CHAR_UUID])
        self.storage_status.set_value(payloads[STORAGE_STATUS_CHAR_UUID])
        self.gps_status.set_value(payloads[GPS_STATUS_CHAR_UUID])

    def has_subscribers(self) -> bool:
        return any(char.is_notifying() for char in self.characteristics if isinstance(char, StatusCharacteristic))


class BlueZBackend:
    def __init__(self, parent: Any):
        self.parent = parent
        self.config = parent.config
        self.runtime = parent.runtime
        self.thread: threading.Thread | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ready = threading.Event()
        self.running = False
        self.start_error: Exception | None = None
        self.bus: MessageBus | None = None
        self.adapter_path: str | None = None
        self.application: BlueZApplication | None = None
        self.refresh_task: asyncio.Task | None = None
        self.refresh_interval = max(0.5, self.config.ble.refresh_interval_seconds)

    def start(self) -> None:
        if self.running:
            return
        self.ready.clear()
        self.start_error = None
        self.thread = threading.Thread(target=self._thread_main, name="signomat-ble", daemon=True)
        self.thread.start()
        self.ready.wait(timeout=10)
        if self.start_error:
            LOGGER.warning("BLE BlueZ backend unavailable: %s", self.start_error)
            return
        self.running = True

    def stop(self) -> None:
        if not self.loop:
            return
        future = asyncio.run_coroutine_threadsafe(self._async_stop(), self.loop)
        try:
            future.result(timeout=10)
        except Exception as exc:  # pragma: no cover - defensive shutdown path
            LOGGER.warning("BLE shutdown encountered an error: %s", exc)
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        self.thread = None
        self.loop = None
        self.running = False

    def refresh(self) -> None:
        if not self.loop or not self.application:
            return
        asyncio.run_coroutine_threadsafe(self._refresh_once(), self.loop)

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self.loop = loop
        asyncio.set_event_loop(loop)
        loop.create_task(self._async_start())
        try:
            loop.run_forever()
        finally:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    async def _async_start(self) -> None:
        try:
            self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            self.adapter_path = await self._resolve_adapter_path()
            local_name = self.config.ble.advertise_name or self.config.app.device_name
            self.application = BlueZApplication(self.parent, local_name=local_name)
            for path, interface in self.application.export_map().items():
                self.bus.export(path, interface)
            await self._configure_adapter()
            self.application.refresh()
            await self._register_application()
            await self._register_advertisement()
            self.refresh_task = asyncio.create_task(self._refresh_loop())
            LOGGER.info("BLE BlueZ backend registered on %s", self.adapter_path)
        except Exception as exc:  # pragma: no cover - depends on system bluetooth state
            self.start_error = exc
            LOGGER.exception("BLE BlueZ backend failed to start")
            await self._async_stop()
        finally:
            self.ready.set()

    async def _async_stop(self) -> None:
        if self.refresh_task:
            self.refresh_task.cancel()
            try:
                await self.refresh_task
            except asyncio.CancelledError:
                pass
            self.refresh_task = None
        if self.bus and self.adapter_path and self.application:
            try:
                await self._call_bluez(
                    path=self.adapter_path,
                    interface=LE_ADVERTISING_MANAGER_INTERFACE,
                    member="UnregisterAdvertisement",
                    signature="o",
                    body=[self.application.advertisement.path],
                )
            except Exception:
                pass
            try:
                await self._call_bluez(
                    path=self.adapter_path,
                    interface=GATT_MANAGER_INTERFACE,
                    member="UnregisterApplication",
                    signature="o",
                    body=[APP_ROOT_PATH],
                )
            except Exception:
                pass
        if self.bus and self.application:
            for path in reversed(list(self.application.export_map().keys())):
                self.bus.unexport(path)
        if self.bus:
            self.bus.disconnect()
        self.parent.connected = False
        self.application = None
        self.bus = None
        if self.loop and self.loop.is_running():
            self.loop.call_soon(self.loop.stop)

    async def _refresh_loop(self) -> None:
        while True:
            await self._refresh_once()
            await asyncio.sleep(self.refresh_interval)

    async def _refresh_once(self) -> None:
        if not self.application:
            return
        self.application.refresh()
        self.parent.connected = self.application.has_subscribers()

    async def _resolve_adapter_path(self) -> str:
        requested = self.config.ble.adapter
        body = await self._call_bluez(
            path="/",
            interface=DBUS_OBJECT_MANAGER,
            member="GetManagedObjects",
            signature="",
            body=[],
        )
        objects: dict[str, dict[str, dict[str, Any]]] = body[0]
        adapters = [
            path
            for path, interfaces in objects.items()
            if GATT_MANAGER_INTERFACE in interfaces and LE_ADVERTISING_MANAGER_INTERFACE in interfaces
        ]
        if requested:
            for path in adapters:
                if path.endswith(f"/{requested}"):
                    return path
            raise RuntimeError(f"Bluetooth adapter {requested!r} not found")
        if not adapters:
            raise RuntimeError("No BLE adapter with GATT and advertising support found")
        return adapters[0]

    async def _configure_adapter(self) -> None:
        assert self.adapter_path is not None
        alias = self.config.ble.advertise_name or self.config.app.device_name
        await self._set_adapter_property("Powered", Variant("b", True))
        await self._set_adapter_property("Pairable", Variant("b", True))
        await self._set_adapter_property("Alias", Variant("s", alias))
        if self.config.ble.discoverable:
            await self._set_adapter_property("Discoverable", Variant("b", True))

    async def _set_adapter_property(self, prop: str, value: Variant) -> None:
        assert self.adapter_path is not None
        try:
            await self._call_bluez(
                path=self.adapter_path,
                interface=DBUS_PROPERTIES,
                member="Set",
                signature="ssv",
                body=[ADAPTER_INTERFACE, prop, value],
            )
        except DBusError as exc:  # pragma: no cover - depends on controller support
            LOGGER.warning("Unable to set adapter property %s: %s", prop, exc)

    async def _register_application(self) -> None:
        assert self.adapter_path is not None
        await self._call_bluez(
            path=self.adapter_path,
            interface=GATT_MANAGER_INTERFACE,
            member="RegisterApplication",
            signature="oa{sv}",
            body=[APP_ROOT_PATH, {}],
        )

    async def _register_advertisement(self) -> None:
        assert self.adapter_path is not None and self.application is not None
        await self._call_bluez(
            path=self.adapter_path,
            interface=LE_ADVERTISING_MANAGER_INTERFACE,
            member="RegisterAdvertisement",
            signature="oa{sv}",
            body=[self.application.advertisement.path, {}],
        )

    async def _call_bluez(
        self,
        *,
        path: str,
        interface: str,
        member: str,
        signature: str,
        body: list[Any],
    ) -> list[Any]:
        if not self.bus:
            raise RuntimeError("BLE bus is not connected")
        message = Message(
            destination=BLUEZ_SERVICE,
            path=path,
            interface=interface,
            member=member,
            signature=signature,
            body=body,
        )
        reply = await self.bus.call(message)
        if reply is None:
            return []
        if reply.message_type is MessageType.ERROR:
            raise DBusError._from_message(reply)
        return reply.body

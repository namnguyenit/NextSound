from __future__ import annotations

import logging
from collections.abc import Callable

import dbus
import dbus.mainloop.glib
from gi.repository import GLib, GObject

from .constants import (
    ADAPTER_IFACE,
    AUDIO_SINK_UUID,
    AUDIO_SOURCE_UUID,
    BLUEZ_SERVICE,
    DEVICE_IFACE,
    OBJECT_MANAGER_IFACE,
    PROPERTIES_IFACE,
    TRANSPORT_IFACE,
)
from .models import BluetoothDevice, device_from_properties

LOG = logging.getLogger(__name__)

TRANSPORT_CODEC_NAMES = {
    0x00: "SBC",
    0x01: "MPEG",
    0x02: "AAC",
    0x04: "ATRAC",
    0xFF: "VENDOR",
}


def _configuration_bytes(configuration) -> bytes:
    try:
        return bytes(int(item) for item in configuration)
    except (TypeError, ValueError):
        return b""


def _is_ldac_configuration(data: bytes) -> bool:
    return (
        len(data) >= 6
        and int.from_bytes(data[:4], "little") == 0x0000012D
        and int.from_bytes(data[4:6], "little") == 0x00AA
    )


def transport_codec_name(value, configuration=()) -> str | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    data = _configuration_bytes(configuration)
    if number == 0xFF and _is_ldac_configuration(data):
        return "LDAC"
    return TRANSPORT_CODEC_NAMES.get(number, f"CODEC 0x{number:02X}")


AAC_FREQUENCIES = {
    0x800: 8000,
    0x400: 11025,
    0x200: 12000,
    0x100: 16000,
    0x080: 22050,
    0x040: 24000,
    0x020: 32000,
    0x010: 44100,
    0x008: 48000,
    0x004: 64000,
    0x002: 88200,
    0x001: 96000,
}


def transport_codec_details(codec_value, configuration) -> str | None:
    data = _configuration_bytes(configuration)
    codec = transport_codec_name(codec_value, data)
    if not codec:
        return None
    if codec == "LDAC" and len(data) >= 8:
        frequencies = {0x20: 44100, 0x10: 48000, 0x08: 88200, 0x04: 96000}
        modes = {0x01: "stereo", 0x02: "dual channel", 0x04: "mono"}
        frequency = next((rate for mask, rate in frequencies.items() if data[6] & mask), None)
        channels = next((name for mask, name in modes.items() if data[7] & mask), None)
        parts = [codec]
        if frequency:
            parts.append(f"{frequency / 1000:g} kHz")
        if channels:
            parts.append(channels)
        return " · ".join(parts)
    if codec != "AAC" or len(data) < 6:
        return codec

    frequency_mask = (data[1] << 4) | (data[2] >> 4)
    frequency = next(
        (rate for mask, rate in AAC_FREQUENCIES.items() if frequency_mask & mask),
        None,
    )
    channel_mask = (data[2] >> 2) & 0x03
    channels = "stereo" if channel_mask & 0x01 else "mono" if channel_mask & 0x02 else None
    vbr = bool(data[3] & 0x80)
    bitrate = ((data[3] & 0x7F) << 16) | (data[4] << 8) | data[5]

    parts = [codec]
    if frequency:
        parts.append(f"{frequency / 1000:g} kHz")
    if channels:
        parts.append(channels)
    if bitrate:
        parts.append(f"{bitrate // 1000} kbps")
    if vbr:
        parts.append("VBR")
    return " · ".join(parts)


class BluetoothError(RuntimeError):
    pass


def friendly_dbus_error(error: Exception) -> str:
    name = getattr(error, "get_dbus_name", lambda: "")()
    text = str(error)
    if name.endswith("NotReady"):
        return "Bluetooth chưa sẵn sàng. Hãy bật Bluetooth rồi thử lại."
    if name.endswith("NotPaired") or "not paired" in text.lower():
        return "Điện thoại chưa được ghép đôi với máy tính."
    if name.endswith("InProgress"):
        return "Một kết nối Bluetooth khác đang được xử lý."
    if name.endswith("ConnectionAttemptFailed") or name.endswith("Failed"):
        return "Không thể mở kết nối âm thanh. Hãy bật Bluetooth trên điện thoại và thử lại."
    if name.endswith("NotSupported"):
        return "Thiết bị này không hỗ trợ phát âm thanh A2DP đến máy tính."
    return text or "Lỗi Bluetooth không xác định."


class BluezBackend(GObject.Object):
    """Small BlueZ D-Bus client; PipeWire remains responsible for audio."""

    __gsignals__ = {
        "devices-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "adapter-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "scan-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
    }

    def __init__(self, bus: dbus.SystemBus | None = None) -> None:
        super().__init__()
        try:
            self.bus = bus or dbus.SystemBus(mainloop=dbus.mainloop.glib.DBusGMainLoop())
            root = self.bus.get_object(BLUEZ_SERVICE, "/")
            self.manager = dbus.Interface(root, OBJECT_MANAGER_IFACE)
            self._objects: dict = self.manager.GetManagedObjects()
        except Exception as error:
            raise BluetoothError(
                "Không kết nối được với BlueZ. Hãy cài và khởi động dịch vụ bluetooth."
            ) from error

        self._opened_paths: set[str] = set()
        self._scan_timeout_id: int | None = None
        self._subscribe()

    def _subscribe(self) -> None:
        self.bus.add_signal_receiver(
            self._interfaces_added,
            dbus_interface=OBJECT_MANAGER_IFACE,
            signal_name="InterfacesAdded",
        )
        self.bus.add_signal_receiver(
            self._interfaces_removed,
            dbus_interface=OBJECT_MANAGER_IFACE,
            signal_name="InterfacesRemoved",
        )
        self.bus.add_signal_receiver(
            self._properties_changed,
            dbus_interface=PROPERTIES_IFACE,
            signal_name="PropertiesChanged",
            path_keyword="object_path",
        )

    @property
    def adapter_path(self) -> str | None:
        for path, interfaces in self._objects.items():
            if ADAPTER_IFACE in interfaces:
                return str(path)
        return None

    @property
    def adapter_name(self) -> str:
        path = self.adapter_path
        if not path:
            return "Không có Bluetooth"
        props = self._objects[path][ADAPTER_IFACE]
        return str(props.get("Alias") or props.get("Name") or "Máy tính này")

    @property
    def powered(self) -> bool:
        path = self.adapter_path
        return bool(path and self._objects[path][ADAPTER_IFACE].get("Powered", False))

    @property
    def receiver_supported(self) -> bool:
        path = self.adapter_path
        if not path:
            return False
        uuids = (str(value).lower() for value in self._objects[path][ADAPTER_IFACE].get("UUIDs", ()))
        return AUDIO_SINK_UUID in uuids

    @property
    def discovering(self) -> bool:
        path = self.adapter_path
        return bool(path and self._objects[path][ADAPTER_IFACE].get("Discovering", False))

    def devices(self) -> list[BluetoothDevice]:
        result: list[BluetoothDevice] = []
        for path, interfaces in self._objects.items():
            if DEVICE_IFACE not in interfaces:
                continue
            device_path = str(path)
            transports = self._transports_for(device_path)
            opened = bool(transports) or device_path in self._opened_paths
            streaming = any(str(props.get("State", "")) == "active" for props in transports)
            active_transport = next(
                (props for props in transports if str(props.get("State", "")) == "active"),
                transports[0] if transports else None,
            )
            device = device_from_properties(
                device_path,
                interfaces[DEVICE_IFACE],
                receiver_open=opened,
                streaming=streaming,
                codec=transport_codec_name(
                    active_transport.get("Codec"), active_transport.get("Configuration", ())
                )
                if active_transport
                else None,
                codec_details=transport_codec_details(
                    active_transport.get("Codec"), active_transport.get("Configuration", ())
                )
                if active_transport
                else None,
            )
            # Unpaired devices frequently have no SDP UUIDs yet. The app follows
            # the Windows receiver workflow and shows paired A2DP sources only.
            if device.paired and device.can_stream_audio:
                result.append(device)
        return sorted(result, key=lambda item: (not item.receiver_open, item.name.casefold()))

    def _transports_for(self, device_path: str) -> list[dict]:
        transports = []
        prefix = device_path + "/"
        for path, interfaces in self._objects.items():
            if str(path).startswith(prefix) and TRANSPORT_IFACE in interfaces:
                properties = interfaces[TRANSPORT_IFACE]
                # MediaTransport.UUID describes the local endpoint role:
                # Audio Sink (0x110B) is phone -> computer. Ignore HFP/HSP and
                # the local Audio Source transport used for Bluetooth headsets.
                uuid = str(properties.get("UUID", "")).lower()
                if uuid and uuid != AUDIO_SINK_UUID:
                    continue
                transports.append(properties)
        return transports

    def set_powered(self, powered: bool) -> None:
        path = self.adapter_path
        if not path:
            raise BluetoothError("Máy tính không có bộ điều hợp Bluetooth.")
        props = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE, path), PROPERTIES_IFACE)
        props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(powered))

    def start_scan(self, seconds: int = 15) -> None:
        path = self.adapter_path
        if not path:
            raise BluetoothError("Máy tính không có bộ điều hợp Bluetooth.")
        if not self.powered:
            self.set_powered(True)
        adapter = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE, path), ADAPTER_IFACE)
        try:
            adapter.SetDiscoveryFilter({"Transport": dbus.String("bredr")})
            if not self.discovering:
                adapter.StartDiscovery()
        except dbus.DBusException as error:
            if not error.get_dbus_name().endswith("InProgress"):
                raise BluetoothError(friendly_dbus_error(error)) from error
        if self._scan_timeout_id:
            GLib.source_remove(self._scan_timeout_id)
        self._scan_timeout_id = GLib.timeout_add_seconds(seconds, self._scan_timeout)
        self.emit("scan-changed", True)

    def _scan_timeout(self) -> bool:
        # The timeout source is already being dispatched; removing it again
        # from stop_scan() causes GLib warnings on some versions.
        self._scan_timeout_id = None
        self.stop_scan()
        return GLib.SOURCE_REMOVE

    def stop_scan(self) -> None:
        if self._scan_timeout_id:
            GLib.source_remove(self._scan_timeout_id)
            self._scan_timeout_id = None
        path = self.adapter_path
        if path and self.discovering:
            try:
                dbus.Interface(
                    self.bus.get_object(BLUEZ_SERVICE, path), ADAPTER_IFACE
                ).StopDiscovery()
            except dbus.DBusException:
                LOG.debug("BlueZ had already stopped discovery", exc_info=True)
        self.emit("scan-changed", False)

    def open_receiver(
        self,
        device_path: str,
        on_success: Callable[[], None],
        on_error: Callable[[str], None],
    ) -> None:
        interfaces = self._objects.get(dbus.ObjectPath(device_path)) or self._objects.get(device_path)
        if not interfaces or DEVICE_IFACE not in interfaces:
            on_error("Điện thoại không còn khả dụng.")
            return
        props = interfaces[DEVICE_IFACE]
        if not bool(props.get("Paired", False)):
            on_error("Hãy ghép đôi điện thoại trước khi mở kết nối âm thanh.")
            return

        obj = self.bus.get_object(BLUEZ_SERVICE, device_path)
        properties = dbus.Interface(obj, PROPERTIES_IFACE)
        device = dbus.Interface(obj, DEVICE_IFACE)
        try:
            if not bool(props.get("Trusted", False)):
                properties.Set(DEVICE_IFACE, "Trusted", dbus.Boolean(True))
        except dbus.DBusException:
            LOG.warning("Could not mark device trusted", exc_info=True)

        self._opened_paths.add(device_path)
        self.emit("devices-changed")

        def finish_success() -> None:
            self._refresh_objects()
            if not self._transports_for(device_path):
                self._opened_paths.discard(device_path)
                self.emit("devices-changed")
                on_error("BlueZ đã kết nối thiết bị nhưng chưa mở được profile âm thanh A2DP.")
                return
            self.emit("devices-changed")
            on_success()

        def finish_failure(error: Exception) -> None:
            self._refresh_objects()
            # Device.Connect() may report a failure for an unrelated optional
            # profile after A2DP has already been configured successfully.
            if self._transports_for(device_path):
                finish_success()
                return
            self._opened_paths.discard(device_path)
            self.emit("devices-changed")
            on_error(friendly_dbus_error(error))

        def connect_profile() -> None:
            """Fallback when Connect() only opens an already-known profile."""
            try:
                device.ConnectProfile(
                    AUDIO_SOURCE_UUID,
                    timeout=20,
                    reply_handler=finish_success,
                    error_handler=finish_failure,
                )
            except dbus.DBusException as error:
                finish_failure(error)

        def connect_success() -> None:
            self._refresh_objects()
            if self._transports_for(device_path):
                finish_success()
            else:
                connect_profile()

        def connect_failure(error: Exception) -> None:
            name = getattr(error, "get_dbus_name", lambda: "")()
            self._refresh_objects()
            if self._transports_for(device_path):
                finish_success()
            elif name.endswith("AlreadyConnected"):
                connect_profile()
            else:
                finish_failure(error)

        # Connect() is intentional here. Some Android devices acknowledge a
        # source-only ConnectProfile() request but do not configure an A2DP
        # transport after the local codec endpoints have changed. Connect()
        # reliably reconnects the phone and lets BlueZ negotiate the selected
        # receiver endpoint.
        try:
            device.Connect(
                timeout=30,
                reply_handler=connect_success,
                error_handler=connect_failure,
            )
        except dbus.DBusException as error:
            connect_failure(error)

    def close_receiver(
        self,
        device_path: str,
        on_success: Callable[[], None],
        on_error: Callable[[str], None],
    ) -> None:
        obj = self.bus.get_object(BLUEZ_SERVICE, device_path)
        device = dbus.Interface(obj, DEVICE_IFACE)

        def finish() -> None:
            self._opened_paths.discard(device_path)
            self._refresh_objects()
            self.emit("devices-changed")
            on_success()

        def failure(error: Exception) -> None:
            name = getattr(error, "get_dbus_name", lambda: "")()
            if name.endswith("NotConnected"):
                finish()
                return
            on_error(friendly_dbus_error(error))

        try:
            device.DisconnectProfile(
                AUDIO_SOURCE_UUID,
                timeout=15,
                reply_handler=finish,
                error_handler=failure,
            )
        except dbus.DBusException as error:
            failure(error)

    def _refresh_objects(self) -> None:
        try:
            self._objects = self.manager.GetManagedObjects()
        except dbus.DBusException:
            LOG.debug("Unable to refresh BlueZ object cache", exc_info=True)

    def _interfaces_added(self, path: dbus.ObjectPath, interfaces: dict) -> None:
        current = self._objects.setdefault(path, {})
        current.update(interfaces)
        if DEVICE_IFACE in interfaces or TRANSPORT_IFACE in interfaces:
            self.emit("devices-changed")
        if ADAPTER_IFACE in interfaces:
            self.emit("adapter-changed")

    def _interfaces_removed(self, path: dbus.ObjectPath, interfaces: list[str]) -> None:
        current = self._objects.get(path, {})
        for interface in interfaces:
            current.pop(interface, None)
        if not current:
            self._objects.pop(path, None)
        if TRANSPORT_IFACE in interfaces:
            transport_path = str(path)
            for device_path in tuple(self._opened_paths):
                if (
                    transport_path.startswith(device_path + "/")
                    and not self._transports_for(device_path)
                ):
                    self._opened_paths.discard(device_path)
        if DEVICE_IFACE in interfaces or TRANSPORT_IFACE in interfaces:
            self.emit("devices-changed")
        if ADAPTER_IFACE in interfaces:
            self.emit("adapter-changed")

    def _properties_changed(
        self,
        interface: str,
        changed: dict,
        invalidated: list[str],
        object_path: dbus.ObjectPath,
    ) -> None:
        current = self._objects.setdefault(object_path, {}).setdefault(interface, {})
        current.update(changed)
        for key in invalidated:
            current.pop(key, None)
        if interface in (DEVICE_IFACE, TRANSPORT_IFACE):
            if interface == DEVICE_IFACE and not bool(current.get("Connected", False)):
                self._opened_paths.discard(str(object_path))
            self.emit("devices-changed")
        elif interface == ADAPTER_IFACE:
            if "Discovering" in changed:
                self.emit("scan-changed", bool(changed["Discovering"]))
            self.emit("adapter-changed")

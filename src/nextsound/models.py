from __future__ import annotations

from dataclasses import dataclass, field

from .constants import AUDIO_SOURCE_UUID


@dataclass(frozen=True, slots=True)
class BluetoothDevice:
    path: str
    address: str
    name: str
    paired: bool = False
    connected: bool = False
    trusted: bool = False
    uuids: tuple[str, ...] = field(default_factory=tuple)
    rssi: int | None = None
    receiver_open: bool = False
    streaming: bool = False
    codec: str | None = None
    codec_details: str | None = None

    @property
    def can_stream_audio(self) -> bool:
        return AUDIO_SOURCE_UUID in (uuid.lower() for uuid in self.uuids)

    @property
    def status_text(self) -> str:
        if self.streaming:
            return "Đang phát âm thanh"
        if self.receiver_open:
            return "Đã mở kết nối · chờ điện thoại phát"
        if self.connected:
            return "Đã kết nối Bluetooth"
        return "Sẵn sàng kết nối" if self.paired else "Chưa ghép đôi"


def device_from_properties(
    path: str,
    properties: dict,
    *,
    receiver_open: bool = False,
    streaming: bool = False,
    codec: str | None = None,
    codec_details: str | None = None,
) -> BluetoothDevice:
    """Convert D-Bus values to a UI-safe immutable model."""
    rssi = properties.get("RSSI")
    try:
        safe_rssi = int(rssi) if rssi is not None else None
    except (TypeError, ValueError):
        safe_rssi = None
    uuids = properties.get("UUIDs") or ()
    return BluetoothDevice(
        path=str(path),
        address=str(properties.get("Address", "")),
        name=str(
            properties.get("Alias")
            or properties.get("Name")
            or properties.get("Address")
            or "Thiết bị không rõ tên"
        ),
        paired=bool(properties.get("Paired", False)),
        connected=bool(properties.get("Connected", False)),
        trusted=bool(properties.get("Trusted", False)),
        uuids=tuple(str(value).lower() for value in uuids),
        rssi=safe_rssi,
        receiver_open=receiver_open,
        streaming=streaming,
        codec=codec,
        codec_details=codec_details,
    )

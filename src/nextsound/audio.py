from __future__ import annotations

import json
import glob
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .health import inotify_watch_available


@dataclass(frozen=True, slots=True)
class AudioOutput:
    name: str
    description: str
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class ReceiverStream:
    index: int
    address: str
    description: str
    codec: str
    volume_percent: int
    muted: bool = False


def _percent_from_volume(volume: dict) -> int:
    if not isinstance(volume, dict):
        return 100
    values = []
    for channel in volume.values():
        if not isinstance(channel, dict):
            continue
        raw = str(channel.get("value_percent", "0%")).rstrip("%")
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    return round(sum(values) / len(values)) if values else 100


class AudioBackend:
    """Controls the PulseAudio-compatible layer provided by PipeWire."""

    @staticmethod
    def _run(*args: str) -> str:
        completed = subprocess.run(
            ["pactl", *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
        )
        return completed.stdout.strip()

    def outputs(self) -> list[AudioOutput]:
        try:
            default = self._run("get-default-sink")
            raw = self._run("--format=json", "list", "sinks")
            sinks = json.loads(raw)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return []
        if not isinstance(sinks, list):
            return []
        result = []
        for sink in sinks:
            if not isinstance(sink, dict):
                continue
            name = str(sink.get("name", ""))
            description = str(sink.get("description") or name)
            if name:
                result.append(AudioOutput(name, description, name == default))
        return sorted(result, key=lambda output: (not output.is_default, output.description.casefold()))

    def set_default(self, sink_name: str) -> None:
        self._run("set-default-sink", sink_name)
        # Changing the default only affects new streams. Move already-playing
        # phone streams too so the selection in the UI takes effect at once.
        for stream in self.receiver_streams():
            try:
                self._run("move-sink-input", str(stream.index), sink_name)
            except (OSError, subprocess.SubprocessError):
                # A stream can disappear between listing and moving it.
                continue

    def receiver_streams(self) -> list[ReceiverStream]:
        """Return only phone -> computer A2DP playback streams."""
        try:
            raw = self._run("--format=json", "list", "sink-inputs")
            inputs = json.loads(raw)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            return []
        if not isinstance(inputs, list):
            return []
        result = []
        for stream in inputs:
            if not isinstance(stream, dict):
                continue
            props = stream.get("properties", {})
            if not isinstance(props, dict):
                continue
            if props.get("api.bluez5.profile") != "a2dp-source":
                continue
            address = str(props.get("api.bluez5.address", "")).upper()
            if not address:
                continue
            try:
                stream_index = int(stream["index"])
            except (KeyError, TypeError, ValueError):
                continue
            result.append(
                ReceiverStream(
                    index=stream_index,
                    address=address,
                    description=str(
                        props.get("device.description")
                        or props.get("media.name")
                        or address
                    ),
                    codec=str(props.get("api.bluez5.codec", "unknown")).upper(),
                    volume_percent=_percent_from_volume(stream.get("volume", {})),
                    muted=bool(stream.get("mute", False)),
                )
            )
        return result

    def set_receiver_volume(self, stream_index: int, percent: int) -> None:
        safe_percent = max(0, min(150, int(percent)))
        self._run("set-sink-input-volume", str(stream_index), f"{safe_percent}%")
        if safe_percent > 0:
            self._run("set-sink-input-mute", str(stream_index), "0")

    @staticmethod
    def _codec_plugin_paths() -> list[str]:
        patterns = (
            "/opt/nextsound/runtime/spa-0.2/bluez5/libspa-codec-bluez5-*.so",
            "/usr/lib*/spa-0.2/bluez5/libspa-codec-bluez5-*.so",
            "/usr/lib/*/spa-0.2/bluez5/libspa-codec-bluez5-*.so",
            "/usr/local/lib*/spa-0.2/bluez5/libspa-codec-bluez5-*.so",
            str(
                Path.home()
                / ".local/lib/nextsound/spa-0.2/bluez5/libspa-codec-bluez5-*.so"
            ),
        )
        paths = []
        for pattern in patterns:
            paths.extend(glob.glob(pattern))
        return list(dict.fromkeys(paths))

    @staticmethod
    def _aac_receiver_markers() -> tuple[Path, ...]:
        return (
            Path("/opt/nextsound/runtime/aac-receiver-0.3.48"),
            Path.home() / ".local/lib/nextsound/aac-receiver-0.3.48",
        )

    @classmethod
    def available_bluetooth_codecs(cls) -> set[str]:
        codecs: set[str] = set()
        for path in cls._codec_plugin_paths():
            name = path.rsplit("libspa-codec-bluez5-", 1)[-1].split(".so", 1)[0]
            codecs.add(name.lower())
        # The SBC plugin also implements SBC-XQ.
        if "sbc" in codecs:
            codecs.add("sbc_xq")
        return codecs

    @classmethod
    def aac_decoder_available(cls) -> bool:
        """Distinguish older encode-only AAC plugins from receiver-capable ones."""
        for path in cls._codec_plugin_paths():
            if not path.endswith("libspa-codec-bluez5-aac.so"):
                continue
            try:
                symbols = subprocess.run(
                    ["nm", "-D", path],
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                ).stdout
            except (OSError, subprocess.SubprocessError):
                continue
            if "aacDecoder_DecodeFrame" in symbols:
                return True
        return False

    @classmethod
    def aac_receiver_available(cls) -> bool:
        """Check both the AAC decoder and the old PipeWire buffer fix."""
        if not cls.aac_decoder_available():
            return False
        try:
            output = subprocess.run(
                ["pipewire", "--version"],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=3,
            ).stdout
            version_text = next(
                line.rsplit(" ", 1)[-1]
                for line in output.splitlines()
                if line.startswith("Compiled with libpipewire ")
            )
            version = tuple(int(part) for part in version_text.split(".")[:3])
        except (OSError, StopIteration, ValueError, subprocess.SubprocessError):
            version = (0, 0, 0)
        if version >= (0, 3, 52):
            return True
        return any(marker.is_file() for marker in cls._aac_receiver_markers())

    @classmethod
    def ldac_decoder_available(cls) -> bool:
        """Return true only for an LDAC plugin that can decode incoming audio.

        The commonly packaged PipeWire LDAC plugin links the public Sony/AOSP
        encoder library.  Seeing the plugin file alone therefore does not mean
        that Linux can act as an LDAC A2DP sink.
        """
        decoder_markers = (
            "ldacDecode",
            "ldacdecInit",
            "ldacBT_decode",
            "ldacBT_init_handle_decode",
        )
        for path in cls._codec_plugin_paths():
            if not path.endswith("libspa-codec-bluez5-ldac.so"):
                continue
            try:
                symbols = subprocess.run(
                    ["nm", "-D", path],
                    check=True,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                ).stdout
            except (OSError, subprocess.SubprocessError):
                continue
            if any(marker in symbols for marker in decoder_markers):
                return True
        return False

    @classmethod
    def receiver_codec_available(cls, codec: str) -> bool:
        codec = codec.upper()
        if codec == "SBC":
            return "sbc" in cls.available_bluetooth_codecs()
        if codec == "AAC":
            return cls.aac_receiver_available()
        if codec == "LDAC":
            return cls.ldac_decoder_available()
        return False

    @classmethod
    def available_receiver_codecs(cls) -> tuple[str, ...]:
        """Return codecs that can actually decode phone audio on this host."""
        return tuple(
            codec for codec in ("SBC", "AAC", "LDAC")
            if cls.receiver_codec_available(codec)
        )

    @staticmethod
    def _codec_state_path() -> Path:
        return Path.home() / ".config/nextsound/codec"

    def codec_preference(self) -> str:
        try:
            codec = self._codec_state_path().read_text(encoding="utf-8").strip().upper()
        except OSError:
            codec = ""
        if codec in {"SBC", "AAC", "LDAC"} and self.receiver_codec_available(codec):
            return codec
        return "AAC" if self.aac_receiver_available() else "SBC"

    @staticmethod
    def _wireplumber_is_legacy() -> bool:
        return Path("/usr/share/wireplumber/bluetooth.lua.d").is_dir()

    def set_codec_preference(self, codec: str) -> None:
        """Configure receiver codec preference and restart WirePlumber.

        Only the selected local A2DP Sink endpoint is advertised to phones, so
        BlueZ cannot silently keep using its previously selected receiver
        codec. Outgoing codecs remain enabled for Bluetooth headphones. A
        codec without a decoder is rejected before changing the configuration.
        """
        codec = codec.upper()
        if codec not in {"SBC", "AAC", "LDAC"}:
            raise ValueError(f"Codec không hợp lệ: {codec}")
        if not self.receiver_codec_available(codec):
            if codec == "LDAC":
                raise RuntimeError(
                    "PipeWire trên máy này chỉ có LDAC encoder, không có decoder để nhận từ điện thoại."
                )
            raise RuntimeError(f"Chưa có decoder {codec} để nhận âm thanh từ điện thoại.")

        inotify_ok, inotify_detail = inotify_watch_available()
        if not inotify_ok:
            raise RuntimeError(
                "Không thể đổi codec an toàn vì "
                f"{inotify_detail}. Đóng bớt VS Code/IDE rồi thử lại."
            )

        selected_codec = codec.lower()
        # bluez5.codecs is global: it controls both phone -> computer and
        # computer -> headphones. Keep every installed codec enabled globally
        # and use NextSound's patched bluez5.sink-codec property to restrict
        # only the local A2DP Sink endpoints used by phones.
        codec_order = ("sbc", "sbc_xq", "aac", "ldac", "faststream")
        available = self.available_bluetooth_codecs()
        enabled_codecs = [name for name in codec_order if name in available]
        if selected_codec not in enabled_codecs:
            enabled_codecs.append(selected_codec)
        codec_list = " ".join(enabled_codecs)
        config_root = Path.home() / ".config/wireplumber"
        legacy_path = config_root / "bluetooth.lua.d/54-nextsound-codec.lua"
        modern_path = config_root / "wireplumber.conf.d/54-nextsound-codec.conf"
        if self._wireplumber_is_legacy():
            target = legacy_path
            content = (
                "-- Managed by NextSound.\n"
                f'bluez_monitor.properties["bluez5.codecs"] = "[ {codec_list} ]"\n'
                f'bluez_monitor.properties["bluez5.sink-codec"] = "{selected_codec}"\n'
            )
            obsolete = modern_path
        else:
            target = modern_path
            content = (
                "# Managed by NextSound.\n"
                "monitor.bluez.properties = {\n"
                f"  bluez5.codecs = [ {codec_list} ]\n"
                f'  bluez5.sink-codec = "{selected_codec}"\n'
                "}\n"
            )
            obsolete = legacy_path

        state_path = self._codec_state_path()
        try:
            previous_target = target.read_bytes()
        except FileNotFoundError:
            previous_target = None
        try:
            previous_state = state_path.read_bytes()
        except FileNotFoundError:
            previous_state = None

        def restore(path: Path, previous: bytes | None) -> None:
            if previous is None:
                path.unlink(missing_ok=True)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(previous)

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(codec + "\n", encoding="utf-8")
            subprocess.run(
                ["systemctl", "--user", "restart", "wireplumber"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            for path, previous in (
                (target, previous_target),
                (state_path, previous_state),
            ):
                try:
                    restore(path, previous)
                except OSError:
                    pass
            # Best effort: bring WirePlumber back with the last known-good
            # configuration before reporting the original failure to the UI.
            try:
                subprocess.run(
                    ["systemctl", "--user", "restart", "wireplumber"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15,
                )
            except (OSError, subprocess.SubprocessError):
                pass
            raise
        obsolete.unlink(missing_ok=True)

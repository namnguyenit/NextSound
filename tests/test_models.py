import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nextsound.audio import AudioBackend, _percent_from_volume
from nextsound.backend import BluezBackend, transport_codec_details, transport_codec_name
from nextsound.constants import AUDIO_SINK_UUID, AUDIO_SOURCE_UUID, TRANSPORT_IFACE
from nextsound.models import BluetoothDevice, device_from_properties


class BluetoothDeviceTests(unittest.TestCase):
    def test_audio_source_is_accepted_case_insensitively(self):
        device = BluetoothDevice("/device", "AA:BB", "Phone", paired=True, uuids=(AUDIO_SOURCE_UUID.upper(),))
        self.assertTrue(device.can_stream_audio)

    def test_device_conversion_prefers_alias(self):
        device = device_from_properties(
            "/device",
            {
                "Address": "AA:BB",
                "Name": "Technical name",
                "Alias": "My phone",
                "Paired": True,
                "UUIDs": [AUDIO_SOURCE_UUID],
                "RSSI": -42,
            },
        )
        self.assertEqual(device.name, "My phone")
        self.assertEqual(device.rssi, -42)
        self.assertTrue(device.paired)

    def test_device_conversion_ignores_invalid_rssi_and_null_uuids(self):
        device = device_from_properties(
            "/device",
            {"Address": "AA:BB", "RSSI": "invalid", "UUIDs": None},
        )
        self.assertIsNone(device.rssi)
        self.assertEqual(device.uuids, ())

    def test_status_prioritizes_streaming(self):
        device = BluetoothDevice("/device", "AA:BB", "Phone", connected=True, receiver_open=True, streaming=True)
        self.assertEqual(device.status_text, "Đang phát âm thanh")

    def test_volume_percent_is_averaged(self):
        volume = {
            "left": {"value_percent": "120%"},
            "right": {"value_percent": "100%"},
        }
        self.assertEqual(_percent_from_volume(volume), 110)

    def test_invalid_volume_data_falls_back_safely(self):
        self.assertEqual(_percent_from_volume(None), 100)
        self.assertEqual(_percent_from_volume({"left": None}), 100)

    def test_bluez_aac_codec_number(self):
        self.assertEqual(transport_codec_name(2), "AAC")
        self.assertEqual(transport_codec_name(0), "SBC")

    def test_bluez_aac_configuration_details(self):
        # MPEG-2 AAC-LC, 44.1 kHz, stereo, VBR, 320 kbit/s.
        configuration = [128, 1, 4, 132, 226, 0]
        self.assertEqual(
            transport_codec_details(2, configuration),
            "AAC · 44.1 kHz · stereo · 320 kbps · VBR",
        )

    def test_bluez_ldac_vendor_configuration(self):
        # Sony vendor 0x012d, LDAC codec 0x00aa, 48 kHz, stereo.
        configuration = [0x2D, 0x01, 0x00, 0x00, 0xAA, 0x00, 0x10, 0x01]
        self.assertEqual(transport_codec_name(0xFF, configuration), "LDAC")
        self.assertEqual(
            transport_codec_details(0xFF, configuration),
            "LDAC · 48 kHz · stereo",
        )

    def test_receiver_codec_does_not_disable_headphone_codecs(self):
        backend = AudioBackend()
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch("nextsound.audio.Path.home", return_value=Path(directory)), \
                mock.patch.object(backend, "_wireplumber_is_legacy", return_value=True), \
                mock.patch.object(backend, "receiver_codec_available", return_value=True), \
                mock.patch.object(
                    backend,
                    "available_bluetooth_codecs",
                    return_value={"sbc", "sbc_xq", "aac", "ldac", "faststream"},
                ), \
                mock.patch("nextsound.audio.subprocess.run"):
            backend.set_codec_preference("SBC")
            config = (
                Path(directory)
                / ".config/wireplumber/bluetooth.lua.d/54-nextsound-codec.lua"
            ).read_text(encoding="utf-8")

        self.assertIn("[ sbc sbc_xq aac ldac faststream ]", config)
        self.assertIn('bluez5.sink-codec\"] = \"sbc\"', config)

    def test_set_default_moves_existing_receiver_streams(self):
        backend = AudioBackend()
        sink_inputs = json.dumps(
            [
                {
                    "index": 17,
                    "properties": {
                        "api.bluez5.profile": "a2dp-source",
                        "api.bluez5.address": "AA:BB:CC:DD:EE:FF",
                    },
                    "volume": {},
                },
                {
                    "index": 18,
                    "properties": {"application.name": "Music player"},
                },
            ]
        )

        def run(*args):
            if args == ("--format=json", "list", "sink-inputs"):
                return sink_inputs
            return ""

        with mock.patch.object(backend, "_run", side_effect=run) as pactl:
            backend.set_default("alsa_output.test")

        pactl.assert_any_call("set-default-sink", "alsa_output.test")
        pactl.assert_any_call("move-sink-input", "17", "alsa_output.test")
        self.assertNotIn(
            mock.call("move-sink-input", "18", "alsa_output.test"),
            pactl.call_args_list,
        )

    def test_receiver_streams_ignore_malformed_entries(self):
        backend = AudioBackend()
        payload = json.dumps(
            [
                None,
                {"properties": None},
                {
                    "properties": {
                        "api.bluez5.profile": "a2dp-source",
                        "api.bluez5.address": "AA:BB",
                    }
                },
            ]
        )
        with mock.patch.object(backend, "_run", return_value=payload):
            self.assertEqual(backend.receiver_streams(), [])

    def test_receiver_codec_list_only_reports_decoders(self):
        with mock.patch.object(
            AudioBackend,
            "receiver_codec_available",
            side_effect=lambda codec: codec in {"SBC", "LDAC"},
        ):
            self.assertEqual(AudioBackend.available_receiver_codecs(), ("SBC", "LDAC"))

    def test_codec_change_rolls_back_when_wireplumber_restart_fails(self):
        backend = AudioBackend()
        failure = subprocess.CalledProcessError(1, ["systemctl"])
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / ".config/wireplumber/bluetooth.lua.d/54-nextsound-codec.lua"
            state = home / ".config/nextsound/codec"
            config.parent.mkdir(parents=True)
            state.parent.mkdir(parents=True)
            config.write_text("old config\n", encoding="utf-8")
            state.write_text("AAC\n", encoding="utf-8")
            with mock.patch("nextsound.audio.Path.home", return_value=home), \
                    mock.patch.object(backend, "_wireplumber_is_legacy", return_value=True), \
                    mock.patch.object(backend, "receiver_codec_available", return_value=True), \
                    mock.patch.object(
                        backend, "available_bluetooth_codecs", return_value={"sbc", "aac"}
                    ), \
                    mock.patch(
                        "nextsound.audio.subprocess.run",
                        side_effect=[failure, subprocess.CompletedProcess([], 0)],
                    ):
                with self.assertRaises(subprocess.CalledProcessError):
                    backend.set_codec_preference("SBC")

            self.assertEqual(config.read_text(encoding="utf-8"), "old config\n")
            self.assertEqual(state.read_text(encoding="utf-8"), "AAC\n")

    def test_bluez_transport_filter_keeps_local_sink_and_ignores_headset(self):
        device_path = "/org/bluez/hci0/dev_AA_BB"
        fake_backend = mock.Mock()
        fake_backend._objects = {
            device_path + "/sep_source/fd0": {
                TRANSPORT_IFACE: {"UUID": AUDIO_SINK_UUID, "Codec": 2}
            },
            device_path + "/sep_sink/fd1": {
                TRANSPORT_IFACE: {"UUID": AUDIO_SOURCE_UUID, "Codec": 0}
            },
            device_path + "/sco": {
                TRANSPORT_IFACE: {
                    "UUID": "0000111e-0000-1000-8000-00805f9b34fb",
                    "Codec": 1,
                }
            },
        }

        transports = BluezBackend._transports_for(fake_backend, device_path)
        self.assertEqual(transports, [{"UUID": AUDIO_SINK_UUID, "Codec": 2}])

    def test_removed_transport_clears_optimistic_open_state(self):
        device_path = "/org/bluez/hci0/dev_AA_BB"
        transport_path = device_path + "/fd0"
        fake_backend = mock.Mock()
        fake_backend._objects = {
            transport_path: {TRANSPORT_IFACE: {"UUID": AUDIO_SINK_UUID}}
        }
        fake_backend._opened_paths = {device_path}
        fake_backend._transports_for = lambda path: BluezBackend._transports_for(
            fake_backend, path
        )

        BluezBackend._interfaces_removed(
            fake_backend, transport_path, [TRANSPORT_IFACE]
        )

        self.assertNotIn(device_path, fake_backend._opened_paths)


if __name__ == "__main__":
    unittest.main()

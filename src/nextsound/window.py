from __future__ import annotations

import subprocess
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .audio import AudioBackend, AudioOutput, ReceiverStream
from .backend import BluetoothError, BluezBackend
from .constants import BRAND_CREDIT
from .models import BluetoothDevice


class DeviceRow(Gtk.ListBoxRow):
    def __init__(
        self,
        device: BluetoothDevice,
        callback: Callable[[BluetoothDevice], None],
    ) -> None:
        super().__init__()
        self.device = device
        self.callback = callback
        self.set_activatable(False)
        self.set_selectable(False)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        content.set_margin_start(16)
        content.set_margin_end(16)

        icon = Gtk.Image.new_from_icon_name("phone-symbolic")
        icon.set_pixel_size(30)
        icon.add_css_class("device-icon")
        content.append(icon)

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        labels.set_hexpand(True)
        name = Gtk.Label(label=device.name, xalign=0)
        name.add_css_class("device-name")
        status = Gtk.Label(label=device.status_text, xalign=0)
        status.add_css_class("dim-label")
        status.add_css_class("caption")
        labels.append(name)
        labels.append(status)
        content.append(labels)

        if device.streaming:
            active = Gtk.Spinner()
            active.start()
            content.append(active)

        self.action = Gtk.Button()
        self.action.set_valign(Gtk.Align.CENTER)
        self.action.connect("clicked", lambda _button: self.callback(self.device))
        if device.receiver_open:
            self.action.set_label("Dừng")
            self.action.add_css_class("destructive-action")
            self.action.set_tooltip_text("Đóng kết nối A2DP từ điện thoại")
        else:
            self.action.set_label("Phát")
            self.action.add_css_class("suggested-action")
            self.action.set_tooltip_text("Dùng máy tính như một loa Bluetooth")
        self._idle_label = self.action.get_label()
        content.append(self.action)
        self.set_child(content)

    def set_busy(self, busy: bool) -> None:
        self.action.set_sensitive(not busy)
        self.action.set_label("Đang xử lý…" if busy else self._idle_label)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application, backend: BluezBackend) -> None:
        super().__init__(application=application)
        self.backend = backend
        self.audio = AudioBackend()
        self.rows: dict[str, DeviceRow] = {}
        self.outputs: list[AudioOutput] = []
        self._outputs_initialized = False
        self.receiver_stream: ReceiverStream | None = None
        self._changing_output = False
        self._changing_volume = False
        self._changing_codec = False
        self._volume_timeout_id: int | None = None
        self.codec_options = ("SBC", "AAC", "LDAC")
        self._codec_preference = self.audio.codec_preference()
        # Codec probing uses nm on native plugins. Cache it for this app run
        # instead of spawning those checks once per second while idle.
        self._receiver_codecs = self.audio.available_receiver_codecs()
        self._bluetooth_codecs = self.audio.available_bluetooth_codecs()

        self.set_title("NextSound")
        self.set_default_size(660, 680)
        self.set_size_request(420, 460)

        self.overlay = Adw.ToastOverlay()
        self.set_content(self.overlay)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.overlay.set_child(page)

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label="NextSound"))
        self.scan_button = Gtk.Button(icon_name="view-refresh-symbolic")
        self.scan_button.set_tooltip_text("Quét lại thiết bị")
        self.scan_button.connect("clicked", self._scan)
        header.pack_start(self.scan_button)
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu = Gio.Menu()
        menu.append("Cài đặt Bluetooth", "app.bluetooth-settings")
        menu.append("Giới thiệu", "app.about")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)
        page.append(header)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        page.append(scroller)
        clamp = Adw.Clamp(maximum_size=620, tightening_threshold=500)
        clamp.set_margin_top(28)
        clamp.set_margin_bottom(28)
        clamp.set_margin_start(18)
        clamp.set_margin_end(18)
        scroller.set_child(clamp)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        clamp.set_child(body)

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        hero_icon = Gtk.Image.new_from_icon_name("audio-speakers-symbolic")
        hero_icon.set_pixel_size(72)
        hero_icon.add_css_class("hero-icon")
        title = Gtk.Label(label="Biến máy tính thành loa Bluetooth")
        title.add_css_class("title-2")
        subtitle = Gtk.Label(
            label="Chọn điện thoại đã ghép đôi, nhấn Phát, rồi mở nhạc trên điện thoại."
        )
        subtitle.set_wrap(True)
        subtitle.set_justify(Gtk.Justification.CENTER)
        subtitle.add_css_class("dim-label")
        hero.append(hero_icon)
        hero.append(title)
        hero.append(subtitle)
        brand_badge = Gtk.Label(label=BRAND_CREDIT)
        brand_badge.set_halign(Gtk.Align.CENTER)
        brand_badge.add_css_class("brand-badge")
        hero.append(brand_badge)
        body.append(hero)

        self.readiness = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.readiness.add_css_class("status-card")
        self.readiness_icon = Gtk.Image()
        self.readiness_label = Gtk.Label(xalign=0)
        self.readiness_label.set_hexpand(True)
        self.readiness_label.set_wrap(True)
        self.power_button = Gtk.Button(label="Bật Bluetooth")
        self.power_button.connect("clicked", self._power_on)
        self.readiness.append(self.readiness_icon)
        self.readiness.append(self.readiness_label)
        self.readiness.append(self.power_button)
        body.append(self.readiness)

        output_group = Adw.PreferencesGroup(title="Phát ra")
        output_row = Adw.ActionRow(title="Loa của máy tính")
        output_row.set_subtitle("Luồng từ điện thoại sẽ đi đến thiết bị âm thanh này")
        self.output_model = Gtk.StringList()
        self.output_dropdown = Gtk.DropDown(model=self.output_model)
        self.output_dropdown.set_valign(Gtk.Align.CENTER)
        self.output_dropdown.set_size_request(220, -1)
        self.output_dropdown.connect("notify::selected", self._output_changed)
        output_row.add_suffix(self.output_dropdown)
        output_group.add(output_row)

        self.volume_row = Adw.ActionRow(title="Âm lượng điện thoại")
        self.volume_row.set_subtitle("Bắt đầu phát trên điện thoại để điều chỉnh")
        volume_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        volume_box.set_valign(Gtk.Align.CENTER)
        self.volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 1)
        self.volume_scale.set_size_request(210, -1)
        self.volume_scale.set_draw_value(False)
        self.volume_scale.set_value(100)
        self.volume_scale.add_mark(100, Gtk.PositionType.BOTTOM, None)
        self.volume_scale.set_sensitive(False)
        self.volume_scale.connect("value-changed", self._volume_changed)
        self.volume_value = Gtk.Label(label="100%")
        self.volume_value.set_width_chars(4)
        volume_box.append(self.volume_scale)
        volume_box.append(self.volume_value)
        self.volume_row.add_suffix(volume_box)
        output_group.add(self.volume_row)

        self.codec_row = Adw.ActionRow(title="Chọn codec nhận")
        self.codec_value = Gtk.Label(label="Chưa kết nối")
        self.codec_value.add_css_class("dim-label")
        self.codec_value.set_tooltip_text("Codec thực tế đang được điện thoại sử dụng")
        self.codec_model = Gtk.StringList.new(list(self.codec_options))
        self.codec_dropdown = Gtk.DropDown(model=self.codec_model)
        self.codec_dropdown.set_valign(Gtk.Align.CENTER)
        self.codec_dropdown.set_size_request(110, -1)
        self.codec_dropdown.set_tooltip_text(
            "Chọn SBC, AAC hoặc LDAC để nhận âm thanh từ điện thoại"
        )
        self._changing_codec = True
        self.codec_dropdown.set_selected(self.codec_options.index(self._codec_preference))
        self._changing_codec = False
        self.codec_dropdown.connect("notify::selected", self._codec_changed)
        self.codec_row.add_suffix(self.codec_value)
        self.codec_row.add_suffix(self.codec_dropdown)
        output_group.add(self.codec_row)
        body.append(output_group)

        devices_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        device_title = Gtk.Label(label="Điện thoại đã ghép đôi", xalign=0)
        device_title.add_css_class("heading")
        device_title.set_hexpand(True)
        pair_button = Gtk.Button(label="Ghép đôi thiết bị mới")
        pair_button.add_css_class("flat")
        pair_button.connect("clicked", lambda _button: self._open_bluetooth_settings())
        heading.append(device_title)
        heading.append(pair_button)
        devices_box.append(heading)

        self.device_list = Gtk.ListBox()
        self.device_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.device_list.add_css_class("boxed-list")
        devices_box.append(self.device_list)

        self.empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.empty.set_margin_top(30)
        self.empty.set_margin_bottom(30)
        empty_icon = Gtk.Image.new_from_icon_name("phone-symbolic")
        empty_icon.set_pixel_size(42)
        empty_title = Gtk.Label(label="Chưa tìm thấy điện thoại phù hợp")
        empty_title.add_css_class("heading")
        empty_help = Gtk.Label(
            label="Ghép đôi điện thoại trong Cài đặt Bluetooth, sau đó quay lại và quét lại."
        )
        empty_help.set_wrap(True)
        empty_help.set_justify(Gtk.Justification.CENTER)
        empty_help.add_css_class("dim-label")
        self.empty.append(empty_icon)
        self.empty.append(empty_title)
        self.empty.append(empty_help)
        devices_box.append(self.empty)
        body.append(devices_box)

        note = Gtk.Label(
            label="NextSound dùng A2DP cho âm thanh stereo. Cuộc gọi Bluetooth (HFP) chưa thuộc phạm vi bản đầu tiên."
        )
        note.set_wrap(True)
        note.set_xalign(0)
        note.add_css_class("dim-label")
        note.add_css_class("caption")
        body.append(note)

        brand_separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        brand_separator.set_margin_top(2)
        body.append(brand_separator)
        brand_watermark = Gtk.Label(label=BRAND_CREDIT)
        brand_watermark.set_halign(Gtk.Align.CENTER)
        brand_watermark.set_tooltip_text("NextSound — Made by TrungCao")
        brand_watermark.add_css_class("brand-watermark")
        body.append(brand_watermark)

        backend.connect("devices-changed", lambda *_args: self.refresh_devices())
        backend.connect("adapter-changed", lambda *_args: self.refresh_adapter())
        backend.connect("scan-changed", self._scan_changed)
        self.refresh_adapter()
        self.refresh_outputs()
        self.refresh_devices()
        self.refresh_stream_controls()
        GLib.timeout_add_seconds(1, self._poll_audio_state)

    def toast(self, message: str) -> None:
        self.overlay.add_toast(Adw.Toast.new(message))

    def refresh_adapter(self) -> None:
        if not self.backend.adapter_path:
            self.readiness_icon.set_from_icon_name("dialog-error-symbolic")
            self.readiness_label.set_label("Không tìm thấy bộ điều hợp Bluetooth trên máy tính.")
            self.power_button.set_visible(False)
        elif not self.backend.powered:
            self.readiness_icon.set_from_icon_name("bluetooth-disabled-symbolic")
            self.readiness_label.set_label("Bluetooth đang tắt.")
            self.power_button.set_visible(True)
        elif not self.backend.receiver_supported:
            self.readiness_icon.set_from_icon_name("dialog-warning-symbolic")
            self.readiness_label.set_label(
                "BlueZ chưa công bố vai trò Audio Sink. Chạy nextsound-doctor để xem cách sửa."
            )
            self.power_button.set_visible(False)
        else:
            self.readiness_icon.set_from_icon_name("emblem-ok-symbolic")
            self.readiness_label.set_label(
                f"{self.backend.adapter_name} đã sẵn sàng nhận âm thanh A2DP."
            )
            self.power_button.set_visible(False)
        self.scan_button.set_sensitive(bool(self.backend.adapter_path))

    def refresh_outputs(self) -> None:
        outputs = self.audio.outputs()
        if self._outputs_initialized and outputs == self.outputs:
            return
        self._outputs_initialized = True
        self.outputs = outputs
        self._changing_output = True
        self.output_model.splice(0, self.output_model.get_n_items(), [])
        selected = Gtk.INVALID_LIST_POSITION
        for index, output in enumerate(self.outputs):
            self.output_model.append(output.description)
            if output.is_default:
                selected = index
        self.output_dropdown.set_selected(selected)
        self.output_dropdown.set_sensitive(bool(self.outputs))
        self._changing_output = False

    def refresh_devices(self) -> None:
        child = self.device_list.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.device_list.remove(child)
            child = next_child
        self.rows.clear()
        devices = self.backend.devices()
        for device in devices:
            row = DeviceRow(device, self._toggle_receiver)
            self.rows[device.path] = row
            self.device_list.append(row)
        self.device_list.set_visible(bool(devices))
        self.empty.set_visible(not devices)
        self.refresh_stream_controls()

    def refresh_stream_controls(self) -> None:
        streams = self.audio.receiver_streams()
        devices = self.backend.devices()
        streaming_addresses = {device.address.upper() for device in devices if device.streaming}
        negotiated_device = next(
            (device for device in devices if device.receiver_open and device.codec), None
        )
        self.receiver_stream = next(
            (stream for stream in streams if stream.address in streaming_addresses),
            streams[0] if streams else None,
        )
        stream_device = next(
            (
                device
                for device in devices
                if self.receiver_stream and device.address.upper() == self.receiver_stream.address
            ),
            None,
        )
        self._changing_volume = True
        if self.receiver_stream:
            stream = self.receiver_stream
            self.volume_scale.set_sensitive(True)
            self.volume_scale.set_value(stream.volume_percent)
            self.volume_value.set_label(f"{stream.volume_percent}%")
            self.volume_row.set_subtitle(f"Điều chỉnh riêng âm thanh từ {stream.description}")
            self.codec_value.set_label(stream.codec)
            if stream_device and stream_device.codec_details:
                self.codec_row.set_subtitle(
                    f"Thực tế: {stream_device.codec_details} · ưu tiên {self._codec_preference}"
                )
            else:
                self.codec_row.set_subtitle(
                    f"Thực tế: {stream.codec} · ưu tiên {self._codec_preference}"
                )
        else:
            self.volume_scale.set_sensitive(False)
            self.volume_scale.set_value(100)
            self.volume_value.set_label("100%")
            self.volume_row.set_subtitle("Bắt đầu phát trên điện thoại để điều chỉnh")
            negotiated_codec = negotiated_device.codec if negotiated_device else None
            self.codec_value.set_label(negotiated_codec or "Chưa kết nối")
            if negotiated_device and negotiated_device.codec_details:
                self.codec_row.set_subtitle(
                    f"Đã thương lượng {negotiated_device.codec_details} · chờ điện thoại phát"
                )
            elif negotiated_codec:
                self.codec_row.set_subtitle(
                    f"Kết nối hiện chọn {negotiated_codec} · ưu tiên {self._codec_preference}"
                )
            elif self._receiver_codecs:
                codecs = ", ".join(self._receiver_codecs)
                self.codec_row.set_subtitle(
                    f"Ưu tiên {self._codec_preference} · sẵn sàng nhận {codecs}"
                )
            elif "aac" in self._bluetooth_codecs:
                self.codec_row.set_subtitle("Plugin AAC này chỉ encode, chưa nhận AAC được")
            else:
                self.codec_row.set_subtitle("Plugin AAC chưa được cài trên máy này")
        self._changing_volume = False

    def _poll_audio_state(self) -> bool:
        self.refresh_outputs()
        self.refresh_stream_controls()
        return GLib.SOURCE_CONTINUE

    def _volume_changed(self, scale: Gtk.Scale) -> None:
        if self._changing_volume:
            return
        percent = round(scale.get_value())
        self.volume_value.set_label(f"{percent}%")
        self.volume_row.set_subtitle(
            "Khuếch đại phần mềm; mức trên 100% có thể gây méo tiếng"
            if percent > 100
            else f"Điều chỉnh riêng âm thanh từ {self.receiver_stream.description}"
            if self.receiver_stream
            else "Bắt đầu phát trên điện thoại để điều chỉnh"
        )
        if self._volume_timeout_id:
            GLib.source_remove(self._volume_timeout_id)
        stream_index = self.receiver_stream.index if self.receiver_stream else None
        self._volume_timeout_id = GLib.timeout_add(
            120, self._apply_volume, percent, stream_index
        )

    def _apply_volume(self, percent: int, stream_index: int | None) -> bool:
        self._volume_timeout_id = None
        if stream_index is None:
            return GLib.SOURCE_REMOVE
        try:
            self.audio.set_receiver_volume(stream_index, percent)
        except Exception:
            self.toast("Không thể thay đổi âm lượng điện thoại.")
        return GLib.SOURCE_REMOVE

    def _set_codec_dropdown(self, codec: str) -> None:
        self._changing_codec = True
        self.codec_dropdown.set_selected(self.codec_options.index(codec))
        self._changing_codec = False

    def _codec_changed(self, dropdown: Gtk.DropDown, _param) -> None:
        if self._changing_codec:
            return
        selected = dropdown.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION or selected >= len(self.codec_options):
            return
        codec = self.codec_options[selected]
        previous = self._codec_preference
        if codec == previous:
            return
        if not self.audio.receiver_codec_available(codec):
            self._set_codec_dropdown(previous)
            if codec == "LDAC":
                self.toast(
                    "LDAC chưa thể nhận: hãy chạy ./scripts/install-ldac-user.sh trước."
                )
            else:
                self.toast(f"Máy này chưa có decoder {codec} để nhận từ điện thoại.")
            return

        opened_device = next(
            (device for device in self.backend.devices() if device.receiver_open), None
        )
        self.codec_dropdown.set_sensitive(False)

        def apply_change() -> None:
            try:
                self.audio.set_codec_preference(codec)
            except Exception as error:
                self._set_codec_dropdown(previous)
                self.codec_dropdown.set_sensitive(True)
                self.toast(f"Không đổi được codec: {error}")
                if opened_device:
                    GLib.timeout_add_seconds(
                        2,
                        self._reopen_after_codec,
                        opened_device.path,
                        previous,
                    )
                return
            self._codec_preference = codec
            self._receiver_codecs = self.audio.available_receiver_codecs()
            self._bluetooth_codecs = self.audio.available_bluetooth_codecs()
            self.codec_dropdown.set_sensitive(True)
            self.codec_row.set_subtitle(f"Đã ưu tiên {codec} trong WirePlumber")
            if opened_device:
                self.toast(f"Đã chọn {codec}; đang kết nối lại điện thoại…")
                GLib.timeout_add_seconds(2, self._reopen_after_codec, opened_device.path, codec)
            else:
                self.toast(f"Đã chọn {codec}. Nhấn Phát để dùng codec mới.")

        def close_error(message: str) -> None:
            self._set_codec_dropdown(previous)
            self.codec_dropdown.set_sensitive(True)
            self.toast(f"Không thể ngắt kết nối để đổi codec: {message}")

        if opened_device:
            self.backend.close_receiver(opened_device.path, apply_change, close_error)
        else:
            apply_change()

    def _reopen_after_codec(self, device_path: str, codec: str) -> bool:
        def success() -> None:
            self.toast(f"Đã kết nối lại bằng ưu tiên {codec}.")
            self.refresh_devices()

        def error(message: str) -> None:
            self.toast(f"Đã đổi codec nhưng chưa kết nối lại được: {message}")
            self.refresh_devices()

        self.backend.open_receiver(device_path, success, error)
        return GLib.SOURCE_REMOVE

    def _toggle_receiver(self, device: BluetoothDevice) -> None:
        row = self.rows.get(device.path)
        if row:
            row.set_busy(True)
        success_text = (
            "Đã đóng kết nối âm thanh."
            if device.receiver_open
            else "Đã mở kết nối. Bây giờ hãy phát âm thanh trên điện thoại."
        )

        def success() -> None:
            self.toast(success_text)
            self.refresh_devices()

        def error(message: str) -> None:
            self.toast(message)
            self.refresh_devices()

        if device.receiver_open:
            self.backend.close_receiver(device.path, success, error)
        else:
            self.backend.open_receiver(device.path, success, error)

    def _scan(self, _button: Gtk.Button) -> None:
        try:
            if self.backend.discovering:
                self.backend.stop_scan()
            else:
                self.backend.start_scan()
        except BluetoothError as error:
            self.toast(str(error))

    def _scan_changed(self, _backend: BluezBackend, scanning: bool) -> None:
        self.scan_button.set_icon_name("process-stop-symbolic" if scanning else "view-refresh-symbolic")
        self.scan_button.set_tooltip_text("Dừng quét" if scanning else "Quét lại thiết bị")

    def _power_on(self, _button: Gtk.Button) -> None:
        try:
            self.backend.set_powered(True)
        except Exception as error:
            self.toast(str(error))

    def _output_changed(self, dropdown: Gtk.DropDown, _param) -> None:
        if self._changing_output:
            return
        selected = dropdown.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION or selected >= len(self.outputs):
            return
        try:
            self.audio.set_default(self.outputs[selected].name)
            self.toast(f"Âm thanh sẽ phát qua {self.outputs[selected].description}.")
        except Exception:
            self.toast("Không thể đổi loa đầu ra.")
            self.refresh_outputs()

    def _open_bluetooth_settings(self) -> None:
        try:
            Gio.Subprocess.new(
                ["gnome-control-center", "bluetooth"],
                Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
        except GLib.Error:
            try:
                subprocess.Popen(["blueman-manager"], start_new_session=True)
            except OSError:
                self.toast("Không mở được Cài đặt Bluetooth. Hãy mở từ menu hệ thống.")

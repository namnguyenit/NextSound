from __future__ import annotations

import logging

import dbus.mainloop.glib
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from . import __version__
from .backend import BluetoothError, BluezBackend
from .constants import APP_ID, BRAND_CREDIT
from .window import MainWindow


class NextSoundApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window: MainWindow | None = None
        self.backend: BluezBackend | None = None
        self._add_action("quit", self.quit, ["<primary>q"])
        self._add_action("bluetooth-settings", self._open_settings)
        self._add_action("about", self._about)

    def _add_action(self, name, callback, shortcuts=None) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", lambda *_args: callback())
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b"""
            .hero-icon { color: @accent_color; margin-bottom: 4px; }
            .device-icon { color: @accent_color; }
            .device-name { font-weight: 600; }
            .status-card {
                padding: 12px 14px;
                border-radius: 12px;
                background: alpha(@accent_bg_color, 0.10);
            }
            .brand-badge {
                padding: 4px 10px;
                border-radius: 999px;
                background: alpha(@accent_bg_color, 0.12);
                color: @accent_color;
                font-size: 11px;
                font-weight: 700;
            }
            .brand-watermark {
                color: alpha(@window_fg_color, 0.45);
                font-size: 11px;
                font-weight: 600;
                padding: 8px 0 2px;
            }
            """
        )
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def do_activate(self) -> None:
        if self.window:
            self.window.present()
            return
        try:
            self.backend = BluezBackend()
        except BluetoothError as error:
            dialog = Gtk.MessageDialog(
                transient_for=None,
                modal=True,
                buttons=Gtk.ButtonsType.CLOSE,
                message_type=Gtk.MessageType.ERROR,
                text="Không thể khởi động NextSound",
                secondary_text=str(error),
            )
            dialog.connect("response", lambda *_args: self.quit())
            dialog.present()
            return
        self.window = MainWindow(self, self.backend)
        self.window.present()

    def _open_settings(self) -> None:
        if self.window:
            self.window._open_bluetooth_settings()

    def _about(self) -> None:
        dialog = Gtk.AboutDialog(
            transient_for=self.window,
            modal=True,
            program_name="NextSound",
            version=__version__,
            comments=f"Biến máy tính Ubuntu/Linux thành loa Bluetooth A2DP.\n\n{BRAND_CREDIT}",
            license_type=Gtk.License.MIT_X11,
            authors=[BRAND_CREDIT],
            copyright=BRAND_CREDIT,
        )
        dialog.present()


def run() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    return NextSoundApplication().run(None)

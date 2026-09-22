from __future__ import annotations

import shutil
import subprocess
import sys

import dbus

from .audio import AudioBackend
from .constants import ADAPTER_IFACE, AUDIO_SINK_UUID, BLUEZ_SERVICE, OBJECT_MANAGER_IFACE
from .health import inotify_watch_available


def command_ok(command: str) -> bool:
    return shutil.which(command) is not None


def service_active(name: str, *, user: bool = False) -> bool:
    args = ["systemctl"]
    if user:
        args.append("--user")
    args.extend(["is-active", "--quiet", name])
    try:
        return subprocess.run(args, timeout=3).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def bluez_receiver_ready() -> tuple[bool, str]:
    try:
        bus = dbus.SystemBus()
        root = bus.get_object(BLUEZ_SERVICE, "/")
        objects = dbus.Interface(root, OBJECT_MANAGER_IFACE).GetManagedObjects()
        adapters = []
        for _path, interfaces in objects.items():
            if ADAPTER_IFACE not in interfaces:
                continue
            props = interfaces[ADAPTER_IFACE]
            adapters.append(props)
            uuids = {str(item).lower() for item in props.get("UUIDs", ())}
            if AUDIO_SINK_UUID in uuids:
                return True, str(props.get("Alias") or props.get("Name") or "Bluetooth adapter")
        if adapters:
            return False, "Adapter có mặt nhưng chưa công bố Audio Sink UUID"
        return False, "Không tìm thấy Bluetooth adapter"
    except Exception as error:
        return False, str(error)


def audio_graph_ready() -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            ["pactl", "list", "short", "cards"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    cards = [line for line in completed.stdout.splitlines() if line.strip()]
    if not cards:
        return False, "không có card; PipeWire có thể chỉ còn Dummy Output"
    return True, f"{len(cards)} card âm thanh"


def main() -> int:
    inotify_ok, inotify_detail = inotify_watch_available()
    graph_ok, graph_detail = audio_graph_ready()
    checks = [
        ("bluetoothctl", command_ok("bluetoothctl"), "gói bluez"),
        ("pactl", command_ok("pactl"), "gói pipewire-pulse hoặc pulseaudio-utils"),
        ("BlueZ service", service_active("bluetooth"), "sudo systemctl enable --now bluetooth"),
        ("PipeWire", service_active("pipewire", user=True), "systemctl --user enable --now pipewire"),
        ("WirePlumber", service_active("wireplumber", user=True), "systemctl --user enable --now wireplumber"),
        (
            "Inotify capacity",
            inotify_ok,
            "Đóng bớt VS Code/IDE rồi chạy: systemctl --user restart wireplumber",
        ),
        (
            "Audio graph",
            graph_ok,
            "Giải phóng inotify watches rồi chạy: systemctl --user restart wireplumber",
        ),
    ]
    failed = False
    print("NextSound system check\n")
    for label, ok, hint in checks:
        print(f"[{'OK' if ok else 'FAIL'}] {label}")
        if label == "Inotify capacity":
            print(f"       {inotify_detail}")
        elif label == "Audio graph":
            print(f"       {graph_detail}")
        if not ok:
            failed = True
            print(f"       Gợi ý: {hint}")
    ready, detail = bluez_receiver_ready()
    print(f"[{'OK' if ready else 'FAIL'}] A2DP Audio Sink: {detail}")
    if not ready:
        failed = True
        print(
            "       Bật role a2dp_sink trong cấu hình WirePlumber rồi chạy:\n"
            "       systemctl --user restart wireplumber pipewire pipewire-pulse\n"
            "       sudo systemctl restart bluetooth"
        )
    codecs = AudioBackend.available_bluetooth_codecs()
    codec_text = ", ".join(sorted(item.upper() for item in codecs)) or "không phát hiện"
    print(f"[INFO] Bluetooth codecs: {codec_text}")
    if AudioBackend.aac_receiver_available():
        print("[OK] AAC receiver decoder: sẵn sàng nhận AAC từ điện thoại")
    elif AudioBackend.aac_decoder_available():
        print("[FAIL] AAC receiver buffer: decoder có nhưng buffer A2DP quá nhỏ")
        print("       Chạy lại: ./scripts/install-aac-user.sh")
        failed = True
    elif "aac" in codecs:
        print("[FAIL] AAC receiver decoder: plugin hiện tại chỉ encode")
        failed = True
    else:
        print("       AAC chưa có: thiếu libspa-codec-bluez5-aac.so")
    if AudioBackend.ldac_decoder_available():
        print("[OK] LDAC receiver decoder: sẵn sàng nhận LDAC từ điện thoại")
    elif "ldac" in codecs:
        print("[INFO] LDAC receiver decoder: plugin hiện tại chỉ encode (PC → tai nghe)")
    else:
        print("[INFO] LDAC receiver decoder: chưa có")
    print("\nHệ thống đã sẵn sàng." if not failed else "\nHệ thống còn mục cần xử lý.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

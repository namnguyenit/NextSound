#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data_dir="${XDG_DATA_HOME:-${HOME}/.local/share}"

missing=()
for command in python3 bluetoothctl pactl; do
    command -v "${command}" >/dev/null 2>&1 || missing+=("${command}")
done
if (( ${#missing[@]} )); then
    echo "Thiếu công cụ: ${missing[*]}" >&2
    echo "Ubuntu: sudo apt install python3 python3-pip python3-gi python3-dbus gir1.2-gtk-4.0 gir1.2-adw-1 bluez pipewire wireplumber pipewire-pulse" >&2
    exit 1
fi
if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "Thiếu pip. Cài bằng: sudo apt install python3-pip" >&2
    exit 1
fi
if ! python3 -c 'import dbus, gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' \
        >/dev/null 2>&1; then
    echo "Thiếu thư viện Python/GTK cần cho giao diện NextSound." >&2
    echo "Ubuntu: sudo apt install python3-gi python3-dbus gir1.2-gtk-4.0 gir1.2-adw-1" >&2
    exit 1
fi

python3 -m pip install --user --no-build-isolation "${project_dir}"
install -Dm644 "${project_dir}/data/io.github.namnguyenit.NextSound.desktop" \
    "${data_dir}/applications/io.github.namnguyenit.NextSound.desktop"
install -Dm644 "${project_dir}/data/io.github.namnguyenit.NextSound.metainfo.xml" \
    "${data_dir}/metainfo/io.github.namnguyenit.NextSound.metainfo.xml"
install -Dm644 "${project_dir}/data/icons/io.github.namnguyenit.NextSound.svg" \
    "${data_dir}/icons/hicolor/scalable/apps/io.github.namnguyenit.NextSound.svg"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${data_dir}/applications" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${data_dir}/icons/hicolor" || true
fi

echo "Đã cài NextSound. Mở từ danh sách ứng dụng hoặc chạy: nextsound"
echo "Kiểm tra hệ thống bằng: nextsound-doctor"

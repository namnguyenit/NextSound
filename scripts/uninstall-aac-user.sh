#!/usr/bin/env bash
set -euo pipefail

for command in gcc systemctl; do
    command -v "${command}" >/dev/null 2>&1 || {
        echo "Thiếu công cụ ${command}." >&2
        exit 1
    }
done

multiarch="$(gcc -print-multiarch)"
runtime_dir="${HOME}/.local/lib/nextsound"
bluez_dir="${runtime_dir}/spa-0.2/bluez5"
aac_plugin="${bluez_dir}/libspa-codec-bluez5-aac.so"
system_aac_plugin="/usr/lib/${multiarch}/spa-0.2/bluez5/libspa-codec-bluez5-aac.so"
backend_plugin="${bluez_dir}/libspa-bluez5.so"
system_backend="/usr/lib/${multiarch}/spa-0.2/bluez5/libspa-bluez5.so"
override_file="${HOME}/.config/systemd/user/wireplumber.service.d/nextsound-aac.conf"

remove_file() {
    local path="$1"
    [[ -e "${path}" || -L "${path}" ]] || return 0
    if command -v gio >/dev/null 2>&1; then
        gio trash "${path}" >/dev/null 2>&1 || unlink "${path}"
    else
        unlink "${path}"
    fi
}

# Remove only AAC-owned files. The old uninstaller removed runtime_dir and
# accidentally deleted LDAC, its licence and the shared SPA overlay.
if [[ -f "${aac_plugin}" && ! -L "${aac_plugin}" ]]; then
    remove_file "${aac_plugin}"
fi
if [[ -d "${bluez_dir}" && -e "${system_aac_plugin}" \
      && ! -e "${aac_plugin}" && ! -L "${aac_plugin}" ]]; then
    ln -s "${system_aac_plugin}" "${aac_plugin}"
fi
remove_file "${runtime_dir}/lib/libfdk-aac.so.2"
remove_file "${runtime_dir}/aac-receiver-0.3.48"

# LDAC still relies on the patched backend and SPA override. Restore the
# system backend only when no receiver plugin from NextSound remains.
if [[ ! -f "${runtime_dir}/ldac-receiver-pipewire-1.6.0" ]]; then
    remove_file "${backend_plugin}"
    if [[ -d "${bluez_dir}" && -e "${system_backend}" ]]; then
        ln -s "${system_backend}" "${backend_plugin}"
    fi
    remove_file "${override_file}"
fi
systemctl --user daemon-reload
systemctl --user restart wireplumber
echo "Đã gỡ AAC receiver của NextSound; LDAC (nếu có) vẫn được giữ nguyên."

#!/usr/bin/env bash
set -euo pipefail

multiarch="$(gcc -print-multiarch)"
runtime_dir="${HOME}/.local/lib/nextsound"
bluez_dir="${runtime_dir}/spa-0.2/bluez5"
ldac_plugin="${runtime_dir}/spa-0.2/bluez5/libspa-codec-bluez5-ldac.so"
system_plugin="/usr/lib/${multiarch}/spa-0.2/bluez5/libspa-codec-bluez5-ldac.so"
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

if [[ -f "${ldac_plugin}" && ! -L "${ldac_plugin}" ]]; then
    remove_file "${ldac_plugin}"
fi
if [[ -d "${bluez_dir}" && -e "${system_plugin}" \
      && ! -e "${ldac_plugin}" && ! -L "${ldac_plugin}" ]]; then
    ln -s "${system_plugin}" "${ldac_plugin}"
fi
for path in \
    "${runtime_dir}/lib/libldacBT_dec.so.0" \
    "${runtime_dir}/licenses/libldacdec-LICENSE" \
    "${runtime_dir}/ldac-receiver-pipewire-1.6.0"; do
    remove_file "${path}"
done

# AAC still relies on the shared patched backend and SPA override.
if [[ ! -f "${runtime_dir}/aac-receiver-0.3.48" ]]; then
    remove_file "${backend_plugin}"
    if [[ -d "${bluez_dir}" && -e "${system_backend}" ]]; then
        ln -s "${system_backend}" "${backend_plugin}"
    fi
    remove_file "${override_file}"
fi

systemctl --user daemon-reload
systemctl --user restart wireplumber
echo "Đã gỡ LDAC receiver; SBC/AAC vẫn được giữ nguyên."

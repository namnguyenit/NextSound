#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
architecture="$(uname -m)"
if [[ "${architecture}" != "x86_64" ]]; then
    echo "Trình cài AAC hiện hỗ trợ x86_64; máy này là ${architecture}." >&2
    exit 1
fi

for command in gcc git apt-get chrpath dpkg-deb ninja patch strip systemctl; do
    command -v "${command}" >/dev/null 2>&1 || {
        echo "Thiếu công cụ ${command}." >&2
        exit 1
    }
done

pipewire_version="$(pipewire --version | sed -n 's/^Compiled with libpipewire //p' | head -1)"
if [[ -z "${pipewire_version}" ]]; then
    echo "Không xác định được phiên bản PipeWire." >&2
    exit 1
fi
if [[ "${pipewire_version}" != "0.3.48" ]]; then
    echo "Trình cài này chỉ dành cho PipeWire 0.3.48 của Ubuntu 22.04; máy đang dùng ${pipewire_version}." >&2
    exit 1
fi

build_dir="$(mktemp -d /tmp/nextsound-aac.XXXXXX)"
cleanup() {
    gio trash "${build_dir}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Build AAC receiver cho PipeWire ${pipewire_version}…"
git clone --quiet --depth 1 --branch "${pipewire_version}" \
    https://gitlab.freedesktop.org/pipewire/pipewire.git "${build_dir}/pipewire"
# Ubuntu 22.04's codec predates upstream AAC decoder commit 76adcfaa.
patch -d "${build_dir}/pipewire" -p1 \
    < "${project_dir}/patches/pipewire-0.3.48-aac-decoder.patch"
# Keep the receiver codec restriction separate from codecs used when this
# computer sends audio to Bluetooth headphones.
patch -d "${build_dir}/pipewire" -p1 \
    < "${project_dir}/patches/pipewire-0.3.48-directional-codecs.patch"
# PipeWire 0.3.48 has a 4 KiB decoded buffer, exactly the size of one
# 44.1 kHz stereo AAC frame. Its strict bounds check rejects that frame.
# Backport the 64 KiB decoded buffer used by newer PipeWire releases.
patch -d "${build_dir}/pipewire" -p1 \
    < "${project_dir}/patches/pipewire-0.3.48-a2dp-decode-buffer.patch"

(
    cd "${build_dir}"
    apt-get download \
        meson \
        libbluetooth-dev libbluetooth3 \
        libdbus-1-dev libdbus-1-3 \
        libfdk-aac-dev libfdk-aac2 \
        libsbc-dev libsbc1 \
        libsystemd-dev libsystemd0 \
        libudev-dev libudev1 \
        libusb-1.0-0-dev libusb-1.0-0 >/dev/null
    mkdir root
    for package in ./*.deb; do
        dpkg-deb -x "${package}" root
    done
)

multiarch="$(gcc -print-multiarch)"
fdk_lib_dir="${build_dir}/root/usr/lib/${multiarch}"
aac_plugin_output="${build_dir}/libspa-codec-bluez5-aac.so"
bluez_plugin_output="${build_dir}/pipewire/build/spa/plugins/bluez5/libspa-bluez5.so"
origin_rpath="\$ORIGIN/../../lib"

export PYTHONPATH="${build_dir}/root/usr/lib/python3/dist-packages"
export PKG_CONFIG_SYSROOT_DIR="${build_dir}/root"
export PKG_CONFIG_PATH="${build_dir}/root/usr/lib/${multiarch}/pkgconfig:${build_dir}/root/usr/share/pkgconfig"
python3 "${build_dir}/root/usr/bin/meson" setup \
    "${build_dir}/pipewire/build" "${build_dir}/pipewire" \
    --prefix=/usr \
    -Ddocs=disabled -Dtests=disabled -Dman=disabled \
    -Dsession-managers=[]
ninja -C "${build_dir}/pipewire/build" \
    spa/plugins/bluez5/libspa-bluez5.so
chrpath -d "${bluez_plugin_output}"

gcc -shared -fPIC -O2 -DCODEC_PLUGIN \
    -I"${build_dir}/pipewire/spa/include" \
    -I"${build_dir}/root/usr/include" \
    -L"${fdk_lib_dir}" \
    -Wl,-rpath,"${origin_rpath}" \
    -o "${aac_plugin_output}" \
    "${build_dir}/pipewire/spa/plugins/bluez5/a2dp-codec-aac.c" \
    "${build_dir}/pipewire/spa/plugins/bluez5/a2dp-codecs.c" \
    -lfdk-aac -lm -pthread
strip --strip-unneeded "${bluez_plugin_output}" "${aac_plugin_output}"

runtime_dir="${HOME}/.local/lib/nextsound"
spa_overlay="${runtime_dir}/spa-0.2"
system_spa="/usr/lib/${multiarch}/spa-0.2"
mkdir -p "${spa_overlay}/bluez5" "${runtime_dir}/lib"

# The LDAC installer provides a superset backend (AAC buffer fix,
# directional receiver selection and LDAC decoding). Do not replace it with
# the AAC-only build when users run installers in the opposite order.
preserve_ldac_backend=false
if [[ -f "${runtime_dir}/ldac-receiver-pipewire-1.6.0" \
      && -f "${spa_overlay}/bluez5/libspa-bluez5.so" \
      && ! -L "${spa_overlay}/bluez5/libspa-bluez5.so" ]]; then
    preserve_ldac_backend=true
fi

for source in "${system_spa}"/*; do
    name="$(basename "${source}")"
    [[ "${name}" == "bluez5" ]] && continue
    [[ -e "${spa_overlay}/${name}" || -L "${spa_overlay}/${name}" ]] || \
        ln -s "${source}" "${spa_overlay}/${name}"
done
for source in "${system_spa}/bluez5"/*; do
    destination="${spa_overlay}/bluez5/$(basename "${source}")"
    [[ -e "${destination}" || -L "${destination}" ]] || \
        ln -s "${source}" "${destination}"
done

if [[ -L "${spa_overlay}/bluez5/libspa-codec-bluez5-aac.so" ]]; then
    unlink "${spa_overlay}/bluez5/libspa-codec-bluez5-aac.so"
fi
if [[ "${preserve_ldac_backend}" == false ]]; then
    if [[ -L "${spa_overlay}/bluez5/libspa-bluez5.so" ]]; then
        unlink "${spa_overlay}/bluez5/libspa-bluez5.so"
    fi
    install -m755 "${bluez_plugin_output}" "${spa_overlay}/bluez5/libspa-bluez5.so"
fi
install -m755 "${aac_plugin_output}" "${spa_overlay}/bluez5/libspa-codec-bluez5-aac.so"
install -m755 "${fdk_lib_dir}/libfdk-aac.so.2.0.2" "${runtime_dir}/lib/libfdk-aac.so.2"
install -m644 "${project_dir}/data/aac-receiver-0.3.48" \
    "${runtime_dir}/aac-receiver-0.3.48"

override_dir="${HOME}/.config/systemd/user/wireplumber.service.d"
mkdir -p "${override_dir}"
sed "s|@SPA_PLUGIN_DIR@|${spa_overlay}|g" \
    "${project_dir}/data/nextsound-aac-wireplumber.service.conf.in" \
    > "${override_dir}/nextsound-aac.conf"

systemctl --user daemon-reload
systemctl --user restart wireplumber

echo "Đã cài AAC plugin cấp user."
echo "Dừng/mở lại kết nối điện thoại trong NextSound, rồi phát nhạc để thương lượng lại codec."

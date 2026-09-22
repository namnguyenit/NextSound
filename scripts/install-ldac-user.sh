#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
architecture="$(uname -m)"
pipewire_release="1.6.0"
pipewire_release_commit="700cea78dbe7564131d51b21a7795e2567ee048a"
system_pipewire_release="0.3.48"
system_pipewire_commit="6c4d3a51583f823b789b0de2df1e36d6c2f8dff8"
ldacdec_commit="7f3bd6cc1586b764b02f2e4f20b16c7ff18758b9"

if [[ "${architecture}" != "x86_64" ]]; then
    echo "Trình cài LDAC hiện hỗ trợ x86_64; máy này là ${architecture}." >&2
    exit 1
fi

for command in apt-get chrpath dpkg-deb gcc git ninja patch pkg-config strip systemctl; do
    command -v "${command}" >/dev/null 2>&1 || {
        echo "Thiếu công cụ ${command}." >&2
        exit 1
    }
done
for dependency in glib-2.0 gio-2.0 gio-unix-2.0; do
    pkg-config --exists "${dependency}" || {
        echo "Thiếu development package ${dependency}." >&2
        exit 1
    }
done

installed_pipewire="$(pipewire --version | sed -n 's/^Compiled with libpipewire //p' | head -1)"
if [[ "${installed_pipewire}" != "${system_pipewire_release}" ]]; then
    echo "Backport này dành cho PipeWire ${system_pipewire_release}; máy đang dùng ${installed_pipewire:-không rõ}." >&2
    exit 1
fi

build_dir="$(mktemp -d /tmp/nextsound-ldac.XXXXXX)"
cleanup() {
    gio trash "${build_dir}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Tải source PipeWire ${pipewire_release} từ GitHub…"
git clone --quiet --depth 1 --branch "${pipewire_release}" \
    https://github.com/PipeWire/pipewire.git "${build_dir}/pipewire-${pipewire_release}"
[[ "$(git -C "${build_dir}/pipewire-${pipewire_release}" rev-parse HEAD)" == "${pipewire_release_commit}" ]]

echo "Tải source libldacdec reverse-engineered (MIT)…"
git clone --quiet https://github.com/hegdi/libldacdec.git "${build_dir}/libldacdec"
git -C "${build_dir}/libldacdec" checkout --quiet "${ldacdec_commit}"

echo "Tải source ABI tương thích PipeWire ${system_pipewire_release} từ GitHub…"
git clone --quiet --depth 1 --branch "${system_pipewire_release}" \
    https://github.com/PipeWire/pipewire.git "${build_dir}/pipewire-${system_pipewire_release}"
[[ "$(git -C "${build_dir}/pipewire-${system_pipewire_release}" rev-parse HEAD)" == "${system_pipewire_commit}" ]]

patch -d "${build_dir}/libldacdec" -p1 < "${project_dir}/patches/libldacdec-meson.patch"
patch -d "${build_dir}/libldacdec" -p1 < "${project_dir}/patches/libldacdec-safety.patch"
patch -d "${build_dir}/pipewire-${pipewire_release}" -p1 \
    < "${project_dir}/patches/pipewire-1.6.0-libldacdec.patch"
patch -d "${build_dir}/pipewire-${system_pipewire_release}" -p1 \
    < "${project_dir}/patches/pipewire-0.3.48-ldac-decoder.patch"
patch -d "${build_dir}/pipewire-${system_pipewire_release}" -p1 \
    < "${project_dir}/patches/pipewire-0.3.48-directional-codecs.patch"
patch -d "${build_dir}/pipewire-${system_pipewire_release}" -p1 \
    < "${project_dir}/patches/pipewire-0.3.48-a2dp-decode-buffer.patch"

(
    cd "${build_dir}"
    apt-get download \
        meson \
        libbluetooth-dev libbluetooth3 \
        libdbus-1-dev libdbus-1-3 \
        libldacbt-enc-dev libldacbt-enc2 \
        libldacbt-abr-dev libldacbt-abr2 \
        libsbc-dev libsbc1 >/dev/null
    mkdir root
    for package in ./*.deb; do
        dpkg-deb -x "${package}" root
    done
)

multiarch="$(gcc -print-multiarch)"
meson_cmd="${build_dir}/root/usr/bin/meson"
prefix="${build_dir}/prefix"
pkg_path="${prefix}/lib/pkgconfig:${build_dir}/root/usr/lib/${multiarch}/pkgconfig"
include_path="${build_dir}/root/usr/include:${build_dir}/root/usr/include/dbus-1.0:${build_dir}/root/usr/lib/${multiarch}/dbus-1.0/include:${build_dir}/root/usr/include/ldac:${build_dir}/root/usr/include/sbc"
library_path="${build_dir}/root/usr/lib/${multiarch}"

export PYTHONPATH="${build_dir}/root/usr/lib/python3/dist-packages"
export PKG_CONFIG_PATH="${pkg_path}"
export CPATH="${include_path}"
export LIBRARY_PATH="${library_path}"
export LD_LIBRARY_PATH="${prefix}/lib:${library_path}"

echo "Build libldacdec bằng Meson + Ninja…"
python3 "${meson_cmd}" setup "${build_dir}/libldacdec-build" "${build_dir}/libldacdec" \
    --prefix="${prefix}" --libdir=lib --buildtype=release
ninja -C "${build_dir}/libldacdec-build"
ninja -C "${build_dir}/libldacdec-build" install

common_options=(
    -Dtests=disabled -Dexamples=disabled -Ddocs=disabled -Dman=disabled
    -Dsession-managers=[] -Dbluez5=enabled
    -Dbluez5-codec-ldac=enabled -Dbluez5-codec-ldac-dec=enabled
    -Dbluez5-codec-aac=disabled -Dbluez5-codec-aptx=disabled
)

echo "Compile plugin LDAC gốc PipeWire ${pipewire_release} bằng Meson + Ninja…"
python3 "${meson_cmd}" setup \
    "${build_dir}/pipewire-${pipewire_release}-build" \
    "${build_dir}/pipewire-${pipewire_release}" \
    --prefix=/usr "${common_options[@]}" \
    -Dpipewire-jack=disabled -Dpipewire-v4l2=disabled \
    -Dalsa=disabled -Djack=disabled -Dv4l2=disabled -Dlibcamera=disabled \
    -Dbluez5-codec-lc3plus=disabled -Dbluez5-codec-opus=disabled \
    -Dbluez5-codec-lc3=disabled -Dbluez5-codec-g722=disabled \
    -Dbluez5-plc-spandsp=disabled -Dflatpak=disabled -Dlibusb=disabled \
    -Dudev=disabled -Dx11=disabled -Davahi=disabled -Dlibpulse=disabled \
    -Dsdl2=disabled -Dsndfile=disabled -Dreadline=disabled \
    -Dsystemd-user-service=disabled -Dlibsystemd=disabled -Dselinux=disabled \
    -Decho-cancel-webrtc=disabled -Droc=disabled -Dlv2=disabled -Davb=disabled \
    -Dsnap=disabled -Debur128=disabled -Dfftw=disabled -Donnxruntime=disabled \
    -Dcompress-offload=disabled -Dgsettings=disabled \
    -Dgsettings-pulse-schema=disabled >/dev/null
ninja -C "${build_dir}/pipewire-${pipewire_release}-build" \
    spa/plugins/bluez5/libspa-codec-bluez5-ldac.so

echo "Compile backport ABI ${system_pipewire_release} bằng Meson + Ninja…"
python3 "${meson_cmd}" setup \
    "${build_dir}/pipewire-${system_pipewire_release}-build" \
    "${build_dir}/pipewire-${system_pipewire_release}" \
    --prefix=/usr "${common_options[@]}" \
    -Dalsa=disabled -Dudev=disabled -Dv4l2=disabled \
    -Dlibcamera=disabled -Djack=disabled
ninja -C "${build_dir}/pipewire-${system_pipewire_release}-build" \
    spa/plugins/bluez5/libspa-bluez5.so \
    spa/plugins/bluez5/libspa-codec-bluez5-ldac.so

bluez_plugin="${build_dir}/pipewire-${system_pipewire_release}-build/spa/plugins/bluez5/libspa-bluez5.so"
ldac_plugin="${build_dir}/pipewire-${system_pipewire_release}-build/spa/plugins/bluez5/libspa-codec-bluez5-ldac.so"
origin_rpath="\$ORIGIN/../../lib"
chrpath -d "${bluez_plugin}" 2>/dev/null || true
chrpath -r "${origin_rpath}" "${ldac_plugin}"
strip --strip-unneeded "${bluez_plugin}" "${ldac_plugin}" "${prefix}/lib/libldacBT_dec.so.0.1.0"

runtime_dir="${HOME}/.local/lib/nextsound"
spa_overlay="${runtime_dir}/spa-0.2"
system_spa="/usr/lib/${multiarch}/spa-0.2"
mkdir -p "${spa_overlay}/bluez5" "${runtime_dir}/lib" "${runtime_dir}/licenses"

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

for patched_plugin in libspa-bluez5.so libspa-codec-bluez5-ldac.so; do
    [[ -L "${spa_overlay}/bluez5/${patched_plugin}" ]] && \
        unlink "${spa_overlay}/bluez5/${patched_plugin}"
done
install -m755 "${bluez_plugin}" "${spa_overlay}/bluez5/libspa-bluez5.so"
install -m755 "${ldac_plugin}" "${spa_overlay}/bluez5/libspa-codec-bluez5-ldac.so"
install -m755 "${prefix}/lib/libldacBT_dec.so.0.1.0" "${runtime_dir}/lib/libldacBT_dec.so.0"
install -m644 "${build_dir}/libldacdec/LICENSE" \
    "${runtime_dir}/licenses/libldacdec-LICENSE"
install -m644 "${project_dir}/data/ldac-receiver-pipewire-1.6.0" \
    "${runtime_dir}/ldac-receiver-pipewire-1.6.0"

override_dir="${HOME}/.config/systemd/user/wireplumber.service.d"
mkdir -p "${override_dir}"
sed "s|@SPA_PLUGIN_DIR@|${spa_overlay}|g" \
    "${project_dir}/data/nextsound-aac-wireplumber.service.conf.in" \
    > "${override_dir}/nextsound-aac.conf"

systemctl --user daemon-reload
systemctl --user restart wireplumber

echo "Đã cài LDAC receiver từ PipeWire ${pipewire_release} + libldacdec ở cấp user."
echo "Mở NextSound, chọn LDAC, kết nối lại điện thoại rồi phát nhạc."

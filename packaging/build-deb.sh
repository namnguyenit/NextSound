#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="${1:-0.1.2-1}"
architecture="$(dpkg --print-architecture)"

if [[ "${architecture}" != "amd64" ]]; then
    echo "Release hiện chỉ hỗ trợ amd64; máy build là ${architecture}." >&2
    exit 1
fi
if [[ ! "${version}" =~ ^[0-9][0-9A-Za-z.+:~-]*$ ]]; then
    echo "Version Debian không hợp lệ: ${version}" >&2
    exit 1
fi

for command in dpkg dpkg-deb install md5sum sed sha256sum; do
    command -v "${command}" >/dev/null 2>&1 || {
        echo "Thiếu công cụ build: ${command}" >&2
        exit 1
    }
done

runtime_source="${project_dir}/packaging/runtime/amd64"
for required in \
    "${runtime_source}/spa-0.2/bluez5/libspa-bluez5.so" \
    "${runtime_source}/spa-0.2/bluez5/libspa-codec-bluez5-aac.so" \
    "${runtime_source}/spa-0.2/bluez5/libspa-codec-bluez5-ldac.so" \
    "${runtime_source}/lib/libfdk-aac.so.2" \
    "${runtime_source}/lib/libldacBT_enc.so.2" \
    "${runtime_source}/lib/libldacBT_abr.so.2" \
    "${runtime_source}/lib/libldacBT_dec.so.0"; do
    [[ -f "${required}" ]] || {
        echo "Thiếu runtime artifact: ${required}" >&2
        exit 1
    }
done

build_root="$(mktemp -d /tmp/nextsound-deb.XXXXXX)"
cleanup() {
    gio trash "${build_root}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

package_root="${build_root}/nextsound_${version}_amd64"
mkdir -p \
    "${package_root}/DEBIAN" \
    "${package_root}/opt/nextsound/app" \
    "${package_root}/opt/nextsound/runtime/spa-0.2/bluez5" \
    "${package_root}/opt/nextsound/runtime/lib" \
    "${package_root}/usr/bin" \
    "${package_root}/usr/lib/systemd/user/wireplumber.service.d" \
    "${package_root}/usr/share/applications" \
    "${package_root}/usr/share/icons/hicolor/scalable/apps" \
    "${package_root}/usr/share/metainfo" \
    "${package_root}/usr/share/doc/nextsound/third-party" \
    "${package_root}/etc/wireplumber/bluetooth.lua.d" \
    "${package_root}/etc/wireplumber/wireplumber.conf.d"

sed "s/@VERSION@/${version}/g" \
    "${project_dir}/packaging/debian/control.in" \
    > "${package_root}/DEBIAN/control"
install -m644 "${project_dir}/packaging/debian/conffiles" "${package_root}/DEBIAN/conffiles"
install -m755 "${project_dir}/packaging/debian/postinst" "${package_root}/DEBIAN/postinst"
install -m755 "${project_dir}/packaging/debian/postrm" "${package_root}/DEBIAN/postrm"

cp -a "${project_dir}/src/nextsound" "${package_root}/opt/nextsound/app/"
find "${package_root}/opt/nextsound/app" -type d -name __pycache__ -prune -exec rm -r {} +
find "${package_root}/opt/nextsound/app" -type f -name '*.pyc' -delete

install -m755 "${project_dir}/packaging/nextsound" "${package_root}/usr/bin/nextsound"
install -m755 "${project_dir}/packaging/nextsound-doctor" "${package_root}/usr/bin/nextsound-doctor"
install -m644 "${project_dir}/data/io.github.namnguyenit.NextSound.desktop" \
    "${package_root}/usr/share/applications/io.github.namnguyenit.NextSound.desktop"
install -m644 "${project_dir}/data/io.github.namnguyenit.NextSound.metainfo.xml" \
    "${package_root}/usr/share/metainfo/io.github.namnguyenit.NextSound.metainfo.xml"
install -m644 "${project_dir}/data/icons/io.github.namnguyenit.NextSound.svg" \
    "${package_root}/usr/share/icons/hicolor/scalable/apps/io.github.namnguyenit.NextSound.svg"

cp -a "${runtime_source}/." "${package_root}/opt/nextsound/runtime/"
install -m644 "${project_dir}/data/aac-receiver-0.3.48" \
    "${package_root}/opt/nextsound/runtime/aac-receiver-0.3.48"
install -m644 "${project_dir}/data/ldac-receiver-pipewire-1.6.0" \
    "${package_root}/opt/nextsound/runtime/ldac-receiver-pipewire-1.6.0"
for spa_factory in aec alsa audioconvert audiomixer audiotestsrc control support test v4l2 videoconvert videotestsrc volume; do
    ln -s "/usr/lib/x86_64-linux-gnu/spa-0.2/${spa_factory}" \
        "${package_root}/opt/nextsound/runtime/spa-0.2/${spa_factory}"
done
for codec in faststream sbc; do
    ln -s "/usr/lib/x86_64-linux-gnu/spa-0.2/bluez5/libspa-codec-bluez5-${codec}.so" \
        "${package_root}/opt/nextsound/runtime/spa-0.2/bluez5/libspa-codec-bluez5-${codec}.so"
done

install -m644 "${project_dir}/packaging/nextsound-wireplumber.service.conf" \
    "${package_root}/usr/lib/systemd/user/wireplumber.service.d/nextsound.conf"
install -m644 "${project_dir}/packaging/51-nextsound.lua" \
    "${package_root}/etc/wireplumber/bluetooth.lua.d/51-nextsound.lua"
install -m644 "${project_dir}/packaging/51-nextsound.conf" \
    "${package_root}/etc/wireplumber/wireplumber.conf.d/51-nextsound.conf"

install -m644 "${project_dir}/README.md" "${package_root}/usr/share/doc/nextsound/README.md"
install -m644 "${project_dir}/CHANGELOG.md" "${package_root}/usr/share/doc/nextsound/changelog"
install -m644 "${project_dir}/LICENSE" "${package_root}/usr/share/doc/nextsound/copyright"
cp -a "${project_dir}/packaging/licenses/." "${package_root}/usr/share/doc/nextsound/third-party/"

(
    cd "${package_root}"
    find . -type f ! -path './DEBIAN/*' -printf '%P\0' \
        | sort -z \
        | xargs -0 md5sum > DEBIAN/md5sums
)

mkdir -p "${project_dir}/dist"
output="${project_dir}/dist/nextsound_${version}_amd64.deb"
dpkg-deb --root-owner-group --build "${package_root}" "${output}"
(
    cd "${project_dir}/dist"
    sha256sum "$(basename "${output}")" > SHA256SUMS
)

echo "Đã tạo ${output}"
echo "Checksum: ${project_dir}/dist/SHA256SUMS"

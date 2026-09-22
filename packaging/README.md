# Debian packaging

`build-deb.sh` tạo gói Ubuntu 22.04 amd64 có runtime codec cố định theo ABI PipeWire 0.3.48.

Runtime nhúng gồm:

- `libspa-bluez5.so`: backend A2DP có lựa chọn codec theo chiều và buffer decode đã vá.
- `libspa-codec-bluez5-aac.so` + `libfdk-aac.so.2`: AAC encode/decode.
- `libspa-codec-bluez5-ldac.so` + `libldacBT_dec.so.0`: LDAC encode/decode.

Các SPA factory còn lại được liên kết tới gói PipeWire hệ thống. Không dùng runtime này với ABI PipeWire khác 0.3.48.

```bash
./packaging/build-deb.sh 0.1.1-1
dpkg-deb --info dist/nextsound_0.1.1-1_amd64.deb
dpkg-deb --contents dist/nextsound_0.1.1-1_amd64.deb
```

# Xử lý sự cố

## Chạy kiểm tra hệ thống

```bash
nextsound-doctor
```

## Điện thoại không xuất hiện

- Ghép đôi lại trong GNOME Settings.
- Kiểm tra điện thoại công bố Audio Source UUID `0x110A`.
- Bật **Media audio / Âm thanh phương tiện** trên điện thoại.
- Xóa địa chỉ MAC trước khi chia sẻ log.

## Điện thoại hiện AAC/LDAC nhưng không có tiếng

1. Kiểm tra dòng codec thực tế trong NextSound.
2. Chạy `nextsound-doctor` để xác nhận decoder receiver.
3. Kiểm tra loa đầu ra và âm lượng luồng điện thoại.
4. Thử SBC để phân biệt lỗi codec với lỗi routing.

## Tai nghe bị về SBC

NextSound phải giữ danh sách codec phát tới tai nghe độc lập với codec nhận từ điện thoại. Không đặt `bluez5.codecs = [ sbc ]` toàn cục. Cấu hình NextSound dùng `bluez5.sink-codec` cho riêng endpoint nhận.

## Thu thập phiên bản

```bash
pipewire --version
wireplumber --version
bluetoothctl --version
nextsound-doctor
```

Gói `.deb` v0.1.2 chỉ hỗ trợ PipeWire 0.3.48/WirePlumber 0.4 trên Ubuntu 22.04 amd64.

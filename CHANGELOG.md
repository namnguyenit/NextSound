# Changelog

Mọi thay đổi đáng chú ý của NextSound được ghi lại tại đây. Dự án tuân theo [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-22

### Added

- Giao diện GTK 4/libadwaita để dùng máy tính như loa Bluetooth A2DP.
- Phát hiện điện thoại, mở/đóng receiver và hiển thị trạng thái streaming.
- Chọn loa đầu ra, âm lượng riêng 0–150%, codec SBC/AAC/LDAC theo từng chiều.
- AAC decoder backport và buffer giải mã 64 KiB cho PipeWire 0.3.48.
- LDAC receiver dựa trên PipeWire 1.6.0 và `hegdi/libldacdec`.
- Gói Debian Ubuntu 22.04 amd64 chứa runtime codec đã kiểm thử.
- `nextsound-doctor`, CI và kiểm thử hồi quy.

### Fixed

- Không còn giới hạn codec toàn cục làm tai nghe bị ép về SBC.
- AAC thương lượng thành công nhưng không xuất PCM.
- Lọc nhầm transport A2DP với HFP hoặc chiều tai nghe.
- Cài/gỡ AAC ghi đè hoặc xóa nhầm runtime LDAC.
- Đổi loa không chuyển luồng điện thoại đang phát.
- Trạng thái UI bị kẹt sau khi BlueZ transport biến mất.
- Hoàn tác cấu hình khi WirePlumber restart thất bại.

[0.1.0]: https://github.com/namnguyenit/NextSound/releases/tag/v0.1.0

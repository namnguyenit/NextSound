# Kiến trúc NextSound

> Made by TrungCao

```text
Điện thoại (A2DP Source)
          │ Bluetooth Classic / SBC, AAC, LDAC
          ▼
BlueZ (local A2DP Sink, D-Bus control)
          │ PCM node
          ▼
PipeWire + WirePlumber (decode, policy, routing)
          │
          ▼
Loa mặc định của máy tính (ALSA/USB/Bluetooth/HDMI)
```

## Vì sao không tự nhận packet Bluetooth trong app?

BlueZ và plugin `api.bluez5` của PipeWire đã quản lý endpoint, codec negotiation, transport và PCM graph. Tự đăng ký một endpoint thứ hai từ app dễ xung đột với WirePlumber, phải tự xử lý codec và làm mất tích hợp volume/routing của desktop.

LDAC receiver dùng backend BlueZ đúng ABI của PipeWire hệ thống và một plugin codec được backport từ thiết kế decoder của PipeWire 1.6.0. Plugin gọi trực tiếp `hegdi/libldacdec`, kiểm tra header/kích thước frame trước khi decode và chuyển PCM 16-bit của decoder sang format mà graph PipeWire đã thương lượng. Backend còn tách danh sách endpoint A2DP Sink nhận từ điện thoại khỏi codec A2DP Source phát tới tai nghe, nên việc chọn codec trong NextSound không làm mất AAC/LDAC/SBC-XQ của tai nghe. Source và thư viện đều được build bằng Meson + Ninja ở cấp user.

NextSound vì vậy sử dụng:

- `org.freedesktop.DBus.ObjectManager` để theo dõi adapter, device và media transport.
- `org.bluez.Device1.Connect()` để điện thoại thương lượng lại endpoint A2DP Source sau khi đổi codec; máy tính cung cấp phía Audio Sink `0x110B`.
- `org.bluez.MediaTransport1.State` để phân biệt “đã mở, đang chờ” và “đang stream”.
- `pactl` để đọc/đổi default PipeWire sink qua `pipewire-pulse`.

## Khác biệt với app Windows

Ứng dụng Windows gọi `AudioPlaybackConnection.StartAsync()` để cho phép thiết bị nguồn phát tới endpoint âm thanh cục bộ. Trên Linux, chức năng tương đương được chia giữa BlueZ (Bluetooth profiles/transports) và PipeWire/WirePlumber (codec, node và routing); NextSound cung cấp thao tác Open/Close Connection tương đương ở cấp UI.

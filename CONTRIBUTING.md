# Contributing to NextSound

Cảm ơn bạn đã đóng góp cho NextSound.

## Môi trường phát triển

```bash
sudo apt install python3 python3-gi python3-dbus gir1.2-gtk-4.0 gir1.2-adw-1 \
  bluez pipewire wireplumber pipewire-pulse
./run-dev.sh
```

## Trước khi gửi pull request

```bash
python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
bash -n install.sh run-dev.sh scripts/*.sh packaging/*.sh
```

- Giữ thay đổi tập trung vào một vấn đề.
- Không commit token, cookie, địa chỉ Bluetooth cá nhân hoặc log nội bộ.
- Mọi thay đổi codec phải kiểm thử cả hai chiều: điện thoại → máy tính và máy tính → tai nghe.
- Binary runtime chỉ được cập nhật khi source/commit, quy trình build và giấy phép tương ứng đã được ghi lại.

## Mô tả

<!-- Nêu ngắn gọn vấn đề và thay đổi. -->

## Kiểm thử

- [ ] `python3 -m compileall -q src tests`
- [ ] `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- [ ] Shell scripts đã qua `bash -n` và ShellCheck
- [ ] Đã kiểm tra không chứa token, cookie, địa chỉ Bluetooth hoặc dữ liệu nội bộ

## Ảnh hưởng codec

- [ ] Không ảnh hưởng
- [ ] Đã kiểm thử điện thoại → máy tính
- [ ] Đã kiểm thử máy tính → tai nghe

# Telegram bridge cho Delta

Mã bridge nằm trong Git; token và `chat_id` luôn nằm ngoài repo, theo đường dẫn mặc định `$HOME/tgbridge/token` và `$HOME/tgbridge/chat_id` (hoặc biến môi trường tương ứng).

Bridge chỉ nhận hai lệnh từ đúng `chat_id` đã cấu hình:

- `STATUS`: báo root, branch và HEAD hiện tại.
- `UPDATE`: chạy đúng `python3 delta/delta_updater.py`; không nhận tham số hay lệnh shell từ Telegram.

## Chạy

Khi secret đã được cấu hình ngoài repo bởi luồng triển khai, khởi động từ bản mã đang checkout:

```sh
cd /storage/emulated/0/Download/phanserver-delta
sh tools/tgbridge/start-bridge.sh
```

Chỉ chạy một tiến trình bridge cho mỗi token. Nếu Telegram trả HTTP 409, còn một tiến trình khác đang dùng cùng token; dừng tiến trình đó trước khi khởi động lại.

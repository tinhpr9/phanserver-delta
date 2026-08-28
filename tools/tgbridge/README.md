# Telegram bridge cho Delta

Mã bridge nằm trong Git; token và `chat_id` luôn nằm ngoài repo.

Bridge chỉ nhận hai lệnh từ đúng `chat_id` đã cấu hình:

- `STATUS`: báo root, branch và HEAD hiện tại.
- `UPDATE`: chạy đúng `python3 delta/delta_updater.py`; không nhận tham số hay lệnh shell từ Telegram.

## Chạy trên Termux

Lưu token và chat ID ở ngoài repo:

```sh
mkdir -p "$HOME/tgbridge"
chmod 700 "$HOME/tgbridge"
printf '%s\n' 'TOKEN_CỦA_BOT' > "$HOME/tgbridge/token"
printf '%s\n' 'CHAT_ID_ĐƯỢC_PHÉP' > "$HOME/tgbridge/chat_id"
chmod 600 "$HOME/tgbridge/token" "$HOME/tgbridge/chat_id"
cd /storage/emulated/0/Download/phanserver-delta
tools/tgbridge/start-bridge.sh
```

Chỉ chạy một tiến trình bridge cho mỗi token. Nếu Telegram trả HTTP 409, dừng tiến trình bridge khác đang dùng cùng token trước khi khởi động lại.

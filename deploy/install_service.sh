#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# Installer for phanserver-delta Service Manager (CLI + Termux:Boot Auto-Start)
# ==============================================================================

set -euo pipefail

TARGET_DIR="${1:-/storage/emulated/0/Download/phanserver-delta}"
BIN_PATH="/data/data/com.termux/files/usr/bin/phan"
BOOT_DIR="$HOME/.termux/boot"
BOOT_FILE="$BOOT_DIR/01-phanserver-agent.sh"

echo "=========================================="
echo "  CÀI ĐẶT PHANSERVER-DELTA DAEMON SERVICE"
echo "=========================================="

# 1. Tạo lệnh CLI 'phan' trong $PREFIX/bin
cat << 'INNER_EOF' > "$BIN_PATH"
#!/data/data/com.termux/files/usr/bin/bash
REPO_DIR="/storage/emulated/0/Download/phanserver-delta"
AGENT_PY="$REPO_DIR/agent/agent.py"
PID_FILE="$HOME/.phanserver_agent.pid"
LOG_FILE="$HOME/agent.log"

is_running() {
    if [ -f "$PID_FILE" ]; then
        PID="$(cat "$PID_FILE" 2>/dev/null || echo "")"
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            return 0
        fi
    fi
    pgrep -f "agent/agent.py" >/dev/null 2>&1
}

get_pid() {
    if [ -f "$PID_FILE" ]; then
        cat "$PID_FILE" 2>/dev/null || pgrep -f "agent/agent.py" | head -n 1
    else
        pgrep -f "agent/agent.py" | head -n 1
    fi
}

start_agent() {
    if is_running; then
        echo "⚠️  Agent đang chạy rồi (PID: $(get_pid))"
        return 0
    fi
    echo "[*] Đang khởi động phanserver-delta Agent..."
    if [ ! -f "$AGENT_PY" ]; then
        echo "[!] Không tìm thấy file $AGENT_PY"
        exit 1
    fi
    cd "$REPO_DIR"
    nohup python3 "$AGENT_PY" > "$LOG_FILE" 2>&1 &
    PID=$!
    echo "$PID" > "$PID_FILE"
    sleep 1
    if kill -0 "$PID" 2>/dev/null; then
        echo "✅ Agent đã chạy nền thành công! (PID: $PID)"
        echo "💡 Bạn có thể gõ 'phan log' để xem nhật ký hoạt động."
    else
        echo "❌ Khởi động thất bại. Hãy gõ 'phan log' để kiểm tra lỗi."
    fi
}

stop_agent() {
    if is_running; then
        PID="$(get_pid)"
        echo "[*] Đang dừng Agent (PID: $PID)..."
        pkill -9 -f "agent/agent.py" 2>/dev/null || true
        rm -f "$PID_FILE"
        echo "✅ Đã dừng Agent."
    else
        echo "ℹ️  Agent hiện không chạy."
        rm -f "$PID_FILE"
    fi
}

status_agent() {
    if is_running; then
        PID="$(get_pid)"
        echo "🟢 Trạng thái: ĐANG CHẠY (PID: $PID)"
        echo "📄 File log: $LOG_FILE"
    else
        echo "🔴 Trạng thái: ĐÃ DỪNG"
    fi
}

case "${1:-status}" in
    start)
        start_agent
        ;;
    stop)
        stop_agent
        ;;
    restart)
        stop_agent
        sleep 1
        start_agent
        ;;
    status)
        status_agent
        ;;
    log|logs)
        if [ -f "$LOG_FILE" ]; then
            tail -n "${2:-50}" -f "$LOG_FILE"
        else
            echo "Chưa có file log tại $LOG_FILE"
        fi
        ;;
    upgrade)
        echo "[*] Đang kéo mã nguồn mới nhất từ GitHub..."
        cd "$REPO_DIR"
        git -c safe.directory=* fetch origin fix/delta-stability
        git -c safe.directory=* reset --hard origin/fix/delta-stability
        echo "[*] Khởi động lại Agent..."
        stop_agent
        sleep 1
        start_agent
        ;;
    *)
        echo "Sử dụng lệnh: phan {start|stop|restart|status|log|upgrade}"
        exit 1
        ;;
esac
INNER_EOF

chmod +x "$BIN_PATH" 2>/dev/null || true
echo "[+] Đã tạo script lệnh: 'phan' -> $BIN_PATH"

# 2. Cài đặt Termux:Boot tự khởi động khi mở máy
mkdir -p "$BOOT_DIR"
cat << 'BOOT_EOF' > "$BOOT_FILE"
#!/data/data/com.termux/files/usr/bin/bash
# Tự động chạy phanserver Agent khi máy khởi động
termux-wake-lock 2>/dev/null || true
sleep 5
/data/data/com.termux/files/usr/bin/phan start
BOOT_EOF
chmod +x "$BOOT_FILE" 2>/dev/null || true
echo "[+] Đã cấu hình Termux:Boot: $BOOT_FILE"

echo ""
echo "=========================================="
echo "  ✅ HOÀN TẤT CÀI ĐẶT DỊCH VỤ NỀN!"
echo "=========================================="
echo "Từ bây giờ bạn chỉ cần dùng các lệnh ngắn gọn:"
echo "  • phan start    : Bật Agent chạy ngầm"
echo "  • phan stop     : Tắt Agent"
echo "  • phan restart  : Khởi động lại Agent"
echo "  • phan status   : Xem trạng thái hoạt động"
echo "  • phan log      : Xem trực tiếp nhật ký gửi/nhận lệnh"
echo "  • phan upgrade  : Kéo code mới và nạp lại"
echo "=========================================="

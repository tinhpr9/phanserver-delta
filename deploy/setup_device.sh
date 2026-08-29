#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# phanserver-delta: All-In-One Device Setup (From Zero to Running Daemon)
# Usage:
#   bash deploy/setup_device.sh [DEVICE_ID] [DEVICE_GROUP]
# Example:
#   bash deploy/setup_device.sh m72
#   bash deploy/setup_device.sh m77 NOVA
# ==============================================================================

set -euo pipefail

REPO="/storage/emulated/0/Download/phanserver-delta"
SHOUKO="/storage/emulated/0/Download/Shouko"
REPO_URL="https://github.com/tinhpr9/phanserver-delta.git"
BRANCH="fix/delta-stability"
WORKER_URL="https://phanserver-delta-worker.tinh1020pr.workers.dev/report"

RAW_ID="${1:-}"
RAW_GROUP="${2:-NOVA}"

echo "=========================================="
echo "  🚀 CÀI ĐẶT PHANSERVER-DELTA TỰ ĐỘNG"
echo "=========================================="

# 1. Cấp quyền bộ nhớ
echo "[1/6] Kiểm tra quyền bộ nhớ..."
[ -d "$HOME/storage" ] || termux-setup-storage 2>/dev/null || true

# 2. Cài đặt các gói phụ thuộc bắt buộc
echo "[2/6] Cài đặt Python, Git, Chứng chỉ SSL..."
pkg update -y -o Dpkg::Options::="--force-confnew" 2>/dev/null || true
pkg install -y git python ca-certificates coreutils

# 3. Kéo mã nguồn mới nhất từ GitHub
echo "[3/6] Đồng bộ mã nguồn mới nhất..."
if [ -d "$REPO/.git" ]; then
    cd "$REPO"
    git -c safe.directory=* fetch origin "$BRANCH"
    git -c safe.directory=* reset --hard "origin/$BRANCH"
else
    rm -rf "$REPO"
    git -c safe.directory=* clone --single-branch --branch "$BRANCH" "$REPO_URL" "$REPO"
    cd "$REPO"
fi

# 4. Xác định Device ID
echo "[4/6] Xác thực Device ID..."
if [ -z "$RAW_ID" ]; then
    printf "👉 Nhập Device ID (vd: m72, m77): "
    read -r RAW_ID
fi

DEVICE_ID="$(python3 -c 'import sys; from agent.config import normalize_device_id; x=normalize_device_id(sys.argv[1]); print(x or ""); raise SystemExit(0 if x else 2)' "$RAW_ID")"
DEVICE_GROUP="$(python3 -c 'import sys; from agent.config import normalize_device_group; x=normalize_device_group(sys.argv[1]); print(x or "NOVA"); raise SystemExit(0)' "$RAW_GROUP")"

echo "  -> Device ID   : $DEVICE_ID"
echo "  -> Device Group: $DEVICE_GROUP"

# 5. Tạo tệp cấu hình
echo "[5/6] Tạo cấu hình Agent..."
mkdir -p "$SHOUKO"
cat > "$SHOUKO/agent_config.json" <<EOF2
{
  "worker_report_url": "$WORKER_URL",
  "agent_report_secret": ""
}
EOF2
printf '%s\n' "$DEVICE_ID" > "$SHOUKO/device_id.txt"
printf '%s\n' "$DEVICE_GROUP" > "$SHOUKO/device_group.txt"

# 6. Đăng ký dịch vụ nền 'phan' + Termux:Boot
echo "[6/6] Cài đặt dịch vụ nền và Termux:Boot..."
bash "$REPO/deploy/install_service.sh"

echo "=========================================="
echo "  ✅ CÀI ĐẶT THÀNH CÔNG CHO THIẾT BỊ: $DEVICE_ID"
echo "=========================================="
phan start

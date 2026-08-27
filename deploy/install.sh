#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

REF="${PHANSERVER_REF:-main}"
[[ "$REF" =~ ^[A-Za-z0-9._/-]+$ ]] || { echo "[LỖI] PHANSERVER_REF không hợp lệ" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "[LỖI] Thiếu curl" >&2; exit 1; }

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -fsSL --retry 3 --connect-timeout 15 \
  "https://raw.githubusercontent.com/tinhpr9/phanserver-delta/$REF/deploy/install_runtime.sh" \
  -o "$TMP"
[ -s "$TMP" ] || { echo "[LỖI] install_runtime.sh tải về bị trống" >&2; exit 1; }
bash -n "$TMP" || { echo "[LỖI] install_runtime.sh sai cú pháp" >&2; exit 1; }
exec bash "$TMP" "$@"

#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ok() { echo "[OK] $*"; }
warn() { echo "[!] $*"; }
die() { echo "[LỖI] $*" >&2; exit 1; }

usage() {
  echo "Cách dùng:"
  echo "  install.sh 73 2"
  echo "  install.sh m73 NOVA"
  echo "Nhóm: 1/MARMOT hoặc 2/NOVA"
}

DEVICE_RAW="${1:-}"
GROUP_RAW="${2:-}"
[ -n "$DEVICE_RAW" ] && [ -n "$GROUP_RAW" ] || { usage; exit 2; }

DEVICE_INPUT="$(printf '%s' "$DEVICE_RAW" | tr -d '\r\n ' | tr '[:upper:]' '[:lower:]')"
if [[ "$DEVICE_INPUT" =~ ^[1-9][0-9]{0,5}$ ]]; then
  DEVICE_ID="m$DEVICE_INPUT"
else
  DEVICE_ID="$DEVICE_INPUT"
fi
[[ "$DEVICE_ID" =~ ^m[1-9][0-9]{0,5}$ ]] || die "Device ID không hợp lệ: $DEVICE_RAW"

GROUP_INPUT="$(printf '%s' "$GROUP_RAW" | tr -d '\r\n _-' | tr '[:lower:]' '[:upper:]')"
case "$GROUP_INPUT" in
  1|NHOM1|GROUP1|MARMOT) DEVICE_GROUP="MARMOT" ;;
  2|NHOM2|GROUP2|NOVA) DEVICE_GROUP="NOVA" ;;
  *) die "Nhóm không hợp lệ: $GROUP_RAW" ;;
esac

WORKER_ORIGIN="${PHANSERVER_WORKER_ORIGIN:-https://phanserver-delta-worker.tinh1020pr.workers.dev}"
SOURCE_REF="${PHANSERVER_REF:-main}"

if [ "${PHANSERVER_INSTALL_TEST_MODE:-0}" = "1" ]; then
  echo "PHANSERVER_DEVICE_ID=$DEVICE_ID"
  echo "PHANSERVER_DEVICE_GROUP=$DEVICE_GROUP"
  echo "PHANSERVER_WORKER_ORIGIN=$WORKER_ORIGIN"
  echo "PHANSERVER_SOURCE_REF=$SOURCE_REF"
  exit 0
fi

for command_name in bash curl mktemp mv cp rm mkdir chmod ln readlink date tr grep python3; do
  command -v "$command_name" >/dev/null 2>&1 || die "Thiếu lệnh bắt buộc: $command_name"
done
PYTHON="$(command -v python3)"

case "$WORKER_ORIGIN" in
  https://*) ;;
  *) die "PHANSERVER_WORKER_ORIGIN phải dùng HTTPS" ;;
esac
WORKER_ORIGIN="${WORKER_ORIGIN%/}"

resolve_revision() {
  local ref="$1"
  if [[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
    printf '%s\n' "$(printf '%s' "$ref" | tr '[:upper:]' '[:lower:]')"
    return 0
  fi
  local tmp
  tmp="$(mktemp)"
  if ! curl -fsSL --retry 3 --connect-timeout 15 \
      -H 'Accept: application/vnd.github+json' \
      "https://api.github.com/repos/tinhpr9/phanserver-delta/commits/$ref" \
      -o "$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  local resolved
  resolved="$($PYTHON - "$tmp" <<'PY'
import json
import pathlib
import re
import sys
try:
    data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    sha = str(data.get("sha") or "").lower()
except Exception:
    sha = ""
if not re.fullmatch(r"[0-9a-f]{40}", sha):
    raise SystemExit(1)
print(sha)
PY
)" || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
  printf '%s\n' "$resolved"
}

REVISION="$(resolve_revision "$SOURCE_REF")" || die "Không resolve được PHANSERVER_REF=$SOURCE_REF"
RAW="https://raw.githubusercontent.com/tinhpr9/phanserver-delta/$REVISION"
INSTALL_ROOT="$HOME/.phanserver-delta"
RELEASE_ROOT="$INSTALL_ROOT/releases"
RELEASE_DIR="$RELEASE_ROOT/$REVISION"
CURRENT_LINK="$INSTALL_ROOT/current"
LAST_GOOD_LINK="$INSTALL_ROOT/last_good"
SHOUKO_DIR="/storage/emulated/0/Download/Shouko"
ID_FILE="$SHOUKO_DIR/device_id.txt"
GROUP_FILE="$SHOUKO_DIR/device_group.txt"
CONFIG_FILE="$SHOUKO_DIR/agent_config.json"
BIN_DIR="$HOME/bin"
SERVICE_CMD="$BIN_DIR/phanserver-agent"
BOOT_DIR="$HOME/.termux/boot"
BOOT_FILE="$BOOT_DIR/02-phanserver-delta.sh"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$INSTALL_ROOT" "$RELEASE_ROOT" "$SHOUKO_DIR" "$BIN_DIR" "$BOOT_DIR"

build_release() {
  if [ -f "$RELEASE_DIR/agent/agent.py" ] && [ -f "$RELEASE_DIR/delta/delta_updater.py" ]; then
    ok "Runtime revision $REVISION đã có sẵn"
    return 0
  fi

  local stage
  stage="$(mktemp -d "$INSTALL_ROOT/.stage.XXXXXX")"
  mkdir -p "$stage/agent" "$stage/delta" "$stage/deploy"
  local paths=(
    "agent/agent.py"
    "agent/config.py"
    "agent/server_links.py"
    "delta/delta_updater.py"
    "deploy/device_service.sh"
  )
  local path
  for path in "${paths[@]}"; do
    curl -fsSL --retry 3 --connect-timeout 15 "$RAW/$path" -o "$stage/$path" || {
      rm -rf "$stage"
      die "Không tải được $path ở revision $REVISION"
    }
    [ -s "$stage/$path" ] || { rm -rf "$stage"; die "$path tải về bị trống"; }
  done

  "$PYTHON" -m py_compile \
    "$stage/agent/agent.py" \
    "$stage/agent/config.py" \
    "$stage/agent/server_links.py" \
    "$stage/delta/delta_updater.py" || { rm -rf "$stage"; die "Runtime Python sai cú pháp"; }
  bash -n "$stage/deploy/device_service.sh" || { rm -rf "$stage"; die "device_service.sh sai cú pháp"; }
  chmod 700 "$stage/deploy/device_service.sh"
  mv "$stage" "$RELEASE_DIR" || die "Không materialize được release $REVISION"
  ok "Đã cài runtime revision=$REVISION"
}

config_matches_identity() {
  [ -f "$ID_FILE" ] && [ -f "$GROUP_FILE" ] && [ -f "$CONFIG_FILE" ] || return 1
  [ "$(tr -d '\r\n ' < "$ID_FILE" | tr '[:upper:]' '[:lower:]')" = "$DEVICE_ID" ] || return 1
  [ "$(tr -d '\r\n ' < "$GROUP_FILE" | tr '[:lower:]' '[:upper:]')" = "$DEVICE_GROUP" ] || return 1
  "$PYTHON" - "$CONFIG_FILE" "$WORKER_ORIGIN" <<'PY'
import json
import pathlib
import sys
from urllib.parse import urlparse
path = pathlib.Path(sys.argv[1])
origin = sys.argv[2].rstrip("/")
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
url = str(data.get("worker_report_url") or "").strip()
secret = str(data.get("agent_report_secret") or "").strip()
parsed = urlparse(url)
actual_origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
if actual_origin != origin or parsed.path != "/report" or len(secret) < 32:
    raise SystemExit(1)
PY
}

pair_device() {
  local output="$1"
  "$PYTHON" - "$WORKER_ORIGIN" "$DEVICE_ID" "$DEVICE_GROUP" "$output" <<'PY'
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

origin, device_id, device_group, output_raw = sys.argv[1:5]
output = pathlib.Path(output_raw)

def post(path, payload, timeout=20):
    req = urllib.request.Request(
        origin.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", "Cache-Control": "no-store"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read(65536).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read(65536)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = {}
        return exc.code, data

status, data = post("/agent/pair/request", {"device_id": device_id, "device_group": device_group})
if status != 201 or not data.get("ok"):
    print(f"[LỖI] Không tạo được yêu cầu ghép máy: HTTP {status} {data.get('error', '')}")
    raise SystemExit(1)
pair_id = str(data.get("pair_id") or "")
pair_token = str(data.get("pair_token") or "")
code = str(data.get("verification_code") or "")
expires_in = int(data.get("expires_in") or 600)
poll_after = max(2, min(int(data.get("poll_after") or 3), 10))
if not pair_id or len(pair_token) < 32 or len(code) != 6:
    print("[LỖI] Worker trả dữ liệu ghép máy không hợp lệ")
    raise SystemExit(1)
print("[*] Telegram đã nhận yêu cầu ghép máy.")
print(f"[*] Mã xác minh trên UGPhone: {code}")
print("[*] Đối chiếu đúng mã rồi bấm ✅ Chấp nhận trên bot Telegram.")
deadline = time.monotonic() + min(max(expires_in, 60), 600) + 10
while time.monotonic() < deadline:
    time.sleep(poll_after)
    status, data = post("/agent/pair/status", {"pair_id": pair_id, "pair_token": pair_token})
    if status == 202:
        continue
    if status == 200 and data.get("ok") and data.get("status") == "approved":
        report_url = str(data.get("worker_report_url") or "").strip()
        secret = str(data.get("agent_report_secret") or "").strip()
        if report_url != origin.rstrip("/") + "/report" or len(secret) < 32:
            print("[LỖI] Worker trả credential không hợp lệ")
            raise SystemExit(1)
        tmp = output.with_name(output.name + ".tmp")
        tmp.write_text(json.dumps({"worker_report_url": report_url, "agent_report_secret": secret}, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(output)
        print("[OK] Ghép máy thành công; secret không được hiển thị.")
        raise SystemExit(0)
    if status in {403, 404, 409, 410}:
        print(f"[LỖI] Ghép máy không hoàn tất: HTTP {status} {data.get('error', '')}")
        raise SystemExit(1)
print("[LỖI] Hết thời gian chờ xác nhận Telegram")
raise SystemExit(1)
PY
}

install_identity_and_config() {
  if config_matches_identity; then
    chmod 600 "$CONFIG_FILE" 2>/dev/null || true
    ok "Identity/config đã đúng; không ghép lại"
    return 0
  fi

  local config_stage
  config_stage="$(mktemp "$INSTALL_ROOT/.agent-config.XXXXXX")"
  rm -f "$config_stage"
  pair_device "$config_stage" || { rm -f "$config_stage"; die "Ghép máy thất bại"; }
  [ -s "$config_stage" ] || { rm -f "$config_stage"; die "Credential ghép máy bị trống"; }

  local file
  for file in "$ID_FILE" "$GROUP_FILE" "$CONFIG_FILE"; do
    [ ! -f "$file" ] || cp -p "$file" "${file}.bak-${STAMP}"
  done
  printf '%s\n' "$DEVICE_ID" > "${ID_FILE}.tmp"
  printf '%s\n' "$DEVICE_GROUP" > "${GROUP_FILE}.tmp"
  chmod 600 "$config_stage" 2>/dev/null || true
  mv -f "${ID_FILE}.tmp" "$ID_FILE"
  mv -f "${GROUP_FILE}.tmp" "$GROUP_FILE"
  mv -f "$config_stage" "$CONFIG_FILE"
  chmod 600 "$CONFIG_FILE" 2>/dev/null || true
  config_matches_identity || die "Postcondition identity/config thất bại"
  ok "Đã tự tạo device_id.txt, device_group.txt và agent_config.json"
}

install_service() {
  local service_stage
  service_stage="$(mktemp "$INSTALL_ROOT/.service.XXXXXX")"
  cp -p "$RELEASE_DIR/deploy/device_service.sh" "$service_stage"
  chmod 700 "$service_stage"
  if [ -f "$SERVICE_CMD" ] && cmp -s "$service_stage" "$SERVICE_CMD"; then
    rm -f "$service_stage"
  else
    [ ! -f "$SERVICE_CMD" ] || cp -p "$SERVICE_CMD" "${SERVICE_CMD}.bak-${STAMP}"
    mv -f "$service_stage" "$SERVICE_CMD"
  fi

  local boot_stage
  boot_stage="$(mktemp "$INSTALL_ROOT/.boot.XXXXXX")"
  cat > "$boot_stage" <<'BOOT'
#!/data/data/com.termux/files/usr/bin/bash
sleep 2
"$HOME/bin/phanserver-agent" start >> "$HOME/.phanserver-delta/boot.log" 2>&1 || true
BOOT
  chmod 700 "$boot_stage"
  if [ -f "$BOOT_FILE" ] && cmp -s "$boot_stage" "$BOOT_FILE"; then
    rm -f "$boot_stage"
  else
    [ ! -f "$BOOT_FILE" ] || cp -p "$BOOT_FILE" "${BOOT_FILE}.bak-${STAMP}"
    mv -f "$boot_stage" "$BOOT_FILE"
  fi
  ok "Đã cài service và Termux:Boot entry"
}

activate_release() {
  local previous=""
  if [ -L "$CURRENT_LINK" ]; then
    previous="$(readlink "$CURRENT_LINK" || true)"
  fi
  if [ -n "$previous" ] && [ "$previous" != "$RELEASE_DIR" ] && [ -d "$previous" ]; then
    ln -sfn "$previous" "${LAST_GOOD_LINK}.tmp"
    mv -Tf "${LAST_GOOD_LINK}.tmp" "$LAST_GOOD_LINK"
  fi
  ln -sfn "$RELEASE_DIR" "${CURRENT_LINK}.tmp"
  mv -Tf "${CURRENT_LINK}.tmp" "$CURRENT_LINK"
  printf '%s\n' "$previous"
}

verify_online() {
  "$PYTHON" - "$WORKER_ORIGIN" "$DEVICE_ID" <<'PY'
import json
import sys
import time
import urllib.request
origin, device_id = sys.argv[1:3]
deadline = time.monotonic() + 35
while time.monotonic() < deadline:
    try:
        req = urllib.request.Request(origin.rstrip("/") + "/aot/hub/state", headers={"Cache-Control": "no-store"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read(1024 * 1024).decode("utf-8"))
        devices = data.get("state", {}).get("devices", [])
        target = next((item for item in devices if item.get("device_id") == device_id), None)
        if target and target.get("online") and "allocate_server_2pc" in (target.get("capabilities") or []):
            print("PHANSERVER_SERVER_ONLINE=YES")
            print("PHANSERVER_ALLOCATE_CAPABILITY=YES")
            raise SystemExit(0)
    except Exception:
        pass
    time.sleep(2)
print("PHANSERVER_SERVER_ONLINE=NO")
raise SystemExit(1)
PY
}

build_release
install_identity_and_config
install_service
PREVIOUS_RELEASE="$(activate_release)"
if ! "$SERVICE_CMD" restart; then
  if [ -n "$PREVIOUS_RELEASE" ] && [ -d "$PREVIOUS_RELEASE" ]; then
    warn "Khởi động bản mới lỗi; rollback current về bản trước"
    ln -sfn "$PREVIOUS_RELEASE" "${CURRENT_LINK}.rollback"
    mv -Tf "${CURRENT_LINK}.rollback" "$CURRENT_LINK"
    "$SERVICE_CMD" restart || true
  fi
  die "Agent service không khởi động được"
fi

if ! verify_online; then
  if [ -L "$LAST_GOOD_LINK" ]; then
    PREVIOUS_RELEASE="$(readlink "$LAST_GOOD_LINK" || true)"
  fi
  if [ -n "$PREVIOUS_RELEASE" ] && [ -d "$PREVIOUS_RELEASE" ]; then
    warn "Bản mới không ONLINE; rollback về last_good"
    ln -sfn "$PREVIOUS_RELEASE" "${CURRENT_LINK}.rollback"
    mv -Tf "${CURRENT_LINK}.rollback" "$CURRENT_LINK"
    "$SERVICE_CMD" restart || true
  fi
  die "Server chưa thấy $DEVICE_ID ONLINE với allocate_server_2pc"
fi

ok "device_id=$DEVICE_ID"
ok "device_group=$DEVICE_GROUP"
ok "revision=$REVISION"
ok "Agent WebSocket ONLINE và có allocate_server_2pc"
echo "PHANSERVER_ONBOARDING=READY"
echo "Lần sau chỉ dùng Telegram: /phanserver $DEVICE_ID <1..10>"

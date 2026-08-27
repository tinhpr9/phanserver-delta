#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ok() { echo "[OK] $*"; }
warn() { echo "[!] $*"; }
die() { echo "[LỖI] $*" >&2; exit 1; }

usage() {
  echo "Cách dùng: install.sh 73 2"
  echo "          install.sh m73 NOVA"
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
[[ "$SOURCE_REF" =~ ^[A-Za-z0-9._/-]+$ ]] || die "PHANSERVER_REF chứa ký tự không hợp lệ"
case "$WORKER_ORIGIN" in
  https://*) ;;
  *) die "PHANSERVER_WORKER_ORIGIN phải dùng HTTPS" ;;
esac
WORKER_ORIGIN="${WORKER_ORIGIN%/}"

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

resolve_revision() {
  local ref="$1"
  if [[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
    printf '%s\n' "$(printf '%s' "$ref" | tr '[:upper:]' '[:lower:]')"
    return 0
  fi
  local tmp resolved
  tmp="$(mktemp)"
  curl -fsSL --retry 3 --connect-timeout 15 \
    -H 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/tinhpr9/phanserver-delta/commits/$ref" \
    -o "$tmp" || { rm -f "$tmp"; return 1; }
  resolved="$($PYTHON - "$tmp" <<'PY'
import json, pathlib, re, sys
try:
    sha = str(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")).get("sha") or "").lower()
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
DEVICE_ROOT="$INSTALL_ROOT/device"
ID_FILE="$DEVICE_ROOT/device_id.txt"
GROUP_FILE="$DEVICE_ROOT/device_group.txt"
CONFIG_FILE="$DEVICE_ROOT/agent_config.json"
BIN_DIR="$HOME/bin"
SERVICE_CMD="$BIN_DIR/phanserver-agent"
BOOT_DIR="$HOME/.termux/boot"
BOOT_FILE="$BOOT_DIR/02-phanserver-delta.sh"
STAMP="$(date +%Y%m%d-%H%M%S)"
TX_DIR="$INSTALL_ROOT/.txn-$STAMP-$$"
ROLLBACK_ARMED=0

mkdir -p "$INSTALL_ROOT" "$RELEASE_ROOT" "$DEVICE_ROOT" "$BIN_DIR" "$BOOT_DIR"
chmod 700 "$INSTALL_ROOT" "$DEVICE_ROOT" 2>/dev/null || true

snapshot_file() {
  local name="$1" path="$2"
  mkdir -p "$TX_DIR/files"
  if [ -f "$path" ]; then
    cp -p "$path" "$TX_DIR/files/$name"
    : > "$TX_DIR/$name.present"
  else
    : > "$TX_DIR/$name.absent"
  fi
}

restore_file() {
  local name="$1" path="$2"
  if [ -f "$TX_DIR/$name.present" ]; then
    mkdir -p "$(dirname "$path")"
    cp -p "$TX_DIR/files/$name" "$path"
  elif [ -f "$TX_DIR/$name.absent" ]; then
    rm -f "$path"
  fi
}

rollback_transaction() {
  [ "$ROLLBACK_ARMED" = "1" ] || return 0
  ROLLBACK_ARMED=0
  set +e
  warn "Setup lỗi; đang khôi phục trạng thái trước đó"
  [ -x "$SERVICE_CMD" ] && "$SERVICE_CMD" stop >/dev/null 2>&1

  if [ -f "$TX_DIR/current.present" ]; then
    previous="$(cat "$TX_DIR/current.target" 2>/dev/null)"
    rm -f "$CURRENT_LINK"
    [ -n "$previous" ] && ln -s "$previous" "$CURRENT_LINK"
  else
    rm -f "$CURRENT_LINK"
  fi

  restore_file identity "$ID_FILE"
  restore_file group "$GROUP_FILE"
  restore_file config "$CONFIG_FILE"
  restore_file service "$SERVICE_CMD"
  restore_file boot "$BOOT_FILE"

  if [ -x "$SERVICE_CMD" ] && [ -L "$CURRENT_LINK" ]; then
    "$SERVICE_CMD" start >/dev/null 2>&1 || true
  fi
  echo "PHANSERVER_ROLLBACK=RESTORED"
}
trap rollback_transaction ERR

build_release() {
  if [ -f "$RELEASE_DIR/agent/secure_agent.py" ] && [ -f "$RELEASE_DIR/deploy/device_service.sh" ]; then
    ok "Runtime revision=$REVISION đã có sẵn"
    return 0
  fi

  local stage path
  stage="$(mktemp -d "$INSTALL_ROOT/.stage.XXXXXX")"
  mkdir -p "$stage/agent" "$stage/delta" "$stage/deploy"
  local paths=(
    "agent/agent.py"
    "agent/secure_agent.py"
    "agent/config.py"
    "agent/server_links.py"
    "delta/delta_updater.py"
    "deploy/device_service.sh"
  )
  for path in "${paths[@]}"; do
    curl -fsSL --retry 3 --connect-timeout 15 "$RAW/$path" -o "$stage/$path" || {
      rm -rf "$stage"
      die "Không tải được $path ở revision $REVISION"
    }
    [ -s "$stage/$path" ] || { rm -rf "$stage"; die "$path tải về bị trống"; }
  done

  "$PYTHON" -m py_compile \
    "$stage/agent/agent.py" "$stage/agent/secure_agent.py" \
    "$stage/agent/config.py" "$stage/agent/server_links.py" \
    "$stage/delta/delta_updater.py" || { rm -rf "$stage"; die "Runtime Python sai cú pháp"; }
  bash -n "$stage/deploy/device_service.sh" || { rm -rf "$stage"; die "device_service.sh sai cú pháp"; }
  chmod 700 "$stage/deploy/device_service.sh"
  mv "$stage" "$RELEASE_DIR" || die "Không materialize được release $REVISION"
  ok "Đã tải runtime revision=$REVISION"
}

config_matches_identity() {
  [ -f "$ID_FILE" ] && [ -f "$GROUP_FILE" ] && [ -f "$CONFIG_FILE" ] || return 1
  [ "$(tr -d '\r\n ' < "$ID_FILE" | tr '[:upper:]' '[:lower:]')" = "$DEVICE_ID" ] || return 1
  [ "$(tr -d '\r\n ' < "$GROUP_FILE" | tr '[:lower:]' '[:upper:]')" = "$DEVICE_GROUP" ] || return 1
  "$PYTHON" - "$CONFIG_FILE" "$WORKER_ORIGIN" <<'PY'
import json, pathlib, sys
from urllib.parse import urlparse
try:
    data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)
origin = sys.argv[2].rstrip("/")
url = str(data.get("worker_report_url") or "").strip()
secret = str(data.get("agent_report_secret") or "").strip()
p = urlparse(url)
actual = f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""
if actual != origin or p.path != "/report" or len(secret) < 32:
    raise SystemExit(1)
PY
}

pair_device() {
  local output="$1"
  "$PYTHON" - "$WORKER_ORIGIN" "$DEVICE_ID" "$DEVICE_GROUP" "$output" <<'PY'
import json, os, pathlib, sys, time, urllib.error, urllib.request
origin, device_id, device_group, output_raw = sys.argv[1:5]
output = pathlib.Path(output_raw)

def post(path, payload, timeout=20):
    req = urllib.request.Request(
        origin.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type":"application/json","Accept":"application/json","Cache-Control":"no-store"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read(65536).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read(65536)
        try: data = json.loads(raw.decode("utf-8"))
        except Exception: data = {}
        return exc.code, data

status, data = post("/agent/pair/request", {"device_id":device_id,"device_group":device_group})
if status == 409 and data.get("error") == "pair_already_pending":
    print("[LỖI] Máy này đang có yêu cầu ghép khác chưa hết hạn; chờ yêu cầu cũ hết hạn rồi chạy lại.")
    raise SystemExit(1)
if status != 201 or not data.get("ok"):
    print(f"[LỖI] Không tạo được yêu cầu ghép máy: HTTP {status} {data.get('error','')}")
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
    status, data = post("/agent/pair/status", {"pair_id":pair_id,"pair_token":pair_token})
    if status == 202: continue
    if status == 200 and data.get("ok") and data.get("status") == "approved":
        report_url = str(data.get("worker_report_url") or "").strip()
        secret = str(data.get("agent_report_secret") or "").strip()
        if report_url != origin.rstrip("/") + "/report" or len(secret) < 32:
            print("[LỖI] Worker trả credential không hợp lệ")
            raise SystemExit(1)
        tmp = output.with_name(output.name + ".tmp")
        tmp.write_text(json.dumps({"worker_report_url":report_url,"agent_report_secret":secret}, indent=2) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(output)
        print("[OK] Ghép máy thành công; credential không được in ra màn hình.")
        raise SystemExit(0)
    if status in {403,404,409,410}:
        print(f"[LỖI] Ghép máy không hoàn tất: HTTP {status} {data.get('error','')}")
        raise SystemExit(1)
print("[LỖI] Hết thời gian chờ xác nhận Telegram")
raise SystemExit(1)
PY
}

install_service_and_boot() {
  cp -p "$RELEASE_DIR/deploy/device_service.sh" "$SERVICE_CMD"
  chmod 700 "$SERVICE_CMD"
  cat > "$BOOT_FILE" <<'BOOT'
#!/data/data/com.termux/files/usr/bin/bash
sleep 2
"$HOME/bin/phanserver-agent" start >> "$HOME/.phanserver-delta/boot.log" 2>&1 || true
BOOT
  chmod 700 "$BOOT_FILE"
}

verify_online() {
  "$PYTHON" - "$WORKER_ORIGIN" "$DEVICE_ID" "$CONFIG_FILE" <<'PY'
import json, pathlib, sys, time, urllib.error, urllib.request
origin, device_id, config_path = sys.argv[1:4]
config = json.loads(pathlib.Path(config_path).read_text(encoding="utf-8"))
secret = str(config.get("agent_report_secret") or "")
if len(secret) < 32: raise SystemExit(1)
deadline = time.monotonic() + 40
while time.monotonic() < deadline:
    req = urllib.request.Request(
        origin.rstrip("/") + "/agent/status",
        data=json.dumps({"device_id":device_id}).encode("utf-8"),
        method="POST",
        headers={"Content-Type":"application/json","X-Agent-Secret":secret,"Cache-Control":"no-store"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read(65536).decode("utf-8"))
        device = data.get("device") or {}
        if device.get("device_id") == device_id and device.get("online") and "allocate_server_2pc" in (device.get("capabilities") or []):
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

CONFIG_STAGE="$(mktemp "$INSTALL_ROOT/.agent-config.XXXXXX")"
rm -f "$CONFIG_STAGE"
if config_matches_identity; then
  cp -p "$CONFIG_FILE" "$CONFIG_STAGE"
  ok "Identity/config hiện tại khớp; không ghép lại"
else
  pair_device "$CONFIG_STAGE"
fi
[ -s "$CONFIG_STAGE" ] || die "Credential ghép máy bị trống"

mkdir -p "$TX_DIR"
snapshot_file identity "$ID_FILE"
snapshot_file group "$GROUP_FILE"
snapshot_file config "$CONFIG_FILE"
snapshot_file service "$SERVICE_CMD"
snapshot_file boot "$BOOT_FILE"
if [ -L "$CURRENT_LINK" ]; then
  : > "$TX_DIR/current.present"
  readlink "$CURRENT_LINK" > "$TX_DIR/current.target"
elif [ -e "$CURRENT_LINK" ]; then
  rm -f "$CONFIG_STAGE"
  die "current tồn tại nhưng không phải symlink"
else
  : > "$TX_DIR/current.absent"
fi
ROLLBACK_ARMED=1

printf '%s\n' "$DEVICE_ID" > "$ID_FILE.tmp"
printf '%s\n' "$DEVICE_GROUP" > "$GROUP_FILE.tmp"
chmod 600 "$ID_FILE.tmp" "$GROUP_FILE.tmp" "$CONFIG_STAGE"
mv -f "$ID_FILE.tmp" "$ID_FILE"
mv -f "$GROUP_FILE.tmp" "$GROUP_FILE"
mv -f "$CONFIG_STAGE" "$CONFIG_FILE"
chmod 600 "$ID_FILE" "$GROUP_FILE" "$CONFIG_FILE"

install_service_and_boot

PREVIOUS_RELEASE=""
if [ -L "$CURRENT_LINK" ]; then PREVIOUS_RELEASE="$(readlink "$CURRENT_LINK")"; fi
if [ -n "$PREVIOUS_RELEASE" ] && [ "$PREVIOUS_RELEASE" != "$RELEASE_DIR" ] && [ -d "$PREVIOUS_RELEASE" ]; then
  rm -f "$LAST_GOOD_LINK"
  ln -s "$PREVIOUS_RELEASE" "$LAST_GOOD_LINK"
fi
rm -f "$CURRENT_LINK"
ln -s "$RELEASE_DIR" "$CURRENT_LINK"

"$SERVICE_CMD" restart
verify_online

ROLLBACK_ARMED=0
rm -rf "$TX_DIR"
ok "device_id=$DEVICE_ID"
ok "device_group=$DEVICE_GROUP"
ok "revision=$REVISION"
ok "Agent WebSocket ONLINE và có allocate_server_2pc"
echo "PHANSERVER_ONBOARDING=READY"
echo "Lần sau chỉ dùng Telegram: /phanserver $DEVICE_ID <1..10>"

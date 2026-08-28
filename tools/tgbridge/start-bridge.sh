#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
: "${TG_BRIDGE_STATE_DIR:=$HOME/tgbridge}"
: "${TG_BRIDGE_TOKEN_FILE:=$TG_BRIDGE_STATE_DIR/token}"
: "${TG_BRIDGE_CHAT_ID_FILE:=$TG_BRIDGE_STATE_DIR/chat_id}"

test -s "$TG_BRIDGE_TOKEN_FILE"
test -s "$TG_BRIDGE_CHAT_ID_FILE"
exec python3 "$ROOT_DIR/tools/tgbridge/bridge.py"

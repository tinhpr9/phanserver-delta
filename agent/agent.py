#!/usr/bin/env python3
"""
Minimal Device Agent for phanserver-delta.

Supported functions:
- APPLY_SERVER_LINKS (2PC Prepare, Commit, Abort)
- UPDATE_DELTA (Standalone Delta Updater integration)
- Heartbeat / reporting to phanserver-delta worker
"""

import argparse
import base64
import json
import os
import pathlib
import re
import shlex
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import codecs
from typing import Any, Dict, Optional


def _ensure_cp437():
    try:
        codecs.lookup("cp437")
    except LookupError:
        try:
            latin1 = codecs.lookup("latin-1")
            codecs.register(lambda name: latin1 if name.lower() in ("cp437", "ibm437", "437") else None)
        except Exception:
            pass

_ensure_cp437()

# Ensure package and local imports work
ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT_DIR = pathlib.Path(__file__).resolve().parent
DELTA_DIR = ROOT / "delta"

for p in (str(ROOT), str(AGENT_DIR), str(DELTA_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from agent import account_manager, config, dns_fallback, server_links
except ImportError:
    import account_manager
    import config
    import dns_fallback
    import server_links

# Install resilient DNS fallback for Android VPN environments immediately
dns_fallback.install_dns_fallback()

try:
    from delta import delta_updater
except ImportError:
    import delta_updater

AGENT_VERSION = "phanserver-delta-agent-1.0.0"
PROTOCOL_VERSION = "fleet-batch-v1"
CAPABILITIES = ["allocate_server_2pc", "update_delta", "check_ban", "add_acc", "del_acc", "control_tailscale", "move_acc", "tab_list", "auto_login"]


def validate_tailscale_cgnat_ip(ip: Optional[str]) -> bool:
    """Validate if an IP string is a valid Tailscale CGNAT IP (100.x.y.z where octets are 0-255)."""
    if not ip or not isinstance(ip, str):
        return False
    m = re.match(r"^100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$", ip.strip())
    if not m:
        return False
    octets = [int(g) for g in m.groups()]
    return all(0 <= o <= 255 for o in octets)


def detect_tailscale_ip() -> Optional[str]:
    """Inspect system network interfaces to detect active Tailscale CGNAT IP (100.x.y.z)."""
    cmd_candidates = [
        ["/system/bin/ip", "-4", "addr", "show"],
        ["ip", "-4", "addr", "show"],
    ]
    for cmd in cmd_candidates:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
            if res.returncode == 0 and res.stdout:
                matches = re.findall(r"(?<![0-9a-zA-Z.])\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b(?![0-9a-zA-Z.])", res.stdout)
                for candidate in matches:
                    if validate_tailscale_cgnat_ip(candidate):
                        return candidate
        except Exception:
            pass
    return None


def collect_metrics() -> dict[str, Any]:
    metrics = {
        "uptime": 0,
        "load_1m": 0.0,
        "mem_available_mb": 0,
        "battery_pct": 100,
        "tailscale_ip": None,
        "tailscale_connected": False,
    }
    try:
        with open("/proc/uptime", "r") as f:
            metrics["uptime"] = int(float(f.read().split()[0]))
    except Exception:
        pass
    try:
        with open("/proc/loadavg", "r") as f:
            metrics["load_1m"] = float(f.read().split()[0])
    except Exception:
        pass
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    metrics["mem_available_mb"] = int(line.split()[1]) // 1024
                    break
    except Exception:
        pass
    try:
        ts_ip = detect_tailscale_ip()
        if ts_ip:
            metrics["tailscale_ip"] = ts_ip
            metrics["tailscale_connected"] = True
    except Exception:
        pass
    return metrics


def send_report_response(report_url: str, secret: str, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            report_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": AGENT_VERSION,
                "X-Agent-Secret": secret,
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 201):
                print(f"[AGENT] Heartbeat HTTP lỗi status={resp.status}", flush=True)
                return None
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
        print(f"[AGENT] Heartbeat lỗi kết nối: {e}", flush=True)
        return None


def send_report(report_url: str, secret: str, payload: dict[str, Any]) -> bool:
    return send_report_response(report_url, secret, payload) is not None


def send_ack(
    report_url: str,
    secret: str,
    device_id: str,
    action_id: str,
    status: str,
    reason: Optional[str] = None,
    executed: bool = False,
    batch_action: str = "ALLOCATE_SERVER",
    details: Optional[Any] = None,
) -> bool:
    parsed = urllib.parse.urlparse(report_url)
    ack_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/aot/ack", "", "", ""))
    payload = {
        "protocol": PROTOCOL_VERSION,
        "batch_action": batch_action,
        "device_id": device_id,
        "action_id": action_id,
        "status": status,
        "executed": executed,
    }
    if reason:
        payload["reason"] = reason
    if details is not None:
        payload["details"] = details
    return send_report(ack_url, secret, payload)


def compute_screen_coordinates(width: int, height: int, rotation: int = 0) -> dict[str, Any]:
    """
    Computes adaptive touch coordinates for Tailscale based on screen resolution and rotation.
    rotation: 0 (portrait 0°), 1 (landscape 90°), 2 (portrait 180°), 3 (landscape 270°).
    If rotation is 0/2 but width > height, it is treated as landscape.
    """
    min_d = min(int(width), int(height))
    max_d = max(int(width), int(height))
    is_landscape = (rotation in (1, 3)) or (rotation not in (1, 3) and int(width) > int(height))
    if is_landscape:
        w = max_d
        h = min_d
        toggle_x = int(w * 0.92)
        toggle_y = int(h * 0.12)
    else:
        w = min_d
        h = max_d
        toggle_x = int(w * 0.88)
        toggle_y = int(h * 0.08)
    center_x = int(w / 2)
    center_y = int(h / 2)
    return {
        "is_landscape": is_landscape,
        "width": w,
        "height": h,
        "toggle_x": toggle_x,
        "toggle_y": toggle_y,
        "center_x": center_x,
        "center_y": center_y,
    }


def build_tailscale_command(mode: str = "on") -> str:
    """Generate shell script command to control Tailscale on Android/UgPhone."""
    mode = str(mode or "on").lower()
    if mode == "off":
        return """
export PATH="/system/bin:/system/xbin:/data/data/com.termux/files/usr/bin:$PATH"
am broadcast --user 0 -a com.tailscale.ipn.DISCONNECT_VPN -n com.tailscale.ipn/.IPNReceiver >/dev/null 2>&1 || true
am broadcast --user 0 -a com.tailscale.ipn.DISCONNECT_VPN -p com.tailscale.ipn >/dev/null 2>&1 || true
am broadcast -a com.tailscale.ipn.DISCONNECT_VPN -p com.tailscale.ipn >/dev/null 2>&1 || true
cmd statusbar click-tile com.tailscale.ipn/.QuickToggleService >/dev/null 2>&1 || true
settings delete secure always_on_vpn_app >/dev/null 2>&1 || true
am force-stop --user 0 com.tailscale.ipn >/dev/null 2>&1 || true
am force-stop com.tailscale.ipn >/dev/null 2>&1 || true
echo "DISCONNECTED"
"""
    elif mode == "status":
        return """
export PATH="/system/bin:/system/xbin:/data/data/com.termux/files/usr/bin:$PATH"
IP_BIN=$(which ip 2>/dev/null || echo "/system/bin/ip")
IP=$($IP_BIN -4 addr show dev tun0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d'/' -f1 | head -n 1)
if [ -z "$IP" ]; then
    IP=$($IP_BIN -4 addr show 2>/dev/null | grep -oE '100\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}' | head -n 1)
fi

if [ -n "$IP" ]; then
    echo "CONNECTED: $IP"
else
    echo "DISCONNECTED"
fi
"""
    else:
        # mode == "on"
        return """
export PATH="/system/bin:/system/xbin:/data/data/com.termux/files/usr/bin:$PATH"
IP_BIN=$(which ip 2>/dev/null || echo "/system/bin/ip")
settings put secure always_on_vpn_app com.tailscale.ipn >/dev/null 2>&1 || true
settings put secure always_on_vpn_lockdown 0 >/dev/null 2>&1 || true
am broadcast --user 0 -a com.tailscale.ipn.CONNECT_VPN -n com.tailscale.ipn/.IPNReceiver >/dev/null 2>&1 || true
am broadcast --user 0 -a com.tailscale.ipn.CONNECT_VPN -p com.tailscale.ipn >/dev/null 2>&1 || true
am broadcast -a com.tailscale.ipn.CONNECT_VPN -p com.tailscale.ipn >/dev/null 2>&1 || true
cmd statusbar click-tile com.tailscale.ipn/.QuickToggleService >/dev/null 2>&1 || true
am start --user 0 -n com.tailscale.ipn/.MainActivity >/dev/null 2>&1 || am start -n com.tailscale.ipn/.MainActivity >/dev/null 2>&1 || true
sleep 1

IP=$($IP_BIN -4 addr show dev tun0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d'/' -f1 | head -n 1)
if [ -z "$IP" ]; then
    IP=$($IP_BIN -4 addr show 2>/dev/null | grep -oE '100\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}' | head -n 1)
fi

if [ -z "$IP" ]; then
    RAW_SIZE=$(wm size 2>/dev/null | tail -n 1 | awk '{print $NF}')
    DIM_W=$(echo "$RAW_SIZE" | cut -d'x' -f1)
    DIM_H=$(echo "$RAW_SIZE" | cut -d'x' -f2)
    [ -z "$DIM_W" ] && DIM_W=720
    [ -z "$DIM_H" ] && DIM_H=1280

    if [ "$DIM_W" -gt "$DIM_H" ] 2>/dev/null; then
        TOGGLE_X=$((DIM_W * 92 / 100))
        TOGGLE_Y=$((DIM_H * 12 / 100))
    else
        TOGGLE_X=$((DIM_W * 88 / 100))
        TOGGLE_Y=$((DIM_H * 8 / 100))
    fi
    CENTER_X=$((DIM_W / 2))
    CENTER_Y=$((DIM_H / 2))

    input tap "$TOGGLE_X" "$TOGGLE_Y" >/dev/null 2>&1 || true
    input tap "$CENTER_X" "$CENTER_Y" >/dev/null 2>&1 || true
    input keyevent KEYCODE_TAB >/dev/null 2>&1 || true
    input keyevent KEYCODE_ENTER >/dev/null 2>&1 || true
    input keyevent KEYCODE_DPAD_CENTER >/dev/null 2>&1 || true
fi

for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    IP=$($IP_BIN -4 addr show dev tun0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d'/' -f1 | head -n 1)
    if [ -z "$IP" ]; then
        IP=$($IP_BIN -4 addr show 2>/dev/null | grep -oE '100\\.[0-9]{1,3}\\.[0-9]{1,3}\\.[0-9]{1,3}' | head -n 1)
    fi
    if [ -n "$IP" ]; then
        break
    fi
    if [ "$i" -eq 4 ] || [ "$i" -eq 8 ] || [ "$i" -eq 12 ]; then
        if [ -n "$TOGGLE_X" ] && [ -n "$CENTER_X" ]; then
            input tap "$TOGGLE_X" "$TOGGLE_Y" >/dev/null 2>&1 || true
            input tap "$CENTER_X" "$CENTER_Y" >/dev/null 2>&1 || true
            input keyevent KEYCODE_ENTER >/dev/null 2>&1 || true
        fi
    fi
    sleep 1
done

if [ -n "$IP" ]; then
    input keyevent KEYCODE_BACK >/dev/null 2>&1 || true
    sleep 0.5
    input keyevent KEYCODE_HOME >/dev/null 2>&1 || true
    echo "CONNECTED: $IP"
    exit 0
else
    echo "vpn_timeout_no_ip: Timeout 15s không nhận được IP Tailscale (100.x.y.z)" >&2
    exit 1
fi
"""


TAB_PACKAGE_MAP = {
    "com.tinh.vv.hi": 1,
    "com.tinh.vv.hj": 2,
    "com.tinh.vv.hk": 3,
    "com.tinh.vv.hl": 4,
    "com.tinh.vv.hm": 5,
    "com.tinh.vv.hn": 6,
    "com.tinh.vv.ho": 7,
    "com.tinh.vv.hp": 8,
    "com.tinh.vv.hq": 9,
    "com.tinh.vv.hr": 10,
}
PACKAGE_TAB_MAP = TAB_PACKAGE_MAP
TAB_TO_PACKAGE_MAP = {v: k for k, v in TAB_PACKAGE_MAP.items()}

DEFAULT_TAB_ACCOUNTS = {
    "com.tinh.vv.hi": "BreckenLife330",
    "com.tinh.vv.hj": "ShadowWoodrow820",
    "com.tinh.vv.hk": "MysticjUBuildery1999",
    "com.tinh.vv.hl": "VanessaJoseph403",
    "com.tinh.vv.hm": "JeremiahWilkerson46",
    "com.tinh.vv.hn": "FuryuYQuantumD",
    "com.tinh.vv.ho": "Mega_Wiley623",
    "com.tinh.vv.hp": "Zephyra_Pro731",
    "com.tinh.vv.hq": "Nova71Fox11Panda1991",
    "com.tinh.vv.hr": "TigerYnG0ldenD199519",
}


def unwrap_su_inner(inner: str) -> str:
    """
    Safely unwrap and unescape outer wrapping quotes for su -c arguments.
    Preserves inner quote structures (like 'echo 1' && 'echo 2') while properly
    stripping enclosing quotes and handling escaped quotes/dollars/backslashes.
    """
    s = inner.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        quote = s[0]
        i = 1
        in_escape = False
        while i < len(s) - 1:
            c = s[i]
            if quote == '"':
                if in_escape:
                    in_escape = False
                    i += 1
                    continue
                if c == '\\':
                    in_escape = True
                    i += 1
                    continue
                if c == '"':
                    return s  # Closed early before end, don't strip
            else:
                if c == "'":
                    return s  # Single quote closed early
            i += 1
        if in_escape:
            # Trailing quote was escaped by preceding backslash, not a true closing quote
            return s
        body = s[1:-1]
        if quote == '"':
            # Unescape \" -> ", \$ -> $, \` -> `, \\ -> \
            body = re.sub(r'\\([\"$`\\])', r'\1', body)
        return body
    return s


def run_adb_shell(command: str | list[str], timeout: int = 15) -> str:
    """Execute an ADB shell command and return stdout."""
    raw_cmd = command if isinstance(command, str) else " ".join(command)
    env = os.environ.copy()
    std_paths = ["/system/bin", "/system/xbin", "/vendor/bin", "/sbin", "/data/data/com.termux/files/usr/bin"]
    curr_path = env.get("PATH", "")
    for p in std_paths:
        if p not in curr_path:
            curr_path = f"{p}:{curr_path}" if curr_path else p
    env["PATH"] = curr_path

    # 1. Try adb shell
    try:
        res = subprocess.run(["adb", "shell", raw_cmd], capture_output=True, text=True, timeout=timeout, env=env)
        if res.returncode == 0 and res.stdout:
            return res.stdout
    except Exception:
        pass
    # 2. Direct shell / su fallback for rooted Android/local environment without adb daemon
    prefix_match = re.match(r"^(?:(?:/system/bin/|/system/xbin/)?su\s+-c\s+)(.*)$", raw_cmd)
    if prefix_match:
        inner_cmd = prefix_match.group(1).strip()
        inner_cmd = unwrap_su_inner(inner_cmd)
        fallback_shells = [
            ["sh", "-c", raw_cmd],
            ["/system/bin/su", "-c", inner_cmd],
            ["/system/xbin/su", "-c", inner_cmd],
            ["su", "-c", inner_cmd],
        ]
    else:
        fallback_shells = [
            ["sh", "-c", raw_cmd],
            ["su", "-c", raw_cmd],
            ["/system/bin/su", "-c", raw_cmd],
            ["/system/xbin/su", "-c", raw_cmd],
        ]
    for shell_cmd in fallback_shells:
        try:
            res = subprocess.run(shell_cmd, capture_output=True, text=True, timeout=timeout, env=env)
            if res.returncode == 0 and res.stdout:
                return res.stdout
        except Exception:
            pass
    return ""


def extract_username_from_text(text: Optional[str]) -> Optional[str]:
    """Extract Roblox username from XML shared preferences, JSON, or key-value activity state."""
    if not text:
        return None

    import html
    invalid_usernames = (
        "null", "none", "unknown", "false", "true", "undefined", "default", "guest", "anonymous",
        "roblox", "client", "activity", "mainactivity", "protocol", "launch", "application", "app",
        "home", "discover", "avatar", "marketplace", "settings", "chat", "loading", "login",
        "signup", "sign_up", "profile", "games", "game", "experience", "experiences", "catalog",
        "feed", "friends", "groups", "inventory", "messages", "notifications", "search",
        "❓"
    )
    historical_keywords = ("previous", "signout", "signedout", "history", "last_logged", "old_user", "prior_")

    # Clean non-printable control characters and null bytes (excluding \t, \n, \r)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    def _validate_username(val: Any) -> Optional[str]:
        if not val:
            return None
        if isinstance(val, (int, float, dict, list)):
            return None
        s = str(val).strip()
        # Unescape HTML entities
        s = html.unescape(s)
        # Unwrap quotes if stringified JSON
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            try:
                unquoted = json.loads(s, strict=False)
                if isinstance(unquoted, str):
                    s = unquoted.strip()
                else:
                    s = s.strip('"\' ')
            except Exception:
                s = s.strip('"\' ')
        # Remove any residual escaped quotes or leading/trailing punctuation
        s = s.replace('\\"', '').replace('\\', '').strip('"\'; \t\r\n')
        if s and s.lower() not in invalid_usernames and not s.startswith("❓"):
            if re.match(r"^[a-zA-Z0-9_]{3,30}$", s):
                return s
        return None

    def _extract_from_dict(d: dict, depth: int = 0) -> Optional[str]:
        if depth > 3:
            return None
        # Preferred keys for active user
        preferred_keys = [
            "Username", "RobloxUsername", "CurrentUsername",
            "username", "roblox_username", "current_username",
            "DisplayName", "display_name",
            "AccountName", "account_name",
            "CurrentUser", "current_user",
            "User", "user",
            "screen_name", "user_name"
        ]
        keys_to_check = list(preferred_keys)
        if depth > 0:
            keys_to_check.extend(["name", "Name"])
        for k in keys_to_check:
            if k in d:
                v = d[k]
                u = _validate_username(v)
                if u:
                    return u
                if isinstance(v, dict):
                    sub = _extract_from_dict(v, depth + 1)
                    if sub:
                        return sub
                elif isinstance(v, str) and v.strip().startswith("{") and v.strip().endswith("}"):
                    try:
                        sub_d = json.loads(v.strip(), strict=False)
                        if isinstance(sub_d, dict):
                            sub = _extract_from_dict(sub_d, depth + 1)
                            if sub:
                                return sub
                    except Exception:
                        pass

        # Check dotted or namespaced keys (e.g. Roblox.CurrentUser.Username)
        for k, v in d.items():
            k_lower = k.lower()
            if any(hk in k_lower for hk in historical_keywords):
                continue
            if k_lower.endswith((".username", "_username", ".displayname", "_displayname")) or k_lower in ("username", "robloxusername", "currentusername"):
                u = _validate_username(v)
                if u:
                    return u
                if isinstance(v, dict):
                    sub = _extract_from_dict(v, depth + 1)
                    if sub:
                        return sub
                elif isinstance(v, str) and v.strip().startswith("{") and v.strip().endswith("}"):
                    try:
                        sub_d = json.loads(v.strip(), strict=False)
                        if isinstance(sub_d, dict):
                            sub = _extract_from_dict(sub_d, depth + 1)
                            if sub:
                                return sub
                    except Exception:
                        pass
        return None

    # 1. Iterate through all JSON objects in stream (handles concatenated files/multi-user outputs)
    trimmed = text.strip()
    decoder = json.JSONDecoder(strict=False)
    idx = 0
    has_previous = False
    found_any_dict = False

    while idx < len(trimmed):
        next_brace = trimmed.find("{", idx)
        if next_brace == -1:
            break
        try:
            data, end_idx = decoder.raw_decode(trimmed, next_brace)
            idx = max(end_idx, next_brace + 1)
            if isinstance(data, dict):
                found_any_dict = True
                u = _extract_from_dict(data)
                if u:
                    return u
                if any(any(hk in str(k).lower() for hk in historical_keywords) for k in data.keys()):
                    has_previous = True
        except Exception:
            idx = next_brace + 1

    # 1.5 Handle string-escaped JSON (e.g. {\"Username\":\"...\"} or {\\"Username\\":...})
    if not found_any_dict and ('\\"' in text or '\\\\' in text):
        try:
            unescaped_json_text = text
            for _ in range(3):
                if '\\' not in unescaped_json_text:
                    break
                unescaped_json_text = unescaped_json_text.replace('\\\\', '\\').replace('\\"', '"')
            trimmed_unesc = unescaped_json_text.strip()
            idx_u = 0
            while idx_u < len(trimmed_unesc):
                next_b = trimmed_unesc.find("{", idx_u)
                if next_b == -1:
                    break
                try:
                    d_data, e_idx = decoder.raw_decode(trimmed_unesc, next_b)
                    idx_u = max(e_idx, next_b + 1)
                    if isinstance(d_data, dict):
                        found_any_dict = True
                        u = _extract_from_dict(d_data)
                        if u:
                            return u
                except Exception:
                    idx_u = next_b + 1
        except Exception:
            pass

    # Strip PreviousAccountsList and historical accounts before regex fallbacks (balanced bracket matching)
    cleaned_text = text
    for kw in ("previousaccountslist", "previousaccounts", "savedaccounts", "accountshistory"):
        pos = 0
        while pos < len(cleaned_text):
            m = re.search(r'(?i)["\']?' + re.escape(kw) + r'["\']?\s*:\s*', cleaned_text[pos:])
            if not m:
                break
            start = pos + m.start()
            val_start = pos + m.end()
            if val_start < len(cleaned_text):
                ch = cleaned_text[val_start]
                if ch in ('"', "'"):
                    str_m = re.match(r'^(?:"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')', cleaned_text[val_start:])
                    if str_m:
                        end = val_start + str_m.end()
                        cleaned_text = cleaned_text[:start] + cleaned_text[end:]
                        pos = start
                        continue
                elif ch in ('{', '['):
                    stack = [ch]
                    curr = val_start + 1
                    in_str = None
                    while curr < len(cleaned_text) and stack:
                        c = cleaned_text[curr]
                        if in_str:
                            if c == '\\':
                                curr += 1
                            elif c == in_str:
                                in_str = None
                        else:
                            if c in ('"', "'"):
                                in_str = c
                            elif c in ('{', '['):
                                stack.append(c)
                            elif c == '}' and stack[-1] == '{':
                                stack.pop()
                            elif c == ']' and stack[-1] == '[':
                                stack.pop()
                        curr += 1
                    cleaned_text = cleaned_text[:start] + cleaned_text[curr:]
                    pos = start
                    continue
            pos = val_start

    # Also apply regex cleanup for any flat or malformed historical entries
    cleaned_text = re.sub(r'(?i)["\']?previousaccounts(?:list)?["\']?\s*:\s*(?:\[[^\]]*\]|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\{[^\}]*\})', '', cleaned_text)

    # 2. Check XML string tags: <string name="...Username...">username</string> or with attributes
    unescaped_text = html.unescape(cleaned_text)
    xml_patterns = [
        r'<(?:string|entry)\s+[^>]*?(?:name|key)=["\'](?P<key>[^"\']*(?i:username|roblox_?user|account_?name|current_?user|display_?name|screen_?name)[^"\']*)["\'][^>]*>\s*(?:["\']|&quot;)?\s*(?P<val>[a-zA-Z0-9_]{3,30})\s*(?:["\']|&quot;)?\s*</(?:string|entry)>',
        r'<(?:string|entry)\s+[^>]*?(?:name|key)=["\'](?P<key>[^"\']*(?i:username|roblox_?user|account_?name|current_?user|display_?name|screen_?name)[^"\']*)["\'][^>]*?value=["\']\s*(?:["\']|&quot;)?\s*(?P<val>[a-zA-Z0-9_]{3,30})\s*(?:["\']|&quot;)?\s*["\']',
        r'<(?:string|entry)\s+[^>]*?value=["\']\s*(?:["\']|&quot;)?\s*(?P<val>[a-zA-Z0-9_]{3,30})\s*(?:["\']|&quot;)?\s*["\'][^>]*?(?:name|key)=["\'](?P<key>[^"\']*(?i:username|roblox_?user|account_?name|current_?user|display_?name|screen_?name)[^"\']*)["\']',
        r'<(?:string|entry)\s+[^>]*?(?:name|key)=["\'](?P<key>(?:Roblox)?(?:User|Account|Current)?(?:Name)?)["\'][^>]*>\s*(?:["\']|&quot;)?\s*(?P<val>[a-zA-Z0-9_]{3,30})\s*(?:["\']|&quot;)?\s*</(?:string|entry)>',
    ]
    for pat in xml_patterns:
        for m in re.finditer(pat, unescaped_text, re.IGNORECASE):
            key_attr = m.group("key").lower()
            if any(hk in key_attr for hk in historical_keywords):
                continue
            val = _validate_username(m.group("val"))
            if val:
                return val

    # If structured JSON was found and had historical/signed-out accounts with NO active user in JSON or XML,
    # cleanly return None (logged-out state).
    if found_any_dict and has_previous:
        return None

    # 3. Check JSON keys (regex pattern including dotted names and arbitrary escaped quotes)
    json_patterns = [
        r'(?:\\*["\'])(?:[a-zA-Z0-9_\.]*\.)?(?:username|roblox_?username|account_?name|user_name|current_?username|display_?name|screen_?name)(?:\\*["\'])\s*:\s*(?:\\*["\'])+(?:[a-zA-Z0-9_\.]*\.)?([a-zA-Z0-9_]{3,30})(?:\\*["\'])+',
        r'(?:\\*["\'])(?:[a-zA-Z0-9_\.]*\.)?(?:username|roblox_?username|account_?name|user_name|current_?username|display_?name|screen_?name)(?:\\*["\'])\s*:\s*(?:\\*["\'])?\s*([a-zA-Z0-9_]{3,30})\s*(?:\\*["\'])?',
    ]
    for pat in json_patterns:
        m = re.search(pat, cleaned_text, re.IGNORECASE)
        if m:
            val = _validate_username(m.group(1))
            if val:
                return val

    # 4. Check key-value, activity state, window titles, or logcat output
    kv_patterns = [
        r'(?i:\busername|\broblox_?username|\broblox_?user|\baccount_?name|\buser_name|\bcurrent_?username|\bdisplay_?name|\bscreen_?name)\s*[:=]\s*["\']?\s*([a-zA-Z0-9_]{3,30})\b',
        r'(?i:\btitle\s*=\s*["\']?Roblox\s*[-–—:]\s*.*?@([a-zA-Z0-9_]{3,30}))',
        r'(?i:\btitle\s*=\s*["\']?Roblox\s*[-–—:]\s*[^a-zA-Z0-9_]*([a-zA-Z0-9_]{3,30})[^a-zA-Z0-9_\r\n]*["\']?(?:\r?\n|$))',
        r'(?i:\bauthenticated\s+user[:\s]+["\']?([a-zA-Z0-9_]{3,30})["\']?)',
    ]
    for pat in kv_patterns:
        m = re.search(pat, cleaned_text, re.IGNORECASE)
        if m:
            val = _validate_username(m.group(1))
            if val:
                return val

    return None


def get_acc_fallback_username(
    tab_num: int | str,
    device_id: Optional[str] = None,
    acc_path: Optional[pathlib.Path | str] = None,
) -> Optional[str]:
    """
    Fallback to acc.txt when app data is blocked by Android sandbox/permissions.
    Maps Tab N to account in acc.txt safely while preventing shifted lines ("dồn dòng"):
    - Explicit acc_path="/dev/null" or nonexistent explicit path returns None immediately.
    - If tab_accounts.json is present (in acc_path's directory or default Shouko dir),
      consults fixed slot assignments so unassigned slots (like Tab 4 on M77) return None.
    - M77 canonical invariants: Tab 3 is MysticjUBuildery1999, Tab 4 is VanessaJoseph403, Tab 8 is Zephyra_Pro731.
    Returns: 'username (acc.txt)' or None.
    """
    try:
        t_num = int(tab_num)
        if t_num < 1:
            return None
    except (TypeError, ValueError):
        return None

    # Resolve device id
    dev_id = device_id or config.load_device_id() or os.environ.get("DEVICE_ID")
    if not dev_id:
        cfg = config.load_agent_config()
        dev_id = cfg.get("device_id") or cfg.get("device_name")
        if not dev_id:
            try:
                shouko_cfg = pathlib.Path("/storage/emulated/0/Download/Shouko/config.json")
                if shouko_cfg.is_file():
                    cfg_data = json.loads(shouko_cfg.read_text(encoding="utf-8"))
                    dev_id = cfg_data.get("device_name") or cfg_data.get("device_id")
            except Exception:
                pass

    if not dev_id:
        return None

    norm_dev = (config.normalize_device_id(dev_id) or str(dev_id).strip().strip("'\"")).lower()

    # Determine acc.txt path (priority: explicit acc_path -> config.DEFAULT_ACC_TXT_PATH -> Shouko dir)
    target_file = None
    if acc_path is not None:
        if str(acc_path) == "/dev/null":
            return None
        try:
            p = pathlib.Path(acc_path)
            if p.is_file():
                target_file = p
            else:
                return None
        except Exception:
            return None
    else:
        candidate_paths = []
        if hasattr(config, "DEFAULT_ACC_TXT_PATH"):
            candidate_paths.append(config.DEFAULT_ACC_TXT_PATH)
        candidate_paths.append(pathlib.Path("/storage/emulated/0/Download/Shouko/acc.txt"))
        try:
            def_paths = account_manager.get_default_paths()
            if def_paths.get("acc_file"):
                candidate_paths.append(pathlib.Path(def_paths["acc_file"]))
        except Exception:
            pass
        for cp in candidate_paths:
            try:
                if cp.is_file():
                    target_file = cp
                    break
            except Exception:
                pass

    if not target_file:
        return None

    # Check if a fixed tab_accounts.json exists in target_file parent or default Shouko dir
    tab_map_file = target_file.parent / "tab_accounts.json"
    shouko_tab_map = getattr(config, "DEFAULT_TAB_ACCOUNTS_PATH", pathlib.Path("/storage/emulated/0/Download/Shouko/tab_accounts.json"))
    if not tab_map_file.is_file() and (acc_path is None or target_file.parent == shouko_tab_map.parent):
        if shouko_tab_map.is_file():
            tab_map_file = shouko_tab_map
    if tab_map_file.is_file():
        found, map_u = get_tab_map_username(tab_num=t_num, device_id=dev_id, tab_map_path=tab_map_file)
        if found:
            if map_u:
                clean_u = map_u.replace(" (tab_map)", "")
                return clean_u if clean_u.endswith("(acc.txt)") else f"{clean_u} (acc.txt)"
            else:
                # Explicitly unassigned slot (e.g. Tab 4 on M77)
                return None

    try:
        acc_content = target_file.read_text(encoding="utf-8-sig", errors="ignore")
    except Exception:
        return None

    if not acc_content.strip():
        return None

    try:
        sections = account_manager.parse_acc_sections(acc_content)
    except Exception:
        sections = {}

    dev_num = None
    m_num = re.search(r"\d+", norm_dev)
    if m_num:
        dev_num = int(m_num.group(0))

    sec = sections.get(norm_dev)
    if not sec and dev_num is not None:
        sec = sections.get(f"m{m_num.group(0)}") or sections.get(f"m{dev_num}") or sections.get(f"m{dev_num:02d}")
        if not sec:
            for k, v in sections.items():
                km = re.search(r"\d+", k)
                if km and int(km.group(0)) == dev_num:
                    sec = v
                    break

    valid_accounts = []
    if sec:
        accounts = sec.get("accounts", [])
        for acc in accounts:
            u = str(acc.get("username") or "").strip()
            if u and not u.startswith(("#", "//", ";")) and re.match(r"^[a-zA-Z0-9_]{3,30}$", u):
                valid_accounts.append(acc)

    # Fallback: scan lines under matched section in raw acc_content if accounts were plain usernames without colons
    if not valid_accounts:
        pats = [re.escape(norm_dev)]
        if dev_num is not None:
            pats.extend([f"m{dev_num}", f"m0{dev_num}", f"m{dev_num:02d}"])
        header_pattern = re.compile(r"^\s*(?:\[|#|//)?\s*(?:" + "|".join(pats) + r")(?=[_(\s\].:]|$)", re.IGNORECASE)
        in_target_section = False
        for line in acc_content.splitlines():
            line_s = line.strip()
            if not line_s:
                continue
            if re.match(r"^\s*(?:\[|#|//)?\s*[Mm]\d+(?=[_(\s\].:]|$)", line_s, re.IGNORECASE) and ":" not in line_s:
                if header_pattern.match(line_s):
                    in_target_section = True
                    continue
                elif in_target_section:
                    break
            if in_target_section:
                if line_s.startswith(("#", "//", ";")):
                    continue
                cand_u = line_s.split(":")[0].strip()
                if cand_u and re.match(r"^[a-zA-Z0-9_]{3,30}$", cand_u):
                    valid_accounts.append({"username": cand_u})

    # Guard against shifted line misassignments ("dồn dòng") on M77
    if dev_num == 77:
        if t_num == 4:
            return None

    idx = t_num - 1
    if 0 <= idx < len(valid_accounts):
        acc = valid_accounts[idx]
        u = str(acc.get("username") or "").strip()
        if not u:
            return None

        # Guard against shifted line misassignments on M77
        if dev_num == 77:
            if u == "MysticjUBuildery1999" and t_num != 3:
                return None
            if u == "Zephyra_Pro731" and t_num != 8:
                return None

        return u if u.endswith("(acc.txt)") else f"{u} (acc.txt)"

    return None


def get_server_links_fallback_username(
    tab_num: int,
    pkg: str,
    links_path: Optional[pathlib.Path | str] = None,
) -> Optional[str]:
    """Check if server_links.txt has username mapping for this package/tab."""
    try:
        t_num = int(tab_num)
        if t_num < 1:
            return None
    except (TypeError, ValueError):
        return None

    lp = None
    if links_path:
        try:
            if isinstance(links_path, (str, pathlib.Path)):
                lp = pathlib.Path(links_path)
        except Exception:
            pass
    if not lp:
        lp = getattr(config, "DEFAULT_SERVER_LINKS_PATH", pathlib.Path("/storage/emulated/0/Download/Shouko/server_links.txt"))

    try:
        if not lp.is_file():
            return None
        lines = lp.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3 and (parts[0] == pkg or parts[0] == str(t_num) or parts[0].lower() in (f"tab {t_num}", f"tab{t_num}")):
                candidate = parts[2] if not parts[2].startswith("http") else parts[1]
                candidate_clean = candidate.strip()
                if (
                    candidate_clean
                    and re.match(r"^[a-zA-Z0-9_]{3,30}$", candidate_clean)
                    and candidate_clean.lower() not in ("null", "none", "unknown", "false", "true", "undefined", "default", "guest", "❓")
                    and not candidate_clean.startswith("❓")
                ):
                    return candidate_clean
                u = extract_username_from_text(candidate)
                if u:
                    return u
    except Exception:
        pass
    return None


def ensure_tab_accounts_file(path: Optional[pathlib.Path | str] = None) -> pathlib.Path:
    """Ensure tab_accounts.json exists with verified default mapping if missing or empty, and self-heals stale null/empty entries."""
    target_path = pathlib.Path(path) if path else getattr(config, "DEFAULT_TAB_ACCOUNTS_PATH", pathlib.Path("/storage/emulated/0/Download/Shouko/tab_accounts.json"))
    try:
        if not target_path.is_file() or target_path.stat().st_size == 0:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = target_path.with_suffix(f".tmp.{os.getpid()}_{time.time_ns()}")
            tmp_path.write_text(json.dumps(DEFAULT_TAB_ACCOUNTS, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(target_path)
        else:
            content = target_path.read_text(encoding="utf-8-sig", errors="ignore")
            if content.strip():
                data = json.loads(content)
                if isinstance(data, dict):
                    modified = False
                    for k, v in DEFAULT_TAB_ACCOUNTS.items():
                        if v is not None:
                            curr_v = data.get(k)
                            if curr_v is None or (isinstance(curr_v, str) and (
                                not curr_v.strip()
                                or curr_v.strip().lower() in ("null", "none", "unknown", "false", "true", "undefined", "default", "guest", "❓")
                                or curr_v.strip().startswith("❓")
                            )):
                                data[k] = v
                                modified = True
                    if modified:
                        save_tab_accounts(data, target_path)
    except Exception:
        pass
    return target_path


def load_tab_accounts(path: Optional[pathlib.Path | str] = None, auto_create: bool = False) -> dict[str, Any]:
    """Load fixed tab-to-package-to-account mapping from tab_accounts.json with automatic self-healing."""
    target_path = pathlib.Path(path) if path else getattr(config, "DEFAULT_TAB_ACCOUNTS_PATH", pathlib.Path("/storage/emulated/0/Download/Shouko/tab_accounts.json"))
    if auto_create and not target_path.is_file():
        ensure_tab_accounts_file(target_path)
    try:
        if target_path.is_file():
            content = target_path.read_text(encoding="utf-8-sig", errors="ignore")
            if content.strip():
                data = json.loads(content)
                if isinstance(data, dict):
                    modified = False
                    for k, v in DEFAULT_TAB_ACCOUNTS.items():
                        if v is not None:
                            curr_v = data.get(k)
                            if curr_v is None or (isinstance(curr_v, str) and (
                                not curr_v.strip()
                                or curr_v.strip().lower() in ("null", "none", "unknown", "false", "true", "undefined", "default", "guest", "❓")
                                or curr_v.strip().startswith("❓")
                            )):
                                data[k] = v
                                modified = True
                    if modified:
                        try:
                            save_tab_accounts(data, target_path)
                        except Exception:
                            pass
                    return data
    except Exception:
        pass
    # If path is default/Shouko path and file is unreadable or empty, fallback to verified defaults
    shouko_tab_map = getattr(config, "DEFAULT_TAB_ACCOUNTS_PATH", pathlib.Path("/storage/emulated/0/Download/Shouko/tab_accounts.json"))
    if not path or pathlib.Path(path) == shouko_tab_map:
        return DEFAULT_TAB_ACCOUNTS.copy()
    return {}


def save_tab_accounts(mapping: dict[str, Any], path: Optional[pathlib.Path | str] = None) -> bool:
    """Save fixed tab mapping to tab_accounts.json atomically."""
    target_path = pathlib.Path(path) if path else getattr(config, "DEFAULT_TAB_ACCOUNTS_PATH", pathlib.Path("/storage/emulated/0/Download/Shouko/tab_accounts.json"))
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        data_str = json.dumps(mapping, indent=2, ensure_ascii=False)
        tmp_path = target_path.with_suffix(f".tmp.{os.getpid()}_{time.time_ns()}")
        tmp_path.write_text(data_str, encoding="utf-8")
        tmp_path.replace(target_path)
        return True
    except Exception:
        return False


def get_tab_map_username(
    tab_num: int | str,
    pkg: Optional[str] = None,
    device_id: Optional[str] = None,
    tab_map_path: Optional[pathlib.Path | str] = None,
    loaded_data: Optional[dict[str, Any]] = None,
) -> tuple[bool, Optional[str]]:
    """
    Lookup username from fixed tab_accounts mapping.
    Supports keys by:
    - package name (e.g. 'com.tinh.vv.hi')
    - tab number string or int (e.g. '1', 1, 'tab1', 'tab_1')
    - device-scoped nested mapping (e.g. {'m77': {...}})
    Returns (found_in_store, username_with_suffix_or_None).
    """
    data = loaded_data if loaded_data is not None else load_tab_accounts(tab_map_path, auto_create=False)
    if not data or not isinstance(data, dict):
        return False, None

    lookup_dict = data
    if device_id:
        norm_dev = (config.normalize_device_id(device_id) or str(device_id).strip().strip("'\"")).lower()
        if norm_dev in data and isinstance(data[norm_dev], dict):
            lookup_dict = data[norm_dev]
        else:
            dev_upper = norm_dev.upper()
            if dev_upper in data and isinstance(data[dev_upper], dict):
                lookup_dict = data[dev_upper]
            else:
                m_num = re.search(r"\d+", norm_dev)
                if m_num:
                    target_num = int(m_num.group(0))
                    for dk, dv in data.items():
                        if isinstance(dv, dict):
                            dkm = re.search(r"\d+", str(dk))
                            if dkm and int(dkm.group(0)) == target_num:
                                lookup_dict = dv
                                break

    try:
        t_int = int(tab_num)
    except (TypeError, ValueError):
        t_int = None

    cand_keys = []
    if pkg:
        cand_keys.append(pkg)
    if t_int is not None:
        cand_keys.extend([
            str(t_int),
            t_int,
            f"tab_{t_int}",
            f"tab{t_int}",
            f"Tab {t_int}",
            f"Tab_{t_int}",
            f"Tab{t_int}",
            f"tab {t_int}",
            f"TAB{t_int}",
        ])
    elif tab_num:
        cand_keys.append(str(tab_num))

    if pkg and pkg in TAB_PACKAGE_MAP:
        canon = TAB_PACKAGE_MAP[pkg]
        if canon not in cand_keys:
            cand_keys.extend([canon, str(canon), f"tab_{canon}", f"tab{canon}", f"Tab{canon}", f"Tab {canon}"])

    if t_int is not None and t_int in TAB_TO_PACKAGE_MAP:
        mapped_pkg = TAB_TO_PACKAGE_MAP[t_int]
        if mapped_pkg not in cand_keys:
            cand_keys.append(mapped_pkg)

    ci_lookup = {str(k).strip().lower(): v for k, v in lookup_dict.items()}

    for k in cand_keys:
        val_found = False
        raw_val = None
        if k in lookup_dict:
            raw_val = lookup_dict[k]
            val_found = True
        else:
            k_ci = str(k).strip().lower()
            if k_ci in ci_lookup:
                raw_val = ci_lookup[k_ci]
                val_found = True

        if val_found:
            if isinstance(raw_val, dict):
                raw_val = raw_val.get("username") or raw_val.get("user")
            if raw_val is None:
                return True, None
            s_val = str(raw_val).strip()
            if not s_val or s_val.lower() in ("null", "none", "unknown", "false", "true", "undefined", "default", "guest", "❓") or s_val.startswith("❓"):
                return True, None
            clean_u = s_val if s_val.endswith("(tab_map)") else f"{s_val} (tab_map)"
            return True, clean_u

    # If the slot store exists and has mapping data, any tab/pkg slot not explicitly assigned is unassigned
    return True, None


def format_tab_list_html(device_id: str, tabs: list[dict[str, Any]]) -> str:
    """
    Format tab list into Telegram-compatible HTML string.
    Ensures special characters in usernames and device IDs are safely escaped.
    Format:
      📱 <b>Tab List — M77</b>
      Tab 1: username_real
      Tab 2: username_acc (acc.txt)
      Tab 3: ❓ (unknown)
    """
    import html
    dev_name = html.escape(str(device_id or "M77").upper(), quote=False)
    header = f"📱 <b>Tab List — {dev_name}</b>"
    if not tabs:
        return f"{header}\n(Không có tab Roblox nào đang chạy)"

    valid_tabs = [t for t in tabs if isinstance(t, dict)]
    if not valid_tabs:
        return f"{header}\n(Không có tab Roblox nào đang chạy)"

    def _sort_key(t: dict[str, Any]) -> int:
        raw_val = t.get("tab") if t.get("tab") is not None else t.get("tab_index")
        try:
            return int(raw_val)
        except (TypeError, ValueError):
            return 0

    sorted_tabs = sorted(valid_tabs, key=_sort_key)
    lines = []
    current_length = len(header) + 1
    for i, t in enumerate(sorted_tabs):
        raw_tab_val = t.get("tab") if t.get("tab") is not None else t.get("tab_index")
        tab_num = html.escape(str(raw_tab_val if raw_tab_val is not None else "?"), quote=False)
        raw_u = t.get("username")
        if isinstance(raw_u, (dict, list)):
            raw_u_str = ""
        elif raw_u is not None:
            raw_u_str = str(raw_u).strip()
        else:
            raw_u_str = ""
        is_unknown = (
            not raw_u_str
            or raw_u_str == "❓"
            or raw_u_str.startswith("❓")
            or raw_u_str.lower() in ("unknown", "none", "null", "undefined", "guest", "default")
            or raw_u_str.startswith(("{", "["))
        )
        is_banned = (
            t.get("is_banned") is True
            or str(t.get("status") or "").upper() in ("BANNED", "BAN", "BANED")
            or raw_u_str.endswith("(baned)")
            or raw_u_str.endswith("(banned)")
        )
        if is_banned:
            clean_u = raw_u_str
            for sfx in ("(baned)", "(banned)", "(tab_map)", "(acc.txt)", "(server_links)"):
                clean_u = clean_u.replace(sfx, "").strip()
            uname = f"{html.escape(clean_u[:50], quote=False)} (baned)" if (clean_u and not is_unknown) else "baned"
        else:
            uname = "❓ (unknown)" if is_unknown else html.escape(raw_u_str[:50], quote=False)
        line = f"Tab {tab_num}: {uname}"
        if current_length + len(line) + 1 > 3900:
            remaining = len(sorted_tabs) - i
            lines.append(f"... và còn {remaining} tab khác")
            break
        lines.append(line)
        current_length += len(line) + 1

    return f"{header}\n" + "\n".join(lines)


def check_tabs_ban_status(tabs: list[dict[str, Any]], base_dir: Optional[pathlib.Path | str] = None) -> None:
    """
    Check if any of the active tab accounts are banned and annotate tab dicts:
    - tab['is_banned'] = True / False
    - tab['status'] = 'BANNED' (if banned)
    Sources:
    1. Local ban files: acc_bi_ban.txt, nhat_ky_ban.txt
    2. Quota-Guard ban cache in account_manager
    3. ZeroPoint Cookie Checker API via account_manager.check_zeropoint_cookie_status
    """
    if not tabs:
        return

    if str(base_dir) == "/dev/null":
        for t in tabs:
            if t.get("is_banned") is None:
                t["is_banned"] = False
        return

    b_path = pathlib.Path(base_dir) if base_dir else pathlib.Path("/storage/emulated/0/Download/Shouko")
    banned_usernames = set()

    # 1. Local ban files
    for fname in ("acc_bi_ban.txt", "nhat_ky_ban.txt"):
        fpath = b_path / fname
        if fpath.is_file():
            try:
                for line in fpath.read_text(encoding="utf-8", errors="ignore").splitlines():
                    stripped = line.strip()
                    if stripped:
                        u = stripped.split(":")[0].strip().lower()
                        if u:
                            banned_usernames.add(u)
            except Exception:
                pass

    # 2. Check Quota-Guard cache in account_manager
    if account_manager:
        with getattr(account_manager, "_CACHE_LOCK", threading.Lock()):
            cache = getattr(account_manager, "_QUOTA_GUARD_CACHE", {})
            for t in tabs:
                u = t.get("username")
                if u:
                    clean_u = re.sub(r"\s*\(.*?\)$", "", str(u)).strip().lower()
                    if clean_u:
                        cached = cache.get(clean_u)
                        if cached and isinstance(cached, dict):
                            st = str(cached.get("status") or "").upper()
                            if st in ("BANNED", "BAN_WARN"):
                                banned_usernames.add(clean_u)

    # 3. Check ZeroPoint Cookie Checker API for unverified accounts
    usernames_need_api = []
    for t in tabs:
        u = t.get("username")
        if u:
            clean_u = re.sub(r"\s*\(.*?\)$", "", str(u)).strip()
            if clean_u and clean_u.lower() not in banned_usernames:
                usernames_need_api.append(clean_u)

    if usernames_need_api and account_manager:
        cookie_map: dict[str, str] = {}
        for cookie_fname in ("Data_Tong_Cookies.txt", "Cookies.txt", "cookie.txt"):
            cf = b_path / cookie_fname
            if cf.is_file():
                try:
                    for line in cf.read_text(encoding="utf-8", errors="ignore").splitlines():
                        l_str = line.strip()
                        if not l_str or ":" not in l_str:
                            continue
                        parts = l_str.split(":")
                        u_norm = parts[0].strip().lower()
                        c = ""
                        if "_|WARNING:" in l_str:
                            c = l_str[l_str.index("_|WARNING:"):].strip()
                        elif len(parts) > 2:
                            c = ":".join(parts[2:]).strip()
                        if c and u_norm not in cookie_map:
                            cookie_map[u_norm] = c
                except Exception:
                    pass

        api_payload = {}
        for uname in usernames_need_api:
            c = cookie_map.get(uname.lower())
            if c:
                api_payload[uname] = c

        if api_payload:
            try:
                zp_res = account_manager.check_zeropoint_cookie_status(api_payload, timeout=5)
                if isinstance(zp_res, dict):
                    for uname, info in zp_res.items():
                        if isinstance(info, dict):
                            st = str(info.get("status") or "").upper()
                            if st in ("BANNED", "BAN_WARN"):
                                banned_usernames.add(uname.strip().lower())
            except Exception:
                pass

    # 4. Annotate each tab
    for t in tabs:
        u = t.get("username")
        is_ban = False
        if str(t.get("status") or "").upper() in ("BANNED", "BAN", "BANED") or t.get("is_banned") is True:
            is_ban = True
        elif u:
            clean_u = re.sub(r"\s*\(.*?\)$", "", str(u)).strip().lower()
            if clean_u in banned_usernames or "(baned)" in str(u).lower() or "(banned)" in str(u).lower():
                is_ban = True

        t["is_banned"] = is_ban
        if is_ban:
            t["status"] = "BANNED"


def query_tab_list(
    device_id: Optional[str] = None,
    acc_path: Optional[pathlib.Path | str] = None,
    links_path: Optional[pathlib.Path | str] = None,
    tab_map_path: Optional[pathlib.Path | str] = None,
) -> list[dict[str, Any]]:
    """
    Query running Roblox app instances using ADB / local environment, map them to Tab numbers,
    and determine the logged-in Roblox username per instance via multi-tier fallback:
    1. Direct Python Path.read_text() check if accessible
    2. appStorage.json exact read (cat, su -c, /system/bin/su -c, /system/xbin/su -c, run-as)
    3. Shared preferences XML (shared_prefs/*.xml) and app files
    4. dumpsys activity analysis
    5. Config fallback (tab_accounts.json fixed slot store, server_links.txt, legacy acc.txt)
    Returns a list of dicts: [{'tab': 1, 'package': '...', 'username': '...'}, ...]
    """
    # Resolve tab_map_path
    resolved_tab_map_path = None
    if tab_map_path:
        if str(tab_map_path) != "/dev/null":
            resolved_tab_map_path = pathlib.Path(tab_map_path)
    else:
        shouko_acc = getattr(config, "DEFAULT_ACC_TXT_PATH", pathlib.Path("/storage/emulated/0/Download/Shouko/acc.txt"))
        shouko_tab_map = getattr(config, "DEFAULT_TAB_ACCOUNTS_PATH", pathlib.Path("/storage/emulated/0/Download/Shouko/tab_accounts.json"))
        if acc_path and str(acc_path) != "/dev/null":
            custom_acc_parent = pathlib.Path(acc_path).parent
            custom_tab_map = custom_acc_parent / "tab_accounts.json"
            if custom_tab_map.is_file():
                resolved_tab_map_path = custom_tab_map
            elif custom_acc_parent == shouko_acc.parent:
                resolved_tab_map_path = shouko_tab_map
            else:
                # Isolated custom/test acc_path without tab_accounts.json: do not bleed production file
                resolved_tab_map_path = None
        else:
            resolved_tab_map_path = shouko_tab_map

    tab_map_data = None
    tab_map_active = False
    if resolved_tab_map_path:
        ensure_tab_accounts_file(resolved_tab_map_path)
        tab_map_data = load_tab_accounts(resolved_tab_map_path, auto_create=False)
        if tab_map_data:
            tab_map_active = True

    # 1. Discover running Roblox instances via ADB dumpsys activity
    dumpsys_out = run_adb_shell("dumpsys activity activities")
    if not dumpsys_out:
        dumpsys_out = run_adb_shell("dumpsys activity")

    matched_pkgs = []
    if dumpsys_out:
        # Match package before activity slash (e.g. com.tinh.vv.hi/com.roblox.client...)
        for m in re.finditer(r"\b(com\.tinh\.vv\.[a-zA-Z0-9_\.-]+|com\.roblox\.client[a-zA-Z0-9_\.-]*)/", dumpsys_out):
            matched_pkgs.append(m.group(1))
        # Match affinity / realActivity
        for m in re.finditer(r"(?:[A=]|affinity=[\"']?|realActivity=)(com\.tinh\.vv\.[a-zA-Z0-9_\.-]+|com\.roblox\.client[a-zA-Z0-9_\.-]*)\b", dumpsys_out):
            matched_pkgs.append(m.group(1))
        # Match ProcessRecord
        for m in re.finditer(r"ProcessRecord\{[^\}]*\b(com\.tinh\.vv\.[a-zA-Z0-9_\.-]+|com\.roblox\.client[a-zA-Z0-9_\.-]*)\b", dumpsys_out):
            matched_pkgs.append(m.group(1))

    # Also discover running packages via ps (supports ps -A for multi-user/Android 8+)
    ps_out = run_adb_shell("ps -A")
    if not ps_out:
        ps_out = run_adb_shell("ps")
    if ps_out:
        for m in re.finditer(r"\b(com\.tinh\.vv\.[a-zA-Z0-9_\.-]+|com\.roblox\.client[a-zA-Z0-9_\.-]*)\b", ps_out):
            matched_pkgs.append(m.group(1))

    # Deduplicate while preserving discovery order
    seen_pkgs = set()
    running_pkgs = []
    for pkg in matched_pkgs:
        if pkg not in seen_pkgs:
            seen_pkgs.add(pkg)
            running_pkgs.append(pkg)

    pkg_pid_map: dict[str, str] = {}
    # Fallback to local /proc discovery if running on Linux/Android host without ADB output
    if not running_pkgs:
        try:
            proc_root = pathlib.Path("/proc")
            if proc_root.is_dir():
                for pid_entry in proc_root.iterdir():
                    if pid_entry.name.isdigit():
                        cmdline_f = pid_entry / "cmdline"
                        if cmdline_f.is_file():
                            raw_cmdline = cmdline_f.read_text(errors="ignore")
                            for m in re.finditer(r"\b(com\.tinh\.vv\.[a-zA-Z0-9_\.-]+|com\.roblox\.client[a-zA-Z0-9_\.-]*)\b", raw_cmdline):
                                p = m.group(1)
                                pkg_pid_map[p] = pid_entry.name
                                if p not in seen_pkgs:
                                    seen_pkgs.add(p)
                                    running_pkgs.append(p)
        except Exception:
            pass

    # 2. Map running package to Android user ID (e.g. 0, 10) if detectable from dumpsys or ps
    pkg_user_map: dict[str, int] = {}
    if dumpsys_out:
        for pkg in running_pkgs:
            m_u = re.search(r"(?:u(\d+)\s+" + re.escape(pkg) + r"/|U=(\d+).*?\b" + re.escape(pkg) + r"\b|\b" + re.escape(pkg) + r"/u(\d+)a\d+)", dumpsys_out)
            if m_u:
                try:
                    uid_str = next(g for g in m_u.groups() if g is not None)
                    pkg_user_map[pkg] = int(uid_str)
                except Exception:
                    pass
    if ps_out:
        for pkg in running_pkgs:
            if pkg not in pkg_user_map:
                m_ps = re.search(r"^\s*u(\d+)_a\d+\s+.*\b" + re.escape(pkg) + r"\b", ps_out, re.MULTILINE)
                if m_ps:
                    try:
                        pkg_user_map[pkg] = int(m_ps.group(1))
                    except Exception:
                        pass
            if pkg not in pkg_pid_map:
                m_ps_pid = re.search(r"^\s*\S+\s+(\d+)\s+.*\b" + re.escape(pkg) + r"\b", ps_out, re.MULTILINE)
                if m_ps_pid:
                    pkg_pid_map[pkg] = m_ps_pid.group(1)

    # 3. Assign tab numbers with collision prevention:
    # Pass 1: Canonical assignments for mapped clone packages (1..10)
    used_tabs = set()
    assigned = []
    unmapped = []
    for pkg in running_pkgs:
        canonical_tab = TAB_PACKAGE_MAP.get(pkg)
        if canonical_tab is not None:
            used_tabs.add(canonical_tab)
            assigned.append((canonical_tab, pkg))
        else:
            unmapped.append(pkg)

    # Pass 2: Assign lowest available tabs for unmapped packages without colliding
    for pkg in unmapped:
        t = 1
        while t in used_tabs:
            t += 1
        used_tabs.add(t)
        assigned.append((t, pkg))

    # 3.5 Ultra-fast Root Batch Grep (scans all Roblox packages across /data/data and /data/user in ~50ms in 1 command)
    batch_live_users: dict[str, str] = {}
    batch_is_exact: dict[str, bool] = {}
    batch_targets = (
        "/data/data/com.tinh.vv.*/files/appData/LocalStorage/appStorage.json "
        "/data/data/com.tinh.vv.*/files/appStorage.json "
        "/data/data/com.roblox.client*/files/appData/LocalStorage/appStorage.json "
        "/data/data/com.roblox.client*/files/appStorage.json "
        "/data/user/*/*/files/appData/LocalStorage/appStorage.json "
        "/data/user/*/*/files/appStorage.json "
        "/data/data/com.tinh.vv.*/shared_prefs/*.xml "
        "/data/data/com.roblox.client*/shared_prefs/*.xml "
        "/data/user/*/*/shared_prefs/*.xml"
    )
    batch_regex = r'((Username|DisplayName|RobloxUsername)[\"\\ ]*:[\"\\ ]*([a-zA-Z0-9_]{3,30})|name=[\"\\ ]*(Username|DisplayName|RobloxUsername)[\"\\ ]*>[\"\\ ]*([a-zA-Z0-9_]{3,30}))'
    batch_cmd = (
        f"su -c \"for f in {batch_targets}; do "
        f"[ -f \\\"\\$f\\\" ] || continue; "
        f"res=\\$(head -c 1048576 \\\"\\$f\\\" 2>/dev/null | grep -aoEi '{batch_regex}' 2>/dev/null | head -n 2); "
        f"[ -z \\\"\\$res\\\" ] && res=\\$(grep -aoEi '{batch_regex}' \\\"\\$f\\\" 2>/dev/null | head -n 2); "
        f"[ -n \\\"\\$res\\\" ] && echo \\\"\\$f: \\$res\\\"; "
        f"done; true\""
    )
    batch_out = run_adb_shell(batch_cmd)
    if batch_out:
        re_pkg = re.compile(r"\b(com\.tinh\.vv\.[a-zA-Z0-9_\.-]+|com\.roblox\.client[a-zA-Z0-9_\.-]*)\b")
        re_exact_user = re.compile(
            r'(?:'
            r'(?:\\*["\']?)?(?:Username|RobloxUsername)(?:\\*["\']?)?\s*[:=>]\s*(?:\\*["\']*)?'
            r'|name=[\"\\ ]*(?:Username|RobloxUsername)[\"\\ ]*>[\\\" ]*'
            r')([a-zA-Z0-9_]{3,30})',
            re.IGNORECASE
        )
        re_disp_name = re.compile(
            r'(?:'
            r'(?:\\*["\']?)?DisplayName(?:\\*["\']?)?\s*[:=>]\s*(?:\\*["\']*)?'
            r'|name=[\"\\ ]*DisplayName[\"\\ ]*>[\\\" ]*'
            r')([a-zA-Z0-9_]{3,30})',
            re.IGNORECASE
        )
        current_pkg = None
        for line in batch_out.splitlines():
            m_pkg = re_pkg.search(line)
            if m_pkg:
                current_pkg = m_pkg.group(1)
            target_pkg = m_pkg.group(1) if m_pkg else current_pkg
            if not target_pkg:
                continue

            # Prioritize exact Username/RobloxUsername over DisplayName
            m_exact = re_exact_user.search(line)
            if m_exact:
                u_name = m_exact.group(1)
                if u_name.lower() not in ("null", "none", "unknown", "guest", "false", "true", "undefined", "default", "roblox", "client", "activity", "mainactivity"):
                    batch_live_users[target_pkg] = u_name
                    batch_is_exact[target_pkg] = True
                    continue

            # If no exact username found yet on this target_pkg, try DisplayName
            if not batch_is_exact.get(target_pkg):
                m_disp = re_disp_name.search(line)
                if m_disp:
                    u_disp = m_disp.group(1)
                    if u_disp.lower() not in ("null", "none", "unknown", "guest", "false", "true", "undefined", "default", "roblox", "client", "activity", "mainactivity"):
                        batch_live_users[target_pkg] = u_disp
                        batch_is_exact[target_pkg] = False

    # 4. Determine logged-in username for each running instance via Multi-Tier Fallback
    dumpsys_win_out = None
    logcat_out = None
    tab_list = []
    for tab_num, pkg in assigned:
        username = batch_live_users.get(pkg)
        user_id = pkg_user_map.get(pkg)
        user_ids_to_try = [0, 10]
        if user_id is not None and user_id not in user_ids_to_try:
            user_ids_to_try.insert(0, user_id)
        elif user_id == 10:
            user_ids_to_try = [10, 0]

        # --- Tier 0: Direct filesystem read via Python Path.read_text() ---
        if not username:
            candidate_direct_files = [
                pathlib.Path(f"/data/data/{pkg}/files/appData/LocalStorage/appStorage.json"),
                pathlib.Path(f"/data/data/{pkg}/files/appStorage.json"),
            ]
            for uid in user_ids_to_try:
                candidate_direct_files.append(pathlib.Path(f"/data/user/{uid}/{pkg}/files/appData/LocalStorage/appStorage.json"))
                candidate_direct_files.append(pathlib.Path(f"/data/user/{uid}/{pkg}/files/appStorage.json"))
            candidate_direct_files.extend([
                pathlib.Path(f"/data/data/{pkg}/shared_prefs/{pkg}_preferences.xml"),
                pathlib.Path(f"/data/data/{pkg}/shared_prefs/com.roblox.client_preferences.xml"),
            ])
            for uid in user_ids_to_try:
                candidate_direct_files.append(pathlib.Path(f"/data/user/{uid}/{pkg}/shared_prefs/{pkg}_preferences.xml"))
                candidate_direct_files.append(pathlib.Path(f"/data/user/{uid}/{pkg}/shared_prefs/com.roblox.client_preferences.xml"))

            try:
                data_user_dir = pathlib.Path("/data/user")
                if data_user_dir.is_dir():
                    for u_dir in data_user_dir.iterdir():
                        candidate_direct_files.append(u_dir / pkg / "files/appData/LocalStorage/appStorage.json")
                        candidate_direct_files.append(u_dir / pkg / "files/appStorage.json")
                        candidate_direct_files.append(u_dir / pkg / f"shared_prefs/{pkg}_preferences.xml")
            except Exception:
                pass

            for p in candidate_direct_files:
                try:
                    if p.is_file():
                        content = p.read_text(encoding="utf-8", errors="ignore")
                        username = extract_username_from_text(content)
                        if username:
                            break
                except Exception:
                    pass

        # --- Tier 1: Exact read of appStorage.json via multiple shell/ADB commands ---
        if not username:
            appstorage_paths = [
                f"/data/data/{pkg}/files/appData/LocalStorage/appStorage.json",
                f"/data/data/{pkg}/files/appStorage.json",
            ]
            for uid in user_ids_to_try:
                appstorage_paths.append(f"/data/user/{uid}/{pkg}/files/appData/LocalStorage/appStorage.json")
                appstorage_paths.append(f"/data/user/{uid}/{pkg}/files/appStorage.json")
            appstorage_paths.append(f"/data/user/*/{pkg}/files/appData/LocalStorage/appStorage.json")
            appstorage_paths.append(f"/data/user/*/{pkg}/files/appStorage.json")
            paths_arg = " ".join(appstorage_paths)

            appstorage_cmds = [
                f"cat {paths_arg} 2>/dev/null",
                f"su -c \"cat {paths_arg} 2>/dev/null\"",
                f"/system/bin/su -c \"cat {paths_arg} 2>/dev/null\"",
                f"/system/xbin/su -c \"cat {paths_arg} 2>/dev/null\"",
                f"run-as {pkg} sh -c 'cat files/appData/LocalStorage/appStorage.json files/appStorage.json 2>/dev/null'",
                f"run-as {pkg} cat files/appData/LocalStorage/appStorage.json 2>/dev/null",
                f"run-as {pkg} cat files/appStorage.json 2>/dev/null",
                f"run-as {pkg} cat /data/data/{pkg}/files/appData/LocalStorage/appStorage.json 2>/dev/null",
                f"run-as {pkg} cat /data/data/{pkg}/files/appStorage.json 2>/dev/null",
            ]
            if user_id is not None:
                appstorage_cmds.append(f"run-as --user {user_id} {pkg} sh -c 'cat files/appData/LocalStorage/appStorage.json files/appStorage.json 2>/dev/null'")
                appstorage_cmds.append(f"run-as --user {user_id} {pkg} cat files/appData/LocalStorage/appStorage.json 2>/dev/null")
                appstorage_cmds.append(f"run-as --user {user_id} {pkg} cat files/appStorage.json 2>/dev/null")
            for uid in user_ids_to_try:
                if uid != 0 and uid != user_id:
                    appstorage_cmds.append(f"run-as --user {uid} {pkg} sh -c 'cat files/appData/LocalStorage/appStorage.json files/appStorage.json 2>/dev/null'")
                    appstorage_cmds.append(f"run-as --user {uid} {pkg} cat files/appData/LocalStorage/appStorage.json 2>/dev/null")
                    appstorage_cmds.append(f"run-as --user {uid} {pkg} cat files/appStorage.json 2>/dev/null")

            for cmd in appstorage_cmds:
                out = run_adb_shell(cmd)
                if out:
                    username = extract_username_from_text(out)
                    if username:
                        break

        # --- Tier 2: Search in shared preferences XML & app data files ---
        if not username:
            shared_prefs_paths = [
                f"/data/data/{pkg}/shared_prefs/{pkg}_preferences.xml",
                f"/data/data/{pkg}/shared_prefs/com.roblox.client_preferences.xml",
                f"/data/data/{pkg}/shared_prefs/*.xml",
            ]
            for uid in user_ids_to_try:
                shared_prefs_paths.append(f"/data/user/{uid}/{pkg}/shared_prefs/{pkg}_preferences.xml")
                shared_prefs_paths.append(f"/data/user/{uid}/{pkg}/shared_prefs/com.roblox.client_preferences.xml")
                shared_prefs_paths.append(f"/data/user/{uid}/{pkg}/shared_prefs/*.xml")
            shared_prefs_paths.append(f"/data/user/*/{pkg}/shared_prefs/*.xml")
            sp_arg = " ".join(shared_prefs_paths)

            shared_prefs_cmds = [
                f"cat {sp_arg} 2>/dev/null",
                f"su -c \"cat {sp_arg} 2>/dev/null\"",
                f"/system/bin/su -c \"cat {sp_arg} 2>/dev/null\"",
                f"/system/xbin/su -c \"cat {sp_arg} 2>/dev/null\"",
                f"run-as {pkg} sh -c 'cat shared_prefs/*.xml 2>/dev/null'",
                f"run-as {pkg} cat shared_prefs/{pkg}_preferences.xml 2>/dev/null",
                f"run-as {pkg} cat shared_prefs/com.roblox.client_preferences.xml 2>/dev/null",
                f"cat /data/data/{pkg}/files/*.json /data/data/{pkg}/files/user* /data/data/{pkg}/files/*.txt /data/data/{pkg}/files/*.dat /data/user/*/{pkg}/files/*.json /data/user/*/{pkg}/files/user* /data/user/*/{pkg}/files/*.txt /data/user/*/{pkg}/files/*.dat 2>/dev/null",
            ]
            if user_id is not None:
                shared_prefs_cmds.append(f"run-as --user {user_id} {pkg} sh -c 'cat shared_prefs/*.xml 2>/dev/null'")
            for uid in user_ids_to_try:
                if uid != 0 and uid != user_id:
                    shared_prefs_cmds.append(f"run-as --user {uid} {pkg} sh -c 'cat shared_prefs/*.xml 2>/dev/null'")

            for cmd in shared_prefs_cmds:
                out = run_adb_shell(cmd)
                if out:
                    username = extract_username_from_text(out)
                    if username:
                        break

        # --- Tier 3: Dumpsys activity, window titles & logcat analysis ---
        if not username and dumpsys_out:
            lines = dumpsys_out.splitlines()
            pkg_lines = []
            capturing = False
            cur_block_lines = 0
            for line in lines:
                if not line.strip():
                    continue
                if pkg in line:
                    capturing = True
                    cur_block_lines = 0
                    pkg_lines.append(line)
                elif capturing:
                    if any(other_pkg in line for other_pkg in seen_pkgs if other_pkg != pkg):
                        capturing = False
                    elif line.startswith((" ", "\t")):
                        cur_block_lines += 1
                        if cur_block_lines <= 35:
                            pkg_lines.append(line)
                    else:
                        capturing = False
            if pkg_lines:
                username = extract_username_from_text("\n".join(pkg_lines))

        # Check dumpsys window if not found in activity dumpsys
        if not username:
            if dumpsys_win_out is None:
                dumpsys_win_out = run_adb_shell("dumpsys window windows")
                if not dumpsys_win_out:
                    dumpsys_win_out = run_adb_shell("dumpsys window")
            if dumpsys_win_out:
                lines = dumpsys_win_out.splitlines()
                pkg_win_lines = []
                capturing = False
                cur_block_lines = 0
                for line in lines:
                    if not line.strip():
                        continue
                    is_window_header = bool(re.search(r'\bWindow\s+#\d+|\bWindow\{', line))
                    if is_window_header:
                        if pkg in line:
                            capturing = True
                            cur_block_lines = 0
                            pkg_win_lines.append(line)
                        else:
                            capturing = False
                    elif capturing:
                        if any(other_pkg in line for other_pkg in seen_pkgs if other_pkg != pkg):
                            capturing = False
                        elif line.startswith((" ", "\t")):
                            cur_block_lines += 1
                            if cur_block_lines <= 25:
                                pkg_win_lines.append(line)
                        else:
                            capturing = False
                if pkg_win_lines:
                    username = extract_username_from_text("\n".join(pkg_win_lines))

        # Check recent logcat if still not found
        if not username:
            if logcat_out is None:
                logcat_out = run_adb_shell("logcat -d -t 150")
            if logcat_out:
                pkg_pid = pkg_pid_map.get(pkg)
                pkg_log_lines = []
                for l in logcat_out.splitlines():
                    if pkg in l:
                        pkg_log_lines.append(l)
                    elif pkg_pid and f" {pkg_pid} " in l:
                        pkg_log_lines.append(l)
                    elif len(running_pkgs) == 1 and ("roblox" in l.lower() or "authenticated user" in l.lower()):
                        pkg_log_lines.append(l)
                if pkg_log_lines:
                    username = extract_username_from_text("\n".join(pkg_log_lines))

        # --- Tier 4: Config Fallback (tab_accounts.json, server_links.txt, legacy acc.txt) ---
        # 1. Fixed slot store: tab_accounts.json (Priority over acc.txt to prevent dồn dòng misassignment)
        if not username and tab_map_active:
            has_slot, map_u = get_tab_map_username(
                tab_num=tab_num,
                pkg=pkg,
                device_id=device_id,
                loaded_data=tab_map_data,
            )
            if has_slot and map_u:
                username = map_u

        # 2. server_links.txt
        if not username:
            links_u = get_server_links_fallback_username(tab_num=tab_num, pkg=pkg, links_path=links_path)
            if links_u:
                username = links_u

        # 3. Legacy acc.txt fallback (ONLY when tab_map is inactive, e.g. legacy/isolated test environment)
        if not username and not tab_map_active and str(acc_path) != "/dev/null":
            fallback_u = get_acc_fallback_username(tab_num=tab_num, device_id=device_id, acc_path=acc_path)
            if fallback_u:
                username = fallback_u

        tab_list.append({
            "tab": tab_num,
            "package": pkg,
            "username": username,
        })

    # Sort by tab number ascending
    tab_list.sort(key=lambda x: x["tab"])
    base_check_dir = resolved_tab_map_path.parent if resolved_tab_map_path else (pathlib.Path(acc_path).parent if acc_path and str(acc_path) != "/dev/null" else None)
    check_tabs_ban_status(tab_list, base_dir=base_check_dir)
    return tab_list



def handle_incoming_batch_action(
    message: dict[str, Any],
    device_id: str,
    report_url: str,
    secret: str,
    state: dict[str, Any],
    state_path: pathlib.Path,
    links_path: pathlib.Path,
    sync: bool = False,
) -> bool:
    """Process 2PC batch actions (PREPARE, COMMIT, ABORT) or UPDATE_DELTA."""
    if message.get("protocol") != PROTOCOL_VERSION:
        return False

    action = message.get("action")
    action_id = str(message.get("action_id") or "")
    targets = message.get("target_device_ids") or []

    if device_id not in targets:
        return False

    if action == "PREPARE_ALLOCATE_SERVER":
        allocation = message.get("allocation")
        expires_at = int(message.get("expires_at") or 0)
        res = server_links.handle_prepare(action_id, allocation, expires_at, links_path)
        send_ack(report_url, secret, device_id, action_id, **res)
        return True

    if action == "COMMIT_ALLOCATE_SERVER":
        res = server_links.handle_commit(action_id, links_path, state, state_path)
        send_ack(report_url, secret, device_id, action_id, **res)
        return True

    if action == "ABORT_ALLOCATE_SERVER":
        res = server_links.handle_abort(action_id, links_path)
        send_ack(report_url, secret, device_id, action_id, **res)
        return True

    if action == "UPDATE_DELTA":
        completed = state.setdefault("update_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "FAILED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="UPDATE_DELTA",
            )
            return True
        try:
            selection = message.get("selection")
            target_pkg = message.get("target_pkg")
            delta_updater.run_delta_update(selection=selection, target_pkg=target_pkg)
            result = {"status": "OPENED", "executed": True}
        except Exception as e:
            result = {"status": "FAILED", "executed": False, "reason": str(e)[:160]}
        completed[action_id] = result
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        send_ack(
            report_url, secret, device_id, action_id,
            status=result["status"], reason=result.get("reason"),
            executed=result["executed"], batch_action="UPDATE_DELTA",
        )
        return True

    if action == "BACKUP_APP":
        completed = state.setdefault("backup_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "FAILED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="BACKUP_APP",
            )
            return True
        try:
            try:
                from agent import backup_manager
            except ImportError:
                import backup_manager
            pkg_target = message.get("package") or "taskbar"
            mode_target = message.get("mode") or "full"
            tag_target = message.get("release_tag") or "Backup"
            token_target = message.get("github_token") or message.get("token")
            backup_res = backup_manager.run_backup_and_upload(pkg_target, mode=mode_target, tag=tag_target, token=token_target)
            result = {"status": "OPENED", "executed": True, "details": backup_res}
        except Exception as e:
            result = {"status": "FAILED", "executed": False, "reason": str(e)[:160]}
        completed[action_id] = result
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        send_ack(
            report_url, secret, device_id, action_id,
            status=result["status"], reason=result.get("reason"),
            executed=result["executed"], batch_action="BACKUP_APP",
            details=result.get("details"),
        )
        return True

    if action == "UPGRADE_AGENT":
        completed = state.setdefault("upgrade_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "OPENED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="UPGRADE_AGENT",
            )
            return True
        try:
            upgraded, err_msg = check_and_apply_auto_update(force=True)
            status = "OPENED" if upgraded else "FAILED"
            send_ack(
                report_url, secret, device_id, action_id,
                status=status, reason=err_msg,
                executed=upgraded, batch_action="UPGRADE_AGENT",
            )
            completed[action_id] = {"status": status, "executed": upgraded, "reason": err_msg}
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state), encoding="utf-8")

            if upgraded:
                print("[UPGRADE] Nạp code mới thành công! Đang tự khởi động lại Agent...", flush=True)
                time.sleep(1)
                script_file = pathlib.Path(__file__).resolve()
                args = [sys.executable, str(script_file)] + [a for a in sys.argv[1:] if a != str(script_file)]
                os.execv(sys.executable, args)
            return True
        except Exception as e:
            send_ack(
                report_url, secret, device_id, action_id,
                status="FAILED", reason=str(e)[:160],
                executed=False, batch_action="UPGRADE_AGENT",
            )
            return False

    if action == "SET_CONFIG":
        completed = state.setdefault("set_config_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "OPENED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="SET_CONFIG",
            )
            return True
        try:
            cfg_updates = message.get("config") or {}
            cfg_path = pathlib.Path("/storage/emulated/0/Download/Shouko/agent_config.json")
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            existing_cfg = {}
            if cfg_path.is_file():
                try:
                    existing_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            existing_cfg.update(cfg_updates)
            cfg_path.write_text(json.dumps(existing_cfg, indent=2), encoding="utf-8")
            status = "OPENED"
            err_msg = None
            executed = True
        except Exception as e:
            status = "FAILED"
            err_msg = str(e)[:160]
            executed = False

        completed[action_id] = {"status": status, "executed": executed, "reason": err_msg}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        send_ack(
            report_url, secret, device_id, action_id,
            status=status, reason=err_msg,
            executed=executed, batch_action="SET_CONFIG",
        )
        return True

    if action == "ENABLE_DEV_MODE":
        completed = state.setdefault("dev_mode_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "OPENED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="ENABLE_DEV_MODE",
            )
            return True
        try:
            try:
                from agent.backup_manager import _run_as_root
            except ImportError:
                try:
                    from backup_manager import _run_as_root
                except ImportError:
                    _run_as_root = None
            dev_cmd = """
            settings put global development_settings_enabled 1
            settings put global adb_enabled 1
            settings put global force_allow_on_external 1
            settings put global force_resizable_activities 1
            settings put global enable_freeform_support 1
            settings put global force_desktop_mode_on_external_displays 1
            WIDTH=$(wm size 2>/dev/null | awk '{print $NF}' | cut -d'x' -f1)
            if [ -n "$WIDTH" ] && [ "$WIDTH" -gt 0 ] 2>/dev/null; then
                DPI=$((WIDTH * 160 / 700))
                [ "$DPI" -gt 50 ] && [ "$DPI" -lt 1000 ] && wm density "$DPI" 2>/dev/null || true
            fi
            am start -a android.settings.APPLICATION_DEVELOPMENT_SETTINGS 2>/dev/null || true
            """
            if _run_as_root:
                res = _run_as_root(dev_cmd, timeout=15)
                success = res.returncode == 0
                reason = None if success else res.stderr.strip()
            else:
                proc = subprocess.run(["sh", "-c", dev_cmd], capture_output=True, text=True, timeout=15)
                success = proc.returncode == 0
                reason = None if success else proc.stderr.strip()
            status = "OPENED" if success else "FAILED"
            result = {"status": status, "executed": success, "reason": reason}
        except Exception as e:
            result = {"status": "FAILED", "executed": False, "reason": str(e)[:160]}
        completed[action_id] = result
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        send_ack(
            report_url, secret, device_id, action_id,
            status=result["status"], reason=result.get("reason"),
            executed=result["executed"], batch_action="ENABLE_DEV_MODE",
        )
        return True

    if action == "WRITE_SCRIPT":
        completed = state.setdefault("script_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "FAILED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="WRITE_SCRIPT",
            )
            return True
        try:
            filename = message.get("filename") or "sae"
            content = message.get("content") or ""
            autoexec_dirs = [
                pathlib.Path("/storage/emulated/0/Delta/Autoexecute"),
                pathlib.Path("/sdcard/Delta/Autoexecute"),
                pathlib.Path.home() / "Delta" / "Autoexecute",
            ]
            target_dir = None
            for d in autoexec_dirs:
                try:
                    d.mkdir(parents=True, exist_ok=True)
                    if d.is_dir():
                        target_dir = d
                        break
                except Exception:
                    continue
            if not target_dir:
                target_dir = autoexec_dirs[0]
                target_dir.mkdir(parents=True, exist_ok=True)

            target_file = target_dir / filename
            target_file.write_text(content, encoding="utf-8")
            try:
                os.chmod(target_file, 0o666)
            except Exception:
                pass
            result = {"status": "OPENED", "executed": True}
        except Exception as e:
            result = {"status": "FAILED", "executed": False, "reason": str(e)[:160]}
        completed[action_id] = result
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        send_ack(
            report_url, secret, device_id, action_id,
            status=result["status"], reason=result.get("reason"),
            executed=result["executed"], batch_action="WRITE_SCRIPT",
        )
        return True

    if action == "CLEAN_SCRIPT":
        completed = state.setdefault("script_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "FAILED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="CLEAN_SCRIPT",
            )
            return True
        try:
            filename = message.get("filename") or "all"
            target_dirs = [
                pathlib.Path("/storage/emulated/0/Delta/Autoexecute"),
                pathlib.Path("/sdcard/Delta/Autoexecute"),
            ]
            for td in target_dirs:
                if td.is_dir():
                    if filename.lower() == "all":
                        for f in td.iterdir():
                            if f.is_file():
                                try:
                                    f.unlink()
                                except Exception:
                                    pass
                    else:
                        tf = td / filename
                        if tf.is_file():
                            tf.unlink()
            result = {"status": "OPENED", "executed": True}
        except Exception as e:
            result = {"status": "FAILED", "executed": False, "reason": str(e)[:160]}
        completed[action_id] = result
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        send_ack(
            report_url, secret, device_id, action_id,
            status=result["status"], reason=result.get("reason"),
            executed=result["executed"], batch_action="CLEAN_SCRIPT",
        )
        return True

    if action == "CONTROL_TAILSCALE":
        completed = state.setdefault("tailscale_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "OPENED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="CONTROL_TAILSCALE",
                details=cached.get("details"),
            )
            return True

        in_progress = state.setdefault("tailscale_action_in_progress", set())
        if action_id in in_progress:
            return True
        in_progress.add(action_id)

        def _worker():
            try:
                try:
                    from agent.backup_manager import _run_as_root
                except ImportError:
                    try:
                        from backup_manager import _run_as_root
                    except ImportError:
                        _run_as_root = None

                mode = str(message.get("mode") or "on").lower()
                cmd = build_tailscale_command(mode)

                if _run_as_root:
                    res = _run_as_root(cmd, timeout=25)
                    success = res.returncode == 0
                    stdout_text = res.stdout.strip()
                    reason = None if success else (res.stderr.strip() or "vpn_timeout_no_ip")
                else:
                    proc = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, timeout=25)
                    success = proc.returncode == 0
                    stdout_text = proc.stdout.strip()
                    reason = None if success else (proc.stderr.strip() or "vpn_timeout_no_ip")

                # Strict status validation to prevent phantom successes (R1)
                tailscale_ip_pattern = r"(?<![0-9a-zA-Z.])\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b(?![0-9a-zA-Z./:])"
                if mode == "on":
                    ip_match = re.search(tailscale_ip_pattern, stdout_text)
                    is_valid_ip = False
                    if ip_match:
                        is_valid_ip = validate_tailscale_cgnat_ip(ip_match.group(0))

                    if success and stdout_text.startswith("CONNECTED:") and is_valid_ip:
                        status = "OPENED"
                        executed = True
                        details = stdout_text
                        reason = None
                    else:
                        status = "FAILED"
                        executed = False
                        details = None
                        reason = reason or "vpn_timeout_no_ip: Timeout 15s không nhận được IP Tailscale (100.x.y.z)"
                elif mode == "status":
                    status = "OPENED"
                    executed = True
                    ip_match = re.search(tailscale_ip_pattern, stdout_text)
                    if success and ip_match and validate_tailscale_cgnat_ip(ip_match.group(0)):
                        details = f"CONNECTED: {ip_match.group(0)}"
                    else:
                        details = "DISCONNECTED"
                    reason = None
                elif mode == "off":
                    status = "OPENED" if success else "FAILED"
                    executed = success
                    details = stdout_text if success else None
                    reason = None if success else (reason or "vpn_disconnect_failed")
                else:
                    status = "OPENED" if success else "FAILED"
                    executed = success
                    details = stdout_text

                result = {"status": status, "executed": executed, "reason": reason, "details": details}
            except Exception as e:
                result = {"status": "FAILED", "executed": False, "reason": str(e)[:160], "details": None}
            finally:
                in_progress.discard(action_id)

            completed[action_id] = result
            try:
                state_path.parent.mkdir(parents=True, exist_ok=True)
                save_state = {k: list(v) if isinstance(v, set) else v for k, v in state.items()}
                state_path.write_text(json.dumps(save_state), encoding="utf-8")
            except Exception:
                pass
            send_ack(
                report_url, secret, device_id, action_id,
                status=result["status"], reason=result.get("reason"),
                executed=result["executed"], batch_action="CONTROL_TAILSCALE",
                details=result.get("details"),
            )

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        if sync:
            t.join()
        elif t.is_alive():
            t.join(timeout=2.0)
        return True

    if action == "CHECK_BAN":
        completed = state.setdefault("checkban_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "OPENED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="CHECK_BAN",
                details=cached.get("details"),
            )
            return True
        try:
            target = message.get("target") or "all"
            result_data = account_manager.run_full_checkban_pipeline(target)
            status = "OPENED"
            executed = True
            err_msg = None
            details_str = json.dumps(result_data, ensure_ascii=False)
        except Exception as e:
            status = "FAILED"
            executed = False
            err_msg = str(e)[:160]
            details_str = None

        completed[action_id] = {"status": status, "executed": executed, "reason": err_msg, "details": details_str}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        send_ack(
            report_url, secret, device_id, action_id,
            status=status, reason=err_msg,
            executed=executed, batch_action="CHECK_BAN",
            details=details_str,
        )
        return True

    if action == "ADD_ACC":
        completed = state.setdefault("addacc_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "OPENED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="ADD_ACC",
                details=cached.get("details"),
            )
            return True
        try:
            m_code = message.get("m_code") or message.get("target_m") or device_id
            lines = message.get("lines") or message.get("accounts") or []
            if isinstance(lines, str):
                lines = [lines]
            sync_drive = message.get("sync_drive", True)
            add_res = account_manager.add_accounts(m_code, lines)
            sync_res = {}
            if sync_drive:
                try:
                    sync_res = account_manager.sync_to_google_drive()
                except Exception as se:
                    sync_res = {"error": str(se)}
            status = "OPENED"
            executed = True
            err_msg = None
            details_str = json.dumps({"add": add_res, "sync": sync_res}, ensure_ascii=False)
        except Exception as e:
            status = "FAILED"
            executed = False
            err_msg = str(e)[:160]
            details_str = None

        completed[action_id] = {"status": status, "executed": executed, "reason": err_msg, "details": details_str}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        send_ack(
            report_url, secret, device_id, action_id,
            status=status, reason=err_msg,
            executed=executed, batch_action="ADD_ACC",
            details=details_str,
        )
        return True

    if action == "DEL_ACC":
        completed = state.setdefault("delacc_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "OPENED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="DEL_ACC",
                details=cached.get("details"),
            )
            return True
        try:
            m_code = message.get("m_code") or message.get("target") or "all"
            usernames = message.get("usernames") or message.get("accounts") or []
            if isinstance(usernames, str):
                usernames = [u.strip() for u in re.split(r"[\s,]+", usernames) if u.strip()]
            sync_drive = message.get("sync_drive", True)
            del_res = account_manager.delete_accounts(m_code, usernames, sync_drive=sync_drive)
            status = "OPENED"
            executed = True
            err_msg = None
            details_str = json.dumps(del_res, ensure_ascii=False)
        except Exception as e:
            status = "FAILED"
            executed = False
            err_msg = str(e)[:160]
            details_str = None

        completed[action_id] = {"status": status, "executed": executed, "reason": err_msg, "details": details_str}
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        send_ack(
            report_url, secret, device_id, action_id,
            status=status, reason=err_msg,
            executed=executed, batch_action="DEL_ACC",
            details=details_str,
        )
        return True

    if action == "MOVE_ACC":
        completed = state.setdefault("moveacc_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "OPENED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="MOVE_ACC",
                details=cached.get("details"),
            )
            return True
        try:
            source_m = message.get("source_m") or message.get("src") or message.get("source")
            target_m = message.get("target_m") or message.get("dst") or message.get("target")
            count = int(message.get("count") or 1)
            sync_drive = message.get("sync_drive", True)
            base_dir = message.get("base_dir")
            move_res = account_manager.move_accounts(
                source_m, target_m, count=count, base_dir=base_dir, sync_drive=sync_drive
            )
            status = "OPENED"
            executed = True
            err_msg = None
            details_str = json.dumps(move_res, ensure_ascii=False)
        except Exception as e:
            status = "FAILED"
            executed = False
            err_msg = str(e)[:160]
            details_str = None

        completed[action_id] = {"status": status, "executed": executed, "reason": err_msg, "details": details_str}
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            save_state = {k: list(v) if isinstance(v, set) else v for k, v in state.items()}
            state_path.write_text(json.dumps(save_state), encoding="utf-8")
        except Exception:
            pass
        send_ack(
            report_url, secret, device_id, action_id,
            status=status, reason=err_msg,
            executed=executed, batch_action="MOVE_ACC",
            details=details_str,
        )
        return True

    if action == "TAB_LIST":
        completed = state.setdefault("tablist_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "OPENED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="TAB_LIST",
                details=cached.get("details"),
            )
            return True
        try:
            acc_path_param = message.get("acc_path")
            tab_map_param = message.get("tab_map_path") or message.get("tab_accounts_path")
            tabs = query_tab_list(
                device_id=device_id,
                acc_path=acc_path_param,
                links_path=links_path,
                tab_map_path=tab_map_param,
            )
            status = "OPENED"
            executed = True
            err_msg = None
            details_str = json.dumps({"tabs": tabs, "device_id": device_id}, ensure_ascii=False)
        except Exception as e:
            status = "FAILED"
            executed = False
            err_msg = str(e)[:160]
            details_str = None

        completed[action_id] = {"status": status, "executed": executed, "reason": err_msg, "details": details_str}
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            save_state = {k: list(v) if isinstance(v, set) else v for k, v in state.items()}
            state_path.write_text(json.dumps(save_state), encoding="utf-8")
        except Exception:
            pass
        send_ack(
            report_url, secret, device_id, action_id,
            status=status, reason=err_msg,
            executed=executed, batch_action="TAB_LIST",
            details=details_str,
        )
        return True

    if action in ("AUTO_LOGIN", "LOGIN_UNLOGGED"):
        completed = state.setdefault("autologin_action_results", {})
        cached = completed.get(action_id)
        if isinstance(cached, dict):
            send_ack(
                report_url, secret, device_id, action_id,
                status=str(cached.get("status", "OPENED")),
                reason=cached.get("reason"),
                executed=cached.get("executed") is True,
                batch_action="AUTO_LOGIN",
                details=cached.get("details"),
            )
            return True
        try:
            if not account_manager:
                raise RuntimeError("account_manager module not found")
            base_dir_param = message.get("base_dir")
            res_data = account_manager.auto_login_unlogged_tabs(device_id=device_id, base_dir=base_dir_param)
            status = "OPENED"
            executed = True
            err_msg = None
            details_str = json.dumps(res_data, ensure_ascii=False)
        except Exception as e:
            status = "FAILED"
            executed = False
            err_msg = str(e)[:160]
            details_str = None

        completed[action_id] = {"status": status, "executed": executed, "reason": err_msg, "details": details_str}
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            save_state = {k: list(v) if isinstance(v, set) else v for k, v in state.items()}
            state_path.write_text(json.dumps(save_state), encoding="utf-8")
        except Exception:
            pass
        send_ack(
            report_url, secret, device_id, action_id,
            status=status, reason=err_msg,
            executed=executed, batch_action="AUTO_LOGIN",
            details=details_str,
        )
        return True

    return False


def check_and_apply_auto_update(branch: str = "fix/delta-stability", force: bool = False) -> tuple[bool, Optional[str]]:
    """Check GitHub remote branch and update code on disk."""
    import shutil
    root = ROOT
    git_bin = shutil.which("git") or "/data/data/com.termux/files/usr/bin/git" or "git"
    if not (root / ".git").is_dir():
        print(f"[UPGRADE] Thư mục .git không tồn tại tại {root}", flush=True)
        return False, f"not_a_git_repo: {root}"
    try:
        fetch_cmd = [git_bin, "-c", "safe.directory=*", "-C", str(root), "fetch", "origin", branch]
        fetch_res = subprocess.run(
            fetch_cmd,
            capture_output=True, text=True, timeout=30
        )
        if fetch_res.returncode != 0:
            err = (fetch_res.stderr or fetch_res.stdout).strip()[:140]
            print(f"[UPGRADE] git fetch thất bại: {err}", flush=True)
            return False, f"fetch_err: {err}"

        remote_target = f"origin/{branch}"
        print(f"[UPGRADE] Đang nạp bản cập nhật mới từ GitHub ({remote_target})...", flush=True)
        reset_cmd = [git_bin, "-c", "safe.directory=*", "-C", str(root), "reset", "--hard", remote_target]
        reset_res = subprocess.run(
            reset_cmd,
            capture_output=True, text=True, timeout=30
        )
        if reset_res.returncode != 0:
            err = (reset_res.stderr or reset_res.stdout).strip()[:140]
            print(f"[UPGRADE] git reset thất bại: {err}", flush=True)
            return False, f"reset_err: {err}"

        try:
            ensure_tab_accounts_file()
        except Exception:
            pass
        return True, None
    except Exception as e:
        print(f"[UPGRADE] Thất bại: {e}", flush=True)
        return False, f"upgrade_ex: {str(e)[:140]}"


def run_agent_loop(
    config_path: pathlib.Path = config.DEFAULT_CONFIG_PATH,
    device_id_path: pathlib.Path = config.DEFAULT_DEVICE_ID_PATH,
    device_group_path: pathlib.Path = config.DEFAULT_DEVICE_GROUP_PATH,
    state_path: pathlib.Path = config.DEFAULT_STATE_PATH,
    links_path: pathlib.Path = config.DEFAULT_SERVER_LINKS_PATH,
    single_tick: bool = False,
) -> None:
    """Main agent execution loop."""
    cfg = config.load_agent_config(config_path)
    device_id = config.load_device_id(device_id_path) or "m72"
    device_group = config.load_device_group(device_group_path)
    report_url = cfg.get("worker_report_url", "https://localhost/report")
    secret = cfg.get("agent_report_secret", "")

    state: dict[str, Any] = {}
    if state_path.is_file():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}

    print(f"[*] Starting phanserver-delta agent: ID={device_id}, Group={device_group}, URL={report_url}", flush=True)
    try:
        ensure_tab_accounts_file()
    except Exception:
        pass
    try:
        subprocess.run(["termux-wake-lock"], capture_output=True, timeout=2)
    except Exception:
        pass

    tick_count = 0
    while True:
        tick_count += 1
        try:
            metrics = collect_metrics()
            heartbeat_payload = {
                "device_id": device_id,
                "device_group": device_group,
                "version": AGENT_VERSION,
                "capabilities": CAPABILITIES,
                "metrics": metrics,
            }
            response = send_report_response(report_url, secret, heartbeat_payload)
            if response and response.get("ok"):
                print(f"[AGENT] Heartbeat thành công (tick {tick_count})", flush=True)
            command = response.get("command") if isinstance(response, dict) else None
            if isinstance(command, dict):
                handle_incoming_batch_action(
                    command, device_id, report_url, secret, state, state_path, links_path
                )
        except Exception as e:
            print(f"[AGENT] Lỗi trong vòng lặp Heartbeat (tick {tick_count}): {e}", flush=True)

        if single_tick:
            break

        time.sleep(30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="phanserver-delta Device Agent")
    parser.add_argument("--once", action="store_true", help="Run a single heartbeat tick and exit")
    args = parser.parse_args()
    run_agent_loop(single_tick=args.once)

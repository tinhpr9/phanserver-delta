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
CAPABILITIES = ["allocate_server_2pc", "update_delta", "check_ban", "add_acc", "del_acc", "control_tailscale", "move_acc"]


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

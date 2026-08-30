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
    from agent import config, server_links
except ImportError:
    import config
    import server_links

try:
    from delta import delta_updater
except ImportError:
    import delta_updater

AGENT_VERSION = "phanserver-delta-agent-1.0.0"
PROTOCOL_VERSION = "fleet-batch-v1"
CAPABILITIES = ["allocate_server_2pc", "update_delta"]


def collect_metrics() -> dict[str, Any]:
    metrics = {
        "uptime": 0,
        "load_1m": 0.0,
        "mem_available_mb": 0,
        "battery_pct": 100,
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
                return None
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
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
    return send_report(ack_url, secret, payload)


def handle_incoming_batch_action(
    message: dict[str, Any],
    device_id: str,
    report_url: str,
    secret: str,
    state: dict[str, Any],
    state_path: pathlib.Path,
    links_path: pathlib.Path,
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

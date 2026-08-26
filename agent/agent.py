#!/usr/bin/env python3
"""
Minimal Device Agent for phanserver-delta.

Supported functions:
- APPLY_SERVER_LINKS (2PC Prepare, Commit, Abort)
- UPDATE_DELTA (Standalone Delta Updater integration)
- Heartbeat / reporting to phanserver-delta worker
- Authenticated WebSocket command transport
"""

import argparse
import base64
import hashlib
import json
import os
import pathlib
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

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

AGENT_VERSION = "phanserver-delta-agent-1.1.0"
PROTOCOL_VERSION = "fleet-batch-v1"
CAPABILITIES = ["allocate_server_2pc", "update_delta"]
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


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


def send_report(report_url: str, secret: str, payload: dict[str, Any]) -> bool:
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
            return resp.status in (200, 201)
    except Exception:
        return False


def send_ack(
    report_url: str,
    secret: str,
    device_id: str,
    action_id: str,
    status: str,
    reason: Optional[str] = None,
    executed: bool = False,
) -> bool:
    parsed = urllib.parse.urlparse(report_url)
    ack_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/aot/ack", "", "", ""))
    payload = {
        "protocol": PROTOCOL_VERSION,
        "batch_action": "ALLOCATE_SERVER",
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
        try:
            delta_updater.run_delta_update()
            send_ack(report_url, secret, device_id, action_id, status="OPENED", executed=True)
        except Exception as exc:
            send_ack(report_url, secret, device_id, action_id, status="FAILED", reason=str(exc), executed=False)
        return True

    return False


def build_websocket_url(report_url: str, device_id: str, device_group: str, secret: str) -> str:
    """Derive the WebSocket endpoint from the configured Worker report URL."""
    parsed = urllib.parse.urlparse(report_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("worker_report_url_invalid")
    if not secret:
        raise RuntimeError("agent_report_secret_missing")
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    query = urllib.parse.urlencode(
        {
            "device_id": device_id,
            "group": device_group,
            "secret": secret,
        }
    )
    return urllib.parse.urlunparse((ws_scheme, parsed.netloc, "/ws", "", query, ""))


class WebSocketClient:
    """Small RFC 6455 client using only the Python standard library."""

    def __init__(self, url: str, timeout: float = 30.0):
        self.url = url
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self._buffer = b""

    def connect(self) -> None:
        parsed = urllib.parse.urlparse(self.url)
        if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
            raise RuntimeError("websocket_url_invalid")

        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        raw_sock = socket.create_connection((parsed.hostname, port), timeout=15)
        try:
            if parsed.scheme == "wss":
                context = ssl.create_default_context()
                sock = context.wrap_socket(raw_sock, server_hostname=parsed.hostname)
            else:
                sock = raw_sock
        except Exception:
            raw_sock.close()
            raise

        sock.settimeout(15)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        default_port = 443 if parsed.scheme == "wss" else 80
        host = parsed.hostname if port == default_port else f"{parsed.hostname}:{port}"
        request = (
            f"GET {target} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"User-Agent: {AGENT_VERSION}\r\n"
            "\r\n"
        ).encode("ascii")
        sock.sendall(request)

        header_bytes = b""
        while b"\r\n\r\n" not in header_bytes:
            chunk = sock.recv(4096)
            if not chunk:
                sock.close()
                raise ConnectionError("websocket_handshake_closed")
            header_bytes += chunk
            if len(header_bytes) > 65536:
                sock.close()
                raise ConnectionError("websocket_handshake_too_large")

        raw_headers, self._buffer = header_bytes.split(b"\r\n\r\n", 1)
        lines = raw_headers.decode("iso-8859-1").split("\r\n")
        if not lines or " 101 " not in f" {lines[0]} ":
            sock.close()
            raise ConnectionError("websocket_handshake_rejected")

        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()

        expected_accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
        ).decode("ascii")
        if headers.get("sec-websocket-accept") != expected_accept:
            sock.close()
            raise ConnectionError("websocket_accept_invalid")
        if headers.get("upgrade", "").lower() != "websocket":
            sock.close()
            raise ConnectionError("websocket_upgrade_invalid")

        sock.settimeout(self.timeout)
        self.sock = sock

    def close(self) -> None:
        sock = self.sock
        self.sock = None
        if sock is None:
            return
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass

    def _read_exact(self, size: int) -> bytes:
        if self.sock is None:
            raise ConnectionError("websocket_not_connected")
        data = b""
        if self._buffer:
            take = min(size, len(self._buffer))
            data = self._buffer[:take]
            self._buffer = self._buffer[take:]
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("websocket_closed")
            data += chunk
        return data

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self.sock is None:
            raise ConnectionError("websocket_not_connected")
        length = len(payload)
        first = 0x80 | (opcode & 0x0F)
        mask_key = os.urandom(4)
        if length < 126:
            header = struct.pack("!BB", first, 0x80 | length)
        elif length <= 0xFFFF:
            header = struct.pack("!BBH", first, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", first, 0x80 | 127, length)
        masked = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(header + mask_key + masked)

    def recv_text(self) -> str:
        fragments: list[bytes] = []
        started = False
        while True:
            first_two = self._read_exact(2)
            first, second = first_two[0], first_two[1]
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            if length > 4 * 1024 * 1024:
                raise ConnectionError("websocket_frame_too_large")
            mask_key = self._read_exact(4) if masked else None
            payload = self._read_exact(length) if length else b""
            if mask_key is not None:
                payload = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))

            if opcode == 0x8:
                raise ConnectionError("websocket_remote_close")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                if started:
                    raise ConnectionError("websocket_nested_text_frame")
                started = True
                fragments.append(payload)
            elif opcode == 0x0 and started:
                fragments.append(payload)
            else:
                raise ConnectionError("websocket_unsupported_frame")

            if fin:
                return b"".join(fragments).decode("utf-8")


def _heartbeat_payload(device_id: str, device_group: str) -> dict[str, Any]:
    return {
        "device_id": device_id,
        "device_group": device_group,
        "version": AGENT_VERSION,
        "capabilities": CAPABILITIES,
        "metrics": collect_metrics(),
    }


def run_websocket_session(
    report_url: str,
    secret: str,
    device_id: str,
    device_group: str,
    state: dict[str, Any],
    state_path: pathlib.Path,
    links_path: pathlib.Path,
) -> None:
    """Keep one authenticated WebSocket session alive and execute received actions."""
    client = WebSocketClient(build_websocket_url(report_url, device_id, device_group, secret))
    client.connect()
    try:
        while True:
            try:
                raw = client.recv_text()
            except socket.timeout:
                send_report(report_url, secret, _heartbeat_payload(device_id, device_group))
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                handle_incoming_batch_action(
                    message,
                    device_id,
                    report_url,
                    secret,
                    state,
                    state_path,
                    links_path,
                )
    finally:
        client.close()


def run_agent_loop(
    config_path: pathlib.Path = config.DEFAULT_CONFIG_PATH,
    device_id_path: pathlib.Path = config.DEFAULT_DEVICE_ID_PATH,
    device_group_path: pathlib.Path = config.DEFAULT_DEVICE_GROUP_PATH,
    state_path: pathlib.Path = config.DEFAULT_STATE_PATH,
    links_path: pathlib.Path = config.DEFAULT_SERVER_LINKS_PATH,
    single_tick: bool = False,
    max_sessions: Optional[int] = None,
) -> None:
    """Main agent execution loop."""
    cfg = config.load_agent_config(config_path)
    device_id = config.load_device_id(device_id_path)
    if not device_id:
        raise RuntimeError("device_id_missing_or_invalid")
    device_group = config.load_device_group(device_group_path)
    report_url = str(cfg.get("worker_report_url") or "").strip()
    secret = str(cfg.get("agent_report_secret") or "").strip()
    if not report_url:
        raise RuntimeError("worker_report_url_missing")
    if not secret:
        raise RuntimeError("agent_report_secret_missing")
    build_websocket_url(report_url, device_id, device_group, secret)

    state: dict[str, Any] = {}
    if state_path.is_file():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    state = loaded
        except Exception:
            state = {}

    print(
        f"[*] Starting phanserver-delta agent: ID={device_id}, Group={device_group}, "
        f"Worker={urllib.parse.urlparse(report_url).netloc}",
        flush=True,
    )

    send_report(report_url, secret, _heartbeat_payload(device_id, device_group))
    if single_tick:
        return

    sessions = 0
    retry_delay = 1
    while True:
        try:
            run_websocket_session(
                report_url,
                secret,
                device_id,
                device_group,
                state,
                state_path,
                links_path,
            )
            retry_delay = 1
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[!] WebSocket session ended: {type(exc).__name__}", flush=True)

        sessions += 1
        if max_sessions is not None and sessions >= max_sessions:
            return
        time.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, 30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="phanserver-delta Device Agent")
    parser.add_argument("--once", action="store_true", help="Run a single heartbeat tick and exit")
    args = parser.parse_args()
    run_agent_loop(single_tick=args.once)

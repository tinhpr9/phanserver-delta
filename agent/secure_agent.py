#!/usr/bin/env python3
"""Hardened phanserver-delta runtime entrypoint.

The base agent owns allocation behavior and retry logic. This entrypoint replaces
only the WebSocket transport so the per-device credential is carried in the
X-Agent-Secret handshake header instead of the URL query string. Fresh-device
identity/config/state live under the private phanserver install root, so setup
does not depend on Android shared-storage permission.
"""

import argparse
import base64
import hashlib
import json
import os
import pathlib
import socket
import ssl
import urllib.parse

import agent as base


def build_websocket_url(report_url: str, device_id: str, device_group: str, secret: str) -> str:
    parsed = urllib.parse.urlparse(report_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("worker_report_url_invalid")
    if not secret:
        raise RuntimeError("agent_report_secret_missing")
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    query = urllib.parse.urlencode({"device_id": device_id, "group": device_group})
    return urllib.parse.urlunparse((ws_scheme, parsed.netloc, "/ws", "", query, ""))


class AuthenticatedWebSocketClient(base.WebSocketClient):
    def __init__(self, url: str, secret: str, timeout: float = 30.0):
        super().__init__(url, timeout=timeout)
        if not secret or any(ch in secret for ch in "\r\n"):
            raise RuntimeError("agent_report_secret_invalid")
        self.secret = secret

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
            f"User-Agent: {base.AGENT_VERSION}\r\n"
            f"X-Agent-Secret: {self.secret}\r\n"
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
            hashlib.sha1((key + base.WS_GUID).encode("ascii")).digest()
        ).decode("ascii")
        if headers.get("sec-websocket-accept") != expected_accept:
            sock.close()
            raise ConnectionError("websocket_accept_invalid")
        if headers.get("upgrade", "").lower() != "websocket":
            sock.close()
            raise ConnectionError("websocket_upgrade_invalid")

        sock.settimeout(self.timeout)
        self.sock = sock


def run_websocket_session(
    report_url,
    secret,
    device_id,
    device_group,
    state,
    state_path,
    links_path,
):
    client = AuthenticatedWebSocketClient(
        build_websocket_url(report_url, device_id, device_group, secret),
        secret,
    )
    client.connect()
    try:
        while True:
            try:
                raw = client.recv_text()
            except socket.timeout:
                base.send_report(report_url, secret, base._heartbeat_payload(device_id, device_group))
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                base.handle_incoming_batch_action(
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


def main() -> None:
    parser = argparse.ArgumentParser(description="phanserver-delta hardened device agent")
    parser.add_argument("--once", action="store_true", help="Run a single heartbeat tick and exit")
    args = parser.parse_args()

    # run_agent_loop resolves these globals at runtime, so the hardened transport
    # becomes the only live command path used by the installed service.
    base.build_websocket_url = build_websocket_url
    base.run_websocket_session = run_websocket_session

    state_root = pathlib.Path(
        os.environ.get("PHANSERVER_DELTA_STATE_ROOT", str(pathlib.Path.home() / ".phanserver-delta"))
    )
    device_root = state_root / "device"
    device_root.mkdir(parents=True, exist_ok=True)

    base.run_agent_loop(
        config_path=device_root / "agent_config.json",
        device_id_path=device_root / "device_id.txt",
        device_group_path=device_root / "device_group.txt",
        state_path=device_root / "state.json",
        links_path=device_root / "server_links.txt",
        single_tick=args.once,
    )


if __name__ == "__main__":
    main()

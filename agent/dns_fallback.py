"""
Resilient DNS Fallback Resolver for phanserver-delta Agent.

Fixes Android VPN (Tailscale/tun0) DNS blackhole where Android bionic libc getaddrinfo
returns [Errno 7] EAI_NODATA (No address associated with hostname) due to Tailscale's
MagicDNS intercepting queries without upstream public nameservers.

Provides:
1. Standard system getaddrinfo lookup first.
2. If gaierror occurs (Errno 7, -2, etc.):
   a. Queries public DNS resolvers (8.8.8.8, 1.1.1.1) via raw UDP socket on port 53.
   b. If UDP 53 is blocked or times out, falls back to pre-cached Cloudflare Anycast IPs
      for Cloudflare Worker domains (*.workers.dev, *cloudflare*).
3. Thread-safe in-memory caching with TTL to avoid redundant lookups.
"""

import concurrent.futures
import random
import socket
import struct
import threading
import time
from typing import Any, List, Optional, Tuple

PUBLIC_DNS_SERVERS = ["8.8.8.8", "1.1.1.1", "8.8.4.4", "9.9.9.9"]
CLOUDFLARE_ANYCAST_IPS = ["172.67.159.108", "104.21.57.53", "104.21.80.1", "104.26.12.181"]
DNS_CACHE_TTL_SECONDS = 300.0
DEFAULT_PRESEED_HOSTS = ["phanserver-delta-worker.tinh1020pr.workers.dev"]

_dns_cache_lock = threading.Lock()
_dns_cache: dict[str, Tuple[List[str], float]] = {}
_dns_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="dns_fallback")


def query_dns_udp(host: str, dns_server: str, timeout: float = 1.5) -> List[str]:
    """Query an upstream DNS server directly via raw UDP socket on port 53."""
    host_clean = host.strip(".")
    if not host_clean:
        return []

    try:
        query_id = random.randint(1, 65535)
        # DNS Header: ID, Flags (0x0100 = recursion desired), QDCOUNT=1, ANCOUNT=0, NSCOUNT=0, ARCOUNT=0
        header = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
        parts = host_clean.split(".")
        qname = b"".join(struct.pack("B", len(p)) + p.encode("ascii") for p in parts) + b"\x00"
        # QTYPE=1 (A record), QCLASS=1 (IN)
        packet = header + qname + struct.pack("!HH", 1, 1)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(packet, (dns_server, 53))
            data, _ = sock.recvfrom(1024)
        finally:
            sock.close()

        if len(data) < 12:
            return []

        res_id, flags, qd_c, an_c, _, _ = struct.unpack("!HHHHHH", data[:12])
        if res_id != query_id or an_c == 0:
            return []

        offset = 12
        # Skip Question section
        for _ in range(qd_c):
            while offset < len(data) and data[offset] != 0:
                if (data[offset] & 0xC0) == 0xC0:
                    offset += 2
                    break
                offset += 1 + data[offset]
            else:
                offset += 1
            offset += 4  # skip qtype and qclass

        ips: List[str] = []
        # Parse Answer section
        for _ in range(an_c):
            if offset >= len(data):
                break
            if (data[offset] & 0xC0) == 0xC0:
                offset += 2
            else:
                while offset < len(data) and data[offset] != 0:
                    offset += 1 + data[offset]
                offset += 1
            if offset + 10 > len(data):
                break
            rtype, rclass, ttl, rdlength = struct.unpack("!HHIH", data[offset : offset + 10])
            offset += 10
            if rtype == 1 and rdlength == 4 and offset + 4 <= len(data):
                ip = socket.inet_ntoa(data[offset : offset + 4])
                if ip not in ips:
                    ips.append(ip)
            offset += rdlength

        return ips
    except Exception:
        return []


def _normalize_port(port: Any) -> int:
    """Normalize numeric or string port service names into integer ports."""
    if isinstance(port, int):
        return port
    if isinstance(port, str):
        if port.isdigit():
            return int(port)
        port_lower = port.lower()
        if port_lower == "https":
            return 443
        if port_lower == "http":
            return 80
        try:
            return socket.getservbyname(port_lower)
        except (OSError, socket.error):
            return 0
    return 0


def _is_ip_address(host: str) -> bool:
    """Check if host string is an IPv4 or IPv6 address."""
    try:
        socket.inet_aton(host)
        return True
    except (socket.error, OSError):
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return True
    except (socket.error, OSError, AttributeError):
        pass
    return False


def resolve_with_fallback(host: str) -> List[str]:
    """Resolve hostname using UDP direct queries, fallback IPs, and cache."""
    now = time.time()
    with _dns_cache_lock:
        if host in _dns_cache:
            ips, expires = _dns_cache[host]
            if expires > now and ips:
                return list(ips)

    ips: List[str] = []
    # 1. Try public DNS resolvers via raw UDP
    for ns in PUBLIC_DNS_SERVERS:
        res = query_dns_udp(host, ns)
        if res:
            ips = res
            break

    # 2. If UDP resolution failed and domain is Cloudflare Worker, fallback to static Anycast IPs
    if not ips and ("workers.dev" in host.lower() or "cloudflare" in host.lower()):
        ips = list(CLOUDFLARE_ANYCAST_IPS)

    if ips:
        with _dns_cache_lock:
            _dns_cache[host] = (ips, now + DNS_CACHE_TTL_SECONDS)

    return ips


_original_getaddrinfo = socket.getaddrinfo


def resilient_getaddrinfo(host: Any, port: Any, family: int = 0, type: int = 0, proto: int = 0, flags: int = 0) -> List[Tuple]:
    """Drop-in wrapper for socket.getaddrinfo with DNS fallback protection."""
    if not host or not isinstance(host, str) or _is_ip_address(host):
        return _original_getaddrinfo(host, port, family, type, proto, flags)

    target_port = _normalize_port(port)
    sock_type = type if type != 0 else socket.SOCK_STREAM
    sock_proto = proto if proto != 0 else (socket.IPPROTO_TCP if sock_type == socket.SOCK_STREAM else socket.IPPROTO_UDP)

    # Check cache first for instant resolution without blocking
    now = time.time()
    with _dns_cache_lock:
        if host in _dns_cache:
            ips, expires = _dns_cache[host]
            if expires > now and ips:
                return [(socket.AF_INET, sock_type, sock_proto, "", (ip, target_port)) for ip in ips]

    # Try original getaddrinfo with 1.5s timeout to prevent Android libc Bionic hang
    try:
        future = _dns_executor.submit(_original_getaddrinfo, host, port, family, type, proto, flags)
        res = future.result(timeout=1.5)
        # Cache successful IPv4 results
        ips = []
        for item in res:
            if item[0] == socket.AF_INET and item[4] and item[4][0] not in ips:
                ips.append(item[4][0])
        if ips:
            with _dns_cache_lock:
                _dns_cache[host] = (ips, now + DNS_CACHE_TTL_SECONDS)
        return res
    except (socket.gaierror, concurrent.futures.TimeoutError, Exception) as orig_err:
        recovered_ips = resolve_with_fallback(host)
        if recovered_ips:
            print(f"[AGENT] [DNS-FALLBACK] Đã khôi phục kết nối cho '{host}' -> {recovered_ips}", flush=True)
            return [(socket.AF_INET, sock_type, sock_proto, "", (ip, target_port)) for ip in recovered_ips]

        if isinstance(orig_err, socket.gaierror):
            raise orig_err
        raise socket.gaierror(getattr(socket, "EAI_NONAME", -2), f"Resolution timeout or failure for {host}: {orig_err}")


def install_dns_fallback(preseed_hosts: Optional[List[str]] = None) -> None:
    """Install resilient_getaddrinfo as the global socket.getaddrinfo hook and preseed worker hosts."""
    targets = list(DEFAULT_PRESEED_HOSTS)
    if preseed_hosts:
        targets.extend(preseed_hosts)

    now = time.time()
    with _dns_cache_lock:
        for h in targets:
            if h not in _dns_cache:
                _dns_cache[h] = (list(CLOUDFLARE_ANYCAST_IPS), now + 86400.0)

    if getattr(socket, "_phanserver_dns_fallback_installed", False):
        return
    socket.getaddrinfo = resilient_getaddrinfo
    socket._phanserver_dns_fallback_installed = True
    print("[AGENT] [DNS-FALLBACK] Đã cài đặt bộ giải mã DNS dự phòng cho Android VPN", flush=True)

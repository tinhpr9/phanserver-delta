import pathlib
import random
import socket
import struct
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from agent import dns_fallback


class TestDnsFallback(unittest.TestCase):
    def setUp(self):
        with dns_fallback._dns_cache_lock:
            dns_fallback._dns_cache.clear()

    def test_normalize_port(self):
        self.assertEqual(dns_fallback._normalize_port(443), 443)
        self.assertEqual(dns_fallback._normalize_port("8080"), 8080)
        self.assertEqual(dns_fallback._normalize_port("https"), 443)
        self.assertEqual(dns_fallback._normalize_port("http"), 80)
        self.assertEqual(dns_fallback._normalize_port("unknown_service_xyz"), 0)
        self.assertEqual(dns_fallback._normalize_port(None), 0)

    def test_is_ip_address(self):
        self.assertTrue(dns_fallback._is_ip_address("127.0.0.1"))
        self.assertTrue(dns_fallback._is_ip_address("104.21.57.53"))
        self.assertTrue(dns_fallback._is_ip_address("::1"))
        self.assertFalse(dns_fallback._is_ip_address("phanserver-delta-worker.tinh1020pr.workers.dev"))
        self.assertFalse(dns_fallback._is_ip_address("google.com"))

    def test_query_dns_udp_packet_parsing(self):
        # Construct a synthetic DNS response packet
        query_id = 0x5678
        flags = 0x8180  # Standard response, no error
        qd_c = 1
        an_c = 2
        header = struct.pack("!HHHHHH", query_id, flags, qd_c, an_c, 0, 0)
        question = b"\x07example\x03com\x00" + struct.pack("!HH", 1, 1)

        # Answer 1: pointer to question name (0xC00C), A record, TTL 300, 4 bytes IP 1.2.3.4
        ans1 = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 300, 4) + socket.inet_aton("1.2.3.4")
        # Answer 2: pointer to question name (0xC00C), A record, TTL 300, 4 bytes IP 5.6.7.8
        ans2 = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 300, 4) + socket.inet_aton("5.6.7.8")

        mock_data = header + question + ans1 + ans2

        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock_cls.return_value = mock_sock
            # Make sure query_id matches
            with patch("random.randint", return_value=query_id):
                mock_sock.recvfrom.return_value = (mock_data, ("8.8.8.8", 53))
                ips = dns_fallback.query_dns_udp("example.com", "8.8.8.8")
                self.assertEqual(ips, ["1.2.3.4", "5.6.7.8"])

    def test_resolve_with_fallback_cache(self):
        with patch.object(dns_fallback, "query_dns_udp", return_value=["192.0.2.1"]) as mock_query:
            # First call queries UDP
            ips1 = dns_fallback.resolve_with_fallback("cache-test.example.com")
            self.assertEqual(ips1, ["192.0.2.1"])
            self.assertEqual(mock_query.call_count, 1)

            # Second call should use in-memory cache
            ips2 = dns_fallback.resolve_with_fallback("cache-test.example.com")
            self.assertEqual(ips2, ["192.0.2.1"])
            self.assertEqual(mock_query.call_count, 1)

    def test_resolve_with_fallback_cloudflare_workers(self):
        # When UDP queries all fail (return empty list)
        with patch.object(dns_fallback, "query_dns_udp", return_value=[]):
            ips = dns_fallback.resolve_with_fallback("phanserver-delta-worker.tinh1020pr.workers.dev")
            self.assertEqual(ips, dns_fallback.CLOUDFLARE_ANYCAST_IPS)

    def test_resilient_getaddrinfo_recovers_from_errno_7(self):
        target_host = "phanserver-delta-worker.tinh1020pr.workers.dev"

        def mock_orig_getaddrinfo(h, p, *args, **kwargs):
            if h == target_host:
                raise socket.gaierror(7, "No address associated with hostname")
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 80))]

        with patch.object(dns_fallback, "_original_getaddrinfo", side_effect=mock_orig_getaddrinfo):
            with patch.object(dns_fallback, "query_dns_udp", return_value=["104.21.57.53"]):
                res = dns_fallback.resilient_getaddrinfo(target_host, "https")
                self.assertTrue(len(res) > 0)
                family, socktype, proto, canonname, sockaddr = res[0]
                self.assertEqual(family, socket.AF_INET)
                self.assertEqual(sockaddr, ("104.21.57.53", 443))

    def test_resilient_getaddrinfo_raises_for_unresolvable_unknown_host(self):
        def mock_orig_getaddrinfo(h, p, *args, **kwargs):
            raise socket.gaierror(-2, "Name or service not known")

        with patch.object(dns_fallback, "_original_getaddrinfo", side_effect=mock_orig_getaddrinfo):
            with patch.object(dns_fallback, "query_dns_udp", return_value=[]):
                with self.assertRaises(socket.gaierror):
                    dns_fallback.resilient_getaddrinfo("definitely-nonexistent-domain-xyz.internal", 80)

    def test_install_dns_fallback_idempotent(self):
        dns_fallback.install_dns_fallback()
        self.assertEqual(socket.getaddrinfo, dns_fallback.resilient_getaddrinfo)
        # Calling again should not cause error or double-wrapping
        dns_fallback.install_dns_fallback()
        self.assertEqual(socket.getaddrinfo, dns_fallback.resilient_getaddrinfo)

    def test_preseed_instant_resolution(self):
        dns_fallback.install_dns_fallback(preseed_hosts=["custom-worker.workers.dev"])
        with patch.object(dns_fallback, "_original_getaddrinfo") as mock_orig:
            res = dns_fallback.resilient_getaddrinfo("custom-worker.workers.dev", 443)
            self.assertEqual(mock_orig.call_count, 0)
            self.assertTrue(len(res) > 0)
            self.assertEqual(res[0][4][0], dns_fallback.CLOUDFLARE_ANYCAST_IPS[0])

    def test_timeout_fallback_on_slow_system_resolver(self):
        def hanging_getaddrinfo(*args, **kwargs):
            time.sleep(2.5)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.2.3.4", 80))]

        with patch.object(dns_fallback, "_original_getaddrinfo", side_effect=hanging_getaddrinfo):
            with patch.object(dns_fallback, "resolve_with_fallback", return_value=["104.21.57.53"]):
                start = time.time()
                res = dns_fallback.resilient_getaddrinfo("slow-domain.com", 80)
                elapsed = time.time() - start
                self.assertLess(elapsed, 2.2)
                self.assertEqual(res[0][4][0], "104.21.57.53")


if __name__ == "__main__":
    unittest.main()

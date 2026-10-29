#!/usr/bin/env python3
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = pathlib.Path("/root/phanserver-delta")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.agent import (
    build_tailscale_command,
    compute_screen_coordinates,
    handle_incoming_batch_action,
    validate_tailscale_cgnat_ip,
)


class TestHardenedTailscaleAgent(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = pathlib.Path(self.temp_dir.name)
        self.links_path = self.root_path / "server_links.txt"
        self.state_path = self.root_path / "state.json"
        self.report_url = "https://mock.worker/report"
        self.secret = "mock-secret"
        self.device_id = "m77"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cgnat_100_ip_validation_hardened(self):
        # Valid Tailscale CGNAT IPs
        self.assertTrue(validate_tailscale_cgnat_ip("100.80.175.55"))
        self.assertTrue(validate_tailscale_cgnat_ip("100.64.0.1"))
        self.assertTrue(validate_tailscale_cgnat_ip("100.115.92.14"))
        self.assertTrue(validate_tailscale_cgnat_ip("100.127.255.254"))

        # Invalid IPs - Out of range octets & 4-digit octet suffix attacks
        self.assertFalse(validate_tailscale_cgnat_ip("100.300.1.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.2.2555"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.256.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.1.999"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.999.999.999"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.abc.1.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.2.3.4"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.-1.0.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.2.3/24"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.2."))
        self.assertFalse(validate_tailscale_cgnat_ip(".100.1.2.3"))
        self.assertFalse(validate_tailscale_cgnat_ip("100..1.2"))
        self.assertFalse(validate_tailscale_cgnat_ip("192.168.1.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("10.0.0.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("172.16.0.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("127.0.0.1"))
        self.assertFalse(validate_tailscale_cgnat_ip(""))
        self.assertFalse(validate_tailscale_cgnat_ip(None))
        self.assertFalse(validate_tailscale_cgnat_ip(12345))
        self.assertFalse(validate_tailscale_cgnat_ip(["100.64.0.1"]))

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_tailscale_connect_malformed_ip_returns_failed_300(self, mock_subproc, mock_ack):
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "CONNECTED: 100.300.1.1\n"
        mock_subproc.return_value.stderr = ""
        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "ts-bad-300",
            "mode": "on",
            "target_device_ids": [self.device_id],
        }

        handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["status"], "FAILED")
        self.assertFalse(kwargs["executed"])
        self.assertIsNone(kwargs["details"])
        self.assertIn("vpn_timeout_no_ip", kwargs["reason"])

    def test_screen_orientation_adversarial_resolutions(self):
        coords_tall = compute_screen_coordinates(1080, 2400, rotation=0)
        self.assertFalse(coords_tall["is_landscape"])
        self.assertGreater(coords_tall["toggle_x"], 0)
        self.assertLess(coords_tall["toggle_x"], 1080)
        self.assertGreater(coords_tall["toggle_y"], 0)
        self.assertLess(coords_tall["toggle_y"], 2400)

        coords_sq = compute_screen_coordinates(1000, 1000, rotation=0)
        self.assertEqual(coords_sq["center_x"], 500)
        self.assertEqual(coords_sq["center_y"], 500)

        coords_oob = compute_screen_coordinates(720, 1280, rotation=4)
        self.assertFalse(coords_oob["is_landscape"])

    def test_ui_keyevents_error_suppression(self):
        cmd = build_tailscale_command("on")
        for ke in ["KEYCODE_BACK", "KEYCODE_HOME"]:
            pattern = rf"input keyevent {ke}\s*>/dev/null\s*2>&1\s*\|\|\s*true"
            self.assertRegex(cmd, pattern, f"Keyevent {ke} missing error suppression")


if __name__ == "__main__":
    unittest.main()

"""Adversarial stress test suite for Agent Tailscale implementation.
Tests edge cases in:
- Screen orientation, aspect ratios, square/odd displays, invalid rotation inputs
- IP regex, octet validation, partial matches, malformed IPs
- Subprocess timeout, signal termination, exit codes, fake TRIGGERED
- UI keyevent resilience and error suppression
"""

import pathlib
import re
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from agent.agent import (
    build_tailscale_command,
    compute_screen_coordinates,
    handle_incoming_batch_action,
    validate_tailscale_cgnat_ip,
)


class TestOrientationStress(unittest.TestCase):
    """Stress testing screen orientation and coordinate computation."""

    def test_standard_resolutions_all_rotations(self):
        """Test standard 720p and 1080p across rotations 0, 1, 2, 3."""
        resolutions = [(720, 1280), (1080, 1920)]
        for w, h in resolutions:
            for rot in [0, 1, 2, 3]:
                coords = compute_screen_coordinates(w, h, rotation=rot)
                self.assertIn("toggle_x", coords)
                self.assertIn("toggle_y", coords)
                self.assertIn("center_x", coords)
                self.assertIn("center_y", coords)
                self.assertGreaterEqual(coords["toggle_x"], 0)
                self.assertLessEqual(coords["toggle_x"], coords["width"])
                self.assertGreaterEqual(coords["toggle_y"], 0)
                self.assertLessEqual(coords["toggle_y"], coords["height"])
                self.assertEqual(coords["center_x"], coords["width"] // 2)
                self.assertEqual(coords["center_y"], coords["height"] // 2)
                if rot in (1, 3):
                    self.assertTrue(coords["is_landscape"])
                    self.assertEqual(coords["width"], max(w, h))
                    self.assertEqual(coords["height"], min(w, h))
                else:
                    self.assertFalse(coords["is_landscape"])
                    self.assertEqual(coords["width"], min(w, h))
                    self.assertEqual(coords["height"], max(w, h))

    def test_odd_and_ultra_tall_resolutions(self):
        """Test odd modern smartphone aspect ratios: 1080x2400 (20:9), 720x1520 (19:9), 1440x3200."""
        odd_resolutions = [
            (1080, 2400),
            (720, 1520),
            (1440, 3200),
            (1080, 2340),
            (540, 960),
            (320, 480),
        ]
        for w, h in odd_resolutions:
            for rot in [0, 1]:
                coords = compute_screen_coordinates(w, h, rotation=rot)
                self.assertGreaterEqual(coords["toggle_x"], 0)
                self.assertLessEqual(coords["toggle_x"], coords["width"])
                self.assertGreaterEqual(coords["toggle_y"], 0)
                self.assertLessEqual(coords["toggle_y"], coords["height"])

    def test_square_display(self):
        """Test square display e.g. 1000x1000 (smartwatch, POS, emulator)."""
        coords = compute_screen_coordinates(1000, 1000, rotation=0)
        self.assertFalse(coords["is_landscape"])
        self.assertEqual(coords["width"], 1000)
        self.assertEqual(coords["height"], 1000)
        self.assertEqual(coords["toggle_x"], 880)
        self.assertEqual(coords["toggle_y"], 80)
        self.assertEqual(coords["center_x"], 500)
        self.assertEqual(coords["center_y"], 500)

        coords_rot1 = compute_screen_coordinates(1000, 1000, rotation=1)
        self.assertTrue(coords_rot1["is_landscape"])
        self.assertEqual(coords_rot1["toggle_x"], 920)
        self.assertEqual(coords_rot1["toggle_y"], 120)

    def test_inverted_dimensions_portrait_rotation(self):
        """If input width > height (e.g. 1920x1080) but rotation is 0, heuristic detects landscape."""
        coords = compute_screen_coordinates(1920, 1080, rotation=0)
        self.assertTrue(coords["is_landscape"])
        self.assertEqual(coords["width"], 1920)
        self.assertEqual(coords["height"], 1080)

    def test_unexpected_rotation_types_and_values(self):
        """Check behavior when rotation is out of 0-3 range or unexpected type."""
        # rotation = 4 (undefined)
        coords = compute_screen_coordinates(720, 1280, rotation=4)
        self.assertFalse(coords["is_landscape"])
        self.assertEqual(coords["width"], 720)
        self.assertEqual(coords["height"], 1280)

        # rotation = -1
        coords_neg = compute_screen_coordinates(720, 1280, rotation=-1)
        self.assertFalse(coords_neg["is_landscape"])

        # string inputs for dimensions
        coords_str = compute_screen_coordinates("720", "1280", rotation=0)
        self.assertEqual(coords_str["width"], 720)


class TestIPValidationStress(unittest.TestCase):
    """Stress testing IP validation and regex matching."""

    def test_valid_cgnat_ips(self):
        valid = [
            "100.64.0.1",
            "100.127.255.254",
            "100.80.175.55",
            "100.0.0.0",
            "100.255.255.255",
            "100.100.100.100",
            "  100.80.175.55  ",  # should strip whitespace
        ]
        for ip in valid:
            self.assertTrue(
                validate_tailscale_cgnat_ip(ip),
                f"Expected {ip} to be valid CGNAT IP",
            )

    def test_invalid_octets_greater_than_255(self):
        invalid = [
            "100.300.1.1",
            "100.1.256.1",
            "100.1.1.999",
            "100.999.999.999",
            "100.256.0.0",
        ]
        for ip in invalid:
            self.assertFalse(
                validate_tailscale_cgnat_ip(ip),
                f"Expected {ip} to be rejected (octet > 255)",
            )

    def test_malformed_ip_structures(self):
        malformed = [
            "100.abc.1.1",
            "100.1.1",
            "100.1.2.3.4",
            "100.-1.0.1",
            "100.1.2.3/24",
            "100.1.2.",
            ".100.1.2.3",
            "100..1.2",
            "192.168.1.1",
            "10.0.0.1",
            "172.16.0.1",
            "100.1.2.3; echo hacked",
            "<script>alert(1)</script>",
            "",
            None,
            12345,
            ["100.64.0.1"],
        ]
        for ip in malformed:
            self.assertFalse(
                validate_tailscale_cgnat_ip(ip),
                f"Expected {ip!r} to be rejected",
            )

    def test_partial_ip_suffix_attack_on_agent_handling(self):
        """Adversarial check: if stdout is 'CONNECTED: 100.1.2.2555', what does agent do?
        100.1.2.2555 has 4 digits in last octet.
        """
        temp_dir = tempfile.TemporaryDirectory()
        root_path = pathlib.Path(temp_dir.name)
        state_path = root_path / "state.json"
        links_path = root_path / "server_links.txt"
        state = {}

        msg = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "test-act-partial-ip",
            "mode": "on",
            "target_device_ids": ["m77"],
        }

        # Subprocess returns CONNECTED: 100.1.2.2555
        mock_proc = MagicMock(returncode=0, stdout="CONNECTED: 100.1.2.2555\n", stderr="")
        with patch("subprocess.run", return_value=mock_proc), patch("agent.agent.send_ack") as mock_ack:
            handle_incoming_batch_action(msg, "m77", "http://worker/report", "sec", state, state_path, links_path)
            self.assertTrue(mock_ack.called)
            ack_args = mock_ack.call_args[1]
            ack_status = ack_args.get("status")
            ack_details = ack_args.get("details")

            print(f"\n[EMPIRICAL TEST] Suffix 100.1.2.2555 result: status={ack_status}, details={ack_details}")
            # In stdout_text, 100.1.2.255 was captured by regex 100\.\d{1,3}\.\d{1,3}\.\d{1,3}
            # This demonstrates how agent behaves with 4-digit octets.
        temp_dir.cleanup()


class TestSubprocessTimeoutAndFailureStress(unittest.TestCase):
    """Stress testing subprocess timeouts, crashes, signals, and fake TRIGGERED."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = pathlib.Path(self.temp_dir.name)
        self.state_path = self.root_path / "state.json"
        self.links_path = self.root_path / "server_links.txt"
        self.state = {"pending_actions": {}, "completed_actions": {}}

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_subprocess_timeout_expired(self):
        """When subprocess.run raises TimeoutExpired, result must be FAILED, never OPENED."""
        msg = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "act-timeout",
            "mode": "on",
            "target_device_ids": ["m77"],
        }
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="sh", timeout=30)), \
             patch("agent.agent.send_ack") as mock_ack:
            handle_incoming_batch_action(msg, "m77", "http://worker/report", "sec", self.state, self.state_path, self.links_path)
            self.assertTrue(mock_ack.called)
            args = mock_ack.call_args[1]
            self.assertEqual(args["status"], "FAILED")
            self.assertFalse(args["executed"])
            self.assertTrue(
                "quá thời gian" in args["reason"].lower() or "timed out" in args["reason"].lower(),
                f"Expected timeout reason, got: {args['reason']}"
            )
            self.assertIsNone(args["details"])

    def test_shell_exit_code_1_timeout(self):
        """When shell script exits with code 1 after 12s timeout, result must be FAILED."""
        msg = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "act-shell-timeout",
            "mode": "on",
            "target_device_ids": ["m77"],
        }
        mock_proc = MagicMock(
            returncode=1,
            stdout="",
            stderr="vpn_timeout_no_ip: Timeout 12s không nhận được IP Tailscale (100.x.y.z)\n",
        )
        with patch("subprocess.run", return_value=mock_proc), patch("agent.agent.send_ack") as mock_ack:
            handle_incoming_batch_action(msg, "m77", "http://worker/report", "sec", self.state, self.state_path, self.links_path)
            self.assertTrue(mock_ack.called)
            args = mock_ack.call_args[1]
            self.assertEqual(args["status"], "FAILED")
            self.assertFalse(args["executed"])
            self.assertIn("vpn_timeout_no_ip", args["reason"])
            self.assertIsNone(args["details"])

    def test_shell_killed_by_sigkill(self):
        """When process is terminated by SIGKILL (returncode -9 / 137)."""
        msg = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "act-sigkill",
            "mode": "on",
            "target_device_ids": ["m77"],
        }
        mock_proc = MagicMock(returncode=-9, stdout="", stderr="Killed\n")
        with patch("subprocess.run", return_value=mock_proc), patch("agent.agent.send_ack") as mock_ack:
            handle_incoming_batch_action(msg, "m77", "http://worker/report", "sec", self.state, self.state_path, self.links_path)
            self.assertTrue(mock_ack.called)
            args = mock_ack.call_args[1]
            self.assertEqual(args["status"], "FAILED")
            self.assertFalse(args["executed"])
            self.assertIsNone(args["details"])

    def test_fake_success_triggered_is_rejected(self):
        """If legacy script returns TRIGGERED with code 0, must be FAILED."""
        msg = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "act-fake-triggered",
            "mode": "on",
            "target_device_ids": ["m77"],
        }
        mock_proc = MagicMock(returncode=0, stdout="TRIGGERED\n", stderr="")
        with patch("subprocess.run", return_value=mock_proc), patch("agent.agent.send_ack") as mock_ack:
            handle_incoming_batch_action(msg, "m77", "http://worker/report", "sec", self.state, self.state_path, self.links_path)
            self.assertTrue(mock_ack.called)
            args = mock_ack.call_args[1]
            self.assertEqual(args["status"], "FAILED")
            self.assertFalse(args["executed"])
            self.assertIsNone(args["details"])

    def test_invalid_ip_in_stdout_returns_failed(self):
        """If stdout has CONNECTED: 100.300.1.1 (invalid octet 300), must be FAILED."""
        msg = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "act-bad-ip",
            "mode": "on",
            "target_device_ids": ["m77"],
        }
        mock_proc = MagicMock(returncode=0, stdout="CONNECTED: 100.300.1.1\n", stderr="")
        with patch("subprocess.run", return_value=mock_proc), patch("agent.agent.send_ack") as mock_ack:
            handle_incoming_batch_action(msg, "m77", "http://worker/report", "sec", self.state, self.state_path, self.links_path)
            self.assertTrue(mock_ack.called)
            args = mock_ack.call_args[1]
            self.assertEqual(args["status"], "FAILED")
            self.assertFalse(args["executed"])


class TestUIKeyeventsAndCommandIntegrity(unittest.TestCase):
    """Stress testing command generation and keyevents."""

    def test_keyevents_and_user0_present(self):
        cmd = build_tailscale_command("on")
        self.assertIn("am start --user 0 -n com.tailscale.ipn/.MainActivity", cmd)
        self.assertIn("input keyevent KEYCODE_BACK", cmd)
        self.assertIn("input keyevent KEYCODE_HOME", cmd)
        self.assertIn("dev tun0", cmd)
        self.assertIn("100\\.", cmd)

    def test_keyevents_have_error_suppression(self):
        """Keyevents must have >/dev/null 2>&1 || true so missing 'input' doesn't abort."""
        cmd = build_tailscale_command("on")
        for ke in ["KEYCODE_BACK", "KEYCODE_HOME", "KEYCODE_TAB", "KEYCODE_ENTER", "KEYCODE_DPAD_CENTER"]:
            pattern = rf"input keyevent {ke}\s*>/dev/null\s*2>&1\s*\|\|\s*true"
            self.assertRegex(cmd, pattern, f"Keyevent {ke} missing error suppression || true")


if __name__ == "__main__":
    unittest.main()

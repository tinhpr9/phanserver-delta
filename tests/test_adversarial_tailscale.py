#!/usr/bin/env python3
"""Adversarial stress test harness for Tailscale VPN implementation.
Tests edge cases, boundary values, malformed inputs, concurrency, and idempotency.
Strictly compliant with R4: zero execution on real UgPhone devices.
"""

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent import agent
from agent.agent import (
    build_tailscale_command,
    compute_screen_coordinates,
    handle_incoming_batch_action,
    validate_tailscale_cgnat_ip,
)


class TestAdversarialTailscale(unittest.TestCase):
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

    # =========================================================================
    # 1. ADVERSARIAL IP VALIDATION & MALFORMED OUTPUTS
    # =========================================================================

    def test_cgnat_ip_adversarial_inputs(self):
        """Stress-test validate_tailscale_cgnat_ip with diverse malicious and malformed inputs."""
        malicious_or_invalid = [
            "100.80.175.55\nrm -rf /",
            "100.80.175.55; id",
            "100.80.175.55 && echo pwned",
            "100.256.0.1",       # Octet > 255
            "100.0.256.1",
            "100.0.0.256",
            "100.-1.0.1",        # Negative
            "100.64.0.0/10",     # CIDR notation
            "100.64.0.1:80",     # Port notation
            "100.64.0",          # Too short
            "100.64.0.1.2",      # Too long
            "192.168.1.1",       # Private Class C
            "10.0.0.1",          # Private Class A
            "172.16.0.1",        # Private Class B
            "127.0.0.1",         # Loopback
            "0.0.0.0",
            "255.255.255.255",
            "",
            "   ",
            None,
            12345,
            [],
            {},
            "100.64.0.1\x00",
        ]
        for item in malicious_or_invalid:
            self.assertFalse(
                validate_tailscale_cgnat_ip(item),
                f"Expected invalid for: {item!r}"
            )

        valid_cgnat_ips = [
            "100.64.0.0",
            "100.64.0.1",
            "100.80.175.55",
            "100.115.92.14",
            "100.127.255.254",
            "100.127.255.255",
            " 100.80.175.55 ",   # Whitespace stripped
        ]
        for ip in valid_cgnat_ips:
            self.assertTrue(
                validate_tailscale_cgnat_ip(ip),
                f"Expected valid for: {ip!r}"
            )

    # =========================================================================
    # 2. ADVERSARIAL FAKE SUCCESS ELIMINATION (AGENT LEVEL)
    # =========================================================================

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_fake_success_various_stdout_shapes(self, mock_subproc, mock_ack):
        """Rigorously challenge agent response when stdout does NOT contain a valid 100.x.y.z IP."""
        bad_outputs = [
            ("TRIGGERED", 0, "legacy TRIGGERED bug"),
            ("CONNECTED: 192.168.1.100", 0, "LAN IP disguised as Tailscale"),
            ("CONNECTED: 10.0.0.1", 0, "Class A IP"),
            ("CONNECTED: 172.16.0.5", 0, "Class B IP"),
            ("CONNECTED: 100.300.1.1", 0, "Invalid octet IP"),
            ("CONNECTED: ", 0, "Empty IP suffix"),
            ("CONNECTED:", 0, "No whitespace or IP"),
            ("CONNECTED: none", 0, "Word 'none'"),
            ("SUCCESS", 0, "Generic success word"),
            ("OK", 0, "Generic OK"),
            ("", 0, "Empty stdout with returncode 0"),
            ("CONNECTED: 100.80.175.55", 1, "Exit code 1 despite text in stdout"),
            ("CONNECTED: 100.80.175.55", 127, "Command not found exit code"),
        ]

        state = {}
        for idx, (stdout_val, ret_code, desc) in enumerate(bad_outputs):
            mock_subproc.return_value.returncode = ret_code
            mock_subproc.return_value.stdout = stdout_val
            mock_subproc.return_value.stderr = "error_text" if ret_code != 0 else ""
            mock_ack.reset_mock()

            action_id = f"ts-fake-shape-{idx}"
            message = {
                "protocol": "fleet-batch-v1",
                "action": "CONTROL_TAILSCALE",
                "action_id": action_id,
                "mode": "on",
                "target_device_ids": [self.device_id],
            }

            handle_incoming_batch_action(
                message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
            )

            kwargs = mock_ack.call_args.kwargs
            self.assertEqual(
                kwargs["status"],
                "FAILED",
                f"Failed for {desc}: expected status 'FAILED' but got {kwargs['status']}"
            )
            self.assertFalse(
                kwargs["executed"],
                f"Failed for {desc}: expected executed=False"
            )
            self.assertIsNone(
                kwargs["details"],
                f"Failed for {desc}: expected details=None"
            )

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_subprocess_timeout_and_exceptions(self, mock_subproc, mock_ack):
        """Test agent behavior when subprocess.run raises TimeoutExpired or OSError."""
        state = {}

        # 1. TimeoutExpired
        mock_subproc.side_effect = subprocess.TimeoutExpired(cmd="sh -c ...", timeout=30)
        message = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "ts-timeout-exc",
            "mode": "on",
            "target_device_ids": [self.device_id],
        }
        handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["status"], "FAILED")
        self.assertFalse(kwargs["executed"])

        # 2. OSError (e.g. sh binary missing or fork failure)
        mock_ack.reset_mock()
        mock_subproc.side_effect = OSError("Cannot allocate memory")
        message["action_id"] = "ts-os-exc"
        handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["status"], "FAILED")
        self.assertFalse(kwargs["executed"])
        self.assertIn("Cannot allocate memory", kwargs["reason"])

    # =========================================================================
    # 3. CONCURRENCY & IDEMPOTENCY
    # =========================================================================

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_idempotency_caching_failed_status(self, mock_subproc, mock_ack):
        """Ensure that if an action failed, re-submitting identical action_id returns FAILED from cache."""
        mock_subproc.return_value.returncode = 1
        mock_subproc.return_value.stdout = ""
        mock_subproc.return_value.stderr = "vpn_timeout_no_ip: Timeout 12s"

        state = {}
        action_id = "ts-failed-cache-01"
        message = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": action_id,
            "mode": "on",
            "target_device_ids": [self.device_id],
        }

        # First run: fails
        handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertEqual(mock_subproc.call_count, 1)
        self.assertEqual(mock_ack.call_args.kwargs["status"], "FAILED")

        # Second run: must replay cached failure WITHOUT invoking subprocess
        handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertEqual(mock_subproc.call_count, 1, "Subprocess was invoked on cached replay!")
        self.assertEqual(mock_ack.call_args.kwargs["status"], "FAILED")

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_rapid_mode_switching(self, mock_subproc, mock_ack):
        """Test rapid switching between on -> off -> status -> on."""
        mock_subproc.return_value.returncode = 0
        state = {}

        # 1. Turn on
        mock_subproc.return_value.stdout = "CONNECTED: 100.80.175.55"
        handle_incoming_batch_action(
            {"protocol": "fleet-batch-v1", "action": "CONTROL_TAILSCALE", "action_id": "act-1", "mode": "on", "target_device_ids": [self.device_id]},
            self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertEqual(mock_ack.call_args.kwargs["status"], "OPENED")
        self.assertEqual(mock_ack.call_args.kwargs["details"], "CONNECTED: 100.80.175.55")

        # 2. Turn off
        mock_subproc.return_value.stdout = "DISCONNECTED"
        handle_incoming_batch_action(
            {"protocol": "fleet-batch-v1", "action": "CONTROL_TAILSCALE", "action_id": "act-2", "mode": "off", "target_device_ids": [self.device_id]},
            self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertEqual(mock_ack.call_args.kwargs["status"], "OPENED")
        self.assertEqual(mock_ack.call_args.kwargs["details"], "DISCONNECTED")

        # 3. Check status (disconnected)
        mock_subproc.return_value.stdout = "DISCONNECTED"
        handle_incoming_batch_action(
            {"protocol": "fleet-batch-v1", "action": "CONTROL_TAILSCALE", "action_id": "act-3", "mode": "status", "target_device_ids": [self.device_id]},
            self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertEqual(mock_ack.call_args.kwargs["status"], "OPENED")
        self.assertEqual(mock_ack.call_args.kwargs["details"], "DISCONNECTED")

        # 4. Turn on again with new IP
        mock_subproc.return_value.stdout = "CONNECTED: 100.115.92.14"
        handle_incoming_batch_action(
            {"protocol": "fleet-batch-v1", "action": "CONTROL_TAILSCALE", "action_id": "act-4", "mode": "on", "target_device_ids": [self.device_id]},
            self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertEqual(mock_ack.call_args.kwargs["status"], "OPENED")
        self.assertEqual(mock_ack.call_args.kwargs["details"], "CONNECTED: 100.115.92.14")

        # Verify all 4 actions are stored independently in state
        self.assertEqual(len(state["tailscale_action_results"]), 4)

    # =========================================================================
    # 4. SCREEN ORIENTATION & COORDINATE BOUNDARY STRESS TESTS
    # =========================================================================

    def test_coordinate_computation_boundary_cases(self):
        """Stress-test compute_screen_coordinates with various resolutions and rotations."""
        test_resolutions = [
            (720, 1280),    # Standard 720p portrait
            (1280, 720),    # Standard 720p landscape
            (1080, 1920),   # 1080p portrait
            (1920, 1080),   # 1080p landscape
            (1440, 2560),   # 2K portrait
            (2560, 1440),   # 2K landscape
            (1080, 1080),   # Square display
            (480, 800),     # Low res
        ]
        for w, h in test_resolutions:
            for rot in [0, 1, 2, 3]:
                coords = compute_screen_coordinates(w, h, rotation=rot)
                actual_w = coords["width"]
                actual_h = coords["height"]
                tx, ty = coords["toggle_x"], coords["toggle_y"]
                cx, cy = coords["center_x"], coords["center_y"]

                # Ensure coordinates are strictly within screen boundaries
                self.assertGreater(cx, 0)
                self.assertLess(cx, actual_w)
                self.assertGreater(cy, 0)
                self.assertLess(cy, actual_h)

                self.assertGreater(tx, 0)
                self.assertLess(tx, actual_w)
                self.assertGreater(ty, 0)
                self.assertLess(ty, actual_h)

                if rot in (1, 3) or (rot not in (1, 3) and w > h):
                    self.assertTrue(coords["is_landscape"])
                    self.assertEqual(actual_w, max(w, h))
                    self.assertEqual(actual_h, min(w, h))
                else:
                    self.assertFalse(coords["is_landscape"])
                    self.assertEqual(actual_w, min(w, h))
                    self.assertEqual(actual_h, max(w, h))

    # =========================================================================
    # 5. R4 COMPLIANCE: ZERO REAL DEVICE / NETWORK COMMAND AUDIT
    # =========================================================================

    def test_shell_script_hermetic_syntax(self):
        """Verify build_tailscale_command syntax without executing on real Android devices."""
        for mode in ["on", "off", "status"]:
            cmd = build_tailscale_command(mode)
            self.assertIsInstance(cmd, str)
            self.assertGreater(len(cmd), 10)
            # Check for dangerous unquoted variables or destructive commands
            self.assertNotIn("rm -rf /", cmd)
            self.assertNotIn("mkfs", cmd)
            # Check bash syntax using bash -n (dry run syntax check)
            proc = subprocess.run(["bash", "-n"], input=cmd, text=True, capture_output=True)
            self.assertEqual(
                proc.returncode, 0,
                f"Bash syntax error in build_tailscale_command('{mode}'): {proc.stderr}"
            )


if __name__ == "__main__":
    unittest.main()

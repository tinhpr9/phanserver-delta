#!/usr/bin/env python3
"""Comprehensive mock unit test suite for Device Agent Tailscale handling.
Strictly compliant with R4: zero execution on real UgPhone devices.
"""

import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

# Ensure project root is on sys.path
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


class TestTailscaleDeviceAgent(unittest.TestCase):
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

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_tailscale_connect_success_portrait(self, mock_subproc, mock_ack):
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "CONNECTED: 100.80.175.55"
        mock_subproc.return_value.stderr = ""
        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "ts-portrait-01",
            "mode": "on",
            "target_device_ids": [self.device_id],
        }

        success = handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertTrue(success)
        self.assertEqual(mock_ack.call_count, 1)
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["batch_action"], "CONTROL_TAILSCALE")
        self.assertEqual(kwargs["status"], "OPENED")
        self.assertTrue(kwargs["executed"])
        self.assertEqual(kwargs["details"], "CONNECTED: 100.80.175.55")
        self.assertIsNone(kwargs["reason"])

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_tailscale_connect_success_landscape(self, mock_subproc, mock_ack):
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "CONNECTED: 100.115.92.14"
        mock_subproc.return_value.stderr = ""
        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "ts-landscape-01",
            "mode": "on",
            "target_device_ids": [self.device_id],
        }

        success = handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertTrue(success)
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["status"], "OPENED")
        self.assertTrue(kwargs["executed"])
        self.assertEqual(kwargs["details"], "CONNECTED: 100.115.92.14")
        self.assertIsNone(kwargs["reason"])

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_tailscale_connect_timeout_returns_failed(self, mock_subproc, mock_ack):
        # Shell script timed out and exited 1 with error
        mock_subproc.return_value.returncode = 1
        mock_subproc.return_value.stdout = ""
        mock_subproc.return_value.stderr = "vpn_timeout_no_ip: Timeout 12s không nhận được IP Tailscale (100.x.y.z)"
        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "ts-timeout-01",
            "mode": "on",
            "target_device_ids": [self.device_id],
        }

        success = handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertTrue(success)
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["status"], "FAILED")
        self.assertFalse(kwargs["executed"])
        self.assertIsNone(kwargs["details"])
        self.assertIn("vpn_timeout_no_ip", kwargs["reason"])

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_elimination_of_fake_triggered_opened(self, mock_subproc, mock_ack):
        # Emulating legacy bug where script returned code 0 with TRIGGERED (no IP)
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "TRIGGERED"
        mock_subproc.return_value.stderr = ""
        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "ts-fake-01",
            "mode": "on",
            "target_device_ids": [self.device_id],
        }

        handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        kwargs = mock_ack.call_args.kwargs
        # Must be rejected as FAILED, NEVER OPENED!
        self.assertEqual(kwargs["status"], "FAILED")
        self.assertFalse(kwargs["executed"])
        self.assertNotEqual(kwargs["status"], "OPENED")

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_tailscale_disconnect_off(self, mock_subproc, mock_ack):
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "DISCONNECTED"
        mock_subproc.return_value.stderr = ""
        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "ts-off-01",
            "mode": "off",
            "target_device_ids": [self.device_id],
        }

        success = handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertTrue(success)
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["status"], "OPENED")
        self.assertTrue(kwargs["executed"])
        self.assertEqual(kwargs["details"], "DISCONNECTED")

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_tailscale_status_connected(self, mock_subproc, mock_ack):
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "CONNECTED: 100.64.10.5"
        mock_subproc.return_value.stderr = ""
        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "ts-status-01",
            "mode": "status",
            "target_device_ids": [self.device_id],
        }

        success = handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertTrue(success)
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["status"], "OPENED")
        self.assertTrue(kwargs["executed"])
        self.assertEqual(kwargs["details"], "CONNECTED: 100.64.10.5")

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_tailscale_status_disconnected(self, mock_subproc, mock_ack):
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "DISCONNECTED"
        mock_subproc.return_value.stderr = ""
        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "ts-status-02",
            "mode": "status",
            "target_device_ids": [self.device_id],
        }

        success = handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertTrue(success)
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["status"], "OPENED")
        self.assertTrue(kwargs["executed"])
        self.assertEqual(kwargs["details"], "DISCONNECTED")

    def test_user_0_flag_present(self):
        on_cmd = build_tailscale_command("on")
        off_cmd = build_tailscale_command("off")

        self.assertIn("am start --user 0 -n com.tailscale.ipn/.MainActivity", on_cmd)
        self.assertIn("am broadcast --user 0 -a com.tailscale.ipn.CONNECT_VPN", on_cmd)
        self.assertIn("am broadcast --user 0 -a com.tailscale.ipn.DISCONNECT_VPN", off_cmd)
        self.assertIn("am force-stop --user 0 com.tailscale.ipn", off_cmd)

    def test_orientation_and_coordinate_computation(self):
        # Portrait test (720x1280, rotation 0)
        p = compute_screen_coordinates(720, 1280, rotation=0)
        self.assertFalse(p["is_landscape"])
        self.assertEqual(p["width"], 720)
        self.assertEqual(p["height"], 1280)
        self.assertEqual(p["center_x"], 360)
        self.assertEqual(p["center_y"], 640)
        self.assertEqual(p["toggle_x"], int(720 * 0.88))
        self.assertEqual(p["toggle_y"], int(1280 * 0.08))

        # Landscape test (rotation 1: 90°)
        l1 = compute_screen_coordinates(720, 1280, rotation=1)
        self.assertTrue(l1["is_landscape"])
        self.assertEqual(l1["width"], 1280)
        self.assertEqual(l1["height"], 720)
        self.assertEqual(l1["center_x"], 640)
        self.assertEqual(l1["center_y"], 360)
        self.assertEqual(l1["toggle_x"], int(1280 * 0.92))
        self.assertEqual(l1["toggle_y"], int(720 * 0.12))

        # Landscape test (rotation 3: 270°)
        l3 = compute_screen_coordinates(1080, 1920, rotation=3)
        self.assertTrue(l3["is_landscape"])
        self.assertEqual(l3["width"], 1920)
        self.assertEqual(l3["height"], 1080)
        self.assertEqual(l3["center_x"], 960)
        self.assertEqual(l3["center_y"], 540)
        self.assertEqual(l3["toggle_x"], int(1920 * 0.92))
        self.assertEqual(l3["toggle_y"], int(1080 * 0.12))

        # Landscape by dimension (1280x720, rotation 0)
        ldim = compute_screen_coordinates(1280, 720, rotation=0)
        self.assertTrue(ldim["is_landscape"])
        self.assertEqual(ldim["width"], 1280)
        self.assertEqual(ldim["height"], 720)

    def test_cgnat_100_ip_validation(self):
        # Valid Tailscale CGNAT IPs
        self.assertTrue(validate_tailscale_cgnat_ip("100.80.175.55"))
        self.assertTrue(validate_tailscale_cgnat_ip("100.64.0.1"))
        self.assertTrue(validate_tailscale_cgnat_ip("100.115.92.14"))
        self.assertTrue(validate_tailscale_cgnat_ip("100.127.255.254"))
        self.assertTrue(validate_tailscale_cgnat_ip("100.0.0.0"))
        self.assertTrue(validate_tailscale_cgnat_ip("100.255.255.255"))

        # Invalid IPs
        self.assertFalse(validate_tailscale_cgnat_ip("192.168.1.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("10.0.0.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("172.16.0.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("127.0.0.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.300.1.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.2"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.2.2555"))
        self.assertFalse(validate_tailscale_cgnat_ip("1100.1.2.3"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.2.3.4"))
        self.assertFalse(validate_tailscale_cgnat_ip(".100.1.2.3"))
        self.assertFalse(validate_tailscale_cgnat_ip(""))
        self.assertFalse(validate_tailscale_cgnat_ip(None))

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_tailscale_idempotency(self, mock_subproc, mock_ack):
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "CONNECTED: 100.80.175.55"
        mock_subproc.return_value.stderr = ""
        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "ts-idempotent-01",
            "mode": "on",
            "target_device_ids": [self.device_id],
        }

        # First execution
        handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertEqual(mock_subproc.call_count, 1)
        self.assertEqual(mock_ack.call_count, 1)

        # Second execution with same action_id
        handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        # Subprocess must NOT have been called again
        self.assertEqual(mock_subproc.call_count, 1)
        self.assertEqual(mock_ack.call_count, 2)
        self.assertEqual(mock_ack.call_args.kwargs["status"], "OPENED")
        self.assertEqual(mock_ack.call_args.kwargs["details"], "CONNECTED: 100.80.175.55")

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_tailscale_connect_rejects_octet_greater_than_255(self, mock_subproc, mock_ack):
        """Verify that an ACK with octet > 255 (e.g. 100.300.1.1) is rejected as FAILED."""
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "CONNECTED: 100.300.1.1\n"
        mock_subproc.return_value.stderr = ""
        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "ts-bad-octet-01",
            "mode": "on",
            "target_device_ids": [self.device_id],
        }

        handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertEqual(mock_ack.call_count, 1)
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["status"], "FAILED")
        self.assertFalse(kwargs["executed"])
        self.assertIsNone(kwargs["details"])
        self.assertIn("vpn_timeout_no_ip", kwargs["reason"])

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_tailscale_connect_rejects_4digit_octet_suffix_no_truncation(self, mock_subproc, mock_ack):
        """Verify that 100.1.2.2555 is NOT truncated to 100.1.2.255 and is rejected as FAILED."""
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "CONNECTED: 100.1.2.2555\n"
        mock_subproc.return_value.stderr = ""
        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "CONTROL_TAILSCALE",
            "action_id": "ts-suffix-trunc-01",
            "mode": "on",
            "target_device_ids": [self.device_id],
        }

        handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertEqual(mock_ack.call_count, 1)
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["status"], "FAILED")
        self.assertFalse(kwargs["executed"])
        self.assertIsNone(kwargs["details"])
        self.assertIn("vpn_timeout_no_ip", kwargs["reason"])

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_tailscale_connect_rejects_4digit_prefix_and_5_octets(self, mock_subproc, mock_ack):
        """Verify that 1100.1.2.3 and 100.1.2.3.4 are rejected as FAILED."""
        for malformed_stdout in ["CONNECTED: 1100.1.2.3\n", "CONNECTED: 100.1.2.3.4\n"]:
            mock_subproc.return_value.returncode = 0
            mock_subproc.return_value.stdout = malformed_stdout
            mock_subproc.return_value.stderr = ""
            mock_ack.reset_mock()
            state = {}
            message = {
                "protocol": "fleet-batch-v1",
                "action": "CONTROL_TAILSCALE",
                "action_id": f"ts-malformed-{abs(hash(malformed_stdout))}",
                "mode": "on",
                "target_device_ids": [self.device_id],
            }

            handle_incoming_batch_action(
                message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
            )
            self.assertEqual(mock_ack.call_count, 1)
            kwargs = mock_ack.call_args.kwargs
            self.assertEqual(kwargs["status"], "FAILED", f"Expected FAILED for {malformed_stdout.strip()}")
            self.assertFalse(kwargs["executed"])
            self.assertIsNone(kwargs["details"])
            self.assertIn("vpn_timeout_no_ip", kwargs["reason"])

    def test_ui_dismiss_keyevent_sent(self):
        on_cmd = build_tailscale_command("on")
        self.assertIn("input keyevent KEYCODE_BACK", on_cmd)
        self.assertIn("input keyevent KEYCODE_HOME", on_cmd)
        self.assertIn("1 2 3 4 5 6 7 8 9 10 11 12", on_cmd)
        self.assertNotIn("echo \"TRIGGERED\"", on_cmd)
        self.assertNotIn("uiautomator dump", on_cmd)
        self.assertNotIn("dumpsys input", on_cmd)
        self.assertNotIn("dumpsys window", on_cmd)

    def test_capabilities_includes_control_tailscale(self):
        from agent.agent import CAPABILITIES
        self.assertIn("control_tailscale", CAPABILITIES)


class TestMoveAccDeviceAgent(unittest.TestCase):
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

    def test_capabilities_includes_move_acc(self):
        from agent.agent import CAPABILITIES
        self.assertIn("move_acc", CAPABILITIES)

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.account_manager.move_accounts")
    def test_moveacc_success_dispatches_opened_ack(self, mock_move, mock_ack):
        mock_move.return_value = {
            "source_m": "M109",
            "target_m": "M77",
            "count": 1,
            "moved_accounts": ["MegaRegan426"],
            "source_remaining_count": 3,
            "target_current_count": 3,
            "backup_acc": "/fake/acc.txt.bak_20260914",
            "sync_result": {"acc_sync": True, "rule34_verified": True},
        }

        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "MOVE_ACC",
            "action_id": "moveacc-agent-01",
            "source_m": "m109",
            "target_m": "m77",
            "count": 1,
            "sync_drive": True,
            "target_device_ids": [self.device_id],
        }

        success = handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertTrue(success)
        mock_move.assert_called_once_with(
            "m109", "m77", count=1, base_dir=None, sync_drive=True
        )
        self.assertEqual(mock_ack.call_count, 1)
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["batch_action"], "MOVE_ACC")
        self.assertEqual(kwargs["status"], "OPENED")
        self.assertTrue(kwargs["executed"])
        self.assertIsNone(kwargs["reason"])
        details = json.loads(kwargs["details"])
        self.assertEqual(details["source_m"], "M109")
        self.assertEqual(details["target_m"], "M77")

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.account_manager.move_accounts")
    def test_moveacc_failure_dispatches_failed_ack(self, mock_move, mock_ack):
        mock_move.side_effect = ValueError("Dàn máy nguồn M109 chỉ có 1 tài khoản, không đủ 3 tài khoản để chuyển.")

        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "MOVE_ACC",
            "action_id": "moveacc-agent-fail-01",
            "source_m": "m109",
            "target_m": "m77",
            "count": 3,
            "sync_drive": True,
            "target_device_ids": [self.device_id],
        }

        success = handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertTrue(success)
        self.assertEqual(mock_ack.call_count, 1)
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["batch_action"], "MOVE_ACC")
        self.assertEqual(kwargs["status"], "FAILED")
        self.assertFalse(kwargs["executed"])
        self.assertIn("không đủ 3 tài khoản", kwargs["reason"])
        self.assertIsNone(kwargs["details"])

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.account_manager.move_accounts")
    def test_moveacc_idempotency_cached_response(self, mock_move, mock_ack):
        mock_move.return_value = {
            "source_m": "M109",
            "target_m": "M77",
            "count": 1,
            "moved_accounts": ["User1"],
            "source_remaining_count": 2,
            "target_current_count": 5,
        }

        state = {}
        message = {
            "protocol": "fleet-batch-v1",
            "action": "MOVE_ACC",
            "action_id": "moveacc-idemp-agent-01",
            "source_m": "m109",
            "target_m": "m77",
            "count": 1,
            "target_device_ids": [self.device_id],
        }

        # 1st invocation
        handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertEqual(mock_move.call_count, 1)

        # 2nd invocation (duplicate replay)
        mock_ack.reset_mock()
        handle_incoming_batch_action(
            message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertEqual(mock_move.call_count, 1, "move_accounts must not be called again on replay")
        self.assertEqual(mock_ack.call_count, 1)
        kwargs = mock_ack.call_args.kwargs
        self.assertEqual(kwargs["status"], "OPENED")
        self.assertTrue(kwargs["executed"])


if __name__ == "__main__":
    unittest.main()

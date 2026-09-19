#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Challenger 2 Adversarial Stress-Test Suite: Batch Action Idempotency & Replay Resilience.
Targets:
1. Agent-side CHECK_BAN command idempotency (Quota-Guard preservation, zero redundant pipeline executions).
2. Agent-side ADD_ACC command idempotency (zero redundant file appends, zero duplicate accounts).
3. Persistent agent state validation across repeated heartbeats and simulated restarts.
4. File-system level assertion on acc.txt and Data_Tong_Cookies.txt single-execution guarantee.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agent.agent import handle_incoming_batch_action, PROTOCOL_VERSION
import agent.account_manager as account_manager


class TestAdversarialAgentIdempotency(unittest.TestCase):
    """Adversarial stress-testing of agent-side batch action idempotency."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        self.state_file = self.base_path / ".phanserver_agent_state.json"
        self.links_file = self.base_path / "server_links.txt"
        self.links_file.write_text("test_link\n", encoding="utf-8")

        # Mock storage paths
        self.acc_file = self.base_path / "acc.txt"
        self.data_tong_file = self.base_path / "Data_Tong_Cookies.txt"
        self.acc_bi_ban_file = self.base_path / "acc_bi_ban.txt"
        self.nhat_ky_file = self.base_path / "nhat_ky_ban.txt"
        self.reserve_file = self.base_path / "acc_du_phong.txt"

        # Seed initial files
        self.acc_file.write_text(
            "M77___(gag2)\n"
            "ExistingUser1:Pass1\n"
            "ExistingUser2:Pass2\n",
            encoding="utf-8"
        )
        self.data_tong_file.write_text(
            "ExistingUser1:Pass1 | COOKIE_VAL_1\n"
            "ExistingUser2:Pass2 | COOKIE_VAL_2\n",
            encoding="utf-8"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("agent.agent.send_ack")
    @patch("agent.account_manager.run_full_checkban_pipeline")
    def test_checkban_heartbeat_replay_idempotency(self, mock_pipeline, mock_send_ack):
        """Verify repeated CHECK_BAN command deliveries execute pipeline exactly once."""
        mock_pipeline.return_value = {
            "target": "M77",
            "total": 2,
            "live": 2,
            "banned": 0,
            "error": 0,
            "banned_list": [],
            "cached": False
        }

        action_id = "checkban-test-replay-uuid-001"
        command_msg = {
            "type": "aot_batch_action",
            "protocol": PROTOCOL_VERSION,
            "action": "CHECK_BAN",
            "action_id": action_id,
            "target_device_ids": ["m72"],
            "target": "m77"
        }

        # Simulated state object loaded from state_file
        agent_state = {}

        # First delivery (HB 1)
        res1 = handle_incoming_batch_action(
            command_msg,
            device_id="m72",
            report_url="https://mock.worker/report",
            secret="test_secret",
            state=agent_state,
            state_path=self.state_file,
            links_path=self.links_file
        )
        self.assertTrue(res1)
        self.assertEqual(mock_pipeline.call_count, 1)
        self.assertEqual(mock_send_ack.call_count, 1)
        self.assertEqual(mock_send_ack.call_args_list[0].kwargs["batch_action"], "CHECK_BAN")
        self.assertEqual(mock_send_ack.call_args_list[0].kwargs["status"], "OPENED")

        # Second delivery (HB 2 replay before DO acknowledged or duplicate in-flight message)
        res2 = handle_incoming_batch_action(
            command_msg,
            device_id="m72",
            report_url="https://mock.worker/report",
            secret="test_secret",
            state=agent_state,
            state_path=self.state_file,
            links_path=self.links_file
        )
        self.assertTrue(res2)
        # CRITICAL ASSERTION: Pipeline must NOT be re-executed! Zero API quota wasted!
        self.assertEqual(mock_pipeline.call_count, 1, "Pipeline was re-executed on replay!")
        # ACK is re-sent from cached state
        self.assertEqual(mock_send_ack.call_count, 2)
        self.assertEqual(mock_send_ack.call_args_list[1].kwargs["batch_action"], "CHECK_BAN")

        # Third delivery (HB 3)
        res3 = handle_incoming_batch_action(
            command_msg,
            device_id="m72",
            report_url="https://mock.worker/report",
            secret="test_secret",
            state=agent_state,
            state_path=self.state_file,
            links_path=self.links_file
        )
        self.assertTrue(res3)
        self.assertEqual(mock_pipeline.call_count, 1, "Pipeline must remain called exactly once")

        # Verify state file on disk contains the cached result
        self.assertTrue(self.state_file.is_file())
        disk_state = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertIn("checkban_action_results", disk_state)
        self.assertIn(action_id, disk_state["checkban_action_results"])
        self.assertEqual(disk_state["checkban_action_results"][action_id]["status"], "OPENED")

    @patch("agent.agent.send_ack")
    @patch("agent.account_manager.sync_to_google_drive")
    def test_addacc_heartbeat_replay_idempotency_filesystem(self, mock_sync, mock_send_ack):
        """Verify repeated ADD_ACC command deliveries do NOT append duplicate lines to acc.txt."""
        mock_sync.return_value = {"acc_sync": True, "rule34_verified": True}

        action_id = "addacc-test-replay-uuid-002"
        command_msg = {
            "type": "aot_batch_action",
            "protocol": PROTOCOL_VERSION,
            "action": "ADD_ACC",
            "action_id": action_id,
            "target_device_ids": ["m72"],
            "m_code": "M77",
            "lines": ["NewPlayer_123:Pass123"],
            "sync_drive": True
        }

        # Override default paths to our temporary sandbox
        orig_get_default_paths = account_manager.get_default_paths

        def mock_paths(base_dir=None):
            return {
                "acc_file": str(self.acc_file),
                "data_tong_file": str(self.data_tong_file),
                "acc_bi_ban_file": str(self.acc_bi_ban_file),
                "nhat_ky_file": str(self.nhat_ky_file),
                "acc_du_phong_file": str(self.reserve_file),
                "base_dir": str(self.base_path),
            }

        account_manager.get_default_paths = mock_paths

        try:
            agent_state = {}

            # First delivery (HB 1)
            res1 = handle_incoming_batch_action(
                command_msg,
                device_id="m72",
                report_url="https://mock.worker/report",
                secret="test_secret",
                state=agent_state,
                state_path=self.state_file,
                links_path=self.links_file
            )
            self.assertTrue(res1)
            self.assertEqual(mock_send_ack.call_count, 1)

            # Read acc.txt after 1st execution
            content1 = self.acc_file.read_text(encoding="utf-8")
            self.assertEqual(content1.count("NewPlayer_123:Pass123"), 1, "New account should appear exactly once")

            # Second delivery (HB 2 duplicate replay)
            res2 = handle_incoming_batch_action(
                command_msg,
                device_id="m72",
                report_url="https://mock.worker/report",
                secret="test_secret",
                state=agent_state,
                state_path=self.state_file,
                links_path=self.links_file
            )
            self.assertTrue(res2)
            self.assertEqual(mock_send_ack.call_count, 2)

            # Read acc.txt after 2nd execution -> MUST STILL BE EXACTLY 1!
            content2 = self.acc_file.read_text(encoding="utf-8")
            self.assertEqual(content2.count("NewPlayer_123:Pass123"), 1, "Duplicate replay created duplicated accounts in acc.txt!")

            # Third delivery (HB 3)
            res3 = handle_incoming_batch_action(
                command_msg,
                device_id="m72",
                report_url="https://mock.worker/report",
                secret="test_secret",
                state=agent_state,
                state_path=self.state_file,
                links_path=self.links_file
            )
            self.assertTrue(res3)
            content3 = self.acc_file.read_text(encoding="utf-8")
            self.assertEqual(content3.count("NewPlayer_123:Pass123"), 1)

        finally:
            account_manager.get_default_paths = orig_get_default_paths

    @patch("agent.agent.send_ack")
    @patch("agent.account_manager.run_full_checkban_pipeline")
    def test_state_persistence_across_process_restart(self, mock_pipeline, mock_send_ack):
        """Verify cached actions survive agent process restart via disk state file."""
        mock_pipeline.return_value = {"total": 5, "live": 5, "banned": 0}
        action_id = "checkban-restart-uuid-003"
        command_msg = {
            "type": "aot_batch_action",
            "protocol": PROTOCOL_VERSION,
            "action": "CHECK_BAN",
            "action_id": action_id,
            "target_device_ids": ["m72"],
            "target": "m77"
        }

        # Process 1: Executes command and writes state to disk
        state_proc1 = {}
        handle_incoming_batch_action(
            command_msg,
            device_id="m72",
            report_url="https://mock.worker/report",
            secret="test_secret",
            state=state_proc1,
            state_path=self.state_file,
            links_path=self.links_file
        )
        self.assertEqual(mock_pipeline.call_count, 1)

        # Process 2: Simulates newly spawned agent process reading state_file from disk
        self.assertTrue(self.state_file.is_file())
        state_proc2 = json.loads(self.state_file.read_text(encoding="utf-8"))

        # Replay command in Process 2
        handle_incoming_batch_action(
            command_msg,
            device_id="m72",
            report_url="https://mock.worker/report",
            secret="test_secret",
            state=state_proc2,
            state_path=self.state_file,
            links_path=self.links_file
        )
        # CRITICAL ASSERTION: Even in fresh process, mock_pipeline is NOT called again!
        self.assertEqual(mock_pipeline.call_count, 1, "Pipeline was executed in restarted process instead of using disk cache!")


if __name__ == "__main__":
    unittest.main(verbosity=2)

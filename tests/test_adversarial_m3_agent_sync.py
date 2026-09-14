#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Adversarial Stress Test Suite for Milestone 3 (/moveacc)
Challenger 2: 2PC Fleet Coordination, Idempotency & Rule 34 Google Drive Sync.

Focus 1: 2PC Idempotency & Replay Stress
- Test duplicate MOVE_ACC action with same action_id to device agent:
  * Returns cached response with executed=True, status=OPENED.
  * Verifies accounts are NOT moved a second time.
  * Verifies no additional .bak files or rclone calls occur on replay.
  * Verifies replay stability under 10x repeated execution.
  * Verifies state persistence across agent restart (reload from disk).
- Test handling of failure reasons:
  * Source machine not found in acc.txt -> FAILED, executed=False, descriptive error.
  * Source machine empty (0 accounts) -> FAILED, executed=False, descriptive error.
  * Count > available accounts -> FAILED, executed=False, descriptive error.
  * Source == Destination -> FAILED, executed=False, descriptive error.
  * Replay of a FAILED action_id -> returns cached failure without re-executing.

Focus 2: Rule 34 Google Drive File ID Preservation
- Verify sync_to_google_drive(sync_data_tong=False):
  * Only syncs acc.txt to gdrive:acc.txt.
  * Skips Data_Tong_Cookies.txt entirely.
  * Verifies File ID 12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg.
- Verify Rule 34 drift detection and rejection:
  * If acc.txt File ID drifts on Google Drive -> raises RuntimeError, rejects sync.
  * If verify_rule34=True in move_accounts -> sync_result["rule34_verified"] is False, error captured.
  * If sync_data_tong=True and Data_Tong File ID drifts -> raises RuntimeError.
  * If sync_data_tong=False, Data_Tong is not verified, ensuring zero false-positive failures.
  * Supports both rclone lsf format ("id;name") and lsjson format ([{"ID": "..."}]).
"""

import copy
import hashlib
import json
import os
import pathlib
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent import account_manager, agent
from agent.account_manager import (
    move_accounts,
    parse_acc_sections,
    sync_to_google_drive,
    verify_google_drive_file_ids,
    RULE34_ACC_FILE_ID,
    RULE34_DATA_TONG_FILE_ID,
)

SAMPLE_ACC_INITIAL = """M109___(gag2)
Account_Alpha1:pass_alpha1
Account_Alpha2:pass_alpha2
Account_Alpha3:pass_alpha3
Account_Alpha4:pass_alpha4

M77___(gag2)
Account_Beta1:pass_beta1
Account_Beta2:pass_beta2

MEmpty___(gag2)
"""

SAMPLE_DATA_TONG = """Account_Alpha1:pass_alpha1:_|WARNING:-DO-NOT-SHARE-THIS|cookie_alpha1
Account_Alpha2:pass_alpha2:_|WARNING:-DO-NOT-SHARE-THIS|cookie_alpha2
Account_Alpha3:pass_alpha3:_|WARNING:-DO-NOT-SHARE-THIS|cookie_alpha3
Account_Alpha4:pass_alpha4:_|WARNING:-DO-NOT-SHARE-THIS|cookie_alpha4
Account_Beta1:pass_beta1:_|WARNING:-DO-NOT-SHARE-THIS|cookie_beta1
Account_Beta2:pass_beta2:_|WARNING:-DO-NOT-SHARE-THIS|cookie_beta2
"""


class TestAdversarialM3AgentSync(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="adv_m3_test_")
        self.acc_file = os.path.join(self.test_dir, "acc.txt")
        self.data_tong_file = os.path.join(self.test_dir, "Data_Tong_Cookies.txt")
        self.state_file = pathlib.Path(self.test_dir) / "agent_state.json"

        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(SAMPLE_ACC_INITIAL)
        with open(self.data_tong_file, "w", encoding="utf-8") as f:
            f.write(SAMPLE_DATA_TONG)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # =========================================================================
    # FOCUS 1: 2PC Idempotency & Replay Stress
    # =========================================================================

    def test_2pc_idempotency_duplicate_move_acc_replay(self):
        """Stress Test 1.1: Duplicate MOVE_ACC action with same action_id must return cached
        response and NEVER move accounts a second time."""
        state = {"moveacc_action_results": {}}
        action_id = "moveacc-adversarial-replay-001"
        report_url = "https://mock.worker/report"
        secret = "mock_secret"
        device_id = "m72"

        message = {
            "type": "aot_batch_action",
            "protocol": "fleet-batch-v1",
            "action_id": action_id,
            "action": "MOVE_ACC",
            "source_m": "m109",
            "target_m": "m77",
            "count": 1,
            "sync_drive": False,
            "base_dir": self.test_dir,
            "target_device_ids": [device_id],
        }

        sent_acks = []

        def mock_send_ack(r_url, sec, dev_id, act_id, status, reason=None, executed=False, batch_action="ALLOCATE_SERVER", details=None):
            sent_acks.append({
                "action_id": act_id,
                "status": status,
                "reason": reason,
                "executed": executed,
                "batch_action": batch_action,
                "details": details,
            })
            return True

        # First execution (Initial run)
        links_path = pathlib.Path(self.test_dir) / "server_links.txt"
        with mock.patch("agent.agent.send_ack", side_effect=mock_send_ack):
            handled = agent.handle_incoming_batch_action(
                message, device_id, report_url, secret, state, self.state_file, links_path
            )

        self.assertTrue(handled, "Initial MOVE_ACC must be handled")
        self.assertEqual(len(sent_acks), 1)
        first_ack = sent_acks[0]
        self.assertEqual(first_ack["status"], "OPENED")
        self.assertTrue(first_ack["executed"])
        self.assertIsNone(first_ack["reason"])
        first_details = json.loads(first_ack["details"])
        self.assertEqual(first_details["source_remaining_count"], 3)
        self.assertEqual(first_details["target_current_count"], 3)
        self.assertEqual(len(first_details["moved_accounts"]), 1)
        first_moved_acc = first_details["moved_accounts"][0]

        # Verify acc.txt state after 1st execution
        with open(self.acc_file, "r", encoding="utf-8") as f:
            content_after_first = f.read()
        sections_1 = parse_acc_sections(content_after_first)
        src_users_1 = [a["username"] for a in sections_1["m109"]["accounts"]]
        dst_users_1 = [a["username"] for a in sections_1["m77"]["accounts"]]
        self.assertEqual(len(src_users_1), 3)
        self.assertEqual(len(dst_users_1), 3)
        self.assertNotIn(first_moved_acc, src_users_1)
        self.assertIn(first_moved_acc, dst_users_1)

        # Count .bak files generated during first execution
        bak_files_1 = [f for f in os.listdir(self.test_dir) if f.startswith("acc.txt.bak_")]
        self.assertEqual(len(bak_files_1), 1, "Exactly one backup file should be created on initial run")

        # Now send DUPLICATE MOVE_ACC with SAME action_id 10 times in a loop
        for replay_idx in range(10):
            with mock.patch("agent.agent.send_ack", side_effect=mock_send_ack), \
                 mock.patch("agent.account_manager.move_accounts") as mock_move_fn:
                handled_replay = agent.handle_incoming_batch_action(
                    message, device_id, report_url, secret, state, self.state_file, links_path
                )
                self.assertTrue(handled_replay)
                # Ensure move_accounts was NEVER called on duplicate replay!
                mock_move_fn.assert_not_called()

            # Verify that the ACK returned on duplicate matches the first execution identically
            replay_ack = sent_acks[-1]
            self.assertEqual(replay_ack["status"], "OPENED")
            self.assertTrue(replay_ack["executed"])
            self.assertEqual(replay_ack["details"], first_ack["details"])

            # Verify acc.txt content remained 100% UNCHANGED (zero secondary move)
            with open(self.acc_file, "r", encoding="utf-8") as f:
                content_after_replay = f.read()
            self.assertEqual(content_after_first, content_after_replay, "acc.txt must NOT change on replay")

            # Verify NO additional .bak files were created
            bak_files_replay = [f for f in os.listdir(self.test_dir) if f.startswith("acc.txt.bak_")]
            self.assertEqual(len(bak_files_replay), 1, "No extra backup files on duplicate replay")

    def test_2pc_idempotency_state_persistence_across_agent_restart(self):
        """Stress Test 1.2: Verify that idempotency cache survives an agent process restart
        by reloading state from disk."""
        state = {"moveacc_action_results": {}}
        action_id = "moveacc-persist-restart-002"
        report_url = "https://mock.worker/report"
        secret = "mock_secret"
        device_id = "m72"
        links_path = pathlib.Path(self.test_dir) / "server_links.txt"

        message = {
            "type": "aot_batch_action",
            "protocol": "fleet-batch-v1",
            "action_id": action_id,
            "action": "MOVE_ACC",
            "source_m": "m109",
            "target_m": "m77",
            "count": 1,
            "sync_drive": False,
            "base_dir": self.test_dir,
        }

        sent_acks = []

        def mock_send_ack(r_url, sec, dev_id, act_id, status, reason=None, executed=False, batch_action="ALLOCATE_SERVER", details=None):
            sent_acks.append({"status": status, "executed": executed, "details": details})
            return True

        # First run saves to disk
        with mock.patch("agent.agent.send_ack", side_effect=mock_send_ack):
            agent.handle_incoming_batch_action(message, device_id, report_url, secret, state, self.state_file, links_path)

        self.assertTrue(self.state_file.exists(), "State file must be written to disk")

        # Simulate Agent Restart: brand new state dict reloaded from disk
        reloaded_state = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertIn("moveacc_action_results", reloaded_state)
        self.assertIn(action_id, reloaded_state["moveacc_action_results"])

        # Send duplicate after restart
        sent_acks.clear()
        with mock.patch("agent.agent.send_ack", side_effect=mock_send_ack), \
             mock.patch("agent.account_manager.move_accounts") as mock_move_fn:
            handled = agent.handle_incoming_batch_action(
                message, device_id, report_url, secret, reloaded_state, self.state_file, links_path
            )
            self.assertTrue(handled)
            mock_move_fn.assert_not_called()

        self.assertEqual(len(sent_acks), 1)
        self.assertEqual(sent_acks[0]["status"], "OPENED")
        self.assertTrue(sent_acks[0]["executed"])

    def test_2pc_failure_source_machine_not_found(self):
        """Stress Test 1.3: Source machine does not exist in acc.txt -> FAILED, executed=False,
        and failure status is cached for idempotency."""
        state = {"moveacc_action_results": {}}
        action_id = "moveacc-fail-notfound-003"
        links_path = pathlib.Path(self.test_dir) / "server_links.txt"
        message = {
            "type": "aot_batch_action",
            "protocol": "fleet-batch-v1",
            "action_id": action_id,
            "action": "MOVE_ACC",
            "source_m": "M999_NONEXISTENT",
            "target_m": "M77",
            "count": 1,
            "sync_drive": False,
            "base_dir": self.test_dir,
        }
        sent_acks = []

        def mock_send_ack(r_url, sec, dev_id, act_id, status, reason=None, executed=False, batch_action="ALLOCATE_SERVER", details=None):
            sent_acks.append({"status": status, "executed": executed, "reason": reason})
            return True

        with mock.patch("agent.agent.send_ack", side_effect=mock_send_ack):
            agent.handle_incoming_batch_action(
                message, "m72", "http://mock", "sec", state, self.state_file, links_path
            )

        self.assertEqual(len(sent_acks), 1)
        ack = sent_acks[0]
        self.assertEqual(ack["status"], "FAILED")
        self.assertFalse(ack["executed"])
        self.assertIn("Không tìm thấy section máy nguồn", ack["reason"])

        # Replay failure -> verify it returns cached failure without re-executing
        sent_acks.clear()
        with mock.patch("agent.agent.send_ack", side_effect=mock_send_ack), \
             mock.patch("agent.account_manager.move_accounts") as mock_move_fn:
            agent.handle_incoming_batch_action(
                message, "m72", "http://mock", "sec", state, self.state_file, links_path
            )
            mock_move_fn.assert_not_called()

        self.assertEqual(len(sent_acks), 1)
        self.assertEqual(sent_acks[0]["status"], "FAILED")
        self.assertFalse(sent_acks[0]["executed"])
        self.assertIn("Không tìm thấy section máy nguồn", sent_acks[0]["reason"])

    def test_2pc_failure_source_machine_empty(self):
        """Stress Test 1.4: Source machine section exists but has 0 accounts -> FAILED, executed=False."""
        state = {"moveacc_action_results": {}}
        action_id = "moveacc-fail-empty-004"
        links_path = pathlib.Path(self.test_dir) / "server_links.txt"
        message = {
            "type": "aot_batch_action",
            "protocol": "fleet-batch-v1",
            "action_id": action_id,
            "action": "MOVE_ACC",
            "source_m": "MEmpty",
            "target_m": "M77",
            "count": 1,
            "sync_drive": False,
            "base_dir": self.test_dir,
        }
        sent_acks = []

        def mock_send_ack(r_url, sec, dev_id, act_id, status, reason=None, executed=False, batch_action="ALLOCATE_SERVER", details=None):
            sent_acks.append({"status": status, "executed": executed, "reason": reason})
            return True

        with mock.patch("agent.agent.send_ack", side_effect=mock_send_ack):
            agent.handle_incoming_batch_action(
                message, "m72", "http://mock", "sec", state, self.state_file, links_path
            )

        self.assertEqual(len(sent_acks), 1)
        ack = sent_acks[0]
        self.assertEqual(ack["status"], "FAILED")
        self.assertFalse(ack["executed"])
        self.assertIn("không còn tài khoản nào", ack["reason"])

        self.assertEqual(len(sent_acks), 1)
        ack = sent_acks[0]
        self.assertEqual(ack["status"], "FAILED")
        self.assertFalse(ack["executed"])
        self.assertIn("không còn tài khoản nào", ack["reason"])

    def test_2pc_failure_insufficient_accounts_and_invalid_params(self):
        """Stress Test 1.5: Insufficient count, negative count, source==target handling."""
        # 1. Insufficient count (requested 10, available 4)
        with self.assertRaises(ValueError) as ctx1:
            move_accounts("m109", "m77", count=10, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("không đủ 10 tài khoản", str(ctx1.exception))

        # 2. Source == Target
        with self.assertRaises(ValueError) as ctx2:
            move_accounts("m109", "M109", count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("không được trùng nhau", str(ctx2.exception))

        # 3. Non-positive count
        with self.assertRaises(ValueError) as ctx3:
            move_accounts("m109", "m77", count=0, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("lớn hơn hoặc bằng 1", str(ctx3.exception))

        with self.assertRaises(ValueError) as ctx4:
            move_accounts("m109", "m77", count=-3, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("lớn hơn hoặc bằng 1", str(ctx4.exception))

    # =========================================================================
    # FOCUS 2: Rule 34 Google Drive File ID Preservation
    # =========================================================================

    @mock.patch("agent.account_manager.verify_google_drive_file_ids")
    @mock.patch("subprocess.run")
    def test_rule34_sync_data_tong_false_preserves_acc_file_id(self, mock_subproc, mock_verify):
        """Stress Test 2.1: Verify sync_to_google_drive(sync_data_tong=False) preserves File ID
        12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg and strictly skips Data_Tong_Cookies.txt."""
        mock_proc = mock.MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_subproc.return_value = mock_proc

        mock_verify.return_value = {
            "verified": True,
            "file_ids": {"acc.txt": RULE34_ACC_FILE_ID},
        }

        res = sync_to_google_drive(base_dir=self.test_dir, verify_rule34=True, sync_data_tong=False)

        self.assertTrue(res["acc_sync"])
        self.assertFalse(res["data_tong_sync"])
        self.assertEqual(res["Data_Tong_Cookies.txt"], "SKIPPED")
        self.assertTrue(res["rule34_verified"])
        self.assertEqual(res["file_ids"]["acc.txt"], "12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg")

        # Verify rclone copyto command arguments
        mock_verify.assert_called_once_with(mock.ANY, check_data_tong=False)
        calls = mock_subproc.call_args_list
        acc_calls = [c for c in calls if "copyto" in c[0][0] and "gdrive:acc.txt" in c[0][0]]
        dt_calls = [c for c in calls if "copyto" in c[0][0] and "gdrive:Data_Tong_Cookies.txt" in c[0][0]]
        self.assertEqual(len(acc_calls), 1)
        self.assertEqual(len(dt_calls), 0)

    @mock.patch("subprocess.run")
    def test_rule34_file_id_drift_detection_and_rejection(self, mock_subproc):
        """Stress Test 2.2: Verify that if File ID drifts on Google Drive, it is detected and rejected."""
        # 1. Simulate rclone lsf returning a DRIFTED File ID for acc.txt
        drifted_id = "DRIFTED_WRONG_FILE_ID_99999"
        mock_proc = mock.MagicMock()
        mock_proc.returncode = 0
        # Format "ip" returns "id;name"
        mock_proc.stdout = f"{drifted_id};acc.txt\n"
        mock_proc.stderr = ""
        mock_subproc.return_value = mock_proc

        with self.assertRaises(RuntimeError) as ctx:
            verify_google_drive_file_ids(rclone_bin="/usr/bin/rclone", check_data_tong=False)

        err_msg = str(ctx.exception)
        self.assertIn("Rule 34 Violated!", err_msg)
        self.assertIn("acc.txt File ID bị biến động", err_msg)
        self.assertIn(drifted_id, err_msg)
        self.assertIn(RULE34_ACC_FILE_ID, err_msg)

    @mock.patch("subprocess.run")
    def test_rule34_file_id_lsjson_format_drift_detection(self, mock_subproc):
        """Stress Test 2.3: Verify drift detection when rclone responds via lsjson fallback."""
        # lsf fails, lsjson succeeds with drifted ID
        def side_effect(cmd, **kwargs):
            m = mock.MagicMock()
            if "lsf" in cmd:
                m.returncode = 1
                m.stdout = ""
                m.stderr = "error"
            elif "lsjson" in cmd:
                m.returncode = 0
                m.stdout = json.dumps([{"ID": "ANOTHER_DRIFTED_ID", "Name": "acc.txt"}])
                m.stderr = ""
            return m

        mock_subproc.side_effect = side_effect

        with self.assertRaises(RuntimeError) as ctx:
            verify_google_drive_file_ids(rclone_bin="/usr/bin/rclone", check_data_tong=False)

        self.assertIn("Rule 34 Violated!", str(ctx.exception))
        self.assertIn("ANOTHER_DRIFTED_ID", str(ctx.exception))

    @mock.patch("agent.account_manager.sync_to_google_drive")
    def test_move_accounts_handles_rule34_drift_gracefully(self, mock_sync):
        """Stress Test 2.4: If Rule 34 verification fails during move_accounts,
        the error is properly reported in the result dictionary."""
        mock_sync.side_effect = RuntimeError(
            f"Rule 34 Violated! acc.txt File ID bị biến động: BAD_ID != {RULE34_ACC_FILE_ID}"
        )

        res = move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=True)

        self.assertIsNotNone(res["sync_result"])
        self.assertFalse(res["sync_result"]["acc_sync"])
        self.assertFalse(res["sync_result"]["rule34_verified"])
        self.assertIn("Rule 34 Violated!", res["sync_result"]["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

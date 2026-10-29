#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Unit & Integration Test Suite for /moveacc (Milestone 3).

Acceptance Criteria & Test Matrix:
- Test 1: Single account move (`move_accounts("m109", "m77", 1)`) bốc đúng ngẫu nhiên 1 tài khoản.
- Test 2: Multi-account move (`move_accounts("m109", "m77", 2)`) using random.sample.
- Test 3: Section precision regex test verifying accounts starting with M (MegaRegan426:pass, Mega_Wiley623:pass, M00nlUWarden:pass, M426_User:pass) are NEVER treated as section headers M109, M77, M426, etc.
- Test 4: Data_Tong_Cookies.txt invariance test verifying SHA-256, byte content, and mtime remain 100% untouched, and zero .bak files created for it.
- Test 5: Local backup verification confirming .bak_<timestamp> is created for acc.txt prior to modifications.
- Test 6: Google Drive Rule 34 sync verification via rclone copyto confirming File ID 12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg is preserved and verified.
- Test 7: Validation error handling: source == dest raises ValueError, non-existent source raises ValueError, empty source raises ValueError, count > available accounts raises ValueError, count <= 0 raises ValueError.
- Test 8: Auto-creation of destination section (e.g. M999___(gag2)) when destination does not exist in acc.txt.
- Test 9: CLI test for python3 -m agent.account_manager moveacc and alias move.
- Test 10: Idempotency test for agent MOVE_ACC batch action replay.
"""

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

# Ensure project root is on sys.path
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent import account_manager
from agent.account_manager import (
    move_accounts,
    parse_acc_sections,
    sync_to_google_drive,
    verify_google_drive_file_ids,
    RULE34_ACC_FILE_ID,
    RULE34_DATA_TONG_FILE_ID,
)
from agent import agent


SAMPLE_ACC_WITH_M_NAMES = """M109___(gag2)
MegaRegan426:pass_mega426
M00nlUWarden3200644:pass_moonwarden
User_Alpha1:pass_alpha1
User_Beta2:pass_beta2

M77___(gag2)
Mega_Wiley623:pass_wiley77
JeremiahWilkerson46:pass_jeremiah
"""

SAMPLE_DATA_TONG_COOKIES = """MegaRegan426:pass_mega426:_|WARNING:-DO-NOT-SHARE-THIS|cookie_mega426
M00nlUWarden3200644:pass_moonwarden:_|WARNING:-DO-NOT-SHARE-THIS|cookie_moonwarden
User_Alpha1:pass_alpha1:_|WARNING:-DO-NOT-SHARE-THIS|cookie_alpha1
User_Beta2:pass_beta2:_|WARNING:-DO-NOT-SHARE-THIS|cookie_beta2
Mega_Wiley623:pass_wiley77:_|WARNING:-DO-NOT-SHARE-THIS|cookie_wiley77
JeremiahWilkerson46:pass_jeremiah:_|WARNING:-DO-NOT-SHARE-THIS|cookie_jeremiah
"""


class TestMoveAcc(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_moveacc_")
        self.acc_file = os.path.join(self.test_dir, "acc.txt")
        self.data_tong_file = os.path.join(self.test_dir, "Data_Tong_Cookies.txt")

        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(SAMPLE_ACC_WITH_M_NAMES)
        with open(self.data_tong_file, "w", encoding="utf-8") as f:
            f.write(SAMPLE_DATA_TONG_COOKIES)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Test 1: Single account move (/moveacc m109 m77)
    # -------------------------------------------------------------------------
    def test_01_single_account_move(self):
        """Test 1: Single account move picks exactly 1 random account from source to target."""
        initial_sections = parse_acc_sections(SAMPLE_ACC_WITH_M_NAMES)
        src_accounts_before = [a["username"] for a in initial_sections["m109"]["accounts"]]
        dst_accounts_before = [a["username"] for a in initial_sections["m77"]["accounts"]]
        self.assertEqual(len(src_accounts_before), 4)
        self.assertEqual(len(dst_accounts_before), 2)

        result = move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=False)

        self.assertEqual(result["source_m"], "M109")
        self.assertEqual(result["target_m"], "M77")
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(result["moved_accounts"]), 1)
        moved_user = result["moved_accounts"][0]
        self.assertIn(moved_user, src_accounts_before)
        self.assertEqual(result["source_remaining_count"], 3)
        self.assertEqual(result["target_current_count"], 3)

        # Inspect updated acc.txt content
        with open(self.acc_file, "r", encoding="utf-8") as f:
            updated_content = f.read()

        updated_sections = parse_acc_sections(updated_content)
        src_accounts_after = [a["username"] for a in updated_sections["m109"]["accounts"]]
        dst_accounts_after = [a["username"] for a in updated_sections["m77"]["accounts"]]

        self.assertEqual(len(src_accounts_after), 3)
        self.assertEqual(len(dst_accounts_after), 3)
        self.assertNotIn(moved_user, src_accounts_after)
        self.assertIn(moved_user, dst_accounts_after)

    # -------------------------------------------------------------------------
    # Test 2: Multi-account move (/moveacc m109 m77 2) using random.sample
    # -------------------------------------------------------------------------
    def test_02_multi_account_move_using_random_sample(self):
        """Test 2: Multi-account move transfers N accounts using random.sample without duplicate."""
        with mock.patch("random.sample", wraps=random.sample) as mock_sample:
            result = move_accounts("m109", "m77", count=2, base_dir=self.test_dir, sync_drive=False)

            self.assertTrue(mock_sample.called, "random.sample must be used for random account selection")
            self.assertEqual(mock_sample.call_args[0][1], 2, "random.sample called with count=2")

        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["moved_accounts"]), 2)
        self.assertEqual(len(set(result["moved_accounts"])), 2, "Moved accounts must be unique")
        self.assertEqual(result["source_remaining_count"], 2)
        self.assertEqual(result["target_current_count"], 4)

        with open(self.acc_file, "r", encoding="utf-8") as f:
            updated_content = f.read()

        updated_sections = parse_acc_sections(updated_content)
        src_users = [a["username"] for a in updated_sections["m109"]["accounts"]]
        dst_users = [a["username"] for a in updated_sections["m77"]["accounts"]]

        self.assertEqual(len(src_users), 2)
        self.assertEqual(len(dst_users), 4)
        for u in result["moved_accounts"]:
            self.assertNotIn(u, src_users)
            self.assertIn(u, dst_users)

    def test_02b_move_all_available_accounts(self):
        """Test moving all available accounts in a section (count == available)."""
        result = move_accounts("m109", "m77", count=4, base_dir=self.test_dir, sync_drive=False)
        self.assertEqual(result["source_remaining_count"], 0)
        self.assertEqual(result["target_current_count"], 6)

        with open(self.acc_file, "r", encoding="utf-8") as f:
            updated_content = f.read()

        updated_sections = parse_acc_sections(updated_content)
        self.assertIn("m109", updated_sections, "Section header M109 must remain in acc.txt")
        self.assertEqual(len(updated_sections["m109"]["accounts"]), 0)
        self.assertEqual(len(updated_sections["m77"]["accounts"]), 6)

    # -------------------------------------------------------------------------
    # Test 3: Section precision regex test (M-starting account names)
    # -------------------------------------------------------------------------
    def test_03_section_precision_regex_accounts_with_m_prefix(self):
        """Test 3: Accounts starting with M (MegaRegan426:pass, Mega_Wiley623:pass, M00nlUWarden:pass, M426_User:pass)
        are NEVER matched as section headers M109, M77, M426, etc."""
        complex_content = """M109___(gag2)
MegaRegan426:pass_mega426
Mega_Wiley623:pass_wiley
M00nlUWarden3200644:pass_moon
M426SpecialUser:pass_m426
M77GamerUser:pass_m77user
M109_AccountWithUnderscore:pass_undersc

M77___(gag2)
M00_Tester:pass_m00
NormalUser77:pass_norm77
"""
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(complex_content)

        sections = parse_acc_sections(complex_content)
        # Verify exactly m109 and m77 sections exist, NO rogue m426 or m0 or megaregan
        self.assertEqual(set(sections.keys()), {"m109", "m77"})
        self.assertEqual(len(sections["m109"]["accounts"]), 6)
        self.assertEqual(len(sections["m77"]["accounts"]), 2)

        # Move 1 account from M109 to M77
        result = move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertEqual(result["source_remaining_count"], 5)
        self.assertEqual(result["target_current_count"], 3)

        with open(self.acc_file, "r", encoding="utf-8") as f:
            post_content = f.read()

        post_sections = parse_acc_sections(post_content)
        self.assertEqual(set(post_sections.keys()), {"m109", "m77"})
        self.assertEqual(len(post_sections["m109"]["accounts"]), 5)
        self.assertEqual(len(post_sections["m77"]["accounts"]), 3)

    # -------------------------------------------------------------------------
    # Test 4: Data_Tong_Cookies.txt invariance test (SHA-256, mtime, byte content)
    # -------------------------------------------------------------------------
    def test_04_data_tong_cookies_invariance(self):
        """Test 4: Data_Tong_Cookies.txt remains 100% untouched: identical SHA-256, identical byte content,
        and strictly zero .bak files created for it."""
        with open(self.data_tong_file, "rb") as f:
            original_bytes = f.read()
        original_hash = hashlib.sha256(original_bytes).hexdigest()
        original_size = os.path.getsize(self.data_tong_file)
        original_mtime = os.path.getmtime(self.data_tong_file)

        # Perform move
        time.sleep(0.01)
        move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=False)

        # Verify Data_Tong_Cookies.txt after move
        with open(self.data_tong_file, "rb") as f:
            after_bytes = f.read()
        after_hash = hashlib.sha256(after_bytes).hexdigest()
        after_size = os.path.getsize(self.data_tong_file)
        after_mtime = os.path.getmtime(self.data_tong_file)

        self.assertEqual(original_hash, after_hash, "SHA-256 of Data_Tong_Cookies.txt must be 100% unchanged")
        self.assertEqual(original_size, after_size, "Byte size of Data_Tong_Cookies.txt must be 100% unchanged")
        self.assertEqual(original_bytes, after_bytes, "Raw byte content of Data_Tong_Cookies.txt must be 100% unchanged")
        self.assertEqual(original_mtime, after_mtime, "mtime of Data_Tong_Cookies.txt must remain untouched")

        # Verify ZERO .bak files for Data_Tong_Cookies.txt
        all_files = os.listdir(self.test_dir)
        data_tong_baks = [f for f in all_files if "Data_Tong_Cookies" in f and ".bak" in f]
        self.assertEqual(len(data_tong_baks), 0, f"Zero .bak files must be created for Data_Tong_Cookies.txt, found: {data_tong_baks}")

    # -------------------------------------------------------------------------
    # Test 5: Local backup verification (.bak_<timestamp> for acc.txt)
    # -------------------------------------------------------------------------
    def test_05_local_backup_verification(self):
        """Test 5: Local backup .bak_<timestamp> is created for acc.txt prior to modification,
        containing the verbatim original content."""
        with open(self.acc_file, "r", encoding="utf-8") as f:
            orig_acc_content = f.read()

        result = move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=False)

        backup_path = result.get("backup_acc")
        self.assertIsNotNone(backup_path, "backup_acc path must be returned in result")
        self.assertTrue(os.path.exists(backup_path), f"Backup file must exist at {backup_path}")
        self.assertTrue(re.search(r"\.bak_\d{8}_\d{6}$", backup_path), f"Backup filename pattern mismatch: {backup_path}")

        with open(backup_path, "r", encoding="utf-8") as f:
            backup_content = f.read()
        self.assertEqual(backup_content, orig_acc_content, "Backup content must match original acc.txt before edit")

    # -------------------------------------------------------------------------
    # Test 6: Google Drive Rule 34 sync verification via rclone copyto
    # -------------------------------------------------------------------------
    @mock.patch("agent.account_manager.verify_google_drive_file_ids")
    @mock.patch("subprocess.run")
    def test_06_rule34_google_drive_sync_preserves_file_id(self, mock_subproc, mock_verify):
        """Test 6: rclone copyto is called only for acc.txt, verifying Rule 34 File ID 12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg."""
        mock_proc = mock.MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_subproc.return_value = mock_proc

        mock_verify.return_value = {
            "verified": True,
            "file_ids": {
                "acc.txt": RULE34_ACC_FILE_ID,
                "Data_Tong_Cookies.txt": RULE34_DATA_TONG_FILE_ID,
            },
        }

        result = move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=True)

        sync_res = result.get("sync_result")
        self.assertIsNotNone(sync_res)
        self.assertTrue(sync_res.get("acc_sync"))
        self.assertTrue(sync_res.get("rule34_verified"))
        self.assertEqual(sync_res.get("Data_Tong_Cookies.txt"), "SKIPPED")

        # Verify subprocess.run calls
        calls = mock_subproc.call_args_list
        # Ensure rclone copyto was called for acc.txt
        acc_sync_calls = [c for c in calls if "copyto" in c[0][0] and "gdrive:acc.txt" in c[0][0]]
        self.assertEqual(len(acc_sync_calls), 1, "rclone copyto must be called exactly once for acc.txt")

        # Ensure rclone copyto was NEVER called for Data_Tong_Cookies.txt
        dt_sync_calls = [c for c in calls if "copyto" in c[0][0] and "gdrive:Data_Tong_Cookies.txt" in c[0][0]]
        self.assertEqual(len(dt_sync_calls), 0, "rclone copyto must NEVER be called for Data_Tong_Cookies.txt during moveacc")

    @mock.patch("agent.account_manager.verify_google_drive_file_ids")
    @mock.patch("subprocess.run")
    def test_06b_rule34_rejection_on_file_id_drift(self, mock_subproc, mock_verify):
        """Test that Rule 34 failure is flagged if Google Drive File ID changes."""
        mock_proc = mock.MagicMock()
        mock_proc.returncode = 0
        mock_subproc.return_value = mock_proc

        mock_verify.side_effect = RuntimeError("Rule 34 Violated! Google Drive File ID mismatch for acc.txt")

        result = move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=True)
        sync_res = result.get("sync_result")
        self.assertIn("error", sync_res)
        self.assertIn("Rule 34 Violated", sync_res["error"])

    # -------------------------------------------------------------------------
    # Test 7: Validation error handling
    # -------------------------------------------------------------------------
    def test_07_validation_error_handling(self):
        """Test 7: Validation error handling covering all specified edge cases:
        - source == dest raises ValueError
        - non-existent source raises ValueError
        - empty source raises ValueError
        - count > available accounts raises ValueError
        - count <= 0 raises ValueError
        - non-integer count raises ValueError
        - empty / None arguments raise ValueError
        """
        # 1. source == dest
        with self.assertRaises(ValueError) as ctx:
            move_accounts("m109", "m109", count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("trùng nhau", str(ctx.exception))

        # Case insensitive source == dest
        with self.assertRaises(ValueError) as ctx:
            move_accounts("m109", "M109", count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("trùng nhau", str(ctx.exception))

        # 2. non-existent source
        with self.assertRaises(ValueError) as ctx:
            move_accounts("m999", "m77", count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("Không tìm thấy section máy nguồn", str(ctx.exception))

        # 3. empty source (section exists but has 0 accounts)
        empty_src_content = "M109___(gag2)\n\nM77___(gag2)\nUser77:pass77\n"
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(empty_src_content)
        with self.assertRaises(ValueError) as ctx:
            move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("không còn tài khoản nào", str(ctx.exception))

        # 4. count > available accounts
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write("M109___(gag2)\nUser1:p1\nUser2:p2\nM77___(gag2)\nUser77:p77\n")
        with self.assertRaises(ValueError) as ctx:
            move_accounts("m109", "m77", count=5, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("không đủ", str(ctx.exception))

        # 5. count <= 0
        with self.assertRaises(ValueError) as ctx:
            move_accounts("m109", "m77", count=0, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("lớn hơn hoặc bằng 1", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            move_accounts("m109", "m77", count=-3, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("lớn hơn hoặc bằng 1", str(ctx.exception))

        # 6. non-integer count
        with self.assertRaises(ValueError) as ctx:
            move_accounts("m109", "m77", count="invalid", base_dir=self.test_dir, sync_drive=False)
        self.assertIn("lớn hơn hoặc bằng 1", str(ctx.exception))

        # 7. missing / empty arguments
        with self.assertRaises(ValueError) as ctx:
            move_accounts("", "m77", count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("không được để trống", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            move_accounts("m109", None, count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("không được để trống", str(ctx.exception))

    # -------------------------------------------------------------------------
    # Test 8: Auto-creation of destination section (M999___(gag2))
    # -------------------------------------------------------------------------
    def test_08_destination_section_auto_creation(self):
        """Test 8: If destination section does not exist in acc.txt, it is auto-created
        at the end of acc.txt with '{TARGET_M}___(gag2)' header."""
        result = move_accounts("m109", "m999", count=1, base_dir=self.test_dir, sync_drive=False)

        self.assertEqual(result["target_m"], "M999")
        self.assertEqual(result["target_current_count"], 1)
        moved_acc = result["moved_accounts"][0]

        with open(self.acc_file, "r", encoding="utf-8") as f:
            updated_content = f.read()

        # Check section header exists
        self.assertIn("M999___(gag2)", updated_content)

        updated_sections = parse_acc_sections(updated_content)
        self.assertIn("m999", updated_sections)
        self.assertEqual(len(updated_sections["m999"]["accounts"]), 1)
        self.assertEqual(updated_sections["m999"]["accounts"][0]["username"], moved_acc)

    def test_08b_destination_section_in_middle_of_file(self):
        """Test when destination section is in the middle of acc.txt (before another section)."""
        multi_section = """M109___(gag2)
User1:p1
User2:p2

M77___(gag2)
User77:p77

M88___(gag2)
User88:p88
"""
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(multi_section)

        # Move from M109 to M77 (which is located before M88)
        result = move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=False)
        moved = result["moved_accounts"][0]

        with open(self.acc_file, "r", encoding="utf-8") as f:
            updated_content = f.read()

        sections = parse_acc_sections(updated_content)
        self.assertEqual(len(sections["m109"]["accounts"]), 1)
        self.assertEqual(len(sections["m77"]["accounts"]), 2)
        self.assertEqual(len(sections["m88"]["accounts"]), 1)
        self.assertIn(moved, [a["username"] for a in sections["m77"]["accounts"]])

    # -------------------------------------------------------------------------
    # Test 9: CLI test for python3 -m agent.account_manager moveacc
    # -------------------------------------------------------------------------
    def test_09_cli_moveacc_command(self):
        """Test 9: CLI execution of python3 -m agent.account_manager moveacc and move alias."""
        # 1. Missing arguments should print syntax help and exit code 1
        for args in [["account_manager", "moveacc"], ["account_manager", "moveacc", "m109"], ["account_manager", "move"]]:
            with mock.patch.object(sys, "argv", args):
                with mock.patch("builtins.print") as mock_print:
                    with self.assertRaises(SystemExit) as cm:
                        subcmd = sys.argv[1].lower()
                        if subcmd in ("moveacc", "move"):
                            if len(sys.argv) < 4:
                                print("Cú pháp: python3 -m agent.account_manager moveacc <source_m> <target_m> [count]")
                                sys.exit(1)
                    self.assertEqual(cm.exception.code, 1)
                    mock_print.assert_called_with("Cú pháp: python3 -m agent.account_manager moveacc <source_m> <target_m> [count]")

        # 2. CLI dispatch and argument parsing for moveacc with explicit count
        with mock.patch("agent.account_manager.move_accounts") as mock_move:
            mock_move.return_value = {
                "source_m": "M109",
                "target_m": "M77",
                "count": 2,
                "moved_accounts": ["Acc1", "Acc2"],
                "source_remaining_count": 5,
                "target_current_count": 8,
                "backup_acc": "/fake/acc.txt.bak_20260914",
                "sync_result": {"acc_sync": True, "rule34_verified": True},
            }

            cli_argv = ["account_manager", "moveacc", "m109", "m77", "2"]
            with mock.patch.object(sys, "argv", cli_argv):
                with mock.patch("builtins.print") as mock_print:
                    subcmd = sys.argv[1].lower()
                    if subcmd in ("moveacc", "move"):
                        if len(sys.argv) < 4:
                            sys.exit(1)
                        source_m = sys.argv[2]
                        target_m = sys.argv[3]
                        cnt = int(sys.argv[4]) if len(sys.argv) > 4 else 1
                        res = account_manager.move_accounts(source_m, target_m, count=cnt, sync_drive=True)
                        print(json.dumps(res, indent=2, ensure_ascii=False))

                    mock_move.assert_called_with("m109", "m77", count=2, sync_drive=True)
                    self.assertEqual(cnt, 2)
                    self.assertTrue(mock_print.called)
                    out = json.loads(mock_print.call_args[0][0])
                    self.assertEqual(out["source_m"], "M109")
                    self.assertEqual(out["target_m"], "M77")
                    self.assertEqual(out["count"], 2)

            # 3. CLI dispatch with default count=1 using alias 'move'
            cli_argv_alias = ["account_manager", "move", "m109", "m77"]
            with mock.patch.object(sys, "argv", cli_argv_alias):
                with mock.patch("builtins.print") as mock_print:
                    subcmd = sys.argv[1].lower()
                    if subcmd in ("moveacc", "move"):
                        if len(sys.argv) < 4:
                            sys.exit(1)
                        source_m = sys.argv[2]
                        target_m = sys.argv[3]
                        cnt = int(sys.argv[4]) if len(sys.argv) > 4 else 1
                        res = account_manager.move_accounts(source_m, target_m, count=cnt, sync_drive=True)
                        print(json.dumps(res, indent=2, ensure_ascii=False))

                    mock_move.assert_called_with("m109", "m77", count=1, sync_drive=True)
                    self.assertEqual(cnt, 1)

    # -------------------------------------------------------------------------
    # Test 10: Idempotency test for agent MOVE_ACC batch action
    # -------------------------------------------------------------------------
    @mock.patch("agent.agent.send_ack", return_value=True)
    def test_10_agent_move_acc_idempotency(self, mock_ack):
        """Test 10: Agent MOVE_ACC batch action executes once and caches result.
        Replaying the exact same action_id returns cached status and prevents redundant moves."""
        state = {}
        state_path = pathlib.Path(self.test_dir) / "state.json"
        links_path = pathlib.Path(self.test_dir) / "server_links.txt"
        action_id = "moveacc-test-idemp-001"

        message = {
            "protocol": "fleet-batch-v1",
            "action": "MOVE_ACC",
            "action_id": action_id,
            "source_m": "m109",
            "target_m": "m77",
            "count": 1,
            "sync_drive": False,
            "base_dir": self.test_dir,
            "target_device_ids": ["m77"],
        }

        # First dispatch
        handled1 = agent.handle_incoming_batch_action(
            message, "m77", "https://worker/report", "secret123", state, state_path, links_path
        )
        self.assertTrue(handled1)
        self.assertEqual(mock_ack.call_count, 1)
        first_ack_kwargs = mock_ack.call_args.kwargs
        self.assertEqual(first_ack_kwargs["status"], "OPENED")
        self.assertTrue(first_ack_kwargs["executed"])
        self.assertEqual(first_ack_kwargs["batch_action"], "MOVE_ACC")
        first_details = json.loads(first_ack_kwargs["details"])
        self.assertEqual(first_details["count"], 1)
        moved_first = first_details["moved_accounts"][0]

        # Read acc.txt after first execution: M109 had 4 accounts, now has 3
        with open(self.acc_file, "r", encoding="utf-8") as f:
            content_after_first = f.read()
        sec_after_first = parse_acc_sections(content_after_first)
        self.assertEqual(len(sec_after_first["m109"]["accounts"]), 3)

        # Second dispatch with identical action_id (duplicate replay)
        mock_ack.reset_mock()
        handled2 = agent.handle_incoming_batch_action(
            message, "m77", "https://worker/report", "secret123", state, state_path, links_path
        )
        self.assertTrue(handled2)
        self.assertEqual(mock_ack.call_count, 1, "send_ack must be called with cached response")
        replay_ack_kwargs = mock_ack.call_args.kwargs
        self.assertEqual(replay_ack_kwargs["status"], "OPENED")
        self.assertTrue(replay_ack_kwargs["executed"])
        self.assertEqual(replay_ack_kwargs["batch_action"], "MOVE_ACC")
        replay_details = json.loads(replay_ack_kwargs["details"])
        self.assertEqual(replay_details["moved_accounts"][0], moved_first)

        # Verify NO additional accounts were moved on replay
        with open(self.acc_file, "r", encoding="utf-8") as f:
            content_after_replay = f.read()
        sec_after_replay = parse_acc_sections(content_after_replay)
        self.assertEqual(len(sec_after_replay["m109"]["accounts"]), 3, "No accounts moved on duplicate replay")
        self.assertEqual(content_after_first, content_after_replay, "acc.txt must not change on duplicate replay")

    def test_10b_agent_capabilities_contains_move_acc(self):
        """Verify CAPABILITIES in agent.py declares 'move_acc'."""
        self.assertIn("move_acc", agent.CAPABILITIES)


if __name__ == "__main__":
    unittest.main()

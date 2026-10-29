#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Empirical Adversarial Stress-Test Suite for Milestone M3.
Targeting:
1. Roblox API ban detection & Quota-Guard Cache (TTL expiry, clearing, concurrency, 429 backoff & Retry-After).
2. Dual-Storage Account Isolation (dual .bak_<timestamp>, cookie extraction, logging, missing Data_Tong).
3. Rule 34 Google Drive in-place sync (rclone copyto, File ID preservation, fail-closed drift rejection).
4. Automated replacement from reserve pool (section regex collisions, duplicate merging, unassigned, depletion).
"""

import os
import re
import sys
import time
import shutil
import tempfile
import unittest
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock
import urllib.error

# Project root setup
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agent.account_manager import (
    parse_acc_sections,
    clean_banned_accounts,
    add_accounts,
    replace_banned_accounts_from_reserve,
    check_roblox_ban_status,
    run_full_checkban_pipeline,
    query_roblox_api,
    clear_ban_cache,
    invalidate_ban_cache,
    get_ban_cache_stats,
    sync_to_google_drive,
    verify_google_drive_file_ids,
    get_default_paths,
    RULE34_ACC_FILE_ID,
    RULE34_DATA_TONG_FILE_ID,
    DEFAULT_CACHE_TTL,
)


class TestM3RobloxBanAndQuotaGuard(unittest.TestCase):
    """Stress tests for Roblox API ban detection & Quota-Guard Cache."""

    def setUp(self):
        clear_ban_cache()

    def tearDown(self):
        clear_ban_cache()

    @patch("agent.account_manager.query_roblox_api")
    def test_quota_guard_ttl_expiry_and_refresh(self, mock_api):
        """Verify Quota-Guard Cache expires after TTL (300s) and refreshes from API."""
        call_counts = {"batch": 0, "detail": 0}

        def mock_query(url, method="GET", data=None, retries=3, backoff_factor=1.0):
            if "usernames/users" in url:
                call_counts["batch"] += 1
                return {
                    "data": [
                        {"requestedUsername": "expiring_user", "id": 9901, "name": "ExpiringUser"}
                    ]
                }
            if "users/9901" in url:
                call_counts["detail"] += 1
                return {"isBanned": False, "id": 9901, "name": "ExpiringUser"}
            return None

        mock_api.side_effect = mock_query

        # Step 1: Initial query at t = 1000.0
        current_time = [1000.0]
        with patch("time.time", side_effect=lambda: current_time[0]):
            res1 = check_roblox_ban_status(["expiring_user"], use_cache=True)
            self.assertEqual(res1["expiring_user"]["cached"], False)
            self.assertEqual(res1["expiring_user"]["isBanned"], False)
            self.assertEqual(call_counts["batch"], 1)
            self.assertEqual(call_counts["detail"], 1)

            # Step 2: Immediate query within TTL (t = 1010.0) -> cache hit
            current_time[0] = 1010.0
            res2 = check_roblox_ban_status(["expiring_user"], use_cache=True)
            self.assertEqual(res2["expiring_user"]["cached"], True)
            self.assertEqual(call_counts["batch"], 1)
            self.assertEqual(call_counts["detail"], 1)

            stats = get_ban_cache_stats()
            self.assertEqual(stats["active_entries"], 1)
            self.assertEqual(stats["expired_entries"], 0)

            # Step 3: Advance time beyond DEFAULT_CACHE_TTL (t = 1350.0, 350s later)
            current_time[0] = 1350.0
            stats_expired = get_ban_cache_stats()
            self.assertEqual(stats_expired["active_entries"], 0)
            self.assertEqual(stats_expired["expired_entries"], 1)

            # Step 4: Query after TTL expiry -> must re-fetch from API
            res3 = check_roblox_ban_status(["expiring_user"], use_cache=True)
            self.assertEqual(res3["expiring_user"]["cached"], False)
            self.assertEqual(call_counts["batch"], 2)
            self.assertEqual(call_counts["detail"], 2)

            stats_refreshed = get_ban_cache_stats()
            self.assertEqual(stats_refreshed["active_entries"], 1)
            self.assertEqual(stats_refreshed["expired_entries"], 0)

    @patch("agent.account_manager.query_roblox_api")
    def test_quota_guard_cache_clearing_and_selective_invalidation(self, mock_api):
        """Verify targeted invalidation vs global cache clearing."""
        mock_api.side_effect = lambda url, **kw: (
            {"data": [{"requestedUsername": f"u{i}", "id": 1000 + i, "name": f"U{i}"} for i in range(5)]}
            if "usernames/users" in url
            else {"isBanned": False, "id": int(url.split("/")[-1]), "name": "U"}
        )

        users = [f"u{i}" for i in range(5)]
        check_roblox_ban_status(users, use_cache=True, cache_ttl=300)
        stats = get_ban_cache_stats()
        self.assertEqual(stats["total_entries"], 5)

        # Selective invalidation of u0, u1
        invalidate_ban_cache(["u0", "u1"])
        stats2 = get_ban_cache_stats()
        self.assertEqual(stats2["total_entries"], 3)

        # Query u2 (should be cached) and u0 (should be re-queried)
        res = check_roblox_ban_status(["u2", "u0"], use_cache=True, cache_ttl=300)
        self.assertEqual(res["u2"]["cached"], True)
        self.assertEqual(res["u0"]["cached"], False)

        # Full clear
        clear_ban_cache()
        self.assertEqual(get_ban_cache_stats()["total_entries"], 0)

    @patch("agent.account_manager.query_roblox_api")
    def test_quota_guard_concurrent_requests_stress(self, mock_api):
        """Stress test Quota-Guard Cache under high concurrency across 20 threads."""
        mock_api.side_effect = lambda url, **kw: (
            {"data": [
                {"requestedUsername": "thread_user_1", "id": 501, "name": "T1"},
                {"requestedUsername": "thread_user_2", "id": 502, "name": "T2"},
                {"requestedUsername": "thread_user_3", "id": 503, "name": "T3"},
            ]}
            if "usernames/users" in url
            else {"isBanned": ("502" in url), "id": 500, "name": "T"}
        )

        usernames = ["thread_user_1", "thread_user_2", "thread_user_3"]
        errors = []

        def worker_thread():
            try:
                for _ in range(5):
                    res = check_roblox_ban_status(usernames, use_cache=True, cache_ttl=300)
                    if "thread_user_1" not in res or res["thread_user_1"]["isBanned"] is not False:
                        errors.append("Invalid user 1 result")
                    if "thread_user_2" not in res or res["thread_user_2"]["isBanned"] is not True:
                        errors.append("Invalid user 2 result")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker_thread) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Concurrent thread errors: {errors}")
        stats = get_ban_cache_stats()
        self.assertEqual(stats["total_entries"], 3)

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_roblox_api_429_retry_after_variations(self, mock_urlopen, mock_sleep):
        """Adversarial testing of 429 Retry-After parsing: int, float, invalid, negative, capped."""
        success_resp = MagicMock()
        success_resp.read.return_value = b'{"status": "ok"}'
        success_resp.__enter__.return_value = success_resp

        def make_429(retry_val):
            hdrs = MagicMock()
            hdrs.get.side_effect = lambda k, default=None: str(retry_val) if k == "Retry-After" else default
            return urllib.error.HTTPError(
                url="https://api", code=429, msg="Too Many Requests", hdrs=hdrs, fp=None
            )

        # 1. Float Retry-After ("2.5") -> sleeps 2.5
        mock_urlopen.side_effect = [make_429(2.5), success_resp]
        mock_sleep.reset_mock()
        query_roblox_api("https://api", retries=2)
        mock_sleep.assert_called_with(2.5)

        # 2. Invalid string ("bad_header") -> fallback to exponential 1.0 * 2^0 = 1.0
        mock_urlopen.side_effect = [make_429("bad_header"), success_resp]
        mock_sleep.reset_mock()
        query_roblox_api("https://api", retries=2, backoff_factor=1.0)
        mock_sleep.assert_called_with(1.0)

        # 3. Negative value ("-5") -> fallback to exponential
        mock_urlopen.side_effect = [make_429(-5), success_resp]
        mock_sleep.reset_mock()
        query_roblox_api("https://api", retries=2, backoff_factor=1.5)
        mock_sleep.assert_called_with(1.5)

        # 4. Overly large header ("120") -> clamped to 60.0 max
        mock_urlopen.side_effect = [make_429(120), success_resp]
        mock_sleep.reset_mock()
        query_roblox_api("https://api", retries=2)
        mock_sleep.assert_called_with(60.0)

        # 5. Very small header ("0.001") -> clamped to 0.1 min
        mock_urlopen.side_effect = [make_429(0.001), success_resp]
        mock_sleep.reset_mock()
        query_roblox_api("https://api", retries=2)
        mock_sleep.assert_called_with(0.1)

        # 6. Persistent 429 exceeding max retries -> raises HTTPError
        mock_urlopen.side_effect = [make_429(1), make_429(1), make_429(1)]
        with self.assertRaises(urllib.error.HTTPError):
            query_roblox_api("https://api", retries=3)

    @patch("agent.account_manager.query_roblox_api")
    def test_roblox_batch_chunking_and_payload_invariants(self, mock_api):
        """Verify queries exceeding 100 usernames are chunked into 100-user requests with excludeBannedUsers=False."""
        captured_payloads = []

        def mock_query(url, method="GET", data=None, retries=3, backoff_factor=1.0):
            if "usernames/users" in url:
                captured_payloads.append(data)
                return {
                    "data": [
                        {"requestedUsername": u, "id": idx + 1, "name": u}
                        for idx, u in enumerate(data.get("usernames", []))
                    ]
                }
            return {"isBanned": False, "id": 1, "name": "U"}

        mock_api.side_effect = mock_query

        # Generate 250 distinct usernames
        test_users = [f"bulk_user_{i}" for i in range(250)]
        results = check_roblox_ban_status(test_users, use_cache=False)

        self.assertEqual(len(results), 250)
        # Verify 3 chunks: 100, 100, 50
        self.assertEqual(len(captured_payloads), 3)
        self.assertEqual(len(captured_payloads[0]["usernames"]), 100)
        self.assertEqual(len(captured_payloads[1]["usernames"]), 100)
        self.assertEqual(len(captured_payloads[2]["usernames"]), 50)

        # Verify excludeBannedUsers: False in all payloads
        for p in captured_payloads:
            self.assertEqual(p["excludeBannedUsers"], False)


class TestM3DualStorageAccountIsolation(unittest.TestCase):
    """Stress tests for Dual-Storage Account Isolation and backups."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="m3_iso_")
        self.acc_file = os.path.join(self.test_dir, "acc.txt")
        self.data_tong_file = os.path.join(self.test_dir, "Data_Tong_Cookies.txt")
        self.acc_bi_ban_file = os.path.join(self.test_dir, "acc_bi_ban.txt")
        self.nhat_ky_ban_file = os.path.join(self.test_dir, "nhat_ky_ban.txt")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_dual_backups_created_on_clean_and_add(self):
        """Verify .bak_<timestamp> is created for BOTH acc.txt and Data_Tong_Cookies.txt on clean and add."""
        initial_acc = "M77___(gag2)\nAlpha:pass1\nBeta:pass2\nGamma:pass3\n"
        initial_dt = (
            "Alpha:pass1:_|WARNING:-DO-NOT-SHARE-THIS|cookie_alpha\n"
            "Beta:pass2:_|WARNING:-DO-NOT-SHARE-THIS|cookie_beta\n"
            "Gamma:pass3:_|WARNING:-DO-NOT-SHARE-THIS|cookie_gamma\n"
        )
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(initial_acc)
        with open(self.data_tong_file, "w", encoding="utf-8") as f:
            f.write(initial_dt)

        # 1. Test clean_banned_accounts
        res_clean = clean_banned_accounts("m77", ["Beta"], base_dir=self.test_dir)
        self.assertTrue(os.path.exists(res_clean["backup_acc"]))
        self.assertTrue(os.path.exists(res_clean["backup_data_tong"]))
        self.assertTrue(res_clean["backup_acc"].startswith(f"{self.acc_file}.bak_"))
        self.assertTrue(res_clean["backup_data_tong"].startswith(f"{self.data_tong_file}.bak_"))

        # Verify backup contents preserve original state
        with open(res_clean["backup_acc"], "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), initial_acc)
        with open(res_clean["backup_data_tong"], "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), initial_dt)

        # 2. Test add_accounts creates both backups
        time.sleep(1.05)  # Ensure distinct timestamp
        res_add = add_accounts("m77", ["Delta:pass4:_|WARNING|cookie_delta"], base_dir=self.test_dir)
        self.assertTrue(os.path.exists(res_add["backup_acc"]))
        self.assertTrue(os.path.exists(res_add["backup_data_tong"]))

    def test_dual_storage_when_data_tong_initially_missing(self):
        """Verify clean and add execute gracefully when Data_Tong_Cookies.txt is missing."""
        initial_acc = "M77___(gag2)\nSoloUser:pwd\n"
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(initial_acc)

        # clean without Data_Tong_Cookies.txt
        res = clean_banned_accounts("m77", ["SoloUser"], base_dir=self.test_dir)
        self.assertEqual(res["removed_from_acc"], 1)
        self.assertIsNone(res["backup_data_tong"])
        self.assertTrue(os.path.exists(res["backup_acc"]))

        # add without Data_Tong_Cookies.txt
        res_add = add_accounts("m77", ["NewUser:pwd"], base_dir=self.test_dir)
        self.assertEqual(res_add["added_count"], 1)
        self.assertIsNone(res_add["backup_data_tong"])
        self.assertTrue(os.path.exists(res_add["backup_acc"]))

    def test_cookie_extraction_and_nhat_ky_ban_logging_integrity(self):
        """Verify cookie extraction to acc_bi_ban.txt and log formatting in nhat_ky_ban.txt."""
        acc_text = "M77___(gag2)\nUserA:passA\nUserB:passB\nUserC:passC\n"
        dt_text = (
            "UserA:passA:_|WARNING:-DO-NOT-SHARE-THIS|cookie_A_secret\n"
            "UserB:passB:_|WARNING:-DO-NOT-SHARE-THIS|cookie_B_secret\n"
            "UserC:passC:_|WARNING:-DO-NOT-SHARE-THIS|cookie_C_secret\n"
        )
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(acc_text)
        with open(self.data_tong_file, "w", encoding="utf-8") as f:
            f.write(dt_text)

        res = clean_banned_accounts("m77", ["UserB"], base_dir=self.test_dir)
        self.assertEqual(res["archived_cookies_count"], 1)

        # Verify acc_bi_ban.txt contains full cookie line
        with open(self.acc_bi_ban_file, "r", encoding="utf-8") as f:
            banned_cookies = f.read()
        self.assertIn("UserB:passB:_|WARNING:-DO-NOT-SHARE-THIS|cookie_B_secret", banned_cookies)
        self.assertNotIn("UserA", banned_cookies)

        # Verify nhat_ky_ban.txt format
        with open(self.nhat_ky_ban_file, "r", encoding="utf-8") as f:
            nhat_ky = f.read()
        self.assertIn("UserB:::banned", nhat_ky)
        self.assertIn("Máy 77", nhat_ky)

        # Verify Data_Tong_Cookies.txt has UserB removed, UserA and UserC kept
        with open(self.data_tong_file, "r", encoding="utf-8") as f:
            dt_cleaned = f.read()
        self.assertNotIn("UserB", dt_cleaned)
        self.assertIn("UserA", dt_cleaned)
        self.assertIn("UserC", dt_cleaned)


class TestM3Rule34GoogleDriveSync(unittest.TestCase):
    """Stress tests for Rule 34 Google Drive in-place sync & File ID invariants."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="m3_r34_")
        self.acc_file = os.path.join(self.test_dir, "acc.txt")
        self.data_tong_file = os.path.join(self.test_dir, "Data_Tong_Cookies.txt")
        with open(self.acc_file, "w") as f:
            f.write("test acc")
        with open(self.data_tong_file, "w") as f:
            f.write("test dt")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("agent.account_manager.verify_google_drive_file_ids")
    @patch("subprocess.run")
    def test_rclone_copyto_command_arguments(self, mock_subproc, mock_verify):
        """Verify rclone copyto is invoked strictly for in-place overwrite preserving File ID."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        mock_subproc.return_value = mock_proc
        mock_verify.return_value = {"verified": True, "file_ids": {}}

        res = sync_to_google_drive(base_dir=self.test_dir, verify_rule34=True)
        self.assertTrue(res["acc_sync"])
        self.assertTrue(res["data_tong_sync"])

        calls = mock_subproc.call_args_list
        # Must be exactly 2 calls: one for acc.txt, one for Data_Tong_Cookies.txt
        self.assertEqual(len(calls), 2)
        cmd_acc = calls[0][0][0]
        cmd_dt = calls[1][0][0]

        # Verify 'copyto' is used (NOT 'copy', 'sync', or 'move')
        self.assertEqual(cmd_acc[1], "copyto")
        self.assertEqual(cmd_acc[2], self.acc_file)
        self.assertEqual(cmd_acc[3], "gdrive:acc.txt")

        self.assertEqual(cmd_dt[1], "copyto")
        self.assertEqual(cmd_dt[2], self.data_tong_file)
        self.assertEqual(cmd_dt[3], "gdrive:Data_Tong_Cookies.txt")

    @patch("subprocess.run")
    def test_rule34_file_id_drift_raises_runtime_error(self, mock_subproc):
        """Adversarial check: ensure any deviation in File ID immediately aborts and raises RuntimeError."""
        # 1. acc.txt File ID drift
        mock_proc1 = MagicMock()
        mock_proc1.returncode = 0
        mock_proc1.stdout = f"TAMPERED_ID_1;acc.txt\n{RULE34_DATA_TONG_FILE_ID};Data_Tong_Cookies.txt\n"
        mock_subproc.return_value = mock_proc1

        with self.assertRaises(RuntimeError) as ctx1:
            verify_google_drive_file_ids()
        self.assertIn("Rule 34 Violated! acc.txt File ID bị biến động", str(ctx1.exception))

        # 2. Data_Tong_Cookies.txt File ID drift
        mock_proc2 = MagicMock()
        mock_proc2.returncode = 0
        mock_proc2.stdout = f"{RULE34_ACC_FILE_ID};acc.txt\nTAMPERED_ID_2;Data_Tong_Cookies.txt\n"
        mock_subproc.return_value = mock_proc2

        with self.assertRaises(RuntimeError) as ctx2:
            verify_google_drive_file_ids()
        self.assertIn("Rule 34 Violated! Data_Tong_Cookies.txt File ID bị biến động", str(ctx2.exception))

    @patch("subprocess.run")
    def test_rclone_process_failure_handling(self, mock_subproc):
        """Verify rclone command failure raises descriptive RuntimeError."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "Fatal: token expired or network unreachable"
        mock_subproc.return_value = mock_proc

        with self.assertRaises(RuntimeError) as ctx:
            sync_to_google_drive(base_dir=self.test_dir, verify_rule34=False)
        self.assertIn("token expired or network unreachable", str(ctx.exception))


class TestM3ReservePoolAndSectionParsing(unittest.TestCase):
    """Stress tests for reserve pool replenishment and section regex edge cases."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="m3_res_")
        self.acc_file = os.path.join(self.test_dir, "acc.txt")
        self.data_tong_file = os.path.join(self.test_dir, "Data_Tong_Cookies.txt")
        self.acc_du_phong_file = os.path.join(self.test_dir, "acc_du_phong.txt")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_section_regex_adversarial_account_names(self):
        """Stress test section header regex against account names starting with M or numbers."""
        tricky_content = """
# Unassigned accounts at top
TopAcc_1:pwd1
M00nlUWarden3200644:V0Ff6eS@R*@JTrHL
Mega_Wiley623:pass_mega
M123_Player456:pwd_m123

M77___(gag2)
M77_User1:p1
M77_User2:p2

M00___(duplicate_00)
M00_User1:p00

M00___(duplicate_00_again)
M00_User2:p00_2

M109(gag2)____
User_109:p109
"""
        sections = parse_acc_sections(tricky_content)

        # Top unassigned accounts must capture all 4 top accounts
        self.assertIn("unassigned", sections)
        unassigned_names = [a["username"] for a in sections["unassigned"]["accounts"]]
        self.assertEqual(
            unassigned_names,
            ["TopAcc_1", "M00nlUWarden3200644", "Mega_Wiley623", "M123_Player456"]
        )

        # Verify M00nlUWarden3200644 and Mega_Wiley623 are NEVER parsed as sections
        self.assertNotIn("m00nluwarden3200644", sections)
        self.assertNotIn("mega_wiley623", sections)
        self.assertNotIn("m123_player456", sections)

        # Verify duplicate section M00 merging
        self.assertIn("m00", sections)
        m00_accounts = [a["username"] for a in sections["m00"]["accounts"]]
        self.assertEqual(m00_accounts, ["M00_User1", "M00_User2"])

    def test_reserve_pool_depletion_and_undersupply(self):
        """Verify replenishment when reserve pool has fewer accounts than needed, or 0 accounts."""
        # Initial reserve pool has only 2 accounts
        reserve_text = (
            "# Header comment line\n"
            "Reserve1:pass1:_|WARNING|cookie_res1\n"
            "Reserve2:pass2\n"
            "# Trailing comment\n"
        )
        with open(self.acc_du_phong_file, "w", encoding="utf-8") as f:
            f.write(reserve_text)

        acc_text = "M77___(gag2)\nOldUser1:p1\n"
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(acc_text)
        with open(self.data_tong_file, "w", encoding="utf-8") as f:
            f.write("OldUser1:p1:cookie_old\n")

        # Request 5 accounts when only 2 exist (under-supply)
        res1 = replace_banned_accounts_from_reserve("m77", num_needed=5, base_dir=self.test_dir)
        self.assertEqual(res1["replaced_count"], 2)
        self.assertEqual(res1["replaced_accounts"], ["Reserve1", "Reserve2"])
        self.assertEqual(res1["remaining_reserve_count"], 0)

        # Verify reserve pool comments were preserved, accounts removed
        with open(self.acc_du_phong_file, "r", encoding="utf-8") as f:
            pool_content = f.read()
        self.assertIn("# Header comment line", pool_content)
        self.assertIn("# Trailing comment", pool_content)
        self.assertNotIn("Reserve1:pass1", pool_content)
        self.assertNotIn("Reserve2:pass2", pool_content)

        # Second request when pool is completely empty -> returns 0 without error
        res2 = replace_banned_accounts_from_reserve("m77", num_needed=2, base_dir=self.test_dir)
        self.assertEqual(res2["replaced_count"], 0)
        self.assertEqual(res2["replaced_accounts"], [])
        self.assertEqual(res2["remaining_reserve_count"], 0)

    @patch("agent.account_manager.sync_to_google_drive")
    @patch("agent.account_manager.query_roblox_api")
    def test_end_to_end_pipeline_multi_section_replacement(self, mock_api, mock_sync):
        """End-to-end stress test of pipeline with target 'all' replacing across multiple sections."""
        acc_content = (
            "M77___(gag2)\n"
            "User_M77_1:p1\n"
            "User_M77_2:p2\n"
            "M109(gag2)____\n"
            "User_M109_1:p3\n"
            "User_M109_2:p4\n"
        )
        dt_content = (
            "User_M77_1:p1:cookie1\n"
            "User_M77_2:p2:cookie2\n"
            "User_M109_1:p3:cookie3\n"
            "User_M109_2:p4:cookie4\n"
        )
        reserve_content = (
            "Rep1:p_r1\n"
            "Rep2:p_r2\n"
            "Rep3:p_r3\n"
        )
        with open(self.acc_file, "w") as f:
            f.write(acc_content)
        with open(self.data_tong_file, "w") as f:
            f.write(dt_content)
        with open(self.acc_du_phong_file, "w") as f:
            f.write(reserve_content)

        # Mock: User_M77_2 and User_M109_1 are banned
        def mock_query(url, method="GET", data=None, retries=3, backoff_factor=1.0):
            if "usernames/users" in url:
                return {
                    "data": [
                        {"requestedUsername": "user_m77_1", "id": 1, "name": "User_M77_1"},
                        {"requestedUsername": "user_m77_2", "id": 2, "name": "User_M77_2"},
                        {"requestedUsername": "user_m109_1", "id": 3, "name": "User_M109_1"},
                        {"requestedUsername": "user_m109_2", "id": 4, "name": "User_M109_2"},
                    ]
                }
            if "users/2" in url or "users/3" in url:
                return {"isBanned": True}
            return {"isBanned": False}

        mock_api.side_effect = mock_query
        mock_sync.return_value = {"acc.txt": "OK", "Data_Tong_Cookies.txt": "OK"}

        report = run_full_checkban_pipeline("all", base_dir=self.test_dir, auto_replace=True)

        self.assertEqual(report["total"], 4)
        self.assertEqual(report["live"], 2)
        self.assertEqual(report["banned"], 2)
        self.assertEqual(set(report["banned_list"]), {"User_M77_2", "User_M109_1"})

        # Check replace_result by section
        self.assertIsNotNone(report["replace_result"])
        self.assertEqual(report["replace_result"]["replaced_count"], 2)
        self.assertIn("m77", report["replace_result"]["by_section"])
        self.assertIn("m109", report["replace_result"]["by_section"])

        # Check acc.txt content
        with open(self.acc_file, "r") as f:
            final_acc = f.read()
        self.assertNotIn("User_M77_2", final_acc)
        self.assertNotIn("User_M109_1", final_acc)
        self.assertIn("User_M77_1", final_acc)
        self.assertIn("User_M109_2", final_acc)
        self.assertIn("Rep1:p_r1", final_acc)
        self.assertIn("Rep2:p_r2", final_acc)


if __name__ == "__main__":
    unittest.main()


class TestM3AdversarialEdgeCases(unittest.TestCase):
    """Extreme edge case testing: CRLF endings, corrupt inputs, 5xx server errors, multiple cookies per user."""

    def setUp(self):
        clear_ban_cache()
        self.test_dir = tempfile.mkdtemp(prefix="m3_edge_")
        self.acc_file = os.path.join(self.test_dir, "acc.txt")
        self.data_tong_file = os.path.join(self.test_dir, "Data_Tong_Cookies.txt")
        self.acc_bi_ban_file = os.path.join(self.test_dir, "acc_bi_ban.txt")
        self.nhat_ky_ban_file = os.path.join(self.test_dir, "nhat_ky_ban.txt")
        self.acc_du_phong_file = os.path.join(self.test_dir, "acc_du_phong.txt")

    def tearDown(self):
        clear_ban_cache()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_crlf_windows_line_endings_support(self):
        """Verify acc.txt and Data_Tong_Cookies.txt with Windows \r\n line endings parse and clean properly."""
        crlf_acc = "M77___(gag2)\r\nUserWin1:pass1\r\nUserWin2:pass2\r\nM109\r\nUserWin3:pass3\r\n"
        crlf_dt = "UserWin1:pass1:cookie1\r\nUserWin2:pass2:cookie2\r\nUserWin3:pass3:cookie3\r\n"

        with open(self.acc_file, "wb") as f:
            f.write(crlf_acc.encode("utf-8"))
        with open(self.data_tong_file, "wb") as f:
            f.write(crlf_dt.encode("utf-8"))

        res = clean_banned_accounts("m77", ["UserWin2"], base_dir=self.test_dir)
        self.assertEqual(res["removed_from_acc"], 1)
        self.assertEqual(res["archived_cookies_count"], 1)

        with open(self.acc_file, "r", encoding="utf-8") as f:
            cleaned_acc = f.read()
        self.assertNotIn("UserWin2", cleaned_acc)
        self.assertIn("UserWin1", cleaned_acc)
        self.assertIn("UserWin3", cleaned_acc)

    @patch("agent.account_manager.query_roblox_api")
    def test_roblox_500_internal_server_error_resilience(self, mock_api):
        """Verify that HTTP 500 or network timeout marks accounts as error without aborting pipeline."""
        mock_api.side_effect = urllib.error.HTTPError(
            url="https://api", code=500, msg="Internal Server Error", hdrs=None, fp=None
        )

        results = check_roblox_ban_status(["error_user_1", "error_user_2"], use_cache=False)
        self.assertEqual(len(results), 2)
        self.assertIn("ID_LOOKUP_ERROR", results["error_user_1"]["error"])
        self.assertIsNone(results["error_user_1"]["isBanned"])

    def test_multiple_cookies_for_same_user_in_data_tong(self):
        """Verify all cookie entries for a banned account are archived when multiple exist."""
        acc_text = "M77___(gag2)\nMultiCookieUser:pwd\nOtherUser:pwd2\n"
        dt_text = (
            "MultiCookieUser:pwd:_|WARNING|cookie_v1\n"
            "OtherUser:pwd2:_|WARNING|cookie_other\n"
            "MultiCookieUser:pwd:_|WARNING|cookie_v2\n"
        )
        with open(self.acc_file, "w") as f:
            f.write(acc_text)
        with open(self.data_tong_file, "w") as f:
            f.write(dt_text)

        res = clean_banned_accounts("m77", ["MultiCookieUser"], base_dir=self.test_dir)
        self.assertEqual(res["removed_from_acc"], 1)
        self.assertEqual(res["archived_cookies_count"], 2)

        with open(self.acc_bi_ban_file, "r") as f:
            banned_cookies = f.read()
        self.assertIn("cookie_v1", banned_cookies)
        self.assertIn("cookie_v2", banned_cookies)

        with open(self.data_tong_file, "r") as f:
            cleaned_dt = f.read()
        self.assertNotIn("MultiCookieUser", cleaned_dt)
        self.assertIn("OtherUser", cleaned_dt)

    def test_add_accounts_rejects_empty_lines(self):
        """Verify add_accounts raises ValueError when provided only empty lines or malformed lines without colon."""
        initial_acc = "M77___(gag2)\nUserA:passA\n"
        with open(self.acc_file, "w") as f:
            f.write(initial_acc)

        with self.assertRaises(ValueError):
            add_accounts("m77", ["", "   ", "malformed_line_no_colon"], base_dir=self.test_dir)

    def test_clean_banned_accounts_when_no_accounts_banned(self):
        """Verify clean_banned_accounts handles empty banned list gracefully."""
        initial_acc = "M77___(gag2)\nUserA:passA\n"
        with open(self.acc_file, "w") as f:
            f.write(initial_acc)

        res = clean_banned_accounts("m77", [], base_dir=self.test_dir)
        self.assertEqual(res["banned_count"], 0)
        self.assertEqual(res["removed_from_acc"], 0)
        self.assertEqual(res["archived_cookies_count"], 0)

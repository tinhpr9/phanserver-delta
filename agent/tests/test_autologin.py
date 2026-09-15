#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for auto-login feature:
- write_cookie_to_package: writes .ROBLOSECURITY to SQLite WebView DB
- auto_login_unlogged_tabs: scans empty tabs, allocates accounts from acc.txt, writes cookies, updates tab_accounts.json
- handle_incoming_batch_action: AUTO_LOGIN action handling, caching, ACK dispatch
"""

import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from agent import account_manager, agent


class TestAutoLogin(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = pathlib.Path(self.temp_dir.name)
        self.data_dir = self.base_dir / "data_data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.base_dir / "state.json"
        self.links_path = self.base_dir / "links.txt"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_write_cookie_to_package_sqlite(self):
        pkg = "com.tinh.vv.hi"
        cookie_val = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-into-your-account"
        ok, msg = account_manager.write_cookie_to_package(pkg, cookie_val, base_data_dir=str(self.data_dir))
        self.assertTrue(ok)
        self.assertEqual(msg, "sqlite_success")

        # Verify SQLite DB contents
        db_file = self.data_dir / pkg / "app_webview" / "Default" / "Cookies"
        self.assertTrue(db_file.is_file())

        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        cursor.execute("SELECT name, value, host_key FROM cookies WHERE name='.ROBLOSECURITY'")
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], ".ROBLOSECURITY")
        self.assertEqual(row[1], cookie_val)
        self.assertEqual(row[2], ".roblox.com")

    def test_auto_login_unlogged_tabs_all_assigned(self):
        # Create acc.txt and tab_accounts.json where all 10 tabs are already assigned
        acc_file = self.base_dir / "acc.txt"
        acc_file.write_text("M77___(gag2)\nuser1:pass1\nuser2:pass2\n", encoding="utf-8")

        tab_map_file = self.base_dir / "tab_accounts.json"
        all_assigned = {
            f"com.tinh.vv.h{chr(ord('i') + i)}": f"user_{i}" for i in range(10)
        }
        tab_map_file.write_text(json.dumps(all_assigned), encoding="utf-8")

        res = account_manager.auto_login_unlogged_tabs("m77", base_dir=str(self.base_dir), base_data_dir=str(self.data_dir))
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_unlogged"], 0)
        self.assertEqual(res["total_logged"], 0)
        self.assertIn("đều đã có tài khoản", res["message"])

    def test_auto_login_unlogged_tabs_success(self):
        acc_file = self.base_dir / "acc.txt"
        acc_file.write_text(
            "M77___(gag2)\n"
            "Zephyra_Pro731:pass123\n"
            "M00nlUWarden:pass456\n",
            encoding="utf-8"
        )
        data_tong_file = self.base_dir / "Data_Tong_Cookies.txt"
        data_tong_file.write_text(
            "Zephyra_Pro731:pass123:_|WARNING:cookie_zephyra\n"
            "M00nlUWarden:pass456:_|WARNING:cookie_moon\n",
            encoding="utf-8"
        )

        tab_map_file = self.base_dir / "tab_accounts.json"
        # tab 1 is com.tinh.vv.hi, assigned to existing_user
        # tab 2 is com.tinh.vv.hj, unassigned/null
        # tab 3 is com.tinh.vv.hk, unassigned
        tab_map_file.write_text(json.dumps({
            "com.tinh.vv.hi": "existing_user"
        }), encoding="utf-8")

        res = account_manager.auto_login_unlogged_tabs("m77", base_dir=str(self.base_dir), base_data_dir=str(self.data_dir))
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_logged"], 2)

        # Verify tab_accounts.json updated
        updated_map = json.loads(tab_map_file.read_text(encoding="utf-8"))
        self.assertEqual(updated_map.get("com.tinh.vv.hi"), "existing_user")
        self.assertEqual(updated_map.get("com.tinh.vv.hj"), "Zephyra_Pro731")
        self.assertEqual(updated_map.get("com.tinh.vv.hk"), "M00nlUWarden")

        # Verify cookie written into SQLite for com.tinh.vv.hj
        db_file = self.data_dir / "com.tinh.vv.hj" / "app_webview" / "Default" / "Cookies"
        self.assertTrue(db_file.is_file())
        conn = sqlite3.connect(str(db_file))
        c = conn.cursor()
        c.execute("SELECT value FROM cookies WHERE name='.ROBLOSECURITY'")
        row = c.fetchone()
        conn.close()
        self.assertEqual(row[0], "_|WARNING:cookie_zephyra")

    def test_handle_incoming_batch_action_auto_login(self):
        state = {}
        msg = {
            "protocol": "fleet-batch-v1",
            "action": "AUTO_LOGIN",
            "action_id": "login-001",
            "target_device_ids": ["m77"],
            "base_dir": str(self.base_dir),
        }

        # Setup acc.txt
        acc_file = self.base_dir / "acc.txt"
        acc_file.write_text("M77___(gag2)\nAutoUser1:p1\n", encoding="utf-8")
        cookie_file = self.base_dir / "Data_Tong_Cookies.txt"
        cookie_file.write_text("AutoUser1:p1:_|WARNING:auto_cookie\n", encoding="utf-8")

        with mock.patch("agent.agent.send_ack") as mock_ack:
            handled = agent.handle_incoming_batch_action(
                msg, "m77", "https://mock.worker/report", "secret", state, self.state_path, self.links_path
            )
            self.assertTrue(handled)
            mock_ack.assert_called_once()
            call_kwargs = mock_ack.call_args.kwargs
            self.assertEqual(call_kwargs["batch_action"], "AUTO_LOGIN")
            self.assertEqual(call_kwargs["status"], "OPENED")
            self.assertTrue(call_kwargs["executed"])

            # Verify cached replay
            mock_ack.reset_mock()
            handled_replay = agent.handle_incoming_batch_action(
                msg, "m77", "https://mock.worker/report", "secret", state, self.state_path, self.links_path
            )
            self.assertTrue(handled_replay)
            mock_ack.assert_called_once()
            self.assertEqual(mock_ack.call_args.kwargs["status"], "OPENED")

    def test_auto_login_replaces_banned_and_duplicate_accounts(self):
        # 1. Setup ban list
        ban_file = self.base_dir / "acc_bi_ban.txt"
        ban_file.write_text("BannedUser1:p1\nBannedUser2:p2\n", encoding="utf-8")

        # 2. Setup tab_accounts.json with a banned account and a duplicate account
        tab_map_file = self.base_dir / "tab_accounts.json"
        tab_map_file.write_text(json.dumps({
            "com.tinh.vv.hi": "CleanAssigned1",
            "com.tinh.vv.hj": "BannedUser1",      # Banned
            "com.tinh.vv.hk": "CleanAssigned1",  # Duplicate of tab 1
            "com.tinh.vv.hl": "",                # Unassigned
        }), encoding="utf-8")

        # 3. Setup acc.txt (# M77) with mix of assigned, banned, and good candidates
        acc_file = self.base_dir / "acc.txt"
        acc_file.write_text(
            "M77___(gag2)\n"
            "CleanAssigned1:p1\n"
            "BannedUser2:p2\n"       # Banned candidate, must NOT be picked!
            "CandidateGood1:p3\n"
            "CandidateGood2:p4\n"
            "CandidateGood3:p5\n",
            encoding="utf-8"
        )

        # 4. Setup cookie store
        cookie_file = self.base_dir / "Data_Tong_Cookies.txt"
        cookie_file.write_text(
            "CandidateGood1:p3:_|WARNING:cookie_good1\n"
            "CandidateGood2:p4:_|WARNING:cookie_good2\n"
            "CandidateGood3:p5:_|WARNING:cookie_good3\n",
            encoding="utf-8"
        )

        res = account_manager.auto_login_unlogged_tabs(
            "m77", base_dir=str(self.base_dir), base_data_dir=str(self.data_dir)
        )
        self.assertTrue(res["ok"])
        # Should replace Tab 2 (banned), Tab 3 (duplicate), and Tab 4 (unassigned)
        self.assertGreaterEqual(res["total_logged"], 3)

        updated_tabs = json.loads(tab_map_file.read_text(encoding="utf-8"))
        # Tab 1 should remain CleanAssigned1
        self.assertEqual(updated_tabs.get("com.tinh.vv.hi"), "CleanAssigned1")
        # Tab 2, 3, 4 should now have good candidates, NOT BannedUser1 or BannedUser2
        self.assertEqual(updated_tabs.get("com.tinh.vv.hj"), "CandidateGood1")
        self.assertEqual(updated_tabs.get("com.tinh.vv.hk"), "CandidateGood2")
        self.assertEqual(updated_tabs.get("com.tinh.vv.hl"), "CandidateGood3")

        # Verify summary message mentions replaced accounts
        self.assertIn("thay", res["message"])


if __name__ == "__main__":
    unittest.main()

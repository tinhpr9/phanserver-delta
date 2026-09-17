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
        acc_file.write_text("M77___(gag2)\n" + "\n".join(f"user_{i}:pass_{i}" for i in range(10)) + "\n", encoding="utf-8")

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
            "existing_user:pass0\n"
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

        with mock.patch("agent.agent.send_ack") as mock_ack, \
             mock.patch("agent.agent.query_tab_list", return_value=[]) as mock_qtabs:
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

    def test_auto_login_replaces_dead_cookies_and_facelock(self):
        # 1. Setup dead cookie and face lock files
        dead_file = self.base_dir / "acc_dead_cookies.txt"
        dead_file.write_text("DeadUser1:p1:_|WARNING:dead_ck\n", encoding="utf-8")
        face_file = self.base_dir / "acc_face_lock.txt"
        face_file.write_text("FaceUser2:p2:_|WARNING:face_ck\n", encoding="utf-8")

        # 2. Setup tab_accounts.json mapping
        tab_map_file = self.base_dir / "tab_accounts.json"
        tab_map_file.write_text(json.dumps({
            "com.tinh.vv.hi": "CleanUser1",
            "com.tinh.vv.hj": "DeadUser1",   # dead cookie -> must replace
            "com.tinh.vv.hk": "FaceUser2",   # face lock -> must replace
        }), encoding="utf-8")

        # 3. Setup acc.txt (# M77)
        acc_file = self.base_dir / "acc.txt"
        acc_file.write_text(
            "M77___(gag2)\n"
            "CleanUser1:p1\n"
            "DeadUser1:p2\n"       # Dead in acc.txt, must NOT be picked as candidate!
            "FaceUser2:p3\n"       # Face-locked in acc.txt, must NOT be picked!
            "CleanReplacement1:p4\n"
            "CleanReplacement2:p5\n",
            encoding="utf-8"
        )

        # 4. Setup cookie store
        cookie_file = self.base_dir / "Data_Tong_Cookies.txt"
        cookie_file.write_text(
            "CleanReplacement1:p4:_|WARNING:rep_cookie1\n"
            "CleanReplacement2:p5:_|WARNING:rep_cookie2\n",
            encoding="utf-8"
        )

        res = account_manager.auto_login_unlogged_tabs(
            "m77", base_dir=str(self.base_dir), base_data_dir=str(self.data_dir)
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_logged"], 2)

        updated_tabs = json.loads(tab_map_file.read_text(encoding="utf-8"))
        self.assertEqual(updated_tabs.get("com.tinh.vv.hi"), "CleanUser1")
        self.assertEqual(updated_tabs.get("com.tinh.vv.hj"), "CleanReplacement1")
        self.assertEqual(updated_tabs.get("com.tinh.vv.hk"), "CleanReplacement2")

        # Verify summary message contains dead and face details
        self.assertIn("cookie chết", res["message"])
        self.assertIn("FaceID", res["message"])

    def test_auto_login_live_tabs_and_reserve_replenishment(self):
        # 1. Device section in acc.txt only has 1 clean account and 1 duplicate
        acc_file = self.base_dir / "acc.txt"
        acc_file.write_text(
            "M77___(gag2)\n"
            "UserA:p1\n"
            "UserB:p2\n",
            encoding="utf-8"
        )

        # 2. Reserve file has additional clean accounts
        reserve_file = self.base_dir / "acc_du_phong.txt"
        reserve_file.write_text(
            "ReserveUser1:p_res1:_|WARNING:cookie_reserve1\n"
            "ReserveUser2:p_res2:_|WARNING:cookie_reserve2\n",
            encoding="utf-8"
        )

        # 3. Live tabs on device: Tab 3 and Tab 6 both running UserA (Duplicate!)
        # Tab 1 running UserA, Tab 2 running UserB
        live_users = {
            "com.tinh.vv.hi": "UserA",
            "com.tinh.vv.hj": "UserB",
            "com.tinh.vv.hk": "UserA", # Duplicate on Tab 3!
        }

        tab_map_file = self.base_dir / "tab_accounts.json"
        tab_map_file.write_text(json.dumps({
            "com.tinh.vv.hi": "UserA",
            "com.tinh.vv.hj": "UserB",
            "com.tinh.vv.hk": "OldStaticUser", # Overridden by live tab UserA
        }), encoding="utf-8")

        res = account_manager.auto_login_unlogged_tabs(
            "m77",
            base_dir=str(self.base_dir),
            base_data_dir=str(self.data_dir),
            live_tab_users=live_users,
        )
        self.assertTrue(res["ok"])
        self.assertGreaterEqual(res["total_logged"], 1)

        updated_tabs = json.loads(tab_map_file.read_text(encoding="utf-8"))
        self.assertEqual(updated_tabs.get("com.tinh.vv.hi"), "UserA")
        self.assertEqual(updated_tabs.get("com.tinh.vv.hj"), "UserB")
        # Tab 3 duplicate must be replaced by ReserveUser1 from reserve pool
        self.assertEqual(updated_tabs.get("com.tinh.vv.hk"), "ReserveUser1")

        # Verify cookie.txt was written with full User:Pass:Cookie format
        cookie_txt = self.base_dir / "cookie.txt"
        self.assertTrue(cookie_txt.is_file())
        cookie_content = cookie_txt.read_text(encoding="utf-8")
        self.assertIn("ReserveUser1:p_res1:_|WARNING:cookie_reserve1", cookie_content)

        # Verify tab_numbers and tool guidance
        self.assertEqual(res.get("tab_numbers"), "3,4")
        self.assertIn("👉 Các tab cần nạp trên Tool: 3,4", res["message"])
        self.assertIn("Vào Tool UgPhone", res["message"])

    def test_auto_login_replaces_alien_account_not_in_device(self):
        # acc.txt has 10 legitimate accounts for M77, including ItsMcKenzie266
        # But tab_accounts.json has VanessaJoseph403 on Tab 4 (not in acc.txt)
        acc_file = self.base_dir / "acc.txt"
        m77_accounts = [f"AccM77_{i}:pwd_{i}" for i in range(1, 10)] + ["ItsMcKenzie266:pwd_mckenzie"]
        acc_file.write_text("M77___(gag2)\n" + "\n".join(m77_accounts) + "\n", encoding="utf-8")

        data_tong = self.base_dir / "Data_Tong_Cookies.txt"
        data_tong.write_text("ItsMcKenzie266:pwd_mckenzie:_|WARNING:cookie_mckenzie\n", encoding="utf-8")

        tab_map_file = self.base_dir / "tab_accounts.json"
        assigned = {
            "com.tinh.vv.hi": "AccM77_1",
            "com.tinh.vv.hj": "AccM77_2",
            "com.tinh.vv.hk": "AccM77_3",
            "com.tinh.vv.hl": "VanessaJoseph403",  # ALIEN account! Not in M77 acc.txt!
            "com.tinh.vv.hm": "AccM77_4",
            "com.tinh.vv.hn": "AccM77_5",
            "com.tinh.vv.ho": "AccM77_6",
            "com.tinh.vv.hp": "AccM77_7",
            "com.tinh.vv.hq": "AccM77_8",
            "com.tinh.vv.hr": "AccM77_9",
        }
        tab_map_file.write_text(json.dumps(assigned), encoding="utf-8")

        res = account_manager.auto_login_unlogged_tabs(
            "m77", base_dir=str(self.base_dir), base_data_dir=str(self.data_dir)
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_logged"], 1)
        self.assertEqual(res.get("tab_numbers"), "4")

        # Tab 4 must be replaced by ItsMcKenzie266
        updated_tabs = json.loads(tab_map_file.read_text(encoding="utf-8"))
        self.assertEqual(updated_tabs.get("com.tinh.vv.hl"), "ItsMcKenzie266")

        # Verify reason mentions not_in_device
        self.assertEqual(res["logged_in"][0]["tab"], 4)
        self.assertIn("not_in_device: VanessaJoseph403", res["logged_in"][0]["replaced_reason"])

        # Verify cookie.txt has ItsMcKenzie266
        cookie_txt = self.base_dir / "cookie.txt"
        self.assertIn("ItsMcKenzie266:pwd_mckenzie:_|WARNING:cookie_mckenzie", cookie_txt.read_text(encoding="utf-8"))

    def test_auto_login_discards_corrupted_css_lines_in_reserve(self):
        # Setup acc.txt with only 1 user
        acc_file = self.base_dir / "acc.txt"
        acc_file.write_text("M77___(gag2)\nGoodUser:p1\n", encoding="utf-8")

        # Reserve file has corrupted CSS lines followed by a valid Roblox user
        reserve_file = self.base_dir / "acc_du_phong.txt"
        reserve_file.write_text(
            ");letter-spacing:0rem;line-height:1.4285714286\n"
            "--c-afwt, 500: bad_css_value\n"
            "invalid user name with spaces:pass123\n"
            "ValidReserveUser99:pwd_valid:_|WARNING:valid_cookie_val\n",
            encoding="utf-8"
        )

        tab_map_file = self.base_dir / "tab_accounts.json"
        tab_map_file.write_text(json.dumps({
            "com.tinh.vv.hi": "GoodUser",
            "com.tinh.vv.hj": "AlienUser404",  # Needs replacement
        }), encoding="utf-8")

        res = account_manager.auto_login_unlogged_tabs(
            "m77", base_dir=str(self.base_dir), base_data_dir=str(self.data_dir)
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_logged"], 1)
        self.assertEqual(res["logged_in"][0]["username"], "ValidReserveUser99")

        # Ensure no corrupted CSS was ever picked
        updated_tabs = json.loads(tab_map_file.read_text(encoding="utf-8"))
        self.assertEqual(updated_tabs.get("com.tinh.vv.hj"), "ValidReserveUser99")
        self.assertNotIn("letter-spacing", json.dumps(updated_tabs))
        self.assertNotIn("--c-afwt", json.dumps(updated_tabs))

    def test_auto_login_prioritizes_data_tong_cookies_over_legacy_reserve(self):
        # 1. Setup ban list
        ban_file = self.base_dir / "acc_bi_ban.txt"
        ban_file.write_text("BannedInDT:p_ban\n", encoding="utf-8")

        # 2. Setup acc.txt with M77 and M109
        acc_file = self.base_dir / "acc.txt"
        acc_file.write_text(
            "M77___(gag2)\n"
            "DeviceUser1:pwd1\n"
            "\n"
            "M109(gag2)____\n"
            "OtherDeviceUser:pwd_oth\n",
            encoding="utf-8"
        )

        # 3. Setup Data_Tong_Cookies.txt (Cloud SSOT)
        data_tong_file = self.base_dir / "Data_Tong_Cookies.txt"
        data_tong_file.write_text(
            "DataTongUser99:pwd_dt99:_|WARNING:cookie_from_datatong\n"
            "OtherDeviceUser:pwd_oth:_|WARNING:cookie_oth\n"  # Allocated to M109, must not be stolen!
            "BannedInDT:p_ban:_|WARNING:cookie_banned\n",    # Banned, must not be picked!
            encoding="utf-8"
        )

        # 4. Setup legacy reserve file (acc_khong_trung_moi.txt)
        legacy_file = self.base_dir / "acc_khong_trung_moi.txt"
        legacy_file.write_text(
            "LegacyReserveUser1:pwd_leg1\n",
            encoding="utf-8"
        )

        # 5. Tab 1 has DeviceUser1, Tab 2 has AlienUser to replace
        tab_map_file = self.base_dir / "tab_accounts.json"
        tab_map_file.write_text(json.dumps({
            "com.tinh.vv.hi": "DeviceUser1",
            "com.tinh.vv.hj": "UnknownAlienUser",
        }), encoding="utf-8")

        res = account_manager.auto_login_unlogged_tabs(
            "m77", base_dir=str(self.base_dir), base_data_dir=str(self.data_dir)
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_logged"], 2)

        # Tab 2 MUST prioritize DataTongUser99 over LegacyReserveUser1
        self.assertEqual(res["logged_in"][0]["tab"], 2)
        self.assertEqual(res["logged_in"][0]["username"], "DataTongUser99")
        self.assertEqual(res["logged_in"][0]["source"], "Data_Tong_Cookies.txt")

        # Tab 3 fallback to legacy reserve ONLY after Data_Tong has no more candidates
        self.assertEqual(res["logged_in"][1]["tab"], 3)
        self.assertEqual(res["logged_in"][1]["username"], "LegacyReserveUser1")
        self.assertEqual(res["logged_in"][1]["source"], "acc_khong_trung_moi.txt")

        # Verify cookie written to WebView SQLite
        db_file = self.data_dir / "com.tinh.vv.hj" / "app_webview" / "Default" / "Cookies"
        self.assertTrue(db_file.is_file())
        conn = sqlite3.connect(str(db_file))
        c = conn.cursor()
        c.execute("SELECT value FROM cookies WHERE name='.ROBLOSECURITY'")
        row = c.fetchone()
        conn.close()
        self.assertEqual(row[0], "_|WARNING:cookie_from_datatong")

        # Verify device cookie.txt has full User:Pass:Cookie format from Data_Tong
        cookie_txt = self.base_dir / "cookie.txt"
        self.assertIn("DataTongUser99:pwd_dt99:_|WARNING:cookie_from_datatong", cookie_txt.read_text(encoding="utf-8"))

        # Verify acc.txt recorded DataTongUser99 under M77
        acc_text = acc_file.read_text(encoding="utf-8")
        self.assertIn("DataTongUser99:pwd_dt99", acc_text)


if __name__ == "__main__":
    unittest.main()

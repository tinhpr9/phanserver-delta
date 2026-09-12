#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for agent.account_manager module:
- Parsing acc.txt sections without edge case collisions
- Banned account cleanup and dual-channel archiving
- Account addition into target section
- Roblox API ban status detection logic
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is in sys.path
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agent.account_manager import (
    parse_acc_sections,
    clean_banned_accounts,
    add_accounts,
    check_roblox_ban_status,
    run_full_checkban_pipeline,
)

SAMPLE_ACC_CONTENT = """
M77___(gag2) 
BreckenLife330:9W6DZB_yIhAIfJ3:
ShadowWoodrow820:tjp_QHJc4OJqCFz
Mega_Wiley623:h_vH1gKmnuDEjP
JeremiahWilkerson46:password123

M109(gag2)____
Cerys_a38540:MO_QFMPgWjzuD:
PureJannikGamer329:xbg8_hnVoLe760c:ps99:warn:
"""

SAMPLE_DATA_TONG_CONTENT = """BreckenLife330:9W6DZB_yIhAIfJ3:_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-to-your-account-and-to-steal-your-ROBUX-and-infrastructure|cookie_brecken
ShadowWoodrow820:tjp_QHJc4OJqCFz:_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-to-your-account-and-to-steal-your-ROBUX-and-infrastructure|cookie_shadow
Mega_Wiley623:h_vH1gKmnuDEjP:_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-to-your-account-and-to-steal-your-ROBUX-and-infrastructure|cookie_mega
JeremiahWilkerson46:password123:_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-to-your-account-and-to-steal-your-ROBUX-and-infrastructure|cookie_jeremiah
Cerys_a38540:MO_QFMPgWjzuD:_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-to-your-account-and-to-steal-your-ROBUX-and-infrastructure|cookie_cerys
"""


class TestAccountManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_acc_mgr_")
        self.acc_file = os.path.join(self.test_dir, "acc.txt")
        self.data_tong_file = os.path.join(self.test_dir, "Data_Tong_Cookies.txt")
        self.acc_bi_ban_file = os.path.join(self.test_dir, "acc_bi_ban.txt")
        self.nhat_ky_ban_file = os.path.join(self.test_dir, "nhat_ky_ban.txt")

        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(SAMPLE_ACC_CONTENT)
        with open(self.data_tong_file, "w", encoding="utf-8") as f:
            f.write(SAMPLE_DATA_TONG_CONTENT)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parse_acc_sections(self):
        sections = parse_acc_sections(SAMPLE_ACC_CONTENT)
        self.assertIn("m77", sections)
        self.assertIn("m109", sections)

        # Kiểm tra không nhận nhầm Mega_Wiley623 thành section header
        m77_accounts = [a["username"] for a in sections["m77"]["accounts"]]
        self.assertEqual(len(m77_accounts), 4)
        self.assertIn("Mega_Wiley623", m77_accounts)
        self.assertIn("BreckenLife330", m77_accounts)
        self.assertIn("JeremiahWilkerson46", m77_accounts)

        m109_accounts = [a["username"] for a in sections["m109"]["accounts"]]
        self.assertEqual(len(m109_accounts), 2)
        self.assertIn("Cerys_a38540", m109_accounts)

    def test_clean_banned_accounts(self):
        banned = ["Mega_Wiley623", "JeremiahWilkerson46"]
        res = clean_banned_accounts("m77", banned, base_dir=self.test_dir)

        self.assertEqual(res["banned_count"], 2)
        self.assertEqual(res["archived_cookies_count"], 2)

        # Kiểm tra acc.txt đã bị xóa 2 acc này
        with open(self.acc_file, "r", encoding="utf-8") as f:
            acc_content = f.read()
        self.assertNotIn("Mega_Wiley623", acc_content)
        self.assertNotIn("JeremiahWilkerson46", acc_content)
        self.assertIn("BreckenLife330", acc_content)
        self.assertIn("ShadowWoodrow820", acc_content)
        # Máy m109 không bị ảnh hưởng
        self.assertIn("Cerys_a38540", acc_content)

        # Kiểm tra Data_Tong_Cookies.txt đã xóa 2 acc này
        with open(self.data_tong_file, "r", encoding="utf-8") as f:
            dt_content = f.read()
        self.assertNotIn("cookie_mega", dt_content)
        self.assertNotIn("cookie_jeremiah", dt_content)
        self.assertIn("cookie_brecken", dt_content)

        # Kiểm tra acc_bi_ban.txt đã lưu đủ cookie
        with open(self.acc_bi_ban_file, "r", encoding="utf-8") as f:
            banned_content = f.read()
        self.assertIn("cookie_mega", banned_content)
        self.assertIn("cookie_jeremiah", banned_content)

        # Kiểm tra nhat_ky_ban.txt
        with open(self.nhat_ky_ban_file, "r", encoding="utf-8") as f:
            nk_content = f.read()
        self.assertIn("Mega_Wiley623:::banned", nk_content)
        self.assertIn("JeremiahWilkerson46:::banned", nk_content)

    def test_add_accounts(self):
        new_accs = [
            "NewPlayer1:Pass123",
            "NewPlayer2:Pass456:_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-to-your-account-and-to-steal-your-ROBUX-and-infrastructure|cookie_new2"
        ]
        res = add_accounts("m77", new_accs, base_dir=self.test_dir)
        self.assertEqual(res["added_count"], 2)
        self.assertEqual(res["cookies_added"], 1)

        with open(self.acc_file, "r", encoding="utf-8") as f:
            acc_content = f.read()
        self.assertIn("NewPlayer1:Pass123", acc_content)
        self.assertIn("NewPlayer2:Pass456", acc_content)

        # Kiểm tra vị trí chèn phải nằm trong m77 và trước m109
        idx_new = acc_content.find("NewPlayer1:Pass123")
        idx_m109 = acc_content.find("M109(gag2)____")
        self.assertTrue(idx_new < idx_m109, "Acc mới phải nằm trước section M109")

        # Kiểm tra Data_Tong_Cookies.txt có cookie mới
        with open(self.data_tong_file, "r", encoding="utf-8") as f:
            dt_content = f.read()
        self.assertIn("cookie_new2", dt_content)

    @patch("agent.account_manager.query_roblox_api")
    def test_check_roblox_ban_status(self, mock_api):
        # Mock batch response
        def mock_query(url, method="GET", data=None, retries=3):
            if "usernames/users" in url:
                return {
                    "data": [
                        {"requestedUsername": "liveuser", "id": 1001, "name": "LiveUser"},
                        {"requestedUsername": "banneduser", "id": 1002, "name": "BannedUser"},
                    ]
                }
            if "users/1001" in url:
                return {"isBanned": False, "id": 1001, "name": "LiveUser"}
            if "users/1002" in url:
                return {"isBanned": True, "id": 1002, "name": "BannedUser"}
            return None

        mock_api.side_effect = mock_query

        results = check_roblox_ban_status(["liveuser", "banneduser"])
        self.assertEqual(results["liveuser"]["isBanned"], False)
        self.assertEqual(results["banneduser"]["isBanned"], True)

    @patch("agent.account_manager.sync_to_google_drive")
    @patch("agent.account_manager.query_roblox_api")
    def test_run_full_checkban_pipeline(self, mock_api, mock_sync):
        def mock_query(url, method="GET", data=None, retries=3):
            if "usernames/users" in url:
                return {
                    "data": [
                        {"requestedUsername": "breckenlife330", "id": 101, "name": "BreckenLife330"},
                        {"requestedUsername": "shadowwoodrow820", "id": 102, "name": "ShadowWoodrow820"},
                        {"requestedUsername": "mega_wiley623", "id": 103, "name": "Mega_Wiley623"},
                        {"requestedUsername": "jeremiahwilkerson46", "id": 104, "name": "JeremiahWilkerson46"},
                    ]
                }
            if "users/101" in url or "users/102" in url:
                return {"isBanned": False}
            if "users/103" in url or "users/104" in url:
                return {"isBanned": True}
            return None

        mock_api.side_effect = mock_query
        mock_sync.return_value = {"acc.txt": "OK", "Data_Tong_Cookies.txt": "OK"}

        report = run_full_checkban_pipeline("m77", base_dir=self.test_dir)
        self.assertEqual(report["total"], 4)
        self.assertEqual(report["live"], 2)
        self.assertEqual(report["banned"], 2)
        self.assertEqual(set(report["banned_list"]), {"Mega_Wiley623", "JeremiahWilkerson46"})
        mock_sync.assert_called_once_with(base_dir=self.test_dir)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for agent.account_manager module:
- Parsing acc.txt sections without edge case collisions (Mega_Wiley623, M00nlUWarden, duplicate sections, top accounts)
- Banned account cleanup and dual-channel archiving
- Account addition into target section
- Roblox API ban status detection logic
- Quota-Guard TTL Cache (hit, miss, expiry, invalidation)
- HTTP 429 Exponential Backoff and Retry-After header handling
- Dual-storage .bak_<timestamp> backups for acc.txt and Data_Tong_Cookies.txt
- Rule 34 Google Drive in-place sync & File ID verification
- Automated replacement from reserve pool (acc_du_phong.txt)
"""

import os
import re
import sys
import time
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import json
import urllib.error

# Ensure project root is in sys.path
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agent.account_manager import (
    parse_acc_sections,
    clean_banned_accounts,
    add_accounts,
    delete_accounts,
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
        clear_ban_cache()
        self.test_dir = tempfile.mkdtemp(prefix="test_acc_mgr_")
        self.acc_file = os.path.join(self.test_dir, "acc.txt")
        self.data_tong_file = os.path.join(self.test_dir, "Data_Tong_Cookies.txt")
        self.acc_bi_ban_file = os.path.join(self.test_dir, "acc_bi_ban.txt")
        self.nhat_ky_ban_file = os.path.join(self.test_dir, "nhat_ky_ban.txt")
        self.acc_du_phong_file = os.path.join(self.test_dir, "acc_du_phong.txt")

        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(SAMPLE_ACC_CONTENT)
        with open(self.data_tong_file, "w", encoding="utf-8") as f:
            f.write(SAMPLE_DATA_TONG_CONTENT)

    def tearDown(self):
        clear_ban_cache()
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

    def test_parse_acc_sections_edge_cases(self):
        """
        Kiểm tra các trường hợp biên:
        - M00nlUWarden không bị nhận thành section header
        - Trùng lặp header section (nhiều header M0) được gộp lại
        - Tài khoản unassigned ở đầu file được ghi nhận
        """
        complex_content = """
TopUser1:pass1:keepsign
TopUser2:pass2:bf

M77___(gag2)
BreckenLife330:pass1
M00nlUWarden3200644:V0Ff6eS@R*@JTrHL:extra

M0_____(bf)
M0_User1:p1
M0_User2:p2

M110___(gag2)
User110:p110

M0___
M0_User3:p3
M0_User4:p4
"""
        sections = parse_acc_sections(complex_content)

        # 1. Kiểm tra top unassigned accounts
        self.assertIn("unassigned", sections)
        top_users = [a["username"] for a in sections["unassigned"]["accounts"]]
        self.assertEqual(top_users, ["TopUser1", "TopUser2"])

        # 2. Kiểm tra M00nlUWarden3200644 là tài khoản trong m77, không phải section
        m77_users = [a["username"] for a in sections["m77"]["accounts"]]
        self.assertIn("M00nlUWarden3200644", m77_users)
        self.assertNotIn("m00nluwarden3200644", sections)

        # 3. Kiểm tra gộp trùng lặp section m0 (M0_____(bf) và M0___)
        self.assertIn("m0", sections)
        m0_users = [a["username"] for a in sections["m0"]["accounts"]]
        self.assertEqual(len(m0_users), 4)
        self.assertEqual(m0_users, ["M0_User1", "M0_User2", "M0_User3", "M0_User4"])

    def test_clean_banned_accounts(self):
        banned = ["Mega_Wiley623", "JeremiahWilkerson46"]
        res = clean_banned_accounts("m77", banned, base_dir=self.test_dir)

        self.assertEqual(res["banned_count"], 2)
        self.assertEqual(res["removed_from_acc"], 2)
        self.assertEqual(res["archived_cookies_count"], 2)
        self.assertTrue(os.path.exists(res["backup_acc"]))
        self.assertTrue(os.path.exists(res["backup_data_tong"]))

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

    def test_clean_banned_accounts_with_username_target_and_all(self):
        """Kiểm tra clean_banned_accounts khi target là 'all' hoặc danh sách username rời."""
        # Clean với target là 'all'
        banned = ["BreckenLife330", "Cerys_a38540"]
        res = clean_banned_accounts("all", banned, base_dir=self.test_dir)
        self.assertEqual(res["banned_count"], 2)
        self.assertEqual(res["removed_from_acc"], 2)
        self.assertEqual(res["removed_per_section"], {"m77": 1, "m109": 1})

        # Clean với target là danh sách usernames
        banned2 = ["ShadowWoodrow820"]
        res2 = clean_banned_accounts("ShadowWoodrow820", banned2, base_dir=self.test_dir)
        self.assertEqual(res2["removed_from_acc"], 1)

    def test_add_accounts(self):
        new_accs = [
            "NewPlayer1:Pass123",
            "NewPlayer2:Pass456:_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-to-your-account-and-to-steal-your-ROBUX-and-infrastructure|cookie_new2"
        ]
        res = add_accounts("m77", new_accs, base_dir=self.test_dir)
        self.assertEqual(res["added_count"], 2)
        self.assertEqual(res["cookies_added"], 1)
        self.assertTrue(os.path.exists(res["backup_acc"]))
        self.assertTrue(os.path.exists(res["backup_data_tong"]))

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
        def mock_query(url, method="GET", data=None, retries=3, backoff_factor=1.0):
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

    @patch("agent.account_manager.query_roblox_api")
    def test_quota_guard_ttl_cache(self, mock_api):
        """Kiểm tra Quota-Guard Cache hit, miss, expiry và invalidation."""
        call_count = [0]

        def mock_query(url, method="GET", data=None, retries=3, backoff_factor=1.0):
            call_count[0] += 1
            if "usernames/users" in url:
                return {
                    "data": [
                        {"requestedUsername": "cached_user", "id": 2001, "name": "CachedUser"},
                        {"requestedUsername": "other_user", "id": 2002, "name": "OtherUser"},
                    ]
                }
            if "users/2001" in url:
                return {"isBanned": False, "id": 2001, "name": "CachedUser"}
            if "users/2002" in url:
                return {"isBanned": True, "id": 2002, "name": "OtherUser"}
            return None

        mock_api.side_effect = mock_query

        # Lần 1: Cache Miss, phải gọi API
        res1 = check_roblox_ban_status(["cached_user"], use_cache=True, cache_ttl=2)
        self.assertEqual(res1["cached_user"]["isBanned"], False)
        self.assertEqual(res1["cached_user"]["cached"], False)
        first_calls = call_count[0]
        self.assertGreater(first_calls, 0)

        stats = get_ban_cache_stats()
        self.assertEqual(stats["total_entries"], 1)
        self.assertEqual(stats["active_entries"], 1)

        # Lần 2: Cache Hit ngay lập tức (không gọi lại Roblox API cho cached_user)
        res2 = check_roblox_ban_status(["cached_user"], use_cache=True, cache_ttl=2)
        self.assertEqual(res2["cached_user"]["isBanned"], False)
        self.assertEqual(res2["cached_user"]["cached"], True)
        self.assertEqual(call_count[0], first_calls)  # Không có thêm cuộc gọi API nào

        # Lần 3: Truy vấn kết hợp cached_user và other_user mới
        res3 = check_roblox_ban_status(["cached_user", "other_user"], use_cache=True, cache_ttl=2)
        self.assertEqual(res3["cached_user"]["cached"], True)
        self.assertEqual(res3["other_user"]["cached"], False)
        self.assertEqual(res3["other_user"]["isBanned"], True)

        # Lần 4: Hủy cache từng phần (invalidate_ban_cache)
        invalidate_ban_cache(["cached_user"])
        stats_after_inv = get_ban_cache_stats()
        self.assertEqual(stats_after_inv["total_entries"], 1)  # Chỉ còn other_user

        # Lần 5: Xóa toàn bộ cache (clear_ban_cache)
        clear_ban_cache()
        stats_cleared = get_ban_cache_stats()
        self.assertEqual(stats_cleared["total_entries"], 0)

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_query_roblox_api_429_retry_after_and_backoff(self, mock_urlopen, mock_sleep):
        """Kiểm tra xử lý HTTP 429 và đọc header Retry-After."""
        # Mô phỏng lỗi 429 kèm header Retry-After
        headers_with_retry_after = MagicMock()
        headers_with_retry_after.get.side_effect = lambda k, default=None: "3" if k == "Retry-After" else default

        err_429 = urllib.error.HTTPError(
            url="https://users.roblox.com/v1/users/1",
            code=429,
            msg="Too Many Requests",
            hdrs=headers_with_retry_after,
            fp=None
        )

        success_response = MagicMock()
        success_response.read.return_value = b'{"isBanned": false, "id": 1, "name": "Player"}'
        success_response.__enter__.return_value = success_response

        mock_urlopen.side_effect = [err_429, success_response]

        data = query_roblox_api("https://users.roblox.com/v1/users/1", retries=3)
        self.assertIsNotNone(data)
        self.assertEqual(data["name"], "Player")
        # Kiểm tra sleep đúng số giây chỉ định trong Retry-After (3.0 giây)
        mock_sleep.assert_called_with(3.0)

    @patch("time.sleep")
    @patch("urllib.request.urlopen")
    def test_query_roblox_api_429_exponential_backoff_fallback(self, mock_urlopen, mock_sleep):
        """Kiểm tra xử lý HTTP 429 khi không có header Retry-After (lùi lũy thừa 2 ** attempt)."""
        headers_no_retry = MagicMock()
        headers_no_retry.get.return_value = None

        err_429 = urllib.error.HTTPError(
            url="https://users.roblox.com/v1/users/1",
            code=429,
            msg="Too Many Requests",
            hdrs=headers_no_retry,
            fp=None
        )

        success_response = MagicMock()
        success_response.read.return_value = b'{"status": "ok"}'
        success_response.__enter__.return_value = success_response

        mock_urlopen.side_effect = [err_429, success_response]

        data = query_roblox_api("https://users.roblox.com/v1/users/1", retries=3, backoff_factor=1.0)
        self.assertEqual(data, {"status": "ok"})
        # Lần thử 0: wait_time = 1.0 * (2.0 ** 0) = 1.0 giây
        mock_sleep.assert_called_with(1.0)

    @patch("agent.account_manager.verify_google_drive_file_ids")
    @patch("subprocess.run")
    def test_sync_to_google_drive_rule34_verification(self, mock_subproc, mock_verify):
        """Kiểm tra đồng bộ Google Drive in-place rclone copyto và cổng kiểm chứng File ID (Rule 34)."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = ""
        mock_proc.stdout = ""
        mock_subproc.return_value = mock_proc

        mock_verify.return_value = {
            "verified": True,
            "file_ids": {
                "acc.txt": RULE34_ACC_FILE_ID,
                "Data_Tong_Cookies.txt": RULE34_DATA_TONG_FILE_ID,
            }
        }

        res = sync_to_google_drive(base_dir=self.test_dir, verify_rule34=True)
        self.assertEqual(res["acc_sync"], True)
        self.assertEqual(res["data_tong_sync"], True)
        self.assertEqual(res["rule34_verified"], True)
        self.assertEqual(res["acc.txt"], "OK")
        self.assertEqual(res["Data_Tong_Cookies.txt"], "OK")

        # Xác thực lệnh rclone copyto được gọi chính xác
        calls = mock_subproc.call_args_list
        self.assertEqual(len(calls), 2)
        cmd1 = calls[0][0][0]
        self.assertIn("copyto", cmd1)
        self.assertIn("gdrive:acc.txt", cmd1)
        cmd2 = calls[1][0][0]
        self.assertIn("copyto", cmd2)
        self.assertIn("gdrive:Data_Tong_Cookies.txt", cmd2)

    @patch("subprocess.run")
    def test_verify_google_drive_file_ids_rejection(self, mock_subproc):
        """Kiểm tra Rule 34 phát hiện và từ chối khi File ID trên Google Drive bị sai lệch."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        # Trả về File ID acc.txt bị đổi khác với RULE34_ACC_FILE_ID
        mock_proc.stdout = f"WRONG_ID_99999999999999;acc.txt\n{RULE34_DATA_TONG_FILE_ID};Data_Tong_Cookies.txt\n"
        mock_subproc.return_value = mock_proc

        with self.assertRaises(RuntimeError) as ctx:
            verify_google_drive_file_ids()
        self.assertIn("Rule 34 Violated!", str(ctx.exception))

    def test_replace_banned_accounts_from_reserve(self):
        """Kiểm tra nạp bù tự động từ kho acc_du_phong.txt."""
        reserve_content = """# Danh sách acc dự trữ
ReserveUser1:Pass101
ReserveUser2:Pass102:_|WARNING:-DO-NOT-SHARE-THIS|cookie_reserve2
ReserveUser3:Pass103:_|WARNING:-DO-NOT-SHARE-THIS|cookie_reserve3
ReserveUser4:Pass104
"""
        with open(self.acc_du_phong_file, "w", encoding="utf-8") as f:
            f.write(reserve_content)

        # Nạp bù 2 acc cho dàn m77
        res = replace_banned_accounts_from_reserve("m77", num_needed=2, base_dir=self.test_dir)
        self.assertEqual(res["replaced_count"], 2)
        self.assertEqual(res["replaced_accounts"], ["ReserveUser1", "ReserveUser2"])
        self.assertEqual(res["remaining_reserve_count"], 2)

        # Kiểm tra acc.txt có tài khoản mới được chèn vào m77
        with open(self.acc_file, "r", encoding="utf-8") as f:
            acc_text = f.read()
        self.assertIn("ReserveUser1:Pass101", acc_text)
        self.assertIn("ReserveUser2:Pass102", acc_text)

        # Kiểm tra Data_Tong_Cookies.txt được bổ sung cookie
        with open(self.data_tong_file, "r", encoding="utf-8") as f:
            dt_text = f.read()
        self.assertIn("cookie_reserve2", dt_text)

        # Kiểm tra acc_du_phong.txt đã bị trừ đi 2 acc đã dùng
        with open(self.acc_du_phong_file, "r", encoding="utf-8") as f:
            remain_text = f.read()
        self.assertNotIn("ReserveUser1", remain_text)
        self.assertNotIn("ReserveUser2", remain_text)
        self.assertIn("ReserveUser3", remain_text)
        self.assertIn("ReserveUser4", remain_text)

        # Kiểm tra tệp sao lưu .bak_<timestamp> của acc_du_phong.txt đã được tạo
        bak_files = [f for f in os.listdir(self.test_dir) if f.startswith("acc_du_phong.txt.bak_")]
        self.assertTrue(len(bak_files) >= 1)

    @patch("agent.account_manager.sync_to_google_drive")
    @patch("agent.account_manager.query_roblox_api")
    def test_run_full_checkban_pipeline(self, mock_api, mock_sync):
        def mock_query(url, method="GET", data=None, retries=3, backoff_factor=1.0):
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

    @patch("agent.account_manager.sync_to_google_drive")
    @patch("agent.account_manager.query_roblox_api")
    def test_run_full_checkban_pipeline_with_auto_replace(self, mock_api, mock_sync):
        """Kiểm tra end-to-end pipeline với auto_replace=True tự động nạp bù tài khoản bị ban."""
        # Tạo kho dự trữ
        with open(self.acc_du_phong_file, "w", encoding="utf-8") as f:
            f.write("Replacer1:pwd1\nReplacer2:pwd2\n")

        def mock_query(url, method="GET", data=None, retries=3, backoff_factor=1.0):
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

        report = run_full_checkban_pipeline("m77", base_dir=self.test_dir, auto_replace=True)
        self.assertEqual(report["banned"], 2)
        self.assertIsNotNone(report["replace_result"])
        self.assertEqual(report["replace_result"]["replaced_count"], 2)
        self.assertEqual(report["replace_result"]["replaced_accounts"], ["Replacer1", "Replacer2"])

        # Kiểm tra acc.txt đã có Replacer1 và Replacer2
        with open(self.acc_file, "r", encoding="utf-8") as f:
            acc_content = f.read()
        self.assertIn("Replacer1:pwd1", acc_content)
        self.assertIn("Replacer2:pwd2", acc_content)
        self.assertNotIn("Mega_Wiley623", acc_content)

    @patch("agent.account_manager.query_roblox_api")
    def test_cli_multi_username_parsing(self, mock_api):
        """Kiểm tra logic phân tích cú pháp CLI khi cung cấp nhiều username (tgt = ' '.join(sys.argv[2:]))."""
        mock_api.return_value = {"data": []}
        cli_argv = ["account_manager.py", "checkban", "player_alpha", "player_beta", "player_gamma"]
        with patch.object(sys, "argv", cli_argv):
            tgt = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "m77"
            self.assertEqual(tgt, "player_alpha player_beta player_gamma")
            report = run_full_checkban_pipeline(tgt, base_dir=self.test_dir)
            self.assertEqual(report["total"], 3)
            self.assertIn("player_alpha", report["target"])

    @patch("urllib.request.urlopen")
    def test_check_zeropoint_cookie_status_parsing(self, mock_urlopen):
        """Kiểm tra phân tích kết quả ZeroPoint CookieChecker API chính xác 5 danh mục."""
        fake_cookie_1 = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-to-your-account-and-to-steal-your-ROBUX-and-infrastructure|" + "A" * 300
        fake_cookie_2 = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-to-your-account-and-to-steal-your-ROBUX-and-infrastructure|" + "B" * 300
        fake_cookie_3 = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-to-your-account-and-to-steal-your-ROBUX-and-infrastructure|" + "C" * 300
        fake_cookie_4 = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-to-your-account-and-to-steal-your-ROBUX-and-infrastructure|" + "D" * 300
        fake_cookie_5 = "_|WARNING:-DO-NOT-SHARE-THIS.--Sharing-this-will-allow-someone-to-log-in-to-your-account-and-to-steal-your-ROBUX-and-infrastructure|" + "E" * 300

        user_cookie_map = {
            "user_live": fake_cookie_1,
            "user_face": fake_cookie_2,
            "user_captcha": fake_cookie_3,
            "user_banned": fake_cookie_4,
            "user_dead": fake_cookie_5,
        }

        # Mock responses
        submit_resp = MagicMock()
        submit_resp.read.return_value = json.dumps({"session_id": "test_sess_123"}).encode("utf-8")
        submit_resp.__enter__.return_value = submit_resp

        status_resp = MagicMock()
        status_resp.read.return_value = json.dumps({
            "status": "completed",
            "download_files": {
                "alive": "/download/alive",
                "face_lock": "/download/face_lock",
                "captcha_lock": "/download/captcha_lock",
                "ban_warn": "/download/ban_warn",
                "dead": "/download/dead",
            }
        }).encode("utf-8")
        status_resp.__enter__.return_value = status_resp

        dl_alive = MagicMock()
        dl_alive.read.return_value = (fake_cookie_1 + "\n").encode("utf-8")
        dl_alive.__enter__.return_value = dl_alive

        dl_face = MagicMock()
        dl_face.read.return_value = (fake_cookie_2 + "\n").encode("utf-8")
        dl_face.__enter__.return_value = dl_face

        dl_captcha = MagicMock()
        dl_captcha.read.return_value = (fake_cookie_3 + "\n").encode("utf-8")
        dl_captcha.__enter__.return_value = dl_captcha

        dl_ban = MagicMock()
        dl_ban.read.return_value = (fake_cookie_4 + "\n").encode("utf-8")
        dl_ban.__enter__.return_value = dl_ban

        dl_dead = MagicMock()
        dl_dead.read.return_value = (fake_cookie_5 + "\n").encode("utf-8")
        dl_dead.__enter__.return_value = dl_dead

        def mock_urlopen_side_effect(req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "submit" in url:
                return submit_resp
            if "status/test_sess_123" in url:
                return status_resp
            if "download/test_sess_123/alive" in url:
                return dl_alive
            if "download/test_sess_123/face_lock" in url:
                return dl_face
            if "download/test_sess_123/captcha_lock" in url:
                return dl_captcha
            if "download/test_sess_123/ban_warn" in url:
                return dl_ban
            if "download/test_sess_123/dead" in url:
                return dl_dead
            return MagicMock()

        mock_urlopen.side_effect = mock_urlopen_side_effect

        from agent.account_manager import check_zeropoint_cookie_status
        res = check_zeropoint_cookie_status(user_cookie_map, api_key="test_key", timeout=5)

        self.assertEqual(res["user_live"]["status"], "ALIVE")
        self.assertEqual(res["user_face"]["status"], "FACE_LOCK")
        self.assertEqual(res["user_captcha"]["status"], "CAPTCHA_LOCK")
        self.assertEqual(res["user_banned"]["status"], "BANNED")
        self.assertEqual(res["user_dead"]["status"], "DEAD")

    def test_clean_banned_accounts_with_categories(self):
        """Kiểm tra lưu trữ phân loại riêng biệt cho Banned, FaceID Lock, Captcha Lock và Dead Cookies."""
        from agent.account_manager import clean_banned_accounts
        cat_map = {
            "breckenlife330": "FACE_LOCK",
            "shadowwoodrow820": "DEAD",
            "mega_wiley623": "BANNED",
            "jeremiahwilkerson46": "CAPTCHA_LOCK"
        }
        res = clean_banned_accounts(
            "m77",
            ["BreckenLife330", "ShadowWoodrow820", "Mega_Wiley623", "JeremiahWilkerson46"],
            base_dir=self.test_dir,
            categories_map=cat_map
        )
        self.assertEqual(res["removed_from_acc"], 4)

        paths = get_default_paths(self.test_dir)
        # Face lock files
        self.assertTrue(os.path.exists(paths["acc_face_lock_file"]))
        with open(paths["acc_face_lock_file"], "r") as f:
            self.assertIn("BreckenLife330", f.read())
        self.assertTrue(os.path.exists(paths["face_target_file"]))
        with open(paths["face_target_file"], "r") as f:
            self.assertIn("acc_face_lock.txt", f.read())

        # Dead cookies file
        self.assertTrue(os.path.exists(paths["acc_dead_cookies_file"]))
        with open(paths["acc_dead_cookies_file"], "r") as f:
            self.assertIn("ShadowWoodrow820", f.read())

        # Banned file
        self.assertTrue(os.path.exists(paths["acc_bi_ban_file"]))
        with open(paths["acc_bi_ban_file"], "r") as f:
            self.assertIn("Mega_Wiley623", f.read())

        # Captcha lock file
        self.assertTrue(os.path.exists(paths["acc_captcha_lock_file"]))
        with open(paths["acc_captcha_lock_file"], "r") as f:
            self.assertIn("JeremiahWilkerson46", f.read())

    @patch("agent.account_manager.sync_to_google_drive")
    @patch("agent.account_manager.check_zeropoint_cookie_status")
    def test_run_full_checkban_pipeline_with_zeropoint(self, mock_zp, mock_sync):
        """Kiểm tra run_full_checkban_pipeline nhận diện FaceID và Dead từ ZeroPoint và tự nạp bù."""
        # Tạo kho dự trữ
        with open(self.acc_du_phong_file, "w", encoding="utf-8") as f:
            f.write("NewReserve1:pass1\nNewReserve2:pass2\n")

        mock_zp.return_value = {
            "BreckenLife330": {"status": "ALIVE", "reason": "ZeroPoint: alive"},
            "ShadowWoodrow820": {"status": "FACE_LOCK", "reason": "ZeroPoint: face_lock"},
            "Mega_Wiley623": {"status": "BANNED", "reason": "ZeroPoint: banned"},
            "JeremiahWilkerson46": {"status": "ALIVE", "reason": "ZeroPoint: alive"},
        }
        mock_sync.return_value = {"acc.txt": "OK", "Data_Tong_Cookies.txt": "OK"}

        report = run_full_checkban_pipeline("m77", base_dir=self.test_dir, auto_replace=True)

        self.assertEqual(report["total"], 4)
        self.assertEqual(report["live"], 2)
        self.assertEqual(report["face_lock"], 1)
        self.assertEqual(report["banned"], 1)
        self.assertEqual(report["checker_engine"], "ZeroPoint")
        # Only BANNED account is replaced, FACE_LOCK account is preserved in acc.txt
        self.assertEqual(report["replace_result"]["replaced_count"], 1)
        self.assertEqual(report["replace_result"]["replaced_accounts"], ["NewReserve1"])

        # acc.txt has new account for banned, kept face_lock, removed banned
        with open(self.acc_file, "r") as f:
            acc_c = f.read()
        self.assertIn("NewReserve1:pass1", acc_c)
        self.assertIn("ShadowWoodrow820", acc_c)
        self.assertNotIn("Mega_Wiley623", acc_c)

    @patch("agent.account_manager.check_roblox_ban_status")
    @patch("urllib.request.urlopen")
    def test_check_roblox_cookie_status(self, mock_urlopen, mock_ban_status):
        """Kiểm tra check_roblox_cookie_status phân loại ALIVE, DEAD, FACE_LOCK, BANNED."""
        from agent.account_manager import check_roblox_cookie_status
        fake_ck = "_|WARNING:" + "x" * 300
        cookie_map = {
            "user_live": fake_ck,
            "user_dead": fake_ck,
            "user_facelock": fake_ck,
            "user_banned": fake_ck,
        }

        def mock_urlopen_side_effect(req, *args, **kwargs):
            headers = req.headers
            cookie_header = headers.get("Cookie", "")
            # Check user by mock behavior
            if "live" in req.full_url or "live" in str(req):
                pass
            return MagicMock()

        # Mock responses
        def side_effect(req, *args, **kwargs):
            cookie = req.headers.get("Cookie", "")
            # We can distinguish by cookie or mock urlopen per call
            resp = MagicMock()
            resp.read.return_value = json.dumps({"id": 12345, "name": "LiveUser"}).encode("utf-8")
            resp.__enter__.return_value = resp
            return resp

        # Test each individual user
        # 1. ALIVE
        resp_alive = MagicMock()
        resp_alive.read.return_value = json.dumps({"id": 12345, "name": "LiveUser"}).encode("utf-8")
        resp_alive.__enter__.return_value = resp_alive
        mock_urlopen.return_value = resp_alive
        res1 = check_roblox_cookie_status({"user_live": fake_ck})
        self.assertEqual(res1["user_live"]["status"], "ALIVE")

        # 2. DEAD (HTTP 401)
        err_401 = urllib.error.HTTPError(
            "https://users.roblox.com/v1/users/authenticated",
            401,
            "Unauthorized",
            {},
            MagicMock(read=lambda: b'{"errors":[{"code":9002,"message":"User is not authenticated"}]}')
        )
        mock_urlopen.side_effect = err_401
        res2 = check_roblox_cookie_status({"user_dead": fake_ck})
        self.assertEqual(res2["user_dead"]["status"], "DEAD")

        # 3. FACE_LOCK (HTTP 403 moderated + isBanned: False)
        err_403 = urllib.error.HTTPError(
            "https://users.roblox.com/v1/users/authenticated",
            403,
            "Forbidden",
            {},
            MagicMock(read=lambda: b'{"errors":[{"code":0,"message":"User is moderated"}]}')
        )
        mock_urlopen.side_effect = err_403
        mock_ban_status.return_value = {"user_facelock": {"isBanned": False}}
        res3 = check_roblox_cookie_status({"user_facelock": fake_ck})
        self.assertEqual(res3["user_facelock"]["status"], "FACE_LOCK")

        # 4. BANNED (HTTP 403 moderated + isBanned: True)
        mock_ban_status.return_value = {"user_banned": {"isBanned": True}}
        res4 = check_roblox_cookie_status({"user_banned": fake_ck})
        self.assertEqual(res4["user_banned"]["status"], "BANNED")

    @patch("agent.account_manager.sync_to_google_drive")
    @patch("agent.account_manager.check_zeropoint_cookie_status")
    @patch("agent.account_manager.check_roblox_cookie_status")
    def test_run_full_checkban_pipeline_fallback_to_roblox_cookie(self, mock_rbx_ck, mock_zp, mock_sync):
        """Kiểm tra khi ZeroPoint thất bại/rỗng, pipeline tự động fallback sang check_roblox_cookie_status."""
        # ZeroPoint fails or returns empty
        mock_zp.return_value = {}
        # Roblox direct cookie auth succeeds
        mock_rbx_ck.return_value = {
            "BreckenLife330": {"status": "ALIVE", "reason": "Roblox Session Valid"},
            "ShadowWoodrow820": {"status": "ALIVE", "reason": "Roblox Session Valid"},
            "Mega_Wiley623": {"status": "FACE_LOCK", "reason": "User is moderated"},
            "JeremiahWilkerson46": {"status": "DEAD", "reason": "Cookie expired"},
        }
        mock_sync.return_value = {"acc.txt": "OK", "Data_Tong_Cookies.txt": "OK"}

        # Tạo kho dự trữ
        with open(self.acc_du_phong_file, "w", encoding="utf-8") as f:
            f.write("ReserveA:pA\nReserveB:pB\n")

        # Inject real-length cookies into test data_tong_file
        with open(self.data_tong_file, "w", encoding="utf-8") as f:
            for u in ["BreckenLife330", "ShadowWoodrow820", "Mega_Wiley623", "JeremiahWilkerson46"]:
                f.write(f"{u}:pass:_|WARNING:{'A' * 300}\n")

        report = run_full_checkban_pipeline("m77", base_dir=self.test_dir, auto_replace=True)
        self.assertEqual(report["total"], 4)
        self.assertEqual(report["live"], 2)
        self.assertEqual(report["face_lock"], 1)
        self.assertEqual(report["dead"], 1)
        self.assertIsNone(report["replace_result"])
        # Both FACE_LOCK and DEAD accounts remain in acc.txt
        with open(self.acc_file, "r") as f:
            acc_c = f.read()
        self.assertIn("Mega_Wiley623", acc_c)
        self.assertIn("JeremiahWilkerson46", acc_c)

    def test_delete_accounts_specific_m_code(self):
        """Kiểm tra xóa tài khoản chỉ định khỏi section của máy cụ thể."""
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(
                "M77___(gag2)\n"
                "UserKeep1:pass1:\n"
                "UserDeleteMe:passDel:\n"
                "M109___(gag2)\n"
                "UserDeleteMe:passDelOtherMachine:\n"
                "UserKeep2:pass2:\n"
            )
        with open(self.data_tong_file, "w", encoding="utf-8") as f:
            f.write(
                "UserKeep1:pass1:cookie1\n"
                "UserDeleteMe:passDel:cookieDel\n"
                "UserKeep2:pass2:cookie2\n"
            )

        res = delete_accounts("m77", ["UserDeleteMe"], base_dir=self.test_dir, sync_drive=False)
        self.assertEqual(res["target"], "M77")
        self.assertEqual(res["removed_from_acc"], 1)
        self.assertEqual(res["removed_from_data_tong"], 1)

        with open(self.acc_file, "r", encoding="utf-8") as f:
            acc_content = f.read()
        # UserDeleteMe in M77 was deleted, but in M109 it remains because target was m77
        self.assertIn("M109___(gag2)\nUserDeleteMe:passDelOtherMachine:", acc_content)
        self.assertNotIn("M77___(gag2)\nUserKeep1:pass1:\nUserDeleteMe", acc_content)
        self.assertIn("UserKeep1:pass1:", acc_content)

        with open(self.data_tong_file, "r", encoding="utf-8") as f:
            data_content = f.read()
        self.assertNotIn("UserDeleteMe:passDel:cookieDel", data_content)
        self.assertIn("UserKeep1:pass1:cookie1", data_content)

        # Kiểm tra backup file được tạo
        self.assertTrue(os.path.exists(res["backup_acc"]))
        self.assertTrue(os.path.exists(res["backup_data_tong"]))

    def test_delete_accounts_all_targets(self):
        """Kiểm tra xóa tài khoản trên tất cả các section khi target là 'all'."""
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(
                "M77___(gag2)\n"
                "VanessaJoseph403:cowmama@934056:\n"
                "ShadowWoodrow820:pass2\n"
                "M109___(gag2)\n"
                "VanessaJoseph403:cowmama@934056:\n"
            )
        with open(self.data_tong_file, "w", encoding="utf-8") as f:
            f.write(
                "VanessaJoseph403:cowmama@934056:cookieValen\n"
                "ShadowWoodrow820:pass2:cookieShadow\n"
            )

        res = delete_accounts("all", ["VanessaJoseph403"], base_dir=self.test_dir, sync_drive=False)
        self.assertEqual(res["removed_from_acc"], 2)
        self.assertEqual(res["removed_from_data_tong"], 1)

        with open(self.acc_file, "r", encoding="utf-8") as f:
            acc_content = f.read()
        self.assertNotIn("VanessaJoseph403", acc_content)
        self.assertIn("ShadowWoodrow820", acc_content)

    @patch("agent.account_manager.sync_to_google_drive")
    def test_delete_accounts_with_drive_sync(self, mock_sync):
        """Kiểm tra gọi đồng bộ Google Drive khi sync_drive=True."""
        mock_sync.return_value = {"acc.txt": "OK", "Data_Tong_Cookies.txt": "OK"}
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write("M77___(gag2)\nTestUser:pass:\n")

        res = delete_accounts("m77", ["TestUser"], base_dir=self.test_dir, sync_drive=True)
        mock_sync.assert_called_once()
        self.assertEqual(res["removed_from_acc"], 1)
        self.assertEqual(res["sync_result"], {"acc.txt": "OK", "Data_Tong_Cookies.txt": "OK"})


if __name__ == "__main__":
    unittest.main()

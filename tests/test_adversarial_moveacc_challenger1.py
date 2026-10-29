#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Adversarial Stress Test Suite for Milestone 3 /moveacc.
Challenger 1 empirical verification harness.

Focus areas:
1. Regex precision boundary stress test (tricky M accounts, lookahead boundaries, M10 vs M109).
2. Random sampling stress test (random.sample, no duplicates, count=all, edge error validations, auto-creation).
3. Data_Tong_Cookies.txt invariance test (SHA-256, mtime_ns, inode, zero backups).
4. Local backup verification (.bak_<timestamp>, byte identity, exact original content).
5. Conservation of accounts under heavy random sequential transfers (zero duplication, zero loss).
6. Handling of duplicate accounts in source, extra colons in credentials, and whitespace/tabs in headers.
"""

import hashlib
import os
import pathlib
import random
import re
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

# Ensure project root is in sys.path
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent import account_manager
from agent.account_manager import move_accounts, parse_acc_sections


class TestAdversarialMoveAccChallenger1(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="challenger1_moveacc_")
        self.acc_file = os.path.join(self.test_dir, "acc.txt")
        self.data_tong_file = os.path.join(self.test_dir, "Data_Tong_Cookies.txt")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # =========================================================================
    # 1. REGEX PRECISION BOUNDARY STRESS TESTS
    # =========================================================================
    def test_01_regex_boundary_tricky_m_accounts_and_sections(self):
        """
        Adversarial Test 1:
        Mock acc.txt containing tricky account lines:
        - MegaRegan426:pass
        - Mega_Wiley623:pass
        - M00nlUWarden:pass
        - M426_Special:pass
        - M109_TrickUser:pass
        - M10(gag2)____ vs M109(gag2)____ vs M1(gag2) vs M100(gag2) vs M1090(gag2)
        Verify that parsing M109 NEVER matches MegaRegan426 or M10 or M109_TrickUser as section header.
        """
        tricky_acc_content = """M10(gag2)____
MegaRegan426:pass_mega426
Mega_Wiley623:pass_wiley623
M00nlUWarden:pass_moonwarden
M426_Special:pass_m426
M109_TrickUser:pass_m109trick
AccountInM10:pass_m10_extra

M109(gag2)____
M10_TrickUser:pass_m10trick
RegularUser109A:pass_109a
RegularUser109B:pass_109b

M1___(gag2)
UserM1:pass_m1

M100___(gag2)
UserM100:pass_m100

M1090___(gag2)
UserM1090:pass_m1090

M426___(gag2)
M426_User:pass_426user

M0___(gag2)
M00nlUWarden_InM0:pass_m0
"""
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(tricky_acc_content)

        # 1. Test parse_acc_sections
        sections = parse_acc_sections(tricky_acc_content)
        expected_keys = {"m10", "m109", "m1", "m100", "m1090", "m426", "m0"}
        self.assertEqual(
            set(sections.keys()),
            expected_keys,
            f"Expected section keys {expected_keys}, but got {set(sections.keys())}"
        )

        # Ensure tricky account lines are NOT treated as section headers
        for rogue_key in ["megaregan426", "mega_wiley623", "m00nluwarden", "m426_special", "m109_trickuser", "m10_trickuser"]:
            self.assertNotIn(
                rogue_key,
                sections,
                f"Account line '{rogue_key}' must NEVER become a section header key in sections dictionary!"
            )

        # Verify exact account counts in sections
        self.assertEqual(len(sections["m10"]["accounts"]), 6)
        self.assertEqual(len(sections["m109"]["accounts"]), 3)
        self.assertEqual(len(sections["m1"]["accounts"]), 1)
        self.assertEqual(len(sections["m100"]["accounts"]), 1)
        self.assertEqual(len(sections["m1090"]["accounts"]), 1)
        self.assertEqual(len(sections["m426"]["accounts"]), 1)
        self.assertEqual(len(sections["m0"]["accounts"]), 1)

        # Verify M109_TrickUser is an account under M10, NOT M109
        m10_usernames = [a["username"] for a in sections["m10"]["accounts"]]
        self.assertIn("M109_TrickUser", m10_usernames)
        self.assertIn("MegaRegan426", m10_usernames)
        self.assertIn("Mega_Wiley623", m10_usernames)
        self.assertIn("M00nlUWarden", m10_usernames)
        self.assertIn("M426_Special", m10_usernames)

        m109_usernames = [a["username"] for a in sections["m109"]["accounts"]]
        self.assertNotIn("M109_TrickUser", m109_usernames)
        self.assertIn("M10_TrickUser", m109_usernames)

        # 2. Test move_accounts from M109 to a new machine M77
        res1 = move_accounts("M109", "M77", count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertEqual(res1["source_m"], "M109")
        self.assertEqual(res1["target_m"], "M77")
        self.assertEqual(res1["count"], 1)
        self.assertEqual(res1["source_remaining_count"], 2)
        self.assertEqual(res1["target_current_count"], 1)

        moved_from_109 = res1["moved_accounts"][0]
        # Moved account MUST belong to original M109 accounts
        self.assertIn(moved_from_109, m109_usernames)
        # Moved account CANNOT be M109_TrickUser (which is in M10!)
        self.assertNotEqual(moved_from_109, "M109_TrickUser")

        # Verify updated acc.txt content: M10 must remain completely untouched!
        with open(self.acc_file, "r", encoding="utf-8") as f:
            updated_acc = f.read()

        updated_sections = parse_acc_sections(updated_acc)
        self.assertEqual(len(updated_sections["m10"]["accounts"]), 6, "M10 accounts must remain 6")
        self.assertEqual(len(updated_sections["m109"]["accounts"]), 2, "M109 accounts must be 2")
        self.assertEqual(len(updated_sections["m77"]["accounts"]), 1, "M77 accounts must be 1")
        self.assertEqual(len(updated_sections["m1"]["accounts"]), 1)
        self.assertEqual(len(updated_sections["m100"]["accounts"]), 1)
        self.assertEqual(len(updated_sections["m1090"]["accounts"]), 1)

        # 3. Test move_accounts from M10 to M77 (moving 2 accounts)
        res2 = move_accounts("m10", "m77", count=2, base_dir=self.test_dir, sync_drive=False)
        self.assertEqual(res2["source_remaining_count"], 4)
        self.assertEqual(res2["target_current_count"], 3)  # 1 earlier + 2 new

        with open(self.acc_file, "r", encoding="utf-8") as f:
            updated_acc2 = f.read()

        updated_sections2 = parse_acc_sections(updated_acc2)
        self.assertEqual(len(updated_sections2["m10"]["accounts"]), 4)
        self.assertEqual(len(updated_sections2["m109"]["accounts"]), 2)
        self.assertEqual(len(updated_sections2["m77"]["accounts"]), 3)

    def test_01b_regex_boundary_whitespace_and_formatting_variants(self):
        """Test section boundary regex against leading spaces, tabs, and format variations."""
        content = """   M109___(gag2)
UserA:passA

\tM77(gag2)____
UserB:passB

M88
UserC:passC

  M99 (gag2)
UserD:passD
"""
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(content)

        sections = parse_acc_sections(content)
        self.assertEqual(set(sections.keys()), {"m109", "m77", "m88", "m99"})

        # Move from M109 to M99
        res = move_accounts("  m109  ", "m99", count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertEqual(res["source_remaining_count"], 0)
        self.assertEqual(res["target_current_count"], 2)

    # =========================================================================
    # 2. RANDOM SAMPLING STRESS TESTS
    # =========================================================================
    def test_02_random_sampling_integrity_and_distribution(self):
        """
        Adversarial Test 2:
        Run move_accounts repeatedly with various counts (1, 2, all).
        Verify random.sample guarantees no duplicate selections in the same transfer.
        Verify distribution across multiple runs.
        """
        base_accounts = [f"User_Stress_{i:02d}:pass_{i:02d}" for i in range(1, 11)]

        # --- Test 2a: Count = 1 across 100 runs, verify all accounts get chosen ---
        selection_counts = {f"User_Stress_{i:02d}": 0 for i in range(1, 11)}
        for run_idx in range(100):
            # Reset acc.txt with 10 accounts in M109, and M77 empty
            content = "M109___(gag2)\n" + "\n".join(base_accounts) + "\n\nM77___(gag2)\n"
            with open(self.acc_file, "w", encoding="utf-8") as f:
                f.write(content)

            res = move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=False)
            self.assertEqual(res["count"], 1)
            self.assertEqual(len(res["moved_accounts"]), 1)
            self.assertEqual(res["source_remaining_count"], 9)
            self.assertEqual(res["target_current_count"], 1)

            chosen = res["moved_accounts"][0]
            selection_counts[chosen] += 1

        # Check that sampling is truly random (entropy > 0, at least 5 different accounts picked out of 10 in 100 runs)
        picked_unique = sum(1 for c in selection_counts.values() if c > 0)
        self.assertGreaterEqual(
            picked_unique, 5,
            f"Random sampling must pick diverse accounts across 100 runs, only picked {picked_unique} distinct accounts!"
        )

        # --- Test 2b: Count = 2, verify no duplicates within transfer ---
        for _ in range(50):
            content = "M109___(gag2)\n" + "\n".join(base_accounts) + "\n\nM77___(gag2)\n"
            with open(self.acc_file, "w", encoding="utf-8") as f:
                f.write(content)

            res = move_accounts("m109", "m77", count=2, base_dir=self.test_dir, sync_drive=False)
            self.assertEqual(len(res["moved_accounts"]), 2)
            self.assertEqual(len(set(res["moved_accounts"])), 2, "random.sample MUST guarantee no duplicate selections!")
            self.assertEqual(res["source_remaining_count"], 8)
            self.assertEqual(res["target_current_count"], 2)

        # --- Test 2c: Count = all (10 accounts) ---
        content = "M109___(gag2)\n" + "\n".join(base_accounts) + "\n\nM77___(gag2)\n"
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(content)

        res_all = move_accounts("m109", "m77", count=10, base_dir=self.test_dir, sync_drive=False)
        self.assertEqual(res_all["count"], 10)
        self.assertEqual(len(res_all["moved_accounts"]), 10)
        self.assertEqual(len(set(res_all["moved_accounts"])), 10)
        self.assertEqual(res_all["source_remaining_count"], 0)
        self.assertEqual(res_all["target_current_count"], 10)

        with open(self.acc_file, "r", encoding="utf-8") as f:
            updated_content = f.read()
        secs = parse_acc_sections(updated_content)
        self.assertIn("m109", secs, "Section header M109 must remain even when 0 accounts remain")
        self.assertEqual(len(secs["m109"]["accounts"]), 0)
        self.assertEqual(len(secs["m77"]["accounts"]), 10)

    def test_02b_validation_errors_and_edge_cases(self):
        """
        Verify all error validations:
        - count > available accounts
        - source == dest (exact, case-insensitive, stripped)
        - empty / invalid inputs
        - auto-creation of destination section at end of file
        """
        content = "M109___(gag2)\nUser1:p1\nUser2:p2\n\nM77___(gag2)\nUser77:p77\n"
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(content)

        # 1. count > available
        with self.assertRaises(ValueError) as ctx:
            move_accounts("m109", "m77", count=3, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("không đủ", str(ctx.exception))

        # 2. source == dest
        for s, d in [("m109", "m109"), ("M109", "m109"), (" m109 ", "M109")]:
            with self.assertRaises(ValueError) as ctx:
                move_accounts(s, d, count=1, base_dir=self.test_dir, sync_drive=False)
            self.assertIn("trùng nhau", str(ctx.exception))

        # 3. count <= 0 or invalid
        for invalid_cnt in [0, -1, -99, "abc", None]:
            with self.assertRaises(ValueError) as ctx:
                move_accounts("m109", "m77", count=invalid_cnt, base_dir=self.test_dir, sync_drive=False)
            self.assertIn("lớn hơn hoặc bằng 1", str(ctx.exception))

        # 4. empty or None source / dest
        for s, d in [("", "m77"), (None, "m77"), ("m109", ""), ("m109", None)]:
            with self.assertRaises(ValueError) as ctx:
                move_accounts(s, d, count=1, base_dir=self.test_dir, sync_drive=False)
            self.assertIn("không được để trống", str(ctx.exception))

        # 5. Non-existent source machine
        with self.assertRaises(ValueError) as ctx:
            move_accounts("m999", "m77", count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertIn("Không tìm thấy section máy nguồn", str(ctx.exception))

        # 6. Auto-creation of destination section when destination does not exist
        res_auto = move_accounts("m109", "m999", count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertEqual(res_auto["target_m"], "M999")
        self.assertEqual(res_auto["target_current_count"], 1)

        with open(self.acc_file, "r", encoding="utf-8") as f:
            created_content = f.read()

        self.assertIn("M999___(gag2)", created_content)
        secs_auto = parse_acc_sections(created_content)
        self.assertIn("m999", secs_auto)
        self.assertEqual(len(secs_auto["m999"]["accounts"]), 1)

        # Subsequent move to the auto-created section M999
        res_subsequent = move_accounts("m109", "m999", count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertEqual(res_subsequent["target_current_count"], 2)

        with open(self.acc_file, "r", encoding="utf-8") as f:
            subsequent_content = f.read()
        secs_sub = parse_acc_sections(subsequent_content)
        self.assertEqual(len(secs_sub["m999"]["accounts"]), 2)
        # Ensure M999 header is NOT duplicated
        self.assertEqual(subsequent_content.count("M999___(gag2)"), 1)

    # =========================================================================
    # 3. DATA_TONG_COOKIES.TXT INVARIANCE TESTS
    # =========================================================================
    def test_03_data_tong_cookies_strict_invariance_stress(self):
        """
        Adversarial Test 3:
        Compute SHA-256, byte length, and mtime_ns of Data_Tong_Cookies.txt.
        Execute transfers repeatedly across various configurations.
        Verify SHA-256 and mtime remain 100% identical, inode remains identical,
        and strictly no .bak file was created.
        """
        cookies_data = (
            "User1:pass1:_|WARNING:-DO-NOT-SHARE-THIS|cookie_data_1\n"
            "User2:pass2:_|WARNING:-DO-NOT-SHARE-THIS|cookie_data_2\n"
            "User3:pass3:_|WARNING:-DO-NOT-SHARE-THIS|cookie_data_3\n"
            "MegaRegan426:pass426:_|WARNING:-DO-NOT-SHARE-THIS|cookie_mega\n"
        )
        with open(self.data_tong_file, "w", encoding="utf-8") as f:
            f.write(cookies_data)

        acc_data = (
            "M109___(gag2)\n"
            "User1:pass1\n"
            "User2:pass2\n"
            "User3:pass3\n"
            "MegaRegan426:pass426\n"
            "\nM77___(gag2)\n"
            "NormalUser77:pass77\n"
        )
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(acc_data)

        # Capture initial state of Data_Tong_Cookies.txt
        with open(self.data_tong_file, "rb") as f:
            initial_bytes = f.read()
        initial_hash = hashlib.sha256(initial_bytes).hexdigest()
        initial_stat = os.stat(self.data_tong_file)
        initial_mtime_ns = initial_stat.st_mtime_ns
        initial_size = initial_stat.st_size
        initial_ino = initial_stat.st_ino

        # Run multiple moves in sequence
        time.sleep(0.02)
        res1 = move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=False)
        time.sleep(0.02)
        res2 = move_accounts("m109", "m88", count=1, base_dir=self.test_dir, sync_drive=False)
        time.sleep(0.02)
        res3 = move_accounts("m77", "m99", count=1, base_dir=self.test_dir, sync_drive=False)

        # Inspect Data_Tong_Cookies.txt after operations
        with open(self.data_tong_file, "rb") as f:
            current_bytes = f.read()
        current_hash = hashlib.sha256(current_bytes).hexdigest()
        current_stat = os.stat(self.data_tong_file)

        self.assertEqual(initial_hash, current_hash, "Data_Tong_Cookies.txt SHA-256 hash has been altered!")
        self.assertEqual(initial_size, current_stat.st_size, "Data_Tong_Cookies.txt size has changed!")
        self.assertEqual(initial_mtime_ns, current_stat.st_mtime_ns, "Data_Tong_Cookies.txt mtime_ns was modified!")
        self.assertEqual(initial_ino, current_stat.st_ino, "Data_Tong_Cookies.txt inode changed (file was replaced)!")

        # Verify no .bak files created for Data_Tong_Cookies.txt
        dir_files = os.listdir(self.test_dir)
        dt_backups = [f for f in dir_files if "Data_Tong_Cookies" in f and ".bak" in f]
        self.assertEqual(
            len(dt_backups), 0,
            f"Data_Tong_Cookies.txt must NEVER have backup files created, found: {dt_backups}"
        )

    # =========================================================================
    # 4. LOCAL BACKUP VERIFICATION TESTS
    # =========================================================================
    def test_04_local_backup_accuracy_and_timestamp(self):
        """
        Adversarial Test 4:
        Verify .bak_<timestamp> is created for acc.txt prior to file write,
        with exact original content (byte-for-byte).
        """
        original_content = (
            "M109___(gag2)\n"
            "AccAlpha:passA\n"
            "AccBeta:passB\n"
            "\nM77___(gag2)\n"
            "AccGamma:passG\n"
        )
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(original_content)

        orig_hash = hashlib.sha256(original_content.encode("utf-8")).hexdigest()

        # Execute move
        res = move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=False)
        backup_path = res.get("backup_acc")

        self.assertIsNotNone(backup_path, "backup_acc must be returned in move_accounts result")
        self.assertTrue(os.path.exists(backup_path), f"Backup file must exist at {backup_path}")

        # Check timestamp regex pattern: .bak_YYYYMMDD_HHMMSS
        self.assertTrue(
            bool(re.search(r"\.bak_\d{8}_\d{6}$", backup_path)),
            f"Backup filename format invalid: {backup_path}"
        )

        # Check backup content verbatim
        with open(backup_path, "rb") as f:
            backup_bytes = f.read()
        backup_hash = hashlib.sha256(backup_bytes).hexdigest()

        self.assertEqual(
            orig_hash, backup_hash,
            "Backup content does not match original acc.txt before modification!"
        )

        # Check that current acc.txt differs from backup
        with open(self.acc_file, "rb") as f:
            current_bytes = f.read()
        current_hash = hashlib.sha256(current_bytes).hexdigest()
        self.assertNotEqual(backup_hash, current_hash, "acc.txt was not modified!")

    # =========================================================================
    # 5. ACCOUNT CONSERVATION UNDER HEAVY SEQUENTIAL TRANSFERS
    # =========================================================================
    def test_05_account_conservation_under_heavy_sequential_moves(self):
        """
        Adversarial Test 5:
        Perform 50 sequential random transfers between random sections.
        Verify Account Conservation Invariant:
        - Total account count across all sections remains invariant.
        - The multiset of all usernames across all sections remains invariant.
        - Zero accounts duplicated, zero accounts dropped.
        - Data_Tong_Cookies.txt remains invariant throughout all 50 operations.
        """
        cookies_content = "MasterCookieStore:pass:cookie123\n"
        with open(self.data_tong_file, "w", encoding="utf-8") as f:
            f.write(cookies_content)
        cookie_hash = hashlib.sha256(cookies_content.encode("utf-8")).hexdigest()

        # Create 4 machines with 8 accounts each = 32 total accounts
        sections_data = {
            "M10": [f"User_M10_{i:02d}:pass10_{i}" for i in range(1, 9)],
            "M20": [f"User_M20_{i:02d}:pass20_{i}" for i in range(1, 9)],
            "M30": [f"User_M30_{i:02d}:pass30_{i}" for i in range(1, 9)],
            "M40": [f"User_M40_{i:02d}:pass40_{i}" for i in range(1, 9)],
        }

        all_initial_usernames = set()
        file_lines = []
        for sec, accs in sections_data.items():
            file_lines.append(f"{sec}___(gag2)")
            for a in accs:
                file_lines.append(a)
                all_initial_usernames.add(a.split(":")[0])
            file_lines.append("")

        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write("\n".join(file_lines))

        machine_pool = ["M10", "M20", "M30", "M40", "M50", "M60"]

        for step in range(50):
            with open(self.acc_file, "r", encoding="utf-8") as f:
                current_secs = parse_acc_sections(f.read())

            # Pick a source machine that has accounts
            sources_with_acc = [k for k, v in current_secs.items() if k.startswith("m") and len(v["accounts"]) > 0]
            if not sources_with_acc:
                break

            src = random.choice(sources_with_acc)
            available = len(current_secs[src]["accounts"])

            # Pick target distinct from source
            possible_targets = [m for m in machine_pool if m.lower() != src]
            dst = random.choice(possible_targets)

            count_to_move = random.randint(1, min(available, 3))

            res = move_accounts(src, dst, count=count_to_move, base_dir=self.test_dir, sync_drive=False)
            self.assertEqual(len(res["moved_accounts"]), count_to_move)

        # After 50 sequential random moves:
        with open(self.acc_file, "r", encoding="utf-8") as f:
            final_content = f.read()

        final_sections = parse_acc_sections(final_content)
        all_final_usernames = []
        for sec_name, sec_info in final_sections.items():
            if sec_name == "unassigned":
                continue
            for a in sec_info["accounts"]:
                all_final_usernames.append(a["username"])

        # INVARIANT 1: Total account count must be exactly 32
        self.assertEqual(
            len(all_final_usernames), 32,
            f"Account conservation violated! Expected 32 accounts, found {len(all_final_usernames)}"
        )

        # INVARIANT 2: Set of usernames must match original 32 usernames exactly
        self.assertEqual(
            set(all_final_usernames), all_initial_usernames,
            "Usernames set mismatch after 50 random transfers!"
        )

        # INVARIANT 3: No duplicates
        self.assertEqual(
            len(set(all_final_usernames)), 32,
            "Duplicate usernames found after transfers!"
        )

        # INVARIANT 4: Data_Tong_Cookies.txt hash unchanged
        with open(self.data_tong_file, "rb") as f:
            self.assertEqual(
                hashlib.sha256(f.read()).hexdigest(), cookie_hash,
                "Data_Tong_Cookies.txt was modified during 50 moves!"
            )

    # =========================================================================
    # 6. EDGE CASES: DUPLICATE USERNAMES AND EXTRA CREDENTIAL DATA
    # =========================================================================
    def test_06_duplicate_usernames_in_source_section(self):
        """
        Test behavior when source section contains duplicate usernames:
        - Moving 1 account cuts only 1 instance, leaving the duplicate in source.
        - Moving 2 accounts cuts both instances.
        """
        content = """M109___(gag2)
DupUser:pass1
DupUser:pass2
OtherUser:pass3

M77___(gag2)
User77:pass77
"""
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(content)

        # Move 1 DupUser specifically by mocking random.sample
        with mock.patch("random.sample") as mock_sample:
            secs = parse_acc_sections(content)
            # Pick first DupUser
            mock_sample.return_value = [secs["m109"]["accounts"][0]]
            res = move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=False)

        self.assertEqual(res["moved_accounts"], ["DupUser"])
        self.assertEqual(res["source_remaining_count"], 2)
        self.assertEqual(res["target_current_count"], 2)

        with open(self.acc_file, "r", encoding="utf-8") as f:
            post_content = f.read()

        post_secs = parse_acc_sections(post_content)
        m109_users = [a["username"] for a in post_secs["m109"]["accounts"]]
        # Exactly one DupUser remains in M109
        self.assertEqual(m109_users.count("DupUser"), 1)
        self.assertEqual(m109_users.count("OtherUser"), 1)

        m77_users = [a["username"] for a in post_secs["m77"]["accounts"]]
        # Exactly one DupUser in M77
        self.assertEqual(m77_users.count("DupUser"), 1)

    def test_07_credential_lines_with_extra_colons_and_tokens(self):
        """
        Test that account lines with extra colons (passwords with colons, auth tokens, etc.)
        are preserved 100% verbatim when transferred.
        """
        raw_account_line = "ComplexUser:pass:word:with:many:colons:and:token=XYZ=="
        content = f"""M109___(gag2)
{raw_account_line}

M77___(gag2)
"""
        with open(self.acc_file, "w", encoding="utf-8") as f:
            f.write(content)

        res = move_accounts("m109", "m77", count=1, base_dir=self.test_dir, sync_drive=False)
        self.assertEqual(res["moved_accounts"], ["ComplexUser"])

        with open(self.acc_file, "r", encoding="utf-8") as f:
            updated_content = f.read()

        self.assertIn(raw_account_line, updated_content, "Account line with extra colons was corrupted or truncated!")
        post_secs = parse_acc_sections(updated_content)
        self.assertEqual(len(post_secs["m77"]["accounts"]), 1)
        self.assertEqual(post_secs["m77"]["accounts"][0]["raw_line"].strip(), raw_account_line)


if __name__ == "__main__":
    unittest.main()

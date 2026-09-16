import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

import agent.agent as agent


class TestTabList(unittest.TestCase):
    def test_capabilities_includes_tab_list(self):
        self.assertIn("tab_list", agent.CAPABILITIES)

    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_extracts_running_tabs_and_accounts(self, mock_adb):
        # 1. Dumpsys activity output showing 3 running Roblox instances
        dumpsys_output = """
        ACTIVITY MANAGER ACTIVITIES (dumpsys activity activities)
        Stack #1:
          TaskRecord{31c1a21 #101 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{41e9b28 u0 com.tinh.vv.hi/com.roblox.client.ActivityProtocolLaunch t101}
          TaskRecord{31c1a22 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{8b1c430 u0 com.tinh.vv.hj/com.roblox.client.ActivityProtocolLaunch t102}
          TaskRecord{31c1a23 #103 A=com.tinh.vv.hk U=0}
            Hist #0: ActivityRecord{5a2b3c1 u0 com.tinh.vv.hk/com.roblox.client.ActivityProtocolLaunch t103}
        """

        # 2. Shared prefs outputs
        hi_prefs = '<map><string name="Username">username_a</string></map>'
        hj_prefs = '<map><string name="RobloxUsername">username_b</string></map>'
        hk_prefs = '<map><string name="OtherSetting">true</string></map>'

        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            if "com.tinh.vv.hi" in cmd_str:
                return hi_prefs
            if "com.tinh.vv.hj" in cmd_str:
                return hj_prefs
            if "com.tinh.vv.hk" in cmd_str:
                return hk_prefs
            return ""

        mock_adb.side_effect = side_effect

        tabs = agent.query_tab_list(tab_map_path="/dev/null", acc_path="/dev/null")
        self.assertEqual(len(tabs), 3)
        self.assertEqual(tabs[0]["tab"], 1)
        self.assertEqual(tabs[0]["package"], "com.tinh.vv.hi")
        self.assertEqual(tabs[0]["username"], "username_a")

        self.assertEqual(tabs[1]["tab"], 2)
        self.assertEqual(tabs[1]["package"], "com.tinh.vv.hj")
        self.assertEqual(tabs[1]["username"], "username_b")

        self.assertEqual(tabs[2]["tab"], 3)
        self.assertEqual(tabs[2]["package"], "com.tinh.vv.hk")
        self.assertIsNone(tabs[2]["username"])

    @mock.patch("agent.agent.run_adb_shell")
    def test_dumpsys_activity_class_name_not_falsely_matched(self, mock_adb):
        """Ensure /com.roblox.client.ActivityProtocolLaunch is not detected as running package com.roblox.client."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{123 #1 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{456 u0 com.tinh.vv.hi/com.roblox.client.ActivityProtocolLaunch t1}
        """
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys" in cmd_str:
                return dumpsys_output
            if "ps" in cmd_str:
                return "u0_a100 123 1 0 0 0 0 S com.tinh.vv.hi"
            if "shared_prefs" in cmd_str:
                return '<map><string name="Username">player1</string></map>'
            return ""

        mock_adb.side_effect = side_effect
        tabs = agent.query_tab_list()
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["tab"], 1)
        self.assertEqual(tabs[0]["package"], "com.tinh.vv.hi")
        self.assertEqual(tabs[0]["username"], "player1")

    @mock.patch("agent.agent.run_adb_shell")
    def test_tab_collision_prevention_with_unmapped_packages(self, mock_adb):
        """Ensure com.roblox.client and com.tinh.vv.hi running together do not both get Tab 1."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{1 #1 A=com.roblox.client U=0}
            Hist #0: ActivityRecord{11 u0 com.roblox.client/.MainActivity t1}
          TaskRecord{2 #2 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{22 u0 com.tinh.vv.hi/.MainActivity t2}
        """
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys" in cmd_str:
                return dumpsys_output
            return ""

        mock_adb.side_effect = side_effect
        tabs = agent.query_tab_list()
        self.assertEqual(len(tabs), 2)
        # com.tinh.vv.hi must have Tab 1 (canonical)
        # com.roblox.client must have Tab 2 (non-colliding)
        tab_nums = [t["tab"] for t in tabs]
        self.assertEqual(tab_nums, [1, 2])
        self.assertEqual(tabs[0]["package"], "com.tinh.vv.hi")
        self.assertEqual(tabs[1]["package"], "com.roblox.client")

    @mock.patch("agent.agent.run_adb_shell")
    def test_ps_discovery_when_dumpsys_empty(self, mock_adb):
        """Test fallback discovery via ps output when dumpsys returns empty."""
        ps_out = """
        USER      PID  PPID VSIZE  RSS   WCHAN            PC  NAME
        u0_a50   1001     1 12345 6789   00000000 00000000 S com.tinh.vv.hj
        u0_a51   1002     1 12345 6789   00000000 00000000 S com.tinh.vv.hk
        """
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys" in cmd_str:
                return ""
            if "ps" in cmd_str:
                return ps_out
            if "com.tinh.vv.hj" in cmd_str:
                return '<map><string name="Username">player_j</string></map>'
            return ""

        mock_adb.side_effect = side_effect
        tabs = agent.query_tab_list(tab_map_path="/dev/null", acc_path="/dev/null")
        self.assertEqual(len(tabs), 2)
        self.assertEqual(tabs[0]["tab"], 2)
        self.assertEqual(tabs[0]["package"], "com.tinh.vv.hj")
        self.assertEqual(tabs[0]["username"], "player_j")
        self.assertEqual(tabs[1]["tab"], 3)
        self.assertEqual(tabs[1]["package"], "com.tinh.vv.hk")
        self.assertIsNone(tabs[1]["username"])

    def test_extract_username_from_text_edge_cases(self):
        # XML tags with internal whitespace
        xml_with_spaces = '<string name="Username">  ProGamer99  </string>'
        self.assertEqual(agent.extract_username_from_text(xml_with_spaces), "ProGamer99")

        # XML with value attribute
        xml_attr = '<entry key="Roblox_Username" value="AlphaWolf_1" />'
        self.assertEqual(agent.extract_username_from_text(xml_attr), "AlphaWolf_1")

        # JSON formats
        json_text = '{"roblox_username": "RobloxPlayer42"}'
        self.assertEqual(agent.extract_username_from_text(json_text), "RobloxPlayer42")

        # Null / None / Unknown / ❓ strings should return None
        for bad_val in ["None", "null", "unknown", "false", "true", "undefined", "default", "guest", "❓"]:
            bad_xml = f'<string name="Username">{bad_val}</string>'
            self.assertIsNone(agent.extract_username_from_text(bad_xml))

        # Reverse attribute ordering: value before key/name
        xml_attr_rev = '<entry value="BetaWolf_2" key="Roblox_Username" />'
        self.assertEqual(agent.extract_username_from_text(xml_attr_rev), "BetaWolf_2")

        # DisplayName tag
        xml_display = '<string name="DisplayName">SuperStar88</string>'
        self.assertEqual(agent.extract_username_from_text(xml_display), "SuperStar88")

        # XML with other attributes before name
        xml_pre_attr = '<string id="custom" name="Username">PreAttrUser</string>'
        self.assertEqual(agent.extract_username_from_text(xml_pre_attr), "PreAttrUser")

        # XML entry tag with multiple attributes
        xml_entry_multi = '<entry id="10" key="username" enabled="true">EntryUser</entry>'
        self.assertEqual(agent.extract_username_from_text(xml_entry_multi), "EntryUser")

        # screen_name in JSON
        json_screen = '{"screen_name": "ScreenUser42"}'
        self.assertEqual(agent.extract_username_from_text(json_screen), "ScreenUser42")

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.query_tab_list")
    def test_handle_incoming_batch_action_tab_list(self, mock_query, mock_ack):
        mock_query.return_value = [
            {"tab": 1, "package": "com.tinh.vv.hi", "username": "username_a"},
            {"tab": 2, "package": "com.tinh.vv.hj", "username": "username_b"},
            {"tab": 3, "package": "com.tinh.vv.hk", "username": None},
        ]

        state = {}
        state_path = pathlib.Path("/tmp/test_state_tablist.json")
        links_path = pathlib.Path("/tmp/test_links_tablist.txt")
        message = {
            "protocol": "fleet-batch-v1",
            "action": "TAB_LIST",
            "action_id": "tablist-test-01",
            "target_device_ids": ["m77"],
        }

        handled = agent.handle_incoming_batch_action(
            message, "m77", "https://mock.worker/report", "mock_secret", state, state_path, links_path
        )
        self.assertTrue(handled)
        mock_ack.assert_called_once()
        k = mock_ack.call_args[1]
        self.assertEqual(k.get("batch_action"), "TAB_LIST")
        self.assertEqual(k.get("status"), "OPENED")
        self.assertTrue(k.get("executed"))
        details = json.loads(k.get("details", "{}"))
        self.assertEqual(len(details.get("tabs", [])), 3)
        self.assertEqual(details["tabs"][0]["username"], "username_a")
        self.assertIsNone(details["tabs"][2]["username"])

        # Test duplicate idempotency
        mock_query.reset_mock()
        mock_ack.reset_mock()
        handled_replay = agent.handle_incoming_batch_action(
            message, "m77", "https://mock.worker/report", "mock_secret", state, state_path, links_path
        )
        self.assertTrue(handled_replay)
        mock_query.assert_not_called()
        mock_ack.assert_called_once()

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.query_tab_list")
    def test_handle_incoming_batch_action_error_handling(self, mock_query, mock_ack):
        mock_query.side_effect = RuntimeError("ADB dumpsys timeout mock error")
        state = {}
        state_path = pathlib.Path("/tmp/test_state_tablist_err.json")
        links_path = pathlib.Path("/tmp/test_links_tablist_err.txt")
        message = {
            "protocol": "fleet-batch-v1",
            "action": "TAB_LIST",
            "action_id": "tablist-err-01",
            "target_device_ids": ["m77"],
        }
        handled = agent.handle_incoming_batch_action(
            message, "m77", "https://mock.worker/report", "mock_secret", state, state_path, links_path
        )
        self.assertTrue(handled)
        mock_ack.assert_called_once()
        k = mock_ack.call_args[1]
        self.assertEqual(k.get("status"), "FAILED")
        self.assertFalse(k.get("executed"))
        self.assertIn("ADB dumpsys timeout", str(k.get("reason")))


    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_multi_user_profile_support(self, mock_adb):
        """Test that Roblox instances running under secondary Android users (/data/user/10/...) are discovered."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{999 #1 A=com.tinh.vv.hl U=10}
            Hist #0: ActivityRecord{888 u10 com.tinh.vv.hl/com.roblox.client.ActivityProtocolLaunch t1}
        """
        user_10_prefs = '<map><string name="Username">MultiUserHero</string></map>'

        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys" in cmd_str:
                return dumpsys_output
            if "/data/user/" in cmd_str and "com.tinh.vv.hl" in cmd_str:
                return user_10_prefs
            return ""

        mock_adb.side_effect = side_effect
        tabs = agent.query_tab_list()
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["tab"], 4)
        self.assertEqual(tabs[0]["package"], "com.tinh.vv.hl")
        self.assertEqual(tabs[0]["username"], "MultiUserHero")

    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_zero_tabs(self, mock_adb):
        """Test that empty list is returned cleanly when no Roblox instances are running."""
        mock_adb.return_value = ""
        tabs = agent.query_tab_list()
        self.assertEqual(tabs, [])

    def test_extract_username_appstorage_json_structure(self):
        """Test extract_username_from_text on real appStorage.json payload with active and signed-out users."""
        sample_json = json.dumps({
            "PreviousAccountsList": json.dumps({
                "1111111": {"username": "OldUser123", "signOutTimestamp": 1000}
            }),
            "Username": "ActiveRobloxUser99",
            "DisplayName": "ActiveRobloxUser99",
            "UserId": "2222222"
        })
        self.assertEqual(agent.extract_username_from_text(sample_json), "ActiveRobloxUser99")

        # Key variations
        self.assertEqual(agent.extract_username_from_text('{"RobloxUsername": "Hero_01"}'), "Hero_01")
        self.assertEqual(agent.extract_username_from_text('{"username": "Hero_02"}'), "Hero_02")
        self.assertEqual(agent.extract_username_from_text('{"CurrentUsername": "Hero_03"}'), "Hero_03")

    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_tier1_appstorage_su_and_run_as(self, mock_adb):
        """Test Tier 1: Reading appStorage.json via su and run-as commands."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{101 #101 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{1 u0 com.tinh.vv.hi/com.roblox.client.Activity t101}
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.Activity t102}
        """
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys" in cmd_str:
                return dumpsys_output
            # Tab 1: cat fails, but su -c succeeds
            if "com.tinh.vv.hi" in cmd_str and "su -c" in cmd_str:
                return '{"Username": "SuUser99"}'
            # Tab 2: cat and su fail, but run-as succeeds
            if "com.tinh.vv.hj" in cmd_str and "run-as" in cmd_str:
                return '{"Username": "RunAsUser88"}'
            return ""

        mock_adb.side_effect = side_effect
        tabs = agent.query_tab_list()
        self.assertEqual(len(tabs), 2)
        self.assertEqual(tabs[0]["tab"], 1)
        self.assertEqual(tabs[0]["username"], "SuUser99")
        self.assertEqual(tabs[1]["tab"], 2)
        self.assertEqual(tabs[1]["username"], "RunAsUser88")

    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_tier4_acc_txt_fallback_correlation(self, mock_adb):
        """Test Tier 4: Config fallback to acc.txt when app data is blocked by sandbox permissions."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{101 #101 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{1 u0 com.tinh.vv.hi/com.roblox.client.Activity t101}
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.Activity t102}
          TaskRecord{103 #103 A=com.tinh.vv.hk U=0}
            Hist #0: ActivityRecord{3 u0 com.tinh.vv.hk/com.roblox.client.Activity t103}
        """
        # ADB shell returns nothing for file reads (simulating sandbox permission denied)
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys" in cmd_str:
                return dumpsys_output
            return ""

        mock_adb.side_effect = side_effect

        mock_acc_content = """
M77___(gag2)
AccountOne:pass1:
AccountTwo:pass2:
AccountThree:pass3:
"""
        import tempfile
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix="_acc.txt", delete=False) as tf:
            tf.write(mock_acc_content)
            tf.flush()
            temp_acc_path = tf.name

        try:
            tabs = agent.query_tab_list(device_id="m77", acc_path=temp_acc_path)
            self.assertEqual(len(tabs), 3)
            self.assertEqual(tabs[0]["tab"], 1)
            self.assertEqual(tabs[0]["username"], "AccountOne (acc.txt)")
            self.assertEqual(tabs[1]["tab"], 2)
            self.assertEqual(tabs[1]["username"], "AccountTwo (acc.txt)")
            self.assertEqual(tabs[2]["tab"], 3)
            self.assertEqual(tabs[2]["username"], "AccountThree (acc.txt)")
        finally:
            pathlib.Path(temp_acc_path).unlink(missing_ok=True)

    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_precedence_real_username_over_acc_txt(self, mock_adb):
        """Test that real username from appStorage.json has precedence over acc.txt fallback."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{101 #101 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{1 u0 com.tinh.vv.hi/com.roblox.client.Activity t101}
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.Activity t102}
        """
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys" in cmd_str:
                return dumpsys_output
            # Tab 1 has readable appStorage.json
            if "com.tinh.vv.hi" in cmd_str and "appStorage.json" in cmd_str:
                return '{"Username": "RealPlayerOne"}'
            # Tab 2 is blocked
            return ""

        mock_adb.side_effect = side_effect

        mock_acc_content = """
M77___(gag2)
FallbackAcc1:pass1:
FallbackAcc2:pass2:
"""
        import tempfile
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix="_acc.txt", delete=False) as tf:
            tf.write(mock_acc_content)
            tf.flush()
            temp_acc_path = tf.name

        try:
            tabs = agent.query_tab_list(device_id="m77", acc_path=temp_acc_path)
            self.assertEqual(len(tabs), 2)
            # Tab 1 should use real username without suffix
            self.assertEqual(tabs[0]["username"], "RealPlayerOne")
            # Tab 2 should fallback to acc.txt with suffix
            self.assertEqual(tabs[1]["username"], "FallbackAcc2 (acc.txt)")
        finally:
            pathlib.Path(temp_acc_path).unlink(missing_ok=True)

    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_acc_txt_boundary_and_server_links_fallback(self, mock_adb):
        """Test Tab index beyond acc.txt accounts and server_links.txt fallback."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{101 #101 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{1 u0 com.tinh.vv.hi/com.roblox.client.Activity t101}
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.Activity t102}
        """
        def side_effect(cmd, **kwargs):
            if "dumpsys" in str(cmd):
                return dumpsys_output
            return ""

        mock_adb.side_effect = side_effect

        # acc.txt only has 1 account for M77
        mock_acc_content = """
M77___(gag2)
OnlyOneAcc:pass1:
"""
        import tempfile
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix="_acc.txt", delete=False) as tf:
            tf.write(mock_acc_content)
            tf.flush()
            temp_acc_path = tf.name

        try:
            tabs = agent.query_tab_list(device_id="m77", acc_path=temp_acc_path)
            self.assertEqual(len(tabs), 2)
            self.assertEqual(tabs[0]["username"], "OnlyOneAcc (acc.txt)")
            # Tab 2 has no account in M77 section -> None
            self.assertIsNone(tabs[1]["username"])
        finally:
            pathlib.Path(temp_acc_path).unlink(missing_ok=True)

    def test_format_tab_list_html(self):
        """Test Telegram HTML report formatting and safety escaping."""
        tabs = [
            {"tab": 2, "package": "com.tinh.vv.hj", "username": "username_real"},
            {"tab": 3, "package": "com.tinh.vv.hk", "username": "username_acc (acc.txt)"},
            {"tab": 4, "package": "com.tinh.vv.hl", "username": None},
            {"tab": 5, "package": "com.tinh.vv.hm", "username": "<script>alert('xss')&bad</script>"},
        ]
        html_out = agent.format_tab_list_html("m77", tabs)
        self.assertIn("📱 <b>Tab List — M77</b>", html_out)
        self.assertIn("Tab 2: username_real", html_out)
        self.assertIn("Tab 3: username_acc (acc.txt)", html_out)
        self.assertIn("Tab 4: ❓ (unknown)", html_out)
        self.assertIn("Tab 5: &lt;script&gt;alert('xss')&amp;bad&lt;/script&gt;", html_out)

        # Empty tabs
        empty_out = agent.format_tab_list_html("m77", [])
        self.assertIn("(Không có tab Roblox nào đang chạy)", empty_out)

    def test_format_tab_list_html_banned_tabs(self):
        """Test formatting of banned tabs: username (baned) or baned if unknown."""
        tabs = [
            {"tab": 1, "package": "com.tinh.vv.hi", "username": "AlivePlayer99", "is_banned": False},
            {"tab": 2, "package": "com.tinh.vv.hj", "username": "BannedPlayer100", "is_banned": True},
            {"tab": 3, "package": "com.tinh.vv.hk", "username": "Zephyra_Pro731 (baned)"},
            {"tab": 4, "package": "com.tinh.vv.hl", "username": None, "is_banned": True},
            {"tab": 5, "package": "com.tinh.vv.hm", "username": "❓", "status": "BANNED"},
        ]
        html_out = agent.format_tab_list_html("m77", tabs)
        self.assertIn("Tab 1: AlivePlayer99", html_out)
        self.assertIn("Tab 2: BannedPlayer100 (baned)", html_out)
        self.assertIn("Tab 3: Zephyra_Pro731 (baned)", html_out)
        self.assertIn("Tab 4: baned", html_out)
        self.assertIn("Tab 5: baned", html_out)

    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_detects_banned_from_acc_bi_ban(self, mock_adb):
        """Test that query_tab_list automatically flags accounts present in acc_bi_ban.txt."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{101 #101 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{101 u0 com.tinh.vv.hi/com.roblox.client.ActivityProtocolLaunch t101}
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{102 u0 com.tinh.vv.hj/com.roblox.client.ActivityProtocolLaunch t102}
        """
        def side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            if "com.tinh.vv.hi" in cmd_str:
                return '<map><string name="Username">CleanUser1</string></map>'
            if "com.tinh.vv.hj" in cmd_str:
                return '<map><string name="Username">Zephyra_Pro731</string></map>'
            return ""

        mock_adb.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = pathlib.Path(tmpdir)
            ban_file = tmppath / "acc_bi_ban.txt"
            ban_file.write_text("Zephyra_Pro731:::banned on M77\n", encoding="utf-8")
            acc_file = tmppath / "acc.txt"
            acc_file.write_text("# m77\nCleanUser1:pass\nZephyra_Pro731:pass\n", encoding="utf-8")

            tabs = agent.query_tab_list(device_id="m77", acc_path=acc_file, tab_map_path=tmppath / "tab_accounts.json")
            self.assertEqual(len(tabs), 2)
            self.assertFalse(tabs[0]["is_banned"])
            self.assertEqual(tabs[0]["username"], "CleanUser1")

            self.assertTrue(tabs[1]["is_banned"])
            self.assertEqual(tabs[1]["status"], "BANNED")

            html_out = agent.format_tab_list_html("m77", tabs)
            self.assertIn("Tab 1: CleanUser1", html_out)
            self.assertIn("Tab 2: Zephyra_Pro731 (baned)", html_out)

    @mock.patch("subprocess.run")
    def test_run_adb_shell_tries_multi_su_fallbacks(self, mock_run):
        """Test that run_adb_shell tries /system/bin/su and /system/xbin/su when standard su fails."""
        call_count = 0
        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            cmd_list = cmd if isinstance(cmd, list) else [cmd]
            # Succeed only on /system/xbin/su
            if cmd_list[0] == "/system/xbin/su":
                res = mock.MagicMock()
                res.returncode = 0
                res.stdout = "root_success\n"
                return res
            # All earlier commands fail
            res = mock.MagicMock()
            res.returncode = 1
            res.stdout = ""
            return res

        mock_run.side_effect = fake_run
        out = agent.run_adb_shell("id")
        self.assertEqual(out.strip(), "root_success")
        self.assertGreaterEqual(call_count, 4)

    def test_get_acc_fallback_username_edge_cases(self):
        """Test edge cases for get_acc_fallback_username: invalid tabs, missing file, empty content."""
        self.assertIsNone(agent.get_acc_fallback_username(0, device_id="m77"))
        self.assertIsNone(agent.get_acc_fallback_username(-1, device_id="m77"))
        self.assertIsNone(agent.get_acc_fallback_username(1, device_id=None, acc_path="/non/existent/path.txt"))

        # Test case insensitivity (M77 vs m77) and header with spaces
        mock_acc = "\n\nM77___(gag2)  \nUserM77_1:pass1:\nUserM77_2:pass2:extra\n"
        import tempfile
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix="_acc.txt", delete=False) as tf:
            tf.write(mock_acc)
            tf.flush()
            tpath = tf.name
        try:
            # Uppercase device_id
            self.assertEqual(agent.get_acc_fallback_username(1, device_id="M77", acc_path=tpath), "UserM77_1 (acc.txt)")
            # Lowercase device_id
            self.assertEqual(agent.get_acc_fallback_username(2, device_id="m77", acc_path=tpath), "UserM77_2 (acc.txt)")
            # Out of bounds
            self.assertIsNone(agent.get_acc_fallback_username(3, device_id="m77", acc_path=tpath))
        finally:
            pathlib.Path(tpath).unlink(missing_ok=True)

    def test_get_server_links_fallback_username(self):
        """Test fallback extracting username from server_links.txt if present in pkg,url,username format."""
        links_content = "com.tinh.vv.hi,https://roblox.com/games/123?linkCode=abc,LinkUser42\n"
        import tempfile
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix="_links.txt", delete=False) as tf:
            tf.write(links_content)
            tf.flush()
            tpath = tf.name
        try:
            u = agent.get_server_links_fallback_username(1, "com.tinh.vv.hi", links_path=tpath)
            self.assertEqual(u, "LinkUser42")
            # Unmatched pkg
            self.assertIsNone(agent.get_server_links_fallback_username(2, "com.tinh.vv.hj", links_path=tpath))
        finally:
            pathlib.Path(tpath).unlink(missing_ok=True)

    def test_extract_username_quoted_and_stringified_json(self):
        """Test extraction from stringified JSON, quoted values, dotted keys, and nested dicts."""
        self.assertEqual(agent.extract_username_from_text('{"Username": "\\"QuotedUser\\""}'), "QuotedUser")
        self.assertEqual(agent.extract_username_from_text('{"Username": "\'SingleQuoted\'"}'), "SingleQuoted")
        self.assertEqual(agent.extract_username_from_text('{"Roblox.CurrentUser.Username": "DottedUser"}'), "DottedUser")
        self.assertEqual(agent.extract_username_from_text('{"CurrentUser": {"name": "NestedDictUser"}}'), "NestedDictUser")
        self.assertEqual(agent.extract_username_from_text('{"CurrentUser": "{\\"Username\\": \\"StringDictUser\\"}"}'), "StringDictUser")

    def test_extract_username_previous_accounts_isolation(self):
        """Test that signed-out accounts in PreviousAccountsList do not override active user or leak when logged out."""
        # Active user present alongside PreviousAccountsList
        text_with_active = '{"PreviousAccountsList": "[{\\"Username\\": \\"SignedOut1\\"}]", "Username": "\\"ActiveUser\\""}'
        self.assertEqual(agent.extract_username_from_text(text_with_active), "ActiveUser")

        # Only signed-out accounts present (user logged out)
        text_signed_out_only = '{"PreviousAccountsList": "[{\\"Username\\": \\"SignedOutOnly\\"}]"}'
        self.assertIsNone(agent.extract_username_from_text(text_signed_out_only))

    def test_extract_username_xml_quoted_and_entities(self):
        """Test extraction from XML shared preferences with quotes and HTML entities."""
        xml_quoted = '<map><string name="Username">"XmlQuoted"</string></map>'
        self.assertEqual(agent.extract_username_from_text(xml_quoted), "XmlQuoted")

        xml_entity = '<map><string name="Username">&quot;XmlEntity&quot;</string></map>'
        self.assertEqual(agent.extract_username_from_text(xml_entity), "XmlEntity")

    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_tier3_multiline_dumpsys_intent_extras(self, mock_adb):
        """Test Tier 3: dumpsys where intent extras are on indented lines following the activity record."""
        dumpsys_multiline = """
        Stack #1:
          TaskRecord{101 #101 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{1 u0 com.tinh.vv.hi/com.roblox.client.Activity t101}
              Intent { act=android.intent.action.MAIN flg=0x10000000 cmp=com.tinh.vv.hi/com.roblox.client.Activity }
                extras: Bundle[{username=RealIntentPlayer}]
        """
        def side_effect(cmd, **kwargs):
            if "dumpsys" in str(cmd):
                return dumpsys_multiline
            return ""

        mock_adb.side_effect = side_effect
        tabs = agent.query_tab_list()
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["tab"], 1)
        self.assertEqual(tabs[0]["username"], "RealIntentPlayer")

    def test_get_acc_fallback_username_leading_zero_and_comments(self):
        """Test that device IDs with leading zeros (e.g. m077) match sections and comment lines are skipped."""
        mock_acc = """
M77___(gag2)
# Internal note: do not use this line
ValidUser1:pass1:
# Another comment
ValidUser2:pass2:
"""
        import tempfile
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix="_acc.txt", delete=False) as tf:
            tf.write(mock_acc)
            tf.flush()
            tpath = tf.name
        try:
            # m077 should match M77 section
            self.assertEqual(agent.get_acc_fallback_username(1, device_id="m077", acc_path=tpath), "ValidUser1 (acc.txt)")
            # Tab 2 should skip comments and map to ValidUser2
            self.assertEqual(agent.get_acc_fallback_username(2, device_id="m077", acc_path=tpath), "ValidUser2 (acc.txt)")
        finally:
            pathlib.Path(tpath).unlink(missing_ok=True)

    def test_format_tab_list_html_non_int_tabs(self):
        """Test format_tab_list_html does not crash when tab properties are non-integer strings."""
        tabs = [
            {"tab": "?", "username": "MysteryUser"},
            {"tab": None, "tab_index": "2", "username": "TabTwoUser"},
        ]
        out = agent.format_tab_list_html("m77", tabs)
        self.assertIn("Tab ?: MysteryUser", out)
        self.assertIn("Tab 2: TabTwoUser", out)

    @mock.patch("subprocess.run")
    def test_run_adb_shell_su_prefix_handling(self, mock_run):
        """Test that run_adb_shell does not double-nest su when command starts with su -c."""
        executed_cmds = []
        def fake_run(cmd, **kwargs):
            executed_cmds.append(cmd)
            res = mock.MagicMock()
            if cmd[0] == "/system/bin/su":
                res.returncode = 0
                res.stdout = "su_success\n"
                return res
            res.returncode = 1
            res.stdout = ""
            return res

        mock_run.side_effect = fake_run
        out = agent.run_adb_shell("su -c 'cat test'")
        self.assertEqual(out.strip(), "su_success")
        found = any(c == ["/system/bin/su", "-c", "cat test"] for c in executed_cmds)
        self.assertTrue(found, f"Expected unnested su command, got: {executed_cmds}")

    def test_extract_username_concatenated_json_multi_user(self):
        """Test extraction from concatenated JSON streams where first object is signed-out and second has active user."""
        # Multi-user stream: user 0 has only PreviousAccountsList, user 10 has active user
        concat_stream = '{"PreviousAccountsList": "[{\\"Username\\": \\"OldUser\\"}]"}{"Username": "ActiveUser10"}'
        self.assertEqual(agent.extract_username_from_text(concat_stream), "ActiveUser10")

        # Concatenated with theme/empty object first
        concat_empty_first = '{"theme": "dark"}{"Username": "ActiveSecond"}'
        self.assertEqual(agent.extract_username_from_text(concat_empty_first), "ActiveSecond")

        # Multi-object where all objects are signed out
        concat_all_signed_out = '{"PreviousAccountsList": "[{\\"Username\\": \\"Old1\\"}]"}{"PreviousAccountsList": "[{\\"Username\\": \\"Old2\\"}]"}'
        self.assertIsNone(agent.extract_username_from_text(concat_all_signed_out))

    def test_extract_username_null_bytes_and_control_chars(self):
        """Test that UTF-16LE null bytes and unescaped control characters in JSON are handled cleanly."""
        utf16_like = "{\x00\"\x00U\x00s\x00e\x00r\x00n\x00a\x00m\x00e\x00\"\x00:\x00 \x00\"\x00U\x00t\x00f\x00U\x00s\x00e\x00r\x00\"\x00}\x00"
        self.assertEqual(agent.extract_username_from_text(utf16_like), "UtfUser")

        # JSON with control character (strict=False)
        control_char_json = '{"Username": "Ctrl\x01Player"}'
        self.assertEqual(agent.extract_username_from_text(control_char_json), "CtrlPlayer")

    def test_extract_username_xml_historical_tags_rejected(self):
        """Test that XML tags with historical keywords (PreviousUsername, LastLoggedInUsername) are rejected."""
        xml_only_prev = '<map><string name="PreviousUsername">SignedOutXml</string></map>'
        self.assertIsNone(agent.extract_username_from_text(xml_only_prev))

        xml_with_active = '<map><string name="PreviousUsername">SignedOutXml</string><string name="Username">ActiveXmlUser</string></map>'
        self.assertEqual(agent.extract_username_from_text(xml_with_active), "ActiveXmlUser")

    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_tier3_dumpsys_non_breaking_blocks(self, mock_adb):
        """Test Tier 3: dumpsys does not break out of loop when earlier block has >25 lines before Intent extras."""
        dumpsys_large_earlier_block = """
        Stack #0:
          mResumedActivity: ActivityRecord{1 u0 com.tinh.vv.hi/com.roblox.client.Activity}
            line1
            line2
            line3
            line4
            line5
            line6
            line7
            line8
            line9
            line10
            line11
            line12
            line13
            line14
            line15
            line16
            line17
            line18
            line19
            line20
            line21
            line22
            line23
            line24
            line25
            line26
            line27
            line28
        Stack #1:
          TaskRecord{101 #101 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{1 u0 com.tinh.vv.hi/com.roblox.client.Activity t101}
              Intent { act=android.intent.action.MAIN }
                extras: Bundle[{username=DeepHiddenPlayer}]
        """
        def side_effect(cmd, **kwargs):
            if "dumpsys" in str(cmd):
                return dumpsys_large_earlier_block
            return ""

        mock_adb.side_effect = side_effect
        tabs = agent.query_tab_list(acc_path="/dev/null")
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["username"], "DeepHiddenPlayer")

    def test_get_acc_fallback_username_type_robustness(self):
        """Test get_acc_fallback_username handles string tab_num, non-string acc_path, and plain usernames without colons."""
        mock_acc = """
M77___(gag2)
PlainUser1
PlainUser2
"""
        import tempfile
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8-sig", suffix="_acc.txt", delete=False) as tf:
            tf.write(mock_acc)
            tf.flush()
            tpath = tf.name
        try:
            # String tab_num "1" should work without TypeError
            self.assertEqual(agent.get_acc_fallback_username("1", device_id="m77", acc_path=tpath), "PlainUser1 (acc.txt)")
            self.assertEqual(agent.get_acc_fallback_username("2", device_id="m77", acc_path=tpath), "PlainUser2 (acc.txt)")
            # Invalid dict acc_path should not crash with TypeError
            self.assertIsNone(agent.get_acc_fallback_username(1, device_id="nonexistent_dev_999", acc_path={"invalid": "type"}))
        finally:
            pathlib.Path(tpath).unlink(missing_ok=True)

    def test_format_tab_list_html_robustness_and_limits(self):
        """Test format_tab_list_html filters None elements, non-dict objects, and respects message limits."""
        tabs = [
            None,
            "not a dict",
            {"tab": 1, "username": "RealUser1"},
            {"tab": 2, "username": {"invalid": "object"}},
        ]
        out = agent.format_tab_list_html("m77", tabs)
        self.assertIn("Tab 1: RealUser1", out)
        self.assertIn("Tab 2: ❓ (unknown)", out)

        # Huge number of tabs to trigger Telegram 3900-char truncation bound
        many_tabs = [{"tab": i, "username": f"User_{i}_" + "x" * 40} for i in range(1, 100)]
        out_huge = agent.format_tab_list_html("m77", many_tabs)
        self.assertIn("... và còn", out_huge)
        self.assertLessEqual(len(out_huge), 4096)

    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_multi_user_paths_resolution(self, mock_adb):
        """Test that query_tab_list detects user 10 from dumpsys and queries /data/user/10/ and run-as --user 10."""
        executed_cmds = []
        dumpsys_u10 = """
        TaskRecord{101 #101 A=com.tinh.vv.hi U=10}
        Hist #0: ActivityRecord{1 u10 com.tinh.vv.hi/com.roblox.client.Activity t101}
        """
        def fake_adb(cmd, **kwargs):
            cmd_str = str(cmd)
            executed_cmds.append(cmd_str)
            if "dumpsys" in cmd_str:
                return dumpsys_u10
            if "run-as --user 10" in cmd_str:
                return '{"Username": "UserInSpace10"}'
            return ""

        mock_adb.side_effect = fake_adb
        tabs = agent.query_tab_list(acc_path="/dev/null")
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["username"], "UserInSpace10")
        # Verify /data/user/10/ was checked in shell commands
        found_u10_path = any("/data/user/10/" in c for c in executed_cmds)
        self.assertTrue(found_u10_path, f"Expected /data/user/10/ in commands, got: {executed_cmds}")
        # Verify run-as --user 10 was checked
        found_run_as_u10 = any("run-as --user 10" in c for c in executed_cmds)
        self.assertTrue(found_run_as_u10, f"Expected run-as --user 10 in commands, got: {executed_cmds}")

    @mock.patch("subprocess.run")
    def test_run_adb_shell_xbin_and_bin_su_commands(self, mock_run):
        """Test that run_adb_shell handles /system/bin/su and /system/xbin/su prefixes unnested."""
        executed_cmds = []
        def fake_run(cmd, **kwargs):
            executed_cmds.append(cmd)
            res = mock.MagicMock()
            if cmd[0] in ("/system/bin/su", "/system/xbin/su"):
                res.returncode = 0
                res.stdout = "su_ok\n"
                return res
            res.returncode = 1
            res.stdout = ""
            return res

        mock_run.side_effect = fake_run
        out1 = agent.run_adb_shell("/system/bin/su -c 'echo 1'")
        self.assertEqual(out1.strip(), "su_ok")
        self.assertTrue(any(c == ["/system/bin/su", "-c", "echo 1"] for c in executed_cmds))

        executed_cmds.clear()
        out2 = agent.run_adb_shell("/system/xbin/su -c 'echo 2'")
        self.assertEqual(out2.strip(), "su_ok")
        self.assertTrue(any(c == ["/system/bin/su", "-c", "echo 2"] or c == ["/system/xbin/su", "-c", "echo 2"] for c in executed_cmds))

    def test_extract_username_nested_historical_blocks_no_leak(self):
        """Test that unquoted/corrupted nested PreviousAccountsList blocks do not leak signed-out accounts."""
        # Multi-entry nested historical block without outer { - should return None
        raw_prev = 'PreviousAccountsList: {"111": {"username": "OldUser1"}, "222": {"username": "OldUser2"}}'
        self.assertIsNone(agent.extract_username_from_text(raw_prev))

        # Nested historical block followed by real active user - should extract active user
        with_active = 'PreviousAccountsList: {"111": {"username": "OldUser1"}, "222": {"username": "OldUser2"}} Username: ActiveRealPlayer'
        self.assertEqual(agent.extract_username_from_text(with_active), "ActiveRealPlayer")

    def test_extract_username_user_dict_and_user_name(self):
        """Test extracting username from user/User dictionaries and user string values."""
        self.assertEqual(agent.extract_username_from_text('{"user": {"name": "PlayerFromUserDict"}}'), "PlayerFromUserDict")
        self.assertEqual(agent.extract_username_from_text('{"User": {"name": "PlayerFromCapUserDict"}}'), "PlayerFromCapUserDict")
        self.assertEqual(agent.extract_username_from_text('{"user": "PlayerDirectUser"}'), "PlayerDirectUser")

    def test_extract_username_kv_patterns_user_name_and_roblox_user(self):
        """Test KV activity patterns matching user_name, roblox_user, and current_username."""
        self.assertEqual(agent.extract_username_from_text("Intent extras: Bundle[{user_name=PlayerKvName}]"), "PlayerKvName")
        self.assertEqual(agent.extract_username_from_text("Intent extras: Bundle[{roblox_user=PlayerKvRoblox}]"), "PlayerKvRoblox")
        self.assertEqual(agent.extract_username_from_text("Intent extras: Bundle[{current_username=PlayerKvCur}]"), "PlayerKvCur")

    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_tier3_dumpsys_blank_lines_inside_block(self, mock_adb):
        """Test that dumpsys with blank lines between ActivityRecord and Intent extras does not drop capture."""
        dumpsys_with_blanks = """
        Stack #1:
          TaskRecord{101 #101 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{1 u0 com.tinh.vv.hi/com.roblox.client.Activity t101}

              Intent { act=android.intent.action.MAIN }

                extras: Bundle[{username=BlankLinePlayer}]
        """
        def fake_adb(cmd, **kwargs):
            if "dumpsys" in str(cmd):
                return dumpsys_with_blanks
            return ""

        mock_adb.side_effect = fake_adb
        tabs = agent.query_tab_list(acc_path="/dev/null")
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["username"], "BlankLinePlayer")

    @mock.patch("subprocess.run")
    def test_run_adb_shell_safe_unquoting_chained_quotes(self, mock_run):
        """Test that run_adb_shell does not corrupt chained single quotes like 'echo 1' && 'echo 2'."""
        executed_cmds = []
        def fake_run(cmd, **kwargs):
            executed_cmds.append(cmd)
            res = mock.MagicMock()
            if cmd[0] in ("/system/bin/su", "/system/xbin/su", "su"):
                res.returncode = 0
                res.stdout = "done\n"
                return res
            res.returncode = 1
            res.stdout = ""
            return res

        mock_run.side_effect = fake_run
        agent.run_adb_shell("/system/bin/su -c \"'echo 1' && 'echo 2'\"")
        # Ensure inner command preserved separate quotes and did not strip outer edges incorrectly
        matching_su = [c for c in executed_cmds if c[0] in ("/system/bin/su", "/system/xbin/su", "su")]
        self.assertTrue(any(c[2] == "'echo 1' && 'echo 2'" for c in matching_su), f"Unexpected su cmd: {matching_su}")

    def test_get_acc_fallback_username_device_variations_plain_acc(self):
        """Test get_acc_fallback_username matches M77___ across device_id variants with plain usernames."""
        mock_acc = """
M77___(gag2)
AlphaUser
BetaUser
"""
        import tempfile
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8-sig", suffix="_acc.txt", delete=False) as tf:
            tf.write(mock_acc)
            tf.flush()
            tpath = tf.name
        try:
            self.assertEqual(agent.get_acc_fallback_username(1, device_id="device-77", acc_path=tpath), "AlphaUser (acc.txt)")
            self.assertEqual(agent.get_acc_fallback_username(1, device_id="m077", acc_path=tpath), "AlphaUser (acc.txt)")
            self.assertEqual(agent.get_acc_fallback_username(1, device_id="M77___(gag2)", acc_path=tpath), "AlphaUser (acc.txt)")
            self.assertEqual(agent.get_acc_fallback_username(1, device_id="77", acc_path=tpath), "AlphaUser (acc.txt)")
            self.assertEqual(agent.get_acc_fallback_username(2, device_id="device-77", acc_path=tpath), "BetaUser (acc.txt)")
            # Different device should return None
            self.assertIsNone(agent.get_acc_fallback_username(1, device_id="m78", acc_path=tpath))
        finally:
            pathlib.Path(tpath).unlink(missing_ok=True)

    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_direct_files_appstorage_fallback(self, mock_adb):
        """Test Tier 1 queries legacy files/appStorage.json and extracts username."""
        executed_cmds = []
        dumpsys_out = """
        Hist #0: ActivityRecord{1 u0 com.tinh.vv.hi/com.roblox.client.Activity}
        """
        def fake_adb(cmd, **kwargs):
            cmd_str = str(cmd)
            executed_cmds.append(cmd_str)
            if "dumpsys" in cmd_str:
                return dumpsys_out
            if "files/appStorage.json" in cmd_str and "files/appData" not in cmd_str:
                return '{"Username": "LegacyAppStorageUser"}'
            return ""

        mock_adb.side_effect = fake_adb
        tabs = agent.query_tab_list(acc_path="/dev/null")
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["username"], "LegacyAppStorageUser")

    def test_get_server_links_fallback_tab_index_mapping(self):
        """Test get_server_links_fallback_username supports tab-index lines (e.g. 1,link,username)."""
        mock_links = """
1,https://www.roblox.com/games/123,TabOneUser
Tab 2,https://www.roblox.com/games/456,TabTwoUser
com.tinh.vv.hk,https://www.roblox.com/games/789,TabThreeUser
"""
        import tempfile
        with tempfile.NamedTemporaryFile("w+", encoding="utf-8-sig", suffix="_links.txt", delete=False) as tf:
            tf.write(mock_links)
            tf.flush()
            tpath = tf.name
        try:
            self.assertEqual(agent.get_server_links_fallback_username(1, pkg="com.tinh.vv.hi", links_path=tpath), "TabOneUser")
            self.assertEqual(agent.get_server_links_fallback_username(2, pkg="com.tinh.vv.hj", links_path=tpath), "TabTwoUser")
            self.assertEqual(agent.get_server_links_fallback_username(3, pkg="com.tinh.vv.hk", links_path=tpath), "TabThreeUser")
            self.assertIsNone(agent.get_server_links_fallback_username(4, pkg="com.tinh.vv.hl", links_path=tpath))
        finally:
            pathlib.Path(tpath).unlink(missing_ok=True)

    def test_strict_tab_package_canonical_mapping_r1(self):
        """R1: Test 100% strict 10 Tab to 10 Clone Package canonical mappings."""
        expected_mappings = {
            1: "com.tinh.vv.hi",
            2: "com.tinh.vv.hj",
            3: "com.tinh.vv.hk",
            4: "com.tinh.vv.hl",
            5: "com.tinh.vv.hm",
            6: "com.tinh.vv.hn",
            7: "com.tinh.vv.ho",
            8: "com.tinh.vv.hp",
            9: "com.tinh.vv.hq",
            10: "com.tinh.vv.hr",
        }
        for tab_num, pkg in expected_mappings.items():
            self.assertEqual(agent.TAB_PACKAGE_MAP.get(pkg), tab_num)
            self.assertEqual(agent.PACKAGE_TAB_MAP.get(pkg), tab_num)
            self.assertEqual(agent.TAB_TO_PACKAGE_MAP.get(tab_num), pkg)

    def test_tab_accounts_file_auto_creation_and_defaults_r2(self):
        """R2: Test tab_accounts.json creation, verified default data, and persistence."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = pathlib.Path(tmpdir) / "test_tab_accounts.json"
            self.assertFalse(test_file.exists())

            # Auto-create via ensure_tab_accounts_file
            agent.ensure_tab_accounts_file(test_file)
            self.assertTrue(test_file.is_file())

            data = agent.load_tab_accounts(test_file)
            self.assertEqual(data.get("com.tinh.vv.hi"), "BreckenLife330")
            self.assertEqual(data.get("com.tinh.vv.hj"), "ShadowWoodrow820")
            self.assertEqual(data.get("com.tinh.vv.hk"), "MysticjUBuildery1999")
            self.assertEqual(data.get("com.tinh.vv.hl"), "VanessaJoseph403")
            self.assertEqual(data.get("com.tinh.vv.hm"), "JeremiahWilkerson46")
            self.assertEqual(data.get("com.tinh.vv.hn"), "FuryuYQuantumD")
            self.assertEqual(data.get("com.tinh.vv.ho"), "Mega_Wiley623")
            self.assertEqual(data.get("com.tinh.vv.hp"), "Zephyra_Pro731")
            self.assertEqual(data.get("com.tinh.vv.hq"), "Nova71Fox11Panda1991")
            self.assertEqual(data.get("com.tinh.vv.hr"), "TigerYnG0ldenD199519")

            # Save updated mapping
            data["com.tinh.vv.hl"] = "NewUser_Tab4"
            agent.save_tab_accounts(data, test_file)
            reloaded = agent.load_tab_accounts(test_file)
            self.assertEqual(reloaded.get("com.tinh.vv.hl"), "NewUser_Tab4")

    @mock.patch("agent.agent.run_adb_shell")
    def test_tab4_not_assigned_to_mystic_when_shifted_in_acc_txt(self, mock_adb):
        """
        R2/R3/R4: Core Bug Reproduction & Fix:
        When Tab 2, Tab 3, Tab 4 are running on M77,
        even if acc.txt has shifted lines where line 4 is MysticjUBuildery1999,
        Tab 4 MUST report VanessaJoseph403 (tab_map), NEVER MysticjUBuildery1999.
        Tab 3 MUST report MysticjUBuildery1999 (tab_map).
        Tab 2 MUST report ShadowWoodrow820 (tab_map).
        """
        dumpsys_output = """
        Stack #1:
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.Activity t102}
          TaskRecord{103 #103 A=com.tinh.vv.hk U=0}
            Hist #0: ActivityRecord{3 u0 com.tinh.vv.hk/com.roblox.client.Activity t103}
          TaskRecord{104 #104 A=com.tinh.vv.hl U=0}
            Hist #0: ActivityRecord{4 u0 com.tinh.vv.hl/com.roblox.client.Activity t104}
        """
        mock_adb.side_effect = lambda cmd, **kw: dumpsys_output if "dumpsys" in str(cmd) else ""

        # Real-world shifted acc.txt where lines were removed, putting Zephyra on line 3 and Mystic on line 4
        mock_acc_content = """
M77___(gag2)
BreckenLife330:pass1:
ShadowWoodrow820:pass2:
Zephyra_Pro731:pass3:
MysticjUBuildery1999:pass4:
MegaRegan426:pass5:
"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_acc_path = pathlib.Path(tmpdir) / "acc.txt"
            temp_acc_path.write_text(mock_acc_content, encoding="utf-8")

            temp_map_path = pathlib.Path(tmpdir) / "tab_accounts.json"
            agent.ensure_tab_accounts_file(temp_map_path)

            tabs = agent.query_tab_list(
                device_id="m77",
                acc_path=temp_acc_path,
                tab_map_path=temp_map_path,
            )

            self.assertEqual(len(tabs), 3)

            # Tab 2: com.tinh.vv.hj -> ShadowWoodrow820 (tab_map)
            tab2 = next(t for t in tabs if t["tab"] == 2)
            self.assertEqual(tab2["package"], "com.tinh.vv.hj")
            self.assertEqual(tab2["username"], "ShadowWoodrow820 (tab_map)")

            # Tab 3: com.tinh.vv.hk -> MysticjUBuildery1999 (tab_map)
            tab3 = next(t for t in tabs if t["tab"] == 3)
            self.assertEqual(tab3["package"], "com.tinh.vv.hk")
            self.assertEqual(tab3["username"], "MysticjUBuildery1999 (tab_map)")

            # Tab 4: com.tinh.vv.hl -> VanessaJoseph403 (tab_map), NOT MysticjUBuildery1999!
            tab4 = next(t for t in tabs if t["tab"] == 4)
            self.assertEqual(tab4["package"], "com.tinh.vv.hl")
            self.assertEqual(tab4["username"], "VanessaJoseph403 (tab_map)")
            self.assertNotEqual(tab4["username"], "MysticjUBuildery1999")
            self.assertNotEqual(tab4["username"], "MysticjUBuildery1999 (acc.txt)")

            # HTML Formatting verification
            html_out = agent.format_tab_list_html("m77", tabs)
            self.assertIn("📱 <b>Tab List — M77</b>", html_out)
            self.assertIn("Tab 2: ShadowWoodrow820 (tab_map)", html_out)
            self.assertIn("Tab 3: MysticjUBuildery1999 (tab_map)", html_out)
            self.assertIn("Tab 4: VanessaJoseph403 (tab_map)", html_out)
            self.assertNotIn("Tab 4: MysticjUBuildery1999", html_out)
            self.assertNotIn("❓ (unknown)", html_out)

    @mock.patch("agent.agent.run_adb_shell")
    def test_acc_txt_modifications_do_not_disrupt_tab_assignments(self, mock_adb):
        """Verify that deleting or adding lines in acc.txt does not disrupt tab assignments."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{101 #101 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{1 u0 com.tinh.vv.hi/com.roblox.client.Activity t101}
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.Activity t102}
        """
        mock_adb.side_effect = lambda cmd, **kw: dumpsys_output if "dumpsys" in str(cmd) else ""

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_acc_path = pathlib.Path(tmpdir) / "acc.txt"
            temp_map_path = pathlib.Path(tmpdir) / "tab_accounts.json"
            agent.ensure_tab_accounts_file(temp_map_path)

            # Baseline run
            temp_acc_path.write_text("M77___(gag2)\nUserA:p:\nUserB:p:\n", encoding="utf-8")
            tabs1 = agent.query_tab_list(device_id="m77", acc_path=temp_acc_path, tab_map_path=temp_map_path)
            self.assertEqual(tabs1[0]["username"], "BreckenLife330 (tab_map)")
            self.assertEqual(tabs1[1]["username"], "ShadowWoodrow820 (tab_map)")

            # Delete first line in acc.txt (inducing shift)
            temp_acc_path.write_text("M77___(gag2)\nUserB:p:\n", encoding="utf-8")
            tabs2 = agent.query_tab_list(device_id="m77", acc_path=temp_acc_path, tab_map_path=temp_map_path)
            self.assertEqual(tabs2[0]["username"], "BreckenLife330 (tab_map)")
            self.assertEqual(tabs2[1]["username"], "ShadowWoodrow820 (tab_map)")

            # Add multiple lines in acc.txt
            temp_acc_path.write_text("M77___(gag2)\nExtra1:p:\nExtra2:p:\nExtra3:p:\n", encoding="utf-8")
            tabs3 = agent.query_tab_list(device_id="m77", acc_path=temp_acc_path, tab_map_path=temp_map_path)
            self.assertEqual(tabs3[0]["username"], "BreckenLife330 (tab_map)")
            self.assertEqual(tabs3[1]["username"], "ShadowWoodrow820 (tab_map)")

    @mock.patch("agent.agent.run_adb_shell")
    def test_precedence_real_username_over_tab_map(self, mock_adb):
        """Verify real username from app memory has precedence over tab_accounts.json."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{101 #101 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{1 u0 com.tinh.vv.hi/com.roblox.client.Activity t101}
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.Activity t102}
        """
        def side_effect(cmd, **kw):
            cmd_s = str(cmd)
            if "dumpsys" in cmd_s:
                return dumpsys_output
            # Tab 1 has readable appStorage
            if "com.tinh.vv.hi" in cmd_s and "appStorage.json" in cmd_s:
                return '{"Username": "RealLivePlayer"}'
            return ""

        mock_adb.side_effect = side_effect

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_map_path = pathlib.Path(tmpdir) / "tab_accounts.json"
            agent.ensure_tab_accounts_file(temp_map_path)

            tabs = agent.query_tab_list(device_id="m77", tab_map_path=temp_map_path)
            self.assertEqual(tabs[0]["tab"], 1)
            # Real username without suffix
            self.assertEqual(tabs[0]["username"], "RealLivePlayer")
            # Tab 2 falls back to tab_accounts.json with suffix
            self.assertEqual(tabs[1]["tab"], 2)
            self.assertEqual(tabs[1]["username"], "ShadowWoodrow820 (tab_map)")

    def test_get_tab_map_username_key_formats_and_edge_cases(self):
        """Test get_tab_map_username supports package names, tab numbers, and device namespaces."""
        test_data = {
            "com.tinh.vv.hi": "PkgUser",
            "2": "TabNumUser",
            "tab_3": "PrefixUser",
            "4": None,  # explicitly unassigned
            "5": "null",  # null string
            "6": "",  # empty string
            "m78": {
                "com.tinh.vv.hi": "M78User",
            },
        }
        # Package match
        found, u = agent.get_tab_map_username(1, pkg="com.tinh.vv.hi", loaded_data=test_data)
        self.assertTrue(found)
        self.assertEqual(u, "PkgUser (tab_map)")

        # Tab number match
        found, u = agent.get_tab_map_username(2, pkg="unmapped.pkg", loaded_data=test_data)
        self.assertTrue(found)
        self.assertEqual(u, "TabNumUser (tab_map)")

        # Tab prefix match
        found, u = agent.get_tab_map_username(3, pkg="unmapped.pkg", loaded_data=test_data)
        self.assertTrue(found)
        self.assertEqual(u, "PrefixUser (tab_map)")

        # None / null / empty
        found, u = agent.get_tab_map_username(4, pkg="com.tinh.vv.hl", loaded_data=test_data)
        self.assertTrue(found)
        self.assertIsNone(u)

        found, u = agent.get_tab_map_username(5, pkg="com.tinh.vv.hm", loaded_data=test_data)
        self.assertTrue(found)
        self.assertIsNone(u)

        found, u = agent.get_tab_map_username(6, pkg="com.tinh.vv.hn", loaded_data=test_data)
        self.assertTrue(found)
        self.assertIsNone(u)

        # Device namespace match
        found, u = agent.get_tab_map_username(1, pkg="com.tinh.vv.hi", device_id="m78", loaded_data=test_data)
        self.assertTrue(found)
        self.assertEqual(u, "M78User (tab_map)")

    @mock.patch("agent.agent.run_adb_shell")
    def test_tab4_never_assigned_mystic_with_acc_path_dev_null(self, mock_adb):
        """Verify Tab 4 is never assigned MysticjUBuildery1999 when acc_path is /dev/null."""
        mock_adb.return_value = """
        Stack #1:
          TaskRecord{104 #104 A=com.tinh.vv.hl U=0}
            Hist #0: ActivityRecord{4 u0 com.tinh.vv.hl/com.roblox.client.Activity t104}
        """
        tabs = agent.query_tab_list(device_id="m77", acc_path="/dev/null")
        tab4 = next((t for t in tabs if t["tab"] == 4), None)
        self.assertIsNotNone(tab4)
        self.assertEqual(tab4["package"], "com.tinh.vv.hl")
        exp_u4 = agent.load_tab_accounts().get("com.tinh.vv.hl")
        self.assertEqual(tab4["username"], f"{exp_u4} (tab_map)")
        self.assertNotEqual(tab4["username"], "MysticjUBuildery1999")
        self.assertNotEqual(tab4["username"], "MysticjUBuildery1999 (acc.txt)")

        html_out = agent.format_tab_list_html("m77", tabs)
        self.assertIn(f"Tab 4: {exp_u4} (tab_map)", html_out)
        self.assertNotIn("MysticjUBuildery1999", html_out)

    @mock.patch("agent.agent.run_adb_shell")
    def test_tab4_never_assigned_mystic_with_tab_map_path_dev_null(self, mock_adb):
        """Verify Tab 4 is never assigned MysticjUBuildery1999 even when tab_map_path is /dev/null."""
        mock_adb.return_value = """
        Stack #1:
          TaskRecord{104 #104 A=com.tinh.vv.hl U=0}
            Hist #0: ActivityRecord{4 u0 com.tinh.vv.hl/com.roblox.client.Activity t104}
        """
        tabs = agent.query_tab_list(device_id="m77", tab_map_path="/dev/null")
        tab4 = next((t for t in tabs if t["tab"] == 4), None)
        self.assertIsNotNone(tab4)
        self.assertEqual(tab4["package"], "com.tinh.vv.hl")
        exp_u4 = agent.load_tab_accounts().get("com.tinh.vv.hl")
        self.assertEqual(tab4["username"], f"{exp_u4} (acc.txt)")
        self.assertNotEqual(tab4["username"], "MysticjUBuildery1999")

        html_out = agent.format_tab_list_html("m77", tabs)
        self.assertIn(f"Tab 4: {exp_u4}", html_out)
        self.assertNotIn("MysticjUBuildery1999", html_out)

    @mock.patch("agent.agent.run_adb_shell")
    def test_tab4_never_assigned_mystic_with_shifted_acc_txt_isolated(self, mock_adb):
        """Verify shifted lines in an isolated acc.txt without tab_accounts.json do not misassign Tab 4."""
        mock_adb.return_value = """
        Stack #1:
          TaskRecord{104 #104 A=com.tinh.vv.hl U=0}
            Hist #0: ActivityRecord{4 u0 com.tinh.vv.hl/com.roblox.client.Activity t104}
        """
        mock_acc = """M77___(gag2)
BreckenLife330:pass1:
ShadowWoodrow820:pass2:
Zephyra_Pro731:pass3:
MysticjUBuildery1999:pass4:
MegaRegan426:pass5:
"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_acc = pathlib.Path(tmpdir) / "acc.txt"
            temp_acc.write_text(mock_acc, encoding="utf-8")

            tabs = agent.query_tab_list(device_id="m77", acc_path=temp_acc, tab_map_path="/dev/null")
            tab4 = next((t for t in tabs if t["tab"] == 4), None)
            self.assertIsNotNone(tab4)
            self.assertIsNone(tab4["username"])
            self.assertNotEqual(tab4["username"], "MysticjUBuildery1999")
            self.assertNotEqual(tab4["username"], "MysticjUBuildery1999 (acc.txt)")

            html_out = agent.format_tab_list_html("m77", tabs)
            self.assertIn("Tab 4: ❓ (unknown)", html_out)
            self.assertNotIn("MysticjUBuildery1999", html_out)

    def test_get_acc_fallback_username_guards_m77_and_explicit_paths(self):
        """Verify get_acc_fallback_username guards against M77 shifted lines and handles explicit paths strictly."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Isolated acc.txt without tab_accounts.json
            temp_acc = pathlib.Path(tmpdir) / "acc.txt"
            temp_acc.write_text("M77___(gag2)\nBreckenLife330:p:\nShadowWoodrow820:p:\nZephyra_Pro731:p:\nMysticjUBuildery1999:p:\n", encoding="utf-8")
            # Tab 4 on M77 is strictly blocked from taking MysticjUBuildery1999
            self.assertIsNone(agent.get_acc_fallback_username(4, device_id="m77", acc_path=temp_acc))
            # Tab 1 resolves BreckenLife330
            self.assertEqual(agent.get_acc_fallback_username(1, device_id="m77", acc_path=temp_acc), "BreckenLife330 (acc.txt)")
            # Tab 3 has Zephyra on shifted line 3, which is blocked (belongs to Tab 8)
            self.assertIsNone(agent.get_acc_fallback_username(3, device_id="m77", acc_path=temp_acc))
            # Explicit acc_path="/dev/null" returns None immediately
            self.assertIsNone(agent.get_acc_fallback_username(1, device_id="m77", acc_path="/dev/null"))
            # Explicit non-existent path returns None immediately without bleeding production acc.txt
            self.assertIsNone(agent.get_acc_fallback_username(1, device_id="m77", acc_path="/non/existent/acc.txt"))

    def test_save_and_ensure_tab_accounts_atomic(self):
        """Verify save_tab_accounts and ensure_tab_accounts_file operate atomically without leftover tmp files."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            map_path = pathlib.Path(tmpdir) / "sub" / "tab_accounts.json"
            agent.ensure_tab_accounts_file(map_path)
            self.assertTrue(map_path.is_file())

            data = agent.load_tab_accounts(map_path)
            self.assertEqual(data["com.tinh.vv.hi"], "BreckenLife330")

            data["com.tinh.vv.hl"] = "AssignedPlayer4"
            success = agent.save_tab_accounts(data, map_path)
            self.assertTrue(success)

            reloaded = agent.load_tab_accounts(map_path)
            self.assertEqual(reloaded["com.tinh.vv.hl"], "AssignedPlayer4")

            # Verify no temporary files remain in folder
            tmp_files = list(map_path.parent.glob("*.tmp.*"))
            self.assertEqual(len(tmp_files), 0)

    def test_load_tab_accounts_malformed_json_fallback(self):
        """Verify load_tab_accounts handles malformed JSON without crashing."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_json_path = pathlib.Path(tmpdir) / "bad.json"
            bad_json_path.write_text("{corrupt: json syntax...", encoding="utf-8")
            data = agent.load_tab_accounts(bad_json_path)
            self.assertEqual(data, {})

    def test_get_tab_map_username_bidirectional_package_tab_mapping(self):
        """Verify get_tab_map_username resolves packages from tab numbers and vice versa."""
        tab_map = agent.load_tab_accounts()
        exp_u1 = tab_map.get("com.tinh.vv.hi")
        exp_u3 = tab_map.get("com.tinh.vv.hk")
        exp_u4 = tab_map.get("com.tinh.vv.hl")
        exp_u8 = tab_map.get("com.tinh.vv.hp")

        # Tab 1 without pkg resolves com.tinh.vv.hi
        found, u = agent.get_tab_map_username(tab_num=1, device_id="m77")
        self.assertTrue(found)
        self.assertEqual(u, f"{exp_u1} (tab_map)")

        # Tab 3 without pkg resolves com.tinh.vv.hk
        found, u = agent.get_tab_map_username(tab_num=3, device_id="m77")
        self.assertTrue(found)
        self.assertEqual(u, f"{exp_u3} (tab_map)")

        # Tab 4 without pkg resolves com.tinh.vv.hl
        found, u = agent.get_tab_map_username(tab_num=4, device_id="m77")
        self.assertTrue(found)
        self.assertEqual(u, f"{exp_u4} (tab_map)")

        # Tab 8 without pkg resolves com.tinh.vv.hp
        found, u = agent.get_tab_map_username(tab_num=8, device_id="m77")
        self.assertTrue(found)
        self.assertEqual(u, f"{exp_u8} (tab_map)")

        # Case-insensitive tab format in custom map
        custom_data = {
            "Tab4": "PlayerCustom4",
            "tab 5": "PlayerCustom5",
            "TAB6": "PlayerCustom6",
        }
        found, u = agent.get_tab_map_username(tab_num=4, pkg="com.tinh.vv.hl", loaded_data=custom_data)
        self.assertTrue(found)
        self.assertEqual(u, "PlayerCustom4 (tab_map)")

        found, u = agent.get_tab_map_username(tab_num=5, pkg="com.tinh.vv.hm", loaded_data=custom_data)
        self.assertTrue(found)
        self.assertEqual(u, "PlayerCustom5 (tab_map)")

        found, u = agent.get_tab_map_username(tab_num=6, pkg="com.tinh.vv.hn", loaded_data=custom_data)
        self.assertTrue(found)
        self.assertEqual(u, "PlayerCustom6 (tab_map)")

    def test_stale_tab_accounts_file_with_nulls_is_automatically_healed(self):
        """Verify that a stale tab_accounts.json on disk with nulls (from previous commit) is self-healed."""
        import tempfile
        stale_content = {
            "com.tinh.vv.hi": "BreckenLife330",
            "com.tinh.vv.hj": "ShadowWoodrow820",
            "com.tinh.vv.hk": None,
            "com.tinh.vv.hl": None,
            "com.tinh.vv.hm": None,
            "com.tinh.vv.hn": None,
            "com.tinh.vv.ho": "Mega_Wiley623",
            "com.tinh.vv.hp": "Zephyra_Pro731",
            "com.tinh.vv.hq": None,
            "com.tinh.vv.hr": None,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            stale_file = pathlib.Path(tmpdir) / "tab_accounts.json"
            stale_file.write_text(json.dumps(stale_content, indent=2), encoding="utf-8")

            # 1. Test ensure_tab_accounts_file heals the file on disk
            agent.ensure_tab_accounts_file(stale_file)
            healed_disk = json.loads(stale_file.read_text(encoding="utf-8"))
            self.assertEqual(healed_disk.get("com.tinh.vv.hk"), "MysticjUBuildery1999")
            self.assertEqual(healed_disk.get("com.tinh.vv.hl"), "VanessaJoseph403")
            self.assertEqual(healed_disk.get("com.tinh.vv.hm"), "JeremiahWilkerson46")
            self.assertEqual(healed_disk.get("com.tinh.vv.hn"), "FuryuYQuantumD")

            # 2. Reset with nulls and test load_tab_accounts also heals
            stale_file.write_text(json.dumps(stale_content, indent=2), encoding="utf-8")
            loaded = agent.load_tab_accounts(stale_file)
            self.assertEqual(loaded.get("com.tinh.vv.hk"), "MysticjUBuildery1999")
            self.assertEqual(loaded.get("com.tinh.vv.hl"), "VanessaJoseph403")

    @mock.patch("agent.agent.run_adb_shell")
    def test_stale_tab_accounts_file_query_tab_list_resolves_tab3_and_tab4(self, mock_adb):
        """Verify query_tab_list with a stale tab_accounts.json resolves Tab 3 and Tab 4 without unknown."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.Activity t102}
          TaskRecord{103 #103 A=com.tinh.vv.hk U=0}
            Hist #0: ActivityRecord{3 u0 com.tinh.vv.hk/com.roblox.client.Activity t103}
          TaskRecord{104 #104 A=com.tinh.vv.hl U=0}
            Hist #0: ActivityRecord{4 u0 com.tinh.vv.hl/com.roblox.client.Activity t104}
        """
        mock_adb.side_effect = lambda cmd, **kw: dumpsys_output if "dumpsys" in str(cmd) else ""
        import tempfile
        stale_content = {
            "com.tinh.vv.hi": "BreckenLife330",
            "com.tinh.vv.hj": "ShadowWoodrow820",
            "com.tinh.vv.hk": None,
            "com.tinh.vv.hl": None,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            stale_file = pathlib.Path(tmpdir) / "tab_accounts.json"
            stale_file.write_text(json.dumps(stale_content, indent=2), encoding="utf-8")

            tabs = agent.query_tab_list(device_id="m77", tab_map_path=stale_file)
            self.assertEqual(len(tabs), 3)

            tab2 = next(t for t in tabs if t["tab"] == 2)
            self.assertEqual(tab2["package"], "com.tinh.vv.hj")
            self.assertEqual(tab2["username"], "ShadowWoodrow820 (tab_map)")

            tab3 = next(t for t in tabs if t["tab"] == 3)
            self.assertEqual(tab3["package"], "com.tinh.vv.hk")
            self.assertEqual(tab3["username"], "MysticjUBuildery1999 (tab_map)")

            tab4 = next(t for t in tabs if t["tab"] == 4)
            self.assertEqual(tab4["package"], "com.tinh.vv.hl")
            self.assertEqual(tab4["username"], "VanessaJoseph403 (tab_map)")

            html_out = agent.format_tab_list_html("m77", tabs)
            self.assertIn("Tab 2: ShadowWoodrow820 (tab_map)", html_out)
            self.assertIn("Tab 3: MysticjUBuildery1999 (tab_map)", html_out)
            self.assertIn("Tab 4: VanessaJoseph403 (tab_map)", html_out)
            self.assertNotIn("❓ (unknown)", html_out)

    def test_stale_tab_map_file_heals_and_resolves_get_tab_map_username(self):
        """Verify load_tab_accounts heals stale nulls and get_tab_map_username returns healed accounts."""
        import tempfile
        null_data = {
            "com.tinh.vv.hk": None,
            "com.tinh.vv.hl": "null",
            "com.tinh.vv.hm": "unknown",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            stale_file = pathlib.Path(tmpdir) / "tab_accounts.json"
            stale_file.write_text(json.dumps(null_data, indent=2), encoding="utf-8")

            healed_data = agent.load_tab_accounts(stale_file)
            found3, u3 = agent.get_tab_map_username(tab_num=3, pkg="com.tinh.vv.hk", loaded_data=healed_data)
            self.assertTrue(found3)
            self.assertEqual(u3, "MysticjUBuildery1999 (tab_map)")

            found4, u4 = agent.get_tab_map_username(tab_num=4, pkg="com.tinh.vv.hl", loaded_data=healed_data)
            self.assertTrue(found4)
            self.assertEqual(u4, "VanessaJoseph403 (tab_map)")

            found5, u5 = agent.get_tab_map_username(tab_num=5, pkg="com.tinh.vv.hm", loaded_data=healed_data)
            self.assertTrue(found5)
            self.assertEqual(u5, "JeremiahWilkerson46 (tab_map)")

    @mock.patch("agent.agent.run_adb_shell")
    def test_batch_root_grep_extracts_usernames_multi_package(self, mock_adb):
        """Verify batch root grep extracts usernames for multiple packages in one pass without (tab_map) suffix."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{101 #101 A=com.roblox.client U=0}
            Hist #0: ActivityRecord{1 u0 com.roblox.client/.MainActivity t101}
          TaskRecord{102 #102 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hi/com.roblox.client.ActivityProtocolLaunch t102}
          TaskRecord{103 #103 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{3 u0 com.tinh.vv.hj/com.roblox.client.ActivityProtocolLaunch t103}
        """

        grep_batch_output = (
            "/data/data/com.roblox.client/files/appData/LocalStorage/appStorage.json:\"DisplayName\":\"Zephyra_Pro731\"\n"
            "/data/data/com.tinh.vv.hi/files/appData/LocalStorage/appStorage.json:\"Username\":\"BreckenLife330\"\n"
            "/data/data/com.tinh.vv.hj/shared_prefs/com.tinh.vv.hj_preferences.xml:<string name=\"Username\">ShadowWoodrow820</string>\n"
        )

        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            if "grep" in cmd_str:
                return grep_batch_output
            return ""

        mock_adb.side_effect = side_effect

        tabs = agent.query_tab_list(tab_map_path="/dev/null", acc_path="/dev/null")
        self.assertEqual(len(tabs), 3)

        tab1 = next(t for t in tabs if t["package"] == "com.tinh.vv.hi")
        self.assertEqual(tab1["tab"], 1)
        self.assertEqual(tab1["username"], "BreckenLife330")
        self.assertFalse(tab1["username"].endswith("(tab_map)"))

        tab2 = next(t for t in tabs if t["package"] == "com.tinh.vv.hj")
        self.assertEqual(tab2["tab"], 2)
        self.assertEqual(tab2["username"], "ShadowWoodrow820")
        self.assertFalse(tab2["username"].endswith("(tab_map)"))

        tab_roblox = next(t for t in tabs if t["package"] == "com.roblox.client")
        self.assertEqual(tab_roblox["username"], "Zephyra_Pro731")
        self.assertFalse(tab_roblox["username"].endswith("(tab_map)"))

        html_out = agent.format_tab_list_html("m77", tabs)
        self.assertIn("BreckenLife330", html_out)
        self.assertIn("ShadowWoodrow820", html_out)
        self.assertIn("Zephyra_Pro731", html_out)
        self.assertNotIn("(tab_map)", html_out)

    @mock.patch("agent.agent.run_adb_shell")
    def test_batch_root_grep_case_insensitive_and_multi_user(self, mock_adb):
        """Verify batch root grep handles case-insensitive keys and multi-user paths."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{101 #101 A=com.tinh.vv.hk U=0}
            Hist #0: ActivityRecord{1 u0 com.tinh.vv.hk/com.roblox.client.ActivityProtocolLaunch t101}
        """
        grep_batch_output = (
            "/data/user/10/com.tinh.vv.hk/files/appData/LocalStorage/appStorage.json:\"username\":\"MysticjUBuildery1999\"\n"
        )

        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            if "grep" in cmd_str:
                return grep_batch_output
            return ""

        mock_adb.side_effect = side_effect

        tabs = agent.query_tab_list(tab_map_path="/dev/null", acc_path="/dev/null")
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["username"], "MysticjUBuildery1999")
        self.assertFalse(tabs[0]["username"].endswith("(tab_map)"))

    @mock.patch("agent.agent.run_adb_shell")
    def test_batch_root_grep_ignores_invalid_usernames_and_falls_back(self, mock_adb):
        """Verify batch root grep skips invalid placeholders (null, guest, unknown) and falls back to tab_accounts.json."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{101 #101 A=com.tinh.vv.hk U=0}
            Hist #0: ActivityRecord{1 u0 com.tinh.vv.hk/com.roblox.client.ActivityProtocolLaunch t101}
        """
        # Grep returns placeholder string
        grep_batch_output = (
            "/data/data/com.tinh.vv.hk/files/appData/LocalStorage/appStorage.json:\"Username\":\"null\"\n"
        )

        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            if "grep" in cmd_str:
                return grep_batch_output
            return ""

        mock_adb.side_effect = side_effect

        import tempfile
        tab_map_content = {"com.tinh.vv.hk": "MysticjUBuildery1999"}
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = pathlib.Path(tmpdir) / "tab_accounts.json"
            fpath.write_text(json.dumps(tab_map_content), encoding="utf-8")
            tabs = agent.query_tab_list(tab_map_path=fpath, acc_path="/dev/null")
            self.assertEqual(len(tabs), 1)
            # Should have fallen back to tab_map with (tab_map) suffix
            self.assertEqual(tabs[0]["username"], "MysticjUBuildery1999 (tab_map)")

    @mock.patch("agent.agent.run_adb_shell")
    def test_batch_root_grep_prioritizes_username_over_displayname(self, mock_adb):
        """Verify that when both DisplayName and Username appear, exact Username is preferred."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{101 #101 A=com.roblox.client U=0}
            Hist #0: ActivityRecord{1 u0 com.roblox.client/.MainActivity t101}
        """
        grep_batch_output = (
            "/data/data/com.roblox.client/files/appData/LocalStorage/appStorage.json:\"DisplayName\":\"Zephyra_\"\n"
            "/data/data/com.roblox.client/files/appData/LocalStorage/appStorage.json:\"Username\":\"Zephyra_Pro731\"\n"
        )

        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            if "grep" in cmd_str:
                return grep_batch_output
            return ""

        mock_adb.side_effect = side_effect

        tabs = agent.query_tab_list(tab_map_path="/dev/null", acc_path="/dev/null")
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["username"], "Zephyra_Pro731")

    def test_run_adb_shell_unwrap_su_inner_complex_quotes(self):
        """Test unwrap_su_inner handles complex shell quotes, escapes, and chained commands."""
        # Simple wrapping
        self.assertEqual(agent.unwrap_su_inner('"cat test"'), "cat test")
        self.assertEqual(agent.unwrap_su_inner("'cat test'"), "cat test")
        # Chained single quotes inside double quotes
        self.assertEqual(agent.unwrap_su_inner("\"'echo 1' && 'echo 2'\""), "'echo 1' && 'echo 2'")
        # Escaped quotes and variables
        self.assertEqual(
            agent.unwrap_su_inner('"{ [ -f \\"\\$f\\" ] && echo \\"\\$f\\"; }"'),
            '{ [ -f "$f" ] && echo "$f"; }'
        )
        # Unwrapped commands not enclosed in single pair of quotes
        self.assertEqual(agent.unwrap_su_inner('"cmd1" && "cmd2"'), '"cmd1" && "cmd2"')
        self.assertEqual(agent.unwrap_su_inner("'cmd1' && 'cmd2'"), "'cmd1' && 'cmd2'")

    @mock.patch("subprocess.run")
    def test_run_adb_shell_with_nested_su_quotes_stripping(self, mock_run):
        """Verify run_adb_shell strips outer quotes from su -c with nested quotes."""
        executed = []
        def fake_run(cmd, **kwargs):
            executed.append(cmd)
            res = mock.MagicMock()
            if cmd[0] == "/system/bin/su":
                res.returncode = 0
                res.stdout = "ok\n"
                return res
            res.returncode = 1
            res.stdout = ""
            return res

        mock_run.side_effect = fake_run
        cmd = 'su -c "for f in /data/data/*; do [ -f \\"\\$f\\" ] && grep -aoEi \\"Username\\" \\"\\$f\\"; done"'
        out = agent.run_adb_shell(cmd)
        self.assertEqual(out.strip(), "ok")
        su_call = next(c for c in executed if c[0] == "/system/bin/su")
        self.assertEqual(su_call[1], "-c")
        self.assertEqual(su_call[2], 'for f in /data/data/*; do [ -f "$f" ] && grep -aoEi "Username" "$f"; done')

    @mock.patch("agent.agent.run_adb_shell")
    def test_batch_root_grep_escaped_json_m77(self, mock_adb):
        """Verify batch root grep correctly extracts live usernames on M77 when JSON is escaped."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.Activity t102}
          TaskRecord{103 #103 A=com.tinh.vv.hk U=0}
            Hist #0: ActivityRecord{3 u0 com.tinh.vv.hk/com.roblox.client.Activity t103}
          TaskRecord{104 #104 A=com.tinh.vv.hl U=0}
            Hist #0: ActivityRecord{4 u0 com.tinh.vv.hl/com.roblox.client.Activity t104}
        """
        # Grep output with escaped backslash quotes as found in real appStorage.json on M77
        grep_batch_output = (
            '/data/data/com.tinh.vv.hj/files/appData/LocalStorage/appStorage.json: Username\\":\\"ShadowWoodrow820"\n'
            '/data/data/com.tinh.vv.hk/files/appData/LocalStorage/appStorage.json: \\"Username\\":\\"MysticjUBuildery1999\\"\n'
            '/data/data/com.tinh.vv.hl/files/appData/LocalStorage/appStorage.json: Username\\":\\"VanessaJoseph403"\n'
        )

        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            if "grep" in cmd_str:
                return grep_batch_output
            return ""

        mock_adb.side_effect = side_effect

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_map_path = pathlib.Path(tmpdir) / "tab_accounts.json"
            agent.ensure_tab_accounts_file(temp_map_path)

            tabs = agent.query_tab_list(device_id="m77", tab_map_path=temp_map_path)
            self.assertEqual(len(tabs), 3)

            # Tab 2: com.tinh.vv.hj -> ShadowWoodrow820 (LIVE without suffix)
            tab2 = next(t for t in tabs if t["tab"] == 2)
            self.assertEqual(tab2["package"], "com.tinh.vv.hj")
            self.assertEqual(tab2["username"], "ShadowWoodrow820")
            self.assertFalse(tab2["username"].endswith("(tab_map)"))

            # Tab 3: com.tinh.vv.hk -> MysticjUBuildery1999 (LIVE without suffix)
            tab3 = next(t for t in tabs if t["tab"] == 3)
            self.assertEqual(tab3["package"], "com.tinh.vv.hk")
            self.assertEqual(tab3["username"], "MysticjUBuildery1999")
            self.assertFalse(tab3["username"].endswith("(tab_map)"))

            # Tab 4: com.tinh.vv.hl -> VanessaJoseph403 (LIVE without suffix)
            tab4 = next(t for t in tabs if t["tab"] == 4)
            self.assertEqual(tab4["package"], "com.tinh.vv.hl")
            self.assertEqual(tab4["username"], "VanessaJoseph403")
            self.assertFalse(tab4["username"].endswith("(tab_map)"))

            # HTML Output check: NO (tab_map) suffix in live report
            html_out = agent.format_tab_list_html("m77", tabs)
            self.assertIn("Tab 2: ShadowWoodrow820", html_out)
            self.assertIn("Tab 3: MysticjUBuildery1999", html_out)
            self.assertIn("Tab 4: VanessaJoseph403", html_out)
            self.assertNotIn("(tab_map)", html_out)

    @mock.patch("agent.agent.run_adb_shell")
    def test_run_as_extraction_fallback_when_root_denied(self, mock_adb):
        """Verify run-as fallback extracts username from app files without full root."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{104 #104 A=com.tinh.vv.hl U=0}
            Hist #0: ActivityRecord{4 u0 com.tinh.vv.hl/com.roblox.client.Activity t104}
        """
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            # Root batch grep fails / returns empty (permission denied)
            if "for f in" in cmd_str or "grep" in cmd_str:
                return ""
            # run-as succeeds
            if "run-as com.tinh.vv.hl" in cmd_str:
                return '{"CurrentUser":"{\\"Username\\":\\"VanessaJoseph403\\"}"}'
            return ""

        mock_adb.side_effect = side_effect

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_map_path = pathlib.Path(tmpdir) / "tab_accounts.json"
            agent.ensure_tab_accounts_file(temp_map_path)

            tabs = agent.query_tab_list(device_id="m77", tab_map_path=temp_map_path)
            self.assertEqual(len(tabs), 1)
            self.assertEqual(tabs[0]["tab"], 4)
            self.assertEqual(tabs[0]["package"], "com.tinh.vv.hl")
            self.assertEqual(tabs[0]["username"], "VanessaJoseph403")
            self.assertFalse(tabs[0]["username"].endswith("(tab_map)"))

    @mock.patch("agent.agent.run_adb_shell")
    def test_dumpsys_window_extraction_tier3(self, mock_adb):
        """Verify Tier 3 dumpsys window extracts username from window titles."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{104 #104 A=com.tinh.vv.hl U=0}
            Hist #0: ActivityRecord{4 u0 com.tinh.vv.hl/com.roblox.client.Activity t104}
        """
        window_output = """
        WINDOW MANAGER WINDOWS (dumpsys window windows)
          Window #1 Window{1a2b3c u0 com.tinh.vv.hl/com.roblox.client.ActivityProtocolLaunch}:
            mCurrentFocus=null
            title="Roblox - VanessaJoseph403"
        """
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            if "dumpsys window" in cmd_str:
                return window_output
            return ""

        mock_adb.side_effect = side_effect

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_map_path = pathlib.Path(tmpdir) / "tab_accounts.json"
            agent.ensure_tab_accounts_file(temp_map_path)

            tabs = agent.query_tab_list(device_id="m77", tab_map_path=temp_map_path)
            self.assertEqual(len(tabs), 1)
            self.assertEqual(tabs[0]["username"], "VanessaJoseph403")
            self.assertFalse(tabs[0]["username"].endswith("(tab_map)"))

    @mock.patch("agent.agent.run_adb_shell")
    def test_logcat_extraction_tier3(self, mock_adb):
        """Verify Tier 3 logcat extracts username from recent application log lines."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{104 #104 A=com.tinh.vv.hl U=0}
            Hist #0: ActivityRecord{4 u0 com.tinh.vv.hl/com.roblox.client.Activity t104}
        """
        logcat_output = """
        09-15 10:00:00.000  1234  1234 I Roblox: Authenticated user: VanessaJoseph403
        """
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            if "logcat" in cmd_str:
                return logcat_output
            return ""

        mock_adb.side_effect = side_effect

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_map_path = pathlib.Path(tmpdir) / "tab_accounts.json"
            agent.ensure_tab_accounts_file(temp_map_path)

            tabs = agent.query_tab_list(device_id="m77", tab_map_path=temp_map_path)
            self.assertEqual(len(tabs), 1)
            self.assertEqual(tabs[0]["username"], "VanessaJoseph403")
            self.assertFalse(tabs[0]["username"].endswith("(tab_map)"))

    def test_extract_username_from_text_arbitrary_escaped_json(self):
        """Verify extract_username_from_text handles multiple levels of string escaping."""
        self.assertEqual(agent.extract_username_from_text('{"Username":"VanessaJoseph403"}'), "VanessaJoseph403")
        self.assertEqual(agent.extract_username_from_text(r'{\"Username\":\"VanessaJoseph403\"}'), "VanessaJoseph403")
        self.assertEqual(agent.extract_username_from_text(r'{\\"Username\\":\\"VanessaJoseph403\\"}'), "VanessaJoseph403")
        self.assertEqual(agent.extract_username_from_text(r'{\\\"Username\\\":\\\"VanessaJoseph403\\\"}'), "VanessaJoseph403")
        self.assertEqual(agent.extract_username_from_text(r'\"Username\":\"VanessaJoseph403\"'), "VanessaJoseph403")
        self.assertEqual(agent.extract_username_from_text(r'\\"Username\\":\\"VanessaJoseph403\\"'), "VanessaJoseph403")
        self.assertEqual(agent.extract_username_from_text(r'{"CurrentUser":"{\"Username\":\"VanessaJoseph403\"}"}'), "VanessaJoseph403")


    def test_window_title_generic_roblox_and_components_not_extracted(self):
        """Verify generic component titles like Roblox or MainActivity are not extracted as usernames."""
        self.assertIsNone(agent.extract_username_from_text('title="Roblox"'))
        self.assertIsNone(agent.extract_username_from_text('title="MainActivity"'))
        self.assertIsNone(agent.extract_username_from_text('title="Roblox Client"'))

    def test_window_title_with_emojis_and_decorations(self):
        """Verify Roblox usernames are extracted from window titles containing emojis and handles."""
        self.assertEqual(agent.extract_username_from_text('title="Roblox - 👑 VanessaJoseph403 👑"'), "VanessaJoseph403")
        self.assertEqual(agent.extract_username_from_text('title="Roblox - 🎮 Gamer_Boy99 🎮"'), "Gamer_Boy99")
        self.assertEqual(agent.extract_username_from_text('title="Roblox - ProGamer (@VanessaJoseph403)"'), "VanessaJoseph403")
        self.assertEqual(agent.extract_username_from_text('title="Roblox – VanessaJoseph403"'), "VanessaJoseph403")
        self.assertEqual(agent.extract_username_from_text('title="Roblox — VanessaJoseph403"'), "VanessaJoseph403")
        self.assertEqual(agent.extract_username_from_text('title="Roblox: VanessaJoseph403"'), "VanessaJoseph403")

    @mock.patch("agent.agent.run_adb_shell")
    def test_dumpsys_window_avoids_cross_tab_contamination(self, mock_adb):
        """Verify dumpsys window parser respects window boundaries and does not leak adjacent window titles."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.ActivityProtocolLaunch t102}
          TaskRecord{103 #103 A=com.tinh.vv.hk U=0}
            Hist #0: ActivityRecord{3 u0 com.tinh.vv.hk/com.roblox.client.ActivityProtocolLaunch t103}
        """
        window_output = """
        WINDOW MANAGER WINDOWS (dumpsys window windows)
          Window #1 Window{1111 u0 com.tinh.vv.hj/com.roblox.client.ActivityProtocolLaunch}:
            mCurrentFocus=null
            mHasSurface=true
            title="Roblox"
          Window #2 Window{2222 u0 com.tinh.vv.hk/com.roblox.client.ActivityProtocolLaunch}:
            mCurrentFocus=null
            title="Roblox - MysticjUBuildery1999"
        """
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            if "dumpsys window" in cmd_str:
                return window_output
            return ""

        mock_adb.side_effect = side_effect

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_map_path = pathlib.Path(tmpdir) / "tab_accounts.json"
            agent.ensure_tab_accounts_file(temp_map_path)

            tabs = agent.query_tab_list(device_id="m77", tab_map_path=temp_map_path)
            self.assertEqual(len(tabs), 2)

            # Tab 2: com.tinh.vv.hj must NOT steal Tab 3's window title; falls back to its own tab_map
            tab2 = next(t for t in tabs if t["package"] == "com.tinh.vv.hj")
            self.assertEqual(tab2["username"], "ShadowWoodrow820 (tab_map)")

            # Tab 3: com.tinh.vv.hk must have live username MysticjUBuildery1999 without suffix
            tab3 = next(t for t in tabs if t["package"] == "com.tinh.vv.hk")
            self.assertEqual(tab3["username"], "MysticjUBuildery1999")
            self.assertFalse(tab3["username"].endswith("(tab_map)"))

    @mock.patch("agent.agent.run_adb_shell")
    def test_logcat_avoids_cross_tab_contamination_with_multiple_instances(self, mock_adb):
        """Verify generic logcat lines are not falsely attributed across multiple running Roblox instances."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.ActivityProtocolLaunch t102}
          TaskRecord{103 #103 A=com.tinh.vv.hk U=0}
            Hist #0: ActivityRecord{3 u0 com.tinh.vv.hk/com.roblox.client.ActivityProtocolLaunch t103}
        """
        logcat_output = """
        09-15 10:00:00.000  9999  9999 I Roblox: Authenticated user: VanessaJoseph403
        """
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            if "logcat" in cmd_str:
                return logcat_output
            return ""

        mock_adb.side_effect = side_effect

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_map_path = pathlib.Path(tmpdir) / "tab_accounts.json"
            agent.ensure_tab_accounts_file(temp_map_path)

            tabs = agent.query_tab_list(device_id="m77", tab_map_path=temp_map_path)
            self.assertEqual(len(tabs), 2)

            tab2 = next(t for t in tabs if t["package"] == "com.tinh.vv.hj")
            tab3 = next(t for t in tabs if t["package"] == "com.tinh.vv.hk")

            # Neither tab should steal VanessaJoseph403 from generic logcat
            self.assertNotEqual(tab2["username"], "VanessaJoseph403")
            self.assertNotEqual(tab3["username"], "VanessaJoseph403")
            self.assertEqual(tab2["username"], "ShadowWoodrow820 (tab_map)")
            self.assertEqual(tab3["username"], "MysticjUBuildery1999 (tab_map)")

    @mock.patch("agent.agent.run_adb_shell")
    def test_batch_grep_display_name_before_username_priority(self, mock_adb):
        """Verify batch grep prioritizes exact Username over DisplayName even when DisplayName appears first."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{104 #104 A=com.tinh.vv.hl U=0}
            Hist #0: ActivityRecord{4 u0 com.tinh.vv.hl/com.roblox.client.Activity t104}
        """
        grep_batch_output = (
            '/data/data/com.tinh.vv.hl/files/appData/LocalStorage/appStorage.json: "DisplayName":"Vanessa","Username":"VanessaJoseph403"\n'
        )
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            if "grep" in cmd_str:
                return grep_batch_output
            return ""

        mock_adb.side_effect = side_effect

        tabs = agent.query_tab_list(tab_map_path="/dev/null", acc_path="/dev/null")
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["username"], "VanessaJoseph403")

    def test_unwrap_su_inner_edge_cases(self):
        """Verify unwrap_su_inner handles escaped trailing quotes and escapes accurately."""
        # Trailing escaped quote should NOT be stripped (unclosed string)
        self.assertEqual(agent.unwrap_su_inner(r'"echo test\"'), r'"echo test\"')
        # Trailing escaped backslash before quote is closed properly
        self.assertEqual(agent.unwrap_su_inner(r'"echo test\\"'), 'echo test\\')
        # Single quotes inside double quotes
        self.assertEqual(agent.unwrap_su_inner('"echo \'hello\'"'), "echo 'hello'")

    def test_batch_cmd_preserves_shell_dollar_variable_without_premature_expansion(self):
        """Verify batch command escapes $f properly so outer shell (adb shell/sh -c) does not expand to empty string."""
        import subprocess
        # Simulate adbd outer shell: sh -c "raw_cmd"
        # We create a mock su that records the exact arguments passed to it
        with tempfile.TemporaryDirectory() as tmpdir:
            mock_su = os.path.join(tmpdir, "su")
            log_file = os.path.join(tmpdir, "su.log")
            with open(mock_su, "w") as f:
                f.write(f"#!/bin/sh\necho \"$@\" > {log_file}\n")
            os.chmod(mock_su, 0o755)

            # Generate batch_cmd with test target
            batch_targets = "/data/data/com.tinh.vv.*/files/appData/LocalStorage/appStorage.json"
            batch_regex = r'((Username|DisplayName|RobloxUsername)[\"\\ ]*:[\"\\ ]*([a-zA-Z0-9_]{3,30}))'
            batch_cmd = (
                f"{mock_su} -c \"for f in {batch_targets}; do "
                f"[ -f \\\"\\$f\\\" ] || continue; "
                f"res=\\$(head -c 1048576 \\\"\\$f\\\" 2>/dev/null | grep -aoEi '{batch_regex}' 2>/dev/null | head -n 2); "
                f"[ -z \\\"\\$res\\\" ] && res=\\$(grep -aoEi '{batch_regex}' \\\"\\$f\\\" 2>/dev/null | head -n 2); "
                f"[ -n \\\"\\$res\\\" ] && echo \\\"\\$f: \\$res\\\"; "
                f"done; true\""
            )

            # Execute via sh -c as adbd does
            subprocess.run(["sh", "-c", batch_cmd], capture_output=True, text=True)
            with open(log_file) as f:
                captured_args = f.read()

            # Ensure $f was NOT expanded to empty string ""
            self.assertIn('$f', captured_args)
            self.assertNotIn('[ -f "" ]', captured_args)

    def test_window_title_rejects_roblox_navigation_screens_and_game_titles(self):
        """Verify Roblox navigation screens (Home, Profile, Discover) and game titles (Blox Fruits) are rejected."""
        # System UI navigation screens
        self.assertIsNone(agent.extract_username_from_text('title="Roblox - Home"'))
        self.assertIsNone(agent.extract_username_from_text('title="Roblox - Profile"'))
        self.assertIsNone(agent.extract_username_from_text('title="Roblox - Discover"'))
        self.assertIsNone(agent.extract_username_from_text('title="Roblox - Settings"'))
        self.assertIsNone(agent.extract_username_from_text('title="Roblox - Avatar"'))
        self.assertIsNone(agent.extract_username_from_text('title="Roblox - Marketplace"'))
        self.assertIsNone(agent.extract_username_from_text('title="Roblox - Chat"'))
        self.assertIsNone(agent.extract_username_from_text('title="Roblox - Loading..."'))
        self.assertIsNone(agent.extract_username_from_text('title="Roblox - Login"'))
        self.assertIsNone(agent.extract_username_from_text('title="Roblox - SignUp"'))

        # Game titles (multi-word without @)
        self.assertIsNone(agent.extract_username_from_text('title="Roblox - Blox Fruits"'))
        self.assertIsNone(agent.extract_username_from_text('title="Roblox - Adopt Me!"'))
        self.assertIsNone(agent.extract_username_from_text('title="Roblox - Pet Simulator 99"'))

        # Real usernames must still succeed
        self.assertEqual(agent.extract_username_from_text('title="Roblox - 👑 VanessaJoseph403 👑"'), "VanessaJoseph403")
        self.assertEqual(agent.extract_username_from_text('title="Roblox - Gamer_Boy99"'), "Gamer_Boy99")
        self.assertEqual(agent.extract_username_from_text('title="Roblox - ProGamer (@VanessaJoseph403)"'), "VanessaJoseph403")

    @mock.patch("agent.agent.run_adb_shell")
    def test_dumpsys_activity_avoids_cross_tab_contamination(self, mock_adb):
        """Verify dumpsys activity parser isolates packages and does not allow Tab 2 to steal Tab 3's intent username."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.ActivityProtocolLaunch t102}
              Intent { act=android.intent.action.MAIN cat=[android.intent.category.LAUNCHER] }
          TaskRecord{103 #103 A=com.tinh.vv.hk U=0}
            Hist #0: ActivityRecord{3 u0 com.tinh.vv.hk/com.roblox.client.ActivityProtocolLaunch t103}
              Intent { act=android.intent.action.VIEW dat=roblox://placeId=123&username=MysticjUBuildery1999 }
        """
        def side_effect(cmd, **kwargs):
            cmd_str = str(cmd)
            if "dumpsys activity" in cmd_str:
                return dumpsys_output
            return ""

        mock_adb.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_map_path = pathlib.Path(tmpdir) / "tab_accounts.json"
            agent.ensure_tab_accounts_file(temp_map_path)

            tabs = agent.query_tab_list(device_id="m77", tab_map_path=temp_map_path)
            self.assertEqual(len(tabs), 2)

            # Tab 2: com.tinh.vv.hj must NOT steal Tab 3's MysticjUBuildery1999 from dumpsys activity
            tab2 = next(t for t in tabs if t["package"] == "com.tinh.vv.hj")
            self.assertEqual(tab2["username"], "ShadowWoodrow820 (tab_map)")

            # Tab 3: com.tinh.vv.hk must have live username MysticjUBuildery1999 from its own intent
            tab3 = next(t for t in tabs if t["package"] == "com.tinh.vv.hk")
            self.assertEqual(tab3["username"], "MysticjUBuildery1999")
            self.assertFalse(tab3["username"].endswith("(tab_map)"))

    @mock.patch("agent.agent.run_adb_shell")
    def test_direct_boot_bfu_locked_storage_graceful_fallback(self, mock_adb):
        """Verify Direct Boot / BFU locked state gracefully falls back to tab_accounts.json without crashing."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.ActivityProtocolLaunch t102}
        """
        # All storage reads fail or return permission denied / empty
        mock_adb.return_value = ""
        mock_adb.side_effect = lambda cmd, **kwargs: dumpsys_output if "dumpsys activity" in str(cmd) else ""

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_map_path = pathlib.Path(tmpdir) / "tab_accounts.json"
            agent.ensure_tab_accounts_file(temp_map_path)

            tabs = agent.query_tab_list(device_id="m77", tab_map_path=temp_map_path)
            self.assertEqual(len(tabs), 1)
            self.assertEqual(tabs[0]["tab"], 2)
            self.assertEqual(tabs[0]["package"], "com.tinh.vv.hj")
            # Graceful fallback to fixed slot in tab_accounts.json
            self.assertEqual(tabs[0]["username"], "ShadowWoodrow820 (tab_map)")

    @mock.patch("agent.agent.run_adb_shell")
    def test_package_discovery_with_hyphens_and_uppercase(self, mock_adb):
        """Verify package discovery regex captures packages with hyphens, underscores, and uppercase letters."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{105 #105 A=com.tinh.vv.clone-1 U=0}
            Hist #0: ActivityRecord{5 u0 com.tinh.vv.clone-1/com.roblox.client.Activity t105}
          TaskRecord{106 #106 A=com.roblox.client-beta U=0}
            Hist #0: ActivityRecord{6 u0 com.roblox.client-beta/com.roblox.client.Activity t106}
        """
        mock_adb.side_effect = lambda cmd, **kwargs: dumpsys_output if "dumpsys activity" in str(cmd) else ""

        tabs = agent.query_tab_list(tab_map_path="/dev/null", acc_path="/dev/null")
        pkgs = [t["package"] for t in tabs]
        self.assertIn("com.tinh.vv.clone-1", pkgs)
        self.assertIn("com.roblox.client-beta", pkgs)

    @mock.patch("agent.agent.run_adb_shell")
    def test_query_tab_list_all_tabs_returns_all_10_canonical_tabs(self, mock_adb):
        """Verify that when all_tabs=True, all 10 canonical tabs (1..10) are returned even if only 2 are running."""
        dumpsys_output = """
        Stack #1:
          TaskRecord{101 #101 A=com.tinh.vv.hi U=0}
            Hist #0: ActivityRecord{1 u0 com.tinh.vv.hi/com.roblox.client.Activity t101}
          TaskRecord{102 #102 A=com.tinh.vv.hj U=0}
            Hist #0: ActivityRecord{2 u0 com.tinh.vv.hj/com.roblox.client.Activity t102}
        """
        mock_adb.side_effect = lambda cmd, **kwargs: dumpsys_output if "dumpsys activity" in str(cmd) else ""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = pathlib.Path(tmpdir)
            ban_file = tmppath / "acc_bi_ban.txt"
            ban_file.write_text("BannedUser5:pass\n", encoding="utf-8")

            tab_map_file = tmppath / "tab_accounts.json"
            tab_map_file.write_text(json.dumps({
                "com.tinh.vv.hi": "LiveUser1",
                "com.tinh.vv.hj": "LiveUser2",
                "com.tinh.vv.hm": "BannedUser5",
            }), encoding="utf-8")

            tabs = agent.query_tab_list(
                device_id="m77",
                tab_map_path=tab_map_file,
                all_tabs=True,
            )
            # Must return all 10 canonical tabs
            self.assertEqual(len(tabs), 10)
            tab_nums = [t["tab"] for t in tabs]
            self.assertEqual(tab_nums, list(range(1, 11)))

            # Tab 5 (com.tinh.vv.hm) must be flagged as banned
            tab5 = next(t for t in tabs if t["tab"] == 5)
            self.assertTrue(tab5["is_banned"])
            self.assertEqual(tab5["status"], "BANNED")

            html = agent.format_tab_list_html("m77", tabs)
            for i in range(1, 11):
                self.assertIn(f"Tab {i}:", html)
            self.assertIn("BannedUser5 (baned)", html)


if __name__ == "__main__":
    unittest.main()

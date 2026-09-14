import json
import pathlib
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

        tabs = agent.query_tab_list()
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
        tabs = agent.query_tab_list()
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


if __name__ == "__main__":
    unittest.main()

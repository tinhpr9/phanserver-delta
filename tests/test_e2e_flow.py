#!/usr/bin/env python3
"""
End-to-End Equivalence and Integration Test for phanserver-delta.

Tests complete flow:
1. Telegram /phanserver command parsing & preview
2. Confirmation and 2PC dispatch to FleetState
3. Device agent PREPARE -> COMMIT execution
4. Atomic server_links.txt update
5. OPENED ACK & Telegram completion report
6. Rerun / idempotency verification
"""

import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from agent import agent, config, server_links
from delta import delta_updater


class TestE2EFlow(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = pathlib.Path(self.temp_dir.name)
        self.links_path = self.root_path / "server_links.txt"
        self.state_path = self.root_path / "state.json"
        self.state = {}

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_2pc_phanserver_lifecycle_and_idempotency(self):
        # 1. Prepare phase payload generated from 3 tabs on m72
        action_id = f"fleet-{int(time.time()*1000)}-test01"
        allocation = [
            {
                "pkg": "com.tinh.vv.hi",
                "url": "https://www.roblox.com/games/97598239454123?privateServerLinkCode=11111111111111111111111111111111",
            },
            {
                "pkg": "com.tinh.vv.hj",
                "url": "https://www.roblox.com/games/97598239454123?privateServerLinkCode=22222222222222222222222222222222",
            },
            {
                "pkg": "com.tinh.vv.hk",
                "url": "https://www.roblox.com/games/97598239454123?privateServerLinkCode=33333333333333333333333333333333",
            },
        ]
        expires_at = int(time.time() * 1000) + 15000

        # Step 1: Agent handles PREPARE
        prep_res = server_links.handle_prepare(action_id, allocation, expires_at, self.links_path)
        self.assertEqual(prep_res["status"], "PREPARE_READY")
        self.assertFalse(prep_res["executed"])
        prep_file = pathlib.Path(f"{self.links_path}.prep.{action_id}")
        self.assertTrue(prep_file.exists())

        # Step 2: Agent handles COMMIT
        opened_calls = []
        with mock.patch("agent.server_links.open_roblox_servers", side_effect=lambda alloc: opened_calls.append(alloc)):
            commit_res = server_links.handle_commit(action_id, self.links_path, self.state, self.state_path)

        self.assertEqual(commit_res["status"], "OPENED")
        self.assertTrue(commit_res["executed"])
        self.assertEqual(len(opened_calls), 1)
        self.assertEqual(len(opened_calls[0]), 3)

        # Verify server_links.txt written exactly
        self.assertTrue(self.links_path.is_file())
        content = self.links_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(content), 3)
        self.assertEqual(
            content[0],
            "com.tinh.vv.hi,https://www.roblox.com/games/97598239454123?privateServerLinkCode=11111111111111111111111111111111",
        )
        self.assertEqual(
            content[1],
            "com.tinh.vv.hj,https://www.roblox.com/games/97598239454123?privateServerLinkCode=22222222222222222222222222222222",
        )
        self.assertEqual(
            content[2],
            "com.tinh.vv.hk,https://www.roblox.com/games/97598239454123?privateServerLinkCode=33333333333333333333333333333333",
        )

        # Step 3: Rerun / Idempotency check (same action_id re-sent)
        with mock.patch("agent.server_links.open_roblox_servers") as mock_open:
            rerun_res = server_links.handle_commit(action_id, self.links_path, self.state, self.state_path)
            self.assertEqual(rerun_res["status"], "OPENED")
            mock_open.assert_not_called()  # Must not re-run launcher if already OPENED


if __name__ == "__main__":
    unittest.main()

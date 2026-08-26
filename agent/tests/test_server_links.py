import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from agent import server_links


class TestServerLinks2PC(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = pathlib.Path(self.temp_dir.name)
        self.links_path = self.root_path / "server_links.txt"
        self.state_path = self.root_path / "state.json"
        self.state = {}

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_prepare_invalid_format(self):
        res = server_links.handle_prepare("a1", "not-a-list", int(time.time() * 1000) + 10000, self.links_path)
        self.assertEqual(res["status"], "PREPARE_FAILED")
        self.assertEqual(res["reason"], "invalid_allocation_format")

    def test_prepare_invalid_package_order(self):
        alloc = [
            {"pkg": "com.tinh.vv.hi", "url": "https://www.roblox.com/games/123?privateServerLinkCode=abc"},
            {"pkg": "com.tinh.vv.hk", "url": "https://www.roblox.com/games/123?privateServerLinkCode=def"},
        ]
        res = server_links.handle_prepare("a2", alloc, int(time.time() * 1000) + 10000, self.links_path)
        self.assertEqual(res["status"], "PREPARE_FAILED")
        self.assertEqual(res["reason"], "invalid_package_order_at_1")

    def test_prepare_invalid_roblox_url(self):
        alloc = [
            {"pkg": "com.tinh.vv.hi", "url": "https://invalid.url/games/123?code=abc"}
        ]
        res = server_links.handle_prepare("a3", alloc, int(time.time() * 1000) + 10000, self.links_path)
        self.assertEqual(res["status"], "PREPARE_FAILED")
        self.assertEqual(res["reason"], "invalid_roblox_url_at_0")

    def test_prepare_duplicate_url(self):
        alloc = [
            {"pkg": "com.tinh.vv.hi", "url": "https://www.roblox.com/games/123?privateServerLinkCode=abc"},
            {"pkg": "com.tinh.vv.hj", "url": "https://www.roblox.com/games/123?privateServerLinkCode=abc"},
        ]
        res = server_links.handle_prepare("a4", alloc, int(time.time() * 1000) + 10000, self.links_path)
        self.assertEqual(res["status"], "PREPARE_FAILED")
        self.assertEqual(res["reason"], "duplicate_url_at_1")

    def test_prepare_timeout(self):
        alloc = [{"pkg": "com.tinh.vv.hi", "url": "https://www.roblox.com/games/123?privateServerLinkCode=abc"}]
        res = server_links.handle_prepare("a5", alloc, int(time.time() * 1000) - 10000, self.links_path)
        self.assertEqual(res["status"], "TIMEOUT")

    def test_prepare_success_writes_prep_file(self):
        alloc = [{"pkg": "com.tinh.vv.hi", "url": "https://www.roblox.com/games/123?privateServerLinkCode=abc"}]
        res = server_links.handle_prepare("a6", alloc, int(time.time() * 1000) + 10000, self.links_path)
        self.assertEqual(res["status"], "PREPARE_READY")
        prep_file = pathlib.Path(f"{self.links_path}.prep.a6")
        self.assertTrue(prep_file.exists())
        self.assertIn("com.tinh.vv.hi,https://www.roblox.com/games/123?privateServerLinkCode=abc", prep_file.read_text())

    @mock.patch("agent.server_links.open_roblox_servers")
    def test_commit_success_and_idempotency(self, mock_open):
        alloc = [{"pkg": "com.tinh.vv.hi", "url": "https://www.roblox.com/games/123?privateServerLinkCode=abc"}]
        server_links.handle_prepare("a7", alloc, int(time.time() * 1000) + 10000, self.links_path)

        # First commit
        res = server_links.handle_commit("a7", self.links_path, self.state, self.state_path)
        self.assertEqual(res["status"], "OPENED")
        self.assertTrue(self.links_path.exists())
        self.assertEqual(mock_open.call_count, 1)

        # Idempotent replay: does not re-run open_roblox_servers
        res_replay = server_links.handle_commit("a7", self.links_path, self.state, self.state_path)
        self.assertEqual(res_replay["status"], "OPENED")
        self.assertEqual(mock_open.call_count, 1)

    @mock.patch("agent.server_links.open_roblox_servers", side_effect=RuntimeError("Intent launch failed"))
    def test_commit_failure_rolls_back(self, mock_open):
        # Baseline file
        self.links_path.write_text("initial_content\n")

        alloc = [{"pkg": "com.tinh.vv.hi", "url": "https://www.roblox.com/games/123?privateServerLinkCode=abc"}]
        server_links.handle_prepare("a8", alloc, int(time.time() * 1000) + 10000, self.links_path)

        res = server_links.handle_commit("a8", self.links_path, self.state, self.state_path)
        self.assertEqual(res["status"], "FAILED")
        self.assertIn("Intent launch failed", res["reason"])
        # Assert restored
        self.assertEqual(self.links_path.read_text(), "initial_content\n")

    def test_abort_cleans_prep_file(self):
        alloc = [{"pkg": "com.tinh.vv.hi", "url": "https://www.roblox.com/games/123?privateServerLinkCode=abc"}]
        server_links.handle_prepare("a9", alloc, int(time.time() * 1000) + 10000, self.links_path)
        prep_file = pathlib.Path(f"{self.links_path}.prep.a9")
        self.assertTrue(prep_file.exists())

        res = server_links.handle_abort("a9", self.links_path)
        self.assertEqual(res["status"], "FAILED")
        self.assertEqual(res["reason"], "aborted_by_hub")
        self.assertFalse(prep_file.exists())


if __name__ == "__main__":
    unittest.main()

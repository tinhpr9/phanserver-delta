import json
import pathlib
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from agent import agent, config


class TestDeviceAgent(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = pathlib.Path(self.temp_dir.name)
        self.links_path = self.root_path / "server_links.txt"
        self.state_path = self.root_path / "state.json"
        self.cfg_path = self.root_path / "agent_config.json"
        self.id_path = self.root_path / "device_id.txt"
        self.group_path = self.root_path / "device_group.txt"

        self.cfg_path.write_text(json.dumps({
            "worker_report_url": "https://mock.worker/report",
            "agent_report_secret": "test-secret"
        }))
        self.id_path.write_text("m72\n")
        self.group_path.write_text("NOVA\n")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_config_loading(self):
        self.assertEqual(config.load_device_id(self.id_path), "m72")
        self.assertEqual(config.load_device_group(self.group_path), "NOVA")
        cfg = config.load_agent_config(self.cfg_path)
        self.assertEqual(cfg["agent_report_secret"], "test-secret")

    def test_collect_metrics(self):
        m = agent.collect_metrics()
        self.assertIn("uptime", m)
        self.assertIn("battery_pct", m)

    @mock.patch("agent.agent.send_report", return_value=True)
    def test_send_ack(self, mock_send):
        res = agent.send_ack(
            report_url="https://mock.worker/report",
            secret="sec",
            device_id="m72",
            action_id="act1",
            status="PREPARE_READY",
            executed=False
        )
        self.assertTrue(res)
        mock_send.assert_called_once()
        url, sec, payload = mock_send.call_args[0]
        self.assertEqual(url, "https://mock.worker/aot/ack")
        self.assertEqual(payload["status"], "PREPARE_READY")

    @mock.patch("agent.agent.send_ack", return_value=True)
    def test_handle_incoming_prepare_and_commit(self, mock_ack):
        state = {}
        msg_prep = {
            "type": "aot_batch_action",
            "protocol": "fleet-batch-v1",
            "action": "PREPARE_ALLOCATE_SERVER",
            "action_id": "act-100",
            "target_device_ids": ["m72"],
            "expires_at": 9999999999999,
            "allocation": [
                {"pkg": "com.tinh.vv.hi", "url": "https://www.roblox.com/games/123?privateServerLinkCode=abc"}
            ]
        }
        res_prep = agent.handle_incoming_batch_action(
            msg_prep, "m72", "https://mock/report", "sec", state, self.state_path, self.links_path
        )
        self.assertTrue(res_prep)
        self.assertEqual(mock_ack.call_args[1]["status"], "PREPARE_READY")

        msg_commit = {
            "type": "aot_batch_action",
            "protocol": "fleet-batch-v1",
            "action": "COMMIT_ALLOCATE_SERVER",
            "action_id": "act-100",
            "target_device_ids": ["m72"]
        }
        with mock.patch("agent.server_links.open_roblox_servers"):
            res_commit = agent.handle_incoming_batch_action(
                msg_commit, "m72", "https://mock/report", "sec", state, self.state_path, self.links_path
            )
            self.assertTrue(res_commit)
            self.assertEqual(mock_ack.call_args[1]["status"], "OPENED")

    @mock.patch("agent.agent.send_report", return_value=True)
    def test_run_agent_loop_once(self, mock_report):
        agent.run_agent_loop(
            config_path=self.cfg_path,
            device_id_path=self.id_path,
            device_group_path=self.group_path,
            state_path=self.state_path,
            links_path=self.links_path,
            single_tick=True
        )
        mock_report.assert_called_once()
        payload = mock_report.call_args[0][2]
        self.assertEqual(payload["device_id"], "m72")
        self.assertEqual(payload["device_group"], "NOVA")
        self.assertIn("allocate_server_2pc", payload["capabilities"])

    @mock.patch("agent.agent.send_report", return_value=True)
    def test_missing_device_id_fails_closed_instead_of_aliasing_m72(self, mock_report):
        self.id_path.unlink()
        with self.assertRaisesRegex(RuntimeError, "device_id_missing_or_invalid"):
            agent.run_agent_loop(
                config_path=self.cfg_path,
                device_id_path=self.id_path,
                device_group_path=self.group_path,
                state_path=self.state_path,
                links_path=self.links_path,
                single_tick=True,
            )
        mock_report.assert_not_called()

    def test_build_websocket_url_uses_same_worker_and_device_identity(self):
        ws_url = agent.build_websocket_url(
            "https://mock.worker/report",
            "m73",
            "NOVA",
            "pair-secret",
        )
        parsed = urlparse(ws_url)
        self.assertEqual(parsed.scheme, "wss")
        self.assertEqual(parsed.netloc, "mock.worker")
        self.assertEqual(parsed.path, "/ws")
        query = parse_qs(parsed.query)
        self.assertEqual(query["device_id"], ["m73"])
        self.assertEqual(query["group"], ["NOVA"])
        self.assertEqual(query["secret"], ["pair-secret"])

    @mock.patch("agent.agent.run_websocket_session", return_value=None)
    @mock.patch("agent.agent.send_report", return_value=True)
    def test_long_running_agent_enters_websocket_receive_session(self, mock_report, mock_ws):
        agent.run_agent_loop(
            config_path=self.cfg_path,
            device_id_path=self.id_path,
            device_group_path=self.group_path,
            state_path=self.state_path,
            links_path=self.links_path,
            single_tick=False,
            max_sessions=1,
        )
        mock_report.assert_called()
        mock_ws.assert_called_once()
        args = mock_ws.call_args.args
        self.assertEqual(args[0], "https://mock.worker/report")
        self.assertEqual(args[1], "test-secret")
        self.assertEqual(args[2], "m72")
        self.assertEqual(args[3], "NOVA")


if __name__ == "__main__":
    unittest.main()

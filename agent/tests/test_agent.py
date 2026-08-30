import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

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

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.delta_updater.run_delta_update")
    def test_update_delta_is_idempotent(self, mock_update, mock_ack):
        message = {
            "protocol": "fleet-batch-v1",
            "action": "UPDATE_DELTA",
            "action_id": "delta-100",
            "target_device_ids": ["m72"],
        }
        state = {}
        self.assertTrue(agent.handle_incoming_batch_action(
            message, "m72", "https://mock/report", "sec", state, self.state_path, self.links_path
        ))
        self.assertEqual(mock_update.call_count, 1)
        self.assertEqual(mock_ack.call_args.kwargs["batch_action"], "UPDATE_DELTA")
        self.assertTrue(self.state_path.is_file())
        self.assertTrue(agent.handle_incoming_batch_action(
            message, "m72", "https://mock/report", "sec", state, self.state_path, self.links_path
        ))
        self.assertEqual(mock_update.call_count, 1)

    @mock.patch("agent.agent.send_report_response", return_value={})
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
    @mock.patch("agent.agent.subprocess.run")
    def test_check_and_apply_auto_update(self, mock_subproc):
        mock_subproc.return_value.returncode = 0
        mock_subproc.return_value.stdout = "ok"
        mock_subproc.return_value.stderr = ""
        with mock.patch("agent.agent.ROOT", self.root_path):
            (self.root_path / ".git").mkdir()
            success, err = agent.check_and_apply_auto_update(branch="fix/delta-stability")
            self.assertTrue(success)
            self.assertIsNone(err)
            self.assertEqual(mock_subproc.call_count, 2)

    def test_create_folder_backup(self):
        from agent import backup_manager
        test_dir = self.root_path / "TestFolder"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("hello world")
        (test_dir / "file2.json").write_text('{"key": "value"}')

        out_zip = backup_manager.create_folder_backup("TestFolder", str(test_dir), self.root_path)
        self.assertTrue(out_zip.is_file())
        self.assertEqual(out_zip.name, "Testfolder_FolderBackup.zip")

        import zipfile
        with zipfile.ZipFile(out_zip, "r") as zf:
            self.assertIn("folder_meta.json", zf.namelist())
            self.assertIn("folder.tar.gz", zf.namelist())
            meta = json.loads(zf.read("folder_meta.json").decode("utf-8"))
            self.assertEqual(meta["type"], "folder")
            self.assertEqual(meta["folder_name"], "TestFolder")


if __name__ == "__main__":
    unittest.main()

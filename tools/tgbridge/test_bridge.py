import importlib.util
import pathlib
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).with_name("bridge.py")
SPEC = importlib.util.spec_from_file_location("tgbridge_bridge", MODULE_PATH)
bridge = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(bridge)


class TestTelegramBridge(unittest.TestCase):
    def test_only_status_and_update_are_executed_for_allowed_chat(self):
        with mock.patch.object(bridge, "send") as send, mock.patch.object(
            bridge, "status_text", return_value="STATUS_OK"
        ) as status, mock.patch.object(bridge, "update_text", return_value="UPDATE_OK") as update:
            bridge.handle_message("token", "123", {"chat": {"id": 123}, "text": "STATUS"})
            bridge.handle_message("token", "123", {"chat": {"id": 123}, "text": "UPDATE"})
            bridge.handle_message("token", "123", {"chat": {"id": 123}, "text": "rm -rf /"})

        status.assert_called_once_with()
        update.assert_called_once_with()
        self.assertEqual(send.call_count, 4)
        self.assertIn("Lệnh hợp lệ", send.call_args.args[2])

    def test_non_allowed_chat_is_ignored(self):
        with mock.patch.object(bridge, "send") as send, mock.patch.object(bridge, "update_text") as update:
            bridge.handle_message("token", "123", {"chat": {"id": 999}, "text": "UPDATE"})
        send.assert_not_called()
        update.assert_not_called()

    @mock.patch.object(bridge, "run_checked")
    def test_update_uses_fixed_updater_without_message_arguments(self, run_checked):
        run_checked.return_value = mock.MagicMock(returncode=0, stdout="Success", stderr="")
        text = bridge.update_text()
        self.assertEqual(run_checked.call_args.args[0], [bridge.sys.executable, "delta/delta_updater.py"])
        self.assertEqual(run_checked.call_args.kwargs["timeout"], bridge.UPDATE_TIMEOUT_SECONDS)
        self.assertIn("UPDATE_RC=0", text)


if __name__ == "__main__":
    unittest.main()

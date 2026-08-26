import hashlib
import json
import os
import pathlib
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from delta import delta_updater


class TestDeltaUpdater(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = pathlib.Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_calculate_sha256(self):
        f = self.root_path / "test.bin"
        f.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        self.assertEqual(delta_updater.calculate_sha256(f), expected)

    def test_load_manifest_valid_dict(self):
        manifest_data = {
            "channel": "delta",
            "version": "1.2.3",
            "assets": [{"name": "test.apk", "url": "file:///tmp/test.apk"}]
        }
        res = delta_updater.load_manifest(manifest_data)
        self.assertEqual(res["version"], "1.2.3")

    def test_load_manifest_invalid_channel(self):
        manifest_data = {
            "channel": "worker",
            "version": "1.2.3",
            "assets": [{"name": "test.apk", "url": "file:///tmp/test.apk"}]
        }
        with self.assertRaises(delta_updater.DeltaUpdaterError) as ctx:
            delta_updater.load_manifest(manifest_data)
        self.assertIn("Invalid channel in manifest", str(ctx.exception))

    def test_load_manifest_empty_assets(self):
        manifest_data = {"channel": "delta", "version": "1.0", "assets": []}
        with self.assertRaises(delta_updater.DeltaUpdaterError) as ctx:
            delta_updater.load_manifest(manifest_data)
        self.assertIn("no assets", str(ctx.exception))

    @mock.patch("delta.delta_updater.root_available", return_value=False)
    def test_install_apk_non_root_fails_accurately(self, mock_root):
        apk_path = self.root_path / "fake.apk"
        apk_path.write_bytes(b"fake-apk")
        with self.assertRaises(delta_updater.DeltaUpdaterError) as ctx:
            delta_updater.install_apk(apk_path)
        self.assertIn("Root access required", str(ctx.exception))
        self.assertIn("Non-root environment is unsupported", str(ctx.exception))

    @mock.patch("delta.delta_updater.root_available", return_value=True)
    @mock.patch("subprocess.run")
    def test_install_apk_root_success(self, mock_run, mock_root):
        mock_run.return_value = mock.MagicMock(returncode=0, stdout="Success\n", stderr="")
        apk_path = self.root_path / "fake.apk"
        apk_path.write_bytes(b"fake-apk")
        delta_updater.install_apk(apk_path)
        mock_run.assert_called_once()
        self.assertIn("pm install -r", mock_run.call_args[0][0][2])

    @mock.patch("delta.delta_updater.root_available", return_value=True)
    @mock.patch("subprocess.run")
    def test_install_apk_pm_failure_throws(self, mock_run, mock_root):
        mock_run.return_value = mock.MagicMock(returncode=1, stdout="Failure [INSTALL_FAILED_ALREADY_EXISTS]\n", stderr="")
        apk_path = self.root_path / "fake.apk"
        apk_path.write_bytes(b"fake-apk")
        with self.assertRaises(delta_updater.DeltaUpdaterError) as ctx:
            delta_updater.install_apk(apk_path)
        self.assertIn("pm install failed", str(ctx.exception))

    def test_extract_zip_apks(self):
        zip_path = self.root_path / "download.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("test1.apk", b"apk1-content")
            zf.writestr("test2.apk", b"apk2-content")
            zf.writestr("ignore.txt", b"txt-content")

        out_dir = self.root_path / "extracted"
        apks = delta_updater.extract_zip_apks(zip_path, out_dir)
        self.assertEqual(len(apks), 2)
        self.assertTrue(all(p.name.endswith(".apk") for p in apks))

    def test_extract_zip_no_apks_throws(self):
        zip_path = self.root_path / "empty.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("ignore.txt", b"txt-content")

        out_dir = self.root_path / "extracted"
        with self.assertRaises(delta_updater.DeltaUpdaterError) as ctx:
            delta_updater.extract_zip_apks(zip_path, out_dir)
        self.assertIn("contains no APK files", str(ctx.exception))

    @mock.patch("delta.delta_updater.root_available", return_value=True)
    @mock.patch("subprocess.run")
    def test_run_delta_update_sha256_mismatch(self, mock_run, mock_root):
        apk_file = self.root_path / "test.apk"
        apk_file.write_bytes(b"test-apk-bytes")

        manifest = {
            "channel": "delta",
            "version": "1.0.0",
            "assets": [
                {
                    "name": "test.apk",
                    "url": f"file://{apk_file}",
                    "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                }
            ]
        }
        with self.assertRaises(delta_updater.DeltaUpdaterError) as ctx:
            delta_updater.run_delta_update(manifest, download_dir=self.root_path / "dl")
        self.assertIn("SHA256 checksum mismatch", str(ctx.exception))

    @mock.patch("delta.delta_updater.root_available", return_value=True)
    @mock.patch("subprocess.run")
    def test_run_delta_update_success(self, mock_run, mock_root):
        mock_run.return_value = mock.MagicMock(returncode=0, stdout="Success\n", stderr="")
        apk_file = self.root_path / "test.apk"
        apk_bytes = b"valid-apk-content"
        apk_file.write_bytes(apk_bytes)
        sha = hashlib.sha256(apk_bytes).hexdigest()

        manifest = {
            "channel": "delta",
            "version": "2.0.0",
            "assets": [
                {
                    "name": "Delta-2.0.0.apk",
                    "url": f"file://{apk_file}",
                    "sha256": sha,
                }
            ]
        }
        res = delta_updater.run_delta_update(manifest, download_dir=self.root_path / "dl")
        self.assertTrue(res["ok"])
        self.assertEqual(res["installed_count"], 1)
        self.assertEqual(res["version"], "2.0.0")


if __name__ == "__main__":
    unittest.main()

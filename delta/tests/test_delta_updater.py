import hashlib
import io
import pathlib
import shlex
import stat
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from delta import delta_updater


class TestDeltaUpdater(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = pathlib.Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def asset(self, path: pathlib.Path, name: str | None = None) -> dict:
        payload = path.read_bytes()
        return {
            "name": name or path.name,
            "url": path.as_uri(),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
        }

    def manifest(self, *assets: dict, version: str = "test") -> dict:
        return {"channel": "delta", "version": version, "assets": list(assets)}

    def test_calculate_sha256(self):
        path = self.root_path / "test.bin"
        path.write_bytes(b"hello world")
        self.assertEqual(delta_updater.calculate_sha256(path), hashlib.sha256(b"hello world").hexdigest())

    def test_manifest_accepts_arbitrary_apk_names_and_count(self):
        assets = []
        for index, name in enumerate(["Delta.apk", "Swift Backup.apk", "Tên ứng dụng 03.apk"], 1):
            path = self.root_path / f"src-{index}.apk"
            path.write_bytes(f"payload-{index}".encode())
            assets.append(self.asset(path, name=name))
        loaded = delta_updater.load_manifest(self.manifest(*assets))
        self.assertEqual([item["name"] for item in loaded["assets"]], ["Delta.apk", "Swift Backup.apk", "Tên ứng dụng 03.apk"])

    def test_manifest_requires_integrity_and_positive_size(self):
        base = {"name": "Any Name.apk", "url": "https://example.test/app.apk"}
        for broken in (base, {**base, "sha256": "0" * 64}, {**base, "sha256": "0" * 64, "size": 0}):
            with self.assertRaises(delta_updater.DeltaUpdaterError):
                delta_updater.load_manifest(self.manifest(broken))

    def test_manifest_rejects_http_unknown_type_and_path_names(self):
        valid_hash = "1" * 64
        bad_assets = (
            {"name": "A.apk", "url": "http://example.test/A.apk", "sha256": valid_hash, "size": 1},
            {"name": "A.exe", "url": "https://example.test/A.exe", "sha256": valid_hash, "size": 1},
            {"name": "dir/A.apk", "url": "https://example.test/A.apk", "sha256": valid_hash, "size": 1},
            "not-an-object",
        )
        for asset in bad_assets:
            with self.assertRaises(delta_updater.DeltaUpdaterError):
                delta_updater.load_manifest(self.manifest(asset))

    def test_download_hash_failure_is_atomic_and_cleans_part(self):
        source = self.root_path / "source.apk"
        source.write_bytes(b"new-corrupt-bytes")
        destination = self.root_path / "destination.apk"
        destination.write_bytes(b"known-good-old")
        with self.assertRaisesRegex(delta_updater.DeltaUpdaterError, "SHA256 checksum mismatch"):
            delta_updater.download_asset(
                source.as_uri(), destination,
                expected_size=source.stat().st_size,
                expected_sha256="0" * 64,
            )
        self.assertEqual(destination.read_bytes(), b"known-good-old")
        self.assertFalse(destination.with_name(destination.name + ".part").exists())

    def test_download_rejects_size_mismatch_before_replace(self):
        source = self.root_path / "source.apk"
        source.write_bytes(b"123456")
        destination = self.root_path / "destination.apk"
        destination.write_bytes(b"old")
        with self.assertRaisesRegex(delta_updater.DeltaUpdaterError, "size mismatch"):
            delta_updater.download_asset(
                source.as_uri(), destination,
                expected_size=7,
                expected_sha256=hashlib.sha256(b"123456").hexdigest(),
            )
        self.assertEqual(destination.read_bytes(), b"old")

    def test_download_reports_progress_when_label_is_provided(self):
        source = self.root_path / "progress.apk"
        source.write_bytes(b"progress-payload")
        destination = self.root_path / "downloaded.apk"
        output = io.StringIO()
        with redirect_stdout(output):
            delta_updater.download_asset(
                source.as_uri(),
                destination,
                expected_size=source.stat().st_size,
                expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                progress_label="asset 1/1 progress.apk",
            )
        self.assertIn("[DOWNLOAD] asset 1/1 progress.apk: 0%", output.getvalue())
        self.assertIn("[DOWNLOAD] asset 1/1 progress.apk: 100%", output.getvalue())

    @mock.patch("delta.delta_updater.root_available", return_value=False)
    def test_install_apk_non_root_fails_accurately(self, _mock_root):
        apk = self.root_path / "fake.apk"
        apk.write_bytes(b"fake-apk")
        with self.assertRaisesRegex(delta_updater.DeltaUpdaterError, "Root access required"):
            delta_updater.install_apk(apk)

    @mock.patch("delta.delta_updater.os.geteuid", return_value=0)
    @mock.patch("delta.delta_updater.root_available", return_value=True)
    @mock.patch("delta.delta_updater.subprocess.run")
    def test_install_apk_root_uses_argv_not_shell_text(self, mock_run, _mock_root, _mock_euid):
        mock_run.return_value = mock.MagicMock(returncode=0, stdout="Success\n", stderr="")
        apk = self.root_path / "name with ; shell.apk"
        apk.write_bytes(b"fake-apk")
        delta_updater.install_apk(apk)
        self.assertEqual(mock_run.call_args.args[0], ["pm", "install", "-r", "-d", str(apk)])
        self.assertNotIn("stdin", mock_run.call_args.kwargs)
        self.assertNotIn("shell", mock_run.call_args.kwargs)

    @mock.patch("delta.delta_updater.shutil.which", return_value="/system/xbin/su")
    @mock.patch("delta.delta_updater.os.geteuid", return_value=2000)
    @mock.patch("delta.delta_updater.root_available", return_value=True)
    @mock.patch("delta.delta_updater.subprocess.run")
    def test_install_apk_via_su_quotes_path_safely(self, mock_run, _mock_root, _mock_euid, _mock_which):
        apk = self.root_path / "phone.apk"
        apk.write_bytes(b"fake-apk")
        mock_run.return_value = mock.MagicMock(returncode=0, stdout="Success\n", stderr="")
        delta_updater.install_apk(apk)

        expected_cmd = f"exec pm install -r -d {shlex.quote(str(apk))}"
        self.assertEqual(
            mock_run.call_args.args[0],
            ["/system/xbin/su", "-c", expected_cmd],
        )
        self.assertNotIn("stdin", mock_run.call_args.kwargs)

    @mock.patch("delta.delta_updater.shutil.which", return_value="/system/xbin/su")
    @mock.patch("delta.delta_updater.os.geteuid", return_value=2000)
    @mock.patch("delta.delta_updater.root_available", return_value=True)
    @mock.patch("delta.delta_updater.subprocess.run")
    def test_install_apk_via_su_handles_special_characters_and_spaces(self, mock_run, _mock_root, _mock_euid, _mock_which):
        apk = self.root_path / "Tên ứng dụng $1 `test` & more.apk"
        apk.write_bytes(b"payload")
        mock_run.return_value = mock.MagicMock(returncode=0, stdout="Success\n", stderr="")
        delta_updater.install_apk(apk)

        expected_cmd = f"exec pm install -r -d {shlex.quote(str(apk))}"
        self.assertEqual(
            mock_run.call_args.args[0],
            ["/system/xbin/su", "-c", expected_cmd],
        )
        self.assertNotIn("-S", expected_cmd)
        self.assertFalse(expected_cmd.endswith(" -"))
        self.assertNotIn("stdin", mock_run.call_args.kwargs)

    def test_extract_zip_apks_crc_and_normal_content(self):
        archive = self.root_path / "download.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("one.apk", b"apk-one")
            bundle.writestr("nested/two.apk", b"apk-two")
            bundle.writestr("ignore.txt", b"text")
        apks = delta_updater.extract_zip_apks(archive, self.root_path / "extract")
        self.assertEqual([path.read_bytes() for path in apks], [b"apk-one", b"apk-two"])

    def test_extract_zip_rejects_traversal_and_symlink(self):
        traversal = self.root_path / "traversal.zip"
        with zipfile.ZipFile(traversal, "w") as bundle:
            bundle.writestr("../escape.apk", b"apk")
        with self.assertRaisesRegex(delta_updater.DeltaUpdaterError, "Unsafe ZIP path"):
            delta_updater.extract_zip_apks(traversal, self.root_path / "extract-traversal")

        symlink = self.root_path / "symlink.zip"
        info = zipfile.ZipInfo("link.apk")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(symlink, "w") as bundle:
            bundle.writestr(info, "target.apk")
        with self.assertRaisesRegex(delta_updater.DeltaUpdaterError, "symlink"):
            delta_updater.extract_zip_apks(symlink, self.root_path / "extract-symlink")

    def test_mixed_direct_apk_and_zip_are_all_selected(self):
        one = self.root_path / "one.apk"
        archive = self.root_path / "bundle.zip"
        one.write_bytes(b"one")
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("inside.apk", b"inside")
        loaded = delta_updater.load_manifest(self.manifest(self.asset(archive), self.asset(one)))
        selected = delta_updater._select_assets(loaded["assets"])
        self.assertEqual([item["name"] for item in selected], ["bundle.zip", "one.apk"])

    @mock.patch("delta.delta_updater.install_apk")
    def test_run_delta_update_installs_direct_and_zip_apks_after_full_verification(self, mock_install):
        direct = self.root_path / "direct.apk"
        direct.write_bytes(b"direct")
        archive = self.root_path / "bundle.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("inside-one.apk", b"one")
            bundle.writestr("inside-two.apk", b"two")
        download_root = self.root_path / "downloads"
        result = delta_updater.run_delta_update(
            self.manifest(self.asset(direct), self.asset(archive)),
            download_dir=download_root,
        )
        self.assertEqual(result["installed_count"], 3)
        self.assertEqual(mock_install.call_count, 2)
        self.assertEqual(list(download_root.iterdir()), [])

    @mock.patch("delta.delta_updater.install_apk")
    def test_failure_in_later_download_installs_nothing(self, mock_install):
        first = self.root_path / "first.apk"
        second = self.root_path / "second.zip"
        first.write_bytes(b"first-good")
        with zipfile.ZipFile(second, "w") as bundle:
            bundle.writestr("inside.apk", b"inside")
        first_asset = self.asset(first)
        second_asset = self.asset(second)
        second_asset["sha256"] = "0" * 64
        with self.assertRaisesRegex(delta_updater.DeltaUpdaterError, "SHA256 checksum mismatch"):
            delta_updater.run_delta_update(
                self.manifest(first_asset, second_asset),
                download_dir=self.root_path / "downloads",
            )
        mock_install.assert_not_called()

    @mock.patch("delta.delta_updater.shutil.which", return_value="/system/xbin/su")
    @mock.patch("delta.delta_updater.os.geteuid", return_value=2000)
    @mock.patch("delta.delta_updater.root_available", return_value=True)
    @mock.patch("delta.delta_updater.subprocess.run")
    def test_e2e_updater_full_flow_with_su_subprocess(self, mock_run, _mock_root, _mock_euid, _mock_which):
        direct = self.root_path / "app1.apk"
        direct.write_bytes(b"APK_PAYLOAD_1")
        archive = self.root_path / "bundle.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("nested.apk", b"APK_PAYLOAD_NESTED")

        installed_commands = []

        def mock_su_run(cmd_args, **kwargs):
            installed_commands.append(cmd_args)
            self.assertNotIn("stdin", kwargs)
            return mock.MagicMock(returncode=0, stdout="Success\n", stderr="")

        mock_run.side_effect = mock_su_run

        download_root = self.root_path / "downloads_e2e"
        result = delta_updater.run_delta_update(
            self.manifest(self.asset(direct), self.asset(archive)),
            download_dir=download_root,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["installed_count"], 2)
        self.assertEqual(len(installed_commands), 2)
        # Verify commands contain safe direct quoted paths without -S or trailing -
        for cmd in installed_commands:
            self.assertEqual(cmd[0], "/system/xbin/su")
            self.assertEqual(cmd[1], "-c")
            self.assertTrue(cmd[2].startswith("exec pm install -r -d "))
            self.assertNotIn("-S", cmd[2])
            self.assertFalse(cmd[2].endswith(" -"))
        # Verify download directory cleaned up
        self.assertEqual(list(download_root.iterdir()), [])

    def test_filter_apks_modes(self):
        apks = [
            pathlib.Path("0001_1.1.1.1_warp.apk"),
            pathlib.Path("0002_opera_mini.apk"),
            pathlib.Path("0003_delta_roblox_1.apk"),
            pathlib.Path("0004_delta_roblox_2.apk"),
            pathlib.Path("0005_swift_backup.apk"),
        ]
        # All
        self.assertEqual(len(delta_updater.filter_apks(apks, "all")), 5)
        # By index
        self.assertEqual(delta_updater.filter_apks(apks, "2"), [apks[1]])
        # By range
        self.assertEqual(delta_updater.filter_apks(apks, "1-3"), apks[0:3])
        # By keyword
        self.assertEqual(delta_updater.filter_apks(apks, "opera"), [apks[1]])
        self.assertEqual(len(delta_updater.filter_apks(apks, "delta")), 2)
        # Random
        self.assertEqual(len(delta_updater.filter_apks(apks, "random")), 1)
        # Keyword random
        res_kw_rnd = delta_updater.filter_apks(apks, "delta:random")
        self.assertEqual(len(res_kw_rnd), 1)
        self.assertIn("delta", res_kw_rnd[0].name)
        # Multi-keyword
        res_multi = delta_updater.filter_apks(apks, "1.1.1,opera,swift")
        self.assertEqual(len(res_multi), 3)


if __name__ == "__main__":
    unittest.main()

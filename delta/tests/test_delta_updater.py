import hashlib
import pathlib
import stat
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
        self.assertNotIn("shell", mock_run.call_args.kwargs)

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

    def test_direct_apks_are_all_preferred_over_zip(self):
        one = self.root_path / "one.apk"
        two = self.root_path / "two.apk"
        archive = self.root_path / "bundle.zip"
        one.write_bytes(b"one")
        two.write_bytes(b"two")
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("inside.apk", b"inside")
        loaded = delta_updater.load_manifest(self.manifest(self.asset(archive), self.asset(one), self.asset(two)))
        selected = delta_updater._select_assets(loaded["assets"])
        self.assertEqual([item["name"] for item in selected], ["one.apk", "two.apk"])

    @mock.patch("delta.delta_updater.install_apk")
    def test_run_delta_update_installs_arbitrary_number_after_full_verification(self, mock_install):
        assets = []
        for index in range(7):
            apk = self.root_path / f"source-{index}.apk"
            apk.write_bytes(f"apk-{index}".encode())
            assets.append(self.asset(apk, name=f"App tùy ý {index}.apk"))
        download_root = self.root_path / "downloads"
        result = delta_updater.run_delta_update(self.manifest(*assets), download_dir=download_root)
        self.assertEqual(result["installed_count"], 7)
        self.assertEqual(mock_install.call_count, 7)
        self.assertEqual(list(download_root.iterdir()), [])

    @mock.patch("delta.delta_updater.install_apk")
    def test_failure_in_later_download_installs_nothing(self, mock_install):
        first = self.root_path / "first.apk"
        second = self.root_path / "second.apk"
        first.write_bytes(b"first-good")
        second.write_bytes(b"second-bad")
        first_asset = self.asset(first)
        second_asset = self.asset(second)
        second_asset["sha256"] = "0" * 64
        with self.assertRaisesRegex(delta_updater.DeltaUpdaterError, "SHA256 checksum mismatch"):
            delta_updater.run_delta_update(
                self.manifest(first_asset, second_asset),
                download_dir=self.root_path / "downloads",
            )
        mock_install.assert_not_called()


if __name__ == "__main__":
    unittest.main()

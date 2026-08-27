import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from delta.release_selector import ReleaseSelectionError, select_latest_stable_delta_release

SHA_A = "a" * 64
SHA_B = "b" * 64
REPO = "tinhpr9/phanserver-delta"


def asset(name, *, size=123, sha=SHA_A, url=None):
    return {
        "name": name,
        "size": size,
        "digest": f"sha256:{sha}",
        "browser_download_url": url
        or f"https://github.com/{REPO}/releases/download/delta-test/{name}",
    }


def release(release_id, published, assets, *, tag="delta-test", name="Delta", draft=False, prerelease=False):
    return {
        "id": release_id,
        "tag_name": tag,
        "name": name,
        "draft": draft,
        "prerelease": prerelease,
        "created_at": published,
        "published_at": published,
        "html_url": f"https://github.com/{REPO}/releases/tag/{tag}",
        "assets": assets,
    }


class TestReleaseSelector(unittest.TestCase):
    def test_latest_delta_channel_wins_without_fixed_asset_names(self):
        releases = [
            release(1, "2026-08-20T00:00:00Z", [asset("Anything.apk")], tag="delta-old"),
            release(
                2,
                "2026-08-25T00:00:00Z",
                [asset("Swift Backup.apk", sha=SHA_B), asset("ứng dụng tùy ý.apk")],
                tag="delta-current",
            ),
        ]
        selected = select_latest_stable_delta_release(releases)
        self.assertEqual(selected["version"], "current")
        self.assertEqual(selected["release_tag"], "delta-current")
        self.assertEqual([item["name"] for item in selected["assets"]], ["Swift Backup.apk", "ứng dụng tùy ý.apk"])
        self.assertEqual(selected["assets"][0]["sha256"], SHA_B)

    def test_non_delta_draft_and_prerelease_are_excluded(self):
        releases = [
            release(5, "2026-08-30T00:00:00Z", [asset("wrong.apk")], tag="worker-v9"),
            release(4, "2026-08-29T00:00:00Z", [asset("draft.apk")], tag="delta-draft", draft=True),
            release(3, "2026-08-28T00:00:00Z", [asset("pre.apk")], tag="delta-pre", prerelease=True),
            release(2, "2026-08-25T00:00:00Z", [asset("good.apk")], tag="delta-good"),
        ]
        selected = select_latest_stable_delta_release(releases)
        self.assertEqual(selected["release_tag"], "delta-good")

    def test_every_direct_apk_is_selected_and_zip_is_ignored_when_apk_exists(self):
        latest = release(
            10,
            "2026-08-25T00:00:00Z",
            [asset("bundle.zip"), asset("one.apk"), asset("two.apk", sha=SHA_B), asset("notes.txt")],
            tag="delta-latest",
        )
        selected = select_latest_stable_delta_release([latest])
        self.assertEqual([item["name"] for item in selected["assets"]], ["one.apk", "two.apk"])
        self.assertTrue(all(item["kind"] == "apk" for item in selected["assets"]))

    def test_all_zip_assets_are_used_only_when_direct_apk_is_absent(self):
        latest = release(
            10,
            "2026-08-25T00:00:00Z",
            [asset("first.zip"), asset("second.zip")],
            tag="delta-latest",
        )
        selected = select_latest_stable_delta_release([latest])
        self.assertEqual([item["name"] for item in selected["assets"]], ["first.zip", "second.zip"])

    def test_missing_digest_or_zero_size_fails_closed_for_any_selected_asset(self):
        missing_digest = asset("one.apk")
        missing_digest["digest"] = None
        for broken in (missing_digest, asset("two.apk", size=0)):
            latest = release(10, "2026-08-25T00:00:00Z", [asset("good.apk"), broken], tag="delta-latest")
            with self.assertRaises(ReleaseSelectionError):
                select_latest_stable_delta_release([latest])

    def test_untrusted_download_host_or_repo_fails_closed(self):
        bad_host = asset("one.apk", url="https://example.com/one.apk")
        bad_repo = asset("two.apk", url="https://github.com/other/repo/releases/download/x/two.apk")
        for broken in (bad_host, bad_repo):
            with self.assertRaises(ReleaseSelectionError):
                select_latest_stable_delta_release([
                    release(10, "2026-08-25T00:00:00Z", [broken], tag="delta-latest")
                ])

    def test_asset_path_components_are_rejected_but_spaces_and_unicode_are_allowed(self):
        selected = select_latest_stable_delta_release([
            release(10, "2026-08-25T00:00:00Z", [asset("Tên app tự do 01.apk")], tag="delta-latest")
        ])
        self.assertEqual(selected["assets"][0]["name"], "Tên app tự do 01.apk")

        bad = asset("folder/app.apk")
        with self.assertRaisesRegex(ReleaseSelectionError, "No stable"):
            select_latest_stable_delta_release([
                release(11, "2026-08-26T00:00:00Z", [bad], tag="delta-bad")
            ])


if __name__ == "__main__":
    unittest.main()

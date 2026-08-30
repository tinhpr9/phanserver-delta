import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from delta.release_selector import ReleaseSelectionError, select_latest_stable_delta_release

SHA_A = "a" * 64
SHA_B = "b" * 64
REPO = "tinhpr9/phanserver-delta"


def asset(name, *, size=123, sha=SHA_A, tag="Backup", url=None):
    return {
        "name": name,
        "size": size,
        "digest": f"sha256:{sha}",
        "browser_download_url": url
        or f"https://github.com/{REPO}/releases/download/{tag}/{name}",
    }


def release(release_id, published, assets, *, tag="Backup", name="", draft=False, prerelease=False):
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
    def test_latest_stable_installable_release_wins_without_tag_prefix(self):
        releases = [
            release(1, "2026-08-20T00:00:00Z", [asset("old.apk", tag="old")], tag="old"),
            release(
                2,
                "2026-08-28T00:00:00Z",
                [asset("Delta.apk"), asset("delta2.zip"), asset("delta3.zip")],
                tag="Backup",
            ),
        ]
        selected = select_latest_stable_delta_release(releases)
        self.assertEqual(selected["release_tag"], "Backup")
        self.assertEqual([item["name"] for item in selected["assets"]], ["Delta.apk", "delta2.zip", "delta3.zip"])
        self.assertEqual([item["kind"] for item in selected["assets"]], ["apk", "zip", "zip"])

    def test_mixed_apk_zip_release_selects_all_installable_assets(self):
        latest = release(
            10,
            "2026-08-28T00:00:00Z",
            [asset("one.apk"), asset("bundle.zip", sha=SHA_B), asset("notes.txt")],
        )
        selected = select_latest_stable_delta_release([latest])
        self.assertEqual([item["name"] for item in selected["assets"]], ["one.apk", "bundle.zip"])
        self.assertEqual(selected["assets"][1]["sha256"], SHA_B)

    def test_worker_draft_and_prerelease_are_excluded(self):
        releases = [
            release(5, "2026-08-30T00:00:00Z", [asset("worker.apk", tag="worker-v9")], tag="worker-v9", name="AOT Worker 9"),
            release(4, "2026-08-29T00:00:00Z", [asset("draft.apk", tag="draft")], tag="draft", draft=True),
            release(3, "2026-08-28T00:00:00Z", [asset("pre.apk", tag="pre")], tag="pre", prerelease=True),
            release(2, "2026-08-25T00:00:00Z", [asset("good.apk", tag="Backup")], tag="Backup"),
        ]
        selected = select_latest_stable_delta_release(releases)
        self.assertEqual(selected["release_tag"], "Backup")

    def test_missing_digest_or_zero_size_fails_closed_for_any_installable_asset(self):
        missing_digest = asset("one.apk")
        missing_digest["digest"] = None
        for broken in (missing_digest, asset("two.zip", size=0)):
            latest = release(10, "2026-08-28T00:00:00Z", [asset("good.apk"), broken])
            with self.assertRaises(ReleaseSelectionError):
                select_latest_stable_delta_release([latest])

    def test_untrusted_download_host_or_repo_fails_closed(self):
        bad_host = asset("one.apk", url="https://example.com/one.apk")
        bad_repo = asset("two.zip", url="https://github.com/other/repo/releases/download/x/two.zip")
        for broken in (bad_host, bad_repo):
            with self.assertRaises(ReleaseSelectionError):
                select_latest_stable_delta_release([release(10, "2026-08-28T00:00:00Z", [broken])])

    def test_asset_path_components_rejected_but_spaces_unicode_allowed(self):
        selected = select_latest_stable_delta_release([
            release(10, "2026-08-28T00:00:00Z", [asset("Tên app tự do 01.apk")])
        ])
        self.assertEqual(selected["assets"][0]["name"], "Tên app tự do 01.apk")

        bad = asset("folder/app.apk")
        with self.assertRaisesRegex(ReleaseSelectionError, "No stable"):
            select_latest_stable_delta_release([release(11, "2026-08-28T01:00:00Z", [bad])])


if __name__ == "__main__":
    unittest.main()

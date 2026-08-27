import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from delta.release_selector import ReleaseSelectionError, select_latest_stable_delta_release


SHA_A = "a" * 64
SHA_B = "b" * 64


def asset(name, *, size=123, sha=SHA_A, url=None):
    return {
        "name": name,
        "size": size,
        "digest": f"sha256:{sha}",
        "browser_download_url": url
        or f"https://github.com/tinhpr9/Aotscript/releases/download/source-tag/{name}",
    }


def release(release_id, published, assets, *, tag="delta-source", name="Delta", draft=False, prerelease=False):
    return {
        "id": release_id,
        "tag_name": tag,
        "name": name,
        "draft": draft,
        "prerelease": prerelease,
        "created_at": published,
        "published_at": published,
        "html_url": f"https://github.com/tinhpr9/Aotscript/releases/tag/{tag}",
        "assets": assets,
    }


class TestReleaseSelector(unittest.TestCase):
    def test_latest_stable_delta_release_wins_even_when_api_order_is_mixed(self):
        releases = [
            release(1, "2026-08-20T00:00:00Z", [asset("Delta-2.0.0.apk")], tag="old"),
            release(2, "2026-08-25T00:00:00Z", [asset("Delta-2.733.988_clone.apk", sha=SHA_B)], tag="new"),
        ]
        selected = select_latest_stable_delta_release(releases)
        self.assertEqual(selected["version"], "2.733.988")
        self.assertEqual(selected["asset_name"], "Delta-2.733.988_clone.apk")
        self.assertEqual(selected["asset_sha256"], SHA_B)
        self.assertEqual(selected["dedicated_tag"], "delta-v2.733.988")

    def test_worker_draft_and_prerelease_are_excluded(self):
        releases = [
            release(5, "2026-08-30T00:00:00Z", [asset("Delta-9.9.9.apk")], tag="worker-v9", name="AOT Worker 9"),
            release(4, "2026-08-29T00:00:00Z", [asset("Delta-8.8.8.apk")], tag="draft", draft=True),
            release(3, "2026-08-28T00:00:00Z", [asset("Delta-7.7.7.apk")], tag="pre", prerelease=True),
            release(2, "2026-08-25T00:00:00Z", [asset("Delta-2.7.3.apk")], tag="good"),
        ]
        selected = select_latest_stable_delta_release(releases)
        self.assertEqual(selected["source_release_tag"], "good")

    def test_direct_apk_is_preferred_over_zip_in_same_latest_release(self):
        latest = release(
            10,
            "2026-08-25T00:00:00Z",
            [asset("Delta-2.7.3.zip"), asset("Delta-2.7.3_clone.apk", sha=SHA_B)],
            tag="latest",
        )
        selected = select_latest_stable_delta_release([latest])
        self.assertEqual(selected["kind"], "apk")
        self.assertEqual(selected["asset_sha256"], SHA_B)

    def test_zip_is_used_only_when_direct_apk_is_absent(self):
        latest = release(10, "2026-08-25T00:00:00Z", [asset("Delta-2.7.3.zip")], tag="latest")
        selected = select_latest_stable_delta_release([latest])
        self.assertEqual(selected["kind"], "zip")

    def test_ambiguous_direct_assets_fail_closed(self):
        latest = release(
            10,
            "2026-08-25T00:00:00Z",
            [asset("Delta-2.7.3.apk"), asset("Delta-2.7.3_clone.apk")],
            tag="latest",
        )
        with self.assertRaisesRegex(ReleaseSelectionError, "ambiguous direct APK"):
            select_latest_stable_delta_release([latest])

    def test_missing_digest_or_zero_size_fails_closed(self):
        missing_digest = asset("Delta-2.7.3.apk")
        missing_digest["digest"] = None
        for broken in (missing_digest, asset("Delta-2.7.3.apk", size=0)):
            latest = release(10, "2026-08-25T00:00:00Z", [broken], tag="latest")
            with self.assertRaises(ReleaseSelectionError):
                select_latest_stable_delta_release([latest])

    def test_untrusted_download_host_fails_closed(self):
        bad = asset("Delta-2.7.3.apk", url="https://example.com/Delta-2.7.3.apk")
        with self.assertRaisesRegex(ReleaseSelectionError, "download URL"):
            select_latest_stable_delta_release([
                release(10, "2026-08-25T00:00:00Z", [bad], tag="latest")
            ])


if __name__ == "__main__":
    unittest.main()

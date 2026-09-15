import hashlib
import io
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))

from delta import delta_updater


class FakeResponse:
    def __init__(self, payload: bytes, final_url: str, headers=None):
        self._stream = io.BytesIO(payload)
        self._final_url = final_url
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self._stream.read(size)

    def geturl(self):
        return self._final_url


class TestHttpsRedirectGuard(unittest.TestCase):
    @mock.patch("delta.delta_updater.urllib.request.urlopen")
    def test_remote_manifest_rejects_https_to_http_redirect(self, mock_open):
        payload = b'{"channel":"delta","version":"x","assets":[]}'
        mock_open.return_value = FakeResponse(payload, "http://example.test/manifest.json")
        with self.assertRaisesRegex(delta_updater.DeltaUpdaterError, "redirected outside HTTPS"):
            delta_updater.load_manifest("https://example.test/manifest.json")

    @mock.patch("delta.delta_updater.urllib.request.urlopen")
    def test_asset_download_rejects_https_to_http_redirect_before_write(self, mock_open):
        payload = b"apk-bytes"
        mock_open.return_value = FakeResponse(
            payload,
            "http://example.test/app.apk",
            headers={"Content-Length": str(len(payload))},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = pathlib.Path(temp_dir) / "app.apk"
            with self.assertRaisesRegex(delta_updater.DeltaUpdaterError, "redirected outside HTTPS"):
                delta_updater.download_asset(
                    "https://example.test/app.apk",
                    destination,
                    expected_size=len(payload),
                    expected_sha256=hashlib.sha256(payload).hexdigest(),
                )
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name(destination.name + ".part").exists())


if __name__ == "__main__":
    unittest.main()

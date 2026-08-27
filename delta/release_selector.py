#!/usr/bin/env python3
"""Build an install manifest from the latest dedicated Delta GitHub Release."""

from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.parse
from typing import Any

TRUSTED_REPO = "tinhpr9/phanserver-delta"
DELTA_TAG_PREFIX = "delta-"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ReleaseSelectionError(RuntimeError):
    pass


def _release_time(release: dict[str, Any]) -> str:
    return str(release.get("published_at") or release.get("created_at") or "")


def _asset_kind(name: str) -> str:
    value = str(name or "")
    if not value.strip() or "\x00" in value or "/" in value or "\\" in value:
        return ""
    if value in {".", ".."} or len(value.encode("utf-8")) > 255:
        return ""
    lower = value.lower()
    if lower.endswith(".apk"):
        return "apk"
    if lower.endswith(".zip"):
        return "zip"
    return ""


def _candidate_assets(release: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    direct: list[dict[str, Any]] = []
    archives: list[dict[str, Any]] = []
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        kind = _asset_kind(str(asset.get("name") or ""))
        if kind == "apk":
            direct.append(asset)
        elif kind == "zip":
            archives.append(asset)
    return direct, archives


def _validate_asset(asset: dict[str, Any]) -> dict[str, Any]:
    name = str(asset.get("name") or "")
    kind = _asset_kind(name)
    if not kind:
        raise ReleaseSelectionError(f"Invalid Delta asset name/type: {name!r}")

    size = asset.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ReleaseSelectionError(f"Delta asset has invalid size: {name}")

    digest_raw = str(asset.get("digest") or "").strip().lower()
    if not digest_raw.startswith("sha256:"):
        raise ReleaseSelectionError(f"Delta asset has no GitHub SHA-256 digest: {name}")
    sha256 = digest_raw.split(":", 1)[1]
    if not _SHA256_RE.fullmatch(sha256):
        raise ReleaseSelectionError(f"Delta asset SHA-256 is invalid: {name}")

    url = str(asset.get("browser_download_url") or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise ReleaseSelectionError(f"Delta asset download URL is invalid: {name}")
    expected_prefix = f"/{TRUSTED_REPO}/releases/download/"
    if not parsed.path.startswith(expected_prefix):
        raise ReleaseSelectionError(f"Delta asset is outside the trusted repo: {name}")

    return {
        "name": name,
        "url": url,
        "sha256": sha256,
        "size": size,
        "kind": kind,
    }


def select_latest_stable_delta_release(releases: Any) -> dict[str, Any]:
    """Return a manifest for every installable asset in the newest `delta-*` release.

    There is intentionally no business-level fixed APK count and no fixed APK-name list.
    If a release has one or more direct APKs, every APK is selected and ZIPs are ignored.
    ZIP assets are used only when the release has no direct APKs.
    """
    if not isinstance(releases, list):
        raise ReleaseSelectionError("GitHub releases payload must be a list")

    stable: list[dict[str, Any]] = []
    for release in releases:
        if not isinstance(release, dict):
            continue
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = str(release.get("tag_name") or "").strip()
        if not tag.lower().startswith(DELTA_TAG_PREFIX):
            continue
        direct, archives = _candidate_assets(release)
        if direct or archives:
            stable.append(release)

    if not stable:
        raise ReleaseSelectionError("No stable delta-* release with APK/ZIP assets was found")

    stable.sort(key=_release_time, reverse=True)
    latest = stable[0]
    tag = str(latest.get("tag_name") or "").strip()
    direct, archives = _candidate_assets(latest)
    chosen = direct if direct else archives

    validated = [_validate_asset(asset) for asset in chosen]
    names = [asset["name"] for asset in validated]
    if len(names) != len(set(names)):
        raise ReleaseSelectionError("Delta release contains duplicate asset names")

    release_url = str(latest.get("html_url") or "").strip()
    release_id = latest.get("id")
    expected_release_prefix = f"https://github.com/{TRUSTED_REPO}/releases/"
    if not release_url.startswith(expected_release_prefix):
        raise ReleaseSelectionError("Delta release URL is outside the trusted repo")
    if not isinstance(release_id, int) or release_id <= 0:
        raise ReleaseSelectionError("Delta release ID is invalid")

    version = tag[len(DELTA_TAG_PREFIX):].strip() or tag
    return {
        "channel": "delta",
        "version": version,
        "release_id": release_id,
        "release_tag": tag,
        "release_url": release_url,
        "published_at": _release_time(latest),
        "assets": validated,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: release_selector.py releases.json", file=sys.stderr)
        return 2
    path = pathlib.Path(argv[1])
    releases = json.loads(path.read_text(encoding="utf-8"))
    manifest = select_latest_stable_delta_release(releases)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

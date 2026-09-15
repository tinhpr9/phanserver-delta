#!/usr/bin/env python3
"""Build an install manifest from the newest stable installable GitHub Release."""

from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.parse
from typing import Any

TRUSTED_REPO = "tinhpr9/phanserver-delta"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ReleaseSelectionError(RuntimeError):
    pass


def _release_time(release: dict[str, Any]) -> str:
    return str(release.get("published_at") or release.get("created_at") or "")


def _is_excluded_release(release: dict[str, Any]) -> bool:
    """Exclude known non-Delta runtime releases without requiring a naming convention."""
    tag = str(release.get("tag_name") or "").strip().lower()
    name = str(release.get("name") or "").strip().lower()
    return tag.startswith("worker") or name.startswith("worker") or name.startswith("aot worker")


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


def _candidate_assets(release: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        if _asset_kind(str(asset.get("name") or "")):
            candidates.append(asset)
    return candidates


def _validate_asset(asset: dict[str, Any]) -> dict[str, Any]:
    name = str(asset.get("name") or "")
    kind = _asset_kind(name)
    if not kind:
        raise ReleaseSelectionError(f"Invalid installable asset name/type: {name!r}")

    size = asset.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ReleaseSelectionError(f"Installable asset has invalid size: {name}")

    digest_raw = str(asset.get("digest") or "").strip().lower()
    if not digest_raw.startswith("sha256:"):
        raise ReleaseSelectionError(f"Installable asset has no GitHub SHA-256 digest: {name}")
    sha256 = digest_raw.split(":", 1)[1]
    if not _SHA256_RE.fullmatch(sha256):
        raise ReleaseSelectionError(f"Installable asset SHA-256 is invalid: {name}")

    url = str(asset.get("browser_download_url") or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise ReleaseSelectionError(f"Installable asset download URL is invalid: {name}")
    expected_prefix = f"/{TRUSTED_REPO}/releases/download/"
    if not parsed.path.startswith(expected_prefix):
        raise ReleaseSelectionError(f"Installable asset is outside the trusted repo: {name}")

    return {
        "name": name,
        "url": url,
        "sha256": sha256,
        "size": size,
        "kind": kind,
    }


def select_latest_stable_delta_release(releases: Any) -> dict[str, Any]:
    """Return every APK/ZIP from the newest stable installable release.

    There is no business-level fixed asset count, tag prefix, filename inventory,
    or APK-vs-ZIP preference. Draft/prerelease and known worker releases are not
    eligible. Every eligible APK/ZIP in the selected release is validated.
    """
    if not isinstance(releases, list):
        raise ReleaseSelectionError("GitHub releases payload must be a list")

    stable: list[dict[str, Any]] = []
    for release in releases:
        if not isinstance(release, dict):
            continue
        if release.get("draft") or release.get("prerelease") or _is_excluded_release(release):
            continue
        if _candidate_assets(release):
            stable.append(release)

    if not stable:
        raise ReleaseSelectionError("No stable release with APK/ZIP assets was found")

    stable.sort(key=_release_time, reverse=True)
    latest = stable[0]
    validated = [_validate_asset(asset) for asset in _candidate_assets(latest)]

    names = [asset["name"] for asset in validated]
    if len(names) != len(set(names)):
        raise ReleaseSelectionError("Release contains duplicate installable asset names")

    release_url = str(latest.get("html_url") or "").strip()
    release_id = latest.get("id")
    expected_release_prefix = f"https://github.com/{TRUSTED_REPO}/releases/"
    if not release_url.startswith(expected_release_prefix):
        raise ReleaseSelectionError("Release URL is outside the trusted repo")
    if not isinstance(release_id, int) or release_id <= 0:
        raise ReleaseSelectionError("Release ID is invalid")

    tag = str(latest.get("tag_name") or "").strip()
    version = tag or str(release_id)
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

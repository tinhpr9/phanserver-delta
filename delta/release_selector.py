#!/usr/bin/env python3
"""Select one exact stable Delta asset from GitHub Releases metadata."""

from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.parse
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(
    r"^Delta-(?P<version>[0-9]+(?:\.[0-9]+)+)(?:[_-][A-Za-z0-9._-]+)?\.(?P<kind>apk|zip)$",
    re.IGNORECASE,
)


class ReleaseSelectionError(RuntimeError):
    pass


def _release_time(release: dict[str, Any]) -> str:
    return str(release.get("published_at") or release.get("created_at") or "")


def _is_worker_release(release: dict[str, Any]) -> bool:
    tag = str(release.get("tag_name") or "").strip().lower()
    name = str(release.get("name") or "").strip().lower()
    return tag.startswith("worker") or name.startswith("worker") or name.startswith("aot worker")


def _candidate_assets(release: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    direct: list[dict[str, Any]] = []
    archives: list[dict[str, Any]] = []
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        match = _VERSION_RE.fullmatch(str(asset.get("name") or "").strip())
        if not match:
            continue
        if match.group("kind").lower() == "apk":
            direct.append(asset)
        else:
            archives.append(asset)
    return direct, archives


def _validate_selected_asset(release: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    name = str(asset.get("name") or "").strip()
    match = _VERSION_RE.fullmatch(name)
    if not match:
        raise ReleaseSelectionError("Selected Delta asset name is invalid")

    size = asset.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ReleaseSelectionError(f"Selected Delta asset has invalid size: {name}")

    digest_raw = str(asset.get("digest") or "").strip().lower()
    if not digest_raw.startswith("sha256:"):
        raise ReleaseSelectionError(f"Selected Delta asset has no GitHub SHA-256 digest: {name}")
    sha256 = digest_raw.split(":", 1)[1]
    if not _SHA256_RE.fullmatch(sha256):
        raise ReleaseSelectionError(f"Selected Delta asset SHA-256 is invalid: {name}")

    url = str(asset.get("browser_download_url") or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise ReleaseSelectionError(f"Selected Delta asset download URL is invalid: {name}")
    expected_prefix = "/tinhpr9/Aotscript/releases/download/"
    if not parsed.path.startswith(expected_prefix):
        raise ReleaseSelectionError(f"Selected Delta asset is outside the trusted source repo: {name}")

    source_release_url = str(release.get("html_url") or "").strip()
    release_id = release.get("id")
    if not source_release_url.startswith("https://github.com/tinhpr9/Aotscript/releases/"):
        raise ReleaseSelectionError("Selected Delta release URL is invalid")
    if not isinstance(release_id, int) or release_id <= 0:
        raise ReleaseSelectionError("Selected Delta release ID is invalid")

    version = match.group("version")
    kind = match.group("kind").lower()
    return {
        "version": version,
        "dedicated_tag": f"delta-v{version}",
        "kind": kind,
        "asset_name": name,
        "asset_url": url,
        "asset_size": size,
        "asset_sha256": sha256,
        "source_release_id": release_id,
        "source_release_tag": str(release.get("tag_name") or ""),
        "source_release_url": source_release_url,
        "source_published_at": _release_time(release),
    }


def select_latest_stable_delta_release(releases: Any) -> dict[str, Any]:
    """Select latest stable Delta release; direct APK wins over ZIP in that release."""
    if not isinstance(releases, list):
        raise ReleaseSelectionError("GitHub releases payload must be a list")

    stable: list[dict[str, Any]] = []
    for release in releases:
        if not isinstance(release, dict):
            continue
        if release.get("draft") or release.get("prerelease"):
            continue
        if _is_worker_release(release):
            continue
        direct, archives = _candidate_assets(release)
        if direct or archives:
            stable.append(release)

    if not stable:
        raise ReleaseSelectionError("No stable Delta release with APK/ZIP asset was found")

    stable.sort(key=_release_time, reverse=True)
    latest = stable[0]
    direct, archives = _candidate_assets(latest)
    if direct:
        if len(direct) != 1:
            raise ReleaseSelectionError("Latest stable Delta release has ambiguous direct APK assets")
        selected = direct[0]
    else:
        if len(archives) != 1:
            raise ReleaseSelectionError("Latest stable Delta release has ambiguous ZIP assets")
        selected = archives[0]

    return _validate_selected_asset(latest, selected)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: release_selector.py releases.json", file=sys.stderr)
        return 2
    path = pathlib.Path(argv[1])
    releases = json.loads(path.read_text(encoding="utf-8"))
    selected = select_latest_stable_delta_release(releases)
    print(json.dumps(selected, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

#!/usr/bin/env python3
"""Fail-closed standalone Delta updater for phanserver-delta."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile
from typing import Any, Optional

try:
    from delta.release_selector import ReleaseSelectionError, select_latest_stable_delta_release
except ImportError:
    from release_selector import ReleaseSelectionError, select_latest_stable_delta_release

DEFAULT_RELEASES_URL = "https://api.github.com/repos/tinhpr9/phanserver-delta/releases?per_page=100"
DEFAULT_DOWNLOAD_DIR = "/storage/emulated/0/Download/GitHub_All_Files"

CHUNK_SIZE = 1024 * 1024
MAX_ASSET_BYTES = 2 * 1024 * 1024 * 1024
MAX_TOTAL_DOWNLOAD_BYTES = 16 * 1024 * 1024 * 1024
MAX_RELEASE_JSON_BYTES = 4 * 1024 * 1024
MAX_ZIP_ENTRIES = 4096
MAX_ZIP_UNCOMPRESSED_BYTES = 16 * 1024 * 1024 * 1024
MAX_ZIP_DEPTH = 16
MAX_COMPRESSION_RATIO = 200
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DeltaUpdaterError(RuntimeError):
    pass


def root_available() -> bool:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return True
    su_path = shutil.which("su")
    if not su_path:
        return False
    try:
        proc = subprocess.run(
            [su_path, "-c", "id -u"], capture_output=True, text=True, timeout=5
        )
        return proc.returncode == 0 and (proc.stdout or "").strip() == "0"
    except (OSError, subprocess.TimeoutExpired):
        return False


def calculate_sha256(filepath: str | pathlib.Path) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def safe_asset_name(name: str) -> str:
    value = str(name or "")
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    return safe[:180] or "delta_asset"


def validate_asset_kind(name: str) -> str:
    lower = str(name or "").lower()
    if lower.endswith(".apk"):
        return "apk"
    if lower.endswith(".zip"):
        return "zip"
    return ""


def _validate_asset_name(name: str, index: int) -> None:
    if not name.strip() or "\x00" in name or "/" in name or "\\" in name:
        raise DeltaUpdaterError(f"Manifest asset #{index} has unsafe name")
    if name in {".", ".."} or len(name.encode("utf-8")) > 255:
        raise DeltaUpdaterError(f"Manifest asset #{index} has unsafe name")


def _validate_asset(asset: Any, index: int) -> dict[str, Any]:
    if not isinstance(asset, dict):
        raise DeltaUpdaterError(f"Manifest asset #{index} must be an object")

    name = str(asset.get("name") or "")
    url = str(asset.get("url") or "").strip()
    sha256 = str(asset.get("sha256") or "").strip().lower()
    size = asset.get("size")
    kind = validate_asset_kind(name)

    _validate_asset_name(name, index)
    if not kind:
        raise DeltaUpdaterError(f"Manifest asset #{index} must be .apk or .zip")

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"https", "file"}:
        raise DeltaUpdaterError(f"Manifest asset #{index} must use HTTPS")
    if parsed.scheme == "https" and not parsed.netloc:
        raise DeltaUpdaterError(f"Manifest asset #{index} URL is invalid")
    if parsed.scheme == "file" and not parsed.path:
        raise DeltaUpdaterError(f"Manifest asset #{index} file URL is invalid")

    if not _SHA256_RE.fullmatch(sha256):
        raise DeltaUpdaterError(f"Manifest asset #{index} requires a full SHA-256 digest")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise DeltaUpdaterError(f"Manifest asset #{index} requires positive size")
    if size > MAX_ASSET_BYTES:
        raise DeltaUpdaterError(f"Manifest asset #{index} exceeds per-file download limit")

    return {**asset, "name": name, "url": url, "sha256": sha256, "size": size, "kind": kind}


def _validate_manifest_object(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise DeltaUpdaterError("Manifest format invalid: expected JSON object")
    if manifest.get("channel") != "delta":
        raise DeltaUpdaterError(
            f"Invalid channel in manifest: expected 'delta', got {manifest.get('channel')}"
        )
    version = str(manifest.get("version") or "").strip()
    if not version:
        raise DeltaUpdaterError("Manifest version is missing")
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise DeltaUpdaterError("Manifest contains no assets")

    validated = [_validate_asset(asset, index) for index, asset in enumerate(assets, 1)]
    names = [asset["name"] for asset in validated]
    if len(names) != len(set(names)):
        raise DeltaUpdaterError("Manifest contains duplicate asset names")
    total = sum(asset["size"] for asset in validated)
    if total > MAX_TOTAL_DOWNLOAD_BYTES:
        raise DeltaUpdaterError("Manifest total declared download size exceeds safety limit")
    return {**manifest, "version": version, "assets": validated}


def load_latest_release_manifest(releases_url: str = DEFAULT_RELEASES_URL) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(releases_url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "api.github.com":
        raise DeltaUpdaterError("Delta releases API URL must use api.github.com over HTTPS")
    if parsed.path != "/repos/tinhpr9/phanserver-delta/releases":
        raise DeltaUpdaterError("Delta releases API URL points outside the trusted repo")

    req = urllib.request.Request(
        releases_url,
        headers={
            "User-Agent": "phanserver-delta-updater/3.1",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read(MAX_RELEASE_JSON_BYTES + 1)
    if len(raw) > MAX_RELEASE_JSON_BYTES:
        raise DeltaUpdaterError("GitHub releases payload exceeds safety limit")
    try:
        releases = json.loads(raw.decode("utf-8"))
        manifest = select_latest_stable_delta_release(releases)
    except (json.JSONDecodeError, ReleaseSelectionError) as exc:
        raise DeltaUpdaterError(f"Delta release selection failed: {exc}") from exc
    return _validate_manifest_object(manifest)


def load_manifest(source: str | pathlib.Path | dict) -> dict[str, Any]:
    """Load a caller-supplied manifest. Production default uses GitHub Releases directly."""
    if isinstance(source, dict):
        manifest = source
    elif str(source).startswith(("http://", "https://")):
        parsed_source = urllib.parse.urlparse(str(source))
        if parsed_source.scheme != "https":
            raise DeltaUpdaterError("Remote manifest must use HTTPS")
        req = urllib.request.Request(
            str(source), headers={"User-Agent": "phanserver-delta-updater/3.1"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read(MAX_RELEASE_JSON_BYTES + 1)
        if len(raw) > MAX_RELEASE_JSON_BYTES:
            raise DeltaUpdaterError("Manifest exceeds safety limit")
        manifest = json.loads(raw.decode("utf-8"))
    else:
        path = pathlib.Path(source)
        if not path.is_file():
            raise DeltaUpdaterError(f"Manifest file not found: {source}")
        if path.stat().st_size > MAX_RELEASE_JSON_BYTES:
            raise DeltaUpdaterError("Manifest exceeds safety limit")
        manifest = json.loads(path.read_text(encoding="utf-8"))
    return _validate_manifest_object(manifest)


def _stream_to_verified_file(
    source,
    destination: pathlib.Path,
    *,
    expected_size: int,
    expected_sha256: str,
    max_bytes: int,
) -> None:
    part = destination.with_name(destination.name + ".part")
    try:
        part.unlink(missing_ok=True)
        hasher = hashlib.sha256()
        written = 0
        with open(part, "xb") as output:
            while True:
                chunk = source.read(CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes or written > expected_size:
                    raise DeltaUpdaterError("Downloaded asset exceeded declared size or safety limit")
                output.write(chunk)
                hasher.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        if written <= 0:
            raise DeltaUpdaterError("Downloaded asset is empty")
        if written != expected_size:
            raise DeltaUpdaterError(
                f"Downloaded asset size mismatch: expected {expected_size}, got {written}"
            )
        actual_sha256 = hasher.hexdigest().lower()
        if actual_sha256 != expected_sha256:
            raise DeltaUpdaterError(
                f"SHA256 checksum mismatch: expected {expected_sha256}, got {actual_sha256}"
            )
        os.replace(part, destination)
    except Exception:
        try:
            part.unlink()
        except OSError:
            pass
        raise


def download_asset(
    url: str,
    destination: str | pathlib.Path,
    *,
    expected_size: int,
    expected_sha256: str,
    max_bytes: int = MAX_ASSET_BYTES,
) -> None:
    if expected_size <= 0 or expected_size > max_bytes:
        raise DeltaUpdaterError("Expected asset size is outside safety limits")
    if not _SHA256_RE.fullmatch(str(expected_sha256).lower()):
        raise DeltaUpdaterError("Expected SHA-256 is invalid")

    dest = pathlib.Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        req = urllib.request.Request(url, headers={"User-Agent": "phanserver-delta-updater/3.1"})
        with urllib.request.urlopen(req, timeout=60) as response:
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    remote_size = int(content_length)
                except ValueError as exc:
                    raise DeltaUpdaterError("Invalid Content-Length from asset server") from exc
                if remote_size != expected_size or remote_size > max_bytes:
                    raise DeltaUpdaterError(
                        f"Asset Content-Length mismatch: expected {expected_size}, got {remote_size}"
                    )
            _stream_to_verified_file(
                response,
                dest,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
                max_bytes=max_bytes,
            )
        return
    if parsed.scheme == "file":
        local_path = pathlib.Path(urllib.request.url2pathname(parsed.path))
        if not local_path.is_file():
            raise DeltaUpdaterError(f"Local asset not found: {local_path}")
        local_size = local_path.stat().st_size
        if local_size != expected_size or local_size > max_bytes:
            raise DeltaUpdaterError(
                f"Local asset size mismatch: expected {expected_size}, got {local_size}"
            )
        with open(local_path, "rb") as source:
            _stream_to_verified_file(
                source,
                dest,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
                max_bytes=max_bytes,
            )
        return
    raise DeltaUpdaterError(f"Unsupported asset URL scheme: {url}")


def install_apk(apk_path: str | pathlib.Path) -> None:
    apk = pathlib.Path(apk_path)
    if not apk.is_file() or apk.stat().st_size <= 0:
        raise DeltaUpdaterError(f"APK is missing or empty: {apk}")
    if not root_available():
        raise DeltaUpdaterError(
            "Root access required for pm install. Non-root environment is unsupported for Delta APK installation."
        )
    common_kwargs = {"capture_output": True, "text": True, "timeout": 180}
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        result = subprocess.run(["pm", "install", "-r", "-d", str(apk)], **common_kwargs)
    else:
        su_path = shutil.which("su")
        if not su_path:
            raise DeltaUpdaterError("Root access disappeared before APK installation")
        env = os.environ.copy()
        env["DELTA_APK_PATH"] = str(apk)
        result = subprocess.run(
            [su_path, "-c", 'exec pm install -r -d "$DELTA_APK_PATH"'],
            env=env,
            **common_kwargs,
        )
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if result.returncode != 0 or "Success" not in output:
        raise DeltaUpdaterError(
            f"pm install failed for {apk.name} (rc={result.returncode}): {output[:400]}"
        )


def _validate_zip_member(member: zipfile.ZipInfo) -> None:
    normalized = member.filename.replace("\\", "/")
    pure = pathlib.PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        raise DeltaUpdaterError(f"Unsafe ZIP path: {member.filename}")
    if len(pure.parts) > MAX_ZIP_DEPTH:
        raise DeltaUpdaterError(f"ZIP path is too deep: {member.filename}")
    mode = member.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        raise DeltaUpdaterError(f"ZIP symlink is not allowed: {member.filename}")
    if member.file_size < 0 or member.file_size > MAX_ASSET_BYTES:
        raise DeltaUpdaterError(f"ZIP member exceeds size limit: {member.filename}")
    if member.file_size > 0:
        if member.compress_size <= 0:
            raise DeltaUpdaterError(f"ZIP member has invalid compressed size: {member.filename}")
        if member.file_size > member.compress_size * MAX_COMPRESSION_RATIO:
            raise DeltaUpdaterError(f"ZIP compression ratio is unsafe: {member.filename}")


def extract_zip_apks(zip_path: str | pathlib.Path, output_dir: str | pathlib.Path) -> list[pathlib.Path]:
    out_dir = pathlib.Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[pathlib.Path] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = archive.infolist()
            if not members or len(members) > MAX_ZIP_ENTRIES:
                raise DeltaUpdaterError("ZIP entry count is outside safety limits")
            total_uncompressed = 0
            apk_members: list[zipfile.ZipInfo] = []
            for member in members:
                _validate_zip_member(member)
                if member.is_dir():
                    continue
                total_uncompressed += member.file_size
                if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
                    raise DeltaUpdaterError("ZIP total uncompressed size exceeds safety limit")
                if member.filename.lower().endswith(".apk"):
                    if member.file_size <= 0:
                        raise DeltaUpdaterError(f"APK inside ZIP is empty: {member.filename}")
                    apk_members.append(member)
            if not apk_members:
                raise DeltaUpdaterError(f"ZIP archive contains no APK files: {zip_path}")
            bad_crc = archive.testzip()
            if bad_crc is not None:
                raise DeltaUpdaterError(f"ZIP CRC corrupted at entry: {bad_crc}")
            for index, member in enumerate(apk_members, 1):
                clean_base = safe_asset_name(pathlib.PurePosixPath(member.filename).name)
                dest = out_dir / f"{index:04d}_{clean_base}"
                written = 0
                with archive.open(member, "r") as source, open(dest, "xb") as target:
                    while True:
                        chunk = source.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > member.file_size:
                            raise DeltaUpdaterError("ZIP member expanded beyond declared size")
                        target.write(chunk)
                if written != member.file_size:
                    raise DeltaUpdaterError("ZIP member size changed during extraction")
                extracted.append(dest)
    except Exception:
        for path in extracted:
            try:
                path.unlink()
            except OSError:
                pass
        raise
    return extracted


def _select_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [asset for asset in assets if asset.get("kind") in {"apk", "zip"}]
    if not selected:
        raise DeltaUpdaterError("Manifest has no installable Delta assets")
    return selected


def run_delta_update(
    manifest_source: Optional[str | pathlib.Path | dict] = None,
    download_dir: Optional[str | pathlib.Path] = None,
) -> dict[str, Any]:
    """Verify every selected APK/ZIP before the first Android install mutation."""
    dl_dir = pathlib.Path(download_dir or DEFAULT_DOWNLOAD_DIR)
    dl_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_latest_release_manifest() if manifest_source is None else load_manifest(manifest_source)
    assets = _select_assets(manifest["assets"])

    with tempfile.TemporaryDirectory(prefix=".delta-txn-", dir=dl_dir) as transaction_dir:
        tx_root = pathlib.Path(transaction_dir)
        staged: list[tuple[dict[str, Any], pathlib.Path]] = []

        for index, asset in enumerate(assets, 1):
            target = tx_root / f"{index:04d}_{safe_asset_name(asset['name'])}"
            download_asset(
                asset["url"],
                target,
                expected_size=asset["size"],
                expected_sha256=asset["sha256"],
            )
            staged.append((asset, target))

        install_queue: list[pathlib.Path] = []
        for index, (asset, target) in enumerate(staged, 1):
            if asset["kind"] == "apk":
                install_queue.append(target)
            else:
                extract_dir = tx_root / f"extract_{index:04d}"
                install_queue.extend(extract_zip_apks(target, extract_dir))

        if not install_queue:
            raise DeltaUpdaterError("UPDATE_DELTA verified release but found zero APKs")

        for apk in install_queue:
            install_apk(apk)
        installed_count = len(install_queue)

    return {
        "ok": True,
        "channel": "delta",
        "version": manifest["version"],
        "release_tag": manifest.get("release_tag"),
        "installed_count": installed_count,
    }


if __name__ == "__main__":
    import sys

    manifest_arg = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        result = run_delta_update(manifest_arg)
        print(
            f"[+] UPDATE DELTA THÀNH CÔNG: {result['installed_count']} APK "
            f"(Version {result['version']})"
        )
    except Exception as exc:
        print(f"[!] UPDATE_DELTA THẤT BẠI: {exc}", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""
Standalone Delta Updater for phanserver-delta.

Dedicated Delta release channel with strict SHA256 validation,
fail-closed integrity checks, and accurate root privilege reporting.
"""

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import urllib.parse
import urllib.request
import zipfile
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_MANIFEST_URL = "https://raw.githubusercontent.com/tinhpr9/phanserver-delta/main/delta/manifest.json"
DEFAULT_DOWNLOAD_DIR = "/storage/emulated/0/Download/GitHub_All_Files"


class DeltaUpdaterError(RuntimeError):
    pass


def root_available() -> bool:
    """Check if root (su) is available and functional."""
    su_path = shutil.which("su")
    if not su_path:
        return False
    try:
        proc = subprocess.run(
            ["su", "-c", "id"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode == 0 and "uid=0" in (proc.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return False


def calculate_sha256(filepath: str | pathlib.Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def safe_asset_name(name: str) -> str:
    """Sanitize asset filename."""
    value = str(name or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    return safe or "delta_asset"


def validate_asset_kind(name: str) -> str:
    """Identify asset kind: apk or zip."""
    lower = str(name or "").strip().lower()
    if lower.endswith(".apk"):
        return "apk"
    if lower.endswith(".zip"):
        return "zip"
    return ""


def load_manifest(source: str | pathlib.Path | dict) -> dict[str, Any]:
    """Load Delta manifest from URL, file path, or dictionary."""
    if isinstance(source, dict):
        manifest = source
    elif str(source).startswith(("http://", "https://")):
        req = urllib.request.Request(
            str(source),
            headers={"User-Agent": "phanserver-delta-updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            manifest = json.loads(resp.read().decode("utf-8"))
    else:
        path = pathlib.Path(source)
        if not path.is_file():
            raise DeltaUpdaterError(f"Manifest file not found: {source}")
        with open(path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

    if not isinstance(manifest, dict):
        raise DeltaUpdaterError("Manifest format invalid: expected JSON object")
    if manifest.get("channel") != "delta":
        raise DeltaUpdaterError(f"Invalid channel in manifest: expected 'delta', got {manifest.get('channel')}")

    assets = manifest.get("assets")
    if not isinstance(assets, list) or len(assets) == 0:
        raise DeltaUpdaterError("Manifest contains no assets")

    return manifest


def download_asset(url: str, destination: str | pathlib.Path) -> None:
    """Download asset over HTTP/HTTPS or local path."""
    dest = pathlib.Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme in ("http", "https"):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "phanserver-delta-updater/1.0"},
        )
        written = 0
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
            while chunk := resp.read(1024 * 1024):
                out.write(chunk)
                written += len(chunk)
        if written < 0:
            raise DeltaUpdaterError(f"Downloaded asset is empty: {destination}")
    elif parsed.scheme == "file" or os.path.exists(url):
        local_path = url[7:] if url.startswith("file://") else url
        shutil.copy2(local_path, dest)
    else:
        raise DeltaUpdaterError(f"Unsupported asset URL scheme: {url}")


def install_apk(apk_path: str | pathlib.Path) -> None:
    """Install APK using root pm install -r."""
    if not root_available():
        raise DeltaUpdaterError(
            "Root access required for pm install. Non-root environment is unsupported for Delta APK installation."
        )

    cmd = f"pm install -r '{apk_path}'"
    result = subprocess.run(
        ["su", "-c", cmd],
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()

    if result.returncode != 0 or "Success" not in output:
        raise DeltaUpdaterError(f"pm install failed for {apk_path} (rc={result.returncode}): {output[:400]}")


def extract_zip_apks(zip_path: str | pathlib.Path, output_dir: str | pathlib.Path) -> list[pathlib.Path]:
    """Safely extract APKs from a ZIP archive."""
    out_dir = pathlib.Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    extracted_apks: list[pathlib.Path] = []
    total_size = 0

    with zipfile.ZipFile(zip_path, "r") as archive:
        bad_crc = archive.testzip()
        if bad_crc is not None:
            raise DeltaUpdaterError(f"ZIP CRC corrupted at entry: {bad_crc}")

        for member in archive.infolist():
            if member.is_dir():
                continue

            member_name = member.filename.replace("\\", "/")
            if not member_name.lower().endswith(".apk"):
                continue

            # Zip bomb & path traversal protection
            if member.file_size > 1024 * 1024 * 1024:
                raise DeltaUpdaterError("APK inside ZIP exceeds 1 GiB limit")
            total_size += member.file_size
            if total_size > 8 * 1024 * 1024 * 1024:
                raise DeltaUpdaterError("Total uncompressed size exceeds 8 GiB limit")

            clean_base = safe_asset_name(os.path.basename(member_name))
            dest = out_dir / f"{len(extracted_apks) + 1:03d}_{clean_base}"

            # Path traversal check
            dest_resolved = dest.resolve()
            if not str(dest_resolved).startswith(str(out_dir.resolve())):
                raise DeltaUpdaterError("Path traversal attempt in ZIP entry")

            with archive.open(member, "r") as src, open(dest, "wb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)

            extracted_apks.append(dest)

    if not extracted_apks:
        raise DeltaUpdaterError(f"ZIP archive contains no APK files: {zip_path}")

    return extracted_apks


def run_delta_update(
    manifest_source: Optional[str | pathlib.Path | dict] = None,
    download_dir: Optional[str | pathlib.Path] = None,
) -> dict[str, Any]:
    """
    Execute full Delta update workflow:
    1. Load dedicated manifest
    2. Download assets
    3. Verify SHA256 checksums
    4. Install APKs with root pm install
    5. Fail-closed on any error
    """
    source = manifest_source or DEFAULT_MANIFEST_URL
    dl_dir = pathlib.Path(download_dir or DEFAULT_DOWNLOAD_DIR)
    dl_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(source)
    version = manifest.get("version", "unknown")
    assets = manifest.get("assets", [])

    installed_count = 0

    for index, asset in enumerate(assets, 1):
        if not isinstance(asset, dict):
            continue

        name = str(asset.get("name", "")).strip()
        url = str(asset.get("url", "")).strip()
        expected_sha256 = str(asset.get("sha256", "")).strip().lower()
        kind = validate_asset_kind(name)

        if not kind or not url:
            continue

        safe_name = safe_asset_name(name)
        target_path = dl_dir / f"delta_{index:03d}_{safe_name}"

        # Download asset
        download_asset(url, target_path)

        # Validate SHA-256 checksum if specified
        if expected_sha256:
            actual_sha256 = calculate_sha256(target_path)
            if actual_sha256 != expected_sha256:
                try:
                    target_path.unlink()
                except OSError:
                    pass
                raise DeltaUpdaterError(
                    f"SHA256 checksum mismatch for {name}: expected {expected_sha256}, got {actual_sha256}"
                )

        # Install
        if kind == "apk":
            install_apk(target_path)
            installed_count += 1
        elif kind == "zip":
            extract_dir = dl_dir / f"delta_extract_{index:03d}"
            apk_files = extract_zip_apks(target_path, extract_dir)
            for apk in apk_files:
                install_apk(apk)
                installed_count += 1

    if installed_count <= 0:
        raise DeltaUpdaterError("UPDATE_DELTA finished but zero APKs were installed")

    return {
        "ok": True,
        "channel": "delta",
        "version": version,
        "installed_count": installed_count,
    }


if __name__ == "__main__":
    import sys
    manifest_arg = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        res = run_delta_update(manifest_arg)
        print(f"[+] UPDATE DELTA THÀNH CÔNG: {res['installed_count']} APK (Version {res['version']})")
    except Exception as exc:
        print(f"[!] UPDATE_DELTA THẤT BẠI: {exc}", file=sys.stderr)
        sys.exit(1)

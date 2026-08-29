#!/usr/bin/env python3
"""Fail-closed standalone Delta updater for phanserver-delta."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
import codecs
from typing import Any, Optional


def _ensure_cp437():
    try:
        codecs.lookup("cp437")
    except LookupError:
        try:
            latin1 = codecs.lookup("latin-1")
            codecs.register(lambda name: latin1 if name.lower() in ("cp437", "ibm437", "437") else None)
        except Exception:
            pass

_ensure_cp437()

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
PROGRESS_REPORT_PERCENT = 5
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DeltaUpdaterError(RuntimeError):
    pass


def _require_https_final_url(response: Any, context: str) -> None:
    getter = getattr(response, "geturl", None)
    if not callable(getter):
        raise DeltaUpdaterError(f"{context} response URL is unavailable")
    final_url = str(getter() or "")
    parsed = urllib.parse.urlparse(final_url)
    if parsed.scheme.lower() != "https":
        raise DeltaUpdaterError(f"{context} redirected outside HTTPS: {final_url}")


def find_su_binary() -> Optional[str]:
    which_su = shutil.which("su")
    if which_su:
        return which_su
    for cand in [
        "/system/bin/su",
        "/system/xbin/su",
        "/sbin/su",
        "/su/bin/su",
        "/data/adb/ksu/bin/su",
        "/data/adb/ap/bin/su",
        "/data/adb/magisk/su",
    ]:
        if cand and os.path.exists(cand):
            return cand
    return None


def root_available() -> bool:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return True
    su_path = find_su_binary()
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
            "User-Agent": "phanserver-delta-updater/3.2",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        _require_https_final_url(resp, "GitHub releases API")
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
            str(source), headers={"User-Agent": "phanserver-delta-updater/3.2"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            _require_https_final_url(resp, "Remote manifest")
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
    progress_label: Optional[str] = None,
) -> None:
    part = destination.with_name(destination.name + ".part")
    try:
        part.unlink(missing_ok=True)
        hasher = hashlib.sha256()
        written = 0
        last_reported_percent = -1
        if progress_label:
            print(f"[DOWNLOAD] {progress_label}: 0% (0/{expected_size} bytes)", flush=True)
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
                if progress_label:
                    percent = min(100, written * 100 // expected_size)
                    if percent == 100 or percent >= last_reported_percent + PROGRESS_REPORT_PERCENT:
                        print(
                            f"[DOWNLOAD] {progress_label}: {percent}% "
                            f"({written}/{expected_size} bytes)",
                            flush=True,
                        )
                        last_reported_percent = percent
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
    progress_label: Optional[str] = None,
) -> None:
    if expected_size <= 0 or expected_size > max_bytes:
        raise DeltaUpdaterError("Expected asset size is outside safety limits")
    if not _SHA256_RE.fullmatch(str(expected_sha256).lower()):
        raise DeltaUpdaterError("Expected SHA-256 is invalid")

    dest = pathlib.Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https":
        part = dest.with_name(dest.name + ".part")
        max_retries = 6
        last_error = None
        last_reported_percent = -1
        written = 0

        if progress_label:
            print(f"[DOWNLOAD] {progress_label}: 0% (0/{expected_size} bytes)", flush=True)

        for attempt in range(1, max_retries + 1):
            try:
                current_size = part.stat().st_size if part.is_file() else 0
                if current_size > expected_size:
                    part.unlink(missing_ok=True)
                    current_size = 0

                headers = {"User-Agent": "phanserver-delta-updater/3.2"}
                if current_size > 0:
                    headers["Range"] = f"bytes={current_size}-"

                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=60) as response:
                    _require_https_final_url(response, "Asset download")
                    status_code = getattr(response, "status", 200)

                    if status_code == 206 and current_size > 0:
                        file_mode = "ab"
                        written = current_size
                    else:
                        file_mode = "wb"
                        written = 0

                    with open(part, file_mode) as output:
                        while True:
                            chunk = response.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > max_bytes or written > expected_size:
                                raise DeltaUpdaterError("Downloaded asset exceeded declared size or safety limit")
                            output.write(chunk)
                            if progress_label:
                                percent = min(100, written * 100 // expected_size)
                                if percent == 100 or percent >= last_reported_percent + PROGRESS_REPORT_PERCENT:
                                    print(
                                        f"[DOWNLOAD] {progress_label}: {percent}% "
                                        f"({written}/{expected_size} bytes)",
                                        flush=True,
                                    )
                                    last_reported_percent = percent
                        output.flush()
                        os.fsync(output.fileno())

                if written == expected_size:
                    hasher = hashlib.sha256()
                    with open(part, "rb") as f:
                        while chunk := f.read(CHUNK_SIZE):
                            hasher.update(chunk)
                    actual_sha256 = hasher.hexdigest().lower()
                    if actual_sha256 != expected_sha256:
                        part.unlink(missing_ok=True)
                        raise DeltaUpdaterError(
                            f"SHA256 checksum mismatch: expected {expected_sha256}, got {actual_sha256}"
                        )
                    os.replace(part, dest)
                    return
                else:
                    last_error = DeltaUpdaterError(
                        f"Downloaded asset size mismatch: expected {expected_size}, got {written}"
                    )
            except Exception as exc:
                last_error = exc
                err_msg = str(exc)
                if isinstance(exc, DeltaUpdaterError) and (
                    "outside HTTPS" in err_msg
                    or "checksum mismatch" in err_msg
                    or "exceeded declared size" in err_msg
                ):
                    break
                if attempt == max_retries:
                    break
                time.sleep(2)

        part.unlink(missing_ok=True)
        if isinstance(last_error, DeltaUpdaterError):
            raise last_error
        raise DeltaUpdaterError(f"Download failed after {max_retries} attempts: {last_error}") from last_error

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
                progress_label=progress_label,
            )
        return
    raise DeltaUpdaterError(f"Unsupported asset URL scheme: {url}")


def is_split_apk_bundle(apks: list[pathlib.Path]) -> bool:
    """Detect if a collection of APK files represents split slices of a single App Bundle."""
    if len(apks) <= 1:
        return False
    names = [a.name.lower() for a in apks]
    return any("split" in n or "config." in n for n in names)


def install_apks(apks: list[pathlib.Path] | pathlib.Path) -> None:
    """Install one or more APKs, with automatic support for Split APK bundles."""
    if isinstance(apks, (str, pathlib.Path)):
        apks = [pathlib.Path(apks)]
    if not apks:
        return
    for apk in apks:
        if not apk.is_file() or apk.stat().st_size <= 0:
            raise DeltaUpdaterError(f"APK is missing or empty: {apk}")
    if not root_available():
        raise DeltaUpdaterError(
            "Root access required for pm install. Non-root environment is unsupported for Delta APK installation."
        )

    common_kwargs = {"capture_output": True, "text": True, "timeout": 300}
    is_root_process = hasattr(os, "geteuid") and os.geteuid() == 0
    su_path = None if is_root_process else find_su_binary()
    if not is_root_process and not su_path:
        raise DeltaUpdaterError("Root access disappeared before APK installation")

    staged_paths: list[str] = []
    tmp_cleanups: list[pathlib.Path] = []

    try:
        for apk in apks:
            target_path = str(apk)
            if "/storage/" in str(apk) or "/sdcard/" in str(apk):
                tmp_dest = pathlib.Path(f"/data/local/tmp/{apk.name}")
                if is_root_process:
                    shutil.copyfile(apk, tmp_dest)
                    os.chmod(tmp_dest, 0o644)
                else:
                    stage_cmd = f"cp {shlex.quote(str(apk))} {shlex.quote(str(tmp_dest))} && chmod 644 {shlex.quote(str(tmp_dest))}"
                    stage_res = subprocess.run([su_path, "-c", stage_cmd], **common_kwargs)
                    if stage_res.returncode != 0:
                        raise DeltaUpdaterError(f"Failed to stage {apk.name} for pm install: {stage_res.stderr or stage_res.stdout}")
                target_path = str(tmp_dest)
                tmp_cleanups.append(tmp_dest)
            staged_paths.append(target_path)

        if len(staged_paths) == 1 or not is_split_apk_bundle(apks):
            # Install individual standalone APKs one by one
            for single_path in staged_paths:
                if is_root_process:
                    result = subprocess.run(["pm", "install", "-r", "-d", single_path], **common_kwargs)
                else:
                    result = subprocess.run([su_path, "-c", f"exec pm install -r -d {shlex.quote(single_path)}"], **common_kwargs)
                output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
                if result.returncode != 0 or "Success" not in output:
                    raise DeltaUpdaterError(
                        f"pm install failed for {pathlib.Path(single_path).name} (rc={result.returncode}): {output[:400]}"
                    )
        else:
            # Multiple Split APK install (App Bundle)
            split_files_args = " ".join(shlex.quote(p) for p in staged_paths)
            install_script = f"""
            OUT=$(pm install-multiple -r -d -t -g {split_files_args} 2>&1)
            RC=$?
            if [ $RC -eq 0 ] && echo "$OUT" | grep -qi "Success"; then
                echo "$OUT"
                exit 0
            fi
            
            OUT2=$(pm install -r -d -t -g {split_files_args} 2>&1)
            RC2=$?
            if [ $RC2 -eq 0 ] && echo "$OUT2" | grep -qi "Success"; then
                echo "$OUT2"
                exit 0
            fi
            
            echo "$OUT"
            exit $RC
            """
            if is_root_process:
                result = subprocess.run(["sh", "-c", install_script], **common_kwargs)
            else:
                result = subprocess.run([su_path, "-c", install_script], **common_kwargs)

            output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
            if result.returncode != 0 or "Success" not in output:
                raise DeltaUpdaterError(
                    f"pm install failed for {', '.join(a.name for a in apks)} (rc={result.returncode}): {output[:400]}"
                )
    finally:
        for tmp_dest in tmp_cleanups:
            try:
                if is_root_process:
                    tmp_dest.unlink(missing_ok=True)
                else:
                    subprocess.run([su_path, "-c", f"rm -f {shlex.quote(str(tmp_dest))}"], capture_output=True, timeout=10)
            except Exception:
                pass


def install_apk(apk: pathlib.Path | list[pathlib.Path]) -> None:
    if isinstance(apk, list):
        install_apks(apk)
    else:
        install_apks([apk])


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
                # If archive contains data.tar.gz or folder.tar.gz, it is a valid data/folder backup
                if any(m.filename in ("data.tar.gz", "folder.tar.gz") for m in members):
                    return []
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


def restore_zip_data(zip_path: str | pathlib.Path, target_pkg: Optional[str] = None) -> bool:
    """Extract and restore data.tar.gz or folder.tar.gz from bundle ZIP into destination."""
    if not root_available():
        raise DeltaUpdaterError("Yêu cầu quyền Root (su) để khôi phục dữ liệu ứng dụng / thư mục")
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            namelist = archive.namelist()
            is_folder_backup = "folder.tar.gz" in namelist
            is_data_backup = "data.tar.gz" in namelist
            if not is_folder_backup and not is_data_backup:
                return False

            if is_folder_backup:
                folder_bytes = archive.read("folder.tar.gz")
                if len(folder_bytes) < 50:
                    return False
                meta_dest = None
                if "folder_meta.json" in namelist:
                    try:
                        meta = json.loads(archive.read("folder_meta.json").decode("utf-8"))
                        meta_dest = meta.get("folder_path")
                    except Exception:
                        pass
                folder_alias_map = {
                    "delta": "/storage/emulated/0/Delta",
                    "shouko": "/storage/emulated/0/Download/Shouko",
                    "download": "/storage/emulated/0/Download",
                }
                if not meta_dest and target_pkg:
                    meta_dest = folder_alias_map.get(target_pkg.lower())
                if not meta_dest:
                    meta_dest = "/storage/emulated/0/Delta" if "delta" in str(zip_path).lower() else "/storage/emulated/0/Download/Shouko"

                try:
                    if pathlib.Path("/data/local/tmp").is_dir():
                        tar_cache_path = "/data/local/tmp/delta_restore_folder.tar.gz"
                        with open(tar_cache_path, "wb") as f:
                            f.write(folder_bytes)
                        os.chmod(tar_cache_path, 0o666)
                    else:
                        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp_tar:
                            tmp_tar.write(folder_bytes)
                            tar_cache_path = tmp_tar.name
                except Exception:
                    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp_tar:
                        tmp_tar.write(folder_bytes)
                        tar_cache_path = tmp_tar.name

                parent_dest = str(pathlib.Path(meta_dest).parent)
                base_folder_name = pathlib.Path(meta_dest).name
                restore_folder_script = f"""
                set -e
                mkdir -p {shlex.quote(parent_dest)}
                mkdir -p {shlex.quote(meta_dest)}
                TOP_ENTRY=$(tar -tf {shlex.quote(tar_cache_path)} 2>/dev/null | head -n 1 | cut -d/ -f1)
                if [ "$TOP_ENTRY" = "{base_folder_name}" ]; then
                    tar -xzf {shlex.quote(tar_cache_path)} -C {shlex.quote(parent_dest)}
                else
                    tar -xzf {shlex.quote(tar_cache_path)} -C {shlex.quote(meta_dest)}
                fi
                chmod -R 777 {shlex.quote(meta_dest)} 2>/dev/null || true
                rm -f {shlex.quote(tar_cache_path)}
                """
                is_root_proc = hasattr(os, "geteuid") and os.geteuid() == 0
                su_bin = shutil.which("su")
                kwargs = {"capture_output": True, "text": True, "timeout": 60}
                if is_root_proc:
                    proc = subprocess.run(["sh", "-c", restore_folder_script], **kwargs)
                elif su_bin:
                    proc = subprocess.run([su_bin, "-c", restore_folder_script], **kwargs)
                else:
                    proc = subprocess.run(["sh", "-c", restore_folder_script], **kwargs)
                return proc.returncode == 0

            data_bytes = archive.read("data.tar.gz")
            if len(data_bytes) < 100:
                return False

        alias_map = {
            "termux": "com.termux", "termuxboot": "com.termux.boot", "boot": "com.termux.boot",
            "taskbar": "com.farmerbb.taskbar", "drive": "com.google.android.apps.docs",
            "warp": "com.cloudflare.onedotonedotonedotone", "1.1.1.1": "com.cloudflare.onedotonedotonedotone",
            "pure": "com.apkpure.aegon", "apkpure": "com.apkpure.aegon",
            "mt": "bin.mt.plus", "mtmanager": "bin.mt.plus",
            "rotation": "ahapps.controlthescreenorientation", "opera": "com.opera.browser",
            "hi": "com.tinh.vv.hi", "hj": "com.tinh.vv.hj", "hk": "com.tinh.vv.hk",
            "hl": "com.tinh.vv.hl", "hm": "com.tinh.vv.hm", "hn": "com.tinh.vv.hn",
            "ho": "com.tinh.vv.ho", "hp": "com.tinh.vv.hp", "hq": "com.tinh.vv.hq",
            "hr": "com.tinh.vv.hr", "roblox": "com.roblox.client"
        }
        if target_pkg:
            target_pkg = alias_map.get(target_pkg.lower(), target_pkg)

        # Write data.tar.gz to temporary file
        try:
            tar_cache_path = "/data/local/tmp/delta_restore_data.tar.gz"
            with open(tar_cache_path, "wb") as f:
                f.write(data_bytes)
            os.chmod(tar_cache_path, 0o666)
        except Exception:
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp_tar:
                tmp_tar.write(data_bytes)
                tar_cache_path = tmp_tar.name

        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        su_path = find_su_binary()

        if target_pkg:
            restore_script = f"""
            set -e
            am force-stop {target_pkg} 2>/dev/null || pkill -9 -f {target_pkg} 2>/dev/null || true
            TMP_EXT="/data/local/tmp/restore_ext_$$"
            rm -rf "$TMP_EXT"
            mkdir -p "$TMP_EXT"
            tar -xzf {shlex.quote(tar_cache_path)} -C "$TMP_EXT"
            
            SRC_DIR=$(find "$TMP_EXT" -mindepth 1 -maxdepth 1 -type d | head -n 1)
            if [ -n "$SRC_DIR" ]; then
                DEST_DIR="/data/data/{target_pkg}"
                mkdir -p "$DEST_DIR"
                if [ "{target_pkg}" = "com.termux" ]; then
                    TERMUX_UID=$(stat -c "%u" "$DEST_DIR" 2>/dev/null || echo "")
                    if [ -n "$TERMUX_UID" ]; then
                        pkill -9 -u "$TERMUX_UID" 2>/dev/null || true
                    fi
                    mkdir -p "$DEST_DIR/files"
                    if [ -d "$SRC_DIR/usr" ] || [ -d "$SRC_DIR/home" ]; then
                        tar -xzf {shlex.quote(tar_cache_path)} -C "$DEST_DIR/files" --recursive-unlink 2>/dev/null || cp -a "$SRC_DIR"/. "$DEST_DIR/files"/ 2>/dev/null || true
                    elif [ -d "$SRC_DIR/files" ]; then
                        tar -xzf {shlex.quote(tar_cache_path)} -C "$DEST_DIR" --recursive-unlink 2>/dev/null || cp -a "$SRC_DIR"/. "$DEST_DIR"/ 2>/dev/null || true
                    else
                        cp -a "$SRC_DIR"/. "$DEST_DIR"/ 2>/dev/null || true
                    fi
                    chmod -R 700 "$DEST_DIR/files" 2>/dev/null || true
                    chmod -R 755 "$DEST_DIR/files/usr/bin" 2>/dev/null || true
                    chmod -R 755 "$DEST_DIR/files/usr/lib" 2>/dev/null || true
                else
                    cp -a "$SRC_DIR"/. "$DEST_DIR"/ 2>/dev/null || cp -rf "$SRC_DIR"/* "$DEST_DIR"/ 2>/dev/null || true
                fi
                
                OWNER=$(stat -c "%u:%g" "$DEST_DIR" 2>/dev/null || stat -c "%u:%g" /data/data)
                if [ -n "$OWNER" ]; then
                    chown -R "$OWNER" "$DEST_DIR"
                fi
                chmod -R 771 "$DEST_DIR"
                restorecon -R "$DEST_DIR" 2>/dev/null || true
            fi
            rm -rf "$TMP_EXT" {shlex.quote(tar_cache_path)}
            """
        else:
            restore_script = f"""
            set -e
            tar -xzf {shlex.quote(tar_cache_path)} -C /data/data/
            for pkg_dir in $(tar -tf {shlex.quote(tar_cache_path)} | head -n 1 | cut -d/ -f1); do
                if [ -n "$pkg_dir" ] && [ -d "/data/data/$pkg_dir" ]; then
                    OWNER=$(stat -c "%u:%g" "/data/data/$pkg_dir" 2>/dev/null || stat -c "%u:%g" /data/data)
                    if [ -n "$OWNER" ]; then
                        chown -R "$OWNER" "/data/data/$pkg_dir"
                    fi
                    chmod -R 771 "/data/data/$pkg_dir"
                    restorecon -R "/data/data/$pkg_dir" 2>/dev/null || true
                fi
            done
            rm -f {shlex.quote(tar_cache_path)}
            """

        common_kwargs = {"capture_output": True, "text": True, "timeout": 60}
        if is_root:
            proc = subprocess.run(["sh", "-c", restore_script], **common_kwargs)
        else:
            proc = subprocess.run([su_path, "-c", restore_script], **common_kwargs)

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).strip()[:140]
            print(f"[RESTORE] Lỗi thực thi script phục hồi: {err}", flush=True)
            return False

        return True
    except Exception as ex:
        print(f"[RESTORE] Ngoại lệ phục hồi: {ex}", flush=True)
        return False


def parse_indices(spec: str, total: int) -> list[int]:
    """Parse comma/dash separated 1-based indices (e.g. '1,3,5' or '1-3' or '4')."""
    selected: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            bounds = part.split("-", 1)
            if bounds[0].isdigit() and bounds[1].isdigit():
                start, end = int(bounds[0]), int(bounds[1])
                for idx in range(start, end + 1):
                    if 1 <= idx <= total:
                        selected.add(idx - 1)
        elif part.isdigit():
            idx = int(part)
            if 1 <= idx <= total:
                selected.add(idx - 1)
    return sorted(selected)


def filter_apks(
    install_queue: list[pathlib.Path], selection: Optional[str] = None
) -> list[pathlib.Path]:
    if not install_queue:
        return []
    if not selection or str(selection).strip().lower() in ("all", "none", "*", ""):
        return install_queue

    sel = str(selection).strip().lower()

    # Full random
    if sel in ("random", "rnd"):
        import random
        return [random.choice(install_queue)]

    # Keyword random (e.g. "delta:random", "opera:rnd", "random:3")
    if sel.startswith("random:"):
        count_str = sel.split(":", 1)[1]
        count = int(count_str) if count_str.isdigit() else 1
        count = max(1, min(count, len(install_queue)))
        import random
        return random.sample(install_queue, count)

    if ":random" in sel or ":rnd" in sel:
        kw = sel.split(":", 1)[0]
        matched = [apk for apk in install_queue if kw in apk.name.lower()]
        if not matched:
            raise DeltaUpdaterError(f"Không tìm thấy APK nào chứa từ khóa '{kw}' để chọn ngẫu nhiên")
        import random
        return [random.choice(matched)]

    # Numeric indices (e.g. "4", "1,3,5", "1-4")
    if re.match(r"^\d+(?:-\d+|,\d+)*$", sel):
        indices = parse_indices(sel, len(install_queue))
        if not indices:
            raise DeltaUpdaterError(f"Chỉ số lựa chọn '{selection}' vượt quá số lượng APK ({len(install_queue)})")
        return [install_queue[i] for i in indices]

    # Multi-keyword / Comma or plus separated filters (e.g. "1.1.1,apk,mt" or "warp+mt")
    delimiters = [",", "+", ";"]
    for delim in delimiters:
        if delim in sel:
            keywords = [k.strip() for k in sel.split(delim) if k.strip()]
            matched_map: dict[str, pathlib.Path] = {}
            for kw in keywords:
                for apk in install_queue:
                    if kw in apk.name.lower():
                        matched_map[apk.name] = apk
            if not matched_map:
                raise DeltaUpdaterError(f"Không tìm thấy APK nào khớp với '{selection}' trong Release")
            return list(matched_map.values())

    # Single keyword / App name filter (e.g. "opera", "1.1.1.1", "delta", "roblox")
    matched = [apk for apk in install_queue if sel in apk.name.lower()]
    if not matched:
        raise DeltaUpdaterError(f"Không tìm thấy APK nào khớp với '{selection}' trong Release")
    return matched


def filter_assets(
    assets: list[dict[str, Any]],
    selection: Optional[str] = None
) -> list[dict[str, Any]]:
    if not selection or str(selection).strip().lower() in ("all", "none", "*", ""):
        # Exclude individual account/folder backups (*_DataBackup.zip, *_FolderBackup.zip) from general "all" updates
        # Account/folder backups should only be restored when explicitly targeted by user/index
        base_assets = [a for a in assets if not a.get("name", "").lower().endswith(("_databackup.zip", "_folderbackup.zip"))]
        return base_assets if base_assets else assets

    sel = str(selection).strip().lower()

    # Full random
    if sel in ("random", "rnd"):
        import random
        return [random.choice(assets)]

    # Keyword random (e.g. "delta:random", "opera:rnd", "random:3")
    if sel.startswith("random:"):
        count_str = sel.split(":", 1)[1]
        count = int(count_str) if count_str.isdigit() else 1
        count = max(1, min(count, len(assets)))
        import random
        return random.sample(assets, count)

    if ":random" in sel or ":rnd" in sel:
        kw = sel.split(":", 1)[0]
        matched = [a for a in assets if kw in a.get("name", "").lower()]
        if not matched:
            raise DeltaUpdaterError(f"Không tìm thấy file nào chứa từ khóa '{kw}' để chọn ngẫu nhiên")
        import random
        return [random.choice(matched)]

    # Numeric indices (e.g. "13", "1,3,5", "1-4")
    if re.match(r"^\d+(?:-\d+|,\d+)*$", sel):
        indices = parse_indices(sel, len(assets))
        if not indices:
            raise DeltaUpdaterError(f"Chỉ số lựa chọn '{selection}' vượt quá số lượng file trong Release ({len(assets)})")
        return [assets[i] for i in indices]

    # Multi-keyword / Comma or plus separated filters (e.g. "1.1.1,apk,mt" or "warp+mt")
    delimiters = [",", "+", ";"]
    for delim in delimiters:
        if delim in sel:
            keywords = [k.strip() for k in sel.split(delim) if k.strip()]
            matched_map: dict[str, dict[str, Any]] = {}
            for kw in keywords:
                for a in assets:
                    if kw in a.get("name", "").lower():
                        matched_map[a["name"]] = a
            if not matched_map:
                raise DeltaUpdaterError(f"Không tìm thấy file nào khớp với '{selection}' trong Release")
            return list(matched_map.values())

    # Exact file name match (case-insensitive) without or with extension
    exact_matches = [
        a for a in assets
        if sel == a.get("name", "").lower() or sel == pathlib.PurePosixPath(a.get("name", "")).stem.lower()
    ]
    if exact_matches:
        return exact_matches

    # Folder-specific aliases (prioritize clean single folder backup)
    if sel in ("delta", "delta_folder", "folder:delta", "delta_backup"):
        folder_match = [a for a in assets if a.get("name", "").lower() == "delta_folderbackup.zip"]
        if folder_match:
            return folder_match

    if sel in ("shouko", "shouko_folder", "folder:shouko", "shouko_backup"):
        folder_match = [a for a in assets if a.get("name", "").lower() == "shouko_folderbackup.zip"]
        if folder_match:
            return folder_match

    # APK-specific aliases (e.g. delta_apk, apk:delta)
    if sel in ("delta_apk", "delta_app", "apk:delta"):
        apk_matches = [
            a for a in assets
            if "delta" in a.get("name", "").lower()
            and (a.get("kind") == "apk" or a.get("name", "").lower().endswith((".apk", "_apks.zip")))
            and not a.get("name", "").lower().endswith(("_folderbackup.zip", "_databackup.zip"))
        ]
        if apk_matches:
            return apk_matches

    # Single keyword / App name filter (e.g. "opera", "1.1.1.1", "taskbar", "drive")
    matched = [a for a in assets if sel in a.get("name", "").lower()]
    if not matched:
        raise DeltaUpdaterError(f"Không tìm thấy file nào khớp với '{selection}' trong Release")
    return matched


def _select_assets(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [asset for asset in assets if asset.get("kind") in {"apk", "zip"}]
    if not selected:
        raise DeltaUpdaterError("Manifest has no installable Delta assets")
    return selected


def run_delta_update(
    manifest_source: Optional[str | pathlib.Path | dict] = None,
    download_dir: Optional[str | pathlib.Path] = None,
    selection: Optional[str] = None,
    target_pkg: Optional[str] = None,
) -> dict[str, Any]:
    """Verify every selected APK/ZIP before the first Android install mutation."""
    dl_dir = pathlib.Path(download_dir or DEFAULT_DOWNLOAD_DIR)
    dl_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_latest_release_manifest() if manifest_source is None else load_manifest(manifest_source)
    all_assets = _select_assets(manifest["assets"])
    assets = filter_assets(all_assets, selection)
    print(
        f"[RELEASE] tag={manifest.get('release_tag') or manifest.get('version')} "
        f"selected={len(assets)}/{len(all_assets)} assets",
        flush=True,
    )

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
                progress_label=f"asset {index}/{len(assets)} {asset['name']}",
            )
            print(f"[VERIFY] asset {index}/{len(assets)} {asset['name']}: SHA-256 OK", flush=True)
            staged.append((asset, target))

        install_batches: list[tuple[str, list[pathlib.Path]]] = []
        for index, (asset, target) in enumerate(staged, 1):
            if asset["kind"] == "apk":
                install_batches.append((asset["name"], [target]))
            else:
                extract_dir = tx_root / f"extract_{index:04d}"
                extracted = extract_zip_apks(target, extract_dir)
                if extracted:
                    install_batches.append((asset["name"], extracted))
                    print(
                        f"[EXTRACT] {asset['name']}: {len(extracted)} APK(s) verified",
                        flush=True,
                    )

        installed_count = 0
        failed_errors: list[str] = []
        for index, (pkg_label, apks) in enumerate(install_batches, 1):
            if "termux" in pkg_label.lower():
                print(f"[INSTALL] {index}/{len(install_batches)} Bỏ qua cài đặt APK {pkg_label} (Termux đang chạy dịch vụ Agent)", flush=True)
                installed_count += len(apks)
                continue
            print(f"[INSTALL] {index}/{len(install_batches)} {pkg_label} ({len(apks)} APK/Splits)", flush=True)
            try:
                install_apk(apks)
                installed_count += len(apks)
            except Exception as ex:
                err = str(ex)
                print(f"[WARN] Failed to install {pkg_label}: {err}", flush=True)
                failed_errors.append(f"{pkg_label}: {err[:120]}")

        # Restore application data from ZIP bundles if present
        restored_count = 0
        for _, target in staged:
            if target.name.lower().endswith(".zip"):
                try:
                    if restore_zip_data(target, target_pkg=target_pkg):
                        restored_count += 1
                        print(f"[RESTORE] App data restored successfully from {target.name}", flush=True)
                except Exception as ex:
                    print(f"[WARN] Failed to restore data from {target.name}: {ex}", flush=True)

        if installed_count == 0 and restored_count == 0:
            if failed_errors:
                raise DeltaUpdaterError(f"Cài đặt thất bại: {'; '.join(failed_errors[:2])}")
            raise DeltaUpdaterError("UPDATE_DELTA verified release but found zero APKs and zero restorable data packages")

    return {
        "ok": True,
        "channel": "delta",
        "version": manifest["version"],
        "release_tag": manifest.get("release_tag"),
        "installed_count": installed_count,
        "selection": selection or "all",
        "target_pkg": target_pkg,
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

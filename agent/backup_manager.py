#!/usr/bin/env python3
"""Module to create full APK + Data backups of Android apps and upload directly to GitHub Release."""

from __future__ import annotations

import os
import re
import sys
import shutil
import zipfile
import tempfile
import pathlib
import subprocess
from typing import Any, Optional


class BackupError(RuntimeError):
    pass


def _get_pm_bin() -> str:
    if os.path.exists("/system/bin/pm"):
        return "/system/bin/pm"
    return shutil.which("pm") or "pm"


def find_package_name(keyword_or_pkg: str) -> str:
    """Find the exact package name on Android matching keyword or full package name."""
    keyword_or_pkg = keyword_or_pkg.strip()
    pm_bin = _get_pm_bin()
    # Check if exact package exists
    cmd = [pm_bin, "list", "packages", keyword_or_pkg]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        for line in proc.stdout.splitlines():
            clean = line.strip().replace("package:", "")
            if clean == keyword_or_pkg:
                return clean
    except Exception:
        pass

    # Search loosely
    loose_cmd = [pm_bin, "list", "packages"]
    try:
        proc = subprocess.run(loose_cmd, capture_output=True, text=True, timeout=5)
        matches = []
        for line in proc.stdout.splitlines():
            pkg = line.strip().replace("package:", "")
            if keyword_or_pkg.lower() in pkg.lower():
                matches.append(pkg)
        if matches:
            matches.sort(key=len)
            return matches[0]
    except Exception:
        pass

    # Common aliases
    aliases = {
        "taskbar": "com.farmerbb.taskbar",
        "drive": "com.google.android.apps.docs",
        "warp": "com.cloudflare.onedotonedotonedotone",
        "1.1.1.1": "com.cloudflare.onedotonedotonedotone",
        "pure": "com.apkpure.aegon",
        "apkpure": "com.apkpure.aegon",
        "mt": "bin.mt.plus",
        "mtmanager": "bin.mt.plus",
        "rotation": "ahapps.controlthescreenorientation",
        "opera": "com.opera.browser",
    }
    alias_match = aliases.get(keyword_or_pkg.lower())
    if alias_match:
        return alias_match

    raise BackupError(f"Không tìm thấy ứng dụng nào khớp với từ khóa '{keyword_or_pkg}' trên thiết bị.")


def create_app_backup(package_name: str, output_dir: pathlib.Path) -> pathlib.Path:
    """Extract APKs and Data directory for package_name and create a bundle ZIP."""
    # 1. Get APK paths
    pm_cmd = [_get_pm_bin(), "path", package_name]
    proc = subprocess.run(pm_cmd, capture_output=True, text=True, timeout=5)
    apk_paths = []
    for line in proc.stdout.splitlines():
        if line.startswith("package:"):
            apk_paths.append(pathlib.Path(line.replace("package:", "").strip()))

    if not apk_paths:
        raise BackupError(f"Không tìm thấy file APK nào cho gói {package_name}.")

    # 2. Prepare backup bundle
    clean_name = package_name.split(".")[-1].capitalize()
    bundle_name = f"{clean_name}_FullBackup.zip"
    bundle_path = output_dir / bundle_name

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add APKs
        for apk in apk_paths:
            if apk.exists():
                zf.write(apk, arcname=f"apks/{apk.name}")

        # Add Data directory if accessible (via su / root)
        temp_data_tar = output_dir / "data.tar.gz"
        su_cmd = f"cd /data/data && tar -czf {shlex.quote(str(temp_data_tar))} {shlex.quote(package_name)}"
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        if is_root:
            subprocess.run(shlex.split(su_cmd), capture_output=True, timeout=30)
        else:
            su_path = shutil.which("su")
            if su_path:
                subprocess.run([su_path, "-c", su_cmd], capture_output=True, timeout=30)

        if temp_data_tar.exists() and temp_data_tar.stat().st_size > 100:
            zf.write(temp_data_tar, arcname="data.tar.gz")
            temp_data_tar.unlink(missing_ok=True)

    return bundle_path


def upload_to_github_release(
    file_path: pathlib.Path,
    repo: str = "tinhpr9/phanserver-delta",
    tag: str = "Backup",
    token: Optional[str] = None
) -> str:
    """Upload file to GitHub Release using REST API or gh CLI."""
    file_path = pathlib.Path(file_path)
    if not file_path.is_file():
        raise BackupError(f"File không tồn tại: {file_path}")

    auth_token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not auth_token:
        cfg_file = pathlib.Path("/storage/emulated/0/Download/Shouko/agent_config.json")
        if cfg_file.is_file():
            try:
                import json
                with open(cfg_file, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                    auth_token = cfg_data.get("github_token")
            except Exception:
                pass

    if not auth_token:
        try:
            res = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                auth_token = res.stdout.strip()
        except Exception:
            pass

    # 1. Direct Python GitHub REST API upload
    if auth_token:
        try:
            import urllib.request, json
            rel_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
            req = urllib.request.Request(
                rel_url,
                headers={
                    "Authorization": f"Bearer {auth_token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "phanserver-delta-agent/1.0"
                }
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                rel_data = json.loads(resp.read().decode("utf-8"))

            # Delete old asset if already exists
            for asset in rel_data.get("assets", []):
                if asset.get("name") == file_path.name:
                    del_url = f"https://api.github.com/repos/{repo}/releases/assets/{asset['id']}"
                    del_req = urllib.request.Request(
                        del_url,
                        headers={
                            "Authorization": f"Bearer {auth_token}",
                            "Accept": "application/vnd.github+json",
                            "User-Agent": "phanserver-delta-agent/1.0"
                        },
                        method="DELETE"
                    )
                    try:
                        with urllib.request.urlopen(del_req, timeout=10):
                            pass
                    except Exception:
                        pass

            # Upload new asset
            upload_url_template = rel_data.get("upload_url", "")
            base_upload_url = upload_url_template.split("{")[0]
            target_upload_url = f"{base_upload_url}?name={file_path.name}"

            with open(file_path, "rb") as f:
                payload = f.read()

            up_req = urllib.request.Request(
                target_upload_url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {auth_token}",
                    "Content-Type": "application/zip",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "phanserver-delta-agent/1.0"
                },
                method="POST"
            )
            with urllib.request.urlopen(up_req, timeout=60) as up_resp:
                if up_resp.status in (200, 201):
                    return f"https://github.com/{repo}/releases/download/{tag}/{file_path.name}"
        except Exception as ex:
            pass

    # 2. Fallback to gh CLI
    gh_bin = shutil.which("gh") or "/data/data/com.termux/files/usr/bin/gh"
    if os.path.exists(gh_bin) or shutil.which("gh"):
        cmd = [gh_bin, "release", "upload", tag, str(file_path), "--repo", repo, "--clobber"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            return f"https://github.com/{repo}/releases/download/{tag}/{file_path.name}"
        raise BackupError(f"Lỗi khi tải lên GitHub Release qua gh: {proc.stderr.strip() or proc.stdout.strip()}")

    raise BackupError("Không tìm thấy GitHub Token hoặc lệnh 'gh' trên thiết bị để upload Release.")


def run_backup_and_upload(
    keyword_or_pkg: str,
    repo: str = "tinhpr9/phanserver-delta",
    tag: str = "Backup"
) -> dict[str, Any]:
    """Orchestrate finding package, packaging APK+Data, and uploading to GitHub Release."""
    package_name = find_package_name(keyword_or_pkg)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = pathlib.Path(tmpdir)
        bundle_file = create_app_backup(package_name, tmp_path)
        download_url = upload_to_github_release(bundle_file, repo=repo, tag=tag)
        return {
            "ok": True,
            "package_name": package_name,
            "filename": bundle_file.name,
            "download_url": download_url,
            "tag": tag,
        }


if __name__ == "__main__":
    pkg_arg = sys.argv[1] if len(sys.argv) > 1 else "taskbar"
    print(f"[*] Starting backup for {pkg_arg}...")
    res = run_backup_and_upload(pkg_arg)
    print(f"[+] Backup completed: {res}")

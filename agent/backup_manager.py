#!/usr/bin/env python3
"""Module to create full APK + Data backups of Android apps and upload directly to GitHub Release."""

from __future__ import annotations

import json
import codecs
import os
import re
import sys
import shlex
import shutil
import zipfile
import tempfile
import pathlib
import subprocess
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


class BackupError(RuntimeError):
    pass


def _get_pm_bin() -> str:
    if os.path.exists("/system/bin/pm"):
        return "/system/bin/pm"
    return shutil.which("pm") or "pm"


def _run_as_root(cmd: str, timeout: int = 180) -> subprocess.CompletedProcess:
    """Execute command as root using the real Android system su binary."""
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    if is_root:
        try:
            return subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(args=["sh", "-c", cmd], returncode=124, stdout="", stderr=f"Lệnh chạy quá thời gian ({timeout}s)")
        except Exception as e:
            return subprocess.CompletedProcess(args=["sh", "-c", cmd], returncode=1, stdout="", stderr=str(e))

    su_candidates = ["/system/xbin/su", "/system/bin/su", "/sbin/su", "/vendor/bin/su"]
    which_su = shutil.which("su")
    if which_su and not which_su.startswith("/data/data/com.termux/"):
        su_candidates.insert(0, which_su)
    elif which_su:
        su_candidates.append(which_su)

    last_res = None
    for su in su_candidates:
        if os.path.exists(su):
            try:
                res = subprocess.run([su, "-c", cmd], capture_output=True, text=True, timeout=timeout)
                if res.returncode == 0:
                    return res
                last_res = res
            except Exception:
                pass

    if last_res is not None:
        return last_res
    try:
        return subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return subprocess.CompletedProcess(args=["sh", "-c", cmd], returncode=1, stdout="", stderr=str(e))


def find_package_name(keyword_or_pkg: str) -> str:
    """Find the exact package name on Android matching keyword or full package name."""
    keyword_or_pkg = keyword_or_pkg.strip()
    if not keyword_or_pkg:
        raise BackupError("Tên gói hoặc từ khóa ứng dụng không được để trống.")

    # Common aliases
    aliases = {
        "termux": "com.termux",
        "termuxboot": "com.termux.boot",
        "boot": "com.termux.boot",
        "termux:boot": "com.termux.boot",
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
        "roblox": "com.roblox.client",
        "hi": "com.tinh.vv.hi",
        "hj": "com.tinh.vv.hj",
        "hk": "com.tinh.vv.hk",
        "hl": "com.tinh.vv.hl",
        "hm": "com.tinh.vv.hm",
        "hn": "com.tinh.vv.hn",
        "ho": "com.tinh.vv.ho",
        "hp": "com.tinh.vv.hp",
        "hq": "com.tinh.vv.hq",
        "hr": "com.tinh.vv.hr",
    }
    alias_match = aliases.get(keyword_or_pkg.lower())

    pm_bin = _get_pm_bin()
    pkg_lines = []
    try:
        proc = subprocess.run([pm_bin, "list", "packages"], capture_output=True, text=True, timeout=5)
        pkg_lines = proc.stdout.splitlines()
    except Exception:
        pass
    if not pkg_lines:
        try:
            proc = _run_as_root(f"{pm_bin} list packages", timeout=5)
            pkg_lines = proc.stdout.splitlines()
        except Exception:
            pass

    installed = [line.strip().replace("package:", "") for line in pkg_lines if line.strip()]

    if keyword_or_pkg in installed:
        return keyword_or_pkg
    if alias_match and alias_match in installed:
        return alias_match

    # Search loosely
    matches = [pkg for pkg in installed if keyword_or_pkg.lower() in pkg.lower()]
    if matches:
        matches.sort(key=len)
        return matches[0]

    if alias_match:
        return alias_match

    raise BackupError(f"Không tìm thấy ứng dụng nào khớp với từ khóa '{keyword_or_pkg}' trên thiết bị.")


def detect_app_username(package_name: str) -> Optional[str]:
    """Inspect /data/data/<package_name>/shared_prefs and files to discover the logged-in username."""
    probe_script = f"""
    for f in /data/data/{shlex.quote(package_name)}/shared_prefs/*.xml /data/data/{shlex.quote(package_name)}/files/*.json; do
        if [ -f "$f" ]; then
            cat "$f" 2>/dev/null
        fi
    done
    """
    try:
        proc = _run_as_root(probe_script, timeout=5)
        output = proc.stdout or ""
        if output:
            patterns = [
                r'name="[Uu]sername"[^>]*>([a-zA-Z0-9_]{3,25})<',
                r'name="[Uu]serName"[^>]*>([a-zA-Z0-9_]{3,25})<',
                r'name="account_name"[^>]*>([a-zA-Z0-9_]{3,25})<',
                r'name="AccountName"[^>]*>([a-zA-Z0-9_]{3,25})<',
                r'name="displayName"[^>]*>([a-zA-Z0-9_]{3,25})<',
                r'name="DisplayName"[^>]*>([a-zA-Z0-9_]{3,25})<',
                r'name="RobloxUser"[^>]*>([a-zA-Z0-9_]{3,25})<',
                r'"username"\s*:\s*"([a-zA-Z0-9_]{3,25})"',
                r'"UserName"\s*:\s*"([a-zA-Z0-9_]{3,25})"',
                r'"name"\s*:\s*"([a-zA-Z0-9_]{3,25})"',
            ]
            for pat in patterns:
                m = re.search(pat, output, re.IGNORECASE)
                if m:
                    candidate = m.group(1).strip()
                    if candidate and candidate.lower() not in ("true", "false", "null", "none", "default", "guest"):
                        return candidate
    except Exception:
        pass
    return None


def create_app_backup(package_name: str, output_dir: pathlib.Path, mode: str = "full") -> pathlib.Path:
    """Extract APKs, Data directory or both for package_name and create backup artifact."""
    mode = (mode or "full").lower()
    raw_clean_name = package_name.split(".")[-1].capitalize()
    detected_user = detect_app_username(package_name)
    user_tag = f"_{detected_user}" if detected_user else ""
    clean_name = f"{raw_clean_name}{user_tag}"

    # 1. Extract APKs if mode is 'full' or 'apk'
    apk_paths = []
    if mode in ("full", "apk"):
        pm_bin = _get_pm_bin()
        pm_out = ""
        try:
            proc = subprocess.run([pm_bin, "path", package_name], capture_output=True, text=True, timeout=5)
            pm_out = proc.stdout or ""
        except Exception:
            pass
        if not pm_out:
            try:
                proc = _run_as_root(f"{pm_bin} path {shlex.quote(package_name)}", timeout=5)
                pm_out = proc.stdout or ""
            except Exception:
                pass

        for line in pm_out.splitlines():
            if line.startswith("package:"):
                apk_paths.append(pathlib.Path(line.replace("package:", "").strip()))

        if not apk_paths:
            raise BackupError(f"Không tìm thấy file APK nào cho gói {package_name}.")

    # APK-Only Mode
    if mode == "apk":
        if len(apk_paths) == 1:
            dest_apk = output_dir / f"{clean_name}.apk"
            shutil.copyfile(apk_paths[0], dest_apk)
            return dest_apk
        else:
            bundle_path = output_dir / f"{clean_name}_APKs.zip"
            with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for apk in apk_paths:
                    if apk.exists():
                        zf.write(apk, arcname=f"apks/{apk.name}")
            return bundle_path

    # Extract Data directory for 'full' and 'data' modes
    temp_data_tar = output_dir / "data.tar.gz"
    tar_dest = shlex.quote(str(temp_data_tar))
    pkg_q = shlex.quote(package_name)
    if package_name == "com.termux":
        su_cmd = (
            f"cd /data/data && (tar "
            f"--exclude='com.termux/files/usr/tmp' "
            f"--exclude='com.termux/files/usr/var/cache' "
            f"--exclude='com.termux/files/usr/share/doc' "
            f"--exclude='com.termux/files/usr/share/man' "
            f"--exclude='com.termux/cache' "
            f"-czf {tar_dest} com.termux 2>/dev/null || "
            f"tar -czf {tar_dest} com.termux 2>/dev/null || "
            f"tar -cf - com.termux 2>/dev/null | gzip > {tar_dest}) && chmod 666 {tar_dest} 2>/dev/null || true"
        )
        timeout_val = 600
    else:
        su_cmd = f"cd /data/data && (tar -czf {tar_dest} {pkg_q} 2>/dev/null || tar -cf - {pkg_q} 2>/dev/null | gzip > {tar_dest}) && chmod 666 {tar_dest} 2>/dev/null || true"
        timeout_val = 180

    _run_as_root(su_cmd, timeout=timeout_val)

    has_data = temp_data_tar.exists() and temp_data_tar.stat().st_size > 50

    # Data-Only Mode
    if mode == "data":
        if not has_data:
            raise BackupError(f"Không thể đọc thư mục dữ liệu /data/data/{package_name} (yêu cầu quyền Root).")
        bundle_path = output_dir / f"{clean_name}_DataBackup.zip"
        with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(temp_data_tar, arcname="data.tar.gz")
        temp_data_tar.unlink(missing_ok=True)
        return bundle_path

    # Full Backup Mode (APKs + Data)
    bundle_path = output_dir / f"{clean_name}_FullBackup.zip"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for apk in apk_paths:
            if apk.exists():
                zf.write(apk, arcname=f"apks/{apk.name}")
        if has_data:
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
        candidate_configs = [
            pathlib.Path("/storage/emulated/0/Download/Shouko/agent_config.json"),
            pathlib.Path("/storage/emulated/0/Download/agent_config.json"),
            pathlib.Path("/data/data/com.termux/files/home/agent_config.json"),
            pathlib.Path.home() / "agent_config.json",
            pathlib.Path(__file__).resolve().parent.parent / "agent_config.json",
        ]
        for cfg_file in candidate_configs:
            if cfg_file.is_file():
                try:
                    import json
                    with open(cfg_file, "r", encoding="utf-8") as f:
                        cfg_data = json.load(f)
                        token_cand = cfg_data.get("github_token") or cfg_data.get("token")
                        if token_cand:
                            auth_token = str(token_cand).strip()
                            break
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
    last_upload_err = None
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
            try:
                with urllib.request.urlopen(up_req, timeout=300) as up_resp:
                    if up_resp.status in (200, 201):
                        return f"https://github.com/{repo}/releases/download/{tag}/{file_path.name}"
                    last_upload_err = f"HTTP {up_resp.status}"
            except Exception as ex:
                last_upload_err = str(ex)
        except Exception as ex:
            last_upload_err = str(ex)

    # 2. Fallback to gh CLI
    gh_bin = shutil.which("gh") or "/data/data/com.termux/files/usr/bin/gh"
    if os.path.exists(gh_bin) or shutil.which("gh"):
        cmd = [gh_bin, "release", "upload", tag, str(file_path), "--repo", repo, "--clobber"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode == 0:
            return f"https://github.com/{repo}/releases/download/{tag}/{file_path.name}"
        raise BackupError(f"Lỗi khi tải lên GitHub Release (REST: {last_upload_err}, gh: {proc.stderr.strip() or proc.stdout.strip()})")

    if last_upload_err:
        raise BackupError(f"Lỗi khi tải lên GitHub Release qua REST: {last_upload_err}")

    raise BackupError("Không tìm thấy GitHub Token hoặc lệnh 'gh' trên thiết bị để upload Release.")


FOLDER_TARGETS = {
    "delta": "/storage/emulated/0/Delta",
    "shouko": "/storage/emulated/0/Download/Shouko",
    "cookie-pool-leases": "/storage/emulated/0/Download/.cookie-pool-leases",
}


def create_folder_backup(folder_name: str, folder_path: str, output_dir: pathlib.Path) -> pathlib.Path:
    """Compress an Android folder (e.g. /sdcard/Delta or /sdcard/Download/Shouko) into a backup bundle."""
    clean_name = folder_name.capitalize()
    bundle_path = output_dir / f"{clean_name}_FolderBackup.zip"
    temp_tar = pathlib.Path(f"/data/local/tmp/{clean_name}_folder.tar.gz")
    temp_tar.unlink(missing_ok=True)

    tar_dest = shlex.quote(str(temp_tar))
    parent_dir = str(pathlib.Path(folder_path).parent)
    base_name = pathlib.Path(folder_path).name

    cmd = f"cd {shlex.quote(parent_dir)} && (tar -czf {tar_dest} {shlex.quote(base_name)} 2>/dev/null || tar -cf - {shlex.quote(base_name)} 2>/dev/null | gzip > {tar_dest}) && chmod 666 {tar_dest} 2>/dev/null || true"
    _run_as_root(cmd, timeout=300)

    if not temp_tar.exists() or temp_tar.stat().st_size < 50:
        subprocess.run(["sh", "-c", cmd], capture_output=True, timeout=300)

    if not temp_tar.exists() or temp_tar.stat().st_size < 50:
        raise BackupError(f"Không thể nén thư mục {folder_path} (thư mục không tồn tại hoặc rỗng).")

    meta = {
        "type": "folder",
        "folder_name": folder_name,
        "folder_path": folder_path
    }

    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("folder_meta.json", json.dumps(meta, indent=2))
        zf.write(temp_tar, arcname="folder.tar.gz")

    temp_tar.unlink(missing_ok=True)
    return bundle_path


def run_backup_and_upload(
    keyword_or_pkg: str,
    mode: str = "full",
    repo: str = "tinhpr9/phanserver-delta",
    tag: str = "Backup"
) -> dict[str, Any]:
    """Orchestrate finding package(s) or folder(s), packaging, and uploading to GitHub Release."""
    raw = keyword_or_pkg.strip()
    if raw.lower() in ("all", "clones"):
        targets = ["hi", "hj", "hk", "hl", "hm", "hn", "ho", "hp", "hq", "hr", "roblox"]
    elif "," in raw:
        targets = [p.strip() for p in raw.split(",") if p.strip()]
    else:
        targets = [raw]

    results = []
    errors = []

    # Ensure backup directory is created outside /data/data (e.g. /data/local/tmp or /storage/emulated/0)
    backup_base = None
    for cand_base in ("/data/local/tmp", "/storage/emulated/0/Download"):
        p = pathlib.Path(cand_base)
        if p.exists() and os.access(str(p), os.W_OK):
            backup_base = str(p)
            break
        elif p.exists():
            _run_as_root(f"chmod 777 {shlex.quote(str(p))} 2>/dev/null || true")
            backup_base = str(p)
            break

    with tempfile.TemporaryDirectory(dir=backup_base) as tmpdir:
        tmp_path = pathlib.Path(tmpdir)
        for t in targets:
            try:
                if t.lower() in FOLDER_TARGETS or os.path.isdir(t):
                    folder_name = t.lower() if t.lower() in FOLDER_TARGETS else pathlib.Path(t).name
                    folder_path = FOLDER_TARGETS.get(t.lower(), t)
                    bundle_file = create_folder_backup(folder_name, folder_path, tmp_path)
                    pkg_name = f"folder:{folder_name}"
                else:
                    pkg_name = find_package_name(t)
                    bundle_file = create_app_backup(pkg_name, tmp_path, mode=mode)
                download_url = upload_to_github_release(bundle_file, repo=repo, tag=tag)
                results.append({
                    "ok": True,
                    "package_name": pkg_name,
                    "mode": mode,
                    "filename": bundle_file.name,
                    "download_url": download_url,
                })
            except Exception as e:
                err_msg = str(e)
                print(f"[WARN] Backup failed for target {t}: {err_msg}", flush=True)
                errors.append(f"{t}: {err_msg}")

    if not results:
        detail = "; ".join(errors) if errors else "Không tìm thấy dữ liệu"
        raise BackupError(f"Sao lưu thất bại: {detail[:150]}")

    return {
        "ok": True,
        "mode": mode,
        "tag": tag,
        "count": len(results),
        "results": results,
        "filename": ", ".join(r["filename"] for r in results),
        "download_url": results[0]["download_url"] if results else None
    }


if __name__ == "__main__":
    pkg_arg = sys.argv[1] if len(sys.argv) > 1 else "taskbar"
    mode_arg = sys.argv[2] if len(sys.argv) > 2 else "full"
    print(f"[*] Starting backup for {pkg_arg} (Mode: {mode_arg})...")
    res = run_backup_and_upload(pkg_arg, mode=mode_arg)
    print(f"[+] Backup completed: {res}")

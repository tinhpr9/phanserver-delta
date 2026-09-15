#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: agent.account_manager
Nghiệp vụ quản lý dàn tài khoản:
- Phân tích cú pháp acc.txt theo mã dàn máy (M77, M109, M124...).
- Kiểm tra trạng thái Ban Roblox API chính thức (v1/usernames/users & v1/users/{userId}).
- Quota-Guard Cache (TTL 300s) chống lặp truy vấn Roblox API.
- Exponential backoff chống HTTP 429 và phân tích header Retry-After.
- Lưu trữ bảo toàn acc bị ban (acc_bi_ban.txt, nhat_ky_ban.txt).
- Xóa acc ban khỏi acc.txt và Data_Tong_Cookies.txt kèm dual-storage .bak_<timestamp>.
- Tự động nạp bù tài khoản từ kho dự trữ acc_du_phong.txt vào đúng dàn máy.
- Đồng bộ Google Drive in-place qua rclone (tuân thủ tuyệt đối Rule 34 - bảo toàn File ID).
"""

import os
import re
import sys
import json
import time
import shutil
import random
import threading
import urllib.request
import urllib.error
import subprocess
import sqlite3
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_BASE_DIR = "/storage/emulated/0/Download/Shouko"
ROBLOX_BATCH_USERNAMES_URL = "https://users.roblox.com/v1/usernames/users"
ROBLOX_USER_DETAIL_URL = "https://users.roblox.com/v1/users/{userId}"

# Rule 34 Google Drive In-Place Sync & File ID Invariants
RULE34_ACC_FILE_ID = "12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg"
RULE34_DATA_TONG_FILE_ID = "1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B"
RULE34_ACC_RESERVE_FILE_ID = "1sprXB5Sub3Dzt6-CGkaZY7ODsiHd4kG4"

# ZeroPoint CookieChecker API
ZEROPOINT_COOKIE_CHECKER_URL = "https://zeropoint.to/api/cookie-checker-api"
DEFAULT_ZEROPOINT_API_KEY = "ZP_CookieChecker_fGLOGOoJITp2SK402kgMtFqMAZCfXgH9"

# Quota-Guard Cache
_QUOTA_GUARD_CACHE = {}  # username_lower: {"data": dict, "timestamp": float}
_CACHE_LOCK = threading.Lock()
DEFAULT_CACHE_TTL = 300  # 300 seconds (5 phút)


def clear_ban_cache():
    """Xóa toàn bộ Quota-Guard Cache."""
    with _CACHE_LOCK:
        _QUOTA_GUARD_CACHE.clear()


def invalidate_ban_cache(usernames=None):
    """Hủy cache cho một danh sách usernames hoặc toàn bộ nếu None."""
    with _CACHE_LOCK:
        if usernames is None:
            _QUOTA_GUARD_CACHE.clear()
        else:
            for u in usernames:
                if u:
                    _QUOTA_GUARD_CACHE.pop(str(u).strip().lower(), None)


def get_ban_cache_stats():
    """Lấy số liệu thống kê hiện thời của Quota-Guard Cache."""
    with _CACHE_LOCK:
        now = time.time()
        active = sum(1 for v in _QUOTA_GUARD_CACHE.values() if now - v.get("timestamp", 0) < DEFAULT_CACHE_TTL)
        return {
            "total_entries": len(_QUOTA_GUARD_CACHE),
            "active_entries": active,
            "expired_entries": len(_QUOTA_GUARD_CACHE) - active,
        }


def get_default_paths(base_dir=None):
    """Lấy đường dẫn mặc định các tệp tài khoản."""
    bdir = base_dir or DEFAULT_BASE_DIR
    return {
        "base_dir": bdir,
        "acc_file": os.path.join(bdir, "acc.txt"),
        "data_tong_file": os.path.join(bdir, "Data_Tong_Cookies.txt"),
        "acc_bi_ban_file": os.path.join(bdir, "acc_bi_ban.txt"),
        "acc_face_lock_file": os.path.join(bdir, "acc_face_lock.txt"),
        "acc_captcha_lock_file": os.path.join(bdir, "acc_captcha_lock.txt"),
        "acc_dead_cookies_file": os.path.join(bdir, "acc_dead_cookies.txt"),
        "nhat_ky_ban_file": os.path.join(bdir, "nhat_ky_ban.txt"),
        "nhat_ky_face_lock_file": os.path.join(bdir, "nhat_ky_face_lock.txt"),
        "nhat_ky_captcha_lock_file": os.path.join(bdir, "nhat_ky_captcha_lock.txt"),
        "face_target_file": os.path.join(bdir, "Face_Target_File.txt"),
        "acc_du_phong_file": os.path.join(bdir, "acc_du_phong.txt"),
    }


def check_zeropoint_cookie_status(
    user_cookie_map: dict[str, str],
    api_key: str = None,
    timeout: int = 40,
) -> dict[str, dict]:
    """
    Gửi cookies lên ZeroPoint CookieChecker API và phân loại trạng thái:
    - ALIVE: Sống hoàn toàn
    - BANNED: Bị ban / cảnh cáo (ban_warn)
    - FACE_LOCK: Bị khóa FaceID / Checkpoint xác minh
    - CAPTCHA_LOCK: Bị khóa Captcha / Yêu cầu xác minh người thật
    - DEAD: Cookie hỏng hoặc hết hạn
    Trả về dict[username, {"status": "ALIVE"|"BANNED"|"FACE_LOCK"|"CAPTCHA_LOCK"|"DEAD", "reason": ...}]
    """
    if not user_cookie_map:
        return {}

    key = api_key or os.getenv("ZEROPOINT_COOKIE_KEY") or DEFAULT_ZEROPOINT_API_KEY
    cookie_to_users = {}
    for uname, c in user_cookie_map.items():
        if c and c.strip():
            c_clean = c.strip()
            if "_|WARNING:" in c_clean:
                c_clean = c_clean[c_clean.index("_|WARNING:"):].strip()
            cookie_to_users.setdefault(c_clean, []).append(uname)

    if not cookie_to_users:
        return {}

    if not any(len(c) > 250 for c in cookie_to_users):
        return {}

    cookies_payload = "\n".join(cookie_to_users.keys())
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    headers = {
        "X-API-Key": key,
        "Content-Type": "application/json",
        "User-Agent": ua
    }
    submit_url = f"{ZEROPOINT_COOKIE_CHECKER_URL}/submit"

    try:
        data = json.dumps({"cookies": cookies_payload}).encode("utf-8")
        req = urllib.request.Request(submit_url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            sub_res = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[ZEROPOINT] Lỗi gửi submit cookies: {e}", flush=True)
        return {}

    session_id = sub_res.get("session_id")
    if not session_id:
        print(f"[ZEROPOINT] Submit không trả về session_id: {sub_res}", flush=True)
        return {}

    status_url = f"{ZEROPOINT_COOKIE_CHECKER_URL}/status/{session_id}"
    start_time = time.time()
    final_st_data = None
    while time.time() - start_time < timeout:
        time.sleep(2)
        try:
            req = urllib.request.Request(status_url, headers={"X-API-Key": key, "User-Agent": ua})
            with urllib.request.urlopen(req, timeout=8) as resp:
                st_data = json.loads(resp.read().decode("utf-8"))
            if st_data.get("status") in ("completed", "error"):
                final_st_data = st_data
                break
        except Exception:
            continue

    if not final_st_data or final_st_data.get("status") != "completed":
        print(f"[ZEROPOINT] Phiên {session_id} không hoàn tất hoặc lỗi: {final_st_data}", flush=True)
        return {}

    results = {}
    download_files = final_st_data.get("download_files") or {}
    for ftype in list(download_files.keys()):
        norm_type = ftype.lower()
        cat = "ALIVE"
        if "ban" in norm_type or "warn" in norm_type:
            cat = "BANNED"
        elif "face" in norm_type or "checkpoint" in norm_type:
            cat = "FACE_LOCK"
        elif "captcha" in norm_type or "lock" in norm_type:
            cat = "CAPTCHA_LOCK"
        elif "dead" in norm_type or "expired" in norm_type or "invalid" in norm_type:
            cat = "DEAD"
        elif "live" in norm_type or "valid" in norm_type or "alive" in norm_type:
            cat = "ALIVE"

        dl_url = f"{ZEROPOINT_COOKIE_CHECKER_URL}/download/{session_id}/{ftype}"
        try:
            req = urllib.request.Request(dl_url, headers={"X-API-Key": key, "User-Agent": ua})
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("utf-8")
            for c_line in text.splitlines():
                c_clean = c_line.strip()
                if not c_clean:
                    continue
                matched_users = list(cookie_to_users.get(c_clean, []))
                if not matched_users:
                    for orig_c, u_list in cookie_to_users.items():
                        if c_clean in orig_c or orig_c in c_clean:
                            matched_users.extend(u_list)
                for u in set(matched_users):
                    results[u] = {"status": cat, "reason": f"ZeroPoint: {ftype}"}
        except Exception as e:
            print(f"[ZEROPOINT] Lỗi tải kết quả {ftype}: {e}", flush=True)

    if results:
        for u in user_cookie_map:
            if u not in results:
                results[u] = {"status": "ALIVE", "reason": "ZeroPoint default"}

    return results


def check_roblox_cookie_status(
    user_cookie_map: dict[str, str],
    timeout: int = 8,
    use_cache: bool = True,
    cache_ttl: int = DEFAULT_CACHE_TTL
) -> dict[str, dict]:
    """
    Kiểm tra trực tiếp cookie .ROBLOSECURITY qua Roblox API chính thức:
    - https://users.roblox.com/v1/users/authenticated (Session Validation)
    - HTTP 200: ALIVE (Session hoạt động bình thường)
    - HTTP 401: DEAD (Cookie hết hạn hoặc không hợp lệ)
    - HTTP 403 (User is moderated):
        Kiểm tra profile công khai:
        - isBanned: True -> BANNED (Terminated vĩnh viễn)
        - isBanned: False -> FACE_LOCK (Khóa FaceID / Checkpoint xác minh người thật)
    """
    results = {}
    if not user_cookie_map:
        return results

    if not any(c and len(c.strip()) > 250 for c in user_cookie_map.values()):
        return results

    moderated_users = []
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    for uname, cookie in user_cookie_map.items():
        if not cookie or not cookie.strip():
            results[uname] = {"status": "DEAD", "reason": "No cookie provided"}
            continue

        ck = cookie.strip()
        if "_|WARNING:" in ck:
            ck = ck[ck.index("_|WARNING:"):].strip()

        headers = {
            "Cookie": f".ROBLOSECURITY={ck}",
            "User-Agent": ua,
            "Accept": "application/json"
        }

        req = urllib.request.Request("https://users.roblox.com/v1/users/authenticated", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                uid = data.get("id")
                results[uname] = {"status": "ALIVE", "reason": f"Roblox Session Valid (id={uid})"}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if e.code == 401:
                results[uname] = {"status": "DEAD", "reason": "Cookie expired / not authenticated"}
            elif e.code == 403 and "moderated" in err_body.lower():
                moderated_users.append(uname)
            else:
                results[uname] = {"status": "DEAD" if e.code in (401, 403) else "ERROR", "reason": f"HTTP {e.code}: {err_body[:80]}"}
        except Exception as ex:
            results[uname] = {"status": "ERROR", "reason": str(ex)}

    if moderated_users:
        public_res = check_roblox_ban_status(moderated_users, use_cache=use_cache, cache_ttl=cache_ttl)
        for u in moderated_users:
            p_info = public_res.get(u, {})
            if p_info.get("isBanned") is True:
                results[u] = {"status": "BANNED", "reason": "Roblox Moderation: Account Banned"}
            else:
                results[u] = {"status": "FACE_LOCK", "reason": "Roblox Moderation: Checkpoint / FaceID Lock"}

    return results


def parse_acc_sections(acc_content):
    r"""
    Phân tích nội dung acc.txt thành dictionary các section dàn máy.
    Quy tắc nhận diện Section Header:
    - Bắt đầu bằng [Mm]\d+ theo sau là dấu gạch dưới, khoảng trắng, ngoặc đơn hoặc kết thúc chuỗi.
    - KHÔNG chứa dấu hai chấm ':' (loại trừ tuyệt đối Mega_Wiley623:pass, M00nlUWarden...:pass).
    - Hỗ trợ gộp trùng section (ví dụ nhiều header M0 trong cùng file).
    - Lưu vết các tài khoản unassigned ở đầu file vào section 'unassigned'.
    """
    sections = {}
    current_section = None
    unassigned_accounts = []
    lines = acc_content.splitlines()

    section_pattern = re.compile(r"^\s*([Mm]\d+)(?=[_(\s]|$)", re.IGNORECASE)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Kiểm tra xem có phải tiêu đề section (M77___(gag2), M109(gag2)____, M0___)
        m = section_pattern.match(stripped)
        if m and ":" not in stripped:
            raw_header = stripped
            norm_key = m.group(1).lower()
            if norm_key in sections:
                current_section = sections[norm_key]
            else:
                current_section = {
                    "raw_header": raw_header,
                    "norm_key": norm_key,
                    "accounts": []
                }
                sections[norm_key] = current_section
            continue

        # Nếu là dòng tài khoản (user:pass...)
        if ":" in stripped:
            parts = stripped.split(":")
            username = parts[0].strip()
            if username:
                acc_obj = {
                    "raw_line": line,
                    "username": username,
                    "password": parts[1].strip() if len(parts) > 1 else "",
                    "extra": ":".join(parts[2:]) if len(parts) > 2 else ""
                }
                if current_section is not None:
                    current_section["accounts"].append(acc_obj)
                else:
                    unassigned_accounts.append(acc_obj)

    if unassigned_accounts:
        sections["unassigned"] = {
            "raw_header": "UNASSIGNED",
            "norm_key": "unassigned",
            "accounts": unassigned_accounts
        }

    return sections


def query_roblox_api(url, method="GET", data=None, retries=3, backoff_factor=1.0):
    """
    Gửi request đến Roblox API kèm cơ chế thử lại exponential backoff và parse Retry-After chống 429.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    encoded_data = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        encoded_data = json.dumps(data).encode("utf-8")

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                # Rate limited: Đọc Retry-After header nếu có
                retry_after_hdr = e.headers.get("Retry-After") if hasattr(e, "headers") and e.headers else None
                wait_time = None
                if retry_after_hdr:
                    try:
                        wait_time = float(retry_after_hdr)
                    except (ValueError, TypeError):
                        wait_time = None
                if wait_time is None or wait_time <= 0:
                    wait_time = backoff_factor * (2.0 ** attempt)
                wait_time = min(max(wait_time, 0.1), 60.0)
                time.sleep(wait_time)
                continue
            if e.code == 404:
                return None
            if attempt == retries - 1:
                raise
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(backoff_factor * (2.0 ** attempt))
    return None


def check_roblox_ban_status(usernames, max_workers=5, use_cache=True, cache_ttl=DEFAULT_CACHE_TTL, pacing_delay=0.0):
    """
    Kiểm tra trạng thái Ban của danh sách usernames qua Roblox API v1.
    Có Quota-Guard TTL Cache (mặc định 300s) chống gọi trùng lặp và rate pacing.
    Trả về dict: {
        username: {
            "isBanned": bool | None,
            "id": int | None,
            "name": str,
            "error": str | None,
            "cached": bool
        }
    }
    """
    if not usernames:
        return {}

    results = {}
    unique_usernames = list(dict.fromkeys(usernames))

    # 1. Tra cứu Quota-Guard Cache
    now = time.time()
    uncached_usernames = []
    if use_cache:
        with _CACHE_LOCK:
            for u in unique_usernames:
                key = u.strip().lower()
                cached = _QUOTA_GUARD_CACHE.get(key)
                if cached and (now - cached.get("timestamp", 0) < cache_ttl):
                    cached_data = dict(cached["data"])
                    cached_data["cached"] = True
                    results[u] = cached_data
                else:
                    uncached_usernames.append(u)
    else:
        uncached_usernames = list(unique_usernames)

    if not uncached_usernames:
        return results

    # 2. Batch lấy User ID qua POST v1/usernames/users (tối đa 100 usernames/request)
    name_to_id = {}
    chunk_size = 100
    for i in range(0, len(uncached_usernames), chunk_size):
        chunk = uncached_usernames[i:i + chunk_size]
        payload = {"usernames": chunk, "excludeBannedUsers": False}
        try:
            resp = query_roblox_api(ROBLOX_BATCH_USERNAMES_URL, method="POST", data=payload)
            if resp and "data" in resp:
                for item in resp["data"]:
                    req_name = item.get("requestedUsername", "").lower()
                    target_id = item.get("id")
                    actual_name = item.get("name")
                    if target_id:
                        name_to_id[req_name] = (target_id, actual_name)
        except Exception as e:
            for u in chunk:
                results[u] = {"isBanned": None, "id": None, "name": u, "error": f"ID_LOOKUP_ERROR: {e}", "cached": False}

    # 3. Truy vấn chi tiết v1/users/{userId} để đọc trường isBanned
    def check_single_user(uname):
        if pacing_delay > 0:
            time.sleep(pacing_delay)
        uname_lower = uname.strip().lower()
        if uname_lower not in name_to_id:
            return uname, {"isBanned": None, "id": None, "name": uname, "error": "USER_NOT_FOUND", "cached": False}
        uid, real_name = name_to_id[uname_lower]
        try:
            detail_url = ROBLOX_USER_DETAIL_URL.format(userId=uid)
            detail = query_roblox_api(detail_url, method="GET")
            if detail:
                is_banned = bool(detail.get("isBanned", False))
                return uname, {"isBanned": is_banned, "id": uid, "name": real_name or uname, "error": None, "cached": False}
            return uname, {"isBanned": None, "id": uid, "name": uname, "error": "DETAIL_EMPTY", "cached": False}
        except Exception as e:
            return uname, {"isBanned": None, "id": uid, "name": uname, "error": str(e), "cached": False}

    users_to_fetch = [u for u in uncached_usernames if u not in results]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_single_user, u): u for u in users_to_fetch}
        for future in as_completed(futures):
            uname, res = future.result()
            results[uname] = res
            # Cập nhật Quota-Guard Cache
            if use_cache:
                with _CACHE_LOCK:
                    _QUOTA_GUARD_CACHE[uname.strip().lower()] = {
                        "data": {k: v for k, v in res.items() if k != "cached"},
                        "timestamp": time.time()
                    }

    return results


def pull_from_google_drive(base_dir=None, force=False) -> dict[str, str]:
    """
    Tự động kéo acc.txt và Data_Tong_Cookies.txt từ Google Drive về nếu tệp trên máy bị thiếu/rỗng hoặc cần làm mới.
    Chiến lược kép:
    1. HTTP Direct Download bằng File ID gốc (Hoạt động trên 100% môi trường Termux/Android không cần cài đặt rclone).
    2. Fallback qua rclone copyto nếu có cấu hình rclone.
    """
    paths = get_default_paths(base_dir)
    bdir = paths["base_dir"]
    os.makedirs(bdir, exist_ok=True)
    res = {}

    def _http_download(fid: str, target_file: str, name: str) -> bool:
        url = f"https://docs.google.com/uc?export=download&id={fid}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                # Kiểm tra nếu Google trả về trang cảnh báo virus / download_warning đối với file lớn
                if b"download_warning" in data or b"Google Drive - Virus scan warning" in data:
                    text_html = data.decode("utf-8", errors="ignore")
                    m = re.search(r'confirm=([^&"\'\s]+)', text_html)
                    if m:
                        confirm_token = m.group(1)
                        conf_url = f"{url}&confirm={confirm_token}"
                        req_conf = urllib.request.Request(conf_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req_conf, timeout=30) as resp_conf:
                            data = resp_conf.read()
                if len(data) > 0 and b"<!DOCTYPE html>" not in data[:100]:
                    temp_path = f"{target_file}.tmp_{int(time.time())}"
                    with open(temp_path, "wb") as f:
                        f.write(data)
                    os.replace(temp_path, target_file)
                    res[name] = f"PULLED_HTTP ({len(data)} bytes)"
                    return True
        except Exception as e:
            print(f"[PULL_GDRIVE] Lỗi HTTP tải {name}: {e}", flush=True)
        return False

    acc_f = paths["acc_file"]
    dt_f = paths["data_tong_file"]

    # 1. Kéo acc.txt
    need_acc = force or not os.path.exists(acc_f) or os.path.getsize(acc_f) == 0
    if need_acc:
        if not _http_download(RULE34_ACC_FILE_ID, acc_f, "acc.txt"):
            rclone_bin = shutil.which("rclone") or "/data/data/com.termux/files/usr/bin/rclone" or "/usr/bin/rclone" or "rclone"
            if shutil.which(rclone_bin) or os.path.exists(rclone_bin):
                try:
                    p = subprocess.run([rclone_bin, "copyto", "gdrive:acc.txt", acc_f], capture_output=True, text=True, timeout=30)
                    res["acc.txt"] = "PULLED_RCLONE" if p.returncode == 0 else f"ERR: {p.stderr[:80]}"
                except Exception as e:
                    res["acc.txt"] = f"ERR: {e}"

    # 2. Kéo Data_Tong_Cookies.txt
    need_dt = force or not os.path.exists(dt_f) or os.path.getsize(dt_f) == 0
    if need_dt:
        if not _http_download(RULE34_DATA_TONG_FILE_ID, dt_f, "Data_Tong_Cookies.txt"):
            rclone_bin = shutil.which("rclone") or "/data/data/com.termux/files/usr/bin/rclone" or "/usr/bin/rclone" or "rclone"
            if shutil.which(rclone_bin) or os.path.exists(rclone_bin):
                try:
                    p2 = subprocess.run([rclone_bin, "copyto", "gdrive:Data_Tong_Cookies.txt", dt_f], capture_output=True, text=True, timeout=30)
                    res["Data_Tong_Cookies.txt"] = "PULLED_RCLONE" if p2.returncode == 0 else f"ERR: {p2.stderr[:80]}"
                except Exception as e:
                    res["Data_Tong_Cookies.txt"] = f"ERR: {e}"

    # 3. Kéo kho tài khoản dự trữ (acc_khong_trung_moi.txt / acc_du_phong.txt)
    res_f = paths.get("acc_du_phong_file", os.path.join(bdir, "acc_du_phong.txt"))
    alt_res_f = os.path.join(bdir, "acc_khong_trung_moi.txt")
    has_res = (os.path.exists(res_f) and os.path.getsize(res_f) > 0) or (os.path.exists(alt_res_f) and os.path.getsize(alt_res_f) > 0)
    if force or not has_res:
        target_res_save = alt_res_f
        if not _http_download(RULE34_ACC_RESERVE_FILE_ID, target_res_save, "acc_khong_trung_moi.txt"):
            rclone_bin = shutil.which("rclone") or "/data/data/com.termux/files/usr/bin/rclone" or "/usr/bin/rclone" or "rclone"
            if shutil.which(rclone_bin) or os.path.exists(rclone_bin):
                try:
                    p3 = subprocess.run([rclone_bin, "copyto", "gdrive:acc_khong_trung_moi.txt", target_res_save], capture_output=True, text=True, timeout=30)
                    res["acc_khong_trung_moi.txt"] = "PULLED_RCLONE" if p3.returncode == 0 else f"ERR: {p3.stderr[:80]}"
                except Exception as e:
                    res["acc_khong_trung_moi.txt"] = f"ERR: {e}"
        # Đảm bảo nếu acc_du_phong.txt chưa có thì sao chép sang để đồng bộ tên
        if os.path.exists(target_res_save) and os.path.getsize(target_res_save) > 0 and (not os.path.exists(res_f) or os.path.getsize(res_f) == 0):
            try:
                shutil.copy2(target_res_save, res_f)
            except Exception:
                pass

    return res


def clean_banned_accounts(m_code_or_target, banned_usernames, base_dir=None, categories_map=None):
    """
    Xóa các tài khoản bị ban/lỗi khỏi acc.txt và Data_Tong_Cookies.txt,
    đồng thời sao lưu .bak_<timestamp> cho CẢ HAI tệp và lưu trữ vào các tệp phân loại tương ứng:
    - BANNED -> acc_bi_ban.txt (nhat_ky_ban.txt)
    - FACE_LOCK -> acc_face_lock.txt (nhat_ky_face_lock.txt, ghi Face_Target_File.txt)
    - CAPTCHA_LOCK -> acc_captcha_lock.txt (nhat_ky_captcha_lock.txt)
    - DEAD -> acc_dead_cookies.txt
    Hỗ trợ target là mã máy (m77), 'all', 'unassigned' hoặc danh sách username rời.
    Trả về dict: {
        "banned_count": int,
        "removed_from_acc": int,
        "archived_cookies_count": int,
        "backup_acc": str,
        "backup_data_tong": str,
        "removed_per_section": dict
    }
    """
    paths = get_default_paths(base_dir)
    acc_file = paths["acc_file"]
    data_tong_file = paths["data_tong_file"]
    acc_bi_ban_file = paths["acc_bi_ban_file"]
    acc_face_lock_file = paths["acc_face_lock_file"]
    acc_captcha_lock_file = paths["acc_captcha_lock_file"]
    acc_dead_cookies_file = paths["acc_dead_cookies_file"]
    nhat_ky_ban_file = paths["nhat_ky_ban_file"]
    nhat_ky_face_lock_file = paths["nhat_ky_face_lock_file"]
    nhat_ky_captcha_lock_file = paths["nhat_ky_captcha_lock_file"]
    face_target_file = paths["face_target_file"]

    if not os.path.exists(acc_file):
        raise FileNotFoundError(f"Không tìm thấy tệp: {acc_file}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_str = datetime.now().strftime("%d/%m")

    # 1. Tạo bản sao lưu an toàn cho CẢ HAI tệp
    backup_acc = f"{acc_file}.bak_{timestamp}"
    shutil.copy2(acc_file, backup_acc)
    backup_data_tong = None
    if os.path.exists(data_tong_file):
        backup_data_tong = f"{data_tong_file}.bak_{timestamp}"
        shutil.copy2(data_tong_file, backup_data_tong)

    banned_set = {u.strip().lower() for u in banned_usernames if u.strip()}
    cat_map = {k.strip().lower(): str(v).upper() for k, v in (categories_map or {}).items()}

    # 2. Xử lý trích xuất lưu trữ từ Data_Tong_Cookies.txt theo từng nhóm
    archived_full_lines = []
    archived_by_category = {"BANNED": [], "FACE_LOCK": [], "CAPTCHA_LOCK": [], "DEAD": []}
    cleaned_data_tong_lines = []
    if os.path.exists(data_tong_file):
        with open(data_tong_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                user = line_str.split(":")[0].strip().lower()
                if user in banned_set:
                    archived_full_lines.append(line_str)
                    user_cat = cat_map.get(user, "BANNED")
                    if user_cat not in archived_by_category:
                        user_cat = "BANNED"
                    archived_by_category[user_cat].append(line_str)
                else:
                    cleaned_data_tong_lines.append(line_str)

        with open(data_tong_file, "w", encoding="utf-8") as f:
            f.write("\n".join(cleaned_data_tong_lines) + ("\n" if cleaned_data_tong_lines else ""))

    # 3. Ghi vào các tệp phân loại
    target_str = str(m_code_or_target or "Tự do").strip()
    if re.match(r"^[Mm]\d+$", target_str, re.IGNORECASE):
        m_clean = target_str.upper().replace("M", "Máy ")
    elif target_str.lower() == "all":
        m_clean = "Toàn bộ"
    else:
        m_clean = "Tự do"

    # 3a. Banned
    banned_lines = archived_by_category["BANNED"]
    if banned_lines or any(cat_map.get(u.lower(), "BANNED") == "BANNED" for u in banned_usernames):
        if banned_lines:
            with open(acc_bi_ban_file, "a", encoding="utf-8") as f:
                for l in banned_lines:
                    f.write(l + "\n")
        with open(nhat_ky_ban_file, "a", encoding="utf-8") as f:
            for u in banned_usernames:
                if cat_map.get(u.lower(), "BANNED") == "BANNED":
                    f.write(f"{u}:::banned {date_str} - {m_clean}\n")

    # 3b. Face Lock
    face_lines = archived_by_category["FACE_LOCK"]
    if face_lines or any(cat_map.get(u.lower()) == "FACE_LOCK" for u in banned_usernames):
        if face_lines:
            with open(acc_face_lock_file, "a", encoding="utf-8") as f:
                for l in face_lines:
                    f.write(l + "\n")
            try:
                with open(face_target_file, "w", encoding="utf-8") as f:
                    f.write(acc_face_lock_file + "\n")
            except Exception:
                pass
        with open(nhat_ky_face_lock_file, "a", encoding="utf-8") as f:
            for u in banned_usernames:
                if cat_map.get(u.lower()) == "FACE_LOCK":
                    f.write(f"{u}:::facelock {date_str} - {m_clean}\n")

    # 3c. Captcha Lock
    captcha_lines = archived_by_category["CAPTCHA_LOCK"]
    if captcha_lines or any(cat_map.get(u.lower()) == "CAPTCHA_LOCK" for u in banned_usernames):
        if captcha_lines:
            with open(acc_captcha_lock_file, "a", encoding="utf-8") as f:
                for l in captcha_lines:
                    f.write(l + "\n")
        with open(nhat_ky_captcha_lock_file, "a", encoding="utf-8") as f:
            for u in banned_usernames:
                if cat_map.get(u.lower()) == "CAPTCHA_LOCK":
                    f.write(f"{u}:::captchalock {date_str} - {m_clean}\n")

    # 3d. Dead Cookies
    dead_lines = archived_by_category["DEAD"]
    if dead_lines:
        with open(acc_dead_cookies_file, "a", encoding="utf-8") as f:
            for l in dead_lines:
                f.write(l + "\n")

    # 5. Làm sạch acc.txt
    with open(acc_file, "r", encoding="utf-8", errors="ignore") as f:
        old_acc_content = f.read()

    new_acc_lines = []
    section_pattern = re.compile(r"^\s*([Mm]\d+)(?:[_\s(].*)?$", re.IGNORECASE)
    norm_target = target_str.lower()
    is_single_m = bool(re.match(r"^[Mm]\d+$", norm_target))

    current_sec_code = "unassigned"
    removed_from_acc = 0
    removed_per_section = {}

    for line in old_acc_content.splitlines():
        stripped = line.strip()
        m = section_pattern.match(stripped)
        if m and ":" not in stripped:
            current_sec_code = m.group(1).lower()
            new_acc_lines.append(line)
            continue

        if ":" in stripped:
            user = stripped.split(":")[0].strip().lower()
            # Kiểm tra xem dòng này có thuộc phạm vi dọn dẹp không
            should_check = False
            if is_single_m:
                should_check = (current_sec_code == norm_target)
            elif norm_target == "unassigned":
                should_check = (current_sec_code == "unassigned")
            else:
                # "all" hoặc danh sách username rời -> dọn dẹp trên toàn bộ tệp
                should_check = True

            if should_check and user in banned_set:
                removed_from_acc += 1
                removed_per_section[current_sec_code] = removed_per_section.get(current_sec_code, 0) + 1
                continue

        new_acc_lines.append(line)

    with open(acc_file, "w", encoding="utf-8") as f:
        f.write("\n".join(new_acc_lines) + "\n")

    return {
        "banned_count": len(banned_usernames),
        "removed_from_acc": removed_from_acc,
        "archived_cookies_count": len(archived_full_lines),
        "backup_acc": backup_acc,
        "backup_data_tong": backup_data_tong,
        "removed_per_section": removed_per_section,
    }


def add_accounts(m_code, new_acc_lines, base_dir=None):
    """
    Nạp bù tài khoản mới vào đúng section của máy trong acc.txt.
    Tạo bản sao lưu .bak_<timestamp> cho CẢ HAI tệp trước khi ghi.
    Nếu có cookie kèm theo, bổ sung vào Data_Tong_Cookies.txt.
    """
    paths = get_default_paths(base_dir)
    acc_file = paths["acc_file"]
    data_tong_file = paths["data_tong_file"]

    if not os.path.exists(acc_file):
        raise FileNotFoundError(f"Không tìm thấy tệp: {acc_file}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_acc = f"{acc_file}.bak_{timestamp}"
    shutil.copy2(acc_file, backup_acc)
    backup_data_tong = None
    if os.path.exists(data_tong_file):
        backup_data_tong = f"{data_tong_file}.bak_{timestamp}"
        shutil.copy2(data_tong_file, backup_data_tong)

    norm_m_code = m_code.lower().strip()
    with open(acc_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()

    section_pattern = re.compile(r"^\s*([Mm]\d+)(?:[_\s(].*)?$", re.IGNORECASE)
    out_lines = []
    inserted = False
    section_found = False

    # Lọc danh sách dòng mới hợp lệ
    valid_new_lines = []
    cookie_entries = []
    for line in new_acc_lines:
        line_str = line.strip()
        if not line_str or ":" not in line_str:
            continue
        parts = line_str.split(":")
        user = parts[0].strip()
        pwd = parts[1].strip() if len(parts) > 1 else ""
        valid_new_lines.append(f"{user}:{pwd}")
        if len(parts) >= 3 and "_|WARNING" in line_str:
            cookie_entries.append(line_str)

    if not valid_new_lines:
        raise ValueError("Không có dòng tài khoản hợp lệ (định dạng user:pass hoặc user:pass:cookie).")

    for i, line in enumerate(lines):
        stripped = line.strip()
        m = section_pattern.match(stripped)
        if m and ":" not in stripped:
            curr_code = m.group(1).lower()
            if curr_code == norm_m_code:
                section_found = True
            elif section_found and not inserted:
                # Đã duyệt qua hết các acc của section mục tiêu, chèn các acc mới vào đây
                while out_lines and not out_lines[-1].strip():
                    out_lines.pop()
                for nl in valid_new_lines:
                    out_lines.append(nl)
                out_lines.append("")
                inserted = True

        out_lines.append(line)

    # Nếu section nằm ở cuối file mà chưa chèn
    if section_found and not inserted:
        while out_lines and not out_lines[-1].strip():
            out_lines.pop()
        for nl in valid_new_lines:
            out_lines.append(nl)
        inserted = True

    # Nếu chưa có section này, tạo mới section ở cuối
    if not section_found:
        if out_lines and out_lines[-1].strip():
            out_lines.append("")
        out_lines.append(f"{m_code.upper()}___(gag2)")
        for nl in valid_new_lines:
            out_lines.append(nl)

    with open(acc_file, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")

    # Nếu có cookie, bổ sung vào Data_Tong_Cookies.txt
    if cookie_entries and os.path.exists(data_tong_file):
        with open(data_tong_file, "a", encoding="utf-8") as f:
            for ce in cookie_entries:
                f.write(ce + "\n")

    return {
        "m_code": m_code.upper(),
        "added_count": len(valid_new_lines),
        "cookies_added": len(cookie_entries),
        "backup_acc": backup_acc,
        "backup_data_tong": backup_data_tong,
    }


def delete_accounts(m_code_or_target, usernames, base_dir=None, sync_drive=True):
    """
    Xóa danh sách tài khoản chỉ định khỏi acc.txt và Data_Tong_Cookies.txt.
    - m_code_or_target: mã máy (m77), 'all' hoặc tên section.
    - usernames: danh sách username cần xóa.
    - Tạo bản sao lưu .bak_<timestamp> trước khi xóa.
    - Đồng bộ lên Google Drive (Rule 34) nếu sync_drive=True.
    """
    paths = get_default_paths(base_dir)
    acc_file = paths["acc_file"]
    data_tong_file = paths["data_tong_file"]

    if not os.path.exists(acc_file):
        pull_from_google_drive(base_dir, force=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_acc = f"{acc_file}.bak_{timestamp}"
    shutil.copy2(acc_file, backup_acc)
    backup_data_tong = None
    if os.path.exists(data_tong_file):
        backup_data_tong = f"{data_tong_file}.bak_{timestamp}"
        shutil.copy2(data_tong_file, backup_data_tong)

    del_set = {u.strip().lower() for u in usernames if u.strip()}
    if not del_set:
        return {
            "target": str(m_code_or_target or "ALL").upper(),
            "deleted_count": 0,
            "deleted_usernames": [],
            "removed_from_acc": 0,
            "removed_from_data_tong": 0,
            "sync_result": None
        }

    # 1. Xóa khỏi Data_Tong_Cookies.txt
    removed_from_data_tong = 0
    if os.path.exists(data_tong_file):
        cleaned_dt = []
        with open(data_tong_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                stripped = line.strip()
                if not stripped or ":" not in stripped:
                    continue
                user = stripped.split(":")[0].strip().lower()
                if user in del_set:
                    removed_from_data_tong += 1
                else:
                    cleaned_dt.append(stripped)
        with open(data_tong_file, "w", encoding="utf-8") as f:
            f.write("\n".join(cleaned_dt) + ("\n" if cleaned_dt else ""))

    # 2. Xóa khỏi acc.txt
    target_str = str(m_code_or_target or "all").strip().lower()
    is_single_m = bool(re.match(r"^[Mm]\d+$", target_str))
    section_pattern = re.compile(r"^\s*([Mm]\d+)(?:[_\s(].*)?$", re.IGNORECASE)

    current_sec_code = "unassigned"
    removed_from_acc = 0
    new_acc_lines = []

    with open(acc_file, "r", encoding="utf-8", errors="ignore") as f:
        acc_text = f.read()

    for line in acc_text.splitlines():
        stripped = line.strip()
        m = section_pattern.match(stripped)
        if m and ":" not in stripped:
            current_sec_code = m.group(1).lower()
            new_acc_lines.append(line)
            continue

        if ":" in stripped and not stripped.endswith(")") and not stripped.startswith("["):
            user = stripped.split(":")[0].strip().lower()
            should_check = False
            if is_single_m:
                should_check = (current_sec_code == target_str)
            else:
                should_check = True

            if should_check and user in del_set:
                removed_from_acc += 1
                continue

        new_acc_lines.append(line)

    with open(acc_file, "w", encoding="utf-8") as f:
        f.write("\n".join(new_acc_lines) + ("\n" if new_acc_lines else ""))

    sync_res = None
    if sync_drive:
        try:
            sync_res = sync_to_google_drive(base_dir=base_dir)
        except Exception as e:
            sync_res = {"error": str(e)}

    return {
        "target": target_str.upper(),
        "deleted_count": len(del_set),
        "deleted_usernames": list(del_set),
        "removed_from_acc": removed_from_acc,
        "removed_from_data_tong": removed_from_data_tong,
        "backup_acc": backup_acc,
        "backup_data_tong": backup_data_tong,
        "sync_result": sync_res
    }


def move_accounts(source_m, target_m, count=1, base_dir=None, sync_drive=True):
    """
    Điều chuyển ngẫu nhiên N tài khoản từ dàn máy nguồn sang dàn máy đích trong acc.txt.
    - source_m: Mã máy nguồn (ví dụ 'm109', 'M109').
    - target_m: Mã máy đích (ví dụ 'm77', 'M77').
    - count: Số lượng tài khoản bốc ngẫu nhiên (mặc định 1).
    - base_dir: Thư mục chứa các tệp (mặc định get_default_paths()).
    - sync_drive: Đồng bộ Google Drive in-place qua rclone copyto (chỉ sync acc.txt, Rule 34).
    
    Quy tắc nghiệp vụ:
    - Bốc ngẫu nhiên bằng random.sample.
    - Cắt khỏi section nguồn và chèn vào section đích trong acc.txt.
    - Nếu section đích chưa tồn tại, tự động tạo mới header '{TARGET_M}___(gag2)' ở cuối tệp.
    - Tuyệt đối KHÔNG can thiệp, sửa đổi hay tạo backup cho Data_Tong_Cookies.txt.
    - Tạo bản sao lưu .bak_<timestamp> cho acc.txt trước khi sửa đổi.
    - Giữ nguyên File ID gốc của acc.txt (12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg) theo Rule 34.
    """
    if not source_m or not target_m:
        raise ValueError("Mã máy nguồn và máy đích không được để trống.")

    src_norm = str(source_m).strip().upper()
    dst_norm = str(target_m).strip().upper()
    src_key = src_norm.lower()
    dst_key = dst_norm.lower()

    if src_norm == dst_norm:
        raise ValueError("Mã máy nguồn và máy đích không được trùng nhau.")

    try:
        count = int(count)
    except (ValueError, TypeError):
        raise ValueError("Số lượng tài khoản chuyển phải lớn hơn hoặc bằng 1.")

    if count < 1:
        raise ValueError("Số lượng tài khoản chuyển phải lớn hơn hoặc bằng 1.")

    paths = get_default_paths(base_dir)
    acc_file = paths["acc_file"]

    # Đảm bảo tệp acc.txt tồn tại
    if not os.path.exists(acc_file):
        try:
            pull_from_google_drive(base_dir=base_dir, force=True)
        except Exception:
            pass

    if not os.path.exists(acc_file):
        raise FileNotFoundError(f"Không tìm thấy tệp: {acc_file}")

    with open(acc_file, "r", encoding="utf-8", errors="ignore") as f:
        old_content = f.read()

    sections = parse_acc_sections(old_content)
    if src_key not in sections:
        raise ValueError(f"Không tìm thấy section máy nguồn {src_norm} trong acc.txt.")

    src_accounts = sections[src_key]["accounts"]
    total_src_before = len(src_accounts)
    if total_src_before == 0:
        raise ValueError(f"Dàn máy nguồn {src_norm} không còn tài khoản nào.")

    if count > total_src_before:
        raise ValueError(f"Dàn máy nguồn {src_norm} chỉ có {total_src_before} tài khoản, không đủ {count} tài khoản để chuyển.")

    # Bốc ngẫu nhiên bằng random.sample
    selected_objects = random.sample(src_accounts, count)
    selected_usernames = [a["username"] for a in selected_objects]
    selected_lines = [a["raw_line"].strip() for a in selected_objects]

    # Tạo bản sao lưu cục bộ cho acc.txt trước khi sửa đổi
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_acc = f"{acc_file}.bak_{timestamp}"
    shutil.copy2(acc_file, backup_acc)

    # Đếm số lượng cần cắt cho từng username
    to_cut_counts = {}
    for a in selected_objects:
        u = a["username"].strip().lower()
        to_cut_counts[u] = to_cut_counts.get(u, 0) + 1

    # Precision regex nhận diện section ranh giới
    src_boundary_pattern = re.compile(rf"^\s*{re.escape(src_norm)}(?=[_(\s]|$)", re.IGNORECASE)
    dst_boundary_pattern = re.compile(rf"^\s*{re.escape(dst_norm)}(?=[_(\s]|$)", re.IGNORECASE)
    section_ident_pattern = re.compile(r"^\s*([Mm]\d+)(?=[_(\s]|$)", re.IGNORECASE)

    lines = old_content.splitlines()
    out_lines = []
    current_sec = "unassigned"
    dst_found = False
    dst_inserted = False

    for line in lines:
        stripped = line.strip()

        # Kiểm tra tiêu đề section (bắt buộc KHÔNG chứa ':')
        if ":" not in stripped:
            matched_code = None
            if src_boundary_pattern.match(stripped):
                matched_code = src_key
            elif dst_boundary_pattern.match(stripped):
                matched_code = dst_key
                dst_found = True
            else:
                m_sec = section_ident_pattern.match(stripped)
                if m_sec:
                    matched_code = m_sec.group(1).lower()

            if matched_code is not None:
                # Nếu trước đó đang trong section đích và chuẩn bị sang section khác:
                # Chèn các tài khoản chuyển vào cuối section đích
                if current_sec == dst_key and not dst_inserted:
                    while out_lines and not out_lines[-1].strip():
                        out_lines.pop()
                    for sl in selected_lines:
                        out_lines.append(sl)
                    out_lines.append("")
                    dst_inserted = True

                current_sec = matched_code
                out_lines.append(line)
                continue

        # Cắt tài khoản được chọn khỏi section nguồn
        if ":" in stripped and current_sec == src_key:
            user = stripped.split(":")[0].strip().lower()
            if to_cut_counts.get(user, 0) > 0:
                to_cut_counts[user] -= 1
                continue  # Bỏ qua dòng này (cắt khỏi nguồn)

        out_lines.append(line)

    # Nếu section đích nằm ở cuối tệp
    if dst_found and not dst_inserted:
        while out_lines and not out_lines[-1].strip():
            out_lines.pop()
        for sl in selected_lines:
            out_lines.append(sl)
        dst_inserted = True

    # Nếu section đích chưa từng có trong file: tự động tạo mới header ở cuối
    if not dst_found:
        while out_lines and not out_lines[-1].strip():
            out_lines.pop()
        if out_lines:
            out_lines.append("")
        out_lines.append(f"{dst_norm}___(gag2)")
        for sl in selected_lines:
            out_lines.append(sl)
        dst_inserted = True

    # Ghi lại acc.txt
    new_acc_content = "\n".join(out_lines) + "\n"
    with open(acc_file, "w", encoding="utf-8") as f:
        f.write(new_acc_content)

    # Tính toán thống kê
    dst_accounts_before = len(sections[dst_key]["accounts"]) if dst_key in sections else 0
    source_remaining_count = total_src_before - count
    target_current_count = dst_accounts_before + count

    # Đồng bộ Google Drive nếu được yêu cầu (chỉ sync acc.txt, Rule 34)
    sync_result = None
    if sync_drive:
        try:
            sync_result = sync_to_google_drive(base_dir=base_dir, sync_data_tong=False)
        except Exception as e:
            sync_result = {"error": str(e), "acc_sync": False, "rule34_verified": False}

    return {
        "source_m": src_norm,
        "target_m": dst_norm,
        "count": count,
        "moved_accounts": selected_usernames,
        "source_remaining_count": source_remaining_count,
        "target_current_count": target_current_count,
        "backup_acc": backup_acc,
        "sync_result": sync_result
    }


def replace_banned_accounts_from_reserve(m_code, num_needed, base_dir=None, reserve_accounts=None, sync_drive=False):
    """
    Tự động đọc tài khoản từ kho dự trữ acc_du_phong.txt (hoặc qua tham số reserve_accounts),
    nạp vào đúng section máy trong acc.txt, cập nhật Data_Tong_Cookies.txt và cập nhật acc_du_phong.txt.
    """
    if num_needed <= 0:
        return {
            "m_code": m_code.upper(),
            "replaced_count": 0,
            "replaced_accounts": [],
            "remaining_reserve_count": 0,
        }

    paths = get_default_paths(base_dir)
    acc_du_phong_file = paths["acc_du_phong_file"]

    selected_replacements = []
    remaining_reserve_lines = []

    if reserve_accounts is not None:
        selected_replacements = reserve_accounts[:num_needed]
        remaining_reserve_lines = reserve_accounts[num_needed:]
    else:
        # Hỗ trợ cả acc_du_phong.txt và acc_khong_trung_moi.txt
        res_file = acc_du_phong_file
        if not os.path.exists(res_file) or os.path.getsize(res_file) == 0:
            alt_res = os.path.join(paths["base_dir"], "acc_khong_trung_moi.txt")
            if os.path.exists(alt_res) and os.path.getsize(alt_res) > 0:
                res_file = alt_res

        if os.path.exists(res_file) and os.path.getsize(res_file) > 0:
            with open(res_file, "r", encoding="utf-8", errors="ignore") as f:
                raw_lines = f.read().splitlines()

            # Lấy danh sách các tài khoản đã bị cách ly trước đó (FaceID, Ban, Dead, Captcha)
            # để đảm bảo không bao giờ nạp lại một acc đang lỗi vào dàn máy
            defective_known = set()
            for k in ["acc_bi_ban_file", "acc_face_lock_file", "acc_dead_cookies_file", "acc_captcha_lock_file"]:
                fpath = paths.get(k)
                if fpath and os.path.exists(fpath):
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as df:
                        for l in df:
                            if ":" in l:
                                defective_known.add(l.strip().split(":")[0].strip().lower())

            valid_pool = []
            non_acc_lines = []
            for line in raw_lines:
                stripped = line.strip()
                if stripped and ":" in stripped:
                    u_cand = stripped.split(":")[0].strip().lower()
                    if u_cand not in defective_known:
                        valid_pool.append(line)
                    else:
                        non_acc_lines.append(line)
                elif stripped:
                    non_acc_lines.append(line)

            selected_replacements = valid_pool[:num_needed]
            remaining_valid = valid_pool[num_needed:]

            # Tạo bản sao lưu kho dự trữ
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(res_file, f"{res_file}.bak_{timestamp}")

            # Cập nhật lại kho dự trữ
            with open(res_file, "w", encoding="utf-8") as f:
                all_remain = remaining_valid + non_acc_lines
                f.write("\n".join(all_remain) + ("\n" if all_remain else ""))

            remaining_reserve_lines = remaining_valid

    if not selected_replacements:
        return {
            "m_code": m_code.upper(),
            "replaced_count": 0,
            "replaced_accounts": [],
            "remaining_reserve_count": len(remaining_reserve_lines),
        }

    # Nạp bù vào dàn máy
    add_accounts(m_code, selected_replacements, base_dir=base_dir)

    # Đồng bộ Google Drive nếu được yêu cầu
    if sync_drive:
        sync_to_google_drive(base_dir=base_dir)

    replaced_usernames = [l.strip().split(":")[0].strip() for l in selected_replacements if ":" in l]

    return {
        "m_code": m_code.upper(),
        "replaced_count": len(selected_replacements),
        "replaced_accounts": replaced_usernames,
        "remaining_reserve_count": len(remaining_reserve_lines),
    }


def verify_google_drive_file_ids(rclone_bin=None, check_data_tong=True):
    """
    Xác thực File ID của acc.txt (và Data_Tong_Cookies.txt nếu check_data_tong=True) trên Google Drive theo Rule 34.
    File ID acc.txt: 12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg
    File ID Data_Tong_Cookies.txt: 1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B
    """
    bin_path = rclone_bin or shutil.which("rclone") or "/usr/bin/rclone"
    file_ids = {}
    fnames = ["acc.txt", "Data_Tong_Cookies.txt"] if check_data_tong else ["acc.txt"]
    for fname in fnames:
        cmd = [bin_path, "lsf", f"gdrive:{fname}", "--format", "ip"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    line_str = line.strip()
                    if ";" in line_str:
                        parts = line_str.split(";")
                        file_ids[parts[1].strip()] = parts[0].strip()
        except Exception:
            pass

        if fname not in file_ids:
            try:
                cmd_json = [bin_path, "lsjson", f"gdrive:{fname}"]
                proc_j = subprocess.run(cmd_json, capture_output=True, text=True, timeout=90)
                if proc_j.returncode == 0:
                    import json
                    items = json.loads(proc_j.stdout)
                    if isinstance(items, list) and len(items) > 0 and "ID" in items[0]:
                        file_ids[fname] = items[0]["ID"]
            except Exception:
                pass

    # Kiểm tra bảo toàn tuyệt đối File ID (Rule 34)
    if "acc.txt" in file_ids and file_ids["acc.txt"] != RULE34_ACC_FILE_ID:
        raise RuntimeError(
            f"Rule 34 Violated! acc.txt File ID bị biến động: {file_ids['acc.txt']} != {RULE34_ACC_FILE_ID}"
        )
    if check_data_tong and "Data_Tong_Cookies.txt" in file_ids and file_ids["Data_Tong_Cookies.txt"] != RULE34_DATA_TONG_FILE_ID:
        raise RuntimeError(
            f"Rule 34 Violated! Data_Tong_Cookies.txt File ID bị biến động: {file_ids['Data_Tong_Cookies.txt']} != {RULE34_DATA_TONG_FILE_ID}"
        )

    return {"verified": True, "file_ids": file_ids}


def sync_to_google_drive(base_dir=None, verify_rule34=True, sync_data_tong=True):
    """
    Đồng bộ trực tiếp acc.txt (và Data_Tong_Cookies.txt nếu sync_data_tong=True) lên Google Drive qua rclone copyto.
    Bảo toàn 100% File ID gốc theo Rule 34 (Hard Rule) và có cổng xác thực verify_rule34.
    """
    paths = get_default_paths(base_dir)
    acc_file = paths["acc_file"]
    data_tong_file = paths["data_tong_file"]

    rclone_bin = shutil.which("rclone") or "/usr/bin/rclone"
    if not os.path.exists(rclone_bin):
        raise RuntimeError("Không tìm thấy công cụ rclone trên hệ thống để đồng bộ Google Drive.")

    sync_results = {
        "acc.txt": "NOT_FOUND",
        "Data_Tong_Cookies.txt": "SKIPPED" if not sync_data_tong else "NOT_FOUND",
        "acc_sync": False,
        "data_tong_sync": False,
        "rule34_verified": False,
        "file_ids": {},
    }

    if os.path.exists(acc_file):
        cmd = [rclone_bin, "copyto", acc_file, "gdrive:acc.txt"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Lỗi rclone acc.txt: {proc.stderr.strip() or proc.stdout.strip()}")
        sync_results["acc.txt"] = "OK"
        sync_results["acc_sync"] = True

    if sync_data_tong and os.path.exists(data_tong_file):
        cmd = [rclone_bin, "copyto", data_tong_file, "gdrive:Data_Tong_Cookies.txt"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Lỗi rclone Data_Tong_Cookies.txt: {proc.stderr.strip() or proc.stdout.strip()}")
        sync_results["Data_Tong_Cookies.txt"] = "OK"
        sync_results["data_tong_sync"] = True

    if verify_rule34:
        v_res = verify_google_drive_file_ids(rclone_bin, check_data_tong=sync_data_tong)
        sync_results["rule34_verified"] = v_res.get("verified", False)
        sync_results["file_ids"] = v_res.get("file_ids", {})

    return sync_results


def run_full_checkban_pipeline(target, base_dir=None, auto_replace=True, use_cache=True, cache_ttl=DEFAULT_CACHE_TTL, use_zeropoint=True, pull_drive=True):
    """
    Thực hiện trọn gói pipeline checkban:
    1. Trích xuất danh sách tài khoản theo target (m77, all, unassigned hoặc danh sách usernames).
    2. Luôn tự động kéo bản mới nhất từ Google Drive (Rule 34 Dual-Storage) ở môi trường production.
    3. Trích xuất cookie từ Data_Tong_Cookies.txt và gửi lên ZeroPoint CookieChecker API.
    4. Nhận diện chuyên sâu: Sống (ALIVE), Bị Ban (BANNED), FaceID Lock (FACE_LOCK), Captcha Lock (CAPTCHA_LOCK), Cookie Chết (DEAD).
       Đối với các acc không có cookie hoặc ZeroPoint không phản hồi, fallback về Roblox Public API.
    5. Chỉ xóa tài khoản BANNED khỏi dàn máy; giữ nguyên FaceID, Captcha, Dead.
    6. Tự động nạp bù từ kho acc_du_phong.txt nếu auto_replace=True.
    7. Đồng bộ Google Drive bảo toàn File ID theo Rule 34.
    8. Trả về báo cáo tổng hợp chi tiết và tệp phân loại gửi Telegram.
    """
    paths = get_default_paths(base_dir)
    acc_file = paths["acc_file"]
    data_tong_file = paths["data_tong_file"]

    usernames_to_check = []
    target_lower = target.strip().lower()
    is_single_m = bool(re.match(r"^[Mm]\d+$", target_lower))

    if target_lower == "all" or is_single_m or target_lower == "unassigned":
        # Ở môi trường production (base_dir is None), luôn kéo bản mới nhất từ Google Drive để đồng bộ fleet
        if pull_drive and (base_dir is None or not os.path.exists(acc_file) or os.path.getsize(acc_file) == 0):
            try:
                pull_from_google_drive(base_dir, force=(base_dir is None))
            except Exception as e:
                print(f"[CHECK_BAN] Cảnh báo pull Google Drive: {e}", flush=True)

        if not os.path.exists(acc_file):
            raise FileNotFoundError(f"Không tìm thấy file {acc_file}")
        with open(acc_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        sections = parse_acc_sections(content)

        if is_single_m and (target_lower not in sections or not sections[target_lower]["accounts"]):
            # Thử kéo lại từ Google Drive với force=True nếu file cục bộ chưa có section này
            pull_from_google_drive(base_dir, force=True)
            with open(acc_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            sections = parse_acc_sections(content)

        if target_lower == "all":
            for sec in sections.values():
                for acc in sec["accounts"]:
                    usernames_to_check.append(acc["username"])
        elif target_lower == "unassigned":
            sec = sections.get("unassigned")
            if not sec or not sec["accounts"]:
                return {
                    "target": "UNASSIGNED",
                    "total": 0,
                    "live": 0,
                    "banned": 0,
                    "face_lock": 0,
                    "captcha_lock": 0,
                    "dead": 0,
                    "error": 0,
                    "banned_list": [],
                    "message": "Không tìm thấy tài khoản unassigned nào."
                }
            for acc in sec["accounts"]:
                usernames_to_check.append(acc["username"])
        else:
            sec = sections.get(target_lower)
            if not sec or not sec["accounts"]:
                return {
                    "target": target.upper(),
                    "total": 0,
                    "live": 0,
                    "banned": 0,
                    "face_lock": 0,
                    "captcha_lock": 0,
                    "dead": 0,
                    "error": 0,
                    "banned_list": [],
                    "message": f"Không tìm thấy tài khoản nào trong dàn {target.upper()} trong acc.txt."
                }
            for acc in sec["accounts"]:
                usernames_to_check.append(acc["username"])
    else:
        # Target là danh sách username rời (phân tách bởi khoảng trắng hoặc dấu phẩy)
        usernames_to_check = [u.strip() for u in re.split(r"[\s,]+", target) if u.strip()]

    if not usernames_to_check:
        return {
            "target": target,
            "total": 0,
            "live": 0,
            "banned": 0,
            "face_lock": 0,
            "captcha_lock": 0,
            "dead": 0,
            "error": 0,
            "banned_list": [],
            "message": "Danh sách tài khoản trống."
        }

    # 2. Trích xuất mật khẩu và cookie từ acc.txt và Data_Tong_Cookies.txt
    user_pwd_map = {}
    if os.path.exists(acc_file):
        with open(acc_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                stripped = line.strip()
                if stripped and ":" in stripped and not stripped.endswith(")") and not stripped.startswith("["):
                    parts = stripped.split(":")
                    u = parts[0].strip().lower()
                    p = parts[1].strip() if len(parts) > 1 else ""
                    if u and u not in user_pwd_map:
                        user_pwd_map[u] = p

    user_cookie_map = {}
    if not os.path.exists(data_tong_file) or os.path.getsize(data_tong_file) == 0:
        pull_from_google_drive(base_dir, force=True)

    if os.path.exists(data_tong_file):
        with open(data_tong_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line_str = line.strip()
                if not line_str or ":" not in line_str:
                    continue
                parts = line_str.split(":")
                u_norm = parts[0].strip().lower()
                pwd_cand = parts[1].strip() if len(parts) > 1 else ""
                if pwd_cand and u_norm not in user_pwd_map:
                    user_pwd_map[u_norm] = pwd_cand
                c = ""
                if "_|WARNING:" in line_str:
                    c = line_str[line_str.index("_|WARNING:"):].strip()
                elif len(parts) > 2:
                    c = ":".join(parts[2:]).strip()
                elif len(parts) > 1 and ":" in parts[1]:
                    c = ":".join(parts[1].split(":")[1:]).strip()
                else:
                    c = parts[1].strip() if len(parts) > 1 else ""
                if c:
                    user_cookie_map[u_norm] = c

    # Nếu usernames_to_check không có cookie nào trong Data_Tong cục bộ, kéo lại từ Google Drive
    found_any = any(u.lower() in user_cookie_map for u in usernames_to_check)
    if not found_any and usernames_to_check:
        pull_from_google_drive(base_dir, force=True)
        if os.path.exists(data_tong_file):
            with open(data_tong_file, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str or ":" not in line_str:
                        continue
                    parts = line_str.split(":", 1)
                    u_norm = parts[0].strip().lower()
                    c = ""
                    if "_|WARNING:" in line_str:
                        c = line_str[line_str.index("_|WARNING:"):].strip()
                    elif len(parts) > 1 and ":" in parts[1]:
                        c = ":".join(parts[1].split(":")[1:]).strip()
                    else:
                        c = parts[1].strip() if len(parts) > 1 else ""
                    if c:
                        user_cookie_map[u_norm] = c

    # 3. Kiểm tra qua ZeroPoint CookieChecker API và Roblox Direct Cookie Authentication
    zp_input = {}
    for u in usernames_to_check:
        c = user_cookie_map.get(u.lower(), "")
        if c:
            zp_input[u] = c

    cookie_results = {}
    engine_name = None
    if use_zeropoint and zp_input:
        try:
            cookie_results = check_zeropoint_cookie_status(zp_input)
            if cookie_results:
                engine_name = "ZeroPoint"
        except Exception as e:
            print(f"[ZEROPOINT] Lỗi gọi API: {e}", flush=True)
            cookie_results = {}

    # Nếu ZeroPoint không trả kết quả (ví dụ Cloudflare 522/timeout), tự động fallback sang kiểm tra trực tiếp qua Roblox Cookie Auth
    missing_from_zp = {u: zp_input[u] for u in zp_input if u not in cookie_results}
    if missing_from_zp:
        try:
            rbx_results = check_roblox_cookie_status(missing_from_zp, use_cache=use_cache, cache_ttl=cache_ttl)
            for u, r_info in rbx_results.items():
                if u not in cookie_results:
                    cookie_results[u] = r_info
            if not engine_name:
                engine_name = "RobloxCookieAuth"
            elif engine_name == "ZeroPoint":
                engine_name = "ZeroPoint+RobloxAuth"
        except Exception as e:
            print(f"[ROBLOX_COOKIE] Lỗi kiểm tra cookie trực tiếp: {e}", flush=True)

    live_list = []
    banned_list = []
    face_lock_list = []
    captcha_lock_list = []
    dead_list = []
    error_list = []

    remaining_usernames = []
    for u in usernames_to_check:
        if u in cookie_results:
            st = cookie_results[u].get("status", "ALIVE").upper()
            if st == "ALIVE":
                live_list.append(u)
            elif st == "FACE_LOCK":
                face_lock_list.append(u)
            elif st == "CAPTCHA_LOCK":
                captcha_lock_list.append(u)
            elif st in ("BANNED", "BAN_WARN"):
                banned_list.append(u)
            elif st == "DEAD":
                dead_list.append(u)
            else:
                error_list.append(u)
        else:
            remaining_usernames.append(u)

    # Fallback kiểm tra Roblox Public API cho các tài khoản không có cookie
    if remaining_usernames:
        roblox_results = check_roblox_ban_status(remaining_usernames, use_cache=use_cache, cache_ttl=cache_ttl)
        for uname, info in roblox_results.items():
            if info.get("isBanned") is True:
                banned_list.append(uname)
            elif info.get("isBanned") is False:
                live_list.append(uname)
            else:
                error_list.append(uname)

    # 4. Chỉ xóa tài khoản BANNED khỏi acc.txt và Data_Tong_Cookies.txt
    # Tài khoản FACE_LOCK, CAPTCHA_LOCK, DEAD được giữ nguyên trong acc.txt và Data_Tong_Cookies.txt.
    # Toàn bộ trạng thái vẫn được gom vào category_entries để xuất file đính kèm gửi Telegram.
    clean_result = None
    replace_result = None
    sync_result = None

    if banned_list:
        clean_result = clean_banned_accounts(target, banned_list, base_dir=base_dir)

        # 5. Tự động nạp bù tài khoản từ kho dự trữ nếu được kích hoạt
        if auto_replace:
            if is_single_m and clean_result.get("removed_from_acc", 0) > 0:
                replace_result = replace_banned_accounts_from_reserve(
                    target_lower,
                    clean_result["removed_from_acc"],
                    base_dir=base_dir,
                    sync_drive=False
                )
            elif target_lower == "all" and clean_result.get("removed_per_section"):
                all_replaces = {"replaced_count": 0, "replaced_accounts": [], "by_section": {}}
                for sec_k, count in clean_result["removed_per_section"].items():
                    if sec_k != "unassigned" and count > 0:
                        sec_rep = replace_banned_accounts_from_reserve(
                            sec_k,
                            count,
                            base_dir=base_dir,
                            sync_drive=False
                        )
                        all_replaces["replaced_count"] += sec_rep["replaced_count"]
                        all_replaces["replaced_accounts"].extend(sec_rep["replaced_accounts"])
                        all_replaces["by_section"][sec_k] = sec_rep
                replace_result = all_replaces

        try:
            sync_result = sync_to_google_drive(base_dir=base_dir)
        except Exception as e:
            sync_result = {"error": str(e)}

    def _format_entry(uname):
        u_l = uname.lower()
        pwd = user_pwd_map.get(u_l, "")
        cookie = user_cookie_map.get(u_l, "")
        if cookie:
            return f"{uname}:{pwd}:{cookie}"
        elif pwd:
            return f"{uname}:{pwd}"
        return uname

    category_entries = {
        "live": [_format_entry(u) for u in live_list],
        "banned": [_format_entry(u) for u in banned_list],
        "face_lock": [_format_entry(u) for u in face_lock_list],
        "captcha_lock": [_format_entry(u) for u in captcha_lock_list],
        "dead": [_format_entry(u) for u in dead_list],
        "error": [_format_entry(u) for u in error_list],
    }

    return {
        "target": target.upper() if is_single_m else target,
        "total": len(usernames_to_check),
        "live": len(live_list),
        "banned": len(banned_list),
        "face_lock": len(face_lock_list),
        "captcha_lock": len(captcha_lock_list),
        "dead": len(dead_list),
        "error": len(error_list),
        "live_list": live_list,
        "banned_list": banned_list,
        "face_lock_list": face_lock_list,
        "captcha_lock_list": captcha_lock_list,
        "dead_list": dead_list,
        "error_list": error_list,
        "clean_result": clean_result,
        "replace_result": replace_result,
        "sync_result": sync_result,
        "category_entries": category_entries,
        "checker_engine": engine_name if cookie_results else "RobloxAPI",
    }


def write_cookie_to_package(package: str, cookie_value: str, base_data_dir: str = "/data/data") -> tuple[bool, str]:
    """
    Write .ROBLOSECURITY cookie into Chromium WebView Cookies SQLite database:
    {base_data_dir}/{package}/app_webview/Default/Cookies
    """
    if not package or not cookie_value:
        return False, "invalid_params"

    clean_cookie = cookie_value.strip()
    if "_|WARNING:" in clean_cookie:
        clean_cookie = clean_cookie[clean_cookie.index("_|WARNING:"):].strip()

    db_path = os.path.join(base_data_dir, package, "app_webview", "Default", "Cookies")
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    except Exception:
        pass

    # Try direct sqlite3 first
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cookies (
                creation_utc INTEGER NOT NULL,
                host_key TEXT NOT NULL,
                top_frame_site_key TEXT NOT NULL,
                name TEXT NOT NULL,
                value TEXT NOT NULL,
                encrypted_value BLOB NOT NULL,
                path TEXT NOT NULL,
                expires_utc INTEGER NOT NULL,
                is_secure INTEGER NOT NULL,
                is_httponly INTEGER NOT NULL,
                last_access_utc INTEGER NOT NULL,
                has_expires INTEGER NOT NULL,
                is_persistent INTEGER NOT NULL,
                priority INTEGER NOT NULL,
                samesite INTEGER NOT NULL,
                source_scheme INTEGER NOT NULL,
                source_port INTEGER NOT NULL,
                last_update_utc INTEGER NOT NULL,
                source_type INTEGER NOT NULL,
                has_cross_site_ancestor INTEGER NOT NULL
            )
        """)
        chrome_epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        now_chrome = int((now_utc - chrome_epoch).total_seconds() * 1_000_000)
        expires_chrome = int(((now_utc + timedelta(days=730)) - chrome_epoch).total_seconds() * 1_000_000)

        cursor.execute("SELECT COUNT(*) FROM cookies WHERE name = '.ROBLOSECURITY'")
        exists = cursor.fetchone()[0] > 0
        if exists:
            cursor.execute(
                "UPDATE cookies SET value = ?, last_access_utc = ?, last_update_utc = ? WHERE name = '.ROBLOSECURITY'",
                (clean_cookie, now_chrome, now_chrome)
            )
        else:
            cursor.execute("""
                INSERT INTO cookies (
                    creation_utc, host_key, top_frame_site_key, name, value, encrypted_value,
                    path, expires_utc, is_secure, is_httponly, last_access_utc, has_expires,
                    is_persistent, priority, samesite, source_scheme, source_port, last_update_utc,
                    source_type, has_cross_site_ancestor
                ) VALUES (?, '.roblox.com', '', '.ROBLOSECURITY', ?, X'', '/', ?, 1, 1, ?, 1, 1, 1, -1, 2, 443, ?, 0, 0)
            """, (now_chrome, clean_cookie, expires_chrome, now_chrome, now_chrome))
        conn.commit()
        conn.close()
        return True, "sqlite_success"
    except Exception as e:
        # Fallback to root command if running with non-root UID
        try:
            py_code = (
                f"import sqlite3, os; os.makedirs(os.path.dirname('{db_path}'), exist_ok=True); "
                f"c=sqlite3.connect('{db_path}'); "
                f"c.execute(\\\"CREATE TABLE IF NOT EXISTS cookies (creation_utc INTEGER, host_key TEXT, top_frame_site_key TEXT, name TEXT, value TEXT, encrypted_value BLOB, path TEXT, expires_utc INTEGER, is_secure INTEGER, is_httponly INTEGER, last_access_utc INTEGER, has_expires INTEGER, is_persistent INTEGER, priority INTEGER, samesite INTEGER, source_scheme INTEGER, source_port INTEGER, last_update_utc INTEGER, source_type INTEGER, has_cross_site_ancestor INTEGER)\\\"); "
                f"c.execute(\\\"DELETE FROM cookies WHERE name='.ROBLOSECURITY'\\\"); "
                f"c.execute(\\\"INSERT INTO cookies (creation_utc, host_key, top_frame_site_key, name, value, encrypted_value, path, expires_utc, is_secure, is_httponly, last_access_utc, has_expires, is_persistent, priority, samesite, source_scheme, source_port, last_update_utc, source_type, has_cross_site_ancestor) VALUES (0, '.roblox.com', '', '.ROBLOSECURITY', '{clean_cookie}', X'', '/', 9999999999999, 1, 1, 0, 1, 1, 1, -1, 2, 443, 0, 0, 0)\\\"); "
                f"c.commit(); c.close()"
            )
            shell_cmd = f"su -c \"python3 -c \\\"{py_code}\\\"\""
            res = subprocess.run(shell_cmd, shell=True, capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                return True, "su_success"
        except Exception:
            pass
        return False, str(e)


def auto_login_unlogged_tabs(device_id: str, base_dir: str = None, base_data_dir: str = "/data/data") -> dict:
    """
    Tự động quét các tab Roblox clone chưa có tài khoản đăng nhập trên thiết bị (device_id),
    lấy tài khoản tương ứng từ mục phân bổ trong acc.txt (# <device_id>),
    khớp cookie từ Data_Tong_Cookies.txt (hoặc Cookies.txt),
    và nạp trực tiếp cookie vào WebView Cookies của package.
    """
    paths = get_default_paths(base_dir)
    acc_file = paths["acc_file"]
    data_tong_file = paths["data_tong_file"]
    bdir = paths["base_dir"]
    tab_map_file = os.path.join(bdir, "tab_accounts.json")

    dev_key = device_id.strip().lower()
    if not os.path.exists(acc_file):
        return {
            "ok": False,
            "device_id": device_id.upper(),
            "error": f"Không tìm thấy file {acc_file}",
            "logged_in": []
        }

    with open(acc_file, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    sections = parse_acc_sections(content)
    dev_section = sections.get(dev_key)
    if not dev_section or not dev_section["accounts"]:
        return {
            "ok": False,
            "device_id": device_id.upper(),
            "error": f"Không tìm thấy tài khoản nào được phân bổ cho {device_id.upper()} trong acc.txt",
            "logged_in": []
        }

    # Load tab_accounts.json mapping
    tab_accounts = {}
    if os.path.exists(tab_map_file):
        try:
            with open(tab_map_file, "r", encoding="utf-8", errors="ignore") as f:
                tab_accounts = json.load(f)
        except Exception:
            tab_accounts = {}

    TAB_PKG_MAP = {
        1: "com.tinh.vv.hi",
        2: "com.tinh.vv.hj",
        3: "com.tinh.vv.hk",
        4: "com.tinh.vv.hl",
        5: "com.tinh.vv.hm",
        6: "com.tinh.vv.hn",
        7: "com.tinh.vv.ho",
        8: "com.tinh.vv.hp",
        9: "com.tinh.vv.hq",
        10: "com.tinh.vv.hr",
    }

    # 1. Gather banned usernames from all local and cache sources
    banned_usernames = set()
    for fname in ("acc_bi_ban.txt", "nhat_ky_ban.txt"):
        fpath = os.path.join(bdir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped:
                            u = stripped.split(":")[0].strip().lower()
                            if u:
                                banned_usernames.add(u)
            except Exception:
                pass

    # Quota-Guard ban cache
    with _CACHE_LOCK:
        for u_cached, cdata in _QUOTA_GUARD_CACHE.items():
            if isinstance(cdata, dict) and str(cdata.get("status") or "").upper() in ("BANNED", "BAN_WARN"):
                banned_usernames.add(u_cached.strip().lower())

    # 2. Identify tabs needing login or replacement
    # Reasons:
    # - "unassigned": tab has no username (empty/null/unknown)
    # - "banned": tab's current username is known to be banned
    # - "duplicate": tab's current username was already assigned to an earlier tab
    assigned_valid_usernames = set()
    tabs_to_login = []

    for tab_num, pkg in sorted(TAB_PKG_MAP.items()):
        current_u = tab_accounts.get(pkg)
        u_str = str(current_u or "").strip()
        u_clean = re.sub(r"\s*\(.*?\)$", "", u_str).strip()
        u_lower = u_clean.lower()

        if not u_clean or u_lower in ("null", "none", "unknown", "❓", ""):
            tabs_to_login.append((tab_num, pkg, "unassigned"))
        elif u_lower in banned_usernames or "(baned)" in u_str.lower() or "(banned)" in u_str.lower():
            tabs_to_login.append((tab_num, pkg, f"banned: {u_clean}"))
        elif u_lower in assigned_valid_usernames:
            tabs_to_login.append((tab_num, pkg, f"duplicate: {u_clean}"))
        else:
            assigned_valid_usernames.add(u_lower)

    if not tabs_to_login:
        return {
            "ok": True,
            "device_id": device_id.upper(),
            "total_unlogged": 0,
            "total_logged": 0,
            "logged_in": [],
            "message": f"Tất cả 10 tab trên {device_id.upper()} đều đã có tài khoản sạch hợp lệ, không có tab nào bị ban."
        }

    # 3. Candidate accounts from dev_section that are clean (not banned) and not yet assigned to any valid tab
    candidate_accounts = [
        acc for acc in dev_section["accounts"]
        if acc["username"].strip().lower() not in assigned_valid_usernames
        and acc["username"].strip().lower() not in banned_usernames
    ]

    if not candidate_accounts:
        banned_tabs_count = sum(1 for _, _, r in tabs_to_login if "banned" in r)
        dup_tabs_count = sum(1 for _, _, r in tabs_to_login if "duplicate" in r)
        empty_tabs_count = sum(1 for _, _, r in tabs_to_login if r == "unassigned")
        return {
            "ok": True,
            "device_id": device_id.upper(),
            "total_unlogged": len(tabs_to_login),
            "total_logged": 0,
            "logged_in": [],
            "message": (
                f"Phát hiện {len(tabs_to_login)} tab cần nạp trên {device_id.upper()} "
                f"({banned_tabs_count} tab ban, {dup_tabs_count} tab trùng, {empty_tabs_count} tab trống), "
                f"nhưng không còn tài khoản sạch khả dụng trong mục {device_id.upper()} của acc.txt."
            )
        }

    # 4. Load cookie map
    cookie_map = {}
    for cf_name in ("Data_Tong_Cookies.txt", "Cookies.txt", "cookie.txt"):
        cf_path = os.path.join(bdir, cf_name)
        if os.path.exists(cf_path):
            try:
                with open(cf_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line_str = line.strip()
                        if not line_str or ":" not in line_str:
                            continue
                        parts = line_str.split(":")
                        u_norm = parts[0].strip().lower()
                        c = ""
                        if "_|WARNING:" in line_str:
                            c = line_str[line_str.index("_|WARNING:"):].strip()
                        elif len(parts) > 2:
                            c = ":".join(parts[2:]).strip()
                        if c and u_norm not in cookie_map:
                            cookie_map[u_norm] = c
            except Exception:
                pass

    newly_logged = []
    unresolved_tabs = []
    for tab_num, pkg, reason in tabs_to_login:
        if not candidate_accounts:
            unresolved_tabs.append((tab_num, pkg, reason))
            continue
        acc = candidate_accounts.pop(0)
        uname = acc["username"]
        cookie_val = cookie_map.get(uname.lower())

        # If no cookie in file, check if acc line itself contains cookie
        if not cookie_val and "_|WARNING:" in str(acc.get("raw_line", "")):
            raw_l = acc["raw_line"]
            cookie_val = raw_l[raw_l.index("_|WARNING:"):].strip()

        # Write cookie to package
        cookie_written = False
        if cookie_val:
            cookie_written, _ = write_cookie_to_package(pkg, cookie_val, base_data_dir=base_data_dir)

        # Record into tab_accounts mapping
        tab_accounts[pkg] = uname
        assigned_valid_usernames.add(uname.lower())
        newly_logged.append({
            "tab": tab_num,
            "package": pkg,
            "username": uname,
            "replaced_reason": reason,
            "has_cookie": bool(cookie_val),
            "cookie_written": cookie_written
        })

    # Save updated tab_accounts.json
    if newly_logged:
        try:
            with open(tab_map_file, "w", encoding="utf-8") as f:
                json.dump(tab_accounts, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    banned_replaced = sum(1 for item in newly_logged if "banned" in item.get("replaced_reason", ""))
    dup_replaced = sum(1 for item in newly_logged if "duplicate" in item.get("replaced_reason", ""))
    empty_replaced = sum(1 for item in newly_logged if item.get("replaced_reason") == "unassigned")

    summary_parts = []
    if banned_replaced > 0:
        summary_parts.append(f"thay {banned_replaced} acc ban")
    if dup_replaced > 0:
        summary_parts.append(f"thay {dup_replaced} acc trùng")
    if empty_replaced > 0:
        summary_parts.append(f"nạp {empty_replaced} tab trống")
    details_clause = f" ({', '.join(summary_parts)})" if summary_parts else ""

    msg = f"Đã đăng nhập thành công {len(newly_logged)} tài khoản{details_clause} vào các tab trên {device_id.upper()}."
    if unresolved_tabs:
        msg += f" Còn {len(unresolved_tabs)} tab chưa có tài khoản do thiếu acc sạch trong acc.txt."

    return {
        "ok": True,
        "device_id": device_id.upper(),
        "total_unlogged": len(tabs_to_login),
        "total_logged": len(newly_logged),
        "logged_in": newly_logged,
        "unresolved_tabs": [{"tab": t, "package": p, "reason": r} for t, p, r in unresolved_tabs],
        "message": msg
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 -m agent.account_manager checkban <m_code|all|usernames>")
        print("  python3 -m agent.account_manager addacc <m_code> <user:pass...>")
        print("  python3 -m agent.account_manager replace <m_code> <count>")
        print("  python3 -m agent.account_manager moveacc <source_m> <target_m> [count]")
        sys.exit(1)

    subcmd = sys.argv[1].lower()
    if subcmd in ("checkban", "check"):
        tgt = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "m77"
        print(f"[*] Đang quét kiểm tra ban cho: {tgt}...")
        report = run_full_checkban_pipeline(tgt)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif subcmd in ("addacc", "add"):
        if len(sys.argv) < 4:
            print("Cú pháp: python3 -m agent.account_manager addacc <m_code> <user:pass...>")
            sys.exit(1)
        m_code = sys.argv[2]
        lines = sys.argv[3:]
        res = add_accounts(m_code, lines)
        sync_res = sync_to_google_drive()
        print(json.dumps({"add": res, "sync": sync_res}, indent=2, ensure_ascii=False))
    elif subcmd in ("replace", "replenish"):
        if len(sys.argv) < 4:
            print("Cú pháp: python3 -m agent.account_manager replace <m_code> <count>")
            sys.exit(1)
        m_code = sys.argv[2]
        cnt = int(sys.argv[3])
        rep_res = replace_banned_accounts_from_reserve(m_code, cnt, sync_drive=True)
        print(json.dumps(rep_res, indent=2, ensure_ascii=False))
    elif subcmd in ("moveacc", "move"):
        if len(sys.argv) < 4:
            print("Cú pháp: python3 -m agent.account_manager moveacc <source_m> <target_m> [count]")
            sys.exit(1)
        source_m = sys.argv[2]
        target_m = sys.argv[3]
        cnt = int(sys.argv[4]) if len(sys.argv) > 4 else 1
        move_res = move_accounts(source_m, target_m, count=cnt, sync_drive=True)
        print(json.dumps(move_res, indent=2, ensure_ascii=False))
    else:
        print(f"Lệnh không hợp lệ: {subcmd}")

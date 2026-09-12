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
import threading
import urllib.request
import urllib.error
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_BASE_DIR = "/storage/emulated/0/Download/Shouko"
ROBLOX_BATCH_USERNAMES_URL = "https://users.roblox.com/v1/usernames/users"
ROBLOX_USER_DETAIL_URL = "https://users.roblox.com/v1/users/{userId}"

# Rule 34 Google Drive In-Place Sync & File ID Invariants
RULE34_ACC_FILE_ID = "12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg"
RULE34_DATA_TONG_FILE_ID = "1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B"

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
        "nhat_ky_ban_file": os.path.join(bdir, "nhat_ky_ban.txt"),
        "acc_du_phong_file": os.path.join(bdir, "acc_du_phong.txt"),
    }


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

    section_pattern = re.compile(r"^\s*([Mm]\d+)(?:[_\s(].*)?$", re.IGNORECASE)

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


def clean_banned_accounts(m_code_or_target, banned_usernames, base_dir=None):
    """
    Xóa các tài khoản bị ban khỏi acc.txt và Data_Tong_Cookies.txt,
    đồng thời sao lưu .bak_<timestamp> cho CẢ HAI tệp và lưu trữ vào acc_bi_ban.txt, nhat_ky_ban.txt.
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
    nhat_ky_ban_file = paths["nhat_ky_ban_file"]

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

    # 2. Xử lý trích xuất lưu trữ từ Data_Tong_Cookies.txt
    archived_full_lines = []
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
                else:
                    cleaned_data_tong_lines.append(line_str)

        with open(data_tong_file, "w", encoding="utf-8") as f:
            f.write("\n".join(cleaned_data_tong_lines) + ("\n" if cleaned_data_tong_lines else ""))

    # 3. Ghi vào acc_bi_ban.txt (cookies đầy đủ)
    if archived_full_lines:
        with open(acc_bi_ban_file, "a", encoding="utf-8") as f:
            for l in archived_full_lines:
                f.write(l + "\n")

    # 4. Ghi vào nhat_ky_ban.txt
    target_str = str(m_code_or_target or "Tự do").strip()
    if re.match(r"^[Mm]\d+$", target_str, re.IGNORECASE):
        m_clean = target_str.upper().replace("M", "Máy ")
    elif target_str.lower() == "all":
        m_clean = "Toàn bộ"
    else:
        m_clean = "Tự do"

    with open(nhat_ky_ban_file, "a", encoding="utf-8") as f:
        for u in banned_usernames:
            f.write(f"{u}:::banned {date_str} - {m_clean}\n")

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
                for nl in valid_new_lines:
                    out_lines.append(nl)
                inserted = True

        out_lines.append(line)

    # Nếu section nằm ở cuối file mà chưa chèn
    if section_found and not inserted:
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
    elif os.path.exists(acc_du_phong_file):
        with open(acc_du_phong_file, "r", encoding="utf-8", errors="ignore") as f:
            raw_lines = f.read().splitlines()

        valid_pool = []
        non_acc_lines = []
        for line in raw_lines:
            stripped = line.strip()
            if stripped and ":" in stripped:
                valid_pool.append(line)
            elif stripped:
                non_acc_lines.append(line)

        selected_replacements = valid_pool[:num_needed]
        remaining_valid = valid_pool[num_needed:]

        # Tạo bản sao lưu acc_du_phong.txt
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(acc_du_phong_file, f"{acc_du_phong_file}.bak_{timestamp}")

        # Cập nhật lại kho dự trữ
        with open(acc_du_phong_file, "w", encoding="utf-8") as f:
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


def verify_google_drive_file_ids(rclone_bin=None):
    """
    Xác thực File ID của acc.txt và Data_Tong_Cookies.txt trên Google Drive theo Rule 34.
    File ID acc.txt: 12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg
    File ID Data_Tong_Cookies.txt: 1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B
    """
    bin_path = rclone_bin or shutil.which("rclone") or "/usr/bin/rclone"
    cmd = [bin_path, "lsf", "gdrive:", "--format", "ip"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if proc.returncode != 0:
        raise RuntimeError(f"rclone lsf thất bại: {proc.stderr.strip() or proc.stdout.strip()}")

    file_ids = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or ";" not in line:
            continue
        parts = line.split(";")
        fid, fname = parts[0].strip(), parts[1].strip()
        file_ids[fname] = fid

    # Kiểm tra bảo toàn tuyệt đối File ID (Rule 34)
    if "acc.txt" in file_ids and file_ids["acc.txt"] != RULE34_ACC_FILE_ID:
        raise RuntimeError(
            f"Rule 34 Violated! acc.txt File ID bị biến động: {file_ids['acc.txt']} != {RULE34_ACC_FILE_ID}"
        )
    if "Data_Tong_Cookies.txt" in file_ids and file_ids["Data_Tong_Cookies.txt"] != RULE34_DATA_TONG_FILE_ID:
        raise RuntimeError(
            f"Rule 34 Violated! Data_Tong_Cookies.txt File ID bị biến động: {file_ids['Data_Tong_Cookies.txt']} != {RULE34_DATA_TONG_FILE_ID}"
        )

    return {"verified": True, "file_ids": file_ids}


def sync_to_google_drive(base_dir=None, verify_rule34=True):
    """
    Đồng bộ trực tiếp acc.txt và Data_Tong_Cookies.txt lên Google Drive qua rclone copyto.
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
        "Data_Tong_Cookies.txt": "NOT_FOUND",
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

    if os.path.exists(data_tong_file):
        cmd = [rclone_bin, "copyto", data_tong_file, "gdrive:Data_Tong_Cookies.txt"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Lỗi rclone Data_Tong_Cookies.txt: {proc.stderr.strip() or proc.stdout.strip()}")
        sync_results["Data_Tong_Cookies.txt"] = "OK"
        sync_results["data_tong_sync"] = True

    if verify_rule34:
        v_res = verify_google_drive_file_ids(rclone_bin)
        sync_results["rule34_verified"] = v_res.get("verified", False)
        sync_results["file_ids"] = v_res.get("file_ids", {})

    return sync_results


def run_full_checkban_pipeline(target, base_dir=None, auto_replace=True, use_cache=True, cache_ttl=DEFAULT_CACHE_TTL):
    """
    Thực hiện trọn gói pipeline checkban:
    1. Trích xuất danh sách tài khoản theo target (m77, all, unassigned hoặc danh sách usernames).
    2. Kiểm tra trạng thái Roblox Ban API với Quota-Guard Cache.
    3. Nếu có acc ban: tự động sao lưu dual-storage, lưu trữ, xóa khỏi acc.txt & Data_Tong.
    4. Tự động nạp bù từ kho acc_du_phong.txt nếu auto_replace=True.
    5. Đồng bộ Google Drive bảo toàn File ID theo Rule 34.
    6. Trả về báo cáo tổng hợp chi tiết.
    """
    paths = get_default_paths(base_dir)
    acc_file = paths["acc_file"]

    usernames_to_check = []
    target_lower = target.strip().lower()
    is_single_m = bool(re.match(r"^[Mm]\d+$", target_lower))

    if target_lower == "all" or is_single_m or target_lower == "unassigned":
        if not os.path.exists(acc_file):
            raise FileNotFoundError(f"Không tìm thấy file {acc_file}")
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
            "error": 0,
            "banned_list": [],
            "message": "Danh sách tài khoản trống."
        }

    # 2. Kiểm tra Roblox API (sử dụng Quota-Guard Cache)
    ban_results = check_roblox_ban_status(usernames_to_check, use_cache=use_cache, cache_ttl=cache_ttl)

    live_list = []
    banned_list = []
    error_list = []

    for uname, info in ban_results.items():
        if info.get("isBanned") is True:
            banned_list.append(uname)
        elif info.get("isBanned") is False:
            live_list.append(uname)
        else:
            error_list.append(uname)

    # 3. Nếu có acc ban: tự động dọn dẹp, nạp bù dự trữ và sync Google Drive
    clean_result = None
    replace_result = None
    sync_result = None

    if banned_list:
        clean_result = clean_banned_accounts(target, banned_list, base_dir=base_dir)

        # 4. Tự động nạp bù tài khoản từ kho dự trữ nếu được kích hoạt
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

    return {
        "target": target.upper() if is_single_m else target,
        "total": len(usernames_to_check),
        "live": len(live_list),
        "banned": len(banned_list),
        "error": len(error_list),
        "banned_list": banned_list,
        "clean_result": clean_result,
        "replace_result": replace_result,
        "sync_result": sync_result,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 -m agent.account_manager checkban <m_code|all|usernames>")
        print("  python3 -m agent.account_manager addacc <m_code> <user:pass...>")
        print("  python3 -m agent.account_manager replace <m_code> <count>")
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
    else:
        print(f"Lệnh không hợp lệ: {subcmd}")

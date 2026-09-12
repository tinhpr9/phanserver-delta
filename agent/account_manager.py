#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: agent.account_manager
Nghiệp vụ quản lý dàn tài khoản:
- Phân tích cú pháp acc.txt theo mã dàn máy (M77, M109, M124...).
- Kiểm tra trạng thái Ban Roblox API chính thức (v1/usernames/users & v1/users/{userId}).
- Lưu trữ bảo toàn acc bị ban (acc_bi_ban.txt, nhat_ky_ban.txt).
- Xóa acc ban khỏi acc.txt và Data_Tong_Cookies.txt.
- Nạp bù tài khoản mới vào đúng dàn máy.
- Đồng bộ Google Drive in-place qua rclone (tuân thủ tuyệt đối Rule 34 - bảo toàn File ID).
"""

import os
import re
import sys
import json
import time
import shutil
import urllib.request
import urllib.error
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

DEFAULT_BASE_DIR = "/storage/emulated/0/Download/Shouko"
ROBLOX_BATCH_USERNAMES_URL = "https://users.roblox.com/v1/usernames/users"
ROBLOX_USER_DETAIL_URL = "https://users.roblox.com/v1/users/{userId}"


def get_default_paths(base_dir=None):
    bdir = base_dir or DEFAULT_BASE_DIR
    return {
        "base_dir": bdir,
        "acc_file": os.path.join(bdir, "acc.txt"),
        "data_tong_file": os.path.join(bdir, "Data_Tong_Cookies.txt"),
        "acc_bi_ban_file": os.path.join(bdir, "acc_bi_ban.txt"),
        "nhat_ky_ban_file": os.path.join(bdir, "nhat_ky_ban.txt"),
    }


def parse_acc_sections(acc_content):
    r"""
    Phân tích nội dung acc.txt thành dictionary các section dàn máy.
    Quy tắc nhận diện Section Header:
    - Bắt đầu bằng [Mm]\d+ (ví dụ M77, m109, M0).
    - KHÔNG chứa dấu hai chấm ':' (để loại trừ triệt để tài khoản như Mega_Wiley623:pass).
    """
    sections = {}
    current_section = None
    lines = acc_content.splitlines()

    section_pattern = re.compile(r"^\s*([Mm]\d+[^\s:]*)", re.IGNORECASE)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Kiểm tra xem có phải tiêu đề section (M77___(gag2), M109(gag2)____)
        m = section_pattern.match(stripped)
        if m and ":" not in stripped:
            raw_header = stripped
            # Chuẩn hóa mã máy: lấy phần chữ + số đầu tiên (ví dụ M77, M109)
            norm_key = re.match(r"^([Mm]\d+)", stripped, re.IGNORECASE).group(1).lower()
            current_section = {
                "raw_header": raw_header,
                "norm_key": norm_key,
                "accounts": []
            }
            if norm_key not in sections:
                sections[norm_key] = current_section
            continue

        # Nếu là dòng tài khoản (user:pass...)
        if current_section and ":" in stripped:
            parts = stripped.split(":")
            username = parts[0].strip()
            if username:
                current_section["accounts"].append({
                    "raw_line": line,
                    "username": username,
                    "password": parts[1].strip() if len(parts) > 1 else "",
                    "extra": ":".join(parts[2:]) if len(parts) > 2 else ""
                })

    return sections


def query_roblox_api(url, method="GET", data=None, retries=3):
    """
    Gửi request đến Roblox API kèm cơ chế thử lại có giãn cách chống 429 Rate Limit.
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
                # Rate limited, backoff
                time.sleep(1.0 * (attempt + 1))
                continue
            if e.code == 404:
                return None
            if attempt == retries - 1:
                raise
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(0.5)
    return None


def check_roblox_ban_status(usernames, max_workers=5):
    """
    Kiểm tra trạng thái Ban của danh sách usernames qua Roblox API v1.
    Trả về dict: {
        username: {
            "isBanned": bool,
            "id": int or None,
            "name": str,
            "error": str or None
        }
    }
    """
    if not usernames:
        return {}

    results = {}
    unique_usernames = list(dict.fromkeys(usernames))

    # 1. Batch lấy User ID qua POST v1/usernames/users (tối đa 100 usernames/request)
    name_to_id = {}
    chunk_size = 100
    for i in range(0, len(unique_usernames), chunk_size):
        chunk = unique_usernames[i:i + chunk_size]
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
                results[u] = {"isBanned": None, "id": None, "name": u, "error": f"ID_LOOKUP_ERROR: {e}"}

    # 2. Truy vấn chi tiết v1/users/{userId} để đọc trường isBanned
    def check_single_user(uname):
        uname_lower = uname.lower()
        if uname_lower not in name_to_id:
            return uname, {"isBanned": None, "id": None, "name": uname, "error": "USER_NOT_FOUND"}
        uid, real_name = name_to_id[uname_lower]
        try:
            detail_url = ROBLOX_USER_DETAIL_URL.format(userId=uid)
            detail = query_roblox_api(detail_url, method="GET")
            if detail:
                is_banned = bool(detail.get("isBanned", False))
                return uname, {"isBanned": is_banned, "id": uid, "name": real_name or uname, "error": None}
            return uname, {"isBanned": None, "id": uid, "name": uname, "error": "DETAIL_EMPTY"}
        except Exception as e:
            return uname, {"isBanned": None, "id": uid, "name": uname, "error": str(e)}

    # Chạy đa luồng kiểm tra chi tiết
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(check_single_user, u): u for u in unique_usernames if u not in results}
        for future in as_completed(futures):
            uname, res = future.result()
            results[uname] = res

    return results


def clean_banned_accounts(m_code, banned_usernames, base_dir=None):
    """
    Xóa các tài khoản bị ban khỏi acc.txt và Data_Tong_Cookies.txt,
    đồng thời sao lưu và lưu trữ vào acc_bi_ban.txt, nhat_ky_ban.txt.
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

    # 1. Tạo bản sao lưu an toàn
    shutil.copy2(acc_file, f"{acc_file}.bak_{timestamp}")
    if os.path.exists(data_tong_file):
        shutil.copy2(data_tong_file, f"{data_tong_file}.bak_{timestamp}")

    banned_set = {u.strip().lower() for u in banned_usernames if u.strip()}

    # 2. Xử lý lưu trữ từ Data_Tong_Cookies.txt
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

        # Ghi lại Data_Tong_Cookies.txt đã dọn dẹp
        with open(data_tong_file, "w", encoding="utf-8") as f:
            f.write("\n".join(cleaned_data_tong_lines) + ("\n" if cleaned_data_tong_lines else ""))

    # 3. Ghi vào acc_bi_ban.txt (full cookies)
    if archived_full_lines:
        with open(acc_bi_ban_file, "a", encoding="utf-8") as f:
            for l in archived_full_lines:
                f.write(l + "\n")

    # 4. Ghi vào nhat_ky_ban.txt
    m_clean = m_code.upper().replace("M", "Máy ") if m_code else "Tự do"
    with open(nhat_ky_ban_file, "a", encoding="utf-8") as f:
        for u in banned_usernames:
            f.write(f"{u}:::banned {date_str} - {m_clean}\n")

    # 5. Làm sạch acc.txt
    with open(acc_file, "r", encoding="utf-8", errors="ignore") as f:
        old_acc_content = f.read()

    new_acc_lines = []
    in_target_section = False
    section_pattern = re.compile(r"^\s*([Mm]\d+[^\s:]*)", re.IGNORECASE)
    norm_m_code = m_code.lower() if m_code else ""

    for line in old_acc_content.splitlines():
        stripped = line.strip()
        m = section_pattern.match(stripped)
        if m and ":" not in stripped:
            curr_code = re.match(r"^([Mm]\d+)", stripped, re.IGNORECASE).group(1).lower()
            in_target_section = (norm_m_code == "all" or curr_code == norm_m_code)
            new_acc_lines.append(line)
            continue

        if in_target_section and ":" in stripped:
            user = stripped.split(":")[0].strip().lower()
            if user in banned_set:
                # Bỏ qua dòng này vì bị ban
                continue

        new_acc_lines.append(line)

    with open(acc_file, "w", encoding="utf-8") as f:
        f.write("\n".join(new_acc_lines) + "\n")

    return {
        "banned_count": len(banned_usernames),
        "archived_cookies_count": len(archived_full_lines),
        "backup_acc": f"{acc_file}.bak_{timestamp}",
    }


def add_accounts(m_code, new_acc_lines, base_dir=None):
    """
    Nạp bù tài khoản mới vào đúng section của máy trong acc.txt.
    Nếu có cookie kèm theo, nạp vào Data_Tong_Cookies.txt.
    """
    paths = get_default_paths(base_dir)
    acc_file = paths["acc_file"]
    data_tong_file = paths["data_tong_file"]

    if not os.path.exists(acc_file):
        raise FileNotFoundError(f"Không tìm thấy tệp: {acc_file}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(acc_file, f"{acc_file}.bak_{timestamp}")

    norm_m_code = m_code.lower().strip()
    with open(acc_file, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()

    section_pattern = re.compile(r"^\s*([Mm]\d+[^\s:]*)", re.IGNORECASE)
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
            curr_code = re.match(r"^([Mm]\d+)", stripped, re.IGNORECASE).group(1).lower()
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
    }


def sync_to_google_drive(base_dir=None):
    """
    Đồng bộ trực tiếp acc.txt và Data_Tong_Cookies.txt lên Google Drive qua rclone.
    Bảo toàn 100% File ID gốc theo Rule 34 (Hard Rule).
    """
    paths = get_default_paths(base_dir)
    acc_file = paths["acc_file"]
    data_tong_file = paths["data_tong_file"]

    # Kiểm tra rclone
    rclone_bin = shutil.which("rclone") or "/usr/bin/rclone"
    if not os.path.exists(rclone_bin):
        raise RuntimeError("Không tìm thấy công cụ rclone trên hệ thống để đồng bộ Google Drive.")

    sync_results = {}
    if os.path.exists(acc_file):
        cmd = [rclone_bin, "copyto", acc_file, "gdrive:acc.txt"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Lỗi rclone acc.txt: {proc.stderr.strip() or proc.stdout.strip()}")
        sync_results["acc.txt"] = "OK"

    if os.path.exists(data_tong_file):
        cmd = [rclone_bin, "copyto", data_tong_file, "gdrive:Data_Tong_Cookies.txt"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"Lỗi rclone Data_Tong_Cookies.txt: {proc.stderr.strip() or proc.stdout.strip()}")
        sync_results["Data_Tong_Cookies.txt"] = "OK"

    return sync_results


def run_full_checkban_pipeline(target, base_dir=None):
    """
    Thực hiện trọn gói pipeline checkban:
    1. Trích xuất danh sách tài khoản theo target (m77, all, hoặc danh sách usernames).
    2. Kiểm tra trạng thái Roblox Ban API.
    3. Nếu có acc ban: tự động sao lưu, lưu trữ, xóa khỏi acc.txt & Data_Tong và sync Google Drive.
    4. Trả về báo cáo tổng hợp chi tiết.
    """
    paths = get_default_paths(base_dir)
    acc_file = paths["acc_file"]

    usernames_to_check = []
    target_lower = target.strip().lower()

    if target_lower == "all" or re.match(r"^[Mm]\d+$", target_lower):
        if not os.path.exists(acc_file):
            raise FileNotFoundError(f"Không tìm thấy file {acc_file}")
        with open(acc_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        sections = parse_acc_sections(content)

        if target_lower == "all":
            for sec in sections.values():
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
        # Target là danh sách username rời
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

    # 2. Kiểm tra Roblox API
    ban_results = check_roblox_ban_status(usernames_to_check)

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

    # 3. Nếu có acc ban và target là theo máy hoặc all -> Tự động làm sạch & sync Google Drive
    clean_result = None
    sync_result = None
    if banned_list and (target_lower == "all" or re.match(r"^[Mm]\d+$", target_lower)):
        clean_result = clean_banned_accounts(target_lower, banned_list, base_dir=base_dir)
        try:
            sync_result = sync_to_google_drive(base_dir=base_dir)
        except Exception as e:
            sync_result = {"error": str(e)}

    return {
        "target": target.upper() if re.match(r"^[Mm]\d+$", target_lower) else target,
        "total": len(usernames_to_check),
        "live": len(live_list),
        "banned": len(banned_list),
        "error": len(error_list),
        "banned_list": banned_list,
        "clean_result": clean_result,
        "sync_result": sync_result,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 -m agent.account_manager checkban <m_code|all|usernames>")
        print("  python3 -m agent.account_manager addacc <m_code> <user:pass...>")
        sys.exit(1)

    subcmd = sys.argv[1].lower()
    if subcmd in ("checkban", "check"):
        tgt = sys.argv[2] if len(sys.argv) > 2 else "m77"
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
    else:
        print(f"Lệnh không hợp lệ: {subcmd}")

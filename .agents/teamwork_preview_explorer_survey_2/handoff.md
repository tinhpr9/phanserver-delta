# Handoff Report: Storage & Account Isolation Investigation

**Explorer**: Explorer 2 (Storage & Account Isolation Explorer)  
**Working Directory**: `/root/phanserver-delta/.agents/teamwork_preview_explorer_survey_2`  
**Date**: 2026-09-12T15:40:00Z  
**Target Repository**: `/root/phanserver-delta`  

---

## 1. Observation

### 1.1 Account & Storage File Handling Architecture
- **Primary Account Engine**: `/root/phanserver-delta/agent/account_manager.py` (511 lines)
  - `get_default_paths(base_dir=None)` (lines 31–39):
    ```python
    def get_default_paths(base_dir=None):
        bdir = base_dir or DEFAULT_BASE_DIR
        return {
            "base_dir": bdir,
            "acc_file": os.path.join(bdir, "acc.txt"),
            "data_tong_file": os.path.join(bdir, "Data_Tong_Cookies.txt"),
            "acc_bi_ban_file": os.path.join(bdir, "acc_bi_ban.txt"),
            "nhat_ky_ban_file": os.path.join(bdir, "nhat_ky_ban.txt"),
        }
    ```
    *Observation*: `acc_du_phong.txt` is missing from `get_default_paths`.
  - `parse_acc_sections(acc_content)` (lines 42–87):
    Regex pattern: `section_pattern = re.compile(r"^\s*([Mm]\d+[^\s:]*)", re.IGNORECASE)`
    Check: `if m and ":" not in stripped:`
    Key extractor: `norm_key = re.match(r"^([Mm]\d+)", stripped, re.IGNORECASE).group(1).lower()`
  - `check_roblox_ban_status(usernames, max_workers=5)` (lines 124–185):
    Queries `ROBLOX_BATCH_USERNAMES_URL` (`https://users.roblox.com/v1/usernames/users`) in chunks of 100, then queries `ROBLOX_USER_DETAIL_URL` (`https://users.roblox.com/v1/users/{userId}`) to read `isBanned`.
    *Observation*: Does not contain any Quota-Guard short-term TTL cache.
  - `clean_banned_accounts(m_code, banned_usernames, base_dir=None)` (lines 187–276):
    Creates timestamp: `timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")`
    Creates backups: `acc_file.bak_{timestamp}` and `data_tong_file.bak_{timestamp}`.
    Extracts matching cookie lines from `Data_Tong_Cookies.txt` into `acc_bi_ban.txt`.
    Appends to `nhat_ky_ban.txt`: `f"{u}:::banned {date_str} - {m_clean}\n"`.
    Removes banned usernames from target section in `acc.txt`.
  - `add_accounts(m_code, new_acc_lines, base_dir=None)` (lines 278–361):
    Creates backup: `shutil.copy2(acc_file, f"{acc_file}.bak_{timestamp}")`.
    *Observation*: Does NOT back up `data_tong_file` before appending to it at line 353.
  - `sync_to_google_drive(base_dir=None)` (lines 364–393):
    Executes `rclone copyto <acc_file> gdrive:acc.txt` and `rclone copyto <data_tong_file> gdrive:Data_Tong_Cookies.txt`.
  - `run_full_checkban_pipeline(target, base_dir=None)` (lines 396–484):
    Orchestrates extraction, ban checking, cleanup, and Drive sync.
    *Observation*: Line 468 skips cleanup and sync when `target` is a list of usernames:
    ```python
    if banned_list and (target_lower == "all" or re.match(r"^[Mm]\d+$", target_lower)):
        clean_result = clean_banned_accounts(target_lower, banned_list, base_dir=base_dir)
        try:
            sync_result = sync_to_google_drive(base_dir=base_dir)
        except Exception as e:
            sync_result = {"error": str(e)}
    ```

- **Device Agent Layer**: `/root/phanserver-delta/agent/agent.py`
  - Lines 598–633: Handles `CHECK_BAN` action. Checks idempotency cache `state["checkban_action_results"][action_id]`. Calls `account_manager.run_full_checkban_pipeline(target)`. Returns ACK with serialized results.
  - Lines 635–670: Handles `ADD_ACC` action. Checks idempotency cache `state["addacc_action_results"][action_id]`. Calls `account_manager.add_accounts(m_code, lines)` and `account_manager.sync_to_google_drive()`. Returns ACK.

- **Worker Routing & Telegram Interface**:
  - `/root/phanserver-delta/worker/phanserver.js`:
    - Lines 531–585: Parses `/checkban [m_code|all|users]`, selects online device, sends control request to Durable Object `/aot/hub/control` with `kind: "check_ban"`.
    - Lines 587–673: Parses `/addacc <m_code> <user1:pass1> [user2:pass2...]`, validates account tokens with `:`, dispatches `add_acc` to `/aot/hub/control`.
  - `/root/phanserver-delta/worker/fleet_state.js`:
    - Lines 391–408: Control dispatch routing for `check_ban` and `add_acc`.
    - Lines 1002–1030: `queueCheckBan()`.
    - Lines 1031–1109: `acknowledgeCheckBan()`, builds HTML report (`Tổng`, `Sống`, `Bị Ban`, `Lỗi API`, banned usernames, clean & sync status), sends Telegram notification.
    - Lines 1111–1154: `queueAddAcc()`.
    - Lines 1156–1218: `acknowledgeAddAcc()`.

### 1.2 Local Storage & Google Drive Remote State
- **Local Directory `/storage/emulated/0/Download/Shouko/`**:
  Direct inspection via `ls -la /storage/emulated/0/Download/Shouko/`:
  - `acc.txt` (7322 bytes, modified Sep 12 12:58)
  - `Data_Tong_Cookies.txt` (207661 bytes, modified Sep 12 12:58)
  - `acc_bi_ban.txt` (7261 bytes, modified Sep 12 12:58)
  - `nhat_ky_ban.txt` (407 bytes, modified Sep 12 12:58)
  - `acc.txt.bak_20260912_125813` and `Data_Tong_Cookies.txt.bak_20260912_125813`
  - `ZeroPoint_AIO.py` (30943 bytes, modified Aug 29 05:49)
  - `acc_du_phong.txt`: Currently **NOT PRESENT** on filesystem.

- **Google Drive (`gdrive:`) Remote State**:
  Inspected via `rclone lsf gdrive: --format "sip"`:
  ```
  207661;1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B;Data_Tong_Cookies.txt
  7322;12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg;acc.txt
  ```
  - `acc.txt` File ID: `12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg` (matches Rule 34 and ORIGINAL_REQUEST.md exactly).
  - `Data_Tong_Cookies.txt` File ID: `1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B` (matches Rule 34 and ORIGINAL_REQUEST.md exactly).

- **Consumer Script Dependency in `ZeroPoint_AIO.py`**:
  Lines 450–451:
  ```python
  file_id_data = "1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B"
  file_id_acc = "12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg"
  url = "https://docs.google.com/uc?export=download"
  ```
  When users launch `ZeroPoint_AIO.py` and press `'y'`, it downloads `acc.txt` and `Data_Tong_Cookies.txt` directly using those exact File IDs.

### 1.3 Machine Section Header & Account Data Analysis
Inspected `/storage/emulated/0/Download/Shouko/acc.txt`:
- Lines 2–4:
  ```
  Sandra_Specter467:oBlkxDCY6E@ikTr:keepsign4
  Cullen_Master68746:18yuNmximr454d7:bf:keepitemsailorpiece
  ```
  These accounts sit at the beginning of the file before any `M...` section header.
- Line 6: `M77___(gag2) `
- Line 13: `M109(gag2)____`
- Line 96: `M00nlUWarden3200644:V0Ff6eS@R*@JTrHL`
  Username starts with `M` followed by digits `00` (`M00...`), demonstrating an account username starting with `M` + digit that must not be parsed as a machine section.
- Line 113: `M0_____(bf)`
- Line 220: `M0___`
  Demonstrates that duplicate machine codes (`M0`) exist within the same file.

### 1.4 Test Suite Execution
- Running `bash tests/run_all_tests.sh`:
  - `[1/7] Running test_tong_hop_link.mjs` -> PASS
  - `[2/7] Running test_telegram_phanserver.mjs` -> PASS
  - `[3/7] Running test_fleet_state_2pc.mjs` -> PASS
  - `[4/7] Running delta updater tests` -> PASS (27 tests)
  - `[5/7] Running device agent tests` -> PASS (20 tests)
  - `[6/7] Running account manager & ban check tests` -> PASS (5 tests in `test_account_manager.py`)
  - `[7/7] Running E2E flow tests` -> PASS (2 tests)
- Running `python3 tests/verify_production_runtime.py`: PASS (7/7 steps).

---

## 2. Logic Chain

1. **Rule 34 & File ID Integrity**:
   - `ZeroPoint_AIO.py` lines 450–451 hardcode File IDs `12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg` and `1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B`.
   - `rclone lsf gdrive: --format "sip"` confirms those exact File IDs exist on Google Drive.
   - `sync_to_google_drive()` uses `rclone copyto`, which overwrites file content in-place on Google Drive without changing File IDs.
   - However, `sync_to_google_drive()` does not implement the Rule 34 Dual-End Verification Gate: it does not verify post-sync File IDs or report them, so an accidental ID desynchronization would go undetected.

2. **Automated Replacement Gap (Requirement R3)**:
   - `ORIGINAL_REQUEST.md` Requirement R3 specifies automated replacement from reserve account pool (`acc_du_phong.txt` or command arguments).
   - In `account_manager.py`, `acc_du_phong.txt` is neither defined in `get_default_paths()` nor referenced anywhere in the module.
   - `run_full_checkban_pipeline()` only removes banned accounts and does not attempt to replenish the vacant slots in the affected machine sections from `acc_du_phong.txt`.
   - In `/storage/emulated/0/Download/Shouko/`, `acc_du_phong.txt` does not yet exist.

3. **Quota-Guard Cache Gap (Requirement R1)**:
   - `ORIGINAL_REQUEST.md` Requirement R1 requires a short-term result cache (Quota-Guard Cache) to prevent repeated calls for the same accounts during consecutive checks.
   - `check_roblox_ban_status()` currently initializes `results = {}` locally and queries the network every invocation. There is no cache or TTL mechanism.

4. **Section Parsing Edge Cases**:
   - `section_pattern = re.compile(r"^\s*([Mm]\d+[^\s:]*)", re.IGNORECASE)` safely rejects `Mega_Wiley623` because `ega_` is not numeric.
   - For `M00nlUWarden3200644:V0Ff6eS@R*@JTrHL` (line 96), `[Mm]\d+` matches `M00`, but `":" not in stripped` prevents it from being classified as a section. However, if an account line is malformed without colons, this check is vulnerable.
   - In `parse_acc_sections()`, when duplicate section headers occur (e.g. `M0_____(bf)` at line 113 and `M0___` at line 220), `if norm_key not in sections:` is False for the second occurrence. `current_section` is overwritten but never attached to `sections["m0"]`, discarding all accounts in the second section.
   - Accounts placed at the top of `acc.txt` before any section header (lines 2–4) are dropped by `parse_acc_sections()` because `current_section` is None, and are skipped by `clean_banned_accounts()` because `in_target_section` begins as False.

5. **Backup & Cleanup Inconsistencies**:
   - In `add_accounts()`, lines 290–291 create `.bak_<timestamp>` for `acc_file`, but when appending new cookies to `data_tong_file` (lines 352–355), no backup of `data_tong_file` is created.
   - In `run_full_checkban_pipeline()`, line 468 only triggers cleanup and Drive sync when `target_lower == "all"` or matches `^[Mm]\d+$`. When users supply a custom username list (e.g. `/checkban user1 user2`), detected banned accounts are neither cleaned nor synced.
   - In `fleet_state.js:1080`, the Telegram reporting code expects `detailsObj.clean_result.removed_from_acc`, but `clean_banned_accounts()` in `account_manager.py` only returns `banned_count` and `archived_cookies_count`.

---

## 3. Caveats

1. **`acc_du_phong.txt` Initial Content**:
   No `acc_du_phong.txt` currently exists in `/storage/emulated/0/Download/Shouko/`. The implementation must handle both when `acc_du_phong.txt` is absent/empty and when it contains reserve accounts.
2. **Roblox API Network Connectivity in Production**:
   Roblox API endpoints (`users.roblox.com`) require egress internet access from the host/device running the check. In offline or mock environments, unit tests must mock `query_roblox_api`.
3. **No Direct Code Modifications Performed**:
   Per the Explorer archetype and workflow rules, this investigation was strictly read-only. No project source files were altered during this survey.

---

## 4. Conclusion

The core foundation for ban checking and account management is established in `agent/account_manager.py`, `agent/agent.py`, and `worker/fleet_state.js`, and all 7 existing test suites currently pass. However, eight specific implementation gaps and bugs must be resolved to fulfill the user requirements:

1. **Reserve Account Pool & Auto-Replacement (`acc_du_phong.txt`)**:
   Add `acc_du_phong.txt` to `get_default_paths()`, implement a reserve extraction function that reads and removes reserve accounts from `acc_du_phong.txt`, and integrate auto-replacement into `run_full_checkban_pipeline()`.
2. **Quota-Guard Result Cache**:
   Add an in-memory/file-backed TTL cache (e.g. 5–10 minutes) for Roblox ban check results in `check_roblox_ban_status()`.
3. **Rule 34 Dual-End Verification Gate**:
   Update `sync_to_google_drive()` to verify that Google Drive File IDs match `12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg` for `acc.txt` and `1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B` for `Data_Tong_Cookies.txt` via `rclone lsf gdrive: --format "ip"`.
4. **Data_Tong_Cookies.txt Backup in `add_accounts()`**:
   Create `.bak_<timestamp>` for `data_tong_file` whenever cookies are appended.
5. **Username-Target Cleanup & Sync Support**:
   Enable `clean_banned_accounts()` and `sync_to_google_drive()` in `run_full_checkban_pipeline()` even when `target` is a list of usernames.
6. **Duplicate Section Header Account Merging**:
   In `parse_acc_sections()`, merge accounts into existing `sections[norm_key]["accounts"]` if the machine code appears more than once.
7. **Top-Level Unassigned Account Handling**:
   Track unassigned accounts preceding the first section header so they are not dropped or exempted from ban checks and cleanup.
8. **Field Alignment for Telegram HTML Reporting**:
   Include `removed_from_acc` in `clean_banned_accounts()` output to match `fleet_state.js:1080`, and report replacement account counts.

### Files Requiring Modification:
- `/root/phanserver-delta/agent/account_manager.py` (Primary changes)
- `/root/phanserver-delta/tests/test_account_manager.py` (Coverage for reserve replacement, Quota-Guard cache, Rule 34 verification, duplicate sections)
- `/root/phanserver-delta/worker/fleet_state.js` (Reporting alignment for replaced accounts)

---

## 5. Verification Method

To independently verify these findings:
1. **Run Full Test Suite**:
   ```bash
   cd /root/phanserver-delta && bash tests/run_all_tests.sh
   ```
2. **Verify Production Runtime**:
   ```bash
   cd /root/phanserver-delta && python3 tests/verify_production_runtime.py
   ```
3. **Inspect Google Drive File IDs**:
   ```bash
   rclone lsf gdrive: --format "ip" --files-only | grep -E "acc\.txt|Data_Tong_Cookies\.txt"
   ```
   Must output:
   - `12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg;acc.txt`
   - `1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B;Data_Tong_Cookies.txt`
4. **Inspect Machine Section Headers and Accounts**:
   ```bash
   grep -n "^[[:space:]]*[Mm][0-9]" /storage/emulated/0/Download/Shouko/acc.txt
   ```
5. **Inspect Hardcoded IDs in Tool**:
   ```bash
   grep -n "file_id_" /storage/emulated/0/Download/Shouko/ZeroPoint_AIO.py
   ```

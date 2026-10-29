# Handoff Report: Milestone M1 — Core Account Manager & Dual-Storage Engine

**Worker**: Worker M1 (Account Engine Worker)  
**Working Directory**: `/root/phanserver-delta/.agents/teamwork_preview_worker_m1_1`  
**Date**: 2026-09-12T15:48:30Z  
**Target Files Modified**:
- `/root/phanserver-delta/agent/account_manager.py`
- `/root/phanserver-delta/tests/test_account_manager.py`

---

## 1. Observation

### 1.1 Baseline Code State & Deficits Identified
1. **Roblox Ban API Querying & Rate Limiting**:
   - In `agent/account_manager.py` (lines 90–121 previously), `query_roblox_api()` implemented only a linear sleep `time.sleep(1.0 * (attempt + 1))` and did not parse the `Retry-After` header when HTTP 429 Too Many Requests was returned.
   - `check_roblox_ban_status()` had no caching mechanism whatsoever; repeated requests for the same usernames executed duplicate network round-trips every invocation.
2. **Dual-Storage Isolation & Backups**:
   - `clean_banned_accounts()` created `.bak_<timestamp>` for `acc.txt` and `Data_Tong_Cookies.txt`, but did not return `removed_from_acc` in its output dictionary, which caused `worker/fleet_state.js:1080` (`detailsObj.clean_result.removed_from_acc`) to be undefined and fall back to `banned`.
   - `clean_banned_accounts()` skipped cleaning when target was a list of usernames or unassigned accounts.
   - `add_accounts()` created a backup only for `acc.txt`, omitting the required `.bak_<timestamp>` backup for `Data_Tong_Cookies.txt` before appending cookie entries.
3. **Machine Section Header Parsing Edge Cases**:
   - In `acc.txt`, lines such as `M00nlUWarden3200644:V0Ff6eS@R*@JTrHL` contain `M00` followed immediately by letters. The previous regex `r"^\s*([Mm]\d+[^\s:]*)"` risked matching usernames if not guarded.
   - Duplicate machine sections (e.g. multiple `M0_____(bf)` and `M0___` headers in `/storage/emulated/0/Download/Shouko/acc.txt` at lines 113 and 220) caused subsequent sections under the same machine key to overwrite `current_section` without attaching accounts to the primary dictionary entry, dropping accounts.
   - Accounts placed at the top of `acc.txt` before any machine header (e.g., `Sandra_Specter467`, `Cullen_Master68746`) were dropped because `current_section` was None.
4. **Rule 34 Google Drive In-Place Sync & Verification**:
   - `sync_to_google_drive()` called `rclone copyto`, but lacked the Rule 34 Dual-End Verification Gate to confirm that Google Drive File IDs remained `12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg` for `acc.txt` and `1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B` for `Data_Tong_Cookies.txt`.
5. **Reserve Pool Auto-Replacement (R3)**:
   - `acc_du_phong.txt` was not defined in `get_default_paths()` and no replacement logic existed. Vacant slots left by banned accounts were not replenished.
6. **CLI Usernames Truncation**:
   - Line 496 previously set `tgt = sys.argv[2] if len(sys.argv) > 2 else "m77"`. Running `python3 -m agent.account_manager checkban user1 user2 user3` discarded `user2` and `user3`.

### 1.2 Implemented Changes in `agent/account_manager.py`
- **Quota-Guard TTL Cache (300s)**:
  - Added thread-safe in-memory cache `_QUOTA_GUARD_CACHE`, `_CACHE_LOCK`, and `DEFAULT_CACHE_TTL = 300`.
  - Added cache management functions: `clear_ban_cache()`, `invalidate_ban_cache(usernames=None)`, `get_ban_cache_stats()`.
  - In `check_roblox_ban_status(usernames, max_workers=5, use_cache=True, cache_ttl=300, pacing_delay=0.0)`:
    - Checks cache before querying API; returns cached results with `"cached": True`.
    - Only queries Roblox API for uncached usernames; updates cache upon fetch with `"cached": False`.
- **429 Exponential Backoff & Retry-After Parsing**:
  - In `query_roblox_api(url, method="GET", data=None, retries=3, backoff_factor=1.0)`:
    - Reads HTTP `Retry-After` header when `e.code == 429`.
    - Parses seconds from header or falls back to exponential backoff `wait_time = backoff_factor * (2.0 ** attempt)`.
    - Added rate pacing parameter in `check_roblox_ban_status()` for concurrency pacing.
- **Dual-Storage Isolation & Dual Backups**:
  - In both `clean_banned_accounts()` and `add_accounts()`: creates `.bak_<timestamp>` for BOTH `acc.txt` and `Data_Tong_Cookies.txt` before any file write.
  - In `clean_banned_accounts()`:
    - Computes and returns `removed_from_acc: int`, `backup_acc: str`, `backup_data_tong: str`, and `removed_per_section: dict`.
    - Supports cleaning when target is a machine code (`m77`), `"all"`, `"unassigned"`, or a list of usernames.
- **Section Parsing Edge Cases**:
  - Updated regex to `section_pattern = re.compile(r"^\s*([Mm]\d+)(?:[_\s(].*)?$", re.IGNORECASE)` with `":" not in stripped`. Accounts like `Mega_Wiley623` and `M00nlUWarden3200644` are never parsed as sections.
  - Handled duplicate section headers by reusing existing `sections[norm_key]`.
  - Tracked top accounts preceding the first section header into `sections["unassigned"]`.
- **Rule 34 Google Drive In-Place Sync & Verification**:
  - In `sync_to_google_drive(base_dir=None, verify_rule34=True)`: uses `rclone copyto` in-place.
  - Implemented `verify_google_drive_file_ids(rclone_bin=None)` confirming `12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg` for `acc.txt` and `1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B` for `Data_Tong_Cookies.txt`. Raises `RuntimeError` if mismatch occurs.
  - Returns `{"acc_sync": True, "data_tong_sync": True, "rule34_verified": True, "file_ids": {...}, "acc.txt": "OK", "Data_Tong_Cookies.txt": "OK"}`.
- **Automated Replacement from Reserve Pool (`acc_du_phong.txt`)**:
  - Added `"acc_du_phong_file"` to `get_default_paths()`.
  - Implemented `replace_banned_accounts_from_reserve(m_code, num_needed, base_dir=None, reserve_accounts=None, sync_drive=False)`.
  - Integrated auto-replacement into `run_full_checkban_pipeline(target, base_dir=None, auto_replace=True)` so when accounts in a machine section are banned, vacant slots are automatically replenished from `acc_du_phong.txt`.
- **CLI Parsing Fix**:
  - Updated `tgt = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "m77"` to parse all usernames when multiple are provided.

### 1.3 Implemented Tests in `tests/test_account_manager.py`
Expanded from 5 tests to 15 unit tests:
1. `test_parse_acc_sections`: baseline section parsing.
2. `test_parse_acc_sections_edge_cases`: `M00nlUWarden...` account parsing, duplicate `M0` sections merging, top `unassigned` accounts.
3. `test_clean_banned_accounts`: cleanup of banned accounts, cookie extraction, logging, dual backups.
4. `test_clean_banned_accounts_with_username_target_and_all`: cleaning when target is `"all"` or custom username list.
5. `test_add_accounts`: adding accounts, cookie append, dual backups.
6. `test_check_roblox_ban_status`: mapping `isBanned: False` and `isBanned: True`.
7. `test_quota_guard_ttl_cache`: cache miss, cache hit with `cached: True`, partial invalidation, full clear.
8. `test_query_roblox_api_429_retry_after_and_backoff`: parsing `Retry-After` header and sleeping exact duration.
9. `test_query_roblox_api_429_exponential_backoff_fallback`: exponential backoff `2.0 ** attempt` when header is absent.
10. `test_sync_to_google_drive_rule34_verification`: in-place `copyto` and Rule 34 File ID verification.
11. `test_verify_google_drive_file_ids_rejection`: detection and exception raising on File ID drift.
12. `test_replace_banned_accounts_from_reserve`: extracting reserve accounts from `acc_du_phong.txt`, inserting into machine section, cookie append, updating reserve pool, creating backup.
13. `test_run_full_checkban_pipeline`: pipeline execution without replacement.
14. `test_run_full_checkban_pipeline_with_auto_replace`: pipeline with `auto_replace=True` replenishing banned slots.
15. `test_cli_multi_username_parsing`: verifying `sys.argv[2:]` joining and target splitting.

### 1.4 Test Execution Results
- `pytest -v tests/test_account_manager.py`: **15 passed in 2.01s (100% pass)**.
- `bash tests/run_all_tests.sh`: **7/7 suites passed cleanly (100% pass)**:
  - `[1/7] node tests/test_tong_hop_link.mjs` -> OK
  - `[2/7] node tests/test_telegram_phanserver.mjs` -> OK
  - `[3/7] node tests/test_fleet_state_2pc.mjs` -> OK
  - `[4/7] python3 -m unittest discover -s delta/tests` -> Ran 27 tests in 0.963s OK
  - `[5/7] python3 -m unittest discover -s agent/tests` -> Ran 20 tests in 1.135s OK
  - `[6/7] pytest -q tests/test_account_manager.py` -> 15 passed in 2.01s OK
  - `[7/7] python3 tests/test_e2e_flow.py` -> Ran 2 tests in 0.336s OK
- `python3 tests/verify_production_runtime.py`: **ALL RUNTIME PRODUCTION VERIFICATIONS PASSED: 100% OK**.

---

## 2. Logic Chain

1. **Quota Protection (R1)**:
   - *Observation*: Repeated user checks could trigger Roblox API 429 rate limits.
   - *Implementation*: `_QUOTA_GUARD_CACHE` stores lookup outcomes for 300s. Subsequent checks for the same username return `cached: True` without network I/O.
   - *Validation*: `test_quota_guard_ttl_cache` confirms that on second query, `query_roblox_api` call count does not increment and `cached: True` is returned.

2. **429 Resilience**:
   - *Observation*: Roblox rate limits return HTTP 429 with optional `Retry-After`.
   - *Implementation*: `query_roblox_api()` reads `e.headers.get("Retry-After")`. If found, sleeps that duration; otherwise backs off exponentially (`2.0 ** attempt`).
   - *Validation*: `test_query_roblox_api_429_retry_after_and_backoff` and `test_query_roblox_api_429_exponential_backoff_fallback` confirm correct sleep intervals and eventual success.

3. **Data Integrity & Dual Backups (R2)**:
   - *Observation*: R2 mandates that `.bak_<timestamp>` must be created before modifying either storage file.
   - *Implementation*: Both `clean_banned_accounts` and `add_accounts` copy `acc.txt` and `Data_Tong_Cookies.txt` to `.bak_<timestamp>` before modifying file contents.
   - *Validation*: `test_clean_banned_accounts` and `test_add_accounts` verify `os.path.exists(res["backup_acc"])` and `os.path.exists(res["backup_data_tong"])`.

4. **Section Parsing Correctness**:
   - *Observation*: `M00nlUWarden3200644` and duplicate `M0` headers caused section misclassification and account loss.
   - *Implementation*: `^[Mm]\d+(?:[_\s(].*)?$` enforces that digits must be followed by `_`, `\s`, `(`, or end of string. Accounts with letters after digits or containing `:` are not treated as headers. Duplicate headers merge accounts into `sections[norm_key]["accounts"]`. Unassigned top accounts are tracked under `"unassigned"`.
   - *Validation*: `test_parse_acc_sections_edge_cases` confirms `M00nlUWarden` is preserved as an account, `M0` merges all 4 accounts, and top unassigned accounts are captured.

5. **Rule 34 File ID Invariant (R2)**:
   - *Observation*: Scripts like `ZeroPoint_AIO.py` hardcode File IDs `12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg` and `1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B`.
   - *Implementation*: `sync_to_google_drive()` uses `rclone copyto` (in-place overwrite) and invokes `verify_google_drive_file_ids()` to assert matching IDs.
   - *Validation*: `test_sync_to_google_drive_rule34_verification` asserts exact `rclone copyto` arguments and verification, while `test_verify_google_drive_file_ids_rejection` confirms fail-closed behavior on File ID drift.

6. **Reserve Account Pool Auto-Replacement (R3)**:
   - *Observation*: Banned accounts left empty slots in machine sections.
   - *Implementation*: `replace_banned_accounts_from_reserve()` extracts reserve accounts from `acc_du_phong.txt`, appends cookies to `Data_Tong_Cookies.txt`, inserts accounts into target section, updates `acc_du_phong.txt`, and backs up the reserve file. Integrated into `run_full_checkban_pipeline()`.
   - *Validation*: `test_replace_banned_accounts_from_reserve` and `test_run_full_checkban_pipeline_with_auto_replace` confirm end-to-end account replenishment and file updates.

---

## 3. Caveats

1. **Live Google Drive Remote in CI/Offline Sandbox**:
   `rclone lsf gdrive:` requires external Google Drive OAuth network access. In offline or unit test environments, `sync_to_google_drive` is tested via `mock` subprocess calls. The implementation is verified to call exact rclone arguments matching the live environment.
2. **Initial Presence of `acc_du_phong.txt`**:
   If `acc_du_phong.txt` is not yet created on a new device, `replace_banned_accounts_from_reserve` gracefully returns 0 replacements without raising exceptions.
3. **Write Scope Adherence**:
   Only `/root/phanserver-delta/agent/account_manager.py` and `/root/phanserver-delta/tests/test_account_manager.py` were modified, strictly honoring exclusive write ownership.

---

## 4. Conclusion

Milestone M1 (Core Account Manager & Dual-Storage Engine) is 100% implemented, fully verified, and satisfies all requirements R1, R2, and R3:
- Quota-Guard TTL Cache (300s) prevents redundant Roblox API calls.
- Exponential backoff with `Retry-After` header parsing protects against HTTP 429 rate limiting.
- Dual-storage isolation creates `.bak_<timestamp>` for both `acc.txt` and `Data_Tong_Cookies.txt`, archives banned cookies to `acc_bi_ban.txt`, and logs to `nhat_ky_ban.txt`.
- Output dictionary from `clean_banned_accounts` returns `removed_from_acc` matching `fleet_state.js:1080`.
- Section parsing handles `Mega_Wiley623`, `M00nlUWarden`, duplicate `M0` sections, and top unassigned accounts.
- Rule 34 Google Drive in-place sync (`rclone copyto`) and File ID verification gate confirm IDs `12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg` and `1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B`.
- Automated replenishment from `acc_du_phong.txt` seamlessly refills vacant machine slots.
- CLI argument parsing cleanly handles multiple usernames.
- 100% pass on all 7 test suites in `tests/run_all_tests.sh` and production verification in `tests/verify_production_runtime.py`.

---

## 5. Verification Method

To independently verify the implementation and test results:

```bash
# 1. Run unit test suite for account manager (15/15 tests)
cd /root/phanserver-delta && pytest -v tests/test_account_manager.py

# 2. Run the complete automated 7-suite test orchestrator
cd /root/phanserver-delta && bash tests/run_all_tests.sh

# 3. Run production runtime verification
cd /root/phanserver-delta && python3 tests/verify_production_runtime.py

# 4. Verify CLI multi-username argument parsing
python3 -m agent.account_manager checkban user1 user2 user3
```

**Invalidation Conditions**:
- If `pytest tests/test_account_manager.py` reports any failure.
- If `bash tests/run_all_tests.sh` exits with non-zero status.
- If `clean_banned_accounts` modifies files without creating `.bak_<timestamp>` for both files.
- If `sync_to_google_drive` changes the File IDs on Google Drive away from `12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg` or `1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B`.

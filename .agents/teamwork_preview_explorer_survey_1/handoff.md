# Handoff Report: Test Harness & Acceptance Verification Survey

**Agent**: Explorer 1 (Test Harness Explorer)  
**Working Directory**: `/root/phanserver-delta/.agents/teamwork_preview_explorer_survey_1`  
**Date**: 2026-09-12T15:40:00Z  

---

## 1. Observation

### 1.1 Test Suite Orchestration (`tests/run_all_tests.sh`)
- Path: `/root/phanserver-delta/tests/run_all_tests.sh`
- Content (lines 1–32):
  ```bash
  #!/bin/bash
  set -euo pipefail

  echo "========================================="
  echo "  RUNNING PHANSERVER-DELTA TEST SUITE"
  echo "========================================="

  echo "[1/7] Running test_tong_hop_link.mjs..."
  node tests/test_tong_hop_link.mjs

  echo "[2/7] Running test_telegram_phanserver.mjs..."
  node tests/test_telegram_phanserver.mjs

  echo "[3/7] Running test_fleet_state_2pc.mjs..."
  node tests/test_fleet_state_2pc.mjs

  echo "[4/7] Running delta updater tests..."
  python3 -m unittest discover -s delta/tests

  echo "[5/7] Running device agent tests..."
  python3 -m unittest discover -s agent/tests

  echo "[6/7] Running account manager & ban check tests..."
  pytest -q tests/test_account_manager.py

  echo "[7/7] Running E2E flow tests..."
  python3 tests/test_e2e_flow.py

  echo "========================================="
  echo "  ALL PHANSERVER-DELTA TESTS PASSED!"
  echo "========================================="
  ```
- Command Execution Output (`bash tests/run_all_tests.sh`):
  ```
  =========================================
    RUNNING PHANSERVER-DELTA TEST SUITE
  =========================================
  [1/7] Running test_tong_hop_link.mjs...
  TEST_TONG_HOP_LINK_EQUIVALENCE=OK
  [2/7] Running test_telegram_phanserver.mjs...
  TEST_TELEGRAM_PHANSERVER_EQUIVALENCE=OK
  [3/7] Running test_fleet_state_2pc.mjs...
  TEST_FLEET_STATE_2PC_EQUIVALENCE=OK
  [4/7] Running delta updater tests...
  Ran 27 tests in 0.467s
  OK
  [5/7] Running device agent tests...
  Ran 20 tests in 0.515s
  OK
  [6/7] Running account manager & ban check tests...
  .....                                                                    [100%]
  5 passed in 0.30s
  [7/7] Running E2E flow tests...
  ..
  Ran 2 tests in 0.102s
  OK
  =========================================
    ALL PHANSERVER-DELTA TESTS PASSED!
  =========================================
  ```
- Result: **7/7 suites pass 100% (Exit Code 0)**.

---

### 1.2 Inspection of Individual Test Suites

#### Suite 1: `tests/test_tong_hop_link.mjs` (151 lines)
- **Target**: `worker/tong_hop_link.js` (`parseTongHopLink`, `ALLOCATION_PACKAGES`).
- **Runner**: Node.js ES module (`node tests/test_tong_hop_link.mjs`).
- **Checks**:
  - Test 1 (lines 8–13): 1 device, 1 tab mapping to package `com.tinh.vv.hi`.
  - Test 2 (lines 15–20): 1 device, 10 tabs mapping correctly across `com.tinh.vv.hi` through `com.tinh.vv.hr`.
  - Test 3 (lines 21–29): 2 devices, 10 tabs (allocates 20 unique URLs, non-overlapping slices).
  - Test 4 (lines 30–35): 2 devices, 5 tabs (allocates 10 unique URLs, 5th tab on `com.tinh.vv.hm`).
  - Test 5 (lines 36–46): Insufficient URLs triggers fail-fast exception (`"Không đủ URL hợp lệ! Cần 20 URL"`).
  - Test 6 (lines 47–56): URL deduplication; throws if unique URL count < required.
  - Test 7 (lines 58–76): Skips comments, empty lines, separators (`===`), non-URL text, invalid domains.
  - Test 8 (lines 77–86): Backward compatibility with comma-prefixed legacy URLs (`com.tinh.vv.hi,<url>`).
  - Test 9 (lines 87–106): Boundary validation (tab count < 1, tab count > 10, empty target list).
  - Tests 10–12 (lines 107–136): Duplicate device IDs, case-insensitive duplicate device IDs (`M117`, `m117`), invalid/whitespace device IDs.
  - Tests 13–14 (lines 137–149): Case-insensitive query param dedup (`privateServerLinkCode` vs `pRiVaTeSeRvErLiNkCoDe`).
- **Dependencies & Mocks**: None. 100% pure JS logic, zero external network/file dependencies.
- **Status**: PASS.

#### Suite 2: `tests/test_telegram_phanserver.mjs` (345 lines)
- **Target**: `worker/phanserver.js` (`handleUpdate`, `handleCallback`).
- **Runner**: Node.js ES module (`node tests/test_telegram_phanserver.mjs`).
- **Checks**:
  - Tests 1–4 (lines 103–191): Telegram command parsing (`/phanserver m1 <tabs>`), malformed tab checks, interactive preview flow, inline callback handling (Cancel, Double Cancel, Confirm after Cancel, Confirm, Offline device confirm failure, Double Confirm, Cancel after Confirm).
  - Error reproductions (lines 176–191): GitHub 404 error handling, GitHub timeout abort handling.
  - Worker management commands (lines 193–203): `STATUS` (`FLEET_STATUS=ONLINE`), `/devices`.
  - Delta updates (lines 204–234): `UPDATE` guidance, `/update m1,m2` batch dispatch, `/restore` selective & cross-package restore (`/restore m1 10 ho`).
  - Releases & Backups (lines 236–260): `/apks` listing, `/backup m1 taskbar`, granular `/backup m1 taskbar data`.
  - Lua scripts (lines 261–280): `/script m1 sae <url>` auto-wrapping Lua loadstring, `/script m1 clean sae`.
  - Network (lines 281–308): `/tailscale m1 on|off`, `/vpn m1 status`.
  - Account & Ban commands (lines 309–334):
    - `/checkban m1` and `/checkban all` -> verifies queuing into Durable Object with `kind: "check_ban"`.
    - `/addacc m1 testuser:testpass` -> verifies queuing into Durable Object with `kind: "add_acc"`.
  - `/help` command (lines 336–340).
- **Dependencies & Mocks**:
  - `env.telegram`: Mocked function capturing messages into `sentMessages`.
  - `env.answerCallback`: Mocked function capturing callback answers into `answeredCallbacks`.
  - `env.resolveAndValidateTelegramTargets`: Mocked device lookup resolver.
  - `env.getGitHubFile`: Mocked base64 file responder for `tong_hop_link.txt`.
  - `env.fleetStateCall`: Mocked DO router for `/aot/hub/control` and `/aot/hub/state`.
- **Status**: PASS.

#### Suite 3: `tests/test_fleet_state_2pc.mjs` (377 lines)
- **Target**: `worker/fleet_state.js` (`FleetState` Durable Object).
- **Runner**: Node.js ES module (`node tests/test_fleet_state_2pc.mjs`).
- **Checks**:
  - Section 1 (lines 48–67): Device registration via heartbeat (`POST /report`), online state evaluation.
  - Section 2 (lines 68–92): Pending allocate lifecycle: save, single-use consume, double-consume 404 rejection.
  - Section 3 (lines 93–198): 2PC ALLOCATE_SERVER Happy Path:
    - Prepare phase: `PREPARE_ALLOCATE_SERVER` sent to WebSockets.
    - Ack 1: m1 sends `PREPARE_READY`.
    - Ack 2: m2 sends `PREPARE_READY` -> triggers `COMMIT_ALLOCATE_SERVER` broadcast.
    - Final Ack: m1 & m2 send `OPENED` -> triggers Telegram HTML notification (`KẾT QUẢ PHÂN SERVER`).
  - Section 4 (lines 199–247): 2PC Abort Path: m1 sends `PREPARE_READY`, m2 sends `PREPARE_FAILED` -> `ABORT_ALLOCATE_SERVER` sent to m1.
  - Section 5 (lines 248–266): Offline device fail-closed behavior (returns HTTP 400 `offline_devices_in_allocate_batch`).
  - Section 6 (lines 267–291): `UPDATE_DELTA` queued in DO storage, polled via heartbeat, acknowledged via `POST /aot/ack`, verify no redelivery.
  - Section 7 (lines 292–316): `CONTROL_TAILSCALE` queued, polled, acknowledged.
  - Section 8 (lines 317–344): `CHECK_BAN` queued, polled via heartbeat, acknowledged with details payload.
  - Section 9 (lines 345–372): `ADD_ACC` queued, polled via heartbeat, acknowledged with details payload.
- **Dependencies & Mocks**:
  - `globalThis.fetch`: Mocked for Telegram Bot API `https://api.telegram.org`.
  - `MockStorage`: In-memory `Map` simulating Cloudflare Durable Object storage (`get`/`put`).
  - `MockWebSocket`: In-memory array capturing WebSocket message payloads.
- **Status**: PASS.

#### Suite 4: Delta Updater Tests (`delta/tests/`, 27 tests)
- **Target**: `delta/delta_updater.py`, `delta/release_selector.py`.
- **Runner**: `python3 -m unittest discover -s delta/tests`.
- **Files**:
  1. `delta/tests/test_delta_updater.py` (19 tests):
     - SHA-256 calculation, manifest schema validation, rejection of HTTP/insecure schemes, directory traversal in filenames.
     - Atomic downloading with `.part` cleanup on SHA-256 mismatch or size mismatch.
     - Root install command generation using `pm install -r -d <apk>` via direct argv list (never shell text).
     - Android `su -c` quoting safety without `-S` or trailing `-`.
     - Zip extraction security (path traversal, symlink rejection).
     - All-or-nothing verification: if asset 2 fails SHA-256, asset 1 is never installed.
     - Filtering modes: index, range, keyword, random (`delta:random`), multi-keyword.
     - Keyword disambiguation (`delta` vs `delta_apk` vs `Shouko_FolderBackup.zip`).
  2. `delta/tests/test_https_redirect_guard.py` (2 tests):
     - Rejection of HTTPS -> HTTP downgrade redirects on manifests and binary asset downloads.
  3. `delta/tests/test_release_selector.py` (6 tests):
     - Selection of latest stable release, mixed `.apk` and `.zip` asset picking, exclusion of worker draft/prerelease tags, fail-closed on missing digest or untrusted download hosts.
- **Dependencies & Mocks**:
  - `unittest.mock` patching `urllib.request.urlopen`, `subprocess.run`, `shutil.which`, `os.geteuid`.
- **Status**: PASS (27 tests in 0.467s).

#### Suite 5: Device Agent Tests (`agent/tests/`, 20 tests)
- **Target**: `agent/agent.py`, `agent/server_links.py`, `agent/config.py`, `agent/backup_manager.py`.
- **Runner**: `python3 -m unittest discover -s agent/tests`.
- **Files**:
  1. `agent/tests/test_agent.py` (10 tests):
     - Config loading (`device_id.txt`, `device_group.txt`, `agent_config.json`).
     - System metrics collection (`/proc/uptime`, `/proc/loadavg`, `/proc/meminfo`).
     - ACK transmission payload to `/aot/ack`.
     - Batch action dispatch: `PREPARE_ALLOCATE_SERVER` / `COMMIT_ALLOCATE_SERVER`.
     - `UPDATE_DELTA` idempotency.
     - `CONTROL_TAILSCALE` on/off/status and idempotency.
     - `CHECK_BAN` dispatch calling `account_manager.run_full_checkban_pipeline`.
     - `ADD_ACC` dispatch calling `account_manager.add_accounts` and `account_manager.sync_to_google_drive`.
     - Single-tick agent reporting loop.
     - Auto-update git pull verification.
     - Folder backup creation (`backup_manager.create_folder_backup`).
  2. `agent/tests/test_server_links.py` (10 tests):
     - Rejection of invalid allocation format, invalid package order, invalid Roblox server URLs, duplicate URLs, expired prepare timestamps.
     - Writing atomic staging file (`server_links.txt.prep.<action_id>`).
     - Atomic rename on commit, idempotency on replay (zero redundant intent launches).
     - Rollback on intent launch runtime exception.
     - Cleanup of staging file on abort.
- **Dependencies & Mocks**:
  - `unittest.mock` patching `send_report`, `send_ack`, `open_roblox_servers`, `subprocess.run`, `account_manager.*`.
- **Status**: PASS (20 tests in 0.515s).

#### Suite 6: Account Manager Tests (`tests/test_account_manager.py`, 5 tests)
- **Target**: `agent/account_manager.py`.
- **Runner**: `pytest -q tests/test_account_manager.py` (also compatible with `python3 -m unittest`).
- **Checks**:
  - `test_parse_acc_sections` (lines 68–83): Parses `acc.txt` sections (`M77___(gag2)`, `M109(gag2)____`). Confirms account `Mega_Wiley623` is NOT parsed as a section header.
  - `test_clean_banned_accounts` (lines 84–119): Removes banned users (`Mega_Wiley623`, `JeremiahWilkerson46`) from `acc.txt` and `Data_Tong_Cookies.txt`, archives cookies to `acc_bi_ban.txt`, writes log to `nhat_ky_ban.txt`. Unaffected section `M109` preserved intact.
  - `test_add_accounts` (lines 120–143): Inserts new accounts into `M77` section before `M109`, appends cookie entries to `Data_Tong_Cookies.txt`.
  - `test_check_roblox_ban_status` (lines 144–166): Mocks batch `v1/usernames/users` and `/v1/users/{userId}` detail queries, verifying correct mapping of `isBanned: false` and `isBanned: true`.
  - `test_run_full_checkban_pipeline` (lines 167–195): End-to-end checkban pipeline for `m77` with mock Roblox API and mock `sync_to_google_drive`.
- **Dependencies & Mocks**:
  - Isolated temporary directory (`tempfile.mkdtemp`).
  - `@patch("agent.account_manager.query_roblox_api")`.
  - `@patch("agent.account_manager.sync_to_google_drive")`.
- **Status**: PASS (5 tests in 0.30s).

#### Suite 7: E2E Flow Tests (`tests/test_e2e_flow.py`, 2 tests)
- **Target**: End-to-end integration across agent modules.
- **Runner**: `python3 tests/test_e2e_flow.py`.
- **Checks**:
  - `test_full_2pc_phanserver_lifecycle_and_idempotency` (lines 40–98): Full 2PC allocation across 3 tabs on `m72`: prepare -> commit -> file write -> duplicate replay verification.
  - `test_full_folder_backup_and_restore_e2e_lifecycle` (lines 99–130): Creates folder backup `Shouko_FolderBackup.zip` with metadata, simulates root restore via `delta_updater.restore_zip_data`.
- **Dependencies & Mocks**:
  - `unittest.mock` for `server_links.open_roblox_servers`, `subprocess.run`, `root_available`.
- **Status**: PASS (2 tests in 0.102s).

---

### 1.3 Inspection of `tests/verify_production_runtime.py` (271 lines)
- **Target**: Production environment verification on `/storage/emulated/0/Download/Shouko`.
- **Runner**: `python3 tests/verify_production_runtime.py`.
- **Safety Mechanism** (lines 40–51, 218–226): Backs up existing `/storage/emulated/0/Download/Shouko/server_links.txt` before execution and restores it in a `finally` block.
- **Steps Verified**:
  - Step 1: Agent service startup via `deploy/agent_service.sh start`, status verified via `agent_service.sh status`, then stopped.
  - Step 2: Device heartbeat construction and transition from baseline offline to online/ready with capabilities (`allocate_server_2pc`, `update_delta`, `check_ban`, `add_acc`).
  - Step 3: Canary 2PC execution: PREPARE staging file created -> COMMIT atomic file replacement verified (3 tabs).
  - Step 4: Idempotency & duplicate replay: re-sending committed transaction results in `OPENED` with 0 redundant intent launches.
  - Step 5: Real `UPDATE_DELTA` execution with dedicated manifest, SHA-256 validation, and rejection of corrupt SHA-256 (`badc0ffee...`).
  - Step 6: Rerun same production paths for stability.
  - Step 7: Zero runtime dependency on legacy `Aotscript` in `sys.modules`.
- **Execution Result**:
  ```
  ALL RUNTIME PRODUCTION VERIFICATIONS PASSED: 100% OK
  ```
- **Status**: PASS (Exit Code 0).

---

## 2. Logic Chain

1. **Test Harness Execution Baseline**:
   - Observations 1.1, 1.2, and 1.3 demonstrate that `bash tests/run_all_tests.sh` (7/7 suites) and `python3 tests/verify_production_runtime.py` (7 steps) currently execute cleanly and pass without runtime errors.
   - The test infrastructure (Node.js runtime, Python 3.13, pytest, unittest) is fully installed and functional in the working environment.

2. **Gap Analysis vs Acceptance Criteria (`ORIGINAL_REQUEST.md`)**:
   While the automated suites pass, comparing the actual implementations and tests against `ORIGINAL_REQUEST.md` reveals critical missing features:

   - **Gap 1: Missing Quota-Guard Cache in Ban Checker**:
     - *Observation*: `agent/account_manager.py` (lines 124–185) executes batch queries against `users.roblox.com/v1/usernames/users` and `/v1/users/{userId}` directly on every call. There is no cache dictionary, no TTL timestamp mechanism, and no caching logic.
     - *Requirement*: R1 explicitly demands: *"có bộ đệm kết quả (Quota-Guard Cache) ngắn hạn để ngăn chặn việc gọi lặp lại cùng một tài khoản khi người dùng kiểm tra nhiều lần liên tiếp."*
     - *Test Impact*: `tests/test_account_manager.py` mocks `query_roblox_api` and never tests repeated lookup caching or cache expiry.

   - **Gap 2: Missing Automated Replacement from Reserve Account Pool (`acc_du_phong.txt`)**:
     - *Observation*: In `agent/account_manager.py` (lines 465–474), `run_full_checkban_pipeline` only invokes `clean_banned_accounts` and `sync_to_google_drive`. No code touches or reads `acc_du_phong.txt`. There is no auto-replacement logic.
     - *Requirement*: R3 explicitly demands: *"Hệ thống hỗ trợ cơ chế tự động nạp bù tài khoản thay thế khi có tài khoản trong dàn máy bị ban: Đọc từ kho tài khoản dự trữ (`acc_du_phong.txt` hoặc qua tham số lệnh). Chèn tài khoản hợp lệ mới vào đúng vị trí section dàn máy chỉ định... bổ sung cookie tương ứng vào `Data_Tong_Cookies.txt`."*
     - *Test Impact*: `tests/test_account_manager.py` has no tests for `acc_du_phong.txt` or auto-replacement.

   - **Gap 3: Missing Test Verification of Rule 34 Google Drive File ID Preservation**:
     - *Observation*: `tests/test_account_manager.py` (lines 167, 187, 194) completely stubs out `sync_to_google_drive` using `@patch("agent.account_manager.sync_to_google_drive")`. In `agent/account_manager.py` (lines 364–393), `sync_to_google_drive` invokes `rclone copyto`, but no test validates that the Google Drive File IDs (`12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg` and `1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B`) remain invariant.
     - *Requirement*: Acceptance Criteria demands: *"File ID của `acc.txt` (`12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg`) và `Data_Tong_Cookies.txt` (`1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B`) trên Google Drive được giữ nguyên 100%, không bị đổi ID sau khi cập nhật."*

   - **Gap 4: `verify_production_runtime.py` Does Not Test Account Manager Features**:
     - *Observation*: `verify_production_runtime.py` only tests 2PC server links, Delta updater, and agent service. It does not exercise `account_manager.py` (`run_full_checkban_pipeline`, `clean_banned_accounts`, `add_accounts`, `sync_to_google_drive`).
     - *Impact*: Any regression or breakage in the ban checker or account manager will not be caught by `verify_production_runtime.py`.

   - **Gap 5: Roblox API HTTP 429 Backoff Not Validated in Test Suite**:
     - *Observation*: In `tests/test_account_manager.py`, `query_roblox_api` is patched out at the function level. The internal 429 retry backoff loop in `agent/account_manager.py` (lines 109–112) is never exercised under test conditions.

---

## 3. Caveats

1. **Live Network Isolation**: Tests in `run_all_tests.sh` run offline without live network connectivity to `users.roblox.com` or `api.telegram.org`. All external APIs are mocked using `unittest.mock` or custom mock functions.
2. **Device Hardware / Termux Environment**: `verify_production_runtime.py` is designed for Android/Termux environments where `/storage/emulated/0/Download/Shouko` exists. In this environment, `/storage/emulated/0/Download/Shouko` is present with real data files, which is why `verify_production_runtime.py` passes. On a standard Linux VM without this mount, step 1/step 3 would fail unless mock directories are created.
3. **Read-Only Investigation Scope**: In accordance with the Explorer archetype rules, no source code or test files were modified.

---

## 4. Conclusion

1. **Harness Status**: The test harness (`tests/run_all_tests.sh` and `tests/verify_production_runtime.py`) is fully functional and passes 100% (7/7 suites + production runtime verification).
2. **Core Implementation Coverage**:
   - `tong_hop_link.js` has comprehensive edge case and boundary testing (14 assertions).
   - `phanserver.js` covers Telegram bot commands, previews, 2PC dispatch, and error handling (17 scenarios).
   - `fleet_state.js` covers 2PC prepare/commit/abort, heartbeat delivery, and DO state transitions.
   - `delta_updater.py` covers download security, hash integrity, root commands, and release picking.
   - `agent.py` and `server_links.py` cover agent coordination and atomic server link updates.
3. **Implementation Gaps to Address in Subsequent Milestones**:
   - **M1 (Ban Detection)**: Implement an in-memory TTL `Quota-Guard Cache` in `agent/account_manager.py` and add unit tests in `tests/test_account_manager.py` to verify cached responses and 429 backoff handling.
   - **M2 (Dual-Storage & Rule 34)**: Add a dedicated unit test verifying that `sync_to_google_drive` calls `rclone copyto` with exact expected arguments, and verify File ID preservation rules.
   - **M3 (Reserve Account Auto-Replacement)**: Implement reading `acc_du_phong.txt`, extracting valid replacement accounts, inserting them into `acc.txt` (and cookies into `Data_Tong_Cookies.txt`), updating `acc_du_phong.txt`, and adding comprehensive test coverage.
   - **Acceptance Enhancement**: Add account manager runtime verification steps (checkban dry-run or mock execution, addacc verification) to `verify_production_runtime.py` or a dedicated acceptance test suite.

---

## 5. Verification Method

To independently verify these findings, execute:

```bash
# 1. Run the entire automated test suite (all 7 suites)
cd /root/phanserver-delta && bash tests/run_all_tests.sh

# 2. Run the individual test suites directly
node tests/test_tong_hop_link.mjs
node tests/test_telegram_phanserver.mjs
node tests/test_fleet_state_2pc.mjs
python3 -m unittest discover -s delta/tests
python3 -m unittest discover -s agent/tests
pytest -q tests/test_account_manager.py
python3 tests/test_e2e_flow.py

# 3. Run production runtime verification
python3 tests/verify_production_runtime.py

# 4. Verify absence of Quota-Guard Cache and Reserve Pool Replacement in account_manager
grep -i "cache" agent/account_manager.py || echo "NO_CACHE_FOUND"
grep -i "du_phong" agent/account_manager.py || echo "NO_DU_PHONG_FOUND"
```

**Invalidation Conditions**:
- If `tests/run_all_tests.sh` exits with non-zero code.
- If `tests/verify_production_runtime.py` throws an assertion error.
- If `agent/account_manager.py` is found to already contain `QuotaGuardCache` or `acc_du_phong.txt` processing logic.

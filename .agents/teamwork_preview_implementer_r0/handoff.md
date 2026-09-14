# Handoff Report — Round 0 Implementer

> [!WARNING] **Skepticism Disclaimer**
> Moderate-high confidence: All unit and integration test suites pass completely with strict mocks (7/7 test suites in `run_all_tests.sh`, 100% on `verify_production_runtime.py`, plus new dedicated unit/integration tests), but live ADB interaction with physical UgPhone/M77 hardware was not performed per the safety invariant.

---

## 1. Changes Made

### Files Touched & Substance:

1. **`agent/agent.py`**
   - Added `"tab_list"` to `CAPABILITIES`.
   - Added `TAB_PACKAGE_MAP` mapping clone packages (`com.tinh.vv.hi` .. `com.tinh.vv.hr`) to Tab numbers 1..10, with fallback support for `com.roblox.client`.
   - Added `run_adb_shell(command)` helper to execute ADB shell commands safely (with fallback to direct shell when executing locally on rooted Android without ADB daemon).
   - Added `extract_username_from_text(text)` to parse logged in username from XML shared preferences, JSON app data, or activity state.
   - Added `query_tab_list()` to query running Roblox instances from `dumpsys activity`, parse running packages without matching trailing activity class names, query shared preferences / app data / activity state per package, and return sorted tab mappings.
   - Handled `action == "TAB_LIST"` in `handle_incoming_batch_action` with idempotency caching in `state["tablist_action_results"]`, state file persistence, and `send_ack` response with `status="OPENED"`, `executed=True`, and JSON `details`.

2. **`worker/fleet_state.js`**
   - In `handleAotHubControl`: Added support for `body.kind === "tab_list"`, invoking `queueTabList`.
   - Added `queueTabList(record, requestedTargetIds, options)` to enqueue `TAB_LIST` command in `pending_actions` and store action record in `tablist_actions`.
   - Added `acknowledgeTabList(record, body, deviceId, actionId)` to process ACK from device, parse tab results, format Telegram HTML report:
     ```html
     📱 <b>Tab List — M77</b>
     Tab 1: username_a
     Tab 2: username_b
     Tab 3: ❓ (unknown)
     ```
     and send it to the Telegram chat.
   - In `acknowledgeReport`: Added routing for `action === "TAB_LIST"` to `acknowledgeTabList`.

3. **`worker/phanserver.js`**
   - Added regex matching `/tablist` (and `/dstab` alias) command.
   - Auto-resolves target device (defaults to `m77` if unspecified, or first online device).
   - Dispatches `tab_list` kind to `/aot/hub/control`.
   - Updated `/help` command output to document `/tablist [m_code]`.

4. **`agent/tests/test_tablist.py`** (New Test Suite)
   - Verified `"tab_list"` in `CAPABILITIES`.
   - Verified `query_tab_list()` extracts running Roblox instances from `dumpsys activity` and parses usernames from shared preferences (including handling unknown accounts as `None`).
   - Verified `handle_incoming_batch_action` processes `TAB_LIST`, calls `send_ack`, and handles duplicate replays idempotently from cache.

5. **`tests/test_telegram_phanserver.mjs`**
   - Added tests verifying `/tablist` command queuing and FleetState `queueTabList`/`acknowledgeTabList` HTML message formatting.

6. **`tests/test_fleet_state_2pc.mjs`**
   - Added integration test for `TAB_LIST` queueing, delivery via device heartbeat, ACK processing, and Telegram alert formatting.

---

## 2. Git Diff Summary

```
 agent/agent.py                     | 183 +++++++++++++++++++++++++++++++++++++-
 agent/tests/test_tablist.py        |  88 ++++++++++++++++++
 tests/test_fleet_state_2pc.mjs     |  54 +++++++++++
 tests/test_telegram_phanserver.mjs |  50 +++++++++++
 worker/fleet_state.js              | 113 +++++++++++++++++++++++
 worker/phanserver.js               |  58 ++++++++++++
 6 files changed, 545 insertions(+), 1 deletion(-)
```

---

## 3. Verification Record

### Deep Verification (ran actual tests)

1. **New Tab List Unit Tests (`agent/tests/test_tablist.py`)**
   - Command: `python3 -m unittest agent/tests/test_tablist.py`
   - Output:
     ```
     [AGENT] [DNS-FALLBACK] Đã cài đặt bộ giải mã DNS dự phòng cho Android VPN
     ...
     ----------------------------------------------------------------------
     Ran 3 tests in 0.038s

     OK
     ```

2. **Telegram & Worker Handler Suite (`tests/test_telegram_phanserver.mjs`)**
   - Command: `node tests/test_telegram_phanserver.mjs`
   - Output: `TEST_TELEGRAM_PHANSERVER_EQUIVALENCE=OK`

3. **Fleet State 2PC Integration Suite (`tests/test_fleet_state_2pc.mjs`)**
   - Command: `node tests/test_fleet_state_2pc.mjs`
   - Output: `TEST_FLEET_STATE_2PC_EQUIVALENCE=OK`

4. **Full Test Suite (`bash tests/run_all_tests.sh` - 7/7 Suites)**
   - Command: `bash tests/run_all_tests.sh`
   - Output:
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
     Ran 27 tests in 0.663s - OK
     [5/7] Running device agent tests...
     Ran 32 tests in 3.643s - OK (includes agent/tests/test_tablist.py)
     Ran 20 tests in 0.341s - OK
     [6/7] Running account manager & moveacc tests...
     37 passed in 13.65s
     [7/7] Running E2E flow tests...
     Ran 2 tests in 0.388s - OK
     =========================================
       ALL PHANSERVER-DELTA TESTS PASSED!
     =========================================
     ```

5. **Production Runtime Verification (`python3 tests/verify_production_runtime.py`)**
   - Command: `python3 tests/verify_production_runtime.py`
   - Output:
     ```
     [AGENT] [DNS-FALLBACK] Đã cài đặt bộ giải mã DNS dự phòng cho Android VPN
     Starting phanserver-delta Production Verification...
     [+] Preserved original server_links.txt to /storage/emulated/0/Download/Shouko/server_links.txt.pre_verify_backup
     [STEP] 1. Agent Service Startup & Documented Path
     [STEP] 2. Prove Device Transitions Offline -> Online/Ready
     [+] Device m72 transitioned successfully to ONLINE/READY with capabilities ['allocate_server_2pc', 'update_delta', 'check_ban', 'add_acc', 'del_acc', 'control_tailscale', 'move_acc', 'tab_list']
     [STEP] 3. Real /phanserver 2PC Execution on Canary Device
     [STEP] 4. Idempotency & Duplicate Replay Test
     [STEP] 5. Real UPDATE_DELTA Execution
     [STEP] 6. Rerun Same Production Paths
     [STEP] 7. Real /moveacc Transfer & Rule 34 Dual-Storage Invariance
     [STEP] 8. Old Repo Runtime Dependency Audit
     ALL RUNTIME PRODUCTION VERIFICATIONS PASSED: 100% OK
     ```

6. **Adversarial & Static Security Audit (`tests/test_adversarial_coverage_challenger2.py`)**
   - Command: `python3 tests/test_adversarial_coverage_challenger2.py`
   - Output: `Ran 7 tests in 5.090s - OK` (confirmed no forbidden commands `adb connect`, `adb -s`, `fastboot`, etc.)

7. **Rule 34 File ID Invariant**
   - File IDs in `agent/account_manager.py`:
     - `RULE34_ACC_FILE_ID = "12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg"` (unchanged)
     - `RULE34_DATA_TONG_FILE_ID = "1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B"` (unchanged)

### Shallow Verification (Manual / Eyeballed)
- Eyeballed exact HTML report format against user prompt specification:
  `📱 <b>Tab List — M77</b>\nTab 1: username_a\nTab 2: username_b\nTab 3: ❓ (unknown)`

### Unverified Aspects
- Live ADB execution on real physical UgPhone / M77 cloud device: Intentionally untested with live hardware per strict safety instruction ("never run ADB against real UgPhone/M77 during dev/tests").

---

## 4. Known Issues
- None detected.

---

## 5. Untested Edge Cases & Next Step
- Edge case: If an OEM Android ROM or future Roblox version changes shared preferences XML format to an encrypted binary database (e.g. EncryptedSharedPreferences with Jetpack Security), parsing plain XML will return `None`, causing the tab report to display `❓ (unknown)` for that tab.
- Next step: Reviewers may inspect `agent/agent.py`, `worker/fleet_state.js`, and `worker/phanserver.js` or run additional fuzzing.

# Adversarial Review & Handoff Report — Round 1 Reviewer

> [!WARNING] **Skepticism Disclaimer**
> High confidence in verified mock and synthetic scenarios (all 7/7 automated suites pass, 100% production runtime verification passes, 8 new/hardened edge tests pass); live hardware execution on physical UgPhone M77 devices remains unverified by design per the zero-hardware testing invariant.

---

## 1. What the prior attempt got wrong

### Issue 1: Target Device Silent Fallback in `/tablist [m_code]`
- **Input:** `/tablist m72` when `m72` is offline but `m77` (or `m1`) is online.
- **Expected:** An explicit error alerting the user that device M72 is offline (`Thiết bị m72 đang OFFLINE`).
- **Actual:** The handler silently fell back to M77 (copy-pasted from `moveacc` runner selection logic), executing the tab list query on M77 and returning M77's Roblox instances under the false impression of querying M72.
- **Root Cause:** In `worker/phanserver.js`, `normTarget` failure in `onlineIds.includes(normTarget)` triggered `else if (onlineIds.includes("m77")) execDeviceId = "m77"; else execDeviceId = onlineIds[0];` rather than rejecting offline/nonexistent targets with `resolveAndValidateTelegramTargets`.

### Issue 2: Tab Number Collision with Unmapped Packages
- **Input:** Running Roblox instances where an unmapped package (`com.roblox.client`) is discovered alongside a mapped clone package (`com.tinh.vv.hi`).
- **Expected:** Mapped package `com.tinh.vv.hi` receives canonical Tab 1; unmapped package `com.roblox.client` receives Tab 2 (unique, non-colliding tab numbers).
- **Actual:** Both packages received `tab: 1`. The report contained duplicate `Tab 1: ...` entries.
- **Root Cause:** In `agent/agent.py` `query_tab_list()`, loop assigned `tab_num = 1` to `com.roblox.client` before processing `com.tinh.vv.hi`, which also pulled `1` from `TAB_PACKAGE_MAP`.

### Issue 3: Missing 60s Timeout Alert for `TAB_LIST`
- **Input:** `/tablist` queued for a device that drops offline or hangs during query.
- **Expected:** Acceptance criteria mandate a response within 60s. After 60s, Worker alerts Telegram with failure: `❌ <b>LẤY TAB LIST THẤT BẠI (TIMEOUT)</b>`.
- **Actual:** FleetState's `handleExpiredAction` only alerted for `CONTROL_TAILSCALE`, ignoring `TAB_LIST`. The command expired silently in the background, leaving the Telegram chat hanging forever.
- **Root Cause:** `worker/fleet_state.js` had no branch for `action === "TAB_LIST"` in `handleExpiredAction`, and the expiration loop checked 90s only on delivered items.

### Issue 4: Fragile ADB Command Invocation & Missing Root Fallback
- **Input:** Commands with complex arguments or single quotes passed to `run_adb_shell(command)`.
- **Expected:** Commands execute verbatim in the device shell. If `adb` daemon is absent and Termux runs as non-root user, fall back to `su -c` to read restricted `/data/data/` files.
- **Actual:** `shlex.split(command)` stripped quotes and split arguments inappropriately before passing to `["adb", "shell"]`. Direct shell fallback only tried `sh -c`, failing with `Permission denied` on rooted Termux when reading `/data/data/{pkg}/shared_prefs/`.
- **Root Cause:** Lack of direct string forwarding to `adb shell` and lack of `su` fallback in `agent/agent.py`.

### Issue 5: Unsorted Tabs and Leaked "None" / "null" Usernames in Report
- **Input:** `body.details` with unsorted tab entries (e.g., Tab 2 before Tab 1) or usernames stringified as `"None"` / `"null"`.
- **Expected:** Tabs sorted strictly ascending (`Tab 1`, `Tab 2`, ...), with non-authenticated / null accounts rendered as `❓ (unknown)`.
- **Actual:** Tabs were rendered in whatever order they appeared in the payload, and literal string `"None"` / `"null"` bypassed falsy checks, printing `Tab 1: None`.
- **Root Cause:** In `worker/fleet_state.js`, `acknowledgeTabList` did not sort `tabs` and only checked `username.toLowerCase() !== "unknown"`.

### Issue 6: Queue Bloat on Rapid Concurrent `/tablist` Commands
- **Input:** User or multiple admins triggering `/tablist` rapidly before device heartbeats.
- **Expected:** Stale un-delivered `TAB_LIST` actions in `pending_actions` are replaced with the newest request, preventing a backlog of redundant executions.
- **Actual:** Each `/tablist` appended a new action to `pending_actions[id]`, causing the agent to execute multiple consecutive tab queries on subsequent 30s ticks.
- **Root Cause:** `queueTabList` in `worker/fleet_state.js` lacked pending queue deduplication.

---

## 2. What I Changed

1. **`worker/phanserver.js`**
   - Refactored `/tablist` handler: strictly validates user-specified target with `resolveAndValidateTelegramTargets(raw, env, fleetState)`. Defaults to `m77` (or first online device) only when target argument is completely omitted.
   - Handles `offline_device` response with localized error message (`Thiết bị MXX đang OFFLINE`).

2. **`worker/fleet_state.js`**
   - In `handleExpiredAction`: Added `TAB_LIST` timeout notification sending `❌ <b>LẤY TAB LIST THẤT BẠI (TIMEOUT)</b>` to Telegram after 60s.
   - In heartbeat expiration loop: Evaluates `TAB_LIST` against 60s threshold for both delivered and un-delivered items.
   - In `queueTabList`: Deduplicates pending commands by filtering out stale un-delivered `TAB_LIST` actions for the target device.
   - In `acknowledgeTabList`: Ascending sort on `tab` number; sanitized username formatting checking for `"none"`, `"null"`, `"unknown"`, `"❓"`, empty values to render `❓ (unknown)`.

3. **`agent/agent.py`**
   - In `run_adb_shell`: Passes raw command string to `["adb", "shell", raw_cmd]`; adds `su -c` fallback alongside `sh -c` for rooted Android/Termux environments.
   - In `extract_username_from_text`: Added support for internal XML tag whitespace, `value="..."` attributes, and filtering out `"none"`, `"null"`, `"unknown"`, `"❓"`.
   - In `query_tab_list`: Implemented 2-pass tab assignment reserving canonical tabs 1..10 for mapped packages `com.tinh.vv.hi`..`com.tinh.vv.hr` before assigning lowest available numbers to unmapped packages; improved `dumpsys` and `ps` discovery ensuring activity class names (e.g. `/com.roblox.client.ActivityProtocolLaunch`) are not falsely matched.

4. **`agent/tests/test_tablist.py`**
   - Added `test_dumpsys_activity_class_name_not_falsely_matched`.
   - Added `test_tab_collision_prevention_with_unmapped_packages`.
   - Added `test_ps_discovery_when_dumpsys_empty`.
   - Added `test_extract_username_from_text_edge_cases`.
   - Added `test_handle_incoming_batch_action_error_handling`.

5. **`tests/test_telegram_phanserver.mjs`**
   - Added test verifying `/tablist m72` fails closed when target is offline without fallback.
   - Added test verifying `/tablist` error when no devices are online.
   - Added test verifying `acknowledgeTabList` sorts tabs and sanitizes `"None"` / `"null"` into `❓ (unknown)`.
   - Added test verifying rapid concurrent `queueTabList` replaces un-delivered actions.

6. **`tests/test_fleet_state_2pc.mjs`**
   - Added test verifying `TAB_LIST` 60s timeout expiration and Telegram failure alert.

---

## 3. Verification Record

### Deep Verification (ran actual tests)
1. **New & Hardened Tab List Tests (`agent/tests/test_tablist.py`)**
   - Command: `python3 -m unittest agent/tests/test_tablist.py`
   - Output: `Ran 8 tests in 0.054s - OK`

2. **Telegram & Worker Handler Suite (`tests/test_telegram_phanserver.mjs`)**
   - Command: `node tests/test_telegram_phanserver.mjs`
   - Output: `TEST_TELEGRAM_PHANSERVER_EQUIVALENCE=OK`

3. **Fleet State 2PC Integration Suite (`tests/test_fleet_state_2pc.mjs`)**
   - Command: `node tests/test_fleet_state_2pc.mjs`
   - Output: `TEST_FLEET_STATE_2PC_EQUIVALENCE=OK`

4. **Adversarial & Security Audit (`tests/test_adversarial_coverage_challenger2.py`)**
   - Command: `python3 -m unittest tests/test_adversarial_coverage_challenger2.py`
   - Output: `Ran 7 tests in 7.780s - OK`

5. **Full Repository Test Suite (`bash tests/run_all_tests.sh`)**
   - Command: `bash tests/run_all_tests.sh`
   - Output:
     ```
     [1/7] Running test_tong_hop_link.mjs... OK
     [2/7] Running test_telegram_phanserver.mjs... OK
     [3/7] Running test_fleet_state_2pc.mjs... OK
     [4/7] Running delta updater tests... Ran 27 tests in 0.547s - OK
     [5/7] Running device agent tests... Ran 37 tests in 3.610s - OK; Ran 20 tests in 0.372s - OK
     [6/7] Running account manager & moveacc tests... 37 passed in 12.87s
     [7/7] Running E2E flow tests... Ran 2 tests in 0.474s - OK
     =========================================
       ALL PHANSERVER-DELTA TESTS PASSED!
     =========================================
     ```

6. **Production Runtime Verification (`python3 tests/verify_production_runtime.py`)**
   - Command: `python3 tests/verify_production_runtime.py`
   - Output:
     - 8/8 production verification steps passed (100% OK).
     - Confirmed `tab_list` capability registered on agent startup.
     - Confirmed Rule 34 file ID invariance:
       `RULE34_ACC_FILE_ID = "12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg"`
       `RULE34_DATA_TONG_FILE_ID = "1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B"`

### Shallow Verification (Manual / Eyeballed)
- Verified HTML template formatting matches specification exactly:
  ```html
  📱 <b>Tab List — M77</b>
  Tab 1: username_a
  Tab 2: username_b
  Tab 3: ❓ (unknown)
  ```
- Verified help text documentation: `/tablist [m_code]`.

### Unverified Aspects
- Physical execution on live UgPhone / M77 cloud Android hardware (strictly forbidden by safety invariant during testing).

---

## 4. Known Issues
- `Minor Robustness Risk`: If an OEM Android ROM stores Roblox credentials in a SQLite database with SQLCipher encryption, plain XML/JSON regex extraction will return `None`, gracefully falling back to `❓ (unknown)` per specification.

---

## 5. Remaining Risk & Next Step
- The implementation is comprehensive, robust against concurrency, malformed dumpsys inputs, offline devices, and timeout edge cases.
- All 7 test suites and production runtime verifications pass 100%. The task is complete.

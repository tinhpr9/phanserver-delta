# Refinement Round 3 Progress

## Status: Complete (Step 4 - Re-verify)

### Requirements Coverage
- [x] R1. ADB-Based Tab-to-Account Mapping: Agent on M77 queries running Roblox app instances using ADB and determines logged in account per instance (mapping Tab N -> username or None).
- [x] R2. Telegram Command `/tablist`: On-demand only (no polling, background scan, or cron). Returns HTML:
  📱 <b>Tab List — M77</b>
  Tab 1: username_a
  Tab 2: username_b
  Tab 3: ❓ (unknown)
- [x] R3. Worker + Agent Integration: Telegram Bot (`phanserver.js`) sends TAB_LIST action via `fleet-batch-v1` -> Agent (`agent.py`) executes ADB query -> sends result to Worker -> Worker forwards to Telegram. Added "tab_list" to agent CAPABILITIES.
- [x] Acceptance criteria:
  - Functional: `/tablist` returns HTML report within 60s, correct count, tab -> username or ❓.
  - Non-Regression: `bash tests/run_all_tests.sh` passes 7/7 suites, `python3 tests/verify_production_runtime.py` passes 100%, Rule 34 preserved.
  - Safety: Mock unit/integration testing only (zero real hardware ADB executed), no Roblox API calls.

### TDD Cycle Executed
1. **RED Stage**:
   - Added tests in `tests/test_telegram_phanserver.mjs` for corrupted `body.details` string, malformed `tabNum`, multi-target rejection, case insensitivity.
   - Added tests in `agent/tests/test_tablist.py` for XML with attributes preceding `name=` (e.g. `<string id="custom" name="Username">`).
   - Added `test_capabilities_includes_tab_list` in `tests/test_device_agent.py`.
   - Executed tests and verified RED failure:
     - `Error: Corrupted details handling failed. Got: 📱 <b>Tab List — M1</b>\n(Không có tab Roblox nào đang chạy)`
     - `AssertionError: None != 'PreAttrUser'`
2. **GREEN Stage**:
   - Fixed `worker/fleet_state.js`:
     - Tracked `parseFailed` when `body.details` fails JSON parsing; formatted warning instead of falsifying 0 tabs.
     - Filtered arrays from `tabs` using `!Array.isArray(t)`.
     - Safeguarded sort comparator `Number(...) || 0` against `NaN`.
     - Escaped `tabNum` with `escapeHtml` to prevent HTML injection/breakage.
     - Supported numeric usernames in `acknowledgeTabList`.
   - Fixed `worker/phanserver.js`:
     - Added single-target constraint check `single.length > 1` for `/tablist`.
     - Normalized `onlineIds` for default device resolution.
   - Fixed `agent/agent.py`:
     - Updated `xml_patterns` to allow arbitrary attributes before/after `name=`/`key=`.
     - Added `screen_name` support across XML/JSON/KV.
     - Expanded file search in `query_tab_list` to include `.txt` and `.dat`.
   - Re-executed tests:
     - `tests/test_telegram_phanserver.mjs` -> PASS
     - `agent/tests/test_tablist.py` -> PASS (10/10)
     - `tests/test_device_agent.py` -> PASS (21/21)
3. **Full Regression Verification**:
   - `bash tests/run_all_tests.sh` -> 7/7 suites PASSED
   - `python3 tests/verify_production_runtime.py` -> 100% OK, Rule 34 invariant verified

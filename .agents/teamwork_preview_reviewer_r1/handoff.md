# Handoff Report: Adversarial Review & Hardening of `/tablist` Multi-Tier Detection

## Observation
An adversarial review of the prior implementation (Round 0) revealed several functional bugs and edge case failures in username extraction and config fallback:
1. **Quoted / Stringified LocalStorage Values in `appStorage.json`**:
   Roblox and Android LocalStorage often serialize string values as JSON strings (e.g. `{"Username": "\"RealUser\""}` or `{"RobloxUsername": "'Player1'"}`). In r0, `extract_username_from_text` checked raw strings with strict alphanumeric regex `^[a-zA-Z0-9_]{3,30}$` without stripping outer quotes, causing extraction to return `None`.
2. **Signed-out Historical Accounts in `PreviousAccountsList` Leaking / Overriding Active Users**:
   When Roblox account switcher saves `PreviousAccountsList` (e.g. `{"PreviousAccountsList": "[{\"Username\": \"SignedOut1\"}]", "Username": "\"ActiveUser\""}`), the r0 regex fallback scanned the entire string left-to-right, extracting the signed-out account `SignedOut1` instead of `ActiveUser`. Furthermore, when a tab was logged out (only `PreviousAccountsList` present), r0 falsely extracted the signed-out user instead of reporting `None` or falling back to `acc.txt`.
3. **Nested and Stringified JSON Objects**:
   In `appStorage.json`, user objects can be nested or stringified (e.g. `{"CurrentUser": {"name": "NestedUser"}}` or `{"CurrentUser": "{\"Username\": \"StringNested\"}"}`). In r0, `isinstance(v, str)` skipped dict objects and failed on stringified dicts.
4. **Dotted and Namespaced LocalStorage Keys**:
   HTML5 LocalStorage keys with dotted namespaces (e.g. `{"Roblox.CurrentUser.Username": "Hero77"}`) were missed by both preferred keys and step 3 regex.
5. **XML Shared Preferences Quotes and HTML Entities**:
   Preferences containing quotes or HTML entities (e.g. `<string name="Username">"SomeUser"</string>` or `&quot;SomeUser&quot;`) failed the regex capture group.
6. **Dumpsys Activity Multi-Line Intent Extras Dropped**:
   In Android `dumpsys activity`, intent extras (e.g. `extras: Bundle[{username=RealPlayer}]`) appear on indented continuation lines under the `ActivityRecord`. In r0, `[line for line in dumpsys_out.splitlines() if pkg in line]` discarded all continuation lines because they did not repeat the package name.
7. **Double `su -c` Nesting in `run_adb_shell`**:
   When called with `raw_cmd = "su -c 'cat ...'"`, r0 fallback shells wrapped it into `["/system/bin/su", "-c", "su -c 'cat ...'"]`, which fails when `su` is not in default PATH.
8. **Leading Zero Section Mismatches and Comments in `acc.txt`**:
   Device IDs like `m077` failed to match `M77___(gag2)`. Furthermore, comment lines (e.g. `# Note: do not use`) inside `acc.txt` were counted as accounts, skewing tab indexing.
9. **Potential `ValueError` in `format_tab_list_html`**:
   Non-integer or string tab indices (e.g. `{"tab": "?"}`) threw `ValueError` when sorting.

## Logic Chain
1. **`agent/agent.py`**:
   - `extract_username_from_text`:
     - Added `_validate_username` helper that unescapes HTML entities, strips JSON-stringified quotes/slashes, and validates format `^[a-zA-Z0-9_]{3,30}$`.
     - Added `_extract_from_dict` recursive helper (up to depth 3) to inspect nested dicts, stringified JSON dicts, and keys (`name`, `Name`, `user`, `User`) when nested under user objects.
     - Enhanced structured JSON parser with `json.JSONDecoder().raw_decode` fallback to handle concatenated JSON or shell warnings.
     - Explicitly checks for signed-out state: if structured JSON contains `PreviousAccountsList` and no active user, cleanly returns `None`.
     - Strips `PreviousAccountsList` from text using regex before running regex fallbacks, preventing historical accounts from leaking.
     - Updated XML regex to handle optional quotes and `&quot;` entities.
     - Updated JSON regex to match dotted namespace keys (`Roblox.CurrentUser.Username`).
   - `get_acc_fallback_username`:
     - Added integer device number normalization (`m077` -> 77 -> matches `m77` section regardless of leading zeros).
     - Filters out comment and invalid lines when mapping Tab N (`tab_num - 1`) to ensure 1:1 alignment with actual accounts.
   - `run_adb_shell`:
     - Added unwrapping for commands starting with `su -c` so fallback shells run `["/system/bin/su", "-c", inner_cmd]` without double nesting.
   - `query_tab_list`:
     - Enhanced Tier 3 (dumpsys) to capture up to 25 indented continuation lines under matching activity records, preserving intent bundle extras.
     - Added optional `links_path` parameter and propagated to `get_server_links_fallback_username`.
   - `format_tab_list_html`:
     - Replaced strict `int()` in sort key with safe `_sort_key` to avoid `ValueError` on non-integer tab values.
   - `handle_incoming_batch_action`:
     - Passes `links_path=links_path` to `query_tab_list`.

2. **`agent/tests/test_tablist.py`**:
   - Added 7 new adversarial unit tests:
     - `test_extract_username_quoted_and_stringified_json` (quoted JSON, single quotes, dotted keys, nested dicts, stringified dicts)
     - `test_extract_username_previous_accounts_isolation` (signed-out accounts isolated from active accounts, logged-out returns None)
     - `test_extract_username_xml_quoted_and_entities` (quotes and &quot; in XML)
     - `test_query_tab_list_tier3_multiline_dumpsys_intent_extras` (multiline dumpsys extras parsing)
     - `test_get_acc_fallback_username_leading_zero_and_comments` (m077 section matching, comment skipping)
     - `test_format_tab_list_html_non_int_tabs` (safe sorting on non-integer tab keys)
     - `test_run_adb_shell_su_prefix_handling` (unnested su execution)
   - Total tests increased from 19 to 26 (100% pass).

## Verification Record
- **Unit Tests (`test_tablist.py`)**:
  `python3 -m unittest agent/tests/test_tablist.py` -> 26/26 passed in 0.293s.
- **Production Runtime Verification (`verify_production_runtime.py`)**:
  `python3 tests/verify_production_runtime.py` -> 8/8 steps passed (100% OK).
- **Full Test Suite (`run_all_tests.sh`)**:
  `bash tests/run_all_tests.sh` -> 7/7 suites passed (55 device agent tests).
- **Rule 34 Dual-Storage Invariance**:
  SHA-256 verified identical:
  - `acc.txt`: `2db35ee2c4e059515f2a02880dccd3949457f176744490fe675b2bca42114fc9`
  - `Data_Tong_Cookies.txt`: `20528d6d1b0126ac8752e23b8d52236fd04400c2d4e81ed5e756af0b2670822c`

## Caveats / Known Issues / Unverified Aspects
- **Minor Robustness Risk**: On a locked-down Android device where `/data/data/` is strictly unreadable (no root / no run-as), the fallback will map Tab N to account N in `acc.txt` with suffix `(acc.txt)`. If the user manually logged into a different account on that tab, the physical account cannot be discovered without app data access. This is intended per R2.
- **Unverified Aspects**: Execution on a physical M77 hardware phone (simulated via Linux container test harness with mock ADB / root shell / file hierarchies).

## Code Diff Summary
- `agent/agent.py`: Upgraded `extract_username_from_text`, `run_adb_shell`, `get_acc_fallback_username`, `query_tab_list`, `format_tab_list_html`, and `handle_incoming_batch_action`.
- `agent/tests/test_tablist.py`: Added 7 adversarial unit tests covering quoted JSON, nested structures, signed-out account isolation, multiline dumpsys extras, and robust fallback matching.

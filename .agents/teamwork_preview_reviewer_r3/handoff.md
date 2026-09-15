# Handoff Report: Adversarial Review & Hardening Round 3 (`/tablist` Multi-Tier Detection)

## Observation
An independent adversarial review of Round 2 identified 8 distinct vulnerabilities, edge-case regressions, and missing fallbacks across `agent/agent.py` and its test harness:

1. **Leaking of Signed-out / Historical Accounts in Unquoted or Corrupted `PreviousAccountsList` Streams**:
   - **Input**: `PreviousAccountsList: {"111": {"username": "Old1"}, "222": {"username": "Old2"}}` (nested JSON dictionary without outer `{` or truncated stream from shell concatenation).
   - **Expected**: `None` (no active user).
   - **Actual**: `"Old2"` extracted as active user.
   - **Root Cause**: `cleaned_text` regex used flat non-greedy brace matching `\{[^\}]*\}`, which only stripped up to the first closing brace `}`. The remainder of the historical accounts object was left in `cleaned_text`, causing downstream JSON regex fallbacks to falsely extract the second historical account.
2. **Dumpsys Activity Analysis Premature Truncation on Blank Lines (Tier 3)**:
   - **Input**: `dumpsys` activity output containing an empty/blank line between the `ActivityRecord`/`TaskRecord` header and child `Intent` / `extras` lines.
   - **Expected**: Username successfully extracted from `Intent { ... extras: Bundle[{username=BlankLinePlayer}] }`.
   - **Actual**: `None`.
   - **Root Cause**: `line.startswith(("    ", "\t", "  "))` evaluated to `False` on the blank line `""`, immediately setting `capturing = False` and dropping all subsequent indented `Intent` bundle lines.
3. **Missing Key Patterns in Key-Value Activity Analysis (`kv_patterns`)**:
   - **Input**: `Intent extras: Bundle[{user_name=Player1}]` or `Bundle[{roblox_user=Player1}]` or `Bundle[{current_username=Player1}]`.
   - **Expected**: `"Player1"`.
   - **Actual**: `None`.
   - **Root Cause**: `kv_patterns` regex in `extract_username_from_text` only checked `\busername|\broblox_?username|\baccount_?name|\bdisplay_?name|\bscreen_?name`. Key variants `user_name`, `roblox_user`, and `current_username` were omitted from KV patterns despite being present in JSON patterns.
4. **Unsafe Quote Stripping in `run_adb_shell` Corrupting Chained Commands**:
   - **Input**: `su -c "'echo 1' && 'echo 2'"`.
   - **Expected**: Inner command preserved as `'echo 1' && 'echo 2'`.
   - **Actual**: Corrupted to `echo 1' && 'echo 2` with unbalanced quotes.
   - **Root Cause**: Naive `inner_cmd.startswith("'") and inner_cmd.endswith("'")` sliced `[1:-1]` across multiple quoted tokens instead of verifying that the entire string was wrapped in a single enclosing quote pair.
5. **`get_acc_fallback_username` Matching Failure on Non-Standard Device IDs in Plain Username Files**:
   - **Input**: `device_id="device-77"` or `"m077"` or `"77"` when `acc.txt` contains plain usernames without colons under header `M77___(gag2)`.
   - **Expected**: Fallback account from section M77 (`username (acc.txt)`).
   - **Actual**: `None`.
   - **Root Cause**: `header_pattern` only searched for `re.escape(norm_dev)` where `norm_dev` was `"device-77"` or `"m077"`, failing to match `M77___`.
6. **Missing System PATH Augmentation in `run_adb_shell`**:
   - **Root Cause**: In Termux / restricted Android environments where `PATH` lacks `/system/bin` or `/system/xbin`, subshells and fallback binaries (`su`, `sh`, `cat`, `run-as`) could fail with command not found errors.
7. **Roblox Legacy/Direct `files/appStorage.json` Path Missing from Tiers 0 and 1**:
   - **Root Cause**: Tiers 0 and 1 only checked `files/appData/LocalStorage/appStorage.json`, omitting legacy or flat layout `files/appStorage.json`.
8. **Missing Tab-Index Support in `get_server_links_fallback_username`**:
   - **Root Cause**: Only package names were matched against column 0; lines configured by tab index (`1,https://...,user`) were ignored.

## Logic Chain
1. **`agent/agent.py`**:
   - `run_adb_shell`:
     - Augments execution environment `PATH` with `/system/bin`, `/system/xbin`, `/vendor/bin`, `/sbin`, and Termux bin paths.
     - Safe quote stripping: only unwraps quotes when the inner command is strictly enclosed in a single pair of quotes (`"'" not in inner_cmd[1:-1]`).
   - `extract_username_from_text`:
     - Added `_strip_historical_blocks` balanced-bracket parsing for nested `PreviousAccountsList` blocks (`previousaccountslist`, `previousaccounts`, `savedaccounts`, `accountshistory`) to eliminate leaks of signed-out historical usernames even in raw/unquoted text.
     - Added `"User"`, `"user"` to `preferred_keys` in `_extract_from_dict`.
     - Expanded `kv_patterns` regex to match `\buser_name|\broblox_?user|\bcurrent_?username`.
   - `get_acc_fallback_username`:
     - Extended device ID resolution to inspect `/storage/emulated/0/Download/Shouko/config.json` (`device_name` / `device_id`).
     - Normalizes device ID variations (`device-77`, `m077`, `77`) to match `m{dev_num}` patterns in plain username fallback scans.
     - Prevents duplicate `(acc.txt)` suffixing.
   - `get_server_links_fallback_username`:
     - Added tab-index matching (`str(t_num)`, `tab {t_num}`).
   - `query_tab_list`:
     - Added `files/appStorage.json` to candidate direct files (Tier 0) and shell command arguments (Tier 1).
     - Added `run-as {pkg} cat files/appStorage.json` and multi-user `run-as --user {uid}` queries.
     - Made Tier 3 dumpsys activity line processing skip empty lines (`if not line.strip(): continue`) and accept standard whitespace indentations (`line.startswith((" ", "\t"))`).

2. **`agent/tests/test_tablist.py`**:
   - Added 8 new adversarial unit tests:
     - `test_extract_username_nested_historical_blocks_no_leak`
     - `test_extract_username_user_dict_and_user_name`
     - `test_extract_username_kv_patterns_user_name_and_roblox_user`
     - `test_query_tab_list_tier3_dumpsys_blank_lines_inside_block`
     - `test_run_adb_shell_safe_unquoting_chained_quotes`
     - `test_get_acc_fallback_username_device_variations_plain_acc`
     - `test_query_tab_list_direct_files_appstorage_fallback`
     - `test_get_server_links_fallback_tab_index_mapping`
   - Total tests increased from 34 to 42 (100% pass).

## Verification Record
- **Unit Tests (`test_tablist.py`)**:
  `python3 -m unittest agent/tests/test_tablist.py` -> 42/42 passed in 0.426s.
- **Production Runtime Verification (`verify_production_runtime.py`)**:
  `python3 tests/verify_production_runtime.py` -> 8/8 steps passed (100% OK).
- **Full Test Suite (`run_all_tests.sh`)**:
  `bash tests/run_all_tests.sh` -> 7/7 suites passed (71 device agent tests, up from 63).
- **Rule 34 Dual-Storage Invariance**:
  SHA-256 verified identical:
  - `acc.txt`: `2db35ee2c4e059515f2a02880dccd3949457f176744490fe675b2bca42114fc9`
  - `Data_Tong_Cookies.txt`: `20528d6d1b0126ac8752e23b8d52236fd04400c2d4e81ed5e756af0b2670822c`

## Code Diff Summary
- `agent/agent.py`:
  - `run_adb_shell`: PATH injection, safe quote unquoting.
  - `extract_username_from_text`: balanced bracket historical block stripper, `"user"` in `preferred_keys`, expanded `kv_patterns`.
  - `get_acc_fallback_username`: `config.json` resolution, device variations pattern matching, duplicate suffix guard.
  - `get_server_links_fallback_username`: tab index line parsing.
  - `query_tab_list`: `files/appStorage.json` paths, multi-user `run-as`, blank line tolerance in dumpsys parser.
- `agent/tests/test_tablist.py`:
  - 8 new unit tests covering all edge cases.

## Caveats / Known Issues / Unverified Aspects
- **Minor Robustness Risk**: When app data is blocked by strict Android sandbox permissions and `acc.txt` contains fewer accounts than running tabs, tabs beyond the account count will display `❓ (unknown)` rather than guessing. This is intended per R2.
- **Unverified Aspects**: Physical M77 hardware execution across mobile carrier networks (verified via Linux container runtime with mock ADB / root shell / file hierarchies).

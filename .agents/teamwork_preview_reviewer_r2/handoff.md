# Handoff Report: Adversarial Review & Hardening Round 2 (`/tablist` Multi-Tier Detection)

## Observation
An adversarial review of Round 1 revealed several functional bugs and edge-case failures in multi-tier username detection, multi-user Android environments, and fallback handling:

1. **Concatenated JSON Streams / Multi-User Stream Truncation**:
   When reading multi-user appStorage files (e.g. user 0 has logged-out historical state, and user 10 has an active user), `cat` outputs multiple JSON objects:
   `{"PreviousAccountsList": "[{\"Username\": \"OldUser\"}]"}{"Username": "ActiveUser10"}`.
   In r1, `json.JSONDecoder().raw_decode` decoded only the first JSON object. Because the first object contained `PreviousAccountsList` with no active user, the parser executed `return None` immediately, completely ignoring subsequent JSON objects in the stream and failing to extract `ActiveUser10`.
2. **Dumpsys Activity Premature `break` in Tier 3**:
   When `pkg` appeared in an earlier activity block (such as `mResumedActivity` or `mFocusedActivity`) that had > 25 indented lines before the actual `ActivityRecord` / `Intent { extras: Bundle[{username=HiddenPlayer}] }`, `if len(pkg_lines) > 25: break` broke out of the entire `for line in lines:` loop. The actual `ActivityRecord` and Intent extras were never inspected, returning `None`.
3. **Unhandled `TypeError` on Non-String / Non-Path `acc_path`**:
   If `acc_path` was passed as a dict or non-path object (e.g. `{"path": "/tmp"}`), `pathlib.Path(acc_path)` crashed with `TypeError: argument should be a str or an os.PathLike object`.
4. **Unhandled `TypeError` on String / Non-Integer `tab_num`**:
   In `get_acc_fallback_username`, `if tab_num < 1:` crashed with `TypeError: '<' not supported between instances of 'str' and 'int'` when `tab_num` was passed as a string like `"1"`.
5. **Crash in `format_tab_list_html` on `None` or Non-Dict Elements**:
   If `tabs` contained `None` or non-dict items (e.g. `[None, {"tab": 1}]`), `_sort_key` crashed with `AttributeError: 'NoneType' object has no attribute 'get'`.
6. **Missing Direct `su` Binary Execution in `run_adb_shell`**:
   When `run_adb_shell` was invoked with `/system/bin/su -c '...'` or `/system/xbin/su -c '...'` and `adb` was unavailable, `fallback_shells` only tried `["sh", "-c", raw_cmd]`. It never directly invoked `["/system/bin/su", "-c", inner_cmd]` or `["/system/xbin/su", "-c", inner_cmd]`, failing on systems where `/system/bin/su` wasn't in `/bin/sh`'s default PATH or where `/system/xbin/su` was the active root binary.
7. **Missing Explicit User Paths in Shell Commands (Tiers 1 & 2)**:
   When `/data/data` was inaccessible and `/data/user` had mode `0711` (directory listing forbidden, so wildcard `*` globbing failed), `cat /data/user/*/...` failed. Explicit user paths `/data/user/0/...` and `/data/user/10/...` were omitted from shell command arguments.
8. **Historical Accounts Leaking from XML Shared Preferences**:
   XML regexes matched `<string name="PreviousUsername">SignedOutUser</string>` because they did not check for historical keywords like `previous`, `old`, `last`.
9. **Stray Control Characters and UTF-16LE Null Bytes**:
   Null bytes `\x00` from UTF-16 streams or unescaped control characters inside JSON strings caused `json.loads` to raise `JSONDecodeError`.
10. **UTF-8 BOM in `acc.txt`**:
    Files starting with UTF-8 BOM `\ufeffM77___` failed to match regex `^\s*([Mm]\d+)` because `\ufeff` is not matched by `\s`.
11. **`acc_path` Parameter Propagation**:
    `handle_incoming_batch_action` did not extract or pass `acc_path` from incoming `TAB_LIST` messages.

## Logic Chain
1. **`agent/agent.py`**:
   - `extract_username_from_text`:
     - Strips unprintable control characters and null bytes (`[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]`).
     - Added decoder loop with `JSONDecoder(strict=False)` to iterate through all JSON objects in the stream, extracting active usernames from any valid object in concatenated multi-user outputs.
     - Only declares logged-out state if all decoded JSON objects have no active user and historical accounts are present with no active user in XML.
     - Updated XML patterns with named groups `(?P<key>...)` and `(?P<val>...)` to avoid attribute order inversion bugs, and explicitly rejects historical/signed-out key attributes (`previous`, `signout`, `history`, `last_logged`, `old_user`).
   - `get_acc_fallback_username`:
     - Safely converts `tab_num` via `int(tab_num)` with try/except.
     - Type-checks `acc_path` (`isinstance(..., (str, pathlib.Path))`) inside try/except.
     - Reads files with `encoding="utf-8-sig"` to strip UTF-8 BOM.
     - Added secondary parser fallback for plain username lines without colons in `acc.txt`.
   - `get_server_links_fallback_username`:
     - Safely converts `tab_num` and type-checks `links_path`.
     - Reads files with `encoding="utf-8-sig"`.
   - `format_tab_list_html`:
     - Filters out `None` and non-dict elements (`valid_tabs = [t for t in tabs if isinstance(t, dict)]`).
     - Guards against dict/list `username` values.
     - Implements Telegram 3900-char message boundary truncation (`... và còn N tab khác`).
   - `run_adb_shell`:
     - Extracts `inner_cmd` for any prefix matching `^(?:(?:/system/bin/|/system/xbin/)?su\s+-c\s+)(.*)$`.
     - Direct-executes `["/system/bin/su", "-c", inner_cmd]`, `["/system/xbin/su", "-c", inner_cmd]`, and `["su", "-c", inner_cmd]`.
   - `query_tab_list`:
     - Dynamically resolves package-to-user-ID mapping from dumpsys and `ps` (e.g. user 0, user 10).
     - Prioritizes matching user paths (`/data/user/{uid}/...`) in Tier 0 and Tier 1.
     - Adds explicit `/data/user/0/...` and `/data/user/10/...` paths to shell `cat` commands in Tier 1 and Tier 2.
     - Adds `run-as --user {user_id}` command fallback in Tier 1.
     - Fixes Tier 3 dumpsys parser: resets block line counter on matching lines and caps block lines at 30 without breaking out of the outer line loop.
   - `handle_incoming_batch_action`:
     - Extracts `message.get("acc_path")` and passes it to `query_tab_list`.

2. **`agent/tests/test_tablist.py`**:
   - Added 8 new adversarial unit tests:
     - `test_extract_username_concatenated_json_multi_user`
     - `test_extract_username_null_bytes_and_control_chars`
     - `test_extract_username_xml_historical_tags_rejected`
     - `test_query_tab_list_tier3_dumpsys_non_breaking_blocks`
     - `test_get_acc_fallback_username_type_robustness`
     - `test_format_tab_list_html_robustness_and_limits`
     - `test_query_tab_list_multi_user_paths_resolution`
     - `test_run_adb_shell_xbin_and_bin_su_commands`
   - Total tests increased from 26 to 34 (100% pass).

## Verification Record
- **Unit Tests (`test_tablist.py`)**:
  `python3 -m unittest agent/tests/test_tablist.py` -> 34/34 passed in 1.261s.
- **Production Runtime Verification (`verify_production_runtime.py`)**:
  `python3 tests/verify_production_runtime.py` -> 8/8 steps passed (100% OK).
- **Full Test Suite (`run_all_tests.sh`)**:
  `bash tests/run_all_tests.sh` -> 7/7 suites passed (63 device agent tests, up from 55).
- **Rule 34 Dual-Storage Invariance**:
  SHA-256 verified identical:
  - `acc.txt`: `2db35ee2c4e059515f2a02880dccd3949457f176744490fe675b2bca42114fc9`
  - `Data_Tong_Cookies.txt`: `20528d6d1b0126ac8752e23b8d52236fd04400c2d4e81ed5e756af0b2670822c`

## Caveats / Known Issues / Unverified Aspects
- **Minor Robustness Risk**: When app data is blocked by strict Android sandbox permissions and `acc.txt` contains fewer accounts than running tabs, tabs beyond the account count will cleanly display `❓ (unknown)` rather than guessing. This is by design per R2.
- **Unverified Aspects**: Physical M77 hardware execution in a production mobile carrier network (verified via simulated Linux container runtime and mock ADB / root shell / file hierarchies).

## Code Diff Summary
- `agent/agent.py`: Multi-object JSON decoding, control char / null-byte sanitization, named group XML historical filtering, type-safe fallback functions, multi-user Android path resolution, non-breaking dumpsys block parsing, unnested su commands.
- `agent/tests/test_tablist.py`: Added 8 new unit tests covering multi-user concatenated JSON, null bytes, XML historical tags, dumpsys non-breaking blocks, type robustness, and format limits.

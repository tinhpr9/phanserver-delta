# Handoff Report: Multi-Tier Username Detection & Config Fallback for `/tablist`

## Observation
- On device M77, `/tablist` previously rendered `❓ (unknown)` because:
  1. The Roblox username is stored in `/data/data/{pkg}/files/appData/LocalStorage/appStorage.json` (and multi-user variants `/data/user/*/{pkg}/files/appData/LocalStorage/appStorage.json`). Previously, `query_tab_list()` only attempted `cat /data/data/{pkg}/files/*.json`, which failed to reach files inside subdirectories like `appData/LocalStorage/`.
  2. In sandboxed or non-root Android environments, direct file access to `/data/data/{pkg}` is rejected with `Permission denied`. Previously, `run_adb_shell` only tried `adb shell`, `sh -c`, and `su -c` without falling back to `/system/bin/su`, `/system/xbin/su`, or `run-as {pkg}`.
  3. When all device app data reads failed, `agent/agent.py` had no correlation fallback mechanism to look up the assigned Roblox account from `/storage/emulated/0/Download/Shouko/acc.txt` for the current device section (e.g. `M77___(gag2)`), leaving the username as `None`, which the worker formatted as `❓ (unknown)`.

## Logic Chain & Implementation
1. **`agent/config.py`**:
   - Defined `DEFAULT_ACC_TXT_PATH = pathlib.Path("/storage/emulated/0/Download/Shouko/acc.txt")` alongside existing configuration paths.

2. **`agent/agent.py`**:
   - Enhanced `run_adb_shell()`: Added multiple trial shell binaries `["sh", "-c"]`, `["su", "-c"]`, `["/system/bin/su", "-c"]`, `["/system/xbin/su", "-c"]`.
   - Upgraded `extract_username_from_text()`: Added structured JSON parsing first (inspecting `Username`, `RobloxUsername`, `CurrentUsername`, `username`, `roblox_username`, `DisplayName`, etc. while ignoring signed-out historical accounts in `PreviousAccountsList`), followed by XML regex, escaped JSON quote regex, and dumpsys key-value patterns.
   - Added `get_acc_fallback_username(tab_num, device_id, acc_path)`: Resolves device ID (via argument, `config.load_device_id()`, `DEVICE_ID` env, or agent config), loads `acc.txt` (via explicit path, `config.DEFAULT_ACC_TXT_PATH`, or Shouko folder), parses sections via `account_manager.parse_acc_sections()`, finds the device section (e.g. `m77`), and maps Tab N (`tab_num - 1`) to account N, returning `f"{username} (acc.txt)"`.
   - Added `get_server_links_fallback_username(tab_num, pkg, links_path)`: Fallback reading of `server_links.txt` if username is present.
   - Added `format_tab_list_html(device_id, tabs)`: Formats Telegram HTML identically to `worker/fleet_state.js`, escaping `&`, `<`, `>` with `quote=False`.
   - Upgraded `query_tab_list(device_id=None, acc_path=None)`:
     - Tier 0: Direct filesystem read via Python `Path.read_text()` for `appStorage.json` and `shared_prefs/*.xml`.
     - Tier 1: Multi-command read of `appStorage.json` via `cat`, `su -c`, `/system/bin/su -c`, `/system/xbin/su -c`, and `run-as {pkg} cat files/appData/LocalStorage/appStorage.json`.
     - Tier 2: Multi-command read of `shared_prefs/*.xml` and app files.
     - Tier 3: `dumpsys activity` analysis.
     - Tier 4: Config fallback to `acc.txt` (and `server_links.txt`), yielding `username (acc.txt)` if app data is blocked. Real usernames read from app data retain priority over fallback.
     - Also added `/proc` cmdline discovery fallback when dumpsys and ps return empty.
   - Updated `handle_incoming_batch_action()`: Passes `device_id=device_id` into `query_tab_list(device_id=device_id)` when handling `TAB_LIST`.

3. **`agent/tests/test_tablist.py`**:
   - Added 9 new unit tests covering all tiers (appStorage structure, su/run-as shell commands, acc.txt fallback correlation, priority of real username over fallback, index boundary, Telegram HTML formatting/escaping, multi-su fallback, and server_links fallback). Total tests increased from 10 to 19 (100% pass).

## Verification Record
- **Unit Tests (`test_tablist.py`)**:
  `python3 -m unittest agent/tests/test_tablist.py` -> 19/19 passed in 0.358s.
- **Agent Test Suite (`agent/tests`)**:
  `python3 -m unittest discover -s agent/tests` -> 48/48 passed in 4.807s.
- **Production Runtime Verification (`verify_production_runtime.py`)**:
  `python3 tests/verify_production_runtime.py` -> 8/8 steps passed (100% OK).
- **Full Test Suite (`run_all_tests.sh`)**:
  `bash tests/run_all_tests.sh` -> 7/7 suites passed (test_tong_hop_link, test_telegram_phanserver, test_fleet_state_2pc, delta updater, device agent, account manager & moveacc, E2E flow).
- **Rule 34 Dual-Storage Invariance**:
  SHA-256 verified identical before and after:
  - `acc.txt`: `2db35ee2c4e059515f2a02880dccd3949457f176744490fe675b2bca42114fc9`
  - `Data_Tong_Cookies.txt`: `20528d6d1b0126ac8752e23b8d52236fd04400c2d4e81ed5e756af0b2670822c`

## Caveats / Known Issues / Unverified Aspects
- **Minor Robustness Risk**: On a live device where the physical Roblox user has logged into a completely different account than the one provisioned in `acc.txt`, and `/data/data/` is strictly unreadable (sandbox mode without root/run-as), the fallback will display the provisioned account name with `(acc.txt)` indicator rather than the physical account. This is by design per R2 ("fallback ánh xạ Tab N với tài khoản tương ứng trong phần cấu hình của thiết bị trong acc.txt... hiển thị username (acc.txt)").
- **Unverified on Real Hardware**: Physical ADB execution on an actual physical M77 device was not performed (tests executed in the containerized verification environment where ADB shell and mock file structures simulate root/non-root environments).

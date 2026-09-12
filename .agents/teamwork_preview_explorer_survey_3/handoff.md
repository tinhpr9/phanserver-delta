# Handoff Report: Roblox Ban Detection & Telegram Bot Control (R1 & R4)

**Explorer**: Explorer 3 (Ban Detection & Bot Explorer)  
**Date**: 2026-09-12T15:41:30Z  
**Target Repo**: `/root/phanserver-delta`  
**Working Directory**: `/root/phanserver-delta/.agents/teamwork_preview_explorer_survey_3`

---

## 1. Observation

### 1.1 Roblox Ban Detection Architecture & Implementation
* **File**: `/root/phanserver-delta/agent/account_manager.py`
  * **Endpoints**:
    * Line 27: `ROBLOX_BATCH_USERNAMES_URL = "https://users.roblox.com/v1/usernames/users"`
    * Line 28: `ROBLOX_USER_DETAIL_URL = "https://users.roblox.com/v1/users/{userId}"`
  * **Network Helper & HTTP 429 Backoff**:
    * Lines 90–121 (`query_roblox_api`):
      ```python
      def query_roblox_api(url, method="GET", data=None, retries=3):
          ...
          for attempt in range(retries):
              try:
                  req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
                  with urllib.request.urlopen(req, timeout=10) as resp:
                      return json.loads(resp.read().decode("utf-8"))
              except urllib.error.HTTPError as e:
                  if e.code == 429 and attempt < retries - 1:
                      # Rate limited, backoff
                      time.sleep(1.0 * (attempt + 1))
                      continue
                  if e.code == 404:
                      return None
                  if attempt == retries - 1:
                      raise
              except Exception:
                  if attempt == retries - 1:
                      raise
                  time.sleep(0.5)
      ```
      *Observation*: The 429 backoff is linear (`1.0 * (attempt + 1)`, 1s, 2s). It does not parse the HTTP `Retry-After` header.
  * **Batching to `v1/usernames/users`**:
    * Lines 144–157:
      ```python
      chunk_size = 100
      for i in range(0, len(unique_usernames), chunk_size):
          chunk = unique_usernames[i:i + chunk_size]
          payload = {"usernames": chunk, "excludeBannedUsers": False}
          try:
              resp = query_roblox_api(ROBLOX_BATCH_USERNAMES_URL, method="POST", data=payload)
              if resp and "data" in resp:
                  for item in resp["data"]:
                      req_name = item.get("requestedUsername", "").lower()
                      target_id = item.get("id")
                      actual_name = item.get("name")
                      if target_id:
                          name_to_id[req_name] = (target_id, actual_name)
      ```
      *Observation*: Batch chunk size is 100. `"excludeBannedUsers": False` is explicitly set to ensure banned users are resolved into user IDs.
  * **User Detail `isBanned` Classification**:
    * Lines 162–183:
      ```python
      def check_single_user(uname):
          uname_lower = uname.lower()
          if uname_lower not in name_to_id:
              return uname, {"isBanned": None, "id": None, "name": uname, "error": "USER_NOT_FOUND"}
          uid, real_name = name_to_id[uname_lower]
          try:
              detail_url = ROBLOX_USER_DETAIL_URL.format(userId=uid)
              detail = query_roblox_api(detail_url, method="GET")
              if detail:
                  is_banned = bool(detail.get("isBanned", False))
                  return uname, {"isBanned": is_banned, "id": uid, "name": real_name or uname, "error": None}
              return uname, {"isBanned": None, "id": uid, "name": uname, "error": "DETAIL_EMPTY"}
          except Exception as e:
              return uname, {"isBanned": None, "id": uid, "name": uname, "error": str(e)}

      with ThreadPoolExecutor(max_workers=max_workers) as executor:
          futures = {executor.submit(check_single_user, u): u for u in unique_usernames if u not in results}
          for future in as_completed(futures):
              uname, res = future.result()
              results[uname] = res
      ```
      *Observation*: `is_banned` is classified as `bool(detail.get("isBanned", False))`. Returns `isBanned: True` (Banned), `isBanned: False` (Live), or `isBanned: None` (Error / User not found).
  * **Quota-Guard Caching Status**:
    * *Observation*: **MISSING**. There is no cache dictionary, TTL timestamp tracking, or disk-backed cache in `account_manager.py` or anywhere in the repository. Every call to `check_roblox_ban_status` executes full HTTP calls for all queried usernames.
  * **On-Demand Execution (No Crons/Background Polling)**:
    * `/root/phanserver-delta/agent/agent.py` lines 598–633: `account_manager.run_full_checkban_pipeline` is only executed inside `if action == "CHECK_BAN":` when triggered by an incoming batch command.
    * `/root/phanserver-delta/wrangler.jsonc` lines 1–30 & `wrangler.toml` lines 1–18: No cron triggers or scheduled workers defined.
    * No system crontab exists (`crontab -l` returned empty/not found).
    * *Observation*: Zero automated background polling of Roblox API. All operations are strictly on-demand.

---

### 1.2 Telegram Bot Integration (`Preiumbot`, Cloudflare Worker & Durable Objects)
* **Worker Routing**:
  * `/root/phanserver-delta/worker/worker.js` line 72: Receives Telegram updates on `POST /telegram/webhook` and dispatches to `handleUpdate(update, env, fleetStub)`.
  * Line 53 in fallback manifest contains a syntax error / undefined variable:
    ```javascript
    debug_error: debugError,
    ```
    *Observation*: `debugError` is not defined in `worker/worker.js`. If GitHub API fails and triggers this fallback, a `ReferenceError` occurs.
* **Telegram Command Parsing (`worker/phanserver.js`)**:
  * Lines 508–511 (`/help` and `/start` text):
    ```html
    🛡️ <b>Quản lý Tài khoản (Roblox Ban & Add)</b>:
    • <code>/checkban [m_code|all|users]</code>: Quét Roblox API kiểm tra ban, tự dọn dẹp acc.txt & sync Drive (Rule 34)
    • <code>/addacc &lt;m_code&gt; &lt;user:pass...&gt;</code>: Nạp tài khoản vào dàn máy và sync Google Drive
    ```
  * Lines 531–585 (`/checkban` / `/kiemtraban` handler):
    * Strips command prefix to obtain `target = raw || "all"`.
    * Resolves online devices using `resolveAndValidateTelegramTargets("all", env, fleetState)`.
    * Picks matching device or first online device (`execDeviceId`).
    * Dispatches `POST /aot/hub/control` with `kind: "check_ban"`, `target_device_ids: [execDeviceId]`, `target: target`, `telegram_chat_id: chatId`.
    * Replies with immediate queuing confirmation:
      `🛡️ <b>ĐÃ XẾP LỆNH CHECK BAN ROBLOX</b>\n📱 Thiết bị thực thi: <code>${execDeviceId}</code>\n🎯 Mục tiêu: <b>${target.toUpperCase()}</b>...`
  * Lines 587–673 (`/addacc` / `/themacc` handler):
    * Parses tokens: `mCode = tokens[0]`, `accounts = tokens.slice(1)`.
    * Validates that at least one account contains `:`.
    * Dispatches `POST /aot/hub/control` with `kind: "add_acc"`, `target_device_ids: [execDeviceId]`, `m_code: mCode`, `lines: validAccounts`, `telegram_chat_id: chatId`.
    * Replies with immediate queuing confirmation:
      `➕ <b>ĐÃ XẾP LỆNH NẠP TÀI KHOẢN</b>\n📱 Thiết bị thực thi: <code>${execDeviceId}</code>...`
  * Line 138: Missing bot message check:
    ```javascript
    if (!from || !chatId) return;
    ```
    *Observation*: Rule 10 mandates `if (message?.from?.is_bot) return` to prevent webhook echo loops.
* **Durable Object Queueing & Acknowledgement (`worker/fleet_state.js`)**:
  * Lines 988–1029 (`queueCheckBan`):
    * Assigns action ID: `checkban-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`.
    * Pushes command with action `CHECK_BAN` to `fresh.pending_actions[id]` and `fresh.checkban_actions[actionId]`.
  * Lines 1031–1109 (`acknowledgeCheckBan`):
    * Updates action status (`OPENED`, `SUCCESS`, or `FAILED`).
    * Parses `details` JSON string from body.
    * Formats HTML report (lines 1067–1092):
      ```javascript
      msg = `🛡️ <b>KẾT QUẢ CHECK BAN ROBLOX</b>\n`;
      msg += `📱 Thiết bị thực thi: <code>${escapeHtml(deviceId)}</code>\n`;
      msg += `🎯 Mục tiêu: <b>${tgt}</b>\n`;
      msg += `📊 Tổng: <b>${total}</b> | 🟢 Sống: <b>${live}</b> | 🔴 Bị Ban: <b>${banned}</b>`;
      if (errCount > 0) msg += ` | ⚠️ Lỗi API: <b>${errCount}</b>`;
      msg += `\n`;
      if (banned > 0) {
        msg += `\n🔴 <b>Danh sách tài khoản bị Ban:</b>\n`;
        for (const u of bannedList) {
          msg += `• <code>${escapeHtml(u)}</code>\n`;
        }
        if (detailsObj.clean_result) {
          const removed = detailsObj.clean_result.removed_from_acc ?? banned;
          msg += `\n🧹 Đã tự động gỡ <b>${removed}</b> acc khỏi <code>acc.txt</code> & lưu trữ vào <code>acc_bi_ban.txt</code>.`;
        }
        if (detailsObj.sync_result) {
          if (detailsObj.sync_result.error) {
            msg += `\n⚠️ Google Drive sync lỗi: <code>${escapeHtml(detailsObj.sync_result.error)}</code>`;
          } else {
            msg += `\n☁️ <b>Google Drive</b>: Đã đồng bộ an toàn (Bảo toàn File ID gốc theo Rule 34).`;
          }
        }
      } else {
        msg += `\n✅ <b>Tất cả tài khoản đều HOẠT ĐỘNG TỐT (100% LIVE)!</b> Không phát hiện tài khoản nào bị ban.`;
      }
      ```
      *Observation 1*: Line 1080 expects `detailsObj.clean_result.removed_from_acc`. However, `clean_banned_accounts` in `account_manager.py` only returns `{"banned_count", "archived_cookies_count", "backup_acc"}`, causing `removed_from_acc` to be undefined and fall back to `banned`.
      *Observation 2*: Line 1091 declares "100% LIVE" even if `errCount > 0` (as long as `banned === 0`), which is inaccurate if some accounts had lookup errors.
    * Delivers HTML message via Telegram Bot API:
      `fetch("https://api.telegram.org/bot" + this.env.TELEGRAM_BOT_TOKEN + "/sendMessage", { ... parse_mode: "HTML" })`.
  * Lines 1111–1154 & 1156–1219 (`queueAddAcc` & `acknowledgeAddAcc`):
    * Queues `ADD_ACC` and on ACK sends HTML message reporting added accounts, cookies added, and Rule 34 Google Drive sync status.

---

### 1.3 CLI Entrypoints
* **File**: `/root/phanserver-delta/agent/account_manager.py` lines 487–511:
  ```python
  if __name__ == "__main__":
      if len(sys.argv) < 2:
          print("Usage:")
          print("  python3 -m agent.account_manager checkban <m_code|all|usernames>")
          print("  python3 -m agent.account_manager addacc <m_code> <user:pass...>")
          sys.exit(1)

      subcmd = sys.argv[1].lower()
      if subcmd in ("checkban", "check"):
          tgt = sys.argv[2] if len(sys.argv) > 2 else "m77"
          print(f"[*] Đang quét kiểm tra ban cho: {tgt}...")
          report = run_full_checkban_pipeline(tgt)
          print(json.dumps(report, indent=2, ensure_ascii=False))
      elif subcmd in ("addacc", "add"):
          if len(sys.argv) < 4:
              print("Cú pháp: python3 -m agent.account_manager addacc <m_code> <user:pass...>")
              sys.exit(1)
          m_code = sys.argv[2]
          lines = sys.argv[3:]
          res = add_accounts(m_code, lines)
          sync_res = sync_to_google_drive()
          print(json.dumps({"add": res, "sync": sync_res}, indent=2, ensure_ascii=False))
  ```
  *Observation*: Line 496 sets `tgt = sys.argv[2]`. If a user runs `python3 -m agent.account_manager checkban user1 user2 user3`, only `user1` is parsed and `sys.argv[3:]` are discarded.

---

### 1.4 Test Suite Baseline Verification
* Command: `./tests/run_all_tests.sh`
  * `[1/7] node tests/test_tong_hop_link.mjs` -> Passed (`TEST_TONG_HOP_LINK_EQUIVALENCE=OK`)
  * `[2/7] node tests/test_telegram_phanserver.mjs` -> Passed (`TEST_TELEGRAM_PHANSERVER_EQUIVALENCE=OK`)
  * `[3/7] node tests/test_fleet_state_2pc.mjs` -> Passed (`TEST_FLEET_STATE_2PC_EQUIVALENCE=OK`)
  * `[4/7] python3 -m unittest discover -s delta/tests` -> Passed (27 tests)
  * `[5/7] python3 -m unittest discover -s agent/tests` -> Passed (20 tests)
  * `[6/7] pytest -q tests/test_account_manager.py` -> Passed (5 tests)
  * `[7/7] python3 tests/test_e2e_flow.py` -> Passed (2 tests)
* Command: `python3 tests/verify_production_runtime.py`
  * All 7 steps passed cleanly.

---

## 2. Logic Chain

1. **On-Demand Guarantee**:
   * *Observation*: Neither `agent/agent.py` nor `worker/worker.js` contains any recurring cron triggers, intervals, or background worker threads that call Roblox API.
   * *Inference*: The requirement that ban detection is strictly on-demand (triggered exclusively by user Telegram command `/checkban` or CLI `checkban`) is completely satisfied in the existing code architecture.

2. **Roblox Ban Checking Completeness**:
   * *Observation*: `account_manager.py` splits usernames into batches of 100 with `"excludeBannedUsers": False`, queries `v1/usernames/users`, and then queries `v1/users/{userId}` for `isBanned`.
   * *Inference*: The 2-step lookup is mandatory because Roblox `v1/usernames/users` does not expose the `isBanned` field in its response. However, executing individual user lookups concurrently without a Quota-Guard cache results in repeated duplicate calls when users run `/checkban` multiple times within a short window.

3. **Quota-Guard Cache Deficit (R1 Gap)**:
   * *Observation*: `account_manager.py` has no caching mechanism (0 lines of code referencing a cache dictionary, TTL, or cache file).
   * *Inference*: Requirement R1 explicitly specifies: *"có bộ đệm kết quả (Quota-Guard Cache) ngắn hạn để ngăn chặn việc gọi lặp lại cùng một tài khoản khi người dùng kiểm tra nhiều lần liên tiếp."* Without a short-term TTL cache (e.g. 5–15 minutes), multiple `/checkban` requests will exhaust Roblox rate limits and waste network resources.

4. **CLI Usernames Truncation Bug**:
   * *Observation*: Line 496 in `account_manager.py` defines `tgt = sys.argv[2] if len(sys.argv) > 2 else "m77"`.
   * *Inference*: A command like `python3 -m agent.account_manager checkban user1 user2 user3` will only inspect `user1`. `user2` and `user3` will be ignored. Joining all remaining arguments (`" ".join(sys.argv[2:])`) resolves this issue.

5. **Cleaning Restriction on Username Lists**:
   * *Observation*: Line 468 in `account_manager.py` guards cleaning with:
     `if banned_list and (target_lower == "all" or re.match(r"^[Mm]\d+$", target_lower)):`.
   * *Inference*: When checking a specific username or list of usernames via `/checkban user1 user2` or CLI, any identified banned account is NOT purged from `acc.txt` or `Data_Tong_Cookies.txt`, even if that username exists in one of the machine sections. Cleaning should support purging identified banned accounts across `acc.txt` whenever found.

6. **Attribute Desynchronization in HTML Reporting (R4 Bug)**:
   * *Observation*: `worker/fleet_state.js` line 1080 expects `detailsObj.clean_result.removed_from_acc`. However, `clean_banned_accounts` returns:
     `{"banned_count": ..., "archived_cookies_count": ..., "backup_acc": ...}` without `removed_from_acc`.
   * *Inference*: `removed_from_acc` is undefined and falls back to `banned`. If a banned user was not present in `acc.txt`, the bot falsely claims it removed them. Counting and returning `removed_from_acc` in `clean_banned_accounts` aligns the agent with the Telegram reporting layer.

7. **Anti-Webhook Echo Loop & Worker Fallback Integrity**:
   * *Observation*: `worker/phanserver.js` line 138 does not filter `from.is_bot`. `worker/worker.js` line 53 references undefined `debugError`.
   * *Inference*: Adding `if (from.is_bot) return` satisfies Rule 10. Fixing `debugError` avoids `ReferenceError` during GitHub release fallback.

---

## 3. Caveats

1. **Roblox Official Rate Limits**: Roblox does not publish a guaranteed SLA for `users.roblox.com/v1/users/{userId}`. The observed community rate limit is approximately 60 requests/minute per IP. When checking large fleets (e.g. 100 accounts), inter-request delay or rate pacing (token bucket) plus Quota-Guard caching is essential to avoid HTTP 429 during bursts.
2. **Google Drive Sync Verification in Development Environment**: In development environments without real Google Drive credentials or `rclone` configured, `sync_to_google_drive` must be verified using mocked subprocess or local rclone config to prevent pipeline abortion.
3. **Automated Replacement (R3)**: While R1 and R4 are the primary scope of this exploration, auto-replacement from `acc_du_phong.txt` (R3) must be seamlessly integrated into `run_full_checkban_pipeline` so that cleaned slots can optionally be replenished.

---

## 4. Conclusion

The current codebase contains solid foundations for R1 and R4:
1. **Roblox API Ban Detection**: The 2-step query pipeline (`v1/usernames/users` batch chunk 100 with `excludeBannedUsers: False` -> `v1/users/{userId}` detail boolean extraction) correctly identifies `isBanned: True` (banned) and `isBanned: False` (live).
2. **Telegram Bot Control**: Both `/checkban [m_code|all|users]` and `/addacc <m_code> <user:pass...>` are cleanly mapped from Telegram webhook commands through Cloudflare Worker, dispatched via FleetState Durable Objects, pulled by device agents via heartbeat, executed atomically, and acknowledged with detailed HTML reporting.
3. **On-Demand Invariant**: Fully satisfied. No cron jobs or automatic background scanning exists.

However, the following specific gaps and bugs require implementation:
* **[Critical / R1] Implement Quota-Guard Cache**: Add a disk-backed / in-memory cache with configurable TTL (e.g. 300 seconds) in `agent/account_manager.py` that bypasses Roblox API calls for recently verified accounts.
* **[Medium / R1] Enhance 429 Backoff & Concurrency Pacing**: Upgrade linear backoff in `query_roblox_api` to exponential backoff (`2 ** attempt`), parse `Retry-After` HTTP headers, and add pacing to thread pool requests to prevent rate limit exhaustion.
* **[Medium / R4] Fix CLI Argument Parsing**: Update line 496 of `agent/account_manager.py` to `tgt = " ".join(sys.argv[2:])` to handle multi-username CLI invocations.
* **[Medium / R4] Fix `removed_from_acc` Return Value**: In `clean_banned_accounts`, compute and return `removed_from_acc: int` so `worker/fleet_state.js` renders accurate cleanup metrics in Telegram.
* **[Low / R4] Support Cleanup on Username Checks**: Allow `clean_banned_accounts` to remove banned accounts across `acc.txt` even when `target` is a list of usernames.
* **[Low / Rule 10 & Worker Stability]**: Add `if (from.is_bot) return` in `worker/phanserver.js` line 138, and fix undefined `debugError` in `worker/worker.js` line 53.

---

## 5. Verification Method

### 5.1 Project Test Suite Command
Run all existing unit and equivalence tests to confirm baseline integrity:
```bash
./tests/run_all_tests.sh
```
*Expected*: All 7 suites pass (100%).

### 5.2 Verification of Account Manager & Ban Checker
Execute pytest specifically on the account manager test suite:
```bash
pytest -v tests/test_account_manager.py
```
*Expected*: All tests pass.

### 5.3 Verification of Telegram Bot Flow
Execute node tests for Telegram command parsing and FleetState 2PC lifecycle:
```bash
node tests/test_telegram_phanserver.mjs
node tests/test_fleet_state_2pc.mjs
```
*Expected*: Output confirms `TEST_TELEGRAM_PHANSERVER_EQUIVALENCE=OK` and `TEST_FLEET_STATE_2PC_EQUIVALENCE=OK`.

### 5.4 Verification of Production Runtime
Execute the production verification script:
```bash
python3 tests/verify_production_runtime.py
```
*Expected*: Steps 1 through 7 complete with `ALL RUNTIME PRODUCTION VERIFICATIONS PASSED: 100% OK`.

### 5.5 Invalidation Conditions
The findings in this report will be invalidated if:
1. A background cron job or scheduled worker is added that autonomously queries Roblox API.
2. The batching logic in `check_roblox_ban_status` exceeds 100 usernames or omits `excludeBannedUsers: False`.
3. `isBanned` field classification logic is altered such that false positives or false negatives are produced.
4. Telegram HTML reporting in `fleet_state.js` fails to escape special characters (`&`, `<`, `>`) or drops sync status.

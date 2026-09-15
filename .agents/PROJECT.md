# Project: Roblox Ban Detection, Dual-Storage Isolation & Auto-Replacement

## Architecture
- **Agent Account Manager (`agent/account_manager.py`)**:
  - Roblox API Ban Checker: on-demand batch query (100 users/chunk) via `v1/usernames/users` with `excludeBannedUsers: false`, user detail query via `v1/users/{userId}`, `isBanned` classification.
  - Quota-Guard Cache: short-term TTL cache (300s) to prevent redundant Roblox API queries for repeated check requests.
  - 429 Backoff & Concurrency Pacing: exponential backoff with `Retry-After` header parsing.
  - Storage & Isolation: `.bak_<timestamp>` creation on both `acc.txt` and `Data_Tong_Cookies.txt`, extraction of banned cookies to `acc_bi_ban.txt`, logging to `nhat_ky_ban.txt`, clean removal from `acc.txt` and `Data_Tong_Cookies.txt`.
  - Section Parsing: regex for machine codes (e.g., `M77___(gag2)`) without matching account names like `Mega_Wiley623` or `M00nlUWarden...`, duplicate section header merging, unassigned top accounts preservation.
  - Reserve Pool Replacement: reads `acc_du_phong.txt`, extracts valid accounts, inserts into target machine section, updates `Data_Tong_Cookies.txt`, and syncs.
  - Rule 34 Google Drive Sync: in-place overwrite via `rclone copyto`, preserving 100% Google Drive File IDs (`12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg` for `acc.txt`, `1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B` for `Data_Tong_Cookies.txt`), with post-sync ID verification.
- **Worker & Durable Object (`worker/`)**:
  - `phanserver.js`: Telegram bot command router (`/checkban`, `/addacc`), anti-bot loop check (`from.is_bot`).
  - `fleet_state.js`: FleetState Durable Object managing 2PC, queuing actions, processing acknowledgements, HTML formatted Telegram report generation (`Tổng`, `Sống`, `Bị Ban`, `Lỗi API`, `removed_from_acc`, replacements, Google Drive sync status).
  - `worker.js`: Cloudflare worker entrypoint, fallback release manifest error fix.
- **Delta Updater & Agent Services (`delta/`, `agent/`)**:
  - 2PC server links and delta updates.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | On-Demand Roblox Ban Detection | Batch up to 100 usernames via `v1/usernames/users` & `/v1/users/{userId}`, accurate `isBanned` classification, strictly on-demand (no background crons) | M1 | R1 |
| 2 | Quota-Guard Cache & 429 Backoff | In-memory/disk TTL cache (300s) for ban results; exponential backoff handling 429 Too Many Requests & Retry-After | M1 | R1 |
| 3 | Dual-Storage Account Isolation | `.bak_<timestamp>` backup before modifying files; extract banned cookies to `acc_bi_ban.txt`; log to `nhat_ky_ban.txt`; remove from local `acc.txt` & `Data_Tong_Cookies.txt` | M1 | R2 |
| 4 | Rule 34 Google Drive File ID Preservation | In-place sync via `rclone copyto` preserving File IDs `12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg` and `1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B`; post-sync verification gate | M1 | R2 |
| 5 | Section Parsing & Cleanup Edge Cases | Robust regex rejecting non-section accounts like `Mega_Wiley623` and `M00nlUWarden...`; merging duplicate sections; top unassigned accounts support; username target cleaning | M1 | R2, R3 |
| 6 | Automated Replacement from Reserve Pool | Read `acc_du_phong.txt`, extract replacements, insert into designated machine section in `acc.txt` and `Data_Tong_Cookies.txt`, update reserve file, sync to Drive | M1 | R3 |
| 7 | Telegram Bot Control & Delivery | Commands `/checkban [m_code|all|users]`, `/addacc <m_code> <user:pass...>`, HTML report formatting with `removed_from_acc` and replacement counts | M2 | R4 |
| 8 | Worker Stability & Rule 10 Compliance | Anti-bot webhook echo prevention (`from.is_bot`), fix undefined `debugError` in `worker.js` release fallback | M2 | R4 |
| 9 | Comprehensive Verification & Testing Suite | 100% pass on `tests/run_all_tests.sh` (7/7 suites), zero errors on `tests/verify_production_runtime.py`, challenger stress testing & clean forensic audit | M3 | Acceptance |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Core Account Manager & Dual-Storage Engine (R1, R2, R3) | Implement Quota-Guard TTL cache, 429 backoff, dual backups, username list cleanup, Rule 34 post-sync verification, section parsing fixes, reserve pool auto-replacement (`acc_du_phong.txt`) in `agent/account_manager.py` and unit tests in `tests/test_account_manager.py` | None | DONE |
| M2 | Telegram Bot Control & Worker Integration (R4) | HTML report alignment (`removed_from_acc`, replacements), anti-bot loop check, worker fallback fix in `worker/fleet_state.js`, `worker/phanserver.js`, `worker/worker.js`, and `tests/test_telegram_phanserver.mjs` | M1 | DONE |
| M3 | Acceptance Verification & Forensic Integrity Audit | Run full 7/7 test suites, `verify_production_runtime.py`, Challenger adversarial stress tests, and Forensic Auditor integrity verification | M2 | DONE |

## Interface Contracts
### `agent.account_manager`
- `check_roblox_ban_status(usernames, max_workers=5, use_cache=True, cache_ttl=300)`:
  - Input: `list[str]` of usernames
  - Output: `dict[str, dict]` where value is `{"isBanned": bool | None, "id": int | None, "name": str, "error": str | None, "cached": bool}`
- `clean_banned_accounts(m_code_or_target, banned_usernames, base_dir=None)`:
  - Output: `{"banned_count": int, "removed_from_acc": int, "archived_cookies_count": int, "backup_acc": str, "backup_data_tong": str}`
- `replace_banned_accounts_from_reserve(m_code, num_needed, base_dir=None, reserve_accounts=None)`:
  - Output: `{"replaced_count": int, "replaced_accounts": list[str], "remaining_reserve_count": int}`
- `sync_to_google_drive(base_dir=None, verify_rule34=True)`:
  - Output: `{"acc_sync": bool, "data_tong_sync": bool, "rule34_verified": bool, "file_ids": dict}`
- `run_full_checkban_pipeline(target, base_dir=None, auto_replace=True)`:
  - Output: comprehensive report dict with ban stats, clean result, replace result, sync result.

### `worker.fleet_state` ↔ `agent.agent`
- Action: `CHECK_BAN`
  - Request: `{"action": "CHECK_BAN", "action_id": str, "target": str}`
  - Response ACK: `{"action_id": str, "result": "OPENED", "details": json_str}`
- Action: `ADD_ACC`
  - Request: `{"action": "ADD_ACC", "action_id": str, "m_code": str, "lines": list[str]}`
  - Response ACK: `{"action_id": str, "result": "OPENED", "details": json_str}`

## Code Layout
- `agent/account_manager.py`: Core ban checker, cache, storage isolation, reserve pool, sync
- `tests/test_account_manager.py`: Pytest suite for account manager
- `worker/fleet_state.js`: FleetState DO, actions queue, Telegram HTML reporting
- `worker/phanserver.js`: Telegram bot commands
- `worker/worker.js`: Cloudflare worker entrypoint
- `tests/run_all_tests.sh`: 7-suite test orchestrator
- `tests/verify_production_runtime.py`: Production verification script

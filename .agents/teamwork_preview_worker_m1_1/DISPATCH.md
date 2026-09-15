## 2026-09-12T15:42:39Z

You are Worker M1 (Account Engine Worker) implementing Milestone M1 in /root/phanserver-delta.
Your working directory is /root/phanserver-delta/.agents/teamwork_preview_worker_m1_1.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

MANDATORY: Read /root/phanserver-delta/.agents/ORIGINAL_REQUEST.md first.
Also read:
- /root/phanserver-delta/.agents/PROJECT.md
- /root/phanserver-delta/.agents/teamwork_preview_explorer_survey_1/handoff.md
- /root/phanserver-delta/.agents/teamwork_preview_explorer_survey_2/handoff.md
- /root/phanserver-delta/.agents/teamwork_preview_explorer_survey_3/handoff.md

Your exclusive write ownership:
- /root/phanserver-delta/agent/account_manager.py
- /root/phanserver-delta/tests/test_account_manager.py

Tasks:
1. Implement Quota-Guard TTL Cache (e.g., 300 seconds) in agent/account_manager.py for check_roblox_ban_status() so repeated lookups for the same username within TTL return cached results without re-querying Roblox API. Support cache clearing/invalidation if requested.
2. Implement 429 Exponential Backoff and rate pacing in query_roblox_api(): parse Retry-After header if present, exponential backoff (2 ** attempt), pacing in concurrent detail lookups. Ensure accurate isBanned classification. Keep ban checking strictly on-demand (no background polling/crons).
3. Implement Dual-Storage Account Isolation (R2):
   - Ensure .bak_<timestamp> is created for BOTH acc.txt and Data_Tong_Cookies.txt before any modification (in clean_banned_accounts and add_accounts).
   - Extract banned cookies to acc_bi_ban.txt, log timestamp to nhat_ky_ban.txt.
   - Remove banned accounts cleanly from acc.txt and Data_Tong_Cookies.txt.
   - Support clean_banned_accounts when target is a list of usernames or "all" or machine code.
   - Return removed_from_acc in clean_banned_accounts() output matching worker/fleet_state.js expectation.
   - Fix section parsing edge cases in parse_acc_sections(): do not match account names like Mega_Wiley623 or M00nlUWarden...; merge duplicate section headers (e.g. multiple M0 sections); track and handle top unassigned accounts.
4. Implement Rule 34 Google Drive In-Place Sync & Verification (R2):
   - In sync_to_google_drive(), use rclone copyto in-place.
   - Implement Rule 34 verification check confirming File IDs (12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg for acc.txt and 1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B for Data_Tong_Cookies.txt).
5. Implement Automated Replacement from Reserve Account Pool (R3):
   - Add acc_du_phong.txt to default paths.
   - Implement reading and extracting reserve accounts from acc_du_phong.txt (or CLI args), inserting them into the target machine section, appending cookies to Data_Tong_Cookies.txt, updating acc_du_phong.txt, and syncing to Google Drive.
   - Integrate auto-replacement into run_full_checkban_pipeline(target, base_dir=None, auto_replace=True) so when accounts in a machine section are banned, vacant slots are replenished.
6. Fix CLI checkban parsing: parse all arguments when multiple usernames are provided (tgt = " ".join(sys.argv[2:])).
7. Update and expand tests/test_account_manager.py to thoroughly test:
   - Quota-Guard cache hit/miss/expiry.
   - 429 backoff and Retry-After handling.
   - .bak_<timestamp> dual file backups.
   - Rule 34 sync and File ID verification.
   - Reserve pool replacement from acc_du_phong.txt.
   - Section parsing edge cases (Mega_Wiley623, duplicate sections, top accounts).
8. Run pytest tests/test_account_manager.py and bash tests/run_all_tests.sh to verify 100% tests pass.

Write your handoff report to /root/phanserver-delta/.agents/teamwork_preview_worker_m1_1/handoff.md and report back via send_message.

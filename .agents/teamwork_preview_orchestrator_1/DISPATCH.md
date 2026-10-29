## 2026-09-12T15:35:39Z

You are the Project Orchestrator for the project located at /root/phanserver-delta.

Your working directory is /root/phanserver-delta/.agents/teamwork_preview_orchestrator_1.
Please maintain your BRIEFING.md, plan.md, and progress.md in your working directory.

The original user request is stored at /root/phanserver-delta/.agents/ORIGINAL_REQUEST.md.
Review it carefully:
1. R1: On-Demand Roblox Ban Detection with Quota-Guard (no background polling/crons; batch lookup up to 100 usernames/req via users.roblox.com/v1/usernames/users and /v1/users/{userId}; quota-guard caching; 429 backoff; accurate isBanned classification).
2. R2: Strict Dual-Storage Account Isolation and Rule 34 Sync (create .bak_<timestamp> before modifying files; extract banned cookies/accounts to acc_bi_ban.txt & log to nhat_ky_ban.txt; remove from acc.txt & Data_Tong_Cookies.txt on both local /storage/emulated/0/Download/Shouko/ and Google Drive gdrive:; use rclone copyto to preserve 100% Google Drive File IDs per Rule 34).
3. R3: Automated Replacement from Reserve Account Pool (read reserve accounts from acc_du_phong.txt or CLI params; insert into specified machine section like M77___(gag2) without matching account names like Mega_Wiley623; update cookies; sync to Google Drive via rclone copyto).
4. R4: Telegram Bot Control & Interactive Delivery (/checkban [m_code|all|users], /addacc <m_code> <user1:pass1> ... in Cloudflare Worker / Durable Objects; HTML formatted reporting).
5. Acceptance Criteria & Automated Testing Suite:
   - tests/run_all_tests.sh must pass 100% (7/7 suites: tong_hop_link, telegram_phanserver, fleet_state_2pc, delta_updater, device_agent, account_manager, e2e_flow).
   - tests/verify_production_runtime.py must pass with zero errors.

Execute the work with your team, update progress.md continuously, verify all tests and production runtime checks, and send a final report when victory is ready to be claimed.

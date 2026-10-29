# Project Plan: Roblox On-Demand Ban Checker, Dual-Storage Isolation & Auto-Replacement

## Phase 0: Architecture & Codebase Survey
- Dispatch 3 parallel Explorers:
  - Explorer 1: Examine test harness (`tests/run_all_tests.sh`, `tests/verify_production_runtime.py`, test directory layout, mock environments, current pass/fail status).
  - Explorer 2: Examine account storage, dual-storage isolation (`/storage/emulated/0/Download/Shouko/`, Google Drive `gdrive:`, `rclone copyto` Rule 34 preservation of File IDs `12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg` and `1k8B2Vkdu-w3-K-O92vMeC1HQbKGaZb0B`, backup `.bak_<timestamp>`, `acc_bi_ban.txt`, `nhat_ky_ban.txt`, `acc_du_phong.txt`, section regex like `M77___(gag2)` vs `Mega_Wiley623`).
  - Explorer 3: Examine Roblox API ban detection (batch up to 100, Quota-Guard cache, 429 backoff, `isBanned` classification) and Telegram Bot / Cloudflare Worker / Durable Objects (`/checkban`, `/addacc`, HTML formatting).
- Synthesize findings into `PROJECT.md` at `.agents/PROJECT.md` with full feature inventory and milestone definitions.

## Phase 1: Implementation Milestones
- Milestone 1: On-Demand Roblox Ban Detection with Quota-Guard (R1)
- Milestone 2: Dual-Storage Account Isolation & Rule 34 Google Drive Sync (R2)
- Milestone 3: Automated Replacement from Reserve Account Pool (R3)
- Milestone 4: Telegram Bot Control & Interactive Delivery (R4)

## Phase 2: Comprehensive Verification & Acceptance
- Full execution of `tests/run_all_tests.sh` (7/7 test suites passing).
- Full execution of `tests/verify_production_runtime.py` (0 errors).
- Reviewer, Challenger, and Forensic Auditor verification.
- Final synthesis and reporting.

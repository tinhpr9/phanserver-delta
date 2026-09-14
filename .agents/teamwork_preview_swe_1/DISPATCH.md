## 2026-09-14T10:23:50Z

You are teamwork_preview_swe_1, the SWE Light Orchestrator for this task.
Your working directory is: /root/phanserver-delta/.agents/teamwork_preview_swe_1
The project workspace root is: /root/phanserver-delta
The original user request is recorded in: /root/phanserver-delta/.agents/ORIGINAL_REQUEST.md (under timestamp ## 2026-09-14T10:22:49Z).

Task:
Add `/tablist` command to phanserver-delta:
- R1. ADB-Based Tab-to-Account Mapping: Agent on M77 queries running Roblox app instances using ADB and determines logged in account per instance (mapping Tab N -> username).
- R2. Telegram Command `/tablist`: On-demand only (no polling, background scan, or cron). Returns HTML:
📱 <b>Tab List — M77</b>
Tab 1: username_a
Tab 2: username_b
Tab 3: ❓ (unknown)
- R3. Worker + Agent Integration: Telegram Bot (phanserver.js) sends TAB_LIST action via fleet-batch-v1 -> Agent (agent.py) executes ADB query -> sends result to Worker -> Worker forwards to Telegram. Add "tab_list" to agent CAPABILITIES.
- Acceptance criteria:
  - Functional: /tablist returns HTML report within 60s, correct count, tab -> username or ❓.
  - Non-Regression: `bash tests/run_all_tests.sh` passes 7/7 suites, `python3 tests/verify_production_runtime.py` passes 100%, Rule 34 preserved (file IDs for acc.txt and Data_Tong_Cookies.txt unchanged).
  - Safety: Mock unit/integration testing only (never run ADB against real UgPhone/M77 during dev/tests), no Roblox API calls.

Execute the SWE Light protocol: maintain progress.md and handoff.md, coordinate implementation and review rounds, verify with tests, and report back upon completion.

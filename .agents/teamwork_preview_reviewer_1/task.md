# Reviewer 1 Task: Code Review & Verification

## Scope
Review the code changes made by Worker 1 to fulfill Tailscale UgPhone Requirements R1–R4.
Examine `agent/agent.py`, `worker/fleet_state.js`, `tests/test_device_agent.py`, `tests/test_fleet_state_2pc.mjs`, and `tests/run_all_tests.sh`.

## Verification Tasks
1. Verify elimination of fake `TRIGGERED` / `OPENED` reporting (R1).
2. Verify UgPhone `--user 0` flag on `am start` and `am broadcast` (R2).
3. Verify screen orientation detection and adaptive coordinates for Landscape and Portrait (R2).
4. Verify 12s polling loop and checking both `tun0` and `100.x.y.z` CGNAT IP range (R2).
5. Verify UI dismissal (`KEYCODE_BACK` and `KEYCODE_HOME`) after connection (R2).
6. Verify Telegram message formatting for success with IP, failure with reason, and status CONNECTED vs DISCONNECTED (R3).
7. Verify 0 real UgPhone interaction (R4).
8. Execute `bash tests/run_all_tests.sh` and `python3 tests/verify_production_runtime.py`.
9. Document your verdict (APPROVE or REQUEST_CHANGES) in `handoff.md` and send message.

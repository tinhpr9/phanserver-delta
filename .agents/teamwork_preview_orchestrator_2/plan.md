# Execution Plan: Tailscale UgPhone VPN Activation & Verification

## Objective
Address Tailscale VPN activation on UgPhone (`m77`):
1. Eliminate fake success (TRIGGERED / premature OPENED). Only report success when tun0 or 100.x.y.z exists. Timeout after 12s returns FAILED with clear reason.
2. UgPhone compatibility: am start --user 0, auto-detect screen orientation (landscape 90°/270° vs portrait 0°/180°) and calculate adaptive click coordinates for Connect button and toggle switch. Press BACK or HOME after connection to hide UI. Check both tun0 and CGNAT range 100.x.y.z.
3. Telegram bot & Worker command handling for /vpn and /tailscale: clear message formats for success (with IP 100.x.y.z), failure (with specific reason), and status (CONNECTED vs DISCONNECTED).
4. Strictly mock tests in tests/, 0 real device interaction, 100% pass on bash tests/run_all_tests.sh.

## Plan Steps
1. **Survey (Phase 0)**:
   - Spawn 3 parallel Explorers:
     - Explorer 1: Tailscale device agent implementation (`device_agent.py`, `fleet_manager.py`, or similar, looking for CONTROL_TAILSCALE, tun0, IP extraction, am start, input tap, orientation detection).
     - Explorer 2: Telegram Bot & Worker handler (`telegram_bot.py`, Cloudflare Worker scripts, `/vpn` and `/tailscale` commands, status formatting).
     - Explorer 3: Existing test suite (`tests/test_device_agent.py`, `tests/run_all_tests.sh`, mock conventions, runner setup).
2. **Decompose & Design (Phase 1)**:
   - Synthesize explorer reports into `PROJECT.md` with Feature Inventory, Milestones, and Code Layout.
3. **Implementation & Gate (Phase 2)**:
   - Spawn Worker to implement Tailscale logic, orientation detection, coordinate adaptation, IP verification, Telegram/Worker command formatting, and unit tests.
   - Spawn Reviewers (2) to review correctness and safety.
   - Spawn Challengers (2) to stress test boundary cases and test suites.
   - Spawn Forensic Auditor to verify genuine implementation without hardcoded bypasses.
4. **Final Verification & Handoff (Phase 3 & 4)**:
   - Verify full test suite passes.
   - Write handoff.md and send completion message to Sentinel.

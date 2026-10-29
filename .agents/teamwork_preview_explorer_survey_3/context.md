# Explorer 3 Task: Test Suite & Harness Analysis

## Objective
Investigate the existing automated test infrastructure, especially `tests/test_device_agent.py`, `tests/run_all_tests.sh`, and any related mocks.

## Specific Questions to Answer
1. How does `tests/run_all_tests.sh` execute tests? Which test files currently exist and run?
2. What does `tests/test_device_agent.py` currently test regarding Tailscale / VPN?
3. How are adb commands, subprocess calls, and network interfaces mocked in tests?
4. What new test cases must be added to cover:
   - Connect success with valid `100.x.y.z` IP and `tun0` interface.
   - Orientation detection (landscape 90°/270° vs portrait 0°/180°) and coordinate computation.
   - Timeout after 12s returning `status: "FAILED"` with explicit reason without IP.
   - Elimination of fake `TRIGGERED` and premature `OPENED`.
   - Disconnect handling.
   - Status check (`CONNECTED` vs `DISCONNECTED`).
   - Telegram response formatting for success, failure, and status.
5. Ensure 100% compliance with R4 (strictly mock tests, 0 real UgPhone command execution).

# Challenger 2 Task: Adversarial Stress Testing & Coverage Audit

## Scope
Adversarially challenge the implementation of Tailscale VPN on UgPhone (Requirements R1–R4).
Check test suite coverage, robustness against concurrency, race conditions, idempotency, and boundary values.

## Challenge Targets
1. Concurrency and Idempotency: Repeated calls with identical action_id, rapid switching between 'on' and 'off'.
2. Elimination of Fake TRIGGERED / OPENED: Rigorously verify that under NO circumstances does the agent or worker return "OPENED" or report success if the Tailscale IP is missing.
3. Status reporting: Verify that when Tailscale is stopped or disconnected, the status is reported honestly as DISCONNECTED, never claiming the internal network is ready.
4. R4 Verification: Confirm all test scripts use pure mocks with zero real network/ADB execution against real UgPhone devices.
5. Execute full test suite `bash tests/run_all_tests.sh` and empirical tests. Document verdict in `handoff.md`.

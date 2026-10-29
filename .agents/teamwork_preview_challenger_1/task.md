# Challenger 1 Task: Adversarial Stress Testing & Edge Cases

## Scope
Adversarially challenge the implementation of Tailscale VPN on UgPhone (Requirements R1–R4).
Verify that edge cases, boundaries, failure modes, and stress scenarios are correctly handled without false passes or crashes.

## Challenge Targets
1. Edge cases in screen orientation: odd resolutions (e.g. 1080x2400, 720x1520, square displays), unexpected rotation strings.
2. Malformed IPs: IPs that have `100.` prefix but are invalid octets (e.g. `100.300.1.1`, `100.abc.1.1`, `100.1.1`). Ensure regex strictly matches valid IPv4.
3. Timeout stress: Subprocess timing out, shell script exiting with exit code 1 or killed. Ensure status is always FAILED and never OPENED.
4. UI dismissal keyevents: Ensure `KEYCODE_BACK` and `KEYCODE_HOME` are sent properly without raising uncaught exceptions.
5. Telegram HTML escaping: Special characters in reason or error strings (`<`, `>`, `&`). Ensure Telegram formatting doesn't crash on unescaped HTML entities.
6. Run tests to empirically verify. Document findings, empirical tests, and verdict (APPROVE / REQUEST_CHANGES) in `handoff.md`.

# Challenger Iteration 2 - 1 Task: Retest Malformed IP & Boundary Edge Cases

## Scope
Verify that the defects identified in Iteration 1 (Challenger 1 report) are completely resolved by Worker 2.

## Verification Checks
1. Empirically verify that `100.300.1.1` is strictly rejected as FAILED and never produces success notification on Telegram.
2. Empirically verify that `100.1.2.2555` is strictly rejected as FAILED without suffix truncation.
3. Empirically verify that `1100.1.2.3` and `100.1.2.3.4` are strictly rejected.
4. Run `node tests/test_adversarial_fleet.mjs` and `python3 -m unittest -v tests/test_adversarial_agent.py`.
5. Run `bash tests/run_all_tests.sh`.
6. Document empirical results and verdict (APPROVE / REQUEST_CHANGES) in `handoff.md`.

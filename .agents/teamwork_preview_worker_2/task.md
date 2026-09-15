# Worker 2 Task: Malformed IP Extraction & Word Boundary Fix

## Objective
Apply the exact fixes for malformed IP extraction and word boundary enforcement in `worker/fleet_state.js` and `agent/agent.py`, and add regression tests in `tests/test_device_agent.py` and `tests/test_fleet_state_2pc.mjs`.

## Inputs & Findings to Read First
1. `/root/phanserver-delta/.agents/ORIGINAL_REQUEST.md` (mandatory source of requirements)
2. `/root/phanserver-delta/.agents/teamwork_preview_challenger_1/handoff.md` (Challenger 1 defect report)
3. `/root/phanserver-delta/.agents/teamwork_preview_explorer_retry_1/handoff.md`
4. `/root/phanserver-delta/.agents/teamwork_preview_explorer_retry_2/handoff.md`
5. `/root/phanserver-delta/.agents/teamwork_preview_explorer_retry_3/handoff.md`

## Required Code Modifications

### 1. `worker/fleet_state.js`
- Add and export helper function:
  ```javascript
  export function extractValidTailscaleIp(details) {
    const match = String(details || "").match(/(?<![0-9a-zA-Z.])\b100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b(?![0-9a-zA-Z./:])/);
    if (!match) return null;
    const octets = [Number(match[1]), Number(match[2]), Number(match[3])];
    if (octets.some((o) => o < 0 || o > 255 || isNaN(o))) return null;
    return match[0];
  }
  ```
- In `acknowledgeTailscaleControl`:
  Replace:
  `const ipMatch = String(body.details || "").match(/100\.\d{1,3}\.\d{1,3}\.\d{1,3}/);`
  `const tailscaleIp = ipMatch ? ipMatch[0] : null;`
  With:
  `const tailscaleIp = extractValidTailscaleIp(body.details);`
- In `mode === "status"`:
  Ensure `const isConnected = isSuccess && Boolean(tailscaleIp);` so that invalid IPs or malformed details do not trigger a connected status.

### 2. `agent/agent.py`
- In `handle_incoming_batch_action` line 703 (`mode == "on"`):
  Update regex to:
  `ip_match = re.search(r"(?<![0-9a-zA-Z.])\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b(?![0-9a-zA-Z./:])", stdout_text)`
- In `mode == "status"`:
  Validate extracted IP with `validate_tailscale_cgnat_ip`. If valid IP is found, return `status: "OPENED"`, `details: f"CONNECTED: {valid_ip}"`. If not valid, return `details: "DISCONNECTED"`.

### 3. `tests/test_device_agent.py`
- Add unit test methods covering:
  * `test_tailscale_connect_rejects_octet_greater_than_255` (`100.300.1.1` returns FAILED)
  * `test_tailscale_connect_rejects_4digit_octet_suffix_no_truncation` (`100.1.2.2555` returns FAILED, not truncated)
  * `test_tailscale_connect_rejects_4digit_prefix_and_5_octets` (`1100.1.2.3` and `100.1.2.3.4` return FAILED)
- In `test_cgnat_100_ip_validation`, add boundary checks for `100.0.0.0`, `100.255.255.255`, `100.1.2.2555`, `1100.1.2.3`, `100.1.2.3.4`, `.100.1.2.3`.

### 4. `tests/test_fleet_state_2pc.mjs`
- Import `extractValidTailscaleIp` from `../worker/fleet_state.js`.
- Add integration assertions verifying:
  * ACK with `100.300.1.1` returns `status: "FAILED"` and notifies Telegram of failure.
  * ACK with `100.1.2.2555` returns `status: "FAILED"` and does not truncate.
  * Direct unit assertions for `extractValidTailscaleIp` with valid and invalid IP vectors.

## Verification
- Run `bash tests/run_all_tests.sh` (ensure all 7 suites pass 100%).
- Run `python3 tests/verify_production_runtime.py`.
- Run `python3 -m unittest -v tests/test_adversarial_agent.py`.
- Run `node tests/test_adversarial_fleet.mjs`.
- Document all changes and verification output in `handoff.md`.

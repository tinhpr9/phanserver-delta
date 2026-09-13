# Worker Task: Implement Tailscale UgPhone Fix & Telegram Real IP Reporting

## Objective
Implement all changes across `agent/agent.py`, `worker/fleet_state.js`, and automated tests (`tests/test_device_agent.py`, `tests/test_fleet_state_2pc.mjs`, `tests/run_all_tests.sh`) to fulfill Requirements R1–R4.

## Inputs & Reports to Read First
1. `/root/phanserver-delta/.agents/ORIGINAL_REQUEST.md` (mandatory source of requirements)
2. `/root/phanserver-delta/.agents/teamwork_preview_orchestrator_2/PROJECT.md`
3. Explorer 1 findings: `/root/phanserver-delta/.agents/teamwork_preview_explorer_survey_1/handoff.md`
4. Explorer 2 findings: `/root/phanserver-delta/.agents/teamwork_preview_explorer_survey_2/handoff.md`
5. Explorer 3 findings: `/root/phanserver-delta/.agents/teamwork_preview_explorer_survey_3/handoff.md`

## Scope of Work & Implementation Details

### 1. `agent/agent.py` (Device Agent Tailscale Handling)
- Refactor Tailscale execution in `handle_incoming_batch_action` (or a dedicated helper function):
  * In `am start` and `am broadcast`, add `--user 0`:
    `am start --user 0 -n com.tailscale.ipn/.MainActivity`
    `am broadcast --user 0 -a com.tailscale.ipn.CONNECT_VPN ...` (and for DISCONNECT)
  * Orientation detection:
    Query `dumpsys input` for `SurfaceOrientation` (or `dumpsys window` / `settings`).
    Determine if screen is Landscape (rotation 1 or 3, 90°/270°) or Portrait (rotation 0 or 2, 0°/180°).
    Determine active display dimensions `(WIDTH, HEIGHT)`.
  * Compute adaptive coordinates:
    Connect button: center `(WIDTH / 2, HEIGHT / 2)`.
    Toggle switch: top-right corner.
    Landscape: Toggle `(int(WIDTH * 0.92), int(HEIGHT * 0.12))`
    Portrait: Toggle `(int(WIDTH * 0.88), int(HEIGHT * 0.08))`
    Tap both the Toggle switch and the Connect button.
  * Polling loop & timeout (12 seconds):
    Loop for 12 seconds checking both `dev tun0` and any interface with CGNAT IP matching regex `100\.[0-9]+\.[0-9]+\.[0-9]+`.
    If IP is found:
      - Send `KEYCODE_BACK` and `KEYCODE_HOME` to dismiss UI.
      - Output `CONNECTED: 100.x.y.z`.
      - Python marks `status = "OPENED"`, `executed = True`, `details = "CONNECTED: 100.x.y.z"`.
    If IP is NOT found after 12 seconds:
      - Shell script must exit with non-zero (e.g. exit 1).
      - NEVER output `TRIGGERED`.
      - Python marks `status = "FAILED"`, `executed = False`, `reason = "vpn_timeout_no_ip: Timeout 12s không nhận được IP Tailscale (100.x.y.z)"`, `details = None`.
  * Mode `status`:
    Check `dev tun0` and regex `100.x.y.z`.
    If found: `status = "OPENED"`, `details = "CONNECTED: 100.x.y.z"`.
    If not found: `status = "OPENED"`, `details = "DISCONNECTED"`.
  * Subprocess timeout: Ensure Python `subprocess.run` has at least 25-30s timeout so the 12s shell loop doesn't get cut off prematurely.

### 2. `worker/fleet_state.js` (Telegram Bot & Ack Notification)
- In `acknowledgeTailscaleControl`:
  * Extract Tailscale IP `100.x.y.z` from `body.details` via regex.
  * Strict gating: For `mode === "on"`, it is ONLY successful if `(status === "OPENED" || status === "SUCCESS") && tailscaleIp`.
  * If successful for `on`:
    Send Telegram message format:
    `🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: ${tailscaleIp}</b>`
  * If failed for `on` (or no IP):
    Send Telegram message format:
    `❌ <b>BẬT TAILSCALE THẤT BẠI: ${escapeHtml(reason)}</b>`
  * For `mode === "status"`:
    Check if connected with IP.
    If connected:
      `🌐 <b>TRẠNG THÁI TAILSCALE: CONNECTED (${tailscaleIp})</b>`
    If disconnected:
      `⚠️ <b>TRẠNG THÁI TAILSCALE: DISCONNECTED</b>`
  * For `mode === "off"`:
    If success: `🌐 <b>ĐÃ TẮT TAILSCALE THÀNH CÔNG!</b>`

### 3. `tests/test_device_agent.py` & Test Suite
- Create `tests/test_device_agent.py` implementing comprehensive unit tests using mocks (0 real device execution per R4):
  * `test_tailscale_connect_success_portrait`
  * `test_tailscale_connect_success_landscape`
  * `test_tailscale_connect_timeout_returns_failed` (verifying `status: "FAILED"`, `executed: False`, no fake `OPENED`)
  * `test_elimination_of_fake_triggered_opened`
  * `test_tailscale_disconnect_off`
  * `test_tailscale_status_connected`
  * `test_tailscale_status_disconnected`
  * `test_user_0_flag_present`
  * `test_orientation_and_coordinate_computation`
  * `test_cgnat_100_ip_validation`
  * `test_tailscale_idempotency`
  * `test_ui_dismiss_keyevent_sent`
- Update `tests/test_fleet_state_2pc.mjs` to test Telegram message outputs for ON success with IP, ON failure, and STATUS check.
- Update `tests/run_all_tests.sh` to include `tests/test_device_agent.py` if not already picked up by unittest discover.
- Run `bash tests/run_all_tests.sh` to confirm 100% tests pass.

## Verification
- Run `bash tests/run_all_tests.sh` and document full test output in `handoff.md`.

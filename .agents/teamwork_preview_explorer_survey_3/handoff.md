# Explorer 3 (Test Suite Harness Explorer) — Handoff Report

## Executive Summary
This investigation provides a comprehensive audit of the `phanserver-delta` automated test harness, mock architectures, and test coverage relating to Tailscale VPN control (Requirements R1–R4). Currently, `tests/run_all_tests.sh` executes 7 distinct suites and passes 100%. However, Tailscale test coverage is severely deficient: only a single positive mock scenario exists in `agent/tests/test_agent.py`. The production code in `agent/agent.py` contains a critical bug that converts connection timeouts into phantom `status: "OPENED"` with details `"TRIGGERED"`, which the Worker in `worker/fleet_state.js` subsequently broadcasts to Telegram as "ĐÃ BẬT TAILSCALE THÀNH CÔNG!". Furthermore, orientation detection (landscape vs portrait) and UgPhone-specific `--user 0` intent flags are unverified and incomplete. This report details the existing harness, analyzes root causes, provides exact mock blueprints, and outlines a comprehensive test suite (`tests/test_device_agent.py` and JS integration tests) complying 100% with R4 (zero real UgPhone interaction).

---

## 1. Observation

### 1.1 Test Suite Architecture & `tests/run_all_tests.sh` Execution
The master test script `tests/run_all_tests.sh` (32 lines) runs 7 test suites sequentially with `set -euo pipefail`:

```bash
[1/7] node tests/test_tong_hop_link.mjs
[2/7] node tests/test_telegram_phanserver.mjs
[3/7] node tests/test_fleet_state_2pc.mjs
[4/7] python3 -m unittest discover -s delta/tests
[5/7] python3 -m unittest discover -s agent/tests
[6/7] pytest -q tests/test_account_manager.py
[7/7] python3 tests/test_e2e_flow.py
```

- **Execution Results**: All 7 suites currently pass cleanly in ~16s total (Node tests: ~1s; delta tests: 27 passed in 0.57s; agent tests: 20 passed in 2.82s; account manager: 23 passed in 11.57s; e2e flow: 2 passed in 0.27s).
- **Physical Test File Layout**:
  - `tests/`: Contains `test_tong_hop_link.mjs`, `test_telegram_phanserver.mjs`, `test_fleet_state_2pc.mjs`, `test_account_manager.py`, `test_e2e_flow.py`, `test_adversarial_m3.py`, `test_adversarial_m3_challenger2.mjs`, `test_adversarial_m3_challenger2_idempotency.py`, `verify_production_runtime.py`.
  - `agent/tests/`: Contains `test_agent.py` (which defines `TestDeviceAgent` with 11 tests) and `test_server_links.py` (9 tests).
  - Note on `test_device_agent.py`: A separate file named `tests/test_device_agent.py` does **not** currently exist in `tests/`. Instead, device agent tests reside inside `agent/tests/test_agent.py` under the class name `TestDeviceAgent`. To satisfy the requirement for `tests/test_device_agent.py` or dedicated Tailscale tests, a standalone test file can be introduced in `tests/test_device_agent.py` and included in suite [5/7] or run via `pytest`.

### 1.2 Current Tailscale Test Coverage in `agent/tests/test_agent.py`
In `agent/tests/test_agent.py`, Tailscale is tested solely in method `test_control_tailscale_on_off_status` (lines 116–156):
```python
@mock.patch("agent.agent.send_ack", return_value=True)
@mock.patch("agent.agent.subprocess.run")
def test_control_tailscale_on_off_status(self, mock_subproc, mock_ack):
    mock_subproc.return_value.returncode = 0
    mock_subproc.return_value.stdout = "CONNECTED: 100.80.175.55"
    mock_subproc.return_value.stderr = ""
    state = {}
    message_on = {
        "protocol": "fleet-batch-v1",
        "action": "CONTROL_TAILSCALE",
        "action_id": "ts-101",
        "mode": "on",
        "target_device_ids": ["m72"],
    }
    self.assertTrue(agent.handle_incoming_batch_action(
        message_on, "m72", "https://mock/report", "sec", state, self.state_path, self.links_path
    ))
    self.assertEqual(mock_ack.call_args.kwargs["batch_action"], "CONTROL_TAILSCALE")
    self.assertEqual(mock_ack.call_args.kwargs["status"], "OPENED")
    self.assertEqual(mock_ack.call_args.kwargs["details"], "CONNECTED: 100.80.175.55")

    # Idempotency test
    self.assertTrue(agent.handle_incoming_batch_action(
        message_on, "m72", "https://mock/report", "sec", state, self.state_path, self.links_path
    ))
    self.assertEqual(mock_subproc.call_count, 1)

    # Off test
    mock_subproc.return_value.stdout = "DISCONNECTED"
    message_off = {
        "protocol": "fleet-batch-v1",
        "action": "CONTROL_TAILSCALE",
        "action_id": "ts-102",
        "mode": "off",
        "target_device_ids": ["m72"],
    }
    self.assertTrue(agent.handle_incoming_batch_action(
        message_off, "m72", "https://mock/report", "sec", state, self.state_path, self.links_path
    ))
    self.assertEqual(mock_ack.call_args.kwargs["details"], "DISCONNECTED")
```
**Direct Observation of Gaps**:
1. `mode: "status"` is completely untested despite being part of the test method name.
2. Connection failure / timeout is completely untested.
3. Orientation detection and tap coordinate math are completely untested.
4. UgPhone intent flag `--user 0` is unverified.
5. CGNAT IP range `100.x.y.z` validation is unverified.

### 1.3 The Root Cause of Phantom "TRIGGERED" Success in `agent/agent.py`
Examining `agent/agent.py` lines 539–607:
```python
# Line 539: Missing --user 0
am start -n com.tailscale.ipn/.MainActivity >/dev/null 2>&1 || true

# Lines 577-583: Only polls 5 times (5 seconds, not 12s), only tun0
for i in 1 2 3 4 5; do
    IP=$(ip addr show dev tun0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d'/' -f1)
    if [ -n "$IP" ]; then
        break
    fi
    sleep 1
done

# Lines 585-591: Echos TRIGGERED when IP is empty
if [ -n "$IP" ]; then
    input keyevent KEYCODE_BACK >/dev/null 2>&1 || true
    echo "CONNECTED: $IP"
else
    echo "TRIGGERED"
fi

# Lines 594-607: Interprets returncode == 0 as OPENED!
if _run_as_root:
    res = _run_as_root(cmd, timeout=20)
    success = res.returncode == 0
    stdout_text = res.stdout.strip()
    reason = None if success else res.stderr.strip()
else:
    proc = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, timeout=20)
    success = proc.returncode == 0
    stdout_text = proc.stdout.strip()
    reason = None if success else proc.stderr.strip()

status = "OPENED" if success else "FAILED"
details = stdout_text if stdout_text else ("OK" if success else None)
result = {"status": status, "executed": success, "reason": reason, "details": details}
```
When Tailscale fails to acquire an IP, the shell script executes `echo "TRIGGERED"` and exits with return code `0`. Because `returncode == 0`, `agent.py` sets:
- `success = True`
- `status = "OPENED"`
- `details = "TRIGGERED"`
- `reason = None`
Then `send_ack` is dispatched to the Cloudflare Worker with `status: "OPENED"`.

### 1.4 Downstream Telegram Broadcast in `worker/fleet_state.js`
In `worker/fleet_state.js` lines 979–985:
```javascript
const isSuccess = status === "OPENED" || status === "SUCCESS";
const mode = act?.mode || "on";
const modeDesc = mode === "off" ? "TẮT" : (mode === "status" ? "KIỂM TRA TRẠNG THÁI" : "BẬT");
const details = body.details ? `\n📋 Trạng thái: <code>${escapeHtml(body.details)}</code>` : "";
const msg = isSuccess
  ? `🌐 <b>ĐÃ ${modeDesc} TAILSCALE THÀNH CÔNG!</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚙️ Chế độ: <b>${mode.toUpperCase()}</b>${details}\n🔒 Mạng nội bộ Tailscale đã sẵn sàng.`
  : `❌ <b>${modeDesc} TAILSCALE THẤT BẠI</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${escapeHtml(body.reason || "Lỗi thiết bị")}`;
```
Because `status` was `"OPENED"`, `isSuccess` evaluates to `true`. The Telegram Bot reports:
`🌐 ĐÃ BẬT TAILSCALE THÀNH CÔNG!` with `📋 Trạng thái: TRIGGERED`!
Even for `mode === "status"`, when a device is `DISCONNECTED`, `status` is `"OPENED"`, causing the bot to falsely claim:
`🌐 ĐÃ KIỂM TRA TRẠNG THÁI TAILSCALE THÀNH CÔNG! ... 🔒 Mạng nội bộ Tailscale đã sẵn sàng.`!

### 1.5 Mock Architecture & Execution Mechanics
1. **Agent Environment**: The agent runs locally inside Android (Termux/root). Shell commands are executed locally via `_run_as_root` (from `agent.backup_manager`) or `subprocess.run(["sh", "-c", cmd])`.
2. **Mocking Interception**:
   - Both `agent.agent` and `agent.backup_manager` import the standard `subprocess` module.
   - Inside `agent.backup_manager._run_as_root`, if `os.geteuid() == 0` (as is the case in the Docker test environment), it executes `subprocess.run(["sh", "-c", cmd])`.
   - If `agent.agent.subprocess.run` is patched, it patches `sys.modules['subprocess'].run`.
   - To make mocking robust and granular without relying on full multi-line shell string interpretation, Tailscale logic can be factored into clear Python helper functions (or mockable dispatchers) for:
     * Screen orientation detection
     * Touch coordinate calculation
     * IP interface probing (`tun0` and `100.x.y.z`)
     * App launch with `--user 0` and UI dismissal (`BACK`/`HOME`).
3. **JS Worker Mocking**:
   - `tests/test_fleet_state_2pc.mjs` defines `globalThis.fetch` to capture all Telegram API calls into `notifiedTelegram` (line 12).
   - Currently, `test_fleet_state_2pc.mjs` line 308 tests acking `CONTROL_TAILSCALE` with `OPENED`, but **never** asserts what message was sent to Telegram via `notifiedTelegram`.

---

## 2. Logic Chain

1. **Premise (R1 Violation)**: Under R1, the system must never report `OPENED` or "ĐÃ BẬT THÀNH CÔNG" unless an active `100.x.y.z` IP or `tun0` interface exists.
   - *Observation*: In `agent/agent.py` lines 590–605, when no IP is found, the shell script prints `"TRIGGERED"` and exits with returncode 0.
   - *Inference*: `status` is evaluated as `"OPENED"`, and `details` is `"TRIGGERED"`.
   - *Inference*: `worker/fleet_state.js` checks `isSuccess = status === "OPENED"`, triggering the Telegram success template.
   - *Conclusion*: A timeout or failure to obtain an IP must strictly set `status: "FAILED"` with an explicit error message (e.g., `"Timeout 12s chờ IP Tailscale thất bại (không tìm thấy IP 100.x.y.z hoặc tun0)"`), eliminating `"TRIGGERED"` completely.

2. **Premise (R2 Optimization for UgPhone)**: Under R2, UgPhone requires multi-user launch flag `--user 0`, orientation-aware click coordinates for Connect (center) and Toggle Switch (top-right), dual checking of `tun0` and `100.x.y.z`, and hiding the UI upon connection.
   - *Observation*: Currently, line 539 omits `--user 0`.
   - *Observation*: Orientation logic relies only on `wm size` and taps hardcoded positions `CY = HEIGHT * 4 / 5` and `HEIGHT / 2`, omitting the top-right toggle switch entirely.
   - *Inference*: On UgPhone virtual devices in landscape (90°/270°) or portrait (0°/180°), the connect button and toggle switch reside at distinct proportional coordinates:
     * Landscape (e.g. 1280x720): Center button `(W/2, H/2) = (640, 360)`; Toggle switch at top-right `(int(W*0.92), int(H*0.12)) = (1177, 86)`.
     * Portrait (e.g. 720x1280): Center button `(W/2, H/2) = (360, 640)`; Toggle switch at top-right `(int(W*0.88), int(H*0.08)) = (633, 102)`.
   - *Conclusion*: Dedicated coordinate computation functions must be tested with synthetic screen orientations and resolutions.

3. **Premise (R3 Formatting for Telegram & Worker)**: Under R3, Telegram messages must clearly differentiate:
   - Connect success: `🌐 ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.x.y.z`
   - Connect failure: `❌ BẬT TAILSCALE THẤT BẠI: <Lý do cụ thể>`
   - Status: Display explicitly whether CONNECTED (with IP) or DISCONNECTED.
   - *Observation*: `worker/fleet_state.js` currently treats status queries as "ĐÃ KIỂM TRA TRẠNG THÁI THÀNH CÔNG! ... Mạng nội bộ Tailscale đã sẵn sàng" regardless of whether the device is connected or disconnected.
   - *Conclusion*: `worker/fleet_state.js` must format messages conditionally based on `mode` and whether `body.details` contains `CONNECTED: 100.`.

4. **Premise (R4 Zero Real Device Execution)**: Testing against real UgPhone instances is strictly forbidden.
   - *Observation*: All tests in `run_all_tests.sh` run completely offline in under 20s using mocked subprocesses and mocked WebSockets/storage.
   - *Conclusion*: All new tests must strictly operate via unit mocks (`unittest.mock.patch` in Python, mock `fetch` / in-memory DO storage in Node.js).

---

## 3. Caveats

1. **No Real UgPhone Testing**: Per requirement R4, no tests were executed against real UgPhone Android hardware. All behaviors were analyzed from source code and verified against mock test harnesses.
2. **Android Multi-User Assumptions**: The `--user 0` flag is required for Android 10+ multi-user virtual devices (like UgPhone / Redfinger / cloud phones). It does not break single-user Android environments.
3. **Screen Orientation Query Mechanisms**: On Android, orientation can be extracted via:
   - `dumpsys window | grep -E 'mCurrentRotation|mDisplayOrientation'`
   - `dumpsys display | grep -oE 'orientation=[0-9]+'`
   - `settings get system user_rotation`
   - Aspect ratio from `wm size` (`W > H` implies landscape, `W < H` implies portrait).
   The mock suite should test that both rotation metadata and aspect ratio fallbacks are handled robustly.
4. **Placement of `test_device_agent.py`**:
   `ORIGINAL_REQUEST.md` mentions `tests/test_device_agent.py`. In `tests/run_all_tests.sh`, suite [5/7] is `python3 -m unittest discover -s agent/tests`. To ensure 100% compliance with both, `tests/test_device_agent.py` should be placed in `tests/` and run directly via `python3 tests/test_device_agent.py` (or `pytest tests/test_device_agent.py`), while also ensuring `run_all_tests.sh` executes it.

---

## 4. Conclusion & Required Test Suite Specification

To achieve full compliance with Tailscale R1–R4, the following tests and mock structures must be implemented:

### 4.1 Required Python Test Cases (`tests/test_device_agent.py`)

| Test Case Name | Target Requirement | Mock Configuration & Invariants | Expected Result |
|---|---|---|---|
| `test_tailscale_connect_success_portrait` | R1, R2 | Screen: 720x1280 (Portrait). Subprocess outputs `CONNECTED: 100.80.175.55`. | `status: "OPENED"`, `executed: True`, `details: "CONNECTED: 100.80.175.55"`, `reason: None`. |
| `test_tailscale_connect_success_landscape` | R1, R2 | Screen: 1280x720 (Landscape). Subprocess outputs `CONNECTED: 100.115.92.14`. | `status: "OPENED"`, `executed: True`, `details: "CONNECTED: 100.115.92.14"`, `reason: None`. |
| `test_tailscale_connect_timeout_returns_failed` | R1, R4 | Subprocess outputs empty IP after 12s timeout. No `100.x.y.z` interface found. | `status: "FAILED"`, `executed: False`, `reason: "Timeout 12s: Không tìm thấy IP Tailscale (100.x.y.z)"`. Must NOT be `"OPENED"`. |
| `test_elimination_of_fake_triggered_opened` | R1 | Subprocess script emits `"TRIGGERED"` with exit code 0. | Verified that agent intercepts `"TRIGGERED"` and translates to `status: "FAILED"`, rejecting fake success. |
| `test_tailscale_disconnect_off` | R1, R4 | `mode: "off"`. Subprocess outputs `"DISCONNECTED"`. | `status: "OPENED"`, `executed: True`, `details: "DISCONNECTED"`. |
| `test_tailscale_status_connected` | R1, R3 | `mode: "status"`. IP `100.64.10.5` present on `tun0`. | `status: "OPENED"`, `details: "CONNECTED: 100.64.10.5"`. |
| `test_tailscale_status_disconnected` | R1, R3 | `mode: "status"`. No `tun0` interface, daemon stopped. | `status: "OPENED"`, `details: "DISCONNECTED"` (or `"STOPPED"`). |
| `test_user_0_flag_present_in_intent` | R2 | Inspects command generated by agent for Tailscale launch. | Assert command contains `am start --user 0 -n com.tailscale.ipn/.MainActivity`. |
| `test_orientation_and_coordinate_computation` | R2 | Tests unit math for resolutions (720x1280 portrait vs 1280x720 landscape, 1080x1920 vs 1920x1080). | Landscape: Center `(W/2, H/2)`, Toggle `(W*0.92, H*0.12)`. Portrait: Center `(W/2, H/2)`, Toggle `(W*0.88, H*0.08)`. |
| `test_cgnat_100_ip_validation` | R1, R2 | Regex validation against valid CGNAT IPs (`100.64.0.1`, `100.127.255.254`) and rejection of private IPs (`192.168.1.1`, `10.0.0.1`, `127.0.0.1`). | Only IPs matching `^100\.\d{1,3}\.\d{1,3}\.\d{1,3}$` qualify as valid Tailscale connections. |
| `test_tailscale_idempotency` | R4 | Re-submitting identical `action_id`. | Agent returns cached result from `state.json` without calling subprocess again. |
| `test_ui_dismiss_keyevent_sent` | R2 | On successful connection with IP. | Asserts `input keyevent KEYCODE_BACK` or `KEYCODE_HOME` is dispatched. |

### 4.2 Required Worker Integration Test Cases (`tests/test_fleet_state_2pc.mjs`)

| Test Case Name | Target Requirement | Trigger & Payload | Expected Telegram Notification |
|---|---|---|---|
| `test_tailscale_ack_opened_with_ip` | R1, R3 | `CONTROL_TAILSCALE` ack with `status: "OPENED"`, `details: "CONNECTED: 100.80.175.55"` | `notifiedTelegram.text` contains `🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG!</b>` and `100.80.175.55`. |
| `test_tailscale_ack_failed_timeout` | R1, R3 | `CONTROL_TAILSCALE` ack with `status: "FAILED"`, `reason: "Timeout 12s chờ IP"` | `notifiedTelegram.text` contains `❌ <b>BẬT TAILSCALE THẤT BẠI</b>` and `Timeout 12s chờ IP`. Must NOT say "THÀNH CÔNG". |
| `test_tailscale_ack_status_connected` | R3 | Ack for `mode: "status"` with `details: "CONNECTED: 100.80.175.55"` | `notifiedTelegram.text` explicitly displays `CONNECTED` and IP `100.80.175.55`. |
| `test_tailscale_ack_status_disconnected` | R3 | Ack for `mode: "status"` with `details: "DISCONNECTED"` | `notifiedTelegram.text` explicitly displays `DISCONNECTED`. |

### 4.3 Proposed Production Code Refactoring Plan
To enable these tests to pass cleanly:
1. **In `agent/agent.py`**:
   - Extract Tailscale control into a dedicated helper function (e.g. `execute_tailscale_control(mode: str, timeout: int = 12)`).
   - In `am start`, add `--user 0`.
   - Update orientation logic to detect rotation (0°/180° vs 90°/270°) and compute both center Connect coordinates and top-right Toggle Switch coordinates.
   - Poll for IP for up to 12s, searching both `tun0` and any interface matching `100.x.y.z`.
   - When no IP is found after 12s, return `status: "FAILED"`, `reason: "Timeout 12s: Chưa có IP Tailscale (tun0/100.x.y.z)"`. Never output `"TRIGGERED"` as a success.
2. **In `worker/fleet_state.js`**:
   - In `acknowledgeTailscaleControl`:
     * If `mode === "status"`: Format as `📊 <b>TRẠNG THÁI TAILSCALE: ${isConnected ? "CONNECTED" : "DISCONNECTED"}</b>` (with IP if present).
     * If `mode === "on"` and `status === "OPENED"`: Format as `🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG!</b>\n📱 Thiết bị: <code>${deviceId}</code>\n🌐 IP: <code>${ip}</code>`.
     * If `status === "FAILED"`: Format as `❌ <b>${modeDesc} TAILSCALE THẤT BẠI</b>\n⚠️ Lý do: ${reason}`.
3. **In `tests/run_all_tests.sh`**:
   - Ensure `tests/test_device_agent.py` is included in the execution pipeline so `bash tests/run_all_tests.sh` verifies all 7/7 suites plus device agent Tailscale compliance.

---

## 5. Verification Method

To independently verify the test suite and confirm compliance once changes are implemented:

1. **Master Test Suite Command**:
   ```bash
   bash tests/run_all_tests.sh
   ```
   *Expectation*: All suites pass 100% (exits with code 0).

2. **Dedicated Device Agent Test Command**:
   ```bash
   python3 -m unittest -v tests/test_device_agent.py
   # Or via pytest:
   pytest -v tests/test_device_agent.py
   ```
   *Expectation*: All Tailscale test cases pass, verifying:
   - Portrait connect success with `100.x.y.z`
   - Landscape connect success with `100.x.y.z`
   - Timeout without IP returning `status: "FAILED"`
   - Disconnect returning `status: "OPENED"`, `details: "DISCONNECTED"`
   - Status mode check for both CONNECTED and DISCONNECTED
   - Multi-user flag `--user 0` present
   - Screen rotation & coordinate math

3. **Telegram & Worker Integration Test Command**:
   ```bash
   node tests/test_fleet_state_2pc.mjs
   node tests/test_telegram_phanserver.mjs
   ```
   *Expectation*: Telegram messages assert correct formats for ON success with IP, ON failure, and STATUS.

4. **Hermeticity / R4 Compliance Check**:
   ```bash
   # Confirm no active ADB or physical device dependency
   which adb || true
   # Ensure tests execute in complete isolation without network or external device connections
   ```

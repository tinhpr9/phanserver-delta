# Handoff Report: Adversarial Stress Testing & Verification (Challenger 1)

## 1. Observation

### Implementation Inspection & Exact Paths
We conducted an adversarial audit of the Tailscale VPN implementation on UgPhone (`m77`) across the 5 target domains mandated by `ORIGINAL_REQUEST.md`, `task.md`, and `PROJECT.md`:
1. Screen Orientation & Coordinate Computation
2. Malformed IPs & CGNAT Validation
3. Subprocess Timeout, Exit Codes & Termination Signals
4. UI Keyevents & Error Suppression
5. Telegram HTML Escaping & Injection Defense

#### Tested Files & Line References
1. **`agent/agent.py`**
   - Lines 151–160: `validate_tailscale_cgnat_ip(ip)`
   - Lines 162–191: `compute_screen_coordinates(width, height, rotation)`
   - Lines 194–327: `build_tailscale_command(mode)`
   - Lines 702–718: `handle_incoming_batch_action` for `CONTROL_TAILSCALE` mode `on`:
     ```python
     703: ip_match = re.search(r"100\.\d{1,3}\.\d{1,3}\.\d{1,3}", stdout_text)
     704: is_valid_ip = False
     705: if ip_match:
     706:     is_valid_ip = validate_tailscale_cgnat_ip(ip_match.group(0))
     707:
     708: if success and stdout_text.startswith("CONNECTED:") and is_valid_ip:
     709:     status = "OPENED"
     710:     executed = True
     711:     details = stdout_text
     712:     reason = None
     ```
2. **`worker/fleet_state.js`**
   - Lines 960–975: `acknowledgeTailscaleControl`:
     ```javascript
     967: const ipMatch = String(body.details || "").match(/100\.\d{1,3}\.\d{1,3}\.\d{1,3}/);
     968: const tailscaleIp = ipMatch ? ipMatch[0] : null;
     969:
     970: // Strict success gating: mode 'on' requires valid IP and OPENED/SUCCESS status
     971: let isSuccess = status === "OPENED" || status === "SUCCESS";
     972: if (mode === "on") {
     973:   isSuccess = isSuccess && Boolean(tailscaleIp);
     974: }
     ```

### Empirical Test Execution Results

Two dedicated adversarial test harnesses were created and executed outside `.agents/` in `tests/`:
1. `tests/test_adversarial_agent.py` (16 test cases)
2. `tests/test_adversarial_fleet.mjs` (6 test suites)

#### Execution Output 1: `python3 -m unittest -v tests/test_adversarial_agent.py`
```
test_invalid_octets_greater_than_255 (tests.test_adversarial_agent.TestIPValidationStress.test_invalid_octets_greater_than_255) ... ok
test_malformed_ip_structures (tests.test_adversarial_agent.TestIPValidationStress.test_malformed_ip_structures) ... ok
test_partial_ip_suffix_attack_on_agent_handling (tests.test_adversarial_agent.TestIPValidationStress.test_partial_ip_suffix_attack_on_agent_handling)
Adversarial check: if stdout is 'CONNECTED: 100.1.2.2555', what does agent do? ... 
[EMPIRICAL TEST] Suffix 100.1.2.2555 result: status=OPENED, details=CONNECTED: 100.1.2.2555
ok
test_valid_cgnat_ips (tests.test_adversarial_agent.TestIPValidationStress.test_valid_cgnat_ips) ... ok
test_inverted_dimensions_portrait_rotation (tests.test_adversarial_agent.TestOrientationStress.test_inverted_dimensions_portrait_rotation) ... ok
test_odd_and_ultra_tall_resolutions (tests.test_adversarial_agent.TestOrientationStress.test_odd_and_ultra_tall_resolutions) ... ok
test_square_display (tests.test_adversarial_agent.TestOrientationStress.test_square_display) ... ok
test_standard_resolutions_all_rotations (tests.test_adversarial_agent.TestOrientationStress.test_standard_resolutions_all_rotations) ... ok
test_unexpected_rotation_types_and_values (tests.test_adversarial_agent.TestOrientationStress.test_unexpected_rotation_types_and_values) ... ok
test_fake_success_triggered_is_rejected (tests.test_adversarial_agent.TestSubprocessTimeoutAndFailureStress.test_fake_success_triggered_is_rejected) ... ok
test_invalid_ip_in_stdout_returns_failed (tests.test_adversarial_agent.TestSubprocessTimeoutAndFailureStress.test_invalid_ip_in_stdout_returns_failed) ... ok
test_shell_exit_code_1_timeout (tests.test_adversarial_agent.TestSubprocessTimeoutAndFailureStress.test_shell_exit_code_1_timeout) ... ok
test_shell_killed_by_sigkill (tests.test_adversarial_agent.TestSubprocessTimeoutAndFailureStress.test_shell_killed_by_sigkill) ... ok
test_subprocess_timeout_expired (tests.test_adversarial_agent.TestSubprocessTimeoutAndFailureStress.test_subprocess_timeout_expired) ... ok
test_keyevents_and_user0_present (tests.test_adversarial_agent.TestUIKeyeventsAndCommandIntegrity.test_keyevents_and_user0_present) ... ok
test_keyevents_have_error_suppression (tests.test_adversarial_agent.TestUIKeyeventsAndCommandIntegrity.test_keyevents_have_error_suppression) ... ok

----------------------------------------------------------------------
Ran 16 tests in 0.157s

OK
```

#### Execution Output 2: `node tests/test_adversarial_fleet.mjs`
```
=========================================
  RUNNING ADVERSARIAL FLEET TESTS
=========================================

[TEST 1] ACK with malformed IP 100.300.1.1 (octet > 255)
Result for 100.300.1.1: { ok: true, action_id: 'act-1', device_id: 'm77', status: 'OPENED' }
Telegram Msg for 100.300.1.1:
 🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.300.1.1</b>
📱 Thiết bị: <code>m77</code>
⚙️ Chế độ: <b>ON</b>
🔒 Mạng nội bộ Tailscale đã sẵn sàng.
⚠️ FINDING: Fleet State accepted invalid octet 100.300.1.1 because regex /100\.\d{1,3}.../ doesn't check octets <= 255

[TEST 2] ACK with 4-digit octet 100.1.2.2555
Result for 100.1.2.2555: { ok: true, action_id: 'act-2', device_id: 'm77', status: 'OPENED' }
Telegram Msg for 100.1.2.2555:
 🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.1.2.255</b>
📱 Thiết bị: <code>m77</code>
⚙️ Chế độ: <b>ON</b>
🔒 Mạng nội bộ Tailscale đã sẵn sàng.
⚠️ FINDING: Fleet State regex truncated 100.1.2.2555 to 100.1.2.255 due to lack of word boundary \b

[TEST 3] HTML Escaping in failure reason
Escaped Failure Message:
 ❌ <b>BẬT TAILSCALE THẤT BẠI: &lt;script&gt;alert('pwn')&lt;/script&gt; &amp; Error &lt;timeout&gt; with a &gt; b</b>
📱 Thiết bị: <code>m77</code>
⚠️ Lý do: &lt;script&gt;alert('pwn')&lt;/script&gt; &amp; Error &lt;timeout&gt; with a &gt; b
PASS: HTML tags and entities properly escaped in failure message.

[TEST 4] HTML Escaping in status mode disconnected detail
Escaped Status Disconnected Message:
 ⚠️ <b>TRẠNG THÁI TAILSCALE: DISCONNECTED</b>
📱 Thiết bị: <code>m77</code>
📶 Trạng thái: <b>DISCONNECTED</b>
📋 Chi tiết: <code>DISCONNECTED &lt;reason: interface down &amp; unreachable&gt;</code>
PASS: Status disconnected details properly escaped.

[TEST 5] Rejection of legacy fake TRIGGERED
PASS: Legacy TRIGGERED successfully rejected by Fleet State.

[TEST 6] Device ID normalization
PASS: Device ID normalization handles boundary and injection inputs.

=========================================
  ALL ADVERSARIAL FLEET TESTS COMPLETE
=========================================
```

---

## 2. Logic Chain

1. **Orientation & Resolution Stress (Target 1)**:
   - *Observation*: Tested resolutions from standard 720x1280 and 1080x1920 to ultra-tall 1080x2400 (20:9), 720x1520 (19:9), 1440x3200, square displays 1000x1000, and inverted dimensions (width > height with rotation 0).
   - *Logic*: In all scenarios, `compute_screen_coordinates` produced coordinates strictly within screen bounds (`0 <= toggle_x <= width`, `0 <= toggle_y <= height`, `0 <= center_x <= width`, `0 <= center_y <= height`). Toggle switch coordinates remain in the top-right quadrant and Connect button is centered. The shell script in `build_tailscale_command` incorporates fallback heuristics (`wm size` parsing defaults safely to 720x1280 if unparseable).
   - *Conclusion*: Screen orientation and coordinate handling are robust against edge cases.

2. **Timeout, Shell Failure & Kill Signals (Target 3)**:
   - *Observation*: Evaluated `handle_incoming_batch_action` when `subprocess.run` / `_run_as_root` times out after 30s, when the shell script exits with returncode 1 (12s timeout), when the process is killed with `SIGKILL` (returncode -9 / 137), and when legacy `TRIGGERED` is returned.
   - *Logic*: Every failure condition resulted in `status = "FAILED"`, `executed = False`, and `details = None`. Legacy `TRIGGERED` output is strictly rejected in both `agent.py` and `fleet_state.js`.
   - *Conclusion*: Phantom success reporting is reliably eliminated across all failure paths.

3. **UI Keyevents & Error Suppression (Target 4)**:
   - *Observation*: In `build_tailscale_command`, `input keyevent KEYCODE_BACK` and `input keyevent KEYCODE_HOME` are sent with a 0.5s pause upon successful connection.
   - *Logic*: All keyevent invocations are appended with `>/dev/null 2>&1 || true`. If `input` binary is absent, permission-restricted, or fails on a custom emulator ROM, the failure does not abort the shell script or invalidate genuine VPN connections.
   - *Conclusion*: Keyevents are resilient and safely guarded.

4. **Telegram HTML Escaping (Target 5)**:
   - *Observation*: In `worker/fleet_state.js`, all dynamic text fields (`failReason`, `rawDetail`, `detailsStr`, exception messages) are sanitized via `escapeHtml = (str) => String(str || "").replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')`.
   - *Logic*: Entities `&`, `<`, and `>` are escaped in the correct order (preventing double-escaping). Malicious payloads containing `<script>`, `&`, `>`, or `<` render as benign HTML entities. Furthermore, `deviceId` is strictly validated by `normalizeDeviceId`, preventing tag injection in device fields.
   - *Conclusion*: Telegram message formatting is secure against HTML injection and malformed entity errors.

5. **Malformed IPs & Boundary Leakage (Target 2) — DEFECT CONFIRMED**:
   - *Observation A (Fleet State octet range leak)*:
     In `worker/fleet_state.js` line 967:
     `const ipMatch = String(body.details || "").match(/100\.\d{1,3}\.\d{1,3}\.\d{1,3}/);`
     `const tailscaleIp = ipMatch ? ipMatch[0] : null;`
     When an ACK arrives with `details: "CONNECTED: 100.300.1.1"`:
     `ipMatch[0]` evaluates to `"100.300.1.1"`.
     Because `fleet_state.js` performs NO octet boundary checks (`octet <= 255`), `tailscaleIp` is truthy, `isSuccess` evaluates to `true`, and Fleet State broadcasts:
     `🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.300.1.1</b>`!
     This directly violates Task 2: *"Malformed IPs: IPs that have `100.` prefix but are invalid octets (e.g. `100.300.1.1`, `100.abc.1.1`, `100.1.1`). Ensure regex strictly matches valid IPv4."*
   - *Observation B (Missing Word Boundary `\b` Suffix Truncation)*:
     In `agent/agent.py` line 703 and `worker/fleet_state.js` line 967:
     The regex `100\.\d{1,3}\.\d{1,3}\.\d{1,3}` lacks a trailing word boundary `\b`.
     When `stdout_text` is `"CONNECTED: 100.1.2.2555"` (an invalid 4-digit octet):
     `re.search` matches `"100.1.2.255"` (the first 3 digits).
     `validate_tailscale_cgnat_ip("100.1.2.255")` evaluates octets `[1, 2, 255] <= 255` -> `True`!
     `agent.py` accepts this and sends `status: "OPENED"` with `details: "CONNECTED: 100.1.2.2555"`.
   - *Conclusion*: The IP extraction regexes across both `agent.py` and `fleet_state.js` are insufficiently strict against malformed IPv4 octets.

---

## 3. Caveats

1. **Subprocess Execution in Sandboxes**: `agent.py` supports both Termux/root execution via `_run_as_root` and non-root execution via `subprocess.run(["sh", "-c", ...])`. Our tests confirmed that both execution paths correctly propagate timeouts and failures.
2. **Zero Live Device Interaction**: Per Rule R4 of `ORIGINAL_REQUEST.md`, all tests were executed hermetically without contacting live UgPhone devices (`m77`).

---

## 4. Conclusion

### Verdict: **REQUEST_CHANGES**

While Orientation adaptation (R2), Timeout/Fake Success elimination (R1), Keyevents (R2), and HTML Escaping (R3) all pass stress testing with high robustness, the implementation fails Target 2 regarding **Malformed IP extraction and validation**:
1. `worker/fleet_state.js` accepts invalid octets > 255 (e.g. `100.300.1.1`) and reports false success to Telegram.
2. `agent/agent.py` and `worker/fleet_state.js` lack word boundary `\b` enforcement, leading to truncation of 4-digit octets (e.g. `100.1.2.2555` -> `100.1.2.255`).

### Required Changes for Worker:

1. **In `worker/fleet_state.js` (line 967)**:
   Extract IP with word boundaries and validate all octets are within `0–255`:
   ```javascript
   function extractValidTailscaleIp(details) {
     const match = String(details || "").match(/\b100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b/);
     if (!match) return null;
     const octets = [Number(match[1]), Number(match[2]), Number(match[3])];
     if (octets.some((o) => o < 0 || o > 255 || isNaN(o))) return null;
     return match[0];
   }
   ```
   And replace `const ipMatch = ...` with:
   ```javascript
   const tailscaleIp = extractValidTailscaleIp(body.details);
   ```

2. **In `agent/agent.py` (line 703)**:
   Add word boundary `\b` to regex:
   ```python
   ip_match = re.search(r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", stdout_text)
   ```

---

## 5. Verification Method

To independently verify these findings:

1. **Run Standalone Agent Adversarial Suite**:
   ```bash
   python3 -m unittest -v tests/test_adversarial_agent.py
   ```
   *Expected result*: 16/16 tests pass, empirically demonstrating that `CONNECTED: 100.1.2.2555` currently outputs `status=OPENED` due to missing `\b`.

2. **Run Standalone Fleet State Adversarial Suite**:
   ```bash
   node tests/test_adversarial_fleet.mjs
   ```
   *Expected result*: Demonstrates that `100.300.1.1` is accepted as `OPENED` and broadcasted to Telegram due to unconstrained regex matching.

3. **Run Master Test Suite**:
   ```bash
   bash tests/run_all_tests.sh
   ```
   *Expected result*: All 7 existing test suites pass.

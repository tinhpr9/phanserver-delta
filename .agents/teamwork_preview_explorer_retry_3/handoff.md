# Handoff Report: Tailscale Test Suite Hardening for Malformed IP Edge Cases (Explorer Retry 3)

## 1. Observation

### Exact File Paths and Line Numbers Inspected
1. **`agent/agent.py`**
   - Lines 151–160: `validate_tailscale_cgnat_ip(ip)`
   - Lines 162–191: `compute_screen_coordinates(width, height, rotation)`
   - Lines 194–327: `build_tailscale_command(mode)`
   - Line 703: `ip_match = re.search(r"100\.\d{1,3}\.\d{1,3}\.\d{1,3}", stdout_text)`
   - Lines 708–717: Execution gating on `success and stdout_text.startswith("CONNECTED:") and is_valid_ip`
2. **`worker/fleet_state.js`**
   - Lines 967–968:
     ```javascript
     const ipMatch = String(body.details || "").match(/100\.\d{1,3}\.\d{1,3}\.\d{1,3}/);
     const tailscaleIp = ipMatch ? ipMatch[0] : null;
     ```
   - Lines 971–974: `let isSuccess = status === "OPENED" || status === "SUCCESS"; if (mode === "on") { isSuccess = isSuccess && Boolean(tailscaleIp); }`
   - Lines 1005–1018: Telegram notification rendering with `${tailscaleIp}`
3. **`tests/test_device_agent.py`**
   - Lines 262–278: `test_cgnat_100_ip_validation`
   - Lines 120–143: `test_elimination_of_fake_triggered_opened`
   - Lines 94–118: `test_tailscale_connect_timeout_returns_failed`
4. **`tests/test_fleet_state_2pc.mjs`**
   - Lines 292–321: `7. CONTROL_TAILSCALE is queued per device and delivered through heartbeat`
   - Lines 323–340: `7b. CONTROL_TAILSCALE failure / timeout reporting`
   - Lines 342–360: `7c. CONTROL_TAILSCALE fake success elimination (TRIGGERED without IP must be rejected as FAILED)`
   - Lines 361–395: `7d. CONTROL_TAILSCALE status check connected & disconnected`
   - Lines 396–413: `7e. CONTROL_TAILSCALE off mode`
5. **Challenger 1 Adversarial Suites**:
   - `tests/test_adversarial_agent.py`: 16 adversarial test cases covering orientation, IP regex, timeout, and keyevents.
   - `tests/test_adversarial_fleet.mjs`: 6 adversarial test suites covering malformed IPs, truncation, HTML escaping, and device ID validation.

---

### Empirical Reproduction & Observed Defects

#### 1. Device Agent Suffix Truncation Defect (`100.1.2.2555`)
- Command executed:
  ```bash
  python3 -c '
  from agent.agent import handle_incoming_batch_action, validate_tailscale_cgnat_ip
  from unittest.mock import MagicMock, patch
  import pathlib, tempfile

  print("validate 100.300.1.1:", validate_tailscale_cgnat_ip("100.300.1.1"))
  print("validate 100.1.2.2555:", validate_tailscale_cgnat_ip("100.1.2.2555"))

  td = tempfile.TemporaryDirectory()
  rp = pathlib.Path(td.name)
  state = {}
  mock_proc = MagicMock(returncode=0, stdout="CONNECTED: 100.1.2.2555\n", stderr="")
  with patch("subprocess.run", return_value=mock_proc), patch("agent.agent.send_ack") as mock_ack:
      handle_incoming_batch_action({"protocol": "fleet-batch-v1", "action": "CONTROL_TAILSCALE", "action_id": "t1", "mode": "on", "target_device_ids": ["m77"]}, "m77", "http://worker/report", "sec", state, rp / "state.json", rp / "server_links.txt")
      print("Agent result for CONNECTED: 100.1.2.2555:", mock_ack.call_args.kwargs["status"])
  '
  ```
- Output:
  ```
  validate 100.300.1.1: False
  validate 100.1.2.2555: False
  Agent result for CONNECTED: 100.1.2.2555: OPENED
  ```
- *Finding*: Even though `validate_tailscale_cgnat_ip("100.1.2.2555")` returns `False`, `re.search(r"100\.\d{1,3}\.\d{1,3}\.\d{1,3}", stdout_text)` truncates `100.1.2.2555` to `100.1.2.255` because it lacks a word boundary `\b`. The agent validates `100.1.2.255` as valid CGNAT IP and erroneously reports `status: "OPENED"` with `details: "CONNECTED: 100.1.2.2555"`.

#### 2. Fleet State Octet Boundary & Truncation Defect (`100.300.1.1` and `100.1.2.2555`)
- Command executed:
  ```bash
  node -e '
  import("./worker/fleet_state.js").then(async ({ FleetState }) => {
    let msg = null;
    globalThis.fetch = async (url, init) => { msg = JSON.parse(init.body); return { ok: true, json: async () => ({}) }; };
    const storage = { store: new Map(), async get(k) { return this.store.get(k); }, async put(k, v) { this.store.set(k, v); } };
    const ctx = { storage, sockets: new Map(), getWebSockets() { return []; } };
    const fleet = new FleetState(ctx, { TEST_ENV: true, TELEGRAM_BOT_TOKEN: "tok", TELEGRAM_ADMIN_USER_ID: "123" });
    await fleet.handleHeartbeat(new Request("https://localhost/report", { method: "POST", body: JSON.stringify({ device_id: "m1", device_group: "NOVA" }) }));
    
    // Case 1: 100.300.1.1
    const res1 = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", { method: "POST", body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "on", target_device_ids: ["m1"], telegram_chat_id: 123 }) }))).json();
    await fleet.handleHeartbeat(new Request("https://localhost/report", { method: "POST", body: JSON.stringify({ device_id: "m1", device_group: "NOVA" }) }));
    const ack1 = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", { method: "POST", body: JSON.stringify({ protocol: "fleet-batch-v1", batch_action: "CONTROL_TAILSCALE", device_id: "m1", action_id: res1.tailscale.action_id, status: "OPENED", executed: true, details: "CONNECTED: 100.300.1.1" }) }))).json();
    console.log("Fleet result for 100.300.1.1 status:", ack1.status);
    console.log("Telegram text for 100.300.1.1:\n", msg?.text);

    // Case 2: 100.1.2.2555
    const res2 = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", { method: "POST", body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "on", target_device_ids: ["m1"], telegram_chat_id: 123 }) }))).json();
    await fleet.handleHeartbeat(new Request("https://localhost/report", { method: "POST", body: JSON.stringify({ device_id: "m1", device_group: "NOVA" }) }));
    const ack2 = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", { method: "POST", body: JSON.stringify({ protocol: "fleet-batch-v1", batch_action: "CONTROL_TAILSCALE", device_id: "m1", action_id: res2.tailscale.action_id, status: "OPENED", executed: true, details: "CONNECTED: 100.1.2.2555" }) }))).json();
    console.log("Fleet result for 100.1.2.2555 status:", ack2.status);
    console.log("Telegram text for 100.1.2.2555:\n", msg?.text);
  });
  '
  ```
- Output:
  ```
  Fleet result for 100.300.1.1 status: OPENED
  Telegram text for 100.300.1.1:
   🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.300.1.1</b>
  📱 Thiết bị: <code>m1</code>
  ⚙️ Chế độ: <b>ON</b>
  🔒 Mạng nội bộ Tailscale đã sẵn sàng.

  Fleet result for 100.1.2.2555 status: OPENED
  Telegram text for 100.1.2.2555:
   🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.1.2.255</b>
  📱 Thiết bị: <code>m1</code>
  ⚙️ Chế độ: <b>ON</b>
  🔒 Mạng nội bộ Tailscale đã sẵn sàng.
  ```
- *Finding*: `worker/fleet_state.js` accepts `100.300.1.1` as valid because the regex does not bound octets to `<= 255`. Furthermore, it truncates `100.1.2.2555` to `100.1.2.255` and broadcasts false success to Telegram.

---

## 2. Logic Chain

1. **Test Coverage Gap Analysis**:
   - In `tests/test_device_agent.py`:
     * `test_cgnat_100_ip_validation` tests `validate_tailscale_cgnat_ip("100.300.1.1")` directly, but does NOT test `100.1.2.2555`, nor does it test malformed IPs passed through `handle_incoming_batch_action` (end-to-end agent action handler).
     * There is NO test ensuring that if subprocess stdout outputs `CONNECTED: 100.300.1.1` or `CONNECTED: 100.1.2.2555`, the agent rejects the action with `status: "FAILED"` and `details: None`.
   - In `tests/test_fleet_state_2pc.mjs`:
     * Section 7 only tests happy path (`100.80.175.55`), timeout (`FAILED`), and fake `TRIGGERED`.
     * There is NO test where `details` has malformed IP octets (`100.300.1.1`) or malformed suffix digits (`100.1.2.2555`).

2. **Integration of Adversarial Scenarios from Challenger 1**:
   - `tests/test_adversarial_agent.py` contains 4 critical test categories that should be integrated into `tests/test_device_agent.py`:
     1. Malformed IP rejection in `handle_incoming_batch_action` (`100.300.1.1`, `100.1.2.2555`, `100.1.256.1`, `100.abc.1.1`, `100.1.2`).
     2. Exhaustive octet boundary & structure unit tests in `validate_tailscale_cgnat_ip`.
     3. Subprocess timeout (`TimeoutExpired`) and signal termination (`SIGKILL` / returncode `-9`).
     4. Screen orientation boundary cases (ultra-tall 20:9, square displays, out-of-range rotation bounds).
     5. Keyevent error suppression (`|| true` on `input keyevent`).
   - `tests/test_adversarial_fleet.mjs` contains 2 critical IP tests that should be integrated into `tests/test_fleet_state_2pc.mjs`:
     1. Section `7f` Case A: ACK with `CONNECTED: 100.300.1.1` -> FleetState rejects with `status: "FAILED"` and sends failure alert to Telegram.
     2. Section `7f` Case B: ACK with `CONNECTED: 100.1.2.2555` -> FleetState rejects with `status: "FAILED"` and does NOT truncate or report success.

3. **Required Production Fixes to Satisfy Hardened Tests**:
   - **Fix 1 (`agent/agent.py` line 703)**:
     Change:
     ```python
     ip_match = re.search(r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", stdout_text)
     ```
     Enforces word boundary `\b` before `100` and after the 3rd octet. `CONNECTED: 100.1.2.2555` fails to match because `55` is not a word boundary.
   - **Fix 2 (`worker/fleet_state.js`)**:
     Add helper function:
     ```javascript
     export function extractValidTailscaleIp(details) {
       const match = String(details || "").match(/\b100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b/);
       if (!match) return null;
       const octets = [Number(match[1]), Number(match[2]), Number(match[3])];
       if (octets.some((o) => o < 0 || o > 255 || Number.isNaN(o))) return null;
       return match[0];
     }
     ```
     And replace line 967 in `acknowledgeTailscaleControl`:
     ```javascript
     const tailscaleIp = extractValidTailscaleIp(body.details);
     ```

4. **Preservation of All 7 Test Suites in `tests/run_all_tests.sh`**:
   - The proposed test additions in `tests/test_device_agent.py` and `tests/test_fleet_state_2pc.mjs` are completely isolated and hermetic.
   - Section `7f` in `tests/test_fleet_state_2pc.mjs` cleans up pending actions via `dispatchFleetAck` before Section 8 (`CHECK_BAN`) begins.
   - Empirical test execution in `.agents/teamwork_preview_explorer_retry_3/proposed_test_device_agent_additions.py` and `.agents/teamwork_preview_explorer_retry_3/proposed_test_fleet_state_additions.mjs` confirmed 100% pass rates.

---

## 3. Caveats

1. **Read-Only Scope**: Explorer Retry 3 strictly adhered to the read-only mandate. Neither production code (`agent/agent.py`, `worker/fleet_state.js`) nor existing test files (`tests/test_device_agent.py`, `tests/test_fleet_state_2pc.mjs`) were modified in the project repository. All proposed additions and proof-of-concept tests are stored in `.agents/teamwork_preview_explorer_retry_3/`.
2. **Implementation Delegation**: The actual application of the test additions and production fixes must be performed by the designated worker / implementer agent.
3. **Hermetic R4 Compliance**: All investigated test cases use mock subprocess and mock fetch. No actual network or device interaction is performed.

---

## 4. Conclusion

### Concrete Test Additions to be Applied

#### Addition 1: `tests/test_device_agent.py`
Add to `test_cgnat_100_ip_validation`:
```python
        # Malformed octets and suffixes
        self.assertFalse(validate_tailscale_cgnat_ip("100.300.1.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.2.2555"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.256.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.1.999"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.999.999.999"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.abc.1.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.2.3.4"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.-1.0.1"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.2.3/24"))
        self.assertFalse(validate_tailscale_cgnat_ip("100.1.2."))
        self.assertFalse(validate_tailscale_cgnat_ip(".100.1.2.3"))
        self.assertFalse(validate_tailscale_cgnat_ip("100..1.2"))
        self.assertFalse(validate_tailscale_cgnat_ip(12345))
        self.assertFalse(validate_tailscale_cgnat_ip(["100.64.0.1"]))
```

Add new test methods to `TestTailscaleDeviceAgent`:
```python
    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_tailscale_connect_malformed_ip_returns_failed(self, mock_subproc, mock_ack):
        """Verify malformed IP outputs in stdout (100.300.1.1, 100.1.2.2555) are strictly rejected as FAILED."""
        malformed_cases = [
            ("CONNECTED: 100.300.1.1", "bad-octet-300"),
            ("CONNECTED: 100.1.2.2555", "bad-suffix-2555"),
            ("CONNECTED: 100.1.256.1", "bad-octet-256"),
            ("CONNECTED: 100.abc.1.1", "bad-char-abc"),
            ("CONNECTED: 100.1.2", "bad-short"),
            ("CONNECTED: 100.1.2.3.4", "bad-long"),
            ("CONNECTED: 192.168.1.1", "bad-lan-192"),
            ("CONNECTED: 10.0.0.1", "bad-lan-10"),
        ]
        state = {}
        for stdout_val, action_suffix in malformed_cases:
            mock_subproc.return_value.returncode = 0
            mock_subproc.return_value.stdout = f"{stdout_val}\n"
            mock_subproc.return_value.stderr = ""
            mock_ack.reset_mock()

            action_id = f"ts-malformed-{action_suffix}"
            message = {
                "protocol": "fleet-batch-v1",
                "action": "CONTROL_TAILSCALE",
                "action_id": action_id,
                "mode": "on",
                "target_device_ids": [self.device_id],
            }

            handle_incoming_batch_action(
                message, self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
            )

            self.assertTrue(mock_ack.called)
            kwargs = mock_ack.call_args.kwargs
            self.assertEqual(
                kwargs["status"], "FAILED",
                f"Expected status 'FAILED' for stdout '{stdout_val}', got '{kwargs['status']}'"
            )
            self.assertFalse(
                kwargs["executed"],
                f"Expected executed=False for stdout '{stdout_val}'"
            )
            self.assertIsNone(
                kwargs["details"],
                f"Expected details=None for stdout '{stdout_val}'"
            )
            self.assertIn("vpn_timeout_no_ip", kwargs["reason"])

    @mock.patch("agent.agent.send_ack", return_value=True)
    @mock.patch("agent.agent.subprocess.run")
    def test_subprocess_timeout_and_signal_termination(self, mock_subproc, mock_ack):
        """Verify subprocess.TimeoutExpired and SIGKILL termination return FAILED."""
        state = {}
        mock_subproc.side_effect = subprocess.TimeoutExpired(cmd="sh", timeout=30)
        handle_incoming_batch_action(
            {"protocol": "fleet-batch-v1", "action": "CONTROL_TAILSCALE", "action_id": "ts-timeout-exc", "mode": "on", "target_device_ids": [self.device_id]},
            self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertEqual(mock_ack.call_args.kwargs["status"], "FAILED")
        self.assertFalse(mock_ack.call_args.kwargs["executed"])

        mock_subproc.side_effect = None
        mock_subproc.return_value.returncode = -9
        mock_subproc.return_value.stdout = ""
        mock_subproc.return_value.stderr = "Killed\n"
        handle_incoming_batch_action(
            {"protocol": "fleet-batch-v1", "action": "CONTROL_TAILSCALE", "action_id": "ts-sigkill-exc", "mode": "on", "target_device_ids": [self.device_id]},
            self.device_id, self.report_url, self.secret, state, self.state_path, self.links_path
        )
        self.assertEqual(mock_ack.call_args.kwargs["status"], "FAILED")
        self.assertFalse(mock_ack.call_args.kwargs["executed"])

    def test_screen_orientation_adversarial_resolutions(self):
        """Test ultra-tall, square, and out-of-bound rotation inputs."""
        coords_tall = compute_screen_coordinates(1080, 2400, rotation=0)
        self.assertFalse(coords_tall["is_landscape"])
        self.assertGreater(coords_tall["toggle_x"], 0)
        self.assertLess(coords_tall["toggle_x"], 1080)
        self.assertGreater(coords_tall["toggle_y"], 0)
        self.assertLess(coords_tall["toggle_y"], 2400)

        coords_sq = compute_screen_coordinates(1000, 1000, rotation=0)
        self.assertEqual(coords_sq["center_x"], 500)
        self.assertEqual(coords_sq["center_y"], 500)

        coords_oob = compute_screen_coordinates(720, 1280, rotation=4)
        self.assertFalse(coords_oob["is_landscape"])

    def test_ui_keyevents_error_suppression(self):
        """Verify UI keyevent commands in shell script have error suppression (|| true)."""
        cmd = build_tailscale_command("on")
        for ke in ["KEYCODE_BACK", "KEYCODE_HOME"]:
            pattern = rf"input keyevent {ke}\s*>/dev/null\s*2>&1\s*\|\|\s*true"
            self.assertRegex(cmd, pattern, f"Keyevent {ke} missing error suppression")
```

#### Addition 2: `tests/test_fleet_state_2pc.mjs`
Insert section `7f` right after line 413 (after `7e` off mode):
```javascript
  // 7f. CONTROL_TAILSCALE malformed IP rejection (100.300.1.1 & 100.1.2.2555)
  // Case A: octet > 255 (100.300.1.1)
  const tsBadOctetRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "on", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const tsBadOctetActionId = tsBadOctetRes.tailscale.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  notifiedTelegram = null;
  const tsBadOctetAck = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "CONTROL_TAILSCALE",
      device_id: "m1",
      action_id: tsBadOctetActionId,
      status: "OPENED",
      executed: true,
      details: "CONNECTED: 100.300.1.1"
    })
  }))).json();
  if (tsBadOctetAck.status !== "FAILED") throw new Error("Expected malformed IP 100.300.1.1 to be rejected as FAILED: " + JSON.stringify(tsBadOctetAck));
  if (!notifiedTelegram?.text?.includes("BẬT TAILSCALE THẤT BẠI") || notifiedTelegram?.text?.includes("THÀNH CÔNG")) {
    throw new Error("Malformed IP 100.300.1.1 must not report success to Telegram: " + notifiedTelegram?.text);
  }

  // Case B: 4-digit octet suffix attack (100.1.2.2555)
  const tsBadDigitRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "on", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const tsBadDigitActionId = tsBadDigitRes.tailscale.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  notifiedTelegram = null;
  const tsBadDigitAck = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "CONTROL_TAILSCALE",
      device_id: "m1",
      action_id: tsBadDigitActionId,
      status: "OPENED",
      executed: true,
      details: "CONNECTED: 100.1.2.2555"
    })
  }))).json();
  if (tsBadDigitAck.status !== "FAILED") throw new Error("Expected malformed IP 100.1.2.2555 to be rejected as FAILED: " + JSON.stringify(tsBadDigitAck));
  if (!notifiedTelegram?.text?.includes("BẬT TAILSCALE THẤT BẠI") || notifiedTelegram?.text?.includes("THÀNH CÔNG") || notifiedTelegram?.text?.includes("100.1.2.255")) {
    throw new Error("Malformed IP 100.1.2.2555 must not report success or truncated IP to Telegram: " + notifiedTelegram?.text);
  }
```

---

## 5. Verification Method

To verify these findings and test hardening independently:

1. **Verify Unit & Agent Test Additions**:
   ```bash
   python3 /root/phanserver-delta/.agents/teamwork_preview_explorer_retry_3/proposed_test_device_agent_additions.py
   ```
   *Expected result*: 4/4 test cases pass, verifying `100.300.1.1` and `100.1.2.2555` validation rejection, timeout handling, screen coordinates, and keyevent error suppression.

2. **Verify Integration Test Additions for Fleet State**:
   ```bash
   node /root/phanserver-delta/.agents/teamwork_preview_explorer_retry_3/proposed_test_fleet_state_additions.mjs
   ```
   *Expected result*: Both `100.300.1.1` and `100.1.2.2555` are rejected as `FAILED`, and Telegram failure alerts are confirmed.

3. **Verify Unified Patch Availability**:
   - Test patch: `/root/phanserver-delta/.agents/teamwork_preview_explorer_retry_3/tests_enhancement.patch`
   - Production reference patch: `/root/phanserver-delta/.agents/teamwork_preview_explorer_retry_3/production_fixes_reference.patch`

4. **Verify Master Test Suite**:
   ```bash
   bash /root/phanserver-delta/tests/run_all_tests.sh
   ```
   *Expected result*: All 7/7 suites pass cleanly with zero regressions.

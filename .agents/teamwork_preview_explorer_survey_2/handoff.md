# Handoff Report: Telegram Bot & Worker Handler Analysis for /vpn and /tailscale (R3)

## 1. Observation

### 1.1 Baseline Test Suite Execution
Direct execution of the project test runner `bash tests/run_all_tests.sh`:
- Output: All 7 suites passed cleanly (100%):
  - `[1/7] tests/test_tong_hop_link.mjs`: `TEST_TONG_HOP_LINK_EQUIVALENCE=OK`
  - `[2/7] tests/test_telegram_phanserver.mjs`: `TEST_TELEGRAM_PHANSERVER_EQUIVALENCE=OK`
  - `[3/7] tests/test_fleet_state_2pc.mjs`: `TEST_FLEET_STATE_2PC_EQUIVALENCE=OK`
  - `[4/7] delta/tests`: 27 tests in 0.705s OK
  - `[5/7] agent/tests`: 20 tests in 2.735s OK
  - `[6/7] tests/test_account_manager.py`: 23 passed in 11.75s OK
  - `[7/7] tests/test_e2e_flow.py`: 2 tests in 0.189s OK

### 1.2 Telegram Bot Handler Location & Implementation
In `/root/phanserver-delta/worker/phanserver.js` (lines 489–533):
```javascript
489:   if (input.match(/^\/(?:tailscale|vpn)(?:\s|$)/)) {
490:     const raw = input.replace(/^\/(?:tailscale|vpn)\s*/, "").trim();
491:     if (!raw) {
492:       await telegram(env, "sendMessage", {
493:         chat_id: chatId,
494:         text: "Cú pháp: /tailscale <device1,device2... hoặc all> [on|off|status]\nVí dụ: <code>/tailscale m77 on</code> hoặc <code>/vpn m77 status</code>",
495:         parse_mode: "HTML"
496:       });
497:       return;
498:     }
499:     const parts = raw.split(/\s+/);
500:     const targetStr = parts[0];
501:     const mode = (parts[1] || "on").toLowerCase();
502:     if (!["on", "off", "status"].includes(mode)) {
503:       await telegram(env, "sendMessage", {
504:         chat_id: chatId,
505:         text: "Chế độ không hợp lệ. Vui lòng chọn: <code>on</code>, <code>off</code>, hoặc <code>status</code> (mặc định: on).",
506:         parse_mode: "HTML"
507:       });
508:       return;
509:     }
510:     try {
511:       const ids = await resolveAndValidateTelegramTargets(targetStr, env, fleetState);
512:       const result = await fleetStateCall(env, fleetState, "/aot/hub/control", {
513:         method: "POST",
514:         body: {
515:           protocol: "fleet-batch-v1",
516:           kind: "control_tailscale",
517:           target_device_ids: ids,
518:           mode: mode,
519:           telegram_chat_id: chatId
520:         }
521:       });
522:       if (!result?.response?.ok) throw new Error(result?.data?.error || "tailscale_queue_failed");
523:       const modeLabel = mode === "off" ? "TẮT" : (mode === "status" ? "KIỂM TRA TRẠNG THÁI" : "BẬT");
524:       await telegram(env, "sendMessage", {
525:         chat_id: chatId,
526:         text: `🌐 <b>ĐÃ XẾP LỆNH ${modeLabel} TAILSCALE</b>\nThiết bị: <code>${ids.join(", ")}</code>\nChế độ: <b>${mode.toUpperCase()}</b>\nThiết bị sẽ tự động thực thi và gửi thông báo kết quả ở heartbeat kế tiếp.`,
527:         parse_mode: "HTML"
528:       });
529:     } catch (error) {
530:       await telegram(env, "sendMessage", { chat_id: chatId, text: "Lỗi CONTROL_TAILSCALE: " + String(error.message || error) });
531:     }
532:     return;
533:   }
```
In `/root/phanserver-delta/worker/phanserver.js` (line 556):
```javascript
556: • <code>/tailscale &lt;devices&gt; [on|off|status]</code>: Bật/tắt/kiểm tra mạng nội bộ Tailscale VPN
```

### 1.3 Cloudflare Worker Entry Point & Routing
In `/root/phanserver-delta/worker/worker.js` (lines 75–96):
```javascript
75:     // Get FleetState Durable Object stub
76:     const fleetId = env.FLEET_STATE?.idFromName?.("global") || null;
77:     const fleetStub = fleetId ? env.FLEET_STATE.get(fleetId) : null;
78: 
79:     if (path === "/telegram/webhook" && request.method === "POST") {
80:       try {
81:         const update = await request.json();
82:         await handleUpdate(update, env, fleetStub);
83:         return new Response("OK", { status: 200 });
84:       } catch (e) {
85:         return new Response("Error: " + e.message, { status: 500 });
86:       }
87:     }
88: 
89:     if (fleetStub) {
90:       return fleetStub.fetch(request);
91:     }
```

### 1.4 FleetState Durable Object Control & Ack Routing
In `/root/phanserver-delta/worker/fleet_state.js`:
- Control router (lines 382–389):
```javascript
382:     if (body.kind === "control_tailscale") {
383:       return this.queueControlTailscale(
384:         record,
385:         Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
386:         body.mode || "on",
387:         { telegram_chat_id: body.telegram_chat_id }
388:       );
389:     }
```
- Queueing logic (lines 916–958):
```javascript
916:   async queueControlTailscale(record, requestedTargetIds, mode = "on", options = {}) {
...
930:     const actionId = `tailscale-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
931:     const normalizedMode = String(mode).toLowerCase() === "off" ? "off" : (String(mode).toLowerCase() === "status" ? "status" : "on");
932:     const command = {
933:       type: "aot_batch_action",
934:       protocol: AOT_HUB_PROTOCOL_VERSION,
935:       action_id: actionId,
936:       action: "CONTROL_TAILSCALE",
937:       mode: normalizedMode,
938:       target_device_ids: targets,
939:       created_at: Date.now()
940:     };
941:     const devices = {};
942:     for (const id of targets) {
943:       fresh.pending_actions[id] = fresh.pending_actions[id] || [];
944:       fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
945:       devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
946:     }
947:     fresh.tailscale_actions = fresh.tailscale_actions || {};
948:     fresh.tailscale_actions[actionId] = {
949:       action_id: actionId,
950:       action: "CONTROL_TAILSCALE",
951:       mode: normalizedMode,
952:       created_at: Date.now(),
953:       devices,
954:       telegram_chat_id: options.telegram_chat_id
955:     };
956:     await this.writeFleet(fresh);
957:     return json({ ok: true, tailscale: { action_id: actionId, mode: normalizedMode, devices: Object.values(devices) } });
958:   }
```
- Device Heartbeat delivery (lines 194–213):
`handleHeartbeat(request)` pops the command from `record.pending_actions[deviceId]` and returns `{ ok: true, device_id: deviceId, command }`.
- Device ACK routing (lines 1576):
```javascript
1576:     if (action === "CONTROL_TAILSCALE") return this.acknowledgeTailscaleControl(record, body, id, actionId);
```
- Device ACK handling & Telegram message formatting (lines 960–996):
```javascript
960:   async acknowledgeTailscaleControl(record, body, deviceId, actionId) {
961:     const act = record.tailscale_actions?.[actionId];
962:     const device = act?.devices?.[deviceId];
963:     const status = String(body.status || "");
964:     if (device && device.status === "QUEUED") {
965:       device.status = status;
966:       device.executed = body.executed === true;
967:       device.reason = status === "FAILED" ? String(body.reason || "device_failed").slice(0, 160) : null;
968:       device.details = body.details ? String(body.details).slice(0, 200) : null;
969:       device.updated_at = Date.now();
970:     }
971:     for (const command of record.pending_actions?.[deviceId] || []) {
972:       if (command.action_id === actionId) command.acknowledged_at = Date.now();
973:     }
974:     await this.writeFleet(record);
975: 
976:     const chatId = act?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
977:     if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
978:       const escapeHtml = (str) => String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
979:       const isSuccess = status === "OPENED" || status === "SUCCESS";
980:       const mode = act?.mode || "on";
981:       const modeDesc = mode === "off" ? "TẮT" : (mode === "status" ? "KIỂM TRA TRẠNG THÁI" : "BẬT");
982:       const details = body.details ? `\n📋 Trạng thái: <code>${escapeHtml(body.details)}</code>` : "";
983:       const msg = isSuccess
984:         ? `🌐 <b>ĐÃ ${modeDesc} TAILSCALE THÀNH CÔNG!</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚙️ Chế độ: <b>${mode.toUpperCase()}</b>${details}\n🔒 Mạng nội bộ Tailscale đã sẵn sàng.`
985:         : `❌ <b>${modeDesc} TAILSCALE THẤT BẠI</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${escapeHtml(body.reason || "Lỗi thiết bị")}`;
986:       try {
987:         await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
988:           method: "POST",
989:           headers: { "Content-Type": "application/json" },
990:           body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
991:         });
992:       } catch (e) {}
993:     }
994: 
995:     return json({ ok: true, action_id: actionId, device_id: deviceId, status: status || "SUCCESS" });
996:   }
```

### 1.5 Device Agent Current Implementation & Root Cause of Fake Success
In `/root/phanserver-delta/agent/agent.py` (lines 577–607):
```python
577:                 for i in 1 2 3 4 5; do
578:                     IP=$(ip addr show dev tun0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d'/' -f1)
579:                     if [ -n "$IP" ]; then
580:                         break
581:                     fi
582:                     sleep 1
583:                 done
584: 
585:                 if [ -n "$IP" ]; then
586:                     # Ẩn giao diện Tailscale để tránh che khuất màn hình game/Termux
587:                     input keyevent KEYCODE_BACK >/dev/null 2>&1 || true
588:                     echo "CONNECTED: $IP"
589:                 else
590:                     echo "TRIGGERED"
591:                 fi
...
596:                 success = res.returncode == 0
597:                 stdout_text = res.stdout.strip()
...
605:             status = "OPENED" if success else "FAILED"
606:             details = stdout_text if stdout_text else ("OK" if success else None)
607:             result = {"status": status, "executed": success, "reason": reason, "details": details}
```
**Critical finding**:
When `IP` is not acquired, line 590 executes `echo "TRIGGERED"`.
Because `echo` succeeds with exit code 0, line 596 sets `success = True`, line 605 sets `status = "OPENED"`, line 606 sets `details = "TRIGGERED"`.
Then in `fleet_state.js` line 979, `isSuccess = status === "OPENED"` evaluates to `true`.
The bot sends to Telegram:
`🌐 ĐÃ BẬT TAILSCALE THÀNH CÔNG!` with `📋 Trạng thái: TRIGGERED` and `🔒 Mạng nội bộ Tailscale đã sẵn sàng.`
This directly violates R1 and creates the reported "báo cáo thành công ảo".

---

## 2. Logic Chain

### 2.1 Answers to the 5 Specific Questions in `context.md`

#### Question 1: Where are the Telegram bot handlers and Worker endpoints for `/vpn` and `/tailscale` located?
1. **Telegram Webhook Dispatcher**: `/root/phanserver-delta/worker/worker.js` (lines 79–86), receiving incoming webhooks and forwarding them to `handleUpdate(update, env, fleetStub)` in `worker/phanserver.js`.
2. **Telegram Command Parsing**: `/root/phanserver-delta/worker/phanserver.js` (lines 489–533) inside `handleUpdate()`. Regular expression: `/^\/(?:tailscale|vpn)(?:\s|$)/`. Also listed in `/help` text at line 556.
3. **Worker Hub Control Endpoint**: `/root/phanserver-delta/worker/fleet_state.js` (lines 382–389), matching `POST /aot/hub/control` with `body.kind === "control_tailscale"` and dispatching to `queueControlTailscale()` (lines 916–958).
4. **Device Heartbeat Polling Endpoint**: `/root/phanserver-delta/worker/fleet_state.js` (lines 174–213), matching `POST /report`, delivering queued action `CONTROL_TAILSCALE` to the target device.
5. **Device Acknowledgement Endpoint**: `/root/phanserver-delta/worker/fleet_state.js` (lines 1561–1576), matching `POST /aot/ack` with `action === "CONTROL_TAILSCALE"` and routing to `acknowledgeTailscaleControl()` (lines 960–996).
6. **Device Agent Action Handler**: `/root/phanserver-delta/agent/agent.py` (lines 486–620) inside `handle_incoming_batch_action()` for `action == "CONTROL_TAILSCALE"`.

#### Question 2: How are `/vpn <device> [on|off|status]` and `/tailscale` parsed and dispatched to devices?
1. **Input Tokenization**:
   - `input.match(/^\/(?:tailscale|vpn)(?:\s|$)/)` verifies the command starts with `/vpn` or `/tailscale`.
   - `raw = input.replace(/^\/(?:tailscale|vpn)\s*/, "").trim()` strips the command prefix.
   - If empty, the bot replies with syntax help.
   - `parts = raw.split(/\s+/)`: `targetStr = parts[0]`, `mode = (parts[1] || "on").toLowerCase()`.
   - `mode` is validated to be one of `"on"`, `"off"`, or `"status"`.
2. **Target Resolution**:
   - `resolveAndValidateTelegramTargets(targetStr, env, fleetState)` checks whether the target is `"all"`, a device group name, or specific device ID(s) like `"m77"`.
   - Throws error if device does not exist or is OFFLINE.
3. **DO Command Queuing**:
   - Worker calls `fleetStateCall(env, fleetState, "/aot/hub/control", ...)` with `kind: "control_tailscale"`.
   - `queueControlTailscale()` assigns a unique `actionId = tailscale-<timestamp>-<uuid8>`.
   - Appends `{ type: "aot_batch_action", action: "CONTROL_TAILSCALE", mode: normalizedMode, action_id, ... }` to `fresh.pending_actions[deviceId]`.
   - Stores action metadata in `fresh.tailscale_actions[actionId]` along with `telegram_chat_id`.
4. **Immediate Telegram Ack**:
   - Worker immediately sends a message informing the user that the command was queued:
     `🌐 ĐÃ XẾP LỆNH [BẬT|TẮT|KIỂM TRA TRẠNG THÁI] TAILSCALE`
5. **Heartbeat Poll & Device Execution**:
   - Device agent sends periodic heartbeat to `/report`.
   - Worker DO returns the queued command in `{ ok: true, command: nextAction }`.
   - Device executes local root/shell script in `agent.py`.
6. **Device Ack & Final Telegram Notification**:
   - Device agent sends `POST /aot/ack` with `batch_action: "CONTROL_TAILSCALE"`, `status`, `details`, `reason`.
   - `acknowledgeTailscaleControl()` processes the ack and sends a Telegram message directly to the calling user chat.

#### Question 3: What responses are currently formatted and sent back to the user on Telegram?
Two responses occur during the command lifecycle:
1. **Synchronous Queue Response** (from `worker/phanserver.js` line 524):
   ```html
   🌐 <b>ĐÃ XẾP LỆNH [BẬT|TẮT|KIỂM TRA TRẠNG THÁI] TAILSCALE</b>
   Thiết bị: <code>${ids.join(", ")}</code>
   Chế độ: <b>${mode.toUpperCase()}</b>
   Thiết bị sẽ tự động thực thi và gửi thông báo kết quả ở heartbeat kế tiếp.
   ```
2. **Asynchronous Execution Response** (from `worker/fleet_state.js` line 983):
   - When `status === "OPENED"` or `"SUCCESS"`:
     ```html
     🌐 <b>ĐÃ [BẬT|TẮT|KIỂM TRA TRẠNG THÁI] TAILSCALE THÀNH CÔNG!</b>
     📱 Thiết bị: <code>${deviceId}</code>
     ⚙️ Chế độ: <b>${mode.toUpperCase()}</b>
     📋 Trạng thái: <code>${details}</code>
     🔒 Mạng nội bộ Tailscale đã sẵn sàng.
     ```
   - When `status === "FAILED"`:
     ```html
     ❌ <b>[BẬT|TẮT|KIỂM TRA TRẠNG THÁI] TAILSCALE THẤT BẠI</b>
     📱 Thiết bị: <code>${deviceId}</code>
     ⚠️ Lý do: ${escapeHtml(body.reason || "Lỗi thiết bị")}
     ```

**Defects in Current Formatting**:
1. Does NOT show `🌐 ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.x.y.z` as required by R3.
2. In false-success scenarios where `details === "TRIGGERED"`, it still prints `ĐÃ BẬT TAILSCALE THÀNH CÔNG!` and `🔒 Mạng nội bộ Tailscale đã sẵn sàng.` despite having no IP.
3. For `/vpn <device> status`, it does NOT cleanly distinguish `CONNECTED (IP)` vs `DISCONNECTED`. It outputs generic success text with `🔒 Mạng nội bộ Tailscale đã sẵn sàng.` even if the device was stopped or disconnected.
4. For `/vpn <device> off`, it states `🔒 Mạng nội bộ Tailscale đã sẵn sàng.` when Tailscale was intentionally turned off.

#### Question 4: How should the new response formats be integrated?
In `worker/fleet_state.js` within `acknowledgeTailscaleControl(record, body, deviceId, actionId)`:

1. **Extract IP & Validate Real Status**:
   Extract Tailscale IP via regex:
   ```javascript
   const ipMatch = String(body.details || "").match(/100\.\d{1,3}\.\d{1,3}\.\d{1,3}/);
   const tailscaleIp = ipMatch ? ipMatch[0] : null;
   ```
2. **Mode `on` Formatting (Strict Enforcement)**:
   - Success condition: `(status === "OPENED" || status === "SUCCESS") && Boolean(tailscaleIp)`.
   - **Success Template**:
     ```javascript
     const msg = `🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: ${tailscaleIp}</b>\n` +
                 `📱 Thiết bị: <code>${deviceId}</code>\n` +
                 `⚙️ Chế độ: <b>ON</b>\n` +
                 `🔒 Mạng nội bộ Tailscale đã sẵn sàng.`;
     ```
   - **Failure Template** (if status is FAILED or no 100.x.y.z IP acquired):
     ```javascript
     let failReason = body.reason;
     if (!failReason) {
       if (body.details === "TRIGGERED" || !tailscaleIp) {
         failReason = "Timeout 12s không nhận được IP Tailscale (100.x.y.z)";
       } else {
         failReason = body.details || "Không thể kết nối Tailscale";
       }
     }
     const msg = `❌ <b>BẬT TAILSCALE THẤT BẠI: ${escapeHtml(failReason)}</b>\n` +
                 `📱 Thiết bị: <code>${deviceId}</code>\n` +
                 `⚠️ Lý do: ${escapeHtml(failReason)}`;
     ```
3. **Mode `status` Formatting**:
   - Check if IP exists or details indicates `CONNECTED`:
     ```javascript
     const isConnected = (status === "OPENED" || status === "SUCCESS") && (Boolean(tailscaleIp) || String(body.details || "").includes("CONNECTED"));
     ```
   - **Connected Template**:
     ```javascript
     const ipDisplay = tailscaleIp || escapeHtml(body.details).replace(/^CONNECTED:\s*/i, "");
     const msg = `🌐 <b>TRẠNG THÁI TAILSCALE: CONNECTED (${ipDisplay})</b>\n` +
                 `📱 Thiết bị: <code>${deviceId}</code>\n` +
                 `📶 Trạng thái: <b>CONNECTED (${ipDisplay})</b>\n` +
                 `🔒 Mạng nội bộ Tailscale đang hoạt động.`;
     ```
   - **Disconnected Template**:
     ```javascript
     const rawDetail = body.details || body.reason || "Chưa kết nối";
     const msg = `⚠️ <b>TRẠNG THÁI TAILSCALE: DISCONNECTED</b>\n` +
                 `📱 Thiết bị: <code>${deviceId}</code>\n` +
                 `📶 Trạng thái: <b>DISCONNECTED</b>\n` +
                 `📋 Chi tiết: <code>${escapeHtml(rawDetail)}</code>`;
     ```
4. **Mode `off` Formatting**:
   - **Success Template**:
     ```javascript
     const msg = `🌐 <b>ĐÃ TẮT TAILSCALE THÀNH CÔNG!</b>\n` +
                 `📱 Thiết bị: <code>${deviceId}</code>\n` +
                 `⚙️ Chế độ: <b>OFF</b>\n` +
                 `📶 Trạng thái: <b>DISCONNECTED</b>`;
     ```
   - **Failure Template**:
     ```javascript
     const msg = `❌ <b>TẮT TAILSCALE THẤT BẠI: ${escapeHtml(body.reason || "Lỗi thiết bị")}</b>\n` +
                 `📱 Thiết bị: <code>${deviceId}</code>`;
     ```

#### Question 5: What files and lines need to be updated for R3?

| File Path | Line Range | Purpose of Modification |
|---|---|---|
| `worker/fleet_state.js` | Lines 960–996 | In `acknowledgeTailscaleControl`: extract Tailscale IP `100.x.y.z`, guard against fake success without IP, format Telegram messages according to R3 for `on`, `off`, and `status`. |
| `worker/phanserver.js` | Lines 489–533 | In `handleUpdate`: verify syntax support for `/vpn` and `/tailscale`, optionally support flexible arg order (`/vpn status m77`), update syntax error message. |
| `worker/phanserver.js` | Line 556 | In `/help`: explicitly document `/vpn` alias alongside `/tailscale`. |
| `tests/test_fleet_state_2pc.mjs` | Lines 292–316 | Add assertions verifying that `notifiedTelegram.text` contains `🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.80.175.55</b>` on success, `❌ <b>BẬT TAILSCALE THẤT BẠI: ...</b>` on failure, and `CONNECTED (IP)` vs `DISCONNECTED` on status check. |
| `tests/test_telegram_phanserver.mjs` | Lines 283–310 | Ensure command invocation assertions continue to pass and test both `/vpn` and `/tailscale` aliases. |

*(Note: Companion changes in `agent/agent.py` for R1 and R2 are handled by the Device Agent explorer, including multi-user `--user 0`, orientation-aware tap coordinates, 12s timeout loop, checking 100.x.y.z regex, removing `echo TRIGGERED`, and returning `status = "FAILED"` when no IP is found).*

---

## 3. Caveats

1. **Telegram Rate Limits**: Rapidly issuing `/vpn all on` across a large fleet sends one Telegram message per device acknowledgement. The Durable Object sends messages sequentially upon receiving heartbeats, which is safe from burst rate limits since heartbeats arrive staggered (30s intervals).
2. **HTML Parse Mode**: All dynamic fields interpolated into HTML formatted messages (`deviceId`, `body.reason`, `body.details`) must pass through `escapeHtml()` to avoid Telegram API 400 `Bad Request: can't parse entities` errors if reasons contain `<` or `&`.
3. **Dual Alias Compatibility**: The regex `/^\/(?:tailscale|vpn)(?:\s|$)/` handles both `/vpn` and `/tailscale` interchangeably, which is tested in `test_telegram_phanserver.mjs`. Any changes must ensure backward compatibility for both command names.
4. **Unit Test Only Constraint (R4)**: As mandated by R4, all testing must be performed via mock tests in `tests/`. No real UgPhone devices should be contacted.

---

## 4. Conclusion

The current codebase implements the basic pipeline for `/vpn` and `/tailscale` commands across `worker/phanserver.js` (Telegram command intake), `worker/fleet_state.js` (Durable Object queuing and ack notification), and `agent/agent.py` (device execution).

However, the current Telegram message formatting suffers from three critical flaws:
1. **Fake Success Propagation**: When the device fails to acquire a Tailscale IP, `agent.py` emits `"TRIGGERED"` with exit code 0. `fleet_state.js` interprets this as success and messages Telegram that Tailscale is ready.
2. **Format Discrepancy**: The success message does not include the standard header `🌐 ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.x.y.z`.
3. **Ambiguous Status Reporting**: Checking status reports `ĐÃ KIỂM TRA TRẠNG THÁI TAILSCALE THÀNH CÔNG!` and claims the internal network is ready even when disconnected.

The required changes for R3 are localized and clean:
- Refactor `acknowledgeTailscaleControl` in `worker/fleet_state.js` (lines 960–996) with IP regex extraction, strict real-status gating, and dedicated templates for `on`, `off`, and `status`.
- Validate command routing in `worker/phanserver.js` (lines 489–533).
- Enhance test coverage in `tests/test_fleet_state_2pc.mjs` (lines 292–316) to assert on `notifiedTelegram.text` formats.

---

## 5. Verification Method

### 5.1 Independent Verification Commands
To independently verify the existing behavior and future fixes:

1. **Run All Project Tests**:
   ```bash
   bash tests/run_all_tests.sh
   ```
   *Expected outcome*: All 7 test suites pass 100%.

2. **Run Fleet State 2PC & Notification Test**:
   ```bash
   node tests/test_fleet_state_2pc.mjs
   ```
   *Expected outcome*: `TEST_FLEET_STATE_2PC_EQUIVALENCE=OK`.

3. **Run Telegram Bot Parsing Test**:
   ```bash
   node tests/test_telegram_phanserver.mjs
   ```
   *Expected outcome*: `TEST_TELEGRAM_PHANSERVER_EQUIVALENCE=OK`.

4. **Run Device Agent Unit Tests**:
   ```bash
   python3 -m unittest agent/tests/test_agent.py
   ```
   *Expected outcome*: All 20 tests pass.

### 5.2 Files to Inspect
- `/root/phanserver-delta/worker/fleet_state.js` (lines 960–996)
- `/root/phanserver-delta/worker/phanserver.js` (lines 489–533)
- `/root/phanserver-delta/tests/test_fleet_state_2pc.mjs` (lines 292–316)

### 5.3 Invalidation Conditions
- A test where `details: "TRIGGERED"` or missing IP produces a Telegram message containing `"THÀNH CÔNG"`.
- A test where `details: "CONNECTED: 100.80.175.55"` fails to include `IP: 100.80.175.55` in the headline.
- A status check on a disconnected device that outputs `🔒 Mạng nội bộ Tailscale đã sẵn sàng.`

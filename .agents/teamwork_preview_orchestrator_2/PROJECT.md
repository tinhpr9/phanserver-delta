# Project: Tailscale VPN Fix for UgPhone (m77) & Telegram Real IP Reporting

## Architecture
- **Device Agent (`agent/agent.py`)**: Executes in Android environment (Termux/root). Handles `CONTROL_TAILSCALE` batch actions. Manages app launch with `--user 0`, orientation detection via `dumpsys input` / `dumpsys window`, adaptive coordinate tapping, 12s polling of `tun0` & `100.x.y.z`, UI minimization (`BACK` + `HOME`), and strict ACK reporting (`OPENED` with `CONNECTED: 100.x.y.z` or `FAILED` with explicit reason).
- **Durable Object / Fleet State Hub (`worker/fleet_state.js`)**: Receives `CONTROL_TAILSCALE` commands from Telegram / API, queues actions for devices, delivers actions during device heartbeat `/report`, receives execution ACK at `/aot/ack`, and sends formatted status notifications to Telegram.
- **Telegram Bot Intake (`worker/phanserver.js`)**: Parses `/tailscale` and `/vpn` commands (`[on|off|status]`), validates parameters, resolves target devices, queues command into FleetState DO, and replies with immediate queue confirmation.
- **Automated Mock Test Suite (`tests/test_device_agent.py`, `tests/test_fleet_state_2pc.mjs`, `tests/run_all_tests.sh`)**: Hermetic mock unit & integration tests covering all execution scenarios with 0 real device interaction (strict R4 compliance).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Eliminate Fake Success | Replace `echo TRIGGERED` with exit code 1; fail if no `100.x.y.z` or `tun0` after 12s; return `status: "FAILED"`, `executed: False` | M1 | ORIGINAL_REQUEST R1 |
| F2 | UgPhone Multi-User Flag | Add `--user 0` to `am start -n com.tailscale.ipn/.MainActivity` and `am broadcast` commands | M1 | ORIGINAL_REQUEST R2 |
| F3 | Adaptive Screen Orientation & Coordinates | Detect rotation (landscape 90°/270° vs portrait 0°/180°); compute coordinates for Connect button (center) and Toggle switch (top-right) | M1 | ORIGINAL_REQUEST R2 |
| F4 | UI Dismissal | Dispatch `KEYCODE_BACK` followed by `KEYCODE_HOME` after successful connection to ensure UI is hidden | M1 | ORIGINAL_REQUEST R2 |
| F5 | Telegram & Worker Message Formatting | Send `🌐 ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.x.y.z` on success, `❌ BẬT TAILSCALE THẤT BẠI: <Lý do>` on failure, and explicit `CONNECTED (IP)` vs `DISCONNECTED` on status check | M2 | ORIGINAL_REQUEST R3 |
| F6 | Automated Mock Test Suite | Implement `tests/test_device_agent.py` and update `tests/test_fleet_state_2pc.mjs` with 100% pass on `bash tests/run_all_tests.sh` | M3 | ORIGINAL_REQUEST R4 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Tailscale Device Agent Enhancement | Fix `agent/agent.py`: `--user 0`, orientation detection, adaptive coordinates, 12s polling loop, CGNAT IP regex check, UI dismissal, eliminating `TRIGGERED` -> return `FAILED` on timeout | none | DONE |
| M2 | Telegram & Worker Notification Enhancement | Fix `worker/fleet_state.js`: parse Tailscale IP, gate success on genuine IP, format success/failure/status messages per R3; ensure `worker/phanserver.js` compatibility | M1 | DONE |
| M3 | Comprehensive Mock Test Suite & Verification | Implement `tests/test_device_agent.py` covering connect (portrait/landscape), timeout FAILED, disconnect, status, idempotency; update `tests/test_fleet_state_2pc.mjs`; verify 100% pass on `run_all_tests.sh` | M1, M2 | DONE |

## Interface Contracts
### `agent/agent.py` -> `worker/fleet_state.js` (`POST /aot/ack`)
- Success payload:
  `{"status": "OPENED", "executed": True, "details": "CONNECTED: 100.x.y.z", "reason": None}`
- Timeout / Failure payload:
  `{"status": "FAILED", "executed": False, "details": None, "reason": "vpn_timeout_no_ip: Không nhận được IP Tailscale (100.x.y.z) sau 12s"}`
- Disconnect payload:
  `{"status": "OPENED", "executed": True, "details": "DISCONNECTED", "reason": None}`
- Status payload:
  `{"status": "OPENED", "executed": True, "details": "CONNECTED: 100.x.y.z" | "DISCONNECTED", "reason": None}`

### `worker/fleet_state.js` -> Telegram API (`sendMessage`)
- Success message:
  `🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.x.y.z</b>\n📱 Thiết bị: <code>{deviceId}</code>\n⚙️ Chế độ: <b>ON</b>\n🔒 Mạng nội bộ Tailscale đã sẵn sàng.`
- Failure message:
  `❌ <b>BẬT TAILSCALE THẤT BẠI: {reason}</b>\n📱 Thiết bị: <code>{deviceId}</code>\n⚠️ Lý do: {reason}`
- Status message:
  `🌐 <b>TRẠNG THÁI TAILSCALE: CONNECTED (100.x.y.z)</b>...` or `⚠️ <b>TRẠNG THÁI TAILSCALE: DISCONNECTED</b>...`

## Code Layout
- `agent/agent.py`: Device agent execution logic
- `agent/tests/test_agent.py`: Agent unit tests
- `worker/fleet_state.js`: FleetState Durable Object and notification logic
- `worker/phanserver.js`: Telegram bot intake and command parsing
- `tests/test_device_agent.py`: Standalone device agent mock unit tests
- `tests/test_fleet_state_2pc.mjs`: Fleet state integration tests
- `tests/run_all_tests.sh`: Master test runner

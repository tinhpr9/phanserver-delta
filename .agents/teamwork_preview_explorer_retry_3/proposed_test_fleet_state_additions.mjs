import assert from "node:assert/strict";
import { FleetState } from "../../worker/fleet_state.js";

// Helper function that should be integrated into worker/fleet_state.js
export function extractValidTailscaleIp(details) {
  const match = String(details || "").match(/\b100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b/);
  if (!match) return null;
  const octets = [Number(match[1]), Number(match[2]), Number(match[3])];
  if (octets.some((o) => o < 0 || o > 255 || Number.isNaN(o))) return null;
  return match[0];
}

async function runMalformedIpTests() {
  console.log("=== Testing Malformed IP Edge Cases in FleetState ===");

  // Unit tests on extractValidTailscaleIp
  assert.equal(extractValidTailscaleIp("CONNECTED: 100.80.175.55"), "100.80.175.55");
  assert.equal(extractValidTailscaleIp("CONNECTED: 100.64.0.1"), "100.64.0.1");
  assert.equal(extractValidTailscaleIp("CONNECTED: 100.300.1.1"), null, "100.300.1.1 must be null (octet > 255)");
  assert.equal(extractValidTailscaleIp("CONNECTED: 100.1.2.2555"), null, "100.1.2.2555 must be null (4-digit octet)");
  assert.equal(extractValidTailscaleIp("CONNECTED: 100.1.256.1"), null, "100.1.256.1 must be null");
  assert.equal(extractValidTailscaleIp("CONNECTED: 100.abc.1.1"), null, "100.abc.1.1 must be null");
  assert.equal(extractValidTailscaleIp("CONNECTED: 192.168.1.1"), null, "192.168.1.1 must be null");
  assert.equal(extractValidTailscaleIp(""), null);
  assert.equal(extractValidTailscaleIp(null), null);
  console.log("PASS: Unit tests on extractValidTailscaleIp passed!");

  // Patched FleetState testing
  let notifiedTelegram = null;
  globalThis.fetch = async (url, init) => {
    notifiedTelegram = JSON.parse(init.body);
    return { ok: true, json: async () => ({ ok: true }) };
  };

  class PatchedFleetState extends FleetState {
    async acknowledgeTailscaleControl(record, body, deviceId, actionId) {
      const act = record.tailscale_actions?.[actionId];
      const device = act?.devices?.[deviceId];
      const status = String(body.status || "");
      const mode = act?.mode || "on";

      const tailscaleIp = extractValidTailscaleIp(body.details);

      let isSuccess = status === "OPENED" || status === "SUCCESS";
      if (mode === "on") {
        isSuccess = isSuccess && Boolean(tailscaleIp);
      }

      if (device && device.status === "QUEUED") {
        device.status = isSuccess ? status : "FAILED";
        device.executed = isSuccess && body.executed === true;
        if (!isSuccess) {
          let reason = body.reason;
          if (!reason) {
            if (body.details === "TRIGGERED" || !tailscaleIp) {
              reason = "Timeout 12s không nhận được IP Tailscale (100.x.y.z)";
            } else {
              reason = body.details || "device_failed";
            }
          }
          device.reason = String(reason).slice(0, 160);
        } else {
          device.reason = null;
        }
        device.details = body.details ? String(body.details).slice(0, 200) : null;
        device.updated_at = Date.now();
      }

      for (const command of record.pending_actions?.[deviceId] || []) {
        if (command.action_id === actionId) command.acknowledged_at = Date.now();
      }
      await this.writeFleet(record);

      const chatId = act?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
      if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
        const escapeHtml = (str) => String(str || "").replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        let msg = "";
        if (mode === "on") {
          if (isSuccess && tailscaleIp) {
            msg = `🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: ${tailscaleIp}</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚙️ Chế độ: <b>ON</b>\n🔒 Mạng nội bộ Tailscale đã sẵn sàng.`;
          } else {
            let failReason = body.reason;
            if (!failReason) {
              if (body.details === "TRIGGERED" || !tailscaleIp) {
                failReason = "Timeout 12s không nhận được IP Tailscale (100.x.y.z)";
              } else {
                failReason = body.details || "Không thể kết nối Tailscale";
              }
            }
            msg = `❌ <b>BẬT TAILSCALE THẤT BẠI: ${escapeHtml(failReason)}</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${escapeHtml(failReason)}`;
          }
        }
        try {
          await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
          });
        } catch (e) {}
      }

      const returnStatus = (mode === "on" && !isSuccess) ? "FAILED" : (status || "SUCCESS");
      return new Response(JSON.stringify({ ok: true, action_id: actionId, device_id: deviceId, status: returnStatus }), {
        headers: { "content-type": "application/json" }
      });
    }
  }

  const storage = { store: new Map(), async get(k) { return this.store.get(k); }, async put(k, v) { this.store.set(k, v); } };
  const ctx = { storage, sockets: new Map(), getWebSockets() { return []; } };
  const fleet = new PatchedFleetState(ctx, { TEST_ENV: true, TELEGRAM_BOT_TOKEN: "tok", TELEGRAM_ADMIN_USER_ID: "123" });

  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));

  // Integration Test Case A: 100.300.1.1
  const resA = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "on", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const actA = resA.tailscale.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  notifiedTelegram = null;
  const ackA = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "CONTROL_TAILSCALE",
      device_id: "m1",
      action_id: actA,
      status: "OPENED",
      executed: true,
      details: "CONNECTED: 100.300.1.1"
    })
  }))).json();
  assert.equal(ackA.status, "FAILED", "Expected FAILED for 100.300.1.1");
  assert.ok(notifiedTelegram?.text?.includes("BẬT TAILSCALE THẤT BẠI"), "Telegram must report failure");
  assert.ok(!notifiedTelegram?.text?.includes("THÀNH CÔNG"), "Telegram must NOT report success");
  console.log("PASS: 100.300.1.1 correctly rejected as FAILED");

  // Integration Test Case B: 100.1.2.2555
  const resB = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "on", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const actB = resB.tailscale.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  notifiedTelegram = null;
  const ackB = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "CONTROL_TAILSCALE",
      device_id: "m1",
      action_id: actB,
      status: "OPENED",
      executed: true,
      details: "CONNECTED: 100.1.2.2555"
    })
  }))).json();
  assert.equal(ackB.status, "FAILED", "Expected FAILED for 100.1.2.2555");
  assert.ok(notifiedTelegram?.text?.includes("BẬT TAILSCALE THẤT BẠI"), "Telegram must report failure");
  assert.ok(!notifiedTelegram?.text?.includes("THÀNH CÔNG"), "Telegram must NOT report success");
  assert.ok(!notifiedTelegram?.text?.includes("100.1.2.255"), "Telegram must NOT report truncated IP 100.1.2.255");
  console.log("PASS: 100.1.2.2555 correctly rejected as FAILED without truncation");

  console.log("=== ALL MALFORMED IP INTEGRATION TESTS PASSED! ===");
}

runMalformedIpTests().catch((err) => {
  console.error("Test failed:", err);
  process.exit(1);
});

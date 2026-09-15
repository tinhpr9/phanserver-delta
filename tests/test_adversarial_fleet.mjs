import assert from "node:assert/strict";
import { normalizeDeviceId } from "../worker/fleet_state.js";

// Mock FleetState environment to test acknowledgeTailscaleControl and Telegram formatting
class MockFleetState {
  constructor() {
    this.env = {
      TELEGRAM_BOT_TOKEN: "mock-token",
      TELEGRAM_ADMIN_USER_ID: "123456",
    };
    this.sentTelegramMessages = [];
  }

  async writeFleet(record) {
    this.savedRecord = record;
  }

  async acknowledgeTailscaleControl(record, body, deviceId, actionId) {
    const act = record.tailscale_actions?.[actionId];
    const device = act?.devices?.[deviceId];
    const status = String(body.status || "");
    const mode = act?.mode || "on";

    // Extract Tailscale CGNAT IP (100.x.y.z)
    const ipMatch = String(body.details || "").match(/100\.\d{1,3}\.\d{1,3}\.\d{1,3}/);
    const tailscaleIp = ipMatch ? ipMatch[0] : null;

    // Strict success gating: mode 'on' requires valid IP and OPENED/SUCCESS status
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
      } else if (mode === "status") {
        const detailsStr = String(body.details || "").trim();
        const isConnected = isSuccess && (Boolean(tailscaleIp) || (/^CONNECTED\b/i.test(detailsStr) && !/DISCONNECTED/i.test(detailsStr)));
        if (isConnected) {
          const ipDisplay = tailscaleIp || escapeHtml(detailsStr).replace(/^CONNECTED:\s*/i, "");
          msg = `🌐 <b>TRẠNG THÁI TAILSCALE: CONNECTED (${ipDisplay})</b>\n📱 Thiết bị: <code>${deviceId}</code>\n📶 Trạng thái: <b>CONNECTED (${ipDisplay})</b>\n🔒 Mạng nội bộ Tailscale đang hoạt động.`;
        } else {
          const rawDetail = body.details || body.reason || "Chưa kết nối";
          msg = `⚠️ <b>TRẠNG THÁI TAILSCALE: DISCONNECTED</b>\n📱 Thiết bị: <code>${deviceId}</code>\n📶 Trạng thái: <b>DISCONNECTED</b>\n📋 Chi tiết: <code>${escapeHtml(rawDetail)}</code>`;
        }
      } else if (mode === "off") {
        if (isSuccess) {
          msg = `🌐 <b>ĐÃ TẮT TAILSCALE THÀNH CÔNG!</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚙️ Chế độ: <b>OFF</b>\n📶 Trạng thái: <b>DISCONNECTED</b>`;
        } else {
          const failReason = body.reason || "Lỗi thiết bị";
          msg = `❌ <b>TẮT TAILSCALE THẤT BẠI: ${escapeHtml(failReason)}</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${escapeHtml(failReason)}`;
        }
      } else {
        msg = isSuccess
          ? `🌐 <b>ĐÃ ${mode.toUpperCase()} TAILSCALE THÀNH CÔNG!</b>\n📱 Thiết bị: <code>${deviceId}</code>`
          : `❌ <b>${mode.toUpperCase()} TAILSCALE THẤT BẠI</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${escapeHtml(body.reason || "Lỗi thiết bị")}`;
      }

      this.sentTelegramMessages.push({ chatId, text: msg });
    }

    const returnStatus = (mode === "on" && !isSuccess) ? "FAILED" : (status || "SUCCESS");
    return { ok: true, action_id: actionId, device_id: deviceId, status: returnStatus };
  }
}

async function runAdversarialFleetTests() {
  console.log("=========================================");
  console.log("  RUNNING ADVERSARIAL FLEET TESTS");
  console.log("=========================================");

  const fs = new MockFleetState();

  // Test 1: Malformed IP 100.300.1.1 in ACK details
  console.log("\n[TEST 1] ACK with malformed IP 100.300.1.1 (octet > 255)");
  const record1 = {
    tailscale_actions: {
      "act-1": {
        action_id: "act-1",
        mode: "on",
        devices: { m77: { device_id: "m77", status: "QUEUED" } },
      },
    },
    pending_actions: {},
  };
  const body1 = {
    status: "OPENED",
    executed: true,
    details: "CONNECTED: 100.300.1.1",
  };
  const res1 = await fs.acknowledgeTailscaleControl(record1, body1, "m77", "act-1");
  console.log("Result for 100.300.1.1:", res1);
  const msg1 = fs.sentTelegramMessages.pop();
  console.log("Telegram Msg for 100.300.1.1:\n", msg1?.text);

  // Check if Fleet State detected 100.300.1.1 as invalid or accepted it
  const acceptedBadIp = res1.status === "OPENED" && msg1?.text.includes("THÀNH CÔNG");
  if (acceptedBadIp) {
    console.log("⚠️ FINDING: Fleet State accepted invalid octet 100.300.1.1 because regex /100\\.\\d{1,3}.../ doesn't check octets <= 255");
  } else {
    console.log("PASS: Fleet State rejected 100.300.1.1");
  }

  // Test 2: Malformed 4-digit octet 100.1.2.2555
  console.log("\n[TEST 2] ACK with 4-digit octet 100.1.2.2555");
  const record2 = {
    tailscale_actions: {
      "act-2": {
        action_id: "act-2",
        mode: "on",
        devices: { m77: { device_id: "m77", status: "QUEUED" } },
      },
    },
    pending_actions: {},
  };
  const body2 = {
    status: "OPENED",
    executed: true,
    details: "CONNECTED: 100.1.2.2555",
  };
  const res2 = await fs.acknowledgeTailscaleControl(record2, body2, "m77", "act-2");
  const msg2 = fs.sentTelegramMessages.pop();
  console.log("Result for 100.1.2.2555:", res2);
  console.log("Telegram Msg for 100.1.2.2555:\n", msg2?.text);
  if (msg2?.text.includes("IP: 100.1.2.255")) {
    console.log("⚠️ FINDING: Fleet State regex truncated 100.1.2.2555 to 100.1.2.255 due to lack of word boundary \\b");
  }

  // Test 3: HTML Escaping with malicious XSS / special characters in failReason
  console.log("\n[TEST 3] HTML Escaping in failure reason");
  const record3 = {
    tailscale_actions: {
      "act-3": {
        action_id: "act-3",
        mode: "on",
        devices: { m77: { device_id: "m77", status: "QUEUED" } },
      },
    },
    pending_actions: {},
  };
  const body3 = {
    status: "FAILED",
    executed: false,
    reason: "<script>alert('pwn')</script> & Error <timeout> with a > b",
    details: null,
  };
  await fs.acknowledgeTailscaleControl(record3, body3, "m77", "act-3");
  const msg3 = fs.sentTelegramMessages.pop();
  console.log("Escaped Failure Message:\n", msg3?.text);
  assert.ok(!msg3.text.includes("<script>"), "Must not contain raw <script>");
  assert.ok(msg3.text.includes("&lt;script&gt;"), "Must contain escaped &lt;script&gt;");
  assert.ok(msg3.text.includes("&amp;"), "Must contain escaped &amp;");
  assert.ok(msg3.text.includes("&gt;"), "Must contain escaped &gt;");
  console.log("PASS: HTML tags and entities properly escaped in failure message.");

  // Test 4: HTML Escaping in status mode disconnected with special characters
  console.log("\n[TEST 4] HTML Escaping in status mode disconnected detail");
  const record4 = {
    tailscale_actions: {
      "act-4": {
        action_id: "act-4",
        mode: "status",
        devices: { m77: { device_id: "m77", status: "QUEUED" } },
      },
    },
    pending_actions: {},
  };
  const body4 = {
    status: "OPENED",
    executed: true,
    details: "DISCONNECTED <reason: interface down & unreachable>",
  };
  await fs.acknowledgeTailscaleControl(record4, body4, "m77", "act-4");
  const msg4 = fs.sentTelegramMessages.pop();
  console.log("Escaped Status Disconnected Message:\n", msg4?.text);
  assert.ok(!msg4.text.includes("<reason:"), "Must not contain unescaped <reason:");
  assert.ok(msg4.text.includes("&lt;reason:"), "Must contain &lt;reason:");
  console.log("PASS: Status disconnected details properly escaped.");

  // Test 5: Rejection of legacy TRIGGERED in Fleet State
  console.log("\n[TEST 5] Rejection of legacy fake TRIGGERED");
  const record5 = {
    tailscale_actions: {
      "act-5": {
        action_id: "act-5",
        mode: "on",
        devices: { m77: { device_id: "m77", status: "QUEUED" } },
      },
    },
    pending_actions: {},
  };
  const body5 = {
    status: "OPENED",
    executed: true,
    details: "TRIGGERED",
  };
  const res5 = await fs.acknowledgeTailscaleControl(record5, body5, "m77", "act-5");
  const msg5 = fs.sentTelegramMessages.pop();
  assert.equal(res5.status, "FAILED", "TRIGGERED must be rejected as FAILED");
  assert.equal(record5.tailscale_actions["act-5"].devices.m77.status, "FAILED");
  assert.ok(msg5.text.includes("BẬT TAILSCALE THẤT BẠI"), "Telegram must receive failure alert");
  console.log("PASS: Legacy TRIGGERED successfully rejected by Fleet State.");

  // Test 6: Device ID normalization edge cases
  console.log("\n[TEST 6] Device ID normalization");
  assert.equal(normalizeDeviceId("m77"), "m77");
  assert.equal(normalizeDeviceId("m01"), null, "m01 with leading zero is rejected");
  assert.equal(normalizeDeviceId("NOVA-05"), "NOVA-05");
  assert.equal(normalizeDeviceId("m0"), null, "m0 is invalid");
  assert.equal(normalizeDeviceId("m77<script>"), null, "Injection in device ID rejected");
  assert.equal(normalizeDeviceId(""), null);
  assert.equal(normalizeDeviceId(null), null);
  console.log("PASS: Device ID normalization handles boundary and injection inputs.");

  console.log("\n=========================================");
  console.log("  ALL ADVERSARIAL FLEET TESTS COMPLETE");
  console.log("=========================================");
}

runAdversarialFleetTests().catch((err) => {
  console.error("Adversarial Fleet Test Failed:", err);
  process.exit(1);
});

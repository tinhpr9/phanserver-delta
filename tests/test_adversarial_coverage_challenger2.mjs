import test from "node:test";
import assert from "node:assert/strict";
import { FleetState, extractValidTailscaleIp, normalizeDeviceId } from "../worker/fleet_state.js";

class MockStorage {
  constructor() {
    this.store = new Map();
  }
  async get(key) {
    const val = this.store.get(key);
    return val !== undefined ? JSON.parse(JSON.stringify(val)) : undefined;
  }
  async put(key, value) {
    this.store.set(key, JSON.parse(JSON.stringify(value)));
  }
  async delete(key) {
    this.store.delete(key);
  }
}

function createMockFleetState(telegramCapture) {
  const env = {
    TEST_ENV: true,
    FLEET_SHARED_SECRET: "test-secret",
    TELEGRAM_BOT_TOKEN: "mock-token-123",
    TELEGRAM_ADMIN_USER_ID: "12345678"
  };

  const storage = new MockStorage();
  const ctx = {
    storage,
    sockets: new Map(),
    getWebSockets() { return []; }
  };

  return new FleetState(ctx, env);
}

test("Challenger Iter2-2 Adversarial FleetState & Tailscale Test Suite", async (t) => {
  let telegramCalls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    if (typeof url === "string" && url.includes("api.telegram.org")) {
      const body = options.body ? JSON.parse(options.body) : {};
      telegramCalls.push({ url, body });
      return { ok: true, json: async () => ({ ok: true }) };
    }
    return originalFetch(url, options);
  };

  t.after(() => {
    globalThis.fetch = originalFetch;
  });

  // =========================================================================
  // 1. CONCURRENCY: 20 Devices Parallel Queue & Concurrent ACK Dispatch
  // =========================================================================
  await t.test("Concurrency: 20 devices parallel queue and concurrent ACK dispatch", async () => {
    telegramCalls = [];
    const fleet = createMockFleetState();

    const deviceIds = Array.from({ length: 20 }, (_, i) => `m${i + 1}`);

    // Register all 20 devices as online
    for (const devId of deviceIds) {
      await fleet.handleHeartbeat(new Request("https://localhost/report", {
        method: "POST",
        headers: { "x-device-secret": "test-secret", "content-type": "application/json" },
        body: JSON.stringify({
          device_id: devId,
          device_group: "NOVA",
          version: "phanserver-delta-agent-1.0.0",
          capabilities: ["allocate_server_2pc", "update_delta", "control_tailscale"]
        })
      }));
    }

    // Queue Tailscale ON for all 20 devices in a single batch
    const queueRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "on",
        target_device_ids: deviceIds,
        telegram_chat_id: 12345678
      })
    }))).json();

    assert.equal(queueRes.ok, true);
    const actionId = queueRes.tailscale.action_id;
    assert.equal(queueRes.tailscale.devices.length, 20);

    // Concurrently dispatch ACKs for all 20 devices with distinct valid CGNAT IPs
    const ackPromises = deviceIds.map((devId, idx) => {
      const ip = `100.80.${idx + 1}.55`;
      return fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
        method: "POST",
        headers: { "x-device-secret": "test-secret", "content-type": "application/json" },
        body: JSON.stringify({
          protocol: "fleet-batch-v1",
          batch_action: "CONTROL_TAILSCALE",
          device_id: devId,
          action_id: actionId,
          status: "OPENED",
          executed: true,
          details: `CONNECTED: ${ip}`
        })
      })).then((r) => r.json());
    });

    const ackResults = await Promise.all(ackPromises);
    assert.equal(ackResults.length, 20);
    for (const res of ackResults) {
      assert.equal(res.ok, true);
      assert.equal(res.status, "OPENED");
    }

    // Verify all 20 Telegram messages were sent
    assert.equal(telegramCalls.length, 20);
    for (let i = 0; i < 20; i++) {
      const call = telegramCalls[i];
      assert.match(call.body.text, /ĐÃ BẬT TAILSCALE THÀNH CÔNG!/);
      assert.match(call.body.text, /100\.80\.\d+\.55/);
    }
  });

  // =========================================================================
  // 2. IDEMPOTENCY: Duplicate ACK Replay Stress
  // =========================================================================
  await t.test("Idempotency: Replaying identical ACK does not corrupt state or fail", async () => {
    telegramCalls = [];
    const fleet = createMockFleetState();
    const devId = "m77";

    await fleet.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      headers: { "x-device-secret": "test-secret", "content-type": "application/json" },
      body: JSON.stringify({
        device_id: devId,
        device_group: "NOVA",
        capabilities: ["allocate_server_2pc", "update_delta", "control_tailscale"]
      })
    }));

    const queueRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "on",
        target_device_ids: [devId],
        telegram_chat_id: 12345678
      })
    }))).json();

    const actionId = queueRes.tailscale.action_id;

    // Send ACK first time
    const ack1 = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      headers: { "x-device-secret": "test-secret", "content-type": "application/json" },
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: devId,
        action_id: actionId,
        status: "OPENED",
        executed: true,
        details: "CONNECTED: 100.80.175.55"
      })
    }))).json();
    assert.equal(ack1.ok, true);
    assert.equal(ack1.status, "OPENED");

    // Send identical ACK 5 more times
    for (let i = 0; i < 5; i++) {
      const ackN = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
        method: "POST",
        headers: { "x-device-secret": "test-secret", "content-type": "application/json" },
        body: JSON.stringify({
          protocol: "fleet-batch-v1",
          batch_action: "CONTROL_TAILSCALE",
          device_id: devId,
          action_id: actionId,
          status: "OPENED",
          executed: true,
          details: "CONNECTED: 100.80.175.55"
        })
      }))).json();
      assert.equal(ackN.ok, true);
      assert.equal(ackN.status, "OPENED");
    }
  });

  // =========================================================================
  // 3. RAPID MODE SWITCHING & STATUS INQUIRY
  // =========================================================================
  await t.test("Rapid Mode Switching: ON -> STATUS (connected) -> OFF -> STATUS (disconnected)", async () => {
    telegramCalls = [];
    const fleet = createMockFleetState();
    const devId = "m77";

    await fleet.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      headers: { "x-device-secret": "test-secret", "content-type": "application/json" },
      body: JSON.stringify({
        device_id: devId,
        device_group: "NOVA",
        capabilities: ["allocate_server_2pc", "update_delta", "control_tailscale"]
      })
    }));

    // Step A: Turn ON
    const qOn = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "on",
        target_device_ids: [devId],
        telegram_chat_id: 12345678
      })
    }))).json();
    telegramCalls = [];
    await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: devId,
        action_id: qOn.tailscale.action_id,
        status: "OPENED",
        executed: true,
        details: "CONNECTED: 100.80.175.55"
      })
    }));
    assert.equal(telegramCalls.length, 1);
    assert.match(telegramCalls[0].body.text, /ĐÃ BẬT TAILSCALE THÀNH CÔNG!/);
    assert.match(telegramCalls[0].body.text, /100\.80\.175\.55/);

    // Step B: Query STATUS while connected
    const qStatus1 = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "status",
        target_device_ids: [devId],
        telegram_chat_id: 12345678
      })
    }))).json();
    telegramCalls = [];
    await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: devId,
        action_id: qStatus1.tailscale.action_id,
        status: "OPENED",
        executed: true,
        details: "CONNECTED: 100.80.175.55"
      })
    }));
    assert.equal(telegramCalls.length, 1);
    assert.match(telegramCalls[0].body.text, /TRẠNG THÁI TAILSCALE: CONNECTED \(100\.80\.175\.55\)/);

    // Step C: Turn OFF
    const qOff = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "off",
        target_device_ids: [devId],
        telegram_chat_id: 12345678
      })
    }))).json();
    telegramCalls = [];
    await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: devId,
        action_id: qOff.tailscale.action_id,
        status: "OPENED",
        executed: true,
        details: "DISCONNECTED"
      })
    }));
    assert.equal(telegramCalls.length, 1);
    assert.match(telegramCalls[0].body.text, /ĐÃ TẮT TAILSCALE THÀNH CÔNG!/);

    // Step D: Query STATUS while disconnected
    const qStatus2 = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "status",
        target_device_ids: [devId],
        telegram_chat_id: 12345678
      })
    }))).json();
    telegramCalls = [];
    await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: devId,
        action_id: qStatus2.tailscale.action_id,
        status: "OPENED",
        executed: true,
        details: "DISCONNECTED"
      })
    }));
    assert.equal(telegramCalls.length, 1);
    assert.match(telegramCalls[0].body.text, /TRẠNG THÁI TAILSCALE: DISCONNECTED/);
  });

  // =========================================================================
  // 4. DEEP IP REGEX & EXTRACTION FUZZING (extractValidTailscaleIp)
  // =========================================================================
  await t.test("IP Extraction Fuzzing: exhaustive boundary test matrix", async () => {
    const validPairs = [
      ["100.80.175.55", "100.80.175.55"],
      ["CONNECTED: 100.80.175.55", "100.80.175.55"],
      ["IP is 100.64.0.1 on tun0", "100.64.0.1"],
      ["100.0.0.0", "100.0.0.0"],
      ["100.255.255.255", "100.255.255.255"],
      ["[100.115.92.14]", "100.115.92.14"],
      ["(100.115.92.14)", "100.115.92.14"],
    ];
    for (const [input, expected] of validPairs) {
      assert.equal(extractValidTailscaleIp(input), expected, `Failed for input: ${input}`);
    }

    const invalidInputs = [
      "100.300.1.1",            // octet > 255
      "100.1.256.1",
      "100.1.2.256",
      "100.1.2.2555",           // 4-digit octet suffix
      "1100.1.2.3",             // 4-digit prefix
      "100.1.2.3.4",            // 5 octets
      ".100.1.2.3",             // leading dot
      "100.1.2.3:80",           // port
      "100.1.2.3/24",           // CIDR
      "192.168.1.1",            // non-100 prefix
      "10.0.0.1",
      "172.16.0.1",
      "127.0.0.1",
      "TRIGGERED",
      "DISCONNECTED",
      "",
      null,
      undefined
    ];
    for (const input of invalidInputs) {
      assert.equal(extractValidTailscaleIp(input), null, `Expected null for: ${input}`);
    }
  });

  // =========================================================================
  // 5. HTML ESCAPING IN FAILURE REASONS
  // =========================================================================
  await t.test("HTML escaping in error reasons prevents injection into Telegram", async () => {
    telegramCalls = [];
    const fleet = createMockFleetState();
    const devId = "m77";

    await fleet.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      headers: { "x-device-secret": "test-secret", "content-type": "application/json" },
      body: JSON.stringify({
        device_id: devId,
        device_group: "NOVA",
        capabilities: ["allocate_server_2pc", "update_delta", "control_tailscale"]
      })
    }));

    const q = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "on",
        target_device_ids: [devId],
        telegram_chat_id: 12345678
      })
    }))).json();

    await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: devId,
        action_id: q.tailscale.action_id,
        status: "FAILED",
        executed: false,
        reason: "<script>alert('pwn')</script> & error <b>bold</b>"
      })
    }));

    assert.equal(telegramCalls.length, 1);
    const text = telegramCalls[0].body.text;
    assert.match(text, /&lt;script&gt;alert\('pwn'\)&lt;\/script&gt;/);
    assert.match(text, /&amp; error/);
    assert.match(text, /&lt;b&gt;bold&lt;\/b&gt;/);
  });
});

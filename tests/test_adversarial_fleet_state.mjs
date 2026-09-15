import test from "node:test";
import assert from "node:assert/strict";
import { FleetState } from "../worker/fleet_state.js";

class MockStorage {
  constructor() { this.store = new Map(); }
  async get(key) { return this.store.get(key); }
  async put(key, value) { this.store.set(key, JSON.parse(JSON.stringify(value))); }
  async delete(key) { this.store.delete(key); }
}

test("Adversarial FleetState: Tailscale VPN control & Telegram reporting", async (t) => {
  let telegramCalls = [];

  const env = {
    TEST_ENV: true,
    FLEET_SHARED_SECRET: "test-secret",
    TELEGRAM_BOT_TOKEN: "mock-token",
    TELEGRAM_ADMIN_USER_ID: "12345"
  };

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

  const storage = new MockStorage();
  const ctx = {
    storage,
    sockets: new Map(),
    getWebSockets() { return []; }
  };

  const fleet = new FleetState(ctx, env);

  // Initialize fleet with device m77
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    headers: { "x-device-secret": "test-secret", "content-type": "application/json" },
    body: JSON.stringify({
      device_id: "m77",
      device_group: "NOVA",
      version: "phanserver-delta-agent-1.0.0",
      capabilities: ["allocate_server_2pc", "update_delta", "control_tailscale"]
    })
  }));

  // -------------------------------------------------------------------------
  // Test 1: Offline Device Fail-Closed
  // -------------------------------------------------------------------------
  await t.test("offline device is rejected with 400 invalid_batch_target", async () => {
    const res = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "on",
        target_device_ids: ["offline_dev_99"],
        telegram_chat_id: 12345
      })
    }))).json();

    assert.equal(res.ok, false);
    assert.equal(res.error, "invalid_batch_target");
  });

  // -------------------------------------------------------------------------
  // Test 2: Fake success rejection (details: TRIGGERED, LAN IP, empty, etc.)
  // -------------------------------------------------------------------------
  const fakeScenarios = [
    { details: "TRIGGERED", status: "OPENED", label: "legacy TRIGGERED" },
    { details: "CONNECTED: 192.168.1.50", status: "OPENED", label: "LAN 192.168 IP" },
    { details: "CONNECTED: 10.0.0.1", status: "OPENED", label: "LAN 10.x IP" },
    { details: "CONNECTED: 172.16.0.1", status: "OPENED", label: "LAN 172.16 IP" },
    { details: "CONNECTED: ", status: "OPENED", label: "empty IP suffix" },
    { details: "", status: "OPENED", label: "empty details" },
    { details: null, status: "OPENED", label: "null details" },
    { details: "CONNECTED: 100.80.175.55", status: "FAILED", label: "FAILED status despite IP" },
  ];

  for (const sc of fakeScenarios) {
    await t.test(`rejects fake success [${sc.label}]`, async () => {
      telegramCalls = [];
      const queueRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
        method: "POST",
        body: JSON.stringify({
          protocol: "fleet-batch-v1",
          kind: "control_tailscale",
          mode: "on",
          target_device_ids: ["m77"],
          telegram_chat_id: 12345
        })
      }))).json();

      assert.equal(queueRes.ok, true);
      const actionId = queueRes.tailscale.action_id;

      // Deliver via heartbeat
      await fleet.handleHeartbeat(new Request("https://localhost/report", {
        method: "POST",
        headers: { "x-device-secret": "test-secret" },
        body: JSON.stringify({ device_id: "m77" })
      }));

      // Agent returns ACK with fake success or failed status
      const ackRes = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
        method: "POST",
        body: JSON.stringify({
          protocol: "fleet-batch-v1",
          batch_action: "CONTROL_TAILSCALE",
          device_id: "m77",
          action_id: actionId,
          status: sc.status,
          executed: sc.status === "OPENED",
          details: sc.details
        })
      }))).json();

      assert.equal(ackRes.status, "FAILED", `Expected FAILED for ${sc.label} but got ${ackRes.status}`);

      // Verify Telegram notification sent was a FAILURE notification
      assert.equal(telegramCalls.length, 1);
      const msg = telegramCalls[0].body.text;
      assert.ok(msg.includes("BẬT TAILSCALE THẤT BẠI"), `Expected failure msg for ${sc.label}, got: ${msg}`);
      assert.ok(!msg.includes("THÀNH CÔNG"), `Failure msg contained THÀNH CÔNG for ${sc.label}: ${msg}`);
    });
  }

  // -------------------------------------------------------------------------
  // Test 3: Genuine connection success with real Tailscale IP (100.x.y.z)
  // -------------------------------------------------------------------------
  await t.test("genuine connection success formats correctly with IP", async () => {
    telegramCalls = [];
    const queueRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "on",
        target_device_ids: ["m77"],
        telegram_chat_id: 12345
      })
    }))).json();

    const actionId = queueRes.tailscale.action_id;

    // Heartbeat
    await fleet.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      headers: { "x-device-secret": "test-secret" },
      body: JSON.stringify({ device_id: "m77" })
    }));

    // ACK with genuine IP
    const ackRes = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: "m77",
        action_id: actionId,
        status: "OPENED",
        executed: true,
        details: "CONNECTED: 100.80.175.55"
      })
    }))).json();

    assert.equal(ackRes.ok, true);
    assert.equal(ackRes.status, "OPENED");

    assert.equal(telegramCalls.length, 1);
    const msg = telegramCalls[0].body.text;
    assert.ok(msg.includes("ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.80.175.55"));
    assert.ok(msg.includes("Mạng nội bộ Tailscale đã sẵn sàng"));
  });

  // -------------------------------------------------------------------------
  // Test 4: HTML escaping in deviceId and reason
  // -------------------------------------------------------------------------
  await t.test("escapes HTML in error reasons", async () => {
    telegramCalls = [];
    const queueRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "on",
        target_device_ids: ["m77"],
        telegram_chat_id: 12345
      })
    }))).json();

    const actionId = queueRes.tailscale.action_id;

    await fleet.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      headers: { "x-device-secret": "test-secret" },
      body: JSON.stringify({ device_id: "m77" })
    }));

    await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: "m77",
        action_id: actionId,
        status: "FAILED",
        executed: false,
        reason: "error <with> & dangerous \"quotes\""
      })
    }));

    assert.equal(telegramCalls.length, 1);
    const msg = telegramCalls[0].body.text;
    assert.ok(msg.includes("&lt;with&gt;"));
    assert.ok(msg.includes("&amp;"));
    assert.ok(!msg.includes("<with>"));
  });

  // -------------------------------------------------------------------------
  // Test 5: Replay / Duplicate ACK handling
  // -------------------------------------------------------------------------
  await t.test("duplicate ACK behavior", async () => {
    telegramCalls = [];
    const queueRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "on",
        target_device_ids: ["m77"],
        telegram_chat_id: 12345
      })
    }))).json();

    const actionId = queueRes.tailscale.action_id;

    await fleet.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      headers: { "x-device-secret": "test-secret" },
      body: JSON.stringify({ device_id: "m77" })
    }));

    // First ACK
    const ack1 = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: "m77",
        action_id: actionId,
        status: "OPENED",
        executed: true,
        details: "CONNECTED: 100.80.175.55"
      })
    }))).json();

    assert.equal(ack1.status, "OPENED");
    const countAfterFirstAck = telegramCalls.length;
    assert.equal(countAfterFirstAck, 1);

    // Second (duplicate) ACK with same action_id
    const ack2 = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: "m77",
        action_id: actionId,
        status: "OPENED",
        executed: true,
        details: "CONNECTED: 100.80.175.55"
      })
    }))).json();

    assert.equal(ack2.status, "OPENED");
  });

  // -------------------------------------------------------------------------
  // Test 6: Multi-Device Batch Dispatch
  // -------------------------------------------------------------------------
  await t.test("multi-device batch: independent execution & notifications", async () => {
    // Register m78
    await fleet.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      headers: { "x-device-secret": "test-secret" },
      body: JSON.stringify({
        device_id: "m78",
        device_group: "NOVA",
        version: "phanserver-delta-agent-1.0.0",
        capabilities: ["allocate_server_2pc", "update_delta", "control_tailscale"]
      })
    }));

    telegramCalls = [];
    const queueRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "on",
        target_device_ids: ["m77", "m78"],
        telegram_chat_id: 12345
      })
    }))).json();

    const actionId = queueRes.tailscale.action_id;

    // Both devices poll heartbeat
    const h1 = await (await fleet.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      headers: { "x-device-secret": "test-secret" },
      body: JSON.stringify({ device_id: "m77" })
    }))).json();
    const h2 = await (await fleet.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      headers: { "x-device-secret": "test-secret" },
      body: JSON.stringify({ device_id: "m78" })
    }))).json();

    assert.equal(h1.command.action_id, actionId);
    assert.equal(h2.command.action_id, actionId);

    // m77 succeeds, m78 times out
    await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: "m77",
        action_id: actionId,
        status: "OPENED",
        executed: true,
        details: "CONNECTED: 100.80.175.55"
      })
    }));

    await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: "m78",
        action_id: actionId,
        status: "FAILED",
        executed: false,
        reason: "Timeout 12s"
      })
    }));

    assert.equal(telegramCalls.length, 2);
    const m77Msg = telegramCalls.find(c => c.body.text.includes("m77"));
    const m78Msg = telegramCalls.find(c => c.body.text.includes("m78"));
    assert.ok(m77Msg.body.text.includes("ĐÃ BẬT TAILSCALE THÀNH CÔNG!"));
    assert.ok(m78Msg.body.text.includes("BẬT TAILSCALE THẤT BẠI"));
  });

  // -------------------------------------------------------------------------
  // Test 7: Disconnect (mode: "off") and Status check reporting
  // -------------------------------------------------------------------------
  await t.test("off mode and status check notifications", async () => {
    // Test mode: "status" connected
    telegramCalls = [];
    const qStatus = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "status",
        target_device_ids: ["m77"],
        telegram_chat_id: 12345
      })
    }))).json();
    const tsStatusId = qStatus.tailscale.action_id;

    await fleet.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      headers: { "x-device-secret": "test-secret" },
      body: JSON.stringify({ device_id: "m77" })
    }));

    await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: "m77",
        action_id: tsStatusId,
        status: "OPENED",
        executed: true,
        details: "CONNECTED: 100.115.92.14"
      })
    }));

    assert.equal(telegramCalls.length, 1);
    assert.ok(telegramCalls[0].body.text.includes("TRẠNG THÁI TAILSCALE: CONNECTED (100.115.92.14)"));

    // Test mode: "status" disconnected
    telegramCalls = [];
    const qStatusDis = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "status",
        target_device_ids: ["m77"],
        telegram_chat_id: 12345
      })
    }))).json();
    const tsStatusDisId = qStatusDis.tailscale.action_id;

    await fleet.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      headers: { "x-device-secret": "test-secret" },
      body: JSON.stringify({ device_id: "m77" })
    }));

    await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: "m77",
        action_id: tsStatusDisId,
        status: "OPENED",
        executed: true,
        details: "DISCONNECTED"
      })
    }));

    assert.equal(telegramCalls.length, 1);
    assert.ok(telegramCalls[0].body.text.includes("TRẠNG THÁI TAILSCALE: DISCONNECTED"));

    // Test mode: "off" success
    telegramCalls = [];
    const qOff = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "control_tailscale",
        mode: "off",
        target_device_ids: ["m77"],
        telegram_chat_id: 12345
      })
    }))).json();
    const tsOffId = qOff.tailscale.action_id;

    await fleet.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      headers: { "x-device-secret": "test-secret" },
      body: JSON.stringify({ device_id: "m77" })
    }));

    await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CONTROL_TAILSCALE",
        device_id: "m77",
        action_id: tsOffId,
        status: "OPENED",
        executed: true,
        details: "DISCONNECTED"
      })
    }));

    assert.equal(telegramCalls.length, 1);
    assert.ok(telegramCalls[0].body.text.includes("ĐÃ TẮT TAILSCALE THÀNH CÔNG!"));
  });
});

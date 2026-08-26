import { FleetState } from "../worker/fleet_state.js";

let notifiedTelegram = null;
const env = {
  TEST_ENV: true,
  TELEGRAM_BOT_TOKEN: "mock-token",
  TELEGRAM_ADMIN_USER_ID: "123"
};

globalThis.fetch = async (url, init) => {
  if (url.includes("api.telegram.org")) {
    notifiedTelegram = JSON.parse(init.body);
    return { ok: true, json: async () => ({ ok: true }) };
  }
  return { ok: true, json: async () => ({}) };
};

class MockStorage {
  constructor() { this.store = new Map(); }
  async get(key) { return this.store.get(key); }
  async put(key, value) { this.store.set(key, JSON.parse(JSON.stringify(value))); }
}

class MockWebSocket {
  constructor(id) {
    this.id = id;
    this.sent = [];
  }
  send(data) { this.sent.push(JSON.parse(data)); }
}

async function runTests() {
  const storage = new MockStorage();
  const ctx = {
    storage,
    sockets: new Map(),
    getWebSockets(tag) {
      const match = tag.match(/device:fleet:(m\d+)/);
      if (match && this.sockets.has(match[1])) {
        return [this.sockets.get(match[1])];
      }
      return [];
    }
  };

  const fleet = new FleetState(ctx, env);

  // 1. Register devices m1, m2
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA", capabilities: ["allocate_server_2pc", "update_delta"] })
  }));
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m2", device_group: "NOVA", capabilities: ["allocate_server_2pc", "update_delta"] })
  }));

  const m1Ws = new MockWebSocket("m1");
  const m2Ws = new MockWebSocket("m2");
  ctx.sockets.set("m1", m1Ws);
  ctx.sockets.set("m2", m2Ws);

  // Verify online state
  const stateRes = await (await fleet.getHubState()).json();
  if (stateRes.state.devices.length !== 2) throw new Error("Expected 2 devices in state");
  if (!stateRes.state.devices.every(d => d.online)) throw new Error("Expected all devices online");

  // 2. Pending allocate lifecycle
  const token = "tok123";
  const spec = { ids: ["m1", "m2"], tabs: 5, allocationMap: { m1: [{ pkg: "com.tinh.vv.hi", url: "https://test1" }] } };
  
  // Save
  let saveRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "pending_allocate_save", token, spec })
  }))).json();
  if (!saveRes.ok) throw new Error("pending_allocate_save failed");

  // Consume (single use)
  let consumeRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "pending_allocate_consume", token })
  }))).json();
  if (!consumeRes.ok || consumeRes.spec.tabs !== 5) throw new Error("pending_allocate_consume failed");

  // Consume again -> should fail 404
  let consumeAgain = await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "pending_allocate_consume", token })
  }));
  if (consumeAgain.status !== 404) throw new Error("double consume did not fail with 404");

  // 3. Dispatch 2PC ALLOCATE_SERVER (Happy Path: m1, m2)
  m1Ws.sent = [];
  m2Ws.sent = [];
  const dispatchRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      kind: "allocate_server",
      target_device_ids: ["m1", "m2"],
      allocationMap: {
        m1: [{ pkg: "com.tinh.vv.hi", url: "https://test1" }],
        m2: [{ pkg: "com.tinh.vv.hi", url: "https://test2" }]
      },
      telegram_chat_id: 12345
    })
  }))).json();

  if (!dispatchRes.ok) throw new Error("dispatch failed: " + JSON.stringify(dispatchRes));
  const actionId = dispatchRes.batch.action_id;

  if (m1Ws.sent.length !== 1 || m1Ws.sent[0].action !== "PREPARE_ALLOCATE_SERVER") {
    throw new Error("m1 did not receive PREPARE_ALLOCATE_SERVER");
  }
  if (m2Ws.sent.length !== 1 || m2Ws.sent[0].action !== "PREPARE_ALLOCATE_SERVER") {
    throw new Error("m2 did not receive PREPARE_ALLOCATE_SERVER");
  }

  // m1 sends PREPARE_READY
  let ack1 = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "ALLOCATE_SERVER",
      device_id: "m1",
      action_id: actionId,
      status: "PREPARE_READY"
    })
  }))).json();
  if (!ack1.ok || ack1.status !== "PREPARE_READY") throw new Error("m1 PREPARE_READY ack failed");

  // m2Ws should not have COMMIT yet
  if (m2Ws.sent.some(f => f.action === "COMMIT_ALLOCATE_SERVER")) {
    throw new Error("COMMIT sent prematurely before all nodes prepared");
  }

  // m2 sends PREPARE_READY -> should trigger COMMIT_ALLOCATE_SERVER to all
  let ack2 = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "ALLOCATE_SERVER",
      device_id: "m2",
      action_id: actionId,
      status: "PREPARE_READY"
    })
  }))).json();
  if (!ack2.ok) throw new Error("m2 PREPARE_READY ack failed");

  if (!m1Ws.sent.some(f => f.action === "COMMIT_ALLOCATE_SERVER")) {
    throw new Error("m1 did not receive COMMIT_ALLOCATE_SERVER");
  }
  if (!m2Ws.sent.some(f => f.action === "COMMIT_ALLOCATE_SERVER")) {
    throw new Error("m2 did not receive COMMIT_ALLOCATE_SERVER");
  }

  // m1 and m2 send ALLOCATED and OPENED
  await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "ALLOCATE_SERVER",
      device_id: "m1",
      action_id: actionId,
      status: "ALLOCATED",
      executed: true
    })
  }));
  await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "ALLOCATE_SERVER",
      device_id: "m1",
      action_id: actionId,
      status: "OPENED",
      executed: true
    })
  }));

  notifiedTelegram = null;
  await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "ALLOCATE_SERVER",
      device_id: "m2",
      action_id: actionId,
      status: "OPENED",
      executed: true
    })
  }));

  if (!notifiedTelegram || !notifiedTelegram.text.includes("KẾT QUẢ PHÂN SERVER")) {
    throw new Error("Telegram completion notification not sent: " + JSON.stringify(notifiedTelegram));
  }

  // 4. Abort Path: m1 sends PREPARE_READY, m2 sends PREPARE_FAILED -> ABORT_ALLOCATE_SERVER sent
  m1Ws.sent = [];
  m2Ws.sent = [];
  const dispatchRes2 = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      kind: "allocate_server",
      target_device_ids: ["m1", "m2"],
      allocationMap: {
        m1: [{ pkg: "com.tinh.vv.hi", url: "https://test1" }],
        m2: [{ pkg: "com.tinh.vv.hi", url: "https://test2" }]
      },
      telegram_chat_id: 12345
    })
  }))).json();

  const actionId2 = dispatchRes2.batch.action_id;

  // m1 sends PREPARE_READY
  await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "ALLOCATE_SERVER",
      device_id: "m1",
      action_id: actionId2,
      status: "PREPARE_READY"
    })
  }));

  // m2 sends PREPARE_FAILED
  await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "ALLOCATE_SERVER",
      device_id: "m2",
      action_id: actionId2,
      status: "PREPARE_FAILED",
      reason: "invalid_roblox_url"
    })
  }));

  // m1Ws should have received ABORT_ALLOCATE_SERVER
  if (!m1Ws.sent.some(f => f.action === "ABORT_ALLOCATE_SERVER")) {
    throw new Error("ABORT_ALLOCATE_SERVER not sent to m1 on peer failure");
  }

  // 5. Offline Target fail-closed test
  ctx.sockets.delete("m2"); // m2 goes offline
  const offlineDispatch = await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      kind: "allocate_server",
      target_device_ids: ["m1", "m2"],
      allocationMap: {}
    })
  }));
  const offlineBody = await offlineDispatch.json();
  if (offlineDispatch.status !== 400 || offlineBody.error !== "offline_devices_in_allocate_batch") {
    throw new Error("offline fail-closed test failed: " + JSON.stringify(offlineBody));
  }

  console.log("TEST_FLEET_STATE_2PC_EQUIVALENCE=OK");
}

runTests().catch(e => { console.error(e); process.exit(1); });

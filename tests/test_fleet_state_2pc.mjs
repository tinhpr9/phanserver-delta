import { FleetState, extractValidTailscaleIp } from "../worker/fleet_state.js";

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
  ctx.sockets.delete("m2"); // m2 WebSocket closes
  const staleRecord = await fleet.readFleet();
  staleRecord.devices.m2.last_seen = Date.now() - 181000; // heartbeat expired
  await fleet.writeFleet(staleRecord);
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

  // 6. UPDATE_DELTA is queued per device and delivered through heartbeat.
  const updateRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "update_delta", target_device_ids: ["m1"] })
  }))).json();
  if (!updateRes.ok || !updateRes.update.action_id) throw new Error("UPDATE_DELTA queue failed");
  const deltaActionId = updateRes.update.action_id;
  const commandRes = await (await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA", capabilities: ["allocate_server_2pc", "update_delta"] })
  }))).json();
  if (commandRes.command?.action !== "UPDATE_DELTA" || commandRes.command?.action_id !== deltaActionId) {
    throw new Error("UPDATE_DELTA was not delivered by heartbeat");
  }
  const deltaAck = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", batch_action: "UPDATE_DELTA", device_id: "m1", action_id: deltaActionId, status: "OPENED", executed: true })
  }))).json();
  if (!deltaAck.ok || deltaAck.status !== "OPENED") throw new Error("UPDATE_DELTA ack failed");
  const afterAck = await (await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA", capabilities: ["allocate_server_2pc", "update_delta"] })
  }))).json();
  if (afterAck.command !== null) throw new Error("acknowledged UPDATE_DELTA was delivered again");

  // 7. CONTROL_TAILSCALE is queued per device and delivered through heartbeat.
  const tailscaleRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "on", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  if (!tailscaleRes.ok || !tailscaleRes.tailscale?.action_id) throw new Error("CONTROL_TAILSCALE queue failed: " + JSON.stringify(tailscaleRes));
  const tailscaleActionId = tailscaleRes.tailscale.action_id;
  const tailscaleCmdRes = await (await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  if (tailscaleCmdRes.command?.action !== "CONTROL_TAILSCALE" || tailscaleCmdRes.command?.action_id !== tailscaleActionId || tailscaleCmdRes.command?.mode !== "on") {
    throw new Error("CONTROL_TAILSCALE was not delivered by heartbeat: " + JSON.stringify(tailscaleCmdRes));
  }
  const tailscaleAck = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", batch_action: "CONTROL_TAILSCALE", device_id: "m1", action_id: tailscaleActionId, status: "OPENED", executed: true, details: "CONNECTED: 100.80.175.55" })
  }))).json();
  if (!tailscaleAck.ok || tailscaleAck.status !== "OPENED") throw new Error("CONTROL_TAILSCALE ack failed: " + JSON.stringify(tailscaleAck));
  if (!notifiedTelegram?.text?.includes("ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.80.175.55")) {
    throw new Error("Telegram message missing real Tailscale IP format: " + notifiedTelegram?.text);
  }
  if (!notifiedTelegram?.text?.includes("m1")) {
    throw new Error("Telegram message missing device ID: " + notifiedTelegram?.text);
  }
  const afterTailscaleAck = await (await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  if (afterTailscaleAck.command !== null) throw new Error("acknowledged CONTROL_TAILSCALE was delivered again");

  const stateAfterTs = await (await fleet.fetch(new Request("https://localhost/aot/hub/state"))).json();
  if (stateAfterTs.state?.devices?.find(d => d.device_id === "m1")?.tailscale_ip !== "100.80.175.55") {
    throw new Error("Fleet state missing tailscale_ip after ack: " + JSON.stringify(stateAfterTs));
  }

  // 7a-2. Heartbeat metrics tailscale_ip telemetry auto-recording
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA", metrics: { tailscale_ip: "100.90.200.1" } })
  }));
  const stateAfterHb = await (await fleet.fetch(new Request("https://localhost/aot/hub/state"))).json();
  if (stateAfterHb.state?.devices?.find(d => d.device_id === "m1")?.tailscale_ip !== "100.90.200.1") {
    throw new Error("Fleet state missing tailscale_ip from heartbeat metrics: " + JSON.stringify(stateAfterHb));
  }

  // 7b. CONTROL_TAILSCALE failure / timeout reporting
  const tsFailRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "on", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const tsFailActionId = tsFailRes.tailscale.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  const tsFailAck = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", batch_action: "CONTROL_TAILSCALE", device_id: "m1", action_id: tsFailActionId, status: "FAILED", executed: false, reason: "Timeout 12s không nhận được IP Tailscale (100.x.y.z)" })
  }))).json();
  if (!tsFailAck.ok || tsFailAck.status !== "FAILED") throw new Error("Expected FAILED status for timeout: " + JSON.stringify(tsFailAck));
  if (!notifiedTelegram?.text?.includes("BẬT TAILSCALE THẤT BẠI: Timeout 12s không nhận được IP Tailscale (100.x.y.z)")) {
    throw new Error("Telegram failure message format mismatch: " + notifiedTelegram?.text);
  }

  // 7c. CONTROL_TAILSCALE fake success elimination (TRIGGERED without IP must be rejected as FAILED)
  const tsFakeRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "on", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const tsFakeActionId = tsFakeRes.tailscale.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  const tsFakeAck = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", batch_action: "CONTROL_TAILSCALE", device_id: "m1", action_id: tsFakeActionId, status: "OPENED", executed: true, details: "TRIGGERED" })
  }))).json();
  if (tsFakeAck.status !== "FAILED") throw new Error("Expected fake TRIGGERED success to be rejected as FAILED: " + JSON.stringify(tsFakeAck));
  if (!notifiedTelegram?.text?.includes("BẬT TAILSCALE THẤT BẠI") || notifiedTelegram?.text?.includes("THÀNH CÔNG")) {
    throw new Error("Fake TRIGGERED must not report success to Telegram: " + notifiedTelegram?.text);
  }

  // 7d. CONTROL_TAILSCALE status check connected & disconnected
  const tsStatusRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "status", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const tsStatusActionId = tsStatusRes.tailscale.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", batch_action: "CONTROL_TAILSCALE", device_id: "m1", action_id: tsStatusActionId, status: "OPENED", executed: true, details: "CONNECTED: 100.80.175.55" })
  }));
  if (!notifiedTelegram?.text?.includes("TRẠNG THÁI TAILSCALE: CONNECTED (100.80.175.55)")) {
    throw new Error("Telegram status connected format mismatch: " + notifiedTelegram?.text);
  }

  const tsStatusDisRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "status", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const tsStatusDisActionId = tsStatusDisRes.tailscale.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", batch_action: "CONTROL_TAILSCALE", device_id: "m1", action_id: tsStatusDisActionId, status: "OPENED", executed: true, details: "DISCONNECTED" })
  }));
  if (!notifiedTelegram?.text?.includes("TRẠNG THÁI TAILSCALE: DISCONNECTED")) {
    throw new Error("Telegram status disconnected format mismatch: " + notifiedTelegram?.text);
  }

  // 7e. CONTROL_TAILSCALE off mode
  const tsOffRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "off", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const tsOffActionId = tsOffRes.tailscale.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", batch_action: "CONTROL_TAILSCALE", device_id: "m1", action_id: tsOffActionId, status: "OPENED", executed: true, details: "DISCONNECTED" })
  }));
  if (!notifiedTelegram?.text?.includes("ĐÃ TẮT TAILSCALE THÀNH CÔNG!")) {
    throw new Error("Telegram off format mismatch: " + notifiedTelegram?.text);
  }

  // 7f. CONTROL_TAILSCALE rejection of malformed IP octet > 255 (e.g. 100.300.1.1)
  const tsBadOctetRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "on", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const tsBadOctetActionId = tsBadOctetRes.tailscale.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA", capabilities: ["allocate_server_2pc", "update_delta"] })
  }));
  notifiedTelegram = null;
  const badOctetAck = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", batch_action: "CONTROL_TAILSCALE", device_id: "m1", action_id: tsBadOctetActionId, status: "OPENED", executed: true, details: "CONNECTED: 100.300.1.1" })
  }))).json();
  if (badOctetAck.status !== "FAILED") throw new Error("CONTROL_TAILSCALE accepted octet > 255: " + JSON.stringify(badOctetAck));
  if (!notifiedTelegram?.text?.includes("BẬT TAILSCALE THẤT BẠI") || notifiedTelegram?.text?.includes("THÀNH CÔNG")) {
    throw new Error("Telegram falsely reported success for invalid octet 100.300.1.1: " + notifiedTelegram?.text);
  }

  // 7g. CONTROL_TAILSCALE rejection of 4-digit octet suffix (e.g. 100.1.2.2555 - must not truncate to 100.1.2.255)
  const ts4DigitRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "on", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const ts4DigitActionId = ts4DigitRes.tailscale.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA", capabilities: ["allocate_server_2pc", "update_delta"] })
  }));
  notifiedTelegram = null;
  const fourDigitAck = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", batch_action: "CONTROL_TAILSCALE", device_id: "m1", action_id: ts4DigitActionId, status: "OPENED", executed: true, details: "CONNECTED: 100.1.2.2555" })
  }))).json();
  if (fourDigitAck.status !== "FAILED") throw new Error("CONTROL_TAILSCALE truncated 4-digit octet 100.1.2.2555: " + JSON.stringify(fourDigitAck));
  if (notifiedTelegram?.text?.includes("100.1.2.255") || !notifiedTelegram?.text?.includes("BẬT TAILSCALE THẤT BẠI")) {
    throw new Error("Telegram accepted truncated IP: " + notifiedTelegram?.text);
  }

  // 7h. Unit tests for extractValidTailscaleIp helper function
  if (typeof extractValidTailscaleIp === "function") {
    const validIPs = ["CONNECTED: 100.80.175.55", "100.64.0.1", "100.127.255.254", "100.0.0.0", "100.255.255.255"];
    for (const ip of validIPs) {
      if (!extractValidTailscaleIp(ip)) throw new Error("extractValidTailscaleIp failed for valid IP: " + ip);
    }
    const invalidIPs = [
      "CONNECTED: 100.300.1.1",
      "CONNECTED: 100.1.256.1",
      "CONNECTED: 100.1.2.2555",
      "CONNECTED: 1100.1.2.3",
      "CONNECTED: 100.1.2.3.4",
      "CONNECTED: .100.1.2.3",
      "100.1.1",
      "100.abc.1.1",
      "TRIGGERED",
      "",
      null
    ];
    for (const ip of invalidIPs) {
      if (extractValidTailscaleIp(ip) !== null) throw new Error("extractValidTailscaleIp accepted invalid IP: " + ip);
    }
  }

  // 7i. CONTROL_TAILSCALE action timeout alert to Telegram when pending action expires (>90s)
  const tsTimeoutRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "control_tailscale", mode: "on", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const tsTimeoutActionId = tsTimeoutRes.tailscale.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  const fleetRecord = await fleet.readFleet();
  for (const cmd of fleetRecord.pending_actions?.["m1"] || []) {
    if (cmd.action_id === tsTimeoutActionId) {
      cmd.delivered_at = Date.now() - 95000;
    }
  }
  await fleet.writeFleet(fleetRecord);
  notifiedTelegram = null;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  if (!notifiedTelegram?.text?.includes("ĐIỀU KHIỂN TAILSCALE QUÁ THỜI GIAN (TIMEOUT)")) {
    throw new Error("Telegram timeout notification not sent: " + notifiedTelegram?.text);
  }
  if (!notifiedTelegram?.text?.includes("m1")) {
    throw new Error("Telegram timeout notification missing deviceId: " + notifiedTelegram?.text);
  }

  // 8. CHECK_BAN is queued per device and acknowledged
  const checkbanRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  if (!checkbanRes.ok || !checkbanRes.checkban?.action_id) throw new Error("CHECK_BAN queue failed: " + JSON.stringify(checkbanRes));
  const cbActionId = checkbanRes.checkban.action_id;
  const cbCmdRes = await (await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  if (cbCmdRes.command?.action !== "CHECK_BAN" || cbCmdRes.command?.action_id !== cbActionId) {
    throw new Error("CHECK_BAN was not delivered by heartbeat");
  }
  const cbAck = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "CHECK_BAN",
      device_id: "m1",
      action_id: cbActionId,
      status: "OPENED",
      executed: true,
      details: JSON.stringify({ target: "M77", total: 5, live: 5, banned: 0, error: 0, banned_list: [] })
    })
  }))).json();
  if (!cbAck.ok || cbAck.status !== "OPENED") throw new Error("CHECK_BAN ack failed: " + JSON.stringify(cbAck));
  if (!notifiedTelegram?.text?.includes("100% LIVE") || !notifiedTelegram?.text?.includes("Tổng: <b>5</b>")) {
    throw new Error("CHECK_BAN 100% LIVE report failed: " + JSON.stringify(notifiedTelegram));
  }

  // 8b. CHECK_BAN: banned === 0 and errCount > 0
  const cbRes2 = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const cbActionId2 = cbRes2.checkban.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  const cbAck2 = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "CHECK_BAN",
      device_id: "m1",
      action_id: cbActionId2,
      status: "OPENED",
      executed: true,
      details: JSON.stringify({ target: "M77", total: 5, live: 3, banned: 0, error: 2, banned_list: [] })
    })
  }))).json();
  if (!cbAck2.ok) throw new Error("CHECK_BAN ack2 failed: " + JSON.stringify(cbAck2));
  if (!notifiedTelegram?.text?.includes("⚠️ Lỗi API: <b>2</b>")) {
    throw new Error("CHECK_BAN error count header failed: " + JSON.stringify(notifiedTelegram));
  }
  if (!notifiedTelegram?.text?.includes("⚠️ Không phát hiện tài khoản bị ban, nhưng có <b>2</b> tài khoản gặp lỗi tra cứu API.")) {
    throw new Error("CHECK_BAN error summary report failed: " + JSON.stringify(notifiedTelegram));
  }

  // 8c. CHECK_BAN: banned > 0, clean_result, replace_result and Rule 34 Google Drive sync
  const cbRes3 = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const cbActionId3 = cbRes3.checkban.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  const cbAck3 = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "CHECK_BAN",
      device_id: "m1",
      action_id: cbActionId3,
      status: "OPENED",
      executed: true,
      details: JSON.stringify({
        target: "M77",
        total: 10,
        live: 8,
        banned: 2,
        error: 0,
        banned_list: ["user_ban1", "user_ban2"],
        clean_result: { removed_from_acc: 2, archived_cookies_count: 2 },
        replace_result: { replaced_count: 2, remaining_reserve_count: 15, replaced_accounts: ["rep1", "rep2"] },
        sync_result: { acc_sync: true, data_tong_sync: true, rule34_verified: true }
      })
    })
  }))).json();
  if (!cbAck3.ok) throw new Error("CHECK_BAN ack3 failed: " + JSON.stringify(cbAck3));
  if (!notifiedTelegram?.text?.includes("📊 Tổng: <b>10</b> | 🟢 Sống: <b>8</b> | 🔴 Bị Ban: <b>2</b>")) {
    throw new Error("CHECK_BAN stats failed: " + JSON.stringify(notifiedTelegram));
  }
  if (!notifiedTelegram?.text?.includes("user_ban1") || !notifiedTelegram?.text?.includes("user_ban2")) {
    throw new Error("CHECK_BAN banned list failed: " + JSON.stringify(notifiedTelegram));
  }
  if (!notifiedTelegram?.text?.includes("Đã tự động gỡ <b>2</b> acc khỏi <code>acc.txt</code>")) {
    throw new Error("CHECK_BAN clean_result failed: " + JSON.stringify(notifiedTelegram));
  }
  if (!notifiedTelegram?.text?.includes("<b>Nạp bù dự phòng</b>: Đã tự động nạp <b>2</b> acc từ kho dự trữ vào máy") || !notifiedTelegram?.text?.includes("Kho còn lại: <b>15</b>")) {
    throw new Error("CHECK_BAN replace_result failed: " + JSON.stringify(notifiedTelegram));
  }
  if (!notifiedTelegram?.text?.includes("Google Drive") || !notifiedTelegram?.text?.includes("Rule 34")) {
    throw new Error("CHECK_BAN sync_result failed: " + JSON.stringify(notifiedTelegram));
  }

  // 8d. CHECK_BAN: removed_from_acc undefined falls back to banned
  const cbRes4 = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const cbActionId4 = cbRes4.checkban.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  const cbAck4 = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "CHECK_BAN",
      device_id: "m1",
      action_id: cbActionId4,
      status: "OPENED",
      executed: true,
      details: JSON.stringify({
        target: "M77",
        total: 5,
        live: 4,
        banned: 1,
        error: 0,
        banned_list: ["user_ban1"],
        clean_result: { archived_cookies_count: 1 }
      })
    })
  }))).json();
  if (!cbAck4.ok) throw new Error("CHECK_BAN ack4 failed: " + JSON.stringify(cbAck4));
  if (!notifiedTelegram?.text?.includes("Đã tự động gỡ <b>1</b> acc khỏi <code>acc.txt</code>")) {
    throw new Error("CHECK_BAN fallback to banned failed: " + JSON.stringify(notifiedTelegram));
  }

  // 8e. CHECK_BAN: Google Drive sync error reporting
  const cbRes5 = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const cbActionId5 = cbRes5.checkban.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  const cbAck5 = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "CHECK_BAN",
      device_id: "m1",
      action_id: cbActionId5,
      status: "OPENED",
      executed: true,
      details: JSON.stringify({
        target: "M77",
        total: 5,
        live: 4,
        banned: 1,
        error: 0,
        banned_list: ["user_ban1"],
        sync_result: { error: "rclone network timeout" }
      })
    })
  }))).json();
  if (!cbAck5.ok) throw new Error("CHECK_BAN ack5 failed: " + JSON.stringify(cbAck5));
  if (!notifiedTelegram?.text?.includes("Google Drive sync lỗi: <code>rclone network timeout</code>")) {
    throw new Error("CHECK_BAN sync error report failed: " + JSON.stringify(notifiedTelegram));
  }

  // 8f. CHECK_BAN: replace_result with remaining_reserve_count undefined
  const cbRes6 = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  const cbActionId6 = cbRes6.checkban.action_id;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));
  const cbAck6 = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "CHECK_BAN",
      device_id: "m1",
      action_id: cbActionId6,
      status: "OPENED",
      executed: true,
      details: JSON.stringify({
        target: "M77",
        total: 5,
        live: 4,
        banned: 1,
        error: 0,
        banned_list: ["user_ban1"],
        clean_result: { removed_from_acc: 1 },
        replace_result: { replaced_count: 1 }
      })
    })
  }))).json();
  if (!cbAck6.ok) throw new Error("CHECK_BAN ack6 failed: " + JSON.stringify(cbAck6));
  if (!notifiedTelegram?.text?.includes("🔄 <b>Nạp bù dự phòng</b>: Đã tự động nạp <b>1</b> acc từ kho dự trữ vào máy.")) {
    throw new Error("CHECK_BAN replace_result without remaining count failed: " + JSON.stringify(notifiedTelegram));
  }
  if (notifiedTelegram?.text?.includes("Kho còn lại")) {
    throw new Error("CHECK_BAN unexpected remaining count text: " + JSON.stringify(notifiedTelegram));
  }

  // 9. ADD_ACC is queued per device and acknowledged
  const addaccRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "add_acc", m_code: "m77", lines: ["user1:pass1"], target_device_ids: ["m1"], telegram_chat_id: 12345 })
  }))).json();
  if (!addaccRes.ok || !addaccRes.addacc?.action_id) throw new Error("ADD_ACC queue failed: " + JSON.stringify(addaccRes));
  const addActionId = addaccRes.addacc.action_id;
  const addCmdRes = await (await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  if (addCmdRes.command?.action !== "ADD_ACC" || addCmdRes.command?.action_id !== addActionId) {
    throw new Error("ADD_ACC was not delivered by heartbeat");
  }
  const addAck = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "ADD_ACC",
      device_id: "m1",
      action_id: addActionId,
      status: "OPENED",
      executed: true,
      details: JSON.stringify({ add: { m_code: "M77", added_count: 1, cookies_added: 0 }, sync: { "acc.txt": "OK" } })
    })
  }))).json();
  if (!addAck.ok || addAck.status !== "OPENED") throw new Error("ADD_ACC ack failed: " + JSON.stringify(addAck));

  // 10. MOVE_ACC queueMoveAcc, heartbeat delivery, ACK processing, and Telegram HTML report
  notifiedTelegram = null;
  const moveaccRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      kind: "move_acc",
      source_m: "m109",
      target_m: "m77",
      count: 2,
      target_device_ids: ["m1"],
      telegram_chat_id: 12345
    })
  }))).json();
  if (!moveaccRes.ok || !moveaccRes.moveacc?.action_id) throw new Error("MOVE_ACC queue failed: " + JSON.stringify(moveaccRes));
  const moveActionId = moveaccRes.moveacc.action_id;

  // Heartbeat delivers MOVE_ACC
  const moveCmdRes = await (await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  if (moveCmdRes.command?.action !== "MOVE_ACC" || moveCmdRes.command?.action_id !== moveActionId) {
    throw new Error("MOVE_ACC was not delivered by heartbeat: " + JSON.stringify(moveCmdRes));
  }
  if (moveCmdRes.command?.source_m !== "M109" || moveCmdRes.command?.target_m !== "M77" || moveCmdRes.command?.count !== 2) {
    throw new Error("MOVE_ACC command payload mismatch: " + JSON.stringify(moveCmdRes.command));
  }

  // Acknowledge MOVE_ACC success with rich details and verify HTML report
  const moveAck = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "MOVE_ACC",
      device_id: "m1",
      action_id: moveActionId,
      status: "OPENED",
      executed: true,
      details: JSON.stringify({
        source_m: "M109",
        target_m: "M77",
        count: 2,
        moved_accounts: ["MegaRegan426", "User_Alpha1"],
        source_remaining_count: 5,
        target_current_count: 8,
        backup_acc: "/storage/emulated/0/Download/Shouko/acc.txt.bak_20260914",
        sync_result: { acc_sync: true, rule34_verified: true, file_ids: { "acc.txt": "12oxXXlSPvHbB0YRUMQcHhLHiE4gemiVg" } }
      })
    })
  }))).json();
  if (!moveAck.ok || moveAck.status !== "OPENED") throw new Error("MOVE_ACC ack failed: " + JSON.stringify(moveAck));
  if (!notifiedTelegram?.text?.includes("ĐIỀU CHUYỂN TÀI KHOẢN THÀNH CÔNG") ||
      !notifiedTelegram?.text?.includes("MegaRegan426") ||
      !notifiedTelegram?.text?.includes("User_Alpha1") ||
      !notifiedTelegram?.text?.includes("Còn lại ở <b>M109</b>: <b>5</b> tài khoản") ||
      !notifiedTelegram?.text?.includes("Hiện có ở <b>M77</b>: <b>8</b> tài khoản") ||
      !notifiedTelegram?.text?.includes("Rule 34")) {
    throw new Error("MOVE_ACC Telegram report verification failed: " + JSON.stringify(notifiedTelegram));
  }

  // MOVE_ACC failure ACK and failure alert formatting
  notifiedTelegram = null;
  const moveFailRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      kind: "move_acc",
      source_m: "M109",
      target_m: "M77",
      count: 5,
      target_device_ids: ["m1"],
      telegram_chat_id: 12345
    })
  }))).json();
  const failActionId = moveFailRes.moveacc.action_id;

  // Consume from heartbeat
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));

  const failAck = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "MOVE_ACC",
      device_id: "m1",
      action_id: failActionId,
      status: "FAILED",
      executed: false,
      reason: "Dàn máy nguồn M109 chỉ có 2 tài khoản, không đủ 5 tài khoản để chuyển."
    })
  }))).json();
  if (!failAck.ok || failAck.status !== "FAILED") throw new Error("MOVE_ACC fail ack failed: " + JSON.stringify(failAck));
  if (!notifiedTelegram?.text?.includes("ĐIỀU CHUYỂN TÀI KHOẢN THẤT BẠI") ||
      !notifiedTelegram?.text?.includes("không đủ 5 tài khoản")) {
    throw new Error("MOVE_ACC fail Telegram alert verification failed: " + JSON.stringify(notifiedTelegram));
  }

  // 12. TAB_LIST queued per device, delivered via heartbeat, acknowledged and reported to Telegram
  const tabQueueRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      kind: "tab_list",
      target_device_ids: ["m1"],
      telegram_chat_id: 12345
    })
  }))).json();
  if (!tabQueueRes.ok || !tabQueueRes.tablist?.action_id) {
    throw new Error("TAB_LIST queue failed: " + JSON.stringify(tabQueueRes));
  }
  const tabActId = tabQueueRes.tablist.action_id;

  const tabCmdRes = await (await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  if (tabCmdRes.command?.action !== "TAB_LIST" || tabCmdRes.command?.action_id !== tabActId) {
    throw new Error("TAB_LIST was not delivered by heartbeat: " + JSON.stringify(tabCmdRes));
  }

  const tabAck = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "TAB_LIST",
      device_id: "m1",
      action_id: tabActId,
      status: "OPENED",
      executed: true,
      details: JSON.stringify({
        tabs: [
          { tab: 1, package: "com.tinh.vv.hi", username: "username_a" },
          { tab: 2, package: "com.tinh.vv.hj", username: "username_b" },
          { tab: 3, package: "com.tinh.vv.hk", username: null }
        ]
      })
    })
  }))).json();
  if (!tabAck.ok || tabAck.status !== "OPENED") throw new Error("TAB_LIST ack failed: " + JSON.stringify(tabAck));

  const expectedTabHtml = `📱 <b>Tab List — M1</b>\nTab 1: username_a\nTab 2: username_b\nTab 3: ❓ (unknown)`;
  if (!notifiedTelegram?.text?.includes(expectedTabHtml)) {
    throw new Error("TAB_LIST Telegram message format mismatch. Got:\n" + notifiedTelegram?.text);
  }

  const afterTabAck = await (await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  if (afterTabAck.command !== null) throw new Error("acknowledged TAB_LIST was delivered again");

  // 13. TAB_LIST timeout alert after 60s
  const tabQueueRes2 = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      kind: "tab_list",
      target_device_ids: ["m1"],
      telegram_chat_id: 12345
    })
  }))).json();
  const tabActId2 = tabQueueRes2.tablist.action_id;

  // Deliver the command
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));

  // Simulate 65 seconds elapsed without ack
  const recWithPending = await fleet.readFleet();
  const pendingCmd = recWithPending.pending_actions["m1"].find(c => c.action_id === tabActId2);
  if (pendingCmd) {
    pendingCmd.delivered_at = Date.now() - 65000;
    await fleet.writeFleet(recWithPending);
  }

  notifiedTelegram = null;
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }));

  if (!notifiedTelegram?.text?.includes("LẤY TAB LIST THẤT BẠI (TIMEOUT)") || !notifiedTelegram?.text?.includes("M1")) {
    throw new Error("TAB_LIST timeout Telegram alert failed. Got:\n" + notifiedTelegram?.text);
  }

  console.log("TEST_FLEET_STATE_2PC_EQUIVALENCE=OK");
}

runTests().catch(e => { console.error(e); process.exit(1); });

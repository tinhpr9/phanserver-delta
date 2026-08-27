import { FleetState } from "../worker/worker.js";

class MockStorage {
  constructor(initial) {
    this.store = new Map([["fleet_state", JSON.parse(JSON.stringify(initial))]]);
  }
  async get(key) {
    const value = this.store.get(key);
    return value == null ? value : JSON.parse(JSON.stringify(value));
  }
  async put(key, value) {
    this.store.set(key, JSON.parse(JSON.stringify(value)));
  }
}

function fakeSocket(attachment) {
  return {
    attachment,
    sent: [],
    closed: [],
    serializeAttachment(value) { this.attachment = value; },
    deserializeAttachment() { return this.attachment; },
    send(value) { this.sent.push(String(value)); },
    close(code, reason) { this.closed.push({ code, reason }); },
  };
}

async function runTests() {
  const oldSocket = fakeSocket({ device_id: "m73", session_id: "old", connected_at: 100 });
  const newSocket = fakeSocket({ device_id: "m73", session_id: "new", connected_at: 200 });
  const sockets = [oldSocket, newSocket];

  const state = {
    devices: {
      m73: {
        device_id: "m73",
        device_group: "NOVA",
        agent_secret_sha256: "paired-digest",
        online: true,
        last_seen: Date.now(),
        active_ws_session_id: "new",
        capabilities: ["allocate_server_2pc", "update_delta"],
      },
    },
    pending_allocates: {},
    pending_pairs: {},
    last_batch: {
      action_id: "act-hibernation",
      action: "ALLOCATE_SERVER",
      created_at: Date.now(),
      expires_at: Date.now() + 30000,
      commit_decided: false,
      commit_sent: false,
      abort_sent: false,
      telegram_chat_id: null,
      telegram_notified: false,
      devices: {
        m73: {
          device_id: "m73",
          status: "PREPARE_SENT",
          history: ["PREPARE_SENT"],
          reason: null,
          updated_at: Date.now(),
        },
      },
    },
  };

  const storage = new MockStorage(state);
  const ctx = {
    storage,
    getWebSockets(tag) {
      if (!tag || tag === "device:fleet:m73") return sockets;
      return [];
    },
  };
  const fleet = new FleetState(ctx, { TEST_ENV: true, AGENT_REPORT_SECRET: "legacy" });

  const sent = fleet.sendPayload("m73", { probe: "single-session" });
  if (sent !== 1) throw new Error("sendPayload did not send exactly once");
  if (oldSocket.sent.length !== 0 || newSocket.sent.length !== 1) {
    throw new Error("sendPayload did not select the newest attached session");
  }

  await fleet.webSocketMessage(newSocket, JSON.stringify({
    type: "ack",
    protocol: "fleet-batch-v1",
    batch_action: "ALLOCATE_SERVER",
    device_id: "m73",
    action_id: "act-hibernation",
    status: "PREPARE_READY",
    executed: false,
  }));

  const afterAck = await storage.get("fleet_state");
  if (afterAck.last_batch.devices.m73.status !== "COMMIT_SENT") {
    throw new Error("hibernation webSocketMessage did not advance 2PC ACK state");
  }
  if (!newSocket.sent.some(value => value.includes("COMMIT_ALLOCATE_SERVER"))) {
    throw new Error("COMMIT was not sent through the current hibernated socket");
  }
  if (oldSocket.sent.length !== 0) {
    throw new Error("stale socket received a command");
  }

  await fleet.webSocketClose(oldSocket, 1000, "old-close", true);
  const afterOldClose = await storage.get("fleet_state");
  if (!afterOldClose.devices.m73.online || afterOldClose.devices.m73.active_ws_session_id !== "new") {
    throw new Error("stale close event took the current session offline");
  }

  await fleet.webSocketClose(newSocket, 1000, "current-close", true);
  const afterCurrentClose = await storage.get("fleet_state");
  if (afterCurrentClose.devices.m73.online !== false || afterCurrentClose.devices.m73.active_ws_session_id) {
    throw new Error("current close event did not mark the device offline");
  }

  console.log("TEST_HIBERNATION_TRANSPORT=OK");
}

runTests().catch(error => {
  console.error(error);
  process.exit(1);
});

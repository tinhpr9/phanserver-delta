import { FleetState } from "../worker/worker.js";

let telegramPayload = null;
globalThis.fetch = async (url, init) => {
  if (String(url).includes("api.telegram.org")) {
    telegramPayload = JSON.parse(init.body);
    return { ok: true, json: async () => ({ ok: true }) };
  }
  return { ok: true, json: async () => ({}) };
};

class MockStorage {
  constructor(initial) {
    this.store = new Map();
    if (initial) this.store.set("fleet_state", JSON.parse(JSON.stringify(initial)));
  }
  async get(key) { return this.store.get(key); }
  async put(key, value) { this.store.set(key, JSON.parse(JSON.stringify(value))); }
}

async function requestPair(fleet) {
  telegramPayload = null;
  const response = await fleet.fetch(new Request("https://localhost/agent/pair/request", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Worker-Origin": "https://phanserver.example"
    },
    body: JSON.stringify({ device_id: "m74", device_group: "NOVA" })
  }));
  const body = await response.json();
  if (response.status !== 201 || !body.ok) throw new Error("legacy pair request failed");

  const approveButton = telegramPayload?.reply_markup?.inline_keyboard?.[0]?.find(
    button => String(button.callback_data || "").startsWith("pair_ok:")
  );
  if (!approveButton) throw new Error("legacy pair approval button missing");
  return { ...body, decisionHandle: approveButton.callback_data.slice("pair_ok:".length) };
}

async function approvePair(fleet, pair) {
  const decision = await fleet.fetch(new Request("https://localhost/agent/pair/decision", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Internal-Pair-Key": "legacy-control-secret"
    },
    body: JSON.stringify({ pair_id: pair.decisionHandle, decision: "approve" })
  }));
  if (decision.status !== 200) throw new Error("legacy pair approval failed");

  const status = await fleet.fetch(new Request("https://localhost/agent/pair/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pair_id: pair.pair_id, pair_token: pair.pair_token })
  }));
  const body = await status.json();
  if (status.status !== 200 || body.status !== "approved") {
    throw new Error("legacy pair status failed");
  }
  return body.agent_report_secret;
}

async function heartbeat(fleet, secret) {
  return fleet.fetch(new Request("https://localhost/report", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Agent-Secret": secret
    },
    body: JSON.stringify({
      device_id: "m74",
      device_group: "NOVA",
      capabilities: ["allocate_server_2pc", "update_delta"]
    })
  }));
}

async function ownStatus(fleet, secret) {
  const response = await fleet.fetch(new Request("https://localhost/agent/status", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Agent-Secret": secret
    },
    body: JSON.stringify({ device_id: "m74" })
  }));
  return { response, body: await response.json() };
}

async function runTests() {
  const closed = [];
  const oldSocket = {
    send() {},
    close(code, reason) { closed.push({ code, reason }); }
  };
  const storage = new MockStorage({
    devices: {
      m74: {
        device_id: "m74",
        device_group: "NOVA",
        online: true,
        capabilities: ["allocate_server_2pc", "update_delta"],
        last_seen: Date.now()
      }
    },
    last_batch: null,
    pending_allocates: {},
    pending_pairs: {},
    pair_request_by_device: {}
  });
  const fleet = new FleetState(
    {
      storage,
      getWebSockets(tag) {
        if (tag === "device:fleet:m74") return [oldSocket];
        return [];
      }
    },
    {
      TEST_ENV: true,
      TELEGRAM_BOT_TOKEN: "mock-token",
      TELEGRAM_ADMIN_USER_ID: "123",
      AGENT_REPORT_SECRET: "legacy-control-secret"
    }
  );

  const pair = await requestPair(fleet);
  const newSecret = await approvePair(fleet, pair);

  if (closed.length !== 0) {
    throw new Error("legacy socket was cut off at Telegram approval");
  }

  const stagedRecord = await storage.get("fleet_state");
  if (stagedRecord.devices.m74.agent_secret_sha256) {
    throw new Error("legacy credential was pinned as a per-device digest after approval");
  }
  if (!stagedRecord.devices.m74.pending_agent_secret_sha256) {
    throw new Error("legacy replacement credential was not left pending");
  }

  const oldBeforePromotion = await heartbeat(fleet, "legacy-control-secret");
  if (oldBeforePromotion.status !== 200) {
    throw new Error("legacy credential stopped working before replacement WebSocket promotion");
  }
  const newBeforePromotion = await heartbeat(fleet, newSecret);
  if (newBeforePromotion.status !== 200) {
    throw new Error("new legacy-migration credential was not staged");
  }

  const stagedStatus = await ownStatus(fleet, newSecret);
  if (stagedStatus.response.status !== 200 || stagedStatus.body.device?.online !== false) {
    throw new Error("staged legacy-migration credential inherited old ONLINE state");
  }

  const promoted = await fleet.promotePendingCredential("m74", newSecret);
  if (!promoted) throw new Error("legacy migration pending credential did not promote");
  if (closed.length !== 1 || closed[0].code !== 4001) {
    throw new Error("legacy socket was not closed exactly at credential promotion");
  }

  const oldAfterPromotion = await heartbeat(fleet, "legacy-control-secret");
  if (oldAfterPromotion.status !== 401) {
    throw new Error("legacy credential remained valid after promotion");
  }
  const newAfterPromotion = await heartbeat(fleet, newSecret);
  if (newAfterPromotion.status !== 200) {
    throw new Error("new credential failed after legacy migration promotion");
  }

  console.log("TEST_LEGACY_CREDENTIAL_ROTATION=OK");
}

runTests().catch(error => {
  console.error(error);
  process.exit(1);
});

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
  constructor() { this.store = new Map(); }
  async get(key) { return this.store.get(key); }
  async put(key, value) { this.store.set(key, JSON.parse(JSON.stringify(value))); }
}

async function requestPair(fleet, deviceId = "m73") {
  telegramPayload = null;
  const response = await fleet.fetch(new Request("https://localhost/agent/pair/request", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Worker-Origin": "https://phanserver.example"
    },
    body: JSON.stringify({ device_id: deviceId, device_group: "NOVA" })
  }));
  const body = await response.json();
  if (response.status !== 201 || !body.ok) {
    throw new Error("pair request failed: " + JSON.stringify(body));
  }
  const approveButton = telegramPayload?.reply_markup?.inline_keyboard?.[0]?.find(
    button => String(button.callback_data || "").startsWith("pair_ok:")
  );
  if (!approveButton) throw new Error("pair approval button missing");
  return { ...body, decisionHandle: approveButton.callback_data.slice("pair_ok:".length) };
}

async function approvePair(fleet, pair) {
  const response = await fleet.fetch(new Request("https://localhost/agent/pair/decision", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Internal-Pair-Key": "legacy-control-secret"
    },
    body: JSON.stringify({ pair_id: pair.decisionHandle, decision: "approve" })
  }));
  if (response.status !== 200) {
    throw new Error("pair approval failed: " + response.status);
  }

  const statusResponse = await fleet.fetch(new Request("https://localhost/agent/pair/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pair_id: pair.pair_id, pair_token: pair.pair_token })
  }));
  const statusBody = await statusResponse.json();
  if (statusResponse.status !== 200 || statusBody.status !== "approved") {
    throw new Error("approved pair status failed: " + JSON.stringify(statusBody));
  }
  return statusBody.agent_report_secret;
}

async function heartbeatStatus(fleet, deviceId, secret) {
  return fleet.fetch(new Request("https://localhost/report", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Agent-Secret": secret
    },
    body: JSON.stringify({
      device_id: deviceId,
      device_group: "NOVA",
      capabilities: ["allocate_server_2pc", "update_delta"]
    })
  }));
}

async function ownStatus(fleet, deviceId, secret) {
  const response = await fleet.fetch(new Request("https://localhost/agent/status", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Agent-Secret": secret
    },
    body: JSON.stringify({ device_id: deviceId })
  }));
  return { response, body: await response.json() };
}

async function runTests() {
  const storage = new MockStorage();
  const closedSockets = [];
  const oldSocket = {
    send() {},
    close(code, reason) { closedSockets.push({ code, reason }); }
  };
  const fleet = new FleetState(
    {
      storage,
      getWebSockets(tag) {
        return tag === "device:fleet:m73" ? [oldSocket] : [];
      }
    },
    {
      TEST_ENV: true,
      TELEGRAM_BOT_TOKEN: "mock-token",
      TELEGRAM_ADMIN_USER_ID: "123",
      AGENT_REPORT_SECRET: "legacy-control-secret"
    }
  );

  // First onboarding establishes the currently working credential.
  const firstPair = await requestPair(fleet);
  const oldSecret = await approvePair(fleet, firstPair);
  const firstHeartbeat = await heartbeatStatus(fleet, "m73", oldSecret);
  if (firstHeartbeat.status !== 200) throw new Error("initial credential was not usable");

  // Re-onboarding issues a new credential but does NOT cut over immediately.
  // The old runtime stays authoritative until the new credential proves a live
  // WebSocket, so a failed installer can roll back without server-side repair.
  const secondPair = await requestPair(fleet);
  const newSecret = await approvePair(fleet, secondPair);
  if (newSecret === oldSecret) throw new Error("credential rotation reused the old secret");
  if (closedSockets.length !== 0) {
    throw new Error("old socket was closed before new runtime proved connectivity");
  }

  const oldBeforePromotion = await heartbeatStatus(fleet, "m73", oldSecret);
  if (oldBeforePromotion.status !== 200) {
    throw new Error("old credential stopped working before promotion");
  }
  const newBeforePromotion = await heartbeatStatus(fleet, "m73", newSecret);
  if (newBeforePromotion.status !== 200) {
    throw new Error("staged credential could not authenticate during onboarding");
  }

  // Status queried with the staged credential must not inherit ONLINE from the
  // old socket; otherwise the installer could falsely report READY.
  const stagedStatus = await ownStatus(fleet, "m73", newSecret);
  if (stagedStatus.response.status !== 200 || stagedStatus.body.device?.online !== false) {
    throw new Error("staged credential inherited old runtime ONLINE state");
  }

  // A third pairing cannot stack another rotation while the staged credential is
  // still waiting to prove its WebSocket.
  telegramPayload = null;
  const stackedPair = await fleet.fetch(new Request("https://localhost/agent/pair/request", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Worker-Origin": "https://phanserver.example"
    },
    body: JSON.stringify({ device_id: "m73", device_group: "NOVA" })
  }));
  const stackedBody = await stackedPair.json();
  if (stackedPair.status !== 409 || stackedBody.error !== "credential_rotation_pending") {
    throw new Error("a second credential rotation could be stacked");
  }

  // This method models the atomic cutover performed immediately before the new
  // authenticated WebSocket is accepted. It revokes the old credential and closes
  // old sockets only after the new credential has proved itself.
  const promoted = await fleet.promotePendingCredential("m73", newSecret);
  if (!promoted) throw new Error("pending credential did not promote");
  if (closedSockets.length !== 1 || closedSockets[0].code !== 4001) {
    throw new Error("old socket was not closed at credential promotion");
  }

  const oldAfterPromotion = await heartbeatStatus(fleet, "m73", oldSecret);
  if (oldAfterPromotion.status !== 401) {
    throw new Error("old credential remained valid after promotion");
  }
  const newAfterPromotion = await heartbeatStatus(fleet, "m73", newSecret);
  if (newAfterPromotion.status !== 200) {
    throw new Error("new credential failed after promotion");
  }

  console.log("TEST_CREDENTIAL_ROTATION=OK");
}

runTests().catch(error => {
  console.error(error);
  process.exit(1);
});

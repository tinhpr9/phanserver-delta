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

async function runTests() {
  const storage = new MockStorage();
  const fleet = new FleetState(
    {
      storage,
      getWebSockets() { return []; }
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

  // Re-onboarding rotates to a new credential. Until the new runtime proves a
  // WebSocket connection, the previous credential remains valid only for the
  // short rollback grace window so installer rollback can recover the old runtime.
  const secondPair = await requestPair(fleet);
  const newSecret = await approvePair(fleet, secondPair);
  if (newSecret === oldSecret) throw new Error("credential rotation reused the old secret");

  const oldDuringGrace = await heartbeatStatus(fleet, "m73", oldSecret);
  if (oldDuringGrace.status !== 200) {
    throw new Error("previous credential was not preserved for rollback grace");
  }
  const newDuringGrace = await heartbeatStatus(fleet, "m73", newSecret);
  if (newDuringGrace.status !== 200) throw new Error("new credential was not usable during grace");

  // A successful WebSocket authenticated with the new credential commits the
  // rotation. The old credential must then fail immediately, not wait for TTL.
  const committed = await fleet.commitCredentialRotation("m73", newSecret);
  if (!committed) throw new Error("credential rotation did not commit");

  const oldAfterCommit = await heartbeatStatus(fleet, "m73", oldSecret);
  if (oldAfterCommit.status !== 401) {
    throw new Error("old credential remained valid after rotation commit");
  }
  const newAfterCommit = await heartbeatStatus(fleet, "m73", newSecret);
  if (newAfterCommit.status !== 200) {
    throw new Error("new credential failed after rotation commit");
  }

  console.log("TEST_CREDENTIAL_ROTATION=OK");
}

runTests().catch(error => {
  console.error(error);
  process.exit(1);
});

import { FleetState } from "../worker/worker.js";
import { handleCallback } from "../worker/phanserver.js";

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

async function runTests() {
  const storage = new MockStorage();
  const closedSockets = [];
  const oldSocket = {
    send() {},
    close(code, reason) { closedSockets.push({ code, reason }); }
  };
  const ctx = {
    storage,
    getWebSockets(tag) {
      return tag === "device:fleet:m73" ? [oldSocket] : [];
    }
  };
  const env = {
    TEST_ENV: true,
    TELEGRAM_BOT_TOKEN: "mock-token",
    TELEGRAM_ADMIN_USER_ID: "123",
    AGENT_REPORT_SECRET: "legacy-control-secret"
  };
  const fleet = new FleetState(ctx, env);

  const requestRes = await fleet.fetch(new Request("https://localhost/agent/pair/request", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Worker-Origin": "https://phanserver.example"
    },
    body: JSON.stringify({ device_id: "m73", device_group: "NOVA" })
  }));
  const requestBody = await requestRes.json();
  if (requestRes.status !== 201 || !requestBody.ok) throw new Error("pair request failed");
  if (!/^[A-Za-z0-9_-]{8,64}$/.test(requestBody.pair_id || "")) throw new Error("pair_id invalid");
  if (!/^[A-Za-z0-9_-]{32,256}$/.test(requestBody.pair_token || "")) throw new Error("pair_token invalid");
  if (!/^\d{6}$/.test(requestBody.verification_code || "")) throw new Error("verification_code invalid");
  if (requestBody.agent_report_secret) throw new Error("pair request leaked device secret");
  if (!telegramPayload?.text?.includes(requestBody.verification_code)) throw new Error("Telegram pairing notice missing verification code");

  const pairButtons = telegramPayload?.reply_markup?.inline_keyboard?.[0] || [];
  const approveButton = pairButtons.find(b => String(b.callback_data || "").startsWith("pair_ok:"));
  const rejectButton = pairButtons.find(b => String(b.callback_data || "").startsWith("pair_no:"));
  if (!approveButton || !rejectButton) throw new Error("Telegram pair buttons missing");
  const decisionHandle = approveButton.callback_data.slice("pair_ok:".length);
  if (decisionHandle === requestBody.pair_id || !decisionHandle.startsWith(requestBody.pair_id + "_")) {
    throw new Error("Telegram decision capability missing");
  }

  // A second unauthenticated request for the same device cannot invalidate the
  // legitimate in-flight pairing token.
  const replacementRes = await fleet.fetch(new Request("https://localhost/agent/pair/request", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Worker-Origin": "https://phanserver.example" },
    body: JSON.stringify({ device_id: "m73", device_group: "NOVA" })
  }));
  if (replacementRes.status !== 409) throw new Error("active pair request was replaceable");

  const pendingRes = await fleet.fetch(new Request("https://localhost/agent/pair/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pair_id: requestBody.pair_id, pair_token: requestBody.pair_token })
  }));
  if (pendingRes.status !== 202) throw new Error("original pending pair token was invalidated");

  // Possessing the public pair_id plus the internal control key is still not enough:
  // the unguessable decision capability exists only in Telegram callback_data.
  const forgedDecision = await fleet.fetch(new Request("https://localhost/agent/pair/decision", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Internal-Pair-Key": "legacy-control-secret" },
    body: JSON.stringify({ pair_id: requestBody.pair_id, decision: "approve" })
  }));
  if (![400, 403].includes(forgedDecision.status)) throw new Error("forged pair approval was accepted");

  const unauthorizedDecision = await fleet.fetch(new Request("https://localhost/agent/pair/decision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pair_id: decisionHandle, decision: "approve" })
  }));
  if (unauthorizedDecision.status !== 401) throw new Error("pair decision internal key was not enforced");

  const approveRes = await fleet.fetch(new Request("https://localhost/agent/pair/decision", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Internal-Pair-Key": "legacy-control-secret" },
    body: JSON.stringify({ pair_id: decisionHandle, decision: "approve" })
  }));
  if (approveRes.status !== 200) throw new Error("pair approval failed");
  if (closedSockets.length !== 0) throw new Error("fresh-device approval unexpectedly closed a socket");

  const approvedRes = await fleet.fetch(new Request("https://localhost/agent/pair/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pair_id: requestBody.pair_id, pair_token: requestBody.pair_token })
  }));
  const approvedBody = await approvedRes.json();
  if (approvedRes.status !== 200 || approvedBody.status !== "approved") throw new Error("approved pair status failed");
  if (approvedBody.worker_report_url !== "https://phanserver.example/report") throw new Error("pair report URL mismatch");
  if (!/^[A-Za-z0-9_-]{32,256}$/.test(approvedBody.agent_report_secret || "")) throw new Error("per-device secret missing");
  if (approvedBody.agent_report_secret === env.AGENT_REPORT_SECRET) throw new Error("global control secret leaked to device");

  const heartbeatRes = await fleet.fetch(new Request("https://localhost/report", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Agent-Secret": approvedBody.agent_report_secret },
    body: JSON.stringify({ device_id: "m73", device_group: "NOVA", capabilities: ["allocate_server_2pc", "update_delta"] })
  }));
  if (heartbeatRes.status !== 200) throw new Error("paired device heartbeat rejected");

  const ownStatus = await fleet.fetch(new Request("https://localhost/agent/status", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Agent-Secret": approvedBody.agent_report_secret },
    body: JSON.stringify({ device_id: "m73" })
  }));
  const ownStatusBody = await ownStatus.json();
  if (ownStatus.status !== 200 || !ownStatusBody.device?.online) throw new Error("authenticated own-device status failed");

  const badHeartbeatRes = await fleet.fetch(new Request("https://localhost/report", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Agent-Secret": "not-the-issued-secret" },
    body: JSON.stringify({ device_id: "m73", device_group: "NOVA" })
  }));
  if (badHeartbeatRes.status !== 401) throw new Error("wrong device secret accepted");

  // WebSocket auth must come from the handshake header; credentials in URLs are ignored.
  const queryOnlyWs = await fleet.fetch(new Request(
    `https://localhost/ws?device_id=m73&group=NOVA&secret=${encodeURIComponent(approvedBody.agent_report_secret)}`,
    { headers: { Upgrade: "websocket" } }
  ));
  if (queryOnlyWs.status !== 401) throw new Error("websocket URL credential was accepted");

  const badWebSocketRes = await fleet.fetch(new Request(
    "https://localhost/ws?device_id=m73&group=NOVA",
    { headers: { Upgrade: "websocket", "X-Agent-Secret": "not-the-issued-secret" } }
  ));
  if (badWebSocketRes.status !== 401) throw new Error("wrong websocket header secret accepted");

  // Public fleet-wide control/state endpoints are not part of the device API.
  const publicControl = await fleet.fetch(new Request("https://phanserver.example/aot/hub/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "allocate_server", target_device_ids: ["m73"] })
  }));
  if (publicControl.status !== 403) throw new Error("public fleet control endpoint was reachable");
  const publicState = await fleet.fetch(new Request("https://phanserver.example/aot/hub/state"));
  if (publicState.status !== 403) throw new Error("public fleet state endpoint was reachable");

  const productionEnv = {
    TELEGRAM_BOT_TOKEN: "mock-token",
    TELEGRAM_ADMIN_USER_ID: "123",
    AGENT_REPORT_SECRET: "legacy-control-secret"
  };
  const rateFleet = new FleetState({ storage: new MockStorage(), getWebSockets() { return []; } }, productionEnv);
  const firstRateRes = await rateFleet.fetch(new Request("https://phanserver.example/agent/pair/request", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_id: "m75", device_group: "NOVA" })
  }));
  if (firstRateRes.status !== 201) throw new Error("first production pair request should succeed");
  const secondDeviceRateRes = await rateFleet.fetch(new Request("https://phanserver.example/agent/pair/request", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_id: "m76", device_group: "NOVA" })
  }));
  if (secondDeviceRateRes.status !== 429) throw new Error("production pair requests were not globally rate limited");

  const noTelegramFleet = new FleetState(
    { storage: new MockStorage(), getWebSockets() { return []; } },
    { AGENT_REPORT_SECRET: "legacy-control-secret" }
  );
  const noTelegramRes = await noTelegramFleet.fetch(new Request("https://phanserver.example/agent/pair/request", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_id: "m77", device_group: "MARMOT" })
  }));
  if (noTelegramRes.status !== 502) throw new Error("pairing did not fail closed without Telegram admin configuration");

  // Telegram callback routing preserves the full decision handle, not the public pair_id.
  const callbackCalls = [];
  const callbackAnswers = [];
  const callbackEnv = {
    AGENT_REPORT_SECRET: "legacy-control-secret",
    fleetStateCall: async (_env, path, init) => {
      callbackCalls.push({ path, init });
      return { response: { ok: true }, data: { ok: true, status: "approved", device_id: "m73" } };
    },
    answerCallback: async (_id, _env, text, alert) => callbackAnswers.push({ text, alert })
  };
  await handleCallback(
    { id: "cb-pair", data: approveButton.callback_data, message: { chat: { id: 1 }, message_id: 9 }, from: { id: "123" } },
    1,
    9,
    callbackEnv,
    null,
    "123"
  );
  if (callbackCalls.length !== 1 || callbackCalls[0].path !== "/agent/pair/decision") throw new Error("Telegram pair callback did not route decision");
  if (callbackCalls[0].init.body.pair_id !== decisionHandle) throw new Error("Telegram decision capability was truncated");
  if (callbackCalls[0].init.body.decision !== "approve") throw new Error("Telegram pair callback decision mismatch");
  if (!callbackAnswers[0]?.text?.includes("m73")) throw new Error("Telegram pair callback response missing device ID");

  console.log("TEST_PAIRING_ONBOARDING=OK");
}

runTests().catch(error => {
  console.error(error);
  process.exit(1);
});

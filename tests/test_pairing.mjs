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
  const ctx = {
    storage,
    getWebSockets() { return []; }
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
  if (!pairButtons.some(b => b.callback_data === `pair_ok:${requestBody.pair_id}`)) throw new Error("Telegram approve callback missing");
  if (!pairButtons.some(b => b.callback_data === `pair_no:${requestBody.pair_id}`)) throw new Error("Telegram reject callback missing");

  const pendingRes = await fleet.fetch(new Request("https://localhost/agent/pair/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pair_id: requestBody.pair_id, pair_token: requestBody.pair_token })
  }));
  if (pendingRes.status !== 202) throw new Error("pending pair status should be 202");

  const unauthorizedDecision = await fleet.fetch(new Request("https://localhost/agent/pair/decision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pair_id: requestBody.pair_id, decision: "approve" })
  }));
  if (unauthorizedDecision.status !== 401) throw new Error("pair decision was not protected");

  const approveRes = await fleet.fetch(new Request("https://localhost/agent/pair/decision", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Internal-Pair-Key": "legacy-control-secret"
    },
    body: JSON.stringify({ pair_id: requestBody.pair_id, decision: "approve" })
  }));
  if (approveRes.status !== 200) throw new Error("pair approval failed");

  const wrongTokenRes = await fleet.fetch(new Request("https://localhost/agent/pair/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pair_id: requestBody.pair_id, pair_token: "wrong-token-wrong-token-wrong-token-1234" })
  }));
  if (wrongTokenRes.status !== 403) throw new Error("wrong pair token was accepted");

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
    headers: {
      "Content-Type": "application/json",
      "X-Agent-Secret": approvedBody.agent_report_secret
    },
    body: JSON.stringify({ device_id: "m73", device_group: "NOVA", capabilities: ["allocate_server_2pc", "update_delta"] })
  }));
  if (heartbeatRes.status !== 200) throw new Error("paired device heartbeat rejected");

  const badHeartbeatRes = await fleet.fetch(new Request("https://localhost/report", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Agent-Secret": "not-the-issued-secret"
    },
    body: JSON.stringify({ device_id: "m73", device_group: "NOVA" })
  }));
  if (badHeartbeatRes.status !== 401) throw new Error("wrong device secret accepted");

  const callbackCalls = [];
  const callbackAnswers = [];
  const callbackEnv = {
    AGENT_REPORT_SECRET: "legacy-control-secret",
    fleetStateCall: async (_env, path, init) => {
      callbackCalls.push({ path, init });
      return { response: { ok: true }, data: { ok: true, status: "approved", device_id: "m73" } };
    },
    answerCallback: async (_id, _env, text, alert) => {
      callbackAnswers.push({ text, alert });
    }
  };
  await handleCallback(
    { id: "cb-pair", data: `pair_ok:${requestBody.pair_id}`, message: { chat: { id: 1 }, message_id: 9 }, from: { id: "123" } },
    1,
    9,
    callbackEnv,
    null,
    "123"
  );
  if (callbackCalls.length !== 1 || callbackCalls[0].path !== "/agent/pair/decision") throw new Error("Telegram pair callback did not route decision");
  if (callbackCalls[0].init.body.decision !== "approve") throw new Error("Telegram pair callback decision mismatch");
  if (callbackCalls[0].init.headers["X-Internal-Pair-Key"] !== "legacy-control-secret") throw new Error("Telegram pair callback missing internal auth");
  if (!callbackAnswers[0]?.text?.includes("m73")) throw new Error("Telegram pair callback response missing device ID");

  console.log("TEST_PAIRING_ONBOARDING=OK");
}

runTests().catch(error => {
  console.error(error);
  process.exit(1);
});

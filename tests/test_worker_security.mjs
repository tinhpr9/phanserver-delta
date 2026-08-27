import worker from "../worker/worker.js";

async function runTests() {
  let forwarded = 0;
  const fleetStub = {
    async fetch() {
      forwarded += 1;
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    }
  };
  const fleetBinding = {
    idFromName() { return "global"; },
    get() { return fleetStub; }
  };

  const baseEnv = {
    FLEET_STATE: fleetBinding,
    TELEGRAM_BOT_TOKEN: "mock-token",
    TELEGRAM_ADMIN_USER_ID: "123"
  };

  const forgedUpdate = {
    callback_query: {
      id: "forged-callback",
      data: "pair_ok:public_pair_id_only",
      from: { id: "123" },
      message: { chat: { id: 1 }, message_id: 9 }
    }
  };

  const missingSecret = await worker.fetch(
    new Request("https://phanserver.example/telegram/webhook", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(forgedUpdate)
    }),
    baseEnv,
    {}
  );
  if (missingSecret.status !== 503) {
    throw new Error("Telegram webhook did not fail closed when secret was unconfigured");
  }

  const securedEnv = { ...baseEnv, TELEGRAM_WEBHOOK_SECRET: "telegram-webhook-secret" };
  const wrongSecret = await worker.fetch(
    new Request("https://phanserver.example/telegram/webhook", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Bot-Api-Secret-Token": "wrong-secret"
      },
      body: JSON.stringify(forgedUpdate)
    }),
    securedEnv,
    {}
  );
  if (wrongSecret.status !== 401) {
    throw new Error("Telegram webhook accepted a wrong secret");
  }

  const validSecret = await worker.fetch(
    new Request("https://phanserver.example/telegram/webhook", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Bot-Api-Secret-Token": "telegram-webhook-secret"
      },
      body: JSON.stringify({})
    }),
    securedEnv,
    {}
  );
  if (validSecret.status !== 200) {
    throw new Error("Telegram webhook rejected the configured secret");
  }

  const publicControl = await worker.fetch(
    new Request("https://phanserver.example/aot/hub/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "allocate_server",
        target_device_ids: ["m73"]
      })
    }),
    securedEnv,
    {}
  );
  if (publicControl.status !== 404) {
    throw new Error("Public fleet control route was forwarded");
  }

  const publicState = await worker.fetch(
    new Request("https://phanserver.example/aot/hub/state"),
    securedEnv,
    {}
  );
  if (publicState.status !== 404) {
    throw new Error("Public fleet state route was forwarded");
  }

  if (forwarded !== 0) {
    throw new Error("Security-gated public requests reached FleetState");
  }

  console.log("TEST_WORKER_SECURITY=OK");
}

runTests().catch(error => {
  console.error(error);
  process.exit(1);
});

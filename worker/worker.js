import { FleetState } from "./final_fleet_state.js";
import { handleUpdate } from "./phanserver.js";

export { FleetState };

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" }
  });
}

function safeEqual(left, right) {
  const a = String(left || "");
  const b = String(right || "");
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let index = 0; index < a.length; index++) {
    diff |= a.charCodeAt(index) ^ b.charCodeAt(index);
  }
  return diff === 0;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (path === "/health") {
      return json({ status: "healthy", service: "phanserver-delta" });
    }

    if (path === "/delta/manifest") {
      return json({
        channel: "delta",
        version: "1.0.0",
        release_date: "2026-08-26T12:00:00Z",
        assets: [
          {
            name: "Delta-v1.0.0.apk",
            url: "https://github.com/tinhpr9/phanserver-delta/releases/download/v1.0.0/Delta-v1.0.0.apk",
            kind: "apk",
            sha256: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            size: 1024
          }
        ]
      });
    }

    const fleetId = env.FLEET_STATE?.idFromName?.("global") || null;
    const fleetStub = fleetId ? env.FLEET_STATE.get(fleetId) : null;

    if (path === "/telegram/webhook" && request.method === "POST") {
      const configuredSecret = String(env?.TELEGRAM_WEBHOOK_SECRET || "");
      if (!configuredSecret) {
        return json({ ok: false, error: "telegram_webhook_secret_not_configured" }, 503);
      }
      const presentedSecret = String(request.headers.get("X-Telegram-Bot-Api-Secret-Token") || "");
      if (!safeEqual(presentedSecret, configuredSecret)) {
        return json({ ok: false, error: "unauthorized" }, 401);
      }
      try {
        const update = await request.json();
        await handleUpdate(update, env, fleetStub);
        return new Response("OK", { status: 200 });
      } catch (e) {
        return json({ ok: false, error: "telegram_update_invalid" }, 400);
      }
    }

    // Fleet-wide state and control are never public HTTP APIs. Telegram command
    // handling talks to the Durable Object directly with localhost requests.
    if (path === "/aot/hub/state" || path === "/aot/hub/control" || path === "/register") {
      return json({ ok: false, error: "not_found" }, 404);
    }

    if (fleetStub) {
      return fleetStub.fetch(request);
    }

    return json({ ok: false, error: "fleet_state_unreachable" }, 503);
  }
};

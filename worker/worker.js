import { FleetState } from "./hardened_fleet_state.js";
import { handleUpdate } from "./phanserver.js";

export { FleetState };

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (path === "/health") {
      return new Response(JSON.stringify({ status: "healthy", service: "phanserver-delta" }), {
        headers: { "Content-Type": "application/json" }
      });
    }

    if (path === "/delta/manifest") {
      return new Response(JSON.stringify({
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
      }), {
        headers: { "Content-Type": "application/json" }
      });
    }

    const fleetId = env.FLEET_STATE?.idFromName?.("global") || null;
    const fleetStub = fleetId ? env.FLEET_STATE.get(fleetId) : null;

    if (path === "/telegram/webhook" && request.method === "POST") {
      try {
        const update = await request.json();
        await handleUpdate(update, env, fleetStub);
        return new Response("OK", { status: 200 });
      } catch (e) {
        return new Response("Error: " + e.message, { status: 500 });
      }
    }

    // Fleet-wide state and control are never public HTTP APIs. Telegram command
    // handling talks to the Durable Object directly with localhost requests.
    if (path === "/aot/hub/state" || path === "/aot/hub/control" || path === "/register") {
      return new Response(JSON.stringify({ ok: false, error: "not_found" }), {
        status: 404,
        headers: { "Content-Type": "application/json", "Cache-Control": "no-store" }
      });
    }

    if (fleetStub) {
      return fleetStub.fetch(request);
    }

    return new Response(JSON.stringify({ ok: false, error: "fleet_state_unreachable" }), {
      status: 503,
      headers: { "Content-Type": "application/json" }
    });
  }
};

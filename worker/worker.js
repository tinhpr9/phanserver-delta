import { FleetState } from "./fleet_state.js";
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
      try {
        const ghRes = await fetch("https://api.github.com/repos/tinhpr9/phanserver-delta/releases?per_page=5", {
          headers: { "User-Agent": "phanserver-delta-worker" }
        });
        if (ghRes.ok) {
          const releases = await ghRes.json();
          if (Array.isArray(releases) && releases.length > 0) {
            const rel = releases[0];
            const assets = (rel.assets || []).map(a => ({
              name: a.name,
              url: a.browser_download_url,
              kind: a.name.toLowerCase().endsWith(".apk") ? "apk" : "zip",
              size: a.size
            }));
            return new Response(JSON.stringify({
              channel: "delta",
              version: rel.tag_name || "1.0.0",
              release_tag: rel.tag_name,
              release_name: rel.name || rel.tag_name,
              assets
            }), {
              headers: { "Content-Type": "application/json" }
            });
          }
        }
      } catch (e) {}

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

    // Get FleetState Durable Object stub
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

    if (fleetStub) {
      return fleetStub.fetch(request);
    }

    return new Response(JSON.stringify({ ok: false, error: "fleet_state_unreachable" }), {
      status: 503,
      headers: { "Content-Type": "application/json" }
    });
  }
};

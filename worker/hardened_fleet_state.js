import { FleetState as SecureFleetState } from "./secure_fleet_state.js";
import {
  FleetState as BaseFleetState,
  normalizeDeviceGroup,
  normalizeDeviceId,
} from "./fleet_state.js";

const CAPABILITIES = ["allocate_server_2pc", "update_delta"];
const PENDING_CREDENTIAL_TTL_MS = 10 * 60 * 1000;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}

function bytesToBase64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function randomToken(byteLength = 18) {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return bytesToBase64Url(bytes);
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(String(value)));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function safeEqual(left, right) {
  const a = String(left || "");
  const b = String(right || "");
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let index = 0; index < a.length; index++) diff |= a.charCodeAt(index) ^ b.charCodeAt(index);
  return diff === 0;
}

function escapeHtml(value) {
  return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export class FleetState extends SecureFleetState {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;

    // These endpoints are only for Worker -> Durable Object calls. Public requests
    // retain the real Worker hostname; phanserver.js constructs localhost requests.
    if (path === "/aot/hub/state" || path === "/aot/hub/control") {
      if (url.hostname !== "localhost") return json({ ok: false, error: "internal_only" }, 403);
      return super.fetch(request);
    }

    // The legacy unauthenticated registration endpoint must not be reachable once
    // pairing is enabled.
    if (path === "/register") return json({ ok: false, error: "not_found" }, 404);

    if (path === "/agent/status") return this.handleAgentStatus(request);
    return super.fetch(request);
  }

  async handlePairRequest(request) {
    let body;
    try {
      body = await request.clone().json();
    } catch (_error) {
      return json({ ok: false, error: "invalid_json" }, 400);
    }
    const deviceId = normalizeDeviceId(body?.device_id);
    const deviceGroup = normalizeDeviceGroup(body?.device_group);
    if (!deviceId || !deviceGroup) return json({ ok: false, error: "invalid_pair_identity" }, 400);

    // Never invalidate a legitimate in-flight pairing merely because another public
    // caller names the same device ID.
    const record = await this.readFleet();
    this.cleanupPendingPairs(record);
    const active = Object.values(record.pending_pairs || {}).find(
      (pair) => pair?.device_id === deviceId && pair?.status === "pending" && Number(pair?.expires_at || 0) > Date.now(),
    );
    if (active) return json({ ok: false, error: "pair_already_pending", retry_after: 15 }, 409);

    const device = record.devices?.[deviceId];
    if (
      device?.pending_agent_secret_sha256 &&
      Number(device.pending_agent_secret_expires_at || 0) > Date.now()
    ) {
      return json({ ok: false, error: "credential_rotation_pending", retry_after: 15 }, 409);
    }

    return super.handlePairRequest(request);
  }

  async notifyPairRequest(pairId, deviceId, deviceGroup, verificationCode) {
    if (!this.env?.TELEGRAM_BOT_TOKEN || !this.env?.TELEGRAM_ADMIN_USER_ID) return false;

    // The pairing requester receives pair_id but never this decision token. A forged
    // Telegram callback containing only pair_id therefore cannot approve itself.
    const decisionToken = randomToken(18);
    const decisionHandle = `${pairId}_${decisionToken}`;
    const record = await this.readFleet();
    const pair = record.pending_pairs?.[pairId];
    if (!pair || pair.status !== "pending") return false;
    pair.decision_token_sha256 = await sha256Hex(decisionToken);
    await this.writeFleet(record);

    const text = [
      "<b>GHÉP MÁY PHÂN SERVER</b>",
      "",
      `Máy: <b>${escapeHtml(deviceId)}</b>`,
      `Nhóm: <b>${escapeHtml(deviceGroup)}</b>`,
      `Mã trên máy: <b>${escapeHtml(verificationCode)}</b>`,
      "",
      "Chỉ chấp nhận nếu mã trên Telegram trùng mã đang hiện trên đúng UGPhone.",
    ].join("\n");

    try {
      const response = await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: this.env.TELEGRAM_ADMIN_USER_ID,
          text,
          parse_mode: "HTML",
          reply_markup: {
            inline_keyboard: [[
              { text: "✅ Chấp nhận", callback_data: `pair_ok:${decisionHandle}` },
              { text: "❌ Từ chối", callback_data: `pair_no:${decisionHandle}` },
            ]],
          },
        }),
      });
      return response.ok;
    } catch (_error) {
      return false;
    }
  }

  async handlePairDecision(request) {
    const controlSecret = String(this.env?.AGENT_REPORT_SECRET || "");
    const presented = String(request.headers.get("X-Internal-Pair-Key") || "");
    if (!controlSecret) return json({ ok: false, error: "pair_control_not_configured" }, 503);
    if (!safeEqual(presented, controlSecret)) return json({ ok: false, error: "unauthorized" }, 401);

    let body;
    try {
      body = await request.json();
    } catch (_error) {
      return json({ ok: false, error: "invalid_json" }, 400);
    }

    const handle = String(body?.pair_id || "");
    const decision = String(body?.decision || "");
    const separator = handle.indexOf("_");
    if (separator < 8 || !["approve", "reject"].includes(decision)) {
      return json({ ok: false, error: "invalid_pair_decision" }, 400);
    }
    const pairId = handle.slice(0, separator);
    const decisionToken = handle.slice(separator + 1);
    if (!/^[A-Za-z0-9_-]{8,64}$/.test(pairId) || !/^[A-Za-z0-9_-]{16,64}$/.test(decisionToken)) {
      return json({ ok: false, error: "invalid_pair_decision" }, 400);
    }

    const record = await this.readFleet();
    const pair = record.pending_pairs?.[pairId];
    if (!pair || pair.status !== "pending" || Number(pair.expires_at || 0) <= Date.now()) {
      return json({ ok: false, error: "pair_not_found" }, 404);
    }
    const tokenHash = await sha256Hex(decisionToken);
    if (!pair.decision_token_sha256 || !safeEqual(tokenHash, pair.decision_token_sha256)) {
      return json({ ok: false, error: "pair_decision_token_invalid" }, 403);
    }

    const previousSecretHash = decision === "approve"
      ? String(record.devices?.[pair.device_id]?.agent_secret_sha256 || "")
      : "";

    const forwarded = new Request("https://localhost/agent/pair/decision", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Internal-Pair-Key": controlSecret,
      },
      body: JSON.stringify({ pair_id: pairId, decision }),
    });
    const response = await super.handlePairDecision(forwarded);

    // For an existing device, approval must not revoke the known-good runtime yet.
    // The newly issued credential is staged and becomes authoritative only when it
    // proves a live WebSocket. If startup fails, the old credential remains current
    // and local installer rollback can restore the old files without server repair.
    if (
      decision === "approve" &&
      response.ok &&
      previousSecretHash &&
      !safeEqual(previousSecretHash, String(pair.device_secret_sha256 || ""))
    ) {
      const fresh = await this.readFleet();
      const device = fresh.devices?.[pair.device_id];
      if (device) {
        device.agent_secret_sha256 = previousSecretHash;
        device.pending_agent_secret_sha256 = String(pair.device_secret_sha256 || "");
        device.pending_agent_secret_expires_at = Date.now() + PENDING_CREDENTIAL_TTL_MS;
        await this.writeFleet(fresh);
      }
    }

    return response;
  }

  async credentialKind(deviceId, presentedSecret) {
    if (!presentedSecret) return null;
    const record = await this.readFleet();
    const device = record.devices?.[deviceId];
    const presentedHash = await sha256Hex(presentedSecret);

    const currentHash = String(device?.agent_secret_sha256 || "");
    if (currentHash && safeEqual(presentedHash, currentHash)) return "current";

    const pendingHash = String(device?.pending_agent_secret_sha256 || "");
    const pendingExpiresAt = Number(device?.pending_agent_secret_expires_at || 0);
    if (pendingHash) {
      if (pendingExpiresAt <= Date.now()) {
        delete device.pending_agent_secret_sha256;
        delete device.pending_agent_secret_expires_at;
        await this.writeFleet(record);
      } else if (safeEqual(presentedHash, pendingHash)) {
        return "pending";
      }
    }

    // Preserve the pre-pairing compatibility path for legacy devices that do not
    // yet have a per-device digest.
    if (!currentHash) {
      const legacySecret = String(this.env?.AGENT_REPORT_SECRET || "");
      if (legacySecret && safeEqual(presentedSecret, legacySecret)) return "current";
    }
    return null;
  }

  async verifyDeviceSecret(deviceId, presentedSecret) {
    return (await this.credentialKind(deviceId, presentedSecret)) !== null;
  }

  closeExistingDeviceSockets(deviceId, code, reason) {
    let closed = 0;
    const tag = `device:fleet:${deviceId}`;
    if (this.ctx?.getWebSockets) {
      for (const ws of this.ctx.getWebSockets(tag)) {
        try {
          ws.close(code, reason);
          closed += 1;
        } catch (_error) {}
      }
    }
    this.aotLive?.delete?.(deviceId);
    return closed;
  }

  async promotePendingCredential(deviceId, presentedSecret) {
    const record = await this.readFleet();
    const device = record.devices?.[deviceId];
    const pendingHash = String(device?.pending_agent_secret_sha256 || "");
    const pendingExpiresAt = Number(device?.pending_agent_secret_expires_at || 0);
    if (!pendingHash || pendingExpiresAt <= Date.now() || !presentedSecret) return false;

    const presentedHash = await sha256Hex(presentedSecret);
    if (!safeEqual(presentedHash, pendingHash)) return false;

    this.closeExistingDeviceSockets(deviceId, 4001, "credential_rotated");
    device.agent_secret_sha256 = pendingHash;
    delete device.pending_agent_secret_sha256;
    delete device.pending_agent_secret_expires_at;
    device.online = false;
    await this.writeFleet(record);
    return true;
  }

  async handleAgentStatus(request) {
    let body = {};
    if (request.method === "POST") {
      try { body = await request.json(); } catch (_error) { return json({ ok: false, error: "invalid_json" }, 400); }
    }
    const url = new URL(request.url);
    const deviceId = normalizeDeviceId(body?.device_id || url.searchParams.get("device_id"));
    if (!deviceId) return json({ ok: false, error: "invalid_device_id" }, 400);
    const secret = String(request.headers.get("X-Agent-Secret") || "");
    const kind = await this.credentialKind(deviceId, secret);
    if (!kind) return json({ ok: false, error: "unauthorized" }, 401);

    const record = await this.readFleet();
    const device = record.devices?.[deviceId];
    if (!device) return json({ ok: false, error: "device_not_found" }, 404);
    return json({
      ok: true,
      device: {
        device_id: deviceId,
        device_group: device.device_group,
        // A staged credential must not inherit ONLINE from the old runtime. This
        // keeps installer verification tied to the new credential's WebSocket.
        online: kind === "current" ? this.isDeviceOnline(deviceId, device) : false,
        capabilities: Array.isArray(device.capabilities) ? device.capabilities : [],
        last_seen: device.last_seen || null,
      },
    });
  }

  sendPayload(deviceId, payload) {
    const encoded = JSON.stringify(payload);
    let sent = 0;
    const taggedSockets = this.ctx?.getWebSockets
      ? this.ctx.getWebSockets(`device:fleet:${deviceId}`)
      : [];

    if (taggedSockets.length > 0) {
      for (const ws of taggedSockets) {
        try {
          ws.send(encoded);
          sent += 1;
        } catch (_error) {}
      }
      return sent;
    }

    // Test/dev contexts may not implement Durable Object socket tags. Fall back
    // to the in-memory socket only when no tagged socket exists, never both.
    const live = this.aotLive.get(deviceId);
    if (live?.socket) {
      try {
        live.socket.send(encoded);
        sent += 1;
      } catch (_error) {}
    }
    return sent;
  }

  async handleWebSocket(request) {
    const upgradeHeader = request.headers.get("Upgrade");
    if (!upgradeHeader || upgradeHeader.toLowerCase() !== "websocket") {
      return new Response("Expected WebSocket", { status: 426 });
    }

    const url = new URL(request.url);
    const deviceId = normalizeDeviceId(url.searchParams.get("device_id"));
    const requestedGroup = normalizeDeviceGroup(url.searchParams.get("group"));
    const presentedSecret = String(request.headers.get("X-Agent-Secret") || "");
    if (!deviceId) return new Response("Invalid device_id", { status: 400 });

    const kind = await this.credentialKind(deviceId, presentedSecret);
    if (!kind) return new Response("Unauthorized", { status: 401 });

    if (kind === "pending") {
      if (!(await this.promotePendingCredential(deviceId, presentedSecret))) {
        return new Response("Credential rotation failed", { status: 409 });
      }
    } else {
      // Enforce one live session per Device ID. A reconnect replaces its older
      // current-credential socket instead of causing duplicate command delivery.
      this.closeExistingDeviceSockets(deviceId, 4000, "device_reconnected");
    }

    const record = await this.readFleet();
    const existing = record.devices?.[deviceId] || {
      device_id: deviceId,
      joined_at: Date.now(),
      device_group: requestedGroup || "NOVA",
    };
    if (existing.device_group && requestedGroup && normalizeDeviceGroup(existing.device_group) !== requestedGroup) {
      return new Response("Device group mismatch", { status: 409 });
    }
    existing.device_group = normalizeDeviceGroup(existing.device_group || requestedGroup || "NOVA") || "NOVA";
    existing.online = true;
    existing.last_seen = Date.now();
    existing.capabilities = CAPABILITIES;
    record.devices[deviceId] = existing;
    await this.writeFleet(record);

    const pair = new WebSocketPair();
    const [client, server] = [pair[0], pair[1]];
    const tag = `device:fleet:${deviceId}`;
    this.ctx?.acceptWebSocket?.(server, [tag]);
    this.aotLive.set(deviceId, { capabilities: CAPABILITIES, connected_at: Date.now(), socket: server });

    server.addEventListener("message", async (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg?.type !== "ack") return;
        if (normalizeDeviceId(msg.device_id) !== deviceId) return;
        await BaseFleetState.prototype.dispatchFleetAck.call(
          this,
          new Request("https://localhost/aot/ack", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(msg),
          }),
        );
      } catch (_error) {}
    });

    server.addEventListener("close", async () => {
      this.aotLive.delete(deviceId);
      const fresh = await this.readFleet();
      if (fresh.devices?.[deviceId]) {
        fresh.devices[deviceId].online = false;
        await this.writeFleet(fresh);
      }
    });

    return new Response(null, { status: 101, webSocket: client });
  }
}

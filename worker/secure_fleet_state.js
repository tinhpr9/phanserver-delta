import {
  FleetState as BaseFleetState,
  normalizeDeviceGroup,
  normalizeDeviceId,
} from "./fleet_state.js";

const PAIR_TTL_MS = 10 * 60 * 1000;
const PAIR_POLL_AFTER_SECONDS = 3;

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

function randomToken(byteLength = 32) {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return bytesToBase64Url(bytes);
}

async function sha256Hex(value) {
  const encoded = new TextEncoder().encode(String(value));
  const digest = await crypto.subtle.digest("SHA-256", encoded);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
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

function escapeHtml(value) {
  return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export class FleetState extends BaseFleetState {
  async readFleet() {
    const record = await super.readFleet();
    if (!record.pending_pairs) record.pending_pairs = {};
    return record;
  }

  async fetch(request) {
    const path = new URL(request.url).pathname;
    if (path === "/agent/pair/request") return this.handlePairRequest(request);
    if (path === "/agent/pair/status") return this.handlePairStatus(request);
    if (path === "/agent/pair/decision") return this.handlePairDecision(request);
    return super.fetch(request);
  }

  cleanupPendingPairs(record) {
    const now = Date.now();
    for (const [pairId, pair] of Object.entries(record.pending_pairs || {})) {
      if (!pair || Number(pair.expires_at || 0) <= now) delete record.pending_pairs[pairId];
    }
  }

  async notifyPairRequest(pairId, deviceId, deviceGroup, verificationCode) {
    if (!this.env?.TELEGRAM_BOT_TOKEN || !this.env?.TELEGRAM_ADMIN_USER_ID) return true;
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
              { text: "✅ Chấp nhận", callback_data: `pair_ok:${pairId}` },
              { text: "❌ Từ chối", callback_data: `pair_no:${pairId}` },
            ]],
          },
        }),
      });
      return response.ok;
    } catch (_error) {
      return false;
    }
  }

  async handlePairRequest(request) {
    let body;
    try {
      body = await request.json();
    } catch (_error) {
      return json({ ok: false, error: "invalid_json" }, 400);
    }

    const deviceId = normalizeDeviceId(body?.device_id);
    const deviceGroup = normalizeDeviceGroup(body?.device_group);
    if (!deviceId || !deviceGroup) {
      return json({ ok: false, error: "invalid_pair_identity" }, 400);
    }

    let workerOrigin;
    try {
      workerOrigin = new URL(request.headers.get("X-Worker-Origin") || request.url).origin;
    } catch (_error) {
      return json({ ok: false, error: "invalid_worker_origin" }, 400);
    }
    if (!workerOrigin.startsWith("https://") && !this.env?.TEST_ENV) {
      return json({ ok: false, error: "worker_origin_must_use_https" }, 400);
    }

    const record = await this.readFleet();
    this.cleanupPendingPairs(record);
    for (const [existingPairId, pair] of Object.entries(record.pending_pairs)) {
      if (pair?.device_id === deviceId && pair?.status === "pending") {
        delete record.pending_pairs[existingPairId];
      }
    }

    const pairId = crypto.randomUUID().replace(/-/g, "").slice(0, 20);
    const pairToken = randomToken(32);
    const deviceSecret = randomToken(32);
    const verificationCode = String(crypto.getRandomValues(new Uint32Array(1))[0] % 1000000).padStart(6, "0");
    const now = Date.now();
    record.pending_pairs[pairId] = {
      pair_id: pairId,
      device_id: deviceId,
      device_group: deviceGroup,
      pair_token_sha256: await sha256Hex(pairToken),
      device_secret: deviceSecret,
      device_secret_sha256: await sha256Hex(deviceSecret),
      verification_code: verificationCode,
      worker_origin: workerOrigin,
      status: "pending",
      created_at: now,
      expires_at: now + PAIR_TTL_MS,
    };
    await this.writeFleet(record);

    const notified = await this.notifyPairRequest(pairId, deviceId, deviceGroup, verificationCode);
    if (!notified && !this.env?.TEST_ENV) {
      const fresh = await this.readFleet();
      delete fresh.pending_pairs?.[pairId];
      await this.writeFleet(fresh);
      return json({ ok: false, error: "telegram_pair_notification_failed" }, 502);
    }

    return json({
      ok: true,
      status: "pending",
      pair_id: pairId,
      pair_token: pairToken,
      verification_code: verificationCode,
      expires_in: Math.floor(PAIR_TTL_MS / 1000),
      poll_after: PAIR_POLL_AFTER_SECONDS,
    }, 201);
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
    const pairId = String(body?.pair_id || "");
    const decision = String(body?.decision || "");
    if (!/^[A-Za-z0-9_-]{8,64}$/.test(pairId) || !["approve", "reject"].includes(decision)) {
      return json({ ok: false, error: "invalid_pair_decision" }, 400);
    }

    const record = await this.readFleet();
    this.cleanupPendingPairs(record);
    const pair = record.pending_pairs[pairId];
    if (!pair) {
      await this.writeFleet(record);
      return json({ ok: false, error: "pair_not_found" }, 404);
    }
    if (pair.status !== "pending") {
      return json({ ok: false, error: "pair_already_decided", status: pair.status }, 409);
    }

    if (decision === "reject") {
      pair.status = "rejected";
      pair.decided_at = Date.now();
      pair.device_secret = "";
      await this.writeFleet(record);
      return json({ ok: true, status: "rejected", device_id: pair.device_id });
    }

    pair.status = "approved";
    pair.decided_at = Date.now();
    const existing = record.devices[pair.device_id] || {
      device_id: pair.device_id,
      joined_at: Date.now(),
    };
    existing.device_group = pair.device_group;
    existing.agent_secret_sha256 = pair.device_secret_sha256;
    existing.paired_at = Date.now();
    existing.online = false;
    existing.capabilities = existing.capabilities || [];
    record.devices[pair.device_id] = existing;
    await this.writeFleet(record);
    return json({ ok: true, status: "approved", device_id: pair.device_id });
  }

  async handlePairStatus(request) {
    let body;
    try {
      body = await request.json();
    } catch (_error) {
      return json({ ok: false, error: "invalid_json" }, 400);
    }
    const pairId = String(body?.pair_id || "");
    const pairToken = String(body?.pair_token || "");
    if (!/^[A-Za-z0-9_-]{8,64}$/.test(pairId) || pairToken.length < 32 || pairToken.length > 256) {
      return json({ ok: false, error: "invalid_pair_status_request" }, 400);
    }

    const record = await this.readFleet();
    const pair = record.pending_pairs[pairId];
    if (!pair) return json({ ok: false, error: "pair_not_found" }, 404);
    if (Number(pair.expires_at || 0) <= Date.now()) {
      delete record.pending_pairs[pairId];
      await this.writeFleet(record);
      return json({ ok: false, error: "pair_expired" }, 410);
    }
    const tokenHash = await sha256Hex(pairToken);
    if (!safeEqual(tokenHash, pair.pair_token_sha256)) {
      return json({ ok: false, error: "pair_token_invalid" }, 403);
    }
    if (pair.status === "pending") {
      return json({ ok: true, status: "pending", poll_after: PAIR_POLL_AFTER_SECONDS }, 202);
    }
    if (pair.status === "rejected") {
      return json({ ok: false, status: "rejected", error: "pair_rejected" }, 403);
    }
    if (pair.status !== "approved" || !pair.device_secret) {
      return json({ ok: false, error: "pair_state_invalid" }, 409);
    }
    return json({
      ok: true,
      status: "approved",
      device_id: pair.device_id,
      device_group: pair.device_group,
      worker_report_url: `${pair.worker_origin}/report`,
      agent_report_secret: pair.device_secret,
    });
  }

  async verifyDeviceSecret(deviceId, presentedSecret) {
    const record = await this.readFleet();
    const device = record.devices?.[deviceId];
    if (device?.agent_secret_sha256) {
      if (!presentedSecret) return false;
      return safeEqual(await sha256Hex(presentedSecret), device.agent_secret_sha256);
    }
    const legacySecret = String(this.env?.AGENT_REPORT_SECRET || "");
    return Boolean(legacySecret) && safeEqual(presentedSecret, legacySecret);
  }

  async handleHeartbeat(request) {
    let body;
    try {
      body = await request.clone().json();
    } catch (_error) {
      return json({ ok: false, error: "invalid_json" }, 400);
    }
    const deviceId = normalizeDeviceId(body?.device_id);
    if (!deviceId) return json({ ok: false, error: "invalid_device_id" }, 400);
    const presentedSecret = String(request.headers.get("X-Agent-Secret") || "");
    if (!(await this.verifyDeviceSecret(deviceId, presentedSecret))) {
      return json({ ok: false, error: "unauthorized" }, 401);
    }
    return super.handleHeartbeat(request);
  }

  async handleWebSocket(request) {
    const url = new URL(request.url);
    const deviceId = normalizeDeviceId(url.searchParams.get("device_id"));
    const presentedSecret = String(url.searchParams.get("secret") || "");
    if (!deviceId) return new Response("Invalid device_id", { status: 400 });
    if (!(await this.verifyDeviceSecret(deviceId, presentedSecret))) {
      return new Response("Unauthorized", { status: 401 });
    }

    const legacySecret = String(this.env?.AGENT_REPORT_SECRET || "");
    if (legacySecret) url.searchParams.set("secret", legacySecret);
    return super.handleWebSocket(new Request(url.toString(), request));
  }

  async dispatchFleetAck(request) {
    let body;
    try {
      body = await request.clone().json();
    } catch (_error) {
      return json({ ok: false, error: "invalid_json" }, 400);
    }
    const deviceId = normalizeDeviceId(body?.device_id);
    if (!deviceId) return json({ ok: false, error: "invalid_aot_ack" }, 400);
    const presentedSecret = String(request.headers.get("X-Agent-Secret") || "");
    if (!(await this.verifyDeviceSecret(deviceId, presentedSecret))) {
      return json({ ok: false, error: "unauthorized" }, 401);
    }
    return super.dispatchFleetAck(request);
  }
}

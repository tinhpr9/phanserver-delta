const AOT_ALLOCATE_SERVER_ACTION = "ALLOCATE_SERVER";
const AOT_ALLOCATE_SERVER_CAPABILITY = "allocate_server_2pc";
const AOT_BATCH_PACKAGE = "com.tinh.vv.hi";
const AOT_BATCH_TTL_MS = 30000;
const AOT_HUB_PROTOCOL_VERSION = "fleet-batch-v1";
const PENDING_ALLOCATE_TTL_MS = 300000; // 5 minutes

export function normalizeDeviceId(value) {
  const raw = String(value || "").trim();
  const dynamicMatch = raw.match(/^m([1-9]\d{0,5})$/i);
  if (dynamicMatch) return `m${dynamicMatch[1]}`;
  const legacyMatch = raw.match(/^(MARMOT|NOVA)-(\d{2})$/i);
  if (!legacyMatch) return null;
  const group = legacyMatch[1].toUpperCase();
  const index = Number(legacyMatch[2]);
  if (index < 1 || index > 10) return null;
  return `${group}-${String(index).padStart(2, "0")}`;
}

export function normalizeDeviceGroup(value) {
  const raw = String(value || "").trim().toUpperCase().replace(/[\s_-]+/g, "");
  if (["1", "NHOM1", "GROUP1", "MARMOT"].includes(raw)) return "MARMOT";
  if (["2", "NHOM2", "GROUP2", "NOVA"].includes(raw)) return "NOVA";
  if (["MARMOT", "NOVA"].includes(raw)) return raw;
  return null;
}

export function compareDeviceIds(left, right) {
  return left.localeCompare(right, undefined, { numeric: true, sensitivity: "base" });
}

export function normalizeDeviceIdList(values) {
  const rawValues = Array.isArray(values) ? values : String(values || "").split(",");
  const result = [];
  const seen = new Set();
  for (const rawValue of rawValues) {
    const deviceId = normalizeDeviceId(rawValue);
    if (!deviceId) throw new Error(`Device ID không hợp lệ: ${rawValue}`);
    if (seen.has(deviceId)) throw new Error(`Device ID bị lặp: ${deviceId}`);
    seen.add(deviceId);
    result.push(deviceId);
  }
  return result.sort(compareDeviceIds);
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

export class FleetState {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    this.aotLive = new Map(); // device_id -> { capabilities, connected_at, socket }
  }

  async readFleet() {
    let record = await this.ctx?.storage?.get?.("fleet_state");
    if (!record) {
      record = {
        devices: {},
        last_batch: null,
        pending_allocates: {}
      };
    }
    if (!record.devices) record.devices = {};
    if (!record.pending_allocates) record.pending_allocates = {};
    return record;
  }

  async writeFleet(record) {
    if (this.ctx?.storage?.put) {
      await this.ctx.storage.put("fleet_state", record);
    }
  }

  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (path === "/ws") {
      return this.handleWebSocket(request);
    }
    if (path === "/aot/hub/state") {
      return this.getHubState();
    }
    if (path === "/aot/hub/control") {
      return this.controlFleetHub(request);
    }
    if (path === "/aot/ack") {
      return this.dispatchFleetAck(request);
    }
    if (path === "/report" || path === "/aot/heartbeat") {
      return this.handleHeartbeat(request);
    }
    if (path === "/register") {
      return this.registerFleetDevice(request);
    }
    return json({ ok: false, error: "not_found" }, 404);
  }

  async handleWebSocket(request) {
    const upgradeHeader = request.headers.get("Upgrade");
    if (!upgradeHeader || upgradeHeader.toLowerCase() !== "websocket") {
      return new Response("Expected WebSocket", { status: 426 });
    }

    const url = new URL(request.url);
    const rawDeviceId = url.searchParams.get("device_id");
    const secret = url.searchParams.get("secret");
    const deviceId = normalizeDeviceId(rawDeviceId);

    if (!deviceId) {
      return new Response("Invalid device_id", { status: 400 });
    }
    if (this.env?.AGENT_REPORT_SECRET && secret !== this.env.AGENT_REPORT_SECRET) {
      return new Response("Unauthorized", { status: 401 });
    }

    const pair = new WebSocketPair();
    const [client, server] = [pair[0], pair[1]];

    const record = await this.readFleet();
    if (!record.devices[deviceId]) {
      record.devices[deviceId] = {
        device_id: deviceId,
        device_group: normalizeDeviceGroup(url.searchParams.get("group") || "NOVA") || "NOVA",
        joined_at: Date.now()
      };
    }
    record.devices[deviceId].online = true;
    record.devices[deviceId].last_seen = Date.now();
    record.devices[deviceId].capabilities = [AOT_ALLOCATE_SERVER_CAPABILITY, "update_delta"];
    await this.writeFleet(record);

    this.ctx?.acceptWebSocket?.(server, [`device:fleet:${deviceId}`]);
    this.aotLive.set(deviceId, {
      capabilities: [AOT_ALLOCATE_SERVER_CAPABILITY, "update_delta"],
      connected_at: Date.now(),
      socket: server
    });

    server.addEventListener("message", async (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "ack") {
          await this.dispatchFleetAck(new Request("https://localhost/aot/ack", {
            method: "POST",
            body: JSON.stringify(msg)
          }));
        }
      } catch (e) {}
    });

    server.addEventListener("close", async () => {
      this.aotLive.delete(deviceId);
      const rec = await this.readFleet();
      if (rec.devices[deviceId]) {
        rec.devices[deviceId].online = false;
        await this.writeFleet(rec);
      }
    });

    return new Response(null, { status: 101, webSocket: client });
  }

  async handleHeartbeat(request) {
    let body;
    try {
      body = await request.json();
    } catch (e) {
      return json({ ok: false, error: "invalid_json" }, 400);
    }

    const deviceId = normalizeDeviceId(body?.device_id);
    if (!deviceId) return json({ ok: false, error: "invalid_device_id" }, 400);

    const record = await this.readFleet();
    const existing = record.devices[deviceId] || { device_id: deviceId, joined_at: Date.now() };
    existing.device_group = normalizeDeviceGroup(body?.device_group || existing.device_group || "NOVA") || "NOVA";
    existing.online = true;
    existing.last_seen = Date.now();
    existing.metrics = body?.metrics || null;
    existing.capabilities = Array.isArray(body?.capabilities) ? body.capabilities : [AOT_ALLOCATE_SERVER_CAPABILITY, "update_delta"];
    record.devices[deviceId] = existing;

    await this.writeFleet(record);
    return json({ ok: true, device_id: deviceId });
  }

  async getHubState() {
    const record = await this.readFleet();
    const devices = Object.values(record.devices).map(d => {
      const isOnline = this.isDeviceOnline(d.device_id, d);
      return {
        device_id: d.device_id,
        device_group: d.device_group,
        online: isOnline,
        last_seen: d.last_seen,
        capabilities: d.capabilities || []
      };
    });
    return json({
      ok: true,
      state: {
        devices,
        last_batch: record.last_batch
      }
    });
  }

  isDeviceOnline(id, recordDevice) {
    if (this.ctx?.getWebSockets) {
      return this.ctx.getWebSockets(`device:fleet:${id}`).length > 0;
    }
    if (this.aotLive.has(id)) return true;
    if (recordDevice && recordDevice.online && (Date.now() - (recordDevice.last_seen || 0) < 180000)) {
      return true;
    }
    return false;
  }

  sendPayload(deviceId, payload) {
    let sent = 0;
    if (this.ctx?.getWebSockets) {
      for (const ws of this.ctx.getWebSockets(`device:fleet:${deviceId}`)) {
        try {
          ws.send(JSON.stringify(payload));
          sent++;
        } catch (e) {}
      }
    }
    const live = this.aotLive.get(deviceId);
    if (live && live.socket) {
      try {
        live.socket.send(JSON.stringify(payload));
        sent++;
      } catch (e) {}
    }
    return sent;
  }

  async controlFleetHub(request) {
    let body;
    try {
      body = await request.json();
    } catch (e) {
      return json({ ok: false, error: "invalid_json" }, 400);
    }
    if (!body || body.protocol !== AOT_HUB_PROTOCOL_VERSION) {
      return json({ ok: false, error: "invalid_hub_control" }, 400);
    }

    const record = await this.readFleet();

    if (body.kind === "pending_allocate_save") {
      if (!record.pending_allocates) record.pending_allocates = {};
      record.pending_allocates[body.token] = { ...body.spec, created: Date.now() };
      for (const t in record.pending_allocates) {
        if (Date.now() - record.pending_allocates[t].created > PENDING_ALLOCATE_TTL_MS) {
          delete record.pending_allocates[t];
        }
      }
      await this.writeFleet(record);
      return json({ ok: true });
    }

    if (body.kind === "pending_allocate_consume") {
      if (!record.pending_allocates) return json({ ok: false, error: "not_found" }, 404);
      const spec = record.pending_allocates[body.token];
      if (spec) {
        delete record.pending_allocates[body.token];
        await this.writeFleet(record);
        if (Date.now() - spec.created > PENDING_ALLOCATE_TTL_MS) {
          return json({ ok: false, error: "expired" }, 400);
        }
        return json({ ok: true, spec });
      }
      return json({ ok: false, error: "not_found" }, 404);
    }

    if (body.kind === "pending_allocate_clear") {
      if (record.pending_allocates && record.pending_allocates[body.token]) {
        delete record.pending_allocates[body.token];
        await this.writeFleet(record);
        return json({ ok: true, cleared: true });
      }
      return json({ ok: true, cleared: false });
    }

    if (body.kind === "allocate_server") {
      return this.dispatchFleetBatch(
        record,
        AOT_ALLOCATE_SERVER_ACTION,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        { allocationMap: body.allocationMap, telegram_chat_id: body.telegram_chat_id }
      );
    }

    return json({ ok: false, error: "unsupported_fleet_control" }, 400);
  }

  async dispatchFleetBatch(record, action, requestedTargetIds, options = {}) {
    if (action !== AOT_ALLOCATE_SERVER_ACTION) {
      return json({ ok: false, error: "invalid_batch_action" }, 400);
    }

    const fresh = await this.readFleet();
    const previous = fresh.last_batch;
    const allocateTerminal = new Set(["OPENED", "FAILED", "TIMEOUT", "PREPARE_FAILED", "SKIPPED_OFFLINE", "ABORT_SENT", "DUPLICATE"]);
    
    if (
      previous?.action === AOT_ALLOCATE_SERVER_ACTION &&
      Number(previous.expires_at || 0) > Date.now() &&
      Object.values(previous.devices || {}).some(d => !allocateTerminal.has(String(d.status)))
    ) {
      return json({ ok: false, error: "allocation_in_progress", action_id: previous.action_id }, 409);
    }

    const seen = new Set();
    const targets = [];
    const missingCapabilityIds = [];

    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      if (!id || seen.has(id) || !fresh.devices[id]) {
        return json({ ok: false, error: "invalid_batch_target" }, 400);
      }
      const isOnline = this.isDeviceOnline(id, fresh.devices[id]);
      if (isOnline) {
        const caps = fresh.devices[id]?.capabilities || [];
        if (!caps.includes(AOT_ALLOCATE_SERVER_CAPABILITY)) {
          missingCapabilityIds.push(id);
        }
      }
      seen.add(id);
      targets.push(id);
    }

    if (missingCapabilityIds.length > 0) {
      return json({ ok: false, error: "worker_missing_allocate_server_2pc_capability", device_ids: missingCapabilityIds }, 409);
    }
    if (!targets.length) {
      return json({ ok: false, error: "invalid_batch_targets" }, 400);
    }

    const createdAt = Date.now();
    const expiresAt = createdAt + AOT_BATCH_TTL_MS;
    const actionId = `fleet-${createdAt}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const devices = {};
    const online = [];

    for (const id of targets) {
      const connected = this.isDeviceOnline(id, fresh.devices[id]);
      const initialStatus = connected ? "PREPARE_SENT" : "SKIPPED_OFFLINE";
      devices[id] = {
        device_id: id,
        status: initialStatus,
        history: [initialStatus],
        reason: connected ? null : "device_offline",
        updated_at: createdAt
      };
      if (connected) online.push(id);
    }

    if (online.length !== targets.length) {
      return json({ ok: false, error: "offline_devices_in_allocate_batch" }, 400);
    }

    fresh.last_batch = {
      action_id: actionId,
      action: AOT_ALLOCATE_SERVER_ACTION,
      package: AOT_BATCH_PACKAGE,
      created_at: createdAt,
      expires_at: expiresAt,
      devices,
      telegram_chat_id: options.telegram_chat_id || null,
      telegram_notified: false
    };

    await this.writeFleet(fresh);

    const payloadTemplate = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      target_device_ids: online,
      action_id: actionId,
      action: "PREPARE_ALLOCATE_SERVER",
      package: AOT_BATCH_PACKAGE,
      expires_at: expiresAt
    };

    for (const id of online) {
      const payload = {
        ...payloadTemplate,
        allocation: options.allocationMap ? options.allocationMap[id] : undefined
      };
      const sentCount = this.sendPayload(id, payload);
      if (sentCount === 0 && !this.env?.TEST_ENV) {
        devices[id].status = "FAILED";
        devices[id].history.push("FAILED");
        devices[id].reason = "websocket_send_failed";
      }
    }

    if (record && typeof record === "object") {
      record.last_batch = fresh.last_batch;
    }
    await this.writeFleet(fresh);

    return json({
      ok: true,
      batch: {
        action_id: actionId,
        devices: Object.values(fresh.last_batch.devices)
      }
    });
  }

  async dispatchFleetAck(request) {
    let body;
    try {
      body = await request.json();
    } catch (e) {
      return json({ ok: false, error: "invalid_json" }, 400);
    }

    const id = normalizeDeviceId(body?.device_id);
    const actionId = String(body?.action_id || "");
    const action = String(body?.batch_action || "");

    if (!id || !/^[A-Za-z0-9_-]{1,128}$/.test(actionId) || action !== AOT_ALLOCATE_SERVER_ACTION) {
      return json({ ok: false, error: "invalid_aot_ack" }, 400);
    }

    const record = await this.readFleet();
    const batch = record.last_batch;
    const device = batch?.devices?.[id];

    const allowed = new Set(["PREPARE_READY", "PREPARE_FAILED", "ACCEPTED", "ALLOCATED", "OPENED", "FAILED", "TIMEOUT", "DUPLICATE"]);
    if (!batch || batch.action_id !== actionId || batch.action !== action || !device || !allowed.has(body.status)) {
      return json({ ok: false, error: "invalid_batch_ack" }, 400);
    }

    const terminal = new Set(["FAILED", "TIMEOUT", "SKIPPED_OFFLINE", "OPENED"]);
    const ranks = {
      "PREPARE_SENT": 0,
      "PREPARE_READY": 0.5,
      "COMMIT_PENDING": 0.7,
      "COMMIT_SENT": 0.8,
      "ABORT_SENT": 0.8,
      "ACCEPTED": 1,
      "ALLOCATED": 1.5,
      "OPENED": 2,
      "PREPARE_FAILED": 8,
      "FAILED": 8,
      "TIMEOUT": 8,
      "SKIPPED_OFFLINE": 8
    };

    if (!terminal.has(device.status) && body.status !== "DUPLICATE") {
      const next = Date.now() >= batch.expires_at ? "TIMEOUT" : body.status;
      if ((ranks[next] || 0) > (ranks[device.status] || 0)) {
        device.status = next;
        if (!device.history.includes(next)) device.history.push(next);
        device.reason = ["FAILED", "PREPARE_FAILED", "TIMEOUT"].includes(next) ? String(body.reason || "worker_reported_failure").slice(0, 160) : null;
        device.executed = body.executed === true;
        device.updated_at = Date.now();

        const statuses = Object.values(batch.devices).map(d => d.status);
        const hasFailures = statuses.some(s => ["PREPARE_FAILED", "FAILED", "TIMEOUT", "SKIPPED_OFFLINE"].includes(s));
        const isPreparePhase = !batch.commit_decided && !statuses.some(s => ["COMMIT_PENDING", "COMMIT_SENT", "ALLOCATED", "OPENED"].includes(s));

        if (hasFailures && isPreparePhase && !batch.abort_sent) {
          batch.abort_sent = true;
          for (const [did, d] of Object.entries(batch.devices)) {
            if (!terminal.has(d.status) && d.status !== "ABORT_SENT" && d.status !== "PREPARE_FAILED") {
              this.sendPayload(did, {
                type: "aot_batch_action",
                protocol: AOT_HUB_PROTOCOL_VERSION,
                target_device_ids: [did],
                action_id: batch.action_id,
                expires_at: batch.expires_at,
                action: "ABORT_ALLOCATE_SERVER",
                package: AOT_BATCH_PACKAGE
              });
              d.status = "ABORT_SENT";
              if (!d.history.includes("ABORT_SENT")) d.history.push("ABORT_SENT");
              d.reason = "aborted_due_to_peer_failure";
            }
          }
        } else if (isPreparePhase && statuses.every(s => s === "PREPARE_READY" || terminal.has(s) || s === "DUPLICATE") && !batch.commit_decided) {
          batch.commit_decided = true;
          batch.commit_sent = true;
          for (const [did, d] of Object.entries(batch.devices)) {
            if (d.status === "PREPARE_READY") {
              d.status = "COMMIT_SENT";
              if (!d.history.includes("COMMIT_SENT")) d.history.push("COMMIT_SENT");
              this.sendPayload(did, {
                type: "aot_batch_action",
                protocol: AOT_HUB_PROTOCOL_VERSION,
                target_device_ids: [did],
                action_id: batch.action_id,
                expires_at: batch.expires_at,
                action: "COMMIT_ALLOCATE_SERVER",
                package: AOT_BATCH_PACKAGE
              });
            }
          }
        }

        if (batch.telegram_chat_id && !batch.telegram_notified) {
          const allTerminal = Object.values(batch.devices).every(d => terminal.has(d.status) || d.status === "DUPLICATE" || d.status === "PREPARE_FAILED" || d.status === "ABORT_SENT" || d.status === "FAILED");
          if (allTerminal) {
            await this.notifyTelegramPhanserver(batch);
            batch.telegram_notified = true;
          }
        }

        await this.writeFleet(record);
      }
    }
    return json({ ok: true, action_id: actionId, device_id: id, status: device.status });
  }

  async notifyTelegramPhanserver(batch) {
    if (!this.env?.TELEGRAM_BOT_TOKEN || !batch.telegram_chat_id) return true;
    const escapeHtml = (str) => String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    let msg = "<b>KẾT QUẢ PHÂN SERVER</b>\n";
    for (const d of Object.values(batch.devices)) {
      const safeId = escapeHtml(d.device_id);
      const safeHistory = d.history.map(escapeHtml).join(' -> ');
      const safeReason = d.reason ? '— ' + escapeHtml(d.reason) : '';
      msg += `\n<b>${safeId}</b>: ${safeHistory} ${safeReason}`;
    }
    try {
      const res = await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: batch.telegram_chat_id, text: msg, parse_mode: "HTML" })
      });
      return res.ok;
    } catch (e) {
      return false;
    }
  }
}

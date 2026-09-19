const AOT_ALLOCATE_SERVER_ACTION = "ALLOCATE_SERVER";
const AOT_ALLOCATE_SERVER_CAPABILITY = "allocate_server_2pc";
const AOT_BATCH_PACKAGE = "com.tinh.vv.hi";
const AOT_BATCH_TTL_MS = 30000;
const AOT_HUB_PROTOCOL_VERSION = "fleet-batch-v1";
const PENDING_ALLOCATE_TTL_MS = 300000; // 5 minutes

export function escapeHtml(str) {
  return String(str ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

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

export function extractValidTailscaleIp(details) {
  const match = String(details || "").match(/(?<![0-9a-zA-Z.])\b100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b(?![0-9a-zA-Z./:])/);
  if (!match) return null;
  const octets = [Number(match[1]), Number(match[2]), Number(match[3])];
  if (octets.some((o) => o < 0 || o > 255 || isNaN(o))) return null;
  return match[0];
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
        pending_allocates: {},
        delta_updates: {},
        pending_actions: {}
      };
    }
    if (!record.devices) record.devices = {};
    if (!record.pending_allocates) record.pending_allocates = {};
    if (!record.delta_updates) record.delta_updates = {};
    if (!record.pending_actions) record.pending_actions = {};
    if (!record.moveacc_actions) record.moveacc_actions = {};
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
    const reportedTsIp = extractValidTailscaleIp(body?.metrics?.tailscale_ip);
    if (reportedTsIp) {
      existing.tailscale_ip = reportedTsIp;
    } else if (body?.metrics && body.metrics.tailscale_connected === false) {
      existing.tailscale_ip = null;
    }
    record.devices[deviceId] = existing;

    const now = Date.now();
    const actions = record.pending_actions[deviceId] || [];
    const handleExpiredAction = (item, reason) => {
      item.acknowledged_at = now;
      item.expired = true;
      if (item.action === "CONTROL_TAILSCALE" && !item.timeout_alerted) {
        item.timeout_alerted = true;
        const act = record.tailscale_actions?.[item.action_id];
        if (act && act.devices?.[deviceId] && act.devices[deviceId].status === "QUEUED") {
          act.devices[deviceId].status = "FAILED";
          act.devices[deviceId].reason = reason;
          act.devices[deviceId].updated_at = now;
        }
        const chatId = act?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
        if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
          const mode = (act?.mode || item.mode || "on").toUpperCase();
          const msg = `⚠️ <b>ĐIỀU KHIỂN TAILSCALE QUÁ THỜI GIAN (TIMEOUT)</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚙️ Chế độ: <b>${mode}</b>\n⚠️ Thiết bị không phản hồi kết quả sau 90 giây. Vui lòng kiểm tra lại thiết bị hoặc kết nối mạng.`;
          fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
          }).catch(() => {});
        }
      } else if (item.action === "TAB_LIST" && !item.timeout_alerted) {
        item.timeout_alerted = true;
        const act = record.tablist_actions?.[item.action_id];
        if (act && act.devices?.[deviceId] && act.devices[deviceId].status === "QUEUED") {
          act.devices[deviceId].status = "FAILED";
          act.devices[deviceId].reason = reason;
          act.devices[deviceId].updated_at = now;
        }
        const chatId = act?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
        if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
          const devName = (act?.device_id || deviceId || "M77").toUpperCase();
          const msg = `❌ <b>LẤY TAB LIST THẤT BẠI (TIMEOUT)</b>\n📱 Thiết bị: <code>${escapeHtml(devName)}</code>\n⚠️ Thiết bị không phản hồi sau 60 giây. Vui lòng kiểm tra kết nối mạng hoặc Agent.`;
          fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
          }).catch(() => {});
        }
      }
    };

    for (const item of actions) {
      if (!item.acknowledged_at) {
        if (item.action === "TAB_LIST" && ((item.delivered_at && now - item.delivered_at > 60000) || (!item.delivered_at && item.created_at && now - item.created_at > 60000))) {
          handleExpiredAction(item, "Timeout 60s không nhận được phản hồi từ thiết bị");
        } else if (item.delivered_at && now - item.delivered_at > 90000) {
          handleExpiredAction(item, "Timeout 90s không nhận được phản hồi từ thiết bị");
        }
      }
    }
    const command = actions.find(item => !item.acknowledged_at) || null;
    if (command) {
      command.delivered_at = command.delivered_at || now;
      command.delivery_count = (command.delivery_count || 0) + 1;
      if (command.delivery_count > 3 && now - command.delivered_at > 60000) {
        handleExpiredAction(command, "Quá 3 lần thử lại không nhận được phản hồi từ thiết bị");
      }
    }
    await this.writeFleet(record);
    return json({ ok: true, device_id: deviceId, command });
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
        capabilities: d.capabilities || [],
        tailscale_ip: d.tailscale_ip || null,
        metrics: d.metrics || null
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
    if (this.ctx?.getWebSockets && this.ctx.getWebSockets(`device:fleet:${id}`).length > 0) return true;
    if (this.aotLive.has(id)) return true;
    return Boolean(recordDevice && recordDevice.online && (Date.now() - (recordDevice.last_seen || 0) < 180000));
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

    if (body.kind === "update_delta") {
      return this.queueDeltaUpdate(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        body.selection || "all",
        { telegram_chat_id: body.telegram_chat_id, target_pkg: body.target_pkg || null }
      );
    }

    if (body.kind === "backup_app") {
      return this.queueAppBackup(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        body.package || "taskbar",
        body.release_tag || "Backup",
        { telegram_chat_id: body.telegram_chat_id, mode: body.mode || "full", github_token: body.github_token }
      );
    }

    if (body.kind === "upgrade_agent") {
      return this.queueAgentUpgrade(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        { telegram_chat_id: body.telegram_chat_id }
      );
    }

    if (body.kind === "enable_dev_mode") {
      return this.queueDevMode(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        { telegram_chat_id: body.telegram_chat_id }
      );
    }

    if (body.kind === "set_config") {
      return this.queueSetConfig(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        body.config || {},
        { telegram_chat_id: body.telegram_chat_id }
      );
    }

    if (body.kind === "write_script") {
      return this.queueWriteScript(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        body.filename || "script.lua",
        body.content || "",
        { telegram_chat_id: body.telegram_chat_id, raw_source: body.raw_source }
      );
    }

    if (body.kind === "clean_script") {
      return this.queueCleanScript(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        body.filename || "all",
        { telegram_chat_id: body.telegram_chat_id }
      );
    }

    if (body.kind === "control_tailscale") {
      return this.queueControlTailscale(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        body.mode || "on",
        { telegram_chat_id: body.telegram_chat_id }
      );
    }

    if (body.kind === "check_ban") {
      return this.queueCheckBan(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        body.target || "all",
        { telegram_chat_id: body.telegram_chat_id }
      );
    }

    if (body.kind === "add_acc") {
      return this.queueAddAcc(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        body.m_code,
        body.lines,
        { telegram_chat_id: body.telegram_chat_id, sync_drive: body.sync_drive !== false }
      );
    }

    if (body.kind === "del_acc") {
      return this.queueDelAcc(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        body.m_code || "all",
        body.usernames || body.lines || [],
        { telegram_chat_id: body.telegram_chat_id, sync_drive: body.sync_drive !== false }
      );
    }

    if (body.kind === "move_acc") {
      const sourceM = body.source_m || body.source || body.src;
      const targetM = body.target_m || body.dest || body.dst || body.target;
      return this.queueMoveAcc(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        sourceM,
        targetM,
        body.count || 1,
        { telegram_chat_id: body.telegram_chat_id, sync_drive: body.sync_drive !== false }
      );
    }

    if (body.kind === "tab_list") {
      return this.queueTabList(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        { telegram_chat_id: body.telegram_chat_id }
      );
    }

    if (body.kind === "auto_login") {
      return this.queueAutoLogin(
        record,
        Array.isArray(body.target_device_ids) ? body.target_device_ids : [],
        { telegram_chat_id: body.telegram_chat_id }
      );
    }

    return json({ ok: false, error: "unsupported_fleet_control" }, 400);
  }

  async queueDeltaUpdate(record, requestedTargetIds, selection = "all", options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    const targetPkg = options.target_pkg || null;
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      if (!(device.capabilities || []).includes("update_delta")) {
        return json({ ok: false, error: "missing_update_delta_capability", device_id: id }, 409);
      }
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `delta-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "UPDATE_DELTA",
      selection: selection,
      target_pkg: targetPkg,
      target_device_ids: targets,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.delta_updates[actionId] = { action_id: actionId, action: "UPDATE_DELTA", target_pkg: targetPkg, created_at: Date.now(), devices, telegram_chat_id: options.telegram_chat_id };
    await this.writeFleet(fresh);
    return json({ ok: true, update: { action_id: actionId, target_pkg: targetPkg, devices: Object.values(devices) } });
  }

  async acknowledgeDeltaUpdate(record, body, deviceId, actionId) {
    const update = record.delta_updates?.[actionId];
    const device = update?.devices?.[deviceId];
    const status = String(body.status || "");
    if (!update || !device || !["OPENED", "FAILED"].includes(status)) {
      return json({ ok: false, error: "invalid_delta_ack" }, 400);
    }
    if (device.status === "QUEUED") {
      device.status = status;
      device.executed = body.executed === true;
      device.reason = status === "FAILED" ? String(body.reason || "device_failed").slice(0, 160) : null;
      device.updated_at = Date.now();
      for (const command of record.pending_actions?.[deviceId] || []) {
        if (command.action_id === actionId) command.acknowledged_at = Date.now();
      }
      await this.writeFleet(record);

      const chatId = update?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
      if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
        const isSuccess = status === "OPENED";
        const targetPkgText = update?.target_pkg ? `\n🎯 Ứng dụng đích: <code>${update.target_pkg}</code>` : "";
        const msg = isSuccess
          ? `✅ <b>RESTORE / CÀI ĐẶT THÀNH CÔNG!</b>\n📱 Thiết bị: <code>${deviceId}</code>${targetPkgText}\n📦 Đã hoàn tất cài đặt / khôi phục dữ liệu.`
          : `❌ <b>RESTORE / CÀI ĐẶT THẤT BẠI</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${body.reason || "Lỗi thiết bị"}`;
        try {
          await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
          });
        } catch (e) {}
      }
    }
    return json({ ok: true, action_id: actionId, device_id: deviceId, status: device.status });
  }

  async queueAppBackup(record, requestedTargetIds, pkg = "taskbar", tag = "Backup", options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    const mode = options.mode || "full";
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `backup-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "BACKUP_APP",
      package: pkg,
      mode: mode,
      release_tag: tag,
      github_token: options.github_token || "",
      target_device_ids: targets,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.app_backups = fresh.app_backups || {};
    fresh.app_backups[actionId] = { action_id: actionId, action: "BACKUP_APP", package: pkg, mode: mode, release_tag: tag, created_at: Date.now(), devices, telegram_chat_id: options.telegram_chat_id };
    await this.writeFleet(fresh);
    return json({ ok: true, backup: { action_id: actionId, package: pkg, mode: mode, devices: Object.values(devices) } });
  }

  async acknowledgeAppBackup(record, body, deviceId, actionId) {
    const backup = record.app_backups?.[actionId];
    const device = backup?.devices?.[deviceId];
    const status = String(body.status || "");
    if (device && device.status === "QUEUED") {
      device.status = status;
      device.executed = body.executed === true;
      device.reason = status === "FAILED" ? String(body.reason || "device_failed").slice(0, 160) : null;
      device.updated_at = Date.now();
    }
    for (const command of record.pending_actions?.[deviceId] || []) {
      if (command.action_id === actionId) command.acknowledged_at = Date.now();
    }
    await this.writeFleet(record);

    const chatId = backup?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
    if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
      const isSuccess = status === "OPENED" || status === "SUCCESS";
      const pkg = backup?.package || "app";
      const mode = backup?.mode || "full";
      const modeText = mode === "apk" ? "Chỉ APK" : (mode === "data" ? "Chỉ Data cấu hình" : "Đầy đủ APK + Data");
      const msg = isSuccess
        ? `✅ <b>SAO LƯU THÀNH CÔNG LÊN RELEASE!</b>\n📱 Thiết bị: <code>${deviceId}</code>\n📦 Ứng dụng: <code>${pkg}</code>\n⚙️ Chế độ: <b>${modeText}</b>\n🏷️ Tag: <b>${backup?.release_tag || "Backup"}</b>\n\n💡 Bạn có thể gõ <code>/apks</code> để xem file mới trong Release.`
        : `❌ <b>SAO LƯU THẤT BẠI</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${body.reason || "Lỗi thiết bị"}`;
      try {
        await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
        });
      } catch (e) {}
    }

    return json({ ok: true, action_id: actionId, device_id: deviceId, status: status || "SUCCESS" });
  }

  async queueAgentUpgrade(record, requestedTargetIds, options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `upgrade-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "UPGRADE_AGENT",
      target_device_ids: targets,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.agent_upgrades = fresh.agent_upgrades || {};
    fresh.agent_upgrades[actionId] = { action_id: actionId, action: "UPGRADE_AGENT", created_at: Date.now(), devices, telegram_chat_id: options.telegram_chat_id };
    await this.writeFleet(fresh);
    return json({ ok: true, upgrade: { action_id: actionId, devices: Object.values(devices) } });
  }

  async acknowledgeAgentUpgrade(record, body, deviceId, actionId) {
    const upgrade = record.agent_upgrades?.[actionId];
    const device = upgrade?.devices?.[deviceId];
    const status = String(body.status || "");
    if (device && device.status === "QUEUED") {
      device.status = status;
      device.executed = body.executed === true;
      device.reason = status === "FAILED" ? String(body.reason || "device_failed").slice(0, 160) : null;
      device.updated_at = Date.now();
    }
    for (const command of record.pending_actions?.[deviceId] || []) {
      if (command.action_id === actionId) command.acknowledged_at = Date.now();
    }
    await this.writeFleet(record);

    const chatId = upgrade?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
    if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
      const isSuccess = status === "OPENED" || status === "SUCCESS";
      const msg = isSuccess
        ? `🚀 <b>TỰ ĐỘNG NÂNG CẤP THÀNH CÔNG!</b>\n📱 Thiết bị: <code>${deviceId}</code>\n📦 Agent đã kéo mã nguồn mới nhất từ GitHub và tự khởi động lại ngầm.`
        : `❌ <b>NÂNG CẤP THẤT BẠI</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${body.reason || "Lỗi thiết bị"}`;
      try {
        await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
        });
      } catch (e) {}
    }

    return json({ ok: true, action_id: actionId, device_id: deviceId, status: status || "SUCCESS" });
  }

  async queueDevMode(record, requestedTargetIds, options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `devmode-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "ENABLE_DEV_MODE",
      target_device_ids: targets,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.dev_mode_actions = fresh.dev_mode_actions || {};
    fresh.dev_mode_actions[actionId] = { action_id: actionId, action: "ENABLE_DEV_MODE", created_at: Date.now(), devices, telegram_chat_id: options.telegram_chat_id };
    await this.writeFleet(fresh);
    return json({ ok: true, dev_mode: { action_id: actionId, devices: Object.values(devices) } });
  }

  async queueSetConfig(record, requestedTargetIds, config = {}, options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `setcfg-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "SET_CONFIG",
      config: config,
      target_device_ids: targets,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.set_config_actions = fresh.set_config_actions || {};
    fresh.set_config_actions[actionId] = { action_id: actionId, action: "SET_CONFIG", created_at: Date.now(), devices, telegram_chat_id: options.telegram_chat_id };
    await this.writeFleet(fresh);
    return json({ ok: true, set_config: { action_id: actionId, devices: Object.values(devices) } });
  }

  async acknowledgeSetConfig(record, body, deviceId, actionId) {
    const setAction = record.set_config_actions?.[actionId];
    const device = setAction?.devices?.[deviceId];
    const status = String(body.status || "");
    if (device && device.status === "QUEUED") {
      device.status = status;
      device.reason = body.reason || null;
      device.updated_at = Date.now();
      await this.writeFleet(record);
    }
    return json({ ok: true, action_id: actionId, device_id: deviceId, status: status || "SUCCESS" });
  }

  async acknowledgeDevMode(record, body, deviceId, actionId) {
    const devAction = record.dev_mode_actions?.[actionId];
    const device = devAction?.devices?.[deviceId];
    const status = String(body.status || "");
    if (device && device.status === "QUEUED") {
      device.status = status;
      device.executed = body.executed === true;
      device.reason = status === "FAILED" ? String(body.reason || "device_failed").slice(0, 160) : null;
      device.updated_at = Date.now();
    }
    for (const command of record.pending_actions?.[deviceId] || []) {
      if (command.action_id === actionId) command.acknowledged_at = Date.now();
    }
    await this.writeFleet(record);

    const chatId = devAction?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
    if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
      const isSuccess = status === "OPENED" || status === "SUCCESS";
      const msg = isSuccess
        ? `⚙️ <b>ĐÃ BẬT TÙY CHỌN NHÀ PHÁT TRIỂN & CẤU HÌNH THÀNH CÔNG!</b>\n📱 Thiết bị: <code>${deviceId}</code>\n✅ Kích hoạt Developer Options & ADB\n✅ Buộc ứng dụng trên bộ nhớ ngoài\n✅ Cho phép thay đổi kích thước hoạt động\n✅ Bật cửa sổ dạng tự do\n✅ Buộc chạy chế độ máy tính\n📐 Đã chỉnh Smallest Width về chuẩn <b>700 dp</b>.`
        : `❌ <b>BẬT TÙY CHỌN NHÀ PHÁT TRIỂN THẤT BẠI</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${body.reason || "Lỗi thiết bị"}`;
      try {
        await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
        });
      } catch (e) {}
    }

    return json({ ok: true, action_id: actionId, device_id: deviceId, status: status || "SUCCESS" });
  }

  async queueWriteScript(record, requestedTargetIds, filename = "sae", content = "", options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `script-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "WRITE_SCRIPT",
      filename: filename,
      content: content,
      raw_source: options.raw_source || "",
      target_device_ids: targets,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.script_actions = fresh.script_actions || {};
    fresh.script_actions[actionId] = {
      action_id: actionId,
      action: "WRITE_SCRIPT",
      filename: filename,
      created_at: Date.now(),
      devices,
      telegram_chat_id: options.telegram_chat_id
    };
    await this.writeFleet(fresh);
    return json({ ok: true, script: { action_id: actionId, filename: filename, devices: Object.values(devices) } });
  }

  async acknowledgeWriteScript(record, body, deviceId, actionId) {
    const act = record.script_actions?.[actionId];
    const device = act?.devices?.[deviceId];
    const status = String(body.status || "");
    if (device && device.status === "QUEUED") {
      device.status = status;
      device.executed = body.executed === true;
      device.reason = status === "FAILED" ? String(body.reason || "device_failed").slice(0, 160) : null;
      device.updated_at = Date.now();
    }
    for (const command of record.pending_actions?.[deviceId] || []) {
      if (command.action_id === actionId) command.acknowledged_at = Date.now();
    }
    await this.writeFleet(record);

    const chatId = act?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
    if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
      const isSuccess = status === "OPENED" || status === "SUCCESS";
      const filename = act?.filename || "script";
      const msg = isSuccess
        ? `✅ <b>NẠP SCRIPT THÀNH CÔNG!</b>\n📱 Thiết bị: <code>${deviceId}</code>\n📄 File: <code>${filename}</code>\n📁 Thư mục: <code>/storage/emulated/0/Delta/Autoexecute/</code>\n🎮 Delta Executor sẽ tự động chạy script khi bạn mở Roblox!`
        : `❌ <b>NẠP SCRIPT THẤT BẠI</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${body.reason || "Lỗi ghi file"}`;
      try {
        await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
        });
      } catch (e) {}
    }

    return json({ ok: true, action_id: actionId, device_id: deviceId, status: status || "SUCCESS" });
  }

  async queueCleanScript(record, requestedTargetIds, filename = "all", options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `cleanscript-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "CLEAN_SCRIPT",
      filename: filename,
      target_device_ids: targets,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.script_actions = fresh.script_actions || {};
    fresh.script_actions[actionId] = {
      action_id: actionId,
      action: "CLEAN_SCRIPT",
      filename: filename,
      created_at: Date.now(),
      devices,
      telegram_chat_id: options.telegram_chat_id
    };
    await this.writeFleet(fresh);
    return json({ ok: true, clean: { action_id: actionId, filename: filename, devices: Object.values(devices) } });
  }

  async acknowledgeCleanScript(record, body, deviceId, actionId) {
    const act = record.script_actions?.[actionId];
    const device = act?.devices?.[deviceId];
    const status = String(body.status || "");
    if (device && device.status === "QUEUED") {
      device.status = status;
      device.executed = body.executed === true;
      device.reason = status === "FAILED" ? String(body.reason || "device_failed").slice(0, 160) : null;
      device.updated_at = Date.now();
    }
    for (const command of record.pending_actions?.[deviceId] || []) {
      if (command.action_id === actionId) command.acknowledged_at = Date.now();
    }
    await this.writeFleet(record);

    const chatId = act?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
    if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
      const isSuccess = status === "OPENED" || status === "SUCCESS";
      const filename = act?.filename || "all";
      const msg = isSuccess
        ? `🧹 <b>ĐÃ DỌN DẸP SCRIPT THÀNH CÔNG!</b>\n📱 Thiết bị: <code>${deviceId}</code>\n🎯 Đã xóa: <code>${filename}</code> khỏi <code>Delta/Autoexecute/</code>`
        : `❌ <b>DỌN DẸP SCRIPT THẤT BẠI</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${body.reason || "Lỗi xóa file"}`;
      try {
        await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
        });
      } catch (e) {}
    }

    return json({ ok: true, action_id: actionId, device_id: deviceId, status: status || "SUCCESS" });
  }

  async queueControlTailscale(record, requestedTargetIds, mode = "on", options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `tailscale-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const normalizedMode = String(mode).toLowerCase() === "off" ? "off" : (String(mode).toLowerCase() === "status" ? "status" : "on");
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "CONTROL_TAILSCALE",
      mode: normalizedMode,
      target_device_ids: targets,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.tailscale_actions = fresh.tailscale_actions || {};
    fresh.tailscale_actions[actionId] = {
      action_id: actionId,
      action: "CONTROL_TAILSCALE",
      mode: normalizedMode,
      created_at: Date.now(),
      devices,
      telegram_chat_id: options.telegram_chat_id
    };
    await this.writeFleet(fresh);
    return json({ ok: true, tailscale: { action_id: actionId, mode: normalizedMode, devices: Object.values(devices) } });
  }

  async acknowledgeTailscaleControl(record, body, deviceId, actionId) {
    const act = record.tailscale_actions?.[actionId];
    const device = act?.devices?.[deviceId];
    const status = String(body.status || "");
    const mode = act?.mode || "on";

    // Extract and strictly validate Tailscale CGNAT IP (100.x.y.z where octets <= 255)
    const tailscaleIp = extractValidTailscaleIp(body.details);

    // Strict success gating: mode 'on' requires valid IP and OPENED/SUCCESS status
    let isSuccess = status === "OPENED" || status === "SUCCESS";
    if (mode === "on") {
      isSuccess = isSuccess && Boolean(tailscaleIp);
    }

    if (device && device.status === "QUEUED") {
      device.status = isSuccess ? status : "FAILED";
      device.executed = isSuccess && body.executed === true;
      if (!isSuccess) {
        let reason = body.reason;
        if (!reason) {
          if (body.details === "TRIGGERED" || !tailscaleIp) {
            reason = "Timeout 12s không nhận được IP Tailscale (100.x.y.z)";
          } else {
            reason = body.details || "device_failed";
          }
        }
        device.reason = String(reason).slice(0, 160);
      } else {
        device.reason = null;
      }
      device.details = body.details ? String(body.details).slice(0, 200) : null;
      device.updated_at = Date.now();
    }
    if (record.devices?.[deviceId]) {
      if (isSuccess && tailscaleIp) {
        record.devices[deviceId].tailscale_ip = tailscaleIp;
      } else if (mode === "off" && isSuccess) {
        record.devices[deviceId].tailscale_ip = null;
      }
    }
    for (const command of record.pending_actions?.[deviceId] || []) {
      if (command.action_id === actionId) command.acknowledged_at = Date.now();
    }
    await this.writeFleet(record);

    const chatId = act?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
    if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
      const escapeHtml = (str) => String(str || "").replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      let msg = "";

      if (mode === "on") {
        if (isSuccess && tailscaleIp) {
          msg = `🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: ${tailscaleIp}</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚙️ Chế độ: <b>ON</b>\n🔒 Mạng nội bộ Tailscale đã sẵn sàng.`;
        } else {
          let failReason = body.reason;
          if (!failReason) {
            if (body.details === "TRIGGERED" || !tailscaleIp) {
              failReason = "Timeout 12s không nhận được IP Tailscale (100.x.y.z)";
            } else {
              failReason = body.details || "Không thể kết nối Tailscale";
            }
          }
          msg = `❌ <b>BẬT TAILSCALE THẤT BẠI: ${escapeHtml(failReason)}</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${escapeHtml(failReason)}`;
        }
      } else if (mode === "status") {
        const isConnected = isSuccess && Boolean(tailscaleIp);
        if (isConnected) {
          msg = `🌐 <b>TRẠNG THÁI TAILSCALE: CONNECTED (${tailscaleIp})</b>\n📱 Thiết bị: <code>${deviceId}</code>\n📶 Trạng thái: <b>CONNECTED (${tailscaleIp})</b>\n🔒 Mạng nội bộ Tailscale đang hoạt động.`;
        } else {
          const rawDetail = body.details || body.reason || "Chưa kết nối";
          msg = `⚠️ <b>TRẠNG THÁI TAILSCALE: DISCONNECTED</b>\n📱 Thiết bị: <code>${deviceId}</code>\n📶 Trạng thái: <b>DISCONNECTED</b>\n📋 Chi tiết: <code>${escapeHtml(rawDetail)}</code>`;
        }
      } else if (mode === "off") {
        if (isSuccess) {
          msg = `🌐 <b>ĐÃ TẮT TAILSCALE THÀNH CÔNG!</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚙️ Chế độ: <b>OFF</b>\n📶 Trạng thái: <b>DISCONNECTED</b>`;
        } else {
          const failReason = body.reason || "Lỗi thiết bị";
          msg = `❌ <b>TẮT TAILSCALE THẤT BẠI: ${escapeHtml(failReason)}</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${escapeHtml(failReason)}`;
        }
      } else {
        msg = isSuccess
          ? `🌐 <b>ĐÃ ${mode.toUpperCase()} TAILSCALE THÀNH CÔNG!</b>\n📱 Thiết bị: <code>${deviceId}</code>`
          : `❌ <b>${mode.toUpperCase()} TAILSCALE THẤT BẠI</b>\n📱 Thiết bị: <code>${deviceId}</code>\n⚠️ Lý do: ${escapeHtml(body.reason || "Lỗi thiết bị")}`;
      }

      try {
        await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
        });
      } catch (e) {}
    }

    const returnStatus = (mode === "on" && !isSuccess) ? "FAILED" : (status || "SUCCESS");
    return json({ ok: true, action_id: actionId, device_id: deviceId, status: returnStatus });
  }

  async queueCheckBan(record, requestedTargetIds, target = "all", options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `checkban-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "CHECK_BAN",
      target: String(target || "all"),
      target_device_ids: targets,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.checkban_actions = fresh.checkban_actions || {};
    fresh.checkban_actions[actionId] = {
      action_id: actionId,
      action: "CHECK_BAN",
      target: String(target || "all"),
      created_at: Date.now(),
      devices,
      telegram_chat_id: options.telegram_chat_id
    };
    await this.writeFleet(fresh);
    return json({ ok: true, checkban: { action_id: actionId, target: target, devices: Object.values(devices) } });
  }

  async acknowledgeCheckBan(record, body, deviceId, actionId) {
    const act = record.checkban_actions?.[actionId];
    const device = act?.devices?.[deviceId];
    const status = String(body.status || "");
    if (device && device.status === "QUEUED") {
      device.status = status;
      device.executed = body.executed === true;
      device.reason = status === "FAILED" ? String(body.reason || "checkban_failed").slice(0, 160) : null;
      device.details = body.details ? String(body.details) : null;
      device.updated_at = Date.now();
    }
    for (const command of record.pending_actions?.[deviceId] || []) {
      if (command.action_id === actionId) command.acknowledged_at = Date.now();
    }
    await this.writeFleet(record);

    const chatId = act?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
    if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
      const escapeHtml = (str) => String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const isSuccess = status === "OPENED" || status === "SUCCESS";
      let detailsObj = null;
      if (body.details) {
        try {
          detailsObj = typeof body.details === "string" ? JSON.parse(body.details) : body.details;
        } catch (e) {}
      }

      let msg = "";
      if (isSuccess && detailsObj) {
        const tgt = escapeHtml(detailsObj.target || act?.target || "ALL");
        const total = detailsObj.total ?? 0;
        const live = detailsObj.live ?? 0;
        const banned = detailsObj.banned ?? 0;
        const faceCount = detailsObj.face_lock ?? 0;
        const captchaCount = detailsObj.captcha_lock ?? 0;
        const deadCount = detailsObj.dead ?? 0;
        const errCount = detailsObj.error ?? 0;
        const bannedList = Array.isArray(detailsObj.banned_list) ? detailsObj.banned_list : [];
        const faceList = Array.isArray(detailsObj.face_lock_list) ? detailsObj.face_lock_list : [];
        const captchaList = Array.isArray(detailsObj.captcha_lock_list) ? detailsObj.captcha_lock_list : [];
        const deadList = Array.isArray(detailsObj.dead_list) ? detailsObj.dead_list : [];

        msg = `🛡️ <b>KẾT QUẢ CHECK BAN ROBLOX</b>\n`;
        msg += `📱 Thiết bị thực thi: <code>${escapeHtml(deviceId)}</code>\n`;
        msg += `🎯 Mục tiêu: <b>${tgt}</b>\n`;
        msg += `📊 Tổng: <b>${total}</b> | 🟢 Sống: <b>${live}</b> | 🔴 Bị Ban: <b>${banned}</b> | 👤 FaceID: <b>${faceCount}</b> | 🧩 Captcha: <b>${captchaCount}</b> | 💀 Dead: <b>${deadCount}</b>`;
        if (errCount > 0) msg += ` | ⚠️ Lỗi API: <b>${errCount}</b>`;
        msg += `\n`;

        if (total === 0) {
          msg += `\n⚠️ <b>Không tìm thấy tài khoản nào cho mục tiêu ${tgt} trong acc.txt!</b>`;
          if (detailsObj.message) {
            msg += `\n<i>${escapeHtml(detailsObj.message)}</i>`;
          }
        } else if (banned > 0 || faceCount > 0 || captchaCount > 0 || deadCount > 0) {
          if (banned > 0) {
            msg += `\n🔴 <b>Danh sách tài khoản bị Ban:</b>\n`;
            for (const u of bannedList) {
              msg += `• <code>${escapeHtml(u)}</code>\n`;
            }
          }
          if (faceCount > 0) {
            msg += `\n👤 <b>Tài khoản dính FaceID Lock:</b>\n`;
            for (const u of faceList) {
              msg += `• <code>${escapeHtml(u)}</code>\n`;
            }
          }
          if (captchaCount > 0) {
            msg += `\n🧩 <b>Tài khoản dính Captcha Lock:</b>\n`;
            for (const u of captchaList) {
              msg += `• <code>${escapeHtml(u)}</code>\n`;
            }
          }
          if (deadCount > 0) {
            msg += `\n💀 <b>Tài khoản Cookie chết / hết hạn:</b>\n`;
            for (const u of deadList) {
              msg += `• <code>${escapeHtml(u)}</code>\n`;
            }
          }
          if (detailsObj.clean_result) {
            const removed = detailsObj.clean_result.removed_from_acc ?? (banned + faceCount + captchaCount + deadCount);
            if (faceCount > 0 || captchaCount > 0 || deadCount > 0) {
              msg += `\n🧹 Đã tự động gỡ <b>${removed}</b> acc lỗi khỏi <code>acc.txt</code> & lưu trữ phân loại an toàn.`;
            } else {
              msg += `\n🧹 Đã tự động gỡ <b>${removed}</b> acc khỏi <code>acc.txt</code> & lưu trữ vào <code>acc_bi_ban.txt</code>.`;
            }
          }
        } else if (errCount > 0) {
          msg += `\n⚠️ Không phát hiện tài khoản bị ban, nhưng có <b>${errCount}</b> tài khoản gặp lỗi tra cứu API.`;
        } else {
          msg += `\n✅ <b>Tất cả tài khoản đều HOẠT ĐỘNG TỐT (100% LIVE)!</b> Không phát hiện tài khoản nào bị ban.`;
        }

        if (detailsObj.replace_result && detailsObj.replace_result.replaced_count > 0) {
          const replaced = detailsObj.replace_result.replaced_count;
          let remaining = detailsObj.replace_result.remaining_reserve_count;
          if (remaining === undefined && detailsObj.replace_result.by_section) {
            const sections = Object.values(detailsObj.replace_result.by_section);
            if (sections.length > 0) {
              remaining = sections[sections.length - 1]?.remaining_reserve_count;
            }
          }
          let repMsg = `\n🔄 <b>Nạp bù dự phòng</b>: Đã tự động nạp <b>${replaced}</b> acc từ kho dự trữ vào máy`;
          if (remaining !== undefined && remaining !== null) {
            repMsg += ` (Kho còn lại: <b>${remaining}</b>)`;
          }
          repMsg += `.`;
          msg += repMsg;
        }

        const syncResult = detailsObj.sync_result || detailsObj.sync;
        if (syncResult) {
          if (syncResult.error) {
            msg += `\n⚠️ Google Drive sync lỗi: <code>${escapeHtml(syncResult.error)}</code>`;
          } else {
            msg += `\n☁️ <b>Google Drive</b>: Đã đồng bộ an toàn (Bảo toàn File ID gốc theo Rule 34).`;
          }
        }
      } else if (isSuccess) {
        msg = `🛡️ <b>ĐÃ HOÀN TẤT QUÉT CHECK BAN</b>\n📱 Thiết bị: <code>${escapeHtml(deviceId)}</code>\nTrạng thái: Hoàn thành thành công.`;
      } else {
        msg = `❌ <b>CHECK BAN THẤT BẠI</b>\n📱 Thiết bị: <code>${escapeHtml(deviceId)}</code>\n⚠️ Lý do: ${escapeHtml(body.reason || "Lỗi kiểm tra ban")}`;
      }

      try {
        await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
        });
      } catch (e) {}

      // Tự động gửi các tệp .txt phân loại (Live, FaceID, Captcha, Dead, Banned)
      if (detailsObj && detailsObj.category_entries && typeof detailsObj.category_entries === "object") {
        const catMap = detailsObj.category_entries;
        const tgtClean = String(detailsObj.target || act?.target || "fleet").replace(/[^a-zA-Z0-9_-]/g, "_");
        const docConfigs = [
          { key: "live", prefix: "Live", emoji: "🟢", label: "tài khoản LIVE" },
          { key: "face_lock", prefix: "FaceID", emoji: "👤", label: "tài khoản dính FaceID Lock" },
          { key: "captcha_lock", prefix: "Captcha", emoji: "🧩", label: "tài khoản dính Captcha Lock" },
          { key: "dead", prefix: "Dead", emoji: "💀", label: "tài khoản Cookie chết / hết hạn" },
          { key: "banned", prefix: "Banned", emoji: "🔴", label: "tài khoản Bị Ban" },
        ];

        for (const cfg of docConfigs) {
          const lines = Array.isArray(catMap[cfg.key]) ? catMap[cfg.key] : [];
          if (lines.length > 0) {
            const fileName = `${cfg.prefix}_${tgtClean}.txt`;
            const fileContent = lines.join("\n") + "\n";
            const caption = `${cfg.emoji} <b>Danh sách ${cfg.label}</b> (${lines.length} acc)`;
            try {
              if (typeof FormData !== "undefined" && typeof Blob !== "undefined") {
                const formData = new FormData();
                formData.append("chat_id", String(chatId));
                formData.append("document", new Blob([fileContent], { type: "text/plain;charset=utf-8" }), fileName);
                formData.append("caption", caption);
                formData.append("parse_mode", "HTML");
                await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendDocument`, {
                  method: "POST",
                  body: formData
                });
              }
            } catch (errDoc) {
              console.error(`[TELEGRAM_DOC] Lỗi gửi ${fileName}:`, errDoc);
            }
          }
        }
      }
    }

    return json({ ok: true, action_id: actionId, device_id: deviceId, status: status || "SUCCESS" });
  }

  async queueAddAcc(record, requestedTargetIds, mCode, lines, options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `addacc-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "ADD_ACC",
      m_code: String(mCode || "").toUpperCase(),
      lines: Array.isArray(lines) ? lines : [String(lines)],
      sync_drive: options.sync_drive !== false,
      target_device_ids: targets,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.addacc_actions = fresh.addacc_actions || {};
    fresh.addacc_actions[actionId] = {
      action_id: actionId,
      action: "ADD_ACC",
      m_code: String(mCode || "").toUpperCase(),
      created_at: Date.now(),
      devices,
      telegram_chat_id: options.telegram_chat_id
    };
    await this.writeFleet(fresh);
    return json({ ok: true, addacc: { action_id: actionId, m_code: mCode, devices: Object.values(devices) } });
  }

  async acknowledgeAddAcc(record, body, deviceId, actionId) {
    const act = record.addacc_actions?.[actionId];
    const device = act?.devices?.[deviceId];
    const status = String(body.status || "");
    if (device && device.status === "QUEUED") {
      device.status = status;
      device.executed = body.executed === true;
      device.reason = status === "FAILED" ? String(body.reason || "addacc_failed").slice(0, 160) : null;
      device.details = body.details ? String(body.details) : null;
      device.updated_at = Date.now();
    }
    for (const command of record.pending_actions?.[deviceId] || []) {
      if (command.action_id === actionId) command.acknowledged_at = Date.now();
    }
    await this.writeFleet(record);

    const chatId = act?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
    if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
      const escapeHtml = (str) => String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const isSuccess = status === "OPENED" || status === "SUCCESS";
      let detailsObj = null;
      if (body.details) {
        try {
          detailsObj = typeof body.details === "string" ? JSON.parse(body.details) : body.details;
        } catch (e) {}
      }

      let msg = "";
      if (isSuccess && detailsObj) {
        const addInfo = detailsObj.add || detailsObj;
        const syncInfo = detailsObj.sync || detailsObj.sync_result || {};
        const mCode = escapeHtml(addInfo.m_code || act?.m_code || "N/A");
        const addedCount = addInfo.added_count ?? 0;
        const cookiesAdded = addInfo.cookies_added ?? 0;

        msg = `➕ <b>THÊM TÀI KHOẢN THÀNH CÔNG!</b>\n`;
        msg += `📱 Thiết bị thực thi: <code>${escapeHtml(deviceId)}</code>\n`;
        msg += `🎯 Dàn máy: <b>${mCode}</b>\n`;
        msg += `✅ Đã thêm vào acc.txt: <b>${addedCount}</b> tài khoản\n`;
        if (cookiesAdded > 0) {
          msg += `🔑 Cookie lưu vào Data_Tong: <b>${cookiesAdded}</b>\n`;
        }
        if (syncInfo.error) {
          msg += `⚠️ Google Drive sync lỗi: <code>${escapeHtml(syncInfo.error)}</code>\n`;
        } else {
          msg += `☁️ <b>Google Drive</b>: Đã đồng bộ an toàn (Bảo toàn File ID gốc theo Rule 34).`;
        }
      } else if (isSuccess) {
        msg = `➕ <b>ĐÃ THÊM TÀI KHOẢN VÀO DÀN ${escapeHtml(act?.m_code || "")}</b>\n📱 Thiết bị: <code>${escapeHtml(deviceId)}</code>`;
      } else {
        msg = `❌ <b>THÊM TÀI KHOẢN THẤT BẠI</b>\n📱 Thiết bị: <code>${escapeHtml(deviceId)}</code>\n⚠️ Lý do: ${escapeHtml(body.reason || "Lỗi thêm acc")}`;
      }

      try {
        await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
        });
      } catch (e) {}
    }

    return json({ ok: true, action_id: actionId, device_id: deviceId, status: status || "SUCCESS" });
  }

  async queueDelAcc(record, requestedTargetIds, mCode, usernames, options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `delacc-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "DEL_ACC",
      m_code: String(mCode || "ALL").toUpperCase(),
      usernames: Array.isArray(usernames) ? usernames : [String(usernames)],
      sync_drive: options.sync_drive !== false,
      target_device_ids: targets,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.delacc_actions = fresh.delacc_actions || {};
    fresh.delacc_actions[actionId] = {
      action_id: actionId,
      action: "DEL_ACC",
      m_code: String(mCode || "ALL").toUpperCase(),
      usernames: Array.isArray(usernames) ? usernames : [String(usernames)],
      created_at: Date.now(),
      devices,
      telegram_chat_id: options.telegram_chat_id
    };
    await this.writeFleet(fresh);
    return json({ ok: true, delacc: { action_id: actionId, m_code: mCode, devices: Object.values(devices) } });
  }

  async acknowledgeDelAcc(record, body, deviceId, actionId) {
    const act = record.delacc_actions?.[actionId];
    const device = act?.devices?.[deviceId];
    const status = String(body.status || "");
    if (device && device.status === "QUEUED") {
      device.status = status;
      device.executed = body.executed === true;
      device.reason = status === "FAILED" ? String(body.reason || "delacc_failed").slice(0, 160) : null;
      device.details = body.details ? String(body.details) : null;
      device.updated_at = Date.now();
    }
    for (const command of record.pending_actions?.[deviceId] || []) {
      if (command.action_id === actionId) command.acknowledged_at = Date.now();
    }
    await this.writeFleet(record);

    const chatId = act?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
    if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
      const escapeHtml = (str) => String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const isSuccess = status === "OPENED" || status === "SUCCESS";
      let detailsObj = null;
      if (body.details) {
        try {
          detailsObj = typeof body.details === "string" ? JSON.parse(body.details) : body.details;
        } catch (e) {}
      }

      let msg = "";
      if (isSuccess && detailsObj) {
        const target = escapeHtml(detailsObj.target || act?.m_code || "ALL");
        const removedAcc = detailsObj.removed_from_acc ?? 0;
        const removedData = detailsObj.removed_from_data_tong ?? 0;
        const deletedUsers = Array.isArray(detailsObj.deleted_usernames) ? detailsObj.deleted_usernames : [];
        const syncInfo = detailsObj.sync_result || {};

        msg = `🗑️ <b>XÓA TÀI KHOẢN THÀNH CÔNG!</b>\n`;
        msg += `📱 Thiết bị thực thi: <code>${escapeHtml(deviceId)}</code>\n`;
        msg += `🎯 Mục tiêu: <b>${target}</b>\n`;
        msg += `❌ Đã xóa khỏi acc.txt: <b>${removedAcc}</b> tài khoản\n`;
        msg += `🔑 Đã xóa khỏi Data_Tong: <b>${removedData}</b> cookie\n`;
        if (deletedUsers.length > 0) {
          msg += `👤 Danh sách: <code>${escapeHtml(deletedUsers.join(", "))}</code>\n`;
        }
        if (syncInfo.error) {
          msg += `⚠️ Google Drive sync lỗi: <code>${escapeHtml(syncInfo.error)}</code>\n`;
        } else {
          msg += `☁️ <b>Google Drive</b>: Đã đồng bộ an toàn (Bảo toàn File ID gốc theo Rule 34).`;
        }
      } else if (isSuccess) {
        msg = `🗑️ <b>ĐÃ XÓA TÀI KHOẢN KHỎI DÀN ${escapeHtml(act?.m_code || "")}</b>\n📱 Thiết bị: <code>${escapeHtml(deviceId)}</code>`;
      } else {
        msg = `❌ <b>XÓA TÀI KHOẢN THẤT BẠI</b>\n📱 Thiết bị: <code>${escapeHtml(deviceId)}</code>\n⚠️ Lý do: ${escapeHtml(body.reason || "Lỗi xóa acc")}`;
      }

      try {
        await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
        });
      } catch (e) {}
    }

    return json({ ok: true, action_id: actionId, device_id: deviceId, status: status || "SUCCESS" });
  }

  async queueMoveAcc(record, requestedTargetIds, sourceM, targetM, count = 1, options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `moveacc-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const src = String(sourceM || "").toUpperCase();
    const dst = String(targetM || "").toUpperCase();
    const moveCount = Math.max(1, parseInt(count, 10) || 1);
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "MOVE_ACC",
      source_m: src,
      target_m: dst,
      source: src,
      dest: dst,
      count: moveCount,
      sync_drive: options.sync_drive !== false,
      target_device_ids: targets,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.moveacc_actions = fresh.moveacc_actions || {};
    fresh.moveacc_actions[actionId] = {
      action_id: actionId,
      action: "MOVE_ACC",
      source_m: src,
      target_m: dst,
      source: src,
      dest: dst,
      count: moveCount,
      created_at: Date.now(),
      devices,
      telegram_chat_id: options.telegram_chat_id
    };
    await this.writeFleet(fresh);
    return json({ ok: true, moveacc: { action_id: actionId, source_m: src, target_m: dst, count: moveCount, devices: Object.values(devices) } });
  }

  async acknowledgeMoveAcc(record, body, deviceId, actionId) {
    const act = record.moveacc_actions?.[actionId];
    const device = act?.devices?.[deviceId];
    const status = String(body.status || "");
    if (device && device.status === "QUEUED") {
      device.status = status;
      device.executed = body.executed === true;
      device.reason = status === "FAILED" ? String(body.reason || "moveacc_failed").slice(0, 160) : null;
      device.details = body.details ? String(body.details) : null;
      device.updated_at = Date.now();
    }
    for (const command of record.pending_actions?.[deviceId] || []) {
      if (command.action_id === actionId) command.acknowledged_at = Date.now();
    }
    await this.writeFleet(record);

    const chatId = act?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
    if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
      const escapeHtml = (str) => String(str ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      const isSuccess = status === "OPENED" || status === "SUCCESS";
      let detailsObj = null;
      if (body.details) {
        try {
          detailsObj = typeof body.details === "string" ? JSON.parse(body.details) : body.details;
        } catch (e) {}
      }

      let msg = "";
      if (isSuccess && detailsObj) {
        const src = escapeHtml(detailsObj.source_m || detailsObj.source || act?.source_m || act?.source || "N/A");
        const dst = escapeHtml(detailsObj.target_m || detailsObj.dest || act?.target_m || act?.dest || "N/A");
        const movedUsers = Array.isArray(detailsObj.moved_accounts)
          ? detailsObj.moved_accounts
          : (Array.isArray(detailsObj.moved_usernames) ? detailsObj.moved_usernames : []);
        const movedCount = detailsObj.count ?? detailsObj.moved_count ?? (movedUsers.length || act?.count || 1);
        const remainingSrc = detailsObj.source_remaining_count ?? detailsObj.remaining_source_count ?? 0;
        const currentDst = detailsObj.target_current_count ?? detailsObj.current_dest_count ?? 0;
        const syncInfo = detailsObj.sync_result || detailsObj.sync || {};

        msg = `🔄 <b>ĐIỀU CHUYỂN TÀI KHOẢN THÀNH CÔNG!</b>\n`;
        msg += `📱 Thiết bị thực thi: <code>${escapeHtml(deviceId)}</code>\n`;
        msg += `📤 Nguồn: <b>${src}</b> ➔ 📥 Đích: <b>${dst}</b>\n`;
        msg += `🎲 Đã chuyển ngẫu nhiên (<b>${movedCount}</b>):\n`;
        if (movedUsers.length > 0) {
          msg += movedUsers.map(u => `• <code>${escapeHtml(u)}</code>`).join("\n") + "\n";
        }
        msg += `\n📊 <b>Trạng thái sau điều chuyển:</b>\n`;
        msg += `• Còn lại ở <b>${src}</b>: <b>${remainingSrc}</b> tài khoản\n`;
        msg += `• Hiện có ở <b>${dst}</b>: <b>${currentDst}</b> tài khoản\n`;
        if (syncInfo.error) {
          msg += `⚠️ Google Drive sync lỗi: <code>${escapeHtml(syncInfo.error)}</code>`;
        } else {
          msg += `☁️ <b>Google Drive</b>: Đã đồng bộ an toàn (Bảo toàn File ID gốc theo Rule 34).`;
        }
      } else if (isSuccess) {
        msg = `🔄 <b>ĐÃ ĐIỀU CHUYỂN TÀI KHOẢN THÀNH CÔNG</b>\n📱 Thiết bị: <code>${escapeHtml(deviceId)}</code>\n📤 Nguồn: <b>${escapeHtml(act?.source_m || act?.source || "")}</b> ➔ 📥 Đích: <b>${escapeHtml(act?.target_m || act?.dest || "")}</b>`;
      } else {
        msg = `❌ <b>ĐIỀU CHUYỂN TÀI KHOẢN THẤT BẠI</b>\n📱 Thiết bị: <code>${escapeHtml(deviceId)}</code>\n⚠️ Lý do: ${escapeHtml(body.reason || "Lỗi điều chuyển tài khoản")}`;
      }

      try {
        await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
        });
      } catch (e) {}
    }

    return json({ ok: true, action_id: actionId, device_id: deviceId, status: status || "SUCCESS" });
  }

  async queueTabList(record, requestedTargetIds, options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `tablist-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "TAB_LIST",
      target_device_ids: targets,
      all_tabs: true,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      // Replace any existing un-delivered TAB_LIST command to avoid queue pileup on rapid invocations
      fresh.pending_actions[id] = fresh.pending_actions[id].filter(
        cmd => !(cmd.action === "TAB_LIST" && !cmd.delivered_at && !cmd.acknowledged_at)
      );
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.tablist_actions = fresh.tablist_actions || {};
    fresh.tablist_actions[actionId] = {
      action_id: actionId,
      action: "TAB_LIST",
      created_at: Date.now(),
      devices,
      device_id: targets[0],
      telegram_chat_id: options.telegram_chat_id
    };
    await this.writeFleet(fresh);
    return json({ ok: true, tablist: { action_id: actionId, devices: Object.values(devices) } });
  }

  async queueAutoLogin(record, requestedTargetIds, options = {}) {
    const fresh = await this.readFleet();
    const targets = [];
    const seen = new Set();
    for (const raw of requestedTargetIds) {
      const id = normalizeDeviceId(raw);
      const device = id && fresh.devices[id];
      if (!id || seen.has(id) || !device) return json({ ok: false, error: "invalid_batch_target" }, 400);
      if (!this.isDeviceOnline(id, device)) return json({ ok: false, error: "offline_device", device_id: id }, 409);
      seen.add(id);
      targets.push(id);
    }
    if (!targets.length) return json({ ok: false, error: "invalid_batch_targets" }, 400);

    const actionId = `autologin-${Date.now()}-${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
    const command = {
      type: "aot_batch_action",
      protocol: AOT_HUB_PROTOCOL_VERSION,
      action_id: actionId,
      action: "AUTO_LOGIN",
      target_device_ids: targets,
      created_at: Date.now()
    };
    const devices = {};
    for (const id of targets) {
      fresh.pending_actions[id] = fresh.pending_actions[id] || [];
      fresh.pending_actions[id] = fresh.pending_actions[id].filter(
        cmd => !(cmd.action === "AUTO_LOGIN" && !cmd.delivered_at && !cmd.acknowledged_at)
      );
      fresh.pending_actions[id].push({ ...command, target_device_ids: [id] });
      devices[id] = { device_id: id, status: "QUEUED", updated_at: Date.now() };
    }
    fresh.autologin_actions = fresh.autologin_actions || {};
    fresh.autologin_actions[actionId] = {
      action_id: actionId,
      action: "AUTO_LOGIN",
      created_at: Date.now(),
      devices,
      device_id: targets[0],
      telegram_chat_id: options.telegram_chat_id
    };
    await this.writeFleet(fresh);
    return json({ ok: true, auto_login: { action_id: actionId, devices: Object.values(devices) } });
  }

  async acknowledgeTabList(record, body, deviceId, actionId) {
    const act = record.tablist_actions?.[actionId];
    const device = act?.devices?.[deviceId];
    const status = String(body.status || "");
    const isSuccess = status === "OPENED" || status === "SUCCESS";

    if (device && device.status === "QUEUED") {
      device.status = isSuccess ? status : "FAILED";
      device.executed = isSuccess && body.executed === true;
      device.reason = status === "FAILED" ? String(body.reason || "tablist_failed").slice(0, 160) : null;
      device.details = body.details ? String(body.details) : null;
      device.updated_at = Date.now();
    }
    for (const command of record.pending_actions?.[deviceId] || []) {
      if (command.action_id === actionId) command.acknowledged_at = Date.now();
    }
    await this.writeFleet(record);

    const chatId = act?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
    if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
      let detailsObj = null;
      let parseFailed = false;
      if (body.details) {
        if (typeof body.details === "string") {
          try {
            detailsObj = JSON.parse(body.details);
          } catch (e) {
            parseFailed = true;
          }
        } else if (typeof body.details === "object" && body.details !== null) {
          detailsObj = body.details;
        } else {
          parseFailed = true;
        }
      }

      let msg = "";
      const devName = (act?.device_id || deviceId || "M77").toUpperCase();
      if (isSuccess && parseFailed) {
        msg = `⚠️ <b>Tab List — ${escapeHtml(devName)}</b>\n(Dữ liệu tab phản hồi không đúng định dạng)`;
      } else if (isSuccess && detailsObj) {
        const rawTabs = Array.isArray(detailsObj.tabs) ? detailsObj.tabs : (Array.isArray(detailsObj) ? detailsObj : []);
        const tabs = rawTabs.filter(t => t && typeof t === "object" && !Array.isArray(t));
        msg = `📱 <b>Tab List — ${escapeHtml(devName)}</b>\n`;
        if (tabs.length === 0) {
          msg += `(Không có tab Roblox nào đang chạy)`;
        } else {
          // Strictly sort tabs ascending by tab number
          const sortedTabs = tabs.slice().sort((a, b) => {
            const ta = Number(a?.tab ?? a?.tab_index ?? a?.index ?? 0) || 0;
            const tb = Number(b?.tab ?? b?.tab_index ?? b?.index ?? 0) || 0;
            return ta - tb;
          });
          const lines = [];
          for (let i = 0; i < sortedTabs.length; i++) {
            const t = sortedTabs[i];
            const rawTabNum = t?.tab ?? t?.tab_index ?? t?.index ?? (i + 1);
            const tabNum = escapeHtml(String(rawTabNum));
            let rawU = "";
            if (typeof t?.username === "string") {
              rawU = t.username.trim();
            } else if (typeof t?.username === "number") {
              rawU = String(t.username);
            }
            const isUnknown = !rawU ||
              rawU === "❓" ||
              rawU.startsWith("❓") ||
              rawU.toLowerCase() === "unknown" ||
              rawU.toLowerCase() === "none" ||
              rawU.toLowerCase() === "null" ||
              rawU.toLowerCase() === "undefined" ||
              rawU.toLowerCase() === "guest" ||
              rawU.toLowerCase() === "default";
            const isBanned = t?.is_banned === true || 
                             ["BANNED", "BAN", "BANED"].includes(String(t?.status || "").toUpperCase()) ||
                             rawU.endsWith("(baned)") || rawU.endsWith("(banned)");
            let uname = "";
            if (isBanned) {
              let cleanU = rawU.replace(/\s*\((baned|banned|tab_map|acc\.txt|server_links)\)/gi, "").trim();
              uname = cleanU && !isUnknown ? `${escapeHtml(cleanU.slice(0, 40))} (baned)` : "baned";
            } else {
              uname = isUnknown ? "❓ (unknown)" : escapeHtml(rawU.slice(0, 50));
            }
            const line = `Tab ${tabNum}: ${uname}`;
            // Telegram 4096-char bound: truncate cleanly if approaching limit
            if (msg.length + lines.join("\n").length + line.length > 3900) {
              const remaining = sortedTabs.length - i;
              lines.push(`... và còn ${remaining} tab khác`);
              break;
            }
            lines.push(line);
          }
          msg += lines.join("\n");
        }
      } else if (isSuccess) {
        msg = `📱 <b>Tab List — ${escapeHtml(devName)}</b>\n(Không có tab Roblox nào đang chạy)`;
      } else {
        msg = `❌ <b>LẤY TAB LIST THẤT BẠI</b>\n📱 Thiết bị: <code>${escapeHtml(devName)}</code>\n⚠️ Lý do: ${escapeHtml(body.reason || "Lỗi truy vấn thiết bị")}`;
      }

      try {
        await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
        });
      } catch (e) {}
    }

    return json({ ok: true, action_id: actionId, device_id: deviceId, status: status || "SUCCESS" });
  }

  async acknowledgeAutoLogin(record, body, deviceId, actionId) {
    const act = record.autologin_actions?.[actionId];
    const device = act?.devices?.[deviceId];
    const status = String(body.status || "");
    const isSuccess = status === "OPENED" || status === "SUCCESS";

    if (device && device.status === "QUEUED") {
      device.status = isSuccess ? status : "FAILED";
      device.executed = isSuccess && body.executed === true;
      device.reason = status === "FAILED" ? String(body.reason || "autologin_failed").slice(0, 160) : null;
      device.details = body.details ? String(body.details) : null;
      device.updated_at = Date.now();
    }
    for (const command of record.pending_actions?.[deviceId] || []) {
      if (command.action_id === actionId) command.acknowledged_at = Date.now();
    }
    await this.writeFleet(record);

    const chatId = act?.telegram_chat_id || this.env?.TELEGRAM_ADMIN_USER_ID;
    if (chatId && this.env?.TELEGRAM_BOT_TOKEN) {
      let detailsObj = null;
      if (body.details) {
        try {
          detailsObj = typeof body.details === "string" ? JSON.parse(body.details) : body.details;
        } catch (e) {}
      }

      const devName = (act?.device_id || deviceId || "M77").toUpperCase();
      let msg = "";
      if (isSuccess && detailsObj) {
        const loggedIn = Array.isArray(detailsObj.logged_in) ? detailsObj.logged_in : [];
        if (loggedIn.length === 0) {
          msg = `🔐 <b>Auto-Login — ${escapeHtml(devName)}</b>\n${escapeHtml(detailsObj.message || "Tất cả các tab đều đã có tài khoản gán.")}`;
        } else {
          msg = `🍪 <b>Auto-Login — ${escapeHtml(devName)}</b>\n✅ Đã bơm ${loggedIn.length} cookie sạch vào <code>cookie.txt</code>:\n`;
          for (const item of loggedIn) {
            const reason = item.replaced_reason ? ` <i>(${escapeHtml(item.replaced_reason)})</i>` : "";
            msg += `• Tab ${escapeHtml(String(item.tab))}: <code>${escapeHtml(String(item.username))}</code>${reason}\n`;
          }
          if (detailsObj.tab_numbers) {
            msg += `\n👉 <b>Các tab cần nạp trên Tool:</b> <code>${escapeHtml(detailsObj.tab_numbers)}</code>\n`;
            msg += `<i>Vào Tool UgPhone > Chọn [7] Login via Cookie > [2] Login via cookies > Nhập: <code>${escapeHtml(detailsObj.tab_numbers)}</code></i>\n`;
          }
          if (Array.isArray(detailsObj.unresolved_tabs) && detailsObj.unresolved_tabs.length > 0) {
            msg += `\n⚠️ Còn ${detailsObj.unresolved_tabs.length} tab chưa có tài khoản do thiếu acc sạch trong kho.`;
          }
        }
      } else if (isSuccess) {
        msg = `🔐 <b>Auto-Login — ${escapeHtml(devName)}</b>\n✅ Đã hoàn tất tự động đăng nhập.`;
      } else {
        msg = `❌ <b>TỰ ĐỘNG LOGIN THẤT BẠI</b>\n📱 Thiết bị: <code>${escapeHtml(devName)}</code>\n⚠️ Lý do: ${escapeHtml(body.reason || "Lỗi nạp tài khoản")}`;
      }

      try {
        await fetch(`https://api.telegram.org/bot${this.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chat_id: chatId, text: msg, parse_mode: "HTML" })
        });
      } catch (e) {}
    }

    return json({ ok: true, action_id: actionId, device_id: deviceId, status: status || "SUCCESS" });
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

    if (!id || !/^[A-Za-z0-9_-]{1,128}$/.test(actionId)) {
      return json({ ok: false, error: "invalid_aot_ack" }, 400);
    }

    const record = await this.readFleet();
    if (action === "UPDATE_DELTA") return this.acknowledgeDeltaUpdate(record, body, id, actionId);
    if (action === "BACKUP_APP") return this.acknowledgeAppBackup(record, body, id, actionId);
    if (action === "UPGRADE_AGENT") return this.acknowledgeAgentUpgrade(record, body, id, actionId);
    if (action === "ENABLE_DEV_MODE") return this.acknowledgeDevMode(record, body, id, actionId);
    if (action === "WRITE_SCRIPT") return this.acknowledgeWriteScript(record, body, id, actionId);
    if (action === "CLEAN_SCRIPT") return this.acknowledgeCleanScript(record, body, id, actionId);
    if (action === "CONTROL_TAILSCALE") return this.acknowledgeTailscaleControl(record, body, id, actionId);
    if (action === "CHECK_BAN") return this.acknowledgeCheckBan(record, body, id, actionId);
    if (action === "ADD_ACC") return this.acknowledgeAddAcc(record, body, id, actionId);
    if (action === "DEL_ACC") return this.acknowledgeDelAcc(record, body, id, actionId);
    if (action === "MOVE_ACC") return this.acknowledgeMoveAcc(record, body, id, actionId);
    if (action === "TAB_LIST") return this.acknowledgeTabList(record, body, id, actionId);
    if (action === "AUTO_LOGIN") return this.acknowledgeAutoLogin(record, body, id, actionId);
    if (action !== AOT_ALLOCATE_SERVER_ACTION) return json({ ok: false, error: "invalid_aot_ack" }, 400);
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

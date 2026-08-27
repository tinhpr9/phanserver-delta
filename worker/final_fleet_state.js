import { FleetState as HardenedFleetState } from "./hardened_fleet_state.js";
import {
  FleetState as BaseFleetState,
  normalizeDeviceGroup,
  normalizeDeviceId,
} from "./fleet_state.js";

const CAPABILITIES = ["allocate_server_2pc", "update_delta"];

function safeEqual(left, right) {
  const a = String(left || "");
  const b = String(right || "");
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let index = 0; index < a.length; index++) diff |= a.charCodeAt(index) ^ b.charCodeAt(index);
  return diff === 0;
}

function decodeWebSocketMessage(message) {
  if (typeof message === "string") return message;
  if (message instanceof ArrayBuffer) return new TextDecoder().decode(message);
  if (ArrayBuffer.isView(message)) {
    return new TextDecoder().decode(message.buffer.slice(message.byteOffset, message.byteOffset + message.byteLength));
  }
  return "";
}

/**
 * Final production invariants for fresh-device onboarding and Durable Object
 * WebSocket transport.
 *
 * Cloudflare's ctx.acceptWebSocket() uses the Hibernation API. Therefore ACK and
 * close handling must live in webSocketMessage/webSocketClose rather than
 * addEventListener callbacks, and socket identity must survive hibernation via a
 * serialized attachment.
 */
export class FleetState extends HardenedFleetState {
  constructor(ctx, env) {
    super(ctx, env);
    this.restoreLiveSocketsFromAttachments();
  }

  socketAttachment(ws) {
    try {
      const attachment = ws?.deserializeAttachment?.();
      return attachment && typeof attachment === "object" ? attachment : null;
    } catch (_error) {
      return null;
    }
  }

  restoreLiveSocketsFromAttachments() {
    if (!this.ctx?.getWebSockets) return;
    const newestByDevice = new Map();
    for (const ws of this.ctx.getWebSockets()) {
      const attachment = this.socketAttachment(ws);
      const deviceId = normalizeDeviceId(attachment?.device_id);
      const connectedAt = Number(attachment?.connected_at || 0);
      if (!deviceId || !connectedAt) continue;
      const previous = newestByDevice.get(deviceId);
      if (!previous || connectedAt > previous.connected_at) {
        newestByDevice.set(deviceId, { socket: ws, connected_at: connectedAt });
      }
    }
    for (const [deviceId, entry] of newestByDevice) {
      this.aotLive.set(deviceId, {
        capabilities: CAPABILITIES,
        connected_at: entry.connected_at,
        socket: entry.socket,
      });
    }
  }

  currentSocket(deviceId) {
    const live = this.aotLive?.get?.(deviceId);
    if (live?.socket) return live.socket;

    if (!this.ctx?.getWebSockets) return null;
    let best = null;
    let bestAt = -1;
    for (const ws of this.ctx.getWebSockets(`device:fleet:${deviceId}`)) {
      const attachment = this.socketAttachment(ws);
      if (normalizeDeviceId(attachment?.device_id) !== deviceId) continue;
      const connectedAt = Number(attachment?.connected_at || 0);
      if (connectedAt > bestAt) {
        best = ws;
        bestAt = connectedAt;
      }
    }
    if (best) {
      this.aotLive.set(deviceId, {
        capabilities: CAPABILITIES,
        connected_at: bestAt,
        socket: best,
      });
    }
    return best;
  }

  isCurrentSocket(deviceId, ws) {
    const current = this.currentSocket(deviceId);
    return current ? current === ws : false;
  }

  async credentialKind(deviceId, presentedSecret) {
    const record = await this.readFleet();
    const device = record.devices?.[deviceId];
    const legacySecret = String(this.env?.AGENT_REPORT_SECRET || "");

    if (!device && legacySecret && safeEqual(presentedSecret, legacySecret)) {
      return null;
    }
    return super.credentialKind(deviceId, presentedSecret);
  }

  async promotePendingCredential(deviceId, presentedSecret) {
    const promoted = await super.promotePendingCredential(deviceId, presentedSecret);
    if (!promoted) return false;

    // Promotion closes the old command socket. Invalidate its persisted session ID
    // immediately so a late ACK from that closing socket cannot advance a 2PC batch
    // during the small interval before the replacement socket is accepted.
    const record = await this.readFleet();
    const device = record.devices?.[deviceId];
    if (device?.active_ws_session_id) {
      delete device.active_ws_session_id;
      await this.writeFleet(record);
    }
    this.aotLive?.delete?.(deviceId);
    return true;
  }

  isDeviceOnline(id, recordDevice) {
    const deviceId = normalizeDeviceId(id);
    if (!deviceId) return false;

    const current = this.currentSocket(deviceId);
    if (current) {
      if (!recordDevice?.agent_secret_sha256) return true;
      const attachment = this.socketAttachment(current);
      const socketSessionId = String(attachment?.session_id || "");
      const activeSessionId = String(recordDevice?.active_ws_session_id || "");
      if (socketSessionId && activeSessionId && safeEqual(socketSessionId, activeSessionId)) {
        return true;
      }
    }

    // A paired device is ONLINE only when its authenticated command socket is the
    // persisted active session. A recent HTTP heartbeat alone must not satisfy
    // fresh onboarding readiness.
    if (recordDevice?.agent_secret_sha256) return false;

    // Temporary compatibility for pre-pairing legacy fleet sockets that were
    // accepted before session attachments existed.
    if (this.ctx?.getWebSockets) {
      const legacySockets = this.ctx.getWebSockets(`device:fleet:${deviceId}`);
      if (legacySockets.length > 0) return true;
    }
    return super.isDeviceOnline(deviceId, recordDevice);
  }

  sendPayload(deviceId, payload) {
    const encoded = JSON.stringify(payload);
    const current = this.currentSocket(deviceId);
    if (current) {
      try {
        current.send(encoded);
        return 1;
      } catch (_error) {
        return 0;
      }
    }

    // Compatibility only: old pre-attachment sockets can exist during rollout.
    // Send to one socket, never every tagged socket, to preserve exactly-once intent.
    if (this.ctx?.getWebSockets) {
      const legacySockets = this.ctx.getWebSockets(`device:fleet:${deviceId}`);
      if (legacySockets.length > 0) {
        try {
          legacySockets[0].send(encoded);
          return 1;
        } catch (_error) {
          return 0;
        }
      }
    }
    return 0;
  }

  async handlePairDecision(request) {
    let body = null;
    try {
      body = await request.clone().json();
    } catch (_error) {
      return super.handlePairDecision(request);
    }

    const handle = String(body?.pair_id || "");
    const decision = String(body?.decision || "");
    const separator = handle.indexOf("_");
    const pairId = separator >= 0 ? handle.slice(0, separator) : handle;

    let freshDeviceId = null;
    if (decision === "approve" && pairId) {
      const before = await this.readFleet();
      const pair = before.pending_pairs?.[pairId];
      const previousHash = String(before.devices?.[pair?.device_id]?.agent_secret_sha256 || "");
      if (pair?.device_id && !previousHash) freshDeviceId = pair.device_id;
    }

    const response = await super.handlePairDecision(request);
    if (response.ok && decision === "approve" && freshDeviceId) {
      this.closeExistingDeviceSockets(freshDeviceId, 4001, "credential_initialized");
      const fresh = await this.readFleet();
      const device = fresh.devices?.[freshDeviceId];
      if (device) {
        device.online = false;
        delete device.active_ws_session_id;
        await this.writeFleet(fresh);
      }
    }
    return response;
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

    // Validate immutable identity/group before rotating credentials or evicting the
    // currently working socket. A malformed reconnect must not take a healthy device down.
    let record = await this.readFleet();
    const before = record.devices?.[deviceId];
    if (before?.device_group && requestedGroup && normalizeDeviceGroup(before.device_group) !== requestedGroup) {
      return new Response("Device group mismatch", { status: 409 });
    }

    if (kind === "pending") {
      if (!(await this.promotePendingCredential(deviceId, presentedSecret))) {
        return new Response("Credential rotation failed", { status: 409 });
      }
    } else {
      this.closeExistingDeviceSockets(deviceId, 4000, "device_reconnected");
    }

    const pair = new WebSocketPair();
    const [client, server] = [pair[0], pair[1]];
    const sessionId = crypto.randomUUID();
    const connectedAt = Date.now();
    const tag = `device:fleet:${deviceId}`;

    // Cloudflare's Hibernation API accepts the socket first; only then are
    // send/close and attachment methods guaranteed to be usable on the server end.
    this.ctx?.acceptWebSocket?.(server, [tag]);
    server.serializeAttachment({
      device_id: deviceId,
      session_id: sessionId,
      connected_at: connectedAt,
    });
    this.aotLive.set(deviceId, {
      capabilities: CAPABILITIES,
      connected_at: connectedAt,
      socket: server,
    });

    record = await this.readFleet();
    const existing = record.devices?.[deviceId] || {
      device_id: deviceId,
      joined_at: connectedAt,
      device_group: requestedGroup || "NOVA",
    };
    existing.device_group = normalizeDeviceGroup(existing.device_group || requestedGroup || "NOVA") || "NOVA";
    existing.online = true;
    existing.last_seen = connectedAt;
    existing.capabilities = CAPABILITIES;
    existing.active_ws_session_id = sessionId;
    record.devices[deviceId] = existing;
    await this.writeFleet(record);

    return new Response(null, { status: 101, webSocket: client });
  }

  async webSocketMessage(ws, message) {
    const attachment = this.socketAttachment(ws);
    const deviceId = normalizeDeviceId(attachment?.device_id);
    const sessionId = String(attachment?.session_id || "");
    if (!deviceId || !sessionId || !this.isCurrentSocket(deviceId, ws)) return;

    // The attachment identifies the socket after hibernation, while storage is the
    // authoritative active-session fence. Both must agree before an ACK is allowed
    // to mutate the 2PC state machine.
    const record = await this.readFleet();
    const activeSessionId = String(record.devices?.[deviceId]?.active_ws_session_id || "");
    if (!activeSessionId || !safeEqual(activeSessionId, sessionId)) return;

    let parsed;
    try {
      parsed = JSON.parse(decodeWebSocketMessage(message));
    } catch (_error) {
      return;
    }
    if (parsed?.type !== "ack") return;
    if (normalizeDeviceId(parsed.device_id) !== deviceId) return;

    await BaseFleetState.prototype.dispatchFleetAck.call(
      this,
      new Request("https://localhost/aot/ack", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed),
      }),
    );
  }

  async releaseSocketSession(ws) {
    const attachment = this.socketAttachment(ws);
    const deviceId = normalizeDeviceId(attachment?.device_id);
    const sessionId = String(attachment?.session_id || "");
    if (!deviceId || !sessionId) return;

    const live = this.aotLive?.get?.(deviceId);
    if (live?.socket === ws) this.aotLive.delete(deviceId);

    const record = await this.readFleet();
    const device = record.devices?.[deviceId];
    if (!device || String(device.active_ws_session_id || "") !== sessionId) return;

    device.online = false;
    delete device.active_ws_session_id;
    await this.writeFleet(record);
  }

  async webSocketClose(ws, _code, _reason, _wasClean) {
    await this.releaseSocketSession(ws);
  }

  async webSocketError(ws, _error) {
    await this.releaseSocketSession(ws);
  }
}

import { FleetState as HardenedFleetState } from "./hardened_fleet_state.js";

function safeEqual(left, right) {
  const a = String(left || "");
  const b = String(right || "");
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let index = 0; index < a.length; index++) diff |= a.charCodeAt(index) ^ b.charCodeAt(index);
  return diff === 0;
}

/**
 * Final security invariants that depend on the distinction between a legacy
 * device and a never-before-seen Device ID.
 *
 * Existing fleet records may temporarily use AGENT_REPORT_SECRET for backwards
 * compatibility. A fresh/nonexistent Device ID must never be able to create a
 * legacy-authenticated WebSocket before pairing, and fresh approval must evict
 * any stale tagged socket that predates the new per-device credential.
 */
export class FleetState extends HardenedFleetState {
  async credentialKind(deviceId, presentedSecret) {
    const record = await this.readFleet();
    const device = record.devices?.[deviceId];
    const legacySecret = String(this.env?.AGENT_REPORT_SECRET || "");

    if (!device && legacySecret && safeEqual(presentedSecret, legacySecret)) {
      return null;
    }
    return super.credentialKind(deviceId, presentedSecret);
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
        await this.writeFleet(fresh);
      }
    }
    return response;
  }
}

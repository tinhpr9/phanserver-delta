import { FleetState as FinalFleetState } from "./final_fleet_state.js";
import { normalizeDeviceId } from "./fleet_state.js";

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

/**
 * Compatibility fence for re-onboarding devices that still authenticate with the
 * legacy AGENT_REPORT_SECRET and therefore do not yet have agent_secret_sha256.
 *
 * Materialize the current legacy credential as a per-device digest only after the
 * same decision capability checks used by the pairing flow pass. That makes the
 * existing runtime look like a normal current per-device credential to the lower
 * rotation layer, so the newly approved secret is staged instead of immediately
 * revoking the old runtime. Promotion still happens only when the new WebSocket
 * proves connectivity.
 */
export class FleetState extends FinalFleetState {
  async handlePairDecision(request) {
    let body;
    try {
      body = await request.clone().json();
    } catch (_error) {
      return super.handlePairDecision(request);
    }

    if (String(body?.decision || "") !== "approve") {
      return super.handlePairDecision(request);
    }

    const handle = String(body?.pair_id || "");
    const separator = handle.indexOf("_");
    if (separator < 8) return super.handlePairDecision(request);

    const pairId = handle.slice(0, separator);
    const decisionToken = handle.slice(separator + 1);
    if (!/^[A-Za-z0-9_-]{8,64}$/.test(pairId) || !/^[A-Za-z0-9_-]{16,64}$/.test(decisionToken)) {
      return super.handlePairDecision(request);
    }

    const controlSecret = String(this.env?.AGENT_REPORT_SECRET || "");
    const presented = String(request.headers.get("X-Internal-Pair-Key") || "");
    if (!controlSecret || !safeEqual(presented, controlSecret)) {
      return super.handlePairDecision(request);
    }

    const record = await this.readFleet();
    const pair = record.pending_pairs?.[pairId];
    if (!pair || pair.status !== "pending" || Number(pair.expires_at || 0) <= Date.now()) {
      return super.handlePairDecision(request);
    }

    const decisionHash = await sha256Hex(decisionToken);
    if (!pair.decision_token_sha256 || !safeEqual(decisionHash, pair.decision_token_sha256)) {
      return super.handlePairDecision(request);
    }

    const deviceId = normalizeDeviceId(pair.device_id);
    const existing = deviceId ? record.devices?.[deviceId] : null;
    if (existing && !existing.agent_secret_sha256) {
      // Before this point the device's current credential is represented implicitly
      // by AGENT_REPORT_SECRET. Persisting its digest preserves exactly the same
      // credential while allowing the normal pending-credential rotation path to
      // keep it authoritative until the replacement WebSocket connects.
      existing.agent_secret_sha256 = await sha256Hex(controlSecret);
      await this.writeFleet(record);
    }

    return super.handlePairDecision(request);
  }
}

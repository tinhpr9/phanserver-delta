import assert from "node:assert/strict";

// Proposed extractValidTailscaleIp
function extractValidTailscaleIp(details) {
  const match = String(details || "").match(/(?<![\d.])\b100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b(?![\d.])/);
  if (!match) return null;
  const octets = [Number(match[1]), Number(match[2]), Number(match[3])];
  if (octets.some((o) => o < 0 || o > 255 || isNaN(o))) return null;
  return match[0];
}

console.log("Testing extractValidTailscaleIp...");

const validIPs = [
  "CONNECTED: 100.80.175.55",
  "100.64.0.1",
  "100.127.255.254",
  "100.0.0.0",
  "100.255.255.255"
];
for (const ip of validIPs) {
  const res = extractValidTailscaleIp(ip);
  assert.ok(res, `Expected valid IP for ${ip}, got ${res}`);
}

const invalidIPs = [
  "CONNECTED: 100.300.1.1",
  "CONNECTED: 100.1.256.1",
  "CONNECTED: 100.1.2.2555",
  "CONNECTED: 1100.1.2.3",
  "CONNECTED: 100.1.2.3.4",
  "CONNECTED: .100.1.2.3",
  "100.1.1",
  "100.abc.1.1",
  "TRIGGERED",
  "",
  null,
  undefined
];
for (const ip of invalidIPs) {
  const res = extractValidTailscaleIp(ip);
  assert.equal(res, null, `Expected null for ${ip}, got ${res}`);
}

console.log("ALL UNIT TESTS FOR extractValidTailscaleIp PASSED!");

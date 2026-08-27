import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { getTongHopLinkContent } from "../worker/phanserver.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const poolPath = path.join(ROOT, "data", "tong_hop_link.txt");
const entryPath = path.join(ROOT, "worker", "cloudflare.js");
const wranglerPath = path.join(ROOT, "wrangler.jsonc");

const pool = fs.readFileSync(poolPath, "utf8");
if (!pool.trim()) {
  throw new Error("production link pool is empty");
}

const entry = fs.readFileSync(entryPath, "utf8");
if (!entry.includes('import tongHopLinkRaw from "../data/tong_hop_link.txt";')) {
  throw new Error("Cloudflare entrypoint does not import the canonical link pool");
}
if (!entry.includes("runtimeEnv.TONG_HOP_LINK_RAW = tongHopLinkRaw")) {
  throw new Error("Cloudflare entrypoint does not inject the bundled link pool");
}

const wrangler = JSON.parse(fs.readFileSync(wranglerPath, "utf8"));
if (wrangler.main !== "worker/cloudflare.js") {
  throw new Error("Wrangler does not deploy the Cloudflare link-pool entrypoint");
}
if (Object.prototype.hasOwnProperty.call(wrangler.vars || {}, "TONG_HOP_LINK_RAW")) {
  throw new Error("blank TONG_HOP_LINK_RAW var can shadow the bundled production pool");
}

const resolved = await getTongHopLinkContent({ TONG_HOP_LINK_RAW: pool });
if (resolved !== pool) {
  throw new Error("production link-pool injection does not reach /phanserver content lookup");
}

console.log("TEST_PRODUCTION_LINK_POOL=OK");

import worker, { FleetState } from "./worker.js";
import tongHopLinkRaw from "../data/tong_hop_link.txt";

export { FleetState };

export default {
  async fetch(request, env, ctx) {
    const runtimeEnv = Object.create(env);
    runtimeEnv.TONG_HOP_LINK_RAW = tongHopLinkRaw;
    return worker.fetch(request, runtimeEnv, ctx);
  },
};

import { handleUpdate, handleCallback } from "../worker/phanserver.js";
import worker from "../worker/worker.js";
import { FleetState } from "../worker/fleet_state.js";

let sentMessages = [];
let answeredCallbacks = [];
let clearedTokens = [];
let pendingAllocates = {};
let fleetControlCalls = [];
let getFleetHubStateCalls = 0;
let isM1Online = true;
let gitHubFileError = null;
let gitHubFileAbort = false;

const env = {
  TELEGRAM_ADMIN_USER_ID: "123",
  TELEGRAM_BOT_TOKEN: "tok",
  telegram: async (env, method, payload) => {
    if (method === "sendMessage" || method === "editMessageText") {
      sentMessages.push(payload);
    }
  },
  answerCallback: async (id, env, text, alert) => {
    answeredCallbacks.push({ id, text, alert });
  },
  resolveAndValidateTelegramTargets: async (targetStr, env) => {
    if (targetStr === "m1,m2") return ["m1", "m2"];
    if (targetStr === "offline") throw new Error("Thiết bị offline đang OFFLINE.");
    if (targetStr === "dup,dup") throw new Error("Thiết bị bị lặp.");
    return ["m1"];
  },
  getGitHubFile: async (path, env, options = {}) => {
    if (options?.signal?.aborted || gitHubFileAbort) {
      const err = new Error("The operation was aborted");
      err.name = "AbortError";
      throw err;
    }
    if (gitHubFileError) {
      throw new Error(gitHubFileError);
    }
    if (path === "tong_hop_link.txt") {
      const contentStr = `com.tinh.vv.hi,https://www.roblox.com/games/975?privateServerLinkCode=11111111111111111111111111111111
com.tinh.vv.hj,https://www.roblox.com/games/975?privateServerLinkCode=22222222222222222222222222222222
com.tinh.vv.hk,https://www.roblox.com/games/975?privateServerLinkCode=33333333333333333333333333333333
com.tinh.vv.hl,https://www.roblox.com/games/975?privateServerLinkCode=44444444444444444444444444444444
com.tinh.vv.hm,https://www.roblox.com/games/975?privateServerLinkCode=55555555555555555555555555555555
com.tinh.vv.hn,https://www.roblox.com/games/975?privateServerLinkCode=66666666666666666666666666666666
com.tinh.vv.ho,https://www.roblox.com/games/975?privateServerLinkCode=77777777777777777777777777777777
com.tinh.vv.hp,https://www.roblox.com/games/975?privateServerLinkCode=88888888888888888888888888888888
com.tinh.vv.hq,https://www.roblox.com/games/975?privateServerLinkCode=99999999999999999999999999999999
com.tinh.vv.hr,https://www.roblox.com/games/975?privateServerLinkCode=00000000000000000000000000000000
===`;
      return {
        content: Buffer.from(contentStr).toString("base64")
      };
    }
    throw new Error(`File ${path} not found`);
  },
  fleetStateCall: async (env, path, init) => {
    if (path === "/aot/hub/control") {
      const body = init.body;
      if (body.kind === "pending_allocate_save") {
        pendingAllocates[body.token] = body.spec;
        return { response: { ok: true } };
      }
      if (body.kind === "pending_allocate_consume") {
        const spec = pendingAllocates[body.token];
        if (spec) {
          delete pendingAllocates[body.token];
          clearedTokens.push(body.token);
          return { response: { ok: true }, data: { spec } };
        }
        return { response: { ok: false } };
      }
      if (body.kind === "pending_allocate_clear") {
        if (pendingAllocates[body.token]) {
          clearedTokens.push(body.token);
          delete pendingAllocates[body.token];
          return { response: { ok: true }, data: { cleared: true } };
        }
        return { response: { ok: true }, data: { cleared: false } };
      }
      fleetControlCalls.push(body);
      return { response: { ok: true }, data: { batch: { action_id: "act-123", devices: [{ device_id: "m1", status: "SENT", history: ["SENT"] }] } } };
    }
    if (path === "/aot/hub/state") {
      getFleetHubStateCalls++;
      const status = getFleetHubStateCalls > 1 ? "OPENED" : "SENT";
      return { response: { ok: true }, data: { state: { devices: [{ device_id: "m1", online: isM1Online, metrics: { tailscale_ip: isM1Online ? "100.80.175.55" : null } }], last_batch: { action_id: "act-123", devices: [{ device_id: "m1", status, history: ["SENT", status] }] } } } };
    }
  }
};

async function runTests() {
  const triggerMessage = async (text) => {
    sentMessages = [];
    await handleUpdate({ message: { from: { id: "123" }, chat: { id: 1 }, text } }, env);
  };
  const triggerCallback = async (data) => {
    answeredCallbacks = [];
    sentMessages = [];
    await handleCallback({ id: "cb1", data, message: { chat: { id: 1 }, message_id: 12 }, from: { id: "123" } }, 1, 12, env);
  };

  // 1. malformed tabs
  await triggerMessage("/phanserver m1 5abc");
  if (!sentMessages[0].text.includes("Số tab phải từ 1 đến 10")) throw new Error("malformed tab test failed");
  await triggerMessage("/phanserver m1 11");
  if (!sentMessages[0].text.includes("Số tab phải từ 1 đến 10")) throw new Error("out of range tab test failed");
  await triggerMessage("/phanserver m1 5.5");
  if (!sentMessages[0].text.includes("Số tab phải từ 1 đến 10")) throw new Error("float tab test failed");

  // 2. preview flow
  await triggerMessage("/phanserver m1 5");
  if (!sentMessages[0] || !sentMessages[0].text.includes("PREVIEW PHÂN SERVER")) throw new Error("preview test failed");
  const inlineKb = sentMessages[0].reply_markup.inline_keyboard[0];
  const okCallbackData = inlineKb[0].callback_data;
  const cancelCallbackData = inlineKb[1].callback_data;

  // Cancel
  await triggerCallback(cancelCallbackData);
  if (clearedTokens[0] !== cancelCallbackData.split(":")[1]) throw new Error("cancel test failed");
  if (answeredCallbacks[0].text !== "Đã hủy PHÂN SERVER.") throw new Error("cancel response failed");
  
  // Double Cancel
  await triggerCallback(cancelCallbackData);
  if (answeredCallbacks[0].text !== "Lệnh đã được xác nhận/đang xử lý, không thể hủy.") throw new Error("double cancel response failed");

  // Confirm after Cancel
  await triggerCallback(okCallbackData);
  if (answeredCallbacks[0].text !== "Xác nhận đã hết hạn hoặc đã được xử lý.") throw new Error("confirm after cancel failed");

  // Confirm
  // recreate pending
  await triggerMessage("/phanserver m1 5");
  const inlineKb2 = sentMessages[0].reply_markup.inline_keyboard[0];
  const okCb2 = inlineKb2[0].callback_data;
  const cancelCb2 = inlineKb2[1].callback_data;
  
  // mock m1 offline for confirm
  isM1Online = false;
  await triggerCallback(okCb2);
  if (!sentMessages[0].text.includes("OFFLINE")) throw new Error("Offline confirm did not fail properly: " + sentMessages[0].text);
  
  // reset to online
  isM1Online = true;
  await triggerMessage("/phanserver m1 5");
  const inlineKb3 = sentMessages[0].reply_markup.inline_keyboard[0];
  const okCb3 = inlineKb3[0].callback_data;
  const cancelCb3 = inlineKb3[1].callback_data;

  await triggerCallback(okCb3);
  if (clearedTokens[clearedTokens.length - 1] !== okCb3.split(":")[1]) throw new Error("confirm clear test failed");
  if (answeredCallbacks[0].text !== "Đang chạy phân server...") throw new Error("confirm response failed");
  const confirmMsg = sentMessages[0];
  
  // Double Confirm
  await triggerCallback(okCb3);
  if (answeredCallbacks[0].text !== "Xác nhận đã hết hạn hoặc đã được xử lý.") throw new Error("double confirm failed");
  
  // Cancel after Confirm
  await triggerCallback(cancelCb3);
  if (answeredCallbacks[0].text !== "Lệnh đã được xác nhận/đang xử lý, không thể hủy.") throw new Error("cancel after confirm failed");

  const lastControl = fleetControlCalls[fleetControlCalls.length - 1];
  if (lastControl.kind !== "allocate_server") throw new Error("fleet control dispatch failed");
  if (lastControl.telegram_chat_id !== 1) throw new Error("fleet control dispatch telegram_chat_id failed");
  if (!confirmMsg || !confirmMsg.text.includes("đang chờ thiết bị phản hồi")) throw new Error("final intermediate result message failed");

  // Duplicate device
  await triggerMessage("/phanserver dup,dup 5");
  if (!sentMessages[0].text.includes("Lỗi: Thiết bị bị lặp")) throw new Error("dup test failed");

  // Offline device
  await triggerMessage("/phanserver offline 5");
  if (!sentMessages[0].text.includes("Lỗi: Thiết bị offline đang OFFLINE")) throw new Error("offline test failed");

  // GitHub fetch failure reproduction test
  gitHubFileError = "GitHub GET 404: Not Found";
  await triggerMessage("/phanserver m1 5");
  if (!sentMessages[0].text.includes("Lỗi: GitHub GET 404: Not Found")) {
    throw new Error("GitHub fetch error reproduction test failed: " + sentMessages[0].text);
  }
  gitHubFileError = null;

  // GitHub timeout abort reproduction test
  gitHubFileAbort = true;
  await triggerMessage("/phanserver m1 5");
  if (!sentMessages[0].text.includes("Lỗi: The operation was aborted")) {
    throw new Error("GitHub timeout abort test failed: " + sentMessages[0].text);
  }
  gitHubFileAbort = false;

  // 7. Worker-owned STATUS command
  await triggerMessage("STATUS");
  if (!sentMessages[0]?.text.includes("FLEET_STATUS=ONLINE") || !sentMessages[0].text.includes("m1: ONLINE")) {
    throw new Error("worker status test failed: " + (sentMessages[0]?.text || ""));
  }

  // 7. Fleet device list and typed UPDATE_DELTA dispatch
  await triggerMessage("/devices");
  if (!sentMessages[0]?.text.includes("m1: ONLINE (Tailscale: 100.80.175.55)")) {
    throw new Error("devices tailscale test failed: " + (sentMessages[0]?.text || ""));
  }

  await triggerMessage("STATUS");
  if (!sentMessages[0]?.text.includes("m1: ONLINE 🌐 100.80.175.55")) {
    throw new Error("status tailscale test failed: " + (sentMessages[0]?.text || ""));
  }

  await triggerMessage("UPDATE");
  if (!sentMessages[0]?.text.includes("UPDATE_TARGET_REQUIRED") || !sentMessages[0].text.includes("/update m1")) {
    throw new Error("bare update guidance test failed: " + (sentMessages[0]?.text || ""));
  }

  await triggerMessage("/update m1,m2");
  const updateCall = fleetControlCalls.at(-1);
  if (updateCall?.kind !== "update_delta" || updateCall?.protocol !== "fleet-batch-v1") {
    throw new Error("update delta dispatch test failed: " + JSON.stringify(updateCall));
  }
  if (!sentMessages[0]?.text.includes("RESTORE")) {
    throw new Error("update delta confirmation test failed: " + (sentMessages[0]?.text || ""));
  }

  // 8. Selective UPDATE_DELTA dispatch via /restore
  await triggerMessage("/restore m1,m2 random");
  const updateCall2 = fleetControlCalls.at(-1);
  if (!sentMessages[0]?.text.includes("random")) {
    throw new Error("selective update delta confirmation test failed: " + (sentMessages[0]?.text || ""));
  }

  // Cross-package restore test
  await triggerMessage("/restore m1 10 ho");
  const crossCall = fleetControlCalls.at(-1);
  if (crossCall?.kind !== "update_delta" || crossCall?.target_pkg !== "ho") {
    throw new Error("cross-package restore dispatch failed: " + JSON.stringify(crossCall));
  }
  if (!sentMessages[0]?.text.includes("ho")) {
    throw new Error("cross-package restore confirmation failed: " + (sentMessages[0]?.text || ""));
  }

  // 9. APKs release list command
  await triggerMessage("/apks");
  if (!sentMessages[0]?.text.includes("DANH SÁCH APP TRONG RELEASE")) {
    throw new Error("apks list test failed: " + (sentMessages[0]?.text || ""));
  }

  // 10. Backup app command
  await triggerMessage("/backup m1 taskbar");
  const backupCall = fleetControlCalls.at(-1);
  if (backupCall?.kind !== "backup_app" || backupCall?.package !== "taskbar") {
    throw new Error("backup app dispatch test failed: " + JSON.stringify(backupCall));
  }
  if (!sentMessages[0]?.text.includes("ĐÃ XẾP LỆNH")) {
    throw new Error("backup confirmation test failed: " + (sentMessages[0]?.text || ""));
  }

  // 11. Granular backup mode (data-only and apk-only)
  await triggerMessage("/backup m1 taskbar data");
  const backupCall2 = fleetControlCalls.at(-1);
  if (backupCall2?.kind !== "backup_app" || backupCall2?.mode !== "data") {
    throw new Error("backup data mode dispatch failed: " + JSON.stringify(backupCall2));
  }
  if (!sentMessages[0]?.text.includes("Chỉ Data cấu hình")) {
    throw new Error("backup data confirmation failed: " + (sentMessages[0]?.text || ""));
  }

  // 12. Script command with raw URL auto-wrapping loadstring
  await triggerMessage("/script m1 sae https://raw.githubusercontent.com/tinhpr9/Aotscript/main/Novagag2");
  const scriptCall = fleetControlCalls.at(-1);
  if (scriptCall?.kind !== "write_script" || scriptCall?.filename !== "sae" || !scriptCall?.content?.includes("loadstring(game:HttpGet")) {
    throw new Error("script write dispatch test failed: " + JSON.stringify(scriptCall));
  }
  if (!sentMessages[0]?.text.includes("ĐÃ XẾP LỆNH NẠP SCRIPT")) {
    throw new Error("script write confirmation failed: " + (sentMessages[0]?.text || ""));
  }

  // 13. Script clean command
  await triggerMessage("/script m1 clean sae");
  const cleanCall = fleetControlCalls.at(-1);
  if (cleanCall?.kind !== "clean_script" || cleanCall?.filename !== "sae") {
    throw new Error("script clean dispatch test failed: " + JSON.stringify(cleanCall));
  }
  if (!sentMessages[0]?.text.includes("ĐÃ XẾP LỆNH XÓA SCRIPT")) {
    throw new Error("script clean confirmation failed: " + (sentMessages[0]?.text || ""));
  }

  // 14. Tailscale control command
  await triggerMessage("/tailscale m1 on");
  const tailscaleCall1 = fleetControlCalls.at(-1);
  if (tailscaleCall1?.kind !== "control_tailscale" || tailscaleCall1?.mode !== "on") {
    throw new Error("tailscale on dispatch test failed: " + JSON.stringify(tailscaleCall1));
  }
  if (!sentMessages[0]?.text.includes("BẬT TAILSCALE")) {
    throw new Error("tailscale on confirmation failed: " + (sentMessages[0]?.text || ""));
  }

  await triggerMessage("/tailscale m1 off");
  const tailscaleCall2 = fleetControlCalls.at(-1);
  if (tailscaleCall2?.kind !== "control_tailscale" || tailscaleCall2?.mode !== "off") {
    throw new Error("tailscale off dispatch test failed: " + JSON.stringify(tailscaleCall2));
  }
  if (!sentMessages[0]?.text.includes("TẮT TAILSCALE")) {
    throw new Error("tailscale off confirmation failed: " + (sentMessages[0]?.text || ""));
  }

  await triggerMessage("/vpn m1 status");
  const tailscaleCall3 = fleetControlCalls.at(-1);
  if (tailscaleCall3?.kind !== "control_tailscale" || tailscaleCall3?.mode !== "status") {
    throw new Error("tailscale status dispatch test failed: " + JSON.stringify(tailscaleCall3));
  }
  if (!sentMessages[0]?.text.includes("KIỂM TRA TRẠNG THÁI TAILSCALE")) {
    throw new Error("tailscale status confirmation failed: " + (sentMessages[0]?.text || ""));
  }

  // 15. Checkban command
  await triggerMessage("/checkban m1");
  const checkbanCall1 = fleetControlCalls.at(-1);
  if (checkbanCall1?.kind !== "check_ban" || checkbanCall1?.target !== "m1" || !checkbanCall1?.target_device_ids?.includes("m1")) {
    throw new Error("checkban m1 dispatch test failed: " + JSON.stringify(checkbanCall1));
  }
  if (!sentMessages[0]?.text.includes("ĐÃ XẾP LỆNH CHECK BAN ROBLOX")) {
    throw new Error("checkban confirmation failed: " + (sentMessages[0]?.text || ""));
  }

  await triggerMessage("/checkban all");
  const checkbanCall2 = fleetControlCalls.at(-1);
  if (checkbanCall2?.kind !== "check_ban" || checkbanCall2?.target !== "all") {
    throw new Error("checkban all dispatch test failed: " + JSON.stringify(checkbanCall2));
  }

  // 16. Add account command
  await triggerMessage("/addacc m1 testuser:testpass");
  const addaccCall = fleetControlCalls.at(-1);
  if (addaccCall?.kind !== "add_acc" || addaccCall?.m_code !== "m1" || !addaccCall?.lines?.includes("testuser:testpass")) {
    throw new Error("addacc dispatch test failed: " + JSON.stringify(addaccCall));
  }
  if (!sentMessages[0]?.text.includes("ĐÃ XẾP LỆNH NẠP TÀI KHOẢN")) {
    throw new Error("addacc confirmation failed: " + (sentMessages[0]?.text || ""));
  }

  // 16b. Delete account command
  await triggerMessage("/delacc m1 testuser");
  const delaccCall = fleetControlCalls.at(-1);
  if (delaccCall?.kind !== "del_acc" || delaccCall?.m_code !== "m1" || !delaccCall?.usernames?.includes("testuser")) {
    throw new Error("delacc dispatch test failed: " + JSON.stringify(delaccCall));
  }
  if (!sentMessages[0]?.text.includes("ĐÃ XẾP LỆNH XÓA TÀI KHOẢN")) {
    throw new Error("delacc confirmation failed: " + (sentMessages[0]?.text || ""));
  }

  // 16c. Move account command (/moveacc and /chuyenacc)
  // Syntax help on empty args
  await triggerMessage("/moveacc");
  if (!sentMessages[0]?.text.includes("Cú pháp:") || !sentMessages[0]?.text.includes("/moveacc")) {
    throw new Error("moveacc syntax help failed: " + (sentMessages[0]?.text || ""));
  }

  // Syntax help on 1 arg
  await triggerMessage("/moveacc m109");
  if (!sentMessages[0]?.text.includes("Cú pháp:") || !sentMessages[0]?.text.includes("/moveacc")) {
    throw new Error("moveacc syntax help on 1 arg failed: " + (sentMessages[0]?.text || ""));
  }

  // Same source and dest error
  await triggerMessage("/moveacc m109 m109");
  if (!sentMessages[0]?.text.includes("không được trùng nhau") || !sentMessages[0]?.text.includes("M109 = M109")) {
    throw new Error("moveacc source==dest validation failed: " + (sentMessages[0]?.text || ""));
  }

  // Invalid count errors (0 or string)
  await triggerMessage("/moveacc m109 m77 0");
  if (!sentMessages[0]?.text.includes("số nguyên dương")) {
    throw new Error("moveacc count=0 validation failed: " + (sentMessages[0]?.text || ""));
  }
  await triggerMessage("/moveacc m109 m77 abc");
  if (!sentMessages[0]?.text.includes("số nguyên dương")) {
    throw new Error("moveacc count=abc validation failed: " + (sentMessages[0]?.text || ""));
  }

  // Offline fleet error
  const origResolve = env.resolveAndValidateTelegramTargets;
  try {
    env.resolveAndValidateTelegramTargets = async () => [];
    await triggerMessage("/moveacc m109 m77 1");
    if (!sentMessages[0]?.text.includes("KHÔNG CÓ THIẾT BỊ NÀO ONLINE")) {
      throw new Error("moveacc offline fleet check failed: " + (sentMessages[0]?.text || ""));
    }
  } finally {
    env.resolveAndValidateTelegramTargets = origResolve;
  }

  // Successful dispatch with count
  await triggerMessage("/moveacc m109 m77 2");
  const moveaccCall = fleetControlCalls.at(-1);
  if (moveaccCall?.kind !== "move_acc" || moveaccCall?.source_m !== "M109" || moveaccCall?.target_m !== "M77" || moveaccCall?.count !== 2) {
    throw new Error("moveacc dispatch test failed: " + JSON.stringify(moveaccCall));
  }
  if (!sentMessages[0]?.text.includes("ĐÃ XẾP LỆNH ĐIỀU CHUYỂN TÀI KHOẢN") ||
      !sentMessages[0]?.text.includes("M109") ||
      !sentMessages[0]?.text.includes("M77") ||
      !sentMessages[0]?.text.includes("2") ||
      sentMessages[0]?.parse_mode !== "HTML") {
    throw new Error("moveacc confirmation text failed: " + (sentMessages[0]?.text || ""));
  }

  // Successful dispatch with default count 1 and alias /chuyenacc
  await triggerMessage("/chuyenacc m109 m77");
  const chuyenaccCall = fleetControlCalls.at(-1);
  if (chuyenaccCall?.kind !== "move_acc" || chuyenaccCall?.source_m !== "M109" || chuyenaccCall?.target_m !== "M77" || chuyenaccCall?.count !== 1) {
    throw new Error("chuyenacc default count dispatch test failed: " + JSON.stringify(chuyenaccCall));
  }

  // 17. Help command
  await triggerMessage("/help");
  if (!sentMessages[0]?.text.includes("DANH SÁCH LỆNH PREIUMBOT") || !sentMessages[0]?.text.includes("/delacc") || !sentMessages[0]?.text.includes("/moveacc")) {
    throw new Error("help command output failed: " + (sentMessages[0]?.text || ""));
  }

  // 18. Anti-bot webhook echo prevention check (Rule 10)
  sentMessages = [];
  const beforeControlLen = fleetControlCalls.length;
  await handleUpdate({
    message: {
      from: { id: "123", is_bot: true },
      chat: { id: 1 },
      text: "/checkban m1"
    }
  }, env);
  if (sentMessages.length > 0 || fleetControlCalls.length !== beforeControlLen) {
    throw new Error("anti-bot echo check failed: bot message was not ignored");
  }

  answeredCallbacks = [];
  await handleUpdate({
    callback_query: {
      id: "cb_bot",
      from: { id: "123", is_bot: true },
      message: { chat: { id: 1 }, message_id: 99 },
      data: "cancel"
    }
  }, env);
  if (answeredCallbacks.length > 0) {
    throw new Error("anti-bot echo check failed: bot callback was not ignored");
  }

  // 19. Worker /delta/manifest release fallback test (debugError -> error?.message || String(error))
  const origFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => { throw new Error("GitHub Network Timeout Mock"); };
    const req = new Request("https://worker.local/delta/manifest");
    const resp = await worker.fetch(req, env);
    if (resp.status !== 200) throw new Error("Worker fallback returned status: " + resp.status);
    const body = await resp.json();
    if (body.channel !== "delta" || !body.debug_error || !body.debug_error.includes("GitHub Network Timeout Mock")) {
      throw new Error("Worker fallback debug_error failed: " + JSON.stringify(body));
    }

    // Fallback when GitHub responds with non-ok HTTP status (e.g. 502)
    globalThis.fetch = async () => ({ ok: false, status: 502 });
    const resp2 = await worker.fetch(req, env);
    const body2 = await resp2.json();
    if (!body2.debug_error || !body2.debug_error.includes("502")) {
      throw new Error("Worker fallback 502 status failed: " + JSON.stringify(body2));
    }
  } finally {
    globalThis.fetch = origFetch;
  }

  // 20. FleetState HTML checkban reporting test with replace_result and Rule 34 Google Drive sync
  class MockTelegramStorage {
    constructor() { this.store = new Map(); }
    async get(key) { return this.store.get(key); }
    async put(key, value) { this.store.set(key, JSON.parse(JSON.stringify(value))); }
  }
  let lastTelegramReport = null;
  const fsEnv = {
    TEST_ENV: true,
    TELEGRAM_BOT_TOKEN: "mock-token",
    TELEGRAM_ADMIN_USER_ID: "123"
  };
  const fsCtx = {
    storage: new MockTelegramStorage(),
    sockets: new Map(),
    getWebSockets() { return []; }
  };
  const fsFleet = new FleetState(fsCtx, fsEnv);
  const origFetchFs = globalThis.fetch;
  try {
    globalThis.fetch = async (url, init) => {
      if (url.includes("api.telegram.org")) {
        lastTelegramReport = JSON.parse(init.body);
        return { ok: true, json: async () => ({ ok: true }) };
      }
      return { ok: true, json: async () => ({}) };
    };

    // Register device m1 and queue checkban
    await fsFleet.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      body: JSON.stringify({ device_id: "m1", device_group: "NOVA", capabilities: ["check_ban"] })
    }));
    const qRes = await (await fsFleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"], telegram_chat_id: 123 })
    }))).json();
    const actionId = qRes.checkban.action_id;

    // Acknowledge checkban with replace_result and Rule 34 sync
    const ackRes = await (await fsFleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CHECK_BAN",
        device_id: "m1",
        action_id: actionId,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          target: "M77",
          total: 10,
          live: 8,
          banned: 2,
          error: 0,
          banned_list: ["banned_user_1", "banned_user_2"],
          clean_result: { removed_from_acc: 2, archived_cookies_count: 2 },
          replace_result: { replaced_count: 2, remaining_reserve_count: 10, replaced_accounts: ["rep1", "rep2"] },
          sync_result: { acc_sync: true, data_tong_sync: true, rule34_verified: true }
        })
      })
    }))).json();

    if (!ackRes.ok) throw new Error("FleetState checkban ack failed: " + JSON.stringify(ackRes));
    if (!lastTelegramReport?.text?.includes("🔄 <b>Nạp bù dự phòng</b>: Đã tự động nạp <b>2</b> acc từ kho dự trữ vào máy") ||
        !lastTelegramReport?.text?.includes("Kho còn lại: <b>10</b>")) {
      throw new Error("FleetState checkban replace_result reporting failed: " + JSON.stringify(lastTelegramReport));
    }
    if (!lastTelegramReport?.text?.includes("Google Drive") || !lastTelegramReport?.text?.includes("Rule 34")) {
      throw new Error("FleetState checkban Rule 34 reporting failed: " + JSON.stringify(lastTelegramReport));
    }

    // Queue and acknowledge delacc
    const qDelRes = await (await fsFleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "del_acc", m_code: "m77", usernames: ["testuser"], target_device_ids: ["m1"], telegram_chat_id: 123 })
    }))).json();
    const delActionId = qDelRes.delacc.action_id;

    const delAckRes = await (await fsFleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "DEL_ACC",
        device_id: "m1",
        action_id: delActionId,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          target: "M77",
          deleted_usernames: ["testuser"],
          removed_from_acc: 1,
          removed_from_data_tong: 1,
          sync_result: { acc_sync: true, data_tong_sync: true, rule34_verified: true }
        })
      })
    }))).json();

    if (!delAckRes.ok) throw new Error("FleetState delacc ack failed: " + JSON.stringify(delAckRes));
    if (!lastTelegramReport?.text?.includes("XÓA TÀI KHOẢN THÀNH CÔNG") ||
        !lastTelegramReport?.text?.includes("testuser")) {
      throw new Error("FleetState delacc reporting failed: " + JSON.stringify(lastTelegramReport));
    }

    // 21. FleetState HTML moveacc reporting test (success with counts, accounts list, Rule 34 sync, and failure alert)
    const qMoveRes = await (await fsFleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "move_acc",
        source_m: "M109",
        target_m: "M77",
        count: 2,
        target_device_ids: ["m1"],
        telegram_chat_id: 123
      })
    }))).json();
    const moveActionId = qMoveRes.moveacc.action_id;

    // Acknowledge moveacc success with details
    const moveAckRes = await (await fsFleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "MOVE_ACC",
        device_id: "m1",
        action_id: moveActionId,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          source_m: "M109",
          target_m: "M77",
          count: 2,
          moved_accounts: ["UserA", "UserB"],
          source_remaining_count: 5,
          target_current_count: 8,
          sync_result: { acc_sync: true, rule34_verified: true }
        })
      })
    }))).json();

    if (!moveAckRes.ok) throw new Error("FleetState moveacc ack failed: " + JSON.stringify(moveAckRes));
    if (!lastTelegramReport?.text?.includes("ĐIỀU CHUYỂN TÀI KHOẢN THÀNH CÔNG") ||
        !lastTelegramReport?.text?.includes("UserA") ||
        !lastTelegramReport?.text?.includes("UserB") ||
        !lastTelegramReport?.text?.includes("Còn lại ở <b>M109</b>: <b>5</b> tài khoản") ||
        !lastTelegramReport?.text?.includes("Hiện có ở <b>M77</b>: <b>8</b> tài khoản") ||
        !lastTelegramReport?.text?.includes("Rule 34")) {
      throw new Error("FleetState moveacc success HTML reporting failed: " + JSON.stringify(lastTelegramReport));
    }

    // Acknowledge moveacc failure
    const qMoveFailRes = await (await fsFleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "move_acc",
        source_m: "M109",
        target_m: "M77",
        count: 1,
        target_device_ids: ["m1"],
        telegram_chat_id: 123
      })
    }))).json();
    const failActionId = qMoveFailRes.moveacc.action_id;

    const moveFailAck = await (await fsFleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "MOVE_ACC",
        device_id: "m1",
        action_id: failActionId,
        status: "FAILED",
        executed: false,
        reason: "Dàn máy nguồn M109 không còn tài khoản nào."
      })
    }))).json();

    if (!moveFailAck.ok) throw new Error("FleetState moveacc failure ack failed: " + JSON.stringify(moveFailAck));
    if (!lastTelegramReport?.text?.includes("ĐIỀU CHUYỂN TÀI KHOẢN THẤT BẠI") ||
        !lastTelegramReport?.text?.includes("Dàn máy nguồn M109 không còn tài khoản nào")) {
      throw new Error("FleetState moveacc failure HTML reporting failed: " + JSON.stringify(lastTelegramReport));
    }

    // Tab list test: Telegram command /tablist
    fleetControlCalls = [];
    await triggerMessage("/tablist");
    if (fleetControlCalls.length === 0 || fleetControlCalls[fleetControlCalls.length - 1].kind !== "tab_list") {
      throw new Error("/tablist did not queue tab_list action: " + JSON.stringify(fleetControlCalls));
    }
    if (!sentMessages.some(m => m.text?.includes("ĐÃ XẾP LỆNH LẤY DANH SÁCH TAB"))) {
      throw new Error("/tablist response missing queuing message: " + JSON.stringify(sentMessages));
    }

    // Tab list test: FleetState queueTabList and acknowledgeTabList
    const qTabRes = await (await fsFleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "tab_list",
        target_device_ids: ["m1"],
        telegram_chat_id: 123
      })
    }))).json();
    if (!qTabRes.ok || !qTabRes.tablist?.action_id) {
      throw new Error("FleetState tablist queue failed: " + JSON.stringify(qTabRes));
    }
    const tabActionId = qTabRes.tablist.action_id;

    const tabAckRes = await (await fsFleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "TAB_LIST",
        device_id: "m1",
        action_id: tabActionId,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          tabs: [
            { tab: 1, package: "com.tinh.vv.hi", username: "username_a" },
            { tab: 2, package: "com.tinh.vv.hj", username: "username_b" },
            { tab: 3, package: "com.tinh.vv.hk", username: null }
          ]
        })
      })
    }))).json();
    if (!tabAckRes.ok) throw new Error("FleetState tablist ack failed: " + JSON.stringify(tabAckRes));

    const expectedHtml = `📱 <b>Tab List — M1</b>\nTab 1: username_a\nTab 2: username_b\nTab 3: ❓ (unknown)`;
    if (!lastTelegramReport?.text || !lastTelegramReport.text.includes(expectedHtml)) {
      throw new Error("FleetState tablist report HTML format mismatch. Got:\n" + lastTelegramReport?.text + "\nExpected:\n" + expectedHtml);
    }

    // Test: /tablist with specific offline target should NOT silently fallback
    sentMessages = [];
    const origResolveTargets = env.resolveAndValidateTelegramTargets;
    try {
      env.resolveAndValidateTelegramTargets = async (t) => {
        if (t === "m72") throw new Error("Thiết bị m72 đang OFFLINE.");
        return ["m1"];
      };
      await triggerMessage("/tablist m72");
      if (!sentMessages.some(m => m.text?.includes("Thiết bị m72 đang OFFLINE"))) {
        throw new Error("/tablist m72 offline validation failed. Got: " + JSON.stringify(sentMessages));
      }
    } finally {
      env.resolveAndValidateTelegramTargets = origResolveTargets;
    }

    // Test: /tablist with no devices online
    sentMessages = [];
    try {
      env.resolveAndValidateTelegramTargets = async () => [];
      await triggerMessage("/tablist");
      if (!sentMessages.some(m => m.text?.includes("Không có thiết bị nào đang ONLINE"))) {
        throw new Error("/tablist no online devices check failed. Got: " + JSON.stringify(sentMessages));
      }
    } finally {
      env.resolveAndValidateTelegramTargets = origResolveTargets;
    }

    // Test: Sorting and unknown filtering in acknowledgeTabList
    const qTabRes2 = await (await fsFleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "tab_list",
        target_device_ids: ["m1"],
        telegram_chat_id: 123
      })
    }))).json();
    const tabActionId2 = qTabRes2.tablist.action_id;

    lastTelegramReport = null;
    await fsFleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "TAB_LIST",
        device_id: "m1",
        action_id: tabActionId2,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          tabs: [
            { tab: 2, package: "com.tinh.vv.hj", username: "None" },
            { tab: 1, package: "com.tinh.vv.hi", username: "player_one" },
            { tab: 3, package: "com.tinh.vv.hk", username: "null" }
          ]
        })
      })
    }));
    const expectedHtml2 = `📱 <b>Tab List — M1</b>\nTab 1: player_one\nTab 2: ❓ (unknown)\nTab 3: ❓ (unknown)`;
    if (!lastTelegramReport?.text || !lastTelegramReport.text.includes(expectedHtml2)) {
      throw new Error("acknowledgeTabList sort & unknown filtering failed. Got:\n" + lastTelegramReport?.text);
    }

    // Test: Rapid concurrent queueTabList replaces un-delivered actions to avoid queue bloat
    const q1 = await (await fsFleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "tab_list", target_device_ids: ["m1"], telegram_chat_id: 123 })
    }))).json();
    const q2 = await (await fsFleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "tab_list", target_device_ids: ["m1"], telegram_chat_id: 123 })
    }))).json();
    const fleetRec = await fsFleet.readFleet();
    const pendingTabCmds = (fleetRec.pending_actions["m1"] || []).filter(c => c.action === "TAB_LIST" && !c.delivered_at && !c.acknowledged_at);
    if (pendingTabCmds.length !== 1 || pendingTabCmds[0].action_id !== q2.tablist.action_id) {
      throw new Error("Rapid queueTabList replacement failed. Pending count: " + pendingTabCmds.length);
    }

    // Test: Robustness against null/malformed tab items and HTML escaping of special characters
    const qTabRes3 = await (await fsFleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "tab_list", target_device_ids: ["m1"], telegram_chat_id: 123 })
    }))).json();
    const tabActionId3 = qTabRes3.tablist.action_id;

    lastTelegramReport = null;
    await fsFleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "TAB_LIST",
        device_id: "m1",
        action_id: tabActionId3,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          tabs: [
            null, // Malformed null entry
            { tab: 1, package: "com.tinh.vv.hi", username: "gamer<123>&pro" },
            undefined, // Malformed undefined entry
            { tab: 2, package: "com.tinh.vv.hj", username: "<b>fake_tag</b>" }
          ]
        })
      })
    }));
    const expectedHtml3 = `📱 <b>Tab List — M1</b>\nTab 1: gamer&lt;123&gt;&amp;pro\nTab 2: &lt;b&gt;fake_tag&lt;/b&gt;`;
    if (!lastTelegramReport?.text || !lastTelegramReport.text.includes(expectedHtml3)) {
      throw new Error("HTML escaping / null resilience failed. Got:\n" + lastTelegramReport?.text);
    }

    // Test: Large tab list (200 tabs) is safely bounded within Telegram's 4096 character limit
    const qTabRes4 = await (await fsFleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "tab_list", target_device_ids: ["m1"], telegram_chat_id: 123 })
    }))).json();
    const tabActionId4 = qTabRes4.tablist.action_id;

    const hugeTabs = [];
    for (let i = 1; i <= 200; i++) {
      hugeTabs.push({ tab: i, package: `com.tinh.vv.clone${i}`, username: `VeryLongRobloxPlayerNameNumber_${i}` });
    }
    lastTelegramReport = null;
    await fsFleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "TAB_LIST",
        device_id: "m1",
        action_id: tabActionId4,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({ tabs: hugeTabs })
      })
    }));
    if (!lastTelegramReport?.text || lastTelegramReport.text.length > 4000) {
      throw new Error("Large tab list exceeded safe message length bound: length=" + lastTelegramReport?.text?.length);
    }
    if (!lastTelegramReport.text.includes("... và còn")) {
      throw new Error("Large tab list missing truncation notice. Got:\n" + lastTelegramReport.text.slice(-200));
    }

    // Test: Corrupted / malformed JSON string in details should report format warning, NOT falsely claim 0 tabs
    const qTabRes5 = await (await fsFleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "tab_list", target_device_ids: ["m1"], telegram_chat_id: 123 })
    }))).json();
    const tabActionId5 = qTabRes5.tablist.action_id;

    lastTelegramReport = null;
    await fsFleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "TAB_LIST",
        device_id: "m1",
        action_id: tabActionId5,
        status: "OPENED",
        executed: true,
        details: "{malformed_json_syntax_error"
      })
    }));
    if (!lastTelegramReport?.text || !lastTelegramReport.text.includes("Dữ liệu tab phản hồi không đúng định dạng")) {
      throw new Error("Corrupted details handling failed. Got:\n" + lastTelegramReport?.text);
    }

    // Test: Malformed tabNum with HTML characters and array element in tabs
    const qTabRes6 = await (await fsFleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "tab_list", target_device_ids: ["m1"], telegram_chat_id: 123 })
    }))).json();
    const tabActionId6 = qTabRes6.tablist.action_id;

    lastTelegramReport = null;
    await fsFleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "TAB_LIST",
        device_id: "m1",
        action_id: tabActionId6,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          tabs: [
            ["should_be_filtered_array"],
            { tab: "1<special>", username: "safe_user" }
          ]
        })
      })
    }));
    if (!lastTelegramReport?.text || !lastTelegramReport.text.includes("Tab 1&lt;special&gt;: safe_user")) {
      throw new Error("tabNum HTML escaping failed. Got:\n" + lastTelegramReport?.text);
    }

    // Test: /tablist with multiple targets should reject with clear single-device message
    sentMessages = [];
    await triggerMessage("/tablist m1,m2");
    if (!sentMessages.some(m => m.text?.includes("Lệnh /tablist chỉ hỗ trợ tra cứu từng thiết bị một"))) {
      throw new Error("/tablist multi-device rejection failed. Got: " + JSON.stringify(sentMessages));
    }

    // Test: /TABLIST M1 case insensitivity
    sentMessages = [];
    await triggerMessage("/TABLIST M1");
    if (!sentMessages.some(m => m.text?.includes("ĐÃ XẾP LỆNH LẤY DANH SÁCH TAB") && m.text?.includes("M1"))) {
      throw new Error("/TABLIST M1 case insensitivity failed. Got: " + JSON.stringify(sentMessages));
    }
  } finally {
    globalThis.fetch = origFetchFs;
  }

  console.log("TEST_TELEGRAM_PHANSERVER_EQUIVALENCE=OK");
}

runTests().catch(e => { console.error(e); process.exit(1); });

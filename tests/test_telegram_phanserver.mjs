import { handleUpdate, handleCallback } from "../worker/phanserver.js";

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
      return { response: { ok: true }, data: { state: { devices: [{ device_id: "m1", online: isM1Online }], last_batch: { action_id: "act-123", devices: [{ device_id: "m1", status, history: ["SENT", status] }] } } } };
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
  if (!sentMessages[0]?.text.includes("m1: ONLINE")) {
    throw new Error("devices test failed: " + (sentMessages[0]?.text || ""));
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
  if (!sentMessages[0]?.text.includes("Đã xếp UPDATE_DELTA")) {
    throw new Error("update delta confirmation test failed: " + (sentMessages[0]?.text || ""));
  }

  // 8. Selective UPDATE_DELTA dispatch
  await triggerMessage("/update m1,m2 random");
  const updateCall2 = fleetControlCalls.at(-1);
  if (updateCall2?.kind !== "update_delta" || updateCall2?.selection !== "random") {
    throw new Error("selective update delta dispatch test failed: " + JSON.stringify(updateCall2));
  }
  if (!sentMessages[0]?.text.includes("Lựa chọn: random")) {
    throw new Error("selective update delta confirmation test failed: " + (sentMessages[0]?.text || ""));
  }

  // 9. APKs release list command
  await triggerMessage("/apks");
  if (!sentMessages[0]?.text.includes("DANH SÁCH APP TRONG RELEASE")) {
    throw new Error("apks list test failed: " + (sentMessages[0]?.text || ""));
  }

  console.log("TEST_TELEGRAM_PHANSERVER_EQUIVALENCE=OK");
}

runTests().catch(e => { console.error(e); process.exit(1); });

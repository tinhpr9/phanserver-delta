#!/usr/bin/env node
/**
 * Challenger 2 Adversarial Stress Testing Suite for Milestone M3.
 * Targets:
 * 1. Telegram Bot commands (/checkban, /addacc) in Worker & Durable Objects.
 * 2. Anti-webhook echo loop check: messages from bots (from.is_bot: true) ignored (Rule 10).
 * 3. HTML formatted reporting in FleetState DO (Tổng, Sống, Bị Ban, bolded Lỗi API,
 *    removed_from_acc, Nạp bù dự phòng with remaining count, Rule 34 Google Drive sync).
 * 4. Worker release manifest fallback without ReferenceError.
 * 5. Idempotency of batch actions (CHECK_BAN, ADD_ACC) across repeated heartbeats.
 */

import { handleUpdate } from "../worker/phanserver.js";
import worker from "../worker/worker.js";
import { FleetState } from "../worker/fleet_state.js";

// Global capture fixtures
let sentMessages = [];
let answeredCallbacks = [];
let fleetControlCalls = [];
let onlineDevicesList = ["m1"];

const mockEnv = {
  TELEGRAM_ADMIN_USER_ID: "999",
  TELEGRAM_BOT_TOKEN: "tok_adversarial",
  telegram: async (env, method, payload) => {
    if (method === "sendMessage" || method === "editMessageText") {
      sentMessages.push(payload);
    }
    return { ok: true, result: { message_id: sentMessages.length } };
  },
  answerCallback: async (id, env, text, alert) => {
    answeredCallbacks.push({ id, text, alert });
    return { ok: true };
  },
  resolveAndValidateTelegramTargets: async (targetStr, env) => {
    if (targetStr === "all" || targetStr === "*") {
      if (onlineDevicesList.length === 0) {
        throw new Error("Không có thiết bị nào đang ONLINE để thực hiện.");
      }
      return [...onlineDevicesList];
    }
    if (onlineDevicesList.includes(targetStr.toLowerCase())) {
      return [targetStr.toLowerCase()];
    }
    if (onlineDevicesList.length === 0) {
      throw new Error(`Thiết bị ${targetStr} đang OFFLINE.`);
    }
    return [onlineDevicesList[0]];
  },
  fleetStateCall: async (env, path, init = {}) => {
    if (path === "/aot/hub/control") {
      fleetControlCalls.push(init.body);
      return {
        response: { ok: true, status: 200 },
        data: {
          ok: true,
          checkban: { action_id: "cb-test-1" },
          addacc: { action_id: "aa-test-1" },
          batch: { action_id: "act-test-id", devices: [{ device_id: "m1", status: "SENT" }] }
        }
      };
    }
    if (path === "/aot/hub/state") {
      return {
        response: { ok: true, status: 200 },
        data: {
          ok: true,
          state: {
            devices: onlineDevicesList.map(id => ({ device_id: id, online: true, device_group: "NOVA" }))
          }
        }
      };
    }
    return { response: { ok: true, status: 200 }, data: {} };
  }
};

class MockDurableStorage {
  constructor() {
    this.store = new Map();
  }
  async get(key) {
    return this.store.get(key);
  }
  async put(key, value) {
    this.store.set(key, JSON.parse(JSON.stringify(value)));
  }
}

function createFleetInstance() {
  const storage = new MockDurableStorage();
  const ctx = {
    storage,
    sockets: new Map(),
    getWebSockets() { return []; }
  };
  const fsEnv = {
    TEST_ENV: true,
    TELEGRAM_BOT_TOKEN: "tok_fs",
    TELEGRAM_ADMIN_USER_ID: "999"
  };
  return new FleetState(ctx, fsEnv);
}

async function triggerMsg(text, senderId = "999", isBot = false) {
  sentMessages = [];
  await handleUpdate({
    message: {
      from: { id: senderId, is_bot: isBot },
      chat: { id: 12345 },
      text
    }
  }, mockEnv);
}

async function triggerCallback(data, senderId = "999", isBot = false) {
  answeredCallbacks = [];
  await handleUpdate({
    callback_query: {
      id: "cb_" + Date.now(),
      from: { id: senderId, is_bot: isBot },
      message: { chat: { id: 12345 }, message_id: 10 },
      data
    }
  }, mockEnv);
}

let passedCount = 0;
function assert(condition, description) {
  if (!condition) {
    console.error(`❌ FAILED: ${description}`);
    throw new Error(description);
  }
  passedCount++;
  console.log(`  ✓ ${description}`);
}

async function runAdversarialSuite() {
  console.log("==================================================================");
  console.log("   CHALLENGER 2: ADVERSARIAL STRESS TEST SUITE (MILESTONE M3)    ");
  console.log("==================================================================");

  // -------------------------------------------------------------------------
  // SECTION 1: Telegram Bot Commands (/checkban, /addacc)
  // -------------------------------------------------------------------------
  console.log("\n[1] Testing Telegram Bot Commands (/checkban, /addacc)...");

  // 1.1 /checkban defaults to "all"
  onlineDevicesList = ["m1"];
  fleetControlCalls = [];
  await triggerMsg("/checkban");
  assert(fleetControlCalls.length === 1, "/checkban triggers 1 hub control call");
  assert(fleetControlCalls[0].kind === "check_ban", "Control kind is check_ban");
  assert(fleetControlCalls[0].target === "all", "/checkban defaults to target 'all'");
  assert(sentMessages.length === 1 && sentMessages[0].text.includes("ĐÃ XẾP LỆNH CHECK BAN ROBLOX"), "/checkban confirms queuing");
  assert(sentMessages[0].parse_mode === "HTML", "/checkban confirmation uses parse_mode HTML");

  // 1.2 /checkban with whitespace padding
  fleetControlCalls = [];
  await triggerMsg("/checkban     ");
  assert(fleetControlCalls[0]?.target === "all", "/checkban with trailing whitespace defaults to 'all'");

  // 1.3 /checkban with specific machine code
  fleetControlCalls = [];
  await triggerMsg("/checkban m77");
  assert(fleetControlCalls[0]?.target === "m77", "/checkban m77 sets target 'm77'");

  // 1.4 /checkban with multi-username target
  fleetControlCalls = [];
  await triggerMsg("/checkban alpha beta gamma");
  assert(fleetControlCalls[0]?.target === "alpha beta gamma", "/checkban with usernames sets target string");

  // 1.5 /kiemtraban alias
  fleetControlCalls = [];
  await triggerMsg("/kiemtraban m99");
  assert(fleetControlCalls[0]?.kind === "check_ban" && fleetControlCalls[0]?.target === "m99", "/kiemtraban alias works identically to /checkban");

  // 1.6 Case insensitivity
  fleetControlCalls = [];
  await triggerMsg("/CHECKBAN ALL");
  assert(fleetControlCalls[0]?.kind === "check_ban", "/CHECKBAN uppercase command recognized");
  fleetControlCalls = [];
  await triggerMsg("/KiemTraBan m12");
  assert(fleetControlCalls[0]?.kind === "check_ban", "/KiemTraBan mixed-case alias recognized");

  // 1.7 /checkban when no devices are online -> HTML warning, zero crashes
  onlineDevicesList = [];
  fleetControlCalls = [];
  await triggerMsg("/checkban m77");
  assert(fleetControlCalls.length === 0, "/checkban with no online devices makes 0 DO calls");
  assert(sentMessages.length === 1 && sentMessages[0].text.includes("KHÔNG CÓ THIẾT BỊ NÀO ONLINE"), "/checkban returns friendly HTML offline warning");
  assert(sentMessages[0].parse_mode === "HTML", "Offline warning uses HTML parse mode");
  onlineDevicesList = ["m1"]; // restore

  // 1.8 /addacc with no arguments -> syntax instructions
  fleetControlCalls = [];
  await triggerMsg("/addacc");
  assert(fleetControlCalls.length === 0, "/addacc with empty args makes 0 DO calls");
  assert(sentMessages[0]?.text.includes("Cú pháp:") && sentMessages[0]?.text.includes("user:pass"), "/addacc empty args prompts syntax");

  // 1.9 /addacc m77 (missing accounts) -> syntax instructions
  fleetControlCalls = [];
  await triggerMsg("/addacc m77");
  assert(fleetControlCalls.length === 0, "/addacc without accounts makes 0 DO calls");
  assert(sentMessages[0]?.text.includes("Cú pháp:"), "/addacc missing accounts prompts syntax");

  // 1.10 /addacc m77 invalid_account (no colon) -> format error
  fleetControlCalls = [];
  await triggerMsg("/addacc m77 invalid_without_colon");
  assert(fleetControlCalls.length === 0, "/addacc with colon-less account makes 0 DO calls");
  assert(sentMessages[0]?.text.includes("Định dạng tài khoản không hợp lệ"), "/addacc invalid account rejects format");

  // 1.11 /addacc m77 valid account -> queues add_acc
  fleetControlCalls = [];
  await triggerMsg("/addacc m77 user1:pass1");
  assert(fleetControlCalls.length === 1, "/addacc queues batch control");
  assert(fleetControlCalls[0].kind === "add_acc", "Control kind is add_acc");
  assert(fleetControlCalls[0].m_code === "m77", "m_code set to m77");
  assert(Array.isArray(fleetControlCalls[0].lines) && fleetControlCalls[0].lines[0] === "user1:pass1", "lines contain user1:pass1");
  assert(sentMessages[0]?.text.includes("ĐÃ XẾP LỆNH NẠP TÀI KHOẢN"), "/addacc confirms queuing");
  assert(sentMessages[0]?.parse_mode === "HTML", "/addacc confirmation uses HTML parse mode");

  // 1.12 /addacc with multiple accounts, extra spaces, and newlines
  fleetControlCalls = [];
  await triggerMsg("/addacc   M77   \n  u1:p1 \t  u2:p2 \n u3:p3  ");
  assert(fleetControlCalls[0]?.m_code === "M77", "m_code extracted across whitespace");
  assert(fleetControlCalls[0]?.lines.length === 3, "Parsed exactly 3 accounts from whitespace/newline mess");
  assert(fleetControlCalls[0]?.lines[1] === "u2:p2", "Account 2 parsed correctly");

  // 1.13 /themacc alias
  fleetControlCalls = [];
  await triggerMsg("/themacc m88 u:p");
  assert(fleetControlCalls[0]?.kind === "add_acc" && fleetControlCalls[0]?.m_code === "m88", "/themacc alias functions identically");

  // 1.14 /addacc when no devices are online -> friendly error
  onlineDevicesList = [];
  fleetControlCalls = [];
  await triggerMsg("/addacc m77 u:p");
  assert(fleetControlCalls.length === 0, "/addacc offline makes 0 DO calls");
  assert(sentMessages[0]?.text.includes("KHÔNG CÓ THIẾT BỊ NÀO ONLINE"), "/addacc returns offline warning");
  onlineDevicesList = ["m1"]; // restore

  // 1.15 Non-admin message rejection
  fleetControlCalls = [];
  await triggerMsg("/checkban", "attacker_id");
  assert(fleetControlCalls.length === 0 && sentMessages.length === 0, "Unauthorized sender message completely ignored");

  // 1.16 Malformed updates
  sentMessages = [];
  await handleUpdate({ message: null }, mockEnv);
  await handleUpdate({ message: { chat: { id: 123 }, text: null } }, mockEnv);
  await handleUpdate({ message: { chat: null } }, mockEnv);
  assert(sentMessages.length === 0, "Malformed updates handled without throwing unhandled errors");

  // -------------------------------------------------------------------------
  // SECTION 2: Anti-Webhook Echo Loop Check (Rule 10)
  // -------------------------------------------------------------------------
  console.log("\n[2] Testing Anti-Webhook Echo Loop Check (Rule 10)...");

  // 2.1 Bot sender in message
  fleetControlCalls = [];
  sentMessages = [];
  await triggerMsg("/checkban", "999", true); // isBot = true
  assert(fleetControlCalls.length === 0, "Bot message (/checkban) produces 0 DO calls");
  assert(sentMessages.length === 0, "Bot message (/checkban) produces 0 Telegram outgoing messages");

  await triggerMsg("/addacc m1 u:p", "999", true);
  assert(fleetControlCalls.length === 0 && sentMessages.length === 0, "Bot message (/addacc) 100% ignored");

  await triggerMsg("/status", "999", true);
  assert(sentMessages.length === 0, "Bot message (/status) 100% ignored");

  await triggerMsg("/update", "999", true);
  assert(sentMessages.length === 0, "Bot message (/update) 100% ignored");

  await triggerMsg("/help", "999", true);
  assert(sentMessages.length === 0, "Bot message (/help) 100% ignored");

  // 2.2 Bot sender in callback query
  answeredCallbacks = [];
  await triggerCallback("action_test", "999", true);
  assert(answeredCallbacks.length === 0, "Bot callback query 100% ignored (0 answerCallback calls)");

  // -------------------------------------------------------------------------
  // SECTION 3: FleetState Durable Object HTML Formatted Reporting
  // -------------------------------------------------------------------------
  console.log("\n[3] Testing FleetState DO HTML Formatted Reporting...");

  const origFetch = globalThis.fetch;
  let lastReport = null;
  globalThis.fetch = async (url, init) => {
    if (url.includes("api.telegram.org") && url.includes("sendMessage")) {
      lastReport = JSON.parse(init.body);
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };

  try {
    const fs = createFleetInstance();

    // Register test device m1
    await fs.handleHeartbeat(new Request("https://localhost/report", {
      method: "POST",
      body: JSON.stringify({ device_id: "m1", device_group: "NOVA", capabilities: ["check_ban", "add_acc"] })
    }));

    // 3.1 100% LIVE Report
    const q1 = await (await fs.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"], telegram_chat_id: 12345 })
    }))).json();
    const actId1 = q1.checkban.action_id;

    lastReport = null;
    await fs.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CHECK_BAN",
        device_id: "m1",
        action_id: actId1,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({ target: "M77", total: 10, live: 10, banned: 0, error: 0, banned_list: [] })
      })
    }));

    assert(lastReport !== null, "Telegram report dispatched for 100% LIVE");
    assert(lastReport.parse_mode === "HTML", "Telegram report uses parse_mode HTML");
    assert(lastReport.text.includes("📊 Tổng: <b>10</b> | 🟢 Sống: <b>10</b> | 🔴 Bị Ban: <b>0</b>"), "Stats line contains Tổng, Sống, Bị Ban formatted in bold");
    assert(lastReport.text.includes("✅ <b>Tất cả tài khoản đều HOẠT ĐỘNG TỐT (100% LIVE)!</b>"), "100% LIVE congratulatory header present");
    assert(!lastReport.text.includes("Lỗi API"), "Zero error does not render Lỗi API block");

    // 3.2 Zero banned with API errors (asserting bolded <b>${errCount}</b>)
    const q2 = await (await fs.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"], telegram_chat_id: 12345 })
    }))).json();
    const actId2 = q2.checkban.action_id;

    lastReport = null;
    await fs.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CHECK_BAN",
        device_id: "m1",
        action_id: actId2,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({ target: "M77", total: 10, live: 7, banned: 0, error: 3, banned_list: [] })
      })
    }));

    assert(lastReport.text.includes("| ⚠️ Lỗi API: <b>3</b>"), "Stats line contains bolded Lỗi API count");
    assert(lastReport.text.includes("⚠️ Không phát hiện tài khoản bị ban, nhưng có <b>3</b> tài khoản gặp lỗi tra cứu API."), "Error summary renders bolded error count");

    // 3.3 Full Ban + clean_result + replace_result with remaining count + Rule 34 Google Drive sync
    const q3 = await (await fs.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"], telegram_chat_id: 12345 })
    }))).json();
    const actId3 = q3.checkban.action_id;

    lastReport = null;
    await fs.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CHECK_BAN",
        device_id: "m1",
        action_id: actId3,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          target: "M77",
          total: 12,
          live: 9,
          banned: 3,
          error: 0,
          banned_list: ["banned_alpha", "banned_beta", "banned_gamma"],
          clean_result: { removed_from_acc: 3, archived_cookies_count: 3 },
          replace_result: { replaced_count: 3, remaining_reserve_count: 50, replaced_accounts: ["rep1", "rep2", "rep3"] },
          sync_result: { acc_sync: true, data_tong_sync: true, rule34_verified: true }
        })
      })
    }));

    assert(lastReport.text.includes("🔴 Bị Ban: <b>3</b>"), "Banned count bolded in stats header");
    assert(lastReport.text.includes("• <code>banned_alpha</code>"), "Banned account 1 rendered in code block");
    assert(lastReport.text.includes("• <code>banned_beta</code>"), "Banned account 2 rendered in code block");
    assert(lastReport.text.includes("• <code>banned_gamma</code>"), "Banned account 3 rendered in code block");
    assert(lastReport.text.includes("🧹 Đã tự động gỡ <b>3</b> acc khỏi <code>acc.txt</code> & lưu trữ vào <code>acc_bi_ban.txt</code>."), "Clean result reports removed_from_acc count");
    assert(lastReport.text.includes("🔄 <b>Nạp bù dự phòng</b>: Đã tự động nạp <b>3</b> acc từ kho dự trữ vào máy (Kho còn lại: <b>50</b>)."), "Nạp bù dự phòng rendered with remaining reserve count");
    assert(lastReport.text.includes("☁️ <b>Google Drive</b>: Đã đồng bộ an toàn (Bảo toàn File ID gốc theo Rule 34)."), "Rule 34 Google Drive sync verified notice");

    // 3.4 Clean result fallback to banned when removed_from_acc is undefined
    const q4 = await (await fs.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"], telegram_chat_id: 12345 })
    }))).json();
    const actId4 = q4.checkban.action_id;

    lastReport = null;
    await fs.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CHECK_BAN",
        device_id: "m1",
        action_id: actId4,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          target: "M77",
          total: 5,
          live: 4,
          banned: 1,
          clean_result: { archived_cookies_count: 1 } // removed_from_acc undefined!
        })
      })
    }));
    assert(lastReport.text.includes("🧹 Đã tự động gỡ <b>1</b> acc khỏi <code>acc.txt</code>"), "removed_from_acc falls back cleanly to banned count");

    // 3.5 Replace result without remaining count
    const q5 = await (await fs.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"], telegram_chat_id: 12345 })
    }))).json();
    const actId5 = q5.checkban.action_id;

    lastReport = null;
    await fs.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CHECK_BAN",
        device_id: "m1",
        action_id: actId5,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          target: "M77",
          total: 5,
          live: 4,
          banned: 1,
          replace_result: { replaced_count: 1 } // remaining_reserve_count undefined
        })
      })
    }));
    assert(lastReport.text.includes("🔄 <b>Nạp bù dự phòng</b>: Đã tự động nạp <b>1</b> acc từ kho dự trữ vào máy."), "Replace message rendered without remaining count");
    assert(!lastReport.text.includes("Kho còn lại"), "No orphan 'Kho còn lại' text when count is undefined");

    // 3.6 Replace result with multi-section by_section structure
    const q6 = await (await fs.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "all", target_device_ids: ["m1"], telegram_chat_id: 12345 })
    }))).json();
    const actId6 = q6.checkban.action_id;

    lastReport = null;
    await fs.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CHECK_BAN",
        device_id: "m1",
        action_id: actId6,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          target: "ALL",
          total: 8,
          live: 6,
          banned: 2,
          replace_result: {
            replaced_count: 2,
            by_section: {
              "M1": { replaced_count: 1, remaining_reserve_count: 25 },
              "M2": { replaced_count: 1, remaining_reserve_count: 24 }
            }
          }
        })
      })
    }));
    assert(lastReport.text.includes("(Kho còn lại: <b>24</b>)"), "Remaining count properly extracted from by_section last entry");

    // 3.7 Google Drive sync error reporting
    const q7 = await (await fs.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"], telegram_chat_id: 12345 })
    }))).json();
    const actId7 = q7.checkban.action_id;

    lastReport = null;
    await fs.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CHECK_BAN",
        device_id: "m1",
        action_id: actId7,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          target: "M77",
          total: 5,
          live: 5,
          sync_result: { error: "Google Drive OAuth token expired" }
        })
      })
    }));
    assert(lastReport.text.includes("⚠️ Google Drive sync lỗi: <code>Google Drive OAuth token expired</code>"), "Drive sync error rendered cleanly in code tags");

    // 3.8 XSS / HTML injection escaping in target, username, and error message
    const q8 = await (await fs.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "<script>alert(1)</script>", target_device_ids: ["m1"], telegram_chat_id: 12345 })
    }))).json();
    const actId8 = q8.checkban.action_id;

    lastReport = null;
    await fs.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "CHECK_BAN",
        device_id: "m1",
        action_id: actId8,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          target: "<script>alert('xss')</script>",
          total: 1,
          live: 0,
          banned: 1,
          banned_list: ["user<with>symbols&tags"],
          sync_result: { error: "<bad_xml>&error" }
        })
      })
    }));
    assert(!lastReport.text.includes("<script>"), "Hostile script tag in target is HTML-escaped");
    assert(lastReport.text.includes("&lt;script&gt;alert('xss')&lt;/script&gt;"), "Target is safely escaped");
    assert(lastReport.text.includes("user&lt;with&gt;symbols&amp;tags"), "Banned username with <, >, & is escaped");
    assert(lastReport.text.includes("&lt;bad_xml&gt;&amp;error"), "Sync error with <, > is escaped");

    // 3.9 ADD_ACC HTML Report with cookies and Rule 34 sync
    const qa1 = await (await fs.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "add_acc", m_code: "m77", lines: ["u1:p1", "u2:p2"], target_device_ids: ["m1"], telegram_chat_id: 12345 })
    }))).json();
    const actIdA1 = qa1.addacc.action_id;

    lastReport = null;
    await fs.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        batch_action: "ADD_ACC",
        device_id: "m1",
        action_id: actIdA1,
        status: "OPENED",
        executed: true,
        details: JSON.stringify({
          add: { m_code: "M77", added_count: 2, cookies_added: 2 },
          sync: { "acc.txt": "OK", "Data_Tong_Cookies.txt": "OK" }
        })
      })
    }));
    assert(lastReport !== null, "Telegram report dispatched for ADD_ACC");
    assert(lastReport.text.includes("➕ <b>THÊM TÀI KHOẢN THÀNH CÔNG!</b>"), "ADD_ACC success header present");
    assert(lastReport.text.includes("🎯 Dàn máy: <b>M77</b>"), "ADD_ACC reports machine code in bold");
    assert(lastReport.text.includes("✅ Đã thêm vào acc.txt: <b>2</b> tài khoản"), "ADD_ACC reports added_count in bold");
    assert(lastReport.text.includes("🔑 Cookie lưu vào Data_Tong: <b>2</b>"), "ADD_ACC reports cookies_added");
    assert(lastReport.text.includes("☁️ <b>Google Drive</b>: Đã đồng bộ an toàn (Bảo toàn File ID gốc theo Rule 34)."), "ADD_ACC reports Rule 34 sync success");

  } finally {
    globalThis.fetch = origFetch;
  }

  // -------------------------------------------------------------------------
  // SECTION 4: Worker Release Manifest Fallback Stability
  // -------------------------------------------------------------------------
  console.log("\n[4] Testing Worker Release Manifest Fallback Stability...");

  const origFetchWorker = globalThis.fetch;
  try {
    // 4.1 Network failure throws exception
    globalThis.fetch = async () => { throw new Error("Simulated GitHub Network Outage / DNS Failure"); };
    const req1 = new Request("https://worker.local/delta/manifest");
    const resp1 = await worker.fetch(req1, mockEnv);
    assert(resp1.status === 200, "Worker returns 200 OK on GitHub network exception");
    const body1 = await resp1.json();
    assert(body1.channel === "delta", "Manifest channel is delta");
    assert(body1.version === "1.0.0", "Fallback version is 1.0.0");
    assert(Array.isArray(body1.assets) && body1.assets.length > 0, "Fallback contains default assets");
    assert(typeof body1.debug_error === "string" && body1.debug_error.includes("Simulated GitHub Network Outage"), "debug_error cleanly populated without ReferenceError");

    // 4.2 Non-200 HTTP status (e.g. 503 Service Unavailable, 403 Forbidden)
    globalThis.fetch = async () => ({ ok: false, status: 503 });
    const resp2 = await worker.fetch(req1, mockEnv);
    assert(resp2.status === 200, "Worker returns 200 OK on GitHub 503");
    const body2 = await resp2.json();
    assert(body2.debug_error.includes("503"), "debug_error reports HTTP status 503");

    // 4.3 Empty releases array []
    globalThis.fetch = async () => ({ ok: true, json: async () => [] });
    const resp3 = await worker.fetch(req1, mockEnv);
    assert(resp3.status === 200, "Worker returns 200 OK on empty GitHub releases");
    const body3 = await resp3.json();
    assert(body3.debug_error === "No releases found", "debug_error notes 'No releases found'");

    // 4.4 Non-array JSON response (e.g. rate limit exceeded error)
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ message: "API rate limit exceeded" }) });
    const resp4 = await worker.fetch(req1, mockEnv);
    assert(resp4.status === 200, "Worker returns 200 OK on non-array JSON");
    const body4 = await resp4.json();
    assert(body4.debug_error === "No releases found", "debug_error handles non-array cleanly");

  } finally {
    globalThis.fetch = origFetchWorker;
  }

  // -------------------------------------------------------------------------
  // SECTION 5: Idempotency of Batch Actions (CHECK_BAN, ADD_ACC) Across Heartbeats
  // -------------------------------------------------------------------------
  console.log("\n[5] Testing Batch Actions Idempotency across Heartbeats & ACKs...");

  const fsIdem = createFleetInstance();

  // Register device m1
  await fsIdem.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA", capabilities: ["check_ban", "add_acc"] })
  }));

  // 5.1 CHECK_BAN delivery, redelivery before ACK, and non-redelivery after ACK
  const cbQ = await (await fsIdem.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "check_ban", target: "m77", target_device_ids: ["m1"] })
  }))).json();
  const cbActionId = cbQ.checkban.action_id;

  // Heartbeat 1: Delivers the command
  const hb1 = await (await fsIdem.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  assert(hb1.command?.action === "CHECK_BAN", "HB1 delivers CHECK_BAN");
  assert(hb1.command?.action_id === cbActionId, "HB1 command action_id matches");
  assert(hb1.command?.delivery_count === 1, "HB1 delivery_count is 1");

  // Heartbeat 2 before ACK: Re-delivers the pending command (retry)
  const hb2 = await (await fsIdem.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  assert(hb2.command?.action === "CHECK_BAN", "HB2 re-delivers in-flight CHECK_BAN");
  assert(hb2.command?.delivery_count === 2, "HB2 delivery_count is incremented to 2");

  // Device sends ACK
  const cbAck = await (await fsIdem.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "CHECK_BAN",
      device_id: "m1",
      action_id: cbActionId,
      status: "OPENED",
      executed: true,
      details: JSON.stringify({ target: "M77", total: 5, live: 5, banned: 0 })
    })
  }))).json();
  assert(cbAck.ok === true && cbAck.status === "OPENED", "CHECK_BAN ACK accepted with OPENED status");

  // Heartbeat 3 after ACK: Command is acknowledged, so NO command is delivered!
  const hb3 = await (await fsIdem.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  assert(hb3.command === null, "HB3 after ACK delivers null (no duplicate delivery)");

  // Heartbeat 4 after ACK: Command remains null!
  const hb4 = await (await fsIdem.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  assert(hb4.command === null, "HB4 after ACK continues to deliver null");

  // Duplicate ACK replay: Device or network sends same ACK again
  const cbDupAck = await (await fsIdem.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "CHECK_BAN",
      device_id: "m1",
      action_id: cbActionId,
      status: "OPENED",
      executed: true,
      details: JSON.stringify({ target: "M77", total: 5, live: 5, banned: 0 })
    })
  }))).json();
  assert(cbDupAck.ok === true, "Duplicate ACK handled gracefully without error");

  // 5.2 ADD_ACC delivery, redelivery before ACK, and non-redelivery after ACK
  const addQ = await (await fsIdem.controlFleetHub(new Request("https://localhost/aot/hub/control", {
    method: "POST",
    body: JSON.stringify({ protocol: "fleet-batch-v1", kind: "add_acc", m_code: "m77", lines: ["user:pass"], target_device_ids: ["m1"] })
  }))).json();
  const addActionId = addQ.addacc.action_id;

  // HB1 for ADD_ACC
  const hbA1 = await (await fsIdem.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  assert(hbA1.command?.action === "ADD_ACC", "HB1 delivers ADD_ACC");
  assert(hbA1.command?.action_id === addActionId, "HB1 ADD_ACC action_id matches");

  // HB2 before ACK
  const hbA2 = await (await fsIdem.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  assert(hbA2.command?.action === "ADD_ACC", "HB2 re-delivers in-flight ADD_ACC");

  // ACK ADD_ACC
  const addAck = await (await fsIdem.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "ADD_ACC",
      device_id: "m1",
      action_id: addActionId,
      status: "OPENED",
      executed: true,
      details: JSON.stringify({ add: { m_code: "M77", added_count: 1 }, sync: { "acc.txt": "OK" } })
    })
  }))).json();
  assert(addAck.ok === true && addAck.status === "OPENED", "ADD_ACC ACK accepted");

  // HB3 after ACK -> null
  const hbA3 = await (await fsIdem.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m1", device_group: "NOVA" })
  }))).json();
  assert(hbA3.command === null, "HB3 after ADD_ACC ACK delivers null");

  // Duplicate ACK for ADD_ACC
  const addDupAck = await (await fsIdem.dispatchFleetAck(new Request("https://localhost/aot/ack", {
    method: "POST",
    body: JSON.stringify({
      protocol: "fleet-batch-v1",
      batch_action: "ADD_ACC",
      device_id: "m1",
      action_id: addActionId,
      status: "OPENED",
      executed: true
    })
  }))).json();
  assert(addDupAck.ok === true, "Duplicate ADD_ACC ACK accepted cleanly");

  console.log("\n==================================================================");
  console.log(`  ALL CHALLENGER 2 ADVERSARIAL STRESS TESTS PASSED! (${passedCount}/${passedCount})`);
  console.log("==================================================================");
}

runAdversarialSuite().catch(err => {
  console.error("FATAL SUITE ERROR:", err);
  process.exit(1);
});

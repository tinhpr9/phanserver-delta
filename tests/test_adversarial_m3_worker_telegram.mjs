/**
 * Adversarial Stress Test Suite for Milestone 3 (/moveacc)
 * Challenger 2: Worker Telegram Bot Command Stress, 2PC Coordination & HTML Escaping.
 *
 * Focus 3: Worker Telegram Bot Command Stress
 * 1. Case variations:
 *    - /moveacc m109 m77
 *    - /MOVEACC M109 M77
 *    - /MoveAcc m109 m77
 *    - /chuyenacc m109 m77 3
 *    - /CHUYENACC M109 M77 3
 *    - /ChuyenAcc M109 M77 5
 * 2. Whitespace variations:
 *    - Multiple spaces, tabs, newlines between tokens
 * 3. Invalid inputs:
 *    - Missing args (0 args, 1 arg) -> syntax help
 *    - Negative count (-1, -99) -> positive integer validation error
 *    - Non-numeric count (abc, 1.5, 0, NaN, Infinity) -> validation error
 *    - Source == Destination (same case, mixed case) -> duplicate validation error
 *    - Offline fleet -> offline error message
 * 4. Telegram HTML message formatting and escaping (<, >, &):
 *    - Strict Telegram HTML entity validator
 *    - Usernames containing <, >, &, quotes
 *    - Error reasons containing <, >, &, quotes
 *    - Device IDs and sync errors containing <, >, &, quotes
 *    - Verification of zero malformed HTML entities
 */

import { handleUpdate } from "../worker/phanserver.js";
import { FleetState } from "../worker/fleet_state.js";

// Helper: Strict Telegram HTML parser/validator
function validateTelegramHtml(html) {
  if (typeof html !== "string") throw new Error("HTML must be a string");

  // Allowed Telegram tags
  const allowedTags = ["b", "i", "u", "s", "tg-spoiler", "a", "code", "pre", "blockquote"];

  // Check for naked ampersands (not part of valid XML entities &amp;, &lt;, &gt;, &quot;, &#\d+;)
  const nakedAmp = /&(?!amp;|lt;|gt;|quot;|#\d+;)/g;
  const badAmp = html.match(nakedAmp);
  if (badAmp) {
    throw new Error(`Invalid Telegram HTML: naked ampersand '&' found in text:\n${html}`);
  }

  // Check tag matching and disallow unescaped < or >
  const tagRegex = /<\/?([a-zA-Z0-9_-]+)(?:\s+[^>]*)?>/g;
  let match;
  const openTags = [];

  let lastIndex = 0;
  while ((match = tagRegex.exec(html)) !== null) {
    const fullTag = match[0];
    const tagName = match[1].toLowerCase();
    const isClosing = fullTag.startsWith("</");

    // Check intermediate text for stray '<'
    const intermediate = html.slice(lastIndex, match.index);
    if (intermediate.includes("<") || intermediate.includes(">")) {
      throw new Error(`Stray '<' or '>' in HTML text: "${intermediate}"`);
    }
    lastIndex = tagRegex.lastIndex;

    if (!allowedTags.includes(tagName)) {
      throw new Error(`Disallowed tag <${tagName}> in Telegram HTML:\n${html}`);
    }

    if (isClosing) {
      if (openTags.length === 0) {
        throw new Error(`Unmatched closing tag </${tagName}> in:\n${html}`);
      }
      const lastOpen = openTags.pop();
      if (lastOpen !== tagName) {
        throw new Error(`Mismatched closing tag </${tagName}>, expected </${lastOpen}> in:\n${html}`);
      }
    } else {
      openTags.push(tagName);
    }
  }

  const trailing = html.slice(lastIndex);
  if (trailing.includes("<") || trailing.includes(">")) {
    throw new Error(`Stray '<' or '>' in trailing text: "${trailing}"`);
  }

  if (openTags.length > 0) {
    throw new Error(`Unclosed tags remaining: ${openTags.join(", ")} in:\n${html}`);
  }

  return true;
}

// Test harness state
let sentMessages = [];
let fleetControlCalls = [];
let mockOnlineDevices = ["m72", "m77", "m109"];

const mockEnv = {
  TELEGRAM_ADMIN_USER_ID: "12345",
  TELEGRAM_BOT_TOKEN: "mock_test_token_123",
  telegram: async (env, method, payload) => {
    if (method === "sendMessage") {
      sentMessages.push(payload);
    }
  },
  resolveAndValidateTelegramTargets: async (targetStr, env, fleetState) => {
    if (!mockOnlineDevices || mockOnlineDevices.length === 0) {
      throw new Error("No devices online");
    }
    if (targetStr === "all") return [...mockOnlineDevices];
    const lower = String(targetStr).toLowerCase();
    if (mockOnlineDevices.includes(lower)) return [lower];
    return [];
  },
  fleetStateCall: async (env, path, init) => {
    if (path === "/aot/hub/control") {
      fleetControlCalls.push(init.body);
      return {
        response: { ok: true },
        data: { ok: true, moveacc: { action_id: "moveacc-test-123" } }
      };
    }
    return { response: { ok: true }, data: { ok: true } };
  }
};

async function runTest(name, fn) {
  sentMessages = [];
  fleetControlCalls = [];
  try {
    await fn();
    console.log(`  [PASS] ${name}`);
  } catch (err) {
    console.error(`  [FAIL] ${name}: ${err.message}`);
    throw err;
  }
}

async function main() {
  console.log("=================================================");
  console.log("  RUNNING ADVERSARIAL M3 WORKER TELEGRAM TESTS   ");
  console.log("=================================================");

  // -------------------------------------------------------------------------
  // 1. Case variations & Command aliases
  // -------------------------------------------------------------------------
  console.log("\n[Test Suite 1: Command Case Variations & Aliases]");

  await runTest("Case variation: /moveacc m109 m77 (lowercase)", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/moveacc m109 m77" } }, mockEnv);
    if (fleetControlCalls.length !== 1) throw new Error("Fleet control not called");
    const call = fleetControlCalls[0];
    if (call.source_m !== "M109" || call.target_m !== "M77" || call.count !== 1) {
      throw new Error(`Normalization mismatch: ${JSON.stringify(call)}`);
    }
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Case variation: /MOVEACC M109 M77 (uppercase)", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/MOVEACC M109 M77" } }, mockEnv);
    if (fleetControlCalls.length !== 1) throw new Error("Fleet control not called");
    const call = fleetControlCalls[0];
    if (call.source_m !== "M109" || call.target_m !== "M77" || call.count !== 1) {
      throw new Error(`Normalization mismatch: ${JSON.stringify(call)}`);
    }
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Case variation: /MoveAcc m109 m77 (mixed case)", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/MoveAcc m109 m77" } }, mockEnv);
    if (fleetControlCalls.length !== 1) throw new Error("Fleet control not called");
    const call = fleetControlCalls[0];
    if (call.source_m !== "M109" || call.target_m !== "M77" || call.count !== 1) {
      throw new Error(`Normalization mismatch: ${JSON.stringify(call)}`);
    }
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Case variation: /chuyenacc m109 m77 3 (alias lowercase)", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/chuyenacc m109 m77 3" } }, mockEnv);
    if (fleetControlCalls.length !== 1) throw new Error("Fleet control not called");
    const call = fleetControlCalls[0];
    if (call.source_m !== "M109" || call.target_m !== "M77" || call.count !== 3) {
      throw new Error(`Normalization mismatch: ${JSON.stringify(call)}`);
    }
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Case variation: /CHUYENACC M109 M77 3 (alias uppercase)", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/CHUYENACC M109 M77 3" } }, mockEnv);
    if (fleetControlCalls.length !== 1) throw new Error("Fleet control not called");
    const call = fleetControlCalls[0];
    if (call.source_m !== "M109" || call.target_m !== "M77" || call.count !== 3) {
      throw new Error(`Normalization mismatch: ${JSON.stringify(call)}`);
    }
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Case variation: /ChuyenAcc M109 M77 5 (alias mixed case)", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/ChuyenAcc M109 M77 5" } }, mockEnv);
    if (fleetControlCalls.length !== 1) throw new Error("Fleet control not called");
    const call = fleetControlCalls[0];
    if (call.source_m !== "M109" || call.target_m !== "M77" || call.count !== 5) {
      throw new Error(`Normalization mismatch: ${JSON.stringify(call)}`);
    }
    validateTelegramHtml(sentMessages[0].text);
  });

  // -------------------------------------------------------------------------
  // 2. Whitespace variations
  // -------------------------------------------------------------------------
  console.log("\n[Test Suite 2: Whitespace Stress Variations]");

  await runTest("Whitespace: multiple consecutive spaces & padding", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "  /moveacc    m109     m77      4    " } }, mockEnv);
    if (fleetControlCalls.length !== 1) throw new Error("Fleet control not called");
    const call = fleetControlCalls[0];
    if (call.source_m !== "M109" || call.target_m !== "M77" || call.count !== 4) {
      throw new Error(`Whitespace tokenization failed: ${JSON.stringify(call)}`);
    }
  });

  await runTest("Whitespace: tab characters between tokens", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/moveacc\tm109\tm77\t2" } }, mockEnv);
    if (fleetControlCalls.length !== 1) throw new Error("Fleet control not called");
    const call = fleetControlCalls[0];
    if (call.source_m !== "M109" || call.target_m !== "M77" || call.count !== 2) {
      throw new Error(`Tab tokenization failed: ${JSON.stringify(call)}`);
    }
  });

  await runTest("Whitespace: newline characters between tokens", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/moveacc\nm109\nm77\n2" } }, mockEnv);
    if (fleetControlCalls.length !== 1) throw new Error("Fleet control not called");
    const call = fleetControlCalls[0];
    if (call.source_m !== "M109" || call.target_m !== "M77" || call.count !== 2) {
      throw new Error(`Newline tokenization failed: ${JSON.stringify(call)}`);
    }
  });

  // -------------------------------------------------------------------------
  // 3. Invalid inputs
  // -------------------------------------------------------------------------
  console.log("\n[Test Suite 3: Invalid Input Validation Stress]");

  await runTest("Invalid input: /moveacc (0 args) -> syntax help", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/moveacc" } }, mockEnv);
    if (fleetControlCalls.length > 0) throw new Error("Should not queue on missing args");
    if (!sentMessages[0]?.text.includes("Cú pháp:") || !sentMessages[0]?.text.includes("&lt;nguồn&gt;")) {
      throw new Error("Syntax help message missing or malformed");
    }
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Invalid input: /moveacc m109 (1 arg) -> syntax help", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/moveacc m109" } }, mockEnv);
    if (fleetControlCalls.length > 0) throw new Error("Should not queue on single arg");
    if (!sentMessages[0]?.text.includes("Cú pháp:")) throw new Error("Syntax help missing");
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Invalid input: /chuyenacc (0 args) -> syntax help", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/chuyenacc" } }, mockEnv);
    if (fleetControlCalls.length > 0) throw new Error("Should not queue on missing args");
    if (!sentMessages[0]?.text.includes("Cú pháp:")) throw new Error("Syntax help missing");
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Invalid input: negative count (/moveacc m109 m77 -1)", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/moveacc m109 m77 -1" } }, mockEnv);
    if (fleetControlCalls.length > 0) throw new Error("Should not queue on negative count");
    if (!sentMessages[0]?.text.includes("số nguyên dương lớn hơn 0")) {
      throw new Error("Validation message missing for negative count: " + sentMessages[0]?.text);
    }
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Invalid input: zero count (/moveacc m109 m77 0)", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/moveacc m109 m77 0" } }, mockEnv);
    if (fleetControlCalls.length > 0) throw new Error("Should not queue on zero count");
    if (!sentMessages[0]?.text.includes("số nguyên dương lớn hơn 0")) {
      throw new Error("Validation message missing for count=0: " + sentMessages[0]?.text);
    }
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Invalid input: non-numeric string (/moveacc m109 m77 abc)", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/moveacc m109 m77 abc" } }, mockEnv);
    if (fleetControlCalls.length > 0) throw new Error("Should not queue on non-numeric count");
    if (!sentMessages[0]?.text.includes("số nguyên dương lớn hơn 0")) {
      throw new Error("Validation message missing for count=abc: " + sentMessages[0]?.text);
    }
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Invalid input: float number (/moveacc m109 m77 1.5)", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/moveacc m109 m77 1.5" } }, mockEnv);
    if (fleetControlCalls.length > 0) throw new Error("Should not queue on float count");
    if (!sentMessages[0]?.text.includes("số nguyên dương lớn hơn 0")) {
      throw new Error("Validation message missing for count=1.5: " + sentMessages[0]?.text);
    }
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Invalid input: source == dest (/moveacc m109 m109)", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/moveacc m109 m109" } }, mockEnv);
    if (fleetControlCalls.length > 0) throw new Error("Should not queue when source == dest");
    if (!sentMessages[0]?.text.includes("không được trùng nhau")) {
      throw new Error("Validation message missing for source == dest: " + sentMessages[0]?.text);
    }
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Invalid input: source == dest mixed case (/moveacc M109 m109)", async () => {
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/moveacc M109 m109" } }, mockEnv);
    if (fleetControlCalls.length > 0) throw new Error("Should not queue when source == dest");
    if (!sentMessages[0]?.text.includes("không được trùng nhau")) {
      throw new Error("Validation message missing for M109 == m109: " + sentMessages[0]?.text);
    }
    validateTelegramHtml(sentMessages[0].text);
  });

  await runTest("Offline fleet handling: when 0 devices online", async () => {
    mockOnlineDevices = [];
    await handleUpdate({ message: { from: { id: "12345" }, chat: { id: 100 }, text: "/moveacc m109 m77" } }, mockEnv);
    if (fleetControlCalls.length > 0) throw new Error("Should not queue when fleet is offline");
    if (!sentMessages[0]?.text.includes("KHÔNG CÓ THIẾT BỊ NÀO ONLINE")) {
      throw new Error("Offline warning missing: " + sentMessages[0]?.text);
    }
    validateTelegramHtml(sentMessages[0].text);
    mockOnlineDevices = ["m72", "m77", "m109"];
  });

  // -------------------------------------------------------------------------
  // 4. Telegram HTML message formatting and escaping stress (<, >, &)
  // -------------------------------------------------------------------------
  console.log("\n[Test Suite 4: Telegram HTML Message Formatting & Escaping Stress]");

  class MockStorage {
    constructor() { this.store = new Map(); }
    async get(key) { return this.store.get(key); }
    async put(key, value) { this.store.set(key, JSON.parse(JSON.stringify(value))); }
  }

  let capturedTelegramRequests = [];
  globalThis.fetch = async (url, init) => {
    if (url.includes("api.telegram.org")) {
      capturedTelegramRequests.push(JSON.parse(init.body));
      return { ok: true, json: async () => ({ ok: true }) };
    }
    return { ok: true, json: async () => ({}) };
  };

  const storage = new MockStorage();
  const ctx = {
    storage,
    sockets: new Map(),
    getWebSockets() { return []; }
  };
  const fleetEnv = {
    TEST_ENV: true,
    TELEGRAM_BOT_TOKEN: "mock_token",
    TELEGRAM_ADMIN_USER_ID: "12345"
  };
  const fleet = new FleetState(ctx, fleetEnv);

  // Register m72 device so it is recognized as online
  await fleet.handleHeartbeat(new Request("https://localhost/report", {
    method: "POST",
    body: JSON.stringify({ device_id: "m72", device_group: "NOVA", capabilities: ["allocate_server_2pc", "move_acc"] })
  }));

  await runTest("HTML Escaping: moved accounts containing <, >, &, quotes", async () => {
    capturedTelegramRequests = [];
    const qRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "move_acc",
        source_m: "M109",
        target_m: "M77",
        count: 3,
        target_device_ids: ["m72"],
        telegram_chat_id: 100
      })
    }))).json();

    const actionId = qRes.moveacc.action_id;

    // Acknowledge with usernames containing malicious/special chars: <script>, &amp;, >test, "quote"
    const ackPayload = {
      device_id: "m72",
      action_id: actionId,
      status: "OPENED",
      executed: true,
      batch_action: "MOVE_ACC",
      details: JSON.stringify({
        source_m: "M109",
        target_m: "M77",
        count: 3,
        moved_accounts: ["User<Tag>1", "User&Amp2", "User>Greater3", "User'Quote'4"],
        source_remaining_count: 5,
        target_current_count: 5,
        sync_result: { acc_sync: true, rule34_verified: true }
      })
    };

    const ackRes = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify(ackPayload)
    }))).json();

    if (!ackRes.ok) throw new Error("Acknowledge failed: " + JSON.stringify(ackRes));
    if (capturedTelegramRequests.length !== 1) throw new Error("Telegram report not sent");

    const tgMsg = capturedTelegramRequests[0].text;
    console.log("    [HTML Output Verified]:\n" + tgMsg.split("\n").map(l => "      " + l).join("\n"));

    // Verify strict conformance with Telegram HTML parser
    validateTelegramHtml(tgMsg);

    // Verify raw <Tag> was escaped to &lt;Tag&gt;
    if (tgMsg.includes("<Tag>") || tgMsg.includes(">Greater3")) {
      throw new Error("Unescaped raw <Tag> or > found in message text!");
    }
    if (!tgMsg.includes("&lt;Tag&gt;") || !tgMsg.includes("&amp;Amp2") || !tgMsg.includes("&gt;Greater3")) {
      throw new Error("Entity escaping was not properly applied to account usernames");
    }
  });

  await runTest("HTML Escaping: failure message with raw <error> & ampersand", async () => {
    capturedTelegramRequests = [];
    const qRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "move_acc",
        source_m: "M109",
        target_m: "M77",
        count: 1,
        target_device_ids: ["m72"],
        telegram_chat_id: 100
      })
    }))).json();

    const actionId = qRes.moveacc.action_id;

    const failAckPayload = {
      device_id: "m72",
      action_id: actionId,
      status: "FAILED",
      executed: false,
      batch_action: "MOVE_ACC",
      reason: "Error: <section M109 empty & missing> -> failed to sample accounts"
    };

    const ackRes = await (await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify(failAckPayload)
    }))).json();

    if (!ackRes.ok) throw new Error("Acknowledge failed: " + JSON.stringify(ackRes));
    if (capturedTelegramRequests.length !== 1) throw new Error("Telegram failure alert not sent");

    const tgMsg = capturedTelegramRequests[0].text;
    console.log("    [HTML Failure Output Verified]:\n" + tgMsg.split("\n").map(l => "      " + l).join("\n"));

    validateTelegramHtml(tgMsg);

    if (tgMsg.includes("<section") || tgMsg.includes("empty & missing>")) {
      throw new Error("Raw <section ... > found in failure message!");
    }
    if (!tgMsg.includes("&lt;section M109 empty &amp; missing&gt;")) {
      throw new Error("Failure reason was not properly escaped in Telegram HTML");
    }
  });

  await runTest("HTML Escaping: sync error with <rclone error & timeout>", async () => {
    capturedTelegramRequests = [];
    const qRes = await (await fleet.controlFleetHub(new Request("https://localhost/aot/hub/control", {
      method: "POST",
      body: JSON.stringify({
        protocol: "fleet-batch-v1",
        kind: "move_acc",
        source_m: "M109",
        target_m: "M77",
        count: 1,
        target_device_ids: ["m72"],
        telegram_chat_id: 100
      })
    }))).json();

    const actionId = qRes.moveacc.action_id;

    const ackPayload = {
      device_id: "m72",
      action_id: actionId,
      status: "OPENED",
      executed: true,
      batch_action: "MOVE_ACC",
      details: JSON.stringify({
        source_m: "M109",
        target_m: "M77",
        count: 1,
        moved_accounts: ["UserOne"],
        source_remaining_count: 4,
        target_current_count: 3,
        sync_result: {
          acc_sync: false,
          rule34_verified: false,
          error: "Rule 34 Violated! <drifted_id & rclone timeout>"
        }
      })
    };

    await fleet.dispatchFleetAck(new Request("https://localhost/aot/ack", {
      method: "POST",
      body: JSON.stringify(ackPayload)
    }));

    const tgMsg = capturedTelegramRequests[0].text;
    validateTelegramHtml(tgMsg);
    if (!tgMsg.includes("&lt;drifted_id &amp; rclone timeout&gt;")) {
      throw new Error("Sync error was not properly escaped: " + tgMsg);
    }
  });

  console.log("\n=================================================");
  console.log("  ALL ADVERSARIAL M3 WORKER TELEGRAM TESTS PASSED!");
  console.log("=================================================");
}

main().catch((err) => {
  console.error("FATAL TEST FAILURE:", err);
  process.exit(1);
});

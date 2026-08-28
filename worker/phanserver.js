import { parseTongHopLink } from "./tong_hop_link.js";
import { normalizeDeviceId, normalizeDeviceGroup, normalizeDeviceIdList, compareDeviceIds } from "./fleet_state.js";

export async function telegram(env, method, payload) {
  if (env?.telegram) {
    return env.telegram(env, method, payload);
  }
  const token = env?.TELEGRAM_BOT_TOKEN;
  if (!token) return { ok: false };
  const response = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return response.json();
}

export async function answerCallback(id, env, text, alert = false) {
  if (env?.answerCallback) {
    return env.answerCallback(id, env, text, alert);
  }
  return telegram(env, "answerCallbackQuery", {
    callback_query_id: id,
    text,
    show_alert: alert
  });
}

export async function resolveAndValidateTelegramTargets(targetStr, env, fleetState) {
  if (env?.resolveAndValidateTelegramTargets) {
    return env.resolveAndValidateTelegramTargets(targetStr, env);
  }
  if (!targetStr || !targetStr.trim()) {
    throw new Error("Target không được để trống.");
  }
  const rawTarget = targetStr.trim();
  const wantedGroup = normalizeDeviceGroup(rawTarget);

  const stateResult = await fleetStateCall(env, fleetState, "/aot/hub/state");
  if (!stateResult?.response?.ok && !stateResult?.data?.state) {
    throw new Error("Không thể lấy trạng thái thiết bị.");
  }
  const durableRecords = stateResult.data?.state?.devices || [];

  if (wantedGroup) {
    const ids = [];
    for (const record of durableRecords) {
      if (normalizeDeviceGroup(record?.device_group) === wantedGroup) {
        if (!record.online) {
          throw new Error(`Thiết bị ${record?.device_id} trong nhóm ${wantedGroup} đang OFFLINE.`);
        }
        ids.push(normalizeDeviceId(record?.device_id));
      }
    }
    if (ids.length === 0) {
      throw new Error(`Nhóm ${wantedGroup} không có thiết bị nào.`);
    }
    return ids.sort(compareDeviceIds);
  }

  const ids = normalizeDeviceIdList(rawTarget);
  if (ids.length === 0) {
    throw new Error("Danh sách target không hợp lệ.");
  }

  const onlineIds = new Set();
  const allIds = new Set();
  for (const record of durableRecords) {
    const did = normalizeDeviceId(record?.device_id);
    if (!did) continue;
    allIds.add(did);
    if (record.online) onlineIds.add(did);
  }

  for (const id of ids) {
    if (!allIds.has(id)) {
      throw new Error(`Thiết bị ${id} không tồn tại.`);
    }
    if (!onlineIds.has(id)) {
      throw new Error(`Thiết bị ${id} đang OFFLINE.`);
    }
  }
  return ids;
}

export async function fleetStateCall(env, fleetState, path, init = {}) {
  if (env?.fleetStateCall) {
    return env.fleetStateCall(env, path, init);
  }
  if (!fleetState) {
    throw new Error("FleetState durable object stub missing");
  }
  const req = new Request(`https://localhost${path}`, {
    method: init.method || "GET",
    headers: { "Content-Type": "application/json" },
    body: init.body ? JSON.stringify(init.body) : undefined
  });
  const res = await fleetState.fetch(req);
  let data = null;
  try {
    data = await res.json();
  } catch (e) {}
  return { response: res, data };
}

export async function getTongHopLinkContent(env) {
  if (env?.getGitHubFile) {
    const fileData = await env.getGitHubFile("tong_hop_link.txt", env);
    if (fileData?.content) {
      return Buffer.from(fileData.content, "base64").toString("utf8");
    }
  }
  if (env?.TONG_HOP_LINK_RAW) {
    return env.TONG_HOP_LINK_RAW;
  }
  return "";
}

export async function handleUpdate(update, env, fleetState) {
  const message = update.message;
  const callback = update.callback_query;
  const from = message?.from || callback?.from;
  const chatId = message?.chat?.id || callback?.message?.chat?.id;
  const messageId = callback?.message?.message_id;

  if (!from || !chatId) return;

  if (env?.TELEGRAM_ADMIN_USER_ID && String(from.id) !== String(env.TELEGRAM_ADMIN_USER_ID)) {
    if (callback) {
      await answerCallback(callback.id, env, "Không có quyền sử dụng bot.", true);
    }
    return;
  }

  if (callback) {
    await handleCallback(callback, chatId, messageId, env, fleetState, from.id);
    return;
  }

  const input = (message.text || message.caption || "").trim();

  if (input === "/devices") {
    try {
      const stateResult = await fleetStateCall(env, fleetState, "/aot/hub/state");
      const devices = stateResult.data?.state?.devices || [];
      const text = devices.length
        ? devices.sort((a, b) => String(a.device_id).localeCompare(String(b.device_id), undefined, { numeric: true }))
          .map(d => `${d.device_id}: ${d.online ? "ONLINE" : "OFFLINE"}`).join("\n")
        : "Chưa có thiết bị nào đăng ký.";
      await telegram(env, "sendMessage", { chat_id: chatId, text });
    } catch (error) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Lỗi lấy danh sách thiết bị." });
    }
    return;
  }

  if (input.match(/^\/update(?:\s|$)/)) {
    const parts = input.split(/\s+/);
    if (parts.length !== 2) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Cú pháp: /update <device1,device2...>" });
      return;
    }
    try {
      const ids = await resolveAndValidateTelegramTargets(parts[1], env, fleetState);
      const result = await fleetStateCall(env, fleetState, "/aot/hub/control", {
        method: "POST",
        body: { protocol: "fleet-batch-v1", kind: "update_delta", target_device_ids: ids }
      });
      if (!result?.response?.ok) throw new Error(result?.data?.error || "update_queue_failed");
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: `Đã xếp UPDATE_DELTA: ${ids.join(", ")}. Thiết bị sẽ nhận lệnh ở heartbeat kế tiếp.`
      });
    } catch (error) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Lỗi UPDATE_DELTA: " + String(error.message || error) });
    }
    return;
  }

  if (input.match(/^\/phanserver(?:\s|$)/)) {
    const parts = input.split(/\s+/);
    if (parts.length !== 3) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "Cú pháp: /phanserver <device1,device2...> <tabs>"
      });
      return;
    }
    const targetStr = parts[1];
    const tabs = Number(parts[2]);
    if (!Number.isInteger(tabs) || tabs < 1 || tabs > 10 || parts[2] !== String(tabs)) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "Số tab phải từ 1 đến 10."
      });
      return;
    }

    try {
      const ids = await resolveAndValidateTelegramTargets(targetStr, env, fleetState);
      const text = await getTongHopLinkContent(env);
      if (!text) {
        throw new Error("Không tìm thấy dữ liệu tong_hop_link.txt");
      }

      const allocationMap = parseTongHopLink(text, ids, tabs);
      const token = crypto.randomUUID().replace(/-/g, "").slice(0, 12);

      const saveRes = await fleetStateCall(env, fleetState, "/aot/hub/control", {
        method: "POST",
        body: {
          protocol: "fleet-batch-v1",
          kind: "pending_allocate_save",
          token,
          spec: { ids, tabs, allocationMap }
        }
      });
      if (!saveRes?.response?.ok) {
        throw new Error("Lỗi lưu trạng thái PHÂN SERVER");
      }

      let textMsg = "<b>PREVIEW PHÂN SERVER</b>\n\n";
      for (const [id, list] of Object.entries(allocationMap)) {
        textMsg += `<b>${id}</b>\n`;
        textMsg += list.map(x => `${x.pkg}: ${x.url}`).join("\n") + "\n\n";
      }
      textMsg += "Xác nhận chạy phân server?";
      if (textMsg.length > 4000) {
        let cutPoint = textMsg.lastIndexOf("\n", 4000);
        if (cutPoint === -1) cutPoint = 4000;
        textMsg = textMsg.slice(0, cutPoint) + "\n\n(Đã cắt bớt)\nXác nhận chạy phân server?";
      }

      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: textMsg,
        parse_mode: "HTML",
        reply_markup: {
          inline_keyboard: [
            [
              { text: "✅ Confirm", callback_data: `allocate_ok:${token}` },
              { text: "❌ Cancel", callback_data: `allocate_cancel:${token}` }
            ]
          ]
        }
      });
    } catch (error) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "Lỗi: " + String(error.message || error)
      });
    }
  }
}

export async function handleCallback(callback, chatId, messageId, env, fleetState, fromId) {
  const data = callback.data || "";

  if (data.startsWith("allocate_cancel:")) {
    const token = data.slice("allocate_cancel:".length);
    const clearRes = await fleetStateCall(env, fleetState, "/aot/hub/control", {
      method: "POST",
      body: {
        protocol: "fleet-batch-v1",
        kind: "pending_allocate_clear",
        token
      }
    });
    if (clearRes?.data?.cleared === true) {
      await answerCallback(callback.id, env, "Đã hủy PHÂN SERVER.");
    } else {
      await answerCallback(callback.id, env, "Lệnh đã được xác nhận/đang xử lý, không thể hủy.", true);
    }
    return;
  }

  if (data.startsWith("allocate_ok:")) {
    const token = data.slice("allocate_ok:".length);
    const consumeRes = await fleetStateCall(env, fleetState, "/aot/hub/control", {
      method: "POST",
      body: {
        protocol: "fleet-batch-v1",
        kind: "pending_allocate_consume",
        token
      }
    });
    const pending = consumeRes?.data?.spec;
    if (!pending) {
      await answerCallback(callback.id, env, "Xác nhận đã hết hạn hoặc đã được xử lý.", true);
      return;
    }

    await answerCallback(callback.id, env, "Đang chạy phân server...");

    try {
      const stateResult = await fleetStateCall(env, fleetState, "/aot/hub/state");
      if (!stateResult?.response?.ok && !stateResult?.data?.state) {
        throw new Error("Không thể lấy trạng thái thiết bị để xác nhận lại.");
      }
      const durableRecords = stateResult.data?.state?.devices || [];
      const onlineMap = new Map();
      for (const r of durableRecords) {
        onlineMap.set(normalizeDeviceId(r.device_id), r.online);
      }
      for (const id of pending.ids) {
        if (!onlineMap.get(id)) {
          throw new Error(`Thiết bị ${id} đã ngắt kết nối (OFFLINE). Lệnh bị hủy.`);
        }
      }

      const result = await fleetStateCall(env, fleetState, "/aot/hub/control", {
        method: "POST",
        body: {
          protocol: "fleet-batch-v1",
          kind: "allocate_server",
          target_device_ids: pending.ids,
          allocationMap: pending.allocationMap,
          telegram_chat_id: chatId
        }
      });

      if (!result?.response?.ok) {
        if (result?.data?.error === "offline_devices_in_allocate_batch") {
          throw new Error("Có thiết bị ngắt kết nối trong lúc xác nhận. Lệnh phân server đã bị hủy toàn bộ.");
        }
        throw new Error(JSON.stringify(result?.data));
      }

      await telegram(env, "editMessageText", {
        chat_id: chatId,
        message_id: callback.message?.message_id || messageId,
        text: "Đã gửi lệnh phân server, đang chờ thiết bị phản hồi..."
      });
    } catch (e) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "Lỗi chạy phân server: " + String(e.message || e)
      });
    }
  }
}

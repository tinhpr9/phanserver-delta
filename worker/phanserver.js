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
  const stateResult = await fleetStateCall(env, fleetState, "/aot/hub/state");
  if (!stateResult?.response?.ok && !stateResult?.data?.state) {
    throw new Error("Không thể lấy trạng thái thiết bị.");
  }
  const durableRecords = stateResult.data?.state?.devices || [];

  // Support "all" or "*" keyword to target all online devices
  if (rawTarget.toLowerCase() === "all" || rawTarget === "*") {
    const onlineDevices = durableRecords
      .filter(record => record.online)
      .map(record => normalizeDeviceId(record.device_id))
      .filter(Boolean);
    if (onlineDevices.length === 0) {
      throw new Error("Không có thiết bị nào đang ONLINE để thực hiện.");
    }
    return onlineDevices.sort(compareDeviceIds);
  }

  const wantedGroup = normalizeDeviceGroup(rawTarget);

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
  if (from?.is_bot) return;

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

  if (input.toUpperCase() === "STATUS" || input === "/status") {
    try {
      const stateResult = await fleetStateCall(env, fleetState, "/aot/hub/state");
      const devices = stateResult.data?.state?.devices || [];
      const online = devices.filter(d => d.online).length;
      const text = devices.length
        ? `FLEET_STATUS=ONLINE\nDEVICES=${devices.length}\nONLINE=${online}\n` + devices
          .sort((a, b) => String(a.device_id).localeCompare(String(b.device_id), undefined, { numeric: true }))
          .map(d => `${d.device_id}: ${d.online ? "ONLINE" : "OFFLINE"}`).join("\n")
        : "FLEET_STATUS=EMPTY\nDEVICES=0\nONLINE=0";
      await telegram(env, "sendMessage", { chat_id: chatId, text });
    } catch (error) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "FLEET_STATUS=UNAVAILABLE" });
    }
    return;
  }

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

  if (input.toUpperCase() === "UPDATE" || input === "/update") {
    try {
      const stateResult = await fleetStateCall(env, fleetState, "/aot/hub/state");
      const devices = stateResult.data?.state?.devices || [];
      const onlineIds = devices
        .filter(device => device.online)
        .map(device => String(device.device_id))
        .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
      const text = onlineIds.length
        ? `UPDATE_TARGET_REQUIRED\nONLINE_DEVICES=${onlineIds.join(",")}\nGửi: /update ${onlineIds.join(",")}`
        : `UPDATE_BLOCKED=NO_ONLINE_DEVICES\nDEVICES=${devices.length}\nONLINE=0`;
      await telegram(env, "sendMessage", { chat_id: chatId, text });
    } catch (error) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "UPDATE_UNAVAILABLE" });
    }
    return;
  }

  if (input === "/apks" || input === "/release") {
    try {
      let assets = [];
      let tag = "Backup";
      if (env?.getManifest) {
        const manifest = await env.getManifest(env);
        assets = manifest?.assets || [];
        tag = manifest?.release_tag || manifest?.version || tag;
      } else {
        const headers = { "User-Agent": "phanserver-delta-worker", "Accept": "application/vnd.github.v3+json" };
        if (env?.GITHUB_TOKEN) {
          headers["Authorization"] = `Bearer ${env.GITHUB_TOKEN}`;
        }
        const manifestRes = await fetch("https://api.github.com/repos/tinhpr9/phanserver-delta/releases?per_page=5", {
          headers
        }).catch(() => null);
        if (manifestRes && manifestRes.ok) {
          const releases = await manifestRes.json();
          if (Array.isArray(releases) && releases.length > 0) {
            const rel = releases[0];
            tag = rel.tag_name || rel.name || tag;
            assets = (rel.assets || []).map(a => ({
              name: a.name,
              size: a.size,
              kind: a.name.toLowerCase().endsWith(".apk") ? "apk" : "zip"
            }));
          }
        }
      }
      if (!assets.length) {
        assets = [{ name: "Delta-v1.0.0.apk", size: 1024, kind: "apk" }];
      }

      function formatSize(bytes) {
        if (!bytes || isNaN(bytes)) return "N/A";
        if (bytes >= 1024 * 1024 * 1024) return (bytes / (1024 * 1024 * 1024)).toFixed(1) + " GB";
        if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MB";
        if (bytes >= 1024) return (bytes / 1024).toFixed(1) + " KB";
        return bytes + " B";
      }

      let text = `📦 DANH SÁCH APP TRONG RELEASE (Tag: ${tag}):\n`;
      assets.forEach((a, i) => {
        text += `${i + 1}. ${a.name} (${formatSize(a.size)})\n`;
      });
      text += `\n💡 Gợi ý lệnh:\n• Cài tất cả: /update <device1,device2...>\n• Cài chọn lọc: /update <device> <keyword|số_thứ_tự>\n• Bốc ngẫu nhiên: /update <device> random`;
      await telegram(env, "sendMessage", { chat_id: chatId, text });
    } catch (error) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Lỗi lấy danh sách Release: " + String(error.message || error) });
    }
    return;
  }

  if (input.match(/^\/(?:restore|update)(?:\s|$)/)) {
    const parts = input.split(/\s+/);
    if (parts.length < 2 || parts.length > 4) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Cú pháp: /restore <device1,device2...> [selection] [target_app] (hoặc /update)" });
      return;
    }
    const targetStr = parts[1];
    const selection = parts[2] || "all";
    const targetPkg = parts[3] || null;
    try {
      const ids = await resolveAndValidateTelegramTargets(targetStr, env, fleetState);
      const result = await fleetStateCall(env, fleetState, "/aot/hub/control", {
        method: "POST",
        body: { protocol: "fleet-batch-v1", kind: "update_delta", target_device_ids: ids, selection, target_pkg: targetPkg, telegram_chat_id: chatId }
      });
      if (!result?.response?.ok) throw new Error(result?.data?.error || "restore_queue_failed");
      const selText = selection !== "all" ? ` (Gói: ${selection})` : "";
      const targetText = targetPkg ? ` ➔ Nạp vào app: <b>${targetPkg}</b>` : "";
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: `📥 <b>ĐÃ XẾP LỆNH RESTORE</b>: <code>${ids.join(", ")}</code>${selText}${targetText}\nThiết bị sẽ tải và khôi phục ứng dụng + dữ liệu ở heartbeat kế tiếp.`,
        parse_mode: "HTML"
      });
    } catch (error) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Lỗi RESTORE: " + String(error.message || error) });
    }
    return;
  }

  if (input.match(/^\/backup(?:\s|$)/)) {
    const raw = input.replace(/^\/backup\s*/, "").trim();
    if (!raw) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Cú pháp: /backup <device1,device2...> [app1,app2... hoặc all] [data|apk|full]" });
      return;
    }
    const tokens = raw.split(/\s+/);
    const targetStr = tokens[0];
    let mode = "full";
    let pkgStr = "taskbar";
    
    if (tokens.length > 1) {
      const lastToken = tokens[tokens.length - 1].toLowerCase();
      if (["data", "apk", "full"].includes(lastToken)) {
        mode = lastToken;
        pkgStr = tokens.slice(1, -1).join(" ") || "taskbar";
      } else {
        pkgStr = tokens.slice(1).join(" ");
      }
    }
    pkgStr = pkgStr.replace(/\s*,\s*/g, ",").trim() || "taskbar";

    try {
      const ids = await resolveAndValidateTelegramTargets(targetStr, env, fleetState);
      const result = await fleetStateCall(env, fleetState, "/aot/hub/control", {
        method: "POST",
        body: { protocol: "fleet-batch-v1", kind: "backup_app", target_device_ids: ids, package: pkgStr, mode, release_tag: "Backup", github_token: env?.GITHUB_TOKEN || "", telegram_chat_id: chatId }
      });
      if (!result?.response?.ok) throw new Error(result?.data?.error || "backup_queue_failed");
      const modeLabel = mode === "apk" ? "Chỉ APK" : (mode === "data" ? "Chỉ Data cấu hình" : "Đầy đủ APK + Data");
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: `📦 <b>ĐÃ XẾP LỆNH SAO LƯU (${modeLabel.toUpperCase()})</b>\nThiết bị: <code>${ids.join(", ")}</code>\nỨng dụng: <code>${pkgStr}</code>\nChế độ: <b>${modeLabel}</b>\nThiết bị sẽ đóng gói và upload lên GitHub Release (Tag: Backup) ở heartbeat kế tiếp.`,
        parse_mode: "HTML"
      });
    } catch (error) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Lỗi BACKUP_APP: " + String(error.message || error) });
    }
    return;
  }

  if (input.match(/^\/upgrade(?:\s|$)/)) {
    const parts = input.split(/\s+/);
    if (parts.length !== 2) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Cú pháp: /upgrade <device1,device2... hoặc all>" });
      return;
    }
    const targetStr = parts[1];
    try {
      const ids = await resolveAndValidateTelegramTargets(targetStr, env, fleetState);
      const result = await fleetStateCall(env, fleetState, "/aot/hub/control", {
        method: "POST",
        body: { protocol: "fleet-batch-v1", kind: "upgrade_agent", target_device_ids: ids, telegram_chat_id: chatId }
      });
      if (!result?.response?.ok) throw new Error(result?.data?.error || "upgrade_queue_failed");
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: `🚀 <b>ĐÃ XẾP LỆNH NÂNG CẤP AGENT</b>\nThiết bị: <code>${ids.join(", ")}</code>\nAgent sẽ tự động kéo code mới nhất từ GitHub và khởi động lại ngầm ở heartbeat kế tiếp.`,
        parse_mode: "HTML"
      });
    } catch (error) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Lỗi UPGRADE_AGENT: " + String(error.message || error) });
    }
    return;
  }

  if (input.match(/^\/(?:script|sae|autoexec)(?:\s|$)/)) {
    const raw = input.replace(/^\/(?:script|sae|autoexec)\s*/, "").trim();
    if (!raw) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "Cú pháp:\n• <code>/script &lt;device1,device2... hoặc all&gt; &lt;tên_file&gt; &lt;link_script hoặc mã_lua&gt;</code>\n• <code>/script &lt;device&gt; clean [tên_file hoặc all]</code>\n\nVí dụ: <code>/script m77 sae https://raw.githubusercontent.com/...</code>",
        parse_mode: "HTML"
      });
      return;
    }

    const parts = raw.split(/\s+/);
    const targetStr = parts[0];

    // Check for clean mode: /script m77 clean [filename|all]
    if (parts.length >= 2 && parts[1].toLowerCase() === "clean") {
      const cleanTarget = parts[2] || "all";
      try {
        const ids = await resolveAndValidateTelegramTargets(targetStr, env, fleetState);
        const result = await fleetStateCall(env, fleetState, "/aot/hub/control", {
          method: "POST",
          body: {
            protocol: "fleet-batch-v1",
            kind: "clean_script",
            target_device_ids: ids,
            filename: cleanTarget,
            telegram_chat_id: chatId
          }
        });
        if (!result?.response?.ok) throw new Error(result?.data?.error || "clean_script_queue_failed");
        await telegram(env, "sendMessage", {
          chat_id: chatId,
          text: `🧹 <b>ĐÃ XẾP LỆNH XÓA SCRIPT</b>: <code>${ids.join(", ")}</code>\n🎯 Mục tiêu: <code>${cleanTarget}</code> trong <code>Delta/Autoexecute/</code>`,
          parse_mode: "HTML"
        });
      } catch (error) {
        await telegram(env, "sendMessage", { chat_id: chatId, text: "Lỗi CLEAN_SCRIPT: " + String(error.message || error) });
      }
      return;
    }

    if (parts.length < 3) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "Cú pháp: <code>/script &lt;device&gt; &lt;tên_file&gt; &lt;link_script hoặc mã_lua&gt;</code>\nVí dụ: <code>/script m77 sae https://raw.githubusercontent.com/...</code>",
        parse_mode: "HTML"
      });
      return;
    }

    const filename = parts[1];
    const rawContent = parts.slice(2).join(" ");
    let content = rawContent;
    if (rawContent.startsWith("http://") || rawContent.startsWith("https://")) {
      content = `loadstring(game:HttpGet("${rawContent}"))()`;
    }

    try {
      const ids = await resolveAndValidateTelegramTargets(targetStr, env, fleetState);
      const result = await fleetStateCall(env, fleetState, "/aot/hub/control", {
        method: "POST",
        body: {
          protocol: "fleet-batch-v1",
          kind: "write_script",
          target_device_ids: ids,
          filename: filename,
          content: content,
          raw_source: rawContent,
          telegram_chat_id: chatId
        }
      });
      if (!result?.response?.ok) throw new Error(result?.data?.error || "write_script_queue_failed");
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: `📜 <b>ĐÃ XẾP LỆNH NẠP SCRIPT VÀO DELTA AUTOEXECUTE</b>\n📱 Thiết bị: <code>${ids.join(", ")}</code>\n📄 Tên file: <code>${filename}</code>\n⚡ Kịch bản sẽ được ghi vào <code>/storage/emulated/0/Delta/Autoexecute/${filename}</code> ở heartbeat kế tiếp.`,
        parse_mode: "HTML"
      });
    } catch (error) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Lỗi WRITE_SCRIPT: " + String(error.message || error) });
    }
    return;
  }

  if (input.match(/^\/(?:devmode|developer|dev)(?:\s|$)/)) {
    const raw = input.replace(/^\/(?:devmode|developer|dev)\s*/, "").trim();
    if (!raw) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Cú pháp: /devmode <device1,device2... hoặc all>" });
      return;
    }
    try {
      const ids = await resolveAndValidateTelegramTargets(raw, env, fleetState);
      const result = await fleetStateCall(env, fleetState, "/aot/hub/control", {
        method: "POST",
        body: { protocol: "fleet-batch-v1", kind: "enable_dev_mode", target_device_ids: ids, telegram_chat_id: chatId }
      });
      if (!result?.response?.ok) throw new Error(result?.data?.error || "dev_mode_queue_failed");
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: `⚙️ <b>ĐÃ XẾP LỆNH BẬT TÙY CHỌN NHÀ PHÁT TRIỂN</b>\nThiết bị: <code>${ids.join(", ")}</code>\nThiết bị sẽ tự động kích hoạt Developer Options & USB Debugging (ADB) và mở màn hình Cài đặt ở heartbeat kế tiếp.`,
        parse_mode: "HTML"
      });
    } catch (error) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Lỗi ENABLE_DEV_MODE: " + String(error.message || error) });
    }
    return;
  }

  if (input.match(/^\/(?:tailscale|vpn)(?:\s|$)/)) {
    const raw = input.replace(/^\/(?:tailscale|vpn)\s*/, "").trim();
    if (!raw) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "Cú pháp: /tailscale <device1,device2... hoặc all> [on|off|status]\nVí dụ: <code>/tailscale m77 on</code> hoặc <code>/vpn m77 status</code>",
        parse_mode: "HTML"
      });
      return;
    }
    const parts = raw.split(/\s+/);
    const targetStr = parts[0];
    const mode = (parts[1] || "on").toLowerCase();
    if (!["on", "off", "status"].includes(mode)) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "Chế độ không hợp lệ. Vui lòng chọn: <code>on</code>, <code>off</code>, hoặc <code>status</code> (mặc định: on).",
        parse_mode: "HTML"
      });
      return;
    }
    try {
      const ids = await resolveAndValidateTelegramTargets(targetStr, env, fleetState);
      const result = await fleetStateCall(env, fleetState, "/aot/hub/control", {
        method: "POST",
        body: {
          protocol: "fleet-batch-v1",
          kind: "control_tailscale",
          target_device_ids: ids,
          mode: mode,
          telegram_chat_id: chatId
        }
      });
      if (!result?.response?.ok) throw new Error(result?.data?.error || "tailscale_queue_failed");
      const modeLabel = mode === "off" ? "TẮT" : (mode === "status" ? "KIỂM TRA TRẠNG THÁI" : "BẬT");
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: `🌐 <b>ĐÃ XẾP LỆNH ${modeLabel} TAILSCALE</b>\nThiết bị: <code>${ids.join(", ")}</code>\nChế độ: <b>${mode.toUpperCase()}</b>\nThiết bị sẽ tự động thực thi và gửi thông báo kết quả ở heartbeat kế tiếp.`,
        parse_mode: "HTML"
      });
    } catch (error) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Lỗi CONTROL_TAILSCALE: " + String(error.message || error) });
    }
    return;
  }

  if (input === "/help" || input === "/start") {
    const helpText = `🤖 <b>DANH SÁCH LỆNH PREIUMBOT / PHANSERVER-DELTA</b>

🛡️ <b>Quản lý Tài khoản (Roblox Ban & Add)</b>:
• <code>/checkban [m_code|all|users]</code>: Quét Roblox API kiểm tra ban, tự dọn dẹp acc.txt & sync Drive (Rule 34)
• <code>/addacc &lt;m_code&gt; &lt;user:pass...&gt;</code>: Nạp tài khoản vào dàn máy và sync Google Drive

📱 <b>Quản trị Thiết bị & Trạng thái</b>:
• <code>/status</code>: Báo cáo trạng thái tổng thể cả dàn
• <code>/devices</code>: Danh sách thiết bị và trạng thái online/offline
• <code>/upgrade &lt;devices|all&gt;</code>: Tự động kéo code mới nhất từ GitHub và restart Agent

🔗 <b>Phân chia Server & Kịch bản</b>:
• <code>/phanserver &lt;devices&gt; &lt;tabs&gt;</code>: Phân phối private server link
• <code>/script &lt;devices&gt; &lt;tên_file&gt; &lt;url|lua&gt;</code>: Nạp script vào Delta Autoexecute
• <code>/script &lt;devices&gt; clean [file|all]</code>: Xóa script Autoexecute

🔧 <b>Hệ thống & Cài đặt</b>:
• <code>/restore</code> hoặc <code>/update &lt;devices&gt;</code>: Cài đặt / cập nhật Roblox & Delta APK
• <code>/backup &lt;devices&gt; [app] [full|data|apk]</code>: Sao lưu ứng dụng lên GitHub Releases
• <code>/tailscale &lt;devices&gt; [on|off|status]</code>: Bật/tắt/kiểm tra mạng nội bộ Tailscale VPN
• <code>/devmode &lt;devices&gt;</code>: Bật Developer Options & ADB`;
    await telegram(env, "sendMessage", { chat_id: chatId, text: helpText, parse_mode: "HTML" });
    return;
  }

  if (input.match(/^\/(?:checkban|kiemtraban)(?:\s|$)/i)) {
    const raw = input.replace(/^\/(?:checkban|kiemtraban)\s*/i, "").trim();
    const target = raw || "all";
    try {
      let execDeviceId = null;
      try {
        const onlineIds = await resolveAndValidateTelegramTargets("all", env, fleetState);
        if (onlineIds && onlineIds.length > 0) {
          const normTarget = target.toLowerCase();
          if (onlineIds.includes(normTarget)) {
            execDeviceId = normTarget;
          } else {
            execDeviceId = onlineIds[0];
          }
        }
      } catch (e) {}

      if (!execDeviceId) {
        try {
          const single = await resolveAndValidateTelegramTargets(target, env, fleetState);
          if (single && single.length > 0) execDeviceId = single[0];
        } catch (e) {}
      }

      if (!execDeviceId) {
        await telegram(env, "sendMessage", {
          chat_id: chatId,
          text: "⚠️ <b>KHÔNG CÓ THIẾT BỊ NÀO ONLINE</b>\nĐể quét ban và đồng bộ tệp theo Rule 34, cần ít nhất 1 thiết bị trong dàn online.",
          parse_mode: "HTML"
        });
        return;
      }

      const result = await fleetStateCall(env, fleetState, "/aot/hub/control", {
        method: "POST",
        body: {
          protocol: "fleet-batch-v1",
          kind: "check_ban",
          target_device_ids: [execDeviceId],
          target: target,
          telegram_chat_id: chatId
        }
      });
      if (!result?.response?.ok) throw new Error(result?.data?.error || "checkban_queue_failed");

      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: `🛡️ <b>ĐÃ XẾP LỆNH CHECK BAN ROBLOX</b>\n📱 Thiết bị thực thi: <code>${execDeviceId}</code>\n🎯 Mục tiêu: <b>${target.toUpperCase()}</b>\n⚡ Agent đang quét Roblox API và sẽ báo cáo kết quả chi tiết kèm xử lý acc ban ngay khi hoàn tất.`,
        parse_mode: "HTML"
      });
    } catch (error) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Lỗi CHECK_BAN: " + String(error.message || error) });
    }
    return;
  }

  if (input.match(/^\/(?:addacc|themacc)(?:\s|$)/i)) {
    const raw = input.replace(/^\/(?:addacc|themacc)\s*/i, "").trim();
    if (!raw) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "Cú pháp:\n<code>/addacc &lt;mã_máy&gt; &lt;user:pass&gt; [user2:pass2...]</code>\n\nVí dụ: <code>/addacc m77 user1:pass1 user2:pass2</code>",
        parse_mode: "HTML"
      });
      return;
    }

    const tokens = raw.split(/[\r\n\s]+/).filter(Boolean);
    if (tokens.length < 2) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "Cú pháp:\n<code>/addacc &lt;mã_máy&gt; &lt;user:pass&gt; [user2:pass2...]</code>\n\nVí dụ: <code>/addacc m77 user1:pass1 user2:pass2</code>",
        parse_mode: "HTML"
      });
      return;
    }

    const mCode = tokens[0];
    const accounts = tokens.slice(1);

    const validAccounts = accounts.filter(a => a.includes(":"));
    if (!validAccounts.length) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "⚠️ Định dạng tài khoản không hợp lệ. Mỗi tài khoản phải theo mẫu <code>username:password</code>.",
        parse_mode: "HTML"
      });
      return;
    }

    try {
      let execDeviceId = null;
      try {
        const onlineIds = await resolveAndValidateTelegramTargets("all", env, fleetState);
        if (onlineIds && onlineIds.length > 0) {
          const normMCode = mCode.toLowerCase();
          if (onlineIds.includes(normMCode)) {
            execDeviceId = normMCode;
          } else {
            execDeviceId = onlineIds[0];
          }
        }
      } catch (e) {}

      if (!execDeviceId) {
        try {
          const single = await resolveAndValidateTelegramTargets(mCode, env, fleetState);
          if (single && single.length > 0) execDeviceId = single[0];
        } catch (e) {}
      }

      if (!execDeviceId) {
        await telegram(env, "sendMessage", {
          chat_id: chatId,
          text: "⚠️ <b>KHÔNG CÓ THIẾT BỊ NÀO ONLINE</b>\nĐể nạp tài khoản và đồng bộ theo Rule 34, cần ít nhất 1 thiết bị trong dàn online.",
          parse_mode: "HTML"
        });
        return;
      }

      const result = await fleetStateCall(env, fleetState, "/aot/hub/control", {
        method: "POST",
        body: {
          protocol: "fleet-batch-v1",
          kind: "add_acc",
          target_device_ids: [execDeviceId],
          m_code: mCode,
          lines: validAccounts,
          telegram_chat_id: chatId
        }
      });
      if (!result?.response?.ok) throw new Error(result?.data?.error || "addacc_queue_failed");

      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: `➕ <b>ĐÃ XẾP LỆNH NẠP TÀI KHOẢN</b>\n📱 Thiết bị thực thi: <code>${execDeviceId}</code>\n🎯 Dàn máy: <b>${mCode.toUpperCase()}</b>\n📝 Số lượng tài khoản: <b>${validAccounts.length}</b>\n⚡ Agent sẽ chèn vào đúng vị trí trong <code>acc.txt</code> và đồng bộ Google Drive ngay.`,
        parse_mode: "HTML"
      });
    } catch (error) {
      await telegram(env, "sendMessage", { chat_id: chatId, text: "Lỗi ADD_ACC: " + String(error.message || error) });
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

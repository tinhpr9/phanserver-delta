export const ALLOCATION_PACKAGES = [
  "com.tinh.vv.hi",
  "com.tinh.vv.hj",
  "com.tinh.vv.hk",
  "com.tinh.vv.hl",
  "com.tinh.vv.hm",
  "com.tinh.vv.hn",
  "com.tinh.vv.ho",
  "com.tinh.vv.hp",
  "com.tinh.vv.hq",
  "com.tinh.vv.hr"
];

export const ROBLOX_URL_REGEX = /^https:\/\/(www\.)?roblox\.com\/games\/\d+\?[pP][rR][iI][vV][aA][tT][eE][sS][eE][rR][vV][eE][rR][lL][iI][nN][kK][cC][oO][dD][eE]=[0-9a-fA-F]+$/;

/**
 * Parses and allocates Roblox private server links from tong_hop_link text
 * to a list of target devices across 1-10 tabs.
 *
 * @param {string} text Raw text containing link URLs
 * @param {string[]} target_device_ids Target device IDs (e.g. ["m1", "m2"])
 * @param {number} tabs Number of tabs (1 to 10)
 * @returns {Record<string, Array<{pkg: string, url: string}>>}
 */
export function parseTongHopLink(text, target_device_ids, tabs) {
  if (!Array.isArray(target_device_ids) || target_device_ids.length === 0) {
    throw new Error("Danh sách thiết bị không hợp lệ.");
  }

  const seenDeviceIds = new Set();
  for (const id of target_device_ids) {
    if (typeof id !== "string" || !id.trim()) {
      throw new Error("Danh sách thiết bị không hợp lệ.");
    }
    const normalized = id.trim().toLowerCase();
    if (seenDeviceIds.has(normalized)) {
      throw new Error(`Device ID bị lặp: ${id}`);
    }
    seenDeviceIds.add(normalized);
  }

  if (!Number.isInteger(tabs) || tabs < 1 || tabs > 10) {
    throw new Error("Số tab phải từ 1 đến 10.");
  }

  const lines = String(text || "").split("\n");
  const validUrls = [];
  const seenUrls = new Set();

  for (let rawLine of lines) {
    let line = rawLine.trim();
    if (!line || line === "===") continue;
    if (line.includes(",")) {
      const commaIndex = line.lastIndexOf(",");
      line = line.slice(commaIndex + 1).trim();
    }
    if (ROBLOX_URL_REGEX.test(line)) {
      const canonicalUrl = line.replace(/\?[pP][rR][iI][vV][aA][tT][eE][sS][eE][rR][vV][eE][rR][lL][iI][nN][kK][cC][oO][dD][eE]=/, '?privateServerLinkCode=');
      if (!seenUrls.has(canonicalUrl)) {
        seenUrls.add(canonicalUrl);
        validUrls.push(canonicalUrl);
      }
    }
  }

  const requiredCount = target_device_ids.length * tabs;
  if (validUrls.length < requiredCount) {
    throw new Error(
      `Không đủ URL hợp lệ! Cần ${requiredCount} URL (${target_device_ids.length} thiết bị × ${tabs} tab), nhưng chỉ có ${validUrls.length} URL khả dụng.`
    );
  }

  const allocationMap = {};
  for (let i = 0; i < target_device_ids.length; i++) {
    const deviceId = target_device_ids[i];
    const slice = validUrls.slice(i * tabs, (i + 1) * tabs);
    allocationMap[deviceId] = slice.map((url, tabIdx) => ({
      pkg: ALLOCATION_PACKAGES[tabIdx],
      url
    }));
  }
  return allocationMap;
}

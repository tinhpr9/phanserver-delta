# Investigation & Strategy Report: Tailscale IP Validation & Boundary Hardening

**Explorer**: Retry 2 (Tailscale IP Validation Explorer)  
**Date**: 2026-09-13  
**Target Files**: `worker/fleet_state.js`, `agent/agent.py`  
**Mandate**: Read-only investigation of Challenger 1 defect findings, edge case analysis, and exact fix strategy recommendation.

---

## 1. Observation

### Implementation Code & Line References

#### 1. `worker/fleet_state.js` (Lines 966–974, 1020–1028)
```javascript
966:     // Extract Tailscale CGNAT IP (100.x.y.z)
967:     const ipMatch = String(body.details || "").match(/100\.\d{1,3}\.\d{1,3}\.\d{1,3}/);
968:     const tailscaleIp = ipMatch ? ipMatch[0] : null;
969: 
970:     // Strict success gating: mode 'on' requires valid IP and OPENED/SUCCESS status
971:     let isSuccess = status === "OPENED" || status === "SUCCESS";
972:     if (mode === "on") {
973:       isSuccess = isSuccess && Boolean(tailscaleIp);
974:     }
...
1020:       } else if (mode === "status") {
1021:         const detailsStr = String(body.details || "").trim();
1022:         const isConnected = isSuccess && (Boolean(tailscaleIp) || (/^CONNECTED\b/i.test(detailsStr) && !/DISCONNECTED/i.test(detailsStr)));
1023:         if (isConnected) {
1024:           const ipDisplay = tailscaleIp || escapeHtml(detailsStr).replace(/^CONNECTED:\s*/i, "");
1025:           msg = `🌐 <b>TRẠNG THÁI TAILSCALE: CONNECTED (${ipDisplay})</b>\n📱 Thiết bị: <code>${deviceId}</code>\n📶 Trạng thái: <b>CONNECTED (${ipDisplay})</b>\n🔒 Mạng nội bộ Tailscale đang hoạt động.`;
1026:         } else {
1027:           const rawDetail = body.details || body.reason || "Chưa kết nối";
1028:           msg = `⚠️ <b>TRẠNG THÁI TAILSCALE: DISCONNECTED</b>\n📱 Thiết bị: <code>${deviceId}</code>\n📶 Trạng thái: <b>DISCONNECTED</b>\n📋 Chi tiết: <code>${escapeHtml(rawDetail)}</code>`;
1029:         }
```

#### 2. `agent/agent.py` (Lines 702–722)
```python
702:             # Strict status validation to prevent phantom successes (R1)
703:             if mode == "on":
704:                 ip_match = re.search(r"100\.\d{1,3}\.\d{1,3}\.\d{1,3}", stdout_text)
705:                 is_valid_ip = False
706:                 if ip_match:
707:                     is_valid_ip = validate_tailscale_cgnat_ip(ip_match.group(0))
708: 
709:                 if success and stdout_text.startswith("CONNECTED:") and is_valid_ip:
710:                     status = "OPENED"
711:                     executed = True
712:                     details = stdout_text
713:                     reason = None
714:                 else:
715:                     status = "FAILED"
716:                     executed = False
717:                     details = None
718:                     reason = reason or "vpn_timeout_no_ip: Timeout 12s không nhận được IP Tailscale (100.x.y.z)"
719:             elif mode == "status":
720:                 status = "OPENED"
721:                 executed = True
722:                 details = stdout_text if stdout_text else "DISCONNECTED"
723:                 reason = None
```

### Empirical Test Execution Results

#### Test 1: `node tests/test_adversarial_fleet.mjs`
```
[TEST 1] ACK with malformed IP 100.300.1.1 (octet > 255)
Result for 100.300.1.1: { ok: true, action_id: 'act-1', device_id: 'm77', status: 'OPENED' }
Telegram Msg for 100.300.1.1:
 🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.300.1.1</b>
📱 Thiết bị: <code>m77</code>
⚙️ Chế độ: <b>ON</b>
🔒 Mạng nội bộ Tailscale đã sẵn sàng.
⚠️ FINDING: Fleet State accepted invalid octet 100.300.1.1 because regex /100\.\d{1,3}.../ doesn't check octets <= 255

[TEST 2] ACK with 4-digit octet 100.1.2.2555
Result for 100.1.2.2555: { ok: true, action_id: 'act-2', device_id: 'm77', status: 'OPENED' }
Telegram Msg for 100.1.2.2555:
 🌐 <b>ĐÃ BẬT TAILSCALE THÀNH CÔNG! IP: 100.1.2.255</b>
📱 Thiết bị: <code>m77</code>
⚙️ Chế độ: <b>ON</b>
🔒 Mạng nội bộ Tailscale đã sẵn sàng.
⚠️ FINDING: Fleet State regex truncated 100.1.2.2555 to 100.1.2.255 due to lack of word boundary \b
```

#### Test 2: `python3 -m unittest -v tests/test_adversarial_agent.py`
```
test_partial_ip_suffix_attack_on_agent_handling (tests.test_adversarial_agent.TestIPValidationStress.test_partial_ip_suffix_attack_on_agent_handling)
Adversarial check: if stdout is 'CONNECTED: 100.1.2.2555', what does agent do? ... 
[EMPIRICAL TEST] Suffix 100.1.2.2555 result: status=OPENED, details=CONNECTED: 100.1.2.2555
ok
```

#### Test 3: Empirical Regex Word Boundary Limitation Test
When testing the simple `\b` boundary proposal `r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"`:
```python
>>> re.search(r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "100.1.2.3.4")
<re.Match object; span=(0, 9), match='100.1.2.3'>
>>> re.search(r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", ".100.1.2.3")
<re.Match object; span=(1, 10), match='100.1.2.3'>
>>> re.search(r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "100.1.2.3.")
<re.Match object; span=(0, 9), match='100.1.2.3'>
>>> re.search(r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "100.1.2.3/24")
<re.Match object; span=(0, 9), match='100.1.2.3'>
```
Because the period `.` and slash `/` are non-word characters (`\W`), regex word boundaries `\b` evaluate to `True` adjacent to them. As a result, `100.1.2.3.4` (5 octets) or `100.1.2.3/24` (CIDR) is incorrectly truncated to `100.1.2.3`.

---

## 2. Logic Chain

1. **Defect 1: Octet Range Leak in `worker/fleet_state.js`**:
   - *Observation*: Line 967 executes `match(/100\.\d{1,3}\.\d{1,3}\.\d{1,3}/)`.
   - *Logic*: Pattern `\d{1,3}` matches any numeric string from `0` to `999`. No subsequent check verifies whether the numbers exceed `255`. If an ACK payload arrives with `details: "CONNECTED: 100.300.1.1"`, `tailscaleIp` becomes `"100.300.1.1"`. In line 973, `isSuccess = isSuccess && Boolean(tailscaleIp)` evaluates to `true`. Fleet State assigns `device.status = "OPENED"` and sends a false success message to Telegram (`IP: 100.300.1.1`).
   - *Conclusion*: `fleet_state.js` requires an explicit numeric bounds check (`0 <= octet <= 255`) for each captured octet.

2. **Defect 2: Missing Boundary & Suffix Truncation in `agent/agent.py` & `fleet_state.js`**:
   - *Observation*: Line 703 of `agent.py` and line 967 of `fleet_state.js` use `/100\.\d{1,3}\.\d{1,3}\.\d{1,3}/` without boundary restrictions.
   - *Logic*: When stdout contains `CONNECTED: 100.1.2.2555`, the engine matches `"100.1.2.255"` (the first 3 digits of `2555`). `validate_tailscale_cgnat_ip("100.1.2.255")` evaluates `255 <= 255` -> `True`. `agent.py` then returns `status: "OPENED"` and `details: "CONNECTED: 100.1.2.2555"`. In `fleet_state.js`, the same unanchored match extracts `"100.1.2.255"` and reports success to Telegram.
   - *Conclusion*: The extraction regex must forbid following or preceding digits.

3. **Defect 3 (Additional Discovery): Insufficiency of Simple `\b` Boundary**:
   - *Observation*: In standard regular expressions, `\b` matches between word characters (`\w`: `[0-9a-zA-Z_]`) and non-word characters (`\W`). The characters `.`, `/`, and `:` are all non-word characters.
   - *Logic*: If the regex is merely `\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b`, an invalid string like `CONNECTED: 100.1.2.3.4` (5 octets) will trigger `\b` between the digit `3` and the period `.`. It extracts `100.1.2.3`, which is valid in range, causing both `agent.py` and `fleet_state.js` to accept `100.1.2.3.4`. Similarly, `100.1.2.3/24` and `100.1.2.3:80` would be extracted as valid IPs.
   - *Conclusion*: A robust fix must use negative lookaround assertions forbidding digits, letters, periods, slashes, and colons immediately before or after the IP:
     `/(?<![0-9a-zA-Z.])100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![0-9a-zA-Z./:])/`
     Additionally, octets with leading zeros (e.g. `100.01.2.3`) must be rejected.

4. **Defect 4 (Additional Discovery): Status Command Vulnerability in `fleet_state.js` & `agent.py`**:
   - *Observation A (`worker/fleet_state.js` lines 1021–1024)*:
     ```javascript
     const isConnected = isSuccess && (Boolean(tailscaleIp) || (/^CONNECTED\b/i.test(detailsStr) && !/DISCONNECTED/i.test(detailsStr)));
     const ipDisplay = tailscaleIp || escapeHtml(detailsStr).replace(/^CONNECTED:\s*/i, "");
     ```
   - *Logic A*: If `body.details` contains a malformed IP (e.g. `CONNECTED: 100.300.1.1` or `CONNECTED: 100.1.2.2555`) or non-Tailscale IP (`CONNECTED: 192.168.1.1`), `tailscaleIp` evaluates to `null`. However, `isConnected` STILL evaluates to `true` because `/^CONNECTED\b/i.test(detailsStr)` is satisfied! Then `ipDisplay` falls back to `escapeHtml(detailsStr).replace(/^CONNECTED:\s*/i, "")`, displaying `100.300.1.1` or `100.1.2.2555` or `192.168.1.1` on Telegram:
     `🌐 TRẠNG THÁI TAILSCALE: CONNECTED (100.300.1.1)`!
     Moreover, if `detailsStr` is `"CONNECTED:"`, `ipDisplay` is empty string, outputting `CONNECTED ()`.
   - *Observation B (`agent/agent.py` lines 719–722)*:
     ```python
     elif mode == "status":
         status = "OPENED"
         executed = True
         details = stdout_text if stdout_text else "DISCONNECTED"
         reason = None
     ```
   - *Logic B*: `agent.py` does not validate `stdout_text` when `mode == "status"`. If `tun0` or `dumpsys` returns an invalid or non-Tailscale IP, `agent.py` passes it unfiltered in `details`.
   - *Conclusion*:
     1. In `worker/fleet_state.js`, remove the loose fallback `|| (/^CONNECTED\b/i.test(detailsStr)...)`. Status mode must strictly evaluate `isConnected = isSuccess && Boolean(tailscaleIp);`. If `tailscaleIp` is null, the state is `DISCONNECTED`.
     2. In `agent/agent.py`, validate `stdout_text` in `status` mode: if not a valid Tailscale CGNAT IP, set `details = "DISCONNECTED"`.

5. **Audit of Other Command Handlers**:
   - *Observation*: We searched all command handlers in `worker/fleet_state.js`, `worker/phanserver.js`, and `agent/agent.py`.
   - *Finding*: Actions `UPDATE_DELTA`, `BACKUP_APP`, `UPGRADE_AGENT`, `ENABLE_DEV_MODE`, `WRITE_SCRIPT`, `CLEAN_SCRIPT`, `CHECK_BAN`, `ADD_ACC`, `DEL_ACC`, and `AOT_ALLOCATE_SERVER_ACTION` deal exclusively with APK assets, package names, git commits, or Roblox cookies.
   - *Conclusion*: No other command handlers or endpoints in the system handle IP validation or are impacted by malformed IPs.

---

## 3. Caveats

1. **Read-Only Protocol Adherence**: Per instructions, NO modifications were made to production source code (`agent/agent.py`, `worker/fleet_state.js`, `worker/phanserver.js`) or test files during this investigation.
2. **Hermetic R4 Compliance**: All validation and behavior modeling were verified hermetically without sending network packets to or interacting with live UgPhone devices (`m77`).
3. **IPv4 Scope**: Tailscale CGNAT is formally defined as IPv4 `100.64.0.0/10` (or `100.x.y.z` where octets are `0–255` per `ORIGINAL_REQUEST.md`). IPv6 addresses (`fd7a:115c:a1e0::/48`) are not used in this UgPhone bot integration contract.
4. **Leading Zero Octets**: IP strings like `100.01.2.3` are treated as malformed to prevent octal ambiguity in downstream tools.

---

## 4. Conclusion

### Core Findings Summary
Challenger 1's findings regarding octet overflow (`100.300.1.1`) and suffix truncation (`100.1.2.2555`) are fully confirmed. Furthermore, this investigation uncovered two additional high-severity edge cases:
1. Regex word boundary `\b` alone is insufficient because `.` is a word boundary delimiter in regex, allowing 5-octet strings (`100.1.2.3.4`) and CIDR notation (`100.1.2.3/24`) to match.
2. The `/vpn status` handler in `worker/fleet_state.js` contained a permissive fallback that bypassed IP validation entirely and broadcasted malformed IPs to Telegram.

### Recommended Fix Strategy & Exact Code Proposals

#### Component 1: `worker/fleet_state.js`

Add the pure validation helper `extractValidTailscaleIp` and update `acknowledgeTailscaleControl`:

```javascript
/**
 * Strictly extracts and validates a Tailscale CGNAT IP (100.x.y.z) from details string.
 * Enforces:
 * 1. Must start with 100.
 * 2. Exactly 4 octets, bounded by negative lookarounds (no preceding/trailing digits, dots, letters, slashes, colons).
 * 3. Each octet 0-255 with no leading zeros (e.g. 01 is rejected).
 */
export function extractValidTailscaleIp(details) {
  const match = String(details || "").match(/(?<![0-9a-zA-Z.])100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![0-9a-zA-Z./:])/);
  if (!match) return null;
  const octets = [Number(match[1]), Number(match[2]), Number(match[3])];
  if (octets.some((o) => o < 0 || o > 255 || isNaN(o))) return null;
  if ([match[1], match[2], match[3]].some((s) => s.length > 1 && s.startsWith("0"))) return null;
  return match[0];
}
```

##### Line 967 Replacement in `worker/fleet_state.js`:
```javascript
// BEFORE (Line 967):
const ipMatch = String(body.details || "").match(/100\.\d{1,3}\.\d{1,3}\.\d{1,3}/);
const tailscaleIp = ipMatch ? ipMatch[0] : null;

// AFTER:
const tailscaleIp = extractValidTailscaleIp(body.details);
```

##### Lines 1020–1026 Replacement in `worker/fleet_state.js` (Status Check Hardening):
```javascript
// BEFORE (Lines 1020–1026):
      } else if (mode === "status") {
        const detailsStr = String(body.details || "").trim();
        const isConnected = isSuccess && (Boolean(tailscaleIp) || (/^CONNECTED\b/i.test(detailsStr) && !/DISCONNECTED/i.test(detailsStr)));
        if (isConnected) {
          const ipDisplay = tailscaleIp || escapeHtml(detailsStr).replace(/^CONNECTED:\s*/i, "");
          msg = `🌐 <b>TRẠNG THÁI TAILSCALE: CONNECTED (${ipDisplay})</b>\n📱 Thiết bị: <code>${deviceId}</code>\n📶 Trạng thái: <b>CONNECTED (${ipDisplay})</b>\n🔒 Mạng nội bộ Tailscale đang hoạt động.`;
        } else {

// AFTER:
      } else if (mode === "status") {
        const isConnected = isSuccess && Boolean(tailscaleIp);
        if (isConnected) {
          msg = `🌐 <b>TRẠNG THÁI TAILSCALE: CONNECTED (${tailscaleIp})</b>\n📱 Thiết bị: <code>${deviceId}</code>\n📶 Trạng thái: <b>CONNECTED (${tailscaleIp})</b>\n🔒 Mạng nội bộ Tailscale đang hoạt động.`;
        } else {
```

---

#### Component 2: `agent/agent.py`

##### Lines 702–723 Replacement in `agent/agent.py`:
```python
# BEFORE (Lines 702–723):
            # Strict status validation to prevent phantom successes (R1)
            if mode == "on":
                ip_match = re.search(r"100\.\d{1,3}\.\d{1,3}\.\d{1,3}", stdout_text)
                is_valid_ip = False
                if ip_match:
                    is_valid_ip = validate_tailscale_cgnat_ip(ip_match.group(0))

                if success and stdout_text.startswith("CONNECTED:") and is_valid_ip:
                    status = "OPENED"
                    executed = True
                    details = stdout_text
                    reason = None
                else:
                    status = "FAILED"
                    executed = False
                    details = None
                    reason = reason or "vpn_timeout_no_ip: Timeout 12s không nhận được IP Tailscale (100.x.y.z)"
            elif mode == "status":
                status = "OPENED"
                executed = True
                details = stdout_text if stdout_text else "DISCONNECTED"
                reason = None

# AFTER:
            # Strict status validation to prevent phantom successes (R1)
            tailscale_ip_pattern = r"(?<![0-9a-zA-Z.])100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![0-9a-zA-Z./:])"
            if mode == "on":
                ip_match = re.search(tailscale_ip_pattern, stdout_text)
                is_valid_ip = False
                if ip_match:
                    is_valid_ip = validate_tailscale_cgnat_ip(ip_match.group(0))

                if success and stdout_text.startswith("CONNECTED:") and is_valid_ip:
                    status = "OPENED"
                    executed = True
                    details = f"CONNECTED: {ip_match.group(0)}"
                    reason = None
                else:
                    status = "FAILED"
                    executed = False
                    details = None
                    reason = reason or "vpn_timeout_no_ip: Timeout 12s không nhận được IP Tailscale (100.x.y.z)"
            elif mode == "status":
                status = "OPENED"
                executed = True
                ip_match = re.search(tailscale_ip_pattern, stdout_text)
                if success and stdout_text.startswith("CONNECTED:") and ip_match and validate_tailscale_cgnat_ip(ip_match.group(0)):
                    details = f"CONNECTED: {ip_match.group(0)}"
                else:
                    details = "DISCONNECTED"
                reason = None
```

##### Also Harden `validate_tailscale_cgnat_ip` in `agent/agent.py` (Line 158):
Reject leading zeros in multi-digit octets:
```python
# BEFORE:
    octets = [int(g) for g in m.groups()]
    return all(0 <= o <= 255 for o in octets)

# AFTER:
    if any(len(g) > 1 and g.startswith("0") for g in m.groups()):
        return False
    octets = [int(g) for g in m.groups()]
    return all(0 <= o <= 255 for o in octets)
```

---

## 5. Verification Method

To independently verify the defects and validate the proposed strategy:

### 1. Test Suite Matrix
| Test Command | Purpose | Target Outcome |
|--------------|---------|----------------|
| `python3 -m unittest -v tests/test_adversarial_agent.py` | Runs 16 agent stress tests | Suffix attack currently produces `status=OPENED` (proves defect). |
| `node tests/test_adversarial_fleet.mjs` | Runs 6 fleet adversarial tests | Demonstrates current acceptance of `100.300.1.1` and truncation of `100.1.2.2555`. |
| `python3 -m unittest -v tests/test_adversarial_tailscale.py` | Runs 7 adversarial tests | Confirms `validate_tailscale_cgnat_ip` boundaries. |
| `bash tests/run_all_tests.sh` | Full master test suite | Baseline passes 100% (7/7 suites). |

### 2. Comprehensive 25-Case Boundary Verification Script
Run the following self-contained node snippet to verify that the recommended `extractValidTailscaleIp` correctly handles all 25 edge cases:

```bash
node -e '
function extractValidTailscaleIp(details) {
  const match = String(details || "").match(/(?<![0-9a-zA-Z.])100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![0-9a-zA-Z./:])/);
  if (!match) return null;
  const octets = [Number(match[1]), Number(match[2]), Number(match[3])];
  if (octets.some((o) => o < 0 || o > 255 || isNaN(o))) return null;
  if ([match[1], match[2], match[3]].some((s) => s.length > 1 && s.startsWith("0"))) return null;
  return match[0];
}

const testCases = [
  ["CONNECTED: 100.80.175.55", "100.80.175.55"],
  ["CONNECTED: 100.64.0.1", "100.64.0.1"],
  ["CONNECTED: 100.115.92.14", "100.115.92.14"],
  ["CONNECTED: 100.127.255.254", "100.127.255.254"],
  ["CONNECTED: 100.0.0.0", "100.0.0.0"],
  ["CONNECTED: 100.255.255.255", "100.255.255.255"],
  ["100.80.175.55", "100.80.175.55"],
  ["CONNECTED (100.80.175.55)", "100.80.175.55"],
  ["CONNECTED: 100.80.175.55\n", "100.80.175.55"],
  ["CONNECTED: 100.300.1.1", null],
  ["CONNECTED: 100.1.2.2555", null],
  ["CONNECTED: 100.256.0.1", null],
  ["CONNECTED: 100.1.2.3.4", null],
  ["CONNECTED: .100.1.2.3", null],
  ["CONNECTED: 100.1.2.3.", null],
  ["CONNECTED: 100.1.2.3/24", null],
  ["CONNECTED: 100.64.0.1:80", null],
  ["CONNECTED: 1100.1.2.3", null],
  ["CONNECTED: 100.1.2.3abc", null],
  ["CONNECTED: abc100.1.2.3", null],
  ["CONNECTED: 100.01.2.3", null],
  ["CONNECTED: 192.168.1.1", null],
  ["CONNECTED: 10.0.0.1", null],
  ["TRIGGERED", null],
  ["", null]
];

for (const [input, expected] of testCases) {
  const actual = extractValidTailscaleIp(input);
  if (actual !== expected) throw new Error(`Mismatch on ${input}: got ${actual}, expected ${expected}`);
}
console.log("All 25 test cases verified successfully.");
'
```

### 3. Invalidation Conditions
This investigation report and proposed fix would be invalidated if:
1. Tailscale introduces non-`100.` CGNAT IP ranges or IPv6 within this product scope.
2. The Telegram bot interface explicitly requires displaying connection status for non-Tailscale VPN interfaces.

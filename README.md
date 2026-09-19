# phanserver-delta

Dedicated, isolated vertical slice for **Telegram `/phanserver`** allocation control and **`UPDATE_DELTA`** APK updates.

## Key Features
- **Strict Telegram Command Control**: `/phanserver <device1,device2...> <tabs>` (tabs 1..10).
- **Target Validation**: Case-insensitive device ID normalization, group resolution (`MARMOT`, `NOVA`), online gating, duplicate rejection.
- **Fail-Closed 2PC Protocol**: Two-phase commit (`PREPARE_ALLOCATE_SERVER` -> `COMMIT_ALLOCATE_SERVER` / `ABORT_ALLOCATE_SERVER`) ensuring all target devices succeed or roll back atomically.
- **Atomic File Updates**: Writes `/storage/emulated/0/Download/Shouko/server_links.txt` atomically with automatic rollback to `.bak` upon launcher error.
- **Standalone Delta Updater**: Dedicated release manifest with SHA-256 verification and root access checks.
- **Idempotency & Replay Safety**: Token consumption prevents double-confirmation; local journal prevents duplicate intent executions.

## Repository Layout
```
phanserver-delta/
├── worker/
│   ├── worker.js           # Cloudflare Worker router & endpoints
│   ├── phanserver.js       # Telegram bot command & callback handler
│   ├── fleet_state.js      # FleetState Durable Object (online tracking & 2PC coordinator)
│   └── tong_hop_link.js    # Link pool parser & package mapping
├── data/
│   └── tong_hop_link.txt   # Link pool data
├── delta/
│   ├── manifest.json       # Dedicated Delta release manifest
│   ├── delta_updater.py    # Standalone Delta updater with SHA-256 checks
│   └── tests/              # Delta updater test suite
├── agent/
│   ├── agent.py            # Minimal device agent daemon
│   ├── config.py           # Device config & ID parser
│   ├── server_links.py     # 2PC server links executor & Roblox opener
│   └── tests/              # Device agent test suite
├── tests/
│   ├── test_tong_hop_link.mjs
│   ├── test_telegram_phanserver.mjs
│   ├── test_fleet_state_2pc.mjs
│   ├── test_e2e_flow.py
│   └── run_all_tests.sh    # Full suite runner
└── deploy/
    ├── wrangler.jsonc      # Worker deployment configuration
    └── agent_service.sh    # Device agent start/stop service
```

## Telegram Bot Command Reference (Preiumbot)

| Lệnh | Cú pháp mẫu | Mô tả chi tiết |
| :--- | :--- | :--- |
| **Kiểm tra trạng thái** | `/status` hoặc `STATUS` | Xem trạng thái hoạt động của Hub và danh sách máy Online/Offline. |
| **Danh sách thiết bị** | `/devices` | Xem các mã máy đang kết nối (`m77`, `m72`...). |
| **Xem file Release** | `/apks` hoặc `/release` | Xem danh sách file APK/ZIP mới nhất kèm số thứ tự (1, 2, 3...) và dung lượng. |
| **Cài đặt Delta Roblox** | `/update m77 delta` hoặc `/update m77 delta:1` | Tải và cài đặt toàn bộ 10 bản APK Delta clone (hoặc chỉ định tab như `delta:1`, `delta:1-5`). |
| **Cài đặt Arceus Roblox** | `/update m77 arceus` hoặc `/update m77 arceus:1` | Tải và cài đặt toàn bộ 10 bản APK Arceus clone (hoặc chỉ định tab như `arceus:1`, `arceus:1-5`). |
| **Khôi phục cấu hình Delta** | `/update m77 delta_folder` | Tải và bung file cấu hình `Delta_FolderBackup.zip` (7.8 MB) vào `/sdcard/Delta/`. |
| **Cài đặt tất cả** | `/update all all` | Cài đặt toàn bộ các gói APK/ZIP trong Release cho mọi máy online. |
| **Cài theo số thứ tự** | `/update m77 1` hoặc `1,2,5` | Cài đặt chính xác các file theo số thứ tự từ danh sách `/apks`. |
| **Cài ngẫu nhiên** | `/update m77 random` | Bốc ngẫu nhiên gói cài đặt (`clone:random`, `random:3`). |
| **Cài app riêng lẻ** | `/update m77 warp` | Cài ứng dụng cụ thể: `warp` (1.1.1.1), `opera`, `mt`, `taskbar`. |
| **Sao lưu app** | `/backup m77 all full` | Đóng gói APK + Data và upload lên GitHub Release (Tag: `Backup`). |
| **Nâng cấp Agent** | `/upgrade m77` hoặc `/upgrade all` | Kéo code Git mới nhất và tự khởi động lại ngầm trong 1 giây. |
| **Nạp script Lua** | `/script m77 track <link>` | Ghi script vào `/sdcard/Delta/Autoexecute/track` để tự chạy khi mở game. |
| **Xóa script Lua** | `/script m77 clean all` | Dọn dẹp script khỏi thư mục Autoexecute. |
| **Điều khiển Tailscale VPN** | `/tailscale m77 on` (hoặc `/vpn m77 on`) | Bật/tắt/kiểm tra IP Tailscale VPN (`on`, `off`, `status`). |
| **Phân server Roblox** | `/phanserver m77 10` | Phân phối server links cho các tab Roblox bằng giao thức 2PC nguyên tử. |

> [!IMPORTANT]
> **Lưu ý phân biệt `clone` vs `delta`**:
> * Muốn cài **10 bản APK clone Roblox** (1.6 GB): Dùng `/update <máy> clone` (hoặc `delta_apk`).
> * Muốn khôi phục **thư mục script Delta** (7.8 MB): Dùng `/update <máy> delta`.

## Running Tests
```bash
# Run entire test suite (JS + Python)
./tests/run_all_tests.sh
```

## Deployment
1. **Worker**:
   ```bash
   wrangler deploy
   ```
2. **Device Agent**:
   ```bash
   ./deploy/agent_service.sh start
   ```

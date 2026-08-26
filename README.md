# phanserver-delta

Dedicated, isolated vertical slice for **Telegram `/phanserver`** allocation control and **`UPDATE_DELTA`** APK updates.

## Key Features
- **Strict Telegram Command Control**: `/phanserver <device1,device2...> <tabs>` (tabs 1..10).
- **Target Validation**: Case-insensitive device ID normalization, group resolution (`MARMOT`, `NOVA`), online gating, duplicate rejection.
- **Fail-Closed 2PC Protocol**: Two-phase commit (`PREPARE_ALLOCATE_SERVER` -> `COMMIT_ALLOCATE_SERVER` / `ABORT_ALLOCATE_SERVER`) ensuring all target devices succeed or roll back atomically.
- **Authenticated Live Agent**: Heartbeat plus authenticated WebSocket command reception; a missing/invalid Device ID fails closed instead of aliasing another machine.
- **Zero-Touch Fresh-Device Onboarding**: one installer command creates identity/group/config, asks for Telegram-admin approval with a matching 6-digit code, installs an exact pinned Git revision, starts the standalone service, and verifies the device ONLINE before reporting READY.
- **Atomic File Updates**: Writes `/storage/emulated/0/Download/Shouko/server_links.txt` atomically with automatic rollback to `.bak` upon launcher error.
- **Standalone Delta Updater**: Dedicated release manifest with SHA-256 verification and root access checks.
- **Idempotency & Replay Safety**: Token consumption prevents double-confirmation; local journal prevents duplicate intent executions.

## Fresh UGPhone Onboarding

Normal first-time setup takes only the intended Device ID and group. For example, `73 2` becomes device `m73` in group `NOVA` (`1` = `MARMOT`, `2` = `NOVA`). The installer itself creates `device_id.txt`, `device_group.txt`, and `agent_config.json`; do not create those files by hand.

```bash
curl -fsSL https://raw.githubusercontent.com/tinhpr9/phanserver-delta/main/deploy/install.sh | bash -s -- 73 2
```

On first pairing the UGPhone prints a 6-digit verification code and the Telegram bot sends the same code with **✅ Chấp nhận** / **❌ Từ chối**. Approve only when both codes match. The global Worker control secret is never returned to the device; the approved device receives its own random credential.

Setup is successful only when the final output includes:

```text
PHANSERVER_SERVER_ONLINE=YES
PHANSERVER_ALLOCATE_CAPABILITY=YES
PHANSERVER_ONBOARDING=READY
```

After that, normal use is Telegram-only:

```text
/phanserver m73 3
```

The `3` means three Roblox app/package slots on `m73`. The allowed range is 1..10.

For staging or evidence-gated verification, `PHANSERVER_WORKER_ORIGIN` may point the installer at a non-production Worker and `PHANSERVER_REF` may pin an exact branch/tag/commit. The installer resolves any supplied ref to a 40-hex Git commit before downloading runtime files.

## Repository Layout

```text
phanserver-delta/
├── worker/
│   ├── worker.js                # Cloudflare Worker router & endpoints
│   ├── phanserver.js            # Telegram /phanserver + pairing callbacks
│   ├── fleet_state.js           # Base online tracking & 2PC coordinator
│   ├── secure_fleet_state.js    # Pairing + per-device authentication layer
│   └── tong_hop_link.js         # Link pool parser & package mapping
├── data/
│   └── tong_hop_link.txt        # Link pool data
├── delta/
│   ├── manifest.json            # Dedicated Delta release manifest
│   ├── delta_updater.py         # Standalone Delta updater with SHA-256 checks
│   └── tests/                   # Delta updater test suite
├── agent/
│   ├── agent.py                 # Heartbeat + WebSocket device daemon
│   ├── config.py                # Device config & ID parser
│   ├── server_links.py          # 2PC server links executor & Roblox opener
│   └── tests/                   # Device agent test suite
├── tests/
│   ├── test_tong_hop_link.mjs
│   ├── test_telegram_phanserver.mjs
│   ├── test_fleet_state_2pc.mjs
│   ├── test_pairing.mjs
│   ├── test_onboarding_install.py
│   ├── test_e2e_flow.py
│   └── run_all_tests.sh
├── deploy/
│   ├── install.sh               # One-time fresh-device onboarding
│   ├── device_service.sh        # Installed standalone agent supervisor
│   └── agent_service.sh         # Repository/dev start-stop helper
└── wrangler.jsonc               # Worker deployment configuration
```

## Running Tests

```bash
./tests/run_all_tests.sh
```

## Worker Deployment

```bash
wrangler deploy
```

A fresh-device onboarding flow is not considered verified from unit tests or CI alone. It requires a fresh UGPhone end-to-end gate that proves the exact Device ID transitions from not-ready to ONLINE and can complete a real `/phanserver` allocation.

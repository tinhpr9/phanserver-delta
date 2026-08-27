# phanserver-delta

Dedicated, isolated vertical slice for **Telegram `/phanserver`** allocation control and **`UPDATE_DELTA`** APK updates.

## Key Features
- **Strict Telegram Command Control**: `/phanserver <device1,device2...> <tabs>` (tabs 1..10).
- **Authenticated Telegram Ingress**: `/telegram/webhook` fails closed unless Telegram presents the configured webhook secret token.
- **Target Validation**: Case-insensitive device ID normalization, group resolution (`MARMOT`, `NOVA`), online gating, duplicate rejection.
- **Fail-Closed 2PC Protocol**: Two-phase commit (`PREPARE_ALLOCATE_SERVER` -> `COMMIT_ALLOCATE_SERVER` / `ABORT_ALLOCATE_SERVER`) ensuring all target devices succeed or roll back atomically.
- **Authenticated Live Agent**: Heartbeat plus authenticated WebSocket command reception; a missing/invalid Device ID fails closed instead of aliasing another machine.
- **Zero-Touch Fresh-Device Onboarding**: one installer command creates identity/group/config, asks for Telegram-admin approval with a matching 6-digit code, installs an exact pinned Git revision, starts the standalone service, and verifies the device ONLINE before reporting READY.
- **Private Runtime State**: onboarding identity, credential, journal, and server-link state live under `$HOME/.phanserver-delta/device`, not Android shared storage.
- **Transactional Rollback**: failed startup/ONLINE verification restores the previous identity, group, config, service wrapper, boot entry, and active release pointer.
- **Standalone Delta Updater**: dedicated release manifest with SHA-256 verification and root access checks.
- **Idempotency & Replay Safety**: token consumption prevents double-confirmation; local journal prevents duplicate intent executions.

## Fresh UGPhone Onboarding

Normal first-time setup takes only the intended Device ID and group. For example, `73 2` becomes device `m73` in group `NOVA` (`1` = `MARMOT`, `2` = `NOVA`). The installer itself creates the identity and credential files; do not create them by hand.

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
│   ├── worker.js                # Public Worker router + Telegram ingress gate
│   ├── phanserver.js            # Telegram /phanserver + pairing callbacks
│   ├── fleet_state.js           # Base online tracking & 2PC coordinator
│   ├── secure_fleet_state.js    # Pairing + per-device authentication layer
│   ├── hardened_fleet_state.js  # Public-route, rotation, socket/ACK hardening
│   └── tong_hop_link.js         # Link pool parser & package mapping
├── data/
│   └── tong_hop_link.txt        # Link pool data
├── delta/
│   ├── manifest.json            # Dedicated Delta release manifest
│   ├── delta_updater.py         # Standalone Delta updater with SHA-256 checks
│   └── tests/                   # Delta updater test suite
├── agent/
│   ├── agent.py                 # Base heartbeat/2PC behavior
│   ├── secure_agent.py          # Production WebSocket transport entrypoint
│   ├── config.py                # Device config & ID parser
│   ├── server_links.py          # 2PC server links executor & Roblox opener
│   └── tests/                   # Device agent test suite
├── tests/
│   ├── test_tong_hop_link.mjs
│   ├── test_telegram_phanserver.mjs
│   ├── test_fleet_state_2pc.mjs
│   ├── test_pairing.mjs
│   ├── test_worker_security.mjs
│   ├── test_onboarding_install.py
│   ├── test_e2e_flow.py
│   └── run_all_tests.sh
├── deploy/
│   ├── install.sh               # Small one-time bootstrap loader
│   ├── install_runtime.sh       # Pinned transactional onboarding runtime
│   ├── device_service.sh        # Installed standalone agent supervisor
│   └── agent_service.sh         # Repository/dev start-stop helper
└── wrangler.jsonc               # Worker deployment configuration
```

## Running Tests

```bash
./tests/run_all_tests.sh
```

## Worker Deployment

Production Telegram ingress requires two Worker secrets:

- `TELEGRAM_BOT_TOKEN`: the Telegram bot token.
- `TELEGRAM_WEBHOOK_SECRET`: a separate random webhook secret containing only letters, digits, `_`, or `-`.

The production deployment workflow expects matching GitHub Actions secrets with those names. It stores them in Cloudflare, deploys the Worker, then calls Telegram `setWebhook` with the same webhook secret. This keeps the Worker and Telegram configuration synchronized and prevents a caller from forging an admin update by posting arbitrary JSON to the public webhook.

A fresh-device onboarding flow is not considered verified from unit tests or CI alone. It requires a fresh UGPhone end-to-end gate that proves the exact Device ID transitions from not-ready to ONLINE and can complete a real `/phanserver` allocation.

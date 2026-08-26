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

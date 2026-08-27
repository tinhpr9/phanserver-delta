# AGENTS.md — Phanserver & Delta Architecture Specifications

## System Boundary & Core Purpose
`phanserver-delta` is a dedicated, minimal, fail-closed vertical slice containing exclusively:
1. **Telegram `/phanserver` Control Path**: Authenticated Telegram webhook ingress, interactive syntax `/phanserver <device1,device2...> <tabs>`, URL parsing, preview inline keyboard, 2PC dispatch.
2. **Device State & Target Validation**: Active online device validation, deduplication, group mapping (`MARMOT`, `NOVA`), capability enforcement (`allocate_server_2pc`).
3. **Pending Allocation Lifecycle**: Single-use token reservation (5-minute TTL), double-click prevention, confirm/cancel safety.
4. **2PC Server Links Allocation**: Two-phase commit protocol (`PREPARE_ALLOCATE_SERVER` -> `COMMIT_ALLOCATE_SERVER` / `ABORT_ALLOCATE_SERVER`) coordinating atomic `server_links.txt` updates across devices.
5. **Minimal Device Agent**: Heartbeat reporting, authenticated WebSocket command reception, `APPLY_SERVER_LINKS` execution, and `UPDATE_DELTA` dispatch.
6. **Standalone Delta Updater**: Dedicated release channel, SHA-256 asset checksum verification, root privilege verification, and fail-closed APK installation.
7. **One-Time Zero-Touch Device Onboarding**: A narrowly scoped installer may materialize this service on a fresh UGPhone from explicit `device_id` + group input, obtain a per-device credential only after Telegram-admin approval, install an exact pinned repository revision, start the standalone agent, and prove the device ONLINE with `allocate_server_2pc` before reporting READY.

## Security & Control-Plane Contract
- `/telegram/webhook` MUST fail closed unless `TELEGRAM_WEBHOOK_SECRET` is configured and the request presents the matching `X-Telegram-Bot-Api-Secret-Token` header.
- `TELEGRAM_WEBHOOK_SECRET` is distinct from the bot token and device credentials. Production deployment MUST keep the Worker secret and Telegram `setWebhook(secret_token=...)` configuration synchronized.
- Public HTTP callers MUST NOT reach fleet-wide `/aot/hub/state`, `/aot/hub/control`, or legacy `/register` behavior. Fleet-wide control remains internal to the Worker -> Durable Object path.
- Pair approval MUST require both the internal decision key and the unguessable decision capability embedded only in the Telegram callback. Knowing a public `pair_id` is insufficient.
- Re-pairing an existing Device ID MUST invalidate sockets authenticated with the previous credential before the new credential becomes authoritative.
- WebSocket device credentials MUST be carried in the `X-Agent-Secret` handshake header, never in the WebSocket URL query string.
- ACKs arriving on an authenticated WebSocket MUST be bound to that socket's authenticated Device ID; direct HTTP ACKs continue to require device authentication.

## Zero-Touch Onboarding Contract
- A fresh device MUST NOT invent, copy, or fall back to another identity. Missing or invalid `device_id` is fatal; in particular there is no `m72` default.
- Normal onboarding input is only the intended Device ID and group. The operator MUST NOT hand-create `device_id.txt`, `device_group.txt`, or `agent_config.json`.
- Pairing is possession + admin gated: the device receives a short-lived pairing token and 6-digit verification code; the Telegram administrator must approve the matching code before the Worker releases that device's credential.
- The global Worker control secret MUST NOT be returned to a device. Approved devices receive a random per-device secret; stored device authentication uses its SHA-256 digest.
- Runtime authentication applies to heartbeat, WebSocket command transport, and allocation ACKs. Wrong or missing credentials fail closed.
- Fresh-device identity, group, config, state, and server-link journal live under `$HOME/.phanserver-delta/device`, not Android shared storage.
- Installer source resolves to an exact 40-hex Git commit before runtime files are downloaded. Runtime files live under immutable revision directories.
- On any post-install startup or ONLINE-verification failure, identity, group, config, service wrapper, boot entry, and active release pointer MUST roll back as one transaction before the prior runtime is restarted.
- After onboarding, production runtime has no import, configuration-path, or execution dependency on `Aotscript`.
- `PHANSERVER_ONBOARDING=READY` may be emitted only after the server sees the exact Device ID ONLINE and advertising `allocate_server_2pc`.
- Unit/CI success is not sufficient for fresh-device readiness. A fresh UGPhone end-to-end gate is required before declaring this onboarding flow VERIFIED or READY_TO_MERGE.

## Excluded Components Policy
The following monolithic features remain strictly excluded from this repository:
- General setup wizards & bootstrap frameworks (`setup/aotsetup/msetup`, Aotscript `Termuxboot`, `provision-device.sh`). The only exception is this repository's bounded `deploy/install.sh` + `deploy/install_runtime.sh` for one-time `phanserver-delta` onboarding.
- Identity & clone migrations (`antigraviny_migration`, `agy-*`, Swift clone).
- Backup & restore (`OPEN_SWIFT_BACKUP`, `BACKUP_RESTORE_DATA`).
- Captcha solvers & solver relays.
- Custom group loaders & autoexecute synchronizers (`Marmotgag2`, `Novagag2`).
- Rollout managers & release scanners for unrelated worker binaries.
- Repair loops & fleet batch scripts.

## Protocol Contracts
- **Protocol Identifier**: `fleet-batch-v1`
- **Actions**:
  - `ALLOCATE_SERVER`
    - `PREPARE_ALLOCATE_SERVER`: payload includes per-device `allocation` list `[{pkg: "com.tinh.vv.h[i-r]", url: "https://..."}]`.
    - `COMMIT_ALLOCATE_SERVER`: atomic file commit and intent launch.
    - `ABORT_ALLOCATE_SERVER`: discard uncommitted candidates.
  - `UPDATE_DELTA`: downloads manifest and installs verified APKs.
- **Statuses**: `PREPARE_READY`, `PREPARE_FAILED`, `ALLOCATED`, `OPENED`, `FAILED`, `TIMEOUT`, `DUPLICATE`.

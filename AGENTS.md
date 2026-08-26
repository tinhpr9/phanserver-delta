# AGENTS.md — Phanserver & Delta Architecture Specifications

## System Boundary & Core Purpose
`phanserver-delta` is a dedicated, minimal, fail-closed vertical slice containing exclusively:
1. **Telegram `/phanserver` Control Path**: Interactive syntax `/phanserver <device1,device2...> <tabs>`, URL parsing, preview inline keyboard, 2PC dispatch.
2. **Device State & Target Validation**: Active online device validation, deduplication, group mapping (`MARMOT`, `NOVA`), capability enforcement (`allocate_server_2pc`).
3. **Pending Allocation Lifecycle**: Single-use token reservation (5-minute TTL), double-click prevention, confirm/cancel safety.
4. **2PC Server Links Allocation**: Two-phase commit protocol (`PREPARE_ALLOCATE_SERVER` -> `COMMIT_ALLOCATE_SERVER` / `ABORT_ALLOCATE_SERVER`) coordinating atomic `server_links.txt` updates across devices.
5. **Minimal Device Agent**: Heartbeat reporting, `APPLY_SERVER_LINKS` execution, and `UPDATE_DELTA` dispatch.
6. **Standalone Delta Updater**: Dedicated release channel, SHA-256 asset checksum verification, root privilege verification, and fail-closed APK installation.

## Excluded Components Policy
The following monolithic features are strictly excluded from this repository:
- Setup wizards & bootstrap routines (`setup/aotsetup/msetup`, `Termuxboot`, `provision-device.sh`).
- Identity & clone migrations (`antigraviny_migration`, `agy-*`, Swift clone).
- Backup & restore (`OPEN_SWIFT_BACKUP`, `BACKUP_RESTORE_DATA`).
- Captcha solvers & solver relays.
- Custom group loaders & autoexecute synchronizers (`Marmotgag2`, `Novagag2`).
- Rollout managers & release scanners for worker binaries.
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

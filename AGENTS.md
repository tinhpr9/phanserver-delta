# AGENTS.md — Phanserver & Delta Architecture Specifications

## System Boundary & Core Purpose
`phanserver-delta` is a dedicated, minimal, fail-closed vertical slice containing exclusively:
1. **Telegram `/phanserver` Control Path**: Interactive syntax `/phanserver <device1,device2...> <tabs>`, URL parsing, preview inline keyboard, 2PC dispatch.
2. **Device State & Target Validation**: Active online device validation, deduplication, group mapping (`MARMOT`, `NOVA`), capability enforcement (`allocate_server_2pc`).
3. **Pending Allocation Lifecycle**: Single-use token reservation (5-minute TTL), double-click prevention, confirm/cancel safety.
4. **2PC Server Links Allocation**: Two-phase commit protocol (`PREPARE_ALLOCATE_SERVER` -> `COMMIT_ALLOCATE_SERVER` / `ABORT_ALLOCATE_SERVER`) coordinating atomic `server_links.txt` updates across devices.
5. **Minimal Device Agent**: Heartbeat reporting, `APPLY_SERVER_LINKS` execution, and `UPDATE_DELTA` dispatch.
6. **Standalone Delta Updater**: Dedicated `delta-*` GitHub Release channel in this repository, GitHub SHA-256 asset verification, root privilege verification, and fail-closed APK installation.

## Delta Release Invariants
- Delta runtime MUST NOT depend on Aotscript releases.
- A stable release is in the Delta channel only when its tag starts with `delta-` and it is neither draft nor prerelease.
- The APK inventory is dynamic: there is NO fixed APK count, NO fixed list of APK names, and NO required `Delta-*` filename prefix.
- Any safe release asset basename ending in `.apk` is eligible. Spaces and Unicode names are allowed; path components are not.
- If a Delta release contains direct APKs, ALL direct APKs are selected. ZIP assets in the same release are ignored.
- ZIP assets are fallback only when the release contains zero direct APKs; all selected ZIPs are validated before extraction.
- Every selected asset requires positive size and a full GitHub `sha256:` digest from the trusted `tinhpr9/phanserver-delta` release URL.
- UPDATE_DELTA MUST download and verify the complete selected release set before the first `pm install` mutation begins.
- Resource safety limits may bound bytes/archive complexity, but MUST NOT encode a business-level APK count such as 29.

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
  - `UPDATE_DELTA`: resolves the latest stable `delta-*` release from this repository, verifies its full selected asset set, then installs verified APKs.
- **Statuses**: `PREPARE_READY`, `PREPARE_FAILED`, `ALLOCATED`, `OPENED`, `FAILED`, `TIMEOUT`, `DUPLICATE`.

# Explorer 1 Task: Tailscale Device Agent Analysis

## Objective
Investigate how Tailscale is currently controlled and executed on devices in the codebase (e.g. device_agent.py, fleet_manager.py, or any related scripts).

## Specific Questions to Answer
1. Where is Tailscale control logic currently implemented (file, function, command handling like CONTROL_TAILSCALE)?
2. How is Tailscale currently started? (Look for `am start`, package name `com.tailscale.ipn`, `--user 0` usage or absence).
3. How are tap coordinates currently determined? Is screen orientation currently detected, or are hardcoded coordinates used? How can Android orientation (landscape 90°/270° vs portrait 0°/180°) and screen dimensions be detected via adb / dumpsys / wm size / dumpsys input / settings?
4. How is the Connect button and Toggle switch tapped?
5. How is IP / interface currently verified? (Is it prematurely returning `status: OPENED` or `TRIGGERED`? How is `tun0` checked? How is `100.x.y.z` parsed/validated?)
6. What timeout is used (we need 12s timeout with FAILED and specific error reason)?
7. How/when are BACK/HOME keys sent to hide Tailscale UI?
8. Where are the exact files and lines that need modification to satisfy R1 and R2?

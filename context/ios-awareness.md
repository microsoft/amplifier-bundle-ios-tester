# iOS Testing (ios-tester)

Drives iOS apps on simulators and physical devices via the `ios_inspector` tool — accessibility-tree-driven interaction with screenshot-based visual verification.

## The One Rule That Matters

**The accessibility tree is the sensor. The screenshot is for judgment, never for targeting.**

Measured live on a simulator, same screenshot, same element (the "General" row in Settings): tree truth `[48,1132][1131,1288]` center **(590, 1210)**; a VLM estimated **(590, 1080)** — **130px off, landing on the row above.** **The miss is silent**: no error, and a screenshot that still looks plausible.

## Points vs Pixels — the iOS-Only Trap

The tree is in **points** (393×852); screenshots are **pixels** (1179×2556); scale **3.0**. Mixing them is a silent 3× error. Every number the tool returns is labeled `*_points` or `*_pixels` — **use those fields; never convert yourself, never use an unlabeled number.**

## Three Tiers — What Each Can Actually Do

| Tier | Can SEE | Can TAP | Status |
|---|---|---|---|
| **Simulator** (Xcode only) | labels **+ frames** | yes | proven |
| **Device — free** (cable + Developer Mode) | screenshot, element list, syslog | **no — the element list has no geometry at all** | proven |
| **Device — WebDriverAgent** (+ Apple Developer account, signing) | yes | yes | unproven |

`tap` on `backend="device"` **refuses**. The free-tier element list carries only `caption`, `estimated_uid`, `platform_identifier`, `spoken_description` — no frame, no rect, no bounds. Tapping from captions alone is precisely the silent miss this bundle exists to prevent.

## Available Agents

| Agent | Use For |
|-------|---------|
| `ios-tester:ios-operator` | Boot a simulator, install, launch, drive the UI, verify end-to-end. Also device identity/apps/syslog on the free tier |
| `ios-tester:ios-visual-tester` | Screenshot sweeps, clipping/blank/overlap detection, before/after comparison of a layout fix |
| `ios-tester:ios-debugger` | Root-cause anomalies: a tap that did nothing, text that vanished, a blank screen, tree/syslog correlation |

## Division of Labour

Covers **iOS simulator and physical-device UI only**. Route elsewhere for:

| Target | Bundle |
|---|---|
| Android emulator or device | `android-tester` |
| Web UI, browsers, SPAs | `browser-tester` |
| TUI and CLI applications | `terminal-tester` |
| **iOS app on a simulator or device** | **this bundle** |

## Delegate — Do Not Drive simctl Yourself

**Do not run `simctl`, `axe`, `xcrun`, or `pymobiledevice3` from the root session.** Delegate to an ios-tester agent. The agents hold the safety raw `simctl` does not enforce: UDID scoping, points/pixels discipline, dump-before-tap, focus assertion before typing, and the device-tier tap refusal.

## Prerequisites

- **macOS with Xcode**, not just Command Line Tools. If `xcode-select` points at CommandLineTools, `simctl` appears missing — set `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`, which needs **no sudo**.
- `axe` (`brew install cameroncooke/axe/axe`) for the simulator; `pymobiledevice3` for the device tier
- Device tier only: cable, Developer Mode enabled, Developer Disk Image mounted

**Setup problems are a supported path, not a dead end.** `doctor` reports every host problem at once with its fix; `create_sim` provisions a simulator. The bundle does not install Xcode. If prerequisites are missing, the agents report the exact fix and stop.

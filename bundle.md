---
bundle:
  name: ios-tester
  version: 0.1.0
  description: iOS app testing on simulators and physical devices — accessibility-tree-driven interaction with visual verification

includes:
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
  - bundle: ios-tester:behaviors/ios-tester

---

# iOS Tester

Test, drive, and debug iOS applications on simulators and physical devices from within Amplifier sessions.

Closes the gap that unit tests and server-side `curl` cannot: **the failure is always at the render/interaction layer, and no agent has ever seen the screen.**

## The Load-Bearing Rule

**The accessibility tree is the sensor. The screenshot is for judgment, never for targeting.**

Tap coordinates come from `ui_dump` (the accessibility tree). Screenshots answer *"does this look right, is anything clipped, what state am I in"* — they never produce coordinates. Measured live on a booted simulator, same screenshot, same element (the "General" row in Settings): the tree's truth was `[48,1132][1131,1288]`, center **(590, 1210)**; a VLM reading the PNG estimated center **(590, 1080)** — **130px off, landing on the row above.** The tap misses, and nothing tells you.

## The iOS-Only Trap: Points vs Pixels

The accessibility tree reports **points**. Screenshots are **pixels**.

```
tree:       393 x 852    (points)
screenshot: 1179 x 2556  (pixels)
scale:      3.0
```

Mixing them is a silent 3× coordinate error. The tool owns the conversion and labels every number it returns (`*_points` / `*_pixels`). **Agents never convert, and never use an unlabeled number.**

## Three Tiers, Honestly Labeled

| Tier | Setup cost | Can SEE | Can TAP | Status |
|---|---|---|---|---|
| **Simulator** | Xcode only | labels **+ frames** | yes | **proven** |
| **Device — free** | cable + Developer Mode | screenshot, element list, syslog | **no — the element list carries no geometry** | **proven** |
| **Device — WebDriverAgent** | + Apple Developer account, signing | yes | yes | **unproven** |

The free device tier is real and worth using: device identity, app inventory, live syslog, and screenshots with no Apple Developer account and no signing. It simply **cannot drive the UI** — and `tap` on `backend="device"` refuses rather than guessing.

## How It Works

The `ios_inspector` tool wraps `simctl`, `axe`, and `pymobiledevice3` with a selector-first contract. Every interaction resolves a selector against a live accessibility dump before touching the screen — the safe path is the default path, and raw coordinates (`tap_xy`) require conspicuous opt-in.

Three specialist agents drive it: an **operator** (boot → install → launch → interact → verify), a **visual tester** (screenshot sweeps, clipping and regression detection), and a **debugger** (root-cause analysis for anomalies).

## Prerequisites

- **macOS with Xcode** (not just Command Line Tools). `DEVELOPER_DIR` pointing at `Xcode.app/Contents/Developer` fixes a CommandLineTools-selected host **without sudo**.
- `axe` for simulator interaction — `brew install cameroncooke/axe/axe`
- `pymobiledevice3` for anything that must reach a physical device
- For the device tier: a cable, Developer Mode enabled, and a mounted Developer Disk Image

The `doctor` operation reports every host problem at once, each with its fix, and `create_sim` provisions a simulator when none exists. Setup gaps are a diagnosable path, not a dead end — the bundle does not install Xcode.

@foundation:context/shared/common-system-base.md

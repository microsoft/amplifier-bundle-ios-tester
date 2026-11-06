# iOS Testing (ios-tester)

Drives iOS apps on simulators and physical devices via the `ios_inspector` tool — accessibility-tree-driven interaction, screenshot-based visual verification.

**The accessibility tree is the sensor; the screenshot is for judgment, never for targeting.** Measured on a simulator, same screenshot, same element (the "General" row in Settings): tree truth `[48,1132][1131,1288]`, center **(590, 1210)**; a VLM estimated **(590, 1080)** — 130px off, landing on the row above. The miss is silent: no error, and a screenshot that still looks plausible.

**Points vs pixels, the iOS-only trap.** The tree is in points (393×852), screenshots in pixels (1179×2556), scale 3.0; mixing them is a silent 3× error. Use the tool's labeled `*_points` / `*_pixels` fields; never convert yourself.

**Three tiers.** Simulator (Xcode only) can SEE labels **and frames** and can TAP — proven. Device, free tier (cable + Developer Mode), sees a screenshot, an element list and syslog but **cannot tap** — proven. Device via WebDriverAgent (+ Apple Developer account, signing) sees and taps — unproven. `tap` on `backend="device"` **refuses** — the free-tier element list has no geometry at all (see the tool's own `device_elements` contract), and tapping from captions alone is precisely the silent miss this bundle exists to prevent.

**Agents.** `ios-tester:ios-operator` drives and verifies (boot, install, launch, exercise a flow; also device identity/apps/syslog on the free tier); `ios-tester:ios-visual-tester` judges how a screen LOOKS (screenshot sweeps, clipping/blank/overlap, before/after); `ios-tester:ios-debugger` root-causes why something broke (a tap that did nothing, text that vanished, a blank screen, tree/syslog correlation).

**Scope: iOS simulator and physical-device UI only.** Route an Android emulator or device to `android-tester`, web UI / browsers / SPAs to `browser-tester`, TUI and CLI applications to `terminal-tester`.

**Delegate — do not drive simctl yourself.** Do not run `simctl`, `axe`, `xcrun` or `pymobiledevice3` from the root session. The agents hold the safety raw `simctl` does not enforce: UDID scoping, points/pixels discipline, dump-before-tap, focus assertion before typing, and the device-tier tap refusal.

**Prerequisites.** macOS with **Xcode**, not just Command Line Tools — if `xcode-select` points at CommandLineTools, `simctl` appears missing; set `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`, which needs **no sudo**. `axe` (`brew install cameroncooke/axe/axe`) for the simulator, `pymobiledevice3` for the device tier. The device tier also needs a cable, Developer Mode enabled and the Developer Disk Image mounted, and **the path differs by iOS version** — measured Aug 2026, `devicectl` reports an iOS 16.7 device *unavailable* (use `pymobiledevice3` + manual DDI) but sees an iOS 26.6 device natively, so read `ProductVersion` first. A signed device build **over SSH fails at signing** — measured 0 codesigning identities over ssh vs 2 in the GUI session — so it must run in the Mac's GUI session; see TROUBLESHOOTING.md.

Setup problems are a supported path, not a dead end: `doctor` reports every host problem at once with its fix, and `create_sim` provisions a simulator. The bundle does not install Xcode; if prerequisites are missing the agents report the exact fix and stop.

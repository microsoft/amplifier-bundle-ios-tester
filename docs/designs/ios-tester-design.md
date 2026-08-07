# ios-tester — Design

**Status:** design. Every capability below was proven live on a real Mac + a real iPhone X
before this document was written. Where something is unproven, it says so.

## Why `ios-tester` and not `iphone-tester`

Device type is a **parameter**, not a platform. `simctl` puts iPhone and iPad in one
`SimDeviceType` namespace with identical `create/boot/install/launch` verbs; `xcodebuild
-destination` uses the same syntax for both; Appium's XCUITest driver covers iOS/iPadOS/tvOS as
one driver. Splitting the bundle would duplicate everything to encode a string. Same call as
`android-tester`, which covers phones and tablets without comment.

## The load-bearing constraint (re-measured on iOS)

**The accessibility tree is the sensor. The screenshot is for judgment, never for targeting.**

Measured on a booted simulator, same screenshot, same element (the "General" row in Settings):

| Source | Pixels | Center |
|---|---|---|
| `axe describe-ui` (truth) | `[48,1132][1131,1288]` | (590, 1210) |
| VLM reading the PNG | `[36,1000][1143,1160]` | (590, 1080) |

Delta **dy = −130px**. The VLM-derived center falls **outside** the real row — it lands on the
row above, and the tap fails silently. Different number from Android's 61/93px miss; identical
lesson, independently re-measured on this platform.

### An iOS-only trap Android does not have

The accessibility tree reports **points**; screenshots are **pixels**.

```
tree:       393 x 852   (points)
screenshot: 1179 x 2556 (pixels)
scale:      3.0
```

Mixing them is a silent 3× coordinate error. This belongs in the tool, not in a doc — the tool
must own the conversion and never hand a caller a raw number whose unit is ambiguous.

## Three tiers, honestly labeled

Feasibility is not binary here. It splits cleanly by what you're willing to pay.

| Tier | Setup cost | Can SEE | Can TAP safely | Status |
|---|---|---|---|---|
| **Simulator** | Xcode only | ✅ labels **+ frames** | ✅ | **proven** |
| **Device — free** | cable + Developer Mode | ✅ screenshot, element list, syslog | ❌ **no rects** | **proven** |
| **Device — WDA** | + Apple Developer account, signing | ✅ | ✅ | **unproven** |

The middle tier is real and worth shipping: device identity, app inventory, live syslog, and
screenshots with no Apple Developer account and no signing. It simply **cannot drive the UI**,
because the element list carries no geometry:

```json
{ "caption": "100% battery power, Charging, ...",
  "estimated_uid": "06000000-...",
  "platform_identifier": "21000000C048...",
  "spoken_description": "..." }
```

Full key set: `caption`, `estimated_uid`, `platform_identifier`, `spoken_description`. A grep of
the entire payload for `frame|rect|bounds|x|y|width|height` returns **zero**. Tapping from
captions alone would be exactly the silent-miss failure this bundle exists to prevent, so the
tool must **refuse** to tap on the free device tier rather than guess.

## What was proven, and how

**Simulator (macOS 26.6, Xcode 26.6, arm64, over bare SSH):**

| Step | Evidence |
|---|---|
| Boot headless over SSH | 2.7s to Booted — the single biggest feasibility risk, cleared |
| Screenshot | 1179×2556 PNG via `simctl io screenshot` |
| Element tree + frames | 33 labeled elements; `General` → `{{16, 377.33}, {361, 52}}` |
| Selector-resolved tap | `axe tap --label "General"` → resolved (196.5, 403.3) → tree went 32 → 73 elements |

**Physical device (iPhone X, iPhone10,6, iOS 16.7.16, arm64):**

| Step | Evidence |
|---|---|
| Pair + identify | UDID, model, build `20H392` |
| Developer Mode | enabled programmatically — `true` from two independent tools |
| DDI mount | Xcode 26 ships **no 16.7 image**; the **16.4** image mounted on 16.7 anyway |
| Screenshot | 1125×2436 PNG off the real device |
| Element list | works — **but no geometry** (see above) |

## Toolchain decisions, with reasons

- **Simulator backend: `axe`** (`brew install cameroncooke/axe/axe`), which vendors current idb
  frameworks. Chosen over `idb-companion` because the Homebrew idb build is from **Aug 2022** and
  emits class-conflict warnings against Xcode 26. Proven working; idb is not.
- **Device backend: `pymobiledevice3`**, not `libimobiledevice`, for anything that must reach the
  device. See the "tool error vs device error" lesson below — this is not a preference, it is the
  difference between getting an answer and getting a local shrug.
- **`DEVELOPER_DIR` over `xcode-select`.** If `xcode-select` points at CommandLineTools, `simctl`
  appears missing. Setting `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer` fixes it
  **with no sudo** — worth knowing, because the documented fix (`sudo xcode-select -s`) needs a
  password and blocks turnkey setup.

## Hard-won lessons the tool must own

Each of these cost real time to discover. They belong in code or in `doctor` output, not in prose
a reader may skip.

1. **Re-seat the *adapter*, not the device.** A device behind a hub, dock, or multiport adapter can
   vanish; the hub holds a stale downstream port state that unplugging the *device* does not clear.
   Signature: `ioreg` shows hubs but no device. `doctor` should name the hubs it sees when no
   device is found.
2. **Connections drop unprompted.** The link disappeared mid-session with nobody touching it.
   Detect mid-run disappearance and fail loudly rather than emitting a confusing downstream error.
3. **"Cannot enable developer-mode when passcode is set."** Undocumented, and it cost six rounds.
   `doctor` must detect a passcode and say this *before* the user tries anything else.
4. **A tool's error is not the device's error.** `libimobiledevice` checked `DeveloperModeStatus`
   *locally* and refused before sending anything, so no Developer Mode prompt ever appeared on the
   phone. `pymobiledevice3` actually asked the device and returned the real cause. When a
   precondition check can be answered locally *or* by the device, prefer the device.
5. **Newer Xcode is not automatically better.** Xcode 26 ships DDIs for 15.0–16.4 only; each
   release drops older ones. For an iOS 16 device an *older* Xcode is friendlier.

## Guidance rule: never ask for a security downgrade without the round trip

When the tool or an agent asks a user to disable a security setting — a passcode being the live
example — it must state **in the same breath** that the change is temporary and that they will be
asked to restore it, and then actually prompt them to restore it afterwards.

> ✅ "Turn the passcode off temporarily — I'll have you turn it back on as soon as Developer Mode
> is enabled, it's only needed off for that one step."
>
> ❌ "Turn the passcode off." *(…later…)* "Okay, turn it back on."

The second form reads as a security ask with no stated end, and a user is right to push back on it.
This applies to any future prompt of this shape, not just passcodes.

## Tool surface — `tool-ios-inspector`

Single verb-dispatch tool, `_ok`/`_err` envelope, mirroring `android_inspector` so the two are
learnable as one thing. `backend` is `simulator` (default) or `device`.

**Environment**
| op | notes |
|---|---|
| `doctor` | every check, never stops at first failure: Xcode/`DEVELOPER_DIR`, `simctl`, `axe`, `pymobiledevice3`, runtimes, device presence, Developer Mode, **passcode**, DDI availability vs device iOS |
| `list_targets` | simulators + physical devices, one list, ambiguity is an error |

**Simulator lifecycle** — `create_sim`, `boot`, `shutdown`, `install`, `launch`, `terminate`

**Sensing** — `screenshot` (path, never inline), `ui_dump` (parsed, **points and pixels both, explicitly labeled**), `find`, `logs`

**Interacting** — `tap` (selector-resolved: dump → resolve → tap → re-dump → report), `tap_xy`
(raw, conspicuously named, always warns), `type_text` (focus-assert + readback), `key`, `swipe`,
`wait_for` (polls; no bare sleeps)

**Device tier** — `device_info`, `device_screenshot`, `device_apps`, `device_syslog`,
`device_elements` (list only). `tap` on `backend=device` **must refuse** with an error explaining
that no geometry is available and naming WDA as the path that would provide it.

## Explicitly deferred

- **WebDriverAgent backend.** Needs an Apple Developer account and signing. Same tool interface,
  added when someone actually needs on-device tapping.
- **Windows/WSL.** Appium's Linux path needs iOS 18+; the iPhone X caps at 16.7.16, so this device
  can never exercise it. No Simulator on Windows at all. Worst substrate on every axis.
- **Physical-device tap via HID.** `pymobiledevice3` offers normalized-coordinate HID taps whose
  documented workflow is "convert pixels yourself, here are some anchors" — precisely the
  coordinate-guessing this design forbids.

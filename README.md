# amplifier-bundle-ios-tester

**Let an agent actually see and drive the iOS screen** — so UI fixes stop shipping "verified" and arriving broken.

Unit tests pass. Server-side `curl` passes. The user opens the app and the fix is broken. The failure is always at the render/interaction layer, and nothing in the loop has ever looked at the screen. This bundle closes that gap.

## The Load-Bearing Rule

**The accessibility tree is the sensor. The screenshot is for judgment, never for targeting.**

Measured live on a booted simulator — same screenshot, same element (the "General" row in Settings):

| Source | Pixels | Center |
|---|---|---|
| `ui_dump` (the accessibility tree) | `[48,1132][1131,1288]` | **(590, 1210)** |
| VLM reading the PNG | `[36,1000][1143,1160]` | (590, 1080) |

Delta **dy −130px** — the VLM-derived center lands **outside the real row**, on the row above.

And the miss is **silent**. iOS has no concept of "you tapped nothing": no error, no exception, and often a screenshot that still looks right. The dangerous case is landing on a *neighbouring* element — adjacent settings rows sit 156px apart, so a 130px error reliably selects the wrong row. You navigate into the wrong screen, assert against it, and report success.

So: vision answers *"does this look right / what state am I in / is anything clipped"*. **Coordinates always come from `ui_dump`.**

## The iOS-Only Trap: Points vs Pixels

Android has one coordinate space. **iOS has two, and they differ by a factor of 3.**

```
accessibility tree:  393 x 852    (POINTS)
screenshot:         1179 x 2556   (PIXELS)
scale:               3.0
```

Mixing them is a **silent 3× coordinate error** — larger than the VLM miss above, and equally invisible. It is also a phantom-bug generator: an element that looks "wildly misplaced" when you compare its frame against a screenshot is almost always a unit error, not a layout defect.

The tool owns every conversion and **never hands you a number whose unit is ambiguous**:

```python
node = {
    "label": "General",
    "frame_points":  {"x": 16.0, "y": 377.33, "w": 361.0, "h": 52.0},
    "frame_pixels":  {"x": 48,   "y": 1132,   "w": 1083,  "h": 156},
    "center_points": [196.5, 403.33],
    "center_pixels": [590, 1210],
}
```

Agents use the labeled field. They never convert by hand, and they state the unit in every geometric claim they report.

## Three Tiers, Honestly Labeled

Feasibility here is not binary. It splits by what you are willing to pay for.

| Tier | Setup cost | Can SEE | Can TAP | Status |
|---|---|---|---|---|
| **Simulator** | Xcode only | labels **+ frames** | **yes** | **proven** |
| **Device — free** | cable + Developer Mode | screenshot, element list, syslog | **no** | **proven** |
| **Device — WebDriverAgent** | + Apple Developer account, signing | yes | yes | **unproven, not implemented** |

The middle tier is real and worth shipping: device identity, app inventory, live syslog, and screenshots with **no Apple Developer account and no signing**. It simply cannot drive the UI, because the element list carries no geometry — this is a complete element, verbatim:

```json
{ "caption": "100% battery power, Charging, ...",
  "estimated_uid": "06000000-...",
  "platform_identifier": "21000000C048...",
  "spoken_description": "..." }
```

Full key set: `caption`, `estimated_uid`, `platform_identifier`, `spoken_description`. Grepping the whole payload for `frame|rect|bounds|x|y|width|height` returns **zero**.

So **`tap` on `backend="device"` refuses** rather than guessing, and names WebDriverAgent as the path that would provide geometry. A read-only tier that honestly says "I cannot tap" is worth more than a tapping tier that guesses.

## What Was Proven, and How

**Simulator** (macOS 26.6, Xcode 26.6, arm64, over bare SSH):

| Step | Evidence |
|---|---|
| Boot headless over SSH | **2.7s** to `Booted` — the single biggest feasibility risk, cleared |
| Screenshot | 1179×2556 PNG via `simctl io screenshot` |
| Element tree + frames | 33 labeled elements; `General` → `{{16, 377.33}, {361, 52}}` |
| Selector-resolved tap | `axe tap --label "General"` → resolved (196.5, 403.3) → tree went **32 → 73** elements |

**Physical device** (iPhone X, iPhone10,6, iOS 16.7.16, arm64):

| Step | Evidence |
|---|---|
| Pair + identify | UDID, model, build `20H392` |
| Developer Mode | enabled programmatically — confirmed `true` by two independent tools |
| DDI mount | Xcode 26 ships **no 16.7 image**; the **16.4** image mounted on 16.7 anyway |
| Screenshot | 1125×2436 PNG off the real device |
| Element list | works — **but no geometry** |

## How It Works

A single `ios_inspector` tool wraps `simctl`, `axe`, and `pymobiledevice3` with a **selector-first** contract — the safe path is the default path:

- `tap` cannot fire without resolving a selector against a **fresh** accessibility dump
- every geometric field is returned in **both** coordinate spaces, explicitly labeled
- `type_text` asserts focus before typing and asserts readback after
- `wait_for` polls the tree; there are no bare sleeps anywhere
- `tap_xy` (raw coordinates) is named to be conspicuous and warns in its own result
- `tap` on the free device tier **refuses**, because there is no geometry to resolve against

An agent *told* to follow these rules skips them at turn 40 of a long run. A tool that structurally *cannot* skip them does not.

## Quick Start

### Installation

**Add as an app bundle (recommended):**
```bash
amplifier bundle add git+https://github.com/microsoft/amplifier-bundle-ios-tester@main#subdirectory=behaviors/ios-tester.yaml --app
```

**Compose into another bundle:**
```yaml
includes:
  - bundle: git+https://github.com/microsoft/amplifier-bundle-ios-tester@main#subdirectory=behaviors/ios-tester.yaml
    as: ios-tester
```

### Prerequisites

**Start by asking the bundle.** `doctor` takes no parameters, never errors, and tells you everything that is wrong in one call:

```python
report = ios_inspector(operation="doctor")
# report["ready"]   — false if any check failed
# report["checks"]  — [{name, status: ok|warn|fail, detail, remediation}, ...]
# report["summary"] — what to fix first
```

It checks Xcode / `DEVELOPER_DIR`, `simctl`, `axe`, `pymobiledevice3`, available runtimes, existing simulators, device presence (**naming the USB hubs it can see** when none is found), Developer Mode, **passcode status**, and DDI availability versus the device's iOS version. It deliberately **does not stop at the first failure**: you fix the host in one pass instead of discovering its problems one confusing error at a time. A broken machine is a *successful diagnosis*, not a tool error — read `ready`, not `success`.

No simulator? `create_sim` provisions one:

```python
ios_inspector(operation="create_sim", name="ios-harness",
              device_type="iPhone 15", runtime="iOS 17.5")
```

**The underlying requirements:**

| Need | Why |
|---|---|
| **macOS with Xcode** (not just Command Line Tools) | `simctl` and the simulator runtimes live in Xcode |
| `axe` — `brew install cameroncooke/axe/axe` | Simulator interaction. Chosen over `idb`, whose Homebrew build is from **Aug 2022** and conflicts with modern Xcode |
| `pymobiledevice3` | Anything that must reach a physical device |
| Cable + Developer Mode + mounted DDI | Device tier only |

**The one setup gotcha worth knowing up front:** if `xcode-select` points at CommandLineTools, `simctl` appears missing. The documented fix is `sudo xcode-select -s …` — which needs a password and blocks turnkey setup. Setting `DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer` fixes it with **no sudo**. `doctor` reports the `DEVELOPER_DIR` fix, not the `sudo` one.

Full detail, including the passcode blocker and the DDI version dance, in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

### Basic Usage

Delegate to an agent — do not drive `simctl` from the root session.

```python
ios_inspector(operation="doctor")

# Boot — measured 2.7s to Booted, headless, over bare SSH
ios_inspector(operation="boot", udid=udid)

ios_inspector(operation="install", udid=udid, app_path="/tmp/MyApp.app")
ios_inspector(operation="launch",  udid=udid, bundle_id="com.example.app")

# Gate on state, never on time — "Booted" is the device, not your app
ios_inspector(operation="wait_for", udid=udid,
              selector={"identifier": "com.example.root"}, timeout_s=30)

# Coordinates come from the tree — this resolves, taps, re-dumps, reports what changed
ios_inspector(operation="tap", udid=udid, selector={"label": "General"})

# The verified field write: focus assertion + readback
r = ios_inspector(operation="type_text", udid=udid,
                  selector={"identifier": "com.example.url_field"},
                  text="http://localhost:9000")
assert r["verified"], f"field write failed, readback: {r['readback']!r}"

# Screenshot for judgment — never for coordinates
snap = ios_inspector(operation="screenshot", udid=udid)

ios_inspector(operation="shutdown", udid=udid)
```

## Agents

### `ios-operator` (primary) — `[coding, general]`

The driver: boot → install → launch → interact → verify → report. Owns the simulator lifecycle, the points/pixels contract, the verified field-write protocol, the "is this data real" assertion, and the security-downgrade round trip for Developer Mode. Prerequisites self-check via `doctor`, numbered workflow with wait-gates, 3-attempt failure budget.

Use for: installing and exercising an app, verifying a fix landed, configuring settings, end-to-end flow testing, free-tier device surveys.

### `ios-visual-tester` — `[vision, critique, general]`

Visual quality judgment: screenshot sweeps, clipping / blank-region / overlap / truncation detection, safe-area collision review, before-and-after comparison. Its sharpest instrument is **dump-vs-render reconciliation** — the tree says where a node is (in points) and what it says; the image says what got drawn (in pixels). Disagreement between them is a defect with exact geometry attached — provided you compare like with like.

Use for: "screenshot every tab and tell me what looks broken", layout regression sweeps, confirming a styling fix is visible.

### `ios-debugger` — `[coding, reasoning, general]`

Anomaly root-cause via frame diffing, focus tracing, and log correlation. Its core job is separating five failures that all present as "I tapped it and nothing happened": tap missed · **coordinate-space (3×) error** · tap landed but the handler did nothing · something intercepted it · handler ran but the UI did not update. It also owns the device-connectivity catalogue — stale hub port state, unprompted drops, the passcode blocker, and tool-error-vs-device-error.

Use for: non-responsive controls, text that lands in the wrong field, blank screens, a device that vanished mid-run, Developer Mode failures.

## Tool Operations Reference

`backend` is `"simulator"` (default) or `"device"`.

| Operation | Description | Key params |
|-----------|-------------|-----------|
| `doctor` | Full host readiness report; runs every check, never errors | — |
| `list_targets` | Simulators + devices in one list; ambiguity is an **error** | — |
| `create_sim` | Provision a simulator (won't clobber; verifies by re-listing) | `name`, `device_type`, `runtime` |
| `boot` / `shutdown` | Simulator lifecycle. 2.7s to `Booted`, headless | `udid` |
| `install` / `launch` / `terminate` | App lifecycle | `udid`, `app_path` / `bundle_id` |
| `screenshot` | PNG **file path**, geometry in pixels, scale, byte size | `udid` |
| `ui_dump` | Parsed node list, frames + centers in **both labeled spaces** | `udid` |
| `find` | Nodes matching a selector | `udid`, `selector` |
| `logs` | Unified log (simulator) or syslog (device) | `udid`, `predicate`, `lines` |
| `tap` | dump → resolve → tap → re-dump → report change | `udid`, `selector` |
| `type_text` | The verified field-write protocol | `udid`, `selector`, `text` |
| `key` | Key event | `udid`, `key` |
| `swipe` | Gesture — endpoints in **points** | `udid`, `x1,y1,x2,y2` |
| `tap_xy` | **Raw coordinates — conspicuous by design** | `udid`, `x`, `y` |
| `wait_for` | Poll the tree until a selector appears/disappears | `udid`, `selector`, `timeout_s` |
| `device_info` | UDID, model, iOS version, build | `udid` |
| `device_screenshot` | Real screen capture off the device | `udid` |
| `device_apps` | Installed app inventory with bundle IDs | `udid` |
| `device_elements` | Element list — **captions only, no geometry** | `udid` |
| `device_enable_devmode` | Enable Developer Mode (blocked by a set passcode) | `udid` |
| `device_mount_ddi` | Mount the closest available Developer Disk Image | `udid` |

## Selector Syntax

```python
{"identifier": "com.example.save"}       # accessibilityIdentifier — most stable, prefer this
{"label": "Save"}                        # accessibility label (usually the visible text)
{"label_contains": "poll"}               # substring — for dynamic text
{"value": "on"}                          # accessibility value — switches, sliders, fields
{"type": "Button", "index": 0}           # positional — last resort
```

Keys combine; all specified keys must match.

## Key Design Decisions

### Why `ios-tester` and not `iphone-tester`

Device type is a **parameter**, not a platform. `simctl` puts iPhone and iPad in one `SimDeviceType` namespace with identical verbs; `xcodebuild -destination` uses the same syntax for both; Appium's XCUITest driver covers iOS/iPadOS/tvOS as one driver. Splitting the bundle would duplicate everything to encode a string.

### Why the accessibility tree and not vision

See the measurement at the top. This is the decision every other one follows from — independently re-measured on iOS rather than inherited from `android-tester`.

### Why the tool owns points↔pixels

A number without a unit is a bug waiting to happen, and on iOS the two units differ by exactly 3. Making the conversion the tool's job — and labeling every field it returns — removes the entire class of error rather than documenting it.

### Why `axe` and not `idb`

The Homebrew `idb-companion` build is from **August 2022** and emits Objective-C class-conflict warnings against Xcode 26. `axe` vendors current idb frameworks and was proven working end-to-end. idb was not. Not a preference between two working options.

### Why `pymobiledevice3` and not `libimobiledevice`

`libimobiledevice` checks `DeveloperModeStatus` **locally** and refuses before sending anything, so no prompt ever appears on the phone and the real cause (a set passcode) never surfaces. `pymobiledevice3` asks the device and returns the real answer.

The general principle, worth more than the specific choice: **when a precondition can be answered locally or by the device, prefer the device.** A local pre-check that short-circuits gives you a fast, confident, wrong error and zero diagnostic signal from the thing you are debugging.

### Why setup is a tool call, not a checklist

A checklist an agent is told to follow gets skipped when a run gets long. `doctor` is the checklist made structural — one call, every finding, with remediation attached. Including the ones nobody would think to check: whether a passcode is blocking Developer Mode, and which USB hubs are visible when no device is.

### Why the free device tier refuses to tap

Because it would have to guess. That is the failure this bundle exists to prevent, and shipping a tier that guesses would undo the whole argument.

### Explicitly deferred

Named so they are not rediscovered as gaps: **WebDriverAgent** (needs an Apple Developer account and signing — same tool interface when someone needs on-device tapping), **HID taps via `pymobiledevice3`** (its documented workflow is "convert pixels yourself, here are some anchors" — coordinate guessing with extra steps), **Windows/WSL** (Appium's Linux path needs iOS 18+; no Simulator on Windows at all), **Xcode installation** (`doctor` diagnoses; installing is the human's call).

## A Note on Security Prompts

Enabling Developer Mode on a physical device requires the passcode to be **off** — an undocumented iOS precondition that cost six rounds to discover.

When this bundle asks a user to disable a security setting, it states **in the same message** that the change is temporary and that they will be asked to restore it, and then actually prompts them to restore it:

> ✅ "iOS requires the passcode to be off temporarily to enable Developer Mode. I'll have you turn it back on as soon as it's enabled — it's only needed off for that one step."
>
> ❌ "Turn off your passcode." *(…later…)* "Okay, turn it back on."

The second form is a security ask with no stated end, and a user is right to push back on it. The round trip is mandatory, including when the run then fails — a failed run still leaves someone's phone unlocked.

## Related Bundles

| Target | Bundle |
|---|---|
| Android emulator or device | `android-tester` |
| Web UI, browsers, SPAs | `browser-tester` |
| TUI and CLI applications | `terminal-tester` |
| **iOS app on a simulator or device** | **this bundle** |

## Getting Help

For host setup, device connectivity, Developer Mode, DDI mounting, and interaction anomalies, see [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). For the design rationale, see [docs/designs/ios-tester-design.md](docs/designs/ios-tester-design.md).

For general Amplifier questions:

- [Amplifier GitHub](https://github.com/microsoft/amplifier)
- [Amplifier Documentation](https://github.com/microsoft/amplifier/tree/main/docs)

## Contributing

> [!NOTE]
> This project is not currently accepting external contributions, but we're actively working toward opening this up. We value community input and look forward to collaborating in the future. For now, feel free to fork and experiment!

Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit [Contributor License Agreements](https://cla.opensource.microsoft.com).

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.

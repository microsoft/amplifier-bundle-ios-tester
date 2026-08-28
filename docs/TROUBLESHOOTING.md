# iOS Inspector — Troubleshooting Guide

Field knowledge from real sessions on a real Mac (macOS 26.6, Xcode 26.6, arm64, driven over bare SSH) against a real iPhone X (iPhone10,6, iOS 16.7.16, build 20H392). Every entry below cost time to discover. It is written down here so nobody repeats it.

A second round in **August 2026** moved to an **iPhone 12 on iOS 26.6** and paid for a further set of entries — code signing over SSH, `pymobiledevice3` output parsing, the lock state, stale UDIDs, and the fact that the device tier's story changed with iOS 26. Those entries are dated inline, because on this platform a finding without a version is a finding you cannot act on.

Several of these workarounds are **owned by the tool** — `doctor` detects them and names the fix. This document explains *why*, so you recognise the symptom when the tool's automation is not in the path (a manual `xcrun` invocation, a different host, a future Xcode that moves things again).

**See also:** [FIELD-NOTES-2026-08.md](FIELD-NOTES-2026-08.md) — a second, additive set of lessons from an extended real-device project: the full ssh→GUI signing bridge, the unsigned-simulator-leg split, physical-device install and crash-log operations, version discipline, and evidence-verification practice.

---

## Quick Reference: Symptom → Cause → Fix

**Before working through this table by hand, run `doctor`** — one call, no parameters, and it reports every host problem at once with its remediation instead of one per failed operation. Most rows below are things `doctor` names for you.

| Symptom | Cause | Fix |
|---|---|---|
| `xcrun: error: unable to find utility "simctl"` on a Mac with Xcode installed | `xcode-select` points at CommandLineTools | Set `DEVELOPER_DIR`, **no sudo needed**. See [DEVELOPER_DIR vs xcode-select](#developer_dir-vs-xcode-select) |
| Device not detected; `doctor` lists USB hubs but no device | A hub/dock/adapter holds **stale downstream port state** | **Re-seat the adapter, not the phone.** See [Re-seat the adapter, not the device](#re-seat-the-adapter-not-the-device) |
| Device was working, then vanished; nobody touched anything | Connections drop **unprompted** | Detect and fail loudly; do not retry blindly. See [Connections drop unprompted](#connections-drop-unprompted) |
| Signing fails: "no signing identity found" over SSH, but the same build signs by hand | `securityd` will not release a private key to a session that cannot present UI | Run the build **in the GUI session** via Apple Events. See [Code signing cannot reach the keychain over SSH](#code-signing-cannot-reach-the-keychain-over-ssh) |
| Build succeeds; the install step cannot find the `.app` | `rsync --delete` re-synced over the build products | Never re-sync between build and install. See [rsync --delete wipes the build products](#rsync---delete-wipes-the-build-products) |
| `json.load` on `pymobiledevice3` output: `Extra data: line 1 column N` | Log lines share stdout with the JSON payload | Parse from the first `{` / `[`; fail **loudly**. See [pymobiledevice3 mixes logs into its JSON](#pymobiledevice3-mixes-logs-into-its-json) |
| `ERROR Device is password protected. Please unlock and retry` | The device is **locked** — the sleep state is irrelevant | Auto-Lock → Never for the run, restored after. See [A locked device refuses everything](#a-locked-device-refuses-everything) |
| Every command succeeds, against a phone that is not on the desk | A hardcoded UDID went stale when the hardware changed | Ask usbmux; refuse on ambiguity. See [A hardcoded UDID goes stale silently](#a-hardcoded-udid-goes-stale-silently) |
| Device guidance that worked on one phone does not apply to another | The device tier's story **changed with iOS 26** | Branch on `ProductVersion`. See [The device path differs by iOS version](#the-device-path-differs-by-ios-version) |
| `Cannot enable developer-mode when passcode is set` | Undocumented iOS precondition | Passcode off temporarily — **with the round trip**. See [The passcode blocker](#the-passcode-blocker) |
| A tool refuses and the phone never shows a Developer Mode prompt | The tool checked the precondition **locally** and never asked the device | Use `pymobiledevice3`. See [A tool's error is not the device's error](#a-tools-error-is-not-the-devices-error) |
| DDI mount fails: no Developer Disk Image for this iOS version | Each Xcode release **drops** older DDIs | An **older** Xcode is friendlier to an older device; and a nearby image often mounts. See [Newer Xcode is not automatically better](#newer-xcode-is-not-automatically-better) |
| `tap` on a physical device returns an error | The free device tier has **no geometry at all** | Not a bug. See [tap refuses on a physical device](#tap-refuses-on-a-physical-device) |
| Coordinates are off by exactly 3× or ⅓× | Points and pixels were mixed | Use the tool's labeled fields. See [The 3× coordinate error](#the-3-coordinate-error) |
| Tap "succeeded" but nothing happened | Coordinates derived from a screenshot, not from `ui_dump` | See [The tap missed and nothing told you](#the-tap-missed-and-nothing-told-you) |
| Typed text landed in the wrong field | Tap missed; no focus assertion before typing | See [Text went into the wrong field](#text-went-into-the-wrong-field) |
| Simulator boots but the tree is nearly empty / the screen is black | `Booted` was treated as "the app is ready" | Gate on your app separately. See [Booted is not ready](#booted-is-not-ready) |
| `idb` emits class-conflict warnings against a modern Xcode | The Homebrew `idb-companion` build is from **Aug 2022** | Use `axe` instead. See [Why axe and not idb](#why-axe-and-not-idb) |
| A visible control is absent from `ui_dump` | SwiftUI merged it, hid it, or it was never labeled | An accessibility defect in its own right. See [A visible control is missing from the tree](#a-visible-control-is-missing-from-the-tree) |
| Screen renders but data may be fake | No independent confirmation | See [Screenshot shows plausible but fake data](#screenshot-shows-plausible-but-fake-data) |

---

## Host Setup Problems

### DEVELOPER_DIR vs xcode-select

**Symptom:** `xcrun: error: unable to find utility "simctl"`, or `simctl` behaving as though it does not exist — on a machine where Xcode is plainly installed.

**Cause:** the active developer directory is `/Library/Developer/CommandLineTools`, not `Xcode.app`. Command Line Tools ship `xcrun`, `git`, and compilers, but **not** `simctl` and not the simulator runtimes. Everything simulator-related appears missing.

**Fix — the documented one, which is the worse one:**

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer   # needs a password
```

**Fix — the one to actually use:**

```bash
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
```

`DEVELOPER_DIR` takes precedence over `xcode-select` for the process that sets it, is per-process rather than machine-wide, and **needs no sudo**. That last point is not a nicety — a `sudo` prompt blocks turnkey setup entirely on a host being driven over SSH by an agent that has no password to give.

The bundle sets `developer_dir` from behavior config for exactly this reason. `doctor` reports which developer directory is active and names the `DEVELOPER_DIR` fix, not the `sudo` one.

**Verify:** `xcrun simctl list runtimes` should print runtimes, not an error.

### Why axe and not idb

**Symptom:** `idb` / `idb-companion` emits Objective-C class-conflict warnings against a current Xcode, and behaves unpredictably.

**Cause:** the Homebrew `idb-companion` build dates from **August 2022** and vendors iOS frameworks from that era. Loaded alongside a modern Xcode's frameworks, duplicate classes collide.

**Fix:** use `axe`, which vendors current idb frameworks:

```bash
brew install cameroncooke/axe/axe
```

`axe` is what was proven working on this host — selector-resolved taps, element trees with frames, screenshots. **idb is not proven; axe is.** This is not a preference between two working options.

### Why pymobiledevice3 and not libimobiledevice

See [A tool's error is not the device's error](#a-tools-error-is-not-the-devices-error). Short version: for anything that must reach the device, `pymobiledevice3` asks the device and returns the real cause. `libimobiledevice` answers some questions locally and refuses before sending anything, which produces a confident wrong error and no diagnostic signal from the device.

### pymobiledevice3 mixes logs into its JSON

**Symptom:** parsing `pymobiledevice3` output fails:

```
json.decoder.JSONDecodeError: Extra data: line 1 column 143 (char 142)
```

**Cause:** `pymobiledevice3` writes INFO/ERROR log lines onto **the same stream as the JSON payload**. `json.load(stdin)` parses the first value it finds and then chokes on the log line sitting behind it.

**The exception is the harmless half.** The dangerous half is that a guard of the shape *"did I get any output at all?"* is **defeated by the log noise** — stdout is non-empty even when the query failed completely. Measured August 2026: a duplicate-app guard reported `(none installed yet)` about a device it had never successfully read. On a freshly-set-up phone that answer happened to be true, which is exactly how it would have stayed hidden until it mattered.

**Fix, for anything parsing this tool's output:**

1. **Find the first `{` or `[` and parse from there.** Do not assume stdout begins with JSON.
2. **Treat a parse failure as a loud failure, never as an empty result.** An unreadable device is never assumed clean.
3. **Never gate on "output is non-empty".** Gate on "output parsed, and here is what it says".

**Inside this bundle:** `device_elements` already does the right thing — an unparseable payload raises. `device_apps` is the softer case: it falls back to `apps: None` and puts the text in `raw_stdout`, so a caller reading only `apps` sees nothing where it should see an error. **If you consume `device_apps`, check `raw_stdout` before concluding a device has no apps installed.**

---

## Building and Signing for a Device

### Code signing cannot reach the keychain over SSH

**Symptom:** a device build fails at the signing step — "no signing identity found", or no matching provisioning profile — on a Mac that plainly has a valid identity. Run by hand in Terminal on the same machine, the same build signs fine.

**Cause:** measured on one Mac, same user, same minute, August 2026:

| Session | `security find-identity -v -p codesigning` |
|---|---|
| over `ssh` | **0 valid identities** |
| GUI (Terminal.app) | **2 valid identities** |

`securityd` will not release a private key to a session that cannot present UI. Ask it directly over ssh and it says so:

```
$ security show-keychain-info
User interaction is not allowed.
```

The login keychain is unlocked **for the GUI session**, and an ssh session is not that session. Neither of the two reflexes helps: `security unlock-keychain` needs the password on the command line and still leaves the ACL demanding UI, and `sudo` moves you to a *different* user's keychain rather than into the graphical session. The session boundary is the thing, and no amount of privilege crosses it.

**Fix — do not fight the keychain; move the build into the session that already has it.** Apple Events reach the GUI session from ssh, so `osascript` can ask Terminal.app to run the build where the keychain is live. The shape that works:

1. Write the build command into a script.
2. Have Terminal.app run it, redirecting stdout and stderr to a file and echoing `$?` into a second file.
3. Poll for the exit-code file, replay the captured output, and **exit with the build's code**.

Step 3 is not decoration. Without it the ssh caller sees `osascript`'s exit code rather than the build's, and a failed build reports success — the same class of silent-wrong-result this bundle exists to prevent, one layer down.

**The gotcha that costs the next hour:** the bridged session starts in a **different working directory**. A relative `./scripts/build.sh` dies with `No such file or directory` even though it is plainly there. **Hand the bridge absolute paths** — for the script, for the project, and for the output files.

**Why this is worth its own section:** an agent driving a device build over ssh otherwise fails at signing with a misleading "no identity found" and no clue why. The identity exists, the certificate is valid, the profile is installed, and nothing in the error points at the session boundary that is actually responsible.

*Measured August 2026 on macOS 26.x / Xcode 26.x.*

### `rsync --delete` wipes the build products

**Symptom:** `xcodebuild` succeeds on the remote Mac. The install step then cannot find the `.app`.

**Cause:** a sync → build → sync → install loop. The build products exist **only on the build host** — they were never in the source tree the sync came from. The second `rsync --delete` sees files that are not in the source and does exactly what it was told to do.

**Fix:** sync **before** the build, and **never between build and install**. If a post-build sync is genuinely needed, pull *from* the build host rather than pushing *to* it, and exclude the build output directory from `--delete`.

A small mistake with an expensive tail: every occurrence costs a full rebuild cycle. *Observed August 2026.*

---

## Physical Device Connectivity

### Re-seat the adapter, not the device

**Symptom:** a device that was previously fine is not detected at all. `ioreg` shows USB **hubs** but no device behind them. Unplugging and replugging the *phone* changes nothing.

**Cause:** the device is behind a hub, dock, or multiport adapter, and the **hub** is holding a stale downstream port state. The phone is not the component that is confused — the adapter is. Reconnecting the phone into a port the hub still believes is in a bad state reproduces the bad state.

**Fix:** **unplug and re-seat the adapter itself** (or the hub's upstream connection), not the device. Then re-check.

`doctor`'s `device_present` check **names the hubs it can see** when no device is found — precisely so this diagnosis is available in the first report rather than after twenty minutes of replugging a phone.

**Why this is worth its own section:** the instinct on "device not detected" is always to reconnect the device. On a hub-connected setup that instinct is wrong, and following it repeatedly is indistinguishable from "the cable is broken".

### Connections drop unprompted

**Symptom:** a session that was working stops working. The device disappears mid-run. Nobody touched the cable, the phone, or the Mac.

**Cause:** this genuinely happens. It was observed live during the design work, with no provoking action.

**Fix:** there is no prevention — the correct response is **detection**. The tool detects mid-run disappearance and **fails loudly, naming the disappearance**, rather than letting a downstream operation emit a confusing secondary error.

**For agents:** a device that vanished mid-run is **exempt from the retry budget**. Do not retry into it. A retry against a device that is no longer attached produces an error about whatever operation you retried, several layers away from the real cause. Report the disappearance as the finding, and go to [Re-seat the adapter](#re-seat-the-adapter-not-the-device).

### A locked device refuses everything

**Symptom:** an operation that worked minutes ago now returns:

```
ERROR Device is password protected. Please unlock and retry
```

Nobody touched the cable or the configuration.

**Cause:** the device **locked**. Not slept — *locked*. It is the lock state that matters, and it arrives on the Auto-Lock timer partway through a long run, which is precisely when nobody is holding the phone. "The screen was on a minute ago" is not evidence either way.

**Fix for a test session:** **Settings → Display & Brightness → Auto-Lock → Never**, restored to its original value afterwards.

**That is a security downgrade, and it takes the same round trip as the passcode ask.** Say in the same message that it is temporary and that you will ask for it back; then actually prompt for restoration when the run ends — including when the run ends in failure. The protocol is [The passcode blocker](#the-passcode-blocker) verbatim; only the setting differs. Record it in the report's Security Round Trip table alongside the passcode.

*Measured August 2026 on iOS 26.6.*

### A hardcoded UDID goes stale silently

**Symptom:** every command succeeds and the results describe a device that is not the one on the desk — an app that should be installed is missing, a screenshot shows an unfamiliar home screen, a build "deploys" and never appears.

**Cause:** a UDID hardcoded as a default. Measured August 2026: **three separate wrapper scripts** each carried the previous iPhone's UDID as their default target. The owner changed phones; every script kept aiming at hardware that was no longer attached, and **nothing errored**. A stale UDID either fails several layers from the cause, or — the worse case — names a *different* attached device and quietly succeeds against it.

**Fix — the shape that holds:**

1. **Ask, do not remember.** Enumerate at run time (`pymobiledevice3 usbmux list`, `idevice_id -l`).
2. **Refuse on ambiguity, naming the candidates.** An iPad is usually attached too. "Pick the first one" is how an app lands on the wrong device.
3. **An explicit UDID always wins.** A caller who names one gets it, with no discovery step.

This is the stance `list_targets` already takes for simulators. **It applies to physical devices for exactly the same reason,** and it applies to any script wrapped around this tool: a default UDID baked into a script is a stale UDID waiting for its owner to buy a new phone.

---

## Developer Mode and DDI

### The passcode blocker

**Symptom:** enabling Developer Mode fails. The error, when you finally get the real one, is:

```
Cannot enable developer-mode when passcode is set
```

**Cause:** an **undocumented iOS precondition**. Developer Mode cannot be enabled while a device passcode is set. This cost six rounds of investigation to surface, because the tools that failed first failed for a *different* stated reason (see the next section).

**Fix:** the passcode must be off for that one step. `doctor` checks passcode status and reports it **before** the user tries anything else, so the blocker is known up front rather than discovered through a chain of opaque failures.

**The security-downgrade protocol — mandatory:**

When you ask a user to turn a passcode off, you must say **in the same message** that it is temporary and that you will ask them to restore it:

> ✅ "To enable Developer Mode, iOS requires the passcode to be off temporarily. Please turn it off in Settings → Face ID & Passcode → Turn Passcode Off. I'll have you turn it back on as soon as Developer Mode is enabled — it's only needed off for that one step."
>
> ❌ "Turn off your passcode." *(…later…)* "Okay, turn it back on."

The second form reads as a security ask with no stated end, and **a user is right to push back on it.**

**And the round trip is not optional.** Immediately after Developer Mode is enabled, prompt for re-enabling the passcode. Not in the final report, not "later" — the next message. Including when the run subsequently fails: a failed run still leaves someone's phone unlocked.

This applies to any prompt of this shape, not just passcodes.

### A tool's error is not the device's error

**Symptom:** a tool refuses to enable Developer Mode, and **no prompt ever appears on the phone**. The error text names a precondition that seems already satisfied, or is simply opaque. Nothing you do on the device changes the outcome.

**Cause:** `libimobiledevice` checks `DeveloperModeStatus` **locally** and refuses **before sending anything to the device**. The phone is never asked, so it never prompts, and the error you get is the local tool's opinion rather than the device's answer. Meanwhile the real blocker (the passcode) is never surfaced.

`pymobiledevice3` actually asks the device, and returned the real cause — the passcode message above.

**Fix:** use `pymobiledevice3` for anything that must reach the device. The bundle does.

**The general principle, which outlives this specific pair of tools:**

> **When a precondition can be answered locally *or* by the device, prefer the device.**

A local pre-check that short-circuits gives you a fast, confident, wrong error, and zero diagnostic signal from the thing you are actually debugging. This is worth remembering the next time any tool refuses without producing evidence that the target was ever contacted.

### Newer Xcode is not automatically better

**Symptom:** DDI (Developer Disk Image) mounting fails because Xcode ships no image for the device's iOS version. Upgrading Xcode does not help — and may make it worse.

**Cause:** each Xcode release **drops older DDIs** as it adds new ones. Xcode 26 ships Developer Disk Images for **iOS 15.0 through 16.4 only**. A device on iOS 14 has no image in Xcode 26 at all; an older Xcode would have had one.

**Fix, and the surprising part:** the **16.4 image mounted successfully on an iOS 16.7 device**. DDIs are more tolerant of minor-version mismatch than the exact-match assumption suggests. `device_mount_ddi` picks the closest available image rather than requiring an exact match, and `doctor` reports the DDIs Xcode ships **alongside the device's iOS version** so the gap is visible before you try.

**If no nearby image exists:** install an **older** Xcode alongside the current one and point `DEVELOPER_DIR` at it. For an old device, an older Xcode is the friendlier toolchain. "Update Xcode" is the wrong reflex here.

### The device path differs by iOS version

**Symptom:** device guidance that worked on one phone does not apply to another. `xcrun devicectl list devices` reports one device as unavailable and another as `State: connected`. DDI mounting is a manual dance on one and a non-event on the other. Nothing about the Mac changed between the two.

**Cause:** **the device tier's story moved with iOS 26.** Measured on the same Mac (macOS 26.x, Xcode 26.x), August 2026:

| Device | `xcrun devicectl` | DDI |
|---|---|---|
| iPhone X, **iOS 16.7** | reports the device **unavailable** | manual mount required — Xcode 26 ships 15.0–16.4, and the 16.4 image mounts on 16.7 |
| iPhone 12, **iOS 26.6** | **sees and reports the device natively** (`State: connected`) | no longer the manual dance iOS 16 needed |

**Fix:** branch on the device's iOS version, and state which version any piece of device guidance applies to:

| Device iOS | Path |
|---|---|
| **16.x** | `pymobiledevice3` + `libimobiledevice`, manual DDI mount. `devicectl` is not an option |
| **26.x** | `devicectl` sees the device directly and DDI is largely handled for you. The `pymobiledevice3` path still works |

Read the version first — `device_info` → `ProductVersion` — and pick the path from it. **Neither path is universal**, and presenting either one as universal is how an hour goes into debugging a device that was never broken.

*Both rows measured August 2026. The iOS 26 row is a single-device field report — one iPhone 12 on 26.6, not a survey — so treat it as "this is what 26.6 did here", not as a guarantee about every 26.x device.*

### tap refuses on a physical device

**Symptom:** `ios_inspector(operation="tap", backend="device", ...)` returns an error instead of tapping.

**Cause:** **this is intentional.** The free device tier's element list carries no geometry. The complete key set of an element is:

```json
{ "caption": "100% battery power, Charging, ...",
  "estimated_uid": "06000000-...",
  "platform_identifier": "21000000C048...",
  "spoken_description": "..." }
```

Grepping the entire payload for `frame|rect|bounds|x|y|width|height` returns **zero matches**. There is nothing to resolve a selector against.

**Fix:** none on this tier, by design. The paths forward are:

| Want | Path |
|---|---|
| Tap on a real device | **WebDriverAgent** — requires an Apple Developer account and code signing. Unproven and not implemented in this bundle |
| Tap now | Use the **simulator** tier, which is proven end-to-end |
| Inspect the device without tapping | The free tier is genuinely good at this: `device_info`, `device_apps`, `device_screenshot`, `device_elements`, `logs` |

**Do not route around this with `tap_xy`.** A coordinate you did not get from a tree is the exact failure this bundle exists to prevent, and on this tier you could only get one from a picture. `pymobiledevice3` does offer normalized-coordinate HID taps, but its documented workflow is "convert pixels yourself, here are some anchors" — coordinate guessing with extra steps. It is deliberately not wired up.

---

## Coordinate Problems

### The 3× coordinate error

**Symptom:** taps land in roughly the right *direction* but at the wrong *distance*. Elements near the top-left almost work; elements further down are wildly off. A reported frame looks nothing like where the element visibly is.

**Cause:** **points and pixels were mixed.**

```
accessibility tree:  393 x 852    (POINTS)
screenshot:         1179 x 2556   (PIXELS)
scale:               3.0
```

This trap does not exist on Android, which has one coordinate space. On iOS the two spaces differ by exactly the device's scale factor, and the resulting error is **silent** and grows linearly with distance from the origin.

**The diagnostic test — one division:**

| Observation | Diagnosis |
|---|---|
| Tapped point ≈ ⅓ of the intended coordinate | A pixel value was used where points were expected |
| Tapped point ≈ 3× the intended coordinate | A point value was used where pixels were expected |
| Ratio ≈ 1.0 | Not a unit error — look elsewhere |

**Fix:** the tool owns every conversion and labels every geometric field it returns — `frame_points` / `frame_pixels`, `center_points` / `center_pixels`.

1. Use the labeled field for the space you are in. Comparing against a screenshot? `frame_pixels`.
2. **Never multiply or divide by the scale yourself.** Writing `* 3` is how the bug gets created.
3. Never use an unlabeled number. If some path hands you a bare `x`/`y`, go back to `ui_dump`.
4. State the unit in every geometric claim you report to a human. "30px" and "30pt" are different claims.

**The commonest instance:** reading a frame from the tree (points), eyeballing it against a screenshot (pixels), concluding the element is "way off to the top-left", and "correcting" for it. The element was never off. The units were.

### The tap missed and nothing told you

**Symptom:** a tap reports success. Nothing on screen changed. No error anywhere.

**Cause:** the coordinates were wrong — most often because they were derived from a **VLM reading of a screenshot** rather than from `ui_dump`.

Measured live on a booted simulator, same screenshot, same "General" row in Settings:

| Source | Pixels | Center |
|---|---|---|
| `ui_dump` (truth) | `[48,1132][1131,1288]` | **(590, 1210)** |
| VLM reading the PNG | `[36,1000][1143,1160]` | (590, 1080) |

Delta **dy −130px** — the VLM-derived center lands **outside the real row**, on the row above. Adjacent settings rows are 156px apart, so a 130px error reliably selects the wrong one: you navigate into the wrong screen, assert against it, and report success.

**Fix:** coordinates always come from `ui_dump` or `find`. Never from vision. `tap` enforces this by resolving a selector against a fresh dump before touching the screen, then re-dumping and reporting what changed.

**Calibration:** a real navigation produces a large tree delta. The proven `tap --label "General"` took the element count from **32 to 73**. A one-node delta after tapping a navigation control is suspicious.

**If a selector will not resolve,** work the list in the guide (wait, dismiss an alert, scroll, SwiftUI quirks) and then **report it as a finding**. A zero-match is information. It is not a licence to estimate coordinates from a picture.

---

## Interaction Problems

### Text went into the wrong field

**Symptom:** a value saves to the wrong setting. One field is correct and its neighbour is not. No error at any point.

**Cause:** the tap that was supposed to focus field A actually landed on field B — or on nothing, leaving focus wherever it already was. The subsequent typing went into whatever *did* have focus.

**Fix:** the verified field-write protocol, enforced by `type_text`:

1. resolve selector from a **fresh** dump
2. tap the resolved center
3. **assert focus on the intended node** — stop here if it is not focused
4. clear existing content deterministically (typing **appends**, it does not replace)
5. type the text
6. dismiss the keyboard **deliberately** — never by "tapping elsewhere"
7. re-dump and **assert readback**

If `verified` comes back false, **stop the run.** Every assertion after a bad config write is untrustworthy.

### Committing a field breaks the next few interactions

**Symptom:** after typing into a field, subsequent taps on the tab bar do nothing.

**Cause:** the field was committed by "tapping elsewhere". "Elsewhere" is another element — the tap focused a different control and left the software keyboard up, overlapping the bottom of the screen and swallowing every tap aimed at the tab bar.

**Fix:** dismiss the keyboard deliberately (a `return` key event, or the app's own dismissal affordance resolved as a selector). A cluster of consecutive no-effect taps beginning immediately after a field write is this pattern's signature.

### A visible control is missing from the tree

**Symptom:** an element is unmistakably visible in the screenshot and completely absent from `ui_dump`.

**Cause:** one of:

- SwiftUI **merged** it into its parent — the parent node's label contains the text, concatenated with its siblings'
- It is marked `.accessibilityHidden(true)`
- It was never given a label (common for icon-only and decorative controls)
- It is inside a custom-drawn surface (Metal, SceneKit, Canvas, `WKWebView`) which is a single opaque node

**Fix:** first check whether the parent's label contains the text — try `label_contains` before concluding the element is absent. If it genuinely is not in the tree, **that is an accessibility defect in its own right** and worth reporting as one: a screen reader cannot reach it either.

**Do not work around it with `tap_xy`** unless it is genuinely a custom-drawn surface — that is the one legitimate case.

### Booted is not ready

**Symptom:** the simulator reports `Booted`, but `ui_dump` returns a nearly empty tree, `screenshot` returns a black or near-black frame, or taps do nothing.

**Cause:** `Booted` describes the **simulator device**, not your app. Boot to `Booted` was measured at **2.7s** headless over SSH — comfortably fast, and comfortably ahead of anything your app has rendered.

**Fix:** two separate gates, never one:

```python
ios_inspector(operation="boot",   udid=udid)                       # device is up
ios_inspector(operation="launch", udid=udid, bundle_id="com.example.app")
ios_inspector(operation="wait_for", udid=udid,
              selector={"identifier": "com.example.root"}, timeout_s=30)
```

Gate on **your app's** root element, and prefer the element that renders *last* in the screen's real load order — a navigation title that appears before the list populates tells you nothing about the list.

**Liveness cross-check:** an implausibly small `screenshot["bytes"]` for the resolution means a solid-colour frame. Treat it as a signal, not as a valid capture.

### Screenshot shows plausible but fake data

**Symptom:** a screen renders convincingly. The data is stale, cached, seeded, or simply absent.

**Cause:** an empty shell, a cached render, and live data are visually indistinguishable — especially to a VLM, which will describe an empty list as "rendering correctly".

**Fix:** never report "verified" on a screenshot alone. Require at least one independent confirmation:

- **Server-log correlation** — the specific endpoints this screen needs, arriving during the interaction window
- **In-app status line** — assert on it from `ui_dump`, not from the image. `Last successful poll: never` alongside plausible-looking rows means the data is not live
- **`logs`** — an app that catches network exceptions and renders an empty state gives you a clean screen and a loud log. Read the log before declaring a pass

With the screenshot and nothing else, the honest report is **"the screen renders; I could not confirm the data is live"**.

---

## Deferred by Design

Named here so they are not rediscovered as gaps:

| Deferred | Why | Consequence |
|---|---|---|
| **WebDriverAgent backend** | Needs an Apple Developer account and code signing | No tapping on physical devices. Same tool interface when someone actually needs it |
| **Physical-device tap via HID** | `pymobiledevice3` offers normalized-coordinate HID taps whose documented workflow is "convert pixels yourself, here are some anchors" | That is coordinate guessing — precisely what this bundle forbids. Deliberately not wired up |
| **Windows / WSL** | Appium's Linux path needs iOS 18+; no Simulator on Windows at all | Worst substrate on every axis. macOS only |
| **Xcode installation** | Out of scope — the bundle assists with setup, it does not bootstrap a machine | `doctor` reports precisely what is missing and how to fix it |
| **`idb` as the simulator backend** | The Homebrew build is from Aug 2022 and conflicts with modern Xcode | `axe` is the proven path |

---

## Why iOS and not "iphone-tester"

Device type is a **parameter**, not a platform. `simctl` puts iPhone and iPad in one `SimDeviceType` namespace with identical `create`/`boot`/`install`/`launch` verbs; `xcodebuild -destination` uses the same syntax for both; Appium's XCUITest driver covers iOS/iPadOS/tvOS as one driver.

Splitting the bundle would duplicate everything in order to encode a string. Same call as `android-tester`, which covers phones and tablets without comment. If you are looking for iPad guidance, it is this document — pick an iPad `device_type` in `create_sim`.

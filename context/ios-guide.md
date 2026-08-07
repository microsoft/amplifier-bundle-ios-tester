# iOS Inspector — Full Reference Guide

Complete reference for agents using the `ios_inspector` tool to drive and verify iOS applications on simulators and physical devices. Read this before any testing session.

---

## Section 0: The Load-Bearing Constraint

### The accessibility tree is the sensor. The screenshot is for judgment, never for targeting.

This is not a style preference. It was measured live, on a booted simulator, against the same screenshot and the same element (the "General" row in Settings):

| Source | Pixels | Center |
|---|---|---|
| `ui_dump` (the accessibility tree) | `[48,1132][1131,1288]` | **(590, 1210)** |
| VLM reading the PNG | `[36,1000][1143,1160]` | (590, 1080) |

Delta: **dy −130px**. The VLM-derived center falls **outside the real row** — it lands on the row above. The tap goes to the wrong setting.

This is a different number from Android's 61/93px miss, independently re-measured on this platform. Identical lesson.

### Why this is worse than it sounds

**The failure is silent.** iOS has no concept of "you tapped nothing". A miss produces:

- no error
- no exception
- no non-zero exit code
- a screenshot that often looks plausible

And the *dangerous* case is not landing on nothing — it is landing on a **neighbouring** element. In a settings list, adjacent rows are 156px apart in pixels (52pt); a 130px error reliably selects the wrong one. You navigate into the wrong screen, assert against it, and report success.

### The division of responsibility

| Question | Answer from |
|---|---|
| Where do I tap? | `ui_dump` / `find` — **always** |
| What is on screen right now? | `ui_dump` for structure, `screenshot` for appearance |
| Does this look right? | `screenshot` + vision |
| Is anything clipped, blank, overlapping, mis-coloured? | `screenshot` + vision |
| Did my tap do what I expected? | `ui_dump` before and after — compare |
| Is the data real, or an empty shell? | `logs` + server logs + in-app status text |

### The rule, stated as a prohibition

**Never derive a tap target from a VLM reading of a screenshot.** Not as an estimate, not as a fallback, not "just to get unstuck". If a selector will not resolve, that is a finding — report it. It is not a licence to guess coordinates from a picture.

`tap_xy` exists for the rare legitimate case (a Metal/canvas surface with no accessibility elements, a deliberate gesture target). It is named to be conspicuous and it emits a warning in its own result. If you find yourself reaching for it because `find` returned nothing, stop and report instead.

---

## Section 1: Points vs Pixels — The iOS-Only Trap

Android has one coordinate space. **iOS has two, and they differ by a factor of 3.**

```
accessibility tree:  393 x 852    (POINTS)
screenshot:         1179 x 2556   (PIXELS)
scale:               3.0
```

A number without a unit is a bug waiting to happen. Mixing the two spaces produces a **silent 3× coordinate error** — far larger than the 130px VLM miss above, and equally invisible.

### The contract

**The tool owns every conversion.** It never hands you a raw number whose unit is ambiguous. Every geometric field it returns carries its unit in its name:

```python
node = {
    "label": "General",
    "frame_points":  {"x": 16.0, "y": 377.33, "w": 361.0, "h": 52.0},
    "frame_pixels":  {"x": 48,   "y": 1132,   "w": 1083,  "h": 156},
    "center_points": [196.5, 403.33],
    "center_pixels": [590, 1210],
}
```

### The rules for you

1. **Use the explicitly-labeled field for the space you are in.** Comparing against a screenshot? `*_pixels`. Feeding a simulator interaction? The tool handles it — pass the selector, not a number.
2. **Never multiply or divide by the scale yourself.** If you are writing `* 3` or `/ 3`, you are about to introduce the bug this section exists to prevent.
3. **Never use an unlabeled number.** If some path hands you a bare `x`/`y`, treat its unit as unknown and go back to `ui_dump`.
4. **When reporting geometry to a human, say which space you mean.** "clipped 30px below the screen" and "clipped 30pt below the screen" are different claims.

The single most common way to get this wrong: reading a frame from the tree (points), eyeballing it against a screenshot (pixels), concluding the element is "way off to the top-left", and then "correcting" for it. The element was never off. The units were.

---

## Section 2: The Three Tiers — Capability Matrix

Feasibility here is not binary. It splits by what you are willing to pay for.

| Tier | Setup cost | Can SEE | Can TAP | Status |
|---|---|---|---|---|
| **Simulator** | Xcode only | labels **+ frames** | **yes** | **proven** |
| **Device — free** | cable + Developer Mode | screenshot, element list, syslog | **no — no geometry exists** | **proven** |
| **Device — WebDriverAgent** | + Apple Developer account, code signing | yes | yes | **unproven — not implemented** |

### What each operation supports

| Operation | `backend="simulator"` | `backend="device"` |
|---|---|---|
| `doctor`, `list_targets` | yes | yes |
| `create_sim`, `boot`, `shutdown` | yes | n/a — device lifecycle is physical |
| `install`, `launch`, `terminate` | yes | requires signing — not on the free tier |
| `screenshot` | yes | yes (`device_screenshot`) |
| `ui_dump`, `find` | yes — **with frames** | `device_elements` — **captions only, no frames** |
| `tap`, `tap_xy`, `type_text`, `key`, `swipe`, `wait_for` | yes | **REFUSED** |
| `logs` | yes | yes (device syslog) |
| `device_info`, `device_apps` | n/a | yes |
| `device_enable_devmode`, `device_mount_ddi` | n/a | yes |

### Why the device tier cannot tap

The free-tier element list is the entire payload — this is a real element, verbatim:

```json
{ "caption": "100% battery power, Charging, ...",
  "estimated_uid": "06000000-...",
  "platform_identifier": "21000000C048...",
  "spoken_description": "..." }
```

Full key set: `caption`, `estimated_uid`, `platform_identifier`, `spoken_description`. Grepping the entire payload for `frame|rect|bounds|x|y|width|height` returns **zero matches**. There is no geometry to resolve a selector against.

**So `tap` on `backend="device"` returns an error, not a guess.** The error names WebDriverAgent as the path that would provide geometry. Do not route around this with `tap_xy` — a coordinate you did not get from a tree is exactly the failure mode this bundle exists to prevent, and on a physical device it is a coordinate you cannot even estimate from a labeled frame, only from a picture.

### What the free device tier IS good for

Genuinely useful, with no Apple Developer account and no signing:

- **`device_info`** — UDID, model, iOS version, build number
- **`device_apps`** — installed app inventory with bundle IDs
- **`device_screenshot`** — real screen capture at real device resolution
- **`device_elements`** — what the screen *says* (accessibility labels), useful for asserting text presence and for accessibility auditing
- **`logs`** — live syslog, the strongest instrument for "did the app actually do the thing"

A read-only device tier that honestly says "I cannot tap" is worth more than a tapping tier that guesses.

---

## Section 3: Tool Operations Reference

All operations take a `udid` (simulator or device identifier) and a `backend` (`"simulator"` — the default — or `"device"`). Every underlying call is UDID-scoped. Ambiguity is an error, not a guess.

### Environment

#### `doctor` — Full host readiness report

```python
report = ios_inspector(operation="doctor")
# report["ready"]    — bool: false if ANY check reported "fail"
# report["checks"]   — [{name, status: "ok"|"warn"|"fail", detail, remediation}, ...]
# report["summary"]  — names what to fix FIRST
```

**No required parameters. Never raises. Always returns a full report.** It checks:

| Check | What it establishes |
|---|---|
| `xcode` / `developer_dir` | A real Xcode is selected, not CommandLineTools. Names the `DEVELOPER_DIR` fix (**no sudo**) rather than the `sudo xcode-select` one |
| `simctl` | `xcrun simctl` resolves and runs |
| `axe` | The simulator interaction backend is installed |
| `pymobiledevice3` | The device backend is installed |
| `runtimes` | Which iOS runtimes are available for `create_sim` |
| `simulators` | Which simulators exist, and their state |
| `device_present` | A physical device is attached. **When none is found, it names the USB hubs it can see** — see the adapter lesson in TROUBLESHOOTING.md |
| `developer_mode` | Developer Mode status on the attached device |
| `passcode` | **Whether a passcode is set** — this blocks enabling Developer Mode, and finding out here saves six rounds of confusing errors |
| `ddi` | Which Developer Disk Images Xcode ships, versus the device's iOS version |

**It does not stop at the first failure.** Every check runs regardless of what came before, because the point is to show everything wrong at once. Fixing a host one confusing error at a time is precisely the experience this operation exists to delete.

**`success` is true whenever a report was produced.** A broken machine is a *successful diagnosis*, not a tool error. Read `ready`, not `success`, to decide whether to proceed — and when `ready` is false, report the failing checks with their `remediation` text and stop.

#### `list_targets` — Enumerate simulators and devices

```python
result = ios_inspector(operation="list_targets")
# {targets: [{udid, name, kind: "simulator"|"device", state, os_version, ...}], count: N}
```

Simulators and physical devices in **one list**, each with its `kind`. **Ambiguity is an error, not a warning.** If two targets could match and you have not pinned a `udid`, the tool refuses rather than guessing.

### Simulator Lifecycle

#### `create_sim` — Provision a simulator

```python
result = ios_inspector(
    operation="create_sim",
    name="ios-harness",          # required — the NEW simulator's name
    device_type="iPhone 15",     # simctl device type
    runtime="iOS 17.5",          # must be an available runtime — see doctor
)
# result["udid"], ["name"], ["device_type"], ["runtime"], ["verified"]
```

Refuses to clobber an existing simulator of the same name without an explicit override, and verifies the result by re-listing rather than trusting an exit code.

#### `boot` — Boot a simulator

```python
r = ios_inspector(operation="boot", udid=udid)
# r["state"] == "Booted", r["elapsed_s"]
```

**Measured 2.7s to `Booted`, headless, over bare SSH.** This was the single largest feasibility risk in the design and it cleared comfortably — a simulator does not need a GUI session, a logged-in desktop, or a visible Simulator.app window.

Boot returning `Booted` means the *device* is up. It does not mean your app is up — gate on your app separately with `wait_for`.

#### `shutdown` — Shut down a simulator

```python
ios_inspector(operation="shutdown", udid=udid)
```

Always call this on completion, including error paths.

### App Lifecycle

#### `install` / `launch` / `terminate`

```python
ios_inspector(operation="install", udid=udid, app_path="/path/to/MyApp.app")
ios_inspector(operation="launch",  udid=udid, bundle_id="com.example.app")
ios_inspector(operation="terminate", udid=udid, bundle_id="com.example.app")
```

`launch` re-foregrounds an already-running app rather than cold-starting it — the app reappears on whatever screen it last showed, not its start screen. Use `terminate` first when you need a genuine cold start.

On `backend="device"`, `install` and `launch` require a signed build. On the free tier they are unavailable; `device_apps` still lets you inspect what is already installed.

### Sensing

#### `screenshot` — Capture the screen as an image

```python
snap = ios_inspector(operation="screenshot", udid=udid)
# snap["image_path"]     — file path to the PNG (never base64 inline)
# snap["width_pixels"], snap["height_pixels"]
# snap["scale"]          — points→pixels factor
# snap["bytes"]          — file size, use as a liveness check
```

Returns a **file path**, not inline image data. Pass the path to vision when you need visual judgment.

**Liveness check:** a suspiciously small byte count (a few KB for a full-resolution screen) usually means a solid-colour frame — a black screen, an unrendered surface, or a device that has gone to sleep. Treat it as a signal, not as a valid capture.

**A screenshot is never evidence of a coordinate.** See Section 0.

#### `ui_dump` — Capture the accessibility tree

```python
dump = ios_inspector(operation="ui_dump", udid=udid)
# dump["screen_points"] = [393, 852]
# dump["screen_pixels"] = [1179, 2556]
# dump["scale"] = 3.0
# dump["nodes"] = [
#   {
#     "type": "Cell",
#     "label": "General",
#     "identifier": "com.example.settings.general",   # accessibilityIdentifier
#     "value": None,
#     "frame_points":  {"x": 16.0, "y": 377.33, "w": 361.0, "h": 52.0},
#     "frame_pixels":  {"x": 48,   "y": 1132,   "w": 1083,  "h": 156},
#     "center_points": [196.5, 403.33],
#     "center_pixels": [590, 1210],
#     "enabled": True,
#     "focused": False,
#   },
#   ...
# ]
```

Returns a **parsed node list**, not raw output. Centers are pre-resolved in **both** spaces — you do not compute them, and you never convert between them.

This is the source of truth for everything positional. Dump before every tap; never reuse coordinates across screens. A dump is cheap; a silent mis-tap is not.

**On `backend="device"` this is `device_elements`, and it returns captions only — no frames, no centers.** See Section 2.

#### `find` — Resolve a selector to matching nodes

```python
hits = ios_inspector(operation="find", udid=udid, selector={"label": "General"})
# hits["nodes"] = [...]  same node shape as ui_dump, with both coordinate spaces
# hits["count"] = N
```

`count == 0` is a finding. `count > 1` means your selector is ambiguous — narrow it before acting.

#### `logs` — Read the log stream

```python
log = ios_inspector(operation="logs", udid=udid, predicate="subsystem == 'com.example.app'", lines=200)
```

On the simulator this is the unified log; on `backend="device"` it is the device syslog. The primary instrument for the "is the data real" assertion (Section 8) and for correlating a UI anomaly with what the app actually did.

### Interacting — All Selector-First, Simulator Only

#### `tap` — Resolve and tap

```python
result = ios_inspector(operation="tap", udid=udid,
                       selector={"identifier": "com.example.settings.general"})
# result["tapped"]  — the node actually hit, with frames in BOTH spaces
# result["changed"] — what differs in the tree after the tap
```

The contract, enforced by the tool:

1. `ui_dump` (fresh — not cached)
2. resolve the selector; fail if zero or ambiguous matches
3. tap the resolved center
4. `ui_dump` again
5. report what changed

**You cannot tap without resolving a selector first.** That is the point. An agent instructed to "always dump before tapping" skips it when a run gets long; a tool that structurally cannot do otherwise does not.

Proven live: `tap --label "General"` resolved to (196.5, 403.3) in points and the tree went from 32 to 73 elements — the navigation actually happened, and the change set is the proof.

Read `result["changed"]`. An empty change set after a tap on a control is a finding — the tap landed but nothing happened, which is different from the tap missing.

**On `backend="device"` this REFUSES.** No geometry exists to resolve against.

#### `type_text` — The verified field-write protocol

```python
result = ios_inspector(operation="type_text", udid=udid,
                       selector={"identifier": "com.example.url_field"},
                       text="http://localhost:9000")
# result["readback"] — what the field actually contains afterwards
# result["verified"] — bool: does readback match the intended text?
```

The single most failure-prone operation in UI automation on any platform:

| Step | Why |
|---|---|
| 1. Resolve selector from a fresh dump | Stale coordinates land on the wrong field |
| 2. Tap the resolved center | — |
| 3. **Assert focus on the intended node** | A tap can silently land on a *neighbouring* field. Without this assertion your keystrokes go wherever focus already was — no error, just wrong data in the wrong field |
| 4. Clear existing content deterministically | Typing **appends**; it does not replace |
| 5. Type the text | — |
| 6. Dismiss the keyboard deliberately | Never commit by "tapping elsewhere" — "elsewhere" is another element, and the software keyboard left up overlaps the bottom of the screen and swallows subsequent taps |
| 7. Re-dump and **assert readback** | The only proof the value actually landed |

If `result["verified"]` is false, **stop**. Do not proceed on the assumption that the field is set. A wrong value in a config field poisons every subsequent assertion in the run.

#### `key` — Send a key event

```python
ios_inspector(operation="key", udid=udid, key="return")
ios_inspector(operation="key", udid=udid, key="home")
```

Common keys: `return`, `escape`, `home`, `delete`, `tab`.

#### `swipe` — Gesture

```python
ios_inspector(operation="swipe", udid=udid,
              x1=196, y1=700, x2=196, y2=200,   # POINTS
              duration_ms=300)
```

Explicit coordinates are permitted here — gestures have no selector analogue. **Derive the endpoints from `ui_dump` `frame_points`** (scroll from inside the list container's frame), not from eyeballing a screenshot, and not from pixel values.

Scroll-to-find pattern: swipe, `ui_dump`, check for the target selector, repeat with a bounded attempt count. Never assume a fixed number of swipes reaches an element.

#### `tap_xy` — Raw coordinates (conspicuous by design)

```python
ios_inspector(operation="tap_xy", udid=udid, x=196.5, y=403.3)   # POINTS
# result["warning"] — always present
```

Named to be uncomfortable. Emits a warning in its own result. Legitimate uses are narrow:

- a Metal / SceneKit / canvas surface with no accessibility elements
- a deliberate gesture target (a specific point in a map or drawing area)
- reproducing a coordinate that came from `ui_dump` in a prior step within the same screen

**Not a legitimate use:** a selector did not resolve and you want to keep going. That is a finding to report, not a hole to route around. And it is *never* the way to work around the device tier's tap refusal.

### Synchronising

#### `wait_for` — Poll until a selector appears or disappears

```python
found = ios_inspector(operation="wait_for", udid=udid,
                      selector={"label": "Base URL"},
                      timeout_s=15,
                      absent=False)       # True = wait for it to *disappear*
# {found: bool, elapsed_s: float, node: {...} | None}
```

**No bare sleeps anywhere.** A sleep is either too short (flaky) or too long (slow), and it is never evidence of anything. `wait_for` polls `ui_dump` and returns the elapsed time — which is itself useful data when you are characterising a slow screen.

### Device Tier

```python
ios_inspector(operation="device_info", udid=device_udid)
ios_inspector(operation="device_apps", udid=device_udid)
ios_inspector(operation="device_screenshot", udid=device_udid)
ios_inspector(operation="device_elements", udid=device_udid)     # captions only
ios_inspector(operation="device_enable_devmode", udid=device_udid)
ios_inspector(operation="device_mount_ddi", udid=device_udid)
```

`device_enable_devmode` fails when a passcode is set — see the security-downgrade protocol in Section 4. `device_mount_ddi` picks the closest available Developer Disk Image; Xcode 26 ships images for 15.0–16.4 only, and the **16.4 image mounts successfully on an iOS 16.7 device**.

---

## Section 4: The Security-Downgrade Protocol

Enabling Developer Mode on a physical device requires the device passcode to be **off**. This is undocumented and it is a real blocker.

When you — or the tool — ask a user to disable a security setting, **state in the same message that the change is temporary and that you will ask them to restore it**, and then actually prompt them to restore it.

> **Correct:** "To enable Developer Mode, iOS requires the passcode to be off temporarily. Please turn it off in Settings → Face ID & Passcode → Turn Passcode Off. I'll have you turn it back on as soon as Developer Mode is enabled — it's only needed off for that one step."
>
> **Wrong:** "Turn off your passcode." *(…later…)* "Okay, turn it back on."

The second form reads as a security ask with no stated end, and a user is right to push back on it. An open-ended request to weaken a device's security is not something to issue casually and explain afterwards.

**The round trip is mandatory.** After `device_enable_devmode` succeeds, your very next message to the user prompts them to re-enable the passcode. Do not batch it into a later step, do not leave it to the final report, and do not silently drop it if the run then fails — a failed run still leaves the user's phone unlocked.

This applies to any future prompt of this shape, not just passcodes.

---

## Section 5: Selector Syntax

| Selector | Matches | Notes |
|---|---|---|
| `{"identifier": "com.example.save"}` | `accessibilityIdentifier` | **Most stable.** Prefer whenever the app sets one |
| `{"label": "Save"}` | accessibility label (usually the visible text) | Readable; breaks on localisation |
| `{"label_contains": "poll"}` | substring of the label | Use for labels with dynamic parts ("Last poll: 3s ago") |
| `{"value": "on"}` | accessibility value | For switches, sliders, fields |
| `{"type": "Button", "index": 0}` | Nth element of a type | Positional and brittle — a last resort |

Selectors may combine keys — all specified keys must match:

```python
{"type": "TextField", "identifier": "com.example.url_field"}
{"label_contains": "Refresh", "enabled": True}
```

### Choosing a selector — order of preference

1. `identifier` — survives text changes, layout changes, and localisation
2. `label` / `label_contains` — readable but coupled to copy
3. `value` — good for asserting switch and field state, weak for targeting
4. `type` + `index` — brittle; document why you had to

### When a selector does not resolve

`count == 0` has a small set of causes. Check them in this order:

1. **The screen has not finished rendering** → `wait_for` with a real timeout
2. **A system alert or sheet is on top** → find and dismiss it, then re-dump
3. **The element is off-screen** → swipe within the container's `frame_points`, re-dump
4. **SwiftUI accessibility gap** → see Section 6
5. **You are on `backend="device"`** → there is no geometry; this tier cannot target. Not a bug
6. **The element genuinely is not there** → **this is your finding.** Report it.

Never resolve a zero-match by estimating coordinates from a screenshot.

---

## Section 6: SwiftUI and UIKit Accessibility Quirks

The tree is populated by the app's accessibility layer, and it is imperfect in predictable ways.

### Labels merge

SwiftUI merges a container's children into a single accessibility element by default. A row showing a title and a subtitle frequently appears as **one** node with a concatenated label, not two. Prefer `label_contains` over `label` when asserting on a label-plus-value string.

### Decorative elements vanish

Elements marked `.accessibilityHidden(true)` — or simply never given a label — do not appear in the tree at all, even though they are clearly visible in the screenshot. **A visible element absent from the tree is an accessibility defect in its own right**, and worth reporting as one.

### Custom-drawn surfaces have no elements

A Metal, SceneKit, Canvas, or drawing view is a single opaque node. Nothing inside it is addressable. This is the one genuine `tap_xy` case.

### The selected item's label may change, not disappear

Unlike Android, iOS usually keeps the element and changes its `value` or appends a trait (e.g. a selected tab bar item). Check `value` and the label suffix before concluding an element is missing.

### Frames are correct even when semantics are odd

Whatever the tree's quirks about merging and hidden elements, **the frames are accurate**. That is precisely why `ui_dump` is the sensor and the screenshot is not.

---

## Section 7: Synchronisation Patterns

### The golden rule: gate on state, never on time

Bad — brittle and slow at the same time:

```python
ios_inspector(operation="tap", udid=udid, selector={"label": "Refresh"})
time.sleep(3)                                    # arbitrary; still flaky
ios_inspector(operation="screenshot", udid=udid)
```

Good:

```python
ios_inspector(operation="tap", udid=udid, selector={"label": "Refresh"})
ios_inspector(operation="wait_for", udid=udid,
              selector={"label_contains": "Last updated"}, timeout_s=10)
ios_inspector(operation="screenshot", udid=udid)
```

### Boot readiness is two-stage — never one

```python
r = ios_inspector(operation="boot", udid=udid)      # ~2.7s to "Booted"
ios_inspector(operation="launch", udid=udid, bundle_id="com.example.app")
ios_inspector(operation="wait_for", udid=udid,
              selector={"identifier": "com.example.root"}, timeout_s=30)
```

`Booted` means the simulator device is up. It says nothing about whether your app has rendered. Gate on your app separately, always.

### Waiting for something to disappear

```python
ios_inspector(operation="wait_for", udid=udid,
              selector={"label": "Loading"}, absent=True, timeout_s=20)
```

Often more reliable than waiting for content to appear, because a spinner has a definite identity while "the list has data" is a fuzzy predicate.

### Waiting on the LAST thing to render

Gating on a navigation-bar title that appears before the list populates tells you nothing about the list. Pick the element that renders last in the screen's real load order.

### Bounded scroll-to-find

```python
for attempt in range(8):
    hits = ios_inspector(operation="find", udid=udid, selector={"label": "Advanced"})
    if hits["count"] > 0:
        break
    ios_inspector(operation="swipe", udid=udid,
                  x1=196, y1=700, x2=196, y2=300, duration_ms=300)   # POINTS
else:
    report("'Advanced' not reachable after 8 scroll attempts")
```

Always bounded. An unbounded scroll loop against a list that never contains the target is indistinguishable from a hang.

---

## Section 8: The "Data Is Real" Assertion

**A screenshot alone does not prove the data is real.**

A screen showing an empty list, a screen showing stale cached data, and a screen showing live data from a healthy backend can be visually indistinguishable — especially to a VLM, which will happily describe an empty shell as "the items list rendering correctly".

This is the failure mode the whole bundle exists to catch. Every capture that claims to show working data needs a second, independent source of evidence.

### The three instruments

1. **Correlate with the server log.** If the app talks to a server you control, its access log is direct proof the app made the request. Assert the *specific endpoints* this screen needs, arriving during the interaction window. "Some requests happened" is weaker than "the request this screen needs happened, just now".

2. **Read the in-app status line from the tree, not the image.**
   ```python
   hits = ios_inspector(operation="find", udid=udid,
                        selector={"label_contains": "Last successful poll"})
   ```
   `Last successful poll: never` alongside a screen full of plausible rows means you are looking at seeded, cached, or placeholder data.

3. **Check `logs` for swallowed errors.** An app that catches its network exceptions and renders an empty state produces a *clean-looking screen* and a *loud log*. Read the log before declaring a pass.

### The assertion, as a checklist

Before reporting that a screen shows working data, you must have:

- [ ] a `ui_dump` showing the expected content nodes (not just a container)
- [ ] at least one independent confirmation: server-log correlation, in-app status line, or `logs` evidence of a successful request
- [ ] no error-level log entries for the app's subsystem during the interaction window

If you have the screenshot and nothing else, the honest report is **"the screen renders; I could not confirm the data is live"** — not "verified".

---

## Section 9: Common Workflow Patterns

### Pattern 1 — Boot, install, launch, verify (simulator)

```python
ios_inspector(operation="doctor")
t = ios_inspector(operation="list_targets")
udid = ...   # pinned explicitly

ios_inspector(operation="boot", udid=udid)
ios_inspector(operation="install", udid=udid, app_path="/tmp/MyApp.app")
ios_inspector(operation="launch",  udid=udid, bundle_id="com.example.app")
ios_inspector(operation="wait_for", udid=udid,
              selector={"identifier": "com.example.root"}, timeout_s=30)

dump = ios_inspector(operation="ui_dump", udid=udid)
snap = ios_inspector(operation="screenshot", udid=udid)
# dump → structural assertions.  snap → visual judgment.

ios_inspector(operation="shutdown", udid=udid)
```

### Pattern 2 — Configure a settings screen (the verified field write)

```python
ios_inspector(operation="wait_for", udid=udid,
              selector={"label": "Base URL"}, timeout_s=10)

r = ios_inspector(operation="type_text", udid=udid,
                  selector={"identifier": "com.example.url_field"},
                  text="http://localhost:9000")
if not r["verified"]:
    report(f"Base URL did not take. Readback: {r['readback']!r}")
    return    # do NOT continue — every later assertion is now untrustworthy
```

**Idempotence:** read the field's current `value` from `ui_dump` first and skip the write if it already matches. Re-running a configure step should be a no-op, not a re-type.

### Pattern 3 — Read-only device survey (free tier)

```python
info = ios_inspector(operation="device_info",       udid=dev, backend="device")
apps = ios_inspector(operation="device_apps",       udid=dev, backend="device")
snap = ios_inspector(operation="device_screenshot", udid=dev, backend="device")
els  = ios_inspector(operation="device_elements",   udid=dev, backend="device")
log  = ios_inspector(operation="logs",              udid=dev, backend="device", lines=300)
```

Everything here works with no Apple Developer account. **Do not attempt any interaction operation on this tier** — `tap` refuses, and it is right to.

### Pattern 4 — Before/after comparison of a fix

```python
snap_before = ios_inspector(operation="screenshot", udid=udid)
dump_before = ios_inspector(operation="ui_dump",   udid=udid)

# ... the change under test ...

snap_after = ios_inspector(operation="screenshot", udid=udid)
dump_after = ios_inspector(operation="ui_dump",   udid=udid)
```

Use **both**. The dump tells you what changed in the tree (in points, precisely); the screenshot tells you whether the result looks acceptable. Neither alone is sufficient.

---

## Section 10: Safety Invariants

These were each learned by breaking something real, or measured directly. The tool enforces them structurally; this section explains *why*, so you recognise the failure when the tool's enforcement is not in the path.

### 1. Every call carries an explicit `udid`

Simulators multiply. `list_targets` treats ambiguity as an error rather than picking one, for the same reason Android's tooling does: operating on a target you did not intend produces a silently wrong run, not a loud failure.

### 2. Dump before every tap; never reuse coordinates across screens

Coordinates are valid for exactly one rendered state. A list that scrolled by one row, a sheet that appeared, a keyboard that opened — any of these invalidates every coordinate you were holding.

### 3. Never mix points and pixels; never convert by hand

The tool labels every number. Using an unlabeled one, or applying the scale yourself, is a silent 3× error. See Section 1.

### 4. After tapping a text field, assert focus before typing

Without it, keystrokes go wherever focus already was. Silent, and the resulting data corruption is discovered by a human, later.

### 5. Never tap on `backend="device"`

There is no geometry. The tool refuses. Routing around the refusal with `tap_xy` re-creates the exact failure the refusal exists to prevent, on the platform where you can least afford it.

### 6. Never ask for a security downgrade without the round trip

Say it is temporary in the same message, and actually prompt for restoration afterwards. See Section 4.

### Why these are in the tool and not just in prose

Prose decays under pressure. An agent instructed to follow six rules will skip them at turn 40 of a long run, exactly when the run is hardest to debug. A tool that *cannot* tap without resolving a selector first, and that *cannot* hand you an unlabeled coordinate, makes the discipline structural. When you notice yourself wanting to route around one of these, that impulse is the signal the rule is working.

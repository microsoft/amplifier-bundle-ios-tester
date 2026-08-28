# Field Notes — August 2026

Distilled from an extended real-device project: several weeks of daily work driving a **Mac build host over ssh from a Linux workstation**, building and installing onto a **developer's own iPhone** on the free provisioning tier, and proving behaviour that only exists on real hardware.

This file is deliberately **additive**. Everything already established in [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — points vs pixels, the three tiers, the silent miss, `DEVELOPER_DIR`, the passcode blocker, DDI version tolerance, `rsync --delete`, the keychain session boundary — is not repeated here. What follows is what that document does not yet cover, plus a small number of **new measurements against known doctrine**, marked where they occur.

The bias throughout is toward mechanisms rather than advice. An instruction gets skipped at turn 40 of a long run; a script that refuses does not.

**Contents**

1. [Signing and building from a headless host](#1-signing-and-building-from-a-headless-host)
2. [Simulator vs device truth](#2-simulator-vs-device-truth)
3. [Physical-device operations](#3-physical-device-operations)
4. [Version and install discipline](#4-version-and-install-discipline)
5. [Verification discipline](#5-verification-discipline)
6. [App-side defect classes worth recognising](#6-app-side-defect-classes-worth-recognising)

---

## 1. Signing and building from a headless host

### Split the pipeline: the simulator leg needs no signing at all

**The need:** an agent driving the Mac over plain ssh wants to gate every change on a real build and a real test run, but the keychain is unreachable from an ssh session (TROUBLESHOOTING: *Code signing cannot reach the keychain over SSH*).

**The insight that makes headless iOS work:** *that wall only stands in front of the device leg.* A simulator build does not need a signing identity:

```bash
xcodebuild -project MyApp.xcodeproj -scheme MyApp \
  -configuration Debug \
  -destination "platform=iOS Simulator,name=iPhone 17 Pro" \
  -derivedDataPath .build \
  CODE_SIGNING_ALLOWED=NO \
  build
```

Add `CODE_SIGN_IDENTITY="-"` for an explicit ad-hoc signature. Both the app build and the full unit-test suite (`xcodebuild ... test` against a test scheme) run this way over bare ssh, with no GUI session and no keychain access.

**So the pipeline has two legs with different requirements:**

| Leg | Signing | Session needed | Use it for |
|---|---|---|---|
| **Simulator** | none (`CODE_SIGNING_ALLOWED=NO`) | plain ssh | every change: build gate, unit tests, UI drive |
| **Device** | real identity | **GUI session** (see next section) | anything the simulator structurally cannot prove |

Treating "iOS builds need the GUI session" as a blanket truth costs you the cheap, fast, fully-automatable 95% of the work. Only the signed device build is expensive.

**A related gotcha, same class:** installing onto a device makes **no codesign call** — the signature was applied at build time, and installing only transfers an already-signed bundle. **The install leg runs fine over plain ssh.** Only the *build* needs the GUI session.

### The GUI bridge, in full

TROUBLESHOOTING describes the *shape* of the Apple Events bridge. This is a working, self-contained implementation, small enough to inline. Drop it at `scripts/guirun.sh`:

```bash
#!/bin/bash
# Run a command in the Mac's GUI (Aqua) session and return its output.
#
#   ./scripts/guirun.sh '/abs/path/to/scripts/build-device.sh'
#   GUIRUN_TIMEOUT=1800 ./scripts/guirun.sh '/abs/path/to/scripts/build-device.sh'
#
# WHY: codesign needs the login keychain's PRIVATE KEY, and an ssh session
# cannot reach it. securityd will not release the key to a session that
# cannot present UI ("User interaction is not allowed"). Neither sudo
# (password-gated) nor `launchctl asuser` (needs root) bridges that gap.
# Apple Events DO reach the GUI session from ssh, so Terminal.app can be
# asked to run the command where the keychain is live. Output is
# round-tripped through a file; the exit code is preserved.
set -u

SCRIPT="$1"
STAMP="$$-$(date +%s)"
OUT="/tmp/guirun.out.$STAMP"
DONE="/tmp/guirun.done.$STAMP"
CMD="/tmp/guirun.cmd.$STAMP"
TIMEOUT="${GUIRUN_TIMEOUT:-120}"

rm -f "$OUT" "$DONE" "$CMD"
cat > "$CMD" <<EOF
{ $SCRIPT ; } > "$OUT" 2>&1
echo \$? > "$DONE"
EOF

osascript -e "tell application \"Terminal\" to do script \"bash $CMD ; exit\"" >/dev/null 2>&1

for _ in $(seq 1 "$TIMEOUT"); do
  [ -f "$DONE" ] && break
  sleep 1
done

if [ ! -f "$DONE" ]; then
  echo "!! guirun timed out after ${TIMEOUT}s (partial output below)" >&2
  [ -f "$OUT" ] && cat "$OUT"
  exit 124
fi

cat "$OUT"
RC="$(cat "$DONE")"
rm -f "$OUT" "$DONE" "$CMD"
echo "--- guirun exit=$RC ---"
exit "$RC"
```

**The four properties that matter, and why each is load-bearing:**

1. **The exit code is preserved.** Without the `$?`-into-a-file round trip, the caller sees `osascript`'s exit code and **a failed build reports success** — the silent-wrong-result failure this bundle exists to prevent, one layer down.
2. **The timeout is bounded and distinguishable.** `exit 124` plus whatever partial output exists. A device build that wedges in the GUI session is otherwise invisible to the ssh caller forever.
3. **Absolute paths only.** Terminal's new shell starts at `$HOME`, not at your working directory. The first attempt at this bridge died with exit `127` on a relative `./scripts/build.sh` that was plainly right there. Either hand the bridge absolute paths, or have the bridged command carry its own `cd`.
4. **`GUIRUN_TIMEOUT` is generous for real builds.** The default 120s is right for `security find-identity`; a cold device build wants 1800.

**Preconditions on the Mac, each a one-time cost:**

- **A logged-in GUI session must exist.** No console user, no bridge. Keep the machine awake for long unattended runs (`caffeinate`, lid open, on AC) — if it sleeps or the session locks out, the bridge stops working and the failure looks like a build hang.
- **Automation consent must be granted once, in the GUI.** The first `osascript → Terminal` triggers a macOS Automation prompt that **cannot be answered over ssh**. Grant it once by hand; after that the bridge is unattended.
- **A Terminal window visibly opens and closes on the Mac's screen** for every bridged command. Expected, not a defect, and worth telling whoever owns the machine before they watch their Mac apparently operate itself.

### Two contradictory identity rules, and when each applies

Both of these are true, and applying the wrong one produces a confident hard error.

**Rule A — manual signing and direct `codesign -s`: select by SHA-1 hash, never by name.**

```
$ codesign -s "Apple Development" ...
error: ... ambiguous (matches multiple identities)
```

Two certificates with the same common name is the normal state of a machine that has been signing for a while. Column 2 of `security find-identity -v -p codesigning` is the SHA-1 hash. Use it:

```bash
IDENTITY="$(security find-identity -v -p codesigning \
  | awk '/Apple Development/ {print $2; exit}')"
```

**Rule B — under `CODE_SIGN_STYLE=Automatic`, naming any identity is a hard error.**

```
error: MyApp has conflicting provisioning settings. MyApp is automatically
signed, but code signing identity <hash> has been manually specified.
```

Automatic signing resolves the certificate itself from the team plus the profile it provisions. Pass the **generic** `CODE_SIGN_IDENTITY="Apple Development"` and let it resolve.

**The useful synthesis:** run `find-identity` anyway, as a **precondition gate rather than a selection**. If it returns nothing you are in an ssh session and the build is going to die at its very last step, twenty minutes from now. Fail at second zero instead, and name `guirun.sh` in the error:

```bash
if [ -z "$IDENTITY" ]; then
  echo "!! no Apple Development codesigning identity is reachable." >&2
  echo "   If this is an ssh session, that is expected: the login keychain's" >&2
  echo "   private keys are not reachable from one. Run via scripts/guirun.sh." >&2
  exit 1
fi
```

The team id is also only visible once identities are reachable — resolve it *after* this gate, and detect it rather than hardcoding it. A hardcoded team id is someone else's, and a second developer cannot sign with it.

### The free-tier device build, end to end

```bash
xcodebuild -project MyApp.xcodeproj -scheme MyApp \
  -destination "platform=iOS,id=<40-hex-device-udid>" \
  -derivedDataPath .build-device \
  -allowProvisioningUpdates \
  DEVELOPMENT_TEAM="<your team id>" \
  CODE_SIGN_STYLE=Automatic \
  CODE_SIGN_IDENTITY="Apple Development" \
  build
```

`-allowProvisioningUpdates` is what lets automatic signing register the device and mint the profile without opening Xcode.

**Confirm the device is a valid destination before you spend a build on it:**

```bash
xcodebuild -project MyApp.xcodeproj -scheme MyApp -showdestinations | grep -vi simulator
```

### `bundle id "…" cannot be registered` — Apple's App ID registry is global

**Symptom:** free-tier automatic signing refuses with *"cannot be registered to your development team"* or *"No profiles for '…' were found"*, for a bundle id you have never published.

**Cause:** the App ID namespace is **global across all of Apple's developers**, not per-team. A short, obvious identifier (`com.myapp.ios`) is very likely already claimed by someone else. Free provisioning can only register an **unclaimed** id.

**Fix:** use a developer-unique prefix (`com.<something-unique>.myapp.ios`) and **declare it in exactly one place** — see the next section for why "one place" is not a style preference.

### Never trust a committed `.xcodeproj`

**Symptom:** a build setting you are certain you changed has no effect; a setting nobody remembers adding is present; the device build and the simulator build disagree about something neither script mentions.

**Cause:** `project.pbxproj` is a generated-looking file that Xcode silently rewrites on any GUI interaction. Once it is committed, it is a second source of truth, and it wins.

**Fix:** keep a declarative project spec (`project.yml` with `xcodegen`) as the single source, do not commit the `.xcodeproj`, and regenerate it on **every** build:

```bash
rm -rf MyApp.xcodeproj && xcodegen generate
```

Then **verify the generated project carries exactly the identifiers the spec declares**, as a gate, before anything is built that carries them. That gate is what stops a stray edit or a resurrected `sed`/`perl` one-liner from quietly producing a second app (§3).

### Assert Info.plist keys on the BUILT bundle, never on the source

**Symptom:** a capability that is plainly declared in your project spec does not work on the device, with an error that names something else entirely.

**The worked example, which is the whole argument:** a CallKit `CXStartCallAction` refused with `Code=1`. That is not a code failure — it is the built bundle missing `voip` from `UIBackgroundModes`. A source-level check passes happily on a bundle that shipped without the key.

**Fix — gate the build on the artifact:**

```bash
MODES="$(/usr/libexec/PlistBuddy -c 'Print :UIBackgroundModes' "$APP/Info.plist")"
echo "$MODES" | grep -qx '    voip' || {
  echo "!! BUILT bundle is missing UIBackgroundModes 'voip' — every call will" >&2
  echo "   be refused Code=1. Stopping." >&2
  exit 1
}
```

Generalise it: **any Info.plist key your runtime behaviour depends on is worth asserting on the built bundle.** The check costs milliseconds and the failure it catches is otherwise only discoverable on real hardware, hours later, presenting as a completely different bug.

### Verify the artifact the device will actually run

```bash
codesign -dv --verbose=4 MyApp.app          # Identifier / TeamIdentifier / Authority / Signature
codesign -d --entitlements :- MyApp.app | plutil -p -
codesign --verify --deep --strict --verbose=2 MyApp.app
```

`--deep --strict` matters: codesign refuses an unsigned subcomponent, so **embedded `.framework`s must be signed too**. A build that produced an app and a broken framework looks identical to a good one until install time.

### Native/Rust slices: the sim and device targets are not interchangeable

**Symptom:** `building for iOS but attempting to link … built for iOS Simulator`.

**Cause:** a static library built for `aarch64-apple-ios-sim` linked into a device build (or the reverse).

**Fix:** carry the target in **one** environment variable that both build legs set, rather than in two places that drift:

| Leg | Rust target |
|---|---|
| Simulator | `aarch64-apple-ios-sim` |
| Device | `aarch64-apple-ios` |

**Related:** a Homebrew-installed Rust ships **no iOS target stdlibs**. Prefer the rustup toolchain and add the targets explicitly:

```bash
export PATH="$HOME/.cargo/bin:$PATH"
rustup target add aarch64-apple-ios aarch64-apple-ios-sim
```

**And a false-negative worth knowing:** grepping Swift sources for a native module's **name** finds nothing even when the module is required — generated FFI binding types (uniffi and friends) carry no trace of the crate name. An agent once concluded the native core was unused, dropped the link, and broke the build. **Verify usage by generated type name, not by module name.**

### BSD vs GNU `sed` on the Mac

A Linux-style in-place edit fails on macOS. `sed -i 's/…/…/' file` → error; you need `sed -i '' 's/…/…/' file` (BSD, with an empty backup-suffix argument) or `sed -i.bak`. This bites any script written on Linux and shipped to the build host — which, in this workflow, is most of them.

---

## 2. Simulator vs device truth

### What the simulator structurally cannot prove

The tiers table in the README is about *what the tooling can do*. This is the other half: **what the platform itself refuses on a simulator**, regardless of tooling.

| Capability | Simulator | Consequence |
|---|---|---|
| **CallKit / `CXStartCallAction`** | **refused** — the request falls back, `Code=1` | `requested → active` is **device-only evidence**. A simulator run can never produce it |
| **Microphone / acoustic input** | no acoustic path at all | Barge-in, echo cancellation, and real capture-rate behaviour are unobservable |
| **Teardown ordering bugs behind a call lifecycle** | unreachable | If the state that triggers them (an active call UUID) can never be non-nil, the buggy code path is never entered |

**The discipline this implies:** before running a device round to prove something, write down **what specifically would count as proof**, and **what result means it was not exercised at all**. For the teardown case above: if the call never goes active, the teardown path was never entered — that is a *finding*, not a pass. A run that cannot fail is not evidence.

### Verify WHICH code path ran, not that a run happened

**This is the single most expensive lesson in this document.**

**Symptom:** "voice works on the simulator, is dead on the device." Eight consecutive device sessions had completed successfully.

**Cause:** every one of those device sessions had been launched with a synthetic-capture environment flag still set — a test seam that exercises a **completely different** `AVAudioSession` branch (`.playback`) from the real microphone path. The real capture chain had **never executed on hardware, once, in the project's history.** Across every evidence file: 15 occurrences of `synthetic`, zero of `mic`.

Eight green runs proved nothing about the thing being debugged, and nothing anywhere said so.

**Fix — make the branch identify itself in the log, and assert on it:**

Emit a structured marker at every audio start, carrying enough to distinguish the branches unambiguously:

```json
{"event": "audio_handshake", "source": "mic",       "input_sample_rate": 48000, "aec_enabled": true}
{"event": "audio_handshake", "source": "synthetic", "input_sample_rate": 24000, "aec_enabled": false}
```

Then gate the device round on `source == "mic"`, not on "the session completed".

**Generalise past audio.** Any test seam that swaps an implementation — a fake clock, a stub transport, a synthetic sensor, an offline provider — creates this exact failure mode: a full green run through the wrong branch. **If a seam can silently change which code executes, the run must state which side of the seam it took.** A green run whose branch you cannot name is not evidence.

### The app data container UUID changes after every test reinstall

**Symptom:** you read the app's sandbox after a test run and see stale data, or an empty directory where files were definitely written.

**Cause:** iOS hands out a **new data-container UUID** after every `xcodebuild test` reinstall. A path resolved before the run points at the previous container.

**Fix:** re-resolve after every install/test cycle, never cache it:

```bash
xcrun simctl get_app_container <SIM_UDID> com.example.myapp data
```

Sandbox roots are only `Documents`, `Library`, and `tmp`. Nothing you write outside those survives, on either tier.

### Deterministic permission state on the simulator

Do not test permission flows against whatever state the simulator happens to be in:

```bash
xcrun simctl privacy <SIM_UDID> reset all com.example.myapp
xcrun simctl privacy <SIM_UDID> grant  microphone com.example.myapp
xcrun simctl privacy <SIM_UDID> revoke microphone com.example.myapp
```

`reset` puts the permission back to *undetermined*, which is the only way to reliably exercise the first-run prompt.

### `xcodebuild` does not forward launch environment to the UI-test runner

**Symptom:** an environment variable set for `xcodebuild test` is simply absent inside the running UI test.

**Cause:** the test runner is a separate process launched by the test host. Plain environment does not cross that boundary.

**Fix:** pass fixtures either through a **shared file channel** the runner reads at startup (`/tmp/<something>` written before the run), or via the `TEST_RUNNER_`-prefixed environment convention. Silently-absent configuration otherwise reads as "the feature is broken".

### Where crash reports live

| Tier | Path |
|---|---|
| **Simulator** | `~/Library/Developer/CoreSimulator/Devices/<SIM_UDID>/**/*.ips` |
| **Device**, pulled to the Mac | `~/Library/Logs/DiagnosticReports/*.ips`, filtered by app name |
| **Device**, pulled directly | `pymobiledevice3 crash ls` / `crash pull <dir>` / `crash parse <file>.ips` |

An empty listing is a real answer: no crash. Say so, rather than reporting "could not find crash logs", which reads as a tooling failure.

---

## 3. Physical-device operations

### One bundle id, enforced by the install script

**The incident, which cost a week:** free-tier automatic signing once produced an **auto-prefixed** bundle id alongside the intended one. The phone ended up carrying **two apps with the same display name and the same icon**, indistinguishable from the home screen.

Because **pairing/session state lives per app container** and **TCC permission grants are keyed per bundle id**, the developer granted the microphone to one and paired the other. Both were then permanently broken in ways that looked exactly like an application bug. **Nothing errored anywhere.** That is what made it expensive.

**The fix that actually holds is a gate in the install path, not a line in a README:**

- **Declare the bundle id in exactly one place** (the project spec) and read it from there in every script. A second hardcoded copy in a sibling script is precisely how this happens.
- **Verify the generated project carries exactly the declared ids** before building.
- **Refuse to install** when a second app matching your family is already present, and **name what is already there** and the uninstall remedy in the refusal.
- Treat *unverifiable* as a refusal, not a pass. If the device query failed, you do not know the device is clean.

**Expect a cost when you clean it up:** uninstalling the relic discards its app container **and** its TCC grants. Budget one re-pair and one permission re-grant, and warn the device's owner before they discover it as a regression.

### TCC permissions are per-bundle-id — including yours

A bundle-id change of any kind (a rename, a device-only prefix, a fresh id after the cleanup above) means the new id has **undetermined** permission state. Nothing carries over. On a physical device you can read the real state directly from the TCC database:

```
kTCCServiceMicrophone|com.example.myapp|auth_value=2
```

`0 = denied`, `2 = allowed`, **absent = undetermined**. The distinction matters: "absent" means the prompt has never been answered, and the app will get it on next launch — a very different diagnosis from "denied".

### Install: terminate first, and bound the install anyway

**Symptom:** `pymobiledevice3 apps install` **hangs forever, emitting zero bytes.** Measured: a 200-second bounded watch saw no output at all, four times in a row, identically. No error, no progress, no diagnosis. It reads exactly like "still working".

**Cause:** the app being replaced was **still running on the device**.

**Fix — two mechanisms, not one:**

1. **Ask the device whether the app is running, and terminate it, before installing.** The hang then does not happen.
2. **Bound the install with a timeout anyway**, and on timeout print the cause and the remedy *by name*. If the hang ever acquires a second cause, the next person reads a sentence instead of losing a week.

**The detection trap — read this before writing that check.** The obvious implementation is wrong:

```bash
if pymobiledevice3 developer dvt process-id-for-bundle-id "$BID"; then
    echo "running"      # WRONG. Always taken.
fi
```

Measured against a tethered iPhone:

| Query | stdout | exit code |
|---|---|---|
| app installed **and running** | `11831` | **0** |
| app installed, **not running** | `0` | **0** |
| app **not installed at all** | `0` | **0** |

**The exit status carries no information. Parse stdout.** A literal `0` on stdout means *not running* — it is not a PID. And `0` does **not** distinguish "not running" from "not installed"; for the install decision that distinction is irrelevant (neither can hold the installer open), so do not pretend to tell them apart. **No parsable integer at all means UNKNOWN, and unknown must be reported as unknown** — never silently treated as "not running", which is the exact shape of the bug the script exists to kill.

These are DVT instrumentation calls, so they need the **Developer Disk Image mounted**. If it is not, detection degrades to UNKNOWN and the install still runs, still bounded. Losing detection degrades you to "the old behaviour, with a timeout". It must never degrade you to a silent hang.

### Scope every device call to an explicit UDID

`pymobiledevice3 <cmd> --help` says it plainly:

```
--udid   Target device UDID (defaults to THE FIRST USB DEVICE).
```

"The first USB device" is not a device your script chose. Attach a second phone — or an iPad, which is usually already in a developer Mac's history — and an unscoped detect/kill silently **answers about, and acts on, whichever one usbmux enumerated first**, while the install goes somewhere else entirely. The result is a script that reports "not running" about the wrong phone and then hangs installing to the right one.

Thread one resolved UDID through **detect, terminate, install, and launch**, and assert in your own tests that every device call carries it. This is the same argument TROUBLESHOOTING makes in *A hardcoded UDID goes stale silently*, from the opposite direction: there, the danger is a **remembered** UDID; here, it is an **implicit** one. Both end up operating on hardware nobody selected.

### Pull the real crash log — it beats every hypothesis

**Symptom:** a user reports a crash; you have a plausible theory and no evidence.

**The move:** pull the actual `.ips` off the device.

```bash
pymobiledevice3 crash ls
pymobiledevice3 crash pull ./crash-dump/
pymobiledevice3 crash parse ./crash-dump/MyApp-2026-08-27-060215.ips
```

A crash report timestamped to the second, matching the user's report, ended a debate that several competing hypotheses had not. **Root-cause from the real stack, not from the most plausible story.** The dSYM for symbolication is in the Mac's build products directory — keep the build that shipped to the device, or the stack is addresses.

### Push files into the app's sandbox on device

For seeding credentials, fixtures, or config onto a device build:

```bash
pymobiledevice3 apps push com.example.myapp ./local-file /remote/path --documents
```

Or the HouseArrest service API with `documents_only=True`, plus the `afc` shell for interactive poking. **The `afc` shell garbles under a non-C locale** — `export LC_ALL=C LANG=C` before using it, and filter the interactive-shell banner noise out of anything you parse.

### When `devicectl` says "unavailable" but the device is fine

TROUBLESHOOTING already establishes that the device path branches on `ProductVersion`. Two additions to that toolkit:

- **Legacy enumeration:** when `xcrun devicectl list devices` reports an older device unavailable, `xcrun xctrace list devices` still sees it — filter out the simulators. Or skip it and enumerate entirely through `pymobiledevice3 usbmux list`.
- **Device recon before blaming the app:** `pymobiledevice3 mounter list` (is the DDI mounted?) and `pymobiledevice3 lockdown info` (`ProductVersion`, `DeveloperModeStatus`, `PasswordProtected`, `ActivationState`, `CPUArchitecture`) answer, in two calls, most of the questions that otherwise turn into an hour of guessing.

### Re-test on device without rebuilding

A device rebuild is the expensive step. If the only thing changing is which tests run, reuse the prebuilt bundle:

```bash
xcodebuild -xctestrun <path>.xctestrun \
  -destination "platform=iOS,id=<device-udid>" \
  -only-testing:MyAppUITests/SomeTest
```

Produce the `.xctestrun` with `build-for-testing` on the earlier signed build.

### The free tier has no synthetic tap — so device tests must self-drive

Extending the README's tier table with what was learned trying to drive a real device as a user:

- **There is no synthetic tap on the free device tier.** Full stop. `pymobiledevice3` gives identity, apps, screenshot, syslog, install and launch — **not** input injection. Driving a real device as a user needs a signed WebDriverAgent, which needs a paid account.
- **Therefore a device UI test must drive itself**: the assertions live inside an XCUITest bundle that runs *on* the device, rather than being poked from the host.
- **And that path is fragile on free signing.** A free-signed XCUITest runner **crashed on launch**; diagnosing it meant `pymobiledevice3 crash ls | grep Runner` → `crash parse`, plus `otool -L` on the xctest binary to check framework/dylib linkage. It is a real path, not a comfortable one — budget accordingly, and prefer moving the assertion into the app's own instrumented output where you can.

### Free provisioning expires every seven days

A build installed with a free-tier profile **stops launching after seven days**. Plan a redeploy cadence, and make it the first question when an app that worked yesterday will not open today — **it is far more often an expired profile than a regression.** The failure gives the device's owner no useful explanation, so if someone else is carrying the phone, tell them this in advance.

---

## 4. Version and install discipline

### The build number must move with the code

**Symptom, and it will happen to you:** someone spends an afternoon debugging bugs that were fixed days ago, because the build on the phone was not the build in the branch.

**Fix — three parts, all cheap:**

1. **The version lives in exactly one place** — the project spec's `MARKETING_VERSION` (`CFBundleShortVersionString`) and `CURRENT_PROJECT_VERSION` (`CFBundleVersion`), with `Info.plist` referencing them via `$(…)` so the built bundle cannot drift from the declaration.
2. **`CFBundleVersion` advances on every marketing bump, not just on its own.** It is the monotonic build number — the thing that tells two builds apart. A marketing bump that leaves it alone ships two different builds wearing the same identifier. (The Android analogue, `versionCode`, is treated as strictly-increasing by its distribution layer, which refuses a non-advancing republish outright; iOS is more permissive and therefore more dangerous.)
3. **Read the version off the BUILT bundle**, with `PlistBuddy` on `<App>/Info.plist` — never from the source. That is the number the device will report.

**The cheap honest fallback, worth shipping:** a "Built &lt;date&gt;" row in the app's own settings screen, derived from the **executable's real mtime** at runtime. It cannot drift, it needs no discipline to maintain, and it turns "which build is this?" into a question the person holding the phone can answer without a cable.

### Match versions before debugging anything

The first question in any device bug report is not "what does the code do" — it is **"which build is actually on the device, and how does it compare to the branch?"**

- iOS: `pymobiledevice3 apps list --user`, or the app's own version row.
- Then compare against the branch, explicitly, before forming a single hypothesis.

Debugging a stale build is unbounded work with no possible success. Ten seconds of version comparison up front eliminates it.

---

## 5. Verification discipline

This section is about how to know whether the thing you just observed is evidence. Every item is a false-positive that actually happened.

### Inherited artifacts are the number one false signal

**The failure shape:** work happens on a branch. That branch inherited an `EVIDENCE/` directory, a transcript, a log — from the branch it forked from. Later, someone reads those inherited files as *this run's* output.

Three separate false alarms in one project, all this shape. The worst: **an inherited simulator transcript nearly "proved" that CallKit worked on a physical device** — a claim the simulator is structurally incapable of producing (§2).

**The gates, both cheap:**

```bash
# 1. Is this file NEW on this branch, or inherited?
git diff --stat $(git merge-base main HEAD)..HEAD -- EVIDENCE/

# 2. Is this specific artifact byte-identical to the inherited copy?
md5sum EVIDENCE/run-transcript.jsonl
git show $(git merge-base main HEAD):EVIDENCE/run-transcript.jsonl | md5sum
```

**`git diff main..HEAD` lies** as soon as `main` moves ahead of your branch point — it reports changes that came from `main`, not from you. **Always diff against `git merge-base main HEAD`.** (This one nearly produced a false accusation in the other direction: a file flagged as an out-of-scope change that the branch had never touched.)

### Delegated monitors fabricate; only your own artifact check promotes anything to proven

A fast-model monitor watching a long device run reported, confidently, **"CallKit went ACTIVE on the device."** It was false. The claim came from a log fragment; an `md5sum` falsified it in about thirty seconds — the file it had read was the inherited simulator transcript, whose only telecom event was the simulator's own refusal.

The same claim became **true** roughly twenty minutes later, on a subsequent run, verified directly. Which is the point: the monitor was not wrong about the world, it was **wrong about what it had evidence for**, and nothing in its report distinguished the two.

**The rule that came out of it, worth putting in the monitor's own instructions verbatim:**

> **You report raw observations only. You do not interpret, conclude, or declare anything proven.**

And on the receiving side: **only an artifact check you run yourself promotes something to proven.** Prefer checks that can actually fail — an `md5sum` against a known-inherited copy, a `git diff --stat` against the merge-base, a grep for a specific structured event — over prose summaries, which cannot.

### Proof by absence needs the mechanism, not just the artifact

**The trap, which very nearly caused a correct fix to be rejected:** a teardown-ordering crash fix was validated by six clean cycles whose transcripts showed the terminal event count as **zero** — which was the *identical signature* an earlier, honest "NOT PROVEN" round had reported.

The truth: the terminal event arrives **after** the transcript writer closes, so a guard correctly **drops** it. **Its absence in the transcript is the fix working.** The actual proof lived in the app log — the chokepoint being reached, then the post-close event being dropped by name.

**The lesson: when your evidence is an absence, you must verify the mechanism that produces the absence.** Otherwise "the bug did not happen" and "the test did not run" are indistinguishable, and you will eventually reject a good fix or accept a run that never executed.

### Rescue evidence off the build host before the run ends

A crash mid-run loses anything uncommitted. On a long device round, copy the transcript/log back to the orchestrating machine **while it still exists**, then immediately `md5sum` it against the known-inherited copy to establish it is genuinely new:

```bash
scp mac-build-host:/tmp/dev-transcript.jsonl ./_rescue/dev-transcript-$(date +%H%M%SZ).jsonl
md5sum ./_rescue/dev-transcript-*.jsonl
```

### Small operational rules that each cost something

- **`tee -a`, never `tee`.** Evidence written with plain `tee` dies with the pane it was running in.
- **Gate, then push, as separate commands.** `pytest | tail -2 && git push` swallows failures: in a pipeline, the exit status is the *last* command's, so `set -e` never fires and a red suite pushes. This one bit twice in a single day.
- **Never judge a background run by whether its pane is still alive.** A killed session emits no completion signal at all. **Check artifacts.**
- **Redact ephemeral provider secrets before committing evidence.** Short-lived client secrets appear in captured API responses and remain in git history long after they expire: `sed -i -E 's/ek_[a-f0-9]{16,}/ek_<REDACTED>/g'`.
- **A device round needs the phone awake and unlocked.** Install and any on-device UI work both require it, and the Auto-Lock timer fires precisely when nobody is holding it (TROUBLESHOOTING: *A locked device refuses everything*). If someone else owns the phone, ask them to leave it unlocked **before** the run rather than paging them mid-round.

---

## 6. App-side defect classes worth recognising

Not harness problems — application bugs that a device/simulator harness is uniquely positioned to surface, and that are hard to identify from a stack trace alone.

### `scrollTo` called synchronously during a rapid SwiftUI list diff

**Symptom:** `SIGABRT` inside `UICollectionView` scroll-target validation, under live-updating list content. Reproduces easily under load, essentially never in a calm manual test.

**Cause:** `ScrollViewProxy.scrollTo` called **synchronously** from `.onChange` / `.onAppear` while the `List` is mid-diff. At a high update rate (a live transcription feed at roughly 10 Hz was the trigger here) the scroll target is validated against a collection state that is already gone.

**Fix:** defer every programmatic scroll past the current update pass — `DispatchQueue.main.asyncAfter(deadline: .now() + …)` or an equivalent hop. The rule generalises: **do not command a scroll from inside the update that changes what you are scrolling to.**

**Why it belongs here:** the crash rate scales with update frequency, so it is invisible to a hand-driven test and obvious to an automated one. If you are driving a screen with fast-changing content, expect this class and check for it deliberately.

---

*All measurements in this document are from macOS 26.x / Xcode 26.x hosts against physical iPhones on iOS 16.7 and iOS 26.6, August 2026, on the free provisioning tier. Where a finding is a single-device field report rather than a survey, it says so.*

---
name: ios-headless-build-and-sign
description: "Build and code-sign an iOS app for the simulator or a physical device from a headless Mac driven over plain SSH, with no GUI session and no Xcode UI in the loop. Covers the unsigned simulator leg (CODE_SIGNING_ALLOWED=NO), the Apple-Events GUI bridge that the signed device leg requires, resolving a signing identity under manual vs automatic signing, the free-tier device build invocation, the App-ID-namespace registration failure and its fix, xcodegen project regeneration discipline, asserting Info.plist keys on the BUILT bundle rather than the source, codesign artifact verification, and the simulator/device Rust-slice target split. Use when driving an iOS build-and-sign pipeline from a non-GUI (ssh) session, when a device build fails at signing with a misleading 'no identity found' error, or when a capability declared in the project spec silently does not work on-device despite a clean compile."
version: 1.0.0
---

# iOS Headless Build and Sign

Build and sign an iOS app end to end from a Mac reached only over plain SSH — no GUI login required for 95% of the pipeline, and a small, bounded GUI bridge for the part that genuinely needs one.

For the full narrative behind each of these findings (measurements, incidents, dates), see `docs/FIELD-NOTES-2026-08.md` §1 in this repo.

## 1. Split the pipeline: only the device leg needs signing

The keychain's private key is unreachable from an ssh session (`securityd` will not release it to a session that cannot present UI). That wall only stands in front of the **device** leg.

| Leg | Signing | Session needed | Use it for |
|---|---|---|---|
| **Simulator** | none (`CODE_SIGNING_ALLOWED=NO`) | plain ssh | every change: build gate, unit tests, UI drive |
| **Device** | real identity | GUI session (§2) | anything the simulator cannot prove |

Build and test the simulator leg over bare ssh:

```bash
xcodebuild -project MyApp.xcodeproj -scheme MyApp \
  -configuration Debug \
  -destination "platform=iOS Simulator,name=iPhone 17 Pro" \
  -derivedDataPath .build \
  CODE_SIGNING_ALLOWED=NO \
  build
# same flags work for `... test` against a test scheme
```

Add `CODE_SIGN_IDENTITY="-"` for an explicit ad-hoc signature if a build step demands one.

**Installing onto a device needs no GUI session either** — installing only transfers a bundle that was already signed at build time. Only the *build* step needs the bridge below.

## 2. The GUI bridge (device leg only)

A ready-to-use implementation ships at `scripts/guirun.sh` in this repo:

```bash
./scripts/guirun.sh '/abs/path/to/scripts/build-device.sh'
GUIRUN_TIMEOUT=1800 ./scripts/guirun.sh '/abs/path/to/scripts/build-device.sh'
```

It asks Terminal.app (via Apple Events, which reach the GUI session from ssh) to run your script where the keychain is live, round-trips the exit code through a file, and preserves it — without that round trip a failed build silently reports success.

**Preconditions, each a one-time cost:**
- A logged-in GUI session must exist on the Mac. Keep it awake for long runs (`caffeinate`, lid open, on AC).
- macOS Automation consent must be granted once, by hand, in the GUI — the first `osascript → Terminal` prompt cannot be answered over ssh.
- A Terminal window will visibly open and close for every bridged command. Expected, not a defect.
- Always pass **absolute paths** into the bridge — the bridged shell starts at `$HOME`, not your working directory.
- `GUIRUN_TIMEOUT` defaults to 120s; a cold device build wants 1800.

## 3. Resolve the signing identity — two rules, and when each applies

**Rule A — manual signing / a direct `codesign -s`: select by SHA-1, never by name.** Two certificates sharing a common name is the normal state of a machine that has signed for a while:

```bash
IDENTITY="$(security find-identity -v -p codesigning \
  | awk '/Apple Development/ {print $2; exit}')"
```

**Rule B — under `CODE_SIGN_STYLE=Automatic`, naming any identity is a hard error.** Pass the generic name and let it resolve:

```
CODE_SIGN_IDENTITY="Apple Development"
```

**Gate on reachability before spending twenty minutes on a build that is going to fail at its last step:**

```bash
if [ -z "$IDENTITY" ]; then
  echo "!! no Apple Development codesigning identity is reachable." >&2
  echo "   If this is an ssh session, that is expected. Run via scripts/guirun.sh." >&2
  exit 1
fi
```

Detect the team id after this gate too — never hardcode one; it belongs to whoever's certificate it is.

## 4. The free-tier device build

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

`-allowProvisioningUpdates` lets automatic signing register the device and mint the profile without opening Xcode. Confirm the device is a valid destination before spending a build on it:

```bash
xcodebuild -project MyApp.xcodeproj -scheme MyApp -showdestinations | grep -vi simulator
```

## 5. `bundle id "…" cannot be registered`

**Cause:** the App ID namespace is global across every Apple developer, not per-team. A short, obvious bundle id (`com.myapp.ios`) is very likely already claimed by someone else, and free provisioning can only register an unclaimed id.

**Fix:** use a developer-unique prefix (`com.<something-unique>.myapp.ios`) and declare it in exactly **one place** — see §6.

## 6. Never trust a committed `.xcodeproj`

`project.pbxproj` is silently rewritten by Xcode on any GUI interaction. Once committed, it is a second, competing source of truth.

**Fix:** keep a declarative spec (`project.yml` + `xcodegen`) as the single source, never commit the `.xcodeproj`, and regenerate it on **every** build:

```bash
rm -rf MyApp.xcodeproj && xcodegen generate
```

Then verify the generated project carries exactly the identifiers the spec declares, as a gate, before building anything with them.

## 7. Assert Info.plist keys on the BUILT bundle, never the source

A capability plainly declared in the project spec can still be absent from the shipped bundle. Worked example: `CXStartCallAction` refused with `Code=1` because the built bundle was missing `voip` from `UIBackgroundModes` — a source-level check passed happily on the bundle that shipped without the key.

```bash
MODES="$(/usr/libexec/PlistBuddy -c 'Print :UIBackgroundModes' "$APP/Info.plist")"
echo "$MODES" | grep -qx '    voip' || {
  echo "!! BUILT bundle is missing UIBackgroundModes 'voip'." >&2
  exit 1
}
```

Generalise: any Info.plist key your runtime behaviour depends on is worth asserting on the built bundle. The check costs milliseconds; the failure it catches is otherwise only discoverable on real hardware, hours later, as an apparently unrelated bug.

## 8. Verify the artifact the device will actually run

```bash
codesign -dv --verbose=4 MyApp.app
codesign -d --entitlements :- MyApp.app | plutil -p -
codesign --verify --deep --strict --verbose=2 MyApp.app
```

`--deep --strict` matters: it refuses an unsigned subcomponent, so embedded `.framework`s must be signed too. A build that produced a good app and a broken framework looks identical to a good one until install time.

## 9. Native/Rust slices: sim and device targets are not interchangeable

| Leg | Rust target |
|---|---|
| Simulator | `aarch64-apple-ios-sim` |
| Device | `aarch64-apple-ios` |

Carry the target in **one** environment variable both build legs read, rather than in two places that drift. A Homebrew-installed Rust ships no iOS target stdlibs — prefer rustup and add the targets explicitly:

```bash
export PATH="$HOME/.cargo/bin:$PATH"
rustup target add aarch64-apple-ios aarch64-apple-ios-sim
```

**A false-negative worth knowing:** grepping Swift sources for a native module's *name* finds nothing even when the module is required — generated FFI binding types (uniffi and similar) carry no trace of the crate name. Verify usage by generated type name, never by module name, before concluding a native crate is unused.

## 10. BSD vs GNU `sed` on the Mac

A Linux-style in-place edit fails: `sed -i 's/…/…/' file` errors on macOS. Use `sed -i '' 's/…/…/' file` (BSD, empty backup-suffix argument) or `sed -i.bak`. This bites any script written on Linux and shipped to the build host, which in a headless-Mac workflow is most of them.

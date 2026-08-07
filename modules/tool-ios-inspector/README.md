# amplifier-module-tool-ios-inspector

Drive and inspect iOS apps on a booted Simulator, or read-only inspect a
physical device, on a macOS host (local, or a remote Mac over SSH).

Mirrors the sibling `amplifier-module-tool-android-inspector` module's shape
(`_ok`/`_err` envelope, single verb-dispatch tool, selector-first
interaction) so the two are learnable as one thing. See
`docs/designs/ios-tester-design.md` in the bundle root for the full design
rationale, including what was independently verified against a real
simulator and device versus inferred from `axe`'s documented conventions.

## Layout

- `runner.py` -- the single seam deciding local vs. `ssh_host`-remote command
  execution (and file transfer).
- `axe.py` -- `AXFrame` parsing, points<->pixels conversion, selector
  matching, and the simulator interaction protocol (tap/type/key/swipe/wait_for).
- `simctl.py` -- simulator lifecycle (`create_sim`/`boot`/.../`terminate`) and
  sensing (`screenshot`, bounded `logs`, scale measurement).
- `device.py` -- the free physical-device tier (info, screenshot, apps,
  elements, Developer Mode, DDI mounting) via `libimobiledevice` +
  `pymobiledevice3`.
- `doctor.py` -- full host readiness report; every check runs even if an
  earlier one fails.
- `evidence.py` -- collision-proof evidence filenames (timestamp + random
  suffix), shared pattern with the Android tool.
- `__init__.py` -- the `IosInspectorTool` verb dispatcher and `mount()`
  entry point.

## Command provenance

Every simulator lifecycle/screenshot/`describe-ui`/`tap --label` command,
and every physical-device `idevice*`/`pymobiledevice3 amfi`/`pymobiledevice3
developer accessibility list-items` command, was run live against a real
Mac + simulator + iPhone X before this module was written. A small number of
simulator interaction ops (`tap_xy`, `key`, `swipe`, `type_text`, and
`device_apps`) use an INFERRED `axe`/`pymobiledevice3` argv shape that
follows the same flag conventions as the verified commands but was not
independently re-run in this design pass -- each says so plainly in its own
docstring and in the tool's `description` property.

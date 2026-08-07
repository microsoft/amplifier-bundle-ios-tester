"""Simulator lifecycle + sensing via `xcrun simctl` and `axe`.

Every command here was run against a real booted simulator before this
module was written (see `docs/designs/ios-tester-design.md`):

    xcrun simctl list devices booted
    xcrun simctl list devicetypes
    xcrun simctl list runtimes
    xcrun simctl create <name> <devicetype-id> <runtime-id>
    xcrun simctl boot <UDID>                       (~2.7s)
    xcrun simctl shutdown <UDID>
    xcrun simctl install <UDID> <path.app>
    xcrun simctl launch <UDID> <bundle-id>
    xcrun simctl terminate <UDID> <bundle-id>
    xcrun simctl io <UDID> screenshot out.png      ("Wrote screenshot to: ...")
    xcrun simctl spawn <UDID> log stream --predicate '...'

All of it runs through `CommandRunner`, so it works unchanged whether the
simulator is on this Mac or a remote one reached over SSH.

CoreSimulator background noise -- read this before touching any of the
success/failure logic below: on this platform, `simctl` prints, on MANY
commands (`boot`, `launch`, `list`, `delete` -- measured live), the exact
two lines:

    Install Started
    Install Failed: Authorization is required to install the packages.

This is CoreSimulator trying (and being denied, harmlessly, since this tool
runs without sudo -- see `runner.py`) to install OPTIONAL background
components. It is NOT the command failing. Proven live: `simctl launch`
printed exactly this AND returned a live pid (`com.apple.Preferences:
92162`) with a 1.165s runtime. Mirrors the sibling `android_inspector`
tool's `adb.AM_START_ERROR_MARKERS` lesson in reverse: there, a command
exits 0 while printing "Error:"; here, a command prints what looks like an
"Install Failed" error while genuinely succeeding. Both mean the same
rule -- decide success from the OBSERVABLE outcome (a pid returned, the
device reaching Booted, a UDID printed, a file written with real bytes),
never from string-matching output alone. `_coresimulator_noise_lines`
recognises this EXACT signature (and only this signature -- a real error
alongside it is never masked); `launch`/`boot`/`screenshot` additionally
verify the real outcome before trusting an exit code.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .axe import build_flat_nodes, describe_ui_payload
from .device import parse_ios_version
from .runner import CommandRunner

__all__ = [
    "DEFAULT_BOOT_TIMEOUT_S",
    "DEFAULT_CREATE_SIM_TIMEOUT_S",
    "DEFAULT_INSTALL_TIMEOUT_S",
    "DEFAULT_LAUNCH_TIMEOUT_S",
    "DEFAULT_LOG_STREAM_DURATION_S",
    "DEFAULT_SCREENSHOT_TIMEOUT_S",
    "SimctlError",
    "boot",
    "create_sim",
    "install",
    "launch",
    "list_devicetypes",
    "list_runtimes",
    "list_simulators",
    "log_stream",
    "measure_scale",
    "png_dimensions",
    "resolve_devicetype",
    "resolve_runtime",
    "screenshot",
    "shutdown",
    "terminate",
]

DEFAULT_LOG_STREAM_DURATION_S = 5.0

# Slow, state-changing simulator operations get their own larger timeout
# budgets (see runner.py's DEFAULT_TIMEOUT_S docstring for the measured
# ssh_host + first-run CoreSimulator latency this addresses). These are
# BUILT-IN floors -- `IosInspectorState.op_timeout()` lets a caller raise
# them further via config, but never silently shrinks below the generic
# default.
DEFAULT_BOOT_TIMEOUT_S = 120.0
DEFAULT_CREATE_SIM_TIMEOUT_S = 180.0
DEFAULT_INSTALL_TIMEOUT_S = 180.0
DEFAULT_LAUNCH_TIMEOUT_S = 120.0
DEFAULT_SCREENSHOT_TIMEOUT_S = 120.0

_DEVICETYPE_IDENTIFIER_PREFIX = "com.apple.CoreSimulator.SimDeviceType."
_RUNTIME_IDENTIFIER_PREFIX = "com.apple.CoreSimulator.SimRuntime."

# The EXACT, measured-live CoreSimulator background-noise signature (see
# module docstring). Deliberately narrow and specific -- broadening this to
# match partial/generic "Install Failed" text would risk masking a genuine
# app-install failure from the 'install' operation, whose own error
# reporting can legitimately start with similar words.
_CORESIMULATOR_INSTALL_NOISE_MARKERS = (
    "Install Started",
    "Install Failed: Authorization is required to install the packages.",
)

# `simctl launch` reports success as a `<bundle-id>: <pid>` line -- the
# OBSERVABLE proof a process actually started. Preferred over trusting exit
# code alone (see module docstring).
_LAUNCH_PID_RE = re.compile(r":\s*(\d+)\s*$")


class SimctlError(RuntimeError):
    """Raised when a `simctl`/`axe` operation fails."""

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.extra: dict[str, Any] = extra


def _xcrun_simctl(*args: str) -> list[str]:
    return ["xcrun", "simctl", *args]


def _coresimulator_noise_lines(text: str | None) -> list[str]:
    """Return the non-empty lines of `text` IFF every single one of them is
    the known CoreSimulator install-authorization noise signature (see
    module docstring). Returns an EMPTY list if `text` is empty/blank, or
    if ANY line is NOT recognized noise -- a real error must never be
    masked just because this noise also happens to be present alongside
    it."""
    if not text or not text.strip():
        return []
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if lines and all(
        any(marker in line for marker in _CORESIMULATOR_INSTALL_NOISE_MARKERS)
        for line in lines
    ):
        return lines
    return []


def _parse_launch_pid(text: str | None) -> int | None:
    """Parse the pid from a `simctl launch` success line
    (`'<bundle-id>: <pid>'`). Returns `None` if no such line is present --
    the caller decides what that means (it does NOT, by itself, mean the
    launch failed; some simctl versions omit it for an already-running
    app)."""
    if not text:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _LAUNCH_PID_RE.search(line)
        if m:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def list_simulators(runner: CommandRunner) -> list[dict[str, Any]]:
    """`xcrun simctl list devices -j`, flattened to one list of simulators
    (each carrying its `runtime` identifier) across every runtime."""
    result = runner.run(_xcrun_simctl("list", "devices", "-j"))
    if not result.ok:
        raise SimctlError(
            f"simctl list devices failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}"
        )
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise SimctlError(f"Failed to parse simctl list devices JSON: {exc}") from exc

    simulators: list[dict[str, Any]] = []
    for runtime_id, devices in (payload.get("devices") or {}).items():
        for device in devices:
            simulators.append(
                {
                    "udid": device.get("udid"),
                    "name": device.get("name"),
                    "state": device.get("state"),
                    "runtime": runtime_id,
                    "is_available": device.get("isAvailable", True),
                    "backend": "simulator",
                }
            )
    return simulators


def list_devicetypes(runner: CommandRunner) -> list[dict[str, Any]]:
    result = runner.run(_xcrun_simctl("list", "devicetypes", "-j"))
    if not result.ok:
        raise SimctlError(
            f"simctl list devicetypes failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}"
        )
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise SimctlError(
            f"Failed to parse simctl list devicetypes JSON: {exc}"
        ) from exc
    return list(payload.get("devicetypes") or [])


def list_runtimes(runner: CommandRunner) -> list[dict[str, Any]]:
    result = runner.run(_xcrun_simctl("list", "runtimes", "-j"))
    if not result.ok:
        raise SimctlError(
            f"simctl list runtimes failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}"
        )
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise SimctlError(f"Failed to parse simctl list runtimes JSON: {exc}") from exc
    return list(payload.get("runtimes") or [])


# ---------------------------------------------------------------------------
# create_sim parameter resolution -- friendly name OR full identifier OR
# default, mirroring the sibling android_inspector tool's create_avd
# auto-detection (device/tag/api_level default from disk, never hardcoded).
# ---------------------------------------------------------------------------


def resolve_devicetype(
    runner: CommandRunner, requested: str | None = None
) -> tuple[str, str]:
    """Resolve `requested` to a `(identifier, display_name)` pair for
    `create_sim`.

    `requested` may be:
    - `None`: defaults to the newest available iPhone device type,
      discovered from `simctl list devicetypes -j` (ordered by
      `minRuntimeVersion`, the field that structurally correlates with
      device recency -- never a hardcoded identifier string, which would
      silently go stale as new device types ship).
    - A full identifier (`com.apple.CoreSimulator.SimDeviceType.*`):
      passed through as-is.
    - A friendly name (e.g. `'iPhone 17 Pro'`): resolved by exact match
      against `simctl list devicetypes`' `name` field.

    Raises:
        SimctlError: `requested` is a friendly name that matches nothing
            -- lists what IS available. Never silently substitutes a
            different device type than what was asked for.
    """
    devicetypes = list_devicetypes(runner)

    if requested:
        if requested.startswith(_DEVICETYPE_IDENTIFIER_PREFIX):
            match = next(
                (dt for dt in devicetypes if dt.get("identifier") == requested), None
            )
            display_name = (match.get("name") if match else None) or requested
            return requested, display_name

        match = next((dt for dt in devicetypes if dt.get("name") == requested), None)
        if match is None or not match.get("identifier"):
            available = sorted(dt["name"] for dt in devicetypes if dt.get("name"))
            raise SimctlError(
                f"No simulator device type named {requested!r}. Available: "
                f"{', '.join(available) if available else 'none discovered'}.",
                requested=requested,
                available_devicetypes=available,
            )
        return match["identifier"], requested

    iphones = [
        dt
        for dt in devicetypes
        if dt.get("productFamily") == "iPhone"
        and dt.get("identifier")
        and dt.get("name")
    ]
    if not iphones:
        raise SimctlError(
            "No iPhone device types discovered via `simctl list devicetypes` -- "
            "cannot pick a default. Pass 'device_type' explicitly.",
        )
    chosen = max(iphones, key=lambda dt: dt.get("minRuntimeVersion", 0))
    return chosen["identifier"], chosen["name"]


def resolve_runtime(
    runner: CommandRunner, requested: str | None = None
) -> tuple[str, str]:
    """Resolve `requested` to a `(identifier, display_name)` pair for
    `create_sim`.

    `requested` may be:
    - `None`: defaults to the newest AVAILABLE iOS runtime, discovered
      from `simctl list runtimes -j` and ordered by parsed version (see
      `device.parse_ios_version`) -- never a hardcoded identifier, which
      goes stale the moment a new Xcode ships.
    - A full identifier (`com.apple.CoreSimulator.SimRuntime.*`): passed
      through as-is.
    - A friendly name (e.g. `'iOS 26.5'`): resolved by exact match against
      `simctl list runtimes`' `name` field.

    Raises:
        SimctlError: `requested` is a friendly name that matches nothing
            -- lists what IS available. Never silently substitutes a
            different runtime than what was asked for.
    """
    runtimes = list_runtimes(runner)

    if requested:
        if requested.startswith(_RUNTIME_IDENTIFIER_PREFIX):
            match = next(
                (rt for rt in runtimes if rt.get("identifier") == requested), None
            )
            display_name = (match.get("name") if match else None) or requested
            return requested, display_name

        match = next((rt for rt in runtimes if rt.get("name") == requested), None)
        if match is None or not match.get("identifier"):
            available = sorted(rt["name"] for rt in runtimes if rt.get("name"))
            raise SimctlError(
                f"No simulator runtime named {requested!r}. Available: "
                f"{', '.join(available) if available else 'none discovered'}.",
                requested=requested,
                available_runtimes=available,
            )
        return match["identifier"], requested

    ios_available = [
        rt
        for rt in runtimes
        if rt.get("isAvailable", True)
        and str(rt.get("identifier", "")).startswith(_RUNTIME_IDENTIFIER_PREFIX)
        and rt.get("name")
    ]
    if not ios_available:
        raise SimctlError(
            "No available iOS simulator runtimes discovered via `simctl list "
            "runtimes` -- cannot pick a default. Install one via Xcode, or pass "
            "'runtime' explicitly.",
        )
    chosen = max(
        ios_available, key=lambda rt: parse_ios_version(str(rt.get("version", "0")))
    )
    return chosen["identifier"], chosen["name"]


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def create_sim(
    runner: CommandRunner,
    *,
    name: str,
    device_type: str | None = None,
    runtime: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Provision a new simulator. `device_type`/`runtime` are OPTIONAL --
    see `resolve_devicetype`/`resolve_runtime` for friendly-name/identifier/
    default resolution."""
    devicetype_id, devicetype_name = resolve_devicetype(runner, device_type)
    runtime_id, runtime_name = resolve_runtime(runner, runtime)

    result = runner.run(
        _xcrun_simctl("create", name, devicetype_id, runtime_id), timeout=timeout
    )
    noise = _coresimulator_noise_lines(result.stderr) if not result.ok else []
    if not result.ok and not noise:
        raise SimctlError(
            f"simctl create {name!r} failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}",
            name=name,
            device_type=devicetype_id,
            runtime=runtime_id,
        )
    udid = result.stdout.strip()
    if not udid:
        # Observable-outcome check: a UDID must actually be printed --
        # never trust exit code (or the absence of a "real" error message
        # alongside benign noise) alone as proof of success.
        raise SimctlError(
            f"simctl create {name!r} exited {result.returncode} but printed no UDID "
            "-- exit code alone is not proof of success.",
            name=name,
        )
    out: dict[str, Any] = {
        "name": name,
        "udid": udid,
        "device_type": devicetype_name,
        "runtime": runtime_name,
    }
    if noise:
        out["warnings"] = noise
    return out


def _list_simulators_safe(runner: CommandRunner) -> list[dict[str, Any]] | None:
    """`list_simulators`, but swallows `SimctlError` -- for OBSERVATIONAL use
    only (confirming a boot actually landed / reporting the resulting
    device state), where a listing failure should degrade gracefully
    (return `None`, never a fabricated list) rather than mask -- or worse,
    override -- the PRIMARY boot operation's own success/failure decision."""
    try:
        return list_simulators(runner)
    except SimctlError:
        return None


def _lookup_sim_state(sims: list[dict[str, Any]] | None, udid: str) -> str | None:
    """The CURRENT observed `state` string (e.g. `'Booted'`, `'Shutdown'`)
    for `udid` within an already-fetched `sims` listing, or `None` if
    `sims` is `None`/empty or `udid` isn't present in it."""
    if not sims:
        return None
    for s in sims:
        if s.get("udid") == udid:
            return s.get("state")
    return None


def boot(
    runner: CommandRunner, udid: str, *, timeout: float | None = None
) -> dict[str, Any]:
    """Boot simulator `udid`.

    Result always carries `udid`, `already_booted`, and `elapsed_s`
    (measured wall-clock seconds for the `simctl boot` call itself). It
    ALSO carries `state` -- the actually-OBSERVED device state after boot,
    fetched via `simctl list devices` -- whenever that observation could be
    made; if the listing call itself fails, `state` is OMITTED rather than
    set to a null placeholder that would look like data but isn't (the
    boot's own success/failure is unaffected either way -- that decision
    was already made above, from the boot command's own observable
    outcome).
    """
    start = time.monotonic()
    result = runner.run(_xcrun_simctl("boot", udid), timeout=timeout)
    duration_s = time.monotonic() - start
    # "Unable to boot device in current state: Booted" is not a failure --
    # an already-booted simulator being asked to boot again is a no-op, not
    # an error condition a caller needs to handle specially.
    already_booted = "current state: Booted" in (result.stderr or "")
    noise: list[str] = []
    # Fetched at most once, and reused below for the 'state' field --
    # never a second, redundant listing call when this one already answers
    # both questions (did it actually boot? what state is it in now?).
    sims: list[dict[str, Any]] | None = None
    if not result.ok and not already_booted:
        noise = _coresimulator_noise_lines(result.stderr)
        if noise:
            sims = _list_simulators_safe(runner)
        if not noise or _lookup_sim_state(sims, udid) != "Booted":
            raise SimctlError(
                f"simctl boot {udid!r} failed (exit {result.returncode}): "
                f"{(result.stderr or result.stdout).strip()}",
                udid=udid,
            )

    if sims is None:
        sims = _list_simulators_safe(runner)
    out: dict[str, Any] = {
        "udid": udid,
        "already_booted": already_booted,
        "elapsed_s": round(duration_s, 3),
    }
    observed_state = _lookup_sim_state(sims, udid)
    if observed_state is not None:
        out["state"] = observed_state
    if noise:
        out["warnings"] = noise
    return out


def shutdown(
    runner: CommandRunner, udid: str, *, timeout: float | None = None
) -> dict[str, Any]:
    result = runner.run(_xcrun_simctl("shutdown", udid), timeout=timeout)
    already_shutdown = "current state: Shutdown" in (result.stderr or "")
    noise: list[str] = []
    if not result.ok and not already_shutdown:
        noise = _coresimulator_noise_lines(result.stderr)
        if not noise:
            raise SimctlError(
                f"simctl shutdown {udid!r} failed (exit {result.returncode}): "
                f"{(result.stderr or result.stdout).strip()}",
                udid=udid,
            )
    out: dict[str, Any] = {"udid": udid, "already_shutdown": already_shutdown}
    if noise:
        out["warnings"] = noise
    return out


def install(
    runner: CommandRunner, udid: str, app_path: str, *, timeout: float | None = None
) -> dict[str, Any]:
    result = runner.run(_xcrun_simctl("install", udid, app_path), timeout=timeout)
    noise = _coresimulator_noise_lines(result.stderr) if not result.ok else []
    if not result.ok and not noise:
        raise SimctlError(
            f"simctl install {app_path!r} on {udid!r} failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}",
            udid=udid,
            app_path=app_path,
        )
    out: dict[str, Any] = {"udid": udid, "app_path": app_path}
    if noise:
        out["warnings"] = noise
    return out


def launch(
    runner: CommandRunner, udid: str, bundle_id: str, *, timeout: float | None = None
) -> dict[str, Any]:
    result = runner.run(_xcrun_simctl("launch", udid, bundle_id), timeout=timeout)
    # Observable-outcome check: a pid actually returned is the real proof a
    # process started -- preferred over trusting exit code alone, since
    # CoreSimulator can print benign "Install Failed: Authorization..."
    # noise (see module docstring) on a launch that still worked fine.
    pid = _parse_launch_pid(result.stdout) or _parse_launch_pid(result.stderr)
    if pid is None and not result.ok:
        raise SimctlError(
            f"simctl launch {bundle_id!r} on {udid!r} failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}",
            udid=udid,
            bundle_id=bundle_id,
        )
    out: dict[str, Any] = {
        "udid": udid,
        "bundle_id": bundle_id,
        "pid": pid,
        "stdout": result.stdout.strip(),
    }
    noise = _coresimulator_noise_lines(result.stderr) or _coresimulator_noise_lines(
        result.stdout
    )
    if noise:
        out["warnings"] = noise
    return out


def terminate(
    runner: CommandRunner, udid: str, bundle_id: str, *, timeout: float | None = None
) -> dict[str, Any]:
    result = runner.run(_xcrun_simctl("terminate", udid, bundle_id), timeout=timeout)
    noise = _coresimulator_noise_lines(result.stderr) if not result.ok else []
    if not result.ok and not noise:
        raise SimctlError(
            f"simctl terminate {bundle_id!r} on {udid!r} failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}",
            udid=udid,
            bundle_id=bundle_id,
        )
    out: dict[str, Any] = {"udid": udid, "bundle_id": bundle_id, "status": "terminated"}
    if noise:
        out["warnings"] = noise
    return out


# ---------------------------------------------------------------------------
# Sensing -- screenshot
# ---------------------------------------------------------------------------


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read width/height from a PNG's IHDR chunk (always the first chunk).
    Stdlib-only -- no imaging library dependency for a liveness/geometry
    check. Same technique as the sibling android_inspector tool."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return (width, height)


def screenshot(
    runner: CommandRunner,
    udid: str,
    local_dest: Path,
    *,
    remote_tmp: str,
    timeout: float | None = None,
) -> dict[str, Any]:
    """`xcrun simctl io <UDID> screenshot <remote_tmp>`, then fetch it to
    `local_dest` (a no-op copy locally, `scp` when `runner.is_remote`).

    `remote_tmp` is a path on the TARGET host (may be the same host as
    `local_dest`'s filesystem when running locally, or a genuinely remote
    Mac's `/tmp` when `runner.is_remote`) -- callers pick a fresh temp path
    per call so concurrent captures never collide.

    A nonzero exit whose ENTIRE stderr is the benign CoreSimulator noise
    (see module docstring) does not raise immediately -- the real,
    observable proof (a valid PNG actually fetched) is checked below
    instead. A genuinely failed screenshot still raises, either here (any
    OTHER error text) or from the PNG liveness check.
    """
    result = runner.run(
        _xcrun_simctl("io", udid, "screenshot", remote_tmp), timeout=timeout
    )
    noise = _coresimulator_noise_lines(result.stderr) if not result.ok else []
    if not result.ok and not noise:
        raise SimctlError(
            f"simctl io screenshot on {udid!r} failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}",
            udid=udid,
        )
    runner.fetch_file(remote_tmp, local_dest)
    data = local_dest.read_bytes()
    dims = png_dimensions(data)
    if dims is None:
        raise SimctlError(
            f"Screenshot at {local_dest} does not look like a PNG -- liveness check failed.",
            udid=udid,
        )
    out: dict[str, Any] = {
        "udid": udid,
        "image_path": str(local_dest.resolve()),
        "byte_size": len(data),
        "width": dims[0],
        "height": dims[1],
    }
    if noise:
        out["warnings"] = noise
    return out


# ---------------------------------------------------------------------------
# Sensing -- scale measurement (points <-> pixels)
# ---------------------------------------------------------------------------


# The only plausible iOS device scale factors. A measured value that isn't
# close to one of these is a MEASUREMENT BUG, not a datum -- see
# `_nearest_plausible_scale`.
PLAUSIBLE_SCALES: tuple[float, ...] = (1.0, 2.0, 3.0)

# Width-derived and height-derived scale must agree within this RELATIVE
# tolerance (fraction of the larger of the two) -- disagreement beyond this
# means something is genuinely wrong with the measurement, not just float
# noise, and must be surfaced as a hard error rather than silently resolved
# by picking one axis or averaging.
_SCALE_AXIS_AGREEMENT_TOLERANCE = 0.02

# How close a measured scale must be to a PLAUSIBLE_SCALES entry (absolute
# distance) to be accepted at all.
_SCALE_PLAUSIBILITY_TOLERANCE = 0.05


def _nearest_plausible_scale(value: float) -> float | None:
    """Return the entry of `PLAUSIBLE_SCALES` nearest to `value` IFF it is
    within `_SCALE_PLAUSIBILITY_TOLERANCE` of it -- else `None`, meaning
    `value` is not a plausible iOS device scale at all."""
    nearest = min(PLAUSIBLE_SCALES, key=lambda s: abs(s - value))
    if abs(nearest - value) <= _SCALE_PLAUSIBILITY_TOLERANCE:
        return nearest
    return None


def measure_scale(
    runner: CommandRunner,
    udid: str,
    *,
    scratch_dir: Path,
    remote_tmp: str,
    ui_dump_timeout: float | None = None,
    screenshot_timeout: float | None = None,
) -> float:
    """Derive the points<->pixels scale factor for `udid` by comparing a
    fresh screenshot's pixel dimensions to the accessibility tree's ROOT
    node's own frame in points -- e.g. 402x874pt vs a 1206x2622px
    screenshot yields the correct 3.0.

    Deliberately NOT an aggregate bounding box over every node in the tree:
    that computation is corrupted by off-screen/clipped elements carrying
    out-of-range frames (measured live: a real dump containing such a node
    inflated the "width in points" enough to produce 2.3103 instead of the
    correct 3.0 -- a ~23% silent coordinate error on every tap this tool
    would go on to compute). The root node's own frame IS the logical
    screen size and is not subject to that corruption.

    Also NOT a hardcoded per-device-type table, which would silently drift
    as new device types ship, and NOT a simctl/device-metadata lookup --
    no such call is independently verified in this tool, so a missing root
    frame is a hard failure (see below) rather than a second, unverified
    guess.

    Both axes are cross-checked against each other (must agree within
    `_SCALE_AXIS_AGREEMENT_TOLERANCE`) and the result is sanity-gated
    against `PLAUSIBLE_SCALES` (must be within `_SCALE_PLAUSIBILITY_TOLERANCE`
    of 1.0, 2.0, or 3.0) -- a measurement that fails either check is a bug
    to report, never a value to silently accept.

    Raises:
        SimctlError: the screenshot could not be captured; the root frame
            is zero/negative; the width-derived and height-derived scale
            disagree; or the measured scale isn't close to any plausible
            iOS device scale.
        UiDumpError: the accessibility tree could not be obtained, produced
            an empty tree, or its root node carries no frame at all
            (nothing to compare against).
    """
    payload = describe_ui_payload(runner, udid, timeout=ui_dump_timeout)
    nodes = build_flat_nodes(payload, scale=1.0)
    if not nodes:
        from .axe import UiDumpError

        raise UiDumpError(
            f"axe describe-ui for {udid!r} produced an empty tree -- cannot measure the "
            "points<->pixels scale factor."
        )
    root = nodes[0]
    if root.frame_points is None:
        from .axe import UiDumpError

        raise UiDumpError(
            f"The root node of the accessibility tree for {udid!r} carries no AXFrame -- "
            "cannot measure the points<->pixels scale factor from it. Deliberately NOT "
            "falling back to an aggregate bounding box over every node (off-screen/clipped "
            "elements with out-of-range frames corrupt that computation -- see this "
            "function's docstring), and no verified simctl/device-metadata fallback for "
            "native scale exists in this tool. This is a hard failure, not a guess."
        )
    _root_x, _root_y, points_width, points_height = root.frame_points
    if points_width <= 0 or points_height <= 0:
        raise SimctlError(
            f"Measured a zero/negative root frame ({points_width}x{points_height}pt) for "
            f"{udid!r} -- cannot compute scale.",
            udid=udid,
        )

    scratch_path = scratch_dir / f"_scale_probe_{udid}.png"
    shot = screenshot(
        runner,
        udid,
        scratch_path,
        remote_tmp=remote_tmp,
        timeout=screenshot_timeout,
    )
    pixel_width = shot["width"]
    pixel_height = shot["height"]

    width_scale = pixel_width / points_width
    height_scale = pixel_height / points_height
    max_axis_scale = max(width_scale, height_scale)
    if (
        max_axis_scale > 0
        and abs(width_scale - height_scale)
        > _SCALE_AXIS_AGREEMENT_TOLERANCE * max_axis_scale
    ):
        raise SimctlError(
            f"Width-derived and height-derived points<->pixels scale disagree for "
            f"{udid!r}: width {pixel_width}px / {points_width}pt = {width_scale:.4f}, "
            f"height {pixel_height}px / {points_height}pt = {height_scale:.4f}. Refusing "
            "to pick one axis or average them -- this indicates a real measurement error, "
            "not a value to silently resolve.",
            udid=udid,
            width_scale=round(width_scale, 4),
            height_scale=round(height_scale, 4),
        )

    measured = (width_scale + height_scale) / 2.0
    plausible = _nearest_plausible_scale(measured)
    if plausible is None:
        raise SimctlError(
            f"Measured points<->pixels scale {measured:.4f} for {udid!r} is not close to "
            f"any plausible iOS device scale {PLAUSIBLE_SCALES} -- refusing to use an "
            "implausible value silently. This is a measurement bug to fix, not a datum.",
            udid=udid,
            measured_scale=round(measured, 4),
        )
    return plausible


# ---------------------------------------------------------------------------
# Sensing -- bounded log stream
# ---------------------------------------------------------------------------


def log_stream(
    runner: CommandRunner,
    udid: str,
    *,
    predicate: str | None = None,
    duration_s: float = DEFAULT_LOG_STREAM_DURATION_S,
) -> dict[str, Any]:
    """`xcrun simctl spawn <UDID> log stream --predicate '<predicate>'`,
    bounded by `duration_s` -- `log stream` has no built-in duration limit,
    so this tool always caps it with a runner-level timeout and treats the
    resulting timeout as the NORMAL termination condition (not a failure),
    capturing whatever was streamed in that window.

    Uses `raise_on_timeout=False` and checks the STRUCTURAL
    `CommandResult.timed_out` marker (never a string match against stderr
    text) to distinguish "we deliberately bounded this and hit the bound"
    from a genuine command failure.
    """
    argv = ["xcrun", "simctl", "spawn", udid, "log", "stream"]
    if predicate:
        argv.extend(["--predicate", predicate])
    result = runner.run(argv, timeout=duration_s, raise_on_timeout=False)
    # A clean nonzero exit (not the bounded-timeout partial-capture path)
    # that isn't just "we killed it at the timeout" is a real failure.
    if not result.ok and not result.timed_out:
        raise SimctlError(
            f"simctl spawn log stream on {udid!r} failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}",
            udid=udid,
        )
    lines = result.stdout.splitlines()
    return {
        "udid": udid,
        "predicate": predicate,
        "duration_s": duration_s,
        "lines": lines,
        "count": len(lines),
    }

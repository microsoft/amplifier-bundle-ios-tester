"""iOS Inspector Tool for Amplifier.

A single verb-dispatch tool for driving and inspecting iOS apps on a booted
Simulator or (read-only) a physical device -- mirroring the sibling
`android_inspector` tool's shape (`_ok`/`_err` envelope, verb dispatch,
selector-first interaction) so the two are learnable as one thing.

The load-bearing constraint: the accessibility tree (`axe describe-ui`) is
the sensor, the screenshot is for judgment. The iOS-specific trap on top of
that: the tree reports POINTS, screenshots report PIXELS -- every `ui_dump`
result carries both, explicitly labeled, plus the `scale` factor (see
`axe.py`).

`backend` is `"simulator"` (default) or `"device"`. The free device tier can
SEE (info, screenshot, app list, element list) but cannot safely TAP --
`device_elements` carries no geometry, so `tap`/`tap_xy` refuse outright on
`backend="device"` rather than guess a coordinate (see `device.py`).

`ssh_host` (tool config) redirects EVERY command this tool issues to a
remote Mac over `ssh -o BatchMode=yes` -- see `runner.py`, the single seam
that decision goes through.

Operations:
- doctor, list_targets                              (environment)
- create_sim, boot, shutdown, install, launch,
  terminate                                          (simulator lifecycle)
- screenshot, ui_dump, find, logs                    (simulator sensing)
- tap, tap_xy, type_text, key, swipe, wait_for        (simulator interacting)
- device_info, device_screenshot, device_apps,
  device_elements, device_enable_devmode,
  device_mount_ddi                                    (device tier)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import axe as _axe
from . import device as _device
from . import doctor as _doctor
from . import simctl as _simctl
from .axe import (
    SelectorError,
    UiDumpError,
    UiInteractionError,
)
from .axe import (
    key_press as _key_press_impl,
)
from .axe import (
    swipe as _swipe_impl,
)
from .axe import (
    tap_selector as _tap_selector_impl,
)
from .axe import (
    tap_xy as _tap_xy_impl,
)
from .axe import (
    type_text as _type_text_impl,
)
from .axe import (
    wait_for as _wait_for_impl,
)
from .device import DeviceError
from .evidence import unique_evidence_path
from .runner import DEFAULT_DEVELOPER_DIR, DEFAULT_TIMEOUT_S, CommandRunner, RunnerError
from .simctl import SimctlError

__all__ = ["IosInspectorState", "IosInspectorTool", "mount"]

_OPERATIONS = (
    "doctor",
    "list_targets",
    "create_sim",
    "boot",
    "shutdown",
    "install",
    "launch",
    "terminate",
    "screenshot",
    "ui_dump",
    "find",
    "tap",
    "tap_xy",
    "type_text",
    "key",
    "swipe",
    "wait_for",
    "logs",
    "device_info",
    "device_screenshot",
    "device_apps",
    "device_elements",
    "device_enable_devmode",
    "device_mount_ddi",
)

# Ops that only make sense against a booted Simulator -- `axe` drives
# instrumentation that has no physical-device equivalent under these names
# (the device tier's counterparts are the separate `device_*` ops).
#
# 'tap' and 'tap_xy' are deliberately EXCLUDED from this generic check: they
# own a MORE SPECIFIC refusal message (_DEFAULT_TAP_REFUSAL, naming the
# device tier's lack of geometry and pointing at WebDriverAgent -- see
# HARD REQUIREMENT #3) inside their own handlers, which would otherwise be
# pre-empted by this generic "only supports backend='simulator'" message.
_SIMULATOR_ONLY_OPS = frozenset(
    {
        "screenshot",
        "ui_dump",
        "find",
        "type_text",
        "key",
        "swipe",
        "wait_for",
        "logs",
    }
)

_DEFAULT_TAP_REFUSAL = (
    "tap/tap_xy are not supported on backend='device'. The free device tier's "
    "'device_elements' (pymobiledevice3 developer accessibility list-items) returns "
    "NO geometry -- only caption/estimated_uid/platform_identifier/spoken_description "
    "-- so there is no verified coordinate to tap, and physical-device tap via HID is "
    "explicitly deferred (it would require guessing pixel<->normalized-coordinate "
    "conversion, exactly the coordinate-guessing this tool forbids). WebDriverAgent "
    "(deferred; needs an Apple Developer account + signing) is the path that would "
    "provide real rects for on-device tapping. This tool will not guess."
)


def _err(message: str, **extra: Any) -> dict[str, Any]:
    return {"success": False, "error": message, **extra}


def _ok(output: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, **output}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass
class IosInspectorState:
    config: dict[str, Any]
    base_dir: Path
    run_dir: Path
    _cmd_runner: CommandRunner | None = None
    _pymobiledevice3_path: str | None = None
    _scale_cache: dict[str, float] = field(default_factory=dict)
    # Populated when `measure_scale` fails for a udid -- remembers the
    # diagnostic message so it is not re-attempted (and re-failed) on
    # every subsequent `ui_dump`/`find`/`tap`/etc. call in this session.
    _scale_unavailable: dict[str, str] = field(default_factory=dict)
    _screenshot_counters: dict[str, int] = field(default_factory=dict)

    @property
    def developer_dir(self) -> str:
        return str(self.config.get("developer_dir") or DEFAULT_DEVELOPER_DIR)

    @property
    def cmd_runner(self) -> CommandRunner:
        if self._cmd_runner is None:
            self._cmd_runner = CommandRunner(
                ssh_host=self.config.get("ssh_host"),
                developer_dir=self.developer_dir,
                default_timeout=float(
                    self.config.get("command_timeout_s", DEFAULT_TIMEOUT_S)
                ),
            )
        return self._cmd_runner

    @property
    def pymobiledevice3_path(self) -> str:
        if self._pymobiledevice3_path is None:
            self._pymobiledevice3_path = _device.resolve_pymobiledevice3_binary(
                self.cmd_runner, self.config
            )
        return self._pymobiledevice3_path

    def next_screenshot_index(self, udid: str) -> int:
        n = self._screenshot_counters.get(udid, 0) + 1
        self._screenshot_counters[udid] = n
        return n

    def op_timeout(self, op: str, builtin_default: float) -> float:
        """Resolve the effective timeout budget (seconds) for operation
        `op` (e.g. 'boot', 'create_sim', 'install', 'launch', 'ui_dump',
        'screenshot').

        Precedence:
        1. An explicit '{op}_timeout_s' config override always wins.
        2. Otherwise, the LARGER of this op's own built-in default budget
           (`builtin_default`) and the globally configured
           'command_timeout_s' -- a caller who raises the global default
           should never end up with a SMALLER effective budget for a slow
           op than what they explicitly asked for.
        3. Otherwise, `builtin_default`.
        """
        key = f"{op}_timeout_s"
        if key in self.config:
            return float(self.config[key])
        configured_global = self.config.get("command_timeout_s")
        if configured_global is not None:
            return max(float(configured_global), float(builtin_default))
        return float(builtin_default)

    def get_scale(self, udid: str) -> float | None:
        """Lazily measure and cache the points<->pixels scale factor for
        `udid` -- measured once per session per simulator (compared
        against the accessibility tree's ROOT node's own frame -- see
        `simctl.measure_scale`), not re-measured on every `ui_dump` call.

        Returns `None` if the scale cannot be established confidently
        (root frame missing, width/height disagreement, or an implausible
        measured value -- see `simctl.measure_scale`'s docstring). The
        failure is cached too (in `_scale_unavailable`), so it is not
        re-attempted -- and re-failed -- on every subsequent call for this
        `udid`. Callers (`ui_dump`, `find`, ...) MUST treat `None` as
        "omit pixel frames", never as license to guess a conversion.
        """
        if udid in self._scale_cache:
            return self._scale_cache[udid]
        if udid in self._scale_unavailable:
            return None
        remote_tmp = f"/tmp/ios_inspector_scale_{udid}.png"
        try:
            scale = _simctl.measure_scale(
                self.cmd_runner,
                udid,
                scratch_dir=self.run_dir,
                remote_tmp=remote_tmp,
                ui_dump_timeout=self.op_timeout(
                    "ui_dump", _axe.DEFAULT_UI_DUMP_TIMEOUT_S
                ),
                screenshot_timeout=self.op_timeout(
                    "screenshot", _simctl.DEFAULT_SCREENSHOT_TIMEOUT_S
                ),
            )
        except (SimctlError, UiDumpError) as exc:
            self._scale_unavailable[udid] = str(exc)
            return None
        self._scale_cache[udid] = scale
        return scale

    def scale_unavailable_reason(self, udid: str) -> str | None:
        """The diagnostic message from the last failed scale measurement
        for `udid`, if any -- surfaced in `ui_dump`/`find`'s `warnings`
        when `get_scale` returned `None`."""
        return self._scale_unavailable.get(udid)


def _build_state(config: dict[str, Any]) -> IosInspectorState:
    """Pure construction, no module-level caching -- mirrors the
    `android_inspector` tool's Defect-4 fix. A second `mount()` call in the
    same process with a different `config` never silently reuses the first
    mount's state; every mounted tool builds and owns its own state."""
    base_dir = Path(
        str(config.get("work_dir", "~/.amplifier/ios-sessions"))
    ).expanduser()
    base_dir.mkdir(parents=True, exist_ok=True)
    run_dir = base_dir / "_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    return IosInspectorState(config=config, base_dir=base_dir, run_dir=run_dir)


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


class IosInspectorTool:
    """Amplifier Tool for driving and inspecting iOS apps via simctl/axe
    (Simulator) and libimobiledevice/pymobiledevice3 (physical device)."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config: dict[str, Any] = config or {}
        self._state: IosInspectorState | None = None

    def _get_state(self) -> IosInspectorState:
        if self._state is None:
            self._state = _build_state(self._config)
        return self._state

    @property
    def name(self) -> str:
        return "ios_inspector"

    @property
    def description(self) -> str:
        return (
            "Drive and inspect iOS apps on a booted Simulator, or read-only inspect a "
            "physical device, on a macOS host (local, or a remote Mac via 'ssh_host').\n\n"
            "axe describe-ui is the sensor -- every interaction resolves a selector "
            "against the live accessibility tree before acting. Screenshots are for "
            "visual judgment only, never for computing tap coordinates. The "
            "accessibility tree reports POINTS; screenshots report PIXELS -- ui_dump "
            "always returns both, explicitly labeled ('frame_points'/'frame_pixels', "
            "'center_points'/'center_pixels'), plus the measured 'scale' factor. Never "
            "trust a bare coordinate whose unit is ambiguous.\n\n"
            "Environment:\n"
            "- doctor: full host readiness report (macOS, DEVELOPER_DIR/Xcode, simctl, "
            "axe, pymobiledevice3, runtimes, booted simulators, physical devices, "
            "per-device Developer Mode + passcode-blocker awareness, DDI availability "
            "vs each device's iOS version) -- every check runs even if an earlier one "
            "fails; never errors, always returns a report\n"
            "- list_targets: simulators + physical devices, one list; ambiguous (>1 "
            "ready target, no explicit 'udid') is an error\n\n"
            "Simulator lifecycle:\n"
            "- create_sim, boot, shutdown, install, launch, terminate\n"
            "- create_sim: 'name' required; 'device_type'/'runtime' OPTIONAL -- accept "
            "a friendly name ('iPhone 17 Pro', 'iOS 26.5') or a full identifier, and "
            "default to a recent available iPhone / the newest available runtime when "
            "omitted. An unrecognised friendly name errors listing what IS available.\n"
            "- boot/create_sim/install/launch/screenshot/ui_dump each have their own, "
            "larger timeout budget (config: 'boot_timeout_s', 'create_sim_timeout_s', "
            "'install_timeout_s', 'launch_timeout_s', 'ui_dump_timeout_s', "
            "'screenshot_timeout_s'; global fallback: 'command_timeout_s', default "
            "120s) -- sized for real ssh_host + first-run CoreSimulator latency. A "
            "timeout ALWAYS raises a distinct, clearly-worded error naming the command "
            "and the exceeded budget -- never surfaces as an empty/absent result.\n"
            "- CoreSimulator's own benign 'Install Started'/'Install Failed: "
            "Authorization is required to install the packages.' noise (seen on many "
            "simctl commands, harmless -- it is CoreSimulator being denied permission "
            "to install OPTIONAL components, not the command failing) never turns a "
            "successful command into an error; when present it is surfaced in a "
            "'warnings' field instead\n\n"
            "Simulator sensing:\n"
            "- screenshot: writes a PNG to disk (path, never inline), fetched via the "
            "runner's local/ssh-transparent file transfer\n"
            "- ui_dump: parsed accessibility tree (type, role, label, value, "
            "unique_id, enabled, frame_points+frame_pixels, "
            "center_points+center_pixels, scale) -- not raw JSON\n"
            "- find: nodes matching a selector, resolved centers in both units\n"
            "- logs: bounded `simctl spawn log stream` capture (no built-in duration "
            "limit upstream, so this tool always caps it and treats the timeout as "
            "normal termination, not failure)\n\n"
            "Simulator interacting -- selector-first:\n"
            "- tap: dump -> resolve selector -> tap via axe's VERIFIED "
            "'--label' resolution (using the resolved node's own label) -> re-dump -> "
            "report. Refuses if the resolved node has no label rather than guessing a "
            "coordinate. Reports the coordinate axe actually resolved and tapped -- "
            "'tapped_at_points'/'tapped_at_pixels' (parsed from axe's own tap-"
            "confirmation output, never a bare guess), plus 'before' (the resolved "
            "node's own label/type/frame_points/frame_pixels, i.e. WHAT was tapped, "
            "not just where). A null in tapped_at_points/pixels is never silent -- "
            "'tap_point_note' explains exactly why (axe's confirmation didn't parse, "
            "vs. the point parsed fine but pixel scale is unavailable). "
            "'total_node_count_before'/'total_node_count_after' count the SAME "
            "population as ui_dump's 'total_node_count' (every node, not the "
            "labelled/valued-only population behind ui_dump's 'node_count') -- named "
            "explicitly so the two never look like the same number under a "
            "same-sounding name.\n"
            "- tap_xy: RAW point coordinates via an INFERRED axe coordinate-tap flag "
            "(not independently verified) -- always warns\n"
            "- type_text: tap to focus -> INFERRED 'axe type' -> re-dump. Cannot "
            "assert focus was gained (iOS accessibility JSON here carries no 'focused' "
            "attribute) -- always warns. Also reports 'tapped_at_points'/"
            "'tapped_at_pixels'/'tap_point_note' for the tap-to-focus step (same "
            "protocol as 'tap' above), and an explicit 'value_after_note' (never a "
            "silent null) when the selector could no longer be re-resolved after "
            "typing to read back 'value_after'.\n"
            "- key, swipe: INFERRED axe argv shapes, not independently verified\n"
            "- wait_for: polls ui_dump until a selector appears/disappears, or "
            "timeout -- no bare sleeps\n\n"
            "Device tier (read-only sensing; free, no Apple Developer account):\n"
            "- device_info: ProductVersion/ProductType/DeviceName/CPUArchitecture + "
            "DeveloperModeStatus, asked of the DEVICE (pymobiledevice3-preferred over "
            "a local-only check -- see design doc's 'tool error vs device error')\n"
            "- device_screenshot: requires the Developer Disk Image mounted first "
            "(see device_mount_ddi)\n"
            "- device_apps: INFERRED pymobiledevice3 'apps list'\n"
            "- device_elements: VERIFIED pymobiledevice3 accessibility list-items -- "
            "NO GEOMETRY (caption/estimated_uid/platform_identifier/spoken_description "
            "only)\n"
            "- device_enable_devmode: if blocked by a set passcode (undocumented "
            "Apple behaviour), the error names the temporary-disable-then-restore "
            "guidance in the SAME message -- never a bare 'turn off your passcode'\n"
            "- device_mount_ddi: selects the nearest DDI version at or below the "
            "device's iOS version (never assumes the newest Xcode-shipped DDI is "
            "right -- newer Xcode may ship none for this device at all)\n\n"
            "tap/tap_xy on backend='device' ALWAYS refuse -- see device_elements' "
            "'no geometry' limitation above.\n\n"
            'Selector: {"label": "General"} | {"label_contains": "Gener"} | '
            '{"value": "On"} | {"role": "..."} | {"type": "..."} | '
            '{"unique_id": "..."}, optional "index" to disambiguate. Multiple keys AND '
            "together. An ambiguous match (>1 node, no index) is an error listing "
            "candidates."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": list(_OPERATIONS),
                    "description": "Operation to perform",
                },
                "backend": {
                    "type": "string",
                    "enum": ["simulator", "device"],
                    "default": "simulator",
                    "description": (
                        "Target backend. 'simulator' (default) drives a booted "
                        "Simulator via simctl/axe. 'device' targets a physical device "
                        "read-only via libimobiledevice/pymobiledevice3 -- passing "
                        "'device' to a simulator-only op (tap, ui_dump, etc.) is an "
                        "error, not silently ignored."
                    ),
                },
                "udid": {
                    "type": "string",
                    "description": (
                        "Simulator or device UDID. If omitted, auto-resolved: the "
                        "single booted simulator / single attached device, or errors "
                        "if zero/ambiguous."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "New simulator name (create_sim)",
                },
                "device_type": {
                    "type": "string",
                    "description": (
                        "create_sim: a friendly simctl device type name (e.g. "
                        "'iPhone 17 Pro') OR a full identifier (e.g. "
                        "'com.apple.CoreSimulator.SimDeviceType.iPhone-16'). Optional -- "
                        "defaults to a recent, available iPhone discovered from "
                        "`simctl list devicetypes`. An unrecognised friendly name errors "
                        "listing what IS available; it is never silently substituted."
                    ),
                },
                "runtime": {
                    "type": "string",
                    "description": (
                        "create_sim: a friendly simctl runtime name (e.g. 'iOS 26.5') OR "
                        "a full identifier (e.g. "
                        "'com.apple.CoreSimulator.SimRuntime.iOS-26-5'). Optional -- "
                        "defaults to the newest available runtime discovered from "
                        "`simctl list runtimes`. An unrecognised friendly name errors "
                        "listing what IS available; it is never silently substituted."
                    ),
                },
                "devicetype_id": {
                    "type": "string",
                    "description": (
                        "Legacy alias for 'device_type' accepting only a full simctl "
                        "device type identifier (create_sim). Prefer 'device_type'."
                    ),
                },
                "runtime_id": {
                    "type": "string",
                    "description": (
                        "Legacy alias for 'runtime' accepting only a full simctl runtime "
                        "identifier (create_sim). Prefer 'runtime'."
                    ),
                },
                "app_path": {
                    "type": "string",
                    "description": "Path to a .app bundle (install)",
                },
                "bundle_id": {
                    "type": "string",
                    "description": "App bundle identifier (launch, terminate)",
                },
                "selector": {
                    "type": "object",
                    "description": (
                        "Selector dict: label, label_contains, value, role, type, "
                        "unique_id, optional index to disambiguate"
                    ),
                },
                "text": {"type": "string", "description": "Text to type (type_text)"},
                "x": {
                    "type": "number",
                    "description": "Raw X coordinate in POINTS (tap_xy)",
                },
                "y": {
                    "type": "number",
                    "description": "Raw Y coordinate in POINTS (tap_xy)",
                },
                "x1": {"type": "number", "description": "Swipe start X (points)"},
                "y1": {"type": "number", "description": "Swipe start Y (points)"},
                "x2": {"type": "number", "description": "Swipe end X (points)"},
                "y2": {"type": "number", "description": "Swipe end Y (points)"},
                "duration_ms": {
                    "type": "integer",
                    "default": 300,
                    "description": "Swipe duration in milliseconds",
                },
                "keycode": {"type": "integer", "description": "Keycode to send (key)"},
                "timeout_s": {
                    "type": "number",
                    "default": 10.0,
                    "description": "Timeout in seconds (wait_for)",
                },
                "poll_s": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Poll interval in seconds (wait_for)",
                },
                "absent": {
                    "type": "boolean",
                    "default": False,
                    "description": "wait_for succeeds when the selector disappears, not appears",
                },
                "all_nodes": {
                    "type": "boolean",
                    "default": False,
                    "description": "ui_dump: include all nodes, not just those with a label/value",
                },
                "predicate": {
                    "type": "string",
                    "description": "logs: NSPredicate filter string for `log stream --predicate`",
                },
                "duration_s": {
                    "type": "number",
                    "default": 5.0,
                    "description": (
                        "logs: how long to capture the log stream. `log stream` has no "
                        "built-in duration limit -- this tool always bounds it and "
                        "treats the timeout as normal termination, not failure."
                    ),
                },
            },
            "required": ["operation"],
        }

    async def execute(self, input: dict[str, Any]) -> dict[str, Any]:
        operation = input.get("operation")
        if not operation:
            return _err("Missing required parameter: operation")
        if operation not in _OPERATIONS:
            return _err(
                f"Unknown operation: {operation!r}. Valid: {sorted(_OPERATIONS)}"
            )

        backend = input.get("backend", "simulator")
        if operation in _SIMULATOR_ONLY_OPS and backend != "simulator":
            return _err(
                f"Operation {operation!r} only supports backend='simulator' "
                f"(got {backend!r}). Device-tier equivalents use separate 'device_*' "
                "operation names.",
                operation=operation,
                backend=backend,
            )

        state = self._get_state()
        handler = getattr(self, f"_{operation}", None)
        if handler is None:
            return _err(f"Operation {operation!r} has no handler implemented.")

        try:
            return handler(state, input)
        except SelectorError as exc:
            return _err(str(exc), candidates=[n.to_dict() for n in exc.candidates])
        except (SimctlError, DeviceError, RunnerError) as exc:
            return _err(str(exc), **getattr(exc, "extra", {}))
        except (UiDumpError, UiInteractionError) as exc:
            return _err(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _err(f"Operation {operation!r} failed: {exc}")

    # -- Helpers ----------------------------------------------------------

    def _resolve_sim_udid(self, state: IosInspectorState, inp: dict[str, Any]) -> str:
        explicit = inp.get("udid")
        if explicit:
            return str(explicit)
        default_udid = state.config.get("default_udid")
        if default_udid:
            return str(default_udid)

        sims = _simctl.list_simulators(state.cmd_runner)
        booted = [s for s in sims if s.get("state") == "Booted"]
        if len(booted) > 1:
            detail = ", ".join(f"{s.get('name')} ({s['udid']})" for s in booted)
            raise SimctlError(
                f"Ambiguous: {len(booted)} booted simulators with no explicit 'udid': "
                f"{detail}. Pass 'udid' to disambiguate."
            )
        if booted:
            return str(booted[0]["udid"])
        raise SimctlError(
            "No booted simulator and no explicit 'udid'. Boot one first ('boot'), or "
            "pass 'udid' directly."
        )

    def _resolve_device_udid(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> str:
        explicit = inp.get("udid")
        if explicit:
            return str(explicit)
        default_udid = state.config.get("default_device_udid")
        if default_udid:
            return str(default_udid)

        devices = _device.list_physical_devices(state.cmd_runner)
        if len(devices) > 1:
            detail = ", ".join(d["udid"] for d in devices)
            raise DeviceError(
                f"Ambiguous: {len(devices)} physical devices attached with no explicit "
                f"'udid': {detail}. Pass 'udid' to disambiguate."
            )
        if devices:
            return str(devices[0]["udid"])
        raise DeviceError("No physical device attached and no explicit 'udid'.")

    def _remote_tmp_png(self, prefix: str, udid: str) -> str:
        import secrets

        return f"/tmp/ios_inspector_{prefix}_{udid}_{secrets.token_hex(4)}.png"

    # -- Environment --------------------------------------------------------

    def _doctor(self, state: IosInspectorState, inp: dict[str, Any]) -> dict[str, Any]:
        # run_doctor() never raises and never stops at the first failure.
        # `success` is always true here: a machine with problems is a
        # successful diagnosis, not a tool error.
        report = _doctor.run_doctor(state.config)
        return _ok(report)

    def _list_targets(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> dict[str, Any]:
        runner = state.cmd_runner
        sims = _simctl.list_simulators(runner)
        device_list_warning = None
        try:
            devices = _device.list_physical_devices(runner)
        except DeviceError as exc:
            devices = []
            device_list_warning = str(exc)

        all_targets = [*sims, *devices]
        explicit_udid = inp.get("udid")
        if explicit_udid:
            matches = [t for t in all_targets if t.get("udid") == explicit_udid]
            return _ok({"targets": matches, "count": len(matches)})

        ready = [
            t
            for t in all_targets
            if t.get("state") == "Booted" or t.get("backend") == "device"
        ]
        if len(ready) > 1:
            detail = ", ".join(
                f"{t.get('name') or t['udid']} ({t['udid']})" for t in ready
            )
            return _err(
                f"Ambiguous: {len(ready)} ready targets with no explicit 'udid': "
                f"{detail}. Pass 'udid' to disambiguate.",
                targets=all_targets,
            )

        result: dict[str, Any] = {"targets": all_targets, "count": len(all_targets)}
        if device_list_warning:
            result["device_list_warning"] = device_list_warning
        return _ok(result)

    # -- Simulator lifecycle ------------------------------------------------

    def _create_sim(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> dict[str, Any]:
        name = inp.get("name")
        if not name:
            return _err("Missing required parameter: name")
        # 'device_type'/'runtime' are the documented, ergonomic parameter
        # names (friendly name OR full identifier OR omitted for a
        # sensible default -- see simctl.resolve_devicetype/resolve_runtime).
        # 'devicetype_id'/'runtime_id' are accepted as legacy aliases for a
        # full identifier, for backward compatibility.
        device_type = inp.get("device_type") or inp.get("devicetype_id")
        runtime = inp.get("runtime") or inp.get("runtime_id")
        result = _simctl.create_sim(
            state.cmd_runner,
            name=str(name),
            device_type=str(device_type) if device_type else None,
            runtime=str(runtime) if runtime else None,
            timeout=state.op_timeout(
                "create_sim", _simctl.DEFAULT_CREATE_SIM_TIMEOUT_S
            ),
        )
        return _ok(result)

    def _boot(self, state: IosInspectorState, inp: dict[str, Any]) -> dict[str, Any]:
        udid = self._resolve_sim_udid(state, inp)
        result = _simctl.boot(
            state.cmd_runner,
            udid,
            timeout=state.op_timeout("boot", _simctl.DEFAULT_BOOT_TIMEOUT_S),
        )
        return _ok(result)

    def _shutdown(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> dict[str, Any]:
        udid = self._resolve_sim_udid(state, inp)
        result = _simctl.shutdown(state.cmd_runner, udid)
        return _ok(result)

    def _install(self, state: IosInspectorState, inp: dict[str, Any]) -> dict[str, Any]:
        app_path = inp.get("app_path")
        if not app_path:
            return _err("Missing required parameter: app_path")
        udid = self._resolve_sim_udid(state, inp)
        result = _simctl.install(
            state.cmd_runner,
            udid,
            str(app_path),
            timeout=state.op_timeout("install", _simctl.DEFAULT_INSTALL_TIMEOUT_S),
        )
        return _ok(result)

    def _launch(self, state: IosInspectorState, inp: dict[str, Any]) -> dict[str, Any]:
        bundle_id = inp.get("bundle_id")
        if not bundle_id:
            return _err("Missing required parameter: bundle_id")
        udid = self._resolve_sim_udid(state, inp)
        result = _simctl.launch(
            state.cmd_runner,
            udid,
            str(bundle_id),
            timeout=state.op_timeout("launch", _simctl.DEFAULT_LAUNCH_TIMEOUT_S),
        )
        return _ok(result)

    def _terminate(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> dict[str, Any]:
        bundle_id = inp.get("bundle_id")
        if not bundle_id:
            return _err("Missing required parameter: bundle_id")
        udid = self._resolve_sim_udid(state, inp)
        result = _simctl.terminate(state.cmd_runner, udid, str(bundle_id))
        return _ok(result)

    # -- Simulator sensing ----------------------------------------------------

    def _screenshot(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> dict[str, Any]:
        udid = self._resolve_sim_udid(state, inp)
        out_dir = state.base_dir / udid
        out_dir.mkdir(parents=True, exist_ok=True)
        idx = state.next_screenshot_index(udid)
        local_path = unique_evidence_path(out_dir, "screenshot", "png", index=idx)
        remote_tmp = self._remote_tmp_png("screenshot", udid)
        result = _simctl.screenshot(
            state.cmd_runner,
            udid,
            local_path,
            remote_tmp=remote_tmp,
            timeout=state.op_timeout(
                "screenshot", _simctl.DEFAULT_SCREENSHOT_TIMEOUT_S
            ),
        )
        return _ok(result)

    def _scale_unavailable_warning(self, state: IosInspectorState, udid: str) -> str:
        reason = state.scale_unavailable_reason(udid)
        return (
            "points<->pixels scale could not be established confidently for this "
            f"simulator ({reason or 'unknown reason'}) -- frame_pixels/center_pixels are "
            "omitted on every node below; only frame_points/center_points are populated. "
            "Do not guess a scale to convert them yourself."
        )

    def _ui_dump(self, state: IosInspectorState, inp: dict[str, Any]) -> dict[str, Any]:
        from .axe import describe_ui

        udid = self._resolve_sim_udid(state, inp)
        scale = state.get_scale(udid)
        ui_timeout = state.op_timeout("ui_dump", _axe.DEFAULT_UI_DUMP_TIMEOUT_S)
        nodes = describe_ui(state.cmd_runner, udid, scale=scale, timeout=ui_timeout)
        all_nodes = bool(inp.get("all_nodes", False))
        filtered = nodes if all_nodes else [n for n in nodes if n.has_content()]
        result: dict[str, Any] = {
            "udid": udid,
            "scale": scale,
            "nodes": [n.to_dict() for n in filtered],
            "node_count": len(filtered),
            "total_node_count": len(nodes),
        }
        if scale is None:
            result["warnings"] = [self._scale_unavailable_warning(state, udid)]
        return _ok(result)

    def _find(self, state: IosInspectorState, inp: dict[str, Any]) -> dict[str, Any]:
        from .axe import describe_ui, find_nodes

        selector = inp.get("selector")
        if not selector:
            return _err("Missing required parameter: selector")
        udid = self._resolve_sim_udid(state, inp)
        scale = state.get_scale(udid)
        ui_timeout = state.op_timeout("ui_dump", _axe.DEFAULT_UI_DUMP_TIMEOUT_S)
        nodes = describe_ui(state.cmd_runner, udid, scale=scale, timeout=ui_timeout)
        matches = find_nodes(nodes, selector)
        result: dict[str, Any] = {
            "udid": udid,
            "selector": selector,
            "matches": [n.to_dict() for n in matches],
            "count": len(matches),
        }
        if scale is None:
            result["warnings"] = [self._scale_unavailable_warning(state, udid)]
        return _ok(result)

    def _logs(self, state: IosInspectorState, inp: dict[str, Any]) -> dict[str, Any]:
        udid = self._resolve_sim_udid(state, inp)
        result = _simctl.log_stream(
            state.cmd_runner,
            udid,
            predicate=inp.get("predicate"),
            duration_s=float(
                inp.get("duration_s", _simctl.DEFAULT_LOG_STREAM_DURATION_S)
            ),
        )
        return _ok(result)

    # -- Simulator interacting ------------------------------------------------

    def _tap(self, state: IosInspectorState, inp: dict[str, Any]) -> dict[str, Any]:
        if inp.get("backend", "simulator") == "device":
            return _err(_DEFAULT_TAP_REFUSAL, backend="device")
        selector = inp.get("selector")
        if not selector:
            return _err("Missing required parameter: selector")
        udid = self._resolve_sim_udid(state, inp)
        scale = state.get_scale(udid)
        ui_timeout = state.op_timeout("ui_dump", _axe.DEFAULT_UI_DUMP_TIMEOUT_S)
        result = _tap_selector_impl(
            state.cmd_runner, udid, selector, scale=scale, timeout=ui_timeout
        )
        result["udid"] = udid
        return _ok(result)

    def _tap_xy(self, state: IosInspectorState, inp: dict[str, Any]) -> dict[str, Any]:
        if inp.get("backend", "simulator") == "device":
            return _err(_DEFAULT_TAP_REFUSAL, backend="device")
        if "x" not in inp or "y" not in inp:
            return _err("Missing required parameters: x, y")
        udid = self._resolve_sim_udid(state, inp)
        result = _tap_xy_impl(state.cmd_runner, udid, float(inp["x"]), float(inp["y"]))
        result["udid"] = udid
        return _ok(result)

    def _type_text(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> dict[str, Any]:
        selector = inp.get("selector")
        text = inp.get("text")
        if not selector:
            return _err("Missing required parameter: selector")
        if text is None:
            return _err("Missing required parameter: text")
        udid = self._resolve_sim_udid(state, inp)
        scale = state.get_scale(udid)
        ui_timeout = state.op_timeout("ui_dump", _axe.DEFAULT_UI_DUMP_TIMEOUT_S)
        result = _type_text_impl(
            state.cmd_runner, udid, selector, str(text), scale=scale, timeout=ui_timeout
        )
        result["udid"] = udid
        return _ok(result)

    def _key(self, state: IosInspectorState, inp: dict[str, Any]) -> dict[str, Any]:
        keycode = inp.get("keycode")
        if keycode is None:
            return _err("Missing required parameter: keycode")
        udid = self._resolve_sim_udid(state, inp)
        result = _key_press_impl(state.cmd_runner, udid, int(keycode))
        result["udid"] = udid
        return _ok(result)

    def _swipe(self, state: IosInspectorState, inp: dict[str, Any]) -> dict[str, Any]:
        required = ("x1", "y1", "x2", "y2")
        missing = [k for k in required if k not in inp]
        if missing:
            return _err(f"Missing required parameters: {', '.join(missing)}")
        udid = self._resolve_sim_udid(state, inp)
        duration_ms = int(inp.get("duration_ms", 300))
        result = _swipe_impl(
            state.cmd_runner,
            udid,
            float(inp["x1"]),
            float(inp["y1"]),
            float(inp["x2"]),
            float(inp["y2"]),
            duration_ms,
        )
        result["udid"] = udid
        return _ok(result)

    def _wait_for(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> dict[str, Any]:
        selector = inp.get("selector")
        if not selector:
            return _err("Missing required parameter: selector")
        udid = self._resolve_sim_udid(state, inp)
        scale = state.get_scale(udid)
        ui_timeout = state.op_timeout("ui_dump", _axe.DEFAULT_UI_DUMP_TIMEOUT_S)
        result = _wait_for_impl(
            state.cmd_runner,
            udid,
            selector,
            scale=scale,
            timeout_s=float(inp.get("timeout_s", 10.0)),
            poll_s=float(inp.get("poll_s", 1.0)),
            absent=bool(inp.get("absent", False)),
            command_timeout=ui_timeout,
        )
        result["udid"] = udid
        return _ok(result)

    # -- Device tier ----------------------------------------------------------

    def _device_info(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> dict[str, Any]:
        udid = self._resolve_device_udid(state, inp)
        result = _device.device_info(state.cmd_runner, udid)
        return _ok(result)

    def _device_screenshot(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> dict[str, Any]:
        udid = self._resolve_device_udid(state, inp)
        out_dir = state.base_dir / udid
        out_dir.mkdir(parents=True, exist_ok=True)
        idx = state.next_screenshot_index(udid)
        local_path = unique_evidence_path(
            out_dir, "device_screenshot", "png", index=idx
        )
        remote_tmp = self._remote_tmp_png("device_screenshot", udid)
        result = _device.device_screenshot(
            state.cmd_runner, udid, local_path, remote_tmp=remote_tmp
        )
        return _ok(result)

    def _device_apps(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> dict[str, Any]:
        udid = self._resolve_device_udid(state, inp)
        result = _device.device_apps(state.cmd_runner, state.pymobiledevice3_path, udid)
        return _ok(result)

    def _device_elements(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> dict[str, Any]:
        udid = self._resolve_device_udid(state, inp)
        result = _device.device_elements(
            state.cmd_runner, state.pymobiledevice3_path, udid
        )
        return _ok(result)

    def _device_enable_devmode(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> dict[str, Any]:
        udid = self._resolve_device_udid(state, inp)
        result = _device.device_enable_devmode(
            state.cmd_runner, state.pymobiledevice3_path, udid
        )
        return _ok(result)

    def _device_mount_ddi(
        self, state: IosInspectorState, inp: dict[str, Any]
    ) -> dict[str, Any]:
        udid = self._resolve_device_udid(state, inp)
        result = _device.device_mount_ddi(
            state.cmd_runner, udid, developer_dir=state.developer_dir
        )
        return _ok(result)


# ---------------------------------------------------------------------------
# Amplifier module mount point
# ---------------------------------------------------------------------------


async def mount(
    coordinator: Any, config: dict[str, Any] | None = None
) -> IosInspectorTool:
    """Mount the ios_inspector tool onto the Amplifier coordinator.

    Args:
        coordinator: Amplifier coordinator for tool registration
        config: Configuration from behaviors/ios-tester.yaml. Keys:
            work_dir: Base directory for screenshots (default: ~/.amplifier/ios-sessions)
            ssh_host: If set, EVERY command this tool issues runs on this remote Mac
                over `ssh -o BatchMode=yes` instead of locally (see runner.py).
            developer_dir: Override for DEVELOPER_DIR (default:
                /Applications/Xcode.app/Contents/Developer)
            command_timeout_s: Generic per-command timeout (default: 120.0 -- see
                runner.DEFAULT_TIMEOUT_S). Raising this also raises the floor for
                every per-operation budget below that doesn't have its own override.
            boot_timeout_s: Timeout override for 'boot' (built-in default: 120.0)
            create_sim_timeout_s: Timeout override for 'create_sim' (built-in
                default: 180.0)
            install_timeout_s: Timeout override for 'install' (built-in default: 180.0)
            launch_timeout_s: Timeout override for 'launch' (built-in default: 120.0)
            ui_dump_timeout_s: Timeout override for every axe describe-ui-driven
                operation (ui_dump, find, tap, type_text, wait_for, and the internal
                scale-measurement probe) (built-in default: 120.0)
            screenshot_timeout_s: Timeout override for 'screenshot' (built-in
                default: 120.0)
            default_udid: Simulator UDID to use when none is given and >1 is booted
            default_device_udid: Device UDID to use when none is given and >1 is attached
            pymobiledevice3_path: Explicit pymobiledevice3 binary override

    Each `mount()` call builds its OWN tool instance and config -- a second
    `mount()` in the same process, e.g. with a different `work_dir`, is
    fully independent and never silently shares or overwrites the first
    mount's state.

    Returns:
        The mounted tool instance.
    """
    tool = IosInspectorTool(config=config or {})
    await coordinator.mount("tools", tool, name=tool.name)
    return tool

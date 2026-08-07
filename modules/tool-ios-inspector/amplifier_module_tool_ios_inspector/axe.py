"""Simulator UI sensing/interaction via `axe` (cameroncooke/axe).

The load-bearing constraint this module encodes: **the accessibility tree
(`axe describe-ui`) is the sensor, the screenshot is for judgment, never for
targeting.** Measured on this platform: a VLM reading a screenshot placed a
tap center 130px away (vertically) from the truth returned by
`axe describe-ui` -- landing on the row *above* the intended target and
failing silently. Every coordinate this module hands back comes from the
parsed accessibility tree.

The second, iOS-specific trap this module exists to close: **the
accessibility tree reports points; screenshots report pixels.**

    tree:       393 x 852   (points)
    screenshot: 1179 x 2556 (pixels)
    scale:      3.0

Mixing them is a silent 3x coordinate error. `ui_dump` (see
`amplifier_module_tool_ios_inspector.simctl`) returns `frame_points`/
`center_points` and, when the scale factor could be established
CONFIDENTLY (see `simctl.measure_scale`), also `frame_pixels`/
`center_pixels`, explicitly labeled, plus the `scale` factor used to derive
one from the other -- never a bare, unit-ambiguous number. If scale cannot
be established confidently, `scale` is `None` and the pixel fields are
likewise `None` -- an honest "unavailable", never a guessed conversion.

Command provenance -- read this before trusting a code path blindly:

- `describe-ui` and `tap --label` are VERIFIED: both were run against a real
  booted simulator and their exact output shape (nested JSON with `AXFrame`
  strings; `"\u2713 Tap at resolved tap point at (x, y)"`) is what the parsers
  below expect.
- `tap` by raw coordinate, `key`, `swipe`, and `type` are INFERRED: `axe`
  (idb-derived) is expected to expose coordinate/keycode/gesture/text
  primitives following the same `--udid`-scoped flag convention as the
  verified `--label` form, but that exact flag shape was not independently
  captured in this design pass. Each such argv builder says so in its own
  docstring. Treat their argv shape as the best-effort, convention-consistent
  guess it is -- not a second verified fact.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from .runner import CommandRunner

__all__ = [
    "DEFAULT_UI_DUMP_TIMEOUT_S",
    "SETTLE_AFTER_TAP_S",
    "AxNode",
    "SelectorError",
    "UiDumpError",
    "UiInteractionError",
    "axe_describe_ui_argv",
    "axe_key_argv",
    "axe_swipe_argv",
    "axe_tap_label_argv",
    "axe_tap_xy_argv",
    "axe_type_text_argv",
    "bounding_box_points",
    "build_flat_nodes",
    "center_points",
    "describe_ui",
    "describe_ui_payload",
    "find_nodes",
    "flatten_tree",
    "key_press",
    "parse_axframe",
    "parse_describe_ui_json",
    "parse_tap_resolved_point",
    "point_to_pixels",
    "points_to_pixels",
    "resolve_selector",
    "swipe",
    "tap_selector",
    "tap_xy",
    "type_text",
    "wait_for",
]

SETTLE_AFTER_TAP_S = 0.3

# Built-in floor for any operation that triggers `axe describe-ui` (ui_dump,
# find, tap, type_text, wait_for, and the scale-measurement probe) -- see
# runner.py's DEFAULT_TIMEOUT_S docstring for the measured ssh_host +
# first-run CoreSimulator latency this addresses.
DEFAULT_UI_DUMP_TIMEOUT_S = 120.0

_AXFRAME_RE = re.compile(
    r"\{\{\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\}\s*,"
    r"\s*\{\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\}\s*\}"
)

_TAP_RESOLVED_RE = re.compile(
    r"resolved tap point at \(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)"
)


class UiDumpError(RuntimeError):
    """Raised when `axe describe-ui` output cannot be obtained or parsed."""


class SelectorError(RuntimeError):
    """Raised when a selector matches zero, or more than one, node ambiguously.

    Ambiguous and absent matches are *always* errors -- never a silent
    first-match. `candidates` carries whatever nodes DID match (for the
    ambiguous case) so the caller can see exactly what needs disambiguating.
    """

    def __init__(self, message: str, candidates: list[AxNode] | None = None) -> None:
        super().__init__(message)
        self.candidates: list[AxNode] = candidates or []


class UiInteractionError(RuntimeError):
    """Raised when an interaction cannot be safely carried out (no usable
    frame/label on the resolved node, focus not confirmed, etc.)."""


# ---------------------------------------------------------------------------
# AXFrame parsing + points<->pixels
# ---------------------------------------------------------------------------


def parse_axframe(frame_str: str | None) -> tuple[float, float, float, float] | None:
    """Parse an `AXFrame` string of the form `"{{x, y}, {w, h}}"` (points)
    into `(x, y, w, h)` floats. Returns `None` for missing/unparseable input
    -- a node with no frame (offscreen, some container types) is a valid
    state, not an error."""
    if not frame_str:
        return None
    m = _AXFRAME_RE.search(frame_str.strip())
    if not m:
        return None
    x, y, w, h = (float(g) for g in m.groups())
    return (x, y, w, h)


def center_points(frame: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, w, h = frame
    return (x + w / 2.0, y + h / 2.0)


def points_to_pixels(
    frame_points: tuple[float, float, float, float], scale: float
) -> tuple[float, float, float, float]:
    """Convert a points-space frame to pixels at the given `scale` (e.g. 2.0
    or 3.0). This is the ONLY place this frame conversion happens -- callers
    never multiply by scale themselves. (For a bare (x, y) point rather than
    a full (x, y, w, h) frame, see `point_to_pixels`.)"""
    x, y, w, h = frame_points
    return (x * scale, y * scale, w * scale, h * scale)


def point_to_pixels(point: tuple[float, float], scale: float) -> tuple[float, float]:
    """Convert a points-space (x, y) point to pixels at the given `scale`.
    The bare-point sibling of `points_to_pixels` -- this is the ONLY place a
    single point (as opposed to a full frame) is scaled; callers never
    multiply by scale themselves. Used for `AxNode.center_pixels` and for the
    tap-confirmation point axe reports back (see `_tap_evidence`)."""
    x, y = point
    return (x * scale, y * scale)


# ---------------------------------------------------------------------------
# Node model + tree flattening
# ---------------------------------------------------------------------------


@dataclass
class AxNode:
    node_type: str
    role: str
    label: str
    value: str
    unique_id: str
    enabled: bool
    frame_points: tuple[float, float, float, float] | None
    # `None` means the points<->pixels scale factor could not be
    # established confidently for this simulator (see
    # `amplifier_module_tool_ios_inspector.simctl.measure_scale`) -- an
    # explicit, honest "unknown", never a value to guess at. When `None`,
    # `frame_pixels`/`center_pixels` are likewise `None` rather than a
    # silently-wrong coordinate computed from a bad scale.
    scale: float | None
    dump_index: int = -1
    children: list[AxNode] = field(default_factory=list, repr=False)

    @property
    def center_points(self) -> tuple[float, float] | None:
        if not self.frame_points:
            return None
        return center_points(self.frame_points)

    @property
    def frame_pixels(self) -> tuple[float, float, float, float] | None:
        if not self.frame_points or self.scale is None:
            return None
        return points_to_pixels(self.frame_points, self.scale)

    @property
    def center_pixels(self) -> tuple[float, float] | None:
        cp = self.center_points
        if cp is None or self.scale is None:
            return None
        return point_to_pixels(cp, self.scale)

    def has_content(self) -> bool:
        return bool(self.label or self.value or self.unique_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.node_type,
            "role": self.role,
            "label": self.label,
            "value": self.value,
            "unique_id": self.unique_id,
            "enabled": self.enabled,
            "frame_points": list(self.frame_points) if self.frame_points else None,
            "frame_pixels": (
                [round(v, 2) for v in self.frame_pixels] if self.frame_pixels else None
            ),
            "center_points": (
                [round(v, 2) for v in self.center_points]
                if self.center_points
                else None
            ),
            "center_pixels": (
                [round(v, 2) for v in self.center_pixels]
                if self.center_pixels
                else None
            ),
            "scale": self.scale,
        }


def _node_from_json(
    raw: dict[str, Any], scale: float | None, index_box: list[int]
) -> AxNode:
    idx = index_box[0]
    index_box[0] += 1
    node = AxNode(
        node_type=str(raw.get("type", "")),
        role=str(raw.get("role", "")),
        label=str(raw.get("AXLabel") or ""),
        value=str(raw.get("AXValue") or ""),
        unique_id=str(raw.get("AXUniqueId") or ""),
        enabled=bool(raw.get("enabled", True)),
        frame_points=parse_axframe(raw.get("AXFrame")),
        scale=scale,
        dump_index=idx,
    )
    for child_raw in raw.get("children") or []:
        node.children.append(_node_from_json(child_raw, scale, index_box))
    return node


def parse_describe_ui_json(payload: Any, *, scale: float | None) -> AxNode:
    """Parse the JSON produced by `axe describe-ui --udid <UDID>` into an
    `AxNode` tree. `payload` may be the already-decoded JSON (a dict, or a
    single-element list containing one), matching the two shapes `axe` has
    been observed to emit for a single-window describe-ui call.

    Raises:
        UiDumpError: `payload` is empty or not a recognisable node shape.
    """
    if isinstance(payload, list):
        if not payload:
            raise UiDumpError(
                "axe describe-ui returned an empty list -- no UI to inspect."
            )
        payload = payload[0]
    if not isinstance(payload, dict):
        raise UiDumpError(
            f"axe describe-ui returned an unrecognised JSON shape: {type(payload).__name__}"
        )
    return _node_from_json(payload, scale, [0])


def flatten_tree(root: AxNode) -> list[AxNode]:
    """Flatten a node tree (depth-first) into a flat list -- the shape every
    selector/find operation in this module operates on."""
    flat: list[AxNode] = []

    def _walk(node: AxNode) -> None:
        flat.append(node)
        for child in node.children:
            _walk(child)

    _walk(root)
    return flat


# ---------------------------------------------------------------------------
# Selectors -- mirrors android_inspector's selector semantics, iOS field names
# ---------------------------------------------------------------------------

_MATCH_KEYS = ("label", "label_contains", "value", "role", "type", "unique_id")


def find_nodes(nodes: list[AxNode], selector: dict[str, Any]) -> list[AxNode]:
    """Return all nodes matching the AND-combined selector (excluding
    'index', which only disambiguates in `resolve_selector`)."""
    candidates = list(nodes)

    if "label" in selector:
        target = selector["label"]
        candidates = [n for n in candidates if n.label == target]
    if "label_contains" in selector:
        target = selector["label_contains"]
        candidates = [n for n in candidates if target in n.label]
    if "value" in selector:
        target = selector["value"]
        candidates = [n for n in candidates if n.value == target]
    if "role" in selector:
        target = selector["role"]
        candidates = [n for n in candidates if n.role == target]
    if "type" in selector:
        target = selector["type"]
        candidates = [n for n in candidates if n.node_type == target]
    if "unique_id" in selector:
        target = selector["unique_id"]
        candidates = [n for n in candidates if n.unique_id == target]

    return candidates


def resolve_selector(nodes: list[AxNode], selector: dict[str, Any]) -> AxNode:
    """Resolve a selector dict to exactly one AxNode.

    An ambiguous match (more than one candidate, no disambiguating 'index')
    is an ERROR listing candidates -- never a silent first-match. A selector
    matching zero nodes is likewise an error.
    """
    if not selector:
        raise SelectorError("Selector must not be empty.")

    if not any(k in selector for k in _MATCH_KEYS):
        raise SelectorError(
            f"Selector has no recognized match keys {_MATCH_KEYS}; got {sorted(selector.keys())}."
        )

    candidates = find_nodes(nodes, selector)

    if "index" in selector:
        idx = selector["index"]
        if not candidates:
            raise SelectorError(
                f"No nodes matched selector (before applying index={idx}): {selector}"
            )
        if not isinstance(idx, int) or idx < 0 or idx >= len(candidates):
            raise SelectorError(
                f"index={idx!r} out of range for selector {selector} -- "
                f"{len(candidates)} candidate(s) matched.",
                candidates=candidates,
            )
        return candidates[idx]

    if not candidates:
        raise SelectorError(f"No nodes matched selector: {selector}")
    if len(candidates) > 1:
        raise SelectorError(
            f"Selector {selector} matched {len(candidates)} nodes ambiguously; "
            "add 'index' to disambiguate or narrow the selector.",
            candidates=candidates,
        )
    return candidates[0]


# ---------------------------------------------------------------------------
# axe argv builders -- see module docstring for VERIFIED vs INFERRED status
# ---------------------------------------------------------------------------


def axe_describe_ui_argv(udid: str) -> list[str]:
    """VERIFIED: `axe describe-ui --udid <UDID>`."""
    return ["axe", "describe-ui", "--udid", udid]


def axe_tap_label_argv(udid: str, label: str) -> list[str]:
    """VERIFIED: `axe tap --label "<label>" --udid <UDID>` -- axe resolves
    the label to a tap point itself and reports it
    (`"\u2713 Tap at resolved tap point at (x, y)"`)."""
    return ["axe", "tap", "--label", label, "--udid", udid]


def axe_tap_xy_argv(udid: str, x: float, y: float) -> list[str]:
    """INFERRED (not independently captured in the verified-command
    transcript). Follows the same `--udid` convention as the verified
    `--label` form for a raw-coordinate (points) tap."""
    return ["axe", "tap", "-x", str(x), "-y", str(y), "--udid", udid]


def axe_key_argv(udid: str, keycode: int) -> list[str]:
    """INFERRED. Not in the verified-command transcript."""
    return ["axe", "key", str(keycode), "--udid", udid]


def axe_swipe_argv(
    udid: str, x1: float, y1: float, x2: float, y2: float, duration_ms: int
) -> list[str]:
    """INFERRED. Not in the verified-command transcript."""
    return [
        "axe",
        "swipe",
        "--start-x",
        str(x1),
        "--start-y",
        str(y1),
        "--end-x",
        str(x2),
        "--end-y",
        str(y2),
        "--duration",
        str(duration_ms),
        "--udid",
        udid,
    ]


def axe_type_text_argv(udid: str, text: str) -> list[str]:
    """INFERRED. Not in the verified-command transcript."""
    return ["axe", "type", "--text", text, "--udid", udid]


def parse_tap_resolved_point(stdout: str) -> tuple[float, float] | None:
    """Parse axe's own `"\u2713 Tap at resolved tap point at (x, y)"` confirmation
    line. Returns `None` if the expected phrasing isn't present -- callers
    treat that as "axe didn't confirm a resolved point", not a hard error,
    since the tap itself may still have succeeded."""
    m = _TAP_RESOLVED_RE.search(stdout)
    if not m:
        return None
    return (float(m.group(1)), float(m.group(2)))


def _tap_evidence(stdout: str, *, scale: float | None) -> dict[str, Any]:
    """Build the tap-coordinate evidence trio (`tapped_at_points`,
    `tapped_at_pixels`, `tap_point_note`) from axe's own tap-confirmation
    stdout -- the load-bearing fix for the defect where a successful tap
    reported `None`/`None` with nothing to explain why: a null here must
    never be indistinguishable from "wasn't tracked".

    Exactly one of three cases, always distinguished by `tap_point_note`:

    1. axe's `"resolved tap point at (x, y)"` confirmation couldn't be
       parsed from `stdout` at all -- BOTH fields are `None`, and
       `tap_point_note` says so explicitly (this is a parse failure, not
       evidence that no coordinate was used -- the tap command itself
       already succeeded by the time this is called).
    2. The point parsed fine, but the points<->pixels `scale` for this
       simulator is `None` (could not be established confidently) --
       `tapped_at_points` is populated, `tapped_at_pixels` is `None`, and
       `tap_point_note` explains it's a scale problem, not a point problem.
    3. Both parsed and scale is known -- both fields populated,
       `tap_point_note` is `None`.
    """
    resolved_point = parse_tap_resolved_point(stdout)
    if resolved_point is None:
        return {
            "tapped_at_points": None,
            "tapped_at_pixels": None,
            "tap_point_note": (
                "axe's tap confirmation output did not match the expected "
                "'resolved tap point at (x, y)' phrasing, so the coordinate axe "
                "actually used could not be captured. This is an explicit parse "
                "failure -- NOT evidence that no coordinate was used; the tap "
                "command itself already succeeded (exit 0). See 'stdout' for the "
                "raw axe output."
            ),
        }
    points_list = [round(v, 2) for v in resolved_point]
    if scale is None:
        return {
            "tapped_at_points": points_list,
            "tapped_at_pixels": None,
            "tap_point_note": (
                "tapped_at_pixels is omitted because the points<->pixels scale "
                "could not be established confidently for this simulator -- NOT "
                "because the tapped point itself is unknown (tapped_at_points is "
                "populated above)."
            ),
        }
    pixels = point_to_pixels(resolved_point, scale)
    return {
        "tapped_at_points": points_list,
        "tapped_at_pixels": [round(v, 2) for v in pixels],
        "tap_point_note": None,
    }


# ---------------------------------------------------------------------------
# Device I/O -- describe-ui dump
# ---------------------------------------------------------------------------


def describe_ui_payload(
    runner: CommandRunner, udid: str, *, timeout: float | None = None
) -> Any:
    """Run `axe describe-ui --udid <UDID>` and return the decoded JSON
    payload, scale-independent. Split out from `describe_ui` so callers that
    need to MEASURE scale (compare tree bounding box in points against a
    screenshot's pixel width) can decode the tree once and build the node
    list twice cheaply (no second `axe` invocation) -- see
    `amplifier_module_tool_ios_inspector.simctl.measure_scale`.

    `timeout`, if given, overrides the runner's default command-timeout
    budget for this call -- see `DEFAULT_UI_DUMP_TIMEOUT_S`. A TIMEOUT
    raises `runner.CommandTimeoutError` from inside `runner.run()` itself
    (the default `raise_on_timeout=True`), so it can never reach -- and be
    confused with -- the "produced no output" check below: that message is
    reserved for a command that genuinely completed with nothing to show,
    never for one that was killed mid-flight for exceeding its budget.

    Raises:
        UiDumpError: the command failed, or produced no output.
    """
    import json

    result = runner.run(axe_describe_ui_argv(udid), timeout=timeout)
    if not result.ok:
        raise UiDumpError(
            f"axe describe-ui failed on {udid!r} (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}"
        )
    if not result.stdout.strip():
        raise UiDumpError(
            f"axe describe-ui on {udid!r} produced no output -- the simulator may not "
            "be booted, or the app under test has no accessible UI yet."
        )
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise UiDumpError(f"Failed to parse axe describe-ui JSON: {exc}") from exc


def build_flat_nodes(payload: Any, *, scale: float | None) -> list[AxNode]:
    """Parse an already-decoded describe-ui payload into a flat node list at
    the given `scale`. Pure/cheap -- no I/O."""
    root = parse_describe_ui_json(payload, scale=scale)
    return flatten_tree(root)


def bounding_box_points(nodes: list[AxNode]) -> tuple[float, float] | None:
    """The (width, height) in points of the smallest box containing every
    node's frame -- used to derive the points<->pixels scale factor by
    comparing this to a screenshot's pixel dimensions. Returns `None` if no
    node in the tree carries a frame."""
    max_right = 0.0
    max_bottom = 0.0
    seen = False
    for node in nodes:
        if node.frame_points is None:
            continue
        x, y, w, h = node.frame_points
        max_right = max(max_right, x + w)
        max_bottom = max(max_bottom, y + h)
        seen = True
    if not seen:
        return None
    return (max_right, max_bottom)


def describe_ui(
    runner: CommandRunner,
    udid: str,
    *,
    scale: float | None,
    timeout: float | None = None,
) -> list[AxNode]:
    """Run `axe describe-ui --udid <UDID>` and return the flattened node
    list at the given (already-known) `scale`.

    Raises:
        UiDumpError: the command failed, or produced unparseable JSON.
    """
    payload = describe_ui_payload(runner, udid, timeout=timeout)
    return build_flat_nodes(payload, scale=scale)


# ---------------------------------------------------------------------------
# Verified interaction protocol
# ---------------------------------------------------------------------------


def tap_selector(
    runner: CommandRunner,
    udid: str,
    selector: dict[str, Any],
    *,
    scale: float | None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """dump -> resolve selector -> tap (via axe's verified `--label`
    resolution, using the RESOLVED node's own label) -> re-dump -> report
    what changed.

    Raises:
        SelectorError: selector matched zero or >1 nodes.
        UiInteractionError: the resolved node has no AXLabel -- axe's only
            VERIFIED tap path is label-based; this tool will not fall back
            to an unverified coordinate tap silently.
    """
    nodes_before = describe_ui(runner, udid, scale=scale, timeout=timeout)
    node = resolve_selector(nodes_before, selector)
    if not node.label:
        raise UiInteractionError(
            f"Resolved node for selector {selector} has no AXLabel. This tool's only "
            "VERIFIED simulator tap path is 'axe tap --label' -- it will not guess a "
            "coordinate tap for an unlabeled node. Narrow the selector to a labeled "
            "element, or use 'tap_xy' (raw coordinates, unverified axe path, always "
            "warns)."
        )

    result = runner.run(axe_tap_label_argv(udid, node.label), timeout=timeout)
    if not result.ok:
        raise UiInteractionError(
            f"axe tap --label {node.label!r} failed on {udid!r} (exit "
            f"{result.returncode}): {(result.stderr or result.stdout).strip()}"
        )
    tap_evidence = _tap_evidence(result.stdout, scale=scale)
    time.sleep(SETTLE_AFTER_TAP_S)

    nodes_after = describe_ui(runner, udid, scale=scale, timeout=timeout)

    return {
        "selector": selector,
        "tapped_label": node.label,
        **tap_evidence,
        # `before` is the resolved node's OWN to_dict() -- label, type, frame_points,
        # frame_pixels, etc. -- so the caller can see WHAT was resolved, not just
        # where the tap landed (tapped_at_points/pixels above).
        "before": node.to_dict(),
        # Counts the SAME population as ui_dump's 'total_node_count' (every node in
        # the tree, not just labelled/valued ones -- see ui_dump's 'node_count' for
        # that filtered population). Named explicitly so it is never confused with
        # a different population under a same-sounding name.
        "total_node_count_before": len(nodes_before),
        "total_node_count_after": len(nodes_after),
        "stdout": result.stdout.strip(),
    }


def tap_xy(runner: CommandRunner, udid: str, x: float, y: float) -> dict[str, Any]:
    """Raw-coordinate tap (points). Conspicuously named and always carries a
    warning -- this is NOT the safe path; `tap_selector` is. Also uses the
    INFERRED (not independently verified) `axe tap -x/-y` argv shape -- see
    module docstring."""
    result = runner.run(axe_tap_xy_argv(udid, x, y))
    if not result.ok:
        raise UiInteractionError(
            f"axe tap -x {x} -y {y} failed on {udid!r} (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}"
        )
    time.sleep(SETTLE_AFTER_TAP_S)
    return {
        "x": x,
        "y": y,
        "warning": (
            "tap_xy used raw point coordinates with no selector resolution or "
            "verification, via an axe coordinate-tap flag shape that was NOT "
            "independently verified against a live simulator (only 'axe tap --label' "
            "was). Coordinates are not validated against the current UI and may "
            "silently land on the wrong element (or nothing). Prefer 'tap' with a "
            "selector."
        ),
        "stdout": result.stdout.strip(),
    }


def wait_for(
    runner: CommandRunner,
    udid: str,
    selector: dict[str, Any],
    *,
    scale: float | None,
    timeout_s: float = 10.0,
    poll_s: float = 1.0,
    absent: bool = False,
    command_timeout: float | None = None,
) -> dict[str, Any]:
    """Poll `describe_ui` until a selector appears (default) or disappears
    (absent=True), or timeout. The ONLY synchronisation mechanism in this
    module -- no bare sleep stands in for it elsewhere.

    `command_timeout` (distinct from `timeout_s`, the overall polling
    deadline) bounds each individual `describe_ui` call within the loop --
    see `DEFAULT_UI_DUMP_TIMEOUT_S`.
    """
    start = time.monotonic()
    deadline = start + timeout_s
    match_count = 0

    while True:
        nodes = describe_ui(runner, udid, scale=scale, timeout=command_timeout)
        match_count = len(find_nodes(nodes, selector))
        condition_met = (match_count == 0) if absent else (match_count > 0)
        elapsed = time.monotonic() - start
        if condition_met:
            return {
                "met": True,
                "selector": selector,
                "absent": absent,
                "match_count": match_count,
                "elapsed_s": elapsed,
            }
        if time.monotonic() >= deadline:
            return {
                "met": False,
                "selector": selector,
                "absent": absent,
                "match_count": match_count,
                "elapsed_s": elapsed,
            }
        time.sleep(poll_s)


def type_text(
    runner: CommandRunner,
    udid: str,
    selector: dict[str, Any],
    text: str,
    *,
    scale: float | None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Resolve `selector`, tap it (via the verified `--label` path) to give
    it focus, then send `text` via the INFERRED `axe type` argv shape.

    Unlike the sibling android_inspector tool's `type_text`, this cannot
    assert focus was gained before typing: the accessibility JSON this
    module parses (`type`, `role`, `AXLabel`, `AXValue`, `AXUniqueId`,
    `enabled`) carries no focus attribute, so there is nothing to check.
    The result always carries a `warning` naming both limitations plainly
    rather than implying a verified guarantee this tool cannot back up.

    Raises:
        SelectorError: selector matched zero or >1 nodes.
        UiInteractionError: the resolved node has no AXLabel (same
            constraint as `tap_selector`), or the tap/type command failed.
    """
    nodes_before = describe_ui(runner, udid, scale=scale, timeout=timeout)
    node = resolve_selector(nodes_before, selector)
    if not node.label:
        raise UiInteractionError(
            f"Resolved node for selector {selector} has no AXLabel -- cannot focus it "
            "via the verified 'axe tap --label' path before typing."
        )

    tap_result = runner.run(axe_tap_label_argv(udid, node.label), timeout=timeout)
    if not tap_result.ok:
        raise UiInteractionError(
            f"axe tap --label {node.label!r} (to focus before typing) failed on "
            f"{udid!r}: {(tap_result.stderr or tap_result.stdout).strip()}"
        )
    # Same underlying 'axe tap --label' path as tap_selector -- carries the same
    # evidence-reporting obligation for the coordinate it resolved to focus.
    tap_evidence = _tap_evidence(tap_result.stdout, scale=scale)
    time.sleep(SETTLE_AFTER_TAP_S)

    type_result = runner.run(axe_type_text_argv(udid, text), timeout=timeout)
    if not type_result.ok:
        raise UiInteractionError(
            f"axe type --text failed on {udid!r} (exit {type_result.returncode}): "
            f"{(type_result.stderr or type_result.stdout).strip()}"
        )
    time.sleep(SETTLE_AFTER_TAP_S)

    nodes_after = describe_ui(runner, udid, scale=scale, timeout=timeout)
    after_node: AxNode | None
    try:
        after_node = resolve_selector(nodes_after, selector)
    except SelectorError:
        after_node = None

    return {
        "selector": selector,
        "tapped_label": node.label,
        **tap_evidence,
        "text_written": text,
        "value_after": after_node.value if after_node else None,
        # Explicit, not a silent null: distinguishes "value_after is None because
        # the field's actual value IS empty/None" from "value_after is None
        # because the selector could no longer be re-resolved after typing (the
        # element may have lost the property this selector matched on, or left
        # the tree entirely)" -- only present when the latter applies.
        "value_after_note": (
            None
            if after_node is not None
            else (
                f"Selector {selector} no longer matched any node after typing -- "
                "value_after is None because there was nothing to read back from, "
                "NOT because the field's value is confirmed empty. The write may "
                "still have succeeded (e.g. the UI navigated away); re-run ui_dump "
                "or find to check the current state."
            )
        ),
        "warning": (
            "iOS accessibility nodes carry no 'focused' attribute in this tool's "
            "parsed schema, so focus cannot be asserted before typing (unlike the "
            "Android tool's verified protocol). The underlying 'axe type' argv shape "
            "is INFERRED, not independently verified against a live simulator."
        ),
    }


def key_press(runner: CommandRunner, udid: str, keycode: int) -> dict[str, Any]:
    """INFERRED `axe key` argv shape -- see module docstring."""
    result = runner.run(axe_key_argv(udid, keycode))
    if not result.ok:
        raise UiInteractionError(
            f"axe key {keycode} failed on {udid!r} (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}"
        )
    time.sleep(SETTLE_AFTER_TAP_S)
    return {"keycode": keycode, "stdout": result.stdout.strip()}


def swipe(
    runner: CommandRunner,
    udid: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    duration_ms: int,
) -> dict[str, Any]:
    """INFERRED `axe swipe` argv shape -- see module docstring. Coordinates
    are POINTS (not pixels) -- gestures have no selector analogue, so this
    is always a raw-coordinate operation, unlike `tap`."""
    result = runner.run(axe_swipe_argv(udid, x1, y1, x2, y2, duration_ms))
    if not result.ok:
        raise UiInteractionError(
            f"axe swipe failed on {udid!r} (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}"
        )
    return {
        "from_points": [x1, y1],
        "to_points": [x2, y2],
        "duration_ms": duration_ms,
        "stdout": result.stdout.strip(),
    }

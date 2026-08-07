"""Tests for axe.py -- AXFrame parsing, points<->pixels conversion, selector
matching, and the tap/type/wait_for protocols. All against a FakeRunner --
no real simulator required."""

from __future__ import annotations

import json

import pytest
from amplifier_module_tool_ios_inspector.axe import (
    SelectorError,
    UiInteractionError,
    axe_describe_ui_argv,
    axe_tap_label_argv,
    bounding_box_points,
    build_flat_nodes,
    center_points,
    find_nodes,
    parse_axframe,
    parse_describe_ui_json,
    parse_tap_resolved_point,
    point_to_pixels,
    points_to_pixels,
    resolve_selector,
    tap_selector,
    tap_xy,
    type_text,
    wait_for,
)
from amplifier_module_tool_ios_inspector.runner import CommandResult, CommandRunner

from .conftest import AMBIGUOUS_DESCRIBE_UI_JSON, SAMPLE_DESCRIBE_UI_JSON, FakeRunner

UDID = "12345678-0000AAAA1234ABCD"

# ---------------------------------------------------------------------------
# AXFrame parsing
# ---------------------------------------------------------------------------


def test_parse_axframe_with_float_components() -> None:
    assert parse_axframe("{{16, 377.33}, {361, 52}}") == (16.0, 377.33, 361.0, 52.0)


def test_parse_axframe_with_integer_components() -> None:
    assert parse_axframe("{{0, 0}, {393, 852}}") == (0.0, 0.0, 393.0, 852.0)


def test_parse_axframe_with_negative_and_whitespace_variants() -> None:
    assert parse_axframe("{{ -10, 5.5 }, { 100, 200 }}") == (-10.0, 5.5, 100.0, 200.0)


def test_parse_axframe_none_input_returns_none() -> None:
    assert parse_axframe(None) is None


def test_parse_axframe_empty_string_returns_none() -> None:
    assert parse_axframe("") is None


def test_parse_axframe_unparseable_returns_none() -> None:
    assert parse_axframe("not a frame") is None


def test_center_points_computes_midpoint() -> None:
    assert center_points((16.0, 377.33, 361.0, 52.0)) == (16.0 + 180.5, 377.33 + 26.0)


# ---------------------------------------------------------------------------
# points <-> pixels conversion
# ---------------------------------------------------------------------------


def test_points_to_pixels_at_scale_3() -> None:
    assert points_to_pixels((16.0, 377.33, 361.0, 52.0), 3.0) == (
        48.0,
        1131.99,
        1083.0,
        156.0,
    )


def test_points_to_pixels_at_scale_2() -> None:
    assert points_to_pixels((10.0, 20.0, 30.0, 40.0), 2.0) == (20.0, 40.0, 60.0, 80.0)


def test_point_to_pixels_at_scale_3() -> None:
    assert point_to_pixels((196.5, 403.33333333333337), 3.0) == (589.5, 1210.0)


def test_axnode_to_dict_carries_both_units_and_scale() -> None:
    nodes = build_flat_nodes(SAMPLE_DESCRIBE_UI_JSON, scale=3.0)
    general = next(n for n in nodes if n.label == "General")
    d = general.to_dict()
    assert d["frame_points"] == [16.0, 377.33, 361.0, 52.0]
    assert d["frame_pixels"] == [48.0, 1131.99, 1083.0, 156.0]
    assert d["center_points"] is not None
    assert d["center_pixels"] is not None
    assert d["scale"] == 3.0


def test_axnode_with_scale_none_omits_pixel_fields_never_guesses() -> None:
    """DEFECT fix: when the points<->pixels scale could not be established
    confidently, `scale=None` must propagate to frame_pixels/center_pixels
    being `None` too -- NEVER a coordinate computed from a missing/guessed
    scale."""
    nodes = build_flat_nodes(SAMPLE_DESCRIBE_UI_JSON, scale=None)
    general = next(n for n in nodes if n.label == "General")
    assert general.frame_points == (16.0, 377.33, 361.0, 52.0)
    assert general.frame_pixels is None
    assert general.center_pixels is None
    assert general.center_points is not None  # points-space is unaffected
    d = general.to_dict()
    assert d["frame_pixels"] is None
    assert d["center_pixels"] is None
    assert d["scale"] is None


def test_bounding_box_points_covers_full_tree() -> None:
    nodes = build_flat_nodes(SAMPLE_DESCRIBE_UI_JSON, scale=1.0)
    bbox = bounding_box_points(nodes)
    assert bbox == (393.0, 852.0)


def test_bounding_box_points_none_when_no_frames() -> None:
    payload = {"type": "X", "role": "x", "children": []}
    nodes = build_flat_nodes(payload, scale=1.0)
    assert bounding_box_points(nodes) is None


# ---------------------------------------------------------------------------
# Tree parsing
# ---------------------------------------------------------------------------


def test_parse_describe_ui_json_flattens_nested_children() -> None:
    root = parse_describe_ui_json(SAMPLE_DESCRIBE_UI_JSON, scale=1.0)
    assert root.label == "MyApp"
    assert len(root.children) == 3


def test_parse_describe_ui_json_accepts_single_element_list() -> None:
    root = parse_describe_ui_json([SAMPLE_DESCRIBE_UI_JSON], scale=1.0)
    assert root.label == "MyApp"


def test_build_flat_nodes_count() -> None:
    nodes = build_flat_nodes(SAMPLE_DESCRIBE_UI_JSON, scale=1.0)
    # root + 3 children
    assert len(nodes) == 4


# ---------------------------------------------------------------------------
# Selector matching
# ---------------------------------------------------------------------------


def test_find_nodes_by_label() -> None:
    nodes = build_flat_nodes(SAMPLE_DESCRIBE_UI_JSON, scale=1.0)
    matches = find_nodes(nodes, {"label": "General"})
    assert len(matches) == 1
    assert matches[0].unique_id == "general-row"


def test_find_nodes_by_label_contains() -> None:
    nodes = build_flat_nodes(SAMPLE_DESCRIBE_UI_JSON, scale=1.0)
    matches = find_nodes(nodes, {"label_contains": "Gener"})
    assert len(matches) == 1


def test_find_nodes_by_value() -> None:
    nodes = build_flat_nodes(SAMPLE_DESCRIBE_UI_JSON, scale=1.0)
    matches = find_nodes(nodes, {"value": "On"})
    assert len(matches) == 1
    assert matches[0].label == "Wi-Fi"


def test_resolve_selector_unambiguous() -> None:
    nodes = build_flat_nodes(SAMPLE_DESCRIBE_UI_JSON, scale=1.0)
    node = resolve_selector(nodes, {"label": "General"})
    assert node.unique_id == "general-row"


def test_resolve_selector_no_match_raises() -> None:
    nodes = build_flat_nodes(SAMPLE_DESCRIBE_UI_JSON, scale=1.0)
    with pytest.raises(SelectorError):
        resolve_selector(nodes, {"label": "Nonexistent"})


def test_resolve_selector_ambiguous_raises_with_candidates() -> None:
    nodes = build_flat_nodes(AMBIGUOUS_DESCRIBE_UI_JSON, scale=1.0)
    with pytest.raises(SelectorError) as exc_info:
        resolve_selector(nodes, {"label": "Row"})
    assert len(exc_info.value.candidates) == 2


def test_resolve_selector_ambiguous_resolved_by_index() -> None:
    nodes = build_flat_nodes(AMBIGUOUS_DESCRIBE_UI_JSON, scale=1.0)
    node = resolve_selector(nodes, {"label": "Row", "index": 1})
    assert node.unique_id == "row-2"


def test_resolve_selector_index_out_of_range_raises() -> None:
    nodes = build_flat_nodes(AMBIGUOUS_DESCRIBE_UI_JSON, scale=1.0)
    with pytest.raises(SelectorError):
        resolve_selector(nodes, {"label": "Row", "index": 5})


def test_resolve_selector_empty_selector_raises() -> None:
    nodes = build_flat_nodes(SAMPLE_DESCRIBE_UI_JSON, scale=1.0)
    with pytest.raises(SelectorError):
        resolve_selector(nodes, {})


def test_resolve_selector_unrecognized_keys_raises() -> None:
    nodes = build_flat_nodes(SAMPLE_DESCRIBE_UI_JSON, scale=1.0)
    with pytest.raises(SelectorError):
        resolve_selector(nodes, {"bogus_key": "x"})


# ---------------------------------------------------------------------------
# axe argv builders
# ---------------------------------------------------------------------------


def test_axe_describe_ui_argv() -> None:
    assert axe_describe_ui_argv(UDID) == ["axe", "describe-ui", "--udid", UDID]


def test_axe_tap_label_argv() -> None:
    assert axe_tap_label_argv(UDID, "General") == [
        "axe",
        "tap",
        "--label",
        "General",
        "--udid",
        UDID,
    ]


def test_parse_tap_resolved_point() -> None:
    stdout = "\u2713 Tap at resolved tap point at (196.5, 403.3)"
    assert parse_tap_resolved_point(stdout) == (196.5, 403.3)


def test_parse_tap_resolved_point_missing_phrase_returns_none() -> None:
    assert parse_tap_resolved_point("some other output") is None


# ---------------------------------------------------------------------------
# tap_selector -- selector-resolved interaction protocol
# ---------------------------------------------------------------------------


def _describe_ui_result(payload: dict) -> CommandResult:
    return CommandResult(args=[], returncode=0, stdout=json.dumps(payload), stderr="")


def test_tap_selector_uses_resolved_label_and_reparses_after() -> None:
    fake = FakeRunner(
        queue=[
            _describe_ui_result(SAMPLE_DESCRIBE_UI_JSON),  # dump before
            CommandResult(
                args=[],
                returncode=0,
                stdout="\u2713 Tap at resolved tap point at (196.5, 403.3)",
                stderr="",
            ),  # the tap itself
            _describe_ui_result(SAMPLE_DESCRIBE_UI_JSON),  # re-dump after
        ]
    )
    runner = CommandRunner(_runner=fake)
    result = tap_selector(runner, UDID, {"label": "General"}, scale=3.0)

    assert result["tapped_label"] == "General"
    # DEFECT fix: the resolved tap coordinate must be reported in BOTH units,
    # parsed from axe's own confirmation output -- never null on success.
    assert result["tapped_at_points"] == [196.5, 403.3]
    assert result["tapped_at_pixels"] == [589.5, 1209.9]
    assert result["tap_point_note"] is None
    # DEFECT fix: the resolved node's own frame is present so the caller can see
    # WHAT was tapped, not just where the tap landed.
    assert result["before"]["label"] == "General"
    assert result["before"]["type"] == "StaticText"
    assert result["before"]["frame_points"] == [16.0, 377.33, 361.0, 52.0]
    assert result["before"]["frame_pixels"] == [48.0, 1131.99, 1083.0, 156.0]
    # DEFECT fix: unambiguous naming -- matches ui_dump's 'total_node_count'
    # population (every node), never confused with ui_dump's filtered
    # 'node_count' under a same-sounding name.
    assert result["total_node_count_before"] == 4
    assert result["total_node_count_after"] == 4
    # The second call must be the verified `axe tap --label` invocation.
    assert fake.calls[1] == axe_tap_label_argv(UDID, "General")


def test_tap_selector_reports_explicit_note_when_confirmation_unparseable() -> None:
    """DEFECT fix: an unparseable tap confirmation must never look like a
    silent 'wasn't tracked' null -- tap_point_note explains why."""
    fake = FakeRunner(
        queue=[
            _describe_ui_result(SAMPLE_DESCRIBE_UI_JSON),
            CommandResult(
                args=[], returncode=0, stdout="some unrelated axe output", stderr=""
            ),
            _describe_ui_result(SAMPLE_DESCRIBE_UI_JSON),
        ]
    )
    runner = CommandRunner(_runner=fake)
    result = tap_selector(runner, UDID, {"label": "General"}, scale=3.0)

    assert result["tapped_at_points"] is None
    assert result["tapped_at_pixels"] is None
    assert result["tap_point_note"] is not None
    assert "parse failure" in result["tap_point_note"]
    assert "NOT evidence that no coordinate was used" in result["tap_point_note"]


def test_tap_selector_reports_explicit_note_when_scale_unavailable() -> None:
    """DEFECT fix: when the point parses fine but pixel scale is unknown,
    tapped_at_points is still populated and the note distinguishes this from
    a parse failure."""
    fake = FakeRunner(
        queue=[
            _describe_ui_result(SAMPLE_DESCRIBE_UI_JSON),
            CommandResult(
                args=[],
                returncode=0,
                stdout="\u2713 Tap at resolved tap point at (196.5, 403.3)",
                stderr="",
            ),
            _describe_ui_result(SAMPLE_DESCRIBE_UI_JSON),
        ]
    )
    runner = CommandRunner(_runner=fake)
    result = tap_selector(runner, UDID, {"label": "General"}, scale=None)

    assert result["tapped_at_points"] == [196.5, 403.3]
    assert result["tapped_at_pixels"] is None
    assert result["tap_point_note"] is not None
    assert "NOT because the tapped point itself is unknown" in result["tap_point_note"]


def test_tap_selector_refuses_when_resolved_node_has_no_label() -> None:
    fake = FakeRunner(queue=[_describe_ui_result(SAMPLE_DESCRIBE_UI_JSON)])
    runner = CommandRunner(_runner=fake)
    with pytest.raises(UiInteractionError, match="no AXLabel"):
        tap_selector(runner, UDID, {"unique_id": "unlabeled-button"}, scale=3.0)
    # Must NOT have attempted a tap command after failing to find a label.
    assert len(fake.calls) == 1


def test_tap_selector_propagates_selector_error_for_zero_matches() -> None:
    fake = FakeRunner(queue=[_describe_ui_result(SAMPLE_DESCRIBE_UI_JSON)])
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SelectorError):
        tap_selector(runner, UDID, {"label": "Nope"}, scale=3.0)


def test_tap_xy_always_carries_warning() -> None:
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=0, stdout="ok", stderr="")
    )
    runner = CommandRunner(_runner=fake)
    result = tap_xy(runner, UDID, 100.0, 200.0)
    assert "warning" in result
    assert "NOT independently verified" in result["warning"]
    assert "selector" in result["warning"]


def test_type_text_taps_to_focus_then_types_and_warns() -> None:
    fake = FakeRunner(
        queue=[
            _describe_ui_result(SAMPLE_DESCRIBE_UI_JSON),  # dump before
            CommandResult(
                args=[],
                returncode=0,
                stdout="\u2713 Tap at resolved tap point at (196.5, 403.3)",
                stderr="",
            ),  # tap-to-focus
            CommandResult(args=[], returncode=0, stdout="ok", stderr=""),  # type
            _describe_ui_result(SAMPLE_DESCRIBE_UI_JSON),  # re-dump after
        ]
    )
    runner = CommandRunner(_runner=fake)
    result = type_text(runner, UDID, {"label": "General"}, "hello", scale=3.0)
    assert result["tapped_label"] == "General"
    assert result["text_written"] == "hello"
    assert "focused" in result["warning"]
    # DEFECT fix: type_text's tap-to-focus uses the same 'axe tap --label' path
    # as tap_selector -- same evidence-reporting obligation applies.
    assert result["tapped_at_points"] == [196.5, 403.3]
    assert result["tapped_at_pixels"] == [589.5, 1209.9]
    assert result["tap_point_note"] is None
    # The selector still resolves after typing (label unchanged), so there's
    # nothing to explain away.
    assert result["value_after_note"] is None


def test_type_text_notes_when_selector_no_longer_resolves_after_typing() -> None:
    """DEFECT-class fix: value_after being None because the selector could not
    be re-resolved must carry an explicit note -- never a silent null
    indistinguishable from 'field value confirmed empty'."""
    fake = FakeRunner(
        queue=[
            _describe_ui_result(SAMPLE_DESCRIBE_UI_JSON),
            CommandResult(
                args=[],
                returncode=0,
                stdout="\u2713 Tap at resolved tap point at (196.5, 403.3)",
                stderr="",
            ),
            CommandResult(args=[], returncode=0, stdout="ok", stderr=""),
            _describe_ui_result(AMBIGUOUS_DESCRIBE_UI_JSON),  # "General" is gone
        ]
    )
    runner = CommandRunner(_runner=fake)
    result = type_text(runner, UDID, {"label": "General"}, "hello", scale=3.0)

    assert result["value_after"] is None
    assert result["value_after_note"] is not None
    assert "no longer matched" in result["value_after_note"]


def test_type_text_refuses_when_no_label() -> None:
    fake = FakeRunner(queue=[_describe_ui_result(SAMPLE_DESCRIBE_UI_JSON)])
    runner = CommandRunner(_runner=fake)
    with pytest.raises(UiInteractionError):
        type_text(runner, UDID, {"unique_id": "unlabeled-button"}, "hello", scale=1.0)


# ---------------------------------------------------------------------------
# wait_for
# ---------------------------------------------------------------------------


def test_wait_for_returns_met_true_when_selector_present_immediately() -> None:
    fake = FakeRunner(default=_describe_ui_result(SAMPLE_DESCRIBE_UI_JSON))
    runner = CommandRunner(_runner=fake)
    result = wait_for(
        runner, UDID, {"label": "General"}, scale=1.0, timeout_s=1.0, poll_s=0.01
    )
    assert result["met"] is True
    assert result["match_count"] == 1


def test_wait_for_times_out_when_selector_never_appears() -> None:
    fake = FakeRunner(default=_describe_ui_result(SAMPLE_DESCRIBE_UI_JSON))
    runner = CommandRunner(_runner=fake)
    result = wait_for(
        runner, UDID, {"label": "Nonexistent"}, scale=1.0, timeout_s=0.05, poll_s=0.01
    )
    assert result["met"] is False
    assert result["match_count"] == 0


def test_wait_for_absent_returns_met_true_when_selector_missing() -> None:
    fake = FakeRunner(default=_describe_ui_result(SAMPLE_DESCRIBE_UI_JSON))
    runner = CommandRunner(_runner=fake)
    result = wait_for(
        runner,
        UDID,
        {"label": "Nonexistent"},
        scale=1.0,
        timeout_s=1.0,
        poll_s=0.01,
        absent=True,
    )
    assert result["met"] is True

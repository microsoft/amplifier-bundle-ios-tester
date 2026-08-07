"""Sanity tests for the IosInspectorTool dispatch surface -- name, schema
shape, error handling for missing/unknown operations, and the mandatory
tap/tap_xy refusal on backend='device'. No simulator/device dependency."""

from __future__ import annotations

from pathlib import Path

import amplifier_module_tool_ios_inspector as pkg
import pytest
from amplifier_module_tool_ios_inspector import IosInspectorState, IosInspectorTool


@pytest.fixture
def tool() -> IosInspectorTool:
    return IosInspectorTool()


def test_tool_name(tool: IosInspectorTool) -> None:
    assert tool.name == "ios_inspector"


def test_input_schema_declares_all_operations(tool: IosInspectorTool) -> None:
    schema = tool.input_schema
    op_enum = schema["properties"]["operation"]["enum"]
    expected = {
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
    }
    assert set(op_enum) == expected
    assert schema["required"] == ["operation"]


def test_input_schema_declares_backend_parameter(tool: IosInspectorTool) -> None:
    schema = tool.input_schema
    backend_prop = schema["properties"]["backend"]
    assert set(backend_prop["enum"]) == {"simulator", "device"}
    assert backend_prop["default"] == "simulator"


async def test_execute_missing_operation_errors(tool: IosInspectorTool) -> None:
    result = await tool.execute({})
    assert result["success"] is False
    assert "operation" in result["error"]


async def test_execute_unknown_operation_errors(tool: IosInspectorTool) -> None:
    result = await tool.execute({"operation": "not_a_real_op"})
    assert result["success"] is False
    assert "Unknown operation" in result["error"]


async def test_execute_tap_missing_selector_errors(tool: IosInspectorTool) -> None:
    result = await tool.execute({"operation": "tap", "udid": "fake-udid"})
    assert result["success"] is False
    assert "selector" in result["error"]


async def test_execute_install_missing_app_path_errors(tool: IosInspectorTool) -> None:
    result = await tool.execute({"operation": "install", "udid": "fake-udid"})
    assert result["success"] is False
    assert "app_path" in result["error"]


async def test_execute_create_sim_missing_name_errors(tool: IosInspectorTool) -> None:
    """DEFECT 3: only 'name' is required -- device_type/runtime are
    OPTIONAL, resolved to sensible defaults when omitted (see
    simctl.resolve_devicetype/resolve_runtime)."""
    result = await tool.execute({"operation": "create_sim"})
    assert result["success"] is False
    assert "name" in result["error"]


async def test_execute_swipe_missing_coords_errors(tool: IosInspectorTool) -> None:
    result = await tool.execute({"operation": "swipe", "udid": "fake-udid"})
    assert result["success"] is False
    assert "x1" in result["error"]


# ---------------------------------------------------------------------------
# HARD REQUIREMENT: tap / tap_xy MUST refuse on backend='device' -- never
# guess a coordinate. This check must fire BEFORE any udid resolution or
# selector validation (so it works even with no device attached at all).
# ---------------------------------------------------------------------------


async def test_execute_tap_refuses_on_device_backend(tool: IosInspectorTool) -> None:
    result = await tool.execute(
        {"operation": "tap", "backend": "device", "selector": {"label": "General"}}
    )
    assert result["success"] is False
    assert "backend='device'" in result["error"]
    assert "no geometry" in result["error"].lower() or "NO GEOMETRY" in result["error"]
    assert "WebDriverAgent" in result["error"]
    assert result["backend"] == "device"


async def test_execute_tap_refuses_on_device_backend_even_without_selector(
    tool: IosInspectorTool,
) -> None:
    """The refusal must fire before the 'missing selector' check -- a
    device-backend tap request is wrong regardless of what else is
    missing."""
    result = await tool.execute({"operation": "tap", "backend": "device"})
    assert result["success"] is False
    assert "backend='device'" in result["error"]


async def test_execute_tap_xy_refuses_on_device_backend(tool: IosInspectorTool) -> None:
    result = await tool.execute(
        {"operation": "tap_xy", "backend": "device", "x": 100, "y": 200}
    )
    assert result["success"] is False
    assert "backend='device'" in result["error"]


async def test_execute_simulator_only_op_rejects_device_backend(
    tool: IosInspectorTool,
) -> None:
    """ui_dump (and the rest of _SIMULATOR_ONLY_OPS) must reject
    backend='device' generically at dispatch time, before even reaching the
    per-operation handler."""
    result = await tool.execute({"operation": "ui_dump", "backend": "device"})
    assert result["success"] is False
    assert "only supports backend='simulator'" in result["error"]


async def test_execute_device_op_works_with_default_backend_param_unset(
    monkeypatch: pytest.MonkeyPatch, tool: IosInspectorTool
) -> None:
    """device_info is not in _SIMULATOR_ONLY_OPS, so it must be reachable
    without any 'backend' param at all (defaults are for simulator ops, not
    device ops -- device_* op names are already unambiguous)."""

    def fake_resolve(self, state, inp):
        return "fake-udid"

    def fake_device_info(runner, udid):
        return {"udid": udid, "ProductVersion": "16.7.16"}

    monkeypatch.setattr(pkg.IosInspectorTool, "_resolve_device_udid", fake_resolve)
    monkeypatch.setattr(pkg._device, "device_info", fake_device_info)

    result = await tool.execute({"operation": "device_info"})
    assert result["success"] is True
    assert result["udid"] == "fake-udid"


# ---------------------------------------------------------------------------
# mount() -- per-instance state (mirrors the android_inspector Defect-4 fix)
# ---------------------------------------------------------------------------


class _FakeCoordinator:
    async def mount(self, kind, obj, *, name):
        return None


async def test_mount_builds_independent_state_per_call(tmp_path: Path) -> None:
    work_dir_1 = tmp_path / "it-c1"
    work_dir_2 = tmp_path / "it-c2"
    coordinator = _FakeCoordinator()

    tool1 = await pkg.mount(coordinator, {"work_dir": str(work_dir_1)})
    tool2 = await pkg.mount(coordinator, {"work_dir": str(work_dir_2)})

    state1 = tool1._get_state()
    state2 = tool2._get_state()

    assert state1.base_dir == work_dir_1
    assert state2.base_dir == work_dir_2
    assert work_dir_1.exists()
    assert work_dir_2.exists()
    assert state1 is not state2


async def test_mount_with_no_config_defaults_independently() -> None:
    coordinator = _FakeCoordinator()
    tool_a = await pkg.mount(coordinator)
    tool_b = await pkg.mount(coordinator)
    assert tool_a is not tool_b
    assert tool_a._config is not tool_b._config


# ---------------------------------------------------------------------------
# list_targets ambiguity handling
# ---------------------------------------------------------------------------


def _state_with_run_dir(tmp_path: Path) -> IosInspectorState:
    base_dir = tmp_path / "sessions"
    run_dir = base_dir / "_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    return IosInspectorState(config={}, base_dir=base_dir, run_dir=run_dir)


async def test_list_targets_ambiguous_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool = IosInspectorTool()
    tool._state = _state_with_run_dir(tmp_path)

    def fake_list_simulators(runner):
        return [
            {
                "udid": "sim-1",
                "name": "iPhone 16",
                "state": "Booted",
                "backend": "simulator",
            },
            {
                "udid": "sim-2",
                "name": "iPhone 15",
                "state": "Booted",
                "backend": "simulator",
            },
        ]

    def fake_list_physical_devices(runner):
        return []

    monkeypatch.setattr(pkg._simctl, "list_simulators", fake_list_simulators)
    monkeypatch.setattr(
        pkg._device, "list_physical_devices", fake_list_physical_devices
    )

    result = await tool.execute({"operation": "list_targets"})
    assert result["success"] is False
    assert "Ambiguous" in result["error"]


SIM_UDID = "sim-1"


# ---------------------------------------------------------------------------
# DEFECT fix: get_scale returns None (never guesses) when measurement fails,
# caches the failure, and ui_dump/find surface an explicit warning + omit
# pixel frames rather than erroring the whole call out.
# ---------------------------------------------------------------------------


def test_get_scale_returns_none_and_caches_failure_on_measurement_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = _state_with_run_dir(tmp_path)
    call_count = {"n": 0}

    def fake_measure_scale(*args, **kwargs):
        call_count["n"] += 1
        raise pkg.SimctlError("width/height disagree for sim-1")

    monkeypatch.setattr(pkg._simctl, "measure_scale", fake_measure_scale)

    assert state.get_scale(SIM_UDID) is None
    assert state.get_scale(SIM_UDID) is None
    # Cached after the first failure -- never re-attempted (and re-failed)
    # on every subsequent call.
    assert call_count["n"] == 1
    assert "disagree" in (state.scale_unavailable_reason(SIM_UDID) or "")


def test_get_scale_returns_and_caches_successful_measurement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = _state_with_run_dir(tmp_path)
    call_count = {"n": 0}

    def fake_measure_scale(*args, **kwargs):
        call_count["n"] += 1
        return 3.0

    monkeypatch.setattr(pkg._simctl, "measure_scale", fake_measure_scale)

    assert state.get_scale(SIM_UDID) == 3.0
    assert state.get_scale(SIM_UDID) == 3.0
    assert call_count["n"] == 1


async def test_ui_dump_omits_pixel_frames_and_warns_when_scale_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool = IosInspectorTool()
    tool._state = _state_with_run_dir(tmp_path)

    def fake_resolve(self, state, inp):
        return SIM_UDID

    def fake_get_scale(self, udid):
        return None

    def fake_scale_unavailable_reason(self, udid):
        return "measured scale not close to any plausible value"

    def fake_describe_ui(runner, udid, *, scale, timeout=None):
        from amplifier_module_tool_ios_inspector.axe import AxNode

        return [
            AxNode(
                node_type="StaticText",
                role="text",
                label="General",
                value="",
                unique_id="general-row",
                enabled=True,
                frame_points=(16.0, 377.33, 361.0, 52.0),
                scale=scale,
            )
        ]

    monkeypatch.setattr(pkg.IosInspectorTool, "_resolve_sim_udid", fake_resolve)
    monkeypatch.setattr(pkg.IosInspectorState, "get_scale", fake_get_scale)
    monkeypatch.setattr(
        pkg.IosInspectorState,
        "scale_unavailable_reason",
        fake_scale_unavailable_reason,
    )
    monkeypatch.setattr(pkg._axe, "describe_ui", fake_describe_ui)

    result = await tool.execute({"operation": "ui_dump"})
    assert result["success"] is True
    assert result["scale"] is None
    assert result["nodes"][0]["frame_pixels"] is None
    assert result["nodes"][0]["center_pixels"] is None
    assert result["nodes"][0]["frame_points"] == [16.0, 377.33, 361.0, 52.0]
    assert "warnings" in result
    assert "not close to any plausible value" in result["warnings"][0]


async def test_find_omits_pixel_frames_and_warns_when_scale_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool = IosInspectorTool()
    tool._state = _state_with_run_dir(tmp_path)

    def fake_resolve(self, state, inp):
        return SIM_UDID

    def fake_get_scale(self, udid):
        return None

    def fake_scale_unavailable_reason(self, udid):
        return "root frame missing"

    def fake_describe_ui(runner, udid, *, scale, timeout=None):
        from amplifier_module_tool_ios_inspector.axe import AxNode

        return [
            AxNode(
                node_type="StaticText",
                role="text",
                label="General",
                value="",
                unique_id="general-row",
                enabled=True,
                frame_points=(16.0, 377.33, 361.0, 52.0),
                scale=scale,
            )
        ]

    monkeypatch.setattr(pkg.IosInspectorTool, "_resolve_sim_udid", fake_resolve)
    monkeypatch.setattr(pkg.IosInspectorState, "get_scale", fake_get_scale)
    monkeypatch.setattr(
        pkg.IosInspectorState,
        "scale_unavailable_reason",
        fake_scale_unavailable_reason,
    )
    monkeypatch.setattr(pkg._axe, "describe_ui", fake_describe_ui)

    result = await tool.execute({"operation": "find", "selector": {"label": "General"}})
    assert result["success"] is True
    assert result["matches"][0]["frame_pixels"] is None
    assert "warnings" in result
    assert "root frame missing" in result["warnings"][0]


async def test_list_targets_explicit_udid_filters_to_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tool = IosInspectorTool()
    tool._state = _state_with_run_dir(tmp_path)

    def fake_list_simulators(runner):
        return [
            {
                "udid": "sim-1",
                "name": "iPhone 16",
                "state": "Booted",
                "backend": "simulator",
            },
            {
                "udid": "sim-2",
                "name": "iPhone 15",
                "state": "Shutdown",
                "backend": "simulator",
            },
        ]

    def fake_list_physical_devices(runner):
        return []

    monkeypatch.setattr(pkg._simctl, "list_simulators", fake_list_simulators)
    monkeypatch.setattr(
        pkg._device, "list_physical_devices", fake_list_physical_devices
    )

    result = await tool.execute({"operation": "list_targets", "udid": "sim-2"})
    assert result["success"] is True
    assert result["count"] == 1
    assert result["targets"][0]["udid"] == "sim-2"

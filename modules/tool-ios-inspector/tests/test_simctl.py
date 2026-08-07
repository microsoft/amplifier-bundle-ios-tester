"""Tests for simctl.py -- CoreSimulator benign-noise handling (DEFECT 2),
create_sim device_type/runtime resolution (DEFECT 3), and per-op timeout
threading (DEFECT 1). All against a FakeRunner -- no real simulator
required."""

from __future__ import annotations

import json

import pytest
from amplifier_module_tool_ios_inspector.axe import UiDumpError
from amplifier_module_tool_ios_inspector.runner import CommandResult, CommandRunner
from amplifier_module_tool_ios_inspector.simctl import (
    SimctlError,
    boot,
    create_sim,
    install,
    launch,
    list_devicetypes,
    log_stream,
    measure_scale,
    resolve_devicetype,
    resolve_runtime,
    screenshot,
    shutdown,
    terminate,
)

from .conftest import FakeRunner, fake_png_bytes

UDID = "12345678-0000AAAA1234ABCD"

# The EXACT measured-live CoreSimulator background-noise signature.
NOISE_STDERR = (
    "Install Started\n"
    "Install Failed: Authorization is required to install the packages."
)

DEVICETYPES_JSON = {
    "devicetypes": [
        {
            "name": "iPhone SE (3rd generation)",
            "identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-SE-3rd-generation",
            "productFamily": "iPhone",
            "minRuntimeVersion": 851968,
        },
        {
            "name": "iPhone 16",
            "identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-16",
            "productFamily": "iPhone",
            "minRuntimeVersion": 1179648,
        },
        {
            "name": "iPhone 17 Pro",
            "identifier": "com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro",
            "productFamily": "iPhone",
            "minRuntimeVersion": 1245184,
        },
        {
            "name": "iPad Pro 11-inch (M4)",
            "identifier": "com.apple.CoreSimulator.SimDeviceType.iPad-Pro-11-inch-M4",
            "productFamily": "iPad",
            "minRuntimeVersion": 1245184,
        },
    ]
}

RUNTIMES_JSON = {
    "runtimes": [
        {
            "name": "iOS 17.5",
            "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-17-5",
            "version": "17.5",
            "isAvailable": True,
        },
        {
            "name": "iOS 26.5",
            "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-26-5",
            "version": "26.5",
            "isAvailable": True,
        },
        {
            "name": "iOS 27.0",
            "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-27-0",
            "version": "27.0",
            "isAvailable": False,
        },
        {
            "name": "watchOS 11.0",
            "identifier": "com.apple.CoreSimulator.SimRuntime.watchOS-11-0",
            "version": "11.0",
            "isAvailable": True,
        },
    ]
}


def _devicetypes_result() -> CommandResult:
    return CommandResult(
        args=[], returncode=0, stdout=json.dumps(DEVICETYPES_JSON), stderr=""
    )


def _runtimes_result() -> CommandResult:
    return CommandResult(
        args=[], returncode=0, stdout=json.dumps(RUNTIMES_JSON), stderr=""
    )


# ---------------------------------------------------------------------------
# DEFECT 2 -- CoreSimulator benign noise never fails a command that
# otherwise succeeded.
# ---------------------------------------------------------------------------


def test_launch_succeeds_with_pid_despite_noise_and_nonzero_exit() -> None:
    """The exact measured scenario: `simctl launch` printed the noise AND
    returned a live pid. Must succeed, not raise."""
    fake = FakeRunner(
        default=CommandResult(
            args=[],
            returncode=-1,
            stdout="com.apple.Preferences: 92162",
            stderr=NOISE_STDERR,
        )
    )
    runner = CommandRunner(_runner=fake)
    result = launch(runner, UDID, "com.apple.Preferences")
    assert result["pid"] == 92162
    assert result["warnings"] == NOISE_STDERR.splitlines()


def test_launch_raises_when_no_pid_and_not_ok_even_with_noise_present() -> None:
    """Noise never overrides the failure decision for launch -- pid absence
    plus nonzero exit is a genuine failure regardless of what else is in
    stderr."""
    fake = FakeRunner(
        default=CommandResult(
            args=[],
            returncode=1,
            stdout="",
            stderr=NOISE_STDERR + "\nSome other genuine problem",
        )
    )
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SimctlError):
        launch(runner, UDID, "com.apple.Preferences")


def test_launch_raises_on_real_error_not_noise() -> None:
    fake = FakeRunner(
        default=CommandResult(
            args=[], returncode=1, stdout="", stderr="Invalid device state"
        )
    )
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SimctlError, match="Invalid device state"):
        launch(runner, UDID, "com.apple.Preferences")


def test_launch_no_warnings_key_when_no_noise() -> None:
    fake = FakeRunner(
        default=CommandResult(
            args=[], returncode=0, stdout="com.apple.Preferences: 111", stderr=""
        )
    )
    runner = CommandRunner(_runner=fake)
    result = launch(runner, UDID, "com.apple.Preferences")
    assert "warnings" not in result


def test_boot_succeeds_when_noise_only_and_confirmed_booted() -> None:
    """boot's observable-outcome verification: nonzero exit + noise-only
    stderr succeeds ONLY if a follow-up `simctl list devices` confirms the
    device actually reached Booted."""
    booted_devices_json = {
        "devices": {
            "com.apple.CoreSimulator.SimRuntime.iOS-26-5": [
                {"udid": UDID, "name": "iPhone 16", "state": "Booted"}
            ]
        }
    }
    fake = FakeRunner(
        queue=[
            CommandResult(args=[], returncode=-1, stdout="", stderr=NOISE_STDERR),
            CommandResult(
                args=[], returncode=0, stdout=json.dumps(booted_devices_json), stderr=""
            ),
        ]
    )
    runner = CommandRunner(_runner=fake)
    result = boot(runner, UDID)
    assert result["warnings"] == NOISE_STDERR.splitlines()
    assert result["already_booted"] is False
    # DEFECT fix: 'state' is the REAL observed state (reusing the SAME
    # `simctl list devices` call already made to confirm the boot -- not a
    # second, redundant listing call), and 'elapsed_s' is always a real
    # measured number, never a null placeholder.
    assert result["state"] == "Booted"
    assert isinstance(result["elapsed_s"], float)
    assert len(fake.calls) == 2  # boot + the one confirming list -- no 3rd call


def test_boot_raises_when_noise_present_but_not_confirmed_booted() -> None:
    """The observable-outcome check must actually gate success -- noise
    alone is not enough if the device never reached Booted."""
    not_booted_devices_json = {
        "devices": {
            "com.apple.CoreSimulator.SimRuntime.iOS-26-5": [
                {"udid": UDID, "name": "iPhone 16", "state": "Shutdown"}
            ]
        }
    }
    fake = FakeRunner(
        queue=[
            CommandResult(args=[], returncode=-1, stdout="", stderr=NOISE_STDERR),
            CommandResult(
                args=[],
                returncode=0,
                stdout=json.dumps(not_booted_devices_json),
                stderr="",
            ),
        ]
    )
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SimctlError):
        boot(runner, UDID)


def test_boot_already_booted_short_circuits_without_noise_check() -> None:
    fake = FakeRunner(
        default=CommandResult(
            args=[], returncode=1, stdout="", stderr="current state: Booted"
        )
    )
    runner = CommandRunner(_runner=fake)
    result = boot(runner, UDID)
    assert result["already_booted"] is True
    assert "warnings" not in result
    assert isinstance(result["elapsed_s"], float)
    # The listing probe for 'state' fails against this fake's canned
    # response (not real JSON) -- 'state' must be OMITTED, never set to a
    # null placeholder, and that failure must not affect the already_booted
    # success determination made above.
    assert "state" not in result


def test_boot_populates_elapsed_s_and_omits_state_when_listing_unavailable() -> None:
    """Plain success path (no noise): 'elapsed_s' is always a real measured
    number. 'state' is omitted -- not null -- when the observational
    listing call can't be parsed/obtained, since that is a DIFFERENT,
    non-fatal concern from the boot's own success."""
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=0, stdout="", stderr="")
    )
    runner = CommandRunner(_runner=fake, default_timeout=30.0)
    result = boot(runner, UDID, timeout=120.0)
    assert result["already_booted"] is False
    assert isinstance(result["elapsed_s"], float)
    assert "state" not in result
    assert "warnings" not in result


def test_boot_populates_state_on_plain_success_when_listing_available() -> None:
    """Plain success path (no noise) where the listing call DOES succeed --
    'state' must be populated with the real observed value."""
    booted_devices_json = {
        "devices": {
            "com.apple.CoreSimulator.SimRuntime.iOS-26-5": [
                {"udid": UDID, "name": "iPhone 16", "state": "Booted"}
            ]
        }
    }
    fake = FakeRunner(
        queue=[
            CommandResult(args=[], returncode=0, stdout="", stderr=""),
            CommandResult(
                args=[], returncode=0, stdout=json.dumps(booted_devices_json), stderr=""
            ),
        ]
    )
    runner = CommandRunner(_runner=fake)
    result = boot(runner, UDID)
    assert result["state"] == "Booted"
    assert isinstance(result["elapsed_s"], float)


def test_boot_raises_on_real_error_not_noise() -> None:
    fake = FakeRunner(
        default=CommandResult(
            args=[], returncode=1, stdout="", stderr="Unable to boot device"
        )
    )
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SimctlError, match="Unable to boot device"):
        boot(runner, UDID)


def test_shutdown_treats_noise_only_failure_as_success() -> None:
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=-1, stdout="", stderr=NOISE_STDERR)
    )
    runner = CommandRunner(_runner=fake)
    result = shutdown(runner, UDID)
    assert result["warnings"] == NOISE_STDERR.splitlines()


def test_install_treats_noise_only_failure_as_success() -> None:
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=-1, stdout="", stderr=NOISE_STDERR)
    )
    runner = CommandRunner(_runner=fake)
    result = install(runner, UDID, "/tmp/app.app")
    assert result["warnings"] == NOISE_STDERR.splitlines()


def test_install_raises_on_real_error_not_noise() -> None:
    fake = FakeRunner(
        default=CommandResult(
            args=[], returncode=1, stdout="", stderr="Invalid app bundle"
        )
    )
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SimctlError, match="Invalid app bundle"):
        install(runner, UDID, "/tmp/app.app")


def test_terminate_treats_noise_only_failure_as_success() -> None:
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=-1, stdout="", stderr=NOISE_STDERR)
    )
    runner = CommandRunner(_runner=fake)
    result = terminate(runner, UDID, "com.apple.Preferences")
    assert result["warnings"] == NOISE_STDERR.splitlines()


def test_screenshot_treats_noise_only_failure_as_success_when_png_valid(
    tmp_path,
) -> None:
    """screenshot's observable-outcome check is the PNG liveness check
    already in place -- noise-only stderr should not block reaching it."""
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    local_dest = tmp_path / "shot.png"
    src = tmp_path / "src.png"
    src.write_bytes(png_bytes)

    fake = FakeRunner(
        default=CommandResult(args=[], returncode=-1, stdout="", stderr=NOISE_STDERR)
    )
    runner = CommandRunner(_runner=fake)
    result = screenshot(runner, UDID, local_dest, remote_tmp=str(src))
    assert result["warnings"] == NOISE_STDERR.splitlines()
    assert result["byte_size"] == len(png_bytes)


def test_screenshot_raises_on_real_error_not_noise(tmp_path) -> None:
    fake = FakeRunner(
        default=CommandResult(
            args=[], returncode=1, stdout="", stderr="Device not booted"
        )
    )
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SimctlError, match="Device not booted"):
        screenshot(runner, UDID, tmp_path / "whatever.png", remote_tmp="/tmp/src.png")


# ---------------------------------------------------------------------------
# DEFECT 3 -- create_sim device_type/runtime: optional, friendly-name,
# identifier passthrough, unknown-name error listing alternatives, defaults.
# ---------------------------------------------------------------------------


def test_resolve_devicetype_friendly_name() -> None:
    fake = FakeRunner(default=_devicetypes_result())
    runner = CommandRunner(_runner=fake)
    identifier, name = resolve_devicetype(runner, "iPhone 16")
    assert identifier == "com.apple.CoreSimulator.SimDeviceType.iPhone-16"
    assert name == "iPhone 16"


def test_resolve_devicetype_full_identifier_passthrough() -> None:
    fake = FakeRunner(default=_devicetypes_result())
    runner = CommandRunner(_runner=fake)
    identifier, name = resolve_devicetype(
        runner, "com.apple.CoreSimulator.SimDeviceType.iPhone-16"
    )
    assert identifier == "com.apple.CoreSimulator.SimDeviceType.iPhone-16"
    assert name == "iPhone 16"


def test_resolve_devicetype_unknown_name_errors_listing_available() -> None:
    fake = FakeRunner(default=_devicetypes_result())
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SimctlError) as exc_info:
        resolve_devicetype(runner, "iPhone 3000")
    message = str(exc_info.value)
    assert "iPhone 3000" in message
    assert "iPhone 16" in message
    assert exc_info.value.extra["available_devicetypes"]


def test_resolve_devicetype_default_picks_newest_iphone() -> None:
    """None -> newest available iPhone (by minRuntimeVersion), never a
    hardcoded identifier, and never an iPad."""
    fake = FakeRunner(default=_devicetypes_result())
    runner = CommandRunner(_runner=fake)
    identifier, name = resolve_devicetype(runner, None)
    assert identifier == "com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro"
    assert name == "iPhone 17 Pro"


def test_resolve_runtime_friendly_name() -> None:
    fake = FakeRunner(default=_runtimes_result())
    runner = CommandRunner(_runner=fake)
    identifier, name = resolve_runtime(runner, "iOS 26.5")
    assert identifier == "com.apple.CoreSimulator.SimRuntime.iOS-26-5"
    assert name == "iOS 26.5"


def test_resolve_runtime_full_identifier_passthrough() -> None:
    fake = FakeRunner(default=_runtimes_result())
    runner = CommandRunner(_runner=fake)
    identifier, name = resolve_runtime(
        runner, "com.apple.CoreSimulator.SimRuntime.iOS-26-5"
    )
    assert identifier == "com.apple.CoreSimulator.SimRuntime.iOS-26-5"
    assert name == "iOS 26.5"


def test_resolve_runtime_unknown_name_errors_listing_available() -> None:
    fake = FakeRunner(default=_runtimes_result())
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SimctlError) as exc_info:
        resolve_runtime(runner, "iOS 99.0")
    message = str(exc_info.value)
    assert "iOS 99.0" in message
    assert "iOS 26.5" in message
    assert exc_info.value.extra["available_runtimes"]


def test_resolve_runtime_default_picks_newest_available_ios() -> None:
    """None -> newest AVAILABLE iOS runtime -- must skip the unavailable
    iOS 27.0 and the non-iOS watchOS runtime."""
    fake = FakeRunner(default=_runtimes_result())
    runner = CommandRunner(_runner=fake)
    identifier, name = resolve_runtime(runner, None)
    assert identifier == "com.apple.CoreSimulator.SimRuntime.iOS-26-5"
    assert name == "iOS 26.5"


def test_create_sim_with_no_device_type_or_runtime_resolves_defaults() -> None:
    fake = FakeRunner(
        queue=[
            _devicetypes_result(),
            _runtimes_result(),
            CommandResult(args=[], returncode=0, stdout=f"{UDID}\n", stderr=""),
        ]
    )
    runner = CommandRunner(_runner=fake)
    result = create_sim(runner, name="ios-tester-proof")
    assert result["udid"] == UDID
    assert result["device_type"] == "iPhone 17 Pro"
    assert result["runtime"] == "iOS 26.5"
    # The actual `simctl create` invocation used the resolved IDENTIFIERS,
    # never the friendly display names.
    create_call = fake.calls[2]
    assert create_call == [
        "xcrun",
        "simctl",
        "create",
        "ios-tester-proof",
        "com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro",
        "com.apple.CoreSimulator.SimRuntime.iOS-26-5",
    ]


def test_create_sim_with_friendly_names_resolves_to_identifiers() -> None:
    fake = FakeRunner(
        queue=[
            _devicetypes_result(),
            _runtimes_result(),
            CommandResult(args=[], returncode=0, stdout=f"{UDID}\n", stderr=""),
        ]
    )
    runner = CommandRunner(_runner=fake)
    result = create_sim(
        runner, name="ios-tester-proof", device_type="iPhone 16", runtime="iOS 17.5"
    )
    assert result["device_type"] == "iPhone 16"
    assert result["runtime"] == "iOS 17.5"
    create_call = fake.calls[2]
    assert create_call[4] == "com.apple.CoreSimulator.SimDeviceType.iPhone-16"
    assert create_call[5] == "com.apple.CoreSimulator.SimRuntime.iOS-17-5"


def test_create_sim_unknown_device_type_errors_before_running_create() -> None:
    fake = FakeRunner(queue=[_devicetypes_result()])
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SimctlError) as exc_info:
        create_sim(runner, name="x", device_type="iPhone 3000")
    assert "iPhone 3000" in str(exc_info.value)
    # Never got as far as invoking `simctl create` with a bogus identifier.
    assert not any(c[:3] == ["xcrun", "simctl", "create"] for c in fake.calls)


def test_create_sim_noise_only_failure_still_requires_a_udid() -> None:
    fake = FakeRunner(
        queue=[
            _devicetypes_result(),
            _runtimes_result(),
            CommandResult(args=[], returncode=-1, stdout="", stderr=NOISE_STDERR),
        ]
    )
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SimctlError, match="no UDID"):
        create_sim(runner, name="x")


def test_create_sim_succeeds_with_warnings_when_noise_and_udid_present() -> None:
    fake = FakeRunner(
        queue=[
            _devicetypes_result(),
            _runtimes_result(),
            CommandResult(
                args=[], returncode=-1, stdout=f"{UDID}\n", stderr=NOISE_STDERR
            ),
        ]
    )
    runner = CommandRunner(_runner=fake)
    result = create_sim(runner, name="x")
    assert result["udid"] == UDID
    assert result["warnings"] == NOISE_STDERR.splitlines()


# ---------------------------------------------------------------------------
# DEFECT 1 -- per-operation timeout budgets are actually applied.
# ---------------------------------------------------------------------------


def test_boot_uses_explicit_timeout_when_given() -> None:
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=0, stdout="", stderr="")
    )
    runner = CommandRunner(_runner=fake, default_timeout=30.0)
    boot(runner, UDID, timeout=120.0)
    assert fake.timeouts[0] == 120.0


def test_launch_uses_explicit_timeout_when_given() -> None:
    fake = FakeRunner(
        default=CommandResult(
            args=[], returncode=0, stdout="com.apple.Preferences: 1\n", stderr=""
        )
    )
    runner = CommandRunner(_runner=fake, default_timeout=30.0)
    launch(runner, UDID, "com.apple.Preferences", timeout=180.0)
    assert fake.timeouts[0] == 180.0


def test_create_sim_uses_explicit_timeout_for_the_create_call() -> None:
    fake = FakeRunner(
        queue=[
            _devicetypes_result(),
            _runtimes_result(),
            CommandResult(args=[], returncode=0, stdout=f"{UDID}\n", stderr=""),
        ]
    )
    runner = CommandRunner(_runner=fake, default_timeout=30.0)
    create_sim(runner, name="x", timeout=180.0)
    # calls[0]/[1] are the list_devicetypes/list_runtimes probes (default
    # timeout); calls[2] is the actual `create` -- it must carry the
    # explicit override.
    assert fake.timeouts[2] == 180.0


def test_screenshot_uses_explicit_timeout_when_given(tmp_path) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    src = tmp_path / "src.png"
    src.write_bytes(png_bytes)
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=0, stdout="", stderr="")
    )
    runner = CommandRunner(_runner=fake, default_timeout=30.0)
    screenshot(runner, UDID, tmp_path / "shot.png", remote_tmp=str(src), timeout=90.0)
    assert fake.timeouts[0] == 90.0


def test_log_stream_uses_structural_timed_out_flag_not_string_match() -> None:
    """log_stream must treat a bounded, expected timeout as normal
    termination via the STRUCTURAL `timed_out` marker, never by parsing
    stderr text for a magic phrase."""
    fake = FakeRunner(
        default=CommandResult(
            args=[],
            returncode=-1,
            stdout="log line 1\nlog line 2",
            stderr="",
            timed_out=True,
        )
    )
    runner = CommandRunner(_runner=fake)
    result = log_stream(runner, UDID, duration_s=2.0)
    assert result["count"] == 2
    assert fake.timeouts[0] == 2.0


def test_log_stream_raises_on_real_nonzero_exit_that_is_not_a_timeout() -> None:
    fake = FakeRunner(
        default=CommandResult(
            args=[], returncode=1, stdout="", stderr="spawn failed", timed_out=False
        )
    )
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SimctlError, match="spawn failed"):
        log_stream(runner, UDID, duration_s=2.0)


def test_list_devicetypes_still_works_unchanged() -> None:
    fake = FakeRunner(default=_devicetypes_result())
    runner = CommandRunner(_runner=fake)
    devicetypes = list_devicetypes(runner)
    assert len(devicetypes) == 4
    assert devicetypes[0]["name"] == "iPhone SE (3rd generation)"


# ---------------------------------------------------------------------------
# DEFECT: measure_scale must derive scale from the accessibility tree's ROOT
# node's own frame -- never an aggregate bounding box over every node (which
# off-screen/clipped elements corrupt). Regression uses the EXACT numbers
# from the reported live defect: root 402x874pt, screenshot 1206x2622px,
# with an off-screen node present that would inflate an aggregate bbox
# computation to the WRONG 2.3103 instead of the correct 3.0.
# ---------------------------------------------------------------------------

UDID2 = "AAAAAAAA-1111-2222-3333-444444444444"


def _describe_ui_cmd_result(payload: dict) -> CommandResult:
    return CommandResult(args=[], returncode=0, stdout=json.dumps(payload), stderr="")


def _root_json(
    width: float, height: float, *, extra_children: list[dict] | None = None
) -> dict:
    return {
        "type": "Application",
        "role": "application",
        "AXLabel": "Settings",
        "AXValue": "",
        "AXUniqueId": "",
        "enabled": True,
        "AXFrame": f"{{{{0, 0}}, {{{width}, {height}}}}}",
        "children": extra_children or [],
    }


# The exact off-screen/negative-origin node from the live defect report.
# An aggregate bounding box over the full tree (max_x - min_x style) is
# inflated by this node's out-of-range frame; a root-frame-only measurement
# must ignore it entirely.
_OFFSCREEN_CHILD_JSON = {
    "type": "Other",
    "role": "other",
    "AXLabel": "OffscreenThing",
    "AXValue": "",
    "AXUniqueId": "offscreen-thing",
    "enabled": True,
    "AXFrame": "{{-120.0, 738.0}, {642.0, 272.0}}",
    "children": [],
}


def _scale_probe_queue(
    payload: dict, png_width: int, png_height: int, src_path
) -> list[CommandResult]:
    src_path.write_bytes(fake_png_bytes(png_width, png_height))
    return [
        _describe_ui_cmd_result(payload),
        CommandResult(args=[], returncode=0, stdout="", stderr=""),
    ]


def test_measure_scale_uses_root_frame_and_ignores_offscreen_nodes(tmp_path) -> None:
    """Regression for the reported defect: root 402x874pt vs a
    1206x2622px screenshot must yield exactly 3.0 -- NOT the corrupted
    2.3103 an aggregate-bbox computation produces once the off-screen node
    is present."""
    src = tmp_path / "src.png"
    payload = _root_json(402.0, 874.0, extra_children=[_OFFSCREEN_CHILD_JSON])
    fake = FakeRunner(queue=_scale_probe_queue(payload, 1206, 2622, src))
    runner = CommandRunner(_runner=fake)
    scale = measure_scale(runner, UDID2, scratch_dir=tmp_path, remote_tmp=str(src))
    assert scale == 3.0


def test_measure_scale_2x_device(tmp_path) -> None:
    src = tmp_path / "src.png"
    payload = _root_json(200.0, 300.0)
    fake = FakeRunner(queue=_scale_probe_queue(payload, 400, 600, src))
    runner = CommandRunner(_runner=fake)
    scale = measure_scale(runner, UDID2, scratch_dir=tmp_path, remote_tmp=str(src))
    assert scale == 2.0


def test_measure_scale_1x_device(tmp_path) -> None:
    src = tmp_path / "src.png"
    payload = _root_json(320.0, 480.0)
    fake = FakeRunner(queue=_scale_probe_queue(payload, 320, 480, src))
    runner = CommandRunner(_runner=fake)
    scale = measure_scale(runner, UDID2, scratch_dir=tmp_path, remote_tmp=str(src))
    assert scale == 1.0


def test_measure_scale_axis_disagreement_raises(tmp_path) -> None:
    """width-derived scale (3.0) vs height-derived scale (1.0) disagree far
    beyond tolerance -- must raise rather than pick one or average."""
    src = tmp_path / "src.png"
    payload = _root_json(100.0, 200.0)
    fake = FakeRunner(queue=_scale_probe_queue(payload, 300, 200, src))
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SimctlError, match="disagree"):
        measure_scale(runner, UDID2, scratch_dir=tmp_path, remote_tmp=str(src))


def test_measure_scale_implausible_value_raises(tmp_path) -> None:
    """A measured scale of 2.5 is not close to any plausible iOS device
    scale (1.0/2.0/3.0) -- must raise rather than accept it."""
    src = tmp_path / "src.png"
    payload = _root_json(100.0, 100.0)
    fake = FakeRunner(queue=_scale_probe_queue(payload, 250, 250, src))
    runner = CommandRunner(_runner=fake)
    with pytest.raises(SimctlError, match="not close to"):
        measure_scale(runner, UDID2, scratch_dir=tmp_path, remote_tmp=str(src))


def test_measure_scale_root_without_frame_raises_uidump_error(tmp_path) -> None:
    """The root node itself carries no AXFrame -- nothing to measure
    against, and no fallback is attempted (no verified device-metadata
    scale lookup exists in this tool)."""
    payload = {
        "type": "Application",
        "role": "application",
        "AXLabel": "Settings",
        "AXValue": "",
        "AXUniqueId": "",
        "enabled": True,
        "children": [],
    }
    fake = FakeRunner(queue=[_describe_ui_cmd_result(payload)])
    runner = CommandRunner(_runner=fake)
    with pytest.raises(UiDumpError, match="no AXFrame"):
        measure_scale(runner, UDID2, scratch_dir=tmp_path, remote_tmp="/tmp/unused.png")


def test_measure_scale_empty_tree_raises_uidump_error(tmp_path) -> None:
    fake = FakeRunner(
        queue=[CommandResult(args=[], returncode=0, stdout=json.dumps([]), stderr="")]
    )
    runner = CommandRunner(_runner=fake)
    with pytest.raises(UiDumpError):
        measure_scale(runner, UDID2, scratch_dir=tmp_path, remote_tmp="/tmp/unused.png")

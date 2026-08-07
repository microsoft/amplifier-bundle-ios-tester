"""Tests for doctor.py -- each check branch (ok/warn/fail), including the
passcode-blocker awareness and DDI-availability-vs-device-version gap.
All against a FakeRunner queued/keyed by argv -- no real Mac required."""

from __future__ import annotations

from amplifier_module_tool_ios_inspector.doctor import (
    check_axe,
    check_developer_dir,
    check_device_dev_mode_and_ddi,
    check_host_platform,
    check_physical_devices,
    check_simctl,
    run_doctor,
)
from amplifier_module_tool_ios_inspector.runner import CommandResult, CommandRunner

from .conftest import FakeRunner

UDID = "00008030-0000000000000000"


def _runner_with(
    responses: dict[tuple, CommandResult], default: CommandResult | None = None
) -> CommandRunner:
    keyed = {tuple(k): v for k, v in responses.items()}
    fake = FakeRunner(responses=keyed, default=default)
    return CommandRunner(_runner=fake)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def test_check_host_platform_ok_on_darwin() -> None:
    runner = _runner_with(
        {
            ("uname", "-s"): CommandResult(
                args=[], returncode=0, stdout="Darwin\n", stderr=""
            )
        }
    )
    result = check_host_platform(runner)
    assert result["status"] == "ok"


def test_check_host_platform_fail_on_linux() -> None:
    runner = _runner_with(
        {
            ("uname", "-s"): CommandResult(
                args=[], returncode=0, stdout="Linux\n", stderr=""
            )
        }
    )
    result = check_host_platform(runner)
    assert result["status"] == "fail"
    assert "Darwin" in result["detail"]


def test_check_developer_dir_ok() -> None:
    dev_dir = "/Applications/Xcode.app/Contents/Developer"
    runner = _runner_with(
        {
            ("test", "-d", dev_dir): CommandResult(
                args=[], returncode=0, stdout="", stderr=""
            )
        }
    )
    result = check_developer_dir(runner, dev_dir)
    assert result["status"] == "ok"


def test_check_developer_dir_fail_when_missing() -> None:
    dev_dir = "/Applications/Xcode.app/Contents/Developer"
    runner = _runner_with(
        {
            ("test", "-d", dev_dir): CommandResult(
                args=[], returncode=1, stdout="", stderr=""
            )
        }
    )
    result = check_developer_dir(runner, dev_dir)
    assert result["status"] == "fail"
    assert result["remediation"] is not None


def test_check_simctl_ok() -> None:
    runner = _runner_with(
        {
            ("xcrun", "simctl", "list", "devices", "booted"): CommandResult(
                args=[], returncode=0, stdout="== Devices ==\n", stderr=""
            )
        }
    )
    result = check_simctl(runner)
    assert result["status"] == "ok"


def test_check_simctl_fail() -> None:
    runner = _runner_with(
        {
            ("xcrun", "simctl", "list", "devices", "booted"): CommandResult(
                args=[], returncode=1, stdout="", stderr="not found"
            )
        }
    )
    result = check_simctl(runner)
    assert result["status"] == "fail"


def test_check_axe_ok_when_which_resolves(monkeypatch) -> None:
    # `CommandRunner.which()` calls `shutil.which` directly for the local
    # (non-ssh) case -- it does not go through the injectable `_runner`.
    runner = CommandRunner()
    monkeypatch.setattr(runner, "which", lambda name: "/opt/homebrew/bin/axe")
    result = check_axe(runner)
    assert result["status"] == "ok"
    assert "axe" in result["detail"]


def test_check_axe_fail_when_not_found(monkeypatch) -> None:
    runner = CommandRunner()
    monkeypatch.setattr(runner, "which", lambda name: None)
    result = check_axe(runner)
    assert result["status"] == "fail"
    assert "brew install" in result["remediation"]


def test_check_physical_devices_warn_with_no_devices_names_hubs() -> None:
    runner = _runner_with(
        {
            ("idevice_id", "-l"): CommandResult(
                args=[], returncode=0, stdout="", stderr=""
            ),
            ("ioreg", "-rc", "IOUSBHostDevice"): CommandResult(
                args=[],
                returncode=0,
                stdout='    "USB Product Name" = "USB-C Multiport Adapter"\n',
                stderr="",
            ),
        }
    )
    result = check_physical_devices(runner)
    assert result["status"] == "warn"
    assert "ADAPTER" in result["remediation"]
    assert "Multiport Adapter" in result["detail"]


def test_check_physical_devices_ok_with_devices() -> None:
    runner = _runner_with(
        {
            ("idevice_id", "-l"): CommandResult(
                args=[], returncode=0, stdout=f"{UDID}\n", stderr=""
            )
        }
    )
    result = check_physical_devices(runner)
    assert result["status"] == "ok"
    assert UDID in result["detail"]


# ---------------------------------------------------------------------------
# Per-device: Developer Mode + passcode awareness + DDI gap
# ---------------------------------------------------------------------------


def _device_info_responses(
    *, version: str, devmode: str = "false"
) -> dict[tuple, CommandResult]:
    return {
        ("ideviceinfo", "-u", UDID, "-k", "ProductVersion"): CommandResult(
            args=[], returncode=0, stdout=f"{version}\n", stderr=""
        ),
        ("ideviceinfo", "-u", UDID, "-k", "ProductType"): CommandResult(
            args=[], returncode=0, stdout="iPhone10,6\n", stderr=""
        ),
        ("ideviceinfo", "-u", UDID, "-k", "DeviceName"): CommandResult(
            args=[], returncode=0, stdout="Test iPhone\n", stderr=""
        ),
        ("ideviceinfo", "-u", UDID, "-k", "CPUArchitecture"): CommandResult(
            args=[], returncode=0, stdout="arm64\n", stderr=""
        ),
        (
            "ideviceinfo",
            "-u",
            UDID,
            "-q",
            "com.apple.security.mac.amfi",
            "-k",
            "DeveloperModeStatus",
        ): CommandResult(args=[], returncode=0, stdout=f"{devmode}\n", stderr=""),
    }


def test_check_device_dev_mode_warns_when_not_enabled_and_mentions_passcode_guidance() -> (
    None
):
    responses = _device_info_responses(version="16.4", devmode="false")
    responses[
        (
            "ls",
            "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/DeviceSupport",
        )
    ] = CommandResult(args=[], returncode=0, stdout="15.0\n15.1\n16.4\n", stderr="")
    runner = _runner_with(responses)
    result = check_device_dev_mode_and_ddi(
        runner, UDID, "/Applications/Xcode.app/Contents/Developer"
    )
    assert result["status"] == "warn"
    assert "passcode" in result["remediation"].lower()
    # The temporary-disable-then-restore guidance must appear in the SAME
    # remediation text, not split across two separate messages.
    assert "temporarily" in result["remediation"].lower()
    assert "back on" in result["remediation"].lower()


def test_check_device_dev_mode_ok_when_enabled() -> None:
    responses = _device_info_responses(version="16.4", devmode="true")
    responses[
        (
            "ls",
            "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/DeviceSupport",
        )
    ] = CommandResult(args=[], returncode=0, stdout="16.4\n", stderr="")
    runner = _runner_with(responses)
    result = check_device_dev_mode_and_ddi(
        runner, UDID, "/Applications/Xcode.app/Contents/Developer"
    )
    assert result["status"] == "ok"


def test_check_device_ddi_gap_fails_when_device_newer_than_all_available() -> None:
    """Xcode 26 ships DDIs 15.0-16.4 only; a 16.7.16 device has NO exact
    match and IS covered by 'nearest below' -- but if NOTHING available is
    <= the device version (e.g. device is OLDER than the oldest shipped
    DDI, a contrived but structurally valid case), doctor must fail and
    name the available versions."""
    responses = _device_info_responses(version="14.0", devmode="true")
    responses[
        (
            "ls",
            "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/DeviceSupport",
        )
    ] = CommandResult(args=[], returncode=0, stdout="15.0\n15.1\n16.4\n", stderr="")
    runner = _runner_with(responses)
    result = check_device_dev_mode_and_ddi(
        runner, UDID, "/Applications/Xcode.app/Contents/Developer"
    )
    assert result["status"] == "fail"
    assert "15.0" in result["detail"] or "15.0" in result["remediation"]


def test_check_device_ddi_nearest_below_is_ok_not_fail() -> None:
    """Measured live: Xcode 26's 16.4 DDI mounted successfully against a
    16.7.16 device -- this is a fine (ok-status) informational note, not a
    failure."""
    responses = _device_info_responses(version="16.7.16", devmode="true")
    responses[
        (
            "ls",
            "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/DeviceSupport",
        )
    ] = CommandResult(args=[], returncode=0, stdout="15.0\n15.1\n16.4\n", stderr="")
    runner = _runner_with(responses)
    result = check_device_dev_mode_and_ddi(
        runner, UDID, "/Applications/Xcode.app/Contents/Developer"
    )
    assert result["status"] == "ok"
    assert "16.4" in result["detail"]


# ---------------------------------------------------------------------------
# run_doctor -- never stops at first failure, always returns a report
# ---------------------------------------------------------------------------


def test_run_doctor_never_raises_and_always_returns_report() -> None:
    # run_doctor() builds its own real CommandRunner internally (it isn't
    # injectable at this level) -- every command against this test host
    # either succeeds or fails, but doctor must assemble a complete report
    # either way, never raising or stopping early.
    report = run_doctor({})
    assert isinstance(report, dict)
    assert "ready" in report
    assert isinstance(report["checks"], list)
    assert len(report["checks"]) >= 8
    assert isinstance(report["summary"], str)
    for check in report["checks"]:
        assert check["status"] in ("ok", "warn", "fail")


def test_run_doctor_crash_backstop_never_raises(monkeypatch) -> None:
    import amplifier_module_tool_ios_inspector.doctor as doctor_mod

    def _boom(config):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(doctor_mod, "_run_doctor_impl", _boom)
    report = doctor_mod.run_doctor({})
    assert report["ready"] is False
    assert "crashed" in report["summary"]

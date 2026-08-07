"""Tests for device.py -- physical-device tier: DDI version resolution,
passcode-blocker error transformation, and idempotent DDI mounting. All
against a FakeRunner -- no real device required."""

from __future__ import annotations

import pytest
from amplifier_module_tool_ios_inspector.device import (
    DeviceError,
    device_enable_devmode,
    device_mount_ddi,
    list_available_ddi_versions,
    list_physical_devices,
    parse_ios_version,
    resolve_nearest_ddi,
)
from amplifier_module_tool_ios_inspector.runner import CommandResult, CommandRunner

from .conftest import FakeRunner

UDID = "00008030-0000000000000000"
DEV_DIR = "/Applications/Xcode.app/Contents/Developer"


def _runner_with(responses: dict[tuple, CommandResult]) -> CommandRunner:
    keyed = {tuple(k): v for k, v in responses.items()}
    return CommandRunner(_runner=FakeRunner(responses=keyed))


# ---------------------------------------------------------------------------
# Version parsing + nearest-DDI resolution
# ---------------------------------------------------------------------------


def test_parse_ios_version_full() -> None:
    assert parse_ios_version("16.7.16") == (16, 7, 16)


def test_parse_ios_version_short() -> None:
    assert parse_ios_version("16.4") == (16, 4)


def test_resolve_nearest_ddi_exact_match() -> None:
    chosen, exact = resolve_nearest_ddi(["15.0", "16.4"], "16.4")
    assert chosen == "16.4"
    assert exact is True


def test_resolve_nearest_ddi_nearest_below() -> None:
    """The exact scenario measured live: Xcode 26 ships no 16.7 image; the
    16.4 image mounts successfully against a 16.7.16 device anyway."""
    chosen, exact = resolve_nearest_ddi(["15.0", "15.1", "16.4"], "16.7.16")
    assert chosen == "16.4"
    assert exact is False


def test_resolve_nearest_ddi_none_when_device_older_than_everything() -> None:
    chosen, exact = resolve_nearest_ddi(["15.0", "16.4"], "14.0")
    assert chosen is None
    assert exact is False


def test_resolve_nearest_ddi_none_when_no_versions_available() -> None:
    chosen, exact = resolve_nearest_ddi([], "16.4")
    assert chosen is None
    assert exact is False


def test_list_available_ddi_versions_sorted_numerically() -> None:
    runner = _runner_with(
        {
            (
                "ls",
                f"{DEV_DIR}/Platforms/iPhoneOS.platform/DeviceSupport",
            ): CommandResult(
                args=[], returncode=0, stdout="16.4\n15.0\n9.0\n15.1\n", stderr=""
            )
        }
    )
    versions = list_available_ddi_versions(runner, DEV_DIR)
    assert versions == ["9.0", "15.0", "15.1", "16.4"]


def test_list_available_ddi_versions_empty_on_failure() -> None:
    runner = _runner_with(
        {
            (
                "ls",
                f"{DEV_DIR}/Platforms/iPhoneOS.platform/DeviceSupport",
            ): CommandResult(
                args=[], returncode=1, stdout="", stderr="no such directory"
            )
        }
    )
    assert list_available_ddi_versions(runner, DEV_DIR) == []


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_list_physical_devices_parses_one_per_line() -> None:
    runner = _runner_with(
        {
            ("idevice_id", "-l"): CommandResult(
                args=[], returncode=0, stdout=f"{UDID}\n", stderr=""
            )
        }
    )
    devices = list_physical_devices(runner)
    assert devices == [{"udid": UDID, "backend": "device"}]


def test_list_physical_devices_empty_when_none_attached() -> None:
    runner = _runner_with(
        {
            ("idevice_id", "-l"): CommandResult(
                args=[], returncode=0, stdout="", stderr=""
            )
        }
    )
    assert list_physical_devices(runner) == []


def test_list_physical_devices_raises_on_command_failure() -> None:
    runner = _runner_with(
        {
            ("idevice_id", "-l"): CommandResult(
                args=[], returncode=1, stdout="", stderr="not found"
            )
        }
    )
    with pytest.raises(DeviceError):
        list_physical_devices(runner)


# ---------------------------------------------------------------------------
# device_enable_devmode -- the passcode-blocker structured error
# ---------------------------------------------------------------------------


def test_device_enable_devmode_success() -> None:
    runner = _runner_with(
        {
            (
                "pymobiledevice3",
                "amfi",
                "enable-developer-mode",
                "--udid",
                UDID,
            ): CommandResult(
                args=[], returncode=0, stdout="Developer Mode enabled\n", stderr=""
            )
        }
    )
    result = device_enable_devmode(runner, "pymobiledevice3", UDID)
    assert result["udid"] == UDID


def test_device_enable_devmode_passcode_blocker_wording() -> None:
    """The exact undocumented failure from the design doc: 'Cannot enable
    developer-mode when passcode is set.' The resulting error must state,
    in the SAME message, that the change is temporary and must be restored
    immediately -- never a bare 'turn off your passcode'."""
    runner = _runner_with(
        {
            (
                "pymobiledevice3",
                "amfi",
                "enable-developer-mode",
                "--udid",
                UDID,
            ): CommandResult(
                args=[],
                returncode=1,
                stdout="",
                stderr="Cannot enable developer-mode when passcode is set.",
            )
        }
    )
    with pytest.raises(DeviceError) as exc_info:
        device_enable_devmode(runner, "pymobiledevice3", UDID)
    message = str(exc_info.value).lower()
    assert exc_info.value.extra["passcode_blocker"] is True
    assert "temporarily" in message
    assert "back on" in message
    # The guidance rule from the design doc: never a bare "turn off your
    # passcode" -- the restore instruction must be in the SAME message.
    assert "turn" in message and "passcode" in message


def test_device_enable_devmode_other_failure_is_not_flagged_as_passcode() -> None:
    runner = _runner_with(
        {
            (
                "pymobiledevice3",
                "amfi",
                "enable-developer-mode",
                "--udid",
                UDID,
            ): CommandResult(
                args=[], returncode=1, stdout="", stderr="device disconnected"
            )
        }
    )
    with pytest.raises(DeviceError) as exc_info:
        device_enable_devmode(runner, "pymobiledevice3", UDID)
    assert exc_info.value.extra["passcode_blocker"] is False


# ---------------------------------------------------------------------------
# device_mount_ddi
# ---------------------------------------------------------------------------


def test_device_mount_ddi_already_mounted_is_idempotent() -> None:
    runner = _runner_with(
        {
            ("ideviceimagemounter", "-u", UDID, "list"): CommandResult(
                args=[], returncode=0, stdout="ImageSignature[0] = ...\n", stderr=""
            )
        }
    )
    result = device_mount_ddi(runner, UDID, developer_dir=DEV_DIR)
    assert result["already_mounted"] is True


def test_device_mount_ddi_mounts_nearest_version() -> None:
    responses = {
        ("ideviceimagemounter", "-u", UDID, "list"): CommandResult(
            args=[], returncode=0, stdout="", stderr=""
        ),
        ("ideviceinfo", "-u", UDID, "-k", "ProductVersion"): CommandResult(
            args=[], returncode=0, stdout="16.7.16\n", stderr=""
        ),
        ("ideviceinfo", "-u", UDID, "-k", "ProductType"): CommandResult(
            args=[], returncode=0, stdout="iPhone10,6\n", stderr=""
        ),
        ("ideviceinfo", "-u", UDID, "-k", "DeviceName"): CommandResult(
            args=[], returncode=0, stdout="Test\n", stderr=""
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
        ): CommandResult(args=[], returncode=0, stdout="true\n", stderr=""),
        ("ls", f"{DEV_DIR}/Platforms/iPhoneOS.platform/DeviceSupport"): CommandResult(
            args=[], returncode=0, stdout="15.0\n16.4\n", stderr=""
        ),
        (
            "ideviceimagemounter",
            "-u",
            UDID,
            f"{DEV_DIR}/Platforms/iPhoneOS.platform/DeviceSupport/16.4/DeveloperDiskImage.dmg",
            f"{DEV_DIR}/Platforms/iPhoneOS.platform/DeviceSupport/16.4/DeveloperDiskImage.dmg.signature",
        ): CommandResult(args=[], returncode=0, stdout="Mounted\n", stderr=""),
    }
    runner = _runner_with(responses)
    result = device_mount_ddi(runner, UDID, developer_dir=DEV_DIR)
    assert result["already_mounted"] is False
    assert result["ddi_version"] == "16.4"
    assert result["exact_version_match"] is False


def test_device_mount_ddi_raises_when_no_ddi_available() -> None:
    responses = {
        ("ideviceimagemounter", "-u", UDID, "list"): CommandResult(
            args=[], returncode=0, stdout="", stderr=""
        ),
        ("ideviceinfo", "-u", UDID, "-k", "ProductVersion"): CommandResult(
            args=[], returncode=0, stdout="14.0\n", stderr=""
        ),
        ("ideviceinfo", "-u", UDID, "-k", "ProductType"): CommandResult(
            args=[], returncode=0, stdout="iPhone10,6\n", stderr=""
        ),
        ("ideviceinfo", "-u", UDID, "-k", "DeviceName"): CommandResult(
            args=[], returncode=0, stdout="Test\n", stderr=""
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
        ): CommandResult(args=[], returncode=0, stdout="true\n", stderr=""),
        ("ls", f"{DEV_DIR}/Platforms/iPhoneOS.platform/DeviceSupport"): CommandResult(
            args=[], returncode=0, stdout="15.0\n16.4\n", stderr=""
        ),
    }
    runner = _runner_with(responses)
    with pytest.raises(DeviceError) as exc_info:
        device_mount_ddi(runner, UDID, developer_dir=DEV_DIR)
    assert exc_info.value.extra["available_versions"] == ["15.0", "16.4"]

"""`doctor` -- full host readiness report. Every check runs even if an
earlier one fails; the whole point is to show everything wrong at once, so
`ready` is the only thing that reflects failure, never an early return.

Checks: host is macOS; `DEVELOPER_DIR`/Xcode present; `simctl` works; `axe`
installed; `pymobiledevice3` installed; available runtimes; booted
simulators; physical devices; per-device Developer Mode; passcode blocker
awareness; DDI availability vs. each device's iOS version.
"""

from __future__ import annotations

from typing import Any

from .device import (
    device_info,
    diagnose_missing_devices,
    list_available_ddi_versions,
    list_physical_devices,
    resolve_nearest_ddi,
    resolve_pymobiledevice3_binary,
)
from .runner import DEFAULT_DEVELOPER_DIR, DEFAULT_TIMEOUT_S, CommandRunner
from .simctl import list_runtimes, list_simulators

__all__ = ["run_doctor"]


def _check(
    name: str, status: str, detail: str, remediation: str | None
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "remediation": remediation,
    }


def check_host_platform(runner: CommandRunner) -> dict[str, Any]:
    result = runner.run(["uname", "-s"], check_output=False)
    system = result.stdout.strip() if result.ok else None
    if system != "Darwin":
        return _check(
            "host_platform",
            "fail",
            f"Target host reports {system or 'unknown'!r}, not Darwin (macOS).",
            "This tool's simulator/device backends require a macOS host. If driving a "
            "remote Mac, verify 'ssh_host' points at one.",
        )
    return _check("host_platform", "ok", "Target host is macOS.", None)


def check_developer_dir(runner: CommandRunner, developer_dir: str) -> dict[str, Any]:
    result = runner.run(["test", "-d", developer_dir], check_output=False)
    if not result.ok:
        return _check(
            "developer_dir",
            "fail",
            f"{developer_dir} does not exist.",
            "Install Xcode, or point tool config 'developer_dir' at the correct "
            "Contents/Developer path. Do not rely on `xcode-select` alone -- if it "
            "points at CommandLineTools, simctl silently appears missing.",
        )
    return _check("developer_dir", "ok", f"{developer_dir} exists.", None)


def check_simctl(runner: CommandRunner) -> dict[str, Any]:
    result = runner.run(
        ["xcrun", "simctl", "list", "devices", "booted"], check_output=False
    )
    if not result.ok:
        return _check(
            "simctl",
            "fail",
            f"`xcrun simctl list devices booted` failed: "
            f"{(result.stderr or result.stdout).strip()}",
            "Verify DEVELOPER_DIR/Xcode (see 'developer_dir' check above). This tool "
            "sets DEVELOPER_DIR on every command it runs -- no `sudo xcode-select` "
            "needed.",
        )
    return _check("simctl", "ok", "simctl is reachable and responds.", None)


def check_axe(runner: CommandRunner) -> dict[str, Any]:
    path = runner.which("axe")
    if not path:
        return _check(
            "axe",
            "fail",
            "'axe' not found on the target host's PATH.",
            "Install: `brew install cameroncooke/axe/axe`. Chosen over idb-companion "
            "because the Homebrew idb build is stale (Aug 2022) and conflicts with "
            "current Xcode.",
        )
    return _check("axe", "ok", f"Resolved at {path}.", None)


def check_pymobiledevice3(
    runner: CommandRunner, config: dict[str, Any]
) -> dict[str, Any]:
    try:
        path = resolve_pymobiledevice3_binary(runner, config)
    except Exception as exc:  # noqa: BLE001 -- doctor must never raise
        return _check(
            "pymobiledevice3",
            "fail",
            str(exc),
            "Install: `pip install --user pymobiledevice3`.",
        )
    return _check("pymobiledevice3", "ok", f"Resolved at {path}.", None)


def check_runtimes(runner: CommandRunner) -> dict[str, Any]:
    try:
        runtimes = list_runtimes(runner)
    except Exception as exc:  # noqa: BLE001
        return _check(
            "runtimes",
            "warn",
            f"Could not list simulator runtimes: {exc}",
            "Ensure Xcode is installed and simctl is reachable (see 'simctl' check).",
        )
    if not runtimes:
        return _check(
            "runtimes",
            "warn",
            "No simulator runtimes installed.",
            "Install one via Xcode > Settings > Platforms, or "
            "`xcodebuild -downloadPlatform iOS`.",
        )
    names = ", ".join(r.get("name", "?") for r in runtimes)
    return _check("runtimes", "ok", f"Runtimes: {names}.", None)


def check_booted_simulators(runner: CommandRunner) -> dict[str, Any]:
    try:
        sims = list_simulators(runner)
    except Exception as exc:  # noqa: BLE001
        return _check(
            "booted_simulators",
            "warn",
            f"Could not list simulators: {exc}",
            "See 'simctl' check.",
        )
    booted = [s for s in sims if s.get("state") == "Booted"]
    if not booted:
        return _check(
            "booted_simulators",
            "ok",
            "No simulators currently booted (this is fine -- 'boot' will start one).",
            None,
        )
    names = ", ".join(f"{s.get('name')} ({s.get('udid')})" for s in booted)
    return _check("booted_simulators", "ok", f"Booted: {names}.", None)


def check_physical_devices(runner: CommandRunner) -> dict[str, Any]:
    try:
        devices = list_physical_devices(runner)
    except Exception as exc:  # noqa: BLE001
        return _check(
            "physical_devices",
            "warn",
            f"Could not list physical devices: {exc}",
            "Ensure libimobiledevice is installed (`idevice_id`).",
        )
    if not devices:
        diag = diagnose_missing_devices(runner)
        hub_like = diag.get("hub_like") or []
        if hub_like:
            detail = (
                "No physical device found. USB hub/dock/adapter(s) ARE visible: "
                f"{', '.join(hub_like)}."
            )
            remediation = (
                "Re-seat the ADAPTER (hub/dock/multiport adapter), not the device -- "
                "the hub can hold stale downstream port state that unplugging the "
                "device alone does not clear."
            )
        else:
            detail = (
                "No physical device found, and no USB hubs/adapters visible either."
            )
            remediation = "Connect a device via cable and unlock it."
        return _check("physical_devices", "warn", detail, remediation)
    udids = ", ".join(d["udid"] for d in devices)
    return _check("physical_devices", "ok", f"Devices: {udids}.", None)


def check_device_dev_mode_and_ddi(
    runner: CommandRunner, udid: str, developer_dir: str
) -> dict[str, Any]:
    """Per-device: Developer Mode status, plus DDI availability vs. this
    device's iOS version. Combined into one check because both need the
    device's `ProductVersion` (a single `device_info` call)."""
    name = f"device_{udid}"
    try:
        info = device_info(runner, udid)
    except Exception as exc:  # noqa: BLE001
        return _check(name, "fail", f"ideviceinfo failed for {udid}: {exc}", None)

    version = info.get("ProductVersion")
    dev_mode_enabled = info.get("developer_mode_enabled")
    details = [f"ProductType={info.get('ProductType')}", f"iOS {version}"]

    if not dev_mode_enabled:
        details.append("Developer Mode: NOT enabled.")
        remediation = (
            "Enable via the 'device_enable_devmode' operation. If it fails with "
            '"Cannot enable developer-mode when passcode is set" (undocumented by '
            "Apple): turn the passcode off TEMPORARILY, enable Developer Mode, then "
            "turn the passcode back on immediately -- it is only needed off for that "
            "one step."
        )
        status = "warn"
    else:
        details.append("Developer Mode: enabled.")
        remediation = None
        status = "ok"

    if version:
        available = list_available_ddi_versions(runner, developer_dir)
        chosen, exact = resolve_nearest_ddi(available, version)
        if chosen is None:
            details.append(
                f"No Developer Disk Image available for iOS {version} under this Xcode "
                f"(ships: {available or 'none'})."
            )
            remediation = ((remediation + " ") if remediation else "") + (
                f"Install an older Xcode that still ships a DDI for iOS {version} -- "
                "newer Xcode is not automatically better here; each release drops "
                "older DDIs."
            )
            status = "fail" if status == "ok" else status
        elif not exact:
            details.append(
                f"Nearest available DDI is {chosen} (device is {version}); the nearest "
                "older image is expected to mount successfully."
            )

    return _check(name, status, " ".join(details), remediation)


def _run_doctor_impl(config: dict[str, Any]) -> dict[str, Any]:
    developer_dir = str(config.get("developer_dir") or DEFAULT_DEVELOPER_DIR)
    runner = CommandRunner(
        ssh_host=config.get("ssh_host"),
        developer_dir=developer_dir,
        default_timeout=float(config.get("command_timeout_s", DEFAULT_TIMEOUT_S)),
    )

    checks: list[dict[str, Any]] = []

    def _safe(fn: Any, name: str) -> dict[str, Any]:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 -- doctor must never raise
            return _check(
                name, "fail", f"Check crashed: {exc}", "This is a bug; report it."
            )

    checks.append(_safe(lambda: check_host_platform(runner), "host_platform"))
    checks.append(
        _safe(lambda: check_developer_dir(runner, developer_dir), "developer_dir")
    )
    checks.append(_safe(lambda: check_simctl(runner), "simctl"))
    checks.append(_safe(lambda: check_axe(runner), "axe"))
    checks.append(
        _safe(lambda: check_pymobiledevice3(runner, config), "pymobiledevice3")
    )
    checks.append(_safe(lambda: check_runtimes(runner), "runtimes"))
    checks.append(_safe(lambda: check_booted_simulators(runner), "booted_simulators"))
    checks.append(_safe(lambda: check_physical_devices(runner), "physical_devices"))

    devices_check = checks[-1]
    if devices_check["status"] == "ok":
        try:
            devices = list_physical_devices(runner)
        except Exception:  # noqa: BLE001
            devices = []
        for device in devices:
            udid = device["udid"]
            checks.append(
                _safe(
                    lambda udid=udid: check_device_dev_mode_and_ddi(
                        runner, udid, developer_dir
                    ),
                    f"device_{udid}",
                )
            )

    failing = [c for c in checks if c["status"] == "fail"]
    warning = [c for c in checks if c["status"] == "warn"]
    ready = not failing

    if failing:
        first = failing[0]
        summary = f"Fix first: {first['name']} -- {first['detail']}"
    elif warning:
        first = warning[0]
        summary = f"Ready, but review {first['name']}: {first['detail']}"
    else:
        summary = "All checks passed."

    return {"ready": ready, "checks": checks, "summary": summary}


def run_doctor(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run every host-readiness check and return a full report.

    Never raises, and never stops at the first failure. `ready` is true iff
    no check reported `fail`. The tool-envelope `success` field is always
    true for this operation -- a machine with problems is a successful
    diagnosis, not a tool error.
    """
    config = config or {}
    try:
        return _run_doctor_impl(config)
    except Exception as exc:  # noqa: BLE001 -- absolute backstop
        return {
            "ready": False,
            "checks": [
                _check(
                    "doctor",
                    "fail",
                    f"doctor crashed unexpectedly: {exc}",
                    "This is a bug in the doctor orchestration itself; report it.",
                )
            ],
            "summary": f"doctor crashed unexpectedly: {exc}",
        }

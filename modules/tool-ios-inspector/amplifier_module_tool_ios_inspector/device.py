"""Physical-device ("free") tier -- `libimobiledevice` for identity/transport,
`pymobiledevice3` for anything that must actually reach the device.

That split is deliberate, not a preference (see
`docs/designs/ios-tester-design.md`, "A tool's error is not the device's
error"): `libimobiledevice` checks `DeveloperModeStatus` *locally* and
refuses before sending anything, so no Developer Mode prompt ever appears on
the phone. `pymobiledevice3` actually asks the device and returns the real
cause. When a precondition can be answered locally *or* by the device, this
module prefers the device.

Commands run live against a real iPhone X (iOS 16.7.16) before this module
was written:

    idevice_id -l
    ideviceinfo -u <UDID> -k ProductVersion|ProductType|DeviceName|CPUArchitecture
    ideviceinfo -u <UDID> -q com.apple.security.mac.amfi -k DeveloperModeStatus
    ~/.local/bin/pymobiledevice3 usbmux list
    ~/.local/bin/pymobiledevice3 amfi enable-developer-mode
    ~/.local/bin/pymobiledevice3 amfi developer-mode-status
    ~/.local/bin/pymobiledevice3 developer accessibility list-items   (JSON, NO GEOMETRY)
    ideviceimagemounter -u <UDID> <DDI.dmg> <DDI.dmg.signature>
    ideviceimagemounter -u <UDID> list
    idevicescreenshot -u <UDID> out.png             (requires DDI mounted)

`--udid <UDID>` on the two `pymobiledevice3` subcommands above (`amfi ...`,
`developer accessibility list-items`) was NOT literally present in the
captured transcript -- only one device was attached during that session.
`--udid` is documented, standard pymobiledevice3 global device targeting; it
is applied here so this tool behaves correctly with more than one device
attached, but that specific combination was not independently re-run.

The critical, load-bearing limitation this module encodes: `device_elements`
(the free tier's UI listing) carries NO geometry. Its keys are only
`caption`, `estimated_uid`, `platform_identifier`, `spoken_description` -- a
grep of the full payload for `frame|rect|bounds|x|y|width|height` returns
zero matches. `tap` on `backend="device"` MUST refuse (see `__init__.py`)
rather than guess a coordinate from a caption.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .runner import CommandRunner

__all__ = [
    "DDI_DEVICE_SUPPORT_SUBPATH",
    "DEVELOPER_MODE_PASSCODE_MARKER",
    "DeviceError",
    "device_apps",
    "device_elements",
    "device_enable_devmode",
    "device_info",
    "device_mount_ddi",
    "device_screenshot",
    "list_available_ddi_versions",
    "list_physical_devices",
    "parse_ios_version",
    "resolve_nearest_ddi",
    "resolve_pymobiledevice3_binary",
]

DDI_DEVICE_SUPPORT_SUBPATH = "Platforms/iPhoneOS.platform/DeviceSupport"

# The exact phrase iOS/pymobiledevice3 reports when Developer Mode cannot be
# toggled because a passcode is set -- undocumented by Apple, cost six
# rounds to discover (see design doc). Checked on message content, never
# inferred any other way.
DEVELOPER_MODE_PASSCODE_MARKER = "passcode"

_INFO_KEYS = ("ProductVersion", "ProductType", "DeviceName", "CPUArchitecture")


class DeviceError(RuntimeError):
    """Raised for physical-device operation failures."""

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.extra: dict[str, Any] = extra


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


def resolve_pymobiledevice3_binary(
    runner: CommandRunner, config: dict[str, Any] | None = None
) -> str:
    """Resolve the `pymobiledevice3` binary on the TARGET host (local or
    remote, via `runner`).

    Probe order: config['pymobiledevice3_path'] override,
    `~/.local/bin/pymobiledevice3` (the path this was verified against),
    then PATH.

    Raises:
        DeviceError: no candidate resolves.
    """
    config = config or {}
    override = config.get("pymobiledevice3_path")
    if override:
        return str(override)

    home_candidate = "~/.local/bin/pymobiledevice3"
    check = runner.run(["test", "-x", home_candidate], check_output=False)
    if check.ok:
        return home_candidate

    on_path = runner.which("pymobiledevice3")
    if on_path:
        return on_path

    raise DeviceError(
        "Could not resolve a working pymobiledevice3 binary on the target host. "
        f"Probed: config override, {home_candidate}, and 'pymobiledevice3' on PATH. "
        "Install it (`pip install --user pymobiledevice3`) or set tool config "
        "'pymobiledevice3_path'."
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def list_physical_devices(runner: CommandRunner) -> list[dict[str, Any]]:
    """`idevice_id -l` -- one UDID per line, one physical device per line."""
    result = runner.run(["idevice_id", "-l"])
    if not result.ok:
        raise DeviceError(
            f"idevice_id -l failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}"
        )
    udids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return [{"udid": udid, "backend": "device"} for udid in udids]


def diagnose_missing_devices(runner: CommandRunner) -> dict[str, Any]:
    """When no physical device is found, name any USB hubs/adapters seen so
    the caller can be told to re-seat the *adapter*, not the device (a
    device behind a hub/dock/multiport adapter can vanish because the hub
    holds stale downstream port state that unplugging the device does not
    clear -- see design doc).

    Never raises -- this is diagnostic-only, folded into `doctor` and
    `list_targets`.
    """
    result = runner.run(["ioreg", "-rc", "IOUSBHostDevice"], check_output=False)
    if not result.ok:
        return {"hubs_seen": [], "note": "ioreg probe failed; cannot diagnose."}
    names = []
    for line in result.stdout.splitlines():
        if '"USB Product Name"' not in line:
            continue
        # Line shape: `    "USB Product Name" = "Some Hub Name"`
        parts = line.split("=", 1)
        if len(parts) == 2:
            names.append(parts[1].strip().strip('"'))
    hub_like = [
        n
        for n in names
        if "hub" in n.lower() or "adapter" in n.lower() or "dock" in n.lower()
    ]
    return {"hubs_seen": names, "hub_like": hub_like}


# ---------------------------------------------------------------------------
# Info + Developer Mode
# ---------------------------------------------------------------------------


def device_info(runner: CommandRunner, udid: str) -> dict[str, Any]:
    """`ideviceinfo -u <UDID> -k <KEY>` for each of `_INFO_KEYS`, plus
    `ideviceinfo -u <UDID> -q com.apple.security.mac.amfi -k
    DeveloperModeStatus`. Missing/failed individual keys are reported as
    `None`, not a hard failure -- a device that answers SOME keys but not
    others is still informative."""
    info: dict[str, Any] = {"udid": udid}
    for key in _INFO_KEYS:
        result = runner.run(["ideviceinfo", "-u", udid, "-k", key], check_output=False)
        info[key] = (
            result.stdout.strip() if result.ok and result.stdout.strip() else None
        )

    devmode_result = runner.run(
        [
            "ideviceinfo",
            "-u",
            udid,
            "-q",
            "com.apple.security.mac.amfi",
            "-k",
            "DeveloperModeStatus",
        ],
        check_output=False,
    )
    raw_status = devmode_result.stdout.strip() if devmode_result.ok else None
    info["developer_mode_status"] = raw_status
    info["developer_mode_enabled"] = (raw_status or "").lower() == "true"
    return info


def device_enable_devmode(
    runner: CommandRunner, pymobiledevice3_path: str, udid: str
) -> dict[str, Any]:
    """`pymobiledevice3 amfi enable-developer-mode` -- prefers asking the
    DEVICE (via pymobiledevice3) rather than checking a local flag, because
    the device's answer is the real one (see module docstring).

    Raises:
        DeviceError: the command failed. If the failure is the passcode
            blocker, `.extra['passcode_blocker'] = True` and the message
            states, in the SAME breath, that the change is temporary and
            must be reverted immediately after -- never a bare "turn off
            your passcode" with no stated end (see design doc's explicit
            guidance rule).
    """
    result = runner.run(
        [pymobiledevice3_path, "amfi", "enable-developer-mode", "--udid", udid],
        check_output=False,
    )
    combined = f"{result.stdout}\n{result.stderr}".lower()
    if not result.ok:
        if DEVELOPER_MODE_PASSCODE_MARKER in combined:
            raise DeviceError(
                "Cannot enable Developer Mode while a passcode is set on this device. "
                "Turn the passcode off TEMPORARILY -- as soon as Developer Mode is "
                "enabled, turn the passcode back on immediately; it is only needed off "
                "for this one step, and you will be prompted to restore it right after.",
                udid=udid,
                passcode_blocker=True,
                raw_stdout=result.stdout,
                raw_stderr=result.stderr,
            )
        raise DeviceError(
            f"pymobiledevice3 amfi enable-developer-mode on {udid!r} failed (exit "
            f"{result.returncode}): {(result.stderr or result.stdout).strip()}",
            udid=udid,
            passcode_blocker=False,
        )
    return {
        "udid": udid,
        "status": "enabled_or_pending_reboot",
        "stdout": result.stdout.strip(),
    }


def device_apps(
    runner: CommandRunner, pymobiledevice3_path: str, udid: str
) -> dict[str, Any]:
    """List installed apps via `pymobiledevice3 apps list --udid <UDID>`.

    INFERRED: this exact subcommand was not in the captured verified-command
    transcript (which covered `usbmux list`, `amfi ...`, and `developer
    accessibility list-items` only). It follows pymobiledevice3's documented
    `apps list` command shape; flagged here so a caller hitting a surprising
    failure knows to check pymobiledevice3's own `--help` for this device's
    installed version.
    """
    result = runner.run(
        [pymobiledevice3_path, "apps", "list", "--udid", udid], check_output=False
    )
    if not result.ok:
        raise DeviceError(
            f"pymobiledevice3 apps list on {udid!r} failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()} -- note: this subcommand's exact "
            "shape was inferred from pymobiledevice3 documentation, not independently "
            "verified in this tool's design pass; check `pymobiledevice3 apps --help` on "
            "the target host if this looks like a syntax mismatch.",
            udid=udid,
        )
    try:
        apps = json.loads(result.stdout)
    except ValueError:
        # Not every pymobiledevice3 version emits JSON for this subcommand
        # by default -- fall back to raw lines rather than failing outright.
        apps = None
    return {
        "udid": udid,
        "apps": apps,
        "raw_stdout": result.stdout if apps is None else None,
    }


def device_elements(
    runner: CommandRunner, pymobiledevice3_path: str, udid: str
) -> dict[str, Any]:
    """VERIFIED: `pymobiledevice3 developer accessibility list-items` --
    JSON, but **NO GEOMETRY**. Full observed key set: `caption`,
    `estimated_uid`, `platform_identifier`, `spoken_description`. This is
    exactly why `tap` refuses on `backend="device"` (see `__init__.py`)."""
    result = runner.run(
        [
            pymobiledevice3_path,
            "developer",
            "accessibility",
            "list-items",
            "--udid",
            udid,
        ],
        check_output=False,
    )
    if not result.ok:
        raise DeviceError(
            f"pymobiledevice3 developer accessibility list-items on {udid!r} failed "
            f"(exit {result.returncode}): {(result.stderr or result.stdout).strip()}",
            udid=udid,
        )
    try:
        items = json.loads(result.stdout)
    except ValueError as exc:
        raise DeviceError(
            f"Failed to parse pymobiledevice3 accessibility list-items JSON: {exc}",
            udid=udid,
        ) from exc
    return {
        "udid": udid,
        "items": items,
        "count": len(items) if isinstance(items, list) else None,
        "note": "No geometry in this payload -- cannot be used to compute a tap point.",
    }


# ---------------------------------------------------------------------------
# Screenshot (requires DDI mounted)
# ---------------------------------------------------------------------------


def device_screenshot(
    runner: CommandRunner, udid: str, local_dest: Path, *, remote_tmp: str
) -> dict[str, Any]:
    """VERIFIED: `idevicescreenshot -u <UDID> <remote_tmp>` -- requires the
    Developer Disk Image (DDI) to be mounted first (see
    `device_mount_ddi`). Fetches the result via the shared `CommandRunner`
    file-transfer path, same as the simulator screenshot op."""
    from .simctl import png_dimensions

    result = runner.run(
        ["idevicescreenshot", "-u", udid, remote_tmp], check_output=False
    )
    if not result.ok:
        combined = f"{result.stdout}\n{result.stderr}".lower()
        hint = ""
        if "disk image" in combined or "developer disk image" in combined:
            hint = " Mount the Developer Disk Image first (see 'device_mount_ddi')."
        raise DeviceError(
            f"idevicescreenshot on {udid!r} failed (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()}.{hint}",
            udid=udid,
        )
    runner.fetch_file(remote_tmp, local_dest)
    data = local_dest.read_bytes()
    dims = png_dimensions(data)
    if dims is None:
        raise DeviceError(
            f"Screenshot at {local_dest} does not look like a PNG -- liveness check failed.",
            udid=udid,
        )
    return {
        "udid": udid,
        "image_path": str(local_dest.resolve()),
        "byte_size": len(data),
        "width": dims[0],
        "height": dims[1],
    }


# ---------------------------------------------------------------------------
# DDI (Developer Disk Image) resolution + mounting
# ---------------------------------------------------------------------------


def parse_ios_version(version: str) -> tuple[int, ...]:
    """Parse an iOS version string (e.g. '16.7.16', '16.4') into a tuple of
    ints for ordering comparisons. Non-numeric trailing components are
    dropped rather than raising -- a version string this tool can't fully
    parse should still compare as "as much as we understood", not crash the
    caller."""
    parts: list[int] = []
    for chunk in version.strip().split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts)


def list_available_ddi_versions(runner: CommandRunner, developer_dir: str) -> list[str]:
    """List the DDI version directories Xcode actually ships, e.g.
    `['15.0', '15.1', ..., '16.4']` -- VERIFIED pattern:
    `<developer_dir>/Platforms/iPhoneOS.platform/DeviceSupport/<ver>/DeveloperDiskImage.dmg`.
    Each release of Xcode ships only a bounded range and drops older ones
    (measured: Xcode 26 ships 15.0-16.4 only) -- this is discovered from
    disk, never hardcoded to a specific range."""
    base = f"{developer_dir}/{DDI_DEVICE_SUPPORT_SUBPATH}"
    result = runner.run(["ls", base], check_output=False)
    if not result.ok:
        return []
    return sorted(
        (line.strip() for line in result.stdout.splitlines() if line.strip()),
        key=parse_ios_version,
    )


def resolve_nearest_ddi(
    available: list[str], device_version: str
) -> tuple[str | None, bool]:
    """Pick the DDI version to use for `device_version`.

    Returns `(chosen_version, exact_match)`. Prefers an exact match; falls
    back to the NEAREST version that is `<=` the device's version (a DDI
    mounts fine against a slightly newer device patch release -- measured
    live: Xcode 26's 16.4 image mounted successfully on a 16.7.16 device).
    Returns `(None, False)` if `available` is empty, or every available
    version is NEWER than the device (an older Xcode is needed instead).
    """
    if not available:
        return (None, False)
    target = parse_ios_version(device_version)
    if device_version in available:
        return (device_version, True)

    candidates = [(v, parse_ios_version(v)) for v in available]
    not_newer = [v for v, parsed in candidates if parsed <= target]
    if not_newer:
        # `available` is sorted ascending -- the last "not newer" entry is
        # the nearest below/equal to the device's version.
        return (not_newer[-1], False)
    return (None, False)


def device_mount_ddi(
    runner: CommandRunner, udid: str, *, developer_dir: str
) -> dict[str, Any]:
    """Mount the Developer Disk Image for `udid`.

    VERIFIED commands: `ideviceimagemounter -u <UDID> list` (idempotency
    check) and `ideviceimagemounter -u <UDID> <dmg> <dmg>.signature` (the
    mount itself). DDI version selection uses `resolve_nearest_ddi` against
    the device's own `ProductVersion` (via `device_info`) -- never assumes
    the newest Xcode-shipped DDI is the right one (newer Xcode is not
    automatically better here: it may ship NO image for this device's iOS
    version at all).

    Raises:
        DeviceError: no DDI directory is available at or below the
            device's version (`.extra['available_versions']` names what
            Xcode does ship, so the caller knows exactly which older Xcode
            to install instead), or the mount command itself failed.
    """
    already = runner.run(
        ["ideviceimagemounter", "-u", udid, "list"], check_output=False
    )
    if already.ok and already.stdout.strip():
        return {
            "udid": udid,
            "already_mounted": True,
            "detail": already.stdout.strip(),
        }

    info = device_info(runner, udid)
    device_version = info.get("ProductVersion")
    if not device_version:
        raise DeviceError(
            f"Could not determine ProductVersion for {udid!r} -- cannot select a DDI.",
            udid=udid,
        )

    available = list_available_ddi_versions(runner, developer_dir)
    chosen, exact = resolve_nearest_ddi(available, device_version)
    if chosen is None:
        raise DeviceError(
            f"No Developer Disk Image at or below iOS {device_version} is available "
            f"under this Xcode (ships: {available or 'none'}). Install an older Xcode "
            "that still carries a DDI for this device's iOS version.",
            udid=udid,
            device_version=device_version,
            available_versions=available,
        )

    ddi_dir = f"{developer_dir}/{DDI_DEVICE_SUPPORT_SUBPATH}/{chosen}"
    dmg_path = f"{ddi_dir}/DeveloperDiskImage.dmg"
    sig_path = f"{dmg_path}.signature"
    mount_result = runner.run(
        ["ideviceimagemounter", "-u", udid, dmg_path, sig_path], check_output=False
    )
    if not mount_result.ok:
        raise DeviceError(
            f"ideviceimagemounter failed mounting {chosen!r} DDI on {udid!r} (exit "
            f"{mount_result.returncode}): {(mount_result.stderr or mount_result.stdout).strip()}",
            udid=udid,
            ddi_version=chosen,
        )
    return {
        "udid": udid,
        "already_mounted": False,
        "device_version": device_version,
        "ddi_version": chosen,
        "exact_version_match": exact,
        "stdout": mount_result.stdout.strip(),
    }

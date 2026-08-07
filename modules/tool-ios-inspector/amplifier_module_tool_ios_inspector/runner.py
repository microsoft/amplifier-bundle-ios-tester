"""Local-vs-remote command execution -- the ONE place this tool decides how a
command actually runs.

The tool normally drives a Mac it runs on directly. It must also be able to
drive a *remote* Mac over SSH (a headless Mac test-runner is a real
deployment shape, not a hypothetical). Every other module in this package
(`simctl.py`, `device.py`, `doctor.py`, `axe.py`) builds plain argv lists as
if they were always running locally; `CommandRunner` is the single seam that
decides whether that argv is exec'd directly or wrapped in
`ssh -o BatchMode=yes <ssh_host> '<cmd>'`. Nothing outside this module ever
constructs an ssh/scp invocation itself.

`DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer` is set on every
command this runner issues -- measured live: this makes `simctl` work with
**no sudo** even when `xcode-select` points at CommandLineTools, where the
documented fix (`sudo xcode-select -s`) needs a password and blocks turnkey
setup.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_DEVELOPER_DIR",
    "DEFAULT_TIMEOUT_S",
    "CommandResult",
    "CommandRunner",
    "CommandTimeoutError",
    "RunnerError",
]

DEFAULT_DEVELOPER_DIR = "/Applications/Xcode.app/Contents/Developer"

# `subprocess.run` timeout default for any single command issued through
# this runner. Individual callers may override per-call.
#
# Measured live: driving a real Mac over `ssh_host` (rather than locally),
# `simctl launch` timed out at the OLD 30.0s default even though the SAME
# command ran directly on the Mac in 1.165s -- SSH round-trip latency plus
# first-run CoreSimulator warm-up work consumed the entire budget. 120s
# gives real headroom for remote operation without being so long that a
# genuinely hung command blocks the caller indefinitely.
DEFAULT_TIMEOUT_S = 120.0


class RunnerError(RuntimeError):
    """Raised when the runner itself cannot execute a command (ssh/scp
    transport failure, binary not found, etc.) -- distinct from the *target*
    command exiting nonzero, which callers observe via `CommandResult.ok`."""

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.extra: dict[str, Any] = extra


class CommandTimeoutError(RunnerError):
    """Raised when a command exceeded its timeout budget and was killed
    before it completed -- structurally DISTINCT from a normal nonzero exit
    or an empty/absent result.

    This exists so a timeout can never be silently reinterpreted downstream
    as "the command ran and returned nothing" (e.g. "no UI present", "no
    output", "screen is empty"). Measured live: over a slow `ssh_host` round
    trip, a timed-out `axe describe-ui` surfaced as "produced no output" --
    indistinguishable from a genuinely empty accessibility tree, when in
    fact the command never got a chance to answer at all. Every
    `CommandTimeoutError` names the exact command and the exact budget (in
    seconds) that was exceeded, so that distinction is never lost.
    """

    def __init__(
        self, message: str, *, argv: list[str], timeout: float, **extra: Any
    ) -> None:
        super().__init__(message, argv=argv, timeout=timeout, **extra)
        self.argv = argv
        self.timeout = timeout


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    # Structural marker for "this command was killed for exceeding its
    # timeout budget" -- set ONLY by the runner layer (never inferred by
    # callers from stderr text). See `CommandTimeoutError`'s docstring for
    # why this must never be conflated with an empty/absent result.
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


RunnerFn = Callable[[list[str], float, dict[str, str] | None], CommandResult]


def _default_subprocess_runner(
    argv: list[str], timeout: float, env: dict[str, str] | None
) -> CommandResult:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial_stdout = exc.stdout
        if isinstance(partial_stdout, bytes):
            partial_stdout = partial_stdout.decode("utf-8", errors="replace")
        partial_stderr = exc.stderr
        if isinstance(partial_stderr, bytes):
            partial_stderr = partial_stderr.decode("utf-8", errors="replace")
        return CommandResult(
            args=argv,
            returncode=-1,
            stdout=partial_stdout or "",
            stderr=(partial_stderr or "")
            + f"\ncommand timed out after {timeout}s: {' '.join(argv)}",
            timed_out=True,
        )
    except FileNotFoundError as exc:
        raise RunnerError(f"Executable not found: {argv[0]!r} ({exc})") from exc
    return CommandResult(
        args=argv, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr
    )


@dataclass
class CommandRunner:
    """Executes commands either directly on this host, or on a remote Mac
    over SSH -- the single seam every other module in this tool funnels
    through.

    `ssh_host` unset (default): commands run locally via `subprocess.run`,
    with `DEVELOPER_DIR` injected into the child's environment.

    `ssh_host` set: every command is executed as
    `ssh -o BatchMode=yes <ssh_host> '<cmd>'`, where `<cmd>` is the caller's
    argv shell-joined and prefixed with an inline `export DEVELOPER_DIR=...;`
    (environment variables set via `env=` on `subprocess.run` have no effect
    over ssh -- they never reach the remote process).
    """

    ssh_host: str | None = None
    developer_dir: str = DEFAULT_DEVELOPER_DIR
    default_timeout: float = DEFAULT_TIMEOUT_S
    _runner: RunnerFn = field(default=_default_subprocess_runner, repr=False)

    @property
    def is_remote(self) -> bool:
        return bool(self.ssh_host)

    # -- Command construction -------------------------------------------

    def build_argv(self, argv: list[str]) -> list[str]:
        """Translate a plain argv into what actually gets exec'd.

        Local: returned unchanged (env carries DEVELOPER_DIR instead).
        Remote: wrapped as `["ssh", "-o", "BatchMode=yes", ssh_host,
        "export DEVELOPER_DIR=<dir>; <shell-quoted argv>"]` -- a single
        remote command string, exactly the shape specified.
        """
        if not self.ssh_host:
            return list(argv)
        remote_cmd = shlex.join(argv)
        full_remote_cmd = (
            f"export DEVELOPER_DIR={shlex.quote(self.developer_dir)}; {remote_cmd}"
        )
        return ["ssh", "-o", "BatchMode=yes", self.ssh_host, full_remote_cmd]

    def run(
        self,
        argv: list[str],
        *,
        timeout: float | None = None,
        check_output: bool = False,
        raise_on_timeout: bool = True,
    ) -> CommandResult:
        """Run `argv` (local exec, or wrapped for ssh -- see `build_argv`).

        Args:
            raise_on_timeout: when True (the default), a command that
                exceeds its timeout budget raises `CommandTimeoutError`
                immediately, from here, before any caller gets a chance to
                treat the (would-be) result as empty/absent. Pass False
                only for the rare case where hitting the timeout IS the
                expected, normal termination condition (e.g. a
                deliberately time-bounded log stream) -- callers doing so
                MUST check `result.timed_out` structurally themselves,
                never by parsing stderr text.

        Raises:
            CommandTimeoutError: the command exceeded its timeout budget
                and `raise_on_timeout` is True (the default). Distinct
                from every other failure mode -- never mistake this for
                an empty/absent result.
            RunnerError: the runner itself failed to invoke the command
                (missing binary, ssh transport failure at the runner
                layer), or `check_output=True` and the *target* command
                exited nonzero. Does NOT raise on a plain nonzero exit
                unless `check_output=True`.
        """
        effective_timeout = timeout if timeout is not None else self.default_timeout
        full_argv = self.build_argv(argv)
        env = (
            None
            if self.ssh_host
            else {**os.environ, "DEVELOPER_DIR": self.developer_dir}
        )
        result = self._runner(full_argv, effective_timeout, env)
        if result.timed_out and raise_on_timeout:
            raise CommandTimeoutError(
                f"Command timed out after {effective_timeout}s (budget exceeded) and "
                f"never completed: {' '.join(argv)}. This is NOT an empty/absent "
                "result -- the command simply did not answer within its time budget. "
                "If this is expected to take longer (e.g. over a remote 'ssh_host'), "
                "raise the timeout via 'command_timeout_s' or the relevant "
                "operation-specific '*_timeout_s' config key.",
                argv=argv,
                timeout=effective_timeout,
            )
        if check_output and not result.ok:
            raise RunnerError(
                f"Command failed ({result.returncode}): {' '.join(argv)}\n"
                f"stderr: {result.stderr.strip()}\nstdout: {result.stdout.strip()}",
                argv=argv,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result

    # -- File transfer ----------------------------------------------------

    def fetch_file(self, remote_path: str, local_path: Path) -> None:
        """Copy a file produced on the target host to `local_path`.

        Local: a plain filesystem copy (the "remote" path is already on
        this host). Remote: `scp -o BatchMode=yes <ssh_host>:<remote_path>
        <local_path>`.

        Callers write ops (screenshots, DDI transfer) against a target-host
        path and always call this to materialise the result locally -- the
        same op code runs unchanged whether `ssh_host` is set or not.
        """
        if not self.ssh_host:
            src = Path(remote_path)
            if src.resolve() != local_path.resolve():
                shutil.copyfile(src, local_path)
            return
        argv = [
            "scp",
            "-o",
            "BatchMode=yes",
            f"{self.ssh_host}:{remote_path}",
            str(local_path),
        ]
        result = self._runner(argv, self.default_timeout, None)
        if result.timed_out:
            raise CommandTimeoutError(
                f"scp fetching {remote_path!r} from {self.ssh_host!r} timed out after "
                f"{self.default_timeout}s -- the file transfer never completed. This is "
                "NOT the same as an empty/missing file.",
                argv=argv,
                timeout=self.default_timeout,
                remote_path=remote_path,
                local_path=str(local_path),
            )
        if not result.ok:
            raise RunnerError(
                f"scp failed fetching {remote_path!r} from {self.ssh_host!r} "
                f"(exit {result.returncode}): {result.stderr.strip()}",
                remote_path=remote_path,
                local_path=str(local_path),
            )

    def which(self, name: str) -> str | None:
        """Resolve a binary's path on the target host. Local: `shutil.which`.
        Remote: `which <name>` over ssh. Returns `None` (never raises) if
        not found -- this is a probe, used by `doctor` and binary
        resolution, not a hard requirement. A TIMEOUT is a distinct failure
        from "not found", though, and still raises `CommandTimeoutError`
        (via `run`'s default `raise_on_timeout=True`) rather than being
        folded into the "not found" `None` result."""
        if not self.ssh_host:
            return shutil.which(name)
        result = self.run(["which", name], check_output=False)
        if not result.ok:
            return None
        line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        return line or None

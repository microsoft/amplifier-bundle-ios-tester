"""Tests for CommandRunner -- local vs. ssh_host command construction, file
transfer, and binary resolution. No real subprocess/ssh/scp invoked."""

from __future__ import annotations

from pathlib import Path

import pytest
from amplifier_module_tool_ios_inspector.runner import (
    DEFAULT_DEVELOPER_DIR,
    DEFAULT_TIMEOUT_S,
    CommandResult,
    CommandRunner,
    CommandTimeoutError,
    RunnerError,
)

from .conftest import FakeRunner


def test_build_argv_local_returns_unchanged() -> None:
    runner = CommandRunner()
    argv = ["xcrun", "simctl", "list", "devices", "booted"]
    assert runner.build_argv(argv) == argv


def test_build_argv_remote_wraps_with_ssh_and_developer_dir() -> None:
    runner = CommandRunner(ssh_host="user@mac.example.com")
    argv = ["xcrun", "simctl", "list", "devices", "booted"]
    built = runner.build_argv(argv)
    assert built[:4] == ["ssh", "-o", "BatchMode=yes", "user@mac.example.com"]
    assert len(built) == 5
    remote_cmd = built[4]
    assert remote_cmd.startswith(f"export DEVELOPER_DIR={DEFAULT_DEVELOPER_DIR}; ")
    assert "xcrun simctl list devices booted" in remote_cmd


def test_build_argv_remote_shell_quotes_special_characters() -> None:
    import shlex

    runner = CommandRunner(ssh_host="mac")
    argv = ["axe", "tap", "--label", "It's a test"]
    built = runner.build_argv(argv)
    remote_cmd = built[4]
    # The command survives a round trip through shlex.split as the exact
    # original argv (after stripping the "export ...;" prefix) -- proof the
    # apostrophe-containing label was quoted correctly for the remote shell,
    # not split into two arguments.
    _, _, tail = remote_cmd.partition("; ")
    assert shlex.split(tail) == argv


def test_run_local_injects_developer_dir_into_env() -> None:
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=0, stdout="ok", stderr="")
    )
    runner = CommandRunner(_runner=fake)
    result = runner.run(["xcrun", "simctl", "list", "devices"])
    assert result.ok
    assert fake.envs[0] is not None
    assert fake.envs[0]["DEVELOPER_DIR"] == DEFAULT_DEVELOPER_DIR


def test_run_remote_does_not_pass_env_uses_inline_export() -> None:
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=0, stdout="ok", stderr="")
    )
    runner = CommandRunner(ssh_host="mac", _runner=fake)
    runner.run(["xcrun", "simctl", "list", "devices"])
    assert fake.envs[0] is None
    assert fake.calls[0][:3] == ["ssh", "-o", "BatchMode=yes"]
    assert "export DEVELOPER_DIR=" in fake.calls[0][4]


def test_run_check_output_raises_runner_error_on_nonzero_exit() -> None:
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=1, stdout="", stderr="boom")
    )
    runner = CommandRunner(_runner=fake)
    try:
        runner.run(["false"], check_output=True)
        raise AssertionError("expected RunnerError")
    except RunnerError as exc:
        assert "boom" in str(exc)
        assert exc.extra["returncode"] == 1


def test_fetch_file_local_copies(tmp_path: Path) -> None:
    src = tmp_path / "src.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\nfakepngdata")
    dest = tmp_path / "dest.png"
    runner = CommandRunner()
    runner.fetch_file(str(src), dest)
    assert dest.read_bytes() == src.read_bytes()


def test_fetch_file_local_is_noop_when_same_path(tmp_path: Path) -> None:
    src = tmp_path / "same.png"
    src.write_bytes(b"data")
    runner = CommandRunner()
    # Must not raise (shutil.copyfile(src, src) would raise SameFileError).
    runner.fetch_file(str(src), src)
    assert src.read_bytes() == b"data"


def test_fetch_file_remote_builds_scp_argv(tmp_path: Path) -> None:
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=0, stdout="", stderr="")
    )
    runner = CommandRunner(ssh_host="mac.local", _runner=fake)
    dest = tmp_path / "out.png"
    runner.fetch_file("/tmp/remote.png", dest)
    assert fake.calls[0] == [
        "scp",
        "-o",
        "BatchMode=yes",
        "mac.local:/tmp/remote.png",
        str(dest),
    ]


def test_fetch_file_remote_raises_on_scp_failure(tmp_path: Path) -> None:
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=1, stdout="", stderr="no such file")
    )
    runner = CommandRunner(ssh_host="mac.local", _runner=fake)
    dest = tmp_path / "out.png"
    try:
        runner.fetch_file("/tmp/remote.png", dest)
        raise AssertionError("expected RunnerError")
    except RunnerError as exc:
        assert "no such file" in str(exc)


def test_which_remote_uses_which_command() -> None:
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=0, stdout="/usr/bin/axe\n", stderr="")
    )
    runner = CommandRunner(ssh_host="mac", _runner=fake)
    assert runner.which("axe") == "/usr/bin/axe"
    assert fake.calls[0][:3] == ["ssh", "-o", "BatchMode=yes"]
    assert "which axe" in fake.calls[0][4]


def test_which_remote_returns_none_when_not_found() -> None:
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=1, stdout="", stderr="")
    )
    runner = CommandRunner(ssh_host="mac", _runner=fake)
    assert runner.which("nonexistent-binary") is None


# ---------------------------------------------------------------------------
# Timeout handling -- DEFECT 1: a timeout must never surface as an
# empty/absent result. It must raise a distinct, clearly-worded error naming
# the command and the exceeded budget.
# ---------------------------------------------------------------------------


def test_default_timeout_is_120_seconds() -> None:
    """The old 30.0s default was measured live to be far too short for
    ssh_host + first-run CoreSimulator latency -- see runner.py."""
    assert DEFAULT_TIMEOUT_S == 120.0
    assert CommandRunner().default_timeout == 120.0


def test_run_raises_command_timeout_error_by_default() -> None:
    """A timed-out command raises CommandTimeoutError -- structurally
    distinct from an empty/absent CommandResult -- BEFORE any caller gets a
    chance to interpret it as 'no output' / 'nothing there'."""
    fake = FakeRunner(
        default=CommandResult(
            args=[], returncode=-1, stdout="", stderr="timed out", timed_out=True
        )
    )
    runner = CommandRunner(_runner=fake, default_timeout=5.0)
    with pytest.raises(CommandTimeoutError) as exc_info:
        runner.run(["axe", "describe-ui", "--udid", "fake"])
    message = str(exc_info.value)
    assert "timed out" in message
    assert "5.0" in message
    assert "axe describe-ui --udid fake" in message
    assert exc_info.value.timeout == 5.0
    assert exc_info.value.argv == ["axe", "describe-ui", "--udid", "fake"]


def test_run_timeout_error_never_looks_like_empty_result() -> None:
    """The timeout error message must be unmistakable -- never phrased in a
    way that could be confused with 'the command ran and returned
    nothing'."""
    fake = FakeRunner(
        default=CommandResult(
            args=[], returncode=-1, stdout="", stderr="", timed_out=True
        )
    )
    runner = CommandRunner(_runner=fake, default_timeout=1.0)
    with pytest.raises(CommandTimeoutError) as exc_info:
        runner.run(["xcrun", "simctl", "boot", "fake-udid"])
    message = str(exc_info.value).lower()
    assert "not an empty/absent" in message


def test_run_raise_on_timeout_false_returns_result_instead_of_raising() -> None:
    """The one legitimate exception: a caller that deliberately bounds a
    command (e.g. log_stream) and wants the timeout treated as normal
    termination must be able to opt out via raise_on_timeout=False, and
    then check the STRUCTURAL `timed_out` flag -- never parse stderr
    text."""
    fake = FakeRunner(
        default=CommandResult(
            args=[], returncode=-1, stdout="partial output", stderr="", timed_out=True
        )
    )
    runner = CommandRunner(_runner=fake, default_timeout=5.0)
    result = runner.run(
        ["xcrun", "simctl", "spawn", "log", "stream"],
        timeout=5.0,
        raise_on_timeout=False,
    )
    assert result.timed_out is True
    assert result.ok is False
    assert result.stdout == "partial output"


def test_command_result_ok_is_false_when_timed_out_even_if_returncode_zero() -> None:
    """Belt-and-suspenders: `.ok` must never be True for a timed-out
    result, regardless of what returncode a runner implementation sets."""
    result = CommandResult(args=[], returncode=0, stdout="", stderr="", timed_out=True)
    assert result.ok is False


def test_per_call_timeout_overrides_default() -> None:
    fake = FakeRunner(
        default=CommandResult(args=[], returncode=0, stdout="ok", stderr="")
    )
    runner = CommandRunner(_runner=fake, default_timeout=30.0)
    runner.run(["xcrun", "simctl", "boot", "fake-udid"], timeout=180.0)
    assert fake.timeouts[0] == 180.0


def test_fetch_file_remote_raises_command_timeout_error_distinctly(
    tmp_path: Path,
) -> None:
    fake = FakeRunner(
        default=CommandResult(
            args=[], returncode=-1, stdout="", stderr="", timed_out=True
        )
    )
    runner = CommandRunner(ssh_host="mac.local", _runner=fake, default_timeout=5.0)
    dest = tmp_path / "out.png"
    with pytest.raises(CommandTimeoutError) as exc_info:
        runner.fetch_file("/tmp/remote.png", dest)
    message = str(exc_info.value).lower()
    assert "timed out" in message
    assert "not the same as an empty/missing file" in message

"""Tests for evidence.py -- collision-proof evidence filename generation."""

from __future__ import annotations

from pathlib import Path

import pytest
from amplifier_module_tool_ios_inspector.evidence import unique_evidence_path


def test_unique_evidence_path_shape(tmp_path: Path) -> None:
    path = unique_evidence_path(tmp_path, "screenshot", "png")
    assert path.parent == tmp_path
    assert path.name.startswith("screenshot_")
    assert path.suffix == ".png"


def test_unique_evidence_path_with_index_appends_suffix(tmp_path: Path) -> None:
    path = unique_evidence_path(tmp_path, "screenshot", "png", index=7)
    assert path.name.endswith("_0007.png")


def test_unique_evidence_path_never_collides_with_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force the first N candidate names to already exist, verifying the
    function retries rather than handing back a colliding path."""
    existing: set[Path] = set()
    calls = {"count": 0}

    real_exists = Path.exists

    def fake_exists(self: Path) -> bool:
        calls["count"] += 1
        if self in existing:
            return True
        if calls["count"] <= 3:
            # Simulate the first 3 candidates colliding, regardless of what
            # they are named (the real timestamp+random naming means this
            # would be astronomically unlikely -- this forces the retry
            # path deterministically for the test).
            existing.add(self)
            return True
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    path = unique_evidence_path(tmp_path, "screenshot", "png")
    assert path not in existing


def test_unique_evidence_path_raises_after_max_attempts_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "exists", lambda self: True)
    with pytest.raises(
        RuntimeError, match="Could not construct a unique evidence path"
    ):
        unique_evidence_path(tmp_path, "screenshot", "png", max_attempts=3)


def test_unique_evidence_path_two_calls_do_not_collide(tmp_path: Path) -> None:
    path1 = unique_evidence_path(tmp_path, "screenshot", "png")
    path1.touch()
    path2 = unique_evidence_path(tmp_path, "screenshot", "png")
    assert path1 != path2

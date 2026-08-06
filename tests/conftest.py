"""Fixtures shared across the suite."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURE_INSTANCE = Path(__file__).parent / "fixtures" / "acme"
"""The synthetic instance of spec 6.1 — never a real organization's (spec 9.2 rule 5)."""


@pytest.fixture
def instance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway copy of the fixture instance, and the working directory.

    Commands operate on the working directory (spec 5.1), so tests that go through the
    CLI need one — and a copy, since a test that writes must not edit the fixture.
    """
    root = tmp_path / "acme"
    shutil.copytree(FIXTURE_INSTANCE, root)
    monkeypatch.chdir(root)
    return root

"""Fixtures shared across the suite."""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

FIXTURE_INSTANCE = Path(__file__).parent / "fixtures" / "acme"
"""The synthetic instance of spec 6.1 — never a real organization's (spec 9.2 rule 5)."""

DUMMY_DISTRIBUTION = Path(__file__).parent / "fixtures" / "dummy-adapter"
"""A third-party adapter distribution, laid out as it looks once installed (spec 5.2)."""

DUMMY_MODULE = "semprini_dummy_adapter"

BROKEN_DISTRIBUTION = Path(__file__).parent / "fixtures" / "broken-adapter"
"""A distribution whose adapter cannot be imported — a real installation state."""


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


@pytest.fixture
def installed_dummy_adapter(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Make the dummy adapter distribution discoverable, the way installing it would.

    Putting the directory on ``sys.path`` is the whole mechanism: ``importlib.metadata``
    finds a distribution by scanning the path for ``*.dist-info``, so this exercises the
    real discovery route rather than a patched registry (spec 5.2). Deliberately *not*
    session-scoped and not autouse — most of the suite must run with no adapter
    installed, which is what the plane ships as until D2.
    """
    monkeypatch.syspath_prepend(str(DUMMY_DISTRIBUTION))
    yield DUMMY_DISTRIBUTION
    # monkeypatch restores sys.path, but an imported module outlives it, and a later
    # test asserting the adapter is *not* discoverable would then be testing a stale
    # interpreter rather than the path.
    sys.modules.pop(DUMMY_MODULE, None)


@pytest.fixture
def installed_broken_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a distribution whose adapter raises on import."""
    monkeypatch.syspath_prepend(str(BROKEN_DISTRIBUTION))


@pytest.fixture
def dummy_source(tmp_path: Path) -> Path:
    """The JSON document the dummy adapter reads — its stand-in for a source system."""
    path = tmp_path / "source.json"
    path.write_text(
        json.dumps(
            {
                "scheme": {"slug": "dummy", "label": "Dummy glossary"},
                "entities": [
                    {"key": "e1", "label": "Customer", "definition": "Someone who buys."},
                    {"key": "e2", "label": "Order"},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path

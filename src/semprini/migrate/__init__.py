"""Version-to-version migrations (spec 7).

:mod:`~semprini.migrate.steps` is the data this release ships,
:mod:`~semprini.migrate.registry` decides which steps one upgrade needs, and
:mod:`~semprini.migrate.apply` is the only part that touches a disk and enforces what a
migration may never do.
"""

from __future__ import annotations

from semprini.migrate.apply import (
    FileChange,
    MigrationReport,
    MigrationResult,
    migrate,
)
from semprini.migrate.registry import (
    InstanceState,
    Migration,
    MigrationError,
    Step,
    Version,
    parse_version,
    plan,
)
from semprini.migrate.steps import MIGRATIONS

__all__ = [
    "MIGRATIONS",
    "FileChange",
    "InstanceState",
    "Migration",
    "MigrationError",
    "MigrationReport",
    "MigrationResult",
    "Step",
    "Version",
    "migrate",
    "parse_version",
    "plan",
]

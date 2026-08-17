"""Version-to-version migrations (spec 7).

A release that changes emitted output ships a migration here, so an upgrade is always a
reviewable diff rather than an unexplained reflow. Migrations never mint new IRIs for
existing objects and never remove ID-map rows — and since that is a promise a release makes
about code nobody has written yet, it is checked rather than trusted.

Three modules, and the split is the point: :mod:`~semprini.migrate.steps` is the data (what
this release ships), :mod:`~semprini.migrate.registry` decides which of it one upgrade needs,
and :mod:`~semprini.migrate.apply` is the only part that touches a disk. Read `apply` first
if you are reviewing an upgrade; read `steps` first if you are writing one.
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

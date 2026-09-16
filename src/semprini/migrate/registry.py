"""Which migrations exist, and which of them one upgrade has to run (spec 7).

A migration is data: a version, a one-sentence summary and a pure function over the
instance's committed state. A step runs when ``recorded < version <= target``, so a
release with no output change ships no step and leaves no gap. Versions are strictly
``X.Y.Z``; anything else is refused.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from rdflib import Graph

from semprini import version_parts
from semprini.identity import IdMap
from semprini.model import Issue, IssueError, Severity

__all__ = [
    "InstanceState",
    "Migration",
    "MigrationError",
    "Step",
    "Version",
    "parse_version",
    "plan",
]

Version = tuple[int, int, int]


class MigrationError(IssueError):
    """An upgrade cannot be performed, or a step misbehaved — exit code 1 (spec 5.1)."""

    noun = "migration error"


@dataclass(frozen=True, slots=True, kw_only=True)
class InstanceState:
    """Everything a migration may rewrite, and nothing else (spec 7): the generated Turtle
    and the ID map. Sources, lock, merge register, manifest and report are not here."""

    graphs: Mapping[str, Graph] = field(hash=False)
    """``generated/*.ttl`` by file name, parsed. ``ontology.ttl`` is refreshed wholesale
    instead and is not here (spec 4.2)."""

    id_map: IdMap
    """``mappings/id-map.csv``. What a step may do to it is enforced by
    :func:`semprini.migrate.apply.migrate`."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "graphs", MappingProxyType(dict(self.graphs)))

    def with_graphs(self, graphs: Mapping[str, Graph]) -> InstanceState:
        """The same state with different graphs; what nearly every step returns."""
        return InstanceState(graphs=graphs, id_map=self.id_map)


Step = Callable[[InstanceState], InstanceState]
"""What a migration does: state in, state out. Pure; it reads no clock and no disk."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Migration:
    """One release's rewrite of what is already committed (spec 7)."""

    version: str
    """The release that introduced the change."""

    summary: str
    """One sentence, for the migration report an adopter reads in the pull request."""

    apply: Step

    def __post_init__(self) -> None:
        parse_version(self.version, what=f"migration {self.version!r}")
        if not self.summary.strip():
            raise MigrationError(
                [
                    Issue(
                        Severity.ERROR,
                        f"the migration to {self.version} has no summary; it is what the "
                        f"report tells an adopter their files were rewritten for",
                        self.version,
                    )
                ]
            )


def parse_version(text: str, *, what: str) -> Version:
    """Parse ``X.Y.Z`` into something comparable.

    Raises :class:`MigrationError` for anything else, including ``0.0.0+source`` (spec 7).
    ``what`` names the thing being parsed in the message.
    """
    parts = version_parts(text)
    if parts is None:
        raise MigrationError(
            [
                Issue(
                    Severity.ERROR,
                    f"{what} is {text!r}, which is not a version of the form X.Y.Z; "
                    f"migrations are ordered by version and one that cannot be compared "
                    f"cannot be placed in the order",
                    what,
                )
            ]
        )
    return parts


def plan(
    migrations: Sequence[Migration], *, recorded: Version, target: Version
) -> tuple[Migration, ...]:
    """The steps, in version order, with ``recorded < version <= target``. Empty is ordinary.

    Raises :class:`MigrationError` for a downgrade or two migrations on one version (spec 7).
    """
    if target < recorded:
        raise MigrationError(
            [
                Issue(
                    Severity.ERROR,
                    f"generated/ was compiled with {_text(recorded)} and cannot be migrated "
                    f"back to {_text(target)}; migrations only ever move forward (spec 7)",
                    "--to",
                )
            ]
        )

    seen: dict[Version, Migration] = {}
    for migration in migrations:
        version = parse_version(migration.version, what=f"migration {migration.version!r}")
        if version in seen:
            raise MigrationError(
                [
                    Issue(
                        Severity.ERROR,
                        f"two migrations are registered for version {migration.version}; "
                        f"one release ships at most one, so that the order steps run in is "
                        f"never ambiguous",
                        migration.version,
                    )
                ]
            )
        seen[version] = migration

    return tuple(
        migration for version, migration in sorted(seen.items()) if recorded < version <= target
    )


def _text(version: Version) -> str:
    return ".".join(str(part) for part in version)

"""Which migrations exist, and which of them one upgrade has to run (spec 7).

A migration is **data**: a version, a sentence saying what changed, and a function from the
instance's committed state to the state the new release would have written. Nothing about a
step knows where the files are, when it is being run, or what the report will say — which is
what makes a step readable a year later, when someone has to decide whether the migration
that ran in an adopter's repository did what its sentence claims.

**One version per migration, and the range rule.** A step declares the release that
introduced the change, and it runs when the instance was compiled with something older:
``recorded < version <= target``. The alternative — a step declaring both ends of a hop —
forces the shipped steps to form an unbroken chain, and then a patch release nobody wrote a
migration for becomes a gap that stalls every adopter sitting on it. Under the range rule a
patch release costs nothing, an adopter three releases behind runs all three steps in
order, and a release with no output change ships no step at all.

Versions are strictly ``X.Y.Z``. A version this cannot compare is refused rather than
guessed at, because the guess decides whether an adopter's files are rewritten.
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
    """An upgrade cannot be performed, or a step misbehaved — exit code 1 (spec 5.1).

    Exit 1 rather than 2 throughout, including for a target version that is not the one
    installed: exit 2 tells an operator to go and edit a configuration file, and nothing
    reported here is fixed by editing one.
    """

    noun = "migration error"


@dataclass(frozen=True, slots=True, kw_only=True)
class InstanceState:
    """Everything a migration may rewrite — and nothing else (spec 7).

    The two files an upgrade can legitimately have to touch: the generated Turtle, and the
    ID map. Deliberately absent are the sources (a migration must not need them — that is
    what makes its diff provably content-neutral), the namespace lock (it records what the
    instance bootstrapped against, and upgrading the metamodel is the manifest's business,
    spec 3.4.4), the merge register (its rows name IRIs, which no migration moves) and the
    manifest and report, which describe the migration rather than being subject to it.
    """

    graphs: Mapping[str, Graph] = field(hash=False)
    """``generated/*.ttl`` by file name, parsed. ``ontology.ttl`` is **not** here: it is a
    verbatim copy of the metamodel the plane carries, so an upgrade refreshes it wholesale
    rather than transforming what the previous release copied (spec 4.2)."""

    id_map: IdMap
    """``mappings/id-map.csv``. A step receives it so that the rare upgrade needing it is
    possible at all; what it may do to it is narrow, and enforced (see
    :func:`semprini.migrate.apply.migrate`)."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "graphs", MappingProxyType(dict(self.graphs)))

    def with_graphs(self, graphs: Mapping[str, Graph]) -> InstanceState:
        """The same state with different files — what nearly every step returns.

        Offered so that a step replaces rather than edits. Editing the graphs it was handed
        would work, and is guarded against rather than forbidden: the before/after
        comparison is taken as an immutable snapshot before any step runs, precisely because
        an ``rdflib`` graph is mutable and a comparison of a mutated object against itself
        would pass every check in :mod:`semprini.migrate.apply`.
        """
        return InstanceState(graphs=graphs, id_map=self.id_map)


Step = Callable[[InstanceState], InstanceState]
"""What a migration does: state in, state out. Pure — it reads no clock and no disk."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Migration:
    """One release's rewrite of what is already committed (spec 7)."""

    version: str
    """The release that introduced the change this step undoes the absence of."""

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
    """Parse ``X.Y.Z`` into something comparable, refusing anything else.

    ``what`` names the thing being parsed, because the three callers fail for different
    reasons an operator acts on differently: a bad ``--to`` is a typo, a recorded version
    that is not ``X.Y.Z`` is an edited manifest, and a bad migration version is this
    project's own bug. Notably refused is ``0.0.0+source`` — a compiler running from a
    source tree identifies no release, so there is no telling what an instance would be
    being migrated *to* (spec 7).
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
    """The steps, in order, that take an instance from ``recorded`` to ``target``.

    Every migration introduced after the version the instance was compiled with and not
    after the version being upgraded to. An empty result is an ordinary answer, not a
    failure: most releases change no output, and the upgrade is then a re-serialization and
    a restamped manifest.

    A downgrade is refused. Migrations are written in one direction only — the support
    policy of spec 7 gives the previous major migrations, not the next one — and a "migration"
    to an older version would rewrite an instance's files with a release that never saw them.
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
            # Two steps for one release have no defined order between them, and the order
            # is the whole contract: run them the other way round and an adopter gets
            # different files. Whoever needs two rewrites in one release composes them into
            # one step, where the order is written down.
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

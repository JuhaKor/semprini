"""``semprini migrate --to`` — an upgrade an adopter can read (spec 5.1, 7).

The problem this solves is not that files need rewriting. It is that an adopter upgrading
the plane otherwise cannot tell an unexplained reflow from a change of meaning. The drift
check (spec 6.1 check 3) puts a stop sign there — an instance compiled by 0.1.0 will not
quietly pass CI under 0.2.0 — and this command is the only thing on the far side of it: it
rewrites what is committed into what the new release would have written, records who did it,
and stops if the rewrite would have cost the instance any identity.

**It does not read the sources, and that is the point.** Everything here is derived from
``generated/`` and ``mappings/id-map.csv``, so the diff an adopter reviews is provably about
the upgrade and nothing else. Two consequences worth being explicit about. A migration is
not a recompile: if the new release would *also* emit different content from the same
sources, the next scheduled compile is what brings that in, in its own pull request. And a
recompile is not a migration: nodes no source reports any more are re-emitted verbatim from
the previous run's output (spec 3.5), so recompiling carries their old statements forward
and would miss exactly the objects nobody is watching.

**Nothing is written until everything is known**, as in :mod:`semprini.run` and for the same
reason: a migration that failed half way through would leave an instance in a state no
release produced, with a manifest describing neither.

**Four refusals, and they are the task.** Spec 7 promises that migrations never mint new
IRIs for existing objects and never remove ID-map rows. A promise a release makes about code
it has not written yet is worth what enforces it, so the promise is checked after the steps
run and before anything is written:

1. the set of subjects in ``generated/`` is **unchanged** — a migration changes what is said
   about the instance's objects, never which objects exist;
2. every ``dcterms:modified`` is unchanged — the date says when the instance's knowledge of
   an object changed, and how that knowledge is written down is not knowledge;
3. the ID map is append-only *and* gained nothing —
   :meth:`~semprini.identity.IdMap.check_append_only` plus a check for new rows, which
   between them leave a step able to edit only the ``note`` column stewards own;
4. every file name a step returned is a ``.ttl`` file directly inside ``generated/``.

Widening any of those is a deliberate change to this module, in a release whose CHANGELOG
says so — not something a step gets to do quietly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS
from rdflib.term import Node

from semprini import build, compiler_version, manifest, ontology_version, report, serialize
from semprini.build import GENERATED_DIR, ONTOLOGY_FILE, OutputFile
from semprini.config import InstanceConfig
from semprini.identity import IdMap
from semprini.manifest import MANIFEST_FILE, Manifest
from semprini.migrate.registry import (
    InstanceState,
    Migration,
    MigrationError,
    parse_version,
    plan,
)
from semprini.migrate.steps import MIGRATIONS
from semprini.model import Issue, Severity
from semprini.report import REPORT_FILE

__all__ = ["FileChange", "MigrationReport", "MigrationResult", "migrate"]


@dataclass(frozen=True, slots=True, kw_only=True)
class FileChange:
    """What the migration did to one file of ``generated/``, for the report."""

    name: str
    statements: int | None
    """``None`` for a file the migration removed, which has no statements any more."""

    change: str
    """``rewritten``, ``unchanged``, ``added`` or ``removed``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MigrationReport:
    """``generated/.report.md``, written by a migration instead of by a compile (spec 5.6).

    The committed report is always the report of whatever produced the files beside it. A
    migration produced them, so it writes the report — a compile report left in place would
    name the release that no longer wrote a single byte in the directory, and would state a
    version the manifest next to it contradicts.

    The next compile that changes anything replaces this with an ordinary run report. One
    that changes nothing writes none (spec 5.6), and this stays, correctly.
    """

    from_compiler: str
    to_compiler: str
    from_ontology: str
    to_ontology: str
    steps: tuple[Migration, ...]
    files: tuple[FileChange, ...]
    ontology_refreshed: bool
    id_map_rows: int

    def render(self) -> str:
        lines = [
            "# Migration report",
            "",
            f"Migrated from compiler **{self.from_compiler}** · ontology "
            f"**{self.from_ontology}** to compiler **{self.to_compiler}** · ontology "
            f"**{self.to_ontology}**.",
            "",
            "## Migrations applied",
            "",
        ]
        if self.steps:
            lines += report.table(
                ["Version", "Change"],
                [[step.version, step.summary] for step in self.steps],
            )
        else:
            lines.append(
                "None. This release changes no committed output, so the files were "
                "re-serialized unchanged and the manifest restamped."
            )
        lines += ["", "## Files", ""]
        lines += report.table(
            ["File", "Statements", "Change"],
            [
                [
                    f"`{file.name}`",
                    "—" if file.statements is None else str(file.statements),
                    file.change,
                ]
                for file in self.files
            ],
            empty="This instance has no generated content yet.",
        )
        refreshed = "refreshed from" if self.ontology_refreshed else "already identical to"
        lines += [
            "",
            f"`{ONTOLOGY_FILE}` is a verbatim copy of the metamodel and is {refreshed} the "
            f"one this compiler carries; it is not counted above.",
            "",
            "## Identity",
            "",
            f"`mappings/id-map.csv` holds {self.id_map_rows} "
            f"{'row' if self.id_map_rows == 1 else 'rows'}, none of them removed, rewritten "
            f"or added. No IRI was minted: a migration changes how this instance's objects "
            f"are written, never which objects exist (spec 7).",
            "",
            "## What this is not",
            "",
            "A migration rewrites what was committed and does not read the sources, so this "
            "diff is about the upgrade and nothing else. If the new release also compiles "
            "the sources differently, the next scheduled compile brings that in — and its "
            "report replaces this one.",
            "",
        ]
        return "\n".join(lines)

    def to_file(self) -> OutputFile:
        """The report as one of the migration's output files.

        Returned this way so that :func:`semprini.build.write_all` writes it, like every
        other file the compiler owns — one writer, one answer about encoding and line
        endings. ``graph`` is ``None``: it is prose.
        """
        return OutputFile(name=REPORT_FILE, text=self.render())


@dataclass(frozen=True, slots=True, kw_only=True)
class MigrationResult:
    """What a migration did — or, when there was nothing to do, that there was not."""

    from_compiler: str
    to_compiler: str
    from_ontology: str
    to_ontology: str

    steps: tuple[Migration, ...] = ()
    files: tuple[OutputFile, ...] = ()
    """Every file of ``generated/`` as it was written. Empty when nothing was."""

    stale: tuple[str, ...] = ()
    report: MigrationReport | None = None
    """``None`` exactly when the instance was already up to date and nothing was written."""

    @property
    def migrated(self) -> bool:
        return self.report is not None

    def summary(self) -> tuple[str, ...]:
        """The migration in a few lines, for an operator watching a terminal or a CI log.

        Deliberately ASCII, like :meth:`semprini.run.RunResult.summary`: a redirected
        Windows console still encodes as cp1252, and a decorative character would raise
        *after* the files were written.
        """
        if not self.migrated:
            return (
                f"generated/ was compiled with {self.from_compiler} and the ontology has "
                f"not moved; nothing to migrate",
            )
        lines = [
            f"migrated generated/ from compiler {self.from_compiler} to {self.to_compiler} "
            f"(ontology {self.from_ontology} to {self.to_ontology})"
        ]
        if self.steps:
            lines.append(f"applied {_count(len(self.steps), 'migration')}:")
            lines.extend(f"  {step.version}  {step.summary}" for step in self.steps)
        else:
            lines.append("no migration step was needed; re-serialized and restamped")
        lines.append(f"wrote {_count(len(self.files), 'file')} to generated/")
        if self.stale:
            lines.append(f"removed {_count(len(self.stale), 'file')} no longer produced")
            lines.extend(f"  {name}" for name in self.stale)
        lines.append("review the diff, then run `semprini check`")
        return tuple(lines)


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def migrate(
    settings: InstanceConfig,
    *,
    to: str,
    migrations: Sequence[Migration] | None = None,
    compiler: str | None = None,
    ontology: str | None = None,
) -> MigrationResult:
    """Migrate the instance ``settings`` describes to version ``to`` (spec 5.1, 7).

    ``to`` must be the compiler version actually installed. It is not a choice of how far to
    go — the steps live in the package, so the installed release is the only version whose
    migrations exist, and the manifest records the release that wrote the files. Requiring
    the operator to name it is the point: a workflow that pinned one version and installed
    another is caught before a byte is rewritten, rather than by whoever reads the manifest
    later.

    ``migrations``, ``compiler`` and ``ontology`` are injected so that the suite can pin
    them; production callers pass none of the three and get the shipped steps and the
    versions actually running (spec 7).
    """
    root = settings.repo_root
    running_compiler = compiler_version() if compiler is None else compiler
    running_ontology = ontology_version() if ontology is None else ontology
    target = parse_version(to, what="--to")
    if to != running_compiler:
        raise MigrationError(
            [
                Issue(
                    Severity.ERROR,
                    f"--to says {to} but this is semprini {running_compiler}; a migration is "
                    f"performed by the release it upgrades to, whose steps only exist in "
                    f"that release. Install semprini=={to} and run it again",
                    "--to",
                )
            ]
        )

    recorded = Manifest.load(root)
    mismatched = recorded.verify(root)
    if mismatched:
        # Refused rather than migrated: a migration rewrites what the compiler wrote, and
        # migrating a directory that disagrees with its manifest would launder a hand edit
        # into a manifest recording the new version as its author (spec 4.3).
        raise MigrationError(
            [
                Issue(
                    Severity.ERROR,
                    "generated/ does not match its manifest, so there is no telling what "
                    "would be migrated; resolve this first (`semprini check`, check 2)",
                    MANIFEST_FILE,
                ),
                *mismatched,
            ]
        )

    from_compiler = parse_version(
        recorded.compiler_version, what=f"the compiler version recorded in {MANIFEST_FILE}"
    )
    steps = plan(
        MIGRATIONS if migrations is None else migrations, recorded=from_compiler, target=target
    )
    if from_compiler == target and recorded.ontology_version == running_ontology:
        # Idempotent, so that re-running one after a failure or a retry is safe, and so that
        # a workflow may call it unconditionally.
        return MigrationResult(
            from_compiler=recorded.compiler_version,
            to_compiler=running_compiler,
            from_ontology=recorded.ontology_version,
            to_ontology=running_ontology,
        )

    after = InstanceState(graphs=build.read_previous_files(root), id_map=IdMap.load(root))
    before = _Snapshot.of(after)
    for step in steps:
        after = _applied(step, after)
    _check_identity(before, after)

    files = _rendered(after, settings.base_iri)
    files += (Manifest.create(files, compiler=compiler, ontology=ontology).to_file(),)
    # The report is kept rather than counted stale even though it is not in `files` yet: it
    # is appended below, and stale files are removed *after* everything is written, so
    # listing it here would delete the report this migration had just written.
    stale = build.stale(files, root, keep=(REPORT_FILE,))
    run_report = MigrationReport(
        from_compiler=recorded.compiler_version,
        to_compiler=running_compiler,
        from_ontology=recorded.ontology_version,
        to_ontology=running_ontology,
        steps=steps,
        files=_changes(files, stale, root),
        ontology_refreshed=not build.unchanged([build.ontology_file()], root),
        id_map_rows=len(after.id_map),
    )
    files += (run_report.to_file(),)

    build.write_all(files, root)
    # The map immediately after the files it describes, and once — the order spec 5.4 needs
    # and that :mod:`semprini.run` keeps for the same reason: generated/ holding IRIs the map
    # does not know is a state only deleting generated/ recovers from.
    after.id_map.save(root)
    build.remove(stale, root)

    return MigrationResult(
        from_compiler=recorded.compiler_version,
        to_compiler=running_compiler,
        from_ontology=recorded.ontology_version,
        to_ontology=running_ontology,
        steps=steps,
        files=files,
        stale=stale,
        report=run_report,
    )


def _applied(step: Migration, state: InstanceState) -> InstanceState:
    """Run one step, and hold it to returning a state.

    A step is this project's own code, so its exceptions are this project's bugs — but they
    surface in an adopter's repository, where a traceback through ``rdflib`` says nothing
    about which upgrade failed. Named here, where the step is known.
    """
    try:
        result = step.apply(state)
    except Exception as error:
        raise MigrationError(
            [
                Issue(
                    Severity.ERROR,
                    f"the migration to {step.version} failed: {error!r}; nothing was written",
                    step.version,
                )
            ]
        ) from error
    if not isinstance(result, InstanceState):
        raise MigrationError(
            [
                Issue(
                    Severity.ERROR,
                    f"the migration to {step.version} returned {type(result).__name__} "
                    f"rather than an InstanceState",
                    step.version,
                )
            ]
        )
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class _Snapshot:
    """What the instance said before any step ran, copied out of the mutable objects.

    The reason this is a snapshot rather than the state itself: an ``rdflib`` graph and an
    :class:`~semprini.identity.IdMap` are both mutable, so a step that edits what it was
    handed — rather than returning a new state — would leave every check below comparing an
    object with itself, and all four refusals would pass on a migration that had just
    minted an IRI. The one place that could go wrong silently, so it does not depend on a
    step behaving.
    """

    subjects: frozenset[URIRef]
    dates: Mapping[URIRef, frozenset[Node]]
    id_map: IdMap
    """Rebuilt from the loaded rows, which are frozen; the loaded map itself is not."""

    @classmethod
    def of(cls, state: InstanceState) -> _Snapshot:
        return cls(
            subjects=_subjects(state.graphs),
            dates=_dates(state.graphs),
            id_map=IdMap(state.id_map.rows, origin=state.id_map.origin),
        )


def _check_identity(before: _Snapshot, after: InstanceState) -> None:
    """Hold the migration to spec 7's promise, before anything is written.

    Every violation is reported, not the first: an adopter reading this in CI would
    otherwise fix one and find the next.
    """
    issues: list[Issue] = []

    was, now = before.subjects, _subjects(after.graphs)
    issues.extend(
        Issue(
            Severity.ERROR,
            "is no longer written to generated/; a migration changes what is said about an "
            "object, and an IRI is never deleted (spec 3.5)",
            str(iri),
        )
        for iri in sorted(was - now)
    )
    issues.extend(
        Issue(
            Severity.ERROR,
            "appears in generated/ and was not there before; a migration never mints an IRI "
            "for an existing object (spec 7)",
            str(iri),
        )
        for iri in sorted(now - was)
    )

    before_dates, after_dates = before.dates, _dates(after.graphs)
    issues.extend(
        Issue(
            Severity.ERROR,
            f"had dcterms:modified {_shown(before_dates.get(iri, frozenset()))} and now has "
            f"{_shown(after_dates.get(iri, frozenset()))}; the date records when this "
            f"instance's knowledge of the object changed, and a migration changes how that "
            f"knowledge is written rather than what it is (spec 3.3)",
            str(iri),
        )
        for iri in sorted(was & now)
        if before_dates.get(iri, frozenset()) != after_dates.get(iri, frozenset())
    )

    # B4's own definition of "this file was not edited", called rather than re-derived: it
    # compares every column but `note`, the one stewards own. Between it and the new-row
    # check below, a step is left able to edit that column and nothing else.
    issues.extend(after.id_map.check_append_only(before.id_map))
    known = {row.ref for row in before.id_map}
    issues.extend(
        Issue(
            Severity.ERROR,
            f"the ID map gained a row for {ref}; a migration never mints an IRI for an "
            f"existing object, and nothing it does adds an object (spec 7)",
            str(ref),
        )
        for ref in sorted(row.ref for row in after.id_map if row.ref not in known)
    )

    if issues:
        raise MigrationError(issues)


def _subjects(graphs: Mapping[str, Graph]) -> frozenset[URIRef]:
    """Every subject written anywhere in ``generated/``.

    Across all files rather than per file, because a subject legitimately spans two of them
    (spec 4.2) and a migration is allowed to move one — what it may not do is add or lose an
    object.
    """
    return frozenset(
        subject
        for graph in graphs.values()
        for subject in graph.subjects()
        if isinstance(subject, URIRef)
    )


def _dates(graphs: Mapping[str, Graph]) -> Mapping[URIRef, frozenset[Node]]:
    """Each subject's ``dcterms:modified``, over the union of the files."""
    dates: dict[URIRef, set[Node]] = {}
    for graph in graphs.values():
        for subject, object_ in graph.subject_objects(DCTERMS.modified):
            if isinstance(subject, URIRef):
                dates.setdefault(subject, set()).add(object_)
    return {subject: frozenset(objects) for subject, objects in dates.items()}


def _shown(dates: frozenset[Node]) -> str:
    return ", ".join(sorted(str(date) for date in dates)) or "none"


def _rendered(state: InstanceState, base_iri: str) -> tuple[OutputFile, ...]:
    """Serialize the migrated state, refusing a file name or a graph no run could write.

    The ontology copy comes from the metamodel *this* compiler carries rather than from what
    the previous release copied — refreshing it is half of what an ontology version bump
    means, and check 7 compares the committed copy against the packaged one.
    """
    issues: list[Issue] = []
    files: list[OutputFile] = [build.ontology_file()]
    for name, graph in sorted(state.graphs.items()):
        location = f"{GENERATED_DIR.as_posix()}/{name}"
        if not manifest.is_generated_file_name(name) or not name.endswith(".ttl"):
            # A migration composes paths under generated/ out of names a step returned, so
            # the escape C1 refuses for a scheme slug and C2 for a manifest key is refused
            # here too — one directory, bounded in every module that writes into it.
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"a migration produced {name!r}, which is not a .ttl file directly "
                    f"inside {GENERATED_DIR.as_posix()}/",
                    location,
                )
            )
            continue
        if name == ONTOLOGY_FILE:
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"a migration produced {ONTOLOGY_FILE}, which is a verbatim copy of the "
                    f"metamodel and is refreshed rather than rewritten (spec 4.2)",
                    location,
                )
            )
            continue
        try:
            text = serialize.serialize(graph, base_iri)
        except ValueError as error:
            # A blank node or a literal subject: legal RDF the canonical serializer refuses
            # (spec 5.5 rules 2 and 7), so no compile could have produced this file either.
            issues.append(
                Issue(Severity.ERROR, f"the migrated graph cannot be serialized: {error}", location)
            )
            continue
        files.append(OutputFile(name=name, text=text, graph=graph))
    if issues:
        raise MigrationError(issues)
    return tuple(files)


def _changes(
    files: Sequence[OutputFile], stale: Sequence[str], root: Path
) -> tuple[FileChange, ...]:
    """What the migration did to each file, by comparing against what is committed."""
    changes = [
        FileChange(
            name=file.name,
            statements=len(file.graph) if file.graph is not None else None,
            change=_change(file, root),
        )
        for file in files
        if file.graph is not None
    ]
    changes += [FileChange(name=name, statements=None, change="removed") for name in stale]
    return tuple(sorted(changes, key=lambda change: change.name))


def _change(file: OutputFile, root: Path) -> str:
    path = root / file.path
    if not path.is_file():
        return "added"
    return "unchanged" if build.unchanged([file], root) else "rewritten"

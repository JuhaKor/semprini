"""``semprini migrate --to`` — rewrite what is committed for a new release (spec 5.1, 7).

Derived from ``generated/`` and ``mappings/id-map.csv`` only, never the sources, so the
diff is about the upgrade and nothing else. Nothing is written until every step has run
and four refusals have passed: the set of subjects is unchanged, every ``dcterms:modified``
is unchanged, the ID map gained, lost, rewrote and reordered no row (only ``note`` may
change), and every file name a step returned is a ``.ttl`` directly inside ``generated/``.
Widening any of those is a deliberate change to this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS
from rdflib.term import Node

from semprini import (
    build,
    compiler_version,
    manifest,
    ontology_version,
    report,
    serialize,
    wheel_url,
)
from semprini.build import GENERATED_DIR, ONTOLOGY_FILE, OutputFile
from semprini.config import InstanceConfig
from semprini.identity import ID_MAP_PATH, IdMap
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
    """``generated/.report.md``, written by a migration instead of a compile (spec 5.6).

    The next compile that changes anything replaces it with an ordinary run report.
    """

    from_compiler: str
    to_compiler: str
    from_ontology: str
    to_ontology: str
    steps: tuple[Migration, ...]
    files: tuple[FileChange, ...]
    ontology_refreshed: bool
    id_map_rows: int

    notes_changed: int = 0
    """Rows whose ``note`` a step rewrote, the one ID-map column a migration may write (spec 5.4).
    """

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
            f"{'row' if self.id_map_rows == 1 else 'rows'}: none added, none removed, none "
            f"reordered{self._notes()}. No IRI was minted — a migration changes how this "
            f"instance's objects are written, never which objects exist (spec 7).",
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

    def _notes(self) -> str:
        if not self.notes_changed:
            return ", none altered"
        rows = "row" if self.notes_changed == 1 else "rows"
        return (
            f", and none altered except the `note` column of {self.notes_changed} {rows} — the "
            f"one column of this file a migration may write, and stewards' to edit either way"
        )

    def to_file(self) -> OutputFile:
        """The report as one of the migration's output files."""
        return OutputFile(name=REPORT_FILE, text=self.render())


@dataclass(frozen=True, slots=True, kw_only=True)
class MigrationResult:
    """What a migration did, or that there was nothing to do."""

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
        """The migration in a few lines for a terminal or CI log.
        ASCII only, for a cp1252 console.
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

    ``to`` must be the installed compiler version; naming it catches a workflow that pinned
    one version and installed another. ``migrations``, ``compiler`` and ``ontology`` let
    the suite pin them. Raises :class:`MigrationError` for a manifest mismatch, a
    downgrade, a failed step, or any of the module's four refusals.
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
                    f"that release. Install semprini {to} from {wheel_url(to)} and run it "
                    f"again",
                    "--to",
                )
            ]
        )

    recorded = Manifest.load(root)
    mismatched = recorded.verify(root)
    if mismatched:
        # Migrating a hand-edited directory would launder the edit (spec 4.3).
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
    if (
        from_compiler == target
        and recorded.ontology_version == running_ontology
        and build.unchanged([build.ontology_file()], root)
    ):
        # Idempotent. The ontology copy is compared as bytes, as check 7 does (spec 6.1).
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
        notes_changed=_notes_changed(before.id_map, after.id_map),
    )
    files += (run_report.to_file(),)

    # The map first, the opposite of a run: a migration mints nothing, and a crash after the
    # manifest was restamped would make the re-run answer "nothing to migrate" with the
    # step's map edits lost. In this order a crash leaves an unstamped manifest to re-run on.
    after.id_map.save(root)
    build.write_all(files, root)
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
    """Run one step, naming it in any failure, and hold it to returning a state."""
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
    """What the instance said before any step ran, copied out of the mutable objects so
    that a step editing its input in place cannot pass the checks by comparing an object
    with itself."""

    subjects: frozenset[URIRef]
    dates: Mapping[URIRef, frozenset[Node]]
    id_map: IdMap
    """Rebuilt from the loaded rows; the loaded map itself is mutable."""

    @classmethod
    def of(cls, state: InstanceState) -> _Snapshot:
        return cls(
            subjects=_subjects(state.graphs),
            dates=_dates(state.graphs),
            id_map=IdMap(state.id_map.rows, origin=state.id_map.origin),
        )


def _check_identity(before: _Snapshot, after: InstanceState) -> None:
    """Hold the migration to spec 7's promise before anything is written; every violation is
    reported.
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

    # Compares every column but `note`; with the two checks below, a step may edit only that.
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

    # Order, which neither check above can see (spec 5.4). Asked only when the rows are
    # otherwise the same set; an addition or removal is already reported.
    if {row.ref for row in after.id_map} == known and [row.ref for row in before.id_map] != [
        row.ref for row in after.id_map
    ]:
        issues.append(
            Issue(
                Severity.ERROR,
                "the ID map's rows came back in a different order; the file is append-only and "
                "its order is the order they were appended in (spec 5.4)",
                ID_MAP_PATH.as_posix(),
            )
        )

    if issues:
        raise MigrationError(issues)


def _notes_changed(before: IdMap, after: IdMap) -> int:
    """How many rows a step rewrote the ``note`` of. Called after the guards have passed."""
    return sum(
        1 for row in after if (found := before.row(row.ref)) is not None and found.note != row.note
    )


def _subjects(graphs: Mapping[str, Graph]) -> frozenset[URIRef]:
    """Every subject written anywhere in ``generated/``; a migration may move one between files
    (spec 4.2).
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

    The ontology copy is refreshed from the metamodel this compiler carries (spec 6.1 check 7).
    """
    issues: list[Issue] = []
    files: list[OutputFile] = [build.ontology_file()]
    for name, graph in sorted(state.graphs.items()):
        location = f"{GENERATED_DIR.as_posix()}/{name}"
        if not manifest.is_generated_file_name(name) or not name.endswith(".ttl"):
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
            # A blank node or a literal subject (spec 5.5 rules 2 and 7).
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

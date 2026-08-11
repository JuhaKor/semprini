"""``semprini run`` — sources in, committed files out (spec 5.1).

The stage nothing else in the compiler can be: every other module answers one question
about one thing, and this one puts them in an order and decides when the answers are
allowed to touch the disk. Three properties follow from that order rather than from any
module below it.

*Nothing is written until everything is known.* Fetching, lifecycle, building,
serialization, the manifest and the report all complete before the first byte is written,
so a source that fails, a merge register that contradicts itself or a model that cannot be
expressed leaves the instance exactly as it was. That is also what makes ``--dry-run`` a
real dry run rather than a rehearsal: the same pipeline, minus the last four lines.

*The report is written only when something moved* (spec 5.6). A scheduled compile that
found nothing new must produce no diff at all, and a report saying "0 new" is a diff.

*``generated/`` is the run's output and nothing else* (spec 4.3). A file the run did not
produce is removed, because the alternative is an instance that accumulates statements no
source still makes and that a consumer loading the directory from Git reads as current.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.term import Node

from semprini import adapters, build, identity, lifecycle, manifest, ontology_version, report
from semprini.build import OutputFile
from semprini.config import InstanceConfig
from semprini.identity import NamespaceLock, NamespaceLockError, Registry
from semprini.model import (
    InternalModel,
    Issue,
    IssueError,
    MergeConflictError,
    RunContext,
    Severity,
    merge_models,
)
from semprini.report import RunReport, SourceSummary

__all__ = ["RunResult", "SourceConflictError", "run"]


class SourceConflictError(IssueError):
    """Two configured sources describe one object and disagree — exit code 1 (spec 5.1).

    A compile failure and a stewardship question: the sources say different things about
    an object the ID map records as one, and the compiler settles neither (spec 5.2). Its
    own class rather than a bare ``ValueError`` so that it reaches an operator as a message
    naming the source it arrived with, like every other refusal in this project.
    """

    noun = "source conflict"


@dataclass(frozen=True, slots=True, kw_only=True)
class RunResult:
    """What a run produced — and, on a dry run, what it would have produced."""

    files: tuple[OutputFile, ...]
    """Every file of ``generated/``, rendered. Carries the exact bytes a real run commits,
    so a caller can show them without a filesystem in the way (spec 5.1)."""

    stale: tuple[str, ...] = ()
    """Files that were in ``generated/`` and are not this run's output (spec 4.3)."""

    report: RunReport | None = None
    """``None`` exactly when the run changed nothing: the committed report then stays as
    it is, and remains the report of the run that produced the files beside it (spec 5.6)."""

    minted: int = 0
    """Rows appended to ``mappings/id-map.csv`` — objects seen for the first time."""

    deprecated: tuple[str, ...] = ()
    """IRIs this run moved to ``sem:status "deprecated"`` (spec 3.5)."""

    dry_run: bool = False

    @property
    def changed(self) -> bool:
        """Whether the instance moved. Removing a stale file counts, which is why this is
        not simply "the produced bytes differ": a run can produce byte-identical files and
        still have deleted output the previous one left behind."""
        return self.report is not None

    def summary(self) -> tuple[str, ...]:
        """The run in a few lines, for an operator watching a terminal or a CI log.

        Deliberately ASCII. This is printed to whatever console the run was started from,
        and a Windows one is often still cp1252 — a decorative character would raise
        ``UnicodeEncodeError`` *after* the files were written, turning a successful compile
        into a traceback and a non-zero exit. The report itself is UTF-8 and unaffected.
        """
        if not self.changed:
            return (f"generated/ is up to date; {_count(len(self.files), 'file')} unchanged",)

        wrote = "would write" if self.dry_run else "wrote"
        lines = [f"{wrote} {_count(len(self.files), 'file')} to generated/"]
        lines.extend(f"  {name}" for name in sorted(file.name for file in self.files))
        if self.stale:
            removed = "would remove" if self.dry_run else "removed"
            lines.append(f"{removed} {_count(len(self.stale), 'file')} no longer produced")
            lines.extend(f"  {name}" for name in self.stale)
        if self.report is not None:
            lines.append(
                f"new {len(self.report.new)}, changed {len(self.report.changed)}, "
                f"deprecated {len(self.report.deprecated)}, warnings {self.report.warnings}"
            )
        if self.minted:
            appended = "would append" if self.dry_run else "appended"
            lines.append(f"{appended} {_count(self.minted, 'row')} to mappings/id-map.csv")
        if self.dry_run:
            lines.append("dry run: nothing was written")
        return tuple(lines)


def _count(number: int, noun: str) -> str:
    """``1 file`` / ``2 files`` — a run of one is common enough to read wrong."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def run(
    settings: InstanceConfig,
    *,
    only_source: str | None = None,
    dry_run: bool = False,
    force_namespace_change: bool = False,
    today: datetime.date | None = None,
    compiler: str | None = None,
    ontology: str | None = None,
) -> RunResult:
    """Compile the instance ``settings`` describes (spec 5.1).

    ``today`` is injected so that nothing but the caller reads a clock — two runs of one
    input on two days must produce the same bytes (spec 4.3). ``compiler`` and ``ontology``
    exist so that the plane's own fixture instance can pin the versions its committed
    manifest and report record; a production run passes neither and records what is
    actually running (spec 7).

    Raises rather than returning a code. :func:`semprini.cli.exit_code_for` is the one
    place an error becomes an exit code, so that a given code means the same thing
    whichever subcommand produced it.
    """
    root = settings.repo_root
    context = settings.run_context(only_source=only_source, dry_run=dry_run)
    if force_namespace_change and only_source is not None:
        # Refused rather than merged into one commit: a namespace move must be readable as
        # "every IRI moved and nothing else did" (spec 3.4.4), and a partial fetch in the
        # same run makes that claim uncheckable — the reviewer cannot tell a rebased line
        # from a changed one.
        raise NamespaceLockError(
            [
                Issue(
                    Severity.ERROR,
                    "--force-namespace-change moves every IRI in the instance and cannot "
                    "be combined with --source; run the move on its own, then compile the "
                    "source",
                    "--source",
                )
            ]
        )

    previous_files = build.read_previous_files(root)
    merges = lifecycle.MergeRegister.load(root)
    if force_namespace_change:
        lock, previous_files, merges, registry = _move_namespace(
            settings, previous_files, merges, today=today, ontology=ontology
        )
    else:
        lock, registry = None, Registry.load(settings, today=today)

    model, sources = _fetch(settings, context)

    # Per file for lifecycle, which keeps a retained node where it was, and unioned for
    # dcterms:modified and the report, which ask about nodes rather than about files.
    previous = build.union_of(previous_files.values())
    plan = lifecycle.plan(
        model,
        registry=registry,
        context=context,
        previous=previous_files,
        sources=[source.name for source in settings.sources],
        merges=merges,
    )
    files = build.build(
        model,
        registry=registry,
        context=context,
        previous=previous,
        today=today,
        carried=plan.carried,
    )
    # The manifest is part of the comparison below, not merely of the output: it carries
    # the compiler and ontology versions, so a recompile after a plane upgrade produces
    # identical Turtle and a changed manifest — a real change, whose report has to be
    # rewritten or the instance commits a manifest and a report naming different releases.
    files += (manifest.Manifest.create(files, compiler=compiler, ontology=ontology).to_file(),)

    stale = _stale(files, root)
    run_report: RunReport | None = None
    if stale or not build.unchanged(files, root):
        run_report = report.create(
            files,
            context=context,
            previous=previous,
            sources=sources,
            compiler=compiler,
            ontology=ontology,
        )
        files += (run_report.to_file(),)

    if not dry_run:
        build.write_all(files, root)
        # Identity immediately after the files it describes, and once: rows accumulate in
        # memory precisely so that a failure anywhere above leaves the map as it was (spec
        # 5.4). Nothing may come between the two — `generated/` holding IRIs the map does
        # not is a state the next run refuses and only deleting `generated/` recovers from,
        # so removing stale output waits until identity is safe. The lock follows the map
        # it describes, so an interrupted namespace move leaves the instance saying it
        # still lives in the old namespace, which a re-run recovers from (spec 3.4.4).
        registry.save(root)
        if lock is not None:
            merges.save(root)
            lock.save(root)
        _remove(stale, root)

    return RunResult(
        files=files,
        stale=stale,
        report=run_report,
        minted=len(registry.minted),
        deprecated=plan.deprecated,
        dry_run=dry_run,
    )


def _fetch(
    settings: InstanceConfig, context: RunContext
) -> tuple[InternalModel, tuple[SourceSummary, ...]]:
    """Read every source in scope and merge what they return (spec 5.1, 5.2).

    An adapter is constructed and used here and nowhere else: it fetches, it is asked to
    describe what it read for the report, and it is done. A failure to reach a source
    propagates as :class:`~semprini.adapters.SourceUnreachableError` — exit 3, the one
    failure CI retries rather than investigates.

    Two sources describing one object and disagreeing about it is a stewardship question,
    not the compiler's (spec 5.2), and ``merge_models`` refuses to pick a side. It raises a
    plain ``ValueError``, though, which the CLI would print as a traceback — so it is
    turned into an issue here, where the source being merged in is known and can be named.
    The Ellie adapter does the same at its own boundary, for exports of one source.
    """
    model = InternalModel()
    summaries: list[SourceSummary] = []
    for source in settings.sources:
        if context.only_source is not None and source.name != context.only_source:
            continue
        adapter = adapters.create(source, context)
        fetched = adapter.fetch()
        try:
            model = merge_models(model, fetched)
        except MergeConflictError as error:
            raise SourceConflictError(
                [
                    Issue(
                        Severity.ERROR,
                        f"source {source.name!r} describes an object another configured "
                        f"source also describes, and they disagree: {error}",
                        source.name,
                    )
                ]
            ) from error
        summaries.append(
            SourceSummary(
                name=source.name,
                adapter=source.adapter,
                objects=len(fetched),
                note=adapter.summary(),
            )
        )
    return model, tuple(summaries)


def _move_namespace(
    settings: InstanceConfig,
    previous_files: Mapping[str, Graph],
    merges: lifecycle.MergeRegister,
    *,
    today: datetime.date | None,
    ontology: str | None,
) -> tuple[NamespaceLock, Mapping[str, Graph], lifecycle.MergeRegister, Registry]:
    """``--force-namespace-change``: the whole instance, in a new namespace (spec 3.4.4).

    The move is computed in memory and written with the run's other output, so a compile
    that fails afterwards leaves nothing half-moved. Everything the run then does is
    ordinary: the registry resolves against the moved map, and the previous state is
    **rebased** so that lifecycle recognizes the nodes already in ``generated/`` as the
    nodes they are. Without the rebase every one of them would look like an IRI the ID map
    has never heard of, which is a refusal (spec 5.4) — and if it were not, every
    deprecated node in the instance would silently be dropped.

    The **merge register moves with them**, and is the one thing a compile ever writes to
    `mappings/merges.csv`. Its rows are the one place in an instance where a person typed
    an IRI, and every one of them names the old base; left behind, each would name an IRI
    the moved map has never heard of and the run would refuse itself — so the migration
    could not be performed at all on an instance that had ever recorded a merge. Rebasing
    changes no decision: a row says the same two objects are one, in the namespace they now
    live in.

    Rebasing rather than starting fresh is also what keeps `dcterms:modified` honest: the
    move changes which namespace an object lives in and nothing it says, so the run's diff
    is every IRI and no dates, and the report says nothing was added or changed. That is
    exactly the claim a reviewer of a once-ever migration needs to be able to check.

    Combining the move with ``--source`` is refused: the commit would have to be read as
    two claims at once — that every IRI moved, and that some content changed — and the
    first cannot be verified through the second.
    """
    lock, moved = identity.plan_namespace_change(
        settings,
        ontology_version=ontology_version() if ontology is None else ontology,
        today=today,
    )
    old_base = NamespaceLock.load(settings.repo_root).base_iri
    rebased = {
        name: _rebased(graph, old_base, settings.base_iri) for name, graph in previous_files.items()
    }
    registry = Registry(moved, settings.base_iri, repo_root=settings.repo_root, today=today)
    return lock, rebased, merges.rebased(old_base, settings.base_iri), registry


def _rebased(graph: Graph, old_base: str, new_base: str) -> Graph:
    """The same statements with every IRI under ``old_base`` moved to ``new_base``.

    Local names survive the move (spec 3.4.4), which is the whole point: the object keeps
    its identity and changes only the namespace it lives in. Nothing outside the old base
    is touched — `sem:` terms, SKOS, literals — and the ID map has already been checked to
    hold no IRI outside it.
    """
    moved = Graph()
    for subject, predicate, object_ in graph:
        moved.add(
            (
                _rebased_term(subject, old_base, new_base),
                _rebased_term(predicate, old_base, new_base),
                _rebased_term(object_, old_base, new_base),
            )
        )
    return moved


def _rebased_term(term: Node, old_base: str, new_base: str) -> Node:
    if isinstance(term, URIRef) and str(term).startswith(old_base):
        return URIRef(new_base + str(term)[len(old_base) :])
    return term


def _stale(files: Sequence[OutputFile], root: Path) -> tuple[str, ...]:
    """Files in ``generated/`` that this run did not produce (spec 4.3).

    ``generated/`` is machine-owned and overwritten wholesale, so anything left over is
    output of a run that no longer describes the instance — a scheme whose objects are now
    written to a differently named file, or a directory somebody added by hand. Left in
    place it would be loaded by every consumer that reads the directory from Git, and would
    fail the manifest's own unrecorded-file check (spec 6.1 check 2) on the next PR.

    Walked recursively, and compared by path relative to ``generated/``: the directory is
    flat by spec, so a nested file is by definition not this run's, and anything reading
    the tree would still read it.

    ``.report.md`` is never stale. It is written on different terms — only when something
    moved (spec 5.6) — so a run that produced no report has not stopped producing the one
    that is committed.
    """
    directory = root / build.GENERATED_DIR
    if not directory.is_dir():
        return ()
    produced = {file.name for file in files} | {report.REPORT_FILE}
    return tuple(
        name
        for path in sorted(directory.rglob("*"))
        if path.is_file() and (name := path.relative_to(directory).as_posix()) not in produced
    )


def _remove(stale: Sequence[str], root: Path) -> None:
    """Delete the stale files, then any directory their removal emptied."""
    directory = root / build.GENERATED_DIR
    for name in stale:
        (directory / name).unlink()
    for path in sorted(directory.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()

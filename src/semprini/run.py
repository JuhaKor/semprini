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
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from semprini import adapters, build, lifecycle, manifest, report
from semprini.build import OutputFile
from semprini.config import InstanceConfig
from semprini.identity import Registry
from semprini.model import (
    InternalModel,
    Issue,
    IssueError,
    MergeConflictError,
    RunContext,
    Severity,
    counting_normalizations,
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
    dry_run: bool = False,
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
    context = settings.run_context(dry_run=dry_run)

    previous_files = build.read_previous_files(root)
    merges = lifecycle.MergeRegister.load(root)
    registry = Registry.load(settings, today=today)

    model, sources = _fetch(settings, context)

    # Per file for lifecycle, which keeps a retained node where it was, and unioned for
    # dcterms:modified and the report, which ask about nodes rather than about files.
    previous = build.union_of(previous_files.values())
    plan = lifecycle.plan(
        model,
        registry=registry,
        previous=previous_files,
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
        # so removing stale output waits until identity is safe.
        registry.save(root)
        build.remove(stale, root)

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
    """Read every configured source and merge what they return (spec 5.1, 5.2).

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
        adapter = adapters.create(source, context)
        with counting_normalizations() as normalizations:
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
                note=_note(adapter.summary(), normalizations[0]),
            )
        )
    return model, tuple(summaries)


def _note(summary: str, normalizations: int) -> str:
    """The adapter's own note, plus what normalization changed on the way in (spec 5.6).

    Said per source rather than once per run, because the answer a steward needs is *which
    file to fix*, and silence is the whole point of the "when there is one" clause: a
    source with nothing to normalize adds nothing to the report, so this line appears only
    where there is something to act on (spec 5.5 rule 9).

    Not an issue per value, deliberately. The fix usually lives in a binary workbook the
    steward may not own, so a per-cell warning would be permanent noise on every run —
    and normalizing silently, with nothing anywhere saying so, is how a compiler that
    edits a source's words stops being trusted.
    """
    if not normalizations:
        return summary
    values = "value" if normalizations == 1 else "values"
    normalized = f"normalized invisible or decomposed characters in {normalizations} {values}"
    return f"{summary}; {normalized}" if summary else normalized


def _stale(files: Sequence[OutputFile], root: Path) -> tuple[str, ...]:
    """Files in ``generated/`` that this run did not produce (spec 4.3).

    ``.report.md`` is the one file kept regardless. It is written on different terms — only
    when something moved (spec 5.6) — so a run that produced no report has not thereby
    stopped producing the one that is committed.
    """
    return build.stale(files, root, keep=(report.REPORT_FILE,))

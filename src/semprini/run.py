"""``semprini run`` — sources in, committed files out (spec 5.1).

The orchestration stage. Nothing is written until every stage has completed, so a
failure anywhere leaves the instance as it was and ``--dry-run`` is the same pipeline
minus the writes. The report is written only when something moved (spec 5.6), and a
file in ``generated/`` the run did not produce is removed (spec 4.3).
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
    """Two configured sources describe one object and disagree — exit code 1 (spec 5.1, 5.2)."""

    noun = "source conflict"


@dataclass(frozen=True, slots=True, kw_only=True)
class RunResult:
    """What a run produced, or on a dry run would have produced."""

    files: tuple[OutputFile, ...]
    """Every file of ``generated/``, rendered to the exact bytes a real run commits."""

    stale: tuple[str, ...] = ()
    """Files that were in ``generated/`` and are not this run's output (spec 4.3)."""

    report: RunReport | None = None
    """``None`` exactly when the run changed nothing and the committed report stays (spec 5.6)."""

    minted: int = 0
    """Rows appended to ``mappings/id-map.csv``."""

    deprecated: tuple[str, ...] = ()
    """IRIs this run moved to ``sem:status "deprecated"`` (spec 3.5)."""

    dry_run: bool = False

    @property
    def changed(self) -> bool:
        """Whether the instance moved. Removing a stale file counts."""
        return self.report is not None

    def summary(self) -> tuple[str, ...]:
        """The run in a few lines for a terminal or CI log. ASCII only: a cp1252 console
        must not raise after the files were written."""
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
    """``1 file`` / ``2 files``."""
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

    ``today`` is the only clock (spec 4.3). ``compiler`` and ``ontology`` let the fixture
    builder pin the versions the manifest records; a production run passes neither.
    Raises rather than returning a code; :func:`semprini.cli.exit_code_for` maps errors.
    """
    root = settings.repo_root
    context = settings.run_context(dry_run=dry_run)

    previous_files = build.read_previous_files(root)
    merges = lifecycle.MergeRegister.load(root)
    registry = Registry.load(settings, today=today)

    model, sources = _fetch(settings, context)

    # Per file for lifecycle, unioned for dcterms:modified and the report.
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
    # The manifest joins the comparison below: a plane upgrade changes it and nothing else,
    # and that is a real change with a report.
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
        # Identity immediately after the files it describes (spec 5.4): generated/ holding
        # IRIs the map does not is a state the next run refuses.
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

    :class:`~semprini.adapters.SourceUnreachableError` propagates. A merge conflict becomes
    a :class:`SourceConflictError` naming the source being merged in.
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
    """The adapter's own note, plus a count of normalized values when there is one (spec 5.5 rule 9,
    5.6).
    """
    if not normalizations:
        return summary
    values = "value" if normalizations == 1 else "values"
    normalized = f"normalized invisible or decomposed characters in {normalizations} {values}"
    return f"{summary}; {normalized}" if summary else normalized


def _stale(files: Sequence[OutputFile], root: Path) -> tuple[str, ...]:
    """Files in ``generated/`` that this run did not produce (spec 4.3). The report is kept (spec
    5.6).
    """
    return build.stale(files, root, keep=(report.REPORT_FILE,))

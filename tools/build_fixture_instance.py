"""Compile the fixture instance and commit the result, ID map included.

    poetry run python tools/build_fixture_instance.py

``tests/fixtures/acme/`` is a *complete* instance: config, workbook, mappings and the
generated Turtle beside each other, exactly as an adopting organization's repository
would hold them. That is what lets the suite assert the interesting thing — recompiling a
committed instance reuses every IRI in its ID map and reproduces its files byte for byte,
which is the whole promise of spec 5.4 and 5.5 in one assertion.

This is a stand-in for ``semprini run``, which arrives with **E2** and will replace it.
It deliberately keeps E2's write order (spec 5.6): lifecycle, build, manifest, then the
report only if something moved, then the files, then the registry once.

Regenerate deliberately, never reflexively. A change in what this writes is a change to
every instance's committed output, and spec 5.5 makes that a major version bump with a
migration (spec 7).
"""

from __future__ import annotations

import datetime
from pathlib import Path

from semprini import adapters, build, config, lifecycle, manifest, report
from semprini.identity import Registry
from semprini.model import InternalModel, merge_models

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTANCE = REPO_ROOT / "tests/fixtures/acme"

TODAY = datetime.date(2026, 8, 6)
"""Fixed, so the committed ``dcterms:modified`` dates do not move when nothing has.

Everything that reads a clock in this project takes the date as an argument for exactly
this reason (spec 4.3): a timestamp nobody passed in is a diff nobody caused."""

COMPILER = "0.1.0"
ONTOLOGY = "0.1.0"
"""Pinned, so the committed manifest and report do not move with every release of the
plane. A production run passes neither and records the versions it is actually running
(spec 7); that is what the drift check compares against."""


def compile_instance(root: Path, *, today: datetime.date = TODAY) -> tuple[build.OutputFile, ...]:
    """Fetch every configured source and build the instance's output files."""
    settings = config.load(root, known_adapters=adapters.adapter_names() or None)
    ctx = settings.run_context()
    registry = Registry.load(settings, today=today)

    model = InternalModel()
    summaries = []
    for source in settings.sources:
        adapter = adapters.create(source, ctx)
        fetched = adapter.fetch()
        model = merge_models(model, fetched)
        summaries.append(
            report.SourceSummary(
                name=source.name,
                adapter=source.adapter,
                objects=len(fetched),
                note=adapter.summary(),
            )
        )

    # Per file for lifecycle, which keeps a retained node where it was, and unioned for
    # dcterms:modified and the report, which ask about nodes rather than files.
    previous_files = build.read_previous_files(root)
    previous = build.union_of(previous_files.values())
    plan = lifecycle.plan(
        model,
        registry=registry,
        context=ctx,
        previous=previous_files,
        sources=[source.name for source in settings.sources],
        merges=lifecycle.MergeRegister.load(root),
    )
    files = build.build(
        model,
        registry=registry,
        context=ctx,
        previous=previous,
        today=today,
        carried=plan.carried,
    )
    document = manifest.Manifest.create(files, compiler=COMPILER, ontology=ONTOLOGY)
    files += (document.to_file(),)
    if not build.unchanged(files, root):
        files += (
            report.create(
                files,
                context=ctx,
                previous=previous,
                sources=summaries,
                compiler=COMPILER,
                ontology=ONTOLOGY,
            ).to_file(),
        )
    build.write_all(files, root)
    registry.save(root)
    return files


if __name__ == "__main__":
    written = compile_instance(INSTANCE)
    print(f"wrote {len(written)} files to {INSTANCE.relative_to(REPO_ROOT)}/generated/")
    for file in sorted(written, key=lambda item: item.name):
        print(f"  {file.name}")

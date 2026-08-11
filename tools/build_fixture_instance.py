"""Compile the fixture instance and commit the result, ID map included.

    poetry run python tools/build_fixture_instance.py

``tests/fixtures/acme/`` is a *complete* instance: config, workbook, mappings and the
generated Turtle beside each other, exactly as an adopting organization's repository
would hold them. That is what lets the suite assert the interesting thing — recompiling a
committed instance reuses every IRI in its ID map and reproduces its files byte for byte,
which is the whole promise of spec 5.4 and 5.5 in one assertion.

It is ``semprini run`` (spec 5.1) with two things pinned — the date and the two version
numbers — so that the committed output describes one run and does not move when the plane
is released. Nothing else here differs from what an adopting organization's CI executes.

Regenerate deliberately, never reflexively. A change in what this writes is a change to
every instance's committed output, and spec 5.5 makes that a major version bump with a
migration (spec 7).
"""

from __future__ import annotations

import datetime
from pathlib import Path

from semprini import adapters, build, config, run

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
    """Compile the instance at ``root``, exactly as ``semprini run`` would."""
    settings = config.load(root, known_adapters=adapters.adapter_names() or None)
    result = run.run(settings, today=today, compiler=COMPILER, ontology=ONTOLOGY)
    return result.files


if __name__ == "__main__":
    written = compile_instance(INSTANCE)
    print(f"wrote {len(written)} files to {INSTANCE.relative_to(REPO_ROOT)}/generated/")
    for file in sorted(written, key=lambda item: item.name):
        print(f"  {file.name}")

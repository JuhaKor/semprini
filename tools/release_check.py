"""``python tools/release_check.py v0.1.0`` — what a release must agree about (spec 7).

Semprini is distributed as a wheel attached to a GitHub release (spec 11 #3), so a tag is
not a label on a commit: it is the version an instance pins, the directory the download URL
is built from, and the number recorded in every `generated/.manifest.json` compiled with it.
Four places state that number, and a release where they disagree is discovered by an adopter
rather than here — as a 404 from a workflow, or as a drift check that cannot be resolved.

So they are compared, once, before anything is published:

- the **tag** (`vX.Y.Z`), which names the download directory;
- **`pyproject.toml`**, which names the wheel and becomes `semprini version`;
- the **installed** distribution, when this runs somewhere the wheel is installed — which is
  what the release workflow does, so the artifact is checked and not merely the source that
  produced it;
- the **changelog**, which must carry a dated section for the version rather than leaving its
  entries under *Unreleased*.

And one thing the other three cannot see: the **current ontology version must be archived**,
byte-identical to the shipped document. Publishing a release publishes the site, and the site
is what makes `https://w3id.org/semprini/ontology/X.Y.Z/` resolve — a path this project
promises is permanent. A release that has not frozen its ontology publishes a version whose
own path disappears at the next bump, which is the gap task A2 left open and this is where it
closes.

Run it before tagging. `.github/workflows/release.yml` runs it again on the tag, where a
failure stops the release rather than reporting on one already published.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import TextIO

from semprini import (
    ONTOLOGY_PATH,
    UNINSTALLED_VERSION,
    compiler_version,
    ontology_version,
    version_parts,
    wheel_url,
)

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "ontology-archive"
CHANGELOG = ROOT / "CHANGELOG.md"
PYPROJECT = ROOT / "pyproject.toml"

TAG = re.compile(r"\Av(?P<version>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\Z")
"""`vX.Y.Z`, and nothing else. Not a style preference: the workflows an instance runs build
the download URL out of this tag, so a tag spelled any other way names a URL that 404s."""


def emit(text: str, *, stream: TextIO = sys.stdout) -> None:
    """Print as UTF-8 whatever the console says it can encode.

    Everything this tool writes is prose from `CHANGELOG.md`, and the release notes are
    redirected to a file and published. A Windows console defaults to cp1252, so a plain
    `print` raises on the first em dash — which would be a release tool that works on the
    runner and crashes for the maintainer rehearsing it beforehand.
    """
    stream.buffer.write(f"{text}\n".encode())
    stream.flush()


def released_section(version: str) -> re.Pattern[str]:
    """The changelog heading that says this version is out.

    Dated, and not `[Unreleased]`: the release notes are cut from this section, and a release
    whose entries are still filed under *Unreleased* is one where nobody decided what shipped.
    """
    return re.compile(rf"^## \[{re.escape(version)}\][ ]+[-—][ ]+\d{{4}}-\d{{2}}-\d{{2}}\s*$", re.M)


def check_versions_agree(version: str) -> list[str]:
    """The tag against everything else that states a version."""
    problems = []

    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    if declared != version:
        problems.append(f"the tag says {version}, but pyproject.toml says {declared}")

    installed = compiler_version()
    if installed == UNINSTALLED_VERSION:
        # Running from a source tree with nothing installed — which is how a maintainer
        # runs this before tagging, so it is a note rather than a failure. The release
        # workflow installs the wheel first, and there this branch is not taken.
        emit(f"note: semprini is not installed here, so only the source was checked ({version})")
    elif installed != version:
        problems.append(f"the tag says {version}, but the installed semprini is {installed}")

    return problems


def check_the_changelog_records_the_release(version: str) -> list[str]:
    text = CHANGELOG.read_text(encoding="utf-8")
    if released_section(version).search(text):
        return []
    return [
        f"CHANGELOG.md has no released section for {version} — expected a heading "
        f"`## [{version}] — YYYY-MM-DD`, with this release's entries moved out of [Unreleased]"
    ]


def check_the_ontology_is_archived() -> list[str]:
    """The current ontology version must be frozen in `ontology-archive/`, unchanged.

    Byte-identical rather than merely present, because the archive is what the site publishes
    at the permanent path while the package ships the other copy. Two documents under one
    version number is the failure this makes impossible, and it is not a hypothetical: it is
    what an ontology edit made without a version bump produces.
    """
    version = ontology_version()
    frozen = ARCHIVE / version / "sem.ttl"

    if not frozen.is_file():
        return [
            f"ontology {version} is not archived — copy src/semprini/ontology/sem.ttl to "
            f"ontology-archive/{version}/sem.ttl, so that its permanent path outlives this "
            f"working tree (see ontology-archive/README.md)"
        ]
    if frozen.read_bytes() != ONTOLOGY_PATH.read_bytes():
        return [
            f"ontology-archive/{version}/sem.ttl differs from the ontology this release "
            f"ships. A released version is frozen: if a term has to change, it changes under "
            f"a new version (spec 7), not under this one"
        ]

    # A released version that is newer than the one being shipped means `owl:versionInfo` went
    # backwards — a botched revert, or a merge that took the wrong side. Nothing else notices:
    # the document matches its own archived copy, so every check above passes while the site
    # would publish a current version older than one already released.
    here = version_parts(version) or (0, 0, 0)
    ahead = [
        name
        for name in (path.name for path in ARCHIVE.iterdir() if path.is_dir())
        if (there := version_parts(name)) is not None and there > here
    ]
    if ahead:
        return [
            f"ontology {version} is older than {', '.join(sorted(ahead))}, which is already "
            f"released — a version number cannot go backwards (spec 7)"
        ]
    return []


def check_the_archive_is_well_formed() -> list[str]:
    """Every archived version is one directory, named for a version, holding one document.

    Checked here rather than left to the site build because the build runs after the release
    is published, and a directory it refuses is then a broken site behind a permanent
    identifier rather than a red job on a tag.
    """
    if not ARCHIVE.is_dir():
        # Nothing to check, and not this function's finding to report: the check above
        # already says which version is missing and where to put it. Raising here would
        # replace that instruction with a traceback.
        return []

    problems = []
    for entry in sorted(ARCHIVE.iterdir()):
        if entry.is_file():
            if entry.name != "README.md":
                problems.append(f"ontology-archive/{entry.name} is not a version directory")
            continue
        if not TAG.match(f"v{entry.name}"):
            problems.append(f"ontology-archive/{entry.name} is not named for a version")
        contents = {path.name for path in entry.iterdir()}
        if contents != {"sem.ttl"}:
            problems.append(
                f"ontology-archive/{entry.name} holds {sorted(contents)}, expected only sem.ttl"
            )
    return problems


def notes(version: str) -> str:
    """The release notes: this version's changelog section, plus how to install it.

    Cut from `CHANGELOG.md` rather than written twice. The install lines are added here
    because a GitHub release page is where somebody arrives who has no instance yet and no
    README in front of them, and with no package index there is nothing they can guess.
    """
    text = CHANGELOG.read_text(encoding="utf-8")
    found = released_section(version).search(text)
    if not found:
        raise SystemExit(f"CHANGELOG.md has no released section for {version}")

    after = text[found.end() :]
    end = re.search(r"^## ", after, re.M)
    body = (after[: end.start()] if end else after).strip()

    return (
        f"{body}\n\n"
        "## Installing\n\n"
        "Semprini is distributed as the wheel attached below; there is no package index.\n\n"
        "```sh\n"
        f'pip install "semprini @ {wheel_url(version)}"\n'
        "```\n\n"
        "`semprini init` writes this same URL into a new instance's two workflows, pinned to "
        "the version that created it.\n"
    )


def check(tag: str) -> list[str]:
    matched = TAG.match(tag)
    if not matched:
        return [f"{tag!r} is not a release tag; releases are tagged vX.Y.Z (spec 7)"]

    version = matched.group("version")
    return [
        *check_versions_agree(version),
        *check_the_changelog_records_the_release(version),
        *check_the_ontology_is_archived(),
        *check_the_archive_is_well_formed(),
    ]


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3) or (len(argv) == 3 and argv[2] != "--notes"):
        emit(f"usage: {Path(argv[0]).name} <tag> [--notes]", stream=sys.stderr)
        return 2

    matched = TAG.match(argv[1])
    if matched and argv[-1] == "--notes":
        emit(notes(matched.group("version")))
        return 0

    problems = check(argv[1])
    for problem in problems:
        emit(f"error: {problem}", stream=sys.stderr)
    if problems:
        return 1

    # Nothing was reported, so the tag matched: `check` refuses one that does not.
    emit(
        f"{argv[1]} is coherent: compiler {argv[1].removeprefix('v')}, "
        f"ontology {ontology_version()} archived"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""``python tools/release_smoke.py 0.1.0`` — what an adopter gets, run against the artifact.

Task G5's verification, automated: *install the release in a clean environment, and confirm
that `semprini init` produces an instance whose workflows pin that same version.* Everything
here is deliberately done the way somebody else would do it — through the console script, on
a tree it just created — because the failures this catches are the ones that only exist in
the installed distribution. A file left out of the wheel, a console script that does not
resolve, a placeholder that survives substitution: none of them can be seen from a source
tree, where the missing file is on disk anyway.

The one thing it cannot check is that the URL it finds resolves. A release's assets do not
exist until the release is published, and this runs before that — so it proves the URL is the
one this version's wheel will be published at, and `CONTRIBUTING.md` asks for a single `curl`
afterwards to prove the release actually carries it.

Run it against a *bare* virtual environment holding nothing but the wheel:

    python -m venv /tmp/bare
    /tmp/bare/bin/pip install dist/semprini-0.1.0-py3-none-any.whl
    /tmp/bare/bin/python tools/release_smoke.py 0.1.0 dist

It checks that environment's own console script, so nothing has to be on PATH. Naming the
distribution directory adds one more check: that the wheel about to be published is named
what the download URL says it is.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from semprini import ONTOLOGY_PATH, compiler_version, ontology_version, wheel_url
from semprini.build import GENERATED_DIR, ONTOLOGY_FILE
from semprini.scaffold import WORKFLOW_DIR, WORKFLOWS


def console_script() -> Path:
    """The `semprini` command belonging to *this* interpreter, addressed by path.

    Not the `semprini` on PATH. A tool whose job is to report what one particular
    installation does would otherwise report on whichever installation the shell found
    first — the same mistake it exists to catch — and on Windows a virtual environment's
    scripts are usually not on PATH at all, so the check would simply not run where it was
    most needed.

    Three spellings, because they are what the two installers produce: pip writes an `.exe`
    launcher on Windows and an extensionless script elsewhere, while a Poetry development
    install writes a `.cmd`. Finding none of them is itself the finding — the wheel declares
    a console script (spec 5.1) and an installation without one cannot be used at all.
    """
    directory = Path(sys.executable).parent
    for name in ("semprini.exe", "semprini.cmd", "semprini") if os.name == "nt" else ("semprini",):
        if (directory / name).is_file():
            return directory / name
    raise SystemExit(f"no semprini console script in {directory} — the entry point is missing")


BASE_IRI = "https://semantics.example.com/"
"""The specification's own example value (spec 3.1). Nothing is compiled here and nothing is
kept, but a base IRI is permanent inside the instance that holds it, so even a throwaway one
is not borrowed from an organization that exists."""


def run(*command: str, cwd: Path | None = None) -> str:
    finished = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False
    )
    if finished.returncode != 0:
        raise SystemExit(
            f"`{' '.join(command)}` exited {finished.returncode}\n"
            f"{finished.stdout}{finished.stderr}"
        )
    return finished.stdout


def check_the_console_script_reports(version: str) -> list[str]:
    """`semprini version`, from the script the wheel installs rather than from an import.

    An entry point that does not resolve is invisible to every test in this project: the
    suite imports `semprini.cli` directly, and so proves the function exists rather than that
    anything can call it by name.
    """
    reported = run(str(console_script()), "version")
    if f"compiler {version}" not in reported:
        return [f"`semprini version` says {reported.strip()!r}, expected compiler {version}"]
    return []


def check_a_new_instance_pins(version: str, root: Path) -> list[str]:
    """The heart of it: what `semprini init` writes into a brand new instance.

    Both workflows and the instance's README carry the download URL for the version that
    created them (spec 5.7, 7). Asserted as the URL rather than as the version alone, because
    with no package index the version is only useful in the address it forms part of — an
    instance that names the right version at the wrong URL is an instance whose CI 404s every
    Monday morning.
    """
    run(
        str(console_script()),
        "init",
        "--base-iri",
        BASE_IRI,
        "--org",
        "example",
        "--dir",
        str(root),
    )

    url = wheel_url(version)
    problems = []

    for name in WORKFLOWS:
        text = (root / WORKFLOW_DIR / name).read_text(encoding="utf-8")
        if version not in text:
            problems.append(f"{name} does not pin {version}")
        elif text.count(version) != 1:
            # One occurrence, on the line an upgrade edits. More than one is a workflow
            # somebody upgrades halfway.
            problems.append(f"{name} names {version} {text.count(version)} times, expected once")
        if "%%" in text:
            problems.append(f"{name} still holds an unsubstituted placeholder")

    readme = (root / "README.md").read_text(encoding="utf-8")
    if url not in readme:
        problems.append(f"the instance README does not carry the download URL {url}")

    return problems


def check_the_metamodel_travelled(root: Path) -> list[str]:
    """The ontology the wheel carries, copied into the instance it just created.

    `sem.ttl` is package data rather than code, and package data is what a packaging change
    drops silently. An instance whose `generated/sem.ttl` is missing fails its first
    `semprini check` in somebody else's repository.
    """
    copied = root / GENERATED_DIR / ONTOLOGY_FILE
    if not copied.is_file():
        return [
            f"the new instance holds no {GENERATED_DIR}/{ONTOLOGY_FILE} — the ontology is missing"
        ]
    if copied.read_bytes() != ONTOLOGY_PATH.read_bytes():
        return [f"{GENERATED_DIR}/{ONTOLOGY_FILE} is not the ontology this wheel ships"]
    if f"{ontology_version()}" not in (root / "mappings" / "namespace.lock").read_text("utf-8"):
        return [f"the namespace lock does not record ontology {ontology_version()}"]
    return []


def check_the_built_wheel_is_named_as_promised(version: str, dist: Path) -> list[str]:
    """The half of the download URL that nothing else compares against anything.

    `wheel_url()` promises a filename as well as a tag directory, and every other check in
    this project compares that formula with itself — the workflows are rendered from it, and
    the tests assert the rendered result matches it. The one thing none of them looks at is
    the file actually built. A packaging change that normalized the distribution name
    differently would publish an asset under one name while every instance's weekly compile
    fetched another, and the first symptom would be a 404 in somebody else's CI.

    Checked against the release's own `dist/`, which is why this takes a directory rather
    than guessing one: the artifact being published is the only one worth checking.
    """
    expected = wheel_url(version).rsplit("/", 1)[-1]
    if (dist / expected).is_file():
        return []

    built = sorted(path.name for path in dist.glob("*.whl"))
    return [
        f"the release will publish {built or 'no wheel at all'}, but every instance built by "
        f"this version fetches {expected} — the download URL and the artifact disagree"
    ]


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(f"usage: {Path(argv[0]).name} <version> [dist-directory]", file=sys.stderr)
        return 2

    version = argv[1]
    installed = compiler_version()
    if installed != version:
        print(
            f"error: this environment holds semprini {installed}, not {version} — "
            f"run it against a virtual environment with the release installed",
            file=sys.stderr,
        )
        return 1

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "instance"
        problems = [
            *check_the_console_script_reports(version),
            *check_a_new_instance_pins(version, root),
            *check_the_metamodel_travelled(root),
        ]
        if len(argv) == 3:
            problems += check_the_built_wheel_is_named_as_promised(version, Path(argv[2]))

    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1

    print(f"semprini {version} installs, bootstraps an instance and pins {wheel_url(version)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

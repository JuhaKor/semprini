"""``semprini init`` — an empty instance repository, ready to compile (spec 5.7).

The one command that writes an instance rather than reading one, and the only place a
base IRI is chosen. Everything else about an instance is revisable: sources come and go,
labels change, the compiler is upgraded. The two values decided here — the base IRI and
the instance id — are frozen into ``mappings/namespace.lock`` on the spot and are
permanent in the strong sense, because every IRI this instance ever mints is built from
them and IRIs are never reused (spec 3.4).

Three properties follow.

*Nothing is written until everything is known.* The whole tree is rendered in memory and
every refusal is raised before the first byte reaches the disk, so a bad argument or an
existing instance leaves the target directory exactly as it was. There is no half-created
instance to clean up.

*Nothing here reaches the network.* No repository is created, no remote is configured, no
version is looked up (spec 11 #8). What an adopter does with the tree afterwards is
theirs; ``init`` produces files and a list of next steps.

*A source tree cannot bootstrap an instance.* The scaffold pins the plane version into two
workflows and into a manifest, and a version that identifies no release pins nothing (spec
4.3, 7).
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from semprini import ONTOLOGY_PATH, UNINSTALLED_VERSION, compiler_version, ontology_version
from semprini.build import GENERATED_DIR, ONTOLOGY_FILE, OutputFile
from semprini.config import (
    CONFIG_PATH,
    DEFAULT_LANGUAGE,
    ConfigError,
    is_slug,
)
from semprini.identity import ID_MAP_PATH, NAMESPACE_LOCK_PATH, IdMap, NamespaceLock
from semprini.lifecycle import MERGES_PATH, MergeRegister
from semprini.manifest import Manifest
from semprini.model import Issue, Severity, is_language_tag
from semprini.serialize import namespaces

__all__ = [
    "INSTANCE_TEMPLATES",
    "WORKFLOWS",
    "WORKFLOW_DIR",
    "WORKFLOW_TEMPLATES",
    "Scaffold",
    "ScaffoldError",
    "ScaffoldFile",
    "create",
    "init",
]

INSTANCE_TEMPLATES = Path(__file__).parent / "templates" / "instance"
"""The platform-neutral tree, materialized verbatim apart from placeholder substitution.

Inside the package rather than at the repository root, for the reason ``ontology/sem.ttl``
and ``shapes/core.ttl`` are: an adopter installs a wheel with pip and never sees this
repository, so anything ``init`` materializes has to travel in the distribution (spec 4.1).
"""

WORKFLOW_TEMPLATES = Path(__file__).parent / "workflows"
"""CI definitions, one directory per platform (spec 6.3).

Separate from the tree above because *where* a workflow file goes is platform-specific
while everything else in an instance is not. A port to GitLab adds a directory here and a
line in :data:`WORKFLOW_DIRS`, and touches no other part of the scaffold.
"""

WORKFLOW_PLATFORM = "github"
"""The platform ``init`` materializes. The only GitHub-specific thing in the scaffold."""

WORKFLOW_DIRS: Mapping[str, PurePosixPath] = {"github": PurePosixPath(".github/workflows")}

WORKFLOWS: tuple[str, ...] = ("compile.yml", "validate.yml")
"""The two workflows of spec 6.2, materialized from ``WORKFLOW_TEMPLATES``."""

WORKFLOW_DIR = WORKFLOW_DIRS[WORKFLOW_PLATFORM]

# `%%name%%` rather than the more usual `{{ name }}`: the workflow templates are full of
# GitHub's own `${{ ... }}` expressions, and a substitution syntax that collided with them
# would either eat one or make "is every placeholder resolved?" unanswerable.
_PLACEHOLDER = re.compile(r"%%(\w+)%%")


class ScaffoldError(ConfigError):
    """``init`` refuses to run — CLI exit code 2 (spec 5.1).

    A :class:`~semprini.config.ConfigError` because every way this command refuses is
    about the arguments it was given or the directory it was pointed at, which is exactly
    what exit 2 tells an operator: go and fix the invocation, nothing was written. It
    writes no content, so it can never produce a validation failure.
    """

    noun = "bootstrap error"


@dataclass(frozen=True, slots=True)
class ScaffoldFile:
    """One file of a new instance, rendered but not yet written."""

    path: PurePosixPath
    """Relative to the instance root, in POSIX form: a scaffold is described the same way
    on every platform, and these paths are printed and compared in tests."""

    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Scaffold:
    """A complete instance, rendered in memory (spec 5.7).

    Held before it is written for the reason a run holds its output: a refusal has to
    leave the target directory untouched, and there is no way to promise that while
    writing file by file.
    """

    root: Path
    files: tuple[ScaffoldFile, ...]
    base_iri: str
    instance_id: str
    version: str
    """The plane version pinned into the workflows and recorded in the manifest."""

    def write(self) -> tuple[Path, ...]:
        """Write every file, creating the directories it needs.

        LF line endings throughout, like everything else the compiler owns: the instance's
        ``.gitattributes`` says the repository is LF (spec 4.3), and a scaffold written
        with the platform default would contradict it on the machine that created it.
        """
        written: list[Path] = []
        for file in self.files:
            path = self.root / Path(file.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(file.text, encoding="utf-8", newline="\n")
            written.append(path)
        return tuple(written)

    def summary(self) -> tuple[str, ...]:
        """The instance, its secrets and what to do next — step 6 of spec 5.7.

        Deliberately ASCII, like a run's summary: this is printed to whatever console the
        command was started from, and a decorative character on a Windows cp1252 console
        would raise ``UnicodeEncodeError`` after the tree was written, turning a successful
        bootstrap into a traceback.
        """
        lines = [f"created an instance in {self.root}", ""]
        lines.extend(f"  {file.path}" for file in self.files)
        lines.extend(
            [
                "",
                f"base IRI      {self.base_iri}",
                f"instance id   {self.instance_id}",
                f"plane version {self.version}, pinned in both workflows",
                "",
                "The base IRI and the instance id are now frozen by "
                f"{NAMESPACE_LOCK_PATH.as_posix()}.",
                "Every IRI this instance mints is built from them and is permanent, so change them",
                "now or not at all.",
                "",
                "No credentials are needed: every adapter this version ships reads files that",
                "are in the repository. If one that calls an API is installed later, it will name",
                "an environment variable, and the workflow will need a repository secret of that",
                "name -- never the value in config/semprini.yaml.",
                "",
                "Next:",
                "  1. git init, commit this tree, and push it to an empty repository.",
                "  2. Protect main: pull requests only, validation required, one review.",
                "  3. Allow GitHub Actions to create pull requests, in the repository's",
                "     Actions settings -- the scheduled compile opens one.",
                f"  4. Add your first source under 'sources:' in {CONFIG_PATH.as_posix()};",
                "     'semprini adapters' lists what is installed.",
                "  5. Run 'semprini run' and review what it wrote.",
            ]
        )
        return tuple(lines)


def init(
    target: Path | None = None,
    *,
    base_iri: str,
    org: str,
    default_language: str = DEFAULT_LANGUAGE,
    compiler: str | None = None,
    ontology: str | None = None,
    today: datetime.date | None = None,
) -> Scaffold:
    """Create an instance repository in ``target`` (spec 5.7)."""
    scaffold = create(
        target,
        base_iri=base_iri,
        org=org,
        default_language=default_language,
        compiler=compiler,
        ontology=ontology,
        today=today,
    )
    scaffold.write()
    return scaffold


def create(
    target: Path | None = None,
    *,
    base_iri: str,
    org: str,
    default_language: str = DEFAULT_LANGUAGE,
    compiler: str | None = None,
    ontology: str | None = None,
    today: datetime.date | None = None,
) -> Scaffold:
    """Render the instance ``init`` would write, without writing it.

    ``compiler``, ``ontology`` and ``today`` are injected for the reason a run injects
    them — a test pins them, and nothing but the caller reads a clock (spec 4.3) — and a
    production caller passes none of the three.

    Raises :class:`ScaffoldError` for anything that would produce an instance nobody can
    use: an argument that cannot be frozen, a plane version that pins nothing, or a target
    directory that already holds one.
    """
    root = Path.cwd() if target is None else Path(target)
    version = compiler_version() if compiler is None else compiler
    metamodel = ontology_version() if ontology is None else ontology
    date = datetime.date.today() if today is None else today

    _check_arguments(base_iri, org, default_language)
    _check_the_plane_is_installed(version)

    values = {
        "base_iri": base_iri,
        "org": org,
        "default_language": default_language,
        "version": version,
    }
    files = tuple(
        sorted(
            [
                *_templated(INSTANCE_TEMPLATES, PurePosixPath(), values),
                *_templated(WORKFLOW_TEMPLATES / WORKFLOW_PLATFORM, WORKFLOW_DIR, values),
                *_identity(base_iri=base_iri, org=org, ontology=metamodel, today=date),
                *_generated(compiler=version, ontology=metamodel),
            ],
            key=lambda file: file.path,
        )
    )
    _check_nothing_is_overwritten(root, files)
    return Scaffold(root=root, files=files, base_iri=base_iri, instance_id=org, version=version)


# ----------------------------------------------------------------------------- refusals


def _check_arguments(base_iri: str, org: str, default_language: str) -> None:
    """Every argument that will be frozen, checked before any of it is (spec 3.4).

    Collected rather than raised one at a time, like every other refusal in this project:
    an operator retyping a bootstrap command deserves all of what is wrong with it.
    """
    issues: list[Issue] = []
    try:
        # The serializer's own rule, so a base IRI accepted here cannot fail when the
        # instance writes its first file (spec 5.5).
        namespaces(base_iri)
    except ValueError as error:
        issues.append(Issue(Severity.ERROR, str(error), "--base-iri"))
    if not is_slug(org):
        issues.append(
            Issue(
                Severity.ERROR,
                f"must be a slug -- lower-case letters, digits, '-' or '_' -- got {org!r}; "
                f"it becomes this instance's permanent id",
                "--org",
            )
        )
    if not is_language_tag(default_language):
        issues.append(
            Issue(Severity.ERROR, f"not a language tag: {default_language!r}", "--language")
        )
    if issues:
        raise ScaffoldError(issues)


def _check_the_plane_is_installed(version: str) -> None:
    """A source tree cannot bootstrap an instance (spec 4.3, 7).

    Two of the files below pin this version: the workflows, which an adopter's CI installs
    from, and the manifest, whose whole job is to say which release produced ``generated/``.
    ``0.0.0+source`` identifies no release — two different working trees report the same
    string — so an instance created from one would carry a workflow that cannot install and
    a manifest the drift check cannot use.

    :meth:`semprini.manifest.Manifest.create` refuses the same value and is the backstop;
    this is here so that the message names the pin an operator would otherwise discover
    from a failing CI job weeks later.
    """
    if version == UNINSTALLED_VERSION:
        raise ScaffoldError(
            [
                Issue(
                    Severity.ERROR,
                    f"the compiler is running from a source tree and reports version "
                    f"{version!r}, which identifies no release; a new instance pins the "
                    f"plane version in both of its workflows and in its manifest, so "
                    f"install the package before creating one",
                    "semprini",
                )
            ]
        )


def _check_nothing_is_overwritten(root: Path, files: Sequence[ScaffoldFile]) -> None:
    """Refuse to write over an instance that already exists (spec 5.7).

    The namespace lock is the case the spec names and the one that matters: it is the
    frozen record of a decision that cannot be taken twice, so a second ``init`` over an
    existing instance would replace permanent identity with a fresh copy while
    ``mappings/id-map.csv`` went on describing the old one.

    Every other file it would write is refused too. Nothing in the scaffold is safe to
    clobber -- a steward's ``config/semprini.yaml``, their overlays README, a workflow they
    have upgraded -- and "it only overwrote the ones you had not touched" is not a state
    anyone can reason about afterwards.
    """
    if root.exists() and not root.is_dir():
        # Otherwise the first mkdir raises an OSError naming a path and nothing else, from
        # inside a write that has already begun.
        raise ScaffoldError([Issue(Severity.ERROR, "is not a directory", str(root))])
    if (root / NAMESPACE_LOCK_PATH).exists():
        raise ScaffoldError(
            [
                Issue(
                    Severity.ERROR,
                    "this directory already holds an instance: its base IRI was frozen "
                    "when it was created and a second bootstrap would mint a parallel set "
                    "of IRIs beside the ones in mappings/id-map.csv (spec 3.4)",
                    str(root / NAMESPACE_LOCK_PATH),
                )
            ]
        )
    existing = [file.path for file in files if (root / Path(file.path)).exists()]
    if existing:
        raise ScaffoldError(
            [
                Issue(
                    Severity.ERROR,
                    "already exists and would be overwritten; 'semprini init' creates an "
                    "instance and never edits one",
                    str(path),
                )
                for path in existing
            ]
        )


# ------------------------------------------------------------------------- the contents


def _templated(
    directory: Path, prefix: PurePosixPath, values: Mapping[str, str]
) -> Iterator[ScaffoldFile]:
    """Every file under ``directory``, rendered and re-rooted at ``prefix``.

    Read as text and re-written with LF, never copied byte for byte: a template checked out
    on a machine with ``core.autocrlf=true`` holds CRLF, and an instance whose
    ``.gitattributes`` promises LF must not be created with the opposite.

    A missing template directory is refused rather than read as an empty one. These files
    ship inside the wheel (spec 4.1), so their absence means a broken or partial install —
    and the alternative is an instance created without its configuration, its workflows or
    its ``.gitattributes``, which nothing downstream would attribute to this.
    """
    if not directory.is_dir():
        raise ScaffoldError(
            [
                Issue(
                    Severity.ERROR,
                    "is missing from this installation of semprini; reinstall the package",
                    str(directory),
                )
            ]
        )
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        relative = PurePosixPath(path.relative_to(directory).as_posix())
        yield ScaffoldFile(prefix / relative, _render(path.read_text(encoding="utf-8"), values))


def _render(text: str, values: Mapping[str, str]) -> str:
    """Substitute ``%%name%%`` throughout, refusing to leave one unresolved.

    An unknown placeholder is a bug in this package's own templates, not in anything an
    adopter did — and one that would otherwise ship a literal ``%%og%%`` into a new
    instance's README, where nobody would ever trace it back here.
    """

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise ValueError(
                f"template placeholder {match.group(0)!r} has no value; known placeholders: "
                f"{', '.join(sorted(values))}"
            )
        return values[name]

    return _PLACEHOLDER.sub(substitute, text)


def _identity(
    *, base_iri: str, org: str, ontology: str, today: datetime.date
) -> Iterator[ScaffoldFile]:
    """``mappings/`` — the lock, and the two registers with their headers (spec 5.7 step 3).

    Written through the classes that own the files rather than as literal text, so that a
    column added to either register reaches a new instance without anyone remembering to
    edit a template. Both registers are empty and both are legal empty: a fresh instance
    has minted nothing and merged nothing.
    """
    lock = NamespaceLock(base_iri=base_iri, instance_id=org, ontology_version=ontology, date=today)
    yield ScaffoldFile(PurePosixPath(NAMESPACE_LOCK_PATH.as_posix()), lock.dumps())
    yield ScaffoldFile(PurePosixPath(ID_MAP_PATH.as_posix()), IdMap().dumps())
    yield ScaffoldFile(PurePosixPath(MERGES_PATH.as_posix()), MergeRegister().dumps())


def _generated(*, compiler: str, ontology: str) -> Iterator[ScaffoldFile]:
    """``generated/`` — the metamodel copy and its manifest (spec 5.7 step 4).

    A fresh instance has no content, so this is the whole of ``generated/``: the pinned
    ontology, copied verbatim as every run copies it (spec 4.2), and a manifest recording
    its hash and the two versions. That is what lets ``semprini check`` pass on an instance
    that has never been compiled — the alternative, an empty directory git cannot even
    commit, would have a new adopter's very first CI run fail on a missing manifest.
    """
    copy = OutputFile(name=ONTOLOGY_FILE, text=ONTOLOGY_PATH.read_text(encoding="utf-8"))
    manifest = Manifest.create([copy], compiler=compiler, ontology=ontology)
    for file in (copy, manifest.to_file()):
        yield ScaffoldFile(PurePosixPath((GENERATED_DIR / file.name).as_posix()), file.text)

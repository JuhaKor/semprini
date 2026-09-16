"""``semprini init`` — an empty instance repository, ready to compile (spec 5.7).

The only place a base IRI and instance id are chosen; both are frozen into
``mappings/namespace.lock`` (spec 3.4). The tree is rendered in memory and every refusal
raised before anything is written. Nothing reaches the network (spec 11 #8), and a
source tree cannot bootstrap an instance because its version pins nothing (spec 4.3, 7).
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from semprini import (
    ONTOLOGY_PATH,
    UNINSTALLED_VERSION,
    compiler_version,
    ontology_version,
    wheel_url,
)
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
Inside the package so that it travels in the wheel (spec 4.1)."""

WORKFLOW_TEMPLATES = Path(__file__).parent / "workflows"
"""CI definitions, one directory per platform (spec 6.3). A new platform adds a directory
here and a line in :data:`WORKFLOW_DIRS`."""

WORKFLOW_PLATFORM = "github"
"""The platform ``init`` materializes. The only GitHub-specific thing in the scaffold."""

WORKFLOW_DIRS: Mapping[str, PurePosixPath] = {"github": PurePosixPath(".github/workflows")}

WORKFLOWS: tuple[str, ...] = ("compile.yml", "validate.yml")
"""The two workflows of spec 6.2, materialized from ``WORKFLOW_TEMPLATES``."""

WORKFLOW_DIR = WORKFLOW_DIRS[WORKFLOW_PLATFORM]

# `%%name%%`, because the workflow templates are full of GitHub's own `${{ ... }}`.
_PLACEHOLDER = re.compile(r"%%(\w+)%%")


class ScaffoldError(ConfigError):
    """``init`` refuses to run — CLI exit code 2 (spec 5.1). Nothing was written."""

    noun = "bootstrap error"


@dataclass(frozen=True, slots=True)
class ScaffoldFile:
    """One file of a new instance, rendered but not yet written."""

    path: PurePosixPath
    """Relative to the instance root, in POSIX form on every platform."""

    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Scaffold:
    """A complete instance, rendered in memory before anything is written (spec 5.7)."""

    root: Path
    files: tuple[ScaffoldFile, ...]
    base_iri: str
    instance_id: str
    version: str
    """The plane version pinned into the workflows and recorded in the manifest."""

    def write(self) -> tuple[Path, ...]:
        """Write every file with LF line endings, creating the directories it needs (spec 4.3)."""
        written: list[Path] = []
        for file in self.files:
            path = self.root / Path(file.path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(file.text, encoding="utf-8", newline="\n")
            written.append(path)
        return tuple(written)

    def summary(self) -> tuple[str, ...]:
        """The instance, its secrets and what to do next (spec 5.7 step 6). ASCII only, for
        a cp1252 console."""
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

    ``compiler``, ``ontology`` and ``today`` let a test pin them (spec 4.3). Raises
    :class:`ScaffoldError` for a bad argument, an uninstalled plane, or a target that
    already holds an instance or any file the scaffold would write.
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
        # Rendered, not written into the template, so `semprini.wheel_url` stays the one definition.
        "wheel_url": wheel_url(version),
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
    """Every argument that will be frozen, checked before any of it is (spec 3.4)."""
    issues: list[Issue] = []
    try:
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
    """A source tree cannot bootstrap an instance: its version pins nothing (spec 4.3, 7)."""
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
    """Refuse to write over an existing instance, or over any file the scaffold would write (spec
    5.7).
    """
    if root.exists() and not root.is_dir():
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

    Read as text, so a CRLF checkout is written as LF. A missing directory is a broken
    install (spec 4.1) and raises :class:`ScaffoldError`.
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
    """Substitute ``%%name%%`` throughout; an unknown placeholder is a template bug and raises."""

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
    """``mappings/``: the lock and the two empty registers, rendered by the classes that
    own them (spec 5.7 step 3)."""
    lock = NamespaceLock(base_iri=base_iri, instance_id=org, ontology_version=ontology, date=today)
    yield ScaffoldFile(PurePosixPath(NAMESPACE_LOCK_PATH.as_posix()), lock.dumps())
    yield ScaffoldFile(PurePosixPath(ID_MAP_PATH.as_posix()), IdMap().dumps())
    yield ScaffoldFile(PurePosixPath(MERGES_PATH.as_posix()), MergeRegister().dumps())


def _generated(*, compiler: str, ontology: str) -> Iterator[ScaffoldFile]:
    """``generated/``: the metamodel copy and its manifest, so that ``semprini check`` passes
    before the first compile (spec 5.7 step 4)."""
    copy = OutputFile(name=ONTOLOGY_FILE, text=ONTOLOGY_PATH.read_text(encoding="utf-8"))
    manifest = Manifest.create([copy], compiler=compiler, ontology=ontology)
    for file in (copy, manifest.to_file()):
        yield ScaffoldFile(PurePosixPath((GENERATED_DIR / file.name).as_posix()), file.text)

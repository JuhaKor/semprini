"""``generated/.manifest.json`` — what makes ``generated/`` machine-owned (spec 4.3, 7). A content
hash of every file the compiler wrote, plus the compiler and ontology versions that wrote them,
so that CI detects a hand edit (spec 6.1 check 2) and version drift (spec 6.1 check 3). No
timestamps. The manifest itself and ``.report.md`` are not hashed (spec 5.6).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from semprini import (
    UNINSTALLED_VERSION,
    compiler_version,
    ontology_version,
    version_parts,
    wheel_url,
)
from semprini.build import GENERATED_DIR, OutputFile
from semprini.model import Issue, IssueError, Severity
from semprini.report import REPORT_FILE

__all__ = [
    "MANIFEST_FILE",
    "Manifest",
    "ManifestError",
    "digest",
    "is_generated_file_name",
]

MANIFEST_FILE = ".manifest.json"

_ALGORITHM = "sha256"

_NOT_RECORDED = frozenset({MANIFEST_FILE, REPORT_FILE})
"""The manifest cannot hash itself, and the report is not governed content (spec 5.6)."""

_KEYS = ("compiler_version", "files", "ontology_version")

_DIGEST = re.compile(rf"{_ALGORITHM}:[0-9a-f]{{64}}")


def digest(data: bytes) -> str:
    """The recorded hash of one file's bytes, algorithm included."""
    return f"{_ALGORITHM}:{hashlib.sha256(data).hexdigest()}"


class ManifestError(IssueError):
    """The manifest is missing, malformed, or disagrees with the files — exit code 1 (spec 5.1)."""

    noun = "manifest error"


@dataclass(frozen=True, slots=True)
class Manifest:
    """What the compiler wrote, and which versions wrote it (spec 4.3)."""

    compiler_version: str
    ontology_version: str

    files: Mapping[str, str] = field(hash=False)
    """File name under ``generated/`` → :func:`digest` of its bytes."""

    def __post_init__(self) -> None:
        # A recorded name becomes a path segment under generated/ (spec 4.3).
        for name in self.files:
            if not is_generated_file_name(name):
                raise ManifestError(
                    [Issue(Severity.ERROR, f"not a file name in generated/: {name!r}", str(name))]
                )
        object.__setattr__(self, "files", MappingProxyType(dict(self.files)))

    # ------------------------------------------------------------------ writing

    @classmethod
    def create(
        cls,
        files: Sequence[OutputFile],
        *,
        compiler: str | None = None,
        ontology: str | None = None,
    ) -> Manifest:
        """Record the files a run produced.

        ``compiler`` and ``ontology`` let a test pin the versions; production callers pass
        neither (spec 7). Raises :class:`ManifestError` for an uninstalled compiler, whose
        version identifies no release, and for a file that is never recorded.
        """
        recorded = compiler_version() if compiler is None else compiler
        if recorded == UNINSTALLED_VERSION:
            raise ManifestError(
                [
                    Issue(
                        Severity.ERROR,
                        f"the compiler is running from a source tree and reports version "
                        f"{recorded!r}, which identifies no release; install the package "
                        f"before writing to generated/ (spec 7)",
                        MANIFEST_FILE,
                    )
                ]
            )

        hashes: dict[str, str] = {}
        for file in files:
            if file.name in _NOT_RECORDED:
                raise ManifestError(
                    [
                        Issue(
                            Severity.ERROR,
                            f"{file.name} is not recorded in the manifest and must not be "
                            f"passed to it",
                            file.name,
                        )
                    ]
                )
            if file.name in hashes:
                raise ManifestError(
                    [Issue(Severity.ERROR, f"{file.name} was produced twice", file.name)]
                )
            hashes[file.name] = digest(file.text.encode("utf-8"))
        return cls(
            compiler_version=recorded,
            ontology_version=ontology_version() if ontology is None else ontology,
            files=hashes,
        )

    def dumps(self) -> str:
        """The manifest as it is written: sorted, indented, one trailing LF (spec 5.5)."""
        document = {
            "compiler_version": self.compiler_version,
            "files": dict(self.files),
            "ontology_version": self.ontology_version,
        }
        return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def to_file(self) -> OutputFile:
        """The manifest as one of the run's output files, written by
        :func:`semprini.build.write_all`.
        """
        return OutputFile(name=MANIFEST_FILE, text=self.dumps())

    # ------------------------------------------------------------------ reading

    @classmethod
    def load(cls, repo_root: Path | None = None) -> Manifest:
        """Read ``<repo_root>/generated/.manifest.json``. A missing
        manifest is an error (spec 5.7).
        """
        path = (Path.cwd() if repo_root is None else Path(repo_root)) / GENERATED_DIR
        path = path / MANIFEST_FILE
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ManifestError(
                [
                    Issue(
                        Severity.ERROR,
                        "the manifest is missing; generated/ cannot be checked against "
                        "anything until a compile writes one",
                        str(path),
                    )
                ]
            ) from None
        except UnicodeDecodeError:
            raise ManifestError(
                [Issue(Severity.ERROR, "the manifest is not valid UTF-8", str(path))]
            ) from None
        except OSError as error:
            raise ManifestError(
                [Issue(Severity.ERROR, f"cannot read the manifest: {error}", str(path))]
            ) from None
        return cls.loads(text, origin=str(path))

    @classmethod
    def loads(cls, text: str, *, origin: str | None = None) -> Manifest:
        """Parse a manifest held in a string, reporting every problem at once."""
        try:
            document = json.loads(text)
        except ValueError as error:
            raise ManifestError(
                [Issue(Severity.ERROR, f"the manifest is not valid JSON: {error}")],
                origin=origin,
            ) from None

        issues: list[Issue] = []
        if not isinstance(document, dict):
            raise ManifestError(
                [Issue(Severity.ERROR, "the manifest must be a JSON object")], origin=origin
            )

        for key in sorted(set(document) - set(_KEYS)):
            issues.append(Issue(Severity.ERROR, f"unknown key {key!r}", key))
        for key in _KEYS:
            if key not in document:
                issues.append(Issue(Severity.ERROR, f"missing key {key!r}", key))

        versions = {
            key: _string(document, key, issues) for key in ("compiler_version", "ontology_version")
        }
        files = _files(document, issues)
        if issues:
            raise ManifestError(issues, origin=origin)
        return cls(
            compiler_version=versions["compiler_version"] or "",
            ontology_version=versions["ontology_version"] or "",
            files=files,
        )

    # ------------------------------------------------------------------ checks

    def verify(self, repo_root: Path | None = None) -> tuple[Issue, ...]:
        """Recompute every hash and compare (spec 6.1 check 2).

        Reports a changed file, a missing file and an unrecorded file alike; every
        problem is returned, not the first.
        """
        directory = (Path.cwd() if repo_root is None else Path(repo_root)) / GENERATED_DIR
        issues: list[Issue] = []
        for name in sorted(self.files):
            path = directory / name
            try:
                found = digest(path.read_bytes())
            except FileNotFoundError:
                issues.append(
                    Issue(Severity.ERROR, "recorded in the manifest but missing", str(path))
                )
                continue
            except OSError as error:
                issues.append(Issue(Severity.ERROR, f"cannot read: {error}", str(path)))
                continue
            if found != self.files[name]:
                issues.append(
                    Issue(
                        Severity.ERROR,
                        "does not match the manifest; generated/ is written by the "
                        "compiler and edited by nothing else (spec 4.3)",
                        str(path),
                    )
                )

        for relative in sorted(_present(directory)):
            if relative not in self.files and relative not in _NOT_RECORDED:
                issues.append(
                    Issue(
                        Severity.ERROR,
                        "is not recorded in the manifest; nothing but the compiler writes "
                        "to generated/ (spec 4.3)",
                        str(directory / relative),
                    )
                )
        return tuple(issues)

    def check_versions(
        self, *, compiler: str | None = None, ontology: str | None = None
    ) -> tuple[Issue, ...]:
        """Compare the recorded versions with the running ones (spec 6.1 check 3, 7).

        The advice depends on which way the drift points: an instance ahead of the
        installed release has a stale pin, not a migration to run.
        """
        running = {
            "compiler": compiler_version() if compiler is None else compiler,
            "ontology": ontology_version() if ontology is None else ontology,
        }
        recorded = {"compiler": self.compiler_version, "ontology": self.ontology_version}
        advice = _advice(recorded["compiler"], running["compiler"])
        return tuple(
            Issue(
                Severity.ERROR,
                f"generated/ was compiled with {which} {recorded[which]}, but {running[which]} "
                f"is running; {advice} (spec 7)",
                f"{MANIFEST_FILE}#{which}_version",
            )
            for which in ("compiler", "ontology")
            if recorded[which] != running[which]
        )


def _advice(recorded: str, running: str) -> str:
    """What to do about drift: migrate forward, fix a stale pin, or, when the versions
    cannot be ordered, make them agree."""
    here, there = version_parts(running), version_parts(recorded)
    if here is None or there is None:
        return "the two must agree before this instance can be committed"
    if here < there:
        return (
            f"the installed release is older than the one that compiled generated/, and a "
            f"migration only ever moves forward; install semprini {recorded} from "
            f"{wheel_url(recorded)} — if this is CI, the pinned version in the workflow is "
            f"the stale value"
        )
    return f"run `semprini migrate --to {running}` in its own PR"


def _present(directory: Path) -> list[str]:
    """Every file under ``generated/``, recursively, relative to it; none if it does not exist."""
    if not directory.is_dir():
        return []
    return [
        path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()
    ]


def _string(document: Mapping[str, Any], key: str, issues: list[Issue]) -> str | None:
    # An absent key is already reported; a present but null one is reported here.
    if key not in document:
        return None
    value = document[key]
    if not isinstance(value, str) or not value:
        issues.append(Issue(Severity.ERROR, f"{key} must be a non-empty string", key))
        return None
    return value


def _files(document: Mapping[str, Any], issues: list[Issue]) -> Mapping[str, str]:
    if "files" not in document:  # already reported as a missing key
        return {}
    value = document["files"]
    if not isinstance(value, dict):
        issues.append(Issue(Severity.ERROR, "files must be a JSON object", "files"))
        return {}
    hashes: dict[str, str] = {}
    for name, recorded in value.items():
        location = f"files.{name}"
        if not is_generated_file_name(name):
            issues.append(
                Issue(Severity.ERROR, f"not a file name in generated/: {name!r}", location)
            )
            continue
        if name in _NOT_RECORDED:
            issues.append(
                Issue(Severity.ERROR, f"{name} is never recorded by the compiler", location)
            )
            continue
        if not isinstance(recorded, str) or not _DIGEST.fullmatch(recorded):
            issues.append(
                Issue(Severity.ERROR, f"not a {_ALGORITHM} digest: {recorded!r}", location)
            )
            continue
        hashes[name] = recorded
    return hashes


def is_generated_file_name(name: Any) -> bool:
    """Whether ``name`` names a file directly inside ``generated/`` and nothing else."""
    if not isinstance(name, str) or not name or name in {".", ".."}:
        return False
    # Both separators, whatever the platform.
    return "/" not in name and "\\" not in name and not PurePosixPath(name).is_absolute()

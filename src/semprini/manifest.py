"""``generated/.manifest.json`` — what makes ``generated/`` machine-owned (spec 4.3, 7).

Every other rule about ``generated/`` is a convention until something enforces it. This
module is that something: it records a content hash of every file the compiler wrote,
plus the compiler and ontology versions that wrote them, so that CI can answer two
questions no amount of review discipline answers reliably.

*Did a human edit a generated file?* A hand-corrected label in ``concepts-sales.ttl`` is
invisible in a PR that also contains a real change, and it would be silently reverted by
the next compile — after living in the graph long enough for something to depend on it.
A recomputed hash catches it (spec 6.1 check 2).

*Is this output still the output of the running compiler?* An upgrade that reflows files
must be a deliberate "recompile with `<version>`" PR, not a surprise mixed into a content
change (spec 7). The recorded versions are what make that drift visible (spec 6.1 check 3).

The manifest carries **no timestamps** and nothing else that varies between two runs of
the same input: it is itself a governed file, and one that changed on every run would make
every scheduled compile open an empty PR.

Two files under ``generated/`` are deliberately **not** hashed: this one, which cannot
contain its own hash, and ``.report.md``, which is prose about a run rather than governed
content and is written on different terms (spec 5.6).
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

from semprini import UNINSTALLED_VERSION, compiler_version, ontology_version
from semprini.build import GENERATED_DIR, OutputFile
from semprini.model import Issue, IssueError, Severity
from semprini.report import REPORT_FILE

__all__ = [
    "MANIFEST_FILE",
    "Manifest",
    "ManifestError",
    "digest",
]

MANIFEST_FILE = ".manifest.json"

_ALGORITHM = "sha256"

_NOT_RECORDED = frozenset({MANIFEST_FILE, REPORT_FILE})
"""The manifest cannot hash itself, and the report is not governed content (spec 5.6)."""

_KEYS = ("compiler_version", "files", "ontology_version")

_DIGEST = re.compile(rf"{_ALGORITHM}:[0-9a-f]{{64}}")


def digest(data: bytes) -> str:
    """The recorded hash of one file's bytes.

    The algorithm is written into every value rather than declared once at the top of the
    document, so that a line of the manifest means something on its own and a change of
    algorithm cannot be mistaken for a change of content.
    """
    return f"{_ALGORITHM}:{hashlib.sha256(data).hexdigest()}"


class ManifestError(IssueError):
    """The manifest is missing, malformed, or disagrees with the files — exit code 1.

    A validation failure rather than a configuration error (spec 5.1): the manifest is
    written by the compiler, so an operator fixes it by running the compiler, not by
    editing a setting.
    """

    noun = "manifest error"


@dataclass(frozen=True, slots=True)
class Manifest:
    """What the compiler wrote, and which versions wrote it (spec 4.3)."""

    compiler_version: str
    ontology_version: str

    files: Mapping[str, str] = field(hash=False)
    """File name under ``generated/`` → :func:`digest` of its bytes.

    Excluded from the generated ``__hash__`` but not from ``__eq__``, the pattern every
    frozen dataclass here that holds a mapping follows: a mapping is unhashable, and a
    class advertised as frozen that cannot go in a set is a trap for the next caller."""

    def __post_init__(self) -> None:
        # The invariant, enforced where a manifest is built rather than where a path is
        # composed from it: a recorded name is used as a path segment under generated/,
        # so one that escapes would have verification read and hash a file outside the
        # machine-owned directory this class exists to bound (spec 4.3). ``loads`` filters
        # these out first, with the offending key named; this catches every other way one
        # could arrive.
        for name in self.files:
            if not _is_generated_file_name(name):
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

        ``compiler`` and ``ontology`` are injected so that a test can pin them; production
        callers pass neither and get the versions actually running (spec 7).

        An uninstalled compiler is **refused**. Running from a source tree with nothing
        installed reports version ``0.0.0+source``, which pins nothing: two different
        working trees record the same string, and the drift check (spec 6.1 check 3) would
        pass between them. A manifest is a promise about which release produced a file,
        and a source tree cannot make it.
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
                # A caller bug, not a file to skip quietly: passing the manifest to itself
                # means whatever it recorded would be stale the moment it was written.
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
        """The manifest as it is written — sorted, indented, one trailing LF.

        Sorted at both levels and formatted the same way every time, for the same reason
        the Turtle is (spec 5.5): a reviewer reads the diff, and a re-ordered JSON object
        would make one changed file look like a rewritten manifest.
        """
        document = {
            "compiler_version": self.compiler_version,
            "files": dict(self.files),
            "ontology_version": self.ontology_version,
        }
        return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def to_file(self) -> OutputFile:
        """The manifest as one of the run's output files.

        Returned this way so that it is written by the same call that writes the Turtle
        (:func:`semprini.build.write_all`), rather than through a second writer that could
        disagree about encoding or line endings. ``graph`` is ``None``: it is not RDF.
        """
        return OutputFile(name=MANIFEST_FILE, text=self.dumps())

    # ------------------------------------------------------------------ reading

    @classmethod
    def load(cls, repo_root: Path | None = None) -> Manifest:
        """Read ``<repo_root>/generated/.manifest.json``.

        A missing manifest is an error, unlike a missing ID map: ``semprini init`` writes
        one (spec 5.7 step 4), so an instance without one has had it deleted, and treating
        that as "nothing to check" would turn the integrity check off by removing a file.
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
            # Rejected rather than ignored, for the reason configuration rejects unknown
            # keys (spec 5.1): a key the compiler does not read is either a typo or a
            # newer manifest this version cannot honestly check.
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

        Three ways to fail, and all three are the same underlying event — something other
        than the compiler wrote in ``generated/``: a recorded file whose bytes changed, a
        recorded file that is gone, and a file present that the manifest does not know
        about. The third matters as much as the first: an instance can otherwise
        accumulate output from a scheme that no longer exists, and a consumer loading the
        directory from Git would read statements no source still makes.

        Every problem is returned, not the first: these are read in CI.
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

        Drift is not a defect in the output — the committed files are exactly what the
        recorded version produced. It is a statement that the instance has not been
        recompiled since the plane was upgraded, which is a separate, reviewable PR
        precisely so that an upgrade's reflow never arrives mixed into a content change.
        """
        running = {
            "compiler": compiler_version() if compiler is None else compiler,
            "ontology": ontology_version() if ontology is None else ontology,
        }
        recorded = {"compiler": self.compiler_version, "ontology": self.ontology_version}
        return tuple(
            Issue(
                Severity.ERROR,
                f"generated/ was compiled with {which} {recorded[which]}, but {running[which]} "
                f"is running; recompile the instance in its own PR (spec 7)",
                f"{MANIFEST_FILE}#{which}_version",
            )
            for which in ("compiler", "ontology")
            if recorded[which] != running[which]
        )


def _present(directory: Path) -> list[str]:
    """Every file under ``generated/``, relative to it, or none if it does not exist.

    Walked recursively although ``generated/`` is flat (spec 4.2), because the point of
    the unrecorded-file check is stale output a consumer would still load from Git:
    ``generated/old/concepts-retired.ttl`` is read by anyone who parses the directory,
    and a check that only looked at the top level would pass it.
    """
    if not directory.is_dir():
        return []
    return [
        path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()
    ]


def _string(document: Mapping[str, Any], key: str, issues: list[Issue]) -> str | None:
    # An absent key is already reported; a key present but null is not the same thing and
    # is reported here, or a manifest could disable a version check by nulling it out.
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
        if not _is_generated_file_name(name):
            # A recorded name is used as a path segment under generated/, so a
            # hand-edited manifest holding "../../secrets" would have verification read
            # and hash a file outside the machine-owned directory it is meant to bound
            # (spec 4.3). The same escape the build stage refuses for a scheme slug.
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


def _is_generated_file_name(name: Any) -> bool:
    """Whether ``name`` names a file directly inside ``generated/`` and nothing else."""
    if not isinstance(name, str) or not name or name in {".", ".."}:
        return False
    # Both separators, whatever the platform: a manifest written on one machine is
    # verified on another, and a backslash is a path segment on exactly one of them.
    return "/" not in name and "\\" not in name and not PurePosixPath(name).is_absolute()

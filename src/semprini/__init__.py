"""Semprini — a compiler that turns modelled business vocabularies into governed RDF.

``docs/rdf-repo-and-compiler-spec.md`` is the authoritative specification; module
docstrings name the sections they implement.

Two version numbers are published independently (spec 7): the compiler version is this
package's own, and the ontology version belongs to the bundled ``sem:`` metamodel.
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version
from pathlib import Path

__all__ = [
    "ONTOLOGY_PATH",
    "PROJECT_URL",
    "UNINSTALLED_VERSION",
    "compiler_version",
    "ontology_version",
    "version_parts",
    "wheel_url",
]

ONTOLOGY_PATH = Path(__file__).parent / "ontology" / "sem.ttl"

PROJECT_URL = "https://github.com/JuhaKor/semprini"
"""Where releases live. Semprini is published as a release asset rather than through a
package index (spec 5.1, 11 #3), so this is not a link in a README: it is half of the only
address from which the compiler can be installed."""

_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")

UNINSTALLED_VERSION = "0.0.0+source"
"""What :func:`compiler_version` reports from a source tree with nothing installed.

Public because it is a value other modules must recognize rather than merely produce: a
manifest records which release wrote a file, and this string identifies no release, so
:class:`semprini.manifest.Manifest` refuses to write one carrying it (spec 7)."""


def wheel_url(version: str) -> str:
    """Where the wheel for one release is downloaded from (spec 5.1, 11 #3).

    Written down once, here, because four things build this URL and none of them may
    disagree: the two workflow templates an instance runs every week, the README those
    instances are created with, and the notes attached to the release itself. The version
    appears in it twice — once as the tag directory, once in the wheel's own filename, which
    is pip's naming rule rather than a choice — and a hand-assembled URL that gets one of
    them wrong fails as a 404 in somebody else's CI.

    The PEP 508 form (``semprini @ <url>``) rather than a bare URL, so that pip checks the
    artifact it downloaded really is the distribution being asked for.
    """
    return f"{PROJECT_URL}/releases/download/v{version}/semprini-{version}-py3-none-any.whl"


def compiler_version() -> str:
    """Return the installed ``semprini`` distribution version (spec 7)."""
    try:
        return _distribution_version("semprini")
    except PackageNotFoundError:
        # Imported straight from a source tree with nothing installed. Runs, but
        # nothing may record this value in a manifest.
        return UNINSTALLED_VERSION


def version_parts(text: str) -> tuple[int, int, int] | None:
    """``"0.10.0"`` → ``(0, 10, 0)``, or ``None`` for anything that is not ``X.Y.Z``.

    The one definition of how two versions of this project are *ordered*, here rather than in
    either caller because both need it and they need it for different jobs: migrations select
    the steps a release needs and refuse a downgrade (spec 7), and the drift check decides
    which of two disagreeing versions is the newer before it tells an operator what to do
    about it. Two answers to "does 0.10.0 come after 0.9.0" is a bug that would show up in
    exactly one of those places.

    Returns ``None`` rather than raising, so that the caller decides whether an unorderable
    version is an error (it is, for a migration) or a reason to say less (it is, for a message
    that would otherwise guess at a direction). Notably unorderable is
    :data:`UNINSTALLED_VERSION`, which identifies no release at all.
    """
    match = _VERSION.match(text)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def ontology_version(path: Path = ONTOLOGY_PATH) -> str:
    """Return ``owl:versionInfo`` of the ``sem:`` metamodel (spec 3.1, 7).

    Read from ``sem.ttl`` rather than duplicated in Python, so the ontology document
    stays the single source of its own version. ``path`` exists for tests; production
    callers read the document bundled with the compiler.
    """
    from rdflib import Graph
    from rdflib.namespace import OWL, RDF

    graph = Graph()
    graph.parse(path, format="turtle")

    ontologies = list(graph.subjects(RDF.type, OWL.Ontology))
    if len(ontologies) != 1:
        raise ValueError(f"{path} must declare exactly one owl:Ontology, found {len(ontologies)}")

    # Not graph.value(): its any=True would pick arbitrarily among several
    # owl:versionInfo triples, and a version that varies per run would surface as
    # unexplained manifest drift in an instance rather than as an error here.
    versions = list(graph.objects(ontologies[0], OWL.versionInfo))
    if len(versions) != 1:
        raise ValueError(f"{path} must declare exactly one owl:versionInfo, found {len(versions)}")
    return str(versions[0])

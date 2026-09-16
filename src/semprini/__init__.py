"""Semprini — a compiler that turns modelled business vocabularies into governed RDF.

``docs/rdf-repo-and-compiler-spec.md`` is the authoritative specification; docstrings
name the sections they implement and leave the reasoning to it.

The compiler version and the ontology version are published independently (spec 7).
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
"""Where releases live; half of the only address the compiler installs from (spec 5.1, 11 #3)."""

_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")

UNINSTALLED_VERSION = "0.0.0+source"
"""What :func:`compiler_version` reports from a source tree with nothing installed.

Identifies no release, so :class:`semprini.manifest.Manifest` refuses to record it (spec 7)."""


def wheel_url(version: str) -> str:
    """The download URL of one release's wheel (spec 5.1, 11 #3).

    The single definition used by the workflow templates, the instance README and the
    release notes, so that none of them can disagree.
    """
    return f"{PROJECT_URL}/releases/download/v{version}/semprini-{version}-py3-none-any.whl"


def compiler_version() -> str:
    """Return the installed ``semprini`` distribution version (spec 7)."""
    try:
        return _distribution_version("semprini")
    except PackageNotFoundError:
        return UNINSTALLED_VERSION


def version_parts(text: str) -> tuple[int, int, int] | None:
    """``"0.10.0"`` → ``(0, 10, 0)``, or ``None`` for anything that is not ``X.Y.Z``.

    The one definition of version ordering, shared by migrations and the drift check.
    :data:`UNINSTALLED_VERSION` is unorderable and yields ``None``.
    """
    match = _VERSION.match(text)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def ontology_version(path: Path = ONTOLOGY_PATH) -> str:
    """Return ``owl:versionInfo`` of the ``sem:`` metamodel, read from ``sem.ttl`` (spec 3.1, 7).

    Raises ``ValueError`` unless the document declares exactly one ontology with exactly
    one version. ``path`` exists for tests.
    """
    from rdflib import Graph
    from rdflib.namespace import OWL, RDF

    graph = Graph()
    graph.parse(path, format="turtle")

    ontologies = list(graph.subjects(RDF.type, OWL.Ontology))
    if len(ontologies) != 1:
        raise ValueError(f"{path} must declare exactly one owl:Ontology, found {len(ontologies)}")

    # Not graph.value(), which would pick arbitrarily among several triples.
    versions = list(graph.objects(ontologies[0], OWL.versionInfo))
    if len(versions) != 1:
        raise ValueError(f"{path} must declare exactly one owl:versionInfo, found {len(versions)}")
    return str(versions[0])

"""Semprini — a compiler that turns modelled business vocabularies into governed RDF.

``docs/rdf-repo-and-compiler-spec.md`` is the authoritative specification; module
docstrings name the sections they implement.

Two version numbers are published independently (spec 7): the compiler version is this
package's own, and the ontology version belongs to the bundled ``sem:`` metamodel.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version
from pathlib import Path

__all__ = ["ONTOLOGY_PATH", "compiler_version", "ontology_version"]

ONTOLOGY_PATH = Path(__file__).parent / "ontology" / "sem.ttl"

_UNINSTALLED = "0.0.0+source"


def compiler_version() -> str:
    """Return the installed ``semprini`` distribution version (spec 7)."""
    try:
        return _distribution_version("semprini")
    except PackageNotFoundError:
        # Imported straight from a source tree with nothing installed. Runs, but
        # nothing may record this value in a manifest.
        return _UNINSTALLED


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

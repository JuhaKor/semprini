"""The bundled metamodel document (spec 3.1, 7).

Task A3 replaces the placeholder with the real vocabulary and adds the term-inventory
test; these assertions hold for both, so they guard the version contract in between.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from rdflib import Graph
from rdflib.namespace import OWL, RDF

from semprini import ONTOLOGY_PATH, ontology_version

ONTOLOGY_IRI = "https://w3id.org/semprini/ontology"

PREAMBLE = "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"


def test_ontology_is_packaged_with_the_compiler() -> None:
    # Read through the installed package, not the source tree: the ontology travels
    # inside the wheel because every instance copies the pinned version verbatim.
    assert ONTOLOGY_PATH.is_file()


def test_ontology_declares_exactly_one_ontology_at_the_fixed_iri() -> None:
    graph = Graph()
    graph.parse(ONTOLOGY_PATH, format="turtle")

    ontologies = list(graph.subjects(RDF.type, OWL.Ontology))
    assert len(ontologies) == 1
    # The metamodel namespace is identical in every deployment (spec 3.1) — a per-fork
    # substitution here would split the shared vocabulary.
    assert str(ontologies[0]) == ONTOLOGY_IRI


def test_ontology_version_is_read_from_the_document() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", ontology_version())


def _write(tmp_path: Path, turtle: str) -> Path:
    document = tmp_path / "sem.ttl"
    document.write_text(PREAMBLE + turtle, encoding="utf-8")
    return document


def test_two_version_statements_raise_rather_than_picking_one(tmp_path: Path) -> None:
    # An arbitrary choice here would reach instances as unexplained manifest drift.
    document = _write(
        tmp_path,
        f'<{ONTOLOGY_IRI}> a owl:Ontology ; owl:versionInfo "1.0.0", "1.1.0" .\n',
    )
    with pytest.raises(ValueError, match="exactly one owl:versionInfo"):
        ontology_version(document)


def test_missing_version_statement_raises(tmp_path: Path) -> None:
    document = _write(tmp_path, f"<{ONTOLOGY_IRI}> a owl:Ontology .\n")
    with pytest.raises(ValueError, match="exactly one owl:versionInfo"):
        ontology_version(document)


def test_two_ontologies_raise(tmp_path: Path) -> None:
    document = _write(
        tmp_path,
        f'<{ONTOLOGY_IRI}> a owl:Ontology ; owl:versionInfo "1.0.0" .\n'
        f'<{ONTOLOGY_IRI}/other> a owl:Ontology ; owl:versionInfo "1.0.0" .\n',
    )
    with pytest.raises(ValueError, match="exactly one owl:Ontology"):
        ontology_version(document)

"""The bundled metamodel document (spec 3.1, 7).

Task A3 replaces the placeholder with the real vocabulary and adds the term-inventory
test; these assertions hold for both, so they guard the version contract in between.
"""

from __future__ import annotations

import re

from rdflib import Graph
from rdflib.namespace import OWL, RDF

from semprini import ONTOLOGY_PATH, ontology_version

ONTOLOGY_IRI = "https://w3id.org/semprini/ontology"


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

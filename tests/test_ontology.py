"""The bundled metamodel document (spec 3.1, 7).

Task A3 replaces the placeholder with the real vocabulary and adds the term-inventory
test; these assertions hold for both, so they guard the version contract in between.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import pytest
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from semprini import ONTOLOGY_PATH, ontology_version

ONTOLOGY_IRI = "https://w3id.org/semprini/ontology"

SEM = Namespace("https://w3id.org/semprini/ontology#")

PREAMBLE = "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"

# The inventory of spec 3.2 and 3.3, transcribed. Held as a literal rather than parsed
# out of the specification's tables: this is the one place the two are compared, so it
# is meant to be edited by hand, in the same change as the table and the ontology.
#
# Classes (3.2), mapped to their superclass. The table's skos:ConceptScheme and plain
# skos:Concept rows are absent on purpose — they are reused SKOS terms, and a metamodel
# that redeclared them would be redefining someone else's vocabulary.
EXPECTED_CLASSES: dict[str, URIRef | None] = {
    "Entity": SKOS.Concept,
    "Attribute": SKOS.Concept,
    "Relationship": None,
    "BusinessTerm": SKOS.Concept,
}

# Properties (3.3), mapped to (domain, range). None where the table names no concrete
# class: an "any" domain, or a reserved term whose classes the metamodel has yet to
# define.
EXPECTED_PROPERTIES: dict[str, tuple[URIRef | None, URIRef | None]] = {
    "attributeOf": (SEM.Attribute, SEM.Entity),
    "source": (SEM.Relationship, SEM.Entity),
    "target": (SEM.Relationship, SEM.Entity),
    "relatesTo": (SEM.Entity, SEM.Entity),
    "enumerates": (SKOS.ConceptScheme, SEM.Entity),
    "status": (None, XSD.string),
    "sourceRef": (None, XSD.string),
    "schemeType": (SKOS.ConceptScheme, XSD.string),
    "isAbout": (None, None),
    "represents": (None, None),
}

EXPECTED_TERMS = frozenset(EXPECTED_CLASSES) | frozenset(EXPECTED_PROPERTIES)


@pytest.fixture(scope="module")
def ontology() -> Graph:
    graph = Graph()
    graph.parse(ONTOLOGY_PATH, format="turtle")
    return graph


def _local_names(nodes: Iterable[object]) -> set[str]:
    """Local names of the sem: IRIs among ``nodes``, ignoring anything else."""
    return {
        str(node).removeprefix(str(SEM))
        for node in nodes
        if isinstance(node, URIRef) and str(node).startswith(str(SEM))
    }


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


def test_the_placeholder_version_is_gone() -> None:
    # 0.0.0 meant "declares no vocabulary; must not be used to mint IRIs". Once terms
    # exist, that value would tell an instance the opposite of the truth.
    assert ontology_version() != "0.0.0"


def test_declared_classes_are_exactly_the_spec_table(ontology: Graph) -> None:
    assert _local_names(ontology.subjects(RDF.type, RDFS.Class)) == set(EXPECTED_CLASSES)


def test_declared_properties_are_exactly_the_spec_table(ontology: Graph) -> None:
    assert _local_names(ontology.subjects(RDF.type, RDF.Property)) == set(EXPECTED_PROPERTIES)


def test_no_undeclared_sem_term_is_referenced(ontology: Graph) -> None:
    # Catches a term reached only as an object — a typo in a domain, range or
    # subClassOf would otherwise pass the two inventory tests above.
    referenced = _local_names(node for triple in ontology for node in triple)
    assert referenced == set(EXPECTED_TERMS)


def test_the_document_describes_only_its_own_terms(ontology: Graph) -> None:
    # A metamodel that made statements about skos: or dcterms: terms would be
    # redefining a vocabulary it does not own (3.6 applies to us as much as to
    # adopters).
    described = set(ontology.subjects())
    assert described <= {URIRef(ONTOLOGY_IRI)} | {SEM[name] for name in EXPECTED_TERMS}


def test_class_superclasses_match_the_spec_table(ontology: Graph) -> None:
    for name, superclass in EXPECTED_CLASSES.items():
        expected = [superclass] if superclass is not None else []
        assert list(ontology.objects(SEM[name], RDFS.subClassOf)) == expected, name


def test_property_domains_and_ranges_match_the_spec_table(ontology: Graph) -> None:
    for name, (domain, range_) in EXPECTED_PROPERTIES.items():
        assert list(ontology.objects(SEM[name], RDFS.domain)) == (
            [domain] if domain is not None else []
        ), name
        assert list(ontology.objects(SEM[name], RDFS.range)) == (
            [range_] if range_ is not None else []
        ), name


def test_every_term_documents_itself(ontology: Graph) -> None:
    # The comments are the vocabulary's documentation: sem.ttl is what resolves at
    # w3id.org, so a term that arrives undocumented arrives unusable.
    for name in EXPECTED_TERMS:
        term = SEM[name]
        assert len(list(ontology.objects(term, RDFS.label))) == 1, name
        assert len(list(ontology.objects(term, RDFS.comment))) == 1, name
        assert list(ontology.objects(term, RDFS.isDefinedBy)) == [URIRef(ONTOLOGY_IRI)], name


def test_owl_is_confined_to_the_document_header(ontology: Graph) -> None:
    # Deliberate: the metamodel is SKOS-based and RDFS-typed, constraints are stated
    # once in SHACL, and OWL typing here would license entailments nothing validates.
    # owl:Ontology stays because owl:versionInfo is where spec 7 keeps the version.
    owl_typed = {
        subject
        for subject, object_ in ontology.subject_objects(RDF.type)
        if str(object_).startswith(str(OWL))
    }
    assert owl_typed == {URIRef(ONTOLOGY_IRI)}


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

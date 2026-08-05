"""The canonical serializer (spec 5.5), one test per rule plus the properties.

The rules are only worth as much as the tests: a serializer that quietly reorders
something once a year would surface as an unexplained diff in an instance's PR, long
after the change that caused it. So each rule is pinned separately, and determinism is
tested as a property over shuffled input rather than on one hand-picked graph.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

import pytest
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import DCTERMS, RDF, SKOS, XSD
from rdflib.term import BNode

from semprini.serialize import CANONICAL_PREFIXES, namespaces, serialize, write

BASE = "https://semantics.example.com/"

NS = namespaces(BASE)
SEM = Namespace(NS["sem"])
C = Namespace(NS["c"])
R = Namespace(NS["r"])
SCH = Namespace(NS["sch"])
V = Namespace(NS["v"])

EXPECTED_PREFIX_BLOCK = """\
@prefix sem: <https://w3id.org/semprini/ontology#> .
@prefix c: <https://semantics.example.com/concepts/> .
@prefix r: <https://semantics.example.com/relationships/> .
@prefix sch: <https://semantics.example.com/schemes/> .
@prefix v: <https://semantics.example.com/values/> .
@prefix x: <https://semantics.example.com/ext#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix a: <https://semantics.example.com/assets/> .
@prefix d: <https://semantics.example.com/docs/> ."""

CUSTOMER = C["7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21"]
ORDER = C["0d9e4c77-6b5a-4c3d-8e2f-1a9b7c5d3e4f"]
PLACES = R["c2d1e0aa-11b2-43c3-9d4e-5f6a7b8c9d0e"]


def graph_of(*triples: tuple[URIRef, URIRef, URIRef | Literal]) -> Graph:
    graph = Graph()
    for triple in triples:
        graph.add(triple)
    return graph


def statement_lines(turtle: str) -> list[str]:
    return [line for line in turtle.splitlines() if line and not line.startswith("@prefix")]


def sample_graph() -> Graph:
    """A graph exercising every construct the compiler emits (spec 3.7)."""
    return graph_of(
        (CUSTOMER, RDF.type, SEM.Entity),
        (CUSTOMER, SKOS.prefLabel, Literal("Customer", lang="en")),
        (CUSTOMER, SKOS.definition, Literal("A buyer of our products.", lang="en")),
        (CUSTOMER, SKOS.inScheme, SCH.sales),
        (CUSTOMER, SEM.sourceRef, Literal("ellie-main:7f3a9b12")),
        (CUSTOMER, SEM.status, Literal("active")),
        (CUSTOMER, SEM.relatesTo, ORDER),
        (CUSTOMER, DCTERMS.modified, Literal("2026-08-03", datatype=XSD.date)),
        (ORDER, RDF.type, SEM.Entity),
        (ORDER, SKOS.prefLabel, Literal("Order", lang="en")),
        (PLACES, RDF.type, SEM.Relationship),
        (PLACES, SKOS.prefLabel, Literal("places", lang="en")),
        (PLACES, SEM.source, CUSTOMER),
        (PLACES, SEM.target, ORDER),
        (SCH.sales, RDF.type, SKOS.ConceptScheme),
        (SCH.sales, SKOS.prefLabel, Literal("Sales glossary", lang="en")),
        (SCH.sales, SEM.schemeType, Literal("glossary")),
        (V["9c1f2e3d-4a5b-4c6d-8e7f-0a1b2c3d4e5f"], SKOS.notation, Literal("PT-DR")),
    )


# --- rule 1: fixed prefix block -------------------------------------------------------


def test_rule_1_the_prefix_block_is_fixed_and_ordered() -> None:
    assert serialize(Graph(), BASE) == EXPECTED_PREFIX_BLOCK + "\n"


def test_rule_1_the_prefix_block_is_emitted_even_where_unused() -> None:
    # Otherwise the first triple in a namespace would also change the file's header,
    # turning a one-line addition into a two-hunk diff.
    turtle = serialize(graph_of((CUSTOMER, RDF.type, SEM.Entity)), BASE)
    assert turtle.startswith(EXPECTED_PREFIX_BLOCK + "\n")


def test_namespaces_derive_every_per_instance_prefix_from_the_base_iri() -> None:
    assert tuple(namespaces(BASE)) == CANONICAL_PREFIXES
    assert namespaces(BASE)["v"] == f"{BASE}values/"
    assert namespaces(BASE)["x"] == f"{BASE}ext#"
    # The metamodel namespace is identical in every deployment (spec 3.1).
    assert namespaces("https://other.example.org/")["sem"] == namespaces(BASE)["sem"]


@pytest.mark.parametrize(
    "base",
    ["https://semantics.example.com", "ftp://semantics.example.com/", "semantics.example.com/"],
)
def test_an_unusable_base_iri_is_refused(base: str) -> None:
    # A base without the trailing separator would silently mint into a namespace one
    # character away from the intended one — exactly what the namespace lock exists to
    # prevent (spec 3.4).
    with pytest.raises(ValueError, match="base IRI"):
        serialize(Graph(), base)


# --- rule 2: subjects sorted, one block each ------------------------------------------


def test_rule_2_subjects_are_sorted_lexicographically_by_iri() -> None:
    turtle = serialize(sample_graph(), BASE)
    subjects = [line.split(" ")[0] for line in statement_lines(turtle) if not line.startswith("  ")]
    assert subjects == sorted(subjects)
    assert subjects[0].startswith("c:0d9e4c77")


def test_rule_2_each_subject_is_one_block() -> None:
    turtle = serialize(sample_graph(), BASE)
    openers = [line.split(" ")[0] for line in statement_lines(turtle) if not line.startswith("  ")]
    assert len(openers) == len(set(openers))
    # One terminating '.' per subject: a subject split across two blocks would produce
    # two hunks in a diff for one changed thing.
    terminators = [line for line in statement_lines(turtle) if line.endswith(" .")]
    assert len(terminators) == len(openers)


def test_rule_2_subject_order_ignores_insertion_order() -> None:
    forwards = serialize(
        graph_of((ORDER, RDF.type, SEM.Entity), (CUSTOMER, RDF.type, SEM.Entity)), BASE
    )
    backwards = serialize(
        graph_of((CUSTOMER, RDF.type, SEM.Entity), (ORDER, RDF.type, SEM.Entity)), BASE
    )
    assert forwards == backwards


# --- rule 3: predicate and object order within a subject ------------------------------


def test_rule_3_type_comes_first_then_preflabel_then_iri_order() -> None:
    customer_only = Graph()
    for triple in sample_graph().triples((CUSTOMER, None, None)):
        customer_only.add(triple)
    lines = statement_lines(serialize(customer_only, BASE))
    predicates = [lines[0].split(" ")[1], *(line.strip().split(" ")[0] for line in lines[1:])]
    # Lexicographic by *IRI*, not by prefixed name: dcterms: and skos: are http://,
    # sem: is https://, so sorting the short forms would give a different file.
    assert predicates == [
        "a",
        "skos:prefLabel",
        "dcterms:modified",
        "skos:definition",
        "skos:inScheme",
        "sem:relatesTo",
        "sem:sourceRef",
        "sem:status",
    ]


def test_rule_3_multiple_objects_of_one_predicate_are_sorted() -> None:
    turtle = serialize(
        graph_of(
            (CUSTOMER, SKOS.inScheme, SCH.sales),
            (CUSTOMER, SKOS.inScheme, SCH.finance),
            (CUSTOMER, SKOS.inScheme, SCH.marketing),
        ),
        BASE,
    )
    assert [line.strip() for line in statement_lines(turtle)] == [
        "c:7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21 skos:inScheme sch:finance ;",
        "skos:inScheme sch:marketing ;",
        "skos:inScheme sch:sales .",
    ]


def test_rule_3_iris_and_literals_have_one_defined_order() -> None:
    # A mixed-object predicate is unusual but must not depend on insertion order; an
    # undefined comparison here is what reorders a file a year later for no reason.
    triples: list[tuple[URIRef, URIRef, URIRef | Literal]] = [
        (CUSTOMER, SEM.isAbout, Literal("zeta")),
        (CUSTOMER, SEM.isAbout, ORDER),
        (CUSTOMER, SEM.isAbout, Literal("alpha", lang="en")),
    ]
    assert serialize(graph_of(*triples), BASE) == serialize(graph_of(*reversed(triples)), BASE)
    assert [line.strip() for line in statement_lines(serialize(graph_of(*triples), BASE))] == [
        "c:7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21 "
        "sem:isAbout c:0d9e4c77-6b5a-4c3d-8e2f-1a9b7c5d3e4f ;",
        'sem:isAbout "alpha"@en ;',
        'sem:isAbout "zeta" .',
    ]


# --- rule 4: one triple per line, two-space indent, ';' continuation -------------------


def test_rule_4_every_line_carries_exactly_one_triple() -> None:
    graph = sample_graph()
    assert len(statement_lines(serialize(graph, BASE))) == len(graph)


def test_rule_4_continuation_lines_are_indented_two_spaces() -> None:
    turtle = serialize(sample_graph(), BASE)
    continuations = [line for line in statement_lines(turtle) if line.startswith(" ")]
    assert continuations
    for line in continuations:
        assert line.startswith("  ") and not line.startswith("   ")


def test_rule_4_blocks_end_with_a_period_and_continue_with_a_semicolon() -> None:
    turtle = serialize(sample_graph(), BASE)
    for line in statement_lines(turtle):
        assert line.endswith(" ;") or line.endswith(" .")


# --- rule 5: UTF-8, LF, newline at EOF, no comments ------------------------------------


def test_rule_5_output_ends_with_exactly_one_newline() -> None:
    turtle = serialize(sample_graph(), BASE)
    assert turtle.endswith("\n")
    assert not turtle.endswith("\n\n")


def test_rule_5_written_files_are_utf8_with_lf_endings(tmp_path: Path) -> None:
    # The point of writing through the module: the platform default would translate
    # every line ending on Windows and produce different bytes from the same graph.
    graph = graph_of((CUSTOMER, SKOS.prefLabel, Literal("Asiakäs — Kundé", lang="fi")))
    path = tmp_path / "concepts-sales.ttl"
    write(path, graph, BASE)

    raw = path.read_bytes()
    assert b"\r" not in raw
    assert "Asiakäs — Kundé".encode() in raw
    assert raw.decode("utf-8") == serialize(graph, BASE)


def test_rule_5_generated_output_carries_no_comments() -> None:
    turtle = serialize(sample_graph(), BASE)
    for line in turtle.splitlines():
        # '#' is legitimate inside an IRI (the sem: and x: namespaces end with one) and
        # inside a literal; anywhere else it would be a comment.
        outside = re.sub(r'<[^>]*>|"(?:[^"\\]|\\.)*"', "", line)
        assert "#" not in outside, line


# --- rule 6: language tags survive ----------------------------------------------------


def test_rule_6_language_tags_are_preserved() -> None:
    # The serializer preserves what the graph holds; requiring the tag on prefLabel and
    # definition is the graph builder's job (task C1).
    turtle = serialize(
        graph_of(
            (CUSTOMER, SKOS.prefLabel, Literal("Customer", lang="en")),
            (CUSTOMER, SKOS.definition, Literal("Asiakas", lang="fi")),
        ),
        BASE,
    )
    assert '"Customer"@en' in turtle
    assert '"Asiakas"@fi' in turtle


def test_rule_6_a_tagged_and_an_untagged_literal_stay_distinct() -> None:
    turtle = serialize(
        graph_of(
            (CUSTOMER, SEM.status, Literal("active")),
            (CUSTOMER, SEM.status, Literal("active", lang="en")),
        ),
        BASE,
    )
    assert [line.strip() for line in statement_lines(turtle)] == [
        'c:7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21 sem:status "active" ;',
        'sem:status "active"@en .',
    ]


# --- rule 7: no blank nodes -----------------------------------------------------------


@pytest.mark.parametrize("position", ["subject", "predicate", "object"])
def test_rule_7_a_blank_node_raises_rather_than_being_emitted(position: str) -> None:
    blank = BNode()
    triple = {
        "subject": (blank, RDF.type, SEM.Entity),
        "predicate": (CUSTOMER, blank, SEM.Entity),
        "object": (CUSTOMER, SEM.relatesTo, blank),
    }[position]
    graph = Graph()
    graph.add(triple)

    with pytest.raises(ValueError, match="no blank nodes"):
        serialize(graph, BASE)


def test_rule_7_the_failure_names_the_position(tmp_path: Path) -> None:
    graph = Graph()
    graph.add((CUSTOMER, SEM.relatesTo, BNode()))
    with pytest.raises(ValueError, match="object position"):
        write(tmp_path / "out.ttl", graph, BASE)
    # Nothing half-written: the whole document is built before anything is written.
    assert list(tmp_path.iterdir()) == []


# --- rule 8: nothing the graph does not contain ---------------------------------------


def test_rule_8_no_timestamp_or_other_content_is_invented() -> None:
    graph = sample_graph()
    turtle = serialize(graph, BASE)

    # Every statement line comes from a triple, and the only date in the output is the
    # dcterms:modified the graph itself carries (spec 3.3: content change, not run time).
    assert len(statement_lines(turtle)) == len(graph)
    assert re.findall(r"\d{4}-\d{2}-\d{2}", turtle) == ["2026-08-03"]
    assert serialize(graph, BASE) == turtle


def test_rule_8_a_graph_without_dates_serializes_without_any() -> None:
    turtle = serialize(graph_of((CUSTOMER, RDF.type, SEM.Entity)), BASE)
    assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}", turtle)


# --- determinism and round-tripping ---------------------------------------------------


def test_insertion_order_never_reaches_the_bytes() -> None:
    triples = list(sample_graph())
    expected = serialize(sample_graph(), BASE)
    shuffler = random.Random(20260805)

    for _ in range(50):
        shuffled = list(triples)
        shuffler.shuffle(shuffled)
        graph = Graph()
        for triple in shuffled:
            graph.add(triple)
        assert serialize(graph, BASE) == expected


def test_parse_then_serialize_round_trips_to_the_same_graph() -> None:
    original = sample_graph()
    turtle = serialize(original, BASE)

    reparsed = Graph()
    reparsed.parse(data=turtle, format="turtle")

    assert isomorphic(reparsed, original)
    # And is a fixed point: re-serializing the reparsed graph changes nothing.
    assert serialize(reparsed, BASE) == turtle


# --- term writing ---------------------------------------------------------------------


def test_an_iri_outside_the_prefix_block_is_written_in_full() -> None:
    external = URIRef("http://www.w3.org/ns/org#Organization")
    assert f"<{external}>" in serialize(graph_of((CUSTOMER, RDF.type, external)), BASE)


def test_a_local_name_that_would_need_escaping_falls_back_to_the_full_iri() -> None:
    # Nothing the compiler mints looks like this, but a hand-written overlay might, and
    # emitting `c:odd/name` would produce a file that no longer parses.
    awkward = URIRef(f"{BASE}concepts/odd/name")
    assert f"<{awkward}>" in serialize(graph_of((awkward, RDF.type, SEM.Entity)), BASE)


def test_the_longest_matching_namespace_wins() -> None:
    # c: is base+concepts/ while a hypothetical shorter namespace could also match; the
    # choice must not depend on the order of the prefix block.
    assert "c:7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21" in serialize(
        graph_of((CUSTOMER, RDF.type, SEM.Entity)), BASE
    )


def test_rdf_type_is_written_as_the_turtle_keyword() -> None:
    turtle = serialize(graph_of((CUSTOMER, RDF.type, SEM.Entity)), BASE)
    assert turtle.strip().endswith("c:7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21 a sem:Entity .")


def test_a_typed_literal_keeps_its_datatype() -> None:
    turtle = serialize(
        graph_of((CUSTOMER, DCTERMS.modified, Literal("2026-08-03", datatype=XSD.date))), BASE
    )
    assert '"2026-08-03"^^xsd:date' in turtle


def test_an_xsd_string_literal_is_written_the_plain_way() -> None:
    # The two are the same RDF term; writing them differently would make two equal
    # graphs produce two different files and break the determinism check.
    typed = serialize(
        graph_of((CUSTOMER, SEM.status, Literal("active", datatype=XSD.string))), BASE
    )
    plain = serialize(graph_of((CUSTOMER, SEM.status, Literal("active"))), BASE)
    assert typed == plain
    assert '"active" .' in plain


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('say "hi"', r'"say \"hi\""'),
        ("back\\slash", r'"back\\slash"'),
        ("two\nlines", r'"two\nlines"'),
        ("tab\there", r'"tab\there"'),
        ("bell" + chr(7), '"bell' + chr(92) + 'u0007"'),
        ("ümläut ✓", '"ümläut ✓"'),
    ],
)
def test_literals_are_escaped_on_one_line(value: str, expected: str) -> None:
    turtle = serialize(graph_of((CUSTOMER, SKOS.definition, Literal(value))), BASE)
    assert expected in turtle
    # A multi-line literal would break one-triple-per-line for everything after it.
    assert len(statement_lines(turtle)) == 1

    reparsed = Graph()
    reparsed.parse(data=turtle, format="turtle")
    assert str(next(reparsed.objects(CUSTOMER, SKOS.definition))) == value

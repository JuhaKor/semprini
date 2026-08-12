"""The core SHACL shapes and the check that applies them (spec 6.1.5).

Every constraint of spec 6.1.5 gets two fixtures here: one graph that satisfies it and one
that breaks it. A shapes file is the kind of artifact that passes silently when it is
wrong — a target that matches nothing reports no violations, which reads exactly like
clean data — so a rule is only covered here if something is shown to *fail* it.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SH, SKOS

from sample import sample_model
from semprini import ONTOLOGY_PATH, config, identity, validate
from semprini.model import Issue, Severity

BASE = "https://semantics.example.com/"

SEM = URIRef("https://w3id.org/semprini/ontology#")
STATUS = URIRef(f"{SEM}status")


def iri(prefix: str, local: str) -> URIRef:
    return URIRef(f"{BASE}{prefix}{local}")


CUSTOMER = "11111111-1111-4111-8111-111111111111"
VIP = "22222222-2222-4222-8222-222222222222"
CATEGORY = "33333333-3333-4333-8333-333333333333"
CUSTOMER_ID = "44444444-4444-4444-8444-444444444444"
PLACES = "55555555-5555-4555-8555-555555555555"
TOOLS = "66666666-6666-4666-8666-666666666666"
DRILLS = "77777777-7777-4777-8777-777777777777"

PREFIXES = f"""
@prefix sem: <https://w3id.org/semprini/ontology#> .
@prefix c: <{BASE}concepts/> .
@prefix r: <{BASE}relationships/> .
@prefix sch: <{BASE}schemes/> .
@prefix v: <{BASE}values/> .
@prefix x: <{BASE}ext#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""

SAMPLE = f"""{PREFIXES}
sch:storefront a skos:ConceptScheme ;
  skos:prefLabel "Storefront"@en ;
  sem:schemeType "glossary" ;
  sem:sourceRef "ellie-main:70337" ;
  sem:status "active" .

sch:product-category a skos:ConceptScheme ;
  skos:prefLabel "Product category"@en ;
  sem:enumerates c:{CATEGORY} ;
  sem:schemeType "taxonomy" ;
  sem:sourceRef "product-category:product-category" ;
  sem:status "active" .

c:{CUSTOMER} a sem:Entity ;
  skos:prefLabel "Customer"@en ;
  skos:definition "Someone who buys our products."@en ;
  skos:inScheme sch:storefront ;
  sem:status "active" .

c:{VIP} a sem:Entity ;
  skos:prefLabel "Key account"@en ;
  skos:definition "A customer we assign an account manager."@en ;
  skos:broader c:{CUSTOMER} ;
  skos:inScheme sch:storefront ;
  sem:status "active" .

c:{CATEGORY} a sem:Entity ;
  skos:prefLabel "Product category"@en ;
  skos:definition "A grouping of related products."@en ;
  skos:inScheme sch:storefront ;
  sem:status "active" .

c:{CUSTOMER_ID} a sem:Attribute ;
  skos:prefLabel "Customer ID"@en ;
  skos:definition "Unique identifier of the customer."@en ;
  skos:inScheme sch:storefront ;
  sem:attributeOf c:{CUSTOMER} ;
  sem:status "active" .

r:{PLACES} a sem:Relationship ;
  skos:prefLabel "belongs to"@en ;
  skos:inScheme sch:storefront ;
  sem:source c:{CUSTOMER} ;
  sem:target c:{CATEGORY} ;
  sem:status "active" .

v:{TOOLS} a skos:Concept ;
  skos:prefLabel "Tools"@en ;
  skos:definition "Implements used to work material."@en ;
  skos:inScheme sch:product-category ;
  skos:notation "T" ;
  skos:topConceptOf sch:product-category ;
  sem:status "active" .

v:{DRILLS} a skos:Concept ;
  skos:prefLabel "Drills"@en ;
  skos:definition "Power tools that bore holes."@en ;
  skos:broader v:{TOOLS} ;
  skos:inScheme sch:product-category ;
  skos:notation "T-DR" ;
  sem:status "active" .
"""
"""One conforming instance of every class the metamodel has (spec 3.2).

Hand-written rather than sliced out of ``tests/fixtures/acme/``: a violation is made here
by removing or adding one statement, and the diff between the graph that passes and the
graph that fails *is* the constraint being tested.
"""


def sample(*extra: str) -> Graph:
    """The conforming sample, plus any additional Turtle."""
    graph = Graph()
    graph.parse(data=SAMPLE + "\n".join(extra), format="turtle")
    return graph


def checked(graph: Graph) -> tuple[Issue, ...]:
    """Every issue the packaged shapes and the IRI policy find in ``graph``."""
    return validate.shacl(graph, validate.core_shapes() + validate.instance_shapes(BASE))


def errors(graph: Graph) -> tuple[Issue, ...]:
    return tuple(issue for issue in checked(graph) if issue.severity is Severity.ERROR)


def assert_error(graph: Graph, *, about: URIRef, saying: str) -> None:
    """Assert exactly one error, about ``about``, whose message contains ``saying``."""
    found = errors(graph)
    assert [issue.location for issue in found] == [str(about)], found
    assert saying in found[0].message, found[0].message


def assert_no_errors(graph: Graph) -> None:
    assert errors(graph) == ()


# ------------------------------------------------------------------ the sample itself


def test_the_sample_graph_conforms() -> None:
    assert checked(sample()) == ()


def test_the_fixture_instance_conforms(instance: Path) -> None:
    """The instance of spec 6.1, validated as an adopter's CI would validate theirs."""
    settings = config.load(instance)
    issues = validate.check_shapes(instance, base_iri=settings.base_iri)

    assert [issue for issue in issues if issue.severity is Severity.ERROR] == []
    # The four order-line attributes the workbook and the model leave undefined — the
    # same four the committed run report lists.
    assert len(issues) == 4
    assert all("skos:definition" in issue.message for issue in issues)


# ------------------------------------------------------------------ labels and status


def test_a_node_without_a_pref_label_is_reported() -> None:
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER), SKOS.prefLabel, None))
    assert_error(graph, about=iri("concepts/", CUSTOMER), saying="skos:prefLabel")


def test_two_pref_labels_in_one_language_are_reported() -> None:
    graph = sample()
    graph.add((iri("concepts/", CUSTOMER), SKOS.prefLabel, Literal("Client", lang="en")))
    assert_error(graph, about=iri("concepts/", CUSTOMER), saying="per language")


def test_two_pref_labels_in_different_languages_are_allowed() -> None:
    graph = sample()
    graph.add((iri("concepts/", CUSTOMER), SKOS.prefLabel, Literal("Asiakas", lang="fi")))
    assert_no_errors(graph)


def test_an_untagged_pref_label_is_reported() -> None:
    """Spec 5.5 rule 6: a label carries a language, so that a query can ask for one."""
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER), SKOS.prefLabel, None))
    graph.add((iri("concepts/", CUSTOMER), SKOS.prefLabel, Literal("Customer")))
    assert_error(graph, about=iri("concepts/", CUSTOMER), saying="language tag")


def test_a_scheme_needs_a_label_too() -> None:
    graph = sample()
    graph.remove((iri("schemes/", "storefront"), SKOS.prefLabel, None))
    assert_error(graph, about=iri("schemes/", "storefront"), saying="skos:prefLabel")


def test_a_node_without_a_status_is_reported() -> None:
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER), STATUS, None))
    assert_error(graph, about=iri("concepts/", CUSTOMER), saying="sem:status")


def test_an_unknown_status_is_reported() -> None:
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER), STATUS, None))
    graph.add((iri("concepts/", CUSTOMER), STATUS, Literal("retired")))
    assert_error(graph, about=iri("concepts/", CUSTOMER), saying="sem:status")


def test_two_statuses_are_reported() -> None:
    """An overlay adding a second status is the reachable way to get here (spec 6.1.5)."""
    graph = sample()
    graph.add((iri("concepts/", CATEGORY), STATUS, Literal("deprecated")))
    assert_error(graph, about=iri("concepts/", CATEGORY), saying="sem:status")


def test_a_scheme_needs_a_status_too() -> None:
    """Spec 3.5 applies to every object: a scheme is deleted from a source like anything
    else, and spec 6.1.5's first bullet did not say so until this task."""
    graph = sample()
    graph.remove((iri("schemes/", "storefront"), STATUS, None))
    assert_error(graph, about=iri("schemes/", "storefront"), saying="sem:status")


# ------------------------------------------------------------------ scheme membership


def test_a_node_in_no_scheme_is_reported() -> None:
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER), SKOS.inScheme, None))
    assert_error(graph, about=iri("concepts/", CUSTOMER), saying="skos:inScheme")


def test_a_node_in_an_undeclared_scheme_is_reported() -> None:
    graph = sample()
    graph.add((iri("concepts/", CUSTOMER), SKOS.inScheme, iri("schemes/", "nowhere")))
    assert_error(graph, about=iri("concepts/", CUSTOMER), saying="skos:inScheme")


def test_a_scheme_is_not_asked_to_be_in_a_scheme() -> None:
    """The one class the membership rule exempts, and the sample proves it passes."""
    graph = sample()
    assert not list(graph.objects(iri("schemes/", "storefront"), SKOS.inScheme))
    assert_no_errors(graph)


def test_a_scheme_without_a_type_is_reported() -> None:
    graph = sample()
    graph.remove((iri("schemes/", "storefront"), URIRef(f"{SEM}schemeType"), None))
    assert_error(graph, about=iri("schemes/", "storefront"), saying="sem:schemeType")


def test_an_unknown_scheme_type_is_reported() -> None:
    graph = sample()
    graph.remove((iri("schemes/", "storefront"), URIRef(f"{SEM}schemeType"), None))
    graph.add((iri("schemes/", "storefront"), URIRef(f"{SEM}schemeType"), Literal("catalogue")))
    assert_error(graph, about=iri("schemes/", "storefront"), saying="sem:schemeType")


def test_enumerating_something_that_is_not_an_entity_is_reported() -> None:
    graph = sample()
    graph.remove((iri("schemes/", "product-category"), URIRef(f"{SEM}enumerates"), None))
    graph.add(
        (iri("schemes/", "product-category"), URIRef(f"{SEM}enumerates"), iri("values/", TOOLS))
    )
    assert_error(graph, about=iri("schemes/", "product-category"), saying="sem:enumerates")


# ------------------------------------------------------------------ definitions


def test_a_missing_definition_is_a_warning_not_a_failure() -> None:
    """Spec 6.1.5: reported in v1, blocking only when an instance turns it on."""
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER), SKOS.definition, None))

    issues = checked(graph)

    assert [issue.severity for issue in issues] == [Severity.WARNING]
    assert issues[0].location == str(iri("concepts/", CUSTOMER))


def test_a_relationship_is_not_asked_for_a_definition() -> None:
    """Its label is a verb; there is nothing a steward would write underneath it."""
    graph = sample()
    assert not list(graph.objects(iri("relationships/", PLACES), SKOS.definition))
    assert checked(graph) == ()


def test_an_untagged_definition_is_reported() -> None:
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER), SKOS.definition, None))
    graph.add((iri("concepts/", CUSTOMER), SKOS.definition, Literal("Someone who buys.")))
    assert_error(graph, about=iri("concepts/", CUSTOMER), saying="language tag")


# ------------------------------------------------------------------ class structure


def test_an_attribute_without_an_owner_is_reported() -> None:
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER_ID), URIRef(f"{SEM}attributeOf"), None))
    assert_error(graph, about=iri("concepts/", CUSTOMER_ID), saying="sem:attributeOf")


def test_an_attribute_of_two_entities_is_reported() -> None:
    graph = sample()
    graph.add((iri("concepts/", CUSTOMER_ID), URIRef(f"{SEM}attributeOf"), iri("concepts/", VIP)))
    assert_error(graph, about=iri("concepts/", CUSTOMER_ID), saying="sem:attributeOf")


def test_an_attribute_of_something_that_is_not_an_entity_is_reported() -> None:
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER_ID), URIRef(f"{SEM}attributeOf"), None))
    graph.add((iri("concepts/", CUSTOMER_ID), URIRef(f"{SEM}attributeOf"), iri("values/", TOOLS)))
    assert_error(graph, about=iri("concepts/", CUSTOMER_ID), saying="sem:attributeOf")


@pytest.mark.parametrize("end", ["source", "target"])
def test_a_relationship_missing_an_end_is_reported(end: str) -> None:
    graph = sample()
    graph.remove((iri("relationships/", PLACES), URIRef(f"{SEM}{end}"), None))
    assert_error(graph, about=iri("relationships/", PLACES), saying=f"sem:{end}")


@pytest.mark.parametrize("end", ["source", "target"])
def test_a_relationship_end_that_is_not_an_entity_is_reported(end: str) -> None:
    graph = sample()
    graph.remove((iri("relationships/", PLACES), URIRef(f"{SEM}{end}"), None))
    graph.add((iri("relationships/", PLACES), URIRef(f"{SEM}{end}"), iri("values/", TOOLS)))
    assert_error(graph, about=iri("relationships/", PLACES), saying=f"sem:{end}")


@pytest.mark.parametrize("end", ["source", "target"])
def test_a_relationship_with_two_ends_of_one_kind_is_reported(end: str) -> None:
    graph = sample()
    graph.add((iri("relationships/", PLACES), URIRef(f"{SEM}{end}"), iri("concepts/", VIP)))
    assert_error(graph, about=iri("relationships/", PLACES), saying=f"sem:{end}")


# ------------------------------------------------------------------ hierarchy


def test_an_entity_narrower_than_a_taxonomy_value_is_reported() -> None:
    graph = sample()
    graph.add((iri("concepts/", CUSTOMER), SKOS.broader, iri("values/", TOOLS)))
    assert_error(
        graph, about=iri("concepts/", CUSTOMER), saying="only be narrower than another entity"
    )


def test_a_taxonomy_value_narrower_than_an_entity_is_reported() -> None:
    graph = sample()
    graph.add((iri("values/", DRILLS), SKOS.broader, iri("concepts/", CUSTOMER)))
    assert_error(graph, about=iri("values/", DRILLS), saying="value of a scheme it is itself in")


def test_a_taxonomy_value_narrower_than_a_value_of_another_scheme_is_reported() -> None:
    """The one rule that is about schemes rather than classes: a hierarchy stays inside
    the taxonomy that declares it (spec 6.1.5)."""
    other = f"""{PREFIXES}
    sch:sizes a skos:ConceptScheme ;
      skos:prefLabel "Sizes"@en ;
      sem:schemeType "taxonomy" ;
      sem:status "active" .

    v:88888888-8888-4888-8888-888888888888 a skos:Concept ;
      skos:prefLabel "Large"@en ;
      skos:definition "Bigger than medium."@en ;
      skos:inScheme sch:sizes ;
      skos:topConceptOf sch:sizes ;
      sem:status "active" .
    """
    graph = sample(other)
    assert_no_errors(graph)

    graph.add(
        (
            iri("values/", DRILLS),
            SKOS.broader,
            iri("values/", "88888888-8888-4888-8888-888888888888"),
        )
    )
    assert_error(graph, about=iri("values/", DRILLS), saying="value of a scheme it is itself in")


@pytest.mark.parametrize("subject", ["concepts/" + CUSTOMER_ID, "relationships/" + PLACES])
def test_a_class_that_forms_no_hierarchy_may_not_carry_broader(subject: str) -> None:
    prefix, local = subject.split("/", 1)
    graph = sample()
    graph.add((iri(f"{prefix}/", local), SKOS.broader, iri("concepts/", CUSTOMER)))
    assert_error(graph, about=iri(f"{prefix}/", local), saying="only entities and taxonomy values")


def test_a_scheme_may_not_carry_broader() -> None:
    graph = sample()
    graph.add((iri("schemes/", "product-category"), SKOS.broader, iri("schemes/", "storefront")))
    assert_error(
        graph, about=iri("schemes/", "product-category"), saying="only entities and taxonomy values"
    )


def test_a_cycle_of_two_entities_is_reported() -> None:
    """What nothing before F1 can catch: an adapter sees one source, and inheritance drawn
    across two of them closes a loop neither one holds (spec 6.1.5)."""
    graph = sample()
    graph.add((iri("concepts/", CUSTOMER), SKOS.broader, iri("concepts/", VIP)))

    found = errors(graph)

    assert {issue.location for issue in found} == {
        str(iri("concepts/", CUSTOMER)),
        str(iri("concepts/", VIP)),
    }
    assert all("own ancestor" in issue.message for issue in found)


def test_a_cycle_of_three_taxonomy_values_is_reported() -> None:
    middle = f"""{PREFIXES}
    v:99999999-9999-4999-8999-999999999999 a skos:Concept ;
      skos:prefLabel "Hammer drills"@en ;
      skos:definition "Drills that also hammer."@en ;
      skos:broader v:{DRILLS} ;
      skos:inScheme sch:product-category ;
      sem:status "active" .
    """
    graph = sample(middle)
    assert_no_errors(graph)

    graph.add(
        (
            iri("values/", TOOLS),
            SKOS.broader,
            iri("values/", "99999999-9999-4999-8999-999999999999"),
        )
    )
    found = errors(graph)

    assert len(found) == 3
    assert all("own ancestor" in issue.message for issue in found)


def test_a_node_that_is_its_own_parent_is_reported() -> None:
    graph = sample()
    graph.add((iri("concepts/", VIP), SKOS.broader, iri("concepts/", VIP)))

    found = errors(graph)

    assert [issue.location for issue in found] == [str(iri("concepts/", VIP))]
    assert "own ancestor" in found[0].message


# ------------------------------------------------------------------ notations


def test_one_notation_used_twice_in_a_scheme_is_reported() -> None:
    graph = sample()
    graph.remove((iri("values/", DRILLS), SKOS.notation, None))
    graph.add((iri("values/", DRILLS), SKOS.notation, Literal("T")))

    found = errors(graph)

    assert {issue.location for issue in found} == {
        str(iri("values/", TOOLS)),
        str(iri("values/", DRILLS)),
    }
    assert all("skos:notation" in issue.message for issue in found)


def test_one_notation_used_in_two_schemes_is_allowed() -> None:
    """Codes are unique *within* a scheme; two taxonomies both using "T" is ordinary."""
    other = f"""{PREFIXES}
    sch:sizes a skos:ConceptScheme ;
      skos:prefLabel "Sizes"@en ;
      sem:schemeType "taxonomy" ;
      sem:status "active" .

    v:88888888-8888-4888-8888-888888888888 a skos:Concept ;
      skos:prefLabel "Tall"@en ;
      skos:definition "Taller than average."@en ;
      skos:inScheme sch:sizes ;
      skos:notation "T" ;
      skos:topConceptOf sch:sizes ;
      sem:status "active" .
    """
    assert_no_errors(sample(other))


def test_a_language_tagged_notation_is_reported() -> None:
    graph = sample()
    graph.remove((iri("values/", DRILLS), SKOS.notation, None))
    graph.add((iri("values/", DRILLS), SKOS.notation, Literal("T-DR", lang="en")))
    assert_error(graph, about=iri("values/", DRILLS), saying="untagged code")


# ------------------------------------------------------------------ lifecycle


def test_an_active_node_hanging_off_a_deprecated_one_is_reported() -> None:
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER), STATUS, None))
    graph.add((iri("concepts/", CUSTOMER), STATUS, Literal("deprecated")))

    found = errors(graph)

    # The key account inherits from it, and the customer ID is an attribute of it.
    assert {issue.location for issue in found} == {
        str(iri("concepts/", VIP)),
        str(iri("concepts/", CUSTOMER_ID)),
    }
    assert all("deprecated" in issue.message for issue in found)


def test_a_deprecated_node_may_hang_off_a_deprecated_one() -> None:
    """Deprecation propagates down a hierarchy; that is not the failure (spec 3.5)."""
    graph = sample()
    for subject in (CUSTOMER, VIP, CUSTOMER_ID):
        graph.remove((iri("concepts/", subject), STATUS, None))
        graph.add((iri("concepts/", subject), STATUS, Literal("deprecated")))
    assert_no_errors(graph)


# ------------------------------------------------------------------ IRI policy


@pytest.mark.parametrize(
    ("subject", "type_"),
    [
        (f"{BASE}values/{CUSTOMER}", "sem:Entity"),
        (f"{BASE}concepts/Customer", "sem:Entity"),
        (f"{BASE}concepts/AAAAAAAA-1111-4111-8111-111111111111", "sem:Entity"),
        ("https://elsewhere.example.org/concepts/" + CUSTOMER, "sem:Entity"),
        (f"{BASE}concepts/{PLACES}", "sem:Relationship"),
        (f"{BASE}schemes/Storefront", "skos:ConceptScheme"),
        (f"{BASE}concepts/{TOOLS}", "skos:Concept"),
    ],
)
def test_an_iri_outside_its_kinds_namespace_is_reported(subject: str, type_: str) -> None:
    """IRIs are opaque and permanent (spec 3.1, 3.4), and this is the check that says so
    about the output: the namespace names the kind, the local name is a UUID or a slug."""
    added = f"""{PREFIXES}
    <{subject}> a {type_} ;
      skos:prefLabel "Something"@en ;
      skos:definition "Anything."@en ;
      skos:inScheme sch:storefront ;
      sem:schemeType "glossary" ;
      sem:attributeOf c:{CUSTOMER} ;
      sem:source c:{CUSTOMER} ;
      sem:target c:{CATEGORY} ;
      sem:status "active" .
    """
    graph = sample(added)

    found = [issue for issue in errors(graph) if issue.location == subject]

    assert len(found) == 1, errors(graph)
    assert "opaque local name" in found[0].message


def test_a_hand_edited_iri_is_caught_by_the_check_itself(instance: Path) -> None:
    """End to end, not only against a graph built in this file: the IRI policy is part of
    check 5, and a hand edit to ``generated/`` is what it exists to catch (spec 4.3)."""
    path = instance / "generated" / "concepts-storefront.ttl"
    path.write_text(
        path.read_text(encoding="utf-8")
        + """
c:hand-edited a sem:Entity ;
  skos:prefLabel "Smuggled in"@en ;
  skos:definition "Added by hand, under a local name nothing could have minted."@en ;
  skos:inScheme sch:storefront ;
  sem:status "active" .
""",
        encoding="utf-8",
        newline="\n",
    )

    found = [issue for issue in check(instance) if issue.severity is Severity.ERROR]

    assert [issue.location for issue in found] == [f"{BASE}concepts/hand-edited"]
    assert "opaque local name" in found[0].message


def test_a_dual_typed_node_is_not_treated_as_a_taxonomy_value() -> None:
    """Why the taxonomy target filters the ``sem:`` classes out rather than trusting
    ``a skos:Concept`` alone.

    Every ``sem:`` class is a ``skos:Concept`` (spec 3.2), so anyone who runs these shapes
    behind an RDFS reasoner — which is what publishing them under CC BY invites — has that
    type materialized on every entity. Without the filter, each of those entities becomes
    a taxonomy value, and the same-scheme rule is enforced on inheritance it was never
    written for.
    """
    graph = sample()
    graph.add((iri("concepts/", VIP), RDF.type, SKOS.Concept))

    assert_no_errors(graph)


def test_a_well_formed_iri_of_every_kind_passes() -> None:
    """The other half of the parametrized case above: the sample uses all five."""
    assert_no_errors(sample())


def test_the_iri_policy_matches_what_identity_mints() -> None:
    """The patterns and the minting rules are the same rule, written for two readers.

    ``mint_local_name`` decides what a local name *is*; the shapes decide what one may
    *look like*. If they drift, an instance either mints IRIs its own validation rejects
    or accepts ones it could never have minted.
    """
    objects = sample_model().objects
    assert {object_.kind for object_ in objects} == set(validate.LOCAL_NAME_PATTERNS)

    for object_ in objects:
        local = identity.mint_local_name(object_)
        pattern = validate.LOCAL_NAME_PATTERNS[object_.kind]
        assert re.fullmatch(pattern, local), (object_.kind, local, pattern)


# ------------------------------------------------------------------ overlays


OVERLAY_PREFIXES = (
    PREFIXES
    + """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
"""
)


def overlay(instance: Path, name: str, turtle: str) -> None:
    path = instance / "overlays" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(OVERLAY_PREFIXES + turtle, encoding="utf-8", newline="\n")


def fixture_entity(instance: Path) -> URIRef:
    """A generated IRI from the fixture instance, read from its own output."""
    graph = Graph()
    graph.parse(instance / "generated" / "concepts-storefront.ttl", format="turtle")
    subjects = sorted(str(s) for s in graph.subjects(RDF.type, URIRef(f"{SEM}Entity")))
    return URIRef(subjects[0])


def check(instance: Path) -> tuple[Issue, ...]:
    settings = config.load(instance)
    return validate.check_shapes(instance, base_iri=settings.base_iri)


def test_an_overlay_may_add_statements_about_a_generated_node(instance: Path) -> None:
    """What overlays are *for*: axioms the sources cannot express (spec 4.2)."""
    subject = fixture_entity(instance)
    overlay(
        instance,
        "patches/criticality.ttl",
        f"""
        x:criticality a rdf:Property ;
          rdfs:label "criticality"@en .

        <{subject}> x:criticality "high" ;
          rdfs:seeAlso <https://example.org/handbook> .
        """,
    )

    assert [issue for issue in check(instance) if issue.severity is Severity.ERROR] == []


@pytest.mark.parametrize(
    ("predicate", "value", "saying"),
    [
        ("skos:prefLabel", '"Renamed"@en', "skos:prefLabel"),
        ("sem:status", '"deprecated"', "sem:status"),
        ("skos:inScheme", "sch:elsewhere", "skos:inScheme"),
    ],
)
def test_an_overlay_may_not_restate_what_a_generated_node_is(
    instance: Path, predicate: str, value: str, saying: str
) -> None:
    """Spec 6.1.5's overlay rule, and the reason overlays are validated on their own: the
    union of the two graphs no longer knows which file a statement came from."""
    subject = fixture_entity(instance)
    overlay(instance, "patches/rename.ttl", f"<{subject}> {predicate} {value} .")

    found = [issue for issue in check(instance) if issue.severity is Severity.ERROR]

    assert [issue.location for issue in found] == [str(subject)]
    assert saying in found[0].message


def test_an_overlay_may_say_anything_about_its_own_terms(instance: Path) -> None:
    """The ``x:`` namespace is the organization's (spec 3.6): a local term carries its own
    label, and the IRI policy has no opinion about it."""
    overlay(
        instance,
        "ext/regions.ttl",
        """
        x:Region a rdfs:Class ;
          skos:prefLabel "Region"@en ;
          skos:inScheme x:LocalScheme ;
          sem:status "active" .
        """,
    )

    assert [issue for issue in check(instance) if issue.severity is Severity.ERROR] == []


def test_an_imported_vocabulary_is_not_judged_by_the_core_shapes(instance: Path) -> None:
    """``overlays/external/`` holds curated subsets of standard vocabularies (spec 4.2).

    Their concepts have no ``sem:status``, no ``sem:sourceRef`` and no scheme of this
    instance's, and they are nobody's to deprecate. Applying the compiler's own guarantees
    to them would report dozens of violations for using overlays exactly as intended —
    which is why the core shapes read ``generated/`` alone.
    """
    overlay(
        instance,
        "external/euro-vocabulary.ttl",
        """
        <https://example.org/vocab/Widget> a skos:Concept ;
          skos:prefLabel "Widget" ;
          skos:broader <https://example.org/vocab/Thing> .
        """,
    )

    assert check(instance) == check_without_overlays(instance)


def check_without_overlays(instance: Path) -> tuple[Issue, ...]:
    scratch = instance.parent / "no-overlays"
    if scratch.exists():
        shutil.rmtree(scratch)
    shutil.copytree(instance, scratch, ignore=shutil.ignore_patterns("overlays"))
    return check(scratch)


def test_an_unreadable_overlay_names_the_file(instance: Path) -> None:
    """Hand-written RDF is where a syntax error is likely; it is not a traceback."""
    overlay(instance, "patches/broken.ttl", "this is not turtle")

    with pytest.raises(validate.ValidationError) as raised:
        check(instance)

    assert "broken.ttl" in str(raised.value)
    assert all(issue.severity is Severity.ERROR for issue in raised.value.issues)


def test_an_instance_with_no_overlays_is_ordinary(instance: Path) -> None:
    assert not (instance / "overlays").exists()
    assert validate.read_overlays(instance) is not None
    assert len(validate.read_overlays(instance)) == 0


# ------------------------------------------------------------------ local shapes


def test_a_local_shape_is_applied(instance: Path) -> None:
    """Spec 6.1.5: the core shapes plus every shape in ``shapes/local/``."""
    path = instance / "shapes" / "local" / "definitions.ttl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""{PREFIXES}
        @prefix sh: <http://www.w3.org/ns/shacl#> .

        <https://semantics.example.com/shapes#Everything> a sh:NodeShape ;
            sh:targetClass sem:Entity ;
            sh:property [ sh:path skos:example ; sh:minCount 1 ;
                          sh:message "our stewards want an example" ] .
        """,
        encoding="utf-8",
        newline="\n",
    )

    found = [issue for issue in check(instance) if "example" in issue.message]

    assert found, check(instance)
    assert all(issue.severity is Severity.ERROR for issue in found)


def test_a_local_shape_sees_the_overlays_too(instance: Path) -> None:
    """An organization's own rules are about the organization's whole graph.

    Targeted by class, deliberately: ``sh:targetNode`` selects a node whether or not the
    data mentions it, so a shape written that way would report the same thing against the
    generated graph alone and prove nothing about which graphs are validated.
    """
    overlay(
        instance,
        "ext/regions.ttl",
        """
        x:Region a rdfs:Class ; skos:prefLabel "Region"@en .
        x:oslo a x:Region ; skos:prefLabel "Oslo"@en .
        """,
    )
    path = instance / "shapes" / "local" / "regions.ttl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""{PREFIXES}
        @prefix sh: <http://www.w3.org/ns/shacl#> .

        <https://semantics.example.com/shapes#Regions> a sh:NodeShape ;
            sh:targetClass x:Region ;
            sh:property [ sh:path skos:definition ; sh:minCount 1 ;
                          sh:message "a local term needs a definition" ] .
        """,
        encoding="utf-8",
        newline="\n",
    )

    found = [issue for issue in check(instance) if "local term" in issue.message]

    assert [issue.location for issue in found] == [f"{BASE}ext#oslo"]


# ------------------------------------------------------------------ the run itself


def test_results_are_sorted() -> None:
    """CI reads this output, so its order is part of it."""
    graph = sample()
    for subject in (VIP, CATEGORY, CUSTOMER):
        graph.remove((iri("concepts/", subject), SKOS.definition, None))

    issues = checked(graph)

    assert [issue.location for issue in issues] == [
        str(iri("concepts/", CUSTOMER)),
        str(iri("concepts/", VIP)),
        str(iri("concepts/", CATEGORY)),
    ]


_ORDER_SCRIPT = """
import sys

sys.path.insert(0, "tests")
from test_validate import SKOS, CATEGORY, CUSTOMER, VIP, checked, iri, sample

graph = sample()
for subject in (VIP, CATEGORY, CUSTOMER):
    graph.remove((iri("concepts/", subject), SKOS.definition, None))
sys.stdout.write("\\n".join(str(issue) for issue in checked(graph)))
"""


def _issue_order_in_a_subprocess(hash_seed: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", _ORDER_SCRIPT],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
        check=True,
    )
    return completed.stdout


def test_the_order_is_the_same_on_every_machine() -> None:
    """Run out of process because that is the only way to vary ``PYTHONHASHSEED``.

    Results arrive from pyshacl in no particular order and are collected in a set, so
    without the explicit sort they would come out following string hashing — identical all
    day on one machine and different on the next, which makes CI output nobody can diff.
    An in-process test of three issues passes by luck one time in six.
    """
    first = _issue_order_in_a_subprocess("0")
    second = _issue_order_in_a_subprocess("12345")
    third = _issue_order_in_a_subprocess("98765")

    assert first == second == third
    # Guards the guard: three identical empty outputs would also pass the line above.
    assert first.count("\n") == 2


def test_the_same_problem_found_twice_is_reported_once() -> None:
    """One problem shown as two costs an operator a search for the second cause."""
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER), SKOS.definition, None))
    duplicate = validate.core_shapes() + validate.core_shapes()

    assert validate.shacl(graph, duplicate) == validate.shacl(graph, validate.core_shapes())


def test_two_shapes_reporting_the_same_thing_are_one_issue() -> None:
    """A node reached by two shapes with the same message is one problem for a steward.

    Reachable as soon as an instance writes a local shape that overlaps a core one, and
    the cost lands in CI: a second identical line is a second search for a second cause.
    """
    shapes = Graph()
    shapes.parse(
        data=f"""{PREFIXES}
        @prefix sh: <http://www.w3.org/ns/shacl#> .

        <urn:test:one> a sh:NodeShape ;
            sh:targetClass sem:Entity ;
            sh:property [ sh:path skos:example ; sh:minCount 1 ; sh:message "needs an example" ] .

        <urn:test:two> a sh:NodeShape ;
            sh:targetClass sem:Entity ;
            sh:property [ sh:path skos:example ; sh:minCount 1 ; sh:message "needs an example" ] .
        """,
        format="turtle",
    )

    issues = validate.shacl(sample(), shapes)

    assert [issue.location for issue in issues] == [
        str(iri("concepts/", CUSTOMER)),
        str(iri("concepts/", VIP)),
        str(iri("concepts/", CATEGORY)),
    ]


def test_a_shape_carrying_two_messages_reports_both_in_a_fixed_order() -> None:
    """rdflib holds a result's messages in a set, so picking "the" message would follow
    string hashing — identical all day on one machine and different on the next."""
    shapes = Graph()
    shapes.parse(
        data=f"""{PREFIXES}
        @prefix sh: <http://www.w3.org/ns/shacl#> .

        <urn:test:messages> a sh:NodeShape ;
            sh:targetClass sem:Attribute ;
            sh:property [ sh:path skos:example ; sh:minCount 1 ;
                          sh:message "beta" , "alpha" ] .
        """,
        format="turtle",
    )

    issues = validate.shacl(sample(), shapes)

    assert [issue.message for issue in issues] == ["alpha; beta"]


def test_every_core_shape_says_what_it_wants() -> None:
    """A violation without an ``sh:message`` reports pyshacl's own wording, which names a
    constraint component rather than the rule a steward broke."""
    shapes = validate.core_shapes()
    for shape in shapes.subjects(RDF.type, SH.NodeShape):
        constraints = list(shapes.objects(shape, SH.property)) + list(
            shapes.objects(shape, SH.sparql)
        )
        assert constraints, shape
        for constraint in constraints:
            assert list(shapes.objects(constraint, SH.message)), (shape, constraint)


def test_the_shapes_do_not_depend_on_the_metamodel_being_loaded() -> None:
    """Every ``sem:`` class is a ``skos:Concept`` (spec 3.2), so a shape targeting
    ``skos:Concept`` would silently start matching entities the moment a caller loaded
    ``sem.ttl`` beside the data — and the taxonomy rules would then be enforced on nodes
    they were never written for. The SPARQL target exists to stop that."""
    plain = sample()
    with_ontology = sample()
    with_ontology.parse(ONTOLOGY_PATH, format="turtle")

    assert checked(with_ontology) == checked(plain) == ()


def test_validation_leaves_the_graph_it_validated_alone() -> None:
    """pyshacl can materialize entailments into the graph it is given. Nothing here asks
    it to, and a check that quietly enlarged the graph would hand every later check
    (spec 6.1 checks 6 and 7) statements the compiler never wrote."""
    graph = sample()
    before = len(graph)

    checked(graph)

    assert len(graph) == before


def test_the_shapes_reach_the_network_for_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A check that dialled out would fail differently on a laptop and in CI, which is
    what spec 6.3 promises it cannot do."""

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("validation opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    assert checked(sample()) == ()


def test_the_taxonomy_target_is_the_one_the_iri_policy_reuses() -> None:
    """The generated shapes point at a target defined in ``core.ttl``; a second copy of
    that query would be a second answer to "what is a taxonomy value"."""
    shapes = validate.core_shapes()

    assert (validate.TAXONOMY_VALUE_TARGET, RDF.type, SH.SPARQLTarget) in shapes
    assert (
        None,
        SH.target,
        validate.TAXONOMY_VALUE_TARGET,
    ) in validate.instance_shapes(BASE)


def test_the_shapes_are_packaged_with_the_compiler() -> None:
    """They ship inside the wheel like the ontology does (spec 8), so an instance
    installs one thing and gets both."""
    assert validate.SHAPES_DIR.is_dir()
    assert sorted(path.name for path in validate.SHAPES_DIR.glob("*.ttl")) == ["core.ttl"]
    assert len(validate.core_shapes()) > 0


def test_shape_iris_are_not_minted_in_the_metamodel_namespace() -> None:
    """``sem:`` resolves to the ontology document, whose inventory is fixed by spec
    3.2/3.3 (task A3). A shape IRI there would be a term the published vocabulary does
    not declare."""
    shapes = validate.core_shapes() + validate.instance_shapes(BASE)
    declared: Iterable[URIRef] = {
        subject for subject in shapes.subjects() if isinstance(subject, URIRef)
    }

    assert declared
    assert not [subject for subject in declared if str(subject).startswith(str(SEM))]

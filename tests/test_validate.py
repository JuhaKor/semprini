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
TERM = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
STRAY = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

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


def test_a_taxonomy_value_narrower_than_something_that_is_not_a_concept_is_reported() -> None:
    """Sharing a scheme is not enough — the parent has to be a taxonomy value.

    Nothing the compiler writes could produce this, which is the point: these shapes judge
    ``generated/``, where a node of an unexpected type is either a hand edit or a defect
    in a source adapter, and both are what check 5 exists to stop (spec 4.3, 6.1.5).
    """
    stray = f"""{PREFIXES}
    v:{STRAY} a x:Region ;
      skos:prefLabel "Nordics"@en ;
      skos:inScheme sch:product-category ;
      sem:status "active" .
    """
    graph = sample(stray)
    assert_no_errors(graph)

    graph.add((iri("values/", DRILLS), SKOS.broader, iri("values/", STRAY)))
    assert_error(graph, about=iri("values/", DRILLS), saying="value of a scheme it is itself in")


@pytest.mark.parametrize("subject", ["concepts/" + CUSTOMER_ID, "relationships/" + PLACES])
def test_a_class_that_forms_no_hierarchy_may_not_carry_broader(subject: str) -> None:
    prefix, local = subject.split("/", 1)
    graph = sample()
    graph.add((iri(f"{prefix}/", local), SKOS.broader, iri("concepts/", CUSTOMER)))
    assert_error(graph, about=iri(f"{prefix}/", local), saying="only entities and taxonomy values")


def test_a_business_term_may_not_carry_broader() -> None:
    """A glossary term is in neither hierarchy the metamodel has (spec 3.3, 6.1.5).

    Refused now rather than left open: no adapter emits a business term yet, and relaxing
    this when a glossary adapter arrives with term-to-term hierarchies is additive, where
    tightening it later would refuse content an instance had already committed.
    """
    term = f"""{PREFIXES}
    c:{TERM} a sem:BusinessTerm ;
      skos:prefLabel "Churn"@en ;
      skos:definition "A customer who stops buying from us."@en ;
      skos:inScheme sch:storefront ;
      sem:status "active" .
    """
    graph = sample(term)
    assert_no_errors(graph)

    graph.add((iri("concepts/", TERM), SKOS.broader, iri("concepts/", CUSTOMER)))
    assert_error(graph, about=iri("concepts/", TERM), saying="only entities and taxonomy values")


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


def test_a_hierarchy_too_deep_to_check_is_named_rather_than_crashing() -> None:
    """rdflib walks ``skos:broader+`` recursively, so a chain about a thousand deep
    exhausts the stack — inside the cycle rule, the one thing a bare traceback here would
    be hiding. The depth is reported as the finding instead."""
    graph = sample()
    chain = [iri("values/", f"{index:08d}-0000-4000-8000-000000000000") for index in range(2000)]
    for child, parent in zip(chain[1:], chain, strict=False):
        graph.add((child, SKOS.broader, parent))

    with pytest.raises(validate.ValidationError, match="too deep to check for cycles"):
        checked(graph)


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


def test_the_iri_policy_names_the_kinds_each_rule_is_about() -> None:
    """These messages are what an operator reads when a run refuses an IRI, so they name
    the classes the rule covers — the ``c:`` rule is as much about attributes and business
    terms as about entities — in a sentence written for a person."""
    messages = {str(value) for value in validate.instance_shapes(BASE).objects(None, SH.message)}

    assert any("an entity, an attribute or a business term is minted" in m for m in messages)
    assert any("a taxonomy value is minted" in m for m in messages)
    assert not any("a entity" in m or "taxonomy-value" in m for m in messages), messages


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


SHAPE_PREFIXES = (
    PREFIXES
    + """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix shp: <https://w3id.org/semprini/shapes#> .
@prefix ours: <https://semantics.example.com/shapes#> .
"""
)
"""``shp:`` is the plane's shape namespace and ``ours:`` is the instance's own.

Both are spelled out in every fixture below, because the difference between them is the
whole of spec 6.1.5's additive rule and a test that blurred it would prove nothing.
"""


def local_shape(instance: Path, name: str, turtle: str) -> Path:
    path = instance / "shapes" / "local" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SHAPE_PREFIXES + turtle, encoding="utf-8", newline="\n")
    return path


def additive(instance: Path) -> tuple[Issue, ...]:
    """What spec 6.1.5's additive-only rule says about the instance's local shapes."""
    return validate.check_additive(validate.read_local_shape_files(instance))


def shapes_from(turtle: str) -> Graph:
    graph = Graph()
    graph.parse(data=SHAPE_PREFIXES + turtle, format="turtle")
    return graph


def test_a_local_shape_is_applied(instance: Path) -> None:
    """Spec 6.1.5: the core shapes plus every shape in ``shapes/local/``."""
    local_shape(
        instance,
        "definitions.ttl",
        """
        ours:Everything a sh:NodeShape ;
            sh:targetClass sem:Entity ;
            sh:property [ sh:path skos:example ; sh:minCount 1 ;
                          sh:message "our stewards want an example" ] .
        """,
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
    local_shape(
        instance,
        "regions.ttl",
        """
        ours:Regions a sh:NodeShape ;
            sh:targetClass x:Region ;
            sh:property [ sh:path skos:definition ; sh:minCount 1 ;
                          sh:message "a local term needs a definition" ] .
        """,
    )

    found = [issue for issue in check(instance) if "local term" in issue.message]

    assert [issue.location for issue in found] == [f"{BASE}ext#oslo"]


def test_the_local_shapes_are_read_one_file_at_a_time(instance: Path) -> None:
    """A local shape is accepted or refused as a *file*, so it is read as one.

    The key is the path a steward would open, from the instance root and in posix form on
    every platform: it is what a rejection reports as its location.
    """
    local_shape(instance, "one.ttl", "ours:One a sh:NodeShape .")
    local_shape(instance, "team/two.ttl", "ours:Two a sh:NodeShape .")

    files = validate.read_local_shape_files(instance)

    assert sorted(files) == ["shapes/local/one.ttl", "shapes/local/team/two.ttl"]
    assert all(len(graph) for graph in files.values())
    # The union is what gets applied, and must be the same statements (spec 6.1.5).
    assert len(validate.read_local_shapes(instance)) == sum(len(g) for g in files.values())


# ------------------------------------------- local shapes are additive only (spec 6.1.5)


def test_a_shape_that_only_adds_is_accepted(instance: Path) -> None:
    """The case the whole rule must not break: an organization's own rule, as strict as
    it likes, about the classes the metamodel defines (spec 3.6)."""
    local_shape(
        instance,
        "stewardship.ttl",
        """
        ours:Stewardship a sh:NodeShape ;
            rdfs:label "What our stewards require" ;
            sh:targetClass sem:Entity, sem:Attribute ;
            sh:property [ sh:path skos:definition ; sh:minCount 1 ; sh:maxCount 1 ;
                          sh:severity sh:Violation ;
                          sh:message "every entity is defined, here" ] ;
            sh:property [ sh:path skos:example ; sh:minCount 1 ] .
        """,
    )

    assert additive(instance) == ()


def test_naming_a_core_term_as_an_object_is_how_a_local_rule_says_what_it_is_about(
    instance: Path,
) -> None:
    """Guards the rule against over-reach in the direction that would matter most.

    ``sh:targetClass sem:Entity`` and ``sh:path sem:status`` mention core IRIs in every
    legitimate local shape there is. Only the *subject* position is the plane's.
    """
    local_shape(
        instance,
        "about-core-terms.ttl",
        """
        ours:Statuses a sh:NodeShape ;
            sh:targetClass sem:Relationship ;
            sh:property [ sh:path sem:status ; sh:hasValue "active" ;
                          sh:message "we do not keep deprecated relationships" ] .
        """,
    )

    assert additive(instance) == ()


def test_a_local_shape_may_not_redefine_a_metamodel_term(instance: Path) -> None:
    """Spec 3.6 rule 2: core terms are never redefined, narrowed or retargeted."""
    local_shape(instance, "terms.ttl", "sem:status rdfs:range xsd:integer .")

    (issue,) = additive(instance)

    assert issue.severity is Severity.ERROR
    assert issue.location == "shapes/local/terms.ttl"
    assert "sem:status" in issue.message
    assert "x: namespace" in issue.message


def test_a_local_shape_may_not_retarget_a_metamodel_class(instance: Path) -> None:
    """SHACL's implicit class target: a ``sem:`` class that is also a ``sh:NodeShape``
    becomes a shape, so this is how a core class would be given rules from outside."""
    local_shape(
        instance,
        "entities.ttl",
        """
        sem:Entity a sh:NodeShape ;
            sh:property [ sh:path skos:prefLabel ; sh:minCount 1 ] .
        """,
    )

    assert [issue.location for issue in additive(instance)] == ["shapes/local/entities.ttl"]
    assert "sem:Entity" in additive(instance)[0].message


def test_a_local_shape_may_not_edit_a_core_shape(instance: Path) -> None:
    """Switching one off is the clearest case: the statement is about ``shp:Node``."""
    local_shape(instance, "off.ttl", "shp:Node sh:deactivated true .")

    (issue,) = additive(instance)

    assert issue.severity is Severity.ERROR
    assert "shp:Node" in issue.message
    assert "core shape" in issue.message


def test_a_local_shape_may_not_claim_a_core_iri_that_does_not_exist_yet(
    instance: Path,
) -> None:
    """Whole namespaces, not today's inventory: a file that claimed an unused ``shp:``
    IRI would be broken by the release that adds one, and its own terms belong in ``x:``
    either way (spec 3.6)."""
    local_shape(instance, "future.ttl", "shp:SomethingWeInvented a sh:NodeShape .")

    assert len(additive(instance)) == 1


@pytest.mark.parametrize(
    ("written", "shape"),
    [
        ("sh:minCount 0", "sh:property [ sh:path skos:prefLabel ; sh:minCount 0 ]"),
        ("sh:uniqueLang false", "sh:property [ sh:path skos:prefLabel ; sh:uniqueLang false ]"),
        ("sh:closed false", "sh:closed false ; sh:property [ sh:path skos:prefLabel ]"),
    ],
)
def test_a_constraint_that_constrains_nothing_is_refused(
    instance: Path, written: str, shape: str
) -> None:
    """The three ways SHACL lets someone write "this is optional now".

    Each is a no-op — every node satisfies ``sh:minCount 0``, and the other two only
    constrain when true — so refusing them blocks no rule anyone meant to write, and says
    the true thing: validation is the sum of every shape, so a local file cannot subtract.
    """
    local_shape(instance, "relaxed.ttl", f"ours:Relaxed a sh:NodeShape ; {shape} .")

    (issue,) = additive(instance)

    assert issue.severity is Severity.ERROR
    assert written in issue.message
    assert "constrains nothing" in issue.message


def test_a_relaxed_cardinality_is_reported_against_the_path_it_was_written_for(
    instance: Path,
) -> None:
    """A property shape is usually a blank node, so the path is the only thing a steward
    can find in their own file."""
    local_shape(
        instance,
        "relaxed.ttl",
        "ours:Relaxed a sh:NodeShape ; sh:property [ sh:path sem:status ; sh:minCount 0 ] .",
    )

    assert "sem:status" in additive(instance)[0].message


def test_the_named_path_does_not_depend_on_rdflib_iteration_order(instance: Path) -> None:
    """A property shape with two paths is malformed and perfectly possible to write.

    rdflib holds a subject's objects in a set, so "the" path is whichever one hashing
    offers first — the trap the run report hit when choosing among a node's labels. The
    first in string order is named instead, and the file is reported as unusable SHACL by
    the same run, which is the other half of what is wrong with it.
    """
    local_shape(
        instance,
        "relaxed.ttl",
        """
        ours:Relaxed a sh:NodeShape ; sh:targetClass sem:Entity ;
            sh:property [ sh:path skos:prefLabel ; sh:path skos:definition ;
                          sh:minCount 0 ] .
        """,
    )

    (issue,) = [item for item in additive(instance) if "constrains nothing" in item.message]

    # In full, since only the two namespaces the plane owns are shortened in a message.
    assert "core#definition" in issue.message
    assert "prefLabel" not in issue.message


def test_a_local_shape_may_not_derive_the_data_it_judges(instance: Path) -> None:
    """``sh:rule`` writes into the graph being validated (spec 4.2, 6.1.5)."""
    local_shape(
        instance,
        "inference.ttl",
        """
        ours:Inferred a sh:NodeShape ;
            sh:targetClass sem:Entity ;
            sh:rule [ a sh:TripleRule ; sh:subject sh:this ;
                      sh:predicate sem:status ; sh:object "active" ] .
        """,
    )

    (issue,) = additive(instance)

    assert issue.severity is Severity.ERROR
    assert "sh:rule" in issue.message
    assert "overlays/" in issue.message


def test_a_shacl_rule_would_otherwise_invent_the_statements_it_checks() -> None:
    """Why ``sh:rule`` is refused rather than tolerated, shown rather than asserted.

    The same shape passes or fails depending only on whether the rule is there — on data
    that is missing the very statement the rule supplies. Nothing in the instance holds
    that statement, so no reviewer would ever see it.
    """
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER), STATUS, None))
    demand = """
        <urn:test:shape> a sh:NodeShape ;
            sh:targetClass sem:Entity ;
            sh:property [ sh:path sem:status ; sh:minCount 1 ; sh:message "needs a status" ] ;
        """
    rule = """
            sh:rule [ a sh:TripleRule ; sh:subject sh:this ;
                      sh:predicate sem:status ; sh:object "active" ] ;
        """

    without = validate.shacl(graph, shapes_from(demand + "."))
    with_rule = validate.shacl(graph, shapes_from(demand + rule + "."))

    assert [issue.location for issue in without] == [str(iri("concepts/", CUSTOMER))]
    assert with_rule == ()


def test_a_local_shape_may_not_reference_a_core_shape(instance: Path) -> None:
    """The first thing an adopter tries after being refused, and it never works: local
    shapes are validated on their own graph, which does not hold the core ones.

    Refused rather than tolerated because the two ways it fails are both silent about the
    cause — see the next test, which is where the reason is pinned.
    """
    local_shape(
        instance,
        "taxonomies.ttl",
        """
        ours:Taxonomies a sh:NodeShape ;
            sh:target shp:TaxonomyValueTarget ;
            sh:property [ sh:path skos:notation ; sh:minCount 1 ;
                          sh:message "our taxonomy values carry a code" ] .
        """,
    )

    (issue,) = additive(instance)

    assert issue.severity is Severity.ERROR
    assert "shp:TaxonomyValueTarget" in issue.message
    assert "validated on their own" in issue.message


@pytest.mark.parametrize(
    ("written", "consequence"),
    [
        ("sh:node shp:Node", "matches every node, since an absent shape constrains nothing"),
        ("sh:target shp:TaxonomyValueTarget", "aborts the validator with no file named"),
    ],
)
def test_a_reference_to_a_core_shape_never_means_what_it_reads_as(
    written: str, consequence: str
) -> None:
    """Why the reference is refused rather than left alone, shown rather than asserted.

    One of these two silently passes everything and the other stops the run, and neither
    is "the core rule also applies here" — which is what an author writing it believes.
    """
    shapes = shapes_from(f"ours:S a sh:NodeShape ; sh:targetClass sem:Entity ; {written} .")
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER), SKOS.prefLabel, None))

    try:
        found = validate.shacl(graph, shapes)
    except validate.ValidationError as error:
        # The abort, named rather than a traceback — and naming no file, which is what
        # `check_shapes` has to supply.
        assert "cannot be applied as SHACL" in str(error), consequence
    else:
        # The silence: the core rule this shape names is not enforced by naming it.
        assert found == (), consequence


def test_a_refused_file_is_not_applied_and_the_others_still_are(instance: Path) -> None:
    """ "Rejected" means the rules do not run: reporting a shape as forbidden and then
    obeying it would leave a verdict resting on a file the plane will not honour. One
    steward's mistake must not switch off an organization's other rules, though.
    """
    local_shape(
        instance,
        "forbidden.ttl",
        """
        shp:Node sh:deactivated true .

        ours:Refused a sh:NodeShape ;
            sh:targetClass sem:Entity ;
            sh:property [ sh:path skos:example ; sh:minCount 1 ;
                          sh:message "the refused rule" ] .
        """,
    )
    local_shape(
        instance,
        "allowed.ttl",
        """
        ours:Allowed a sh:NodeShape ;
            sh:targetClass sem:Entity ;
            sh:property [ sh:path skos:example ; sh:minCount 1 ;
                          sh:message "the allowed rule" ] .
        """,
    )

    found = check(instance)

    # The refused file's rule targets sem:Entity and the fixture instance has entities
    # with no skos:example, so it would fire on several nodes if the file were applied.
    assert [issue.location for issue in found if "the refused rule" in issue.message] == []
    assert [issue.location for issue in found if "the allowed rule" in issue.message]
    assert [issue.location for issue in found if "core shape" in issue.message] == [
        "shapes/local/forbidden.ttl"
    ]


def test_the_core_shapes_copied_and_relaxed_do_not_relax_anything(instance: Path) -> None:
    """The likeliest attempt there is: ``core.ttl`` copied into ``shapes/local/`` and
    edited. Every cardinality in the copy is made optional, and the core rule fires
    anyway — the core shapes are the compiler's, and are applied from the package.
    """
    relaxed = (validate.SHAPES_DIR / "core.ttl").read_text(encoding="utf-8")
    local_shape_file = instance / "shapes" / "local" / "core.ttl"
    local_shape_file.parent.mkdir(parents=True, exist_ok=True)
    local_shape_file.write_text(relaxed.replace("sh:minCount 1", "sh:minCount 0"), encoding="utf-8")
    graph = sample()
    graph.remove((iri("concepts/", CUSTOMER), SKOS.prefLabel, None))

    found = validate.check_shapes(instance, base_iri=BASE, generated=graph, overlays=Graph())

    assert [issue for issue in found if "skos:prefLabel" in issue.message]
    assert {issue.location for issue in found if "core shape" in issue.message} == {
        "shapes/local/core.ttl"
    }


# ------------------------------------------ a local shape that is not usable as SHACL


NOT_USABLE_SHACL = {
    "a property shape with no path": """
        ours:S a sh:NodeShape ; sh:targetClass sem:Entity ;
            sh:property [ sh:minCount 1 ] .
    """,
    "two paths on one property shape": """
        ours:S a sh:NodeShape ; sh:targetClass sem:Entity ;
            sh:property [ sh:path skos:prefLabel ; sh:path skos:definition ; sh:minCount 1 ] .
    """,
    "a pattern that is not a regex": """
        ours:S a sh:NodeShape ; sh:targetClass sem:Entity ;
            sh:property [ sh:path skos:prefLabel ; sh:pattern "((" ] .
    """,
    "a select that is not a query": """
        ours:S a sh:NodeShape ; sh:targetClass sem:Entity ;
            sh:sparql [ a sh:SPARQLConstraint ; sh:message "no" ;
                        sh:select "SELECT ?this WHERE { this is not sparql }" ] .
    """,
}
"""Turtle that parses, is perfectly additive, and is not usable as SHACL.

Every one of these is an ordinary mistake in a hand-written shapes file, and they raise
out of three different libraries — pyshacl, ``re`` and pyparsing. None of them is a thing
this project can enumerate its way out of, which is why the guard is broad.
"""


@pytest.mark.parametrize("turtle", NOT_USABLE_SHACL.values(), ids=list(NOT_USABLE_SHACL))
def test_a_local_shape_that_is_not_usable_shacl_is_a_finding(instance: Path, turtle: str) -> None:
    """Check 1 catches Turtle that does not parse; this is Turtle that does.

    An adopter writes these files by hand (spec 4.2), so being wrong about SHACL is an
    ordinary state for one to be in — and every one of them reached an operator as a
    traceback from inside a library before this.
    """
    local_shape(instance, "broken.ttl", turtle)

    found = [issue for issue in check(instance) if issue.location == "shapes/local/broken.ttl"]

    assert [issue.severity for issue in found] == [Severity.ERROR]
    assert "cannot be applied as SHACL" in found[0].message
    # Rendered as one bullet and pasted into a pull request body (spec 6.2): a newline
    # from a library's message would silently end the list it is in.
    assert "\n" not in found[0].message


def test_the_local_shape_that_cannot_be_applied_is_the_one_named(instance: Path) -> None:
    """A validator says "these shapes are broken" about the whole graph it was handed,
    and its message often names nothing at all. The file is what a steward opens."""
    local_shape(instance, "broken.ttl", NOT_USABLE_SHACL["a property shape with no path"])
    local_shape(
        instance,
        "works.ttl",
        """
        ours:Works a sh:NodeShape ;
            sh:targetClass sem:Entity ;
            sh:property [ sh:path skos:example ; sh:minCount 1 ;
                          sh:message "the working rule" ] .
        """,
    )

    found = check(instance)

    assert [issue.location for issue in found if "cannot be applied" in issue.message] == [
        "shapes/local/broken.ttl"
    ]
    # The files that do load are validated in the same pass, so one run still reports
    # everything (spec 6.1) rather than one broken file hiding the rest.
    assert [issue for issue in found if "the working rule" in issue.message]


def test_shapes_that_only_break_together_are_reported_against_the_directory(
    instance: Path,
) -> None:
    """Each file is usable SHACL on its own; the two of them are not.

    The second adds a path to a property shape the first one defines, and a property shape
    may have only one — so neither file is wrong by itself and their union is. No single
    file is the answer, so the honest location is the directory rather than whichever file
    happened to be read second.
    """
    local_shape(
        instance,
        "one.ttl",
        """
        ours:Entities a sh:NodeShape ; sh:targetClass sem:Entity ; sh:property ours:Labelled .
        ours:Labelled a sh:PropertyShape ; sh:path skos:prefLabel ; sh:minCount 1 .
        """,
    )
    local_shape(instance, "two.ttl", "ours:Labelled sh:path skos:definition .")

    found = [issue for issue in check(instance) if "cannot be applied" in issue.message]

    assert [issue.location for issue in found] == ["shapes/local"]
    assert all(issue.severity is Severity.ERROR for issue in found)


def test_the_fixture_instance_has_no_local_shapes_and_that_is_ordinary(instance: Path) -> None:
    assert not (instance / "shapes" / "local").exists()
    assert validate.read_local_shape_files(instance) == {}
    assert validate.check_additive({}) == ()


REFUSALS = {
    "shapes/local/b.ttl": "sem:status rdfs:range xsd:integer .",
    "shapes/local/a.ttl": "shp:Node sh:deactivated true .\nsem:Entity a sh:NodeShape .",
}


def refusal_order() -> str:
    """Every refusal the two files above produce, in the order they are reported."""
    files = {name: shapes_from(turtle) for name, turtle in REFUSALS.items()}
    return "\n".join(str(issue) for issue in validate.check_additive(files))


_REFUSAL_ORDER_SCRIPT = """
import sys

sys.path.insert(0, "tests")
from test_validate import refusal_order

sys.stdout.write(refusal_order())
"""


def test_refusals_are_reported_in_a_fixed_order() -> None:
    """CI reads these, so their order is part of them (spec 6.1).

    Refusals are collected in a set — one file can break the rule twice, and two files can
    break it identically — so without the explicit sort they come out following string
    hashing. Three issues in a set agree with chance one time in six, which is why this is
    asserted across processes rather than in one: the same trap the core shapes' own
    ordering test fell into.
    """
    first = _in_a_subprocess(_REFUSAL_ORDER_SCRIPT, "0")
    second = _in_a_subprocess(_REFUSAL_ORDER_SCRIPT, "12345")
    third = _in_a_subprocess(_REFUSAL_ORDER_SCRIPT, "98765")

    assert first == second == third
    # Guards the guard: three identical empty outputs would also pass the line above.
    assert first.count("\n") == 2
    assert first.index("a.ttl") < first.rindex("a.ttl") < first.index("b.ttl")


def test_refusals_are_reported_once(instance: Path) -> None:
    for name, turtle in REFUSALS.items():
        local_shape(instance, Path(name).name, turtle)

    found = additive(instance)

    assert len(found) == len(set(found)) == 3


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


def _in_a_subprocess(script: str, hash_seed: str) -> str:
    """Run ``script`` under a given ``PYTHONHASHSEED``.

    Out of process because that is the only way to vary the seed, and the seed is the only
    way to test a promise about ordering: everything here is collected in sets.
    """
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
        check=True,
    )
    return completed.stdout


def _issue_order_in_a_subprocess(hash_seed: str) -> str:
    return _in_a_subprocess(_ORDER_SCRIPT, hash_seed)


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


_SEVERITY_SHAPES = f"""{PREFIXES}
@prefix sh: <http://www.w3.org/ns/shacl#> .

<urn:test:strict> a sh:NodeShape ;
    sh:targetClass sem:Attribute ;
    sh:property [ sh:path skos:example ; sh:minCount 1 ; sh:message "needs an example" ] .

<urn:test:lenient> a sh:NodeShape ;
    sh:targetClass sem:Attribute ;
    sh:property [ sh:path skos:example ; sh:minCount 1 ; sh:severity sh:Warning ;
                  sh:message "needs an example" ] .
"""
"""One node, one message, two severities — what a local shape restating a core rule at a
different severity produces (spec 6.1.5)."""


def test_two_issues_alike_but_for_severity_keep_a_fixed_order() -> None:
    """The pair a location-and-message sort leaves tied, and a set then orders by hashing.

    Not reachable through the core shapes alone, which is exactly why it is worth pinning:
    the first ``shapes/local/`` rule that repeats a core one at a lower severity would
    otherwise reintroduce output that reorders between runs.
    """
    shapes = Graph()
    shapes.parse(data=_SEVERITY_SHAPES, format="turtle")

    issues = validate.shacl(sample(), shapes)

    assert [(issue.severity, issue.location) for issue in issues] == [
        (Severity.ERROR, str(iri("concepts/", CUSTOMER_ID))),
        (Severity.WARNING, str(iri("concepts/", CUSTOMER_ID))),
    ]


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

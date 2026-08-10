"""The internal model (spec 5.1, 5.2).

The interesting behaviour is merging, and the interesting risk is that it merges
*silently wrongly* — dropping a scheme membership, or picking one of two disagreeing
labels. Both would reach a governed file with nothing in the diff to explain them, so
each is pinned here rather than left to the graph builder to notice.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from semprini.model import (
    Attribute,
    Entity,
    InternalModel,
    Issue,
    Kind,
    MergeConflictError,
    Relationship,
    RunContext,
    Scheme,
    SchemeMember,
    SchemeType,
    SemanticObject,
    Severity,
    SourceRef,
    TaxonomyValue,
    Text,
    merge_models,
)

BASE = "https://semantics.example.com/"

CUSTOMER_UUID = "7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21"
ORDER_UUID = "0d9e4c77-6b5a-4c3d-8e2f-1a9b7c5d3e4f"


def entity(
    *, refs: dict[str, str] | None = None, label: str | Text = "Customer", **rest: object
) -> Entity:
    return Entity(source_refs=refs or {"ellie-main": CUSTOMER_UUID}, pref_label=label, **rest)  # type: ignore[arg-type]


# --- construction and immutability ----------------------------------------------------


def test_an_object_carries_its_kind_and_the_namespace_that_kind_mints_in() -> None:
    # The IRI space is partitioned by kind of thing, permanently (spec 3.1), so this
    # mapping is identity's contract as much as the model's.
    assert Entity.kind is Kind.ENTITY
    assert {kind: kind.prefix for kind in Kind} == {
        Kind.ENTITY: "c",
        Kind.ATTRIBUTE: "c",
        Kind.RELATIONSHIP: "r",
        Kind.SCHEME: "sch",
        Kind.TAXONOMY_VALUE: "v",
    }


def test_objects_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        entity().pref_label = "Client"  # type: ignore[misc]


def test_source_refs_cannot_be_mutated_through_the_dict_that_built_them() -> None:
    # Adapters run one after another over shared state; one reaching back into what
    # another returned is the bug this shape exists to make impossible (spec 5.2).
    refs = {"ellie-main": CUSTOMER_UUID}
    customer = entity(refs=refs)
    refs["ellie-main"] = "tampered"

    assert customer.source_refs == {"ellie-main": CUSTOMER_UUID}
    with pytest.raises(TypeError):
        customer.source_refs["ellie-main"] = "tampered"  # type: ignore[index]


def test_sequence_fields_become_tuples() -> None:
    customer = Entity(
        source_refs={"ellie-main": CUSTOMER_UUID},
        pref_label="Customer",
        alt_labels=["Client", "Buyer"],  # type: ignore[arg-type]
        schemes=["sales"],  # type: ignore[arg-type]
    )
    assert customer.alt_labels == (Text("Client"), Text("Buyer"))
    assert customer.schemes == ("sales",)


def test_objects_can_key_a_dict_and_go_in_a_set() -> None:
    # Identity resolution groups and looks objects up (spec 5.4); a frozen class that
    # cannot be hashed would push every such stage onto a parallel key of its own.
    customer = entity()
    assert hash(customer) == hash(entity())
    assert len({customer, entity(), entity(label="Client")}) == 2
    assert hash(InternalModel(entities=(customer,)))


def test_a_model_holds_tuples_whatever_sequence_it_was_given() -> None:
    # An adapter handing over a list would otherwise leave the model holding something
    # it can still mutate, and two models built from the same objects would compare
    # unequal for holding a list against a tuple.
    from_list = InternalModel(entities=[entity()])  # type: ignore[arg-type]
    assert from_list.entities == (entity(),)
    assert from_list == InternalModel(entities=(entity(),))


def test_every_object_can_be_walked_more_than_once() -> None:
    model = InternalModel(entities=(entity(),))
    assert list(model.objects) == list(model.objects) == [entity()]


def test_an_empty_definition_is_the_same_state_as_no_definition() -> None:
    # Neither emits a skos:definition triple (spec 5.3), so they are one state from
    # construction rather than two that every later comparison has to know are equal.
    assert entity(definition="").definition is None
    assert entity(definition="") == entity()


def test_an_object_without_a_source_ref_is_refused() -> None:
    # It could not be looked up, minted or deprecated: invisible to every later stage.
    with pytest.raises(ValueError, match="at least one source ref"):
        Entity(source_refs={}, pref_label="Customer")


def test_an_object_without_a_label_is_refused() -> None:
    with pytest.raises(ValueError, match="prefLabel"):
        Entity(source_refs={"ellie-main": CUSTOMER_UUID}, pref_label="")


# --- source refs ----------------------------------------------------------------------


def test_a_source_ref_writes_itself_the_way_sourceref_carries_it() -> None:
    # sem:sourceRef is "<source-name>:<source-key>" (spec 3.3), and the ID map is keyed
    # by the same pair (spec 5.4) — one string form keeps them from drifting apart.
    assert str(SourceRef("ellie-main", CUSTOMER_UUID)) == f"ellie-main:{CUSTOMER_UUID}"


def test_a_source_name_with_a_colon_is_refused() -> None:
    with pytest.raises(ValueError, match="may not contain ':'"):
        SourceRef("ellie:main", CUSTOMER_UUID)


@pytest.mark.parametrize(("source", "key"), [("", "x"), ("ellie", "")])
def test_an_incomplete_source_ref_is_refused(source: str, key: str) -> None:
    with pytest.raises(ValueError, match="source name and a key"):
        SourceRef(source, key)


def test_an_unusable_source_ref_is_refused_where_the_adapter_built_it() -> None:
    # Not several stages later: by then the message can name the offending pair but not
    # the object that carries it, and the adapter that produced it is long gone.
    with pytest.raises(ValueError, match="may not contain ':'"):
        entity(refs={"ellie:main": CUSTOMER_UUID})


# --- merging --------------------------------------------------------------------------


def test_two_sources_describing_one_object_merge_to_one_identity() -> None:
    from_ellie = entity(refs={"ellie-main": CUSTOMER_UUID}, schemes=("sales",))
    from_collibra = entity(
        refs={"ellie-main": CUSTOMER_UUID, "collibra": "BC-12"},
        schemes=("finance",),
        alt_labels=("Client",),
    )

    merged = merge_models(
        InternalModel(entities=(from_ellie,)), InternalModel(entities=(from_collibra,))
    )

    assert len(merged.entities) == 1
    customer = merged.entities[0]
    assert dict(customer.source_refs) == {"ellie-main": CUSTOMER_UUID, "collibra": "BC-12"}
    # Both memberships survive: an object in two schemes is the ordinary case, not a
    # conflict (spec 5.3).
    assert customer.schemes == ("finance", "sales")
    assert customer.alt_labels == (Text("Client"),)


def test_identity_is_followed_transitively() -> None:
    # A third object can be what reveals two earlier ones were always the same thing.
    first = entity(refs={"ellie-main": CUSTOMER_UUID})
    second = entity(refs={"collibra": "BC-12"})
    bridge = entity(refs={"ellie-main": CUSTOMER_UUID, "collibra": "BC-12"})

    merged = merge_models(InternalModel(entities=(first, second, bridge)))

    assert len(merged.entities) == 1
    assert dict(merged.entities[0].source_refs) == {
        "ellie-main": CUSTOMER_UUID,
        "collibra": "BC-12",
    }


def test_merging_is_independent_of_the_order_the_objects_arrive_in() -> None:
    # Everything downstream inherits this: a model whose order depended on fetch order
    # would produce a different file each run (spec 5.5).
    # Order comes last so that reversing puts a different group first — with the two
    # Customer objects at both ends, grouping order is symmetric and the sort below is
    # never actually exercised.
    objects = (
        entity(refs={"ellie-main": CUSTOMER_UUID}, schemes=("sales",)),
        entity(refs={"ellie-main": CUSTOMER_UUID, "collibra": "BC-12"}, schemes=("finance",)),
        entity(refs={"ellie-main": ORDER_UUID}, label="Order"),
    )
    forwards = merge_models(InternalModel(entities=objects))
    backwards = merge_models(InternalModel(entities=tuple(reversed(objects))))

    assert forwards == backwards
    # Ordered by lowest source ref, so the merged Customer leads on "collibra:BC-12".
    # Which key orders them is arbitrary; that it is a property of the objects rather
    # than of the fetch is not.
    assert [str(e.pref_label) for e in forwards.entities] == ["Customer", "Order"]
    assert [e.sort_key for e in forwards.entities] == sorted(e.sort_key for e in forwards.entities)


def test_one_source_knowing_something_the_other_does_not_is_not_a_conflict() -> None:
    bare = entity(refs={"ellie-main": CUSTOMER_UUID})
    described = entity(refs={"ellie-main": CUSTOMER_UUID}, definition="A buyer.")

    merged = merge_models(InternalModel(entities=(bare, described)))

    assert merged.entities[0].definition == Text("A buyer.")


def test_an_empty_value_is_not_known_rather_than_a_rival_answer() -> None:
    # An empty description emits no skos:definition triple either way (spec 5.3), so a
    # tool that returns "" for a blank field must not fail every run against a tool that
    # fills the same field in.
    blank = entity(refs={"ellie-main": CUSTOMER_UUID}, definition="")
    described = entity(refs={"ellie-main": CUSTOMER_UUID}, definition="A buyer.")

    assert merge_models(InternalModel(entities=(blank, described))).entities[0].definition == Text(
        "A buyer."
    )
    # And with neither saying anything, the two ways of saying nothing collapse onto one,
    # so that the merged model does not depend on which source was fetched first.
    unknown = entity(refs={"ellie-main": CUSTOMER_UUID})
    assert merge_models(InternalModel(entities=(blank, unknown))) == merge_models(
        InternalModel(entities=(unknown, blank))
    )


def test_two_sources_disagreeing_about_a_label_raise_rather_than_one_winning() -> None:
    # Picking a side would put a statement no source made into a governed file, and the
    # diff would show a change nobody can trace. Which side wins is a steward's call.
    ellie = entity(refs={"ellie-main": CUSTOMER_UUID}, label="Customer")
    collibra = entity(refs={"ellie-main": CUSTOMER_UUID}, label="Client")

    with pytest.raises(MergeConflictError, match="pref_label"):
        merge_models(InternalModel(entities=(ellie, collibra)))


def test_one_source_giving_an_object_two_keys_raises() -> None:
    first = entity(refs={"ellie-main": CUSTOMER_UUID, "collibra": "BC-12"})
    second = entity(refs={"ellie-main": ORDER_UUID, "collibra": "BC-12"})

    with pytest.raises(MergeConflictError, match="two keys"):
        merge_models(InternalModel(entities=(first, second)))


def test_one_source_ref_may_not_name_objects_of_two_kinds() -> None:
    # The ID map is keyed by (source_name, source_key) alone — kind is a recorded column,
    # not part of the key (spec 5.4) — so this would be one row and one IRI for two
    # different things.
    model = InternalModel(
        entities=(entity(refs={"excel": "product-category"}),),
        schemes=(
            Scheme(
                source_refs={"excel": "product-category"},
                pref_label="Product category taxonomy",
                slug="product-category",
                scheme_type=SchemeType.TAXONOMY,
            ),
        ),
    )
    with pytest.raises(MergeConflictError, match="keyed by source and key alone"):
        merge_models(model)


def test_merging_disjoint_models_keeps_every_kind() -> None:
    glossary = InternalModel(
        entities=(entity(),),
        attributes=(
            Attribute(
                source_refs={"ellie-main": "a-1"},
                pref_label="Customer number",
                entity=SourceRef("ellie-main", CUSTOMER_UUID),
            ),
        ),
        relationships=(
            Relationship(
                source_refs={"ellie-main": "rel-1"},
                pref_label="places",
                source=SourceRef("ellie-main", CUSTOMER_UUID),
                target=SourceRef("ellie-main", ORDER_UUID),
            ),
        ),
        schemes=(
            Scheme(
                source_refs={"ellie-main": "sales"},
                pref_label="Sales glossary",
                slug="sales",
                scheme_type=SchemeType.GLOSSARY,
            ),
        ),
    )
    taxonomy = InternalModel(
        taxonomy_values=(
            TaxonomyValue(
                source_refs={"taxonomies": "PT-DR"},
                pref_label="Drills",
                code="PT-DR",
                parent=SourceRef("taxonomies", "PT"),
                schemes=("product-category",),
            ),
        )
    )

    merged = glossary.merge(taxonomy)

    assert len(merged) == 5
    assert [object_.kind for object_ in merged.objects] == [
        Kind.ENTITY,
        Kind.ATTRIBUTE,
        Kind.RELATIONSHIP,
        Kind.SCHEME,
        Kind.TAXONOMY_VALUE,
    ]


def test_an_adapter_reporting_one_object_twice_is_normal() -> None:
    # The same entity in two domain models, which Ellie's cross-model reuse produces on
    # purpose (spec 5.3).
    twice = InternalModel(
        entities=(
            entity(schemes=("sales",)),
            entity(schemes=("finance",)),
        )
    )
    assert twice.normalized().entities[0].schemes == ("finance", "sales")


def test_merging_nothing_is_an_empty_model() -> None:
    assert len(merge_models()) == 0


# --- run context ----------------------------------------------------------------------


def test_the_run_context_exposes_the_instance_prefix_block() -> None:
    context = RunContext(base_iri=BASE, instance_id="acme", repo_root=Path("."))
    assert context.namespaces["c"] == f"{BASE}concepts/"
    assert context.iri(Kind.TAXONOMY_VALUE, "9c1f") == f"{BASE}values/9c1f"


def test_the_run_context_is_frozen() -> None:
    context = RunContext(base_iri=BASE, instance_id="acme")
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.base_iri = "https://elsewhere.example.com/"  # type: ignore[misc]


def test_an_unusable_base_iri_fails_at_the_start_of_a_run() -> None:
    # Rather than when the first file is written, an hour of fetching later.
    with pytest.raises(ValueError, match="base IRI"):
        RunContext(base_iri="https://semantics.example.com", instance_id="acme")


@pytest.mark.parametrize("tag", ["", "e", "en_GB", "english-"])
def test_an_unusable_language_tag_is_refused(tag: str) -> None:
    with pytest.raises(ValueError, match="language tag"):
        RunContext(base_iri=BASE, instance_id="acme", default_language=tag)


@pytest.mark.parametrize("tag", ["en", "fi", "en-GB", "sv-FI"])
def test_ordinary_language_tags_are_accepted(tag: str) -> None:
    assert RunContext(base_iri=BASE, instance_id="acme", default_language=tag)


def test_the_run_context_does_not_hand_adapters_an_identity_registry() -> None:
    # Identity resolution is the core's job; an adapter that could mint would break the
    # guarantee that the ID map is authoritative (spec 5.2, 5.4).
    names = {f.name for f in dataclasses.fields(RunContext)}
    assert not names & {"id_map", "identity", "mappings"}


# --- issues ---------------------------------------------------------------------------


def test_an_issue_names_where_the_problem_is() -> None:
    issue = Issue(Severity.ERROR, "unknown adapter 'ellie2'", "sources[0].adapter")
    assert str(issue) == "error: unknown adapter 'ellie2' (sources[0].adapter)"
    assert str(Issue(Severity.WARNING, "no definition")) == "warning: no definition"


# --- text and language ----------------------------------------------------------------


def test_a_plain_string_becomes_a_text_that_states_no_language() -> None:
    # None means "the source did not say", not "no language": the instance's default is
    # applied when the graph is built, which is the only place that knows it (spec 5.5
    # rule 6).
    customer = entity()
    assert customer.pref_label == Text("Customer")
    assert customer.pref_label.language is None


def test_a_label_that_arrives_tagged_keeps_its_language() -> None:
    # Spec 11 #5: the instance default applies only where a source stated nothing.
    customer = entity(label=Text("Asiakas", "fi"))
    assert customer.pref_label == Text("Asiakas", "fi")


def test_two_texts_are_equal_only_when_their_languages_agree() -> None:
    assert Text("Customer", "en") != Text("Customer", "fi")
    assert Text("Customer", "en") != Text("Customer")
    assert Text("Customer", "en") == Text("Customer", "en")


def test_text_refuses_a_language_that_is_not_a_tag() -> None:
    with pytest.raises(ValueError, match="not a language tag"):
        Text("Customer", "not a tag")


def test_an_empty_text_cannot_be_built() -> None:
    # An empty definition emits no triple (spec 5.3); a Text rendering as "" would emit
    # one, which is why absent and empty are made one state before they get here.
    with pytest.raises(ValueError, match="must not be empty"):
        Text("")


def test_empty_members_are_dropped_from_set_valued_text_fields() -> None:
    # A spreadsheet cell that is blank is not a synonym.
    assert entity(alt_labels=["Client", "", "Buyer"]).alt_labels == (Text("Client"), Text("Buyer"))


def test_the_same_text_in_two_languages_is_a_conflict_not_a_silent_choice() -> None:
    # Which of two labels wins would otherwise depend on the order the sources were
    # configured in, and the diff would show a language nobody chose (spec 5.2).
    english = entity(label=Text("Customer", "en"))
    finnish = entity(label=Text("Customer", "fi"))
    with pytest.raises(MergeConflictError, match="pref_label"):
        merge_models(InternalModel(entities=(english, finnish)))


def test_texts_of_mixed_taggedness_can_be_unioned() -> None:
    # Sorting Text against Text by field order would compare None with str and raise,
    # which unioning two set-valued fields does routinely.
    left = entity(alt_labels=[Text("Client", "en")])
    right = entity(alt_labels=[Text("Buyer")])
    merged = merge_models(InternalModel(entities=(left, right))).entities[0]
    assert merged.alt_labels == (Text("Buyer"), Text("Client", "en"))


# --- the reused SKOS fields -----------------------------------------------------------


def test_the_three_reused_skos_fields_are_set_valued_and_union_on_merge() -> None:
    # Two sources each contributing an example are not in disagreement (spec 3.3), so
    # these union rather than having to agree the way a definition does.
    left = entity(hidden_labels=["Custmer"], scope_notes=["Excludes prospects."], examples=["Acme"])
    right = entity(
        hidden_labels=["Cstomer"], scope_notes=["Includes churned."], examples=["Globex"]
    )
    merged = merge_models(InternalModel(entities=(left, right))).entities[0]

    assert merged.hidden_labels == (Text("Cstomer"), Text("Custmer"))
    assert merged.scope_notes == (Text("Excludes prospects."), Text("Includes churned."))
    assert merged.examples == (Text("Acme"), Text("Globex"))


def test_scheme_members_union_every_set_valued_field_the_base_class_has() -> None:
    # SchemeMember adds `schemes` to the list. Re-spelling the inherited names instead of
    # deriving them would make a field added to the base class and forgotten here into a
    # scalar that two sources have to agree on — losing data silently, which is exactly
    # what UNION_FIELDS exists to prevent.
    assert set(SemanticObject.UNION_FIELDS) <= set(SchemeMember.UNION_FIELDS)
    assert "schemes" in SchemeMember.UNION_FIELDS


def test_a_taxonomy_value_needs_no_code() -> None:
    # A ragged workbook states hierarchy and labels and no notation at all (spec 5.3);
    # inventing one from the row's identity key would emit a code no source said.
    value = TaxonomyValue(source_refs={"product-category": "Laptops"}, pref_label="Laptops")
    assert value.code is None
    assert (
        TaxonomyValue(
            source_refs={"product-category": "Laptops"}, pref_label="Laptops", code=""
        ).code
        is None
    )

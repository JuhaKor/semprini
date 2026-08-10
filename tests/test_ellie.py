"""The bundled Ellie adapter (spec 5.3).

Three groups, answering different questions.

*The fixture instance* now has two sources, and their objects meet: the taxonomy's
``sem:enumerates`` points at an entity the Ellie source defines, which is the first
cross-source reference the plane has compiled end to end. Everything the Excel tests
assert about recompiling byte-for-byte holds over the pair.

*The mapping* tests pin decisions rather than transcriptions — inheritance becoming
``skos:broader``, the choice of a relationship's preferred label, which Ellie fields are
carried and which are deliberately not. Each of those would be silently re-decided by
whoever touched this next, and a different decision is a different graph in every instance
that has already committed one.

*The refusals* are the point of the rest. An export is machine-written, so its failures
are not typos: a file copied over the wrong path, a model that lost its entities in a bad
export, an allowlist naming a model nobody exported. Every one of those reads as an
ordinary compile if the adapter is lenient — a scheme quietly changing what it holds,
which spec 5.4 then deprecates everything for.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from tools.build_fixture_instance import INSTANCE, TODAY, compile_instance

from semprini import build, config
from semprini.adapters.base import SourceUnreachableError
from semprini.adapters.ellie import EllieAdapter, EllieContentError
from semprini.config import ConfigError
from semprini.identity import IdMap, Registry
from semprini.model import (
    Entity,
    InternalModel,
    MergeConflictError,
    RunContext,
    Scheme,
    SchemeType,
    SourceRef,
    Text,
    merge_models,
)
from semprini.testing import check_contract

CONTEXT = RunContext(base_iri="https://semantics.example.com/", instance_id="acme")

SOURCE = "ellie-main"
BASE_URL = "https://acme.ellie.ai/api/v1"

# The Product category entity of the fixture export, which the fixture taxonomy enumerates.
PRODUCT_CATEGORY = "8f4b1bf5-8ec7-465b-8e0f-c221d260a34c"
CUSTOMER = "350b0f84-aa23-11ee-8161-0242ac1e0003"
ACTIVE_CUSTOMER = "36627181-eb35-495a-83ca-38b0d1cdbd37"


def entity(key: str, name: str, **fields: Any) -> dict[str, Any]:
    return {"id": key, "name": name, **fields}


def relationship(key: str, source: str, target: str, **fields: Any) -> dict[str, Any]:
    """An ordinary association, with the reading verb in each direction."""
    labels = fields.pop("labels", [{"name": "has", "direction": "target"}])
    start = fields.pop("startType", "one")
    end = fields.pop("endType", "one")
    return {
        "id": key,
        "sourceEntity": {"id": source, "startType": start},
        "targetEntity": {"id": target, "endType": end},
        "labels": labels,
        **fields,
    }


def inheritance(key: str, supertype: str, subtype: str) -> dict[str, Any]:
    """How Ellie draws a specialization: an unnamed, unlabelled relationship."""
    return {
        "id": key,
        "name": None,
        "sourceEntity": {"id": supertype, "startType": "superType"},
        "targetEntity": {"id": subtype, "endType": "subType"},
        "labels": [],
    }


def export(
    path: Path,
    *,
    model_id: int | str = 1234,
    name: str = "Sales domain model",
    wrapped: bool = True,
    **fields: Any,
) -> Path:
    """One exported model, written where the adapter will look for it."""
    document: dict[str, Any] = {"modelId": model_id, "name": name, **fields}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"model": document} if wrapped else document),
        encoding="utf-8",
        newline="\n",
    )
    return path


def adapter(root: Path, *models: dict[str, Any], **settings: Any) -> EllieAdapter:
    settings.setdefault("base_url", BASE_URL)
    settings.setdefault("models", list(models))
    ctx = RunContext(base_iri=CONTEXT.base_iri, instance_id="acme", repo_root=root)
    return EllieAdapter(SOURCE, settings, ctx)


def fetch(root: Path, *models: dict[str, Any], **settings: Any) -> InternalModel:
    return adapter(root, *models, **settings).fetch()


def one_model(root: Path, path: Path, model_id: int | str = 1234, slug: str = "sales") -> Any:
    return {"id": model_id, "path": path.name, "scheme_slug": slug}


def named(model: InternalModel, label: str) -> Any:
    (found,) = [item for item in model.objects if str(item.pref_label) == label]
    return found


# ------------------------------------------------------------------ the fixture instance


def test_the_fixture_instance_compiles_both_sources(tmp_path: Path) -> None:
    """Two sources, one instance, recompiled to exactly what is committed.

    The Excel task proved this for one source. What is new here is that the two sources'
    objects reference each other, so the ID map has to answer questions asked by a source
    that did not mint the row.
    """
    root = tmp_path / "acme"
    shutil.copytree(INSTANCE, root)

    compile_instance(root)

    for committed in sorted((INSTANCE / "generated").iterdir()):
        assert (root / "generated" / committed.name).read_bytes() == committed.read_bytes(), (
            f"{committed.name} changed; regenerate with tools/build_fixture_instance.py"
        )
    assert (root / "mappings/id-map.csv").read_bytes() == (
        INSTANCE / "mappings/id-map.csv"
    ).read_bytes()


def test_the_taxonomy_enumerates_an_entity_the_other_source_defines() -> None:
    """The first cross-source reference the plane has compiled (spec 3.3).

    The workbook states a UUID from the modelling tool; the ID map turns it into the IRI
    the Ellie source minted for that entity. Neither adapter ever saw an IRI.
    """
    taxonomy = (INSTANCE / "generated/taxonomy-product-category.ttl").read_text(encoding="utf-8")
    concepts = (INSTANCE / "generated/concepts-storefront.ttl").read_text(encoding="utf-8")

    assert f"sem:enumerates c:{PRODUCT_CATEGORY}" in taxonomy
    # The same IRI is where the entity itself is defined, in the *other* source's file.
    assert f"c:{PRODUCT_CATEGORY} a sem:Entity" in concepts


def test_the_fixture_report_warns_about_two_objects_sharing_a_name() -> None:
    """Two UUIDs with one name stay two nodes, and the report says so (spec 5.3).

    The export has a ``Product ID`` on both Product and Order line. Merging them would be
    the compiler deciding a stewardship question; saying nothing would leave a reviewer to
    notice it unaided.
    """
    report = (INSTANCE / "generated/.report.md").read_text(encoding="utf-8")

    assert "Same name, different IRI" in report
    assert "**Product ID** (sem:Attribute)" in report


def test_the_fixture_instance_is_read_from_the_wrapped_shape() -> None:
    """The committed export wraps its model, so the unwrapped case below is not the only
    one exercised end to end."""
    document = json.loads((INSTANCE / "sources/ellie/storefront.json").read_text(encoding="utf-8"))

    assert set(document) == {"model"}


def test_the_bundled_adapter_meets_the_contract(tmp_path: Path) -> None:
    """The call a third-party author would write (spec 5.2).

    It fetches twice, so anything order- or state-dependent in the reader shows up here
    rather than in an instance.
    """
    path = export(tmp_path / "sales.json", entities=[entity("e1", "Customer")])

    check_contract(
        EllieAdapter,
        settings={"base_url": BASE_URL, "models": [one_model(tmp_path, path)]},
        unreachable={
            "base_url": BASE_URL,
            "models": [{"id": 1234, "path": "not-there.json", "scheme_slug": "sales"}],
        },
        context=RunContext(base_iri=CONTEXT.base_iri, instance_id="contract", repo_root=tmp_path),
        source_name=SOURCE,
    )


# ------------------------------------------------------------------ the two file shapes


def test_a_wrapped_export_is_read(tmp_path: Path) -> None:
    path = export(tmp_path / "m.json", entities=[entity("e1", "Customer")], wrapped=True)

    model = fetch(tmp_path, one_model(tmp_path, path))

    assert [str(item.pref_label) for item in model.entities] == ["Customer"]


def test_an_unwrapped_export_is_read(tmp_path: Path) -> None:
    """Some exports arrive without the outer ``model`` object, and mean the same thing."""
    path = export(tmp_path / "m.json", entities=[entity("e1", "Customer")], wrapped=False)

    model = fetch(tmp_path, one_model(tmp_path, path))

    assert [str(item.pref_label) for item in model.entities] == ["Customer"]


def test_the_two_shapes_produce_the_same_model(tmp_path: Path) -> None:
    """Unwrapping must be the *only* difference, or the same model would compile to two
    different graphs depending on how it was exported."""
    entities = [entity("e1", "Customer", metadata={"Description": "Someone who buys."})]
    wrapped = export(tmp_path / "a.json", entities=entities, wrapped=True)
    bare = export(tmp_path / "b.json", entities=entities, wrapped=False)

    first = fetch(tmp_path, one_model(tmp_path, wrapped))
    second = fetch(tmp_path, one_model(tmp_path, bare))

    assert first == second


def test_a_document_that_is_neither_shape_is_refused(tmp_path: Path) -> None:
    """Refused by name rather than read as a model with nothing in it.

    An export the adapter cannot recognize would otherwise compile to an empty scheme,
    and an empty scheme deprecates everything the model used to hold (spec 5.4).
    """
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"data": {"id": 1}, "meta": {}}), encoding="utf-8")

    with pytest.raises(EllieContentError) as raised:
        fetch(tmp_path, one_model(tmp_path, path))

    assert "data, meta" in str(raised.value)


def test_a_json_document_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(EllieContentError, match="not an object"):
        fetch(tmp_path, one_model(tmp_path, path))


def test_a_file_that_is_not_json_is_a_compile_failure(tmp_path: Path) -> None:
    """Exit 1, not 3: the file was read perfectly and its content is wrong (spec 5.1)."""
    path = tmp_path / "m.json"
    path.write_text("not json at all", encoding="utf-8")

    with pytest.raises(EllieContentError, match="not readable JSON"):
        fetch(tmp_path, one_model(tmp_path, path))


# ------------------------------------------------------------------ the allowlist


def test_a_listed_model_that_is_missing_fails_the_run(tmp_path: Path) -> None:
    """Exit 3, and it must not be skipped (spec 5.3).

    A model that silently went missing looks exactly like a model whose contents were all
    deleted, and the compiler would deprecate every object in it.
    """
    with pytest.raises(SourceUnreachableError) as raised:
        fetch(tmp_path, {"id": 1234, "path": "gone.json", "scheme_slug": "sales"})

    assert "1234" in str(raised.value)


def test_an_export_of_a_different_model_is_refused(tmp_path: Path) -> None:
    """The allowlist is keyed by Ellie's model id, so the file must be the model it names.

    An export copied over the wrong path otherwise replaces a scheme's entire contents and
    the run reports it as ordinary change.
    """
    path = export(tmp_path / "m.json", model_id=999, entities=[entity("e1", "Customer")])

    with pytest.raises(EllieContentError) as raised:
        fetch(tmp_path, one_model(tmp_path, path, model_id=1234))

    message = str(raised.value)
    assert "999" in message
    assert "1234" in message


def test_a_model_id_matches_whether_it_is_written_as_text_or_a_number(tmp_path: Path) -> None:
    """It is the scheme's source key and the ID map's columns are text (spec 5.4), so a
    quoted id in either file must not mint a second scheme."""
    path = export(tmp_path / "m.json", model_id="1234", entities=[entity("e1", "Customer")])

    model = fetch(tmp_path, one_model(tmp_path, path, model_id=1234))

    assert model.schemes[0].source_refs[SOURCE] == "1234"


def test_the_scheme_is_keyed_by_the_model_id_not_by_its_slug(tmp_path: Path) -> None:
    """Renaming a model in Ellie then costs no identity, and neither does re-slugging it
    here: the source's key is Ellie's, the slug is this instance's (spec 5.4)."""
    path = export(tmp_path / "m.json", entities=[entity("e1", "Customer")])

    (scheme,) = fetch(tmp_path, one_model(tmp_path, path)).schemes

    assert scheme.source_refs[SOURCE] == "1234"
    assert scheme.slug == "sales"
    assert str(scheme.scheme_type) == "glossary"


def test_nothing_outside_the_allowlist_is_read(tmp_path: Path) -> None:
    listed = export(tmp_path / "listed.json", entities=[entity("e1", "Listed")])
    export(tmp_path / "unlisted.json", model_id=999, entities=[entity("e2", "Unlisted")])

    model = fetch(tmp_path, one_model(tmp_path, listed))

    assert [str(item.pref_label) for item in model.entities] == ["Listed"]


# ------------------------------------------------------------------ cross-model reuse


def test_an_entity_in_two_models_is_one_node_in_two_schemes(tmp_path: Path) -> None:
    """Ellie's cross-model reuse, which is the whole reason one instance is one source.

    UUIDs are unique across the instance, so the same entity in two models is the same
    object — and gets one identity with two ``skos:inScheme`` triples (spec 5.3).
    """
    shared = entity("e1", "Customer", metadata={"Description": "Someone who buys."})
    sales = export(tmp_path / "sales.json", model_id=1, entities=[shared])
    finance = export(tmp_path / "finance.json", model_id=2, entities=[shared])

    model = fetch(
        tmp_path,
        one_model(tmp_path, sales, model_id=1, slug="sales"),
        one_model(tmp_path, finance, model_id=2, slug="finance"),
    )

    (customer,) = model.entities
    assert sorted(customer.schemes) == ["finance", "sales"]
    assert customer.source_refs[SOURCE] == "e1"


def test_the_order_models_are_listed_in_does_not_matter(tmp_path: Path) -> None:
    shared = entity("e1", "Customer")
    sales = export(tmp_path / "sales.json", model_id=1, entities=[shared])
    finance = export(tmp_path / "finance.json", model_id=2, entities=[shared])
    first = one_model(tmp_path, sales, model_id=1, slug="sales")
    second = one_model(tmp_path, finance, model_id=2, slug="finance")

    assert fetch(tmp_path, first, second) == fetch(tmp_path, second, first)


def test_two_models_describing_one_entity_differently_is_a_compile_failure(
    tmp_path: Path,
) -> None:
    """Only reachable from hand-edited exports, and reported as an issue rather than a
    traceback out of the merge (spec 5.2)."""
    sales = export(tmp_path / "sales.json", model_id=1, entities=[entity("e1", "Customer")])
    finance = export(tmp_path / "finance.json", model_id=2, entities=[entity("e1", "Client")])

    with pytest.raises(EllieContentError, match="describe one object differently"):
        fetch(
            tmp_path,
            one_model(tmp_path, sales, model_id=1, slug="sales"),
            one_model(tmp_path, finance, model_id=2, slug="finance"),
        )


def test_two_uuids_sharing_a_name_stay_two_nodes(tmp_path: Path) -> None:
    path = export(
        tmp_path / "m.json",
        entities=[entity("e1", "Customer"), entity("e2", "Customer")],
    )

    model = fetch(tmp_path, one_model(tmp_path, path))

    assert sorted(item.source_refs[SOURCE] for item in model.entities) == ["e1", "e2"]


# ------------------------------------------------------------------ inheritance


def test_a_supertype_relationship_becomes_skos_broader(tmp_path: Path) -> None:
    """The decision this task took, and the reason it is not a ``sem:Relationship``.

    Ellie gives these rows no name and no verb labels, so reifying one would mean
    inventing a preferred label no modeller wrote (spec 3.3).
    """
    path = export(
        tmp_path / "m.json",
        entities=[entity("customer", "Customer"), entity("active", "Active customer")],
        relationships=[inheritance("r1", "customer", "active")],
    )

    model = fetch(tmp_path, one_model(tmp_path, path))

    assert model.relationships == ()
    assert [str(ref) for ref in named(model, "Active customer").broader] == [f"{SOURCE}:customer"]
    assert named(model, "Customer").broader == ()


def test_inheritance_is_recognized_from_either_end(tmp_path: Path) -> None:
    path = export(
        tmp_path / "m.json",
        entities=[entity("a", "A"), entity("b", "B")],
        relationships=[
            {
                "id": "r1",
                "sourceEntity": {"id": "a", "startType": "one"},
                "targetEntity": {"id": "b", "endType": "subType"},
                "labels": [],
            }
        ],
    )

    model = fetch(tmp_path, one_model(tmp_path, path))

    assert model.relationships == ()
    assert [str(ref) for ref in named(model, "B").broader] == [f"{SOURCE}:a"]


def test_multiple_inheritance_is_carried(tmp_path: Path) -> None:
    """A scalar field would have to pick one or fail; Ellie can state both."""
    path = export(
        tmp_path / "m.json",
        entities=[entity("a", "A"), entity("b", "B"), entity("c", "C")],
        relationships=[inheritance("r1", "a", "c"), inheritance("r2", "b", "c")],
    )

    model = fetch(tmp_path, one_model(tmp_path, path))

    assert sorted(str(ref) for ref in named(model, "C").broader) == [
        f"{SOURCE}:a",
        f"{SOURCE}:b",
    ]


def test_an_entity_that_is_its_own_supertype_is_refused(tmp_path: Path) -> None:
    path = export(
        tmp_path / "m.json",
        entities=[entity("a", "A")],
        relationships=[inheritance("r1", "a", "a")],
    )

    with pytest.raises(EllieContentError, match="its own supertype"):
        fetch(tmp_path, one_model(tmp_path, path))


def test_inheritance_stated_in_one_model_and_not_another_unions(tmp_path: Path) -> None:
    """Two models that disagree only about how much they draw are not in conflict.

    A scalar ``broader`` would raise here, which would mean an entity could not appear in
    a model that happens not to draw its supertype.
    """
    entities = [entity("a", "A"), entity("c", "C")]
    drawn = export(
        tmp_path / "drawn.json",
        model_id=1,
        entities=entities,
        relationships=[inheritance("r1", "a", "c")],
    )
    plain = export(tmp_path / "plain.json", model_id=2, entities=entities)

    model = fetch(
        tmp_path,
        one_model(tmp_path, drawn, model_id=1, slug="drawn"),
        one_model(tmp_path, plain, model_id=2, slug="plain"),
    )

    assert [str(ref) for ref in named(model, "C").broader] == [f"{SOURCE}:a"]


def test_the_fixture_emits_broader_and_not_its_inverse() -> None:
    """One direction only: ``skos:narrower`` would state the same fact a second time, in
    the other entity's block (spec 5.5 rule 4)."""
    concepts = (INSTANCE / "generated/concepts-storefront.ttl").read_text(encoding="utf-8")

    # The narrower entity is the subject: "Active customer is broader-than Customer".
    assert f"c:{ACTIVE_CUSTOMER} a sem:Entity" in concepts
    assert f"skos:broader c:{CUSTOMER}" in concepts
    assert f'c:{CUSTOMER} a sem:Entity ;\n  skos:prefLabel "Customer"@en' in concepts
    assert "skos:narrower" not in concepts


def test_a_broader_reference_to_nothing_is_a_build_failure() -> None:
    """``skos:broader`` is a cross-reference like any other: resolved by the core, and a
    dangling one is a compile failure rather than a triple pointing at nothing."""
    orphan = Entity(
        source_refs={SOURCE: "a"},
        pref_label="A",
        schemes=("sales",),
        broader=(SourceRef(SOURCE, "missing"),),
    )
    scheme = _glossary()

    with pytest.raises(build.BuildError, match="no such object was compiled"):
        build.build(
            InternalModel(entities=(orphan,), schemes=(scheme,)),
            registry=Registry(IdMap(), CONTEXT.base_iri, today=TODAY),
            context=CONTEXT,
            today=TODAY,
        )


def _glossary() -> Scheme:
    return Scheme(
        source_refs={SOURCE: "1234"},
        pref_label="Sales",
        slug="sales",
        scheme_type=SchemeType.GLOSSARY,
    )


def test_an_entity_cannot_be_broader_than_itself() -> None:
    """Refused where the object is built: ``skos:broader`` onto itself is well-formed RDF
    and a permanent, meaningless cycle of one."""
    with pytest.raises(ValueError, match="broader than itself"):
        Entity(
            source_refs={SOURCE: "a"},
            pref_label="A",
            schemes=("sales",),
            broader=(SourceRef(SOURCE, "a"),),
        )


def test_broader_unions_when_two_sources_describe_one_entity() -> None:
    left = Entity(
        source_refs={SOURCE: "c"},
        pref_label="C",
        schemes=("one",),
        broader=(SourceRef(SOURCE, "a"),),
    )
    right = Entity(
        source_refs={SOURCE: "c"},
        pref_label="C",
        schemes=("two",),
        broader=(SourceRef(SOURCE, "b"),),
    )

    (merged,) = merge_models(InternalModel(entities=(left, right))).entities

    assert [str(ref) for ref in merged.broader] == [f"{SOURCE}:a", f"{SOURCE}:b"]


def test_two_sources_disagreeing_about_a_label_still_conflict() -> None:
    """The union rule is per field: making ``broader`` union does not loosen the rest."""
    with pytest.raises(MergeConflictError):
        merge_models(
            InternalModel(
                entities=(
                    Entity(source_refs={SOURCE: "c"}, pref_label="C", schemes=("one",)),
                    Entity(source_refs={SOURCE: "c"}, pref_label="See", schemes=("two",)),
                )
            )
        )


# ------------------------------------------------------------------ relationships


def test_a_relationship_takes_ellies_name_when_there_is_one(tmp_path: Path) -> None:
    """``name`` first, so that a name filled in later re-labels the node without
    re-minting it (spec 5.4)."""
    path = export(
        tmp_path / "m.json",
        entities=[entity("a", "Order"), entity("b", "Order line")],
        relationships=[
            relationship(
                "r1",
                "a",
                "b",
                name="contains",
                labels=[
                    {"name": "has one or more", "direction": "target"},
                    {"name": "is part of", "direction": "source"},
                ],
            )
        ],
    )

    (found,) = fetch(tmp_path, one_model(tmp_path, path)).relationships

    assert str(found.pref_label) == "contains"
    # Both verbs become alternatives: neither is the name, and both are how someone reads
    # this relationship aloud.
    assert sorted(str(label) for label in found.alt_labels) == ["has one or more", "is part of"]


def test_a_relationship_without_a_name_reads_from_source_to_target(tmp_path: Path) -> None:
    path = export(
        tmp_path / "m.json",
        entities=[entity("a", "Order"), entity("b", "Order line")],
        relationships=[
            relationship(
                "r1",
                "a",
                "b",
                labels=[
                    {"name": "has one or more", "direction": "target"},
                    {"name": "is part of", "direction": "source"},
                ],
            )
        ],
    )

    (found,) = fetch(tmp_path, one_model(tmp_path, path)).relationships

    assert str(found.pref_label) == "has one or more"
    assert [str(label) for label in found.alt_labels] == ["is part of"]
    assert str(found.source) == f"{SOURCE}:a"
    assert str(found.target) == f"{SOURCE}:b"


def test_the_reading_direction_decides_and_not_the_export_order(tmp_path: Path) -> None:
    """The *source*-direction verb comes first in this export, and must still lose.

    Taking whichever label happens to be listed first reads the relationship backwards —
    "Order line has one or more Order" — which is well-formed, plausible and wrong, and
    the export's ordering is not something a modeller controls.
    """
    path = export(
        tmp_path / "m.json",
        entities=[entity("a", "Order"), entity("b", "Order line")],
        relationships=[
            relationship(
                "r1",
                "a",
                "b",
                labels=[
                    {"name": "is part of", "direction": "source"},
                    {"name": "has one or more", "direction": "target"},
                ],
            )
        ],
    )

    (found,) = fetch(tmp_path, one_model(tmp_path, path)).relationships

    assert str(found.pref_label) == "has one or more"
    assert [str(label) for label in found.alt_labels] == ["is part of"]


def test_a_relationship_with_no_label_at_all_is_refused(tmp_path: Path) -> None:
    """Every node needs a preferred label, and inventing one is not the adapter's to do."""
    path = export(
        tmp_path / "m.json",
        entities=[entity("a", "A"), entity("b", "B")],
        relationships=[relationship("r1", "a", "b", labels=[])],
    )

    with pytest.raises(EllieContentError, match="no preferred label"):
        fetch(tmp_path, one_model(tmp_path, path))


def test_a_relationship_missing_an_end_is_refused(tmp_path: Path) -> None:
    path = export(
        tmp_path / "m.json",
        entities=[entity("a", "A")],
        relationships=[{"id": "r1", "sourceEntity": {"id": "a"}, "labels": []}],
    )

    with pytest.raises(EllieContentError, match="both entity ends"):
        fetch(tmp_path, one_model(tmp_path, path))


def test_a_relationship_description_becomes_its_definition(tmp_path: Path) -> None:
    path = export(
        tmp_path / "m.json",
        entities=[entity("a", "A"), entity("b", "B")],
        relationships=[relationship("r1", "a", "b", description="Why these are related.")],
    )

    (found,) = fetch(tmp_path, one_model(tmp_path, path)).relationships

    assert str(found.definition) == "Why these are related."


# ------------------------------------------------------------------ entities and fields


def test_an_entity_carries_its_description_synonyms_and_examples(tmp_path: Path) -> None:
    path = export(
        tmp_path / "m.json",
        entities=[
            entity(
                "e1",
                "Delivery",
                metadata={
                    "Description": "Goods going out.",
                    "Synonyms": "Shipment, Dispatch, Consignment",
                    "Examples": "Parcel, pallet, container",
                },
            )
        ],
    )

    (found,) = fetch(tmp_path, one_model(tmp_path, path)).entities

    assert str(found.definition) == "Goods going out."
    assert [str(label) for label in found.alt_labels] == ["Shipment", "Dispatch", "Consignment"]
    # Unsplit: the field is one prose cell, and cutting it on its commas would invent
    # three statements where the source made one.
    assert [str(item) for item in found.examples] == ["Parcel, pallet, container"]


def test_an_empty_description_emits_no_definition(tmp_path: Path) -> None:
    """Spec 5.3: an empty description states nothing, and neither does a missing one."""
    path = export(
        tmp_path / "m.json",
        entities=[
            entity("e1", "A", metadata={"Description": ""}),
            entity("e2", "B", metadata={"Description": None}),
            entity("e3", "C", metadata={}),
            entity("e4", "D"),
        ],
    )

    model = fetch(tmp_path, one_model(tmp_path, path))

    assert [item.definition for item in model.entities] == [None, None, None, None]


def test_an_attribute_becomes_a_node_pointing_at_its_entity(tmp_path: Path) -> None:
    path = export(
        tmp_path / "m.json",
        entities=[
            entity(
                "e1",
                "Customer",
                attributes=[
                    {
                        "id": "a1",
                        "name": "Customer ID",
                        "metadata": {"Description": "The identifier.", "PK": "true"},
                    }
                ],
            )
        ],
    )

    (found,) = fetch(tmp_path, one_model(tmp_path, path)).attributes

    assert str(found.pref_label) == "Customer ID"
    assert str(found.definition) == "The identifier."
    assert str(found.entity) == f"{SOURCE}:e1"


def test_the_deferred_metadata_reaches_no_statement(tmp_path: Path) -> None:
    """The fields this task deliberately does not carry (spec 5.3).

    Each would need a term the metamodel does not have, and inventing one per Ellie field
    is what the removal of ``sem:ellieId`` ruled out. A future task adding them should
    change this test on purpose.
    """
    path = export(
        tmp_path / "m.json",
        entities=[
            entity(
                "e1",
                "Customer",
                progressStatus="approved",
                type="Event",
                metadata={
                    "Source systems": "CRM",
                    "Administrated by": "Sales ops",
                },
                attributes=[
                    {
                        "id": "a1",
                        "name": "Customer ID",
                        "metadata": {"Data type": "varchar", "Semantic link": "http://x"},
                    }
                ],
            )
        ],
    )

    model = fetch(tmp_path, one_model(tmp_path, path))

    stated = " ".join(
        f"{item.pref_label} {item.definition} {item.alt_labels} {item.examples}"
        for item in model.objects
    )
    for absent in ("approved", "Event", "CRM", "Sales ops", "varchar", "http://x"):
        assert absent not in stated


def test_an_entity_without_an_id_or_a_name_is_refused(tmp_path: Path) -> None:
    path = export(
        tmp_path / "m.json",
        entities=[entity("", "Nameless"), entity("e2", "")],
    )

    with pytest.raises(EllieContentError) as raised:
        fetch(tmp_path, one_model(tmp_path, path))

    # Both, in one run: these are read in CI, where one problem per round trip costs a run.
    assert str(raised.value).count("an entity needs") == 2


def test_an_attribute_without_an_id_or_a_name_is_refused(tmp_path: Path) -> None:
    path = export(
        tmp_path / "m.json",
        entities=[entity("e1", "Customer", attributes=[{"name": "No id"}])],
    )

    with pytest.raises(EllieContentError, match="an attribute needs"):
        fetch(tmp_path, one_model(tmp_path, path))


def test_a_model_without_a_name_is_refused(tmp_path: Path) -> None:
    """The scheme's ``skos:prefLabel`` has to come from somewhere."""
    path = export(tmp_path / "m.json", name="", entities=[entity("e1", "A")])

    with pytest.raises(EllieContentError, match="has no name"):
        fetch(tmp_path, one_model(tmp_path, path))


def test_a_malformed_entities_array_is_refused_rather_than_read_as_empty(
    tmp_path: Path,
) -> None:
    """Silently reading nothing is how a whole model's objects disappear in one run."""
    path = export(tmp_path / "m.json", entities={"e1": "Customer"})

    with pytest.raises(EllieContentError, match="not a list"):
        fetch(tmp_path, one_model(tmp_path, path))


def test_a_member_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    """One malformed member, not the whole array — and it must not be quietly dropped.

    Skipping it loses exactly one entity per run, which is invisible in a report that
    counts what arrived rather than what did not.
    """
    path = export(tmp_path / "m.json", entities=[entity("e1", "Customer"), "Order"])

    with pytest.raises(EllieContentError, match="expected an object"):
        fetch(tmp_path, one_model(tmp_path, path))


def test_a_model_with_no_relationships_is_fine(tmp_path: Path) -> None:
    """A missing array is an empty one — a glossary model may genuinely have none."""
    path = export(tmp_path / "m.json", entities=[entity("e1", "Customer")])

    model = fetch(tmp_path, one_model(tmp_path, path))

    assert model.relationships == ()


def test_labels_arrive_untagged_and_take_the_instance_language(tmp_path: Path) -> None:
    """Ellie states no language, so the instance's ``default_language`` applies when the
    graph is built (spec 5.5 rule 6) — the adapter must not guess one."""
    path = export(tmp_path / "m.json", entities=[entity("e1", "Customer")])

    (found,) = fetch(tmp_path, one_model(tmp_path, path)).entities

    assert found.pref_label == Text("Customer", None)


# ------------------------------------------------------------------ configuration


def test_a_source_with_no_models_is_refused(tmp_path: Path) -> None:
    adapter_ = adapter(tmp_path, models=[])

    assert [issue.location for issue in adapter_.validate_config()] == [
        f"sources.{SOURCE}.config.models"
    ]


def test_a_source_with_no_base_url_is_refused(tmp_path: Path) -> None:
    """Absent and malformed are different mistakes, and the message has to say which.

    The operator's next action is "add the key" or "fix the value"; a message that fits
    both tells them neither.
    """
    path = export(tmp_path / "m.json")
    adapter_ = adapter(tmp_path, one_model(tmp_path, path), base_url="")

    (issue,) = adapter_.validate_config()
    assert issue.location == f"sources.{SOURCE}.config.base_url"
    assert "needs a 'base_url'" in issue.message


def test_a_base_url_that_is_not_a_url_is_refused(tmp_path: Path) -> None:
    path = export(tmp_path / "m.json")
    adapter_ = adapter(tmp_path, one_model(tmp_path, path), base_url="acme.ellie.ai")

    assert [issue.message for issue in adapter_.validate_config()] == ["not a URL: 'acme.ellie.ai'"]


def test_two_models_with_one_id_are_refused(tmp_path: Path) -> None:
    path = export(tmp_path / "m.json")
    adapter_ = adapter(
        tmp_path,
        one_model(tmp_path, path, model_id=1234, slug="a"),
        one_model(tmp_path, path, model_id=1234, slug="b"),
    )

    assert [issue.location for issue in adapter_.validate_config()] == [
        f"sources.{SOURCE}.config.models[1].id"
    ]


def test_two_models_with_one_scheme_slug_are_refused(tmp_path: Path) -> None:
    """Two models in one file: the second would overwrite the first's output, and the ID
    map would hold two source keys for one IRI."""
    path = export(tmp_path / "m.json")
    adapter_ = adapter(
        tmp_path,
        one_model(tmp_path, path, model_id=1, slug="sales"),
        one_model(tmp_path, path, model_id=2, slug="sales"),
    )

    assert [issue.location for issue in adapter_.validate_config()] == [
        f"sources.{SOURCE}.config.models[1].scheme_slug"
    ]


def test_a_scheme_slug_that_is_not_a_slug_is_refused(tmp_path: Path) -> None:
    path = export(tmp_path / "m.json")
    adapter_ = adapter(tmp_path, one_model(tmp_path, path, slug="Sales Domain"))

    assert [issue.location for issue in adapter_.validate_config()] == [
        f"sources.{SOURCE}.config.models[0].scheme_slug"
    ]


@pytest.mark.parametrize("escape", ["/etc/passwd", "C:\\keys\\ellie.json", "../../elsewhere.json"])
def test_a_path_outside_the_instance_is_refused(tmp_path: Path, escape: str) -> None:
    """Exports are committed with the instance and reviewed with it (spec 4.2)."""
    adapter_ = adapter(tmp_path, {"id": 1, "path": escape, "scheme_slug": "sales"})

    assert [issue.location for issue in adapter_.validate_config()] == [
        f"sources.{SOURCE}.config.models[0].path"
    ]


def test_an_unknown_setting_is_refused(tmp_path: Path) -> None:
    path = export(tmp_path / "m.json")
    adapter_ = adapter(tmp_path, one_model(tmp_path, path), allowlist=["everything"])

    assert [issue.message for issue in adapter_.validate_config()] == [
        "unknown setting 'allowlist'"
    ]


def test_a_token_env_says_the_api_mode_has_not_shipped(tmp_path: Path) -> None:
    """A credential configured for a mode that does not exist would silently do nothing,
    which is the worst available outcome for a key an operator went to the trouble of
    wiring into CI."""
    path = export(tmp_path / "m.json")
    adapter_ = adapter(tmp_path, one_model(tmp_path, path), token_env="ELLIE_API_TOKEN")

    (issue,) = adapter_.validate_config()
    assert "does not call the API yet" in issue.message


def test_an_unknown_model_setting_is_refused(tmp_path: Path) -> None:
    path = export(tmp_path / "m.json")
    entry = one_model(tmp_path, path)
    entry["label"] = "Sales domain model"
    adapter_ = adapter(tmp_path, entry)

    assert [issue.location for issue in adapter_.validate_config()] == [
        f"sources.{SOURCE}.config.models[0].label"
    ]


def test_fetch_validates_its_own_configuration_first(tmp_path: Path) -> None:
    """``validate_config()`` is on no compile path, so a run that skipped ``semprini
    check`` would otherwise reach the files with settings nobody validated. Exit 2."""
    with pytest.raises(ConfigError, match="base_url"):
        fetch(tmp_path, base_url="")


def test_every_configuration_problem_is_reported_at_once(tmp_path: Path) -> None:
    adapter_ = adapter(tmp_path, {"id": None, "path": "", "scheme_slug": "Nope"}, base_url="")

    assert len(adapter_.validate_config()) == 4


# ------------------------------------------------------------------ the run report


def test_the_summary_names_the_instance_the_model_and_the_counts(tmp_path: Path) -> None:
    """Spec 5.3: the report lists each model's id, its name as the source states it, and
    object counts — so a model swapped or renamed in Ellie is visible to a reviewer."""
    path = export(
        tmp_path / "m.json",
        entities=[entity("e1", "Customer", attributes=[{"id": "a1", "name": "Customer ID"}])],
    )
    adapter_ = adapter(tmp_path, one_model(tmp_path, path))
    adapter_.fetch()

    summary = adapter_.summary()

    assert BASE_URL in summary
    assert "1234 'Sales domain model'" in summary
    assert "1 entities, 1 attributes, 0 relationships" in summary


def test_an_adapter_that_has_not_fetched_reports_nothing(tmp_path: Path) -> None:
    """``semprini check`` constructs every adapter without fetching (spec 6.1)."""
    path = export(tmp_path / "m.json")

    assert adapter(tmp_path, one_model(tmp_path, path)).summary() == ""


def test_the_fixture_report_names_both_sources() -> None:
    report = (INSTANCE / "generated/.report.md").read_text(encoding="utf-8")

    assert "| ellie-main | `ellie` |" in report
    assert "| product-category | `excel-taxonomy` |" in report
    assert "Storefront Orders domain" in report


def test_the_fixture_instance_names_both_adapters() -> None:
    settings = config.load(INSTANCE)

    assert [source.adapter for source in settings.sources] == ["ellie", "excel-taxonomy"]

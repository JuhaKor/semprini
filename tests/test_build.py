"""The graph builder and file partitioning (spec 3.2, 3.3, 4.2).

Two guarantees are being pinned, and they pull in opposite directions.

*The output says exactly what the model says* — the right classes, the right properties,
the ``sem:relatesTo`` shortcut, ``sem:sourceRef`` composed from the pairs identity is
keyed by. A golden file carries that, because a per-triple assertion tends to check what
the author remembered rather than what the file contains.

*The output does not move on its own.* Recompiling unchanged input must produce identical
bytes **and** leave every ``dcterms:modified`` alone. That is the property a scheduled
compile depends on: a run that changes nothing must open no PR, and a reviewer who sees a
diff must be able to trust that something really changed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF, SKOS

from sample import (
    BASE,
    CUSTOMER,
    ELLIE,
    EXCEL,
    GOLDEN,
    LATER,
    NUMBER,
    ORDER,
    PLACES,
    SEM,
    TODAY,
    by_name,
    compile_,
    context,
    sample_model,
    union,
)
from semprini import ONTOLOGY_PATH, build
from semprini.build import BuildError, OutputFile
from semprini.identity import IdentityError, IdMap, IdMapRow, Registry
from semprini.model import (
    Attribute,
    Entity,
    InternalModel,
    Kind,
    Relationship,
    Scheme,
    SchemeType,
    SourceRef,
    TaxonomyValue,
    Text,
    merge_models,
)


def homes(files: tuple[OutputFile, ...], subject: URIRef) -> list[str]:
    """The files that *describe* ``subject``, which must always be exactly one.

    Carrying a label is the test of description: a file may mention a node — the
    ``sem:relatesTo`` shortcut does — without being where it lives.
    """
    return sorted(
        file.name
        for file in files
        if file.graph is not None and (subject, SKOS.prefLabel, None) in file.graph
    )


# ------------------------------------------------------------------------ golden output


@pytest.mark.parametrize(
    "name",
    [
        "ontology.ttl",
        "concepts-finance.ttl",
        "concepts-sales.ttl",
        "relationships-sales.ttl",
        "taxonomy-product-category.ttl",
    ],
)
def test_the_golden_files_match(name: str) -> None:
    """The file a reviewer would actually read, byte for byte.

    Regenerate deliberately, never reflexively: a change here is a change to every
    instance's committed output, and spec 5.5 makes that a major version bump with a
    migration.
    """
    produced = by_name(compile_())

    assert name in produced
    assert produced[name].text == (GOLDEN / name).read_text(encoding="utf-8")


def test_exactly_these_files_are_produced() -> None:
    """One file per scheme, plus the ontology (spec 4.2) — and nothing else.

    A scheme with no relationships produces no ``relationships-*.ttl`` at all: an empty
    file carrying only a prefix block is noise in a directory a human reviews.
    """
    assert sorted(by_name(compile_())) == [
        "concepts-finance.ttl",
        "concepts-sales.ttl",
        "ontology.ttl",
        "relationships-sales.ttl",
        "taxonomy-product-category.ttl",
    ]


def test_the_ontology_is_copied_verbatim() -> None:
    """Not re-serialized: its term comments are the vocabulary's published documentation,
    and the canonical serializer would strip them (spec 4.2, A3)."""
    produced = by_name(compile_())["ontology.ttl"]

    assert produced.text == ONTOLOGY_PATH.read_text(encoding="utf-8")
    assert produced.graph is None
    assert "rdfs:comment" in produced.text


# --------------------------------------------------------------------------- partitioning


def test_an_object_in_two_schemes_is_written_once() -> None:
    """It carries both memberships, but one changed label must be one changed line."""
    files = compile_()
    customer = URIRef(f"{BASE}concepts/{CUSTOMER}")

    assert homes(files, customer) == ["concepts-finance.ttl"]
    assert set(union(files).objects(customer, SKOS.inScheme)) == {
        URIRef(f"{BASE}schemes/finance"),
        URIRef(f"{BASE}schemes/sales"),
    }


@pytest.mark.parametrize("order", [("sales", "finance"), ("finance", "sales")])
def test_the_home_file_does_not_depend_on_the_order_schemes_arrived_in(
    order: tuple[str, str],
) -> None:
    """Sorted, not "the first one given": an adapter's iteration order must not decide
    which file an object lives in.

    Both glossaries only — the sample taxonomy ``enumerates`` an entity a cut-down model
    does not carry, and that is rightly refused.
    """
    model = InternalModel(
        schemes=sample_model().schemes[:2],
        entities=(Entity(source_refs={ELLIE: CUSTOMER}, pref_label="Customer", schemes=order),),
    )

    files = compile_(merge_models(model))

    assert homes(files, URIRef(f"{BASE}concepts/{CUSTOMER}")) == ["concepts-finance.ttl"]


def test_the_relationship_shortcut_sits_with_its_relationship() -> None:
    """``sem:relatesTo`` is derived from the relationship, so the two change together and
    a reviewer sees both halves in one hunk (spec 3.2)."""
    files = by_name(compile_())
    shortcut = (
        URIRef(f"{BASE}concepts/{CUSTOMER}"),
        URIRef(f"{SEM}relatesTo"),
        URIRef(f"{BASE}concepts/{ORDER}"),
    )

    assert files["relationships-sales.ttl"].graph is not None
    assert shortcut in files["relationships-sales.ttl"].graph
    assert files["concepts-finance.ttl"].graph is not None
    assert shortcut not in files["concepts-finance.ttl"].graph


def test_every_triple_is_written_exactly_once() -> None:
    """Partitioning must not duplicate: the union's size is the sum of the parts."""
    graphs = [file.graph for file in compile_() if file.graph is not None]

    assert len(union(compile_())) == sum(len(graph) for graph in graphs)


def two_relationships_between_one_pair() -> InternalModel:
    """Customer and Order related twice, by relationships living in different schemes."""
    return merge_models(
        InternalModel(
            schemes=sample_model().schemes[:2],
            entities=(
                Entity(
                    source_refs={ELLIE: CUSTOMER},
                    pref_label="Customer",
                    schemes=("sales", "finance"),
                ),
                Entity(
                    source_refs={ELLIE: ORDER}, pref_label="Order", schemes=("sales", "finance")
                ),
            ),
            relationships=(
                Relationship(
                    source_refs={ELLIE: PLACES},
                    pref_label="places",
                    source=SourceRef(ELLIE, CUSTOMER),
                    target=SourceRef(ELLIE, ORDER),
                    schemes=("sales",),
                ),
                Relationship(
                    source_refs={ELLIE: "aaaaaaaa-0000-4000-8000-000000000002"},
                    pref_label="bills",
                    source=SourceRef(ELLIE, CUSTOMER),
                    target=SourceRef(ELLIE, ORDER),
                    schemes=("finance",),
                ),
            ),
        )
    )


def test_one_shortcut_serves_every_relationship_between_the_same_pair() -> None:
    """``sem:relatesTo`` says only *that* two entities are related, so two relationships
    between one pair derive the same triple.

    Written once — in the lexicographically first of their files, so the choice cannot
    depend on model order — for two reasons. It is the module's own "one triple in exactly
    one place" invariant; and were it written twice, deleting one of the two relationships
    would show a removed ``sem:relatesTo`` line for a fact that still holds.
    """
    files = compile_(two_relationships_between_one_pair())
    shortcut = (
        URIRef(f"{BASE}concepts/{CUSTOMER}"),
        URIRef(f"{SEM}relatesTo"),
        URIRef(f"{BASE}concepts/{ORDER}"),
    )

    carrying = [f.name for f in files if f.graph is not None and shortcut in f.graph]

    assert carrying == ["relationships-finance.ttl"]


def test_two_relationships_between_one_pair_still_write_each_triple_once() -> None:
    graphs = [file.graph for file in compile_(two_relationships_between_one_pair())]
    present = [graph for graph in graphs if graph is not None]

    assert len(union(compile_(two_relationships_between_one_pair()))) == sum(
        len(graph) for graph in present
    )


# ------------------------------------------------------------------------- the statements


def test_the_metamodel_classes_are_emitted(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = union(compile_())
    types = {
        str(subject).replace(BASE, ""): str(object_).replace(SEM, "sem:")
        for subject, object_ in graph.subject_objects(RDF.type)
    }

    assert types[f"concepts/{CUSTOMER}"] == "sem:Entity"
    assert types["concepts/a1b2c3d4-0000-4000-8000-000000000001"] == "sem:Attribute"
    assert types[f"relationships/{PLACES}"] == "sem:Relationship"
    assert types["schemes/sales"] == str(SKOS.ConceptScheme)
    # A taxonomy value is a *plain* skos:Concept; its nature comes from the scheme it is
    # in, not from a class of its own (spec 3.2).
    assert types["values/9ba03ae3-5f30-5a06-b5d0-d210799f9c1f"] == str(SKOS.Concept)


def test_source_refs_are_composed_as_the_id_map_keys_them() -> None:
    """``sem:sourceRef`` carries "<source>:<key>" — the pair identity is keyed by, so the
    RDF and the registry cannot tell different stories (spec 3.3, 5.4)."""
    graph = union(compile_())

    assert set(graph.objects(URIRef(f"{BASE}concepts/{CUSTOMER}"), URIRef(f"{SEM}sourceRef"))) == {
        Literal(f"{ELLIE}:{CUSTOMER}")
    }


def test_an_object_known_to_two_sources_carries_a_ref_each() -> None:
    shared = InternalModel(
        # A taxonomy without `enumerates`: what is under test is the source refs, and a
        # scheme pointing at an entity this cut-down model omits would be refused first.
        schemes=(
            Scheme(
                source_refs={EXCEL: "product-category.xlsx"},
                pref_label="Product category taxonomy",
                slug="product-category",
                scheme_type=SchemeType.TAXONOMY,
            ),
        ),
        taxonomy_values=(
            TaxonomyValue(
                source_refs={EXCEL: "PT", "collibra": "POWER-TOOLS"},
                pref_label="Power tools",
                code="PT",
                schemes=("product-category",),
            ),
        ),
    )
    graph = union(compile_(merge_models(shared)))
    refs = set(graph.objects(None, URIRef(f"{SEM}sourceRef")))

    assert Literal(f"{EXCEL}:PT") in refs
    assert Literal("collibra:POWER-TOOLS") in refs


def test_a_missing_definition_emits_no_triple() -> None:
    """Empty and absent are one state (spec 5.3); SHACL reports it as a warning, and an
    empty string in the file would defeat that."""
    graph = union(compile_())

    assert (URIRef(f"{BASE}concepts/{ORDER}"), SKOS.definition, None) not in graph
    assert (URIRef(f"{BASE}concepts/{CUSTOMER}"), SKOS.definition, None) in graph


def test_labels_and_definitions_carry_the_configured_language() -> None:
    """Spec 5.5 rule 6, with the instance's own default rather than a hard-coded 'en'."""
    graph = union(compile_(ctx=context(default_language="fi")))
    labels = set(graph.objects(URIRef(f"{BASE}concepts/{CUSTOMER}"), SKOS.prefLabel))

    assert labels == {Literal("Customer", lang="fi")}
    assert set(graph.objects(URIRef(f"{BASE}concepts/{CUSTOMER}"), SKOS.altLabel)) == {
        Literal("Client", lang="fi"),
        Literal("Account holder", lang="fi"),
    }


def test_a_taxonomy_carries_its_hierarchy_and_codes() -> None:
    graph = union(compile_())
    drills = URIRef(f"{BASE}values/9ba03ae3-5f30-5a06-b5d0-d210799f9c1f")
    power_tools = next(graph.subjects(SKOS.notation, Literal("PT")))

    assert (drills, SKOS.broader, power_tools) in graph
    assert (drills, SKOS.notation, Literal("PT-DR")) in graph
    # The top concept states the relation once, on itself: skos:hasTopConcept would put
    # the same fact in the scheme's block too, in another file (spec 5.5 rule 4).
    assert (power_tools, SKOS.topConceptOf, URIRef(f"{BASE}schemes/product-category")) in graph
    assert (None, SKOS.hasTopConcept, None) not in graph


def test_a_scheme_carries_its_type_and_what_it_enumerates() -> None:
    graph = union(compile_())
    taxonomy = URIRef(f"{BASE}schemes/product-category")

    assert (taxonomy, URIRef(f"{SEM}schemeType"), Literal("taxonomy")) in graph
    assert (taxonomy, URIRef(f"{SEM}enumerates"), URIRef(f"{BASE}concepts/{NUMBER}")) in graph
    assert (
        URIRef(f"{BASE}schemes/sales"),
        URIRef(f"{SEM}schemeType"),
        Literal("glossary"),
    ) in graph


def test_cross_references_resolve_to_iris() -> None:
    """An adapter points with source refs because it has no IRIs (spec 5.2)."""
    graph = union(compile_())
    relationship = URIRef(f"{BASE}relationships/{PLACES}")

    assert (relationship, URIRef(f"{SEM}source"), URIRef(f"{BASE}concepts/{CUSTOMER}")) in graph
    assert (relationship, URIRef(f"{SEM}target"), URIRef(f"{BASE}concepts/{ORDER}")) in graph
    assert (
        URIRef(f"{BASE}concepts/a1b2c3d4-0000-4000-8000-000000000001"),
        URIRef(f"{SEM}attributeOf"),
        URIRef(f"{BASE}concepts/{CUSTOMER}"),
    ) in graph


def test_everything_is_emitted_active() -> None:
    """Deprecation is evaluated against the union of all sources and belongs to lifecycle,
    not to building (spec 3.5, 5.4)."""
    graph = union(compile_())
    statuses = set(graph.objects(None, URIRef(f"{SEM}status")))

    assert statuses == {Literal("active")}
    assert len(list(graph.subjects(URIRef(f"{SEM}status"), None))) == len(sample_model())


# --------------------------------------------------------- determinism and dcterms:modified


def test_recompiling_unchanged_input_is_byte_identical(tmp_path: Path) -> None:
    """The test the whole design exists for: a scheduled run that changes nothing must
    produce no diff at all (spec 5.5, 6.1 check 7)."""
    first = compile_()
    build.write_all(first, tmp_path)

    second = compile_(previous=build.read_previous(tmp_path), today=LATER)

    assert [(file.name, file.text) for file in second] == [(file.name, file.text) for file in first]


def test_an_unchanged_node_keeps_its_modified_date(tmp_path: Path) -> None:
    """Carried forward, not refreshed — otherwise every run would rewrite every date and
    the column would mean "last compiled" rather than "last changed" (spec 3.3)."""
    build.write_all(compile_(), tmp_path)

    graph = union(compile_(previous=build.read_previous(tmp_path), today=LATER))

    assert set(graph.objects(None, DCTERMS.modified)) == {
        Literal(TODAY, datatype=URIRef("http://www.w3.org/2001/XMLSchema#date"))
    }


def test_a_changed_node_takes_the_new_date_and_its_neighbours_do_not(tmp_path: Path) -> None:
    """The point of comparing per node rather than per file."""
    build.write_all(compile_(), tmp_path)
    edited = _with_customer_label("Customer account")

    graph = union(compile_(edited, previous=build.read_previous(tmp_path), today=LATER))
    modified = {
        str(subject): str(object_) for subject, object_ in graph.subject_objects(DCTERMS.modified)
    }

    assert modified[f"{BASE}concepts/{CUSTOMER}"] == LATER.isoformat()
    assert modified[f"{BASE}concepts/{ORDER}"] == TODAY.isoformat()


def test_a_first_compile_dates_everything_today() -> None:
    graph = union(compile_())

    assert set(graph.objects(None, DCTERMS.modified)) == {
        Literal(TODAY, datatype=URIRef("http://www.w3.org/2001/XMLSchema#date"))
    }


def test_the_build_does_not_depend_on_the_order_objects_arrive_in() -> None:
    """Two adapters running in either order must produce the same bytes (spec 5.5)."""
    model = sample_model()
    shuffled = InternalModel(
        entities=tuple(reversed(model.entities)),
        attributes=model.attributes,
        relationships=model.relationships,
        schemes=tuple(reversed(model.schemes)),
        taxonomy_values=tuple(reversed(model.taxonomy_values)),
    )

    assert [(f.name, f.text) for f in compile_(merge_models(shuffled))] == [
        (f.name, f.text) for f in compile_()
    ]


def _with_customer_label(label: str) -> InternalModel:
    model = sample_model()
    return merge_models(
        InternalModel(
            schemes=model.schemes,
            attributes=model.attributes,
            relationships=model.relationships,
            taxonomy_values=model.taxonomy_values,
            entities=tuple(
                Entity(
                    source_refs=dict(entity.source_refs),
                    pref_label=label if entity.refs[0].key == CUSTOMER else entity.pref_label,
                    definition=entity.definition,
                    alt_labels=entity.alt_labels,
                    schemes=entity.schemes,
                )
                for entity in model.entities
            ),
        )
    )


# --------------------------------------------------------------------------- writing out


def test_files_are_written_under_generated(tmp_path: Path) -> None:
    written = build.write_all(compile_(), tmp_path)

    assert {path.parent.name for path in written} == {"generated"}
    assert (tmp_path / "generated" / "ontology.ttl").exists()


def test_written_files_use_lf_endings(tmp_path: Path) -> None:
    """The same trap as everywhere else: a platform default would make one graph two
    files (spec 5.5 rule 5)."""
    build.write_all(compile_(), tmp_path)

    for path in (tmp_path / "generated").glob("*.ttl"):
        assert b"\r" not in path.read_bytes(), path.name


def test_previous_state_ignores_the_ontology_copy(tmp_path: Path) -> None:
    """Its subjects are the metamodel's, identical in every deployment, and none of them
    is an instance's to date."""
    build.write_all(compile_(), tmp_path)

    previous = build.read_previous(tmp_path)

    assert (URIRef(f"{SEM}Entity"), None, None) not in previous
    assert (URIRef(f"{BASE}concepts/{CUSTOMER}"), None, None) in previous


def test_a_missing_generated_directory_is_a_first_compile(tmp_path: Path) -> None:
    assert len(build.read_previous(tmp_path)) == 0


# ------------------------------------------------------------------------ what is refused


def test_an_object_in_no_scheme_is_refused() -> None:
    """Every object belongs to a glossary or a taxonomy — which is also what decides the
    file it is written to (spec 4.2, 6.1.5)."""
    orphan = InternalModel(
        schemes=(sample_model().schemes[0],),
        entities=(Entity(source_refs={ELLIE: CUSTOMER}, pref_label="Customer"),),
    )

    with pytest.raises(BuildError, match="is in no scheme"):
        compile_(merge_models(orphan))


def test_an_object_in_an_undefined_scheme_is_refused() -> None:
    stray = InternalModel(
        schemes=(sample_model().schemes[0],),
        entities=(
            Entity(source_refs={ELLIE: CUSTOMER}, pref_label="Customer", schemes=("missing",)),
        ),
    )

    with pytest.raises(BuildError, match="which no source defined"):
        compile_(merge_models(stray))


def test_a_taxonomy_value_in_a_glossary_is_refused() -> None:
    """The two kinds of scheme are not interchangeable, and the file naming of spec 4.2
    depends on the distinction."""
    misplaced = InternalModel(
        schemes=(sample_model().schemes[0],),
        taxonomy_values=(
            TaxonomyValue(
                source_refs={EXCEL: "PT"}, pref_label="Power tools", code="PT", schemes=("sales",)
            ),
        ),
    )

    with pytest.raises(BuildError, match="belongs in a taxonomy"):
        compile_(merge_models(misplaced))


def test_an_entity_in_a_taxonomy_is_refused() -> None:
    misplaced = InternalModel(
        schemes=(sample_model().schemes[2],),
        entities=(
            Entity(
                source_refs={ELLIE: CUSTOMER},
                pref_label="Customer",
                schemes=("product-category",),
            ),
        ),
    )

    with pytest.raises(BuildError, match="belongs in a glossary"):
        compile_(merge_models(misplaced))


def test_a_reference_to_an_object_that_was_not_compiled_is_refused() -> None:
    """A dangling reference would otherwise reach the output as a triple pointing at
    nothing an instance has ever minted."""
    dangling = InternalModel(
        schemes=(sample_model().schemes[0],),
        entities=(
            Entity(source_refs={ELLIE: CUSTOMER}, pref_label="Customer", schemes=("sales",)),
        ),
        attributes=(
            Attribute(
                source_refs={ELLIE: "a1b2c3d4-0000-4000-8000-000000000001"},
                pref_label="Customer number",
                entity=SourceRef(ELLIE, "never-fetched"),
                schemes=("sales",),
            ),
        ),
    )

    with pytest.raises(BuildError, match="no such object was compiled"):
        compile_(merge_models(dangling))


def test_enumerating_an_unknown_iri_is_refused() -> None:
    """``enumerates`` is configured by hand (spec 5.3), so a typo must not become a triple
    pointing into empty space."""
    wrong = InternalModel(
        schemes=(
            Scheme(
                source_refs={EXCEL: "product-category.xlsx"},
                pref_label="Product category taxonomy",
                slug="product-category",
                scheme_type=SchemeType.TAXONOMY,
                enumerates=SourceRef(ELLIE, "does-not-exist"),
            ),
        ),
    )

    with pytest.raises(BuildError, match="which no run has compiled"):
        compile_(merge_models(wrong))


def test_enumerating_something_that_is_not_an_entity_is_refused() -> None:
    """``sem:enumerates`` runs scheme → entity (spec 3.3). An IRI pasted from the wrong
    file is minted and real, so only the ID map's ``kind`` column can catch it."""
    model = sample_model()
    wrong = InternalModel(
        schemes=(
            model.schemes[0],
            Scheme(
                source_refs={EXCEL: "product-category.xlsx"},
                pref_label="Product category taxonomy",
                slug="product-category",
                scheme_type=SchemeType.TAXONOMY,
                enumerates=SourceRef(ELLIE, "1234"),
            ),
        ),
    )

    with pytest.raises(BuildError, match="which is a scheme; a taxonomy provides"):
        compile_(merge_models(wrong))


def test_a_partial_run_refuses_an_object_another_source_describes() -> None:
    """Files are rewritten whole, so an object rebuilt from half its evidence would have
    the other half deleted (spec 5.4).

    The model here is the full sample compiled as a ``--source ellie-main`` run, so the
    taxonomy's objects are exactly the case: described by a source this run did not fetch.
    """
    with pytest.raises(BuildError, match="which this --source ellie-main run did not fetch"):
        compile_(ctx=context(only_source=ELLIE))


def test_a_partial_run_of_a_source_that_owns_its_objects_is_built() -> None:
    """The ordinary partial run: one source, its own objects, nothing shared.

    What makes it safe is the other half — every object outside the fetched scope arrives
    from lifecycle as a carried node (spec 3.5), which is asserted end to end in
    ``test_run.py`` rather than here.
    """
    only_ellie = merge_models(
        InternalModel(
            schemes=(
                Scheme(
                    source_refs={ELLIE: "1234"},
                    pref_label="Sales domain model",
                    slug="sales",
                    scheme_type=SchemeType.GLOSSARY,
                ),
            ),
            entities=(Entity(source_refs={ELLIE: ORDER}, pref_label="Order", schemes=("sales",)),),
        )
    )

    produced = by_name(compile_(only_ellie, ctx=context(only_source=ELLIE)))

    assert sorted(produced) == ["concepts-sales.ttl", "ontology.ttl"]


# ------------------------------------------------------- references point at real nodes


def test_a_reference_to_a_node_the_run_does_not_write_is_refused() -> None:
    """The ID map answers "was this IRI ever minted", which a row can outlive.

    An entity whose source was reconfigured away leaves its row behind; a relationship
    pointing at it would otherwise reach a governed file as a ``sem:target`` pointing at
    nothing, and no SHACL shape can see a node that is not in the graph.
    """
    model = merge_models(
        InternalModel(
            schemes=(
                Scheme(
                    source_refs={ELLIE: "1234"},
                    pref_label="Sales domain model",
                    slug="sales",
                    scheme_type=SchemeType.GLOSSARY,
                ),
            ),
            entities=(Entity(source_refs={ELLIE: ORDER}, pref_label="Order", schemes=("sales",)),),
            relationships=(
                Relationship(
                    source_refs={ELLIE: PLACES},
                    pref_label="places",
                    source=SourceRef(ELLIE, ORDER),
                    target=SourceRef(ELLIE, CUSTOMER),
                    schemes=("sales",),
                ),
            ),
        )
    )
    # Customer is in the map from an earlier run, and in no file this one writes.
    known = IdMap(
        (
            IdMapRow(
                iri=f"{BASE}concepts/{CUSTOMER}",
                kind=Kind.ENTITY,
                source_name=ELLIE,
                source_key=CUSTOMER,
                first_seen=TODAY,
            ),
        )
    )

    with pytest.raises(
        BuildError, match="nothing in this run's output describes that node"
    ) as raised:
        compile_(model, registry=Registry(known, BASE, today=TODAY))

    # Once, not twice. A relationship's ends are resolved on two paths — for the statement
    # and to key the sem:relatesTo shortcut by entity pair — and one problem reported twice
    # is one an operator reads as two, in a file read in CI (spec 5.2).
    assert len(raised.value.issues) == 1


# ------------------------------------------------------------------ the scheme slug

# A slug names two things — the local name of the scheme's IRI, and the file its members
# are written to (spec 3.4.2, 4.2). Only the first is frozen by the ID map, so identity
# validates a slug on the run that mints it and never looks again.


def escaping_scheme() -> InternalModel:
    return merge_models(
        InternalModel(
            schemes=(
                Scheme(
                    source_refs={ELLIE: "1234"},
                    pref_label="Sales domain model",
                    slug="../../pwned",
                    scheme_type=SchemeType.GLOSSARY,
                ),
            ),
        )
    )


def test_minting_refuses_a_slug_that_is_not_a_slug() -> None:
    """The first line: identity will not freeze such a slug into an IRI (spec 3.4.2)."""
    with pytest.raises(IdentityError, match="cannot become an IRI local name"):
        compile_(escaping_scheme())


def test_a_slug_that_is_not_a_slug_is_refused_even_when_the_id_map_supplies_it() -> None:
    """The second line, and the one that matters here: minting runs once per object, so an
    ID map that already holds such a row never consults the slug rules again.

    ``../../pwned`` composes ``generated/concepts-../../pwned.ttl``, which resolves
    outside the machine-owned directory entirely (spec 4.3) — so the file path is checked
    where the file name is built, not only where the IRI is minted.
    """
    planted = IdMap(
        [
            IdMapRow(
                iri=f"{BASE}schemes/../../pwned",
                kind=Kind.SCHEME,
                source_name=ELLIE,
                source_key="1234",
                first_seen=TODAY,
            )
        ]
    )

    with pytest.raises(BuildError, match="is not a slug"):
        compile_(escaping_scheme(), registry=Registry(planted, BASE, today=TODAY))


def test_renaming_a_slug_after_it_is_minted_is_refused() -> None:
    """The rename would move the scheme's *file* while its IRI stayed where it was, so
    the ID map and the output would disagree about what the scheme is called.

    Reached by editing ``scheme_slug`` in ``config/semprini.yaml`` — an ordinary edit, and
    the run that mints is the only one identity checks a slug on.
    """
    registry = Registry(IdMap(), BASE, today=TODAY)
    before = InternalModel(
        schemes=(
            Scheme(
                source_refs={ELLIE: "1234"},
                pref_label="Sales domain model",
                slug="sales",
                scheme_type=SchemeType.GLOSSARY,
            ),
        ),
    )
    compile_(merge_models(before), registry=registry)

    renamed = InternalModel(
        schemes=(
            Scheme(
                source_refs={ELLIE: "1234"},
                pref_label="Sales domain model",
                slug="revenue",
                scheme_type=SchemeType.GLOSSARY,
            ),
        ),
    )

    with pytest.raises(BuildError, match="assigned once and opaque thereafter"):
        compile_(merge_models(renamed), registry=registry)


# --------------------------------------------------------------- reporting every problem


def test_every_dangling_reference_is_reported_at_once() -> None:
    """One problem per run costs a CI round trip each (spec 5.2), so they are collected."""
    dangling = InternalModel(
        schemes=(sample_model().schemes[0],),
        entities=(
            Entity(source_refs={ELLIE: CUSTOMER}, pref_label="Customer", schemes=("sales",)),
        ),
        attributes=(
            Attribute(
                source_refs={ELLIE: "a1b2c3d4-0000-4000-8000-000000000001"},
                pref_label="Customer number",
                entity=SourceRef(ELLIE, "never-fetched"),
                schemes=("sales",),
            ),
            Attribute(
                source_refs={ELLIE: "a1b2c3d4-0000-4000-8000-000000000002"},
                pref_label="Customer name",
                entity=SourceRef(ELLIE, "also-never-fetched"),
                schemes=("sales",),
            ),
        ),
    )

    with pytest.raises(BuildError) as raised:
        compile_(merge_models(dangling))

    assert len(raised.value.issues) == 2
    assert {"never-fetched", "also-never-fetched"} == {
        issue.message.split("names ellie-main:")[1].split(" ")[0] for issue in raised.value.issues
    }


def test_scheme_and_enumerates_problems_are_reported_together() -> None:
    """Both decide whether the model is expressible at all, so both are in one batch."""
    broken = InternalModel(
        schemes=(
            Scheme(
                source_refs={EXCEL: "product-category.xlsx"},
                pref_label="Product category taxonomy",
                slug="product-category",
                scheme_type=SchemeType.TAXONOMY,
                enumerates=SourceRef(ELLIE, "does-not-exist"),
            ),
        ),
        entities=(Entity(source_refs={ELLIE: CUSTOMER}, pref_label="Customer"),),
    )

    with pytest.raises(BuildError) as raised:
        compile_(merge_models(broken))

    assert len(raised.value.issues) == 2
    assert any("is in no scheme" in issue.message for issue in raised.value.issues)
    assert any("which no run has compiled" in issue.message for issue in raised.value.issues)


def test_unreadable_generated_output_names_the_file(tmp_path: Path) -> None:
    """A hand-edited or truncated file in ``generated/`` is exactly what spec 4.3 guards
    against; it must not surface as an rdflib traceback naming nothing actionable."""
    build.write_all(compile_(), tmp_path)
    (tmp_path / "generated" / "concepts-sales.ttl").write_text("this is not turtle {", "utf-8")

    with pytest.raises(BuildError, match="cannot read generated output"):
        build.read_previous(tmp_path)


def test_the_output_parses_back_to_the_same_graph() -> None:
    """Whatever the serializer wrote, a consumer must read back unchanged."""
    files = compile_()

    for file in files:
        if file.graph is None:
            continue
        reparsed = Graph().parse(data=file.text, format="turtle")
        assert set(reparsed) == set(file.graph), file.name


def test_a_label_that_arrives_tagged_keeps_its_own_language() -> None:
    """Spec 5.5 rule 6, at the point where it becomes bytes.

    The model-level test proves the tag survives into the internal model; this is the
    half that proves the *graph builder* does not overwrite it with the instance default.
    Both halves are needed, and the instance default has to differ from the tag or the
    two branches produce the same literal and neither is under test.
    """
    tagged = Entity(
        source_refs={ELLIE: CUSTOMER},
        pref_label=Text("Asiakas", "fi"),
        definition=Text("Ostaja.", "fi"),
        alt_labels=(Text("Klientti", "fi"),),
        schemes=("sales",),
    )
    model = merge_models(
        InternalModel(
            schemes=(
                Scheme(
                    source_refs={ELLIE: "1234"},
                    pref_label="Sales domain model",
                    slug="sales",
                    scheme_type=SchemeType.GLOSSARY,
                ),
            ),
            entities=(tagged,),
        )
    )

    graph = union(compile_(model, ctx=context()))
    customer = URIRef(f"{BASE}concepts/{CUSTOMER}")

    assert context().default_language == "en"
    assert set(graph.objects(customer, SKOS.prefLabel)) == {Literal("Asiakas", lang="fi")}
    assert set(graph.objects(customer, SKOS.definition)) == {Literal("Ostaja.", lang="fi")}
    assert set(graph.objects(customer, SKOS.altLabel)) == {Literal("Klientti", lang="fi")}


def test_an_untagged_label_takes_the_instance_default() -> None:
    # The paired half: a source that states no language gets the instance's, which is the
    # only place that knows it (spec 11 #5).
    graph = union(compile_())
    customer = URIRef(f"{BASE}concepts/{CUSTOMER}")

    assert set(graph.objects(customer, SKOS.prefLabel)) == {Literal("Customer", lang="en")}

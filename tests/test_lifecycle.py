"""Deprecation, carry-forward and the merge register (spec 3.5, 5.4).

Every test here is really one question asked in a different shape: **can an object leave
an instance?** It must not be able to. A source stops mentioning something, a steward
merges two concepts, a partial run looks at one source out of three — and in each case the
node has to still be there afterwards, still answering to the IRI something published,
with a status saying what happened to it.

So the assertions are deliberately about what *survives* rather than about what the
compiler emits. A test that only checked for ``sem:status "deprecated"`` would pass just
as happily against a compiler that deprecated a node and dropped every other statement it
had.
"""

from __future__ import annotations

import datetime
from collections.abc import Collection, Sequence
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, SKOS
from rdflib.term import Node

from sample import BASE, ELLIE, EXCEL, SEM, TODAY, context, union
from semprini import build, lifecycle, report
from semprini.build import BuildError, CarriedNode, OutputFile
from semprini.identity import IdMap, Registry
from semprini.lifecycle import LifecycleError, MergeRegister, MergeRow
from semprini.model import (
    Entity,
    InternalModel,
    Kind,
    Relationship,
    RunContext,
    Scheme,
    SchemeType,
    SourceRef,
    TaxonomyValue,
    merge_models,
)

SEM_STATUS = URIRef(f"{SEM}status")
ACTIVE = Literal("active")
DEPRECATED = Literal("deprecated")

LATER = datetime.date(2027, 3, 1)
LATER_STILL = datetime.date(2027, 9, 9)

SOURCES = (ELLIE, EXCEL)

SALES = Scheme(
    source_refs={ELLIE: "1234"},
    pref_label="Sales domain model",
    slug="sales",
    scheme_type=SchemeType.GLOSSARY,
)
FINANCE = Scheme(
    source_refs={ELLIE: "1287"},
    pref_label="Finance domain model",
    slug="finance",
    scheme_type=SchemeType.GLOSSARY,
)


# ---------------------------------------------------------------------------- harness


def entity(
    key: str, label: str, *, schemes: tuple[str, ...] = ("sales",), **fields: object
) -> Entity:
    return Entity(source_refs={ELLIE: key}, pref_label=label, schemes=schemes, **fields)  # type: ignore[arg-type]


def model(*objects: object, schemes: tuple[Scheme, ...] = (SALES,)) -> InternalModel:
    """A model built from whatever a test needs, with the schemes it lives in."""
    return merge_models(
        InternalModel(
            schemes=schemes,
            entities=tuple(o for o in objects if isinstance(o, Entity)),
            relationships=tuple(o for o in objects if isinstance(o, Relationship)),
            taxonomy_values=tuple(o for o in objects if isinstance(o, TaxonomyValue)),
        )
    )


def run(
    root: Path,
    compiled: InternalModel,
    *,
    today: datetime.date = TODAY,
    sources: Collection[str] = SOURCES,
    merges: MergeRegister | None = None,
    only_source: str | None = None,
) -> tuple[tuple[OutputFile, ...], lifecycle.LifecyclePlan]:
    """One compile of ``compiled`` over whatever ``root`` already holds.

    The write order ``semprini run`` will keep (spec 5.1): read the previous state, plan
    lifecycle against it, build, write, save the ID map once. The registry is reloaded
    from the CSV each time rather than held across runs, so identity survives the file and
    not just the process.
    """
    ctx = RunContext(base_iri=BASE, instance_id="acme", repo_root=root, only_source=only_source)
    registry = Registry(IdMap.load(root), BASE, repo_root=root, today=today)

    previous_files = build.read_previous_files(root)
    previous = build.union_of(previous_files.values())
    plan = lifecycle.plan(
        compiled,
        registry=registry,
        context=ctx,
        previous=previous_files,
        sources=sources,
        merges=merges,
    )
    files = build.build(
        compiled,
        registry=registry,
        context=ctx,
        previous=previous,
        today=today,
        carried=plan.carried,
    )
    build.write_all(files, root)
    registry.save(root)
    return files, plan


def statements(files: Sequence[OutputFile], iri: str) -> set[tuple[Node, Node]]:
    """Everything the output says about one node, across every file it appears in."""
    subject = URIRef(iri)
    graph = union(tuple(files))
    return {(p, o) for s, p, o in graph if s == subject}


def iri_of(root: Path, key: str, source: str = ELLIE) -> str:
    found = IdMap.load(root).iri(SourceRef(source, key))
    assert found is not None, f"{source}:{key} has no IRI"
    return found


# ------------------------------------------------------------------------- deprecation


def test_an_object_absent_from_every_source_is_deprecated(tmp_path: Path) -> None:
    """Spec 3.5: the node is retained, its status changes, the compiler stops updating it."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Fax number")))
    gone = iri_of(tmp_path, "e2")

    files, plan = run(tmp_path, model(entity("e1", "Customer")), today=LATER)

    assert plan.deprecated == (gone,)
    assert (SEM_STATUS, DEPRECATED) in statements(files, gone)


def test_a_deprecated_object_keeps_every_statement_it_had(tmp_path: Path) -> None:
    """ "Statements preserved" is the whole rule (spec 5.4): a node that lost its label and
    its definition on the way out would be deprecated and useless at once."""
    fax = entity(
        "e2",
        "Fax number",
        definition="The number of a machine nobody has.",
        alt_labels=("Facsimile",),
        schemes=("sales", "finance"),
    )
    before = run(tmp_path, model(entity("e1", "Customer"), fax, schemes=(SALES, FINANCE)))[0]
    gone = iri_of(tmp_path, "e2")
    kept = {
        statement
        for statement in statements(before, gone)
        if statement[0] not in (SEM_STATUS, DCTERMS.modified)
    }

    after = run(tmp_path, model(entity("e1", "Customer"), schemes=(SALES, FINANCE)), today=LATER)[0]

    assert kept <= statements(after, gone)
    assert (SKOS.definition, Literal("The number of a machine nobody has.", lang="en")) in kept


def test_a_deprecated_object_stays_deprecated_and_the_output_stops_moving(
    tmp_path: Path,
) -> None:
    """Carried forward on every later run (spec 3.5), and byte-identical afterwards — a
    deprecation that re-dated itself every night would produce a diff nobody caused."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Fax number")))
    only_customer = model(entity("e1", "Customer"))

    deprecating = run(tmp_path, only_customer, today=LATER)[0]
    again, plan = run(tmp_path, only_customer, today=LATER_STILL)

    assert plan.deprecated == ()
    assert [(f.name, f.text) for f in again] == [(f.name, f.text) for f in deprecating]


def test_the_deprecation_is_dated_and_then_left_alone(tmp_path: Path) -> None:
    """The status change is a content change, so the date moves once — and then never
    again, since the node's statements stop moving (spec 3.3)."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Fax number")))
    gone = iri_of(tmp_path, "e2")
    only_customer = model(entity("e1", "Customer"))

    deprecating = run(tmp_path, only_customer, today=LATER)[0]
    later = run(tmp_path, only_customer, today=LATER_STILL)[0]

    assert (DCTERMS.modified, Literal(LATER, datatype=DCTERMS.W3CDTF)) not in statements(
        deprecating, gone
    )
    assert _modified(deprecating, gone) == LATER
    assert _modified(later, gone) == LATER


def _modified(files: Sequence[OutputFile], iri: str) -> datetime.date:
    dates = [o for p, o in statements(files, iri) if p == DCTERMS.modified]
    assert len(dates) == 1, f"{iri} should carry exactly one dcterms:modified, has {dates}"
    return datetime.date.fromisoformat(str(dates[0]))


def test_a_deprecated_node_stays_in_the_file_that_held_it(tmp_path: Path) -> None:
    """A node that moved file on deprecation would be a deletion in one hunk and an
    addition in another, with nothing tying them together for a reviewer (spec 4.2)."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Fax number")))
    gone = URIRef(iri_of(tmp_path, "e2"))

    files = run(tmp_path, model(entity("e1", "Customer")), today=LATER)[0]

    holders = {f.name for f in files if f.graph is not None and (gone, None, None) in f.graph}
    assert holders == {"concepts-sales.ttl"}


def test_an_object_that_left_one_model_but_not_another_is_not_deprecated(
    tmp_path: Path,
) -> None:
    """Spec 5.4: it loses that ``skos:inScheme`` and nothing else. Judged against the
    union of the sources, never against one model — this is the case that rule is for."""
    both = entity("e1", "Customer", schemes=("sales", "finance"))
    run(tmp_path, model(both, schemes=(SALES, FINANCE)))
    customer = iri_of(tmp_path, "e1")

    files, plan = run(
        tmp_path,
        model(entity("e1", "Customer", schemes=("finance",)), schemes=(SALES, FINANCE)),
        today=LATER,
    )

    assert plan.deprecated == ()
    said = statements(files, customer)
    assert (SEM_STATUS, ACTIVE) in said
    assert (SKOS.inScheme, URIRef(f"{BASE}schemes/finance")) in said
    assert (SKOS.inScheme, URIRef(f"{BASE}schemes/sales")) not in said


def test_a_whole_scheme_can_be_deprecated_with_everything_in_it(tmp_path: Path) -> None:
    """A scheme is deleted from a source as readily as anything else (spec 3.7), and its
    members go with it — including the ``sem:relatesTo`` shortcut written in its file."""
    run(
        tmp_path,
        model(
            entity("e1", "Customer"),
            entity("e2", "Order"),
            Relationship(
                source_refs={ELLIE: "r1"},
                pref_label="places",
                source=SourceRef(ELLIE, "e1"),
                target=SourceRef(ELLIE, "e2"),
                schemes=("sales",),
            ),
        ),
    )
    customer, order = iri_of(tmp_path, "e1"), iri_of(tmp_path, "e2")

    files, plan = run(tmp_path, InternalModel(), today=LATER)

    assert set(plan.deprecated) == {
        customer,
        order,
        iri_of(tmp_path, "r1"),
        iri_of(tmp_path, "1234"),
    }
    # The shortcut is a statement about the entity, so it is retained with it.
    assert (URIRef(f"{SEM}relatesTo"), URIRef(order)) in statements(files, customer)


def test_a_file_that_only_mentions_a_deprecated_node_says_no_more_about_it(
    tmp_path: Path,
) -> None:
    """A node is described in one file however many mention it (spec 4.2). Marking it
    deprecated wherever it appears would put one changed fact in two hunks — and the
    ``sem:relatesTo`` shortcut is exactly the case that has a second file to appear in."""
    run(
        tmp_path,
        model(
            entity("e1", "Customer"),
            entity("e2", "Order"),
            Relationship(
                source_refs={ELLIE: "r1"},
                pref_label="places",
                source=SourceRef(ELLIE, "e1"),
                target=SourceRef(ELLIE, "e2"),
                schemes=("sales",),
            ),
        ),
    )
    customer = URIRef(iri_of(tmp_path, "e1"))

    files = run(tmp_path, InternalModel(), today=LATER)[0]

    mentions = by_file(files)["relationships-sales.ttl"]
    assert {p for p, _ in mentions.predicate_objects(customer)} == {URIRef(f"{SEM}relatesTo")}


def by_file(files: Sequence[OutputFile]) -> dict[str, Graph]:
    return {file.name: file.graph for file in files if file.graph is not None}


def test_a_statement_about_a_node_nothing_describes_is_not_a_node(tmp_path: Path) -> None:
    """Only a node the output *describes* — one carrying a label — is something lifecycle
    can conclude anything about. A bare statement is not a candidate for deprecation, and
    treating it as one would demand an ID-map row for something that is not an object."""
    orphan = Graph()
    orphan.add(
        (
            URIRef(f"{BASE}concepts/a"),
            URIRef(f"{SEM}relatesTo"),
            URIRef(f"{BASE}concepts/b"),
        )
    )

    plan = lifecycle.plan(
        InternalModel(),
        registry=Registry(IdMap(), BASE, repo_root=tmp_path, today=LATER),
        context=context(),
        previous={"relationships-sales.ttl": orphan},
        sources=SOURCES,
    )

    assert plan == lifecycle.LifecyclePlan()


def test_deprecations_are_ordered_by_iri_not_by_the_file_they_were_found_in(
    tmp_path: Path,
) -> None:
    """The previous state is read file by file, and a plan ordered by that would reorder
    itself whenever a scheme was renamed — reaching the run report as a shuffled listing
    nobody caused (spec 5.5)."""
    taxonomy = Scheme(
        source_refs={EXCEL: "product-category.xlsx"},
        pref_label="Product category taxonomy",
        slug="product-category",
        scheme_type=SchemeType.TAXONOMY,
    )
    value = TaxonomyValue(
        source_refs={EXCEL: "PT"}, pref_label="Power tools", schemes=("product-category",)
    )
    run(tmp_path, model(entity("e1", "Customer"), value, schemes=(SALES, taxonomy)))

    plan = run(tmp_path, InternalModel(), today=LATER)[1]

    assert len(plan.deprecated) == 4
    assert list(plan.deprecated) == sorted(plan.deprecated)


def test_a_node_the_id_map_has_never_heard_of_is_refused(tmp_path: Path) -> None:
    """Generated output holding an unmapped IRI means a row was deleted or a file was
    hand-edited (spec 4.3). Dropping it would be the one thing this module forbids."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Fax number")))
    stripped = IdMap(row for row in IdMap.load(tmp_path) if row.source_key != "e2")
    stripped.save(tmp_path)

    with pytest.raises(LifecycleError, match="not in the ID map"):
        run(tmp_path, model(entity("e1", "Customer")), today=LATER)


# ------------------------------------------------------------------------- run scope
#
# A partial run is planned here, not built: what these pin is the rule that makes such a
# run safe at all — a run that did not look cannot conclude. `test_run.py` asserts the
# other half, that a `--source X` run therefore writes the whole directory.


def plan_only(
    root: Path,
    compiled: InternalModel,
    *,
    sources: Collection[str] = SOURCES,
    only_source: str | None = None,
) -> lifecycle.LifecyclePlan:
    return lifecycle.plan(
        compiled,
        registry=Registry(IdMap.load(root), BASE, repo_root=root, today=LATER),
        context=RunContext(
            base_iri=BASE, instance_id="acme", repo_root=root, only_source=only_source
        ),
        previous=build.read_previous_files(root),
        sources=sources,
    )


def carried(plan: lifecycle.LifecyclePlan, iri: str) -> set[tuple[URIRef, object]]:
    """Everything the plan retains about one node, across every file it is written in."""
    return {
        statement
        for node in plan.carried
        if str(node.subject) == iri
        for statement in node.statements
    }


def test_a_partial_run_does_not_deprecate_another_sources_objects(tmp_path: Path) -> None:
    """Spec 5.4: ``--source X`` skips deprecation for anything outside the fetched scope.
    The taxonomy was not fetched, so this run knows nothing about it either way."""
    taxonomy = Scheme(
        source_refs={EXCEL: "product-category.xlsx"},
        pref_label="Product category taxonomy",
        slug="product-category",
        scheme_type=SchemeType.TAXONOMY,
    )
    value = TaxonomyValue(
        source_refs={EXCEL: "PT"}, pref_label="Power tools", schemes=("product-category",)
    )
    run(tmp_path, model(entity("e1", "Customer"), value, schemes=(SALES, taxonomy)))
    power_tools = iri_of(tmp_path, "PT", EXCEL)

    plan = plan_only(tmp_path, model(entity("e1", "Customer")), only_source=ELLIE)

    assert plan.deprecated == ()
    assert (SEM_STATUS, ACTIVE) in carried(plan, power_tools)


def test_an_object_outside_the_scope_is_carried_rather_than_skipped(tmp_path: Path) -> None:
    """ "No deprecation" cannot mean "no output": each file is rewritten whole, so a node
    left out of the plan is a node deleted from the instance — the loud version of the
    thing this module exists to prevent."""
    taxonomy = Scheme(
        source_refs={EXCEL: "product-category.xlsx"},
        pref_label="Product category taxonomy",
        slug="product-category",
        scheme_type=SchemeType.TAXONOMY,
    )
    value = TaxonomyValue(
        source_refs={EXCEL: "PT"},
        pref_label="Power tools",
        definition="Tools with a motor.",
        schemes=("product-category",),
    )
    files = run(tmp_path, model(entity("e1", "Customer"), value, schemes=(SALES, taxonomy)))[0]
    power_tools = iri_of(tmp_path, "PT", EXCEL)
    said = {
        statement
        for statement in statements(files, power_tools)
        if statement[0] != DCTERMS.modified
    }

    plan = plan_only(tmp_path, model(entity("e1", "Customer")), only_source=ELLIE)

    # Verbatim: the run has no evidence about this node, so it changes nothing about it.
    assert carried(plan, power_tools) == said


def test_an_object_two_sources_share_is_out_of_scope_unless_both_were_fetched(
    tmp_path: Path,
) -> None:
    """One fetched source cannot conclude an object is gone when a second source it did
    not read also describes it — that is the ID map's whole point (spec 5.4)."""
    shared = Entity(
        source_refs={ELLIE: "e1", EXCEL: "shared"}, pref_label="Customer", schemes=("sales",)
    )
    run(tmp_path, model(shared))
    customer = iri_of(tmp_path, "e1")

    plan = plan_only(tmp_path, InternalModel(schemes=(SALES,)), only_source=ELLIE)

    assert plan.deprecated == ()
    assert (SEM_STATUS, ACTIVE) in carried(plan, customer)


def relationship(key: str, source: str, target: str, *, scheme: str = "sales") -> Relationship:
    return Relationship(
        source_refs={EXCEL: key},
        pref_label="places",
        source=SourceRef(ELLIE, source),
        target=SourceRef(ELLIE, target),
        schemes=(scheme,),
    )


def test_a_shortcut_survives_when_its_relationship_is_out_of_scope(tmp_path: Path) -> None:
    """The one statement written away from the node it is about (spec 4.2), and so the one
    neither rule reaches on its own: the entity is live and gets rebuilt from a model that
    no longer holds the relationship, while the relationship itself is carried as active.
    Dropping the shortcut would delete a governed triple on a run that concluded nothing."""
    ends = (entity("e1", "Customer"), entity("e2", "Order"))
    before = run(tmp_path, model(*ends, relationship("r1", "e1", "e2")))[0]
    customer, order = iri_of(tmp_path, "e1"), iri_of(tmp_path, "e2")
    shortcut = (URIRef(f"{SEM}relatesTo"), URIRef(order))
    assert shortcut in statements(before, customer)

    after = run(tmp_path, model(*ends), today=LATER, sources=(ELLIE,))[0]

    assert shortcut in statements(after, customer)
    # Nothing moved at all: the run had no evidence about any of it.
    assert [(f.name, f.text) for f in after] == [(f.name, f.text) for f in before]


def test_a_shortcut_goes_when_its_relationship_is_deprecated(tmp_path: Path) -> None:
    """Deliberately not retained, and the opposite of the case above. ``sem:relatesTo``
    carries no status of its own, so keeping it would assert a live relation between two
    entities on the strength of a retired one."""
    ends = (entity("e1", "Customer"), entity("e2", "Order"))
    run(tmp_path, model(*ends, relationship("r1", "e1", "e2")))
    customer, order = iri_of(tmp_path, "e1"), iri_of(tmp_path, "e2")

    after, plan = run(tmp_path, model(*ends), today=LATER)

    assert plan.deprecated == (iri_of(tmp_path, "r1", EXCEL),)
    assert (URIRef(f"{SEM}relatesTo"), URIRef(order)) not in statements(after, customer)


def test_a_shortcut_the_run_still_derives_is_not_also_carried(tmp_path: Path) -> None:
    """Two relationships between one pair derive the identical triple (spec 4.2). With one
    live and one frozen, retaining the frozen one's shortcut as well would write that
    triple into two files — the defect C1 fixed, reached from the other direction."""
    ends = (
        entity("e1", "Customer", schemes=("sales", "finance")),
        entity("e2", "Order", schemes=("sales", "finance")),
    )
    live = Relationship(
        source_refs={ELLIE: "r-live"},
        pref_label="places",
        source=SourceRef(ELLIE, "e1"),
        target=SourceRef(ELLIE, "e2"),
        schemes=("sales",),
    )
    frozen = relationship("r-frozen", "e1", "e2", scheme="finance")
    run(tmp_path, model(*ends, live, frozen, schemes=(SALES, FINANCE)))
    customer, order = iri_of(tmp_path, "e1"), iri_of(tmp_path, "e2")

    after = run(
        tmp_path, model(*ends, live, schemes=(SALES, FINANCE)), today=LATER, sources=(ELLIE,)
    )[0]

    holders = [
        name
        for name, graph in by_file(after).items()
        if (URIRef(customer), URIRef(f"{SEM}relatesTo"), URIRef(order)) in graph
    ]
    assert holders == ["relationships-sales.ttl"]


def test_one_statement_may_not_be_written_into_two_files(tmp_path: Path) -> None:
    """The invariant the whole partitioning scheme rests on (spec 4.2). Checked at build
    time because the model and the retained nodes are assembled from different evidence,
    and a duplicate would surface only as a diff hunk nobody could explain."""
    files = run(tmp_path, model(entity("e1", "Customer")))[0]
    customer = URIRef(iri_of(tmp_path, "e1"))
    registry = Registry(IdMap.load(tmp_path), BASE, repo_root=tmp_path, today=LATER)

    with pytest.raises(BuildError, match="written in both"):
        build.build(
            model(entity("e1", "Customer")),
            registry=registry,
            context=context(),
            previous=union(files),
            today=LATER,
            carried=(
                CarriedNode(
                    file="relationships-sales.ttl",
                    subject=customer,
                    statements=frozenset({(SKOS.prefLabel, Literal("Customer", lang="en"))}),
                    defines=False,
                ),
            ),
        )


def test_a_full_run_deprecates_an_object_all_of_whose_sources_it_fetched(
    tmp_path: Path,
) -> None:
    """The counterpart of the three above: scope is what separates "not looked at" from
    "not there", and with everything fetched the second is the answer."""
    shared = Entity(
        source_refs={ELLIE: "e1", EXCEL: "shared"}, pref_label="Customer", schemes=("sales",)
    )
    run(tmp_path, model(shared))
    customer = iri_of(tmp_path, "e1")

    plan = plan_only(tmp_path, InternalModel(schemes=(SALES,)))

    assert plan.deprecated == (customer,)
    assert (SEM_STATUS, DEPRECATED) in carried(plan, customer)


def test_a_source_missing_from_configuration_is_out_of_scope_rather_than_gone(
    tmp_path: Path,
) -> None:
    """A renamed source is an error `semprini check` reports (spec 5.4). Until it does,
    its objects must not quietly leave: a config typo would empty half the graph."""
    run(tmp_path, model(entity("e1", "Customer")))
    customer = iri_of(tmp_path, "e1")

    files, plan = run(
        tmp_path, InternalModel(schemes=(SALES,)), today=LATER, sources=("renamed-source",)
    )

    assert plan.deprecated == ()
    assert (SEM_STATUS, ACTIVE) in statements(files, customer)


# --------------------------------------------------------------------- merge register


def merged(deprecated_iri: str, replaced_by_iri: str) -> MergeRegister:
    return MergeRegister(
        [
            MergeRow(
                deprecated_iri=deprecated_iri,
                replaced_by_iri=replaced_by_iri,
                date=LATER,
                note="one customer, two records",
            )
        ]
    )


def test_a_merge_register_row_emits_is_replaced_by(tmp_path: Path) -> None:
    """Sources usually implement a merge by deleting one object, which alone is a plain
    deprecation. The register is what turns it into one that names the survivor."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Client")))
    survivor, gone = iri_of(tmp_path, "e1"), iri_of(tmp_path, "e2")

    files, plan = run(
        tmp_path,
        model(entity("e1", "Customer")),
        today=LATER,
        merges=merged(gone, survivor),
    )

    assert plan.deprecated == (gone,)
    said = statements(files, gone)
    assert (DCTERMS.isReplacedBy, URIRef(survivor)) in said
    assert (SEM_STATUS, DEPRECATED) in said


def test_only_the_deprecated_node_carries_the_replacement(tmp_path: Path) -> None:
    """One direction of the pair, like every other inverse the compiler could emit
    (spec 3.3): ``dcterms:replaces`` on the survivor would state the fact twice."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Client")))
    survivor, gone = iri_of(tmp_path, "e1"), iri_of(tmp_path, "e2")

    files = run(
        tmp_path, model(entity("e1", "Customer")), today=LATER, merges=merged(gone, survivor)
    )[0]

    assert not [p for p, _ in statements(files, survivor) if p == DCTERMS.replaces]


def test_removing_a_register_row_removes_the_statement(tmp_path: Path) -> None:
    """The register is read as it stands, so a steward can undo a row and see the triple
    go — rather than having it frozen into the output by the run that first read it."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Client")))
    survivor, gone = iri_of(tmp_path, "e1"), iri_of(tmp_path, "e2")
    only_customer = model(entity("e1", "Customer"))
    run(tmp_path, only_customer, today=LATER, merges=merged(gone, survivor))

    files = run(tmp_path, only_customer, today=LATER_STILL)[0]

    assert (DCTERMS.isReplacedBy, URIRef(survivor)) not in statements(files, gone)
    assert (SEM_STATUS, DEPRECATED) in statements(files, gone)


def test_a_register_row_naming_an_iri_the_id_map_does_not_hold_is_refused(
    tmp_path: Path,
) -> None:
    """The one file in an instance where a person types an IRI, so a typo is the expected
    failure. Unchecked, the row would deprecate nothing and say nothing (spec 5.4)."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Client")))
    gone = iri_of(tmp_path, "e2")

    with pytest.raises(LifecycleError, match="not in the ID map"):
        run(
            tmp_path,
            model(entity("e1", "Customer")),
            today=LATER,
            merges=merged(gone, f"{BASE}concepts/nothing-like-this"),
        )


def test_a_register_row_whose_deprecated_iri_is_unknown_is_refused(tmp_path: Path) -> None:
    run(tmp_path, model(entity("e1", "Customer")))
    survivor = iri_of(tmp_path, "e1")

    with pytest.raises(LifecycleError, match="deprecated_iri"):
        run(
            tmp_path,
            model(entity("e1", "Customer")),
            merges=merged(f"{BASE}concepts/nothing-like-this", survivor),
        )


def test_a_register_row_for_an_object_outside_the_scope_does_nothing_this_run(
    tmp_path: Path,
) -> None:
    """The register is a lifecycle decision and takes the scope rule with it: acting on it
    would mean deprecating a node this run has no evidence about, which is the one thing
    ``--source`` promises not to do. The next full run applies it. On a full run this state
    means the ID map names an unconfigured source, which `semprini check` reports (5.4)."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Client")))
    survivor, out_of_scope = iri_of(tmp_path, "e1"), iri_of(tmp_path, "e2")

    plan = lifecycle.plan(
        model(entity("e1", "Customer")),
        registry=Registry(IdMap.load(tmp_path), BASE, repo_root=tmp_path, today=LATER),
        context=RunContext(base_iri=BASE, instance_id="acme", repo_root=tmp_path),
        previous=build.read_previous_files(tmp_path),
        sources=("some-other-source",),
        merges=merged(out_of_scope, survivor),
    )

    assert plan.deprecated == ()
    assert (DCTERMS.isReplacedBy, URIRef(survivor)) not in carried(plan, out_of_scope)
    assert (SEM_STATUS, ACTIVE) in carried(plan, out_of_scope)


def test_a_successor_that_is_itself_deprecated_is_allowed(tmp_path: Path) -> None:
    """Ordinary history rather than a broken register: A was merged into B, and B was
    later retired by its own source. Refusing it would have the compiler retroactively
    invalidate a decision a steward correctly recorded at the time."""
    run(
        tmp_path,
        model(entity("e1", "Customer"), entity("e2", "Client"), entity("e3", "Buyer")),
    )
    survivor, gone = iri_of(tmp_path, "e2"), iri_of(tmp_path, "e3")

    files = run(
        tmp_path, model(entity("e1", "Customer")), today=LATER, merges=merged(gone, survivor)
    )[0]

    assert (SEM_STATUS, DEPRECATED) in statements(files, survivor)
    assert (DCTERMS.isReplacedBy, URIRef(survivor)) in statements(files, gone)


def test_a_register_row_for_an_object_the_sources_still_describe_is_refused(
    tmp_path: Path,
) -> None:
    """The register and the sources contradict each other, and the compiler settles
    neither: deprecating anyway would override every source from a one-line CSV edit,
    ignoring the row would make the register silently inert."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Client")))
    survivor, still_there = iri_of(tmp_path, "e1"), iri_of(tmp_path, "e2")

    with pytest.raises(LifecycleError, match="still describe it"):
        run(
            tmp_path,
            model(entity("e1", "Customer"), entity("e2", "Client")),
            merges=merged(still_there, survivor),
        )


# ------------------------------------------------------------- the register as a file


def register(*rows: str) -> str:
    return "\n".join(("deprecated_iri,replaced_by_iri,date,note", *rows)) + "\n"


def test_an_instance_with_no_register_has_an_empty_one(tmp_path: Path) -> None:
    """An instance that has never merged two concepts has nothing to record."""
    assert len(MergeRegister.load(tmp_path)) == 0


def test_an_empty_register_file_is_damaged(tmp_path: Path) -> None:
    """`semprini init` writes the header (spec 5.7), so a file without one is not the
    same state as no file at all."""
    (tmp_path / "mappings").mkdir()
    (tmp_path / lifecycle.MERGES_PATH).write_text("", encoding="utf-8")

    with pytest.raises(LifecycleError, match="must carry a header row"):
        MergeRegister.load(tmp_path)


def test_the_register_columns_are_checked(tmp_path: Path) -> None:
    with pytest.raises(LifecycleError, match="unexpected columns"):
        MergeRegister.loads("deprecated,replacement,date,note\n")


def test_a_byte_order_mark_is_tolerated(tmp_path: Path) -> None:
    """Stewards edit this in Excel, which writes one — and left in place it would join the
    first column name and make the header error print two identical-looking lists."""
    (tmp_path / "mappings").mkdir()
    (tmp_path / lifecycle.MERGES_PATH).write_text(register(), encoding="utf-8-sig")

    assert len(MergeRegister.load(tmp_path)) == 0


def test_every_bad_row_is_reported_at_once() -> None:
    """A hand-maintained file is edited in bulk, so one problem per CI round trip costs a
    steward a trip each (spec 5.2)."""
    with pytest.raises(LifecycleError) as raised:
        MergeRegister.loads(register("a,b,not-a-date,", ",b,2026-01-01,", "a,b,c"))

    assert len(raised.value.issues) == 3


def test_a_row_replacing_an_object_with_itself_is_refused() -> None:
    with pytest.raises(LifecycleError, match="replaced by itself"):
        MergeRegister.loads(register("x:a,x:a,2026-01-01,"))


def test_an_object_may_have_only_one_successor() -> None:
    """ "Which of these two survived" is the one question the register exists to answer."""
    with pytest.raises(LifecycleError, match="one successor"):
        MergeRegister.loads(register("x:a,x:b,2026-01-01,", "x:a,x:c,2026-01-01,"))


def test_a_circular_register_is_refused() -> None:
    """Every object in the loop is replaced by one that is itself deprecated, so following
    ``dcterms:isReplacedBy`` never arrives anywhere."""
    with pytest.raises(LifecycleError, match="circular") as raised:
        MergeRegister.loads(register("x:a,x:b,2026-01-01,", "x:b,x:a,2026-01-01,"))

    # One issue for the cycle, not one per member of it.
    assert len(raised.value.issues) == 1


def test_a_chain_of_merges_is_allowed_and_is_not_followed() -> None:
    """A → B recorded, then later B → C. A's successor is B: that is the statement the
    steward made, and rewriting it to C would emit a triple no row supports."""
    parsed = MergeRegister.loads(register("x:a,x:b,2026-01-01,", "x:b,x:c,2026-06-01,"))

    assert parsed.replacement("x:a") == "x:b"
    assert parsed.replacement("x:c") is None


def test_a_hand_typed_iri_is_stripped_of_stray_whitespace() -> None:
    """A trailing space would otherwise match nothing in the ID map and be reported as an
    unknown IRI, which is true and unhelpful."""
    parsed = MergeRegister.loads(register(" x:a , x:b ,2026-01-01, kept  as   written "))

    assert parsed.replacement("x:a") == "x:b"
    assert parsed.rows[0].note == " kept  as   written "


def test_the_register_round_trips_through_its_own_file(tmp_path: Path) -> None:
    (tmp_path / "mappings").mkdir()
    written = MergeRegister.loads(register("x:a,x:b,2026-01-01,merged in Ellie"))

    written.save(tmp_path)

    assert (tmp_path / lifecycle.MERGES_PATH).read_bytes().endswith(b"merged in Ellie\n")
    assert b"\r\n" not in (tmp_path / lifecycle.MERGES_PATH).read_bytes()
    assert MergeRegister.load(tmp_path).rows == written.rows


def test_the_register_is_not_valid_utf_8(tmp_path: Path) -> None:
    (tmp_path / "mappings").mkdir()
    (tmp_path / lifecycle.MERGES_PATH).write_bytes(b"deprecated_iri,\xff\xfe")

    with pytest.raises(LifecycleError, match="not valid UTF-8"):
        MergeRegister.load(tmp_path)


def test_a_register_that_cannot_be_read_is_reported_rather_than_raised(
    tmp_path: Path,
) -> None:
    """A directory where the file should be — an operator's mistake, not a traceback."""
    (tmp_path / lifecycle.MERGES_PATH).mkdir(parents=True)

    with pytest.raises(LifecycleError, match="cannot read the merge register"):
        MergeRegister.load(tmp_path)


# ------------------------------------------------------------------- the build handover


def test_a_carried_node_the_run_also_compiled_is_refused(tmp_path: Path) -> None:
    """One subject built twice would wear two labels and two statuses in one file. The
    plan never produces this; a caller assembling two runs' halves would."""
    files = run(tmp_path, model(entity("e1", "Customer")))[0]
    customer = URIRef(iri_of(tmp_path, "e1"))
    registry = Registry(IdMap.load(tmp_path), BASE, repo_root=tmp_path, today=TODAY)

    with pytest.raises(BuildError, match="either built from the model or retained"):
        build.build(
            model(entity("e1", "Customer")),
            registry=registry,
            context=context(),
            previous=union(files),
            today=LATER,
            carried=(
                CarriedNode(
                    file="concepts-sales.ttl",
                    subject=customer,
                    statements=frozenset({(SKOS.prefLabel, Literal("Customer", lang="en"))}),
                    defines=True,
                ),
            ),
        )


def test_the_previous_state_is_read_per_file_and_skips_the_ontology(tmp_path: Path) -> None:
    """Lifecycle needs to know *where* a statement was written; the metamodel copy is no
    instance's to date or deprecate."""
    run(tmp_path, model(entity("e1", "Customer")))

    per_file = build.read_previous_files(tmp_path)

    assert set(per_file) == {"concepts-sales.ttl"}
    assert len(build.union_of(per_file.values())) == len(per_file["concepts-sales.ttl"])


def test_a_generated_file_that_will_not_parse_names_itself(tmp_path: Path) -> None:
    (tmp_path / "generated").mkdir()
    (tmp_path / "generated" / "concepts-sales.ttl").write_text("this is not turtle {", "utf-8")

    with pytest.raises(BuildError, match="cannot read generated output"):
        build.read_previous_files(tmp_path)


def test_the_plan_and_the_report_agree_on_what_was_deprecated(tmp_path: Path) -> None:
    """One decided it, the other read it out of the graphs (spec 5.6). Two answers to one
    question is exactly how a report ends up contradicting the files beside it."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Fax number")))
    previous = build.read_previous(tmp_path)

    files, plan = run(tmp_path, model(entity("e1", "Customer")), today=LATER)
    summary = report.create(files, context=context(), previous=previous)

    assert {node.iri for node in summary.deprecated} == {
        iri.replace(f"{BASE}concepts/", "c:") for iri in plan.deprecated
    }


def test_nothing_is_minted_while_planning(tmp_path: Path) -> None:
    """The plan asks the ID map questions and answers none of them: an object new to this
    run has no IRI yet, and every node in the previous output has one (spec 5.4)."""
    run(tmp_path, model(entity("e1", "Customer")))
    rows = IdMap.load(tmp_path).rows
    registry = Registry(IdMap.load(tmp_path), BASE, repo_root=tmp_path, today=LATER)

    lifecycle.plan(
        model(entity("e1", "Customer"), entity("e9", "Brand new")),
        registry=registry,
        context=context(),
        previous=build.read_previous_files(tmp_path),
        sources=SOURCES,
    )

    assert registry.minted == ()
    assert registry.id_map.rows == rows


def test_a_first_compile_carries_nothing(tmp_path: Path) -> None:
    files, plan = run(tmp_path, model(entity("e1", "Customer")))

    assert plan == lifecycle.LifecyclePlan()
    assert {f.name for f in files} == {"ontology.ttl", "concepts-sales.ttl"}


def test_a_row_for_a_kind_the_compiler_does_not_write_is_still_carried(
    tmp_path: Path,
) -> None:
    """The carried statements come from the previous output, not from the model, so a node
    of any shape survives — which is what makes this safe across a metamodel change."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Fax number")))
    gone = iri_of(tmp_path, "e2")
    assert IdMap.load(tmp_path).owners(gone)[0].kind is Kind.ENTITY

    files = run(tmp_path, model(entity("e1", "Customer")), today=LATER)[0]

    assert (URIRef(f"{SEM}sourceRef"), Literal(f"{ELLIE}:e2")) in statements(files, gone)


def test_the_id_map_is_untouched_by_a_deprecation(tmp_path: Path) -> None:
    """Spec 3.4: an IRI is never removed or reused. A deprecated object keeps its row, so
    the object coming back tomorrow gets the IRI it always had."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Fax number")))
    before = IdMap.load(tmp_path).rows

    run(tmp_path, model(entity("e1", "Customer")), today=LATER)

    assert IdMap.load(tmp_path).rows == before


def test_an_object_that_comes_back_is_active_again_with_its_old_iri(tmp_path: Path) -> None:
    """Deprecation is a status, not a tombstone: a source that restores an object it
    deleted must not mint a second IRI for it."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Fax number")))
    gone = iri_of(tmp_path, "e2")
    run(tmp_path, model(entity("e1", "Customer")), today=LATER)

    files = run(
        tmp_path, model(entity("e1", "Customer"), entity("e2", "Fax number")), today=LATER_STILL
    )[0]

    assert iri_of(tmp_path, "e2") == gone
    assert (SEM_STATUS, ACTIVE) in statements(files, gone)


def test_an_unmapped_iri_and_a_bad_register_are_reported_together(tmp_path: Path) -> None:
    """Everything the stage can see, in one run: these are read in CI (spec 5.1)."""
    run(tmp_path, model(entity("e1", "Customer"), entity("e2", "Fax number")))
    survivor = iri_of(tmp_path, "e1")
    stripped = IdMap(row for row in IdMap.load(tmp_path) if row.source_key != "e2")
    stripped.save(tmp_path)

    with pytest.raises(LifecycleError) as raised:
        run(
            tmp_path,
            model(entity("e1", "Customer")),
            today=LATER,
            merges=merged(f"{BASE}concepts/nothing-like-this", survivor),
        )

    assert len(raised.value.issues) == 2

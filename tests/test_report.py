"""``generated/.report.md`` — the reviewer's summary of a run (spec 5.6).

The report is the only part of a compile most people read, so the tests here are about
whether it can be trusted rather than whether it renders. Two properties carry that.

*It agrees with the files beside it.* "Changed" in the report and a refreshed
``dcterms:modified`` in the Turtle answer one question, and a run where they disagreed
would teach reviewers to believe neither.

*It does not move on its own.* Everything in it is derived from the output and the state
that output replaced — no clock, no run identifier — and a run that changed nothing does
not rewrite it, because a pull request whose only content is a report saying nothing
changed is the empty diff the whole design exists to avoid.
"""

from __future__ import annotations

import dataclasses
import datetime
import os
import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF, SKOS, XSD

from sample import (
    BASE,
    CUSTOMER,
    ELLIE,
    EXCEL,
    GOLDEN,
    LATER,
    ORDER,
    TODAY,
    VERSIONS,
    by_name,
    compile_,
    context,
    sample_model,
    union,
)
from semprini import build, compiler_version, ontology_version
from semprini.build import OutputFile
from semprini.manifest import Manifest
from semprini.model import (
    Entity,
    InternalModel,
    Scheme,
    SchemeType,
    TaxonomyValue,
    merge_models,
)
from semprini.report import (
    LISTING_LIMIT,
    REPORT_FILE,
    NodeRef,
    RunReport,
    SourceSummary,
    create,
)

SOURCES = (
    SourceSummary(name="ellie-main", adapter="ellie", objects=6, note="2 models"),
    SourceSummary(name="taxonomies", adapter="excel-taxonomy", objects=3, note="1 workbook"),
)


def report(
    files: tuple[OutputFile, ...] | None = None,
    *,
    previous: Graph | None = None,
    sources: tuple[SourceSummary, ...] = SOURCES,
    deprecated: tuple[NodeRef, ...] = (),
) -> RunReport:
    return create(
        compile_() if files is None else files,
        context=context(),
        previous=previous,
        sources=sources,
        deprecated=deprecated,
        compiler=VERSIONS["compiler"],
        ontology=VERSIONS["ontology"],
    )


def labels(nodes: tuple[NodeRef, ...]) -> list[str]:
    return sorted(node.label for node in nodes)


SALES = Scheme(
    source_refs={ELLIE: "1234"},
    pref_label="Sales domain model",
    slug="sales",
    scheme_type=SchemeType.GLOSSARY,
)


def entity(key: str, label: str, definition: str | None = None) -> Entity:
    return Entity(
        source_refs={ELLIE: key}, pref_label=label, definition=definition, schemes=("sales",)
    )


def glossary(*entities: Entity) -> InternalModel:
    """A one-scheme model built around whichever entities a test needs."""
    return merge_models(InternalModel(schemes=(SALES,), entities=entities))


def relabelled(source_key: str, label: str) -> InternalModel:
    """The sample model with one entity renamed — the ordinary source change."""
    model = sample_model()
    return dataclasses.replace(
        model,
        entities=tuple(
            dataclasses.replace(existing, pref_label=label)
            if existing.source_refs.get(ELLIE) == source_key
            else existing
            for existing in model.entities
        ),
    )


# ------------------------------------------------------------------------- golden output


def test_the_golden_report_matches() -> None:
    """The text a reviewer actually reads, pasted into the pull request (spec 6.2)."""
    assert report().render() == (GOLDEN / REPORT_FILE).read_text(encoding="utf-8")


def test_the_report_ends_in_exactly_one_newline() -> None:
    text = report().render()

    assert text.endswith("|\n")
    assert not text.endswith("\n\n")


# ------------------------------------------------------------------------- determinism


def test_two_renders_of_one_run_are_identical() -> None:
    assert report().render() == report().render()


def test_the_report_carries_no_timestamps() -> None:
    """It is a governed file like any other: a date in it would make every scheduled
    compile a diff (spec 5.5 rule 8)."""
    assert str(datetime.date.today().year) not in report().render()


def test_the_report_is_written_with_lf(tmp_path: Path) -> None:
    """Through the same writer as the Turtle, so the platform default cannot translate
    every line ending on Windows (spec 5.5 rule 5)."""
    build.write_all((report().to_file(),), tmp_path)

    assert b"\r\n" not in (tmp_path / "generated" / REPORT_FILE).read_bytes()


def test_the_report_file_carries_no_graph() -> None:
    """It is prose, and must never be round-tripped through the serializer."""
    assert report().to_file().graph is None
    assert report().to_file().name == REPORT_FILE


# ------------------------------------------------------------------------- contents


def test_the_counts_per_class_are_what_was_compiled() -> None:
    counts = {count.term: count.objects for count in report().classes}

    assert counts == {
        "sem:Entity": 3,
        "sem:Attribute": 1,
        "sem:Relationship": 1,
        "skos:Concept": 2,
        "skos:ConceptScheme": 3,
    }


def test_a_class_with_nothing_in_it_is_still_listed() -> None:
    """ "0 relationships" says the run found none, which is different from the report
    forgetting to look."""
    counts = {count.term: count.objects for count in report(compile_(glossary())).classes}

    assert counts["sem:Relationship"] == 0


def test_the_counts_per_file_are_nodes_defined_and_triples_written() -> None:
    files = compile_()
    counted = {count.name: (count.subjects, count.triples) for count in report(files).files}
    graph = by_name(files)["relationships-sales.ttl"].graph

    assert graph is not None
    # One node defined — the relationship — though the file also carries the
    # sem:relatesTo shortcut, whose subject lives in another file (spec 4.2).
    assert counted["relationships-sales.ttl"] == (1, len(graph))


def test_the_ontology_copy_is_not_counted() -> None:
    """It is the metamodel, identical in every deployment, and none of it is content this
    instance compiled."""
    assert "ontology.ttl" not in [count.name for count in report().files]


def test_every_node_is_counted_exactly_once() -> None:
    """Partitioning writes an object once (spec 4.2), and the report must not undo that
    by counting a node in every file that mentions it."""
    counted = sum(count.subjects for count in report().files)

    assert counted == sum(count.objects for count in report().classes)


# ------------------------------------------------------------------------- changes


def test_a_first_compile_reports_everything_as_new() -> None:
    assert len(report().new) == 10
    assert report().changed == ()


def test_recompiling_unchanged_input_reports_nothing() -> None:
    """The run that must not open a pull request (spec 4.3)."""
    first = compile_()

    second = report(compile_(previous=union(first), today=LATER), previous=union(first))

    assert second.new == ()
    assert second.changed == ()
    assert "Nothing changed" in second.render()


def test_a_renamed_object_is_changed_not_new() -> None:
    first = compile_()

    second = report(
        compile_(relabelled(ORDER, "Purchase order"), previous=union(first), today=LATER),
        previous=union(first),
    )

    assert labels(second.changed) == ["Purchase order"]
    assert second.new == ()


def test_an_added_object_is_new_and_nothing_else_changed() -> None:
    """The property a reviewer relies on: adding one term does not report the rest of the
    instance as touched."""
    before = compile_(glossary(entity(CUSTOMER, "Customer")))
    after = compile_(
        glossary(entity(CUSTOMER, "Customer"), entity(ORDER, "Order")),
        previous=union(before),
        today=LATER,
    )

    summary = report(after, previous=union(before))

    assert labels(summary.new) == ["Order"]
    assert summary.changed == ()


def test_changed_and_the_modified_dates_agree() -> None:
    """One definition of "changed", shared with the ``dcterms:modified`` carry-forward
    (spec 3.3): a report saying nothing changed beside a file whose dates all moved would
    be the worst way for these two to disagree.
    """
    first = compile_()
    second_files = compile_(relabelled(ORDER, "Purchase order"), previous=union(first), today=LATER)
    graph = union(second_files)

    summary = report(second_files, previous=union(first))
    refreshed = {
        subject
        for subject, object_ in graph.subject_objects(DCTERMS.modified)
        if object_ == Literal(LATER, datatype=XSD.date)
    }

    assert {node.iri for node in summary.changed} == {f"c:{ORDER}"}
    assert refreshed == {URIRef(f"{BASE}concepts/{ORDER}")}


def test_deprecations_are_reported_as_the_caller_supplies_them() -> None:
    """Deprecation is evaluated against the union of all configured sources (spec 5.4),
    which the emitted graphs do not reveal — **E1** supplies these."""
    gone = NodeRef(label="Fax number", iri="c:0000")

    rendered = report(deprecated=(gone,)).render()

    assert "| Deprecated | 1 |" in rendered
    assert "### Deprecated (1)" in rendered
    assert "Fax number" in rendered


# ------------------------------------------------------------------------- warnings


def test_objects_without_a_definition_are_warned_about() -> None:
    """Reported, not blocking, in v1 (spec 6.1)."""
    assert labels(report().missing_definitions) == [
        "Customer number",
        "Order",
        "Power tools",
        "Product category",
    ]


def test_a_relationship_or_a_scheme_needs_no_definition() -> None:
    """Spec 6.1's warning names entities, attributes and taxonomy concepts; a
    relationship's label is its verb and a scheme's is its title."""
    warned = labels(report().missing_definitions)

    assert "places" not in warned
    assert "Sales domain model" not in warned


def test_two_objects_of_one_class_sharing_a_name_are_warned_about() -> None:
    """Identity comes from source keys, so these stay two objects however obvious the
    duplication looks; only a steward can say whether they are the same thing (spec 5.3).
    """
    files = compile_(glossary(entity(CUSTOMER, "Account"), entity(ORDER, "Account")))

    clashes = report(files).name_clashes

    assert len(clashes) == 1
    assert clashes[0].label == "Account"
    assert clashes[0].term == "sem:Entity"
    assert {node.iri for node in clashes[0].nodes} == {f"c:{CUSTOMER}", f"c:{ORDER}"}


def test_names_differing_only_in_case_are_the_same_ambiguity() -> None:
    files = compile_(glossary(entity(CUSTOMER, "Account"), entity(ORDER, "account")))

    clashes = report(files).name_clashes

    assert len(clashes) == 1
    assert clashes[0].label == "Account"  # the smaller of the two, so the choice is fixed


def test_two_classes_may_share_a_name() -> None:
    """A taxonomy value named after the entity it classifies is ordinary, not suspicious.

    The sample model already does it: the ``Product category`` entity and the taxonomy
    that enumerates it are not the same kind of thing.
    """
    files = compile_(
        merge_models(
            InternalModel(
                schemes=(
                    SALES,
                    Scheme(
                        source_refs={EXCEL: "product-category.xlsx"},
                        pref_label="Product category taxonomy",
                        slug="product-category",
                        scheme_type=SchemeType.TAXONOMY,
                    ),
                ),
                entities=(entity(CUSTOMER, "Drills"),),
                taxonomy_values=(
                    TaxonomyValue(
                        source_refs={EXCEL: "PT-DR"},
                        pref_label="Drills",
                        code="PT-DR",
                        schemes=("product-category",),
                    ),
                ),
            )
        )
    )

    assert report(files).name_clashes == ()


def test_a_clean_run_says_so() -> None:
    files = compile_(glossary(entity(CUSTOMER, "Customer", "Someone who buys things.")))

    summary = report(files)

    assert summary.warnings == 0
    assert "## Warnings\n\nNone.\n" in summary.render()


# ------------------------------------------------------------------------- presentation


def test_iris_are_shortened_against_the_instance_prefixes() -> None:
    """A reviewer reads this in a pull request, and ``c:7f3a…`` is the form that also
    appears in the Turtle beside it (spec 3.1)."""
    assert f"- Customer — `c:{CUSTOMER}`" in report().render()


def test_an_iri_outside_the_instance_namespaces_is_written_in_full() -> None:
    """Abbreviating one would invent a prefix the Turtle does not declare."""
    graph = Graph()
    foreign = URIRef("http://example.org/vocab/thing")
    graph.add((foreign, RDF.type, SKOS.Concept))
    graph.add((foreign, SKOS.prefLabel, Literal("Thing", lang="en")))

    rendered = report((OutputFile(name="external.ttl", text="", graph=graph),)).render()

    assert "`http://example.org/vocab/thing`" in rendered


_MULTILINGUAL_SCRIPT = """
import sys

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SKOS

from semprini.model import RunContext
from semprini.report import create
from semprini.build import OutputFile

BASE = "https://semantics.example.com/"
graph = Graph()
for index in range(20):
    subject = URIRef(f"{BASE}concepts/term-{index:04d}")
    for term in ("Attribute", "Entity"):
        graph.add((subject, RDF.type, URIRef(f"https://w3id.org/semprini/ontology#{term}")))
    for language, text in (("en", f"Term {index}"), ("fi", f"Termi {index}")):
        graph.add((subject, SKOS.prefLabel, Literal(text, lang=language)))

report = create(
    (OutputFile(name="concepts-sales.ttl", text="", graph=graph),),
    context=RunContext(base_iri=BASE, instance_id="acme"),
    compiler="0.1.0",
    ontology="0.1.0",
)
sys.stdout.write(report.render())
"""


def _render_in_a_subprocess(hash_seed: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", _MULTILINGUAL_SCRIPT],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
        check=True,
    )
    return completed.stdout


def test_a_node_with_several_labels_or_types_reports_the_same_on_every_machine() -> None:
    """Which label names a node, and which class it is counted as, are not rdflib's to
    decide. No v1 adapter produces either, but the previous state may hold one and
    ``create`` is public.

    Run out of process because that is the only way to vary ``PYTHONHASHSEED``: rdflib
    holds a subject's objects in a set, so without an explicit choice both follow string
    hashing — identical all day on one machine and different on the next, which is the
    diff nobody caused (spec 5.5 rule 8). Two in-process attempts at this looked like they
    were testing it while asserting nothing.
    """
    first = _render_in_a_subprocess("0")
    second = _render_in_a_subprocess("12345")
    third = _render_in_a_subprocess("98765")

    assert first == second == third
    # Guards the guard: three identical empty renderings would also pass the line above.
    listed = {line for line in first.splitlines() if line.startswith("- Term ")}
    assert len(listed) == LISTING_LIMIT
    assert "Termi" not in first
    # Both nodes' classes resolve the same way, to the lexicographically first.
    assert "| sem:Attribute | 20 |" in first
    assert "| sem:Entity | 0 |" in first


def test_a_long_listing_is_capped_but_the_count_is_not() -> None:
    """A first compile of a large instance would otherwise paste thousands of lines into
    a pull request description and bury the counts."""
    many = LISTING_LIMIT + 5
    files = compile_(
        glossary(*(entity(f"e{index:04d}", f"Term {index:04d}") for index in range(many)))
    )

    rendered = report(files).render()

    assert f"### New ({many + 1})" in rendered  # the entities plus their scheme
    # The listing itself, not the whole document: every one of these labels also appears
    # under "Missing definitions", so a boundary asserted against `rendered` would be
    # pinning that listing's cap while claiming to pin this one's.
    listed = rendered.split(f"### New ({many + 1})\n\n", 1)[1].split("\n\n", 1)[0].splitlines()

    assert len(listed) == LISTING_LIMIT
    assert listed[0] == "- Sales domain model — `sch:sales`"
    assert listed[-1].startswith("- Term 0018 —")
    assert "…and 6 more." in rendered


def test_a_label_carrying_a_line_break_does_not_break_the_listing() -> None:
    """Labels are whatever a source holds — an Excel cell with a line break in it — and
    this file is rendered verbatim into a pull request description (spec 6.2)."""
    files = compile_(glossary(entity(CUSTOMER, "Customer\naccount")))

    listed = [line for line in report(files).render().splitlines() if line.startswith("- ")]

    assert f"- Customer account — `c:{CUSTOMER}`" in listed
    assert all(line.endswith("`") for line in listed)


def test_a_source_note_carrying_a_pipe_does_not_break_the_table() -> None:
    """A third-party adapter supplies these, and a bare ``|`` ends a table column."""
    noisy = SourceSummary(name="ellie-main", adapter="ellie", objects=1, note="a | b")

    rendered = report(sources=(noisy,)).render()

    assert "| ellie-main | `ellie` | 1 | a \\| b |" in rendered


def test_a_run_with_no_source_summary_says_so() -> None:
    """Until **E2** supplies them, an empty table would read as "no sources configured"."""
    assert "No per-source summary was recorded." in report(sources=()).render()


def test_the_versions_are_the_running_ones_by_default() -> None:
    summary = create(compile_(), context=context())

    assert summary.compiler_version == compiler_version()
    assert summary.ontology_version == ontology_version()


# --------------------------------------------------------- when the report is rewritten


def test_a_no_op_run_leaves_the_whole_instance_untouched(tmp_path: Path) -> None:
    """The composition **E2** performs: build, hash, and write the report only if
    something moved. Asserted end to end here, because the guarantee is worth nothing if
    the pieces are individually correct and wired up wrongly.
    """
    files = compile_()
    recorded = Manifest.create(files, compiler=VERSIONS["compiler"], ontology=VERSIONS["ontology"])
    build.write_all((*files, recorded.to_file(), report(files).to_file()), tmp_path)
    before = {
        path.name: path.read_bytes()
        for path in (tmp_path / "generated").iterdir()
        if path.is_file()
    }

    again = compile_(previous=build.read_previous(tmp_path), today=LATER)
    output = (
        *again,
        Manifest.create(
            again, compiler=VERSIONS["compiler"], ontology=VERSIONS["ontology"]
        ).to_file(),
    )
    assert build.unchanged(output, tmp_path)

    build.write_all(output, tmp_path)
    after = {
        path.name: path.read_bytes()
        for path in (tmp_path / "generated").iterdir()
        if path.is_file()
    }
    assert after == before


def test_a_changed_run_is_not_unchanged(tmp_path: Path) -> None:
    files = compile_()
    build.write_all(files, tmp_path)

    changed = compile_(relabelled(ORDER, "Purchase order"), previous=union(files), today=LATER)

    assert not build.unchanged(changed, tmp_path)


def test_an_instance_that_has_never_compiled_is_not_unchanged(tmp_path: Path) -> None:
    assert not build.unchanged(compile_(), tmp_path)


@pytest.mark.parametrize("today", [TODAY, LATER])
def test_the_report_does_not_depend_on_when_the_run_happened(today: datetime.date) -> None:
    """``dcterms:modified`` is the one date in the output and it is excluded from every
    comparison the report makes, so the same input reports the same thing on any day."""
    first = compile_()

    summary = report(compile_(previous=union(first), today=today), previous=union(first))

    assert (
        summary.render() == report(compile_(previous=union(first)), previous=union(first)).render()
    )

"""The synthetic model the emit-stage tests compile, and the helpers that compile it.

Shared rather than copied because the golden files under ``fixtures/golden/`` are the
output of *this* model: the Turtle, the manifest that hashes it and the report that
describes it all have to be describing one run, or a golden file stops being evidence of
anything. Nothing here is any organization's content (spec 9.2 rule 5).
"""

from __future__ import annotations

import datetime
from pathlib import Path

from rdflib import Graph

from semprini import build, serialize
from semprini.build import OutputFile
from semprini.identity import IdMap, Registry
from semprini.model import (
    Attribute,
    Entity,
    InternalModel,
    Relationship,
    RunContext,
    Scheme,
    SchemeType,
    SourceRef,
    TaxonomyValue,
    merge_models,
)

BASE = "https://semantics.example.com/"
TODAY = datetime.date(2026, 8, 6)
LATER = datetime.date(2026, 12, 25)
ELLIE = "ellie-main"
EXCEL = "taxonomies"

GOLDEN = Path(__file__).parent / "fixtures" / "golden"

CUSTOMER = "7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21"
ORDER = "0d9e4c77-1c1e-4a41-9f0c-6a3a0b2f5c10"
NUMBER = "55aa0c3e-9f2b-4c7d-8e1a-3f5b7c9d1e20"
PLACES = "c2d1e0aa-7b3c-4d5e-9f01-2a3b4c5d6e7f"

SEM = serialize.SEM_NAMESPACE

VERSIONS = {"compiler": "0.1.0", "ontology": "0.1.0"}
"""Versions pinned in the golden manifest and report.

Injected rather than read from the installed package: a golden file carrying the running
version would have to be regenerated on every release, and a golden file regenerated as a
matter of routine stops being read (spec 7)."""


def context(**overrides: object) -> RunContext:
    settings: dict[str, object] = {"base_iri": BASE, "instance_id": "acme"}
    settings.update(overrides)
    return RunContext(**settings)  # type: ignore[arg-type]


def sample_model() -> InternalModel:
    """A model exercising every class and property the builder emits.

    Deliberately spans two glossaries and a taxonomy, so that partitioning, multi-scheme
    membership and cross-file references are all covered by the golden files.
    """
    return merge_models(
        InternalModel(
            schemes=(
                Scheme(
                    source_refs={ELLIE: "1234"},
                    pref_label="Sales domain model",
                    slug="sales",
                    scheme_type=SchemeType.GLOSSARY,
                ),
                Scheme(
                    source_refs={ELLIE: "1287"},
                    pref_label="Finance domain model",
                    slug="finance",
                    scheme_type=SchemeType.GLOSSARY,
                ),
                Scheme(
                    source_refs={EXCEL: "product-category.xlsx"},
                    pref_label="Product category taxonomy",
                    slug="product-category",
                    scheme_type=SchemeType.TAXONOMY,
                    enumerates=f"{BASE}concepts/{NUMBER}",
                ),
            ),
            entities=(
                Entity(
                    source_refs={ELLIE: CUSTOMER},
                    pref_label="Customer",
                    definition="A person or organization that buys our products.",
                    alt_labels=("Client", "Account holder"),
                    # In both glossaries: the shared object that proves an entity is
                    # written once and still carries both memberships.
                    schemes=("sales", "finance"),
                ),
                Entity(source_refs={ELLIE: ORDER}, pref_label="Order", schemes=("sales",)),
                Entity(
                    source_refs={ELLIE: NUMBER},
                    pref_label="Product category",
                    schemes=("finance",),
                ),
            ),
            attributes=(
                Attribute(
                    source_refs={ELLIE: "a1b2c3d4-0000-4000-8000-000000000001"},
                    pref_label="Customer number",
                    entity=SourceRef(ELLIE, CUSTOMER),
                    schemes=("sales",),
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
            ),
            taxonomy_values=(
                TaxonomyValue(
                    source_refs={EXCEL: "PT"},
                    pref_label="Power tools",
                    code="PT",
                    schemes=("product-category",),
                ),
                TaxonomyValue(
                    source_refs={EXCEL: "PT-DR"},
                    pref_label="Drills",
                    definition="Tools that make holes.",
                    code="PT-DR",
                    parent=SourceRef(EXCEL, "PT"),
                    schemes=("product-category",),
                ),
            ),
        )
    )


def compile_(
    model: InternalModel | None = None,
    *,
    registry: Registry | None = None,
    previous: Graph | None = None,
    today: datetime.date = TODAY,
    ctx: RunContext | None = None,
) -> tuple[OutputFile, ...]:
    return build.build(
        sample_model() if model is None else model,
        registry=registry if registry is not None else Registry(IdMap(), BASE, today=TODAY),
        context=ctx if ctx is not None else context(),
        previous=previous,
        today=today,
    )


def by_name(files: tuple[OutputFile, ...]) -> dict[str, OutputFile]:
    return {file.name: file for file in files}


def union(files: tuple[OutputFile, ...]) -> Graph:
    """Every generated graph loaded together — what a consumer of the instance sees."""
    graph = Graph()
    for file in files:
        if file.graph is not None:
            graph += file.graph
    return graph

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The build of a semantics repository and its compiler, at the point where implementation is about to
start. There is no code yet, no git repo, no build — the directory currently holds one authoritative
document and one prior-project prototype:

- `rdf-repo-and-compiler-spec.md` — **authoritative.** It specifies both deliverables: a semantics Git
  repository (versioned RDF/Turtle system of record) and a Python compiler that generates its contents
  from Ellie and Excel. It is explicitly self-contained ("no other background material is required to
  implement it"). When anything conflicts with it, the spec wins, and a behaviour change means editing
  the spec in the same change.
- `background-material/kg-converter-old/` — a working converter from an **earlier, similar but
  different** project. Not maintained, and **not authoritative for any specification decision** —
  mine it for learnings, never cite it as a requirement.

Implementation is expected to grow here, following the layout of spec §4 (`compiler/`, `generated/`,
`overlays/`, `sources/`, `mappings/`, `shapes/`, `config/`, `.github/workflows/`) — Python 3.12,
Poetry, `rdflib` / `openpyxl` / `requests` / `pyshacl`, CLI per §5.1.

## Blocking open decision

Spec §9 #1: the base IRI domain is still the placeholder `semantics.example.com`. Because IRIs are
permanent once minted, **no real compilation can happen until it is chosen**. Keep the placeholder in
examples; don't silently pick a domain.

## The old project solved a different problem — mine it, don't copy it

`kg-converter-old` and the spec model the same source data (Ellie models, Excel taxonomies) in
fundamentally different RDF. Treating prototype behaviour as a requirement is the main hazard:

| | prototype (old) | spec (current) |
|---|---|---|
| Modelling | OWL: entity → `owl:Class`, attribute → `owl:DatatypeProperty`, relationship → `owl:ObjectProperty` (+ `owl:inverseOf`) | SKOS-based `sem:` metamodel: `sem:Entity`/`sem:Attribute`/reified `sem:Relationship`, all `skos:Concept` subclasses |
| Taxonomy↔model join | OWL 2 punning (class doubles as `skos:ConceptScheme`) | `sem:enumerates` from scheme to entity; no punning |
| Namespaces | one namespace per source model, everything in it | partitioned by *kind* (`c:`, `r:`, `sch:`, `v:`) — never by domain |
| Input | Ellie JSON export file | Ellie REST API with a model allowlist |
| Output style | commented, sectioned, human-flavoured Turtle | comment-free canonical Turtle, byte-deterministic |
| Identity | Ellie UUID / readable local names derived on the fly | persistent `mappings/id-map.csv` is authoritative over the minting formula |
| Lifecycle | none (one run = one file) | deprecation, `dcterms:isReplacedBy`, merge register |

What is still worth mining from it: the Ellie export field semantics (README §1.1 tables, including
the `superType`/`subType` and label-`direction` cases), the Excel ragged-hierarchy reading logic
(`taxonomy_to_rdf.py`), and `rdf_serialize.py` as evidence that rdflib's own Turtle output must be
wrapped to get stable ordering — the spec §5.4 canonical serializer is a stricter version of the same
idea.

## Spec invariants — check code and spec edits against these

These are load-bearing. A design choice that violates one is wrong even if it passes tests, and a
deliberate change to one usually implies changes elsewhere in the spec.

- **Deterministic serialization is the point.** PR diffs are the governance interface (§1.1), so
  §5.4's fixed prefix block, sorted subjects/predicates, and the CI byte-identity check (§6.5) all
  exist to serve it. Any output-format proposal must survive "would this diff cleanly?".
- **IRIs are opaque and permanent.** No names, codes, or domains in IRIs; domain membership is data
  (`skos:inScheme`). Never deleted, never reused.
- **The ID map, not the formula, is authoritative** (§5.3) — that is what lets codes and minting
  rules change without breaking identity.
- **`generated/` is machine-owned**; `overlays/` is the only hand-written RDF. Enforced by the
  `.manifest.json` hash check, not convention.
- **Deprecation is evaluated against the union of all configured sources**, never one source or
  model — hence `--source X` runs skip deprecation outside their scope (§5.3).
- **Adapters stay source-agnostic** (`BaseAdapter.fetch() -> InternalModel`, generic
  `source_refs: dict[str, str]`) because Collibra and Knowledge Catalog adapters are planned (§8).
  v1 choices must not close those doors.

## Running the old prototype

Only if you need to inspect its behaviour. `rdflib` 7.6 and `openpyxl` 3.1.5 are installed globally
(Python 3.14); the prototype has no packaging, lockfile, or test suite.

```bash
cd background-material/kg-converter-old
python kg_convert.py ontology --input tests/Storefront.json --output /tmp/storefront.ttl \
    --base-iri http://example.org/ontology/storefront/ --prefix storefront
python kg_convert.py taxonomy --input tests/Taxonomy_product_category_storefront.xlsx \
    --output /tmp/taxonomy.ttl --base-iri http://example.org/ontology/storefront/ \
    --prefix storefront --ontology /tmp/storefront.ttl --strict
```

`tests/` holds sample inputs plus committed `.ttl` outputs from a previous run — useful as
before/after references. Write new output to the scratchpad rather than overwriting them.
`background-material/kg-converter-old/CLAUDE.md` documents that project's internals in detail.

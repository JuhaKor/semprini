# Semantics repository & compiler — implementation specification

**Status:** Draft v0.1 · **Author:** Juha Korpela / Datakor · **Date:** August 2026

---

## 1. Purpose

This document specifies two deliverables:

1. **The semantics repository** — a Git repository (GitHub) that acts as the versioned
   system of record for an organization's compiled semantic content: business concepts,
   their relationships, taxonomies, and (in later versions) links between concepts and
   technical data objects. Content is stored as RDF in Turtle (`.ttl`) files.
2. **The compiler** — a Python application that reads semantic content from source
   systems (v1: the Ellie data modeling tool and Excel taxonomy files), transforms it
   into RDF conforming to the metamodel defined in this document, and writes
   deterministic Turtle files into the repository via pull requests.

The repository's contents are consumed downstream by graph-serving components
(e.g., loading into a triple store or graph database for AI-agent access). Downstream
publishing is **out of scope** for this specification; the contract ends at *validated
TTL files on the repository's main branch*.

This document is self-contained: no other background material is required to
implement it.

### 1.1 Design principles

- **Sources are masters; the repo is the record.** Semantic content is authored in
  source tools (Ellie, Excel). The repository never becomes a place where generated
  content is edited by hand. Corrections go to the source, then the compiler
  regenerates.
- **Identity is permanent and opaque.** Every semantic object has an IRI that never
  changes and never encodes mutable facts (names, domains, codes).
- **Diffs are the governance interface.** Every content change arrives as a pull
  request whose diff is human-reviewable. This requires deterministic serialization.
- **Validation is automated.** CI enforces the metamodel with SHACL and structural
  checks on every PR.

---

## 2. Scope

### In scope (v1)

- Repository structure, file conventions, canonical serialization rules
- Metamodel: RDF classes, properties, IRI policy, lifecycle rules
- Compiler: Ellie API adapter, Excel taxonomy adapter, merge, emit
- Identity management (IRI minting and the persistent ID map)
- SHACL shapes and CI validation (GitHub Actions)
- Compile orchestration (scheduled and manual runs producing PRs)

### Out of scope (v1) — designed-for extension points

- Collibra adapter (glossary items, definitions, term–asset links)
- Google Cloud Knowledge Catalog adapter (glossary terms, entry links, asset entries)
- Document isaboutness links
- Publishing to GCS / triple-store loading / serving APIs
- Any UI

---

## 3. Metamodel

### 3.1 Namespaces and prefixes

The base IRI is a placeholder; replace `semantics.example.com` with the
organization's controlled domain before first use. **Once minted, IRIs are permanent** —
choose the domain deliberately.

| Prefix   | Namespace                                        | Use                          |
|----------|--------------------------------------------------|------------------------------|
| `sem:`   | `https://semantics.example.com/ontology#`        | Metamodel classes/properties |
| `c:`     | `https://semantics.example.com/concepts/`        | Entities, attributes, terms  |
| `r:`     | `https://semantics.example.com/relationships/`   | Reified relationships        |
| `sch:`   | `https://semantics.example.com/schemes/`         | Glossaries & taxonomies (as schemes) |
| `v:`     | `https://semantics.example.com/values/`          | Taxonomy value nodes         |
| `skos:`  | `http://www.w3.org/2004/02/skos/core#`           | Labels, definitions, hierarchy |
| `dcterms:` | `http://purl.org/dc/terms/`                    | Provenance, replacement      |
| `xsd:`   | `http://www.w3.org/2001/XMLSchema#`              | Datatypes                    |

The IRI space is partitioned by **kind of thing** (immutable), never by business
domain (mutable). Domain membership is expressed as data (`skos:inScheme`).

Reserved for later versions (declare now, use later): `a:`
(`…/assets/`) for technical data objects, `d:` (`…/docs/`) for documents.

### 3.2 Classes

| Class | Subclass of | Represents | Source (v1) |
|---|---|---|---|
| `sem:Entity` | `skos:Concept` | Business entity / concept ("Customer") | Ellie entity |
| `sem:Attribute` | `skos:Concept` | Attribute with own identity ("Customer number") | Ellie attribute |
| `sem:Relationship` | — | Named relationship between two entities | Ellie relationship |
| `sem:BusinessTerm` | `skos:Concept` | Free-form glossary term | *(Collibra, later)* |
| `skos:ConceptScheme` | — | A domain glossary **or** a taxonomy | Ellie domain model; Excel file |
| `skos:Concept` (plain, in a taxonomy scheme) | — | Taxonomy value node ("Drills") | Excel row |

Notes:

- Attributes are first-class nodes (not RDF properties) because source tools give
  them identity, definitions, and ownership.
- Relationships are reified (own node) because they carry a name/verb and identity.
  The compiler additionally emits a shortcut triple (`sem:relatesTo`) between the two
  entities for cheap traversal.
- Taxonomy value nodes are plain `skos:Concept`s; their nature is indicated by
  membership in a taxonomy-typed scheme (see 3.4).

### 3.3 Properties

**Metamodel properties (`sem:`):**

| Property | Domain → Range | Meaning |
|---|---|---|
| `sem:attributeOf` | `sem:Attribute` → `sem:Entity` | Attribute belongs to entity |
| `sem:source` | `sem:Relationship` → `sem:Entity` | Relationship source end |
| `sem:target` | `sem:Relationship` → `sem:Entity` | Relationship target end |
| `sem:relatesTo` | `sem:Entity` → `sem:Entity` | Compiler-emitted shortcut for a relationship |
| `sem:enumerates` | `skos:ConceptScheme` → `sem:Entity` | Taxonomy provides the values of an entity |
| `sem:status` | any → `xsd:string` | Lifecycle: `"active"` \| `"deprecated"` |
| `sem:ellieId` | any → `xsd:string` | Source UUID in Ellie |
| `sem:sourceRef` | any → `xsd:string` | Generic source reference (file/row for Excel; reserved for Collibra/KC IDs) |
| `sem:schemeType` | `skos:ConceptScheme` → `xsd:string` | `"glossary"` \| `"taxonomy"` |
| `sem:isAbout` | *(reserved, later)* technical object → concept | Semantic linking ("isaboutness") |
| `sem:represents` | *(reserved, later)* column → attribute | Precise linking subproperty |

**Reused standard properties:**

- `skos:prefLabel` (exactly one per node, per language), `skos:altLabel` (synonyms)
- `skos:definition` — definition text
- `skos:inScheme`, `skos:topConceptOf`, `skos:hasTopConcept` — scheme membership
- `skos:broader` / `skos:narrower` — taxonomy hierarchy (only inside taxonomy schemes)
- `skos:notation` — business code of a taxonomy value (e.g. `"PT"`)
- `skos:exactMatch`, `skos:broadMatch` — cross-scheme alignment (e.g., to industry taxonomies)
- `dcterms:isReplacedBy` — deprecated node → successor
- `dcterms:modified` — last content change (`xsd:date`), set by the compiler

### 3.4 IRI policy

1. **Opaque IRIs.** No names, codes, or domains in IRIs. Labels live in
   `skos:prefLabel`, codes in `skos:notation`, domain membership in `skos:inScheme`.
2. **Minting:**
   - Objects with an Ellie UUID → `c:{uuid}` / `r:{uuid}` (the Ellie UUID is used
     directly as the IRI local name; it is already opaque and stable).
   - Schemes → `sch:{slug}` where the slug is assigned **once** at scheme creation and
     recorded in the ID map; treat it as opaque thereafter (renaming the glossary does
     not change the slug).
   - Taxonomy values (no source UUID) → `v:{uuid5}` where `uuid5 = UUIDv5(NAMESPACE_SEM,
     scheme-slug + "|" + source-row-key)`. The source-row-key is the taxonomy code
     column if codes are declared stable for that file, otherwise an explicit `id`
     column that maintainers must add. The resulting mapping is **persisted in the ID
     map** (see 5.3), which is authoritative from then on: if a code later changes, the
     ID map preserves the original IRI.
3. **IRIs are never deleted or reused.** Removal from a source marks the node
   `sem:status "deprecated"`; merges add `dcterms:isReplacedBy`.

### 3.5 Lifecycle rules

| Event in source | Effect in RDF |
|---|---|
| Object renamed | `skos:prefLabel` changes; IRI unchanged |
| Object moved between domains/schemes | `skos:inScheme` changes; IRI unchanged |
| Object deleted in source | Node retained, `sem:status "deprecated"`; compiler stops updating it |
| Two objects merged in source | Surviving node stays active; the other becomes deprecated with `dcterms:isReplacedBy` → survivor (requires an entry in the merge register, see 5.3, because sources typically just delete one object) |
| Taxonomy value code changed | `skos:notation` changes; IRI unchanged (via ID map) |

### 3.6 Example (illustrative)

```turtle
c:7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21 a sem:Entity ;
    skos:prefLabel "Customer"@en ;
    skos:definition "A person or organization that buys our products."@en ;
    skos:inScheme sch:sales ;
    sem:ellieId "7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21" ;
    sem:status "active" ;
    dcterms:modified "2026-08-03"^^xsd:date .

r:c2d1e0aa-... a sem:Relationship ;
    skos:prefLabel "places"@en ;
    sem:source c:7f3a9b12-... ;
    sem:target c:0d9e4c77-... ;      # Order
    sem:status "active" .

c:7f3a9b12-... sem:relatesTo c:0d9e4c77-... .   # compiler-emitted shortcut

sch:product-category a skos:ConceptScheme ;
    skos:prefLabel "Product category taxonomy"@en ;
    sem:schemeType "taxonomy" ;
    sem:enumerates c:55aa0c3e-... .   # "Product Category" reference entity in Ellie

v:9c1f... a skos:Concept ;
    skos:prefLabel "Drills"@en ;
    skos:notation "PT-DR" ;
    skos:broader v:8b0e... ;          # Power tools
    skos:inScheme sch:product-category ;
    sem:status "active" .
```

---

## 4. Repository layout

```
semantics-repo/
├── README.md                  # points to this spec; quickstart
├── generated/                 # compiler output — NEVER hand-edited
│   ├── ontology.ttl               # the sem: metamodel itself (compiler-emitted, static)
│   ├── concepts-<domain>.ttl      # one file per Ellie domain model
│   ├── relationships-<domain>.ttl
│   └── taxonomy-<scheme-slug>.ttl # one file per Excel taxonomy
├── overlays/                  # hand-curated TTL — the only human-edited RDF
│   ├── external/                  # imported standard ontologies/vocabularies (curated subsets)
│   └── patches/                   # axioms & statements the sources cannot express
├── sources/
│   └── taxonomies/                # the Excel taxonomy files (committed here)
├── mappings/
│   ├── id-map.csv                 # persistent identity registry (see 5.3)
│   └── merges.csv                 # merge register (see 5.3)
├── shapes/                    # SHACL shapes (see 7)
├── compiler/                  # the Python package (see 6)
├── config/
│   └── compiler.yaml              # source endpoints, Ellie model allowlist, taxonomy registry
└── .github/workflows/
    ├── compile.yml                # scheduled/manual: run compiler, open PR
    └── validate.yml               # on PR: syntax, SHACL, determinism, policy checks
```

Rules:

- Everything under `generated/` is overwritten wholesale on every compiler run.
  CI **fails any PR that edits `generated/` without the compiler** (enforced by a
  marker: the compiler writes a manifest `generated/.manifest.json` with content
  hashes; validation recomputes and compares).
- `overlays/` files are validated against the same SHACL shapes but written by humans
  through normal PRs.
- Excel taxonomy files are committed under `sources/taxonomies/` so that a taxonomy
  edit and its generated TTL land in the same PR and are reviewed together.

---

## 5. Compiler

### 5.1 Overview

A Python 3.12 package (`compiler/`) using `rdflib` for graph construction and
serialization, `openpyxl` for Excel, `requests` for the Ellie API, `pyshacl` for
local validation. Poetry-managed. Invoked as a CLI:

```
python -m compiler run   --config config/compiler.yaml [--source ellie|excel|all] [--dry-run]
python -m compiler check --config config/compiler.yaml   # validate only, no writes
```

Pipeline stages:

```
fetch (per source adapter)
  → normalize into the internal model (dataclasses: Concept, Attribute,
    Relationship, Scheme, TaxonomyValue)
  → resolve identity (ID map lookup / minting)
  → build rdflib Graphs (one per output file)
  → apply lifecycle rules (diff against previous generated/ state)
  → canonical serialization → write generated/*.ttl + .manifest.json
  → update mappings/id-map.csv (append-only)
```

The compiler is **stateless between runs** except for what is in the repository
(previous TTL, ID map). It must be runnable locally and in CI with identical results.

### 5.2 Source adapters

Adapters implement a common interface (`BaseAdapter.fetch() -> InternalModel`) so that
Collibra and Knowledge Catalog adapters can be added later without pipeline changes.

**Ellie adapter (v1).**

- Reads via Ellie's REST API (token from environment variable `ELLIE_API_TOKEN`;
  endpoint in `compiler.yaml`).
- **Model allowlist.** Ellie contains many models; only explicitly registered,
  validated domain models are ingested. The registry lives in `compiler.yaml`, keyed
  by Ellie's model ID — nothing is fetched that is not listed:

  ```yaml
  ellie:
    base_url: https://<org>.ellie.ai/api/v1
    models:
      - id: 1234                # Ellie model ID (authoritative selector)
        scheme_slug: sales      # assigned once; recorded in the ID map
        label: "Sales domain model"
      - id: 1287
        scheme_slug: finance
        label: "Finance domain model"
  ```

  The compiler fails the run (rather than skipping silently) if a listed model ID is
  not found or not accessible, and the run report lists each model's ID, name as
  returned by the API, and object counts — so a model swapped or renamed in Ellie is
  visible to the reviewer. Removing a model from the allowlist removes its
  `skos:ConceptScheme` and the corresponding `skos:inScheme` triples — but because the
  same Ellie entity can be referenced in multiple models, an object is deprecated only
  if it no longer appears in **any** registered model (deprecation is always evaluated
  against the union of all fetches, per 5.3). An object that remains in other models
  simply loses one scheme membership, identity and statements intact. The run report
  flags both cases prominently, since delisting is expected to be rare and deliberate.
- Fetches, per registered model: entities (id, name, description), attributes
  (id, name, description, parent entity id), relationships (id, name/verb, source and
  target entity ids).
- Mapping: entity → `sem:Entity`; attribute → `sem:Attribute` + `sem:attributeOf`;
  relationship → `sem:Relationship` node + `sem:source`/`sem:target` + one
  `sem:relatesTo` shortcut triple; each registered model → `skos:ConceptScheme`
  (`sem:schemeType "glossary"`, IRI from `scheme_slug`) + `skos:inScheme` for its
  members.
- Ellie descriptions become `skos:definition`. Empty descriptions emit **no**
  `skos:definition` triple (SHACL reports them; see 7 — warning, not error, in v1).
- An entity appearing in multiple domain models must resolve to the **same** Ellie
  UUID (Ellie's cross-model reuse); the compiler merges statements onto one node with
  multiple `skos:inScheme` triples. If two distinct UUIDs carry the same name, they
  remain two nodes — flagged in the run report for stewards.

**Excel taxonomy adapter (v1).**

- Input: one workbook per taxonomy under `sources/taxonomies/`, registered in
  `compiler.yaml` with: file path, scheme slug, scheme label, target entity IRI (for
  `sem:enumerates`, optional), and whether the `code` column is id-stable.
- Expected sheet format (first sheet, header row required):

  | Column | Required | Maps to |
  |---|---|---|
  | `code` | yes | `skos:notation` |
  | `label` | yes | `skos:prefLabel` |
  | `parent_code` | no (empty = top concept) | `skos:broader` |
  | `description` | no | `skos:definition` |
  | `id` | only if codes are not stable | identity key for UUIDv5 minting |

- Rows with a `parent_code` that matches no row → compile error.
- Cycles in the hierarchy → compile error.
- Duplicate codes → compile error.

### 5.3 Identity management

**`mappings/id-map.csv`** — append-only registry, columns:
`iri, kind, source_system, source_key, first_seen, note`.

- On every run, each normalized object is looked up by `(source_system, source_key)`.
  Hit → reuse IRI. Miss → mint per 3.4, append a row.
- The ID map, not the minting formula, is authoritative. This makes identity survive
  code renames, file moves, and even changes to the minting rules.
- CI fails if a run would produce an IRI collision (two source keys → one IRI) or
  remove a row.

**`mappings/merges.csv`** — hand-maintained register, columns:
`deprecated_iri, replaced_by_iri, date, note`. When stewards merge two concepts in a
source tool (which usually just deletes one), they add a row here; the compiler then
emits the deprecation + `dcterms:isReplacedBy` statements instead of a bare
deprecation. Validated: both IRIs must exist in the ID map.

**Deprecation detection.** Deprecation is evaluated against the **union of all
configured sources** in the current run — never against a single source or model. An
object present in the previous generated output (and in the ID map) but absent from
that union is re-emitted with `sem:status "deprecated"` and all its last-known
statements preserved. An object that merely disappeared from one model or source
while remaining in another loses only the corresponding `skos:inScheme` (or other
source-specific) statements. Deprecated nodes are carried forward on subsequent
runs. They are never physically removed. Consequently, a run scoped with
`--source <name>` must not perform deprecation for objects owned by other sources;
partial runs skip deprecation for anything outside the fetched scope.

### 5.4 Canonical serialization

Deterministic output is a hard requirement — it is what makes PR diffs reviewable.
`rdflib`'s default Turtle serializer is **not** deterministic; the compiler must
implement (or vendor) a canonical serializer with these rules:

1. Fixed prefix block (exactly the prefixes of 3.1, in that order), even if unused.
2. Subjects sorted lexicographically by IRI; each subject serialized as one block.
3. Within a subject: `a` (rdf:type) first, then `skos:prefLabel`, then remaining
   predicates sorted lexicographically by IRI; multiple objects per predicate sorted
   lexicographically.
4. One triple per line; two-space indentation; `;` continuation style as in 3.6.
5. UTF-8, LF line endings, newline at EOF. No comments in generated files.
6. Language tags always present on `skos:prefLabel`/`skos:definition` (default `@en`;
   configurable per installation in `compiler.yaml`).

CI's determinism check recompiles from a cached fetch snapshot and requires
byte-identical output (see 7).

### 5.5 Run report

Every run writes `generated/.report.md` (overwritten): counts per class and per file,
new/changed/deprecated objects, objects missing definitions, same-name/different-IRI
warnings. The compile workflow pastes this into the PR description — it is the
reviewer's summary.

---

## 6. Validation (CI)

`validate.yml` runs on every PR and on main. Steps, all blocking unless noted:

1. **Syntax**: every `.ttl` parses (rdflib).
2. **Manifest integrity**: `generated/*` hashes match `.manifest.json` (blocks hand
   edits to generated files).
3. **SHACL** (`pyshacl`, shapes in `shapes/`):
   - Every `sem:Entity` / `sem:Attribute` / taxonomy concept: exactly one
     `skos:prefLabel` per language; at least one `skos:inScheme`; `sem:status`
     present with an allowed value.
   - `skos:definition` present — **warning** in v1 (reported, not blocking),
     switched to blocking when steward workflows are ready.
   - `sem:Attribute` has exactly one `sem:attributeOf`; `sem:Relationship` has
     exactly one `sem:source` and one `sem:target`, both `sem:Entity`.
   - `skos:broader` only between concepts in the same taxonomy scheme; no cycles.
   - `skos:notation` unique within a scheme.
   - Deprecated nodes: no incoming `skos:broader`/`sem:attributeOf` from active nodes.
   - IRI policy: all subject IRIs under the reserved namespaces; local names match
     the expected patterns (UUID / slug).
4. **Identity checks**: ID map is append-only vs. the base branch; no collisions;
   every subject IRI in `generated/` exists in the ID map.
5. **Determinism**: re-serialize the parsed graphs with the canonical serializer;
   output must be byte-identical to the committed files.

`compile.yml` runs on a weekday schedule and on manual dispatch: executes the
compiler against live sources, and if `generated/` or `mappings/` changed, opens a PR
(branch `compile/<date>`) with the run report as description. It never pushes to main.
Branch protection on main: PRs only, validation must pass, at least one review.

---

## 7. Governance rules (operating agreement)

1. Generated files are never edited by hand; content fixes go to Ellie or the Excel
   files, then recompile.
2. Overlays are the only hand-written RDF; they may add statements about generated
   IRIs but never redefine `skos:prefLabel`, `sem:status`, or scheme membership of a
   generated node (SHACL-enforced).
3. Merges of concepts require a `merges.csv` entry in the same PR.
4. Review responsibility follows the file: domain files are reviewed by that domain's
   steward; `mappings/` and `shapes/` changes by the repo owner.
5. Tag main after meaningful merges (`vYYYY.MM.DD`); tags are the citable snapshots
   of the organization's semantics.

---

## 8. Extension points (design obligations on v1)

- **Collibra adapter**: will map glossary items (business concepts → `sem:Entity`
  statements merged onto existing IRIs via a `sem:collibraId` source key; business
  attributes → `sem:Attribute`; business terms → `sem:BusinessTerm`) and term–asset
  links (→ `sem:isAbout`). v1 obligations: adapter interface stays source-agnostic;
  the internal model already carries a generic `source_refs: dict[str, str]`;
  cross-source merging happens on IRI after identity resolution.
- **Knowledge Catalog adapter**: asset entries (→ `a:` namespace, `tech:` classes to
  be added to the ontology), entry links (→ `sem:isAbout`/`sem:represents`). Requires
  concept IRIs to be carried in KC terms (aspect or entry ID) — an obligation on
  whichever component provisions KC's glossary.
- **Documents**: `d:` namespace, `schema:CreativeWork`, links via `sem:isAbout`,
  likely sourced from overlay files first and an automated classifier later.
- **Publishing**: a `publish.yml` triggered on main → package `generated/` + `overlays/`
  → deliver to the serving environment (e.g., GCS bucket consumed by a loader). The
  repo layout requires no changes for this.

---

## 9. Open decisions (to resolve before implementation)

| # | Decision | Default if not decided |
|---|---|---|
| 1 | Final base IRI domain | `semantics.example.com` placeholder blocks first mint — must be decided |
| 2 | Default language tag(s); multilingual labels needed? | `@en` only |
| 3 | Initial contents of the Ellie model allowlist (model IDs of validated domain models) | Empty — models added one by one as they are validated |
| 4 | Definition coverage: when does the missing-definition warning become blocking | After pilot review |
| 5 | Repo visibility & steward review assignments (CODEOWNERS) | Repo owner reviews all |
| 6 | Ellie API rate limits / pagination specifics | Verify against Ellie API docs at build time |

# Semprini — implementation specification

**Status:** Draft v0.2 · **Author:** Juha Korpela / Datakor · **Date:** August 2026

**Changes from v0.1:** the specification now describes a reusable, openly licensed
product deployed many times, rather than a single organization's repository. The
metamodel namespace is fixed and vendor-neutral (3.1); repository layout splits into a
product repository and instance repositories (4); the compiler becomes an installable
package with plugin adapters (5.1, 5.2); versioning, licensing and project governance
are specified (7, 8, 9.2).

**Naming:** the project is called **Semprini**. It was previously "RDF Knowledge
Plane"; the package, CLI, entry-point group, configuration file and metamodel namespace
all follow the new name. *Knowledge plane* remains the architectural term for what
Semprini is — a shared semantic layer over an organization's data — and is used as such
throughout. The `sem:` prefix is unchanged.

---

## 1. Purpose

This document specifies **Semprini**: an openly licensed knowledge-plane toolchain for
turning an organization's semantic content — business concepts, their relationships,
and taxonomies — into versioned, validated RDF held in Git.

It has two parts:

1. **The plane** (this project) — a Python package (the compiler), a metamodel
   ontology, SHACL shapes, CI workflow templates, and an instance scaffold. Developed
   once, released under an open licence (8), and reused by every deployment.
2. **An instance** — one organization's own Git repository, created from the scaffold,
   containing only that organization's configuration, source files, identity registry
   and generated RDF. Each instance is independent: its own IRIs, its own review
   process, its own release cadence.

Instance contents are consumed downstream by graph-serving components (e.g. loading
into a triple store for AI-agent access). Downstream publishing is **out of scope**;
the contract ends at *validated TTL files on an instance's main branch*.

This document is self-contained: no other background material is required to
implement it.

### 1.1 Deployment model

| | The plane repository | An instance repository |
|---|---|---|
| Contains | compiler package, metamodel ontology, core SHACL shapes, workflow templates, instance scaffold, test fixtures | `config/`, `sources/`, `mappings/`, `generated/`, `overlays/`, `shapes/local/`, two thin workflows |
| Owned by | the project (open source) | the adopting organization |
| Versioned by | semantic versioning + released tags (7) | content changes; pins a plane version |
| Holds credentials | never | yes (its own source-system tokens) |
| Count | one | many, unrelated to each other |

An instance depends on the plane the way any project depends on a library: it installs
a **pinned release** and upgrades deliberately (7). It never vendors or forks the
compiler; it never edits core shapes. Everything an organization needs to change is
configuration, source content, overlays, or local shapes.

### 1.2 Design principles

- **Sources are masters; the instance repo is the record.** Semantic content is
  authored in source tools. Generated content is never edited by hand — corrections go
  to the source, then the compiler regenerates.
- **Identity is permanent and opaque.** Every semantic object has an IRI that never
  changes and never encodes mutable facts (names, domains, codes).
- **Diffs are the governance interface.** Every content change arrives as a pull
  request whose diff is human-reviewable. This requires deterministic serialization
  (5.5).
- **Validation is automated.** CI enforces the metamodel with SHACL and structural
  checks on every PR (6).
- **The metamodel is shared; content is sovereign.** One vocabulary describes every
  deployment (3.1), so tools and queries written once work everywhere. All content IRIs
  live in namespaces the adopting organization controls.
- **No lock-in.** The plane depends on no vendor-hosted service. It emits no
  telemetry and makes no network calls other than to the source systems an instance
  explicitly configures. All logic lives in the CLI; CI platforms are interchangeable
  (6.3). An organization that stops using the plane keeps working RDF and a complete
  identity registry.
- **Extension without forking.** New source systems arrive as plugin adapters (5.2);
  organization-specific semantics arrive as local extensions (3.6) and local shapes
  (6.1) — neither requires a change to this project.

---

## 2. Scope

### In scope (v1)

- Metamodel: RDF classes, properties, IRI policy, lifecycle rules
- Instance repository structure, file conventions, canonical serialization rules
- Compiler: packaging, CLI, adapter plugin interface, merge, emit
- Bundled adapters: Ellie API, Excel taxonomy files
- Identity management (IRI minting, the persistent ID map, the namespace lock)
- Core SHACL shapes and CI validation, with portable workflow templates
- Instance bootstrap (`semprini init`) and compile orchestration producing pull requests
- Versioning, compatibility and migration policy; licensing; project governance

### Out of scope (v1) — designed-for extension points

- Collibra and Google Cloud Knowledge Catalog adapters (see 10)
- Document isaboutness links
- Publishing to GCS / triple-store loading / serving APIs
- Any UI
- Cross-instance federation (each deployment stands alone in v1)

---

## 3. Metamodel

### 3.1 Namespaces and prefixes

Namespaces divide into two groups, and the division is the reason a single
implementation can serve many deployments.

**Fixed — identical in every deployment, owned by this project:**

| Prefix | Namespace | Use |
|---|---|---|
| `sem:` | `https://w3id.org/semprini/ontology#` | Metamodel classes and properties |

The metamodel namespace is served through **w3id.org**, a community-maintained
permanent-identifier service, so that resolution does not depend on any single
organization's domain remaining registered. It is versioned independently of the
compiler (7) and is never rewritten per deployment: an agent, query or SHACL shape
written against `sem:` works against every instance.

**Per-instance — chosen once at bootstrap, owned by the adopting organization:**

| Prefix | Namespace | Use |
|---|---|---|
| `c:` | `{base}concepts/` | Entities, attributes, terms |
| `r:` | `{base}relationships/` | Reified relationships |
| `sch:` | `{base}schemes/` | Glossaries & taxonomies (as schemes) |
| `v:` | `{base}values/` | Taxonomy value nodes |
| `x:` | `{base}ext#` | The organization's own extension terms (3.6) |

`{base}` is the instance's base IRI (e.g. `https://semantics.acme.com/`), set in
`config/semprini.yaml` and frozen by the namespace lock (3.4). **Once minted, IRIs are
permanent** — the domain must be one the organization controls and intends to keep.

**Reused standard namespaces:** `skos:`
(`http://www.w3.org/2004/02/skos/core#`), `dcterms:` (`http://purl.org/dc/terms/`),
`xsd:` (`http://www.w3.org/2001/XMLSchema#`).

Reserved for later versions (declare now, use later): `a:` (`{base}assets/`) for
technical data objects, `d:` (`{base}docs/`) for documents.

The instance IRI space is partitioned by **kind of thing** (immutable), never by
business domain (mutable). Domain membership is expressed as data (`skos:inScheme`).

### 3.2 Classes

| Class | Subclass of | Represents | Source (v1) |
|---|---|---|---|
| `sem:Entity` | `skos:Concept` | Business entity / concept ("Customer") | Ellie entity |
| `sem:Attribute` | `skos:Concept` | Attribute with own identity ("Customer number") | Ellie attribute |
| `sem:Relationship` | — | Named relationship between two entities | Ellie relationship |
| `sem:BusinessTerm` | `skos:Concept` | Free-form glossary term | *(adapter-supplied, later)* |
| `skos:ConceptScheme` | — | A domain glossary **or** a taxonomy | Ellie domain model; Excel file |
| `skos:Concept` (plain, in a taxonomy scheme) | — | Taxonomy value node ("Drills") | Excel row |

Notes:

- Attributes are first-class nodes (not RDF properties) because source tools give
  them identity, definitions, and ownership.
- Relationships are reified (own node) because they carry a name/verb and identity.
  The compiler additionally emits a shortcut triple (`sem:relatesTo`) between the two
  entities for cheap traversal.
- Taxonomy value nodes are plain `skos:Concept`s; their nature is indicated by
  membership in a taxonomy-typed scheme (3.4).

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
| `sem:sourceRef` | any → `xsd:string` | Repeatable. Origin of the node, as `"<source-name>:<source-key>"` |
| `sem:schemeType` | `skos:ConceptScheme` → `xsd:string` | `"glossary"` \| `"taxonomy"` |
| `sem:isAbout` | *(reserved, later)* technical object → concept | Semantic linking ("isaboutness") |
| `sem:represents` | *(reserved, later)* column → attribute | Precise linking subproperty |

`sem:sourceRef` deliberately carries no vendor name. v0.1 defined a `sem:ellieId`
property; a shared, openly licensed metamodel must not name one commercial tool, and a
deployment that never uses Ellie should not inherit a dangling term. The value pairs
the instance-configured **source name** with the key that source uses — exactly the
`(source_system, source_key)` pair the ID map is keyed by (5.4) — so multi-source
nodes simply carry several `sem:sourceRef` triples, and identity resolution and RDF
tell the same story.

**Reused standard properties:**

- `skos:prefLabel` (exactly one per node, per language), `skos:altLabel` (synonyms)
- `skos:definition` — definition text
- `skos:inScheme`, `skos:topConceptOf`, `skos:hasTopConcept` — scheme membership
- `skos:broader` / `skos:narrower` — taxonomy hierarchy (only inside taxonomy schemes)
- `skos:notation` — business code of a taxonomy value (e.g. `"PT"`)
- `skos:exactMatch`, `skos:broadMatch` — cross-scheme alignment (e.g. to industry
  taxonomies, or to another instance's concepts)
- `dcterms:isReplacedBy` — deprecated node → successor
- `dcterms:modified` — last content change (`xsd:date`), set by the compiler. Updated
  **only when the node's other statements change**; otherwise carried forward from the
  previous generated output, so that a no-op run produces no diff (5.5).

### 3.4 IRI policy

1. **Opaque IRIs.** No names, codes, or domains in IRIs. Labels live in
   `skos:prefLabel`, codes in `skos:notation`, domain membership in `skos:inScheme`.
2. **Minting:**
   - Objects whose source provides a stable UUID → `c:{uuid}` / `r:{uuid}` (the source
     UUID is used directly as the IRI local name; it is already opaque and stable).
   - Schemes → `sch:{slug}` where the slug is assigned **once** at scheme creation and
     recorded in the ID map; treat it as opaque thereafter (renaming the glossary does
     not change the slug).
   - Objects with no source UUID (e.g. taxonomy values) → `v:{uuid5}` where
     `uuid5 = UUIDv5(NAMESPACE_SEMPRINI, scheme-slug + "|" + source-row-key)`. The
     source-row-key is the taxonomy code column if codes are declared stable for that
     file, otherwise an explicit `id` column that maintainers must add. The resulting
     mapping is **persisted in the ID map** (5.4), which is authoritative from then on:
     if a code later changes, the ID map preserves the original IRI.
3. **IRIs are never deleted or reused.** Removal from a source marks the node
   `sem:status "deprecated"`; merges add `dcterms:isReplacedBy`.
4. **The base IRI is frozen by a namespace lock.** At bootstrap the compiler writes
   `mappings/namespace.lock` (JSON: base IRI, instance id, ontology version, date). On
   every subsequent run it compares the lock to `config/semprini.yaml` and **aborts** on
   mismatch. Without this, an edited base IRI would silently mint a parallel set of
   IRIs alongside an ID map still holding the old ones. Changing it is a migration, not
   a configuration edit: it requires `--force-namespace-change`, which rewrites the ID
   map and every generated file in one reviewable commit and is expected to be a
   once-ever event.

### 3.5 Lifecycle rules

| Event in source | Effect in RDF |
|---|---|
| Object renamed | `skos:prefLabel` changes; IRI unchanged |
| Object moved between domains/schemes | `skos:inScheme` changes; IRI unchanged |
| Object deleted in source | Node retained, `sem:status "deprecated"`; compiler stops updating it |
| Two objects merged in source | Surviving node stays active; the other becomes deprecated with `dcterms:isReplacedBy` → survivor (requires an entry in the merge register, 5.4, because sources typically just delete one object) |
| Taxonomy value code changed | `skos:notation` changes; IRI unchanged (via ID map) |

### 3.6 Local extension by adopters

An organization will eventually need a class or property the metamodel does not
define. It must be able to add one without forking this project.

1. **Local terms live in the instance's own `x:` namespace** (3.1), are declared in
   `overlays/`, and are the organization's to change.
2. **Core `sem:` terms are never redefined, narrowed, or given new domains/ranges by
   an instance.** A local shape may add constraints to instance data; it may not
   restate what a `sem:` term means. If a `sem:` term is genuinely wrong or missing,
   that is an upstream issue (9.2) — this rule exists so that every instance's data
   still answers to the same shared vocabulary.
3. Local terms **should** relate themselves to core terms where the meaning allows
   (`rdfs:subClassOf sem:Entity`, `rdfs:subPropertyOf sem:isAbout`), so that generic
   queries still reach them.
4. Local shapes live in `shapes/local/` and are **additive only** (6.1).

### 3.7 Example (illustrative)

```turtle
c:7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21 a sem:Entity ;
  skos:prefLabel "Customer"@en ;
  skos:definition "A person or organization that buys our products."@en ;
  skos:inScheme sch:sales ;
  sem:sourceRef "ellie-main:7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21" ;
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
  sem:enumerates c:55aa0c3e-... .   # "Product Category" reference entity

v:9c1f... a skos:Concept ;
  skos:prefLabel "Drills"@en ;
  skos:notation "PT-DR" ;
  skos:broader v:8b0e... ;          # Power tools
  skos:inScheme sch:product-category ;
  sem:status "active" .
```

---

## 4. Repository layouts

### 4.1 The plane repository (this project)

```
semprini/
├── README.md
├── LICENSE                        # Apache-2.0 — code (8)
├── LICENSE-DOCS                   # CC BY 4.0 — ontology, shapes, this spec (8)
├── CHANGELOG.md                   # compiler and ontology versions (7)
├── pyproject.toml                 # Poetry: package metadata, dependencies, adapter entry points
├── poetry.lock                    # committed — reproducible dev and CI environments
├── docs/
│   └── rdf-repo-and-compiler-spec.md   # this document (normative)
├── .github/workflows/             # this repository's own CI — lint, types, tests
├── src/semprini/
│   ├── cli.py                     # the whole CLI surface (5.1)
│   ├── model.py                   # internal model dataclasses
│   ├── identity.py                # ID map, minting, namespace lock
│   ├── serialize.py               # canonical Turtle serializer (5.5)
│   ├── validate.py                # SHACL + structural checks (6.1)
│   ├── migrate/                   # version-to-version migrations (7)
│   ├── adapters/
│   │   ├── base.py                # BaseAdapter — the plugin contract (5.2)
│   │   ├── ellie.py               # bundled (5.3)
│   │   └── excel_taxonomy.py      # bundled (5.3)
│   ├── ontology/
│   │   └── sem.ttl                # the metamodel, versioned (3.1, 7)
│   └── shapes/                    # core SHACL shapes (6.1)
├── templates/instance/            # the scaffold `semprini init` materializes (4.2)
├── workflows/                     # reusable/portable CI definitions for *instances* (6.2, 6.3)
└── tests/
    └── fixtures/acme/             # a complete synthetic instance + golden TTL (6.1)
```

### 4.2 An instance repository

```
<org>-semantics/
├── README.md                  # points to the plane's docs; local stewardship notes
├── generated/                 # compiler output — NEVER hand-edited
│   ├── ontology.ttl               # verbatim copy of the pinned sem: ontology
│   ├── concepts-<scheme>.ttl      # one file per glossary scheme
│   ├── relationships-<scheme>.ttl
│   ├── taxonomy-<scheme-slug>.ttl # one file per taxonomy
│   ├── .manifest.json             # content hashes + pinned versions (6.1)
│   └── .report.md                 # last run report (5.6)
├── overlays/                  # hand-curated TTL — the only human-edited RDF
│   ├── external/                  # imported standard vocabularies (curated subsets)
│   ├── ext/                       # the organization's own x: terms (3.6)
│   └── patches/                   # axioms the sources cannot express
├── sources/
│   └── taxonomies/                # the Excel taxonomy files (committed here)
├── mappings/
│   ├── id-map.csv                 # persistent identity registry (5.4)
│   ├── merges.csv                 # merge register (5.4)
│   └── namespace.lock             # frozen base IRI (3.4)
├── shapes/local/              # additive, organization-specific shapes (6.1)
├── config/
│   └── semprini.yaml                 # instance identity + source configuration (5.1)
└── .github/workflows/
    ├── compile.yml                # ~10 lines; pins the plane version
    └── validate.yml               # ~10 lines; pins the plane version
```

An instance contains **no Python**. `generated/ontology.ttl` is a verbatim copy of the
pinned metamodel, written by the compiler so that downstream consumers can load an
instance from Git alone, without installing the package.

### 4.3 Rules

- Everything under `generated/` is overwritten wholesale on every compiler run. CI
  **fails any PR that edits `generated/` without the compiler** (enforced by
  `generated/.manifest.json`, which records content hashes plus the compiler and
  ontology versions; validation recomputes and compares). The manifest contains **no
  timestamps** — it must be reproducible.
- `overlays/` and `shapes/local/` are written by humans through normal PRs and
  validated against the same core shapes.
- Excel taxonomy files are committed under `sources/taxonomies/` so that a taxonomy
  edit and its generated TTL land in the same PR and are reviewed together.

---

## 5. The compiler

### 5.1 Packaging and CLI

A Python 3.12+ package distributed as **`semprini`** (import name `semprini`),
using `rdflib` for graph construction, `openpyxl` for Excel, `requests` for HTTP
sources, `pyshacl` for validation. It installs from PyPI (or a Git tag) and exposes a
console script:

```
semprini init      --base-iri <IRI> --org <slug> [--dir <path>]   # bootstrap an instance (5.7)
semprini run       [--source <name>] [--dry-run]                  # fetch, compile, write
semprini check                                                    # validate only, no writes
semprini migrate   --to <version>                                 # apply migrations (7)
semprini adapters                                                 # list discovered plugins
semprini version                                                  # compiler + ontology versions
```

All commands operate on the instance repository in the working directory and read
`config/semprini.yaml`. Exit codes are part of the contract, so any CI system can act on
them: `0` success · `1` validation or compile failure · `2` configuration or namespace-lock
error · `3` a configured source was unreachable.

Dependencies, the development environment and releases of the plane itself are managed
with **Poetry**: `pyproject.toml` is a Poetry project built by `poetry-core`, and
`poetry.lock` is committed so local development and CI resolve to identical versions.
This is a project-internal choice with no reach into instances — the published artifact
is a standard wheel, so adopters and instance workflows install it with plain `pip`
(6.2) and never need Poetry.

Pipeline stages for `run`:

```
fetch (per configured adapter)
  → normalize into the internal model (Concept, Attribute, Relationship,
    Scheme, TaxonomyValue)
  → resolve identity (ID map lookup / minting)
  → build rdflib Graphs (one per output file)
  → apply lifecycle rules (diff against previous generated/ state)
  → canonical serialization → write generated/*.ttl + .manifest.json + .report.md
  → update mappings/id-map.csv (append-only)
```

The compiler is **stateless between runs** except for what is in the instance
repository (previous TTL, ID map, namespace lock). It must produce identical results
locally and in CI.

Instance configuration (`config/semprini.yaml`):

```yaml
semprini:
  base_iri: https://semantics.acme.com/
  instance_id: acme
  default_language: en

sources:
  - adapter: ellie              # entry-point name of an installed adapter
    name: ellie-main            # source name — appears in sem:sourceRef and the ID
                                # map; assigned once and NEVER changed or reused
    config:
      base_url: https://acme.ellie.ai/api/v1
      token_env: ELLIE_API_TOKEN
      models:
        - id: 1234
          scheme_slug: sales
          label: "Sales domain model"
        - id: 1287
          scheme_slug: finance
          label: "Finance domain model"

  - adapter: excel-taxonomy
    name: taxonomies
    config:
      files:
        - path: sources/taxonomies/product-category.xlsx
          scheme_slug: product-category
          scheme_label: "Product category taxonomy"
          enumerates: c:55aa0c3e-...      # optional
          codes_are_stable: true
```

Credentials are never written to configuration — an adapter names an environment
variable (`token_env`) and the value comes from the CI platform's secret store or the
operator's shell.

### 5.2 Adapter interface (plugins)

Adapters are **discovered, not imported**. The package declares an entry-point group
`semprini.adapters`; any installed distribution may contribute to it, so a
new source system — proprietary, third-party, or organization-internal — is added by
installing a package and naming it in `config/semprini.yaml`. No fork, no patch to this
project.

```python
class BaseAdapter(ABC):
    name: str  # entry-point name, e.g. "ellie"

    def __init__(self, source_name: str, config: dict, ctx: RunContext): ...

    @abstractmethod
    def fetch(self) -> InternalModel: ...

    def validate_config(self) -> list[Issue]:  # called by `semprini check`
        return []
```

Contract obligations on every adapter, which the core relies on:

- `fetch()` performs **no writes** and no identity minting; it returns normalized
  objects carrying a `source_key` per object. Identity resolution is the core's job.
- Objects carry `source_refs: dict[str, str]`, so the same real-world concept seen by
  two adapters merges onto one IRI after identity resolution.
- Fetch failures raise; they never return partial models silently (exit code `3`).
- An adapter contributes only data — never IRIs in another instance's namespace, and
  never `sem:` terms.

Adapters bundled with the plane are ordinary plugins registered by the same mechanism,
so a third-party adapter is never a second-class citizen.

### 5.3 Bundled adapters (v1)

**Ellie adapter (`ellie`).**

- Reads via Ellie's REST API (token from the environment variable named by
  `token_env`; endpoint in `config/semprini.yaml`).
- **Model allowlist.** Ellie contains many models; only explicitly registered,
  validated domain models are ingested, keyed by Ellie's model ID — nothing is fetched
  that is not listed. The compiler fails the run (rather than skipping silently) if a
  listed model ID is not found or not accessible, and the run report lists each model's
  ID, name as returned by the API, and object counts — so a model swapped or renamed in
  Ellie is visible to the reviewer. Removing a model from the allowlist removes its
  `skos:ConceptScheme` and the corresponding `skos:inScheme` triples — but because the
  same Ellie entity can be referenced in multiple models, an object is deprecated only
  if it no longer appears in **any** registered model (deprecation is always evaluated
  against the union of all fetches, per 5.4). An object that remains in other models
  simply loses one scheme membership, identity and statements intact. The run report
  flags both cases prominently, since delisting is expected to be rare and deliberate.
- Fetches, per registered model: entities (id, name, description), attributes (id,
  name, description, parent entity id), relationships (id, name/verb, source and target
  entity ids).
- Mapping: entity → `sem:Entity`; attribute → `sem:Attribute` + `sem:attributeOf`;
  relationship → `sem:Relationship` node + `sem:source`/`sem:target` + one
  `sem:relatesTo` shortcut triple; each registered model → `skos:ConceptScheme`
  (`sem:schemeType "glossary"`, IRI from `scheme_slug`) + `skos:inScheme` for its
  members.
- Ellie descriptions become `skos:definition`. Empty descriptions emit **no**
  `skos:definition` triple (reported by SHACL as a warning in v1; see 6.1).
- An entity appearing in multiple domain models must resolve to the **same** Ellie
  UUID (Ellie's cross-model reuse); the compiler merges statements onto one node with
  multiple `skos:inScheme` triples. If two distinct UUIDs carry the same name, they
  remain two nodes — flagged in the run report for stewards.

**Excel taxonomy adapter (`excel-taxonomy`).**

- Input: one workbook per taxonomy under `sources/taxonomies/`, registered in
  `config/semprini.yaml` with file path, scheme slug, scheme label, target entity IRI (for
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

### 5.4 Identity management

**`mappings/id-map.csv`** — append-only registry, columns:
`iri, kind, source_name, source_key, first_seen, note`.

- On every run, each normalized object is looked up by `(source_name, source_key)`.
  Hit → reuse IRI. Miss → mint per 3.4, append a row.
- The ID map, not the minting formula, is authoritative. This makes identity survive
  code renames, file moves, changes to the minting rules, and compiler upgrades.
- `source_name` is the name given to a source in `config/semprini.yaml`. Renaming a
  configured source therefore breaks identity resolution; `semprini check` treats a
  `source_name` present in the ID map but absent from configuration as an error, with a
  documented rename procedure that rewrites the column in one reviewable commit.
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
statements preserved. An object that merely disappeared from one model or source while
remaining in another loses only the corresponding `skos:inScheme` (or other
source-specific) statements. Deprecated nodes are carried forward on subsequent runs
and are never physically removed. Consequently, a run scoped with `--source <name>`
must not perform deprecation for objects owned by other sources; partial runs skip
deprecation for anything outside the fetched scope.

### 5.5 Canonical serialization

Deterministic output is a hard requirement — it is what makes PR diffs reviewable, and
it is the property that lets an instance trust a compiler upgrade. `rdflib`'s default
Turtle serializer is **not** deterministic; the compiler implements its own with these
rules:

1. Fixed prefix block (the namespaces of 3.1 in that order), even if unused.
2. Subjects sorted lexicographically by IRI; each subject serialized as one block.
3. Within a subject: `a` (rdf:type) first, then `skos:prefLabel`, then remaining
   predicates sorted lexicographically by IRI; multiple objects per predicate sorted
   lexicographically — IRIs before literals, literals by lexical form, then language
   tag, then datatype, so that a mixed-object predicate has one defined order too.
4. One triple per line; two-space indentation; `;` continuation style as in 3.7. A
   predicate with several objects **repeats the predicate**, one object per line, rather
   than joining them with `,` — one changed fact must be one changed line. Subject
   blocks are separated by a single blank line.
5. UTF-8, LF line endings, newline at EOF. No comments in generated files.
6. Language tags always present on `skos:prefLabel`/`skos:definition` (default `@en`;
   set per instance in `config/semprini.yaml`).
7. **No blank nodes in generated output.** Every node the compiler emits has an IRI.
   Blank-node labels are not stable across runs and would defeat the determinism check;
   any construct that would need one must instead use a deterministically minted IRI
   (3.4).
8. No run timestamps anywhere in generated output — `dcterms:modified` reflects
   content change only (3.3).

Terms are written the one way the rules allow: prefixed where the local name needs no
escaping and the full `<IRI>` otherwise, `a` for `rdf:type`, and literals as single-line
quoted strings with control characters escaped. An `xsd:string` literal is written in the
plain form — and written only once, since the two are the same RDF term and writing them
differently, or twice, would make two equal graphs produce two different files. A
character an `<IRI>` cannot carry raw is written as its `\uXXXX` escape rather than
emitted verbatim, so a malformed IRI from a source never produces a file that will not
parse.

CI's determinism check recompiles from a cached fetch snapshot and requires
byte-identical output (6.1).

### 5.6 Run report

Every run writes `generated/.report.md` (overwritten): compiler and ontology versions,
counts per class and per file, new/changed/deprecated objects, objects missing
definitions, same-name/different-IRI warnings, and per-source fetch summaries. The
compile workflow pastes this into the PR description — it is the reviewer's summary.

### 5.7 Bootstrapping an instance

`semprini init --base-iri https://semantics.acme.com/ --org acme`:

1. Materializes `templates/instance/` into the target directory (4.2).
2. Writes `config/semprini.yaml` with the base IRI, instance id and default language, and
   an empty `sources:` list.
3. Writes `mappings/namespace.lock` (3.4) and empty `id-map.csv` / `merges.csv` with
   headers.
4. Writes `generated/ontology.ttl` (the pinned metamodel) and a manifest.
5. Writes the two workflow stubs, pinned to the plane version that produced them.
6. Prints the required secrets and the next steps; makes **no** network calls and
   creates no remote repository.

The command refuses to run in a directory that already contains a `namespace.lock`.

---

## 6. Validation and CI

### 6.1 Checks

All checks are implemented in `semprini check` — CI invokes the CLI and nothing else (6.3).
Steps, all blocking unless noted:

1. **Syntax**: every `.ttl` parses (rdflib).
2. **Manifest integrity**: `generated/*` hashes match `.manifest.json` (blocks hand
   edits to generated files).
3. **Version drift**: the compiler and ontology versions recorded in `.manifest.json`
   match the versions actually running. This makes a plane upgrade a deliberate,
   separately reviewable "recompile with `<version>`" PR rather than a surprise reflow
   of every file mixed into a content change (7).
4. **Namespace lock**: `config/semprini.yaml`'s base IRI matches `mappings/namespace.lock`
   (3.4); every generated subject IRI falls under it.
5. **SHACL** (`pyshacl`), core shapes from the package plus every shape in
   `shapes/local/`:
   - Every `sem:Entity` / `sem:Attribute` / taxonomy concept: exactly one
     `skos:prefLabel` per language; at least one `skos:inScheme`; `sem:status` present
     with an allowed value.
   - `skos:definition` present — **warning** in v1 (reported, not blocking), switched
     to blocking per instance when steward workflows are ready.
   - `sem:Attribute` has exactly one `sem:attributeOf`; `sem:Relationship` has exactly
     one `sem:source` and one `sem:target`, both `sem:Entity`.
   - `skos:broader` only between concepts in the same taxonomy scheme; no cycles.
   - `skos:notation` unique within a scheme.
   - Deprecated nodes: no incoming `skos:broader`/`sem:attributeOf` from active nodes.
   - IRI policy: subject IRIs under the instance's namespaces; local names match the
     expected patterns (UUID / slug).
   - Overlays may add statements about generated IRIs but never redefine
     `skos:prefLabel`, `sem:status`, or scheme membership of a generated node.
   - **Local shapes are additive only**: a shape in `shapes/local/` that targets a
     `sem:` term and weakens a core constraint is rejected. Local shapes constrain
     instance data; they cannot license data the core shapes forbid.
6. **Identity checks**: ID map is append-only versus the base branch; no collisions;
   every subject IRI in `generated/` exists in the ID map; every `source_name` in the
   ID map is configured (5.4).
7. **Determinism**: re-serialize the parsed graphs with the canonical serializer;
   output must be byte-identical to the committed files.

The plane's own test suite runs the same checks against `tests/fixtures/acme/` — a
complete synthetic instance with a mocked source API and sample workbook, plus golden
TTL. Any change to the serializer or metamodel that alters output shows up there as a
reviewable diff, which is what makes the determinism guarantee (5.5) auditable by
adopters rather than merely asserted.

### 6.2 Workflows

Each instance has two workflows, both thin:

- **`validate.yml`** — on every PR and on main: install the pinned plane version, run
  `semprini check`.
- **`compile.yml`** — on a schedule and on manual dispatch: install the pinned plane
  version, run `semprini run`, and if `generated/` or `mappings/` changed, open a PR (branch
  `compile/<date>`) with `generated/.report.md` as the description. It never pushes to
  main.

Branch protection on an instance's main: PRs only, validation must pass, at least one
review.

### 6.3 Portability

**Every check and every side effect lives in the CLI.** Workflow files only install
the package, run a command, and (for `compile.yml`) open a PR. Consequences:

- An adopter on GitLab, Azure DevOps or on-prem Bitbucket ports the plane by
  contributing a YAML file, not by reimplementing logic.
- `semprini check` behaves identically on a developer's laptop and in CI, so failures are
  reproducible locally.
- The plane depends on no GitHub-only feature for correctness; PR creation is the one
  platform-specific step, isolated in the workflow layer.

---

## 7. Versioning and compatibility

Adopters upgrade on their own schedule, so compatibility is a published contract.

**Two version numbers.**

- **Compiler version** — semantic versioning of the `semprini` package.
- **Ontology version** — the `sem:` metamodel's own version (`owl:versionInfo` in
  `sem.ttl`), incremented independently. A metamodel change is breaking for adopters
  even when the Python API is untouched.

Both are recorded in `generated/.manifest.json` and enforced by the drift check (6.1).

**Change classes.**

| Change | Compiler | Ontology | Adopter impact |
|---|---|---|---|
| Bug fix, no output change | patch | — | upgrade freely |
| New optional feature, output unchanged for existing config | minor | — | upgrade freely |
| New `sem:` term, nothing existing altered | minor | minor | upgrade freely; new term appears when used |
| Serialization change (reflows files) | major | — | deliberate recompile PR; diff is large but content-neutral |
| `sem:` term removed, renamed, or given new meaning | major | major | migration required |
| IRI minting rule change | major | — | none, if the ID map is honoured (5.4) |

**Migrations.** A release that changes emitted output ships a migration invoked by
`semprini migrate --to <version>`, which rewrites `generated/` (and, where necessary, the ID
map) deterministically in one commit. An upgrade is therefore always reviewable: the
adopter sees a migration diff, not an unexplained reflow. Migrations never mint new
IRIs for existing objects and never remove ID-map rows.

**Support policy.** The current major version receives fixes; the previous major
receives migrations only. The metamodel namespace itself never changes — versioning
happens inside the ontology document, so IRIs minted in 2026 still resolve unchanged.

---

## 8. Licensing

The project is released as two artifact classes, licensed by convention for their kind:

| Artifact | Licence | Rationale |
|---|---|---|
| Compiler, adapters, CLI, workflow templates, scaffold | **Apache-2.0** | permissive with an explicit patent grant — the expectation of enterprise legal review |
| `sem:` metamodel ontology, core SHACL shapes, this specification | **CC BY 4.0** | vocabularies are documents, not programs; adopters must be able to quote and extend terms in their own documentation and derived vocabularies, as SKOS, Dublin Core and schema.org allow |

Both licences are carried in the repository (`LICENSE`, `LICENSE-DOCS`) and the split
is stated in `README.md`, since a single top-level `LICENSE` would otherwise be read as
governing the vocabulary too. The copyright holder for both is **Datakor Consulting
Oy**, named in the notice of each licence file and in the package metadata.

**Content produced by an instance is the adopting organization's own**, under no
licence from this project. Nothing in the generated RDF carries an obligation back to
the plane; only the `sem:` terms it references are project artifacts, and CC BY permits
their use with attribution.

---

## 9. Governance

### 9.1 Instance operating agreement

Each deployment adopts these rules; they are what the CI checks enforce.

1. Generated files are never edited by hand; content fixes go to the source system,
   then recompile.
2. Overlays are the only hand-written RDF; they may add statements about generated
   IRIs but never redefine `skos:prefLabel`, `sem:status`, or scheme membership of a
   generated node (SHACL-enforced, 6.1).
3. Organization-specific terms go in the instance's `x:` namespace; core `sem:` terms
   are never redefined locally (3.6).
4. Merges of concepts require a `merges.csv` entry in the same PR.
5. Plane upgrades are their own PR, never mixed with content changes (7).
6. Review responsibility follows the file: scheme files are reviewed by that domain's
   steward; `mappings/`, `shapes/local/` and `config/` by the repository owner.
7. Tag main after meaningful merges (`vYYYY.MM.DD`); tags are the citable snapshots of
   the organization's semantics.

### 9.2 Project governance

1. **The metamodel is the compatibility surface.** Additions are welcomed under 7;
   removals and redefinitions are major events requiring a migration.
2. **Adapters do not need to be upstreamed.** The plugin interface (5.2) exists so
   that an organization or vendor can ship an adapter independently, under any licence.
   Bundled adapters are those the project commits to maintaining and testing.
3. **A local extension that recurs across adopters is a candidate for the core.** The
   `x:` namespace convention (3.6) is deliberately the low-friction path; promotion to
   `sem:` is the considered one.
4. **Determinism and identity permanence are non-negotiable.** A contribution that
   makes output non-reproducible, introduces blank nodes into generated files, or
   changes existing objects' IRIs will not be accepted regardless of other merit.
5. Instances are never named in this repository, and no instance's content is used as
   a test fixture — `tests/fixtures/` is synthetic (6.1).

---

## 10. Extension points (design obligations on v1)

- **Collibra adapter**: maps glossary items (business concepts → `sem:Entity`
  statements merged onto existing IRIs via `sem:sourceRef`; business attributes →
  `sem:Attribute`; business terms → `sem:BusinessTerm`) and term–asset links (→
  `sem:isAbout`). v1 obligations: the adapter interface stays source-agnostic; the
  internal model already carries generic `source_refs`; cross-source merging happens on
  IRI after identity resolution.
- **Knowledge Catalog adapter**: asset entries (→ `a:` namespace, technical classes to
  be added to the ontology), entry links (→ `sem:isAbout`/`sem:represents`). Requires
  concept IRIs to be carried in KC terms (aspect or entry ID) — an obligation on
  whichever component provisions KC's glossary.
- **Documents**: `d:` namespace, `schema:CreativeWork`, links via `sem:isAbout`,
  sourced from overlays first and an automated classifier later.
- **Publishing**: a `publish.yml` triggered on an instance's main → package
  `generated/` + `overlays/` → deliver to the serving environment (e.g. a GCS bucket
  consumed by a loader). Requires no layout change.
- **Cross-instance alignment**: because every instance shares the `sem:` metamodel,
  `skos:exactMatch` between two organizations' concepts is already meaningful. No v1
  mechanism; no v1 obstacle.

---

## 11. Open decisions (to resolve before implementation)

| # | Decision | Default if not decided |
|---|---|---|
| 1 | Register the `w3id.org/semprini` namespace (PR to the w3id.org repository); ~~confirm the redirect target that will host the ontology~~ | **Blocks the first release** — the metamodel namespace must resolve before any instance mints IRIs against it. Redirect target **resolved:** the project's own published site, so resolution depends on no domain beyond w3id.org itself (3.1); registration still outstanding |
| 2 | ~~Confirm Apache-2.0 / CC BY 4.0 (8), or choose AGPL for the code if hosted-service competition is a concern~~ | **Resolved:** Apache-2.0 + CC BY 4.0, copyright Datakor Consulting Oy (8) |
| 3 | Distribution channel: PyPI, or Git tags only at first | PyPI once the interface is stable; Git tags until then |
| 4 | Which adapters are bundled versus separately distributed (5.3) | Ellie and Excel bundled; all later adapters evaluated case by case |
| 5 | Default language tag(s); multilingual labels needed? | `@en` only, set per instance |
| 6 | Definition coverage: when the missing-definition warning becomes blocking | per instance, after pilot review |
| 7 | Ellie API rate limits / pagination specifics | verify against Ellie API docs at build time |
| 8 | Whether `semprini init` also creates the remote repository (`gh repo create`) or stays offline | stays offline (5.7) |

Per-instance decisions — base IRI, source allowlist, stewards and CODEOWNERS — are made
at bootstrap by each adopting organization and are deliberately not listed here.

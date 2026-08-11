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
- Bundled adapters: exported Ellie models, Excel taxonomy files
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
- `skos:hiddenLabel` — misspellings and retired names: matched by search, never displayed
- `skos:definition` — definition text
- `skos:scopeNote` — guidance on where a concept's boundaries lie
- `skos:example` — instances that fall under the concept

  `skos:hiddenLabel`, `skos:scopeNote` and `skos:example` may each appear **more than
  once** on a node, unlike `skos:definition`: a concept has *the* definition, whereas two
  sources each contributing an example are not in disagreement, and treating them as
  scalars would fail a run over data that agrees. All three are reused SKOS terms and are
  therefore **not** declared in `sem.ttl` (3.6), so adding them was not an ontology
  version change.

- `skos:inScheme`, `skos:topConceptOf`, `skos:hasTopConcept` — scheme membership
- `skos:broader` / `skos:narrower` — taxonomy hierarchy, and **entity inheritance**

  Two uses, one property, and deliberately so. Inside a taxonomy scheme it is the value
  hierarchy. Between two `sem:Entity` nodes it is specialization as a modelling tool
  states it — "Active customer" is narrower than "Customer" (5.3). A `sem:` term of its
  own would say no more: every entity here is a `skos:Concept`, so the SKOS property
  already means what the modeller drew, and adding one would be a metamodel version bump
  (7) for a fact the vocabulary can already carry.

  Of each inverse pair the compiler emits **one direction only** — `skos:topConceptOf`
  and `skos:broader`, both stated on the narrower node. The inverse says the same fact a
  second time, in another file (4.2), and one changed fact must be one changed line
  (5.5 rule 4). A consumer that wants the inverses can entail them; a reviewer cannot
  un-see a duplicated diff.

- `skos:notation` — business code of a taxonomy value (e.g. `"PT"`), **when the source
  states one**. Not every taxonomy format carries a code: a ragged workbook (5.3) states
  hierarchy and labels and no notation at all, and deriving one from the row's identity
  key would emit a code no source ever said and that stewards would then have to maintain.
- `skos:exactMatch`, `skos:broadMatch` — cross-scheme alignment (e.g. to industry
  taxonomies, or to another instance's concepts)
- `dcterms:isReplacedBy` — deprecated node → successor
- `dcterms:modified` — last content change (`xsd:date`), set by the compiler. Updated
  **only when the node's other statements change**; otherwise carried forward from the
  previous generated output, so that a no-op run produces no diff (5.5).

### 3.4 IRI policy

1. **Opaque IRIs.** No names, codes, or domains in IRIs. Labels live in
   `skos:prefLabel`, codes in `skos:notation`, domain membership in `skos:inScheme`.
2. **Minting.** The namespace is always the one belonging to the object's *kind* (3.1);
   only the local name varies:
   - Objects whose source provides a stable UUID → `c:{uuid}` / `r:{uuid}` (the source
     UUID is used directly as the IRI local name; it is already opaque and stable). A key
     counts as a UUID only when it is written in the canonical `8-4-4-4-12` form; case is
     normalized to lower case, so that a source which starts reporting the same UUID in
     upper case does not mint a second IRI for one object. A 32-digit code is *not* a
     UUID, and takes the derived path below rather than being read as one.
   - Schemes → `sch:{slug}` where the slug is assigned **once** at scheme creation and
     recorded in the ID map; treat it as opaque thereafter (renaming the glossary does
     not change the slug). A slug is lower-case letters, digits, `-` and `_` — the same
     shape as an instance id or a source name. `Sales` and `sales` would otherwise be two
     permanent IRIs for one taxonomy, and one file in `generated/` on a case-insensitive
     filesystem. Because minting runs **once** per object, the slug is also re-checked on
     every later run, against both the shape above and the local name already frozen in
     the ID map: a slug names the scheme's *file* (4.2) as well as its IRI, and only the
     IRI is protected by the map. Editing `scheme_slug` in configuration would otherwise
     move the file while the IRI stayed where it was, leaving the ID map and the output
     disagreeing about what the scheme is called — and a slug that is not a slug at all,
     such as `../../x`, composes a path outside `generated/` entirely.
   - Objects with no source UUID → `{prefix}:{uuid5}`, derived from the fixed namespace
     `NAMESPACE_SEMPRINI` = `8865c94a-2211-5f26-8887-6d6d5cbaa1e0` — itself
     `UUIDv5(NAMESPACE_URL, "https://w3id.org/semprini/ontology#")`, and **permanent**:
     changing it would re-mint every object first seen after the change while the ID map
     went on holding the old IRIs. The name hashed is
     `scheme-slug + "|" + source-row-key` for a taxonomy value, and
     `source-name + ":" + source-key` for anything else — a taxonomy value is identified
     by its position in a taxonomy, everything else by the source that reported it. The
     source-row-key is the taxonomy code column if codes are declared stable for that
     file, otherwise an explicit `id` column that maintainers must add. The resulting
     mapping is **persisted in the ID map** (5.4), which is authoritative from then on:
     if a code later changes, the ID map preserves the original IRI.
   - A local name that could not be written after a prefix in Turtle — a scheme slug
     containing a space, say — is **rejected** rather than escaped. Escaping would work,
     but the ID map would then freeze an IRI nobody intended.
3. **IRIs are never deleted or reused.** Removal from a source marks the node
   `sem:status "deprecated"`; merges add `dcterms:isReplacedBy`.
4. **The base IRI is frozen by a namespace lock.** At bootstrap the compiler writes
   `mappings/namespace.lock` (JSON: base IRI, instance id, ontology version, date). On
   every subsequent run it compares the lock to `config/semprini.yaml` and **aborts** on
   mismatch. Without this, an edited base IRI would silently mint a parallel set of
   IRIs alongside an ID map still holding the old ones. A **missing** lock aborts the
   same way: deleting the file must not become the way around a permanent decision. Base
   IRI and instance id are what is compared — the recorded ontology version says what the
   instance bootstrapped against, and upgrading the metamodel is the manifest's drift
   check to govern (6.1), not this file's. Changing the base IRI is a migration, not a
   configuration edit: it requires `--force-namespace-change`, which rewrites the ID map
   and every generated file in one reviewable commit and is expected to be a once-ever
   event. Local names survive the move unchanged, so an object keeps its identity and
   changes only the namespace it lives in. The flag moves the **base IRI and nothing
   else**: it is the one invocation that suspends the lock's checks, so an instance id
   that has also drifted is refused rather than re-frozen, and a "move" to the base IRI
   already locked is refused too — it would only discard the record of when the namespace
   was frozen. It cannot be combined with `--source`: the commit would then make two
   claims at once — that every IRI moved, and that some content changed — and a reviewer
   cannot check the first through the second.

   The **merge register moves with the map**, and that is the only circumstance in which a
   compile writes `mappings/merges.csv` (5.4). Its rows are the one place in an instance
   where a person typed an IRI; left behind, every one of them would name an IRI the moved
   map has never heard of, the run would refuse itself, and the migration could not be
   performed at all on an instance that had ever recorded a merge. Rebasing changes no
   decision — a row says the same two objects are one, in the namespace they now live in.

   The move is **computed with the run and written with its output**, map, register and
   lock included, and the map is written before the lock. A move performed up front would leave
   an instance whose map says it has moved and whose `generated/` says it has not the
   moment the compile that follows fails, and that state has no way out: a second
   `--force-namespace-change` is refused as a move to the base IRI already locked, and a
   plain run refuses the old IRIs still in the output. The run **rebases the previous
   generated state** before lifecycle reads it, so nodes already written are recognized as
   the nodes they are — without that, every one of them is an IRI the ID map has never
   heard of (5.4), which at best fails the run and at worst would silently drop every
   deprecated object in the instance. Rebasing is also what keeps `dcterms:modified` still:
   the move changes where an object lives and nothing it says, so the commit is every IRI
   and no dates, and the run report shows nothing new and nothing changed.

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

Abbreviated, as the heading says. Every node the compiler writes carries `sem:sourceRef`,
`sem:status` and `dcterms:modified` — **schemes included**: lifecycle (3.5) applies to
every object, and a scheme is deleted from a source as readily as anything else. Blocks
above that omit them are shortened for reading, not showing an exemption.

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
│   ├── run.py                     # the `semprini run` pipeline, end to end (5.1)
│   ├── config.py                  # config/semprini.yaml loading and validation (5.1)
│   ├── model.py                   # internal model dataclasses
│   ├── identity.py                # ID map, minting, namespace lock
│   ├── build.py                   # internal model → the graphs of generated/ (3.2, 3.3, 4.2)
│   ├── lifecycle.py               # deprecation, carry-forward, merge register (3.5, 5.4)
│   ├── manifest.py                # generated/.manifest.json — hashes and versions (4.3, 7)
│   ├── report.py                  # generated/.report.md — the run report (5.6)
│   ├── serialize.py               # canonical Turtle serializer (5.5)
│   ├── validate.py                # SHACL + structural checks (6.1)
│   ├── testing.py                 # the adapter contract, as a check authors run (5.2)
│   ├── migrate/                   # version-to-version migrations (7)
│   ├── adapters/
│   │   ├── base.py                # BaseAdapter — the plugin contract (5.2)
│   │   ├── discovery.py           # entry-point discovery (5.2)
│   │   ├── ellie.py               # bundled (5.3)
│   │   └── excel_taxonomy.py      # bundled (5.3)
│   ├── ontology/
│   │   └── sem.ttl                # the metamodel, versioned (3.1, 7)
│   └── shapes/                    # core SHACL shapes (6.1)
├── templates/instance/            # the scaffold `semprini init` materializes (4.2)
├── workflows/                     # reusable/portable CI definitions for *instances* (6.2, 6.3)
└── tests/
    └── fixtures/
        ├── acme/                  # a complete synthetic instance + golden TTL (6.1)
        └── dummy-adapter/         # a third-party adapter distribution, as installed (5.2)
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
│   ├── ellie/                     # exported domain models, one JSON per model (5.3)
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
pinned metamodel — copied, never re-serialized, because its term comments are the
vocabulary's published documentation (3.1) and 5.5's comment-free rule governs an
instance's own output. It is written so that downstream consumers can load an instance
from Git alone, without installing the package.

**Partitioning.** Output is partitioned by scheme, and **an object is written exactly
once**: in the file of its lexicographically first scheme, carrying all of its
`skos:inScheme` triples there. Repeating a multi-scheme object into each of its schemes'
files would load to the same graph, but it would make one changed label several changed
hunks, and the diff is the governance interface (1.2). *Lexicographically* first rather
than first reported, so that an adapter's iteration order cannot decide where an object
lives.

The `sem:relatesTo` shortcut (3.2) is the one statement deliberately written away from
the node it is about: it is derived from a relationship and belongs in that
relationship's file, so a reviewer sees the reified node and its shortcut in one hunk. A
subject therefore legitimately spans two files, and `dcterms:modified` (3.3) is decided
from everything the run says about a node across **all** files — never from one file's
share of it, which would refresh the date of every entity that happens to be one end of a
relationship, on every run.

The shortcut is emitted **once per entity pair, not once per relationship**. `sem:relatesTo`
says only *that* two entities are related, so several relationships between one pair
derive the identical triple; it is written in the lexicographically first of their files.
Written per relationship instead, it would appear in two files whenever two relationships
between one pair sat in different schemes — and deleting either one would show a removed
`sem:relatesTo` line for a fact that still holds.

A file with no content is **not written**: a glossary with no relationships produces no
`relationships-<scheme>.ttl` at all, rather than one holding only a prefix block.

**No statement is written into two files**, and the build stage checks it rather than
assuming it. One changed fact must be one changed line, which it stops being the moment a
triple lives in two places; and the check is worth its cost because a run assembles its
files from two kinds of evidence — the model, and the nodes lifecycle retained (3.5) — so
a shortcut the previous run wrote and this one also derives would otherwise reach an
instance as a diff hunk nobody could account for.

### 4.3 Rules

- Everything under `generated/` is overwritten wholesale on every compiler run. CI
  **fails any PR that edits `generated/` without the compiler** (enforced by
  `generated/.manifest.json`, which records content hashes plus the compiler and
  ontology versions; validation recomputes and compares). The manifest contains **no
  timestamps** — it must be reproducible.
- **What the manifest records.** Every file the run writes under `generated/`, the
  ontology copy included, as `<file name>: "sha256:<hex>"` — the algorithm is written into
  each value so that a line means something on its own. The document is a JSON object with
  keys sorted at both levels, indented by two spaces, ending in one LF, and holding exactly
  `compiler_version`, `files` and `ontology_version`; an unknown key is an error, for the
  reason a misspelled configuration key is (5.1). Two files are deliberately **not**
  hashed: the manifest, which cannot contain its own hash, and `.report.md`, which is prose
  about a run rather than governed content and is written on different terms (5.6).
- **A file present but unrecorded fails the check** as surely as an edited one. Otherwise
  an instance accumulates output from a scheme that no longer exists, and a consumer
  loading the directory from Git reads statements no source still makes.
- **A run removes what it did not produce.** "Overwritten wholesale" is a statement about
  the directory, not about each file: output the run did not write is deleted, including
  anything nested, since a consumer reading the tree reads that too. This is safe for a
  `--source X` run as well as a full one, because every object outside the fetched scope is
  carried forward by lifecycle (5.4) and so *is* produced. `.report.md` is the exception —
  it is written only when something moved (5.6), so a run that produced no report has not
  stopped producing the committed one. Removing a file counts as a change, so the run that
  does it rewrites the report.
- **A manifest is never written by an uninstalled compiler.** Run from a source tree the
  package reports version `0.0.0+source`, which identifies no release — two different
  working trees record the same string and the drift check (6.1) passes between them, so
  writing to `generated/` is refused instead (7).
- `overlays/` and `shapes/local/` are written by humans through normal PRs and
  validated against the same core shapes.
- Source files are committed — Excel taxonomies under `sources/taxonomies/`, exported
  Ellie models under `sources/ellie/` — so that a source edit and its generated TTL land
  in the same PR and are reviewed together. This is also why an adapter's configured path
  may not lead outside the repository: a file elsewhere is content nobody reviewed.

---

## 5. The compiler

### 5.1 Packaging and CLI

A Python 3.12+ package distributed as **`semprini`** (import name `semprini`),
using `rdflib` for graph construction, `openpyxl` for Excel, `requests` for HTTP
sources, `pyshacl` for validation and `PyYAML` for configuration. It installs from PyPI
(or a Git tag) and exposes a console script:

```
semprini init      --base-iri <IRI> --org <slug> [--dir <path>]   # bootstrap an instance (5.7)
semprini run       [--source <name>] [--dry-run]                  # fetch, compile, write
                   [--force-namespace-change]                     # move the base IRI (3.4)
semprini check                                                    # validate only, no writes
semprini migrate   --to <version>                                 # apply migrations (7)
semprini adapters                                                 # list discovered plugins
semprini version                                                  # compiler + ontology versions
```

Commands operate on the instance repository in the working directory and read
`config/semprini.yaml` — except `version` and `adapters`, which describe the
*installation* rather than an instance and therefore work outside an instance
repository, and `init`, which writes the configuration the others read. Exit codes are
part of the contract, so any CI system can act on them: `0` success · `1` validation or
compile failure · `2` configuration or namespace-lock error · `3` a configured source
was unreachable. One mapping from error to code serves every subcommand, so a given code
means the same thing whichever one produced it.

Dependencies, the development environment and releases of the plane itself are managed
with **Poetry**: `pyproject.toml` is a Poetry project built by `poetry-core`, and
`poetry.lock` is committed so local development and CI resolve to identical versions.
This is a project-internal choice with no reach into instances — the published artifact
is a standard wheel, so adopters and instance workflows install it with plain `pip`
(6.2) and never need Poetry.

Pipeline stages for `run`:

```
fetch (per configured adapter)
  → normalize into the internal model (Entity, Attribute, Relationship,
    Scheme, TaxonomyValue)
  → apply lifecycle rules (diff against previous generated/ state: what is gone,
    what this run is entitled to judge, what the merge register replaces — 3.5, 5.4)
  → resolve identity (ID map lookup / minting)
  → build rdflib Graphs (one per output file), from the model and the nodes
    lifecycle retained
  → canonical serialization → write generated/*.ttl + .manifest.json + .report.md,
    removing output this run did not produce (4.3)
  → update mappings/id-map.csv (append-only)
```

**Nothing is written until every stage has succeeded.** Fetching, lifecycle, building,
serialization, hashing and the report all complete in memory first, so a source that is
down, a merge register that contradicts itself or a model that cannot be expressed leaves
the instance exactly as it was rather than half-written — there is no state in which
`generated/` describes one run and `mappings/` another. `--dry-run` is then the same
pipeline without its last four lines, which is what makes what it reports worth believing:
the bytes it would have committed are the bytes it computed.

`--source <name>` fetches that source alone and compiles it against the previous state:
every object outside the fetched scope arrives from lifecycle as a retained node (5.4), so
the run still writes the whole directory. The one case that cannot be assembled this way is
an object the ID map records against **two** sources when only one was fetched — the model
holds it rebuilt from half its evidence — and the run refuses it (exit `1`) rather than
choosing between deleting the other source's statements and discarding the update it was
invoked for.

Lifecycle runs **before** the build stage rather than over its output: a deprecated object
is not in the model — no adapter returned it — so there is nothing for a later pass to
edit, and the nodes it retains have to be there when files are assembled and dated. It
reads the ID map and mints nothing; an object new to a run has no IRI yet, and every node
in the previous output has one, which is the asymmetry that makes "absent from the
sources" an answerable question.

The compiler is **stateless between runs** except for what is in the instance
repository (previous TTL, ID map, namespace lock). It must produce identical results
locally and in CI.

The **build** stage refuses (exit `1`), naming the source ref of the offending object,
anything no output could honestly represent: an object in no scheme, in a scheme no
source defined, or in the wrong *kind* of scheme — a taxonomy value in a glossary; a
scheme slug that is malformed or that has been renamed since it was minted (3.4.2); a
cross-reference (`sem:attributeOf`, `sem:source`, `sem:target`, `skos:broader`,
`sem:enumerates`) to something the run did not resolve, that the ID map records as the
wrong *kind* — `sem:enumerates` runs scheme → entity (3.3) — or that resolves to a node
**this run does not write**. The first four decide which *file* an object is written to, so
they cannot be deferred to SHACL validation (6.1); the rest would otherwise reach a
governed file as a triple pointing at nothing, or at the wrong thing.

The last of those is a question about the whole output rather than about one statement,
and is asked once the files are assembled. The ID map answers only whether an IRI was ever
minted, and a row outlives the node — an object whose source was reconfigured away leaves
one behind. What makes the stricter question answerable at all is that both legitimate
sources of a node are in hand by then: the model, and the nodes lifecycle retained. A
relationship may point at an entity no source reports any more, which is exactly what
deprecation-not-deletion is for, and on a `--source X` run most of what a reference points
at is retained rather than compiled.

A dangling `sem:enumerates` is the ordinary case while an instance is being brought up
rather than an exotic one: a workbook names its reference entity by that entity's key in
the modelling tool (5.3), so a taxonomy compiled before the modelling tool's source is
configured has nothing to point at. The message says so.

Every problem the stage can see is reported together, not one per run: these are read in
CI, where one problem per round trip is the difference between one fix and five.

Instance configuration (`config/semprini.yaml`):

```yaml
semprini:
  base_iri: https://semantics.acme.com/
  instance_id: acme
  default_language: en

sources:
  # One Ellie *instance* is one source (5.3): its UUIDs are unique across the instance,
  # so every model exported from it is listed under one source name.
  - adapter: ellie              # entry-point name of an installed adapter
    name: ellie-main            # source name — appears in sem:sourceRef and the ID
                                # map; assigned once and NEVER changed or reused
    config:
      base_url: https://acme.ellie.ai/api/v1   # which Ellie instance these UUIDs are from
      models:                   # the allowlist: nothing outside it is read
        - id: 1234
          path: sources/ellie/sales.json
          scheme_slug: sales
        - id: 1287
          path: sources/ellie/finance.json
          scheme_slug: finance

  # One workbook is one taxonomy is one source (5.3). A second taxonomy is a second
  # entry here, and its objects then carry `product-hazard:...` as their sem:sourceRef.
  - adapter: excel-taxonomy
    name: product-category
    config:
      path: sources/taxonomies/product-category.xlsx
      scheme_slug: product-category
      enumerates_source: ellie-main   # required only if the workbook names an entity
```

Credentials are never written to configuration — an adapter names an environment
variable (`token_env`) and the value comes from the CI platform's secret store or the
operator's shell. This is enforced, not merely documented: the compiler **rejects**
(exit 2) a configuration whose keys name a credential rather than a variable, and no
loaded configuration object ever holds a secret value. The rule is the plane's, not any
adapter's, and it holds for third-party adapters that do call a network service; neither
bundled adapter needs a credential in v1, since both read files committed with the
instance (5.3). Unknown keys are rejected for the
same reason a typo must not be silently ignored, and every rejection names the offending
key.

### 5.2 Adapter interface (plugins)

Adapters are **discovered, not imported**. The package declares an entry-point group
`semprini.adapters`; any installed distribution may contribute to it, so a
new source system — proprietary, third-party, or organization-internal — is added by
installing a package and naming it in `config/semprini.yaml`. No fork, no patch to this
project.

```python
class BaseAdapter(ABC):
    name: str  # entry-point name, e.g. "ellie"

    def __init__(self, source_name: str, config: Mapping[str, Any], ctx: RunContext): ...

    @abstractmethod
    def fetch(self) -> InternalModel: ...

    def validate_config(self) -> list[Issue]:  # called by `semprini check`
        return []

    def summary(self) -> str:  # one line for the run report (5.6)
        return ""
```

Contract obligations on every adapter, which the core relies on:

- `fetch()` performs **no writes** and no identity minting; it returns normalized
  objects carrying a `source_key` per object. Identity resolution is the core's job.
- Objects carry `source_refs: dict[str, str]`, so the same real-world concept seen by
  two adapters merges onto one IRI after identity resolution. Every object carries at
  least one ref under the source's own configured `name`, since that is what the ID map
  is keyed by (5.4).
- Fetch failures raise `SourceUnreachableError`; they never return partial models
  silently (exit code `3`). The distinction is the one CI acts on: a source that was
  down is retried, a source that answered with unusable data is a compile failure
  (exit `1`).
- An adapter contributes only data — never IRIs in another instance's namespace, and
  never `sem:` terms.
- Construction is free of side effects. `semprini check` constructs every configured
  adapter purely to call `validate_config()` (6.1), and must not open a connection to
  do it.

Adapters bundled with the plane are ordinary plugins registered by the same mechanism,
so a third-party adapter is never a second-class citizen.

**Discovery imports nothing.** Listing what is installed is a question about metadata:
answering it by importing every registered plugin would run arbitrary third-party code
on every command that loads a configuration. Import happens when an adapter is about to
be used, or in `semprini adapters`, which exists to report whether the installation
works. Consequences: one plugin that fails to import never hides the others, and a
source naming an adapter no installed distribution provides is a *configuration* error
(exit `2`), reported with its key like any other.

An entry point is refused, naming the distribution to uninstall, when it does not import,
does not yield a `BaseAdapter` subclass, leaves `fetch()` unimplemented, or declares a
`name` other than the one it is registered under — an instance writes that name in
`config/semprini.yaml`, so a class calling itself something else would make every message
about it name a thing that appears in no file the operator can open. An alias is a
subclass. Two installed distributions claiming one entry-point name are likewise refused
rather than resolved by order: `adapter: ellie` must not mean different things on a
laptop and in CI. `semprini adapters` reports that clash as well, since an installation
whose configured adapter cannot be resolved does not work even though every plugin in it
imports.

**The contract is executable.** The obligations above are all negative — an adapter that
violates them looks exactly like one that does not until an instance has committed the
damage — so the plane ships `semprini.testing.check_contract()`, which an adapter author
runs against their own adapter from their own test suite. It is framework-free (no
pytest dependency, no base class to inherit), it collects every violation rather than
stopping at the first, and it requires the author to supply both a working configuration
and one whose source cannot be read: an adapter never asked what it does when its source
is down is the adapter that one day answers "deprecate everything" (5.4).

### 5.3 Bundled adapters (v1)

**Ellie adapter (`ellie`).**

**One Ellie instance is one configured source, and it reads exported files.** Each domain
model is exported from Ellie as JSON — the response body of `GET /api/v1/models/{id}` —
and committed under `sources/ellie/`, where it is reviewed with the instance like any
other source. A direct call to the API is a later mode of this same adapter, and
deliberately not a second adapter: identity is keyed by `(source name, Ellie UUID)`, so a
source that changed adapters would re-mint every IRI it owns (5.4). The switch will change
how the bytes arrive and nothing about what they mean, which is also why `base_url` is
configured in file mode — it records *which* Ellie instance the UUIDs belong to, and
appears in the run report.

The instance, not the model, is the unit of a source, and that is the opposite of the
Excel arrangement below for the opposite reason. Ellie UUIDs are unique across an
instance rather than within a model, which is precisely what lets one entity appear in two
domain models and resolve to one node. So every model of one instance is listed under one
source name — listing them separately would give the same entity two identities — and two
Ellie instances are two sources, since their UUID spaces are unrelated.

Both file shapes are accepted: some exports wrap the model in a `model` object and some do
not. The document is recognized by structure, and one that is neither is refused by name
rather than read as a model with no entities — an empty model compiles to an empty scheme,
which deprecates everything the model used to hold (5.4). For the same reason a document
that states no `entities` key **at all** is refused as truncated: an export of an empty
model states an empty list, and the two must not be read alike.

- **Model allowlist.** Ellie contains many models; only explicitly registered, validated
  domain models are ingested, keyed by Ellie's model ID — nothing is read that is not
  listed. Each entry states the model's `id`, the `path` of its export and its
  `scheme_slug`; an export whose `modelId` disagrees with the `id` it is listed under is
  refused, because a file copied over the wrong path otherwise replaces a scheme's entire
  contents and the run reports it as ordinary change. The compiler fails the run (rather
  than skipping silently) if a listed model cannot be read, and the run report lists each
  model's ID, name as the export states it, and object counts — so a model swapped or
  renamed in Ellie is visible to the reviewer. Removing a model from the allowlist removes
  its `skos:ConceptScheme` and the corresponding `skos:inScheme` triples — but because the
  same Ellie entity can be referenced in multiple models, an object is deprecated only
  if it no longer appears in **any** registered model (deprecation is always evaluated
  against the union of all fetches, per 5.4). An object that remains in other models
  simply loses one scheme membership, identity and statements intact. The run report
  flags both cases prominently, since delisting is expected to be rare and deliberate.
- Reads, per registered model: entities (id, name, description, synonyms, examples),
  attributes (id, name, description, parent entity id), relationships (id, name, verb
  labels, source and target entity ids).
- Mapping: entity → `sem:Entity`; attribute → `sem:Attribute` + `sem:attributeOf`;
  relationship → `sem:Relationship` node + `sem:source`/`sem:target` + one
  `sem:relatesTo` shortcut triple; each registered model → `skos:ConceptScheme`
  (`sem:schemeType "glossary"`, IRI from `scheme_slug`) + `skos:inScheme` for its
  members. The scheme's *source key* is Ellie's model id, not the slug: the slug is this
  instance's name for the scheme and the id is the source's, and the ID map is keyed by
  the source's (5.4).
- **Inheritance becomes `skos:broader`.** Ellie draws a supertype relationship as an
  ordinary relationship whose ends are typed `superType`/`subType`, and gives it no name
  and no verb labels. It is emitted as `skos:broader` from the narrower entity to the
  broader one, and **no** reified `sem:Relationship` or `sem:relatesTo` shortcut is
  emitted for it: reifying it would mean inventing a preferred label no modeller wrote,
  and the reused SKOS term states the fact once and costs the metamodel no new vocabulary
  (3.3). Only that direction is emitted — `skos:narrower` would state the same fact a
  second time, in the other entity's block (5.5 rule 4). An entity may have several
  broader entities; multiple inheritance is a thing the source can express. A supertype
  relationship whose narrower end is not among the model's own entities is refused: the
  fact lands *on* that entity, so with no entity to carry it there is no cross-reference
  for a later stage to fail on, and the inheritance would vanish without a diff line.
- **A relationship's `skos:prefLabel` is Ellie's `name` when a modeller filled one in**,
  and otherwise the verb label whose direction reads source → target ("Order *has one or
  more* Order line"). A label reads source → target unless its `direction` is `"source"` —
  `"target"` and an **absent** direction alike, since a relationship carrying a single
  label often omits the field. Every other verb label becomes a `skos:altLabel`. A name appearing
  later re-labels the node without re-minting it, so preferring it costs no identity
  (5.4); a relationship with neither is refused, since a node has to have a label and
  inventing one is not an adapter's to do.
- Ellie descriptions become `skos:definition`. Empty descriptions emit **no**
  `skos:definition` triple (reported by SHACL as a warning in v1; see 6.1). Entity
  synonyms (comma-separated) become `skos:altLabel`; the entity's examples field is one
  `skos:example`, uncut — it is prose a modeller wrote, and splitting it on its commas
  would invent several statements where the source made one.
- **What is deliberately not carried yet**: `progressStatus`, entity `type`, `Source
  systems`, `Administrated by`, relationship cardinality, and every attribute metadata
  field but `Description` — `PK`, `FK`, `Data type`, `Not null`, `Unique`, `Semantic
  link` and the rest. Each would need a term the metamodel does not have, and minting one
  per Ellie field is what the removal of `sem:ellieId` ruled out (3.3). Deferred, not
  dismissed: an attribute's `Data type` and `Semantic link` are what `sem:represents` is
  reserved for (3.1), and adding any of them is a metamodel version bump (7).
- An entity appearing in multiple domain models must resolve to the **same** Ellie
  UUID (Ellie's cross-model reuse); the compiler merges statements onto one node with
  multiple `skos:inScheme` triples. If two distinct UUIDs carry the same name, they
  remain two nodes — flagged in the run report for stewards.

**Excel taxonomy adapter (`excel-taxonomy`).**

**One workbook is one taxonomy is one configured source.** Each workbook under
`sources/taxonomies/` gets its own entry in `config/semprini.yaml`, carrying just a
`path` and a `scheme_slug`; everything else about the scheme comes from the workbook.
Every object in that workbook therefore carries the source's `name` in its
`sem:sourceRef`, which is what makes provenance say *which file* an object came from.

Two consequences of that arrangement are load-bearing:

- **A source name never names the adapter.** `source_name` is half the ID map's key
  (5.4) and so is permanent: anything encoded in it becomes unchangeable without
  re-minting. Naming a source `excel-product-category` would re-mint every IRI in it the
  day the same taxonomy arrives in some other format — the coupling `sem:sourceRef` was
  designed to avoid (3.3). Which adapter read a file is recorded in the configuration and
  in the run report (5.6), neither of which is identity.
- **The path is not the name either.** It lives in `config:` precisely so a workbook can
  be moved or renamed without re-keying its contents. For the same reason the *scheme* is
  keyed by its slug and not by its file name.

`scheme_slug` stays in the configuration rather than in the workbook because it names two
permanent things — the scheme's IRI local name and its output file (4.2) — and both are
frozen by the ID map on the run that mints them.

**Sheet 1, `Concept Scheme`** — a vertical Property/Value table. `Scheme Name` is
required and becomes the scheme's `skos:prefLabel`; `Description` becomes its
`skos:definition`; `Language` is a BCP 47 tag applied to every cell in the workbook that
states none of its own; `Reference Entity UUID` is the *source key* of the entity this
taxonomy enumerates (`sem:enumerates`), optional, and resolved against the ID map when the
graph is built — under the source named by the configured `enumerates_source`, which is
required exactly when that cell is filled. The source name lives in the configuration
rather than the workbook because it is this instance's to choose (5.1): the workbook
states a UUID, and which configured source issued that UUID is not a fact about the
workbook. Without it the reference would be looked up under the taxonomy's *own* source
name, where an entity's key can never be found, since the ID map is keyed by
`(source name, source key)` (5.4) — which is also why `enumerates_source` naming the
taxonomy's own source is refused as configuration (exit `2`) rather than left to fail as
an unresolvable reference much later. Any other row — creator, dates, version, domain — is documentation for
whoever maintains the workbook and is read by nobody.

**Sheet 2, `Taxonomy`** — one value per row, header row required:

| Column | Required | Maps to |
|---|---|---|
| `Concept URI` | yes | identity key for UUIDv5 minting — **not** an emitted IRI |
| `L1..Ln - Preferred Label` | yes (at least `L1`) | `skos:prefLabel`, and the hierarchy |
| `Definition` | no | `skos:definition` |
| `Alternative Labels` | no (`;`-separated) | `skos:altLabel` |
| `Hidden Labels` | no (`;`-separated) | `skos:hiddenLabel` |
| `Scope Note` | no | `skos:scopeNote` |
| `Example` | no | `skos:example` |

Headers are matched on their **first line**, lower-cased — these sheets carry the SKOS
mapping on a second line, which is documentation and no part of a column's name. Columns
the adapter has no home for are tolerated and ignored: a workbook is a working document
and gains columns for reasons of its own, unlike a configuration file, where an unknown
key is an error (5.1). The level columns are the exception: they must run `L1..Ln` with
none missing, because depth is read from a cell's position among them.

A cell may be written in Turtle's literal syntax (`"Power tools"@en`) to state its own
language, which is honoured over the sheet's. Two rules keep that from quietly corrupting
text, and both matter because the failure is silent:

- Semicolon separation is applied **outside** quoted literals only. A cell reading
  `"A; B"@fi; "C"@fi` is two labels, and splitting before parsing would cut the first in
  half, leaving fragments carrying stray quotation marks and losing the language stated.
- A cell counts as literal syntax only when the quoted part contains no further quotation
  mark. Prose that merely opens and closes with one — `"Smart" tools "here"` — is a
  sentence somebody wrote, and a greedy match would delete its outer characters on the way
  into a governed file. The cost is that a label genuinely containing a quotation mark
  keeps its outer quotes; taking a cell too literally is recoverable, quietly editing it
  is not.

**Hierarchy is ragged.** A row's depth is the position of its last filled `L` cell, and
its broader concept is the row whose labels are its own first *n-1*. Two things follow
that are not obvious:

- **A cycle cannot be expressed.** A row's ancestors are a prefix of its own cells, so
  there is nothing to close a loop with. The error conditions below replace the
  cycle check a `parent_code` format needs.
- **A label is structural**, so renaming an `L2` cell re-parents everything beneath it.
  That is why identity comes from `Concept URI` and never from the labels: a taxonomy can
  be re-worded without minting a single new IRI (5.4).

Hierarchy is matched on label *values*, not raw cells, so a workbook that tags some cells
and leaves others bare still describes one branch.

Compile errors, every one of them reported together rather than one per run — a taxonomy
is edited in bulk, so its mistakes arrive in bulk:

- A row whose parent path matches no row.
- Two rows at the same path, or sharing one `Concept URI`.
- A row that **skips a level** (`L1` and `L3` filled, `L2` empty). Collecting the
  non-empty cells and discarding their positions would read this as depth 2 and attach
  the value to the wrong parent — a taxonomy that is well-formed and wrong.
- A row with no `Concept URI`, which is refused rather than skipped: skipping it means a
  value silently vanishing on the next compile, and being deprecated for it (3.5). Only a
  row that is blank **across every column** is treated as spreadsheet punctuation; a row
  carrying a definition but no identity yet is half-finished work, and dropping it is how
  a value a steward believes they added never appears.
- A missing `Concept URI` or `L1` **column**, or level columns that do not run `L1..Ln`.
  Header matching is strict because a sheet whose level columns are named something else
  does not read as a broken taxonomy — it reads as an empty one, which compiles to a
  scheme with no values and deprecates everything that used to be in it. A sheet whose
  levels start at `L2`, or that lost its `L2` in a re-export, is worse still: it reads as
  a *complete* hierarchy with every value one level too shallow, the run succeeds, and the
  diff looks like a re-levelling nobody performed.

An adapter validates **its own configuration before it reads anything**, so a run that
never invoked `semprini check` still fails with the offending key rather than with a
traceback or, worse, an absolute `path` silently overriding the repository root.

A workbook that cannot be read at all is exit 3 (unreachable); every error above is a
compile failure, exit 1.

### 5.4 Identity management

**`mappings/id-map.csv`** — append-only registry, columns:
`iri, kind, source_name, source_key, first_seen, note`.

- On every run, each normalized object is looked up by `(source_name, source_key)`.
  Hit → reuse IRI. Miss → mint per 3.4, append a row. An object known to several sources
  has **one row per source ref**, all carrying the one IRI — the same pairs it carries as
  `sem:sourceRef` triples (3.3), so the registry and the RDF cannot tell different
  stories. If those refs are already mapped to *different* IRIs, the run fails: the
  sources say one object and the map says two, and only a steward can decide which
  survives (`merges.csv`, below).
- `kind` is recorded, not part of the key. A source key that arrives describing a
  different kind than the one recorded is an error, since its IRI is already minted in
  another kind's namespace.
- **Distinct objects must resolve to distinct IRIs**, and this is checked over the whole
  model rather than one object at a time. Several rows legitimately share an IRI — that is
  what a multi-source object looks like — so a lookup alone cannot tell the difference.
  If the cross-reference that merged two objects later disappears from the sources, both
  arrive separately, both hit those rows, and without the check the compiler would emit a
  single node wearing two `skos:prefLabel`s. Reconciling them is the sources' business or
  the merge register's, never the compiler's.
- The file is written UTF-8 with LF line endings and its rows keep the order they were
  appended in. It is committed, and a compile PR's diff over it should be additions only.
  "Append-only" means every column of an existing row is immutable **except `note`**,
  which is the one field stewards own. A byte-order mark is tolerated on read: the file is
  a CSV, and stewards open it in tools that add one.
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
deprecation. It is written UTF-8 with LF line endings, tolerates a byte-order mark on
read, and the compiler never writes a row into it — every row is a steward's decision.
`date` is recorded for the reader and never acted on. Only `dcterms:isReplacedBy` is
emitted, on the deprecated node; the `dcterms:replaces` inverse would state one fact
twice (3.3).

This is the one file in an instance where a person types an IRI, so it is validated
strictly, and every rule below refuses rather than repairs:

- **Both IRIs must exist in the ID map.** A row naming an IRI this instance never minted
  deprecates nothing and points at nothing, with nothing in the diff to show either.
- **One deprecated object has one successor.** Two rows for one `deprecated_iri` leave
  "which of these survived" — the register's only question — unanswered.
- **No row replaces an object with itself, and no chain of rows closes into a cycle.**
  Every object in a cycle is replaced by one that is itself deprecated, so following
  `dcterms:isReplacedBy` never arrives at a surviving object.
- **Chains are allowed and are not followed.** If A → B was recorded and later B → C,
  then A's successor is emitted as B: that is the statement the steward made, and
  rewriting it to C would put a triple in a governed file that no row supports.
- **A successor may itself be deprecated later, and that is not an error.** A was merged
  into B and B was afterwards retired by its own source: ordinary history, recorded
  correctly at the time. Only a *cycle* is refused, because a cycle never had a survivor.
- **The register is applied within the run's scope**, like every other lifecycle decision
  below. A row naming an object this run was not entitled to judge does nothing until a
  run that fetched its sources reaches it; acting on it anyway would deprecate a node on
  no evidence, which is the one thing `--source` promises not to do.
- **A row for an object the sources still describe fails the run** (exit 1). The register
  and the sources contradict each other, and the compiler settles neither: deprecating
  anyway would override every source from a one-line CSV edit, and ignoring the row would
  make the register silently inert. Normally the source tool has already deleted the
  object, which is what the register exists to explain.

Removing a row removes the `dcterms:isReplacedBy` triple on the next run — the register
is read as it stands, so a steward can undo a decision and see it undone.

**Deprecation detection.** Deprecation is evaluated against the **union of all
configured sources** in the current run — never against a single source or model. An
object present in the previous generated output (and in the ID map) but absent from
that union is re-emitted with `sem:status "deprecated"` and all its last-known
statements preserved. An object that merely disappeared from one model or source while
remaining in another loses only the corresponding `skos:inScheme` (or other
source-specific) statements. Deprecated nodes are carried forward on subsequent runs
and are never physically removed.

A retained node keeps the file it was already written in, so its deprecation is one
changed `sem:status` line rather than a deletion in one file and an addition in another.
Its `dcterms:modified` is decided by the ordinary rule (3.3): the status change is a
content change, so the date moves on the run that deprecates it and never again. Only
the block that *describes* the node — the one carrying its label — is marked; a file
that merely mentions it, as the `sem:relatesTo` shortcut does (4.2), states no more about
it than it did before. Deprecation is a status and not a tombstone: the ID-map row is
untouched, so an object a source restores is active again under the IRI it always had.

**Scope.** A run may only conclude that an object is gone if it fetched every source that
owns it — that is, every `source_name` the ID map records against its IRI. Consequently a
run scoped with `--source <name>` performs no deprecation for objects any other source
owns, and neither does a full run for an object whose ID map names a source that is no
longer configured (which `semprini check` reports separately, above).

Out-of-scope objects are **carried forward exactly as they stand**, status included, not
skipped: `generated/` files are rewritten whole, so a node left out of a run's output is a
node deleted from the instance — the opposite of what "skip deprecation" is asking for.

Carrying forward works because an out-of-scope object belongs to nobody the run fetched.
An object the ID map records against **two** sources when only one was fetched is therefore
the one case a partial run cannot assemble: the model holds it rebuilt from one source's
statements, so writing it would delete the other's contribution, and carrying it forward
would discard the very update the run was invoked for. The run refuses it (exit `1`) and
says to compile in full, for the reason merging refuses to guess (5.2) — loosening this
later is easy, and tightening it once instances hold files built under a guess is not.

The `sem:relatesTo` shortcut needs saying separately, because it is the one statement
written away from the node it is about (4.2): its subject is the source entity, but it
lives in the relationship's file. When the entity is still reported and the *relationship*
is out of scope, neither rule above reaches the shortcut — the entity is rebuilt from a
model that no longer holds the relationship — so it is **retained with the relationship**,
which was itself carried forward as active. A shortcut whose pair the run still derives is
not retained, since the build stage writes it (one triple, one file); nor is one whose only
relationship was *deprecated*, since `sem:relatesTo` carries no status of its own and
leaving it would assert a live relation on the strength of a retired one.

**An IRI in `generated/` that the ID map does not hold fails the run** (exit 1). It means
a row was deleted or a file was hand-edited (4.3); the compiler cannot say which source
the node came from, and dropping it would be the deletion this whole mechanism exists to
prevent. This is checked without reference to git, unlike the append-only check (6.1
check 6), so it holds for a local run as well as in CI.

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
6. Language tags always present on the text-valued properties — `skos:prefLabel`,
   `skos:altLabel`, `skos:hiddenLabel`, `skos:definition`, `skos:scopeNote` and
   `skos:example`. (`skos:notation` is untagged: a notation is a code, not prose in a
   language.) One `default_language` per instance, set in
   `config/semprini.yaml` (default `en`), is applied to every label and definition that
   arrives without a language of its own; a label that arrives **with** one keeps it and
   is never overwritten. An instance therefore has one language by default but is not
   limited to one, and a source that already knows its languages does not have to
   discard them.
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

`generated/.report.md` carries: compiler and ontology versions, counts per class and per
file, new/changed/deprecated objects, objects missing definitions,
same-name/different-IRI warnings, and per-source fetch summaries. The compile workflow
pastes it into the PR description — it is the reviewer's summary.

Everything in it is derived from the graphs the run produced and the state they replaced,
never from what an adapter believed it fetched; "changed" and a refreshed
`dcterms:modified` (3.3) are decided by one comparison, so the report and the Turtle
beside it cannot tell different stories. Deprecation is decided by lifecycle (5.4), but
the decision is visible in the output once made and is read from there rather than passed
in — the same rule, applied to the one count that could most easily have been asserted
instead of shown.

New, changed and deprecated **partition** the nodes: a deprecation is a change, but a
reviewer reading "Changed 12 · Deprecated 3" has to be able to tell whether that is twelve
nodes or fifteen. "Deprecated" counts the nodes this run deprecated, not every deprecated
node in the instance — the latter would grow for ever and stop describing the run. It carries no timestamp and no run identifier
(5.5 rule 8), and each listing of nodes is capped — the counts above it are not — because
a first compile of a large instance would otherwise bury them in a PR description.

**The report is rewritten only when the run changed something.** A run whose output is
byte-identical to what is committed leaves it alone. Written unconditionally, a scheduled
no-op compile would rewrite "12 new" to "0 new" and open a PR containing nothing else —
the empty diff the whole design exists to avoid (1.2, 4.3). A committed report is
therefore always the report of the run that produced the files beside it, which is also
what a reviewer wants it to be.

"Changed something" is about the instance, not only about the bytes produced: the
`.manifest.json` the run writes is part of the comparison, so a recompile after a plane
upgrade rewrites the report rather than leaving one that names an older release beside a
manifest that names the new one; and a run that produced byte-identical files while
*removing* stale output (4.3) has changed the instance and rewrites it too.

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
2. **Manifest integrity**: `generated/*` hashes match `.manifest.json`, every recorded
   file is present, and no unrecorded file is (4.3) — this blocks hand edits to generated
   files and stale output alike.
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
   - `skos:broader` only between two nodes of the same class — taxonomy value to taxonomy
     value within one scheme, or entity to entity (inheritance, §3.3) — and **no cycles**,
     of any length. Nothing earlier in the pipeline can catch a cycle: an adapter sees one
     source, and inheritance drawn across two of them closes a loop neither one holds.
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
| ~~1~~ | ~~Register the `w3id.org/semprini` namespace (PR to the w3id.org repository); confirm the redirect target that will host the ontology~~ | **Resolved:** registered and live. `https://w3id.org/semprini/ontology` content-negotiates to the ontology document or to its documentation, and versioned paths resolve for each released version. Redirects point at the project's own published site, so resolution depends on no domain beyond w3id.org itself (3.1). Instances may now mint IRIs |
| 2 | ~~Confirm Apache-2.0 / CC BY 4.0 (8), or choose AGPL for the code if hosted-service competition is a concern~~ | **Resolved:** Apache-2.0 + CC BY 4.0, copyright Datakor Consulting Oy (8) |
| 3 | Distribution channel: PyPI, or Git tags only at first | PyPI once the interface is stable; Git tags until then |
| 4 | Which adapters are bundled versus separately distributed (5.3) | Ellie and Excel bundled; all later adapters evaluated case by case |
| 5 | ~~Default language tag(s); multilingual labels needed?~~ | **Resolved:** one `default_language` per instance, applied to every untagged label and definition; an already-tagged label keeps its tag (5.5 rule 6) |
| 6 | Definition coverage: when the missing-definition warning becomes blocking | per instance, after pilot review |
| 7 | ~~Ellie API rate limits / pagination specifics~~ | **Deferred, and no longer blocking:** the `ellie` adapter reads exported model files (5.3), so v1 makes no API call. Pagination and rate limits are questions for the adapter's later API mode, and are settled against Ellie's API documentation when that mode is built |
| 8 | Whether `semprini init` also creates the remote repository (`gh repo create`) or stays offline | stays offline (5.7) |

Per-instance decisions — base IRI, source allowlist, stewards and CODEOWNERS — are made
at bootstrap by each adopting organization and are deliberately not listed here.

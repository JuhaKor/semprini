# Semprini — implementation specification

**Status:** v0.2 · **Author:** Juha Korpela / Datakor · **Date:** September 2026

This document is the authoritative specification of Semprini. `README.md` introduces
the product and shows how to use it; this document defines how it works inside. It is
self-contained: an implementer needs no other material.

*Knowledge plane* is the architectural term for what Semprini is: a shared semantic
layer over an organization's data. The metamodel prefix is `sem:`.

---

## 1. Purpose

Semprini is an openly licensed knowledge-plane toolchain. It turns an organization's
semantic content (business concepts, their relationships, and taxonomies) into
versioned, validated RDF held in Git.

It has two parts:

1. **The plane** (this project): a Python package (the compiler), a metamodel
   ontology, SHACL shapes, CI workflow templates, and an instance scaffold. The project
   develops it once, releases it under an open licence (8), and every deployment reuses
   it.
2. **An instance**: one organization's own Git repository, created from the scaffold.
   It holds only that organization's configuration, source files, identity registry
   and generated RDF. Each instance is independent, with its own IRIs, its own review
   process and its own release cadence.

Downstream components, such as a triple-store loader that serves AI agents, consume an
instance's content. Downstream publishing is **out of scope**. The contract ends at
*validated TTL files on an instance's main branch*.

### 1.1 Deployment model

| | The plane repository | An instance repository |
|---|---|---|
| Contains | compiler package, metamodel ontology, core SHACL shapes, workflow templates, instance scaffold, test fixtures | `config/`, `sources/`, `mappings/`, `generated/`, `overlays/`, `shapes/local/`, two thin workflows |
| Owned by | the project (open source) | the adopting organization |
| Versioned by | semantic versioning + released tags (7) | content changes; pins a plane version |
| Holds credentials | never | yes (its own source-system tokens) |
| Count | one | many, unrelated to each other |

An instance depends on the plane the way a project depends on a library. It installs a
**pinned release** and upgrades deliberately (7). It never vendors or forks the
compiler, and it never edits core shapes. An organization changes only configuration,
source content, overlays and local shapes.

### 1.2 Design principles

- **Sources are masters; the instance repo is the record.** People author semantic
  content in source tools. Nobody edits generated content by hand: a correction goes to
  the source, and the compiler regenerates.
- **Identity is permanent and opaque.** Every semantic object has an IRI that never
  changes and never encodes mutable facts (names, domains, codes).
- **Diffs are the governance interface.** Every content change arrives as a pull
  request with a human-reviewable diff. This requires deterministic serialization (5.5).
- **Validation is automated.** CI enforces the metamodel with SHACL and structural
  checks on every PR (6).
- **The metamodel is shared; content is sovereign.** One vocabulary describes every
  deployment (3.1), so a tool or query written once works everywhere. All content IRIs
  live in namespaces the adopting organization controls.
- **No lock-in.** The plane depends on no vendor-hosted service. It emits no telemetry
  and calls no network service except the sources an instance configures. All logic
  lives in the CLI, so CI platforms are interchangeable (6.3). An organization that
  stops using the plane keeps working RDF and a complete identity registry.
- **Extension without forking.** A new source system arrives as a plugin adapter (5.2).
  Organization-specific semantics arrive as local extensions (3.6) and local shapes
  (6.1). Neither requires a change to this project.

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
- Cross-instance federation (each deployment stands alone)

---

## 3. Metamodel

### 3.1 Namespaces and prefixes

Namespaces fall into two groups. This division is what lets one implementation serve
many deployments.

**Fixed — identical in every deployment, owned by this project:**

| Prefix | Namespace | Use |
|---|---|---|
| `sem:` | `https://w3id.org/semprini/ontology#` | Metamodel classes and properties |

The metamodel namespace resolves through **w3id.org**, a community-maintained
permanent-identifier service, so resolution does not depend on one organization's
domain. The ontology is versioned independently of the compiler (7) and is never
rewritten per deployment. An agent, query or SHACL shape written against `sem:` works
against every instance.

**Per-instance — chosen once at bootstrap, owned by the adopting organization:**

| Prefix | Namespace | Use |
|---|---|---|
| `c:` | `{base}concepts/` | Entities, attributes, terms |
| `r:` | `{base}relationships/` | Reified relationships |
| `sch:` | `{base}schemes/` | Glossaries & taxonomies (as schemes) |
| `v:` | `{base}values/` | Taxonomy value nodes |
| `x:` | `{base}ext#` | The organization's own extension terms (3.6) |

`{base}` is the instance's base IRI (for example `https://semantics.acme.com/`). It is
set in `config/semprini.yaml` and frozen by the namespace lock (3.4). **Minted IRIs are
permanent**, so the domain must be one the organization controls and intends to keep.

**Reused standard namespaces:** `skos:`
(`http://www.w3.org/2004/02/skos/core#`), `dcterms:` (`http://purl.org/dc/terms/`),
`xsd:` (`http://www.w3.org/2001/XMLSchema#`).

Reserved for later versions (declared now, unused): `a:` (`{base}assets/`) for
technical data objects, `d:` (`{base}docs/`) for documents.

The instance IRI space is partitioned by **kind of thing**, which never changes, and
never by business domain, which does. Domain membership is data (`skos:inScheme`).

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

- Attributes are first-class nodes, not RDF properties, because source tools give them
  identity, definitions and ownership.
- Relationships are reified as their own node because they carry a name or verb and an
  identity. The compiler also emits a shortcut triple (`sem:relatesTo`) between the two
  entities for cheap traversal.
- Taxonomy value nodes are plain `skos:Concept`s. Membership in a taxonomy-typed scheme
  says what they are (3.4).

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

`sem:sourceRef` names no vendor: a shared metamodel must not name one commercial tool.
Its value pairs the instance-configured **source name** with the key that source uses.
This is the same `(source_name, source_key)` pair that keys the ID map (5.4), so a
node known to several sources carries several `sem:sourceRef` triples, and the RDF and
the ID map tell the same story.

**Reused standard properties:**

- `skos:prefLabel` (exactly one per node, per language), `skos:altLabel` (synonyms)
- `skos:hiddenLabel`: misspellings and retired names. Search matches them; nothing
  displays them.
- `skos:definition`: definition text
- `skos:scopeNote`: guidance on where a concept's boundaries lie
- `skos:example`: instances that fall under the concept

  `skos:hiddenLabel`, `skos:scopeNote` and `skos:example` may each appear **more than
  once** on a node. `skos:definition` may not: a concept has *the* definition, whereas
  two sources that each contribute an example do not disagree. All three are reused
  SKOS terms, so `sem.ttl` does not declare them (3.6).

- `skos:inScheme`, `skos:topConceptOf`, `skos:hasTopConcept`: scheme membership
- `skos:broader` / `skos:narrower`: taxonomy hierarchy, and **entity inheritance**

  One property, two uses. Inside a taxonomy scheme it is the value hierarchy. Between
  two `sem:Entity` nodes it is specialization as the modelling tool states it: "Active
  customer" is narrower than "Customer" (5.3). Every entity is a `skos:Concept`, so
  the SKOS property already says what the modeller drew.

  Of each inverse pair the compiler emits **one direction only**: `skos:topConceptOf`
  and `skos:broader`, both stated on the narrower node. The inverse would repeat the
  same fact in another file (4.2), and one changed fact must be one changed line (5.5
  rule 4). A consumer that wants the inverses can entail them.

- `skos:notation`: the business code of a taxonomy value (for example `"PT"`), **only
  when the source states one**. The compiler never derives a code from a row's
  identity key, because that would emit a code no source ever said.
- `skos:exactMatch`, `skos:broadMatch`: cross-scheme alignment, for example to an
  industry taxonomy or to another instance's concepts
- `dcterms:isReplacedBy`: deprecated node → successor
- `dcterms:modified`: last content change (`xsd:date`), set by the compiler. It changes
  **only when the node's other statements change**. Otherwise the compiler carries it
  forward from the previous output, so a no-op run produces no diff (5.5).

### 3.4 IRI policy

1. **Opaque IRIs.** No names, codes or domains appear in an IRI. Labels live in
   `skos:prefLabel`, codes in `skos:notation`, domain membership in `skos:inScheme`.
2. **Minting.** The namespace is always the one for the object's *kind* (3.1). Only the
   local name varies:
   - An object whose source provides a stable UUID gets `c:{uuid}` / `r:{uuid}`. The
     source UUID becomes the local name directly. A key counts as a UUID only in the
     canonical `8-4-4-4-12` form, and the compiler lower-cases it, so a source that
     changes the case of a UUID does not mint a second IRI. A 32-digit code is *not* a
     UUID and takes the derived path below.
   - A scheme gets `sch:{slug}`. The slug is assigned **once**, when the scheme is
     created, and recorded in the ID map. After that it is opaque: renaming the glossary
     does not change it. A slug consists of lower-case letters, digits, `-` and `_`,
     the same shape as an instance id or a source name; otherwise `Sales` and `sales`
     would be two IRIs for one taxonomy, and one file on a case-insensitive filesystem.
     The slug also names the scheme's *file* (4.2), and the ID map protects only the
     IRI. So the compiler re-checks the slug on every run against both the shape above
     and the local name frozen in the ID map. This stops an edited `scheme_slug` from
     moving the file while the IRI stays put, and stops a value such as `../../x` from
     composing a path outside `generated/`.
   - An object with no source UUID gets `{prefix}:{uuid5}`, derived from the fixed
     namespace `NAMESPACE_SEMPRINI` = `8865c94a-2211-5f26-8887-6d6d5cbaa1e0`, which is
     `UUIDv5(NAMESPACE_URL, "https://w3id.org/semprini/ontology#")`. This constant is
     **permanent**: changing it would re-mint every object first seen after the change.
     The hashed name is `scheme-slug + "|" + source-row-key` for a taxonomy value and
     `source-name + ":" + source-key` for anything else. A taxonomy value is identified
     by its position in a taxonomy; everything else by the source that reported it. The
     source-row-key is the taxonomy code column if codes are declared stable for that
     file, otherwise an explicit `id` column that maintainers must add. The compiler
     **persists** the result in the ID map (5.4), which is authoritative from then on.
     If a code later changes, the ID map preserves the original IRI.
   - A local name that cannot follow a prefix in Turtle, such as a scheme slug with a
     space in it, is **rejected**, not escaped. Escaping would freeze an IRI nobody
     intended.
3. **IRIs are never deleted or reused.** Removal from a source marks the node
   `sem:status "deprecated"`. A merge adds `dcterms:isReplacedBy`.
4. **A namespace lock freezes the base IRI.** At bootstrap the compiler writes
   `mappings/namespace.lock` (JSON: base IRI, instance id, ontology version, date). On
   every later run it compares the base IRI and instance id in the lock to
   `config/semprini.yaml` and **aborts** on a mismatch. Without the lock, an edited
   base IRI would silently mint a parallel set of IRIs beside an ID map that still
   held the old ones. A **missing** lock aborts the same way, so deleting the file is
   not a way around a permanent decision. The recorded ontology version only says what
   the instance bootstrapped against; the manifest's drift check governs metamodel
   upgrades (6.1). **The base IRI is permanent.** No command moves an instance to a
   different one. An organization that needs a new base IRI creates a new instance,
   and the old instance's IRIs stay published as they were.

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

1. **Local terms live in the instance's own `x:` namespace** (3.1). They are declared
   in `overlays/`, and the organization is free to change them.
2. **An instance never redefines, narrows or re-scopes a core `sem:` term.** A local
   shape may add constraints to instance data; it may not restate what a `sem:` term
   means. A wrong or missing `sem:` term is an upstream issue (9.2). This rule keeps
   every instance's data answering to the same shared vocabulary.
3. Local terms **should** relate themselves to core terms where the meaning allows
   (`rdfs:subClassOf sem:Entity`, `rdfs:subPropertyOf sem:isAbout`), so that generic
   queries still reach them.
4. Local shapes live in `shapes/local/` and are **additive only**. 6.1 check 5 states
   precisely what that permits and rejects. They may target `sem:` classes; they may
   not make statements about `sem:` terms or about the core shapes.

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

The example is abbreviated. Every node the compiler writes carries `sem:sourceRef`,
`sem:status` and `dcterms:modified`, **schemes included**: lifecycle (3.5) applies to
every object, and a source can delete a scheme as readily as anything else.

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
│   ├── scaffold.py                # the `semprini init` scaffold (5.7)
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
│   ├── migrate/
│   │   ├── steps.py               # the migrations this release ships, in release order (7)
│   │   ├── registry.py            # which of them one upgrade needs (7)
│   │   └── apply.py               # `semprini migrate` — the only part that writes (7)
│   ├── adapters/
│   │   ├── base.py                # BaseAdapter — the plugin contract (5.2)
│   │   ├── discovery.py           # entry-point discovery (5.2)
│   │   ├── ellie.py               # bundled (5.3)
│   │   └── excel_taxonomy.py      # bundled (5.3)
│   ├── ontology/
│   │   └── sem.ttl                # the metamodel, versioned (3.1, 7)
│   ├── shapes/
│   │   └── core.ttl               # core SHACL shapes (6.1.5)
│   ├── templates/instance/        # the scaffold `semprini init` materializes (4.2)
│   └── workflows/                 # portable CI definitions for *instances* (6.2, 6.3)
│       └── github/                # one directory per platform
└── tests/
    └── fixtures/
        ├── acme/                  # a complete synthetic instance + golden TTL (6.1)
        └── dummy-adapter/         # a third-party adapter distribution, as installed (5.2)
```

**Everything `init` materializes lives inside the package**, next to `sem.ttl` and
`core.ttl`. An adopter installs a wheel with pip and never sees this repository, so the
scaffold must travel in the wheel. Workflow templates live in one directory per CI
platform. That is the seam 6.3 promises: a port to GitLab adds a directory and the path
its files go to, and changes nothing else.

### 4.2 An instance repository

```
<org>-semantics/
├── README.md                  # points to the plane's docs; local stewardship notes
├── .gitattributes             # eol=lf — required; see 4.3
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
pinned metamodel. The compiler copies it and never re-serializes it, because its term
comments are the vocabulary's published documentation (3.1); the comment-free rule of
5.5 governs only the instance's own output. The copy lets a downstream consumer load an
instance from Git alone.

**Partitioning.** Output is partitioned by scheme, and **an object is written exactly
once**: in the file of its lexicographically first scheme, with all of its
`skos:inScheme` triples there. Repeating a multi-scheme object in every scheme's file
would turn one changed label into several changed hunks (1.2). *Lexicographically*
first, not first reported, so an adapter's iteration order cannot decide where an
object lives.

The `sem:relatesTo` shortcut (3.2) is the one statement written away from the node it
is about. It is derived from a relationship and goes in that relationship's file, so a
reviewer sees the reified node and its shortcut in one hunk. A subject may therefore
span two files. The compiler decides `dcterms:modified` (3.3) from everything the run
says about a node across **all** files, never from one file's share.

The compiler emits the shortcut **once per entity pair, not once per relationship**,
in the lexicographically first of the relationships' files. `sem:relatesTo` says only
*that* two entities are related, so several relationships between one pair derive the
identical triple. Emitted per relationship, deleting one of them would show a removed
`sem:relatesTo` line for a fact that still holds.

The compiler does **not** write a file with no content. A glossary with no
relationships produces no `relationships-<scheme>.ttl` at all.

**No statement is written into two files**, and the build stage checks this. A run
assembles its files from two kinds of evidence, the model and the nodes lifecycle
retained (3.5), so a node claimed by both would otherwise reach an instance as a diff
hunk nobody could explain.

### 4.3 Rules

- Every compiler run overwrites everything under `generated/`. CI **fails any PR that
  edits `generated/` without the compiler**. `generated/.manifest.json` enforces this:
  it records content hashes plus the compiler and ontology versions, and validation
  recomputes and compares them. The manifest contains **no timestamps**; it must be
  reproducible.
- **What the manifest records.** Every file the run writes under `generated/`, the
  ontology copy included, as `<file name>: "sha256:<hex>"`. The document is a JSON
  object with keys sorted at both levels, indented by two spaces, ending in one LF, and
  holding exactly `compiler_version`, `files` and `ontology_version`. An unknown key is
  an error, as in configuration (5.1). Two files are deliberately **not** hashed: the
  manifest itself, which cannot contain its own hash, and `.report.md`, which is prose
  about a run and is written on different terms (5.6).
- **A file present but unrecorded fails the check**, exactly like an edited one.
  Otherwise an instance accumulates output from a scheme that no longer exists.
- **A run removes what it did not produce.** The run deletes output it did not write,
  nested content included, because a consumer reading the tree reads that too.
  `.report.md` is the exception: the compiler writes it only when something changed
  (5.6), so a run that produced no report has not stopped producing the committed one.
  Removing a file counts as a change, so the run that removes one rewrites the report.
  A migration (7) follows the same rule.
- **An instance commits a `.gitattributes` pinning `eol=lf`, and this is mandatory.**
  Generated files use LF (5.5 rule 5) and are compared byte for byte (6.1 check 7). A
  clone with `core.autocrlf=true`, the Windows default, would otherwise rewrite every
  file on checkout and fail the determinism check. The scaffold writes the file (5.7).
- **An uninstalled compiler never writes a manifest.** Run from a source tree, the
  package reports version `0.0.0+source`, which identifies no release, so the compiler
  refuses to write `generated/` at all (7).
- Humans write `overlays/` and `shapes/local/` through normal PRs. Validation judges
  them by the rules for hand-written RDF, not by the core shapes, which state what the
  *compiler* guarantees about its own output (6.1 check 5).
- Source files are committed: Excel taxonomies under `sources/taxonomies/`, exported
  Ellie models under `sources/ellie/`. A source edit and its generated TTL then land in
  the same PR. For the same reason an adapter's configured path may not lead outside
  the repository: a file elsewhere is content nobody reviewed.

---

## 5. The compiler

### 5.1 Packaging and CLI

The compiler is a Python 3.12+ package distributed as **`semprini`** (import name
`semprini`). It uses `rdflib` for graph construction, `openpyxl` for Excel, `requests`
for HTTP sources, `pyshacl` for validation and `PyYAML` for configuration. It is
published as a wheel attached to a tagged GitHub release, not to a package index
(11 #3). An instance installs it by URL, so no unreleased version is installable. It
exposes a console script:

```
semprini init      --base-iri <IRI> --org <slug> [--dir <path>]   # bootstrap an instance (5.7)
                   [--language <tag>]                             # default_language (5.5 rule 6)
semprini run       [--dry-run]                                    # fetch, compile, write
semprini check     [--base <rev>]                                 # validate only, no writes
semprini migrate   --to <version>                                 # apply migrations (7)
                                                                  # <version> = the installed one
semprini adapters                                                 # list discovered plugins
semprini version                                                  # compiler + ontology versions
```

Commands operate on the instance repository in the working directory and read
`config/semprini.yaml`. Two exceptions: `version` and `adapters` describe the
*installation*, so they work outside an instance repository; and `init` writes the
configuration the others read. Exit codes are part of the contract, so any CI system
can act on them: `0` success · `1` validation or compile failure · `2` configuration or
namespace-lock error · `3` a configured source was unreachable. One mapping from error
to code serves every subcommand.

**Poetry** manages the plane's own dependencies, development environment and releases:
`pyproject.toml` is a Poetry project built by `poetry-core`, and `poetry.lock` is
committed. This choice does not reach instances. The published artifact is a standard
wheel, so adopters and instance workflows install it with plain `pip` (6.2) and never
need Poetry.

Pipeline stages for `run`:

```
fetch (per configured adapter)
  → normalize into the internal model (Entity, Attribute, Relationship,
    Scheme, TaxonomyValue)
  → apply lifecycle rules (diff against previous generated/ state: what is gone,
    what the merge register replaces — 3.5, 5.4)
  → resolve identity (ID map lookup / minting)
  → build rdflib Graphs (one per output file), from the model and the nodes
    lifecycle retained
  → canonical serialization → write generated/*.ttl + .manifest.json + .report.md,
    removing output this run did not produce (4.3)
  → update mappings/id-map.csv (append-only)
```

**Nothing is written until every stage has succeeded.** Fetching, lifecycle, building,
serialization, hashing and the report all complete in memory first. A source that is
down, a merge register that contradicts itself or a model that cannot be expressed
leaves the instance exactly as it was. There is no state in which `generated/`
describes one run and `mappings/` another. `--dry-run` is the same pipeline without
its last four lines, so what it reports is what it would have committed.

Every run fetches **every** configured source. Deprecation is a question about the
union of all sources (5.4), and a run that fetched a subset could not answer it. Both
bundled adapters read committed files, so a full compile is cheap.

Lifecycle runs **before** the build stage, not over its output. A deprecated object is
not in the model, because no adapter returned it, and the nodes lifecycle retains must
exist when files are assembled and dated. Lifecycle reads the ID map and mints nothing.
An object new to a run has no IRI yet, and every node in the previous output has one.
That asymmetry is what makes "absent from the sources" an answerable question.

The compiler is **stateless between runs** except for what is in the instance
repository: previous TTL, ID map, namespace lock. It must produce identical results
locally and in CI.

The **build** stage refuses (exit `1`) anything no output could honestly represent, and
names the source ref of the offending object:

- an object in no scheme, in a scheme no source defined, or in the wrong *kind* of
  scheme (a taxonomy value in a glossary);
- a scheme slug that is malformed or renamed since it was minted (3.4.2);
- a cross-reference (`sem:attributeOf`, `sem:source`, `sem:target`, `skos:broader`,
  `sem:enumerates`) that the run did not resolve, that the ID map records as the wrong
  *kind* (`sem:enumerates` runs scheme → entity, 3.3), or that resolves to a node
  **this run does not write**.

The first two decide which *file* an object goes in, so they cannot wait for SHACL
validation (6.1). The rest would otherwise reach a governed file as a triple pointing at
nothing, or at the wrong thing. The build stage asks the last question once the files
are assembled, because the ID map only answers whether an IRI was ever minted, and a
row outlives its node. A relationship may legitimately point at an entity no source
reports any more; that is what deprecation-not-deletion is for.

A dangling `sem:enumerates` is ordinary while an instance is being brought up: a
workbook names its reference entity by that entity's key in the modelling tool (5.3),
so a taxonomy compiled before that source is configured has nothing to point at. The
error message says so.

The build stage reports every problem it can see together, not one per run. CI reads
these messages, and one problem per round trip is the difference between one fix and
five.

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

Credentials never appear in configuration. An adapter names an environment variable
(`token_env`), and the value comes from the CI platform's secret store or the
operator's shell. The compiler enforces this: it **rejects** (exit 2) a configuration
whose keys name a credential rather than a variable, and no loaded configuration object
ever holds a secret value. The rule belongs to the plane and binds every adapter,
including third-party ones that call a network service. Neither bundled adapter needs
a credential, since both read committed files (5.3). The compiler also rejects unknown
keys, so a typo is never silently ignored, and every rejection names the offending key.

### 5.2 Adapter interface (plugins)

The compiler **discovers** adapters through the entry-point group `semprini.adapters`.
Any installed distribution may contribute to it. To add a new source system, an
organization installs a package and names it in `config/semprini.yaml`. No fork, no
patch to this project.

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

Every adapter must meet these obligations, and the core relies on them:

- The compiler, not the adapter, normalizes the text and source keys an adapter returns
  (5.5 rule 9). An adapter cannot opt out, so the guarantee holds for a plugin this
  project has never seen.
- `fetch()` performs **no writes** and mints no identity. It returns normalized objects
  that each carry a `source_key`. Identity resolution is the core's job.
- Objects carry `source_refs: dict[str, str]`, so the same real-world concept seen by
  two adapters merges onto one IRI after identity resolution. Every object carries at
  least one ref under the source's own configured `name`, because that is what keys the
  ID map (5.4).
- A fetch failure raises `SourceUnreachableError` (exit code `3`). An adapter never
  returns a partial model silently. CI acts on this distinction: a source that was down
  is retried, and a source that answered with unusable data is a compile failure (exit
  `1`).
- An adapter contributes only data. It never emits IRIs in another instance's
  namespace and never emits `sem:` terms.
- Construction has no side effects. `semprini check` constructs every configured
  adapter only to call `validate_config()` (6.1 check 8), and must not open a connection
  to do it. Neither construction nor `validate_config()` reads a source, so an instance
  whose `sources/` is absent still checks clean on this step.

The adapters bundled with the plane are ordinary plugins registered by the same
mechanism.

**Discovery imports nothing.** Importing every registered plugin just to list them
would run arbitrary third-party code on every command that loads a configuration.
Import happens when an adapter is about to be used, or in `semprini adapters`, which
exists to report whether the installation works. So one plugin that fails to import
never hides the others, and a source naming an adapter no installed distribution
provides is a *configuration* error (exit `2`), reported with its key.

The compiler refuses an entry point, and names the distribution to uninstall, when it
does not import, does not yield a `BaseAdapter` subclass, leaves `fetch()`
unimplemented, or declares a `name` other than the one it is registered under. The
instance writes that name in `config/semprini.yaml`, so a class calling itself
something else would make every message about it name a thing that appears in no file
the operator can open. An alias is a subclass. The compiler likewise refuses two
installed distributions that claim one entry-point name: `adapter: ellie` must not mean
different things on a laptop and in CI. `semprini adapters` reports that clash too.

**The contract is executable.** The obligations above are all negative, so a violating
adapter looks exactly like a correct one until an instance has committed the damage.
The plane therefore ships `semprini.testing.check_contract()`, which an adapter author
runs against their own adapter from their own test suite. It is framework-free (no
pytest dependency, no base class to inherit), it collects every violation rather than
stopping at the first, and it requires the author to supply both a working
configuration and one whose source cannot be read. An adapter never asked what it does
when its source is down is the adapter that one day answers "deprecate everything"
(5.4).

### 5.3 Bundled adapters (v1)

**Ellie adapter (`ellie`).**

**One Ellie instance is one configured source, and the adapter reads exported files.**
Each domain model is exported from Ellie as JSON, the response body of
`GET /api/v1/models/{id}`, and committed under `sources/ellie/`, where it is reviewed
like any other source. A direct API call is a later mode of this same adapter, not a
second adapter: identity is keyed by `(source name, Ellie UUID)`, so a source that
changed adapters would re-mint every IRI it owns (5.4). For the same reason `base_url`
is configured in file mode: it records *which* Ellie instance the UUIDs belong to, and
appears in the run report.

The instance, not the model, is the unit of a source. Ellie UUIDs are unique across an
instance rather than within a model, which is what lets one entity appear in two domain
models and resolve to one node. So every model of one instance is listed under one
source name; listing them separately would give the same entity two identities. Two
Ellie instances are two sources, since their UUID spaces are unrelated.

The adapter accepts both export shapes: some exports wrap the model in a `model`
object and some do not. It recognizes the document by structure and refuses one that is
neither, by name, rather than reading it as a model with no entities. An empty model
compiles to an empty scheme, which deprecates everything the model used to hold (5.4).
For the same reason the adapter refuses a document with no `entities` key **at all** as
truncated: an export of an empty model states an empty list.

- **Model allowlist.** Ellie contains many models. The adapter ingests only the models
  listed in configuration, keyed by Ellie's model ID. Each entry states the model's
  `id`, the `path` of its export and its `scheme_slug`. The adapter refuses an export
  whose `modelId` disagrees with the `id` it is listed under; otherwise a file copied
  over the wrong path would replace a scheme's entire contents as ordinary change. The
  compiler fails the run if a listed model cannot be read. The run report lists each
  model's ID, its name as the export states it, and its object counts, so a model
  swapped or renamed in Ellie is visible to the reviewer. Removing a model from the
  allowlist removes its `skos:ConceptScheme` and the corresponding `skos:inScheme`
  triples. Because the same Ellie entity can appear in several models, an object is
  deprecated only if it no longer appears in **any** registered model (5.4). An object
  that remains in other models simply loses one scheme membership. The run report
  flags both cases prominently, since delisting is rare and deliberate.
- The adapter reads, per registered model: entities (id, name, description, synonyms,
  examples), attributes (id, name, description, parent entity id), relationships (id,
  name, verb labels, source and target entity ids).
- Mapping: entity → `sem:Entity`; attribute → `sem:Attribute` + `sem:attributeOf`;
  relationship → `sem:Relationship` node + `sem:source`/`sem:target` + one
  `sem:relatesTo` shortcut triple; each registered model → `skos:ConceptScheme`
  (`sem:schemeType "glossary"`, IRI from `scheme_slug`) + `skos:inScheme` for its
  members. The scheme's *source key* is Ellie's model id, not the slug: the slug is
  this instance's name for the scheme, and the ID map is keyed by the source's (5.4).
- **Inheritance becomes `skos:broader`.** Ellie draws a supertype relationship as an
  ordinary relationship whose ends are typed `superType`/`subType`, with no name and no
  verb labels. The adapter emits it as `skos:broader` from the narrower entity to the
  broader one, and emits **no** reified `sem:Relationship` and no `sem:relatesTo`
  shortcut for it, because reifying it would mean inventing a label no modeller wrote
  (3.3). Only that direction is emitted (5.5 rule 4). An entity may have several
  broader entities. The adapter refuses a supertype relationship whose narrower end is
  not among the model's own entities: the fact lands *on* that entity, and without it
  the inheritance would vanish without a diff line.
- **A relationship's `skos:prefLabel` is Ellie's `name` when a modeller filled one
  in.** Otherwise it is the verb label whose direction reads source → target ("Order
  *has one or more* Order line"). A label reads source → target unless its `direction`
  is `"source"`; `"target"` and an **absent** direction both count as source → target,
  since a relationship with a single label often omits the field. Every other verb
  label becomes a `skos:altLabel`. A name that appears later re-labels the node without
  re-minting it (5.4). The adapter refuses a relationship with neither a name nor a
  label: a node needs a label, and inventing one is not an adapter's job.
- Ellie descriptions become `skos:definition`. An empty description emits **no**
  `skos:definition` triple (SHACL reports it as a warning; see 6.1). Entity synonyms
  (comma-separated) become `skos:altLabel`. The entity's examples field becomes one
  `skos:example`, uncut: it is prose a modeller wrote, and splitting it on commas would
  invent several statements where the source made one.
- **Not carried, deliberately**: `progressStatus`, entity `type`, `Source systems`,
  `Administrated by`, relationship cardinality, and every attribute metadata field
  except `Description` (`PK`, `FK`, `Data type`, `Not null`, `Unique`, `Semantic link`
  and the rest). Each would need a term the metamodel does not have, and the metamodel
  does not mint one term per Ellie field (3.3). An attribute's `Data type` and
  `Semantic link` are what `sem:represents` is reserved for (3.1). Adding any of them
  is a metamodel version bump (7).
- An entity that appears in several domain models must resolve to the **same** Ellie
  UUID (Ellie's cross-model reuse). The compiler merges its statements onto one node
  with several `skos:inScheme` triples. Two distinct UUIDs with the same name remain
  two nodes; the run report flags them for stewards.

**Excel taxonomy adapter (`excel-taxonomy`).**

**One workbook is one taxonomy is one configured source.** Each workbook under
`sources/taxonomies/` gets its own entry in `config/semprini.yaml`, carrying just a
`path` and a `scheme_slug`. Everything else about the scheme comes from the workbook.
Every object in that workbook carries the source's `name` in its `sem:sourceRef`, so
provenance says *which file* an object came from.

Two consequences of that arrangement matter:

- **A source name never names the adapter.** `source_name` is half the ID map's key
  (5.4) and is therefore permanent. Naming a source `excel-product-category` would
  re-mint every IRI in it the day the same taxonomy arrives in another format (3.3).
  The configuration and the run report (5.6) record which adapter read a file, and
  neither is identity.
- **The path is not the name either.** It lives in `config:` so a workbook can be
  moved or renamed without re-keying its contents. For the same reason the *scheme* is
  keyed by its slug and not by its file name.

`scheme_slug` stays in the configuration rather than in the workbook because it names
two permanent things, the scheme's IRI local name and its output file (4.2), and the ID
map freezes both on the run that mints them.

**Sheet 1, `Concept Scheme`**: a vertical Property/Value table. `Scheme Name` is
required and becomes the scheme's `skos:prefLabel`. `Description` becomes its
`skos:definition`. `Language` is a BCP 47 tag applied to every cell in the workbook
that states none of its own. `Reference Entity UUID` is optional; it is the *source key*
of the entity this taxonomy enumerates (`sem:enumerates`). The compiler resolves it
against the ID map when it builds the graph, under the source named by the configured
`enumerates_source`, which is required exactly when that cell is filled. The source
name lives in the configuration because this instance chooses it (5.1): the workbook
states a UUID, and which configured source issued that UUID is not a fact about the
workbook. The compiler refuses (exit `2`) an `enumerates_source` naming the taxonomy's
own source, where an entity's key can never be found (5.4). Any other row (creator,
dates, version, domain) is documentation for whoever maintains the workbook, and
nothing reads it.

**Sheet 2, `Taxonomy`**: one value per row, header row required:

| Column | Required | Maps to |
|---|---|---|
| `Concept URI` | yes | identity key for UUIDv5 minting — **not** an emitted IRI |
| `L1..Ln - Preferred Label` | yes (at least `L1`) | `skos:prefLabel`, and the hierarchy |
| `Definition` | no | `skos:definition` |
| `Alternative Labels` | no (`;`-separated) | `skos:altLabel` |
| `Hidden Labels` | no (`;`-separated) | `skos:hiddenLabel` |
| `Scope Note` | no | `skos:scopeNote` |
| `Example` | no | `skos:example` |

The adapter matches headers on their **first line**, lower-cased. These sheets carry
the SKOS mapping on a second line, which is documentation and no part of a column's
name. The adapter tolerates and ignores columns it has no home for: a workbook is a
working document and gains columns for reasons of its own, unlike a configuration file
(5.1). The level columns are the exception. They must run `L1..Ln` with none missing,
because the adapter reads depth from a cell's position among them.

A cell may use Turtle's literal syntax (`"Power tools"@en`) to state its own language,
which overrides the sheet's. Two rules keep this from quietly corrupting text:

- Semicolon separation applies **outside** quoted literals only. A cell reading
  `"A; B"@fi; "C"@fi` is two labels.
- A cell counts as literal syntax only when the quoted part contains no further
  quotation mark. Prose that merely opens and closes with one (`"Smart" tools "here"`)
  is a sentence somebody wrote, and a greedy match would delete its outer characters.
  The cost is that a label genuinely containing a quotation mark keeps its outer
  quotes. Taking a cell too literally is recoverable; quietly editing it is not.

**Hierarchy is ragged.** A row's depth is the position of its last filled `L` cell, and
its broader concept is the row whose labels are its own first *n-1*. Two things follow:

- **A cycle cannot be expressed.** A row's ancestors are a prefix of its own cells, so
  there is nothing to close a loop with.
- **A label is structural**, so renaming an `L2` cell re-parents everything beneath it.
  This is why identity comes from `Concept URI` and never from the labels: a taxonomy
  can be re-worded without minting a single new IRI (5.4).

The adapter matches hierarchy on label *values*, not raw cells, so a workbook that tags
some cells and leaves others bare still describes one branch.

Compile errors. The adapter reports all of them together, because a taxonomy is edited
in bulk and its mistakes arrive in bulk:

- A row whose parent path matches no row.
- Two rows at the same path, or sharing one `Concept URI`.
- A row that **skips a level** (`L1` and `L3` filled, `L2` empty). Reading it as depth
  2 would attach the value to the wrong parent.
- A row with no `Concept URI`. The adapter refuses it rather than skipping it, because
  a skipped value silently vanishes on the next compile and is deprecated for it (3.5).
  Only a row that is blank **across every column** counts as spreadsheet punctuation.
- A missing `Concept URI` or `L1` **column**, or level columns that do not run
  `L1..Ln`. Header matching is strict because a sheet with mislabelled level columns
  does not read as broken: it reads as empty, which deprecates everything that used to
  be in it. A sheet whose levels start at `L2` is worse: it reads as a *complete*
  hierarchy with every value one level too shallow, and the diff looks like a
  re-levelling nobody performed.

An adapter validates **its own configuration before it reads anything**, so a run that
never invoked `semprini check` still fails with the offending key rather than with a
traceback, or with an absolute `path` silently overriding the repository root.

A workbook that cannot be read at all is exit 3 (unreachable). Every error above is a
compile failure, exit 1.

### 5.4 Identity management

**`mappings/id-map.csv`**: an append-only registry with the columns
`iri, kind, source_name, source_key, first_seen, note`.

- On every run, the compiler looks up each normalized object by
  `(source_name, source_key)`. It normalizes the key first (5.5 rule 9), so two
  spellings of one identifier that differ only by an invisible character are one key.
  A hit reuses the IRI. A miss mints per 3.4 and appends a row. An object known to
  several sources has **one row per source ref**, all carrying the one IRI. These are
  the same pairs it carries as `sem:sourceRef` triples (3.3), so the registry and the
  RDF cannot tell different stories. If those refs are already mapped to *different*
  IRIs, the run fails: the sources say one object and the map says two, and only a
  steward can decide which survives (`merges.csv`, below).
- `kind` is recorded, but it is not part of the key. A source key that arrives
  describing a different kind than the one recorded is an error, because its IRI is
  already minted in another kind's namespace.
- **Distinct objects must resolve to distinct IRIs**, and the compiler checks this over
  the whole model. Several rows legitimately share an IRI, because that is what a
  multi-source object looks like, so a lookup alone cannot tell the difference. If the
  cross-reference that merged two objects later disappears from the sources, both
  arrive separately and both hit those rows. Without the check the compiler would emit
  a single node wearing two `skos:prefLabel`s. Reconciling them is the sources'
  business or the merge register's, never the compiler's.
- The file is UTF-8 with LF line endings, and its rows keep the order they were
  appended in. A compile PR's diff over it should be additions only. "Append-only"
  means every column of an existing row is immutable **except `note`**, which is the
  one field stewards own. The compiler tolerates a byte-order mark on read, because
  stewards open the file in tools that add one.
- The ID map, not the minting formula, is authoritative. This lets identity survive
  code renames, file moves, changes to the minting rules, and compiler upgrades.
- `source_name` is the name given to a source in `config/semprini.yaml`. Renaming a
  configured source therefore breaks identity resolution. `semprini check` treats a
  `source_name` present in the ID map but absent from configuration as an error. The
  documented rename procedure rewrites the column in one reviewable commit.
- CI fails if a run would produce an IRI collision (two source keys → one IRI) or
  remove a row.

**`mappings/merges.csv`**: a hand-maintained register with the columns
`deprecated_iri, replaced_by_iri, date, note`. When stewards merge two concepts in a
source tool, the tool usually just deletes one. The stewards add a row here, and the
compiler then emits the deprecation plus `dcterms:isReplacedBy` instead of a bare
deprecation. The file is UTF-8 with LF line endings and tolerates a byte-order mark on
read. The compiler never writes a row into it: every row is a steward's decision.
`date` is recorded for the reader and never acted on. The compiler emits only
`dcterms:isReplacedBy`, on the deprecated node, never the `dcterms:replaces` inverse
(3.3).

This is the one file in an instance where a person types an IRI, so the compiler
validates it strictly, and every rule below refuses rather than repairs:

- **Both IRIs must exist in the ID map.** A row naming an IRI this instance never
  minted deprecates nothing and points at nothing.
- **One deprecated object has one successor.** Two rows for one `deprecated_iri` leave
  the register's only question, which of these survived, unanswered.
- **No row replaces an object with itself, and no chain of rows closes into a cycle.**
  Following `dcterms:isReplacedBy` around a cycle never arrives at a surviving object.
- **Chains are allowed and are not followed.** If A → B was recorded and later B → C,
  the compiler emits A's successor as B. That is the statement the steward made, and
  rewriting it to C would put a triple in a governed file that no row supports.
- **A successor may itself be deprecated later, and that is not an error.** A was
  merged into B, and B was afterwards retired by its own source. That is ordinary
  history. Only a *cycle* is refused, because a cycle never had a survivor.
- **A row for an object the sources still describe fails the run** (exit 1). The
  register and the sources contradict each other, and the compiler settles neither.
  Deprecating anyway would let a one-line CSV edit override every source; ignoring the
  row would make the register silently inert.

Removing a row removes the `dcterms:isReplacedBy` triple on the next run. The compiler
reads the register as it stands, so a steward can undo a decision and see it undone.

**Deprecation detection.** The compiler evaluates deprecation against the **union of
all configured sources** in the current run, never against a single source or model.
An object present in the previous generated output (and in the ID map) but absent from
that union is re-emitted with `sem:status "deprecated"` and all its last-known
statements preserved. An object that merely disappeared from one model or source while
remaining in another loses only the corresponding `skos:inScheme` (or other
source-specific) statements. Deprecated nodes are carried forward on later runs and are
never physically removed.

A retained node keeps the file it was already written in, so its deprecation is one
changed `sem:status` line. The ordinary rule (3.3) decides its `dcterms:modified`: the
status change is a content change, so the date moves on the run that deprecates the
node and never again. Only the block that *describes* the node, the one carrying its
label, is marked; a file that merely mentions it through a `sem:relatesTo` shortcut
(4.2) is unchanged. Deprecation is a status, not a tombstone: the ID-map row is
untouched, so an object a source restores becomes active again under the IRI it always
had.

**Scope.** Every run fetches every configured source (5.1), so every run can judge
every object. Nothing is carried forward unjudged.

**Removing a source from `config/semprini.yaml` therefore deprecates everything it
owned**, on the next run, in one reviewable commit. A source that is not configured
reports nothing. This is not a deletion: the statements are kept, the ID-map rows are
untouched, and re-adding the source makes those objects active again under the IRIs
they always had. `semprini check` reports an ID map naming a source that is not
configured (6.1 check 6), so an accidental edit is caught before a run acts on it.

**An IRI in `generated/` that the ID map does not hold fails the run** (exit 1). It
means a row was deleted or a file was hand-edited (4.3). The compiler cannot say which
source the node came from, and dropping it would be the deletion this mechanism exists
to prevent. This check does not use git, unlike the append-only check (6.1 check 6),
so it holds for a local run as well as in CI.

### 5.5 Canonical serialization

Deterministic output is a hard requirement. It makes PR diffs reviewable, and it lets
an instance trust a compiler upgrade. `rdflib`'s default Turtle serializer is **not**
deterministic, so the compiler implements its own with these rules:

1. Fixed prefix block (the namespaces of 3.1 in that order), even if unused.
2. Subjects sorted lexicographically by IRI; each subject serialized as one block.
3. Within a subject: `a` (rdf:type) first, then `skos:prefLabel`, then the remaining
   predicates sorted lexicographically by IRI. Multiple objects per predicate are sorted
   lexicographically: IRIs before literals, literals by lexical form, then language
   tag, then datatype.
4. One triple per line; two-space indentation; `;` continuation style as in 3.7. A
   predicate with several objects **repeats the predicate**, one object per line,
   rather than joining them with `,`: one changed fact must be one changed line. A
   single blank line separates subject blocks.
5. UTF-8, LF line endings, newline at EOF. No comments in generated files.
6. Language tags are always present on the text-valued properties: `skos:prefLabel`,
   `skos:altLabel`, `skos:hiddenLabel`, `skos:definition`, `skos:scopeNote` and
   `skos:example`. (`skos:notation` is untagged: a notation is a code, not prose.)
   Each instance sets one `default_language` in `config/semprini.yaml` (default `en`).
   The compiler applies it to every label and definition that arrives without a
   language of its own. A label that arrives **with** one keeps it, so an instance has
   one language by default but is not limited to one.
7. **No blank nodes in generated output.** Every node the compiler emits has an IRI.
   Blank-node labels are not stable across runs and would defeat the determinism check.
   Any construct that would need one must use a deterministically minted IRI instead
   (3.4).
8. No run timestamps anywhere in generated output. `dcterms:modified` reflects content
   change only (3.3).
9. **The compiler normalizes text on the way in**, before it becomes a label, a
   definition or a key. Four steps, in this order, applied to every text and every
   source key an adapter returns: Unicode **NFC**; every character of general category
   `Zs`, `Zl` or `Zp` becomes an ordinary space; `U+200B`, `U+FEFF` and `U+00AD` are
   deleted; the result is stripped. The procedure is idempotent, which keeps a
   recompile byte-identical (6.1). Left alone deliberately: `U+2011`, tabs and newlines
   inside a value, `U+200C` and `U+200D`, and runs of interior whitespace, which are
   **not** collapsed. **NFKC is never applied**: it folds ligatures, superscripts and
   units, which is content damage.

   Two reasons. A literal differing only by an invisible character renders identically
   in a diff, so a reviewer would see a changed line with nothing visibly changed
   (1.2). And an invisible character in a source key is a different key, a different
   minted IRI, and an ID-map row frozen on the run that mints it (5.4). The compiler
   judges emptiness **after** normalization, so a value that normalizes to nothing is
   absent rather than a literal nobody can see.

   The run report (5.6) states the count of normalized values per source where there is
   one. It does not report per value: the fix usually lives in a source file the
   steward may not own, so a per-value warning would be permanent noise.

The serializer writes each term the one way the rules allow: prefixed where the local
name needs no escaping and as a full `<IRI>` otherwise, `a` for `rdf:type`, and
literals as single-line quoted strings with control characters escaped. It writes an
`xsd:string` literal in the plain form, and only once, since the two forms are the same
RDF term. It writes a character an `<IRI>` cannot carry raw as its `\uXXXX` escape, so
a malformed IRI from a source never produces a file that will not parse.

CI's determinism check recompiles from a cached fetch snapshot and requires
byte-identical output (6.1).

### 5.6 Run report

`generated/.report.md` carries: compiler and ontology versions, counts per class and
per file, new/changed/deprecated objects, objects missing definitions,
same-name/different-IRI warnings, and per-source fetch summaries. The compile workflow
pastes it into the PR description. It is the reviewer's summary.

Everything in it is derived from the graphs the run produced and the state they
replaced, never from what an adapter believed it fetched. One comparison decides both
"changed" and a refreshed `dcterms:modified` (3.3), so the report and the Turtle beside
it cannot tell different stories. Lifecycle decides deprecation (5.4), and the report
reads that decision from the output rather than taking it as an input.

New, changed and deprecated **partition** the nodes, so "Changed 12 · Deprecated 3"
means fifteen nodes. "Deprecated" counts the nodes this run deprecated, not every
deprecated node in the instance. The report carries no timestamp and no run identifier
(5.5 rule 8). Each listing of nodes is capped; the counts above it are not.

**The compiler rewrites the report only when the run changed something.** A run whose
output is byte-identical to what is committed leaves it alone. Otherwise a scheduled
no-op compile would rewrite "12 new" to "0 new" and open a PR containing nothing else
(1.2, 4.3). A committed report is therefore always the report of the run that produced
the files beside it.

"Changed something" is about the instance, not only about the bytes produced. The
`.manifest.json` the run writes is part of the comparison, so a recompile after a plane
upgrade rewrites the report. A run that produced byte-identical files while *removing*
stale output (4.3) has also changed the instance and rewrites the report.

`semprini migrate` (7) replaces the file with a **migration report**: the versions
upgraded from and to, the steps that ran, what happened to each file, and confirmation
that no IRI was minted and no ID-map row was lost. The rule is the same: the committed
report describes whatever last produced the files beside it.

### 5.7 Bootstrapping an instance

`semprini init --base-iri https://semantics.acme.com/ --org acme [--language en]`:

1. Materializes `templates/instance/` into the target directory (4.2), `.gitattributes`
   included (4.3). Directories a steward has not filled yet, the three under
   `overlays/` and the two under `sources/`, get a keep file, since git cannot commit
   an empty directory. `overlays/` and `shapes/local/` each carry a README, so an
   adopter meets the rules those directories follow before a file of theirs is
   rejected.
2. Writes `config/semprini.yaml` with the base IRI, instance id and default language,
   and an empty `sources:` list.
3. Writes `mappings/namespace.lock` (3.4) and empty `id-map.csv` / `merges.csv` with
   headers.
4. Writes `generated/ontology.ttl` (the pinned metamodel) and a manifest. A fresh
   instance has no content, so that is the whole of `generated/`. This lets `semprini
   check` pass on an instance that has never been compiled, which an adopter's first CI
   run is. It is also byte for byte what a run would produce, so the first scheduled
   compile finds nothing to change and opens no pull request.
5. Writes the two workflows (6.2) for the target CI platform, pinned to the plane
   version that produced them.
6. Prints the required secrets and the next steps. It makes **no** network calls and
   creates no remote repository (11 #8).

**Nothing is written until every refusal has been made.** The command renders the
whole tree in memory first, so a bad argument or an occupied directory leaves the
target exactly as it was. There is no half-created instance. Every refusal is a
configuration error, exit code 2.

The command refuses to run in a directory that already contains a `namespace.lock`: the
base IRI frozen there is a decision that cannot be taken twice, and a second bootstrap
would mint a parallel set of IRIs. It also refuses on **any** file it would otherwise
overwrite, because nothing in the scaffold is safe to clobber.

**A source tree cannot bootstrap an instance.** Two of the files above pin the plane
version, the workflows and the manifest, and `0.0.0+source` identifies no release (4.3,
7).

---

## 6. Validation and CI

### 6.1 Checks

`semprini check` implements every check. CI invokes the CLI and nothing else (6.3). The
command reads the instance and writes nothing, so it is safe to run where it has no
permission to write.

Every check runs and every check collects its findings, so one CI round trip reports
every problem. Check 1 is the exception: content that does not parse cannot be asked
what checks 4–7 ask, so the command reports those as **not run**. A check that could
not run is never reported as passed, and it does not fail the command. The only other
check that can report itself not run is the append-only half of check 6, which needs a
base revision that does not always exist.

Exit `1` for any error, `0` when only warnings were found, `2` for the two
configuration categories below. The checks, all blocking unless noted:

1. **Syntax**: every `.ttl` parses (rdflib).
2. **Manifest integrity**: `generated/*` hashes match `.manifest.json`, every recorded
   file is present, and no unrecorded file exists (4.3). This blocks hand edits to
   generated files and stale output alike.
3. **Version drift**: the compiler and ontology versions recorded in `.manifest.json`
   match the versions actually running. This makes a plane upgrade a deliberate,
   separately reviewable `semprini migrate --to <version>` PR rather than a surprise
   reflow of every file mixed into a content change (7). The finding names what to do,
   and which version is newer decides that: an instance ahead of the installed release
   needs its *pin* changed, not a migration, since migrations only move forward.
4. **Namespace lock**: the base IRI in `config/semprini.yaml` matches
   `mappings/namespace.lock` (3.4), and every generated subject IRI falls under it. The
   two halves fail differently. A base IRI that disagrees with the lock is exit `2`
   and aborts, because nothing else the command reports would be meaningful under a
   base IRI the instance does not have. A subject outside the base is an ordinary
   finding. The subject rule is weaker than check 5's IRI policy, which also demands
   the namespace of the subject's *kind* and the local name 3.4.2 mints, but it holds
   for a subject no shape targets.
5. **SHACL** (`pyshacl`): the core shapes from the package plus every shape in
   `shapes/local/`. The core shapes' own IRIs live in
   `https://w3id.org/semprini/shapes#`, never in `sem:`, because that namespace
   resolves to the metamodel document, whose term inventory 3.2 and 3.3 fix. The core
   shapes select a taxonomy value with a SPARQL target and therefore need **SHACL
   advanced features**. `semprini check` enables them; a validator run without them
   reports fewer violations rather than failing.

   **Which graph each set of shapes judges** is part of the contract:
   - The **core shapes** judge `generated/` alone, without `generated/ontology.ttl`.
     They state what the compiler guarantees about its own output. They are not applied
     to `overlays/`, which may hold curated subsets of external vocabularies (4.2):
     those concepts carry no `sem:status`, belong to no scheme of this instance, and are
     nobody's to deprecate.
   - The **overlay rules** below judge `overlays/` alone. Which file a statement came
     from is the whole question, and the union of the two graphs no longer knows.
   - **Local shapes** judge `generated/` and `overlays/` together: the organization's
     data as its stewards see it, including their own `x:` terms (3.6).

   The constraints:
   - Every node the compiler writes (`sem:Entity`, `sem:Attribute`,
     `sem:Relationship`, `sem:BusinessTerm`, taxonomy concept **and
     `skos:ConceptScheme`**) has exactly one `skos:prefLabel` per language, each
     language-tagged (5.5 rule 6), and `sem:status` exactly once with an allowed value.
     Schemes are included because 3.5 applies to every object.
   - Every one of those except a scheme has at least one `skos:inScheme`, naming a
     declared `skos:ConceptScheme`. A scheme is not itself in a scheme.
   - `skos:definition` is present. This is a **warning** (reported, not blocking). An
     instance switches it to blocking when its steward workflows are ready. The check
     applies to entities, attributes, business terms and taxonomy values only: a
     relationship's label is its verb and a scheme's label is its title. A definition
     that *is* present must carry a language tag, and that part is an error.
   - `sem:Attribute` has exactly one `sem:attributeOf`. `sem:Relationship` has exactly
     one `sem:source` and one `sem:target`, both `sem:Entity`.
   - `skos:ConceptScheme` has exactly one `sem:schemeType`, `"glossary"` or
     `"taxonomy"`. A `sem:enumerates` names a `sem:Entity` (3.3).
   - `skos:broader` holds only between two nodes of the same class: taxonomy value to
     taxonomy value within one scheme, or entity to entity (inheritance, 3.3), and with
     **no cycles** of any length. Nothing earlier in the pipeline can catch a cycle,
     because an adapter sees one source and inheritance drawn across two sources can
     close a loop neither one holds. The metamodel has those two hierarchies and no
     others, so the check refuses `skos:broader` on an attribute, a relationship, a
     business term or a scheme. A glossary adapter that brings term-to-term hierarchies
     relaxes this in the same change that adds the adapter. A `skos:broader` chain
     some thousand levels deep is reported as *too deep to check* rather than checked,
     because validators evaluate the closure recursively.
   - `skos:notation` is unique within a scheme and untagged (5.5 rule 6). The same code
     in two taxonomies is ordinary.
   - Deprecated nodes have no incoming `skos:broader` or `sem:attributeOf` from active
     nodes.
   - IRI policy: subject IRIs are under the instance's namespace **for their kind**
     (3.1), with the local name 3.4.2 mints: a UUID, or a slug for a scheme. This
     applies to `generated/` only. An overlay's own `x:` term is what 3.6 exists to
     allow.
   - Overlays may add statements about generated IRIs but never redefine
     `skos:prefLabel`, `sem:status`, or scheme membership of a generated node.
   - **Local shapes are additive only**, and this is what that means. A local shape may
     *target* anything, `sem:` classes included (`sh:targetClass sem:Entity` is how a
     local rule says what it is about), and may be as strict as its stewards like. The
     check rejects four things, naming the file:
     1. **A statement about a core IRI**: any subject in the `sem:` namespace (3.2,
        3.3) or in the core shapes' own (`https://w3id.org/semprini/shapes#`). This
        catches `core.ttl` copied into `shapes/local/` and edited, `sem:Entity a
        sh:NodeShape` (SHACL's implicit class target, which turns a metamodel class into
        a shape), and `sh:deactivated true` on a core shape. The rule covers whole
        namespaces rather than the terms that exist today. Naming a core IRI as an
        *object* is allowed.
     2. **A constraint parameter that constrains nothing**: `sh:minCount 0`,
        `sh:uniqueLang false`, `sh:closed false`. Each is a no-op in SHACL, and each is
        what "make the core rule optional here" looks like when written down. That
        cannot work: validation is the sum of every shape, so a local file can add a
        rule but cannot remove one.
     3. **A SHACL rule** (`sh:rule`), which derives statements into the graph being
        validated. Shapes judge the graph. Hand-written statements belong in
        `overlays/` (4.2), where a diff shows them.
     4. **A reference to a core shape**, in any position. Local shapes are validated as
        their own graph, which does not hold the core ones, so the reference either
        matches everything or aborts the validator.

     The check does **not** apply a rejected file's rules; it still applies the other
     files'. Local shapes constrain instance data. They cannot license data the core
     shapes forbid.
   - **A local shape that is not usable SHACL is a finding, not a crash.** A property
     shape with no path, two paths on one, a pattern that is not a regex or a
     `sh:select` that is not a query are ordinary mistakes in a hand-written file, and
     they raise from inside the validator, which does not name the file. The check
     reports the failure as an error against the file that caused it, validates the
     files that do load in the same pass, and where only their *union* fails, reports
     the finding against `shapes/local/` itself.
6. **Identity checks**: the ID map is append-only versus the base branch; there are no
   collisions; every subject IRI in `generated/` exists in the ID map; every
   `source_name` in the ID map is configured (5.4); and the merge register names IRIs
   the map holds.

   Only the first needs anything outside the working tree. "Append-only" is a claim
   about a *change*, so the check judges it against `--base <rev>`, or, absent that,
   the base branch CI names (`GITHUB_BASE_REF`) or the remote's default branch
   (`origin/HEAD`). It compares against the **merge base** of that revision and
   `HEAD`, never the branch tip; otherwise a row another pull request merged since this
   one forked would count as deleted. The check never guesses `main`: a check that
   quietly measures the wrong branch is worse than one that says it measured nothing.
   Where no revision can be resolved, or the ID map at it cannot be read, this half
   reports itself **not run** and the other parts still answer. A base revision
   holding no ID map is an empty map, not a failure: that is the pull request that
   creates the instance.
7. **Determinism**: the check re-serializes the parsed graphs with the canonical
   serializer, and the output must be byte-identical to the committed files, line
   endings included (5.5 rule 5). This is the check that does not trust the manifest:
   a hand edit that recomputes the hash defeats check 2, and this one re-derives the
   content from the graph. The check compares `ontology.ttl` against the metamodel the
   running compiler carries rather than re-serializing it, since the compiler copies it
   verbatim (4.2). It skips that comparison when check 3 found the recorded ontology
   version drifting, because the committed copy is then expected to differ.
8. **Source configuration**: the check constructs every configured adapter and asks it
   for its own verdict on its own settings through `validate_config()` (5.2).
   Configuration loading judges what the compiler defines (a source's name, its
   adapter, a key holding a credential); what is under `config:` belongs to the
   adapter. Without this step a mistyped sheet name or a malformed scheme slug would
   pass review and fail on the first compile after it merges.

   Findings here are ordinary findings: exit `1`, not the exit `2` a namespace lock or
   a credential in configuration aborts with. A source whose settings are wrong
   invalidates none of checks 1–7.

   This is also the only check that still answers when check 1 fails, because it asks
   about configuration rather than about RDF. And it is the one point in `semprini
   check` where third-party code runs, under the 5.2 contract that construction has no
   side effects and reads nothing. An adapter that breaks the contract, by raising from
   construction or from `validate_config()`, or by returning something that is not a
   list of issues, is reported as a finding against the source that configured it,
   never as a traceback.

The plane's own test suite runs the same checks against `tests/fixtures/acme/`, a
complete synthetic instance with a mocked source API and sample workbook, plus golden
TTL. Any change to the serializer or metamodel that alters output shows up there as a
reviewable diff, which makes the determinism guarantee (5.5) auditable rather than
merely asserted.

### 6.2 Workflows

Each instance has two workflows, both thin:

- **`validate.yml`**, on every PR and on main: install the pinned plane version and run
  `semprini check`. It checks out enough history for check 6 to resolve a base revision,
  or passes `--base` explicitly. A single-commit checkout, which several CI platforms
  use by default, silently turns the append-only comparison off.
- **`compile.yml`**, on a schedule and on manual dispatch: install the pinned plane
  version, run `semprini run`, run `semprini check` on what it produced, and if
  `generated/` or `mappings/` changed, open a PR (branch `compile/<date>`) with
  `generated/.report.md` as the description. It never pushes to main. Three details
  follow from the platform. A run that changed nothing writes no report (5.6) and
  leaves nothing to commit, so the PR step is conditional on that file existing and
  must tolerate an empty staging area. The branch is named after the date, so a
  workflow dispatched twice in one day meets its own branch and its own open PR, and
  updates both rather than failing. And a CI platform will not run a workflow on a PR
  its own token opened, so `validate.yml` does not report on a compile PR; that is why
  `compile.yml` validates before it proposes.

  On GitHub the consequence is sharper than "no check runs". GitHub creates the
  `pull_request` run, with actor `github-actions[bot]`, and parks it with conclusion
  `action_required` and no jobs, so it contributes no check run to the PR. Where
  `validate` is a required check, the PR is **unmergeable** (`mergeable_state:
  blocked`) until a human opens that run and approves it. So on a protected main every
  compile PR costs one click. The instance README says so, since this looks like a
  fault and is not: `compile.yml` has already run the same check on the same files. An
  instance that gives the PR step a credential of its own, a PAT or an app token, gets
  the check run on the PR itself and merges without the click.

Branch protection on an instance's main: PRs only, validation must pass, at least one
review.

### 6.3 Portability

**Every check and every side effect lives in the CLI.** Workflow files only install
the package, run a command, and (for `compile.yml`) open a PR. Consequences:

- An adopter on GitLab, Azure DevOps or on-prem Bitbucket ports the plane by
  contributing a YAML file, not by reimplementing logic. **The plane ships GitHub
  definitions only**, because a port nobody runs against a real instance is untested
  template text. The first adopter on another platform contributes one.
- `semprini check` behaves identically on a developer's laptop and in CI, so failures
  are reproducible locally.
- The plane depends on no GitHub-only feature for correctness. PR creation is the one
  platform-specific step, isolated in the workflow layer.
- **That step uses the platform's own CLI, `gh` or `glab`, and never a third-party CI
  action.** A shipped workflow runs in every instance with write access to `generated/`
  and `mappings/`, and an action referenced by a moving tag is code that changes
  without a diff anyone reviews. The step is roughly a dozen lines of shell. It runs
  nothing but `git`, the platform CLI, and the shell's own `date`, which the
  `compile/<date>` branch name of 6.2 requires. A workflow may contain no other logic:
  every step in a shipped workflow is a checkout, a language setup, the pinned install,
  a `semprini` subcommand, or that one step, and the plane's test suite reads the
  shipped files and enforces exactly that.

---

## 7. Versioning and compatibility

Adopters upgrade on their own schedule, so compatibility is a published contract.

**Two version numbers.**

- **Compiler version**: semantic versioning of the `semprini` package.
- **Ontology version**: the `sem:` metamodel's own version (`owl:versionInfo` in
  `sem.ttl`), incremented independently. A metamodel change is breaking for adopters
  even when the Python API is untouched.

`generated/.manifest.json` records both, and the drift check enforces them (6.1).

**Change classes.**

| Change | Compiler | Ontology | Adopter impact |
|---|---|---|---|
| Bug fix, no output change | patch | — | upgrade freely |
| New optional feature, output unchanged for existing config | minor | — | upgrade freely |
| New `sem:` term, nothing existing altered | minor | minor | upgrade freely; new term appears when used |
| Serialization change (reflows files) | major | — | deliberate recompile PR; diff is large but content-neutral |
| `sem:` term removed, renamed, or given new meaning | major | major | migration required |
| IRI minting rule change | major | — | none, if the ID map is honoured (5.4) |

**Migrations.** A release that changes emitted output ships a migration, invoked by
`semprini migrate --to <version>`. It rewrites `generated/` (and, where necessary, the
ID map) deterministically in one commit, so the adopter sees a migration diff, not an
unexplained reflow. A migration never mints new IRIs for existing objects and never
removes ID-map rows.

A migration reads `generated/` and `mappings/id-map.csv` and **never the sources**.
That is what makes the diff provably about the upgrade: the command has no way to bring
in a content change. Two things follow, and both are contract:

- **A migration is not a recompile.** If the new release emits different content from
  the same sources, the next scheduled compile brings that in, in its own pull request.
- **A recompile is not a migration.** A node no source reports any more is re-emitted
  verbatim from the previous run's output (3.5), so a recompile carries its *old*
  statements forward untouched. A term rename performed by recompiling would reach every
  active node and miss every deprecated one.

`--to` must name the compiler version **installed**. A release's migrations exist only
in that release, and the manifest records the release that wrote the files, so a
partial migration has no version to record. Naming the version catches a workflow that
pinned one version and installed another, before anything is rewritten. The command
refuses a migration to an older version: steps run in one direction only.

Each step declares the release that introduced its change, and it runs when the
instance was compiled with something older. An adopter three releases behind runs three
steps in order, and a patch release with no step is not a gap. A release that changes
no output ships no step. `semprini migrate` then re-serializes the committed graphs
unchanged, refreshes the copied metamodel and restamps the manifest, which clears the
drift check (6.1 check 3) without reading a source or a credential. Migrating an
instance that is already current writes nothing.

**Four things a migration may not do.** The command enforces them after the steps run
and before anything is written:

- The set of subjects in `generated/` must be unchanged. A migration changes what is
  said about the instance's objects, never which objects exist.
- Every `dcterms:modified` must be unchanged. The date records when the instance's
  knowledge of an object changed, and how that knowledge is written down is not
  knowledge.
- The ID map must gain no row, lose none, have none rewritten and come back in the
  same order. A step may write the `note` column stewards own and nothing else.
- Every file a migration produces must be a `.ttl` file directly inside `generated/`.

Nothing is written unless all four hold, so a refused migration leaves the instance
exactly as it was. A migration also **refuses to run against a `generated/` that
disagrees with its manifest**: restamping somebody's hand edit as the new release's
output would destroy the hash that would have caught it.

A migration writes the ID map **before** the generated files, the opposite of a
compile's order (5.4). A compile writes the files first because it mints, and
`generated/` holding an IRI the map has never heard of is unrecoverable. A migration
mints nothing, but the manifest is written with the files, and a crash between the two
would leave an instance already recording the new version, which the next invocation
would read as nothing to migrate.

The drift check reports the direction drift points in (6.1 check 3), because only one
direction is an upgrade. An instance already migrated to a newer release than the one
installed, which is what a pull request looks like between the migration commit and the
workflow pin being updated, cannot be migrated backwards. The check tells that operator
to install or pin the recorded version instead.

Because a migration writes and judges nothing, `generated/.report.md` becomes a
**migration report** (5.6). Whether the migrated instance is committable is `semprini
check`'s answer, not the migration's.

**Publication.** A release is a tag (`vX.Y.Z`) carrying a wheel and an sdist. There is
no package index (11 #3). The tag is an address as well as a label: the workflows an
instance runs build their install URL out of it. A release's version is stated by the
tag, by the package metadata, by the changelog and by the ontology archive, and the
release process refuses a release whose statements disagree.

**Every ontology version that has resolved goes on resolving.** `/ontology/X.Y.Z/` is
a permanent identifier, so a released version is published from a frozen copy taken at
its release rather than from the working tree, and each version's documentation is
generated from its own document. **A released ontology version is immutable.** Changing
a term means a new version. The frozen copy and the shipped document are compared byte
for byte, and a disagreement is a failure.

**Support policy.** The current major version receives fixes; the previous major
receives migrations only. The metamodel namespace itself never changes. Versioning
happens inside the ontology document, so IRIs minted in 2026 still resolve unchanged.

---

## 8. Licensing

The project releases two artifact classes, each licensed by the convention for its
kind:

| Artifact | Licence | Rationale |
|---|---|---|
| Compiler, adapters, CLI, workflow templates, scaffold | **Apache-2.0** | permissive with an explicit patent grant — the expectation of enterprise legal review |
| `sem:` metamodel ontology, core SHACL shapes, this specification | **CC BY 4.0** | vocabularies are documents, not programs; adopters must be able to quote and extend terms in their own documentation and derived vocabularies, as SKOS, Dublin Core and schema.org allow |

Both licences live in the repository (`LICENSE`, `LICENSE-DOCS`), and `README.md`
states the split, since a single top-level `LICENSE` would otherwise be read as
governing the vocabulary too. The copyright holder for both is **Datakor Consulting
Oy**, named in the notice of each licence file and in the package metadata.

**Content produced by an instance belongs to the adopting organization**, under no
licence from this project. Nothing in the generated RDF carries an obligation back to
the plane. Only the `sem:` terms it references are project artifacts, and CC BY permits
their use with attribution.

---

## 9. Governance

### 9.1 Instance operating agreement

Each deployment adopts these rules. The CI checks enforce them.

1. Nobody edits generated files by hand. A content fix goes to the source system, and
   then the compiler recompiles.
2. Overlays are the only hand-written RDF. They may add statements about generated
   IRIs but never redefine `skos:prefLabel`, `sem:status`, or scheme membership of a
   generated node (SHACL-enforced, 6.1).
3. Organization-specific terms go in the instance's `x:` namespace. Core `sem:` terms
   are never redefined locally (3.6).
4. A merge of two concepts requires a `merges.csv` entry in the same PR.
5. A plane upgrade is its own PR, never mixed with content changes (7).
6. Review responsibility follows the file: that domain's steward reviews a scheme
   file; the repository owner reviews `mappings/`, `shapes/local/` and `config/`.
7. Tag main after meaningful merges (`vYYYY.MM.DD`). Tags are the citable snapshots of
   the organization's semantics.

### 9.2 Project governance

1. **The metamodel is the compatibility surface.** Additions are welcome under 7.
   Removals and redefinitions are major events that require a migration.
2. **Adapters do not need to be upstreamed.** The plugin interface (5.2) exists so
   that an organization or vendor can ship an adapter independently, under any licence.
   Bundled adapters are those the project commits to maintaining and testing.
3. **A local extension that recurs across adopters is a candidate for the core.** The
   `x:` namespace convention (3.6) is deliberately the low-friction path; promotion to
   `sem:` is the considered one.
4. **Determinism and identity permanence are non-negotiable.** The project rejects a
   contribution that makes output non-reproducible, introduces blank nodes into
   generated files, or changes existing objects' IRIs, whatever its other merit.
5. This repository never names an instance, and no instance's content is used as a
   test fixture. `tests/fixtures/` is synthetic (6.1).

---

## 10. Extension points (design obligations on v1)

- **Collibra adapter**: maps glossary items (business concepts → `sem:Entity`
  statements merged onto existing IRIs via `sem:sourceRef`; business attributes →
  `sem:Attribute`; business terms → `sem:BusinessTerm`) and term–asset links (→
  `sem:isAbout`). Obligations on v1: the adapter interface stays source-agnostic; the
  internal model already carries generic `source_refs`; cross-source merging happens on
  IRI after identity resolution.
- **Knowledge Catalog adapter**: asset entries (→ `a:` namespace, with technical
  classes added to the ontology), entry links (→ `sem:isAbout`/`sem:represents`).
  Requires concept IRIs to be carried in Knowledge Catalog terms (aspect or entry ID),
  which is an obligation on whichever component provisions its glossary.
- **Documents**: `d:` namespace, `schema:CreativeWork`, links via `sem:isAbout`,
  sourced from overlays first and an automated classifier later.
- **Publishing**: a `publish.yml` triggered on an instance's main → package
  `generated/` + `overlays/` → deliver to the serving environment (for example a GCS
  bucket consumed by a loader). Requires no layout change.
- **Cross-instance alignment**: because every instance shares the `sem:` metamodel,
  `skos:exactMatch` between two organizations' concepts is already meaningful. No v1
  mechanism; no v1 obstacle.

---

## 11. Open decisions (to resolve before implementation)

| # | Decision | Status |
|---|---|---|
| 1 | Register the `w3id.org/semprini` namespace and confirm the redirect target | **Resolved.** Registered and live. `https://w3id.org/semprini/ontology` content-negotiates to the ontology document or to its documentation, and versioned paths resolve for each released version. Redirects point at the project's own published site, so resolution depends on no domain beyond w3id.org itself (3.1). Instances may mint IRIs |
| 2 | Licences for code and for the vocabulary | **Resolved.** Apache-2.0 + CC BY 4.0, copyright Datakor Consulting Oy (8) |
| 3 | Distribution channel | **Resolved.** Tagged GitHub releases, each carrying a wheel and an sdist; no package index. The tag (`vX.Y.Z`) is the address: an instance's workflows install the wheel by URL, pinned to the version that created the instance (5.1, 6.2). A later move to an index changes the install line and nothing else |
| 4 | Which adapters are bundled versus separately distributed (5.3) | Ellie and Excel bundled; every later adapter evaluated case by case |
| 5 | Default language and multilingual labels | **Resolved.** One `default_language` per instance, applied to every untagged label and definition; an already-tagged label keeps its tag (5.5 rule 6) |
| 6 | When the missing-definition warning becomes blocking | Per instance, after pilot review |
| 7 | Ellie API rate limits and pagination | **Deferred, not blocking.** The `ellie` adapter reads exported model files (5.3), so it makes no API call. Pagination and rate limits belong to the adapter's later API mode |
| 8 | Whether `semprini init` also creates the remote repository (`gh repo create`) or stays offline | Stays offline (5.7) |

Per-instance decisions (base IRI, source allowlist, stewards and CODEOWNERS) are made
at bootstrap by each adopting organization and are deliberately not listed here.

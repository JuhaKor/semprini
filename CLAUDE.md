# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**This repo is the product, not a deployment.** It builds Semprini — the knowledge plane itself: an
openly licensed Python package (`semprini`) plus a metamodel ontology, core SHACL shapes, CI
templates and an instance scaffold. Organizations run `semprini init` to create their *own* separate
repository holding their config, sources, identity registry and generated RDF. One plane, many
instances — nothing here is ever specific to one customer.

Implementation is under way — `TASKS.md` records what is done and what is next. Two documents
govern the work, alongside one prior-project prototype:

- `docs/rdf-repo-and-compiler-spec.md` — **authoritative** (v0.2). Specifies the metamodel, the
  compiler, the two repository layouts, versioning, licensing and governance. Self-contained: "no
  other background material is required to implement it." When anything conflicts with it, the spec
  wins, and a behaviour change means editing the spec in the same change.
- `TASKS.md` — the build order, one task per session. **Start here.** Each task names the spec
  sections it implements and defines its own verification; a task is done when that verification is
  automated and green, not when the code exists. Tick the box and note anything the next session
  needs before moving on.
- `background-material/kg-converter-old/` — a working converter from an **earlier, similar but
  different** project. Not maintained, **not authoritative for any specification decision** — mine it
  for learnings, never cite it as a requirement.

Target layout is spec §4.1 (`src/semprini/`, `templates/instance/`, `workflows/`, `tests/fixtures/acme/`),
Python 3.12+, `rdflib` / `openpyxl` / `requests` / `pyshacl` / `PyYAML`, CLI per §5.1. Dependencies here
are managed with **Poetry** (`poetry.lock` committed); the shipped wheel is plain, so instances
install it with `pip` and never need Poetry — don't add Poetry to instance templates or workflows. Do **not** create
`generated/`, `overlays/`, `sources/`, `mappings/` or `config/` here — those belong to an instance
(§4.2), and this repo contains no instance content by policy (§9.2 rule 5).

## Reporting back on a task

**Every task report opens with a plain-language summary, and the same summary opens the PR
description.** Not a second version of the commit message: what an adopter or a steward can now
*do* that they could not before, and why that matters to them. Capabilities and consequences, not
modules and function names — someone who does not read Python has to be able to tell what changed
and decide whether it is what they wanted. Where a choice has a downstream effect an organization
would feel (a secret that can no longer be committed, a run that now fails early, a decision that
freezes something permanently), say so in that summary rather than burying it in the detail.

The technical account follows underneath — verification, decisions taken, notes the next session
needs. That part is for whoever writes the next task; the summary is for everyone else, and it is
the part that survives into the repository's history through the PR.

## Blocking open decision

Spec §11 #1: the `sem:` metamodel namespace `https://w3id.org/semprini/ontology#` is not
registered yet. It must resolve before any instance mints IRIs against it. Don't substitute a
different namespace to unblock local work — the whole multi-deployment design rests on every instance
sharing this one.

Registration is under way — see TASKS.md A2, which is the only record of the routing and hosting
decisions, since the drafted w3id files live in the gitignored `background-material/w3id/semprini/`
and are therefore absent from this repo's history.

Base IRIs are no longer a project-level decision: each instance chooses its own at bootstrap and the
namespace lock freezes it (§3.4). Keep `semantics.acme.com` / `https://semantics.example.com/` as
example values only.

## The old project solved a different problem — mine it, don't copy it

`kg-converter-old` and the spec model the same source data (Ellie models, Excel taxonomies) in
fundamentally different RDF. Treating prototype behaviour as a requirement is the main hazard:

| | prototype (old) | spec (current) |
|---|---|---|
| Modelling | OWL: entity → `owl:Class`, attribute → `owl:DatatypeProperty`, relationship → `owl:ObjectProperty` (+ `owl:inverseOf`) | SKOS-based `sem:` metamodel: `sem:Entity`/`sem:Attribute`/reified `sem:Relationship`, all `skos:Concept` subclasses |
| Taxonomy↔model join | OWL 2 punning (class doubles as `skos:ConceptScheme`) | `sem:enumerates` from scheme to entity; no punning |
| Namespaces | one namespace per source model, everything in it | fixed `sem:` metamodel + per-instance content namespaces partitioned by *kind* (`c:`, `r:`, `sch:`, `v:`) |
| Input | Ellie JSON export file | plugin adapters; Ellie via REST API with a model allowlist |
| Output style | commented, sectioned, human-flavoured Turtle | comment-free canonical Turtle, byte-deterministic, no blank nodes |
| Identity | Ellie UUID / readable local names derived on the fly | persistent `mappings/id-map.csv` is authoritative over the minting formula |
| Lifecycle | none (one run = one file) | deprecation, `dcterms:isReplacedBy`, merge register |
| Deployment | one script run, one output file | installable package, pinned per instance, migrations across versions |

What is still worth mining from it: the Ellie export field semantics (README §1.1 tables, including
the `superType`/`subType` and label-`direction` cases), the Excel ragged-hierarchy reading logic
(`taxonomy_to_rdf.py`), and `rdf_serialize.py` as evidence that rdflib's own Turtle output must be
wrapped to get stable ordering — the spec §5.5 canonical serializer is a stricter version of the same
idea.

## Spec invariants — check code and spec edits against these

These are load-bearing. A design choice that violates one is wrong even if it passes tests, and a
deliberate change to one usually implies changes elsewhere in the spec.

- **Deterministic serialization is the point.** PR diffs are the governance interface (§1.2), so
  §5.5's fixed prefix block, sorted subjects/predicates, no-blank-nodes rule, no timestamps, and the
  CI byte-identity check (§6.1.7) all exist to serve it. Any output-format proposal must survive
  "would this diff cleanly?" — and a serialization change is a **major** version bump requiring a
  migration (§7).
- **IRIs are opaque and permanent.** No names, codes, or domains in IRIs; domain membership is data
  (`skos:inScheme`). Never deleted, never reused. The namespace lock (§3.4) exists because an edited
  base IRI would silently mint a parallel universe of IRIs.
- **The ID map, not the formula, is authoritative** (§5.4) — that is what lets codes, minting rules,
  and compiler versions change without breaking identity.
- **`generated/` is machine-owned**; `overlays/` is the only hand-written RDF. Enforced by the
  `.manifest.json` hash check, not convention.
- **Deprecation is evaluated against the union of all configured sources**, never one source or
  model — hence `--source X` runs skip deprecation outside their scope (§5.4).
- **Nothing customer-specific enters this repo** (§9.2 rule 5). Test fixtures are synthetic
  (`tests/fixtures/acme/`); no instance's content is ever used as one.
- **Extension happens without forking.** New sources are entry-point plugins (§5.2); org-specific
  terms go in the instance's own `x:` namespace and never redefine `sem:` (§3.6); local shapes are
  additive only (§6.1.5). If a change would force an adopter to fork, it's the wrong change.
- **No core term names a vendor.** `sem:sourceRef` carries `"<source-name>:<source-key>"` rather than
  a per-tool property — v0.1's `sem:ellieId` was removed for exactly this reason (§3.3).
- **All logic lives in the CLI**, never in workflow YAML (§6.3), so adopters on GitLab or Azure
  DevOps port a config file rather than reimplementing checks.

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

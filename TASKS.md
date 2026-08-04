# TASKS.md — implementation plan

Build order for Semprini. One task per working session; each is
independently implementable and verifiable, and later tasks assume earlier ones are
done and green.

**How to use this file**

- `docs/rdf-repo-and-compiler-spec.md` is authoritative. Tasks name the sections they
  implement and deliberately do not restate them. If a task and the spec disagree, the
  spec wins; if the spec turns out to be wrong, fix the spec in the same change.
- Work tasks in order unless a task says otherwise. Tick the box, and record anything
  the next session needs to know (deviations, discovered constraints) under the task.
- **Verify** is the definition of done. A task is finished when its verification is
  automated and passing in the plane's own test suite — not when the code exists.
- Some tasks are blocked by an open decision from spec §11; those are listed under
  *Decision gates* at the end.

---

## Phase A — Foundations

- [x] **A1 · Repository foundations and package skeleton**
  **Spec:** §4.1, §5.1 (CLI surface and exit codes), §8
  **Deliver:** a Poetry `pyproject.toml` for the `semprini` distribution (import name
  `semprini`, console script `semprini`, `poetry-core` build backend) plus a committed
  `poetry.lock`, the `src/semprini/` module skeleton of §4.1, `LICENSE` and
  `LICENSE-DOCS` (both © Datakor Consulting Oy), `CHANGELOG.md`, dev tooling (pytest,
  ruff, mypy), and a CI workflow running lint + tests for this repository. Implement
  `semprini version` and the exit-code contract; every other subcommand is a stub that
  exits non-zero.
  **Verify:** `poetry install` in a clean checkout, and `pip install .` into a bare venv —
  the wheel must install without Poetry, since instances use pip (§6.2); `semprini version`
  prints compiler and ontology versions; `semprini` with no arguments exits 2; lint, type
  check and the (empty) test suite pass in CI.
  **Done.** 15 tests green; ruff, ruff format and mypy (strict) clean; the wheel installs
  into a bare venv with pip and `semprini version` prints `compiler 0.1.0` / `ontology
  0.0.0`. §4.1 gained `.github/workflows/`, and `workflows/` is now labelled as holding the
  *instance* templates, since the distinction was ambiguous. Notes for later sessions:
  - `ontology/sem.ttl` is a **placeholder** carrying only `owl:versionInfo "0.0.0"`, so that
    the ontology version has one source before A3. Version `0.0.0` means "must not be used
    to mint IRIs". A3 replaces the document; `tests/test_ontology.py` already pins the
    single-`owl:Ontology` and fixed-IRI rules and should keep passing unchanged.
  - Exit codes: stubs return `1` (well-formed invocation, absent feature), leaving `2` for
    configuration and argument errors — argparse already exits `2` on its own. `ExitCode` in
    `cli.py` is the one definition; don't re-spell the numbers.
  - The `semprini.adapters` entry-point group is written but **commented out** in
    `pyproject.toml`: an entry point pointing at a module with no adapter class would break
    discovery. D1 uncomments it as the adapter classes land.
  - Every stub module names the task that fills it, and `cli.py` maps each unimplemented
    subcommand to its task (`init`→G1, `run`→E2, `check`→F2, `migrate`→G3, `adapters`→D1).
    Keep that map honest when task IDs move.
  - CI runs the matrix on 3.12 and 3.14 only; 3.12 is the supported floor and cannot be
    checked locally, since this machine has 3.14 alone.

- [ ] **A2 · Register the `sem:` namespace on w3id.org** *(external lead time — the w3id
  review queue is the one delay that cannot be compressed; submit as soon as the redirect
  target resolves)*
  **Spec:** §3.1, §11 #1
  **Deliver:** a PR to the w3id.org repository (`perma-id/w3id.org`) creating `/semprini/`
  — an `.htaccess` and a `README.md` — with content-negotiated redirects, **plus the
  hosting those redirects point at**.
  **Verify:** `curl -sIL -H 'Accept: text/turtle' https://w3id.org/semprini/ontology`
  resolves to the ontology document; an HTML `Accept` header resolves to documentation.
  **Depends:** A3 — **met.** The site now has a real `sem.ttl` (ontology 0.1.0) to serve;
  publishing the `0.0.0` placeholder under a permanent identifier was the thing worth
  waiting a session to avoid.
  **Redirect target — decided (§11 #1):** the product repo's own GitHub Pages site,
  `https://juhakor.github.io/semprini/`. No further domain then has to stay registered,
  which is the reason §3.1 gives for using w3id at all; if the repo later moves to an
  organization account only the `.htaccess` changes, and no `sem:` IRI does.
  **Routing, as drafted:** `/semprini/ontology` negotiates — an RDF `Accept` gets
  `ontology/sem.ttl`, anything else (browsers, `*/*`) gets `ontology/` documentation;
  `/semprini/ontology/X.Y.Z` does the same for a frozen release; `/semprini/ontology/sem.ttl`
  bypasses negotiation; any other path maps to the same path on the site, so later
  additions need no second trip through the w3id queue. Only Turtle is published, so every
  RDF media type resolves to the one document. Redirects are `302`, not `303`: `sem:`
  terms are hash IRIs, so the request genuinely is for the document.
  **Drafted, not committed:** both files exist in `background-material/w3id/semprini/`,
  rule-checked by simulation against twelve path/`Accept` combinations. That directory is
  **gitignored** — the files are not in this repo's history, and nothing but this entry
  records the decisions above. Move the directory into a `perma-id/w3id.org` fork as
  `semprini/`.
  **Remaining, in order:**
  1. A3, then publish the Pages site: `/`, `/ontology/` (HTML) and `/ontology/sem.ttl`.
     Copy the Turtle from `src/semprini/ontology/sem.ttl` during the site build rather
     than committing a second copy — a duplicated ontology drifts. Emit
     `/ontology/<owl:versionInfo>/sem.ttl` from that same source so the versioned redirect
     resolves from day one instead of 404ing until the first release. §6.3's
     "no logic in workflow YAML" governs the *instance* templates an adopter ports to
     GitLab; it does not constrain this repo's own site build.
  2. Check what `Content-Type` GitHub Pages returns for `.ttl`. If it is not `text/turtle`,
     that is a hosting fix (or a different host) — the w3id file does not change, since
     `AddType` there only affects files w3id itself serves, and we redirect away.
  3. Open the w3id PR: one squashed commit whose message names the project, live target
     URLs in the body. w3id requires contact details and a GitHub username in **both**
     files, and asks that the rules be tested locally first.
  4. On merge, run the two `curl` checks above, then tick the box.

- [x] **A3 · Metamodel ontology (`sem.ttl`)**
  **Spec:** §3.1, §3.2, §3.3, §7 (ontology versioning)
  **Deliver:** `src/semprini/ontology/sem.ttl` declaring exactly the classes of §3.2 and
  properties of §3.3, with `owl:versionInfo` and term-level `rdfs:comment`s.
  **Verify:** the file parses; a test asserts the emitted term inventory equals the
  §3.2/§3.3 tables exactly — no missing terms and, importantly, **no extra ones**, so
  the vocabulary cannot drift from the spec silently. `semprini version` reports the
  ontology version read from this file.
  **Depends:** A1
  **Done.** 28 tests green; ruff, ruff format and mypy (strict) clean; `semprini version`
  prints `compiler 0.1.0` / `ontology 0.1.0`. Both inventory guards were mutation-checked
  — an added term and an altered `rdfs:domain` each fail the suite — since a test of this
  shape passes just as happily when it is asserting nothing. Decisions, for later sessions:
  - **RDFS typing, not OWL.** Terms are `rdfs:Class` / `rdf:Property` with
    `rdfs:domain`/`rdfs:range`; OWL appears only on the document node, which carries
    `owl:versionInfo` (§7). The metamodel is SKOS-based, F1's SHACL states the constraints
    once, and OWL typing on terms subclassing `skos:Concept` would license entailments
    nothing validates. `test_owl_is_confined_to_the_document_header` pins this.
  - The §3.2 rows for `skos:ConceptScheme` and plain `skos:Concept` are **not** declared
    here — they are reused SKOS terms, and redeclaring them is exactly what §3.6 forbids
    an instance from doing to `sem:`. The inventory is therefore 4 classes and 10
    properties, and `test_the_document_describes_only_its_own_terms` keeps foreign
    vocabulary out.
  - `sem:isAbout` and `sem:represents` are declared but **reserved**, mirroring §3.1's
    "declare now, use later" for `a:`/`d:`. They carry no domain, range, or
    `rdfs:subPropertyOf`: §3.3 calls `sem:represents` a subproperty of `sem:isAbout`, but
    asserting that before either is defined would fix semantics the spec hasn't settled.
    The task that defines them owns that triple.
  - The expected inventory is a **literal** in `tests/test_ontology.py`, not parsed from
    the spec's tables, so the spec and the ontology can still drift if a table is edited
    alone. The test is the place that comparison happens: edit table, ontology and literal
    in one change.
  - `sem.ttl` is hand-written and commented, and is **not** canonical-serializer output —
    §5.5's comment-free rule governs an instance's `generated/`, whereas the term comments
    here are the vocabulary's published documentation. B1 must not be pointed at this file.
  - The document carries `dcterms:license` (CC BY 4.0) and `dcterms:rightsHolder`, since
    it is served standalone at w3id and travels without the repo's `LICENSE-DOCS`.
  - Ontology version is now **0.1.0**; `0.0.0` ("must not be used to mint IRIs") is gone
    and `test_the_placeholder_version_is_gone` stops it returning. A2 step 1 is unblocked:
    `src/semprini/ontology/sem.ttl` is the real document the Pages site should copy, and
    `/ontology/0.1.0/sem.ttl` is the versioned path to emit from it.

---

## Phase B — Deterministic core

- [ ] **B1 · Canonical Turtle serializer**
  **Spec:** §5.5 (all eight rules)
  **Deliver:** `src/semprini/serialize.py`. This is the linchpin of the whole design — every
  later guarantee (reviewable diffs, safe upgrades, the CI determinism check) reduces to
  this module being correct.
  **Verify:** one test per rule 1–8, plus: building the same graph from randomly shuffled
  triple orders produces byte-identical output across many permutations; parse→serialize
  round-trips are graph-equal; a graph containing a blank node raises rather than
  emitting one; output ends with exactly one LF.
  **Depends:** A1

- [ ] **B2 · Internal model and run context**
  **Spec:** §5.1 (pipeline stages), §5.2 (`InternalModel`, `source_refs`, `RunContext`)
  **Deliver:** `src/semprini/model.py` — the dataclasses adapters return and the core
  consumes. Frozen/immutable where practical, since adapters must not mutate shared
  state.
  **Verify:** type checks clean under mypy; construction and merge-by-`source_refs`
  unit tests; a model carrying two source refs for one object merges to one identity.
  **Depends:** A1

- [ ] **B3 · Configuration loading**
  **Spec:** §5.1 (`config/semprini.yaml`), exit code 2
  **Deliver:** parsing and validation of instance configuration, including resolving
  `token_env` without ever reading a credential into the config object.
  **Verify:** valid fixture config loads; each malformed case (missing base IRI,
  duplicate source `name`, unknown adapter, credential written inline) exits 2 with a
  message naming the offending key.
  **Depends:** A1

- [ ] **B4 · Identity: ID map, minting, namespace lock**
  **Spec:** §3.4, §5.4
  **Deliver:** `src/semprini/identity.py` — ID-map read/append, minting per §3.4.2, UUIDv5
  namespace constant, collision detection, namespace lock write/verify.
  **Verify:** lookup hit reuses an IRI; miss mints and appends exactly one row; two
  source keys colliding on one IRI raises; a removed row is detected against a base
  revision; base-IRI mismatch against the lock exits 2; `--force-namespace-change`
  rewrites map and lock together. Property test: minting is stable across processes
  (no reliance on hash seed or dict order).
  **Depends:** B2, B3

---

## Phase C — Emit

- [ ] **C1 · Graph builder and file partitioning**
  **Spec:** §3.2, §3.3, §4.2 (`generated/` file naming), §3.3 (`dcterms:modified`
  carry-forward)
  **Deliver:** internal model → one rdflib graph per output file, including the
  `sem:relatesTo` shortcut and `sem:sourceRef` composition.
  **Verify:** golden TTL from a hand-built internal model; recompiling unchanged input
  produces a byte-identical file **and** leaves `dcterms:modified` untouched — the test
  that proves scheduled no-op runs generate no diff.
  **Depends:** B1, B2, B4

- [ ] **C2 · Manifest and run report**
  **Spec:** §4.3, §5.6, §7 (version stamping)
  **Deliver:** `generated/.manifest.json` (content hashes, compiler and ontology
  versions, no timestamps) and `generated/.report.md`.
  **Verify:** manifest is byte-identical across two runs of identical input; recomputed
  hashes match; a hand-edited generated file is detected; the report renders the counts
  and warning categories §5.6 lists.
  **Depends:** C1

---

## Phase D — Adapters

- [ ] **D1 · Adapter interface and plugin discovery**
  **Spec:** §5.2, §5.1 (`semprini adapters`)
  **Deliver:** `BaseAdapter`, entry-point discovery for group
  `semprini.adapters`, and the `semprini adapters` command.
  **Deliver also:** a shared adapter contract test suite third-party authors can run
  against their own adapter — the plugin promise of §1.2 is empty without one.
  **Verify:** a dummy adapter installed from a separate test distribution is discovered
  and listed; the contract suite catches an adapter that writes to disk, mints IRIs, or
  returns a partial model instead of raising; fetch failure exits 3.
  **Depends:** B2

- [ ] **D2 · Excel taxonomy adapter, and the fixture instance**
  **Spec:** §5.3 (Excel adapter), §6.1 (fixture instance), §9.2 rule 5
  **Deliver:** `src/semprini/adapters/excel_taxonomy.py`, plus `tests/fixtures/acme/` — a
  complete synthetic instance (config, workbook, ID map, golden TTL). Chosen before the
  Ellie adapter because it needs no network mocking, so it is the cheapest path to a
  working end-to-end pipeline. The fixture is **synthetic**; no real instance content
  ever enters this repository.
  **Verify:** golden TTL matches for the fixture workbook; each of the three §5.3 error
  conditions (dangling `parent_code`, hierarchy cycle, duplicate code) fails the compile
  with a message identifying the row.
  **Depends:** C2, D1

- [ ] **D3 · Ellie adapter**
  **Spec:** §5.3 (Ellie adapter)
  **Deliver:** `src/semprini/adapters/ellie.py` against the Ellie REST API, with recorded
  responses for tests. Reuse the field semantics documented in
  `background-material/kg-converter-old/README.md` §1.1 — that project read the same
  data and its field tables are trustworthy, though nothing about its RDF mapping is.
  **Verify:** against mocked responses — an allowlisted model that is missing or
  inaccessible fails the run; an entity in two models yields one node with two
  `skos:inScheme` triples; two UUIDs sharing a name yield two nodes plus a report
  warning; an empty description emits no `skos:definition`.
  **Depends:** D1
  **Gated by:** §11 #7 (API pagination and rate-limit specifics)

---

## Phase E — Compile end to end

- [ ] **E1 · Lifecycle, deprecation and the merge register**
  **Spec:** §3.5, §5.4 (deprecation detection), `merges.csv`
  **Deliver:** diffing against previous generated state; deprecation evaluated against
  the union of all configured sources; carry-forward of last-known statements;
  `merges.csv` handling.
  **Verify:** scenario tests — an object removed from one model but present in another
  loses only that `skos:inScheme`; an object absent from every source is deprecated with
  statements preserved; a deprecated node stays deprecated on later runs; a `--source X`
  run deprecates nothing outside X; a `merges.csv` row produces `dcterms:isReplacedBy`
  and is rejected when either IRI is unknown to the ID map.
  **Depends:** C2, D2

- [ ] **E2 · `semprini run` orchestration**
  **Spec:** §5.1 (pipeline and flags)
  **Deliver:** the full fetch → normalize → resolve → build → lifecycle → serialize →
  write sequence, with `--source` and `--dry-run`.
  **Verify:** on the fixture instance, two consecutive runs produce zero diff;
  `--dry-run` writes nothing (assert via filesystem snapshot); a mid-pipeline failure
  leaves `generated/` untouched rather than half-written.
  **Depends:** E1

---

## Phase F — Validation

- [ ] **F1 · Core SHACL shapes**
  **Spec:** §6.1.5
  **Deliver:** `src/semprini/shapes/` covering every constraint listed, with the
  missing-definition rule as a warning.
  **Verify:** each constraint has a conforming and a violating fixture; the fixture
  instance conforms; warnings do not fail the run.
  **Depends:** D2

- [ ] **F2 · `semprini check` pipeline**
  **Spec:** §6.1 items 1–7
  **Deliver:** the full check sequence, including the version-drift check (§7) and the
  determinism re-serialization check.
  **Verify:** the fixture instance passes; a purpose-built failing fixture exists for
  **each** of the seven checks, each producing the documented exit code; drift is
  detected when the manifest's recorded version differs from the running one.
  **Depends:** E2, F1

- [ ] **F3 · Additive-only enforcement for local shapes**
  **Spec:** §3.6, §6.1.5 (final bullet)
  **Deliver:** rejection of a `shapes/local/` shape that weakens a core constraint or
  redefines a `sem:` term. Split out because it is the hardest check to get right —
  "additive only" needs a precise, testable definition before it needs an
  implementation, and getting it wrong either blocks legitimate local rules or silently
  permits core weakening.
  **Verify:** a local shape adding a constraint passes; one relaxing a core cardinality,
  retargeting a `sem:` class, or redeclaring a `sem:` property is rejected with an
  explanatory message.
  **Depends:** F2

---

## Phase G — Distribution and operations

- [ ] **G1 · Instance scaffold and `semprini init`**
  **Spec:** §4.2, §5.7
  **Deliver:** `templates/instance/` and the `init` command, all six steps.
  **Verify:** init into a temp directory then `semprini check` passes on the fresh, empty
  instance; re-running init where `namespace.lock` exists refuses; a socket guard
  asserts init makes **no** network calls; the generated tree matches §4.2 exactly.
  **Depends:** F2

- [ ] **G2 · Workflow templates and CI portability**
  **Spec:** §6.2, §6.3
  **Deliver:** `workflows/` templates for `compile.yml` and `validate.yml`, materialized
  by `init`.
  **Verify:** a test asserts each workflow contains no logic beyond installing the
  pinned version, invoking `semprini`, and (for compile) opening a PR — the mechanical guard
  on §6.3. Run both against the fixture instance in a container and confirm a compile
  PR body carries the run report.
  **Depends:** G1

- [ ] **G3 · Versioning, drift and migrations**
  **Spec:** §7
  **Deliver:** `src/semprini/migrate/`, the migration registry, and `semprini migrate --to`.
  **Verify:** a synthetic output-affecting change ships a migration that takes the
  fixture instance from vN to vN+1 deterministically; migrations never mint new IRIs for
  existing objects and never drop ID-map rows (asserted, not assumed); post-migration
  `semprini check` passes including drift.
  **Depends:** F2

- [ ] **G4 · Project documentation**
  **Spec:** §8, §9.2, §5.2
  **Deliver:** `README.md` stating the two-licence split prominently, `CONTRIBUTING.md`
  covering §9.2 including the four non-negotiables, and an adapter authoring guide
  pointing at the D1 contract test suite.
  **Verify:** a fresh reader can install the package, bootstrap an instance and compile
  the fixture using only the README — walk it through literally, on a clean machine.
  **Depends:** G1

- [ ] **G5 · Release and distribution**
  **Spec:** §7 (support policy), §11 #3
  **Deliver:** tagged release process, CHANGELOG discipline, publication of the package
  and of the ontology at its w3id target.
  **Verify:** install the tagged version in a clean venv from the chosen channel;
  `semprini version` matches the tag; `semprini init` from that install produces an instance whose
  workflows pin that same version.
  **Depends:** A2, G3, G4

---

## Phase H — Pilot

- [ ] **H1 · First instance bootstrap**
  **Spec:** §5.7, §6.2, §9.1
  **Deliver:** a real instance repository for the pilot organization: base IRI decided,
  Ellie allowlist populated one validated model at a time, stewards and CODEOWNERS
  assigned, branch protection on.
  **Verify:** the scheduled compile opens a PR whose report a steward can review
  unaided; a deliberate source change appears as a readable diff on the next run; main
  is tagged per §9.1 rule 7.
  **Depends:** D3, G5

---

## Decision gates

Open decisions from spec §11 and the task each one blocks. Anything not listed here can
be deferred without stalling the build.

| §11 | Decision | Blocks |
|---|---|---|
| 1 | w3id namespace registration — redirect target decided, PR not yet submitted | A2 → G5 (first release); no instance may mint IRIs before it |
| 2 | Confirm Apache-2.0 / CC BY 4.0 | A1 (the licence files are written there) |
| 3 | Distribution channel | G5 |
| 4 | Which adapters ship bundled | D3, G4 |
| 5 | Default language tag(s) | B3 |
| 6 | When missing-definition becomes blocking | per instance; H1 |
| 7 | Ellie pagination and rate limits | D3 |
| 8 | Whether `init` creates the remote repository | G1 |

## Sequencing notes

- **A2 runs in parallel, but is no longer parallel from day one.** Its files are drafted
  and its redirect target is decided; what remains needs A3 and a published Pages site
  before the PR can honestly be submitted. After that it depends on a third party's review
  queue — the only prerequisite for a first release that cannot be compressed by working
  harder. Treat "A3, then hosting, then submit" as the critical path.
- **B1 before everything downstream.** Determinism cannot be retrofitted: once an
  instance holds generated files, every serializer change becomes a migration (§7).
- **F3, G3 and D3 are the three tasks most likely to overrun.** Each has a genuinely
  hard core — defining "additive only", proving migrations preserve identity, and
  an external API's real behaviour versus its documentation.

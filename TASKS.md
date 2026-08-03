# TASKS.md — implementation plan

Build order for the RDF Knowledge Plane. One task per working session; each is
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

- [ ] **A1 · Repository foundations and package skeleton**
  **Spec:** §4.1, §5.1 (CLI surface and exit codes), §8
  **Deliver:** `pyproject.toml` for the `rdf-knowledge-plane` distribution (import name
  `rkp`, console script `rkp`), the `src/rkp/` module skeleton of §4.1, `LICENSE` and
  `LICENSE-DOCS`, `CHANGELOG.md`, dev tooling (pytest, ruff, mypy), and a CI workflow
  running lint + tests for this repository. Implement `rkp version` and the exit-code
  contract; every other subcommand is a stub that exits non-zero.
  **Verify:** `pip install -e .` in a clean venv; `rkp version` prints compiler and
  ontology versions; `rkp` with no arguments exits 2; lint, type check and the (empty)
  test suite pass in CI.

- [ ] **A2 · Register the `sem:` namespace on w3id.org** *(external lead time — start
  now, runs in parallel, blocks only A3's final URL and any real IRI minting)*
  **Spec:** §3.1, §11 #1
  **Deliver:** a PR to the w3id.org repository creating
  `/rdf-knowledge-plane/` with content-negotiated redirects to wherever the ontology
  will be served, plus the hosting itself.
  **Verify:** `curl -sIL -H 'Accept: text/turtle' https://w3id.org/rdf-knowledge-plane/ontology`
  resolves to the ontology document; an HTML `Accept` header resolves to documentation.

- [ ] **A3 · Metamodel ontology (`sem.ttl`)**
  **Spec:** §3.1, §3.2, §3.3, §7 (ontology versioning)
  **Deliver:** `src/rkp/ontology/sem.ttl` declaring exactly the classes of §3.2 and
  properties of §3.3, with `owl:versionInfo` and term-level `rdfs:comment`s.
  **Verify:** the file parses; a test asserts the emitted term inventory equals the
  §3.2/§3.3 tables exactly — no missing terms and, importantly, **no extra ones**, so
  the vocabulary cannot drift from the spec silently. `rkp version` reports the
  ontology version read from this file.
  **Depends:** A1

---

## Phase B — Deterministic core

- [ ] **B1 · Canonical Turtle serializer**
  **Spec:** §5.5 (all eight rules)
  **Deliver:** `src/rkp/serialize.py`. This is the linchpin of the whole design — every
  later guarantee (reviewable diffs, safe upgrades, the CI determinism check) reduces to
  this module being correct.
  **Verify:** one test per rule 1–8, plus: building the same graph from randomly shuffled
  triple orders produces byte-identical output across many permutations; parse→serialize
  round-trips are graph-equal; a graph containing a blank node raises rather than
  emitting one; output ends with exactly one LF.
  **Depends:** A1

- [ ] **B2 · Internal model and run context**
  **Spec:** §5.1 (pipeline stages), §5.2 (`InternalModel`, `source_refs`, `RunContext`)
  **Deliver:** `src/rkp/model.py` — the dataclasses adapters return and the core
  consumes. Frozen/immutable where practical, since adapters must not mutate shared
  state.
  **Verify:** type checks clean under mypy; construction and merge-by-`source_refs`
  unit tests; a model carrying two source refs for one object merges to one identity.
  **Depends:** A1

- [ ] **B3 · Configuration loading**
  **Spec:** §5.1 (`config/plane.yaml`), exit code 2
  **Deliver:** parsing and validation of instance configuration, including resolving
  `token_env` without ever reading a credential into the config object.
  **Verify:** valid fixture config loads; each malformed case (missing base IRI,
  duplicate source `name`, unknown adapter, credential written inline) exits 2 with a
  message naming the offending key.
  **Depends:** A1

- [ ] **B4 · Identity: ID map, minting, namespace lock**
  **Spec:** §3.4, §5.4
  **Deliver:** `src/rkp/identity.py` — ID-map read/append, minting per §3.4.2, UUIDv5
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
  **Spec:** §5.2, §5.1 (`rkp adapters`)
  **Deliver:** `BaseAdapter`, entry-point discovery for group
  `rdf_knowledge_plane.adapters`, and the `rkp adapters` command.
  **Deliver also:** a shared adapter contract test suite third-party authors can run
  against their own adapter — the plugin promise of §1.2 is empty without one.
  **Verify:** a dummy adapter installed from a separate test distribution is discovered
  and listed; the contract suite catches an adapter that writes to disk, mints IRIs, or
  returns a partial model instead of raising; fetch failure exits 3.
  **Depends:** B2

- [ ] **D2 · Excel taxonomy adapter, and the fixture instance**
  **Spec:** §5.3 (Excel adapter), §6.1 (fixture instance), §9.2 rule 5
  **Deliver:** `src/rkp/adapters/excel_taxonomy.py`, plus `tests/fixtures/acme/` — a
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
  **Deliver:** `src/rkp/adapters/ellie.py` against the Ellie REST API, with recorded
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

- [ ] **E2 · `rkp run` orchestration**
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
  **Deliver:** `src/rkp/shapes/` covering every constraint listed, with the
  missing-definition rule as a warning.
  **Verify:** each constraint has a conforming and a violating fixture; the fixture
  instance conforms; warnings do not fail the run.
  **Depends:** D2

- [ ] **F2 · `rkp check` pipeline**
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

- [ ] **G1 · Instance scaffold and `rkp init`**
  **Spec:** §4.2, §5.7
  **Deliver:** `templates/instance/` and the `init` command, all six steps.
  **Verify:** init into a temp directory then `rkp check` passes on the fresh, empty
  instance; re-running init where `namespace.lock` exists refuses; a socket guard
  asserts init makes **no** network calls; the generated tree matches §4.2 exactly.
  **Depends:** F2

- [ ] **G2 · Workflow templates and CI portability**
  **Spec:** §6.2, §6.3
  **Deliver:** `workflows/` templates for `compile.yml` and `validate.yml`, materialized
  by `init`.
  **Verify:** a test asserts each workflow contains no logic beyond installing the
  pinned version, invoking `rkp`, and (for compile) opening a PR — the mechanical guard
  on §6.3. Run both against the fixture instance in a container and confirm a compile
  PR body carries the run report.
  **Depends:** G1

- [ ] **G3 · Versioning, drift and migrations**
  **Spec:** §7
  **Deliver:** `src/rkp/migrate/`, the migration registry, and `rkp migrate --to`.
  **Verify:** a synthetic output-affecting change ships a migration that takes the
  fixture instance from vN to vN+1 deterministically; migrations never mint new IRIs for
  existing objects and never drop ID-map rows (asserted, not assumed); post-migration
  `rkp check` passes including drift.
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
  `rkp version` matches the tag; `rkp init` from that install produces an instance whose
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
| 1 | w3id namespace registration | A2 → G5 (first release); no instance may mint IRIs before it |
| 2 | Confirm Apache-2.0 / CC BY 4.0 | A1 (the licence files are written there) |
| 3 | Distribution channel | G5 |
| 4 | Which adapters ship bundled | D3, G4 |
| 5 | Default language tag(s) | B3 |
| 6 | When missing-definition becomes blocking | per instance; H1 |
| 7 | Ellie pagination and rate limits | D3 |
| 8 | Whether `init` creates the remote repository | G1 |

## Sequencing notes

- **A2 runs in parallel from day one.** It depends on a third party's review queue, and
  it is the only prerequisite for a first release that cannot be compressed by working
  harder.
- **B1 before everything downstream.** Determinism cannot be retrofitted: once an
  instance holds generated files, every serializer change becomes a migration (§7).
- **F3, G3 and D3 are the three tasks most likely to overrun.** Each has a genuinely
  hard core — defining "additive only", proving migrations preserve identity, and
  an external API's real behaviour versus its documentation.

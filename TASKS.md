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

- [x] **A2 · Register the `sem:` namespace on w3id.org** *(merged — 
  [perma-id/w3id.org#6488](https://github.com/perma-id/w3id.org/pull/6488). The namespace
  is live and §11 #1 is resolved.)*
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
  **Where the files live:** both exist in `background-material/w3id/semprini/` and are now
  also in the submitted PR. That directory is **gitignored** — the files are not in this
  repo's history, and nothing but this entry records the decisions above.
  **Remaining, in order:**
  1. ~~Publish the Pages site.~~ **Done.** `tools/build_site.py` generates it from
     `src/semprini/ontology/sem.ttl` and `.github/workflows/pages.yml` deploys it as an
     artifact — the Pages source is **GitHub Actions**, not a branch, which is what keeps
     a generated copy of the ontology out of the repository. All five paths the
     `.htaccess` targets return 200 and the served Turtle is byte-identical to the
     packaged document. Note the versioned **directory** needs its own `index.html`: the
     negotiation rule sends browsers to `/ontology/X.Y.Z/`, not to the `.ttl`, so that
     path 404s without one. This list previously named only the versioned `.ttl`.
  2. ~~Check the `Content-Type` for `.ttl`.~~ **Done.** GitHub Pages returns
     `text/turtle; charset=utf-8`, so no hosting change is needed and the `.htaccess`
     is unaffected.
  3. ~~Open the w3id PR.~~ **Done, 2026-08-04:**
     [perma-id/w3id.org#6488](https://github.com/perma-id/w3id.org/pull/6488). Before
     submission the rules were simulated against the live site over 45 path/`Accept`
     combinations: every rule targets a URL that returns 200, apart from two that are
     deliberately absent (an unreleased version, and the `shapes/` path the catch-all
     reserves for later). The README gained a row for `/ontology/X.Y.Z/sem.ttl`, which the
     `.htaccess` implemented but the documentation did not mention.
  4. ~~Review feedback: "the docs in this are verbose — have you considered using a link to
     your site instead?"~~ **Answered 2026-08-05 by trimming both files**, since the site
     now exists and duplicating it in a repository maintained by other people is a cost
     they carry. The README dropped the project pitch, the versioning essay, the
     negotiation explanation and the `curl` examples, keeping only what w3id's own README
     asks of an entry — what the ID is, where it resolves, who maintains it — and pointing
     at `https://juhakor.github.io/semprini/` for the rest; the `.htaccess` comment header
     shrank to the ID line plus the required contact block. **No `RewriteRule` or
     `RewriteCond` changed**, so the 45-combination simulation from step 3 still holds and
     needs no re-run. Both trimmed files are in `background-material/w3id/semprini/`.
  5. ~~On merge, run the two `curl` checks above, then tick the box.~~ **Done — merged and
     verified live.** All eight paths were checked, not just the two: an RDF `Accept` on
     `/semprini/ontology` gets a `302` to `ontology/sem.ttl` and `200 text/turtle`; an HTML
     `Accept` and a bare `*/*` both get `ontology/` and `200 text/html`;
     `/ontology/sem.ttl`, `/ontology/0.1.0`, `/ontology/0.1.0/` and `/ontology/0.1.0/sem.ttl`
     all resolve `200`; an unreleased version `404`s, as intended. The served Turtle is
     **byte-identical** to `src/semprini/ontology/sem.ttl` at both the negotiated and the
     versioned path. Note for anyone re-checking: `curl -I` follows to a `text/html`
     `Content-Type` on the *redirect* hop, so read the final hop's header, not the first.
  **Known gap — frozen versions do not survive a version bump, and the promise is now
  public.** The site build emits a frozen directory for the *current* ontology version
  only, so publishing 0.2.0 would delete `/ontology/0.1.0/` — a path w3id now promises
  resolves for ever, and which this task just verified does. Nothing is broken today
  (0.1.0 is the only version and nothing is released), but the first bump breaks a
  permanent identifier silently, and it now breaks it in public. **G5 owns the fix**, and
  it is a precondition of shipping a second ontology version, not a nice-to-have: released
  versions have to be published from something that outlives the working tree — a tag, or
  per-release copies the build collects — rather than from `sem.ttl` alone.

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

- [x] **B1 · Canonical Turtle serializer**
  **Spec:** §5.5 (all eight rules)
  **Deliver:** `src/semprini/serialize.py`. This is the linchpin of the whole design — every
  later guarantee (reviewable diffs, safe upgrades, the CI determinism check) reduces to
  this module being correct.
  **Verify:** one test per rule 1–8, plus: building the same graph from randomly shuffled
  triple orders produces byte-identical output across many permutations; parse→serialize
  round-trips are graph-equal; a graph containing a blank node raises rather than
  emitting one; output ends with exactly one LF.
  **Depends:** A1
  **Done.** 75 tests green; ruff, ruff format and mypy (strict) clean. Two cases found in
  review and fixed: a character Turtle forbids inside `<...>` (a space, an angle bracket
  — `rdflib` does not validate a `URIRef` when it is built) was written raw and produced
  a file that would not parse, and is now `\uXXXX`-escaped; and a graph holding both
  `"x"` and `"x"^^xsd:string` — separate entries in `rdflib`, one term in RDF 1.1 —
  emitted the statement twice, so the file re-parsed to fewer triples than it was built
  from and recompiling after that round trip showed a diff nobody caused. Objects are now
  normalized and deduplicated per subject, and the same unsafe characters are **refused**
  in the base IRI rather than escaped — the prefix block is the one place an IRI is
  written raw, and a namespace that had to be escaped would no longer be the namespace
  the instance minted in. Six mutations were checked against the suite — reversed subject
  order, four-space indentation, blank nodes tolerated, unsafe IRIs written raw,
  `xsd:string` neither collapsed nor deduplicated, an unsafe base IRI accepted — and each
  fails it, since a determinism test looks identical whether or not it is asserting
  anything. That check earned its keep: after the review's fix the `xsd:string` rule had
  two homes, `_plain()` and `_literal()`, and the suite passed with the second one broken.
  The dead branch is gone, and normalization now happens in exactly one place. Decisions,
  for later sessions:
  - **API:** `serialize(graph, base_iri) -> str` and `write(path, graph, base_iri)`.
    C1/C2 must write through `write()`, never `Path.write_text` directly: it passes
    `newline="\n"`, and the platform default would translate every line ending on Windows
    and make the same graph produce different bytes on different machines (rule 5).
  - **`namespaces(base_iri)` lives here** and is the only place the per-kind suffixes
    (`concepts/`, `relationships/`, `schemes/`, `values/`, `ext#`, `assets/`, `docs/`) are
    written down. B4 mints into those namespaces and must import it rather than re-spell
    them. §4.1 lists no separate namespaces module, so it stays in `serialize.py`.
  - **Prefix block order is `sem, c, r, sch, v, x, skos, dcterms, xsd, a, d`** — the order
    §3.1 introduces them. The reserved `a:`/`d:` are emitted too, per rule 1's "even if
    unused"; declaring `a:` does not clash with the `a` keyword, and the round-trip test
    parses the output back to prove it.
  - **Four byte-affecting choices §5.5 did not settle are now in the spec**, since each
    would otherwise be re-decided differently by whoever touched this next: objects sort
    IRIs before literals then by lexical form/tag/datatype (rule 3); a predicate with
    several objects repeats the predicate instead of using `,`, and blocks are separated
    by a blank line (rule 4); terms are prefixed only where the local name needs no
    escaping; and an `xsd:string` literal is written in the plain form, because the two
    are the same RDF term and writing them differently would let two equal graphs produce
    two different files. **§3.7's example was reindented from four spaces to two** to
    match rule 4 — it disagreed with the rule it illustrates, which would have reached
    C1 as a wrong golden file.
  - The safe-local-name rule is **deliberately narrower than Turtle's `PN_LOCAL`**:
    minted names are UUIDs and slugs, and anything unusual falls back to `<full IRI>`
    rather than risking an escaping rule this module gets subtly wrong.
  - Blank nodes and literal subjects are rejected **before any bytes are written**, so a
    refused graph leaves no half-written file (asserted, since `write()` is what C1 calls).
  - **Rule 6 is only half here.** The serializer preserves language tags; *requiring* them
    on `skos:prefLabel`/`skos:definition`, and applying the instance's configured default,
    belongs to C1 with the config from B3.
  - Rule 8 is tested as "the output contains nothing the graph does not": statement lines
    equal triple count, and the only date in the sample output is the `dcterms:modified`
    the graph itself carries.
  - `src/semprini/ontology/sem.ttl` is still **not** serializer output (see A3) and was
    not touched. Nothing may point `write()` at it.

- [x] **B2 · Internal model and run context**
  **Spec:** §5.1 (pipeline stages), §5.2 (`InternalModel`, `source_refs`, `RunContext`)
  **Deliver:** `src/semprini/model.py` — the dataclasses adapters return and the core
  consumes. Frozen/immutable where practical, since adapters must not mutate shared
  state.
  **Verify:** type checks clean under mypy; construction and merge-by-`source_refs`
  unit tests; a model carrying two source refs for one object merges to one identity.
  **Depends:** A1
  **Done.** 116 tests green; ruff, ruff format and mypy (strict) clean. Nine mutations
  checked against the suite — conflicts resolved by taking one side, union fields not
  unioned, merged objects left in arrival order, cross-kind refs tolerated, `source_refs`
  left as the caller's dict, identity not followed transitively, an empty definition kept
  as a rival answer, `source_refs` hashed (leaving objects unhashable), a model keeping
  the caller's sequence — and each fails it. The order-independence test had to be
  repaired first: its fixture was symmetric, so reversing it produced the same grouping
  order and the sort was never exercised. Review then found two defects worth recording,
  both fixed: a frozen object could not be **hashed** (the `MappingProxyType` in
  `source_refs` made it unhashable, so identity resolution could not put one in a set —
  `source_refs` is now `field(hash=False)`, compared but not hashed), and an **empty
  definition** merged as a disagreement rather than as silence. Decisions, for later
  sessions:
  - **The classes are `Entity`, `Attribute`, `Relationship`, `Scheme`, `TaxonomyValue`.**
    §5.1's pipeline said `Concept` where §3.2 says `sem:Entity`; `Concept` is actively
    misleading, since the plain `skos:Concept` in this metamodel is the *taxonomy value*.
    §5.1 now says `Entity`. `sem:BusinessTerm` has **no dataclass** — §3.2 marks it
    adapter-supplied and later, and the class arrives with the adapter that produces it
    (§10, Collibra).
  - **Merging refuses to guess.** Set-valued fields union; two sources disagreeing about
    a scalar raise `MergeConflictError` rather than one winning. Nothing in v1 produces
    cross-source objects, so this costs nothing today, and loosening the rule later is
    easier than tightening it once instances hold files built under it. D3/E1 own the
    question of whether a steward-facing resolution mechanism is needed. **An empty
    definition is normalized to `None` at construction**, so `""` and absent are one
    state rather than two the merge rule has to know are equivalent — an empty
    description emits no triple either way (§5.3), and a tool that returns `""` for a
    blank field must not fail every run against one that fills it in. Fixing this in the
    constructor rather than in the merge is deliberate: the algorithm then needs one rule
    (`is None`), and objects are canonical from birth.
  - **A source ref may not name objects of two kinds.** The ID map is keyed by
    `(source_name, source_key)` alone — `kind` is a recorded column, not part of the key
    (§5.4) — so an entity and a scheme sharing a key would collide on one row and one
    IRI. Enforced in `merge_models`; **B4 depends on this** and need not re-check it.
  - **`Kind.prefix` is where kinds map to namespaces** (`c:`/`r:`/`sch:`/`v:`), so B4
    mints from the model's own vocabulary rather than a second copy of §3.1's table.
    Entities, attributes and terms deliberately share `c:`.
  - **`RunContext` deliberately does not carry the ID map**, and a test asserts it: an
    adapter that could mint would break "the ID map is authoritative" (§5.2, §5.4). It
    validates `base_iri` through `serialize.namespaces()` and the language tag's shape at
    construction, so a bad instance config fails at the start of a run rather than when
    the first file is written. *Which* tags an instance may configure is still §11 #5,
    open, and B3 owns it.
  - Labels and definitions are **untagged strings** in the model; the configured language
    is applied when the graph is built (C1), since an adapter does not know it.
  - `Issue`/`Severity` land here because §5.2 names `validate_config() -> list[Issue]`.
    D1 and F2 are their first users; nothing consumes them yet.
  - The merge rules are driven by `dataclasses.fields` plus a `UNION_FIELDS` class
    variable rather than written out per class. Five kinds each gaining fields over time
    would be five places to forget one, and forgetting one loses data silently. A new
    set-valued field must be added to `UNION_FIELDS`, or it will be treated as a scalar
    that has to agree.

- [x] **B3 · Configuration loading**
  **Spec:** §5.1 (`config/semprini.yaml`), exit code 2
  **Deliver:** parsing and validation of instance configuration, including resolving
  `token_env` without ever reading a credential into the config object.
  **Verify:** valid fixture config loads; each malformed case (missing base IRI,
  duplicate source `name`, unknown adapter, credential written inline) exits 2 with a
  message naming the offending key.
  **Depends:** A1
  **Done.** 171 tests green; ruff, ruff format and mypy (strict) clean; the wheel still
  installs into a bare venv with pip and `semprini version` works there. Eighteen
  mutations were checked against the suite — the `token_env` exemption removed, a pasted
  token in `token_env` tolerated, no recursion into nested mappings or into lists,
  duplicate YAML keys tolerated, unknown keys tolerated, duplicate source names
  tolerated, `--source` unvalidated, settings not frozen, only the first issue reported,
  an unset credential tolerated, any language tag accepted, the CLI not validating
  configuration at all, plus the six below — and each fails it. **Review found six
  defects, all fixed**, and each one now has both a test and a mutation:
  - Three ways to get a **traceback instead of exit 2**, which is the whole contract this
    task exists to keep. A YAML key that cannot be hashed (`? [a, b]`) hit the
    duplicate-key scan's `in` test and raised `TypeError`, which is not a `YAMLError` and
    so escaped every handler; the scan now defers to `SafeConstructor`'s own message. A
    file saved in the system codepage raised `UnicodeDecodeError`, which subclasses
    `ValueError` and slipped past the `OSError` handler — an ordinary Windows editor
    mistake, now a named error. And YAML **merge keys** (`<<: *anchor`) were rejected
    outright, because the merge node reached `construct_object` before
    `flatten_mapping` ran; merge nodes are skipped by the scan instead of flattened
    first, since flattening would make overriding a merged value — the point of a merge —
    look like a duplicate.
  - **The credential guard missed camelCase.** `accessToken`, `clientSecret` and
    `bearerToken` split into one segment each and were accepted, while `access_token` was
    refused: the guard depended on an adapter author's naming style rather than on what
    the key means. Keys are now split on case boundaries as well as `-`/`_`. It also did
    not descend through a list *of lists*, so a secret two containers down slipped
    through the same rule the rest of the tree enforces.
  - **`SourceConfig` was frozen but unhashable** — the identical defect B2 fixed on
    `SemanticObject.source_refs`, and fixed the same way (`field(hash=False)`: compared,
    not hashed). Worth noting as a pattern rather than an incident: any frozen dataclass
    here that holds a mapping needs it, and the next one will too.

  Decisions, for later sessions:
  - **§11 #5 is resolved, and slightly wider than the spec's own default.** One
    `default_language` per instance, applied to every label and definition that arrives
    **without** a language; a label that arrives **with** one keeps it and is never
    overwritten. §5.5 rule 6 and the §11 table now say so. The consequence lands on
    **C1**: labels in the internal model can no longer be assumed untagged, so the graph
    builder applies the default per label rather than to all of them. `model.py`'s
    `pref_label` docstring still describes the untagged case, which is what every v1
    adapter produces — C1 owns widening it, and `is_language_tag()` is now public in
    `model.py` so both places agree on what a tag is.
  - **PyYAML is a new runtime dependency**, added to §5.1's dependency sentence in the
    same change. Instances still install with plain pip; nothing about §6.2 changes.
    `_StrictLoader` extends `SafeLoader` and additionally **rejects duplicate mapping
    keys** — YAML's own rule is last-one-wins, which would silently discard a configured
    value in the file whose whole job is to say which sources exist.
  - **Validation collects every issue and raises once.** `ConfigError` carries
    `issues: tuple[Issue, ...]`, each with the dotted key that caused it
    (`sources[1].name`, `sources[0].config.api_key`). F2 should render these rather than
    re-deriving locations, and `semprini check` reports them as a list.
  - **Unknown keys are errors.** A misspelled key that is merely ignored is the worst
    configuration bug available: the run succeeds and does the wrong thing. Adding a key
    to §5.1's config format therefore means adding it to `_TOP_LEVEL_KEYS`,
    `_INSTANCE_KEYS` or `_SOURCE_KEYS`. A source's own `config:` subtree is exempt — it
    belongs to the adapter, which validates it in `validate_config()` (§5.2).
  - **Credentials are refused by key name, at any depth**, including inside lists of
    mappings, and a token pasted into `token_env` is caught by requiring that value to
    look like a variable *name*. The word list is deliberately per key segment, so
    `base_url` and `source_key` pass while `api_key` and `auth_token` do not; a key
    ending in `_env` is the one escape hatch. `SourceConfig.secret()` reads the
    environment and **returns** the value — nothing stores it, so a config object is safe
    to print into a run report. A named-but-unset variable is exit **2**, not 3: the
    operator forgot a secret, the source is not unreachable.
  - **`known_adapters` is injected, not discovered.** Entry-point discovery is D1's, and
    a second copy here would drift. Passing `None` skips the adapter-name check, which is
    what the CLI does today — checking against an empty set would reject every valid
    config. **D1 wires discovery into `cli._load_config`'s one call site.**
  - **`run`, `check` and `migrate` now load configuration before reporting themselves
    unimplemented**, so a broken config exits 2 today rather than 1 after the feature
    lands; `run` also validates `--source` against the configured sources, since a typo
    would otherwise compile nothing and exit 0, which reads as success. `init` is
    excluded — it writes the file — and `adapters`/`version` describe the installation.
  - **Adapter settings are deep-frozen** (nested mappings read-only, nested lists
    tuples). D2/D3 will therefore receive tuples where YAML had lists; iteration is
    unaffected, mutation raises, which is the point (§5.2 forbids an adapter editing
    shared state).
  - **`tests/fixtures/acme/` now exists**, holding only `config/semprini.yaml`, and
    `conftest.py` has an `instance` fixture that copies it to a temp directory and chdirs
    there. **D2 fills in the rest** of the fixture instance around that config, which
    already names `sources/taxonomies/product-category.xlsx` and the
    `product-category` scheme. Its base IRI is `https://semantics.example.com/`
    (reserved by RFC 2606) rather than the spec example's `semantics.acme.com`.

- [x] **B4 · Identity: ID map, minting, namespace lock**
  **Spec:** §3.4, §5.4
  **Deliver:** `src/semprini/identity.py` — ID-map read/append, minting per §3.4.2, UUIDv5
  namespace constant, collision detection, namespace lock write/verify.
  **Verify:** lookup hit reuses an IRI; miss mints and appends exactly one row; two
  source keys colliding on one IRI raises; a removed row is detected against a base
  revision; base-IRI mismatch against the lock exits 2; `--force-namespace-change`
  rewrites map and lock together. Property test: minting is stable across processes
  (no reliance on hash seed or dict order).
  **Depends:** B2, B3
  **Merged — [PR #4](https://github.com/JuhaKor/semprini/pull/4).**
  **Done.** 261 tests green; ruff, ruff format and mypy (strict) clean. Twenty-nine
  mutations were checked against the suite — a source UUID left unnormalized, taxonomy
  schemes taken in arrival order, a value minted from its code, an unsafe local name
  accepted, a duplicate row absorbed, one IRI holding two kinds, a minting collision
  tolerated, an object with two IRIs silently resolved, a source key changing kind, a
  removed row undetected, a rewritten row undetected, an unconfigured source name
  tolerated, three line-ending regressions, rows re-sorted, a missing lock treated as no
  lock, the base IRI or the instance id not compared, the ontology version compared, a
  foreign IRI carried through the move, the move rewriting the lock alone, the registry
  writing as it mints, `Registry.load` skipping verification, the CLI skipping the lock
  check, `--force-namespace-change` not skipping it, the header unchecked, an unknown
  kind coerced, and only the first bad row reported — and each fails it. That battery
  paid for itself twice: `test_nothing_reaches_the_file_until_save` originally watched
  only the path it passed to `save()`, so a mutant that wrote to the *working directory*
  passed it — and wrote a `mappings/` tree into this repository, which §9.2 rule 5
  forbids. The test now chdirs to the temp path and asserts the directory stays empty.

  **Review found nine issues; all are fixed**, with a test and a mutation each (13 more
  mutations, all caught). Two were real defects and both are worth remembering, because
  the second is the shape of mistake this module exists to prevent:
  - **Two distinct objects could resolve to one IRI, silently.** The collision guard sat
    on the *minting* path only, and a lookup that hits never consults another object. The
    reachable history is ordinary: several ID-map rows share an IRI exactly when several
    sources described one object — which is what a merge records — so if the
    cross-reference that merged them later disappears from the sources, both objects
    arrive separately, both hit those rows, and C1 would have emitted one node wearing two
    `skos:prefLabel`s. The question can only be asked over the whole model, so
    `Registry.resolve()` now checks that the mapping it returns is **injective**;
    `iri_for()` structurally cannot.
  - **`Registry.save()` defaulted to the working directory** while `Registry.load()` read
    from `config.repo_root`, so a run whose cwd was not the instance would write a stray
    partial map elsewhere and lose every row it appended. The registry now carries the
    root it loaded from. Nothing was broken yet — today's CLI always has cwd == repo_root
    — but this note previously told C1/E2 to "call `save()` exactly once", and the
    signature invited them to call it with no argument.

  The rest were narrower: `check_append_only` compared only the IRI, so a rewritten `kind`
  or `first_seen` passed (it now compares every column but `note`, the one stewards own);
  `UUID(key)` was treating URNs, braces and bare 32-hex as "the source provided a UUID",
  so a 32-digit business code would have frozen a local name no source issued (only the
  canonical form counts now); a byte-order mark — which Excel writes, and stewards open
  this CSV in Excel — made the header error print two identical-looking column lists (both
  files now read `utf-8-sig`); `--force-namespace-change` suspends every lock check, and
  so silently adopted a drifted `instance_id` and refreshed the lock's date on a no-op
  move (both refused now); scheme slugs were case-sensitive, so `Sales` and `sales` were
  two permanent IRIs and one file on a case-insensitive filesystem (slugs are held to
  `config.is_slug()`, the one definition the whole project uses); and the error handlers
  in `IdMap.load` / `NamespaceLock.load` plus `Registry.iri()` had no tests. Each of those
  changed §3.4 or §5.4, and the spec was edited in the same change.

  Decisions, for later sessions:
  - **`NAMESPACE_SEMPRINI` = `8865c94a-2211-5f26-8887-6d6d5cbaa1e0`**, which is
    `uuid5(NAMESPACE_URL, "https://w3id.org/semprini/ontology#")`. Written as a literal
    rather than as that expression: it is permanent for every instance in existence, and
    a derivation left as live code is a value someone can adjust in passing. It is in the
    spec (§3.4.2) as well as in the module, and a test pins both.
  - **Three spec gaps closed in the same change**, all in §3.4/§5.1: §3.4.2's "no source
    UUID" rule only fitted taxonomy values (it hashed a scheme slug), so it now states
    the general rule — `source-name:source-key` for everything else — and records the
    namespace constant; §5.1's CLI listing never carried `--force-namespace-change`,
    which §3.4.4 requires, so `run` now declares it; and §3.4.4 now says a *missing* lock
    aborts, that only base IRI and instance id are compared, and that local names survive
    a namespace move.
  - **`--force-namespace-change` is declared but not wired.** `identity.force_namespace_change()`
    exists and is tested; the flag currently only suspends the lock check, because the
    move must also rewrite every generated file and those do not exist until C1. **E2
    owns calling it**, and its "one reviewable commit" promise is E2's to keep.
  - **Two error types, two exit codes.** `NamespaceLockError` subclasses `ConfigError`
    (exit 2 — §5.1 makes "configuration or namespace-lock" one category, and the lock is
    frozen configuration); `IdentityError` is exit 1, which is what §6.1 check 6 reports.
    Both now share `model.IssueError`, which is where `ConfigError`'s issue-collecting
    and message rendering moved so that a second copy did not appear here.
  - **F2 should call the checks, not re-derive them.** `IdMap.check_append_only(base)` and
    `IdMap.check_sources_are_configured(names)` return `Issue`s; §6.1 check 6 is those two
    plus what `Registry` raises during a run. Getting the base revision out of git is
    F2's, and is the one part of check 6 not implemented here. **No command reaches an
    `IdentityError` yet**, so the CLI has no handler for one and none was added — dead
    code with no test is worse than the gap. Whoever wires the first identity-touching
    command (E2 or F2) owns mapping it to exit 1, which is what §6.1 check 6 reports.
  - **`Registry` accumulates in memory and writes only on `save()`**, which is what makes
    `--dry-run` and a mid-pipeline failure safe (§5.1). C1/E2 must call `save()` exactly
    once, after the generated files are written.
  - **The fixture instance gained `mappings/`** — a lock matching its configured base IRI,
    and a header-only ID map. D2 fills the map in with the workbook's rows.
  - `serialize.is_safe_local_name()` is now public: minting refuses a local name the
    serializer would have to write as a full `<IRI>`, and both must agree on what is safe.

---

## Phase C — Emit

- [x] **C1 · Graph builder and file partitioning**
  **Spec:** §3.2, §3.3, §4.2 (`generated/` file naming), §3.3 (`dcterms:modified`
  carry-forward)
  **Deliver:** internal model → one rdflib graph per output file, including the
  `sem:relatesTo` shortcut and `sem:sourceRef` composition.
  **Verify:** golden TTL from a hand-built internal model; recompiling unchanged input
  produces a byte-identical file **and** leaves `dcterms:modified` untouched — the test
  that proves scheduled no-op runs generate no diff.
  **Depends:** B1, B2, B4
  **Merged — [PR #6](https://github.com/JuhaKor/semprini/pull/6).**

  **Done.** 308 tests green (47 of them C1's); ruff, ruff format and mypy (strict) clean.
  Thirty mutations were checked against the suite — a subject duplicated into every
  file, the home scheme taken in arrival order, the shortcut moved to the entity's file,
  the shortcut emitted per relationship rather than per entity pair, its file chosen by
  model order, a malformed slug accepted where the file name is built, a renamed slug
  tolerated, a partial run built from part of a model, `enumerates` not checked to point
  at an entity, an unparseable generated file escaping as a traceback, only the first
  problem reported,
  `dcterms:modified` computed from one file's share of a subject, the date refreshed on
  every run, every block dating its subject rather than only the defining one, the previous
  state compared including the date itself, the ontology re-serialized instead of copied,
  schemes emitted without status/sourceRef/modified, `skos:hasTopConcept` emitted
  alongside its inverse, an object in no scheme tolerated, an undefined scheme tolerated, a
  value in the wrong kind of scheme tolerated, a dangling cross-reference emitted, an
  unminted `enumerates` tolerated, labels emitted untagged, CRLF line endings, the ontology
  copy read back as previous state, empty files written, `sem:sourceRef` composed with a
  different separator, a status other than `active`, and a node dated when nothing changed
  — and each fails it.

  **The session resumed from a mid-refactor stop; what was left is recorded here because
  the bug is worth not re-introducing.** A `sem:relatesTo` shortcut is a statement about
  the *source entity* but is written in the relationship's file, so one subject
  legitimately spans two files. The first version computed `dcterms:modified` from only
  the statements in the node's own file, while `read_previous()` compares against the
  union of all files. The two never matched, so every entity that was one end of a
  relationship had its date refreshed on **every run** — precisely the "no-op run produces
  no diff" guarantee C1 exists to establish. The fix is to gather statements per subject
  across all blocks first and date the node from that union;
  `test_recompiling_unchanged_input_is_byte_identical` and
  `test_an_unchanged_node_keeps_its_modified_date` are the two that caught it, and the
  mutation battery confirms both still would. Do not weaken them.

  Two tests also had to be repaired, and the reason generalizes: both reused the sample
  model's `product-category` scheme in cut-down models, and that scheme `enumerates` an
  entity the cut-down models omit — so the build refused them, correctly. A shared fixture
  carrying a cross-reference cannot be sliced. The order-independence test was rewritten
  besides: it claimed to reverse the scheme order but passed the same tuple as the sample
  model, so it asserted nothing the golden files did not already. It is now parametrized
  over both orders and checks which file *defines* the node, not merely which files exist.

  **Decisions taken** (all implemented and now in the spec):
  - **Partitioning is by scheme, and an object is written exactly once**, in the file of
    its lexicographically first scheme, carrying all its `skos:inScheme` triples. Writing
    it into every scheme's file would load to the same graph but make one changed label
    several changed hunks.
  - **The `sem:relatesTo` shortcut goes in the relationship's file**, not the entity's:
    the two change together, so a reviewer sees both halves in one hunk.
  - **`ontology.ttl` is copied verbatim**, never re-serialized — `sem.ttl`'s term comments
    are the vocabulary's published documentation and §5.5's comment-free rule governs an
    instance's own output, not that document (A3).
  - **`sem:status`, `sem:sourceRef` and `dcterms:modified` are emitted on every node**,
    schemes included: lifecycle (§3.5) applies to every object, and a scheme is deleted
    from a source as readily as anything else. §3.7's example omits them, and now says so.
  - **Only `skos:topConceptOf` is emitted, not `skos:hasTopConcept`** — the inverse would
    state one fact twice, in two files (§5.5 rule 4).
  - **Empty files are not written**: a scheme with no relationships produces no
    `relationships-*.ttl` at all.
  - **Rejected at build time, with the source ref named:** an object in no scheme, in an
    undefined scheme, or in the wrong *kind* of scheme (a taxonomy value in a glossary);
    a cross-reference to something the run did not compile; an `enumerates` IRI this
    instance never minted. The first three decide which file an object lands in, so they
    cannot wait for SHACL.
  - **Language:** `default_language` is applied to every label and definition. §5.5 rule
    6's "a label that arrives *with* a tag keeps it" is currently **unreachable** — the
    internal model carries plain strings and no v1 adapter produces a tagged label. The
    seam is one function, `_Builder._text()`. Widening `model` to carry per-label
    languages belongs with **D3**, the first adapter that could produce one.
  - **API, for C2 and E2:** `build(model, *, registry, context, previous=None, today=None)
    -> tuple[OutputFile, ...]`, plus `read_previous(repo_root)` and `write_all(files,
    repo_root)`. An `OutputFile` carries the rendered `text` *and* the `graph` it came
    from, so `--dry-run` and the determinism check see the exact bytes a real run would
    commit without a filesystem in the way; `graph` is `None` for the ontology copy, which
    must never be round-tripped through the serializer. `today` is injected, so nothing
    but the caller reads a clock — C2's manifest must stay timestamp-free (§4.3).
  - **`build()` does not write and does not save the registry.** It mints (through
    `registry.resolve`) but leaves both the files and `mappings/id-map.csv` to the caller,
    which is what keeps a mid-pipeline failure from half-writing an instance. **E2 calls
    `write_all()` then `registry.save()` exactly once, in that order.**

  **Review found seven issues; all are fixed**, with a test and a mutation each (8 more
  mutations, 30/30 now caught). Two were real defects reproduced against the committed
  code, and both are worth remembering:
  - **A scheme slug could move an output file outside `generated/`, and rename one
    silently.** Identity validates a slug on the run that *mints* it; every later run gets
    its IRI from the ID map and never looks at the slug again — but `_file_name()` kept
    using the *current* slug. Editing `scheme_slug` in `config/semprini.yaml` therefore
    moved `concepts-<slug>.ttl` to a new file while the scheme's IRI stayed what it always
    was, so the map and the output disagreed about what the scheme was called; and
    `../../pwned` composed `generated/concepts-../../pwned.ttl`, which resolves outside the
    machine-owned directory §4.3 is supposed to bound. Both are now refused at build time,
    against the shape *and* against the local name frozen in the map. The general lesson:
    **a value validated at mint time is not validated on any later run**, and this one
    named two things while only one of them was frozen.
  - **The `sem:relatesTo` shortcut was written once per relationship, breaking the
    module's own "one triple in exactly one place" invariant.** Two relationships between
    the same entity pair living in different schemes emitted the identical triple into two
    files — union 43 triples, sum of parts 44. The sample model has one relationship, so
    `test_every_triple_is_written_exactly_once` never saw it. The shortcut says only
    *that* two entities are related, so it is now keyed by the pair and written in the
    lexicographically first of their files; deleting one of two relationships no longer
    shows a removed `relatesTo` line for a fact that still holds.

  The rest were narrower: `read_previous()` let rdflib's `BadSyntax` escape as a traceback
  naming nothing actionable, where an unparseable `generated/` file is exactly what §4.3
  guards against (now a `BuildError` naming the file); `sem:enumerates` accepted any minted
  IRI, so one pasted from the wrong file passed while §3.3 types it scheme → **entity**
  (the ID map's `kind` column now decides); build errors were raised in three batches
  rather than collected, against `IssueError`'s whole purpose (now two, and the split is
  forced — `_file_name` cannot run until scheme membership is clean); a `_SchemeEntry`
  built with `iri=... or ""` would have serialized every `skos:inScheme` for that scheme as
  a relative `<>`; and `build()` silently ignored `RunContext.only_source`. Each of those
  changed §3.4.2, §4.2 or §5.1, and the spec was edited in the same change.

  **Known limitation, deliberately left — E2 owns it.** `_reference()` resolves through
  the registry, which also knows IRIs minted on *previous* runs, so what is actually
  refused is "an IRI this instance has never minted" rather than the stricter "an object
  this run compiled" its message describes. Tightening it was the intent, but it interacts
  with `--source X` partial runs (§5.4), where a cross-source reference legitimately falls
  outside the fetched scope. Decide it with that case in view rather than in isolation;
  the caveat is written into the docstring so the next reader does not assume it is
  tighter than it is.

  **Five spec edits landed in the same change**, since each is byte- or governance-
  affecting and would otherwise be re-decided differently by whoever touched this next:
  §4.1 gained `build.py`; §4.2 gained the partitioning rules (written once, in the
  lexicographically first scheme; the shortcut in the relationship's file; a node dated
  from all files, not one; no empty files; the ontology copied, never re-serialized);
  §3.3 now says only one direction of each inverse pair is emitted; §3.7 now says it is
  abbreviated and that `sem:sourceRef`/`sem:status`/`dcterms:modified` are on every node,
  schemes included — the same trap B1 found there, where an illustrative example
  disagreeing with a rule reaches the next task as a wrong golden file; and §5.1 now lists
  what the build stage refuses and why three of the five cannot wait for SHACL.

- [x] **C2 · Manifest and run report**
  **Spec:** §4.3, §5.6, §7 (version stamping)
  **Deliver:** `generated/.manifest.json` (content hashes, compiler and ontology
  versions, no timestamps) and `generated/.report.md`.
  **Verify:** manifest is byte-identical across two runs of identical input; recomputed
  hashes match; a hand-edited generated file is detected; the report renders the counts
  and warning categories §5.6 lists.
  **Depends:** C1
  **Merged — [PR #7](https://github.com/JuhaKor/semprini/pull/7).**
  **Done.** 405 tests green (97 of them C2's); ruff, ruff format and mypy (strict) clean.
  Thirty-seven mutations were checked against the suite — hashes not compared, a missing
  recorded file tolerated, an unrecorded file tolerated, only the top level of
  `generated/` scanned, manifest keys unsorted, no trailing newline, an uninstalled
  compiler recorded, the manifest or the report hashed, a file produced twice absorbed,
  only the compiler version checked for drift, unknown keys tolerated, a missing key
  tolerated, a non-digest value tolerated, a null version tolerated, a different hash
  algorithm, an escaping recorded name accepted, a backslash not treated as a path
  separator, the report recordable by a hand-edited manifest, `dcterms:modified` left in
  the change comparison, `unchanged` tolerating a missing file, `unchanged` comparing
  nothing, definitions demanded of every class, name clashes compared case-sensitively,
  name clashes compared across classes, listings uncapped, IRIs never shortened, an empty
  class omitted, a file counting every subject it mentions, nothing ever changed,
  everything new every run, a node's label or its type chosen by iteration order, free
  text not collapsed to one line, a pipe left unescaped in a table cell, deprecations
  dropped, the ontology copy counted as content, and a run date rendered — and each fails
  it.

  **Two of those needed a subprocess, and the reason generalizes.** rdflib holds a
  subject's objects in a *set*, so "which of a node's two labels names it" and "which of
  its two types is it counted as" follow string hashing: identical all day on one machine
  and different on the next. Both mutations survived in-process tests that *looked* like
  they were testing them — one of them twice. Only varying `PYTHONHASHSEED` across
  processes catches either, which is what B4 established for minting and what any future
  "pick one of several rdflib objects" needs.

  **Two decisions shape everything else here, and both are now in the spec.**

  **The manifest does not hash `.report.md`, and the report is not rewritten when nothing
  changed.** These are one decision. The report has to say "new/changed/deprecated"
  (§5.6), so a no-op run would rewrite "12 new" to "0 new" — and if the manifest hashed
  it, the manifest would move too. A scheduled compile that found nothing would then open
  a PR containing only a report saying it found nothing, which is exactly the empty diff
  C1 exists to prevent. So a run whose output is byte-identical to what is committed
  leaves the report alone, and the committed report is always the report of the run that
  produced the files beside it. **§5.6 said "every run writes it" and now says this** —
  the rule as written could not coexist with §4.3. The mechanism is `build.unchanged()`;
  **E2 owns calling it**, and the composition is asserted end to end in
  `test_a_no_op_run_leaves_the_whole_instance_untouched` rather than only in pieces.

  **A manifest is refused from an uninstalled source tree.** `compiler_version()` reports
  `0.0.0+source` with nothing installed, which identifies no release: two different
  working trees record the same string and the drift check passes between them.
  `UNINSTALLED_VERSION` is now public in `semprini/__init__.py` for exactly this — A1's
  note said "nothing may record this value in a manifest" and C2 is the first code able
  to keep that promise.

  Decisions, for later sessions:
  - **API, for E2 and F2:** `Manifest.create(files, *, compiler=None, ontology=None)`,
    `.to_file()`, `.dumps()`, `Manifest.load(repo_root)`, `.verify(repo_root)` and
    `.check_versions()`; `report.create(files, *, context, previous=None, sources=(),
    deprecated=())`, `.render()` and `.to_file()`. Both `to_file()` return an
    `OutputFile`, so `build.write_all()` writes them and nothing can disagree about
    encoding or line endings. The version arguments exist so the golden files pin
    `0.1.0`; **production callers pass neither**.
  - **`ManifestError` is a plain `IssueError`, exit code 1** (§6.1 checks 2 and 3 are
    validation failures). No command reaches one yet, so the CLI has no handler and none
    was added — dead code with no test is worse than the gap. **F2 owns** mapping it, and
    should call `verify()` and `check_versions()` rather than re-deriving them, the same
    way B4 left check 6.
  - **`sources` and `deprecated` are inputs to the report, not derived.** Only the run
    knows which adapters it invoked (**E2**), and deprecation is evaluated against the
    union of all configured sources (**E1**). Everything else comes from the graphs.
  - **"Removed" is deliberately not reported.** A node vanishing from the output is what
    §3.5 forbids, but it is only detectable when the file that held it is rewritten —
    stale files are not deleted until E2 — so the number would be wrong about as often as
    right. **E1** makes it unnecessary by deprecating instead of dropping; a metric a
    reviewer cannot trust is worse than none.
  - **`build.statements_by_subject()` is now public and is the one definition of "what is
    said about this node"** — excluding `dcterms:modified`, since a node compared against
    its own previous state including its date differs from itself whenever the previous
    run fell on another day. Both the carry-forward and the report's changed count use it;
    `test_changed_and_the_modified_dates_agree` pins them together.
  - Missing definitions are reported for entities, attributes and taxonomy values — the
    classes §6.1's warning names. A relationship's label is its verb and a scheme's is its
    title.
  - Same-name warnings group **within a class** and compare **case-insensitively**: two
    entities called `Customer` and `customer` are one ambiguity for a steward, while a
    taxonomy value named after the entity it classifies is ordinary. §5.3's Ellie warning
    is the same check.
  - **The shared sample model moved to `tests/sample.py`**, unchanged, because the golden
    Turtle, manifest and report must describe one run. `tests/test_build.py` imports it
    and is otherwise untouched. Golden files now include `.manifest.json` and
    `.report.md`; regenerate them deliberately, never reflexively.

  **Review found seven issues; all are fixed**, with a test and a mutation each (7 more
  mutations, 37/37 now caught), and **no golden file moved** — none of them changed what a
  correct run emits. Three are worth remembering:
  - **A recorded file name is a path segment, and nothing checked it.** `Manifest.loads`
    accepted any JSON key, so a hand-edited manifest naming `../../secrets.txt` had
    `verify()` read and hash a file outside `generated/` — the same escape C1 already
    refuses for a scheme slug, missed one module over. The guard now lives in
    `__post_init__` rather than only in the parser: the first attempt validated in
    `loads()` alone, and the test that was meant to prove it walked a hand-built
    `Manifest` straight past it and opened the file. **An invariant belongs where the
    object is built, not where the path is composed.**
  - **The unrecorded-file check only looked at the top level.** `generated/` is flat by
    spec, but anyone parsing the directory reads `generated/old/concepts-retired.ttl` too,
    so a nested file passed the check that exists precisely to catch stale output. Now
    walked recursively, comparing paths relative to `generated/`.
  - **Free text reached Markdown unescaped.** Labels are whatever a source holds — an
    Excel cell with a line break, a note containing `|` — and this file is pasted verbatim
    into a PR description (§6.2). A newline silently ended the bullet list it was in.
    `_inline()` and `_cell()` now bound that at the render points.

  The rest were narrower: a node carrying two `rdf:type`s had its class decided by
  iteration order (`min`, like the label); the per-file node count asked every node in the
  instance whether it was in each file, which is one store lookup per node per file on a
  module written for instances large enough to need `LISTING_LIMIT`; and
  `test_a_long_listing_is_capped_but_the_count_is_not` asserted a boundary against the
  whole document while the label it named appeared only in a *different* listing — it now
  extracts the section it claims to be pinning. The seventh was the handover note above:
  it did not say the manifest's own file belongs in the `unchanged()` comparison, and E2
  omitting it would commit a manifest saying 0.2.0 produced these files beside a report
  whose header says 0.1.0 did.

---

## Phase D — Adapters

- [x] **D1 · Adapter interface and plugin discovery**
  **Spec:** §5.2, §5.1 (`semprini adapters`)
  **Deliver:** `BaseAdapter`, entry-point discovery for group
  `semprini.adapters`, and the `semprini adapters` command.
  **Deliver also:** a shared adapter contract test suite third-party authors can run
  against their own adapter — the plugin promise of §1.2 is empty without one.
  **Verify:** a dummy adapter installed from a separate test distribution is discovered
  and listed; the contract suite catches an adapter that writes to disk, mints IRIs, or
  returns a partial model instead of raising; fetch failure exits 3.
  **Depends:** B2
  **Merged — [PR #8](https://github.com/JuhaKor/semprini/pull/8).**
  **Done.** 478 tests green (74 of them D1's); ruff, ruff format and mypy (strict) clean;
  the wheel still installs into a bare venv with pip and `semprini adapters` runs from it.
  Fifty-three mutations were checked against the suite — discovery unsorted, discovery
  importing every plugin, a duplicate name silently resolved, `load()` skipping each of
  its four refusals in turn, an unimportable plugin escaping as its own exception, an
  entry forgetting its distribution, `adapter_names()` listing only loadable adapters,
  `create()` passing the adapter's name as the source's, configuration loaded without the
  installed names, an empty installation rejecting every configuration, an unreachable
  source reported as a compile failure, every error mapped to exit 2, a broken plugin
  listed but not reported, `adapters` reading an instance, the write guard watching only
  `builtins.open` / ignoring `os.open` / ignoring `os.mkdir` / never restoring itself /
  treating reads as writes, construction unguarded, fetch writes tolerated, minting
  tolerated, a configured `enumerates` counted as minting, `sem:` terms tolerated,
  misattributed objects tolerated, a self-contradictory model tolerated, no second fetch,
  settings mutation undetected, the snapshot aliasing the settings, `validate_config`
  raising or rejecting tolerated, a warning treated as a violation, a multi-line summary
  tolerated, any exception counted as unreachable, a partial model tolerated, the
  unreachable case never exercised, only the first violation reported, a non-slug name
  tolerated, a non-adapter tolerated, tuple contents unscanned, the listing printing whole
  docstrings, and one broken plugin rendered as a list of one — and each fails it. Two
  earned their keep: the docstring mutation survived at first because the dummy adapter's
  docstring was a single line, so "first line" and "whole docstring" were the same string
  (it now has a body, like a real adapter will); and the `os.mkdir` guard turned out to be
  reported twice over, since the second fetch trips on the directory the first left behind
  — which is the concrete reason the no-writes rule exists, so the test now pins both.

  **Decisions taken** (all implemented and now in the spec):
  - **The dummy adapter is a real distribution, committed as it looks once installed** —
    `tests/fixtures/dummy-adapter/` holds the importable package beside its `.dist-info`,
    and a fixture puts that directory on `sys.path`. `importlib.metadata` then finds it by
    the same scan that finds every pip-installed package. Building and `pip install`ing
    it per run would exercise pip, need a build backend and a writable environment, and
    test the same one line. Nothing in `semprini` imports or names it;
    `entry_points.txt` is the only thing connecting the two, which is the claim §1.2
    makes. `tests/fixtures/broken-adapter/` is its counterpart: a plugin that raises on
    import, because "one broken plugin must not hide the others" cannot be faked well.
  - **Discovery imports nothing.** Listing what is installed is a metadata question, and
    answering it by importing would run arbitrary third-party code on every command that
    loads a configuration. `AdapterEntry.load()` is where import happens, and
    `semprini adapters` is the one command that loads everything — that is the question it
    exists to answer. Consequence: `adapter_names()` includes a broken plugin's name, so a
    plugin that fails to import is reported as broken rather than as missing.
  - **An adapter's `name` must equal the entry-point name it is registered under**, and
    `load()` refuses it otherwise, along with an entry point that does not import, is not
    a class, is not a `BaseAdapter`, or leaves `fetch()` abstract. An instance writes
    `adapter: <name>` in its configuration, so a class calling itself something else makes
    every message about it name a thing that appears in no file the operator can open. The
    cost is that one class cannot be registered under two names; an alias is a subclass,
    and that is written into the spec. **Two distributions claiming one name are refused
    too**, never resolved by installation order.
  - **`known_adapters` is now wired** (B3's handover), as `config.load(known_adapters=
    installed or None)`. Passing `None` when *nothing* is installed keeps B3's rule —
    checking against an empty set would reject every valid configuration — and that
    branch stops being reachable in a real install the moment D2 registers the first
    bundled adapter. **It is what keeps the fixture instance loadable today**, since its
    config names `excel-taxonomy` and nothing provides it yet.
  - **One error→exit-code mapping, `cli.exit_code_for`**, and `main()` wraps the whole
    dispatch in one handler. This also settles what B4 and C2 deferred: `IdentityError`
    and `ManifestError` are `IssueError`s, so they now reach the operator as a message
    and exit 1 rather than as a traceback, without either module gaining a handler of its
    own. `_load_config` no longer returns `ConfigError | ExitCode`; it raises, and what an
    operator sees is unchanged (asserted).
  - **`semprini.testing.check_contract()` is the contract, executable** — framework-free
    (no pytest import, no base class), so it ships in the wheel and runs under whatever
    the author's project uses. It collects every violation rather than stopping at the
    first, and requires the author to supply *both* a working configuration and one whose
    source cannot be read: `unreachable` is a required argument, because an adapter never
    asked what it does when its source is down is the one that answers "deprecate
    everything". §4.1 gained `testing.py` and `adapters/discovery.py`.
  - The write guard patches `builtins.open`, `io.open`, `os.open`, `os.mkdir`, `os.remove`
    and `os.replace`, **records rather than blocks**, and restores them in a `finally`. It
    is a guard, not a proof — an adapter determined to write behind it can — and the
    module says so. `io.open` is patched *as well as* `builtins.open` even though they are
    the same function, because `pathlib` holds its own reference and `Path.write_text`
    would otherwise pass straight through; a mutation pins that.

  **Review found six issues; all are fixed**, with a test and a mutation each (9 more
  mutations, 53/53 now caught). Four were in the contract suite, and they share one
  shape worth remembering: **a check that only runs on the happy path certifies the
  failure it exists to catch.**
  - **The write guard was blind to deletion and renaming.** `os.remove` and `os.unlink`
    are two module attributes bound to two different functions, so patching one left
    `Path.unlink()` unrecorded — deletion being the most damaging thing an adapter could
    do to an instance, and `Path.rename()` was never patched at all. The guarded calls
    are now a named list (`_GUARDED_OS_CALLS`), patched by name in a loop, so adding one
    is a word rather than three edits.
  - **Writes were discarded on every failure path.** A fetch that wrote a partial file
    and *then* raised was reported only as a failure; the fetch against the unreachable
    configuration and the second fetch ran with no guard at all. So an adapter that saved
    what it managed to download before giving up passed the contract — on precisely the
    run that was supposed to change nothing. Every guarded block now reports through one
    helper, on both paths.
  - **The minting scan never looked inside a `SourceRef`.** It walked strings, tuples and
    mappings, and a `SourceRef` is a frozen dataclass — so `Attribute.entity`,
    `Relationship.source`/`target` and `TaxonomyValue.parent` escaped it. Those are the
    fields an author is likeliest to write an IRI into, since each one names another
    object. The scan is now recursive through dataclasses.
  - `summary()` was called outside a `try`, so an adapter whose report line raised
    escaped as a traceback rather than joining the collected list.

  The two in the CLI: **`semprini adapters` exited 0 on an installation where the
  configured adapter cannot be resolved** — two distributions claiming one name are
  refused at run time, but the listing loaded each entry independently and reported
  nothing, so the command whose job is "does this installation work" said yes and the run
  said no (`adapters.ambiguities()` is now shared by both, so they answer in the same
  words); and `_summary` used `inspect.getdoc`, which walks the MRO, so an adapter with
  no docstring was listed under `BaseAdapter`'s — a sentence the adapter never wrote,
  reading as though it had.

  **For the tasks that come next:**
  - **D2 and D3 each uncomment their own line in `pyproject.toml`** as their adapter class
    lands (A1's note). D2's is `excel-taxonomy = "semprini.adapters.excel_taxonomy:ExcelTaxonomyAdapter"`,
    and doing it turns the unknown-adapter check on for the fixture instance.
  - **Both should run `check_contract` against their adapter**, exactly as a third party
    would — `tests/test_adapter_contract.py::test_the_installed_dummy_adapter_meets_the_contract`
    is the call to copy. Note it fetches **twice** (determinism), which for D3 means two
    passes over the recorded responses.
  - **E2's fetch loop is `adapters.create(source, ctx)` per configured source**, then
    `fetch()`, then `merge_models(...)`; `adapter.summary()` is the line that fills
    `report.SourceSummary.note`, and the adapter is constructed before it fetches so
    `semprini check` can call `validate_config()` without opening a connection.
  - **Exit 3 is mapped but not yet reachable from the CLI**, since no command fetches.
    `exit_code_for` is tested directly and through the shape E2 will use
    (`test_an_unreachable_source_exits_3`); wiring it into a real run is E2's, and it
    needs no new mapping.
  - **G4's adapter authoring guide should point at `semprini.testing`** and at
    `tests/fixtures/dummy-adapter/`, which is written to be the worked example — a
    `fetch()` that reads and returns, a `validate_config()` that reports rather than
    raises, a `summary()` line, and a source failure raised as `SourceUnreachableError`.

- [x] **D2 · Excel taxonomy adapter, and the fixture instance**
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
  **Merged — [PR #9](https://github.com/JuhaKor/semprini/pull/9).**
  **Done.** 537 tests green (47 of them D2's); ruff, ruff format and mypy (strict) clean;
  the wheel installs into a bare venv with pip and `semprini adapters` lists
  `excel-taxonomy` from it. Thirty mutations were checked against the suite — 26 caught,
  and the four survivors are **equivalent mutants**, recorded below rather than chased.

  **The input format changed, and that is the headline.** §5.3 specified a flat sheet
  with `code` / `label` / `parent_code`; the pilot's workbooks are the shape the old
  prototype read — two sheets, and a **ragged** `L1..Ln` hierarchy where depth is a
  value's position across columns. The pilot format won and the spec was rewritten to
  match. Consequences worth knowing before reading the code:
  - **A cycle cannot be expressed.** A row's ancestors are a prefix of its own cells, so
    §5.3's cycle rule — and this task's own verify line — describe a check the format
    makes impossible. It is replaced by *skipped level* (`L1` and `L3` filled, `L2`
    empty), which is the same class of mistake and is what the prototype got wrong: it
    collected non-empty cells and discarded their positions, reading L1+L3 as depth 2 and
    silently attaching the value to the wrong parent.
  - **A label is structural**, so renaming an `L2` cell re-parents everything under it.
    Identity therefore comes from the `Concept URI` column and never from the labels.
  - **There is no `code` column**, so `TaxonomyValue.code` is now optional and this
    adapter emits no `skos:notation`. Deriving one from `Concept URI` would emit a code
    no source ever said and that stewards would then maintain.

  **One workbook is one taxonomy is one source.** This reverses the arrangement §5.3 and
  the fixture config had (`name: taxonomies` holding a `files:` list) and it was a
  requirement rather than a tidy-up: provenance has to say *which file* an object came
  from. It also removes a hazard rather than solving one — `Concept URI` values are only
  unique **within** a workbook, so one source spanning several would have collided in the
  ID map on a generic `Other` or `Miscellaneous`, and B4's injectivity check would have
  failed the pilot's second workbook. Per-workbook sources make the key unique by
  construction. Two rules protect it:
  - **A source name never names the adapter**, though that was asked for. `source_name`
    is half the ID map key and so permanent; `excel-product-category` would re-mint every
    IRI in that taxonomy the day the same content arrives as CSV. Which adapter read a
    file lives in the config and the run report, neither of which is identity.
  - **The path is not the name either**, and the *scheme* is keyed by its slug rather
    than its file name, so a workbook can be moved or renamed freely.

  **Decisions taken** (all implemented and now in the spec):
  - **`skos:hiddenLabel`, `skos:scopeNote` and `skos:example` are in**, all set-valued and
    on `SemanticObject` rather than on `TaxonomyValue` — everything here is a
    `skos:Concept`, and D3 will supply examples for entities. They are **reused SKOS
    terms**, so `sem.ttl` did not change and there is no ontology version bump: the A2/G5
    frozen-version gap stays closed. Set-valued because two sources each contributing an
    example are not in disagreement; making them scalars would fail runs over data that
    agrees. `Notes` and the four provenance columns are tolerated and ignored — they would
    be real `sem:` additions, and a hand-typed extraction date does not belong in a graph
    the compiler regenerates.
  - **The model now carries language, and D2 inherited that job from D3.** The workbook
    writes `"Power tools"@en`, so this is the first adapter to produce a tagged label and
    §5.5 rule 6's "a label that arrives with a tag keeps it" branch is reachable at last.
    `model.Text` is a value type of `(value, language | None)`; a plain `str` normalizes
    to it, so every existing construction site was untouched. **Two texts with the same
    characters and different languages are not equal**, which makes them a merge conflict
    instead of an order-dependent silent choice — a real limitation (§3.3 allows one
    `prefLabel` per language and a scalar field cannot hold two), but the honest way to
    meet it. Three levels of language, narrowest first: the cell's own tag, the
    workbook's `Language` row, then the instance's `default_language`.
  - **`Scheme.enumerates` is now a `SourceRef`, not an IRI.** The workbook names the
    entity by its key in the modelling tool, and an adapter has no IRIs to point with.
    This **removed the one exception** in `testing.py`'s no-minting check, so that rule
    now reads the same for every field. Note the consequence for H1: a workbook with
    `Reference Entity UUID` filled in will not compile until the Ellie source is
    configured and compiled, and the build error says exactly that. The fixture leaves
    the cell blank.
  - **Header matching is strict.** A missing `Concept URI` or `L1` column is refused,
    naming the headers it did find. Lenient matching is what makes this format fail
    quietly: a sheet whose level columns are called `Level 1` reads as an *empty*
    taxonomy, which compiles to a scheme with no values and deprecates everything that
    was in it.
  - **Every problem in a workbook is reported at once**, which is a deliberate departure
    from `AdapterError`'s single-cause shape (D1). A taxonomy is edited in bulk, so its
    mistakes arrive in bulk, and one per CI run costs a steward a round trip each.

  **One defect found by its own test and worth not re-introducing.** The hierarchy was
  first matched on **raw cell text**, so `"Tools"@en` in one row and a bare `Tools` in
  another were two branches — and every row under the second spelling was reported as an
  orphan pointing at a parent the reviewer could plainly see in the sheet. The fixture's
  own workbook mixes both spellings. Matching is on parsed label *values* now
  (`test_a_branch_spelled_two_ways_is_still_one_branch`). The general lesson is the same
  one C1 recorded about scheme slugs: **a value that is parsed for one purpose must be
  parsed before it is used for another.**

  **The five surviving mutants, so nobody re-litigates them:** depth-by-count instead of
  depth-by-position is equivalent *because* the skipped-level guard runs first, leaving
  `filled` always contiguous; the two spellings of the empty-member filter agree on every
  reachable input, since `Text("")` cannot be constructed; the `enumerates` re-check in
  `build.py` is unreachable by construction (hence its `pragma: no cover`) and exists only
  so that `python -O` cannot turn it into a `TypeError` from inside rdflib; and judging
  only the local path flavour is equivalent on Windows but **is** caught on CI, which runs
  `ubuntu-latest`, by the `C:\keys\...` case.

  **Review found six issues; all are fixed**, with a test and a mutation each (6 more
  mutations, all caught) and **no golden file moved** — none of them changed what a
  correct workbook produces. Three shared one shape, and it is the shape this format
  invites: *a reader that is too permissive does not fail, it produces a different
  taxonomy.*
  - **Level columns were never checked to run `L1..Ln`.** The guard was "at least one
    level column exists" while its message claimed to be about `L1`. A sheet starting at
    `L2` — or one that lost its `L2` in a re-export — compiled as a complete hierarchy
    with every value one level too shallow: every `skos:broader` moved, the run
    succeeded, and the diff read as a deliberate re-levelling. This is the header-level
    twin of the skipped-level rule, and only the header can catch it.
  - **Semicolon splitting ran before literal parsing.** `"A; B"@fi; "C"@fi` came apart
    into fragments that kept stray quotation marks *and* lost the `@fi` the cell stated —
    wrong RDF rather than an error. Splitting now respects quotes.
  - **The literal pattern was greedy**, so a definition reading `"Smart" tools "here"` had
    its outer characters silently deleted on the way into a governed file. Only a cell
    whose quoted part holds no further quotation mark counts as literal syntax now.
  - **A half-finished row vanished.** "Blank row" was judged on the identity and level
    cells alone, so a row carrying a definition but no `Concept URI` yet was dropped as
    punctuation — the same silent disappearance the no-identity rule exists to prevent,
    one condition earlier.
  - **`validate_config()` is on no compile path.** It is called by `semprini check` and by
    the contract suite and by nothing else, so a run that skipped `check` reached the
    workbook with settings nobody had validated — where an absolute `path` silently wins
    over `repo_root` and a missing key is a bare `KeyError`. `fetch()` now validates its
    own configuration first and raises `ConfigError` (exit 2). **E2 should not need to
    remember this**, which is why it lives in the adapter rather than in the run loop.
  - An `assert` guarding the resolved `sem:enumerates` IRI would have been stripped under
    `python -O`, leaving `URIRef(None)`.

  **For the tasks that come next:**
  - **`tools/build_fixture_instance.py` is a stand-in for `semprini run` and E2 replaces
    it.** It already keeps E2's write order (build → manifest → `unchanged()` → report
    only if something moved → `write_all` → `registry.save()` once) and is imported by the
    suite, so the code that regenerates the committed fixture and the code that verifies
    it are the same code. `pythonpath = ["."]` in `pyproject.toml` is what lets tests
    import it; `tools/` gained an `__init__.py` so mypy sees one module, not two.
  - **The fixture instance is now complete and is the thing to compile.** `semprini run`
    against `tests/fixtures/acme/` should reproduce `generated/` byte for byte and append
    no ID-map row; both are asserted today through the stand-in.
  - **`tests/sample.py` was deliberately left alone.** Its `EXCEL = "taxonomies"` source
    and `product-category.xlsx` scheme key model the *old* arrangement, and it is a
    hand-built model exercising all five kinds rather than adapter output — no adapter
    produces entities until D3. Updating it would churn three golden files for no
    behavioural gain, but a reader should not mistake it for what the adapter emits.
  - **F1's shapes** should cover the three new properties with a language-tag constraint
    and nothing more; specifically **do not** extend §6.1's missing-definition warning to
    missing scope notes.
  - **D3 inherits one open question from the language work, and it is a decision, not a
    bug.** `Text` makes "same characters, different language" a merge conflict, and the
    docstring's mitigation — "no v1 adapter produces a tagged label" — expired the moment
    this adapter started tagging every label with the workbook's `Language`. So as soon as
    a second source describes an object the workbook also describes and states no language
    of its own, `merge_models` raises on `pref_label` even though both sources say
    `"Customer"`. It cannot happen before D3, since nothing else produces objects yet.
    **Decide it deliberately:** either an untagged value defers to a tagged one (they are
    the same statement, one of them better informed), or the conflict stands and the
    instance's `default_language` is expected to match. Left raising for now, because
    loosening it later is easy and tightening it once instances hold files built under the
    loose rule is not.
  - The other thing D3 inherits is `sem:enumerates`: Ellie entities are what a taxonomy's
    `Reference Entity UUID` points at, so the fixture can gain a populated one once that
    adapter lands.

- [x] **D3 · Ellie adapter**
  **Spec:** §5.3 (Ellie adapter)
  **Deliver:** `src/semprini/adapters/ellie.py` reading **exported** Ellie models, with a
  synthetic export in the fixture instance. Reuse the field semantics documented in
  `background-material/kg-converter-old/README.md` §1.1 — that project read the same
  data and its field tables are trustworthy, though nothing about its RDF mapping is.
  **Verify:** an allowlisted model that is missing or unreadable fails the run; an entity
  in two models yields one node with two `skos:inScheme` triples; two UUIDs sharing a name
  yield two nodes plus a report warning; an empty description emits no `skos:definition`.
  **Depends:** D1
  **~~Gated by:~~ §11 #7 is resolved by the scope change below** — v1 makes no API call,
  so pagination and rate limits belong to the later API mode.
  **Merged — [PR #10](https://github.com/JuhaKor/semprini/pull/10).**
  **Done.** 619 tests green (72 of them D3's); ruff, ruff format and mypy (strict) clean;
  the wheel installs into a bare venv with pip and `semprini adapters` lists both `ellie`
  and `excel-taxonomy` from it. Fifty mutations were checked against the suite — the
  model never unwrapped, an unrecognized document read as a model, `modelId` unchecked or
  compared raw rather than as text, inheritance detected from one end only, inheritance
  also reified, an entity its own supertype, only the first supertype kept, `broader` not
  a union field, self-broader tolerated, `skos:narrower` emitted instead, `broader` not
  emitted at all, the label preferred over Ellie's `name`, any direction taken as the
  reading direction, the preferred label repeated as an alternative, an unlabelled
  relationship skipped, a missing end tolerated, synonyms unsplit, examples split, an
  entity or attribute missing an id or name skipped, attributes not read, a nameless model
  tolerated, the scheme keyed by its slug, a malformed array read as empty, a non-object
  member skipped, nested metadata never read, the model not normalized, a merge conflict
  escaping as itself, a missing export reported as a compile error, unreadable JSON
  reported as unreachable, only the first problem reported, `fetch` not validating its own
  settings, `base_url` optional or unchecked, duplicate model ids or scheme slugs
  tolerated, a path outside the instance tolerated, an unknown model setting tolerated,
  `token_env` accepted silently, the summary omitting the model name, and the three
  `enumerates_source` mutations below — and each fails it. **Three survived the first
  run**, and all three were gaps in the tests rather than in the code: the
  reading-direction test happened to list the target-direction label first, so "take
  whichever label comes first" passed it; nothing covered a malformed *member* of a
  well-formed array; and the `base_url` test asserted only the issue's location, which
  both the missing and the malformed branch produce.

  **A code review of the branch then changed five behaviours** (all of them refusals or
  leniency, none of them the graph the fixture compiles — it recompiles byte-for-byte):
  - **A verb label with no `direction` now reads source → target**, as Ellie's own rule
    has it: `"source"` is the exception and everything else, absent included, is forward.
    Requiring the literal `"target"` discarded the only label a single-label relationship
    carries and then refused the relationship for having none — a legitimate model made
    uncompilable. The comparison is case-folded too.
  - **A supertype relationship naming a narrower entity the model does not hold is
    refused.** Inheritance lands *on* that entity, so with no entity to carry the
    reference the build stage has nothing to fail on: this was the one cross-reference
    that could vanish without a diff line.
  - **An export stating no `entities` key at all is refused as truncated.** An export of
    an empty model states `"entities": []`, so the two are now separated — reading the
    first as the second compiles an empty scheme and deprecates a whole domain.
  - **A file that will not parse joins the batch** instead of raising on the spot, so two
    broken models cost one CI round trip rather than two. `SourceUnreachableError` still
    raises immediately: exit 3 is a retry, not an edit.
  - **`enumerates_source` naming the taxonomy's own source is refused** (exit 2) — the
    exact mistake the setting was added to undo. A *misspelt* source name is still only
    caught at build: an adapter is given its own settings and not the roster of configured
    sources, and the comment claiming otherwise was corrected rather than the code.

  Two further review findings were left alone deliberately. `skos:broader` cycles of
  length ≥ 2 are real and uncaught — **F1 owns them**, see the note there. And §6.1.5 had
  said `skos:broader` was "only between concepts in the same taxonomy scheme", which D3's
  entity inheritance contradicts; the spec line was corrected in this change, since a
  shape written to it would have rejected the fixture.

  **The scope changed before the work started, and that is the headline.** §5.3 specified
  the Ellie REST API; the requirement is to ingest a JSON file already exported from
  `GET /api/v1/models/{id}`, with a direct API call considered later. The spec was
  rewritten to match, and the consequences are worth knowing before reading the code:
  - **The API mode is a later mode of *this* adapter, not a second adapter.** Identity is
    keyed by `(source name, Ellie UUID)`, so a source that switched adapters would re-mint
    every IRI it owns. `base_url` is therefore configured in file mode too — it records
    which Ellie instance the UUIDs belong to, appears in the run report, and is what the
    API mode will read. A `token_env` is **refused** today with a message saying the API
    mode has not shipped, rather than accepted and ignored.
  - **v1 makes no network call at all**, since both bundled adapters now read committed
    files. `requests` stays a declared dependency for the API mode and is currently unused.
  - **§11 #7 stops gating anything.** Pagination and rate limits are settled against
    Ellie's API documentation when that mode is built.

  **One Ellie instance is one source, which is the opposite of D2's arrangement and for
  the opposite reason.** Ellie UUIDs are unique across an *instance*, not within a model —
  that is exactly what lets one entity appear in two domain models and resolve to one node
  — so every model of an instance is listed under one source name, and two Ellie instances
  are two sources. A workbook's keys are unique only within the file, hence one workbook,
  one source. The allowlist is the `models:` list, each entry carrying `id`, `path` and
  `scheme_slug`; an export whose `modelId` disagrees with the id it is listed under is
  refused, because a file copied over the wrong path otherwise replaces a scheme's whole
  contents and reads as ordinary change.

  **Decisions taken** (all implemented and now in the spec):
  - **Inheritance is `skos:broader`, and emits no relationship node.** Ellie draws a
    supertype as an ordinary relationship whose ends are typed `superType`/`subType` — and
    gives it no name and no verb labels, so reifying it would mean inventing a
    `skos:prefLabel` no modeller wrote. `Entity.broader` is a **tuple**, not a scalar: the
    source can express multiple inheritance, and two models that differ only in whether
    they draw the supertype must union rather than conflict. §3.3 now says `skos:broader`
    has two uses, and that a `sem:` term for inheritance would say no more while costing a
    metamodel version bump.
  - **A relationship's label is Ellie's `name` when a modeller filled one in**, and
    otherwise the verb whose direction reads source → target; every other verb becomes a
    `skos:altLabel`. In the fixture's export `name` is null on all thirteen relationships,
    so the fallback is the live path — but a name appearing later re-labels the node
    without re-minting it, which is why it is preferred.
  - **The scheme's source key is Ellie's model id, not the slug.** The slug is this
    instance's name for the scheme and the id is the source's, and the ID map is keyed by
    the source's (§5.4). Renaming a model in Ellie then costs no identity.
  - **Both file shapes are accepted** — with and without the outer `model` wrapper —
    recognized by *structure* rather than by key presence, and a document that is neither
    is refused by name. A lenient reader here does not fail, it produces an empty model,
    which compiles to an empty scheme and deprecates everything that was in it.
  - **What is deliberately not carried**: `progressStatus`, entity `type`, `Source
    systems`, `Administrated by`, relationship cardinality, and every attribute metadata
    field but `Description`. Each needs a term the metamodel does not have, and minting one
    per Ellie field is what the removal of `sem:ellieId` ruled out (§3.3). The spec records
    them as **deferred, not ignored**, and names `Data type`/`Semantic link` as what
    `sem:represents` is reserved for. A test asserts none of those values reaches a
    statement, so a future task adding them changes it on purpose.
  - **Synonyms are comma-split into `skos:altLabel`; the examples field is one
    `skos:example`, uncut** — it is prose a modeller wrote, and splitting it would invent
    several statements where the source made one. Same rule D2 applied to workbook cells.

  **A defect in D2's `sem:enumerates` was found by populating the fixture, and it made the
  feature unusable rather than merely wrong.** The Excel adapter built the reference as
  `SourceRef(self.source_name, uuid)` — the *taxonomy's* own source name — while the
  entity's ID-map row is keyed under the modelling tool's. The lookup could therefore never
  hit, and the only visible symptom was the build error "enumerates …, which no run has
  compiled", naming a source ref nobody had written. Nothing caught it because no fixture
  had ever filled the cell in. The workbook's source now states `enumerates_source` in its
  configuration, required exactly when the cell is filled: the workbook states a UUID, and
  which configured source issued that UUID is not a fact about the workbook. §5.3 says so.

  **The fixture instance now has two sources whose objects meet.** `Storefront.json` from
  the old prototype's tests is synthetic demo data cleared for use, and is committed as
  `tests/fixtures/acme/sources/ellie/storefront.json` (normalized to LF, otherwise
  verbatim); the taxonomy's `Reference Entity UUID` names its `Product category` entity, so
  `sem:enumerates` resolves across sources for the first time. That deliberately moved the
  committed golden files. What the fixture now exercises that nothing did before: a
  cross-source reference through the ID map, `skos:broader` between entities, a reified
  relationship with its `sem:relatesTo` shortcut, and C2's same-name warning — the export
  has a `Product ID` attribute on both `Product` and `Order line`, which is D3's own verify
  line about two UUIDs sharing a name.

  **For the tasks that come next:**
  - **E1/E2 inherit an unexercised path**: nothing yet compiles a model whose entity is in
    two schemes across two *files*, since the fixture lists one model. The unit tests cover
    the merge; the partitioning rule (written once, in the lexicographically first scheme)
    is covered by C1's own tests.
  - **`config.escapes_the_instance()` is now public**, moved out of the Excel adapter: two
    adapters configure a file to read, and both must refuse a path leading out of the
    repository. A third should import it rather than re-derive it.
  - **The tests that need an uninstalled adapter now name `no-such-adapter`**, not `ellie`.
    They named `ellie` because it was not installed, and D2 had already had to move them
    off `excel-taxonomy` for the same reason. A test whose premise quietly becomes false
    does not fail — it stops testing what it says it does.
  - **D2's language question is still open and still unreachable.** `Text` makes "same
    characters, different language" a merge conflict; Ellie states no language, so its
    labels arrive untagged and take the instance's `default_language` at build time. The
    conflict needs two sources describing *one object*, which nothing produces: the
    taxonomy and the models share no source key. Left raising, deliberately.
  - **G4's adapter guide** now has two worked examples of different shapes — one file, one
    file per allowlisted item — plus the dummy adapter D1 wrote for the purpose.

---

## Phase E — Compile end to end

- [x] **E1 · Lifecycle, deprecation and the merge register**
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
  **Merged — [PR #11](https://github.com/JuhaKor/semprini/pull/11).**
  **Done.** 673 tests green (51 of them E1's); ruff, ruff format and mypy (strict) clean;
  the fixture instance still recompiles byte for byte and appends no ID-map row. Thirty-six
  mutations were checked against the suite — deprecation judged per source rather than the
  union, scope ignored entirely, `--source` ignored, out-of-scope nodes skipped instead of
  carried, only the label carried, the status not changed, `dcterms:modified` carried
  rather than recomputed on either path, a stale `dcterms:isReplacedBy` kept, the
  replacement not emitted, the status written on every block rather than the defining one,
  blocks that define nothing treated as nodes, an unmapped node dropped, every carried node
  reported as newly deprecated, planning minting, nodes walked in arrival order, only the
  first problem reported, self-replacement tolerated, a second successor tolerated, cycles
  tolerated, either IRI unchecked against the ID map, a register row for a live object
  tolerated, the columns unchecked, an empty file read as an empty register,
  `replacement()` following the chain, a hand-typed IRI unstripped, CRLF, a BOM refused, a
  bad row aborting the batch, a carried node colliding with a compiled one tolerated,
  carried nodes never dated, the ontology copy read back as previous state, a deprecation
  counted as a change as well, every deprecated node reported rather than the new ones, and
  a first compile reporting its whole output as deprecated — and each fails it. **Four
  survived the first run**, and all four were gaps in the tests: nothing checked which
  *file* a status line lands in (the shortcut's file is the second file a node can appear
  in); nothing exercised a subject the output states something about but does not describe;
  and `plan.deprecated` was only ever asserted one element at a time, so its ordering was
  unpinned — the previous state is read file by file, and a plan ordered by that would
  reshuffle whenever a scheme was renamed.

  **The shape of the whole task is one rule: a run that did not look cannot conclude.**
  §5.4 says a `--source X` run "skips deprecation" outside its scope, and the obvious
  reading — leave those nodes out — is wrong in the most damaging way available: files are
  rewritten whole, so a node left out of the run's output is a node **deleted** from the
  instance. Out-of-scope objects are therefore carried forward *verbatim*, status and all.
  Scope is decided per object rather than per run: a node is judged only if every
  `source_name` the ID map records against its IRI was fetched. That covers a case the
  spec did not name — a full run whose ID map holds a source no longer in
  `config/semprini.yaml`. Its objects are now carried rather than deprecated, so a
  configuration typo cannot empty half the graph while `semprini check` is still the thing
  that reports the rename (§5.4).

  **Decisions taken** (all implemented and now in the spec):
  - **Lifecycle runs *before* build, not over its output.** §5.1's pipeline listing had it
    after; a deprecated object is not in the model, so there is nothing for a later pass to
    edit, and retained nodes have to exist when files are assembled and dated. The seam is
    `build.CarriedNode` — file, subject, statements, `defines` — and `build(...,
    carried=...)` turns each into the same `_Block` the model produces, so dating,
    partitioning and serialization are one code path for both. §5.1 now says so.
  - **A retained node keeps its file, and only its *defining* block is marked.** The first
    makes a deprecation one changed `sem:status` line instead of a deletion in one file and
    an addition in another; the second stops a `sem:relatesTo` shortcut's file from
    restating the status, which would put one changed fact in two hunks (§4.2, §5.5 rule 4).
  - **Three statements are re-derived, everything else is carried:** `sem:status`,
    `dcterms:isReplacedBy` and `dcterms:modified`. The date then follows the ordinary rule
    (§3.3) with no special case — it moves on the run that deprecates and never again — and
    `dcterms:isReplacedBy` is re-read from the register every run, so a steward can delete
    a row and watch the triple go.
  - **The merge register refuses rather than repairs**, and each rule is one a person can
    trip: both IRIs must be in the ID map, one deprecated object has one successor, no row
    replaces an object with itself, and no chain of rows closes into a cycle — a cycle
    names no survivor, which is the register's only question. **Chains are allowed and
    deliberately not followed**: if A → B is recorded and later B → C, A's successor is
    emitted as B, because that is the statement the steward made.
  - **A register row for an object the sources still describe fails the run.** The register
    and the sources contradict each other and the compiler settles neither: deprecating
    anyway would override every source from a one-line CSV edit, ignoring the row would
    make the register silently inert. The cost is a real one — a steward who adds the row
    before the source export catches up gets a failed compile — and the message names both
    ways out. Recorded here because the alternative is defensible and should be re-decided
    deliberately, not by accident.
  - **An IRI in `generated/` that the ID map does not hold fails the run** (exit 1). It
    means a row was deleted or a file was hand-edited, and the compiler cannot say which
    source the node came from. Checked here rather than left to §6.1 check 6, which needs
    git to compare against a base revision — this holds for a local run too.
  - **The report now derives "deprecated" from the graphs** instead of taking it from the
    caller, which is what C2 left open. Once lifecycle has decided, the decision is *in* the
    output, and report.py's own rule is that everything in it is read from the files it
    describes. `report.create()` lost its `deprecated=` argument. New/changed/deprecated
    now **partition** the nodes — a deprecation was previously counted twice — so
    "Changed 12 · Deprecated 3" means fifteen nodes moved. §5.6 says both.
  - **`build.read_previous_files()` and `build.union_of()` are new and public.** Lifecycle
    needs the previous state per file (a retained node stays where it was) and the builder
    and report need it unioned; parsing `generated/` twice to get both would be waste that
    only shows on the instances large enough to care. `read_previous()` is now the union of
    the former.

  **A code review found three issues; one was a real defect and is fixed, and the other
  two were decisions rather than bugs — recorded here so nobody re-litigates them.**
  - **The `sem:relatesTo` shortcut was silently deleted when its relationship was out of
    scope**, which is the exact failure this module exists to prevent, reached through the
    module itself. The shortcut is the one statement written away from the node it is
    about (§4.2): its subject is the source *entity*, but it lives in the relationship's
    file. So when the entity is still reported and the relationship is not, neither rule
    reached it — the entity was rebuilt from a model that no longer held the relationship,
    while the relationship itself was carried forward as active, and the derived triple
    just vanished. Reproduced against the committed code before fixing. Retention is now
    decided per *block* rather than per subject, and two cases are deliberately not
    retained: a pair the run still derives (the build stage writes it, and writing it here
    as well would put one triple in two files), and a pair whose only relationship was
    *deprecated* — `sem:relatesTo` carries no status of its own, so leaving it would
    assert a live relation on the strength of a retired one. **§4.2 gained a rule and
    `build` gained the check that enforces it**: no statement may be written into two
    files. That was previously an invariant C1 tested for and nothing verified at run time,
    and it stops being safe by construction the moment a run assembles its files from two
    kinds of evidence.
  - **A merge register row for an out-of-scope object does nothing that run** — reported as
    "silently inert". It is the scope rule applied to the register, and the alternative is
    worse: acting on the row means deprecating a node the run has no evidence about, which
    is the one thing `--source` promises not to do. The next full run applies it. On a
    *full* run this state means the ID map names an unconfigured source, which is already
    an error §6.1 check 6 reports. Pinned by a test and written into §5.4.
  - **A successor that is later deprecated by its own source is not an error.** Reported as
    a gap in the cycle check; it is ordinary history — A was merged into B, and B was
    afterwards retired — and refusing it would have the compiler retroactively invalidate a
    decision a steward recorded correctly at the time. A cycle is refused because a cycle
    never had a survivor; a chain that ends in a deprecated node did. §5.4 now says so.

  Seven more mutations cover the fix (43 total, 42 caught). The survivor is an **equivalent
  mutant**: dropping the `handled` guard in the second pass re-yields triples the first
  pass already carried, into the same file, so the union is unchanged — the guard saves
  work and states intent rather than deciding anything.

  **For the tasks that come next:**
  - **E2's write order gains one step at the front:** `read_previous_files()` →
    `lifecycle.plan(...)` → `build(..., carried=plan.carried)` → manifest → `unchanged()` →
    report only if something moved → `write_all` → `registry.save()` once.
    `tools/build_fixture_instance.py` already does exactly this and is imported by the
    suite, so the sketch and the thing that verifies it stay one piece of code.
  - **E2 still owns the partial run, and it is now half solved.** `build()` refuses
    `--source X` as before, and the scope tests here drive `lifecycle.plan()` directly
    rather than a whole run. What E1 supplies is the missing half: every object outside the
    fetched scope comes back as a `CarriedNode`, which is the "merge the fetched subset with
    the previous state" option C1 named. What is left is objects owned by *both* the fetched
    source and another — the model holds them, rebuilt from one source's statements alone —
    and that is the case to decide before removing the guard.
  - **E2's stale-file deletion must not delete a file that only holds carried nodes.** A
    scheme deleted from its source produces a `concepts-<slug>.ttl` containing nothing but
    deprecated nodes, and that file is still output the run produced.
  - **F2 should call `MergeRegister.load()` and `.check_against(id_map)`** rather than
    re-deriving either, the same way B4 and C2 left their checks. A `LifecycleError` is an
    `IssueError`, so `cli.exit_code_for` already maps it to exit 1 with no new mapping.
  - **G1's `init` writes `mappings/merges.csv`** with its header (§5.7 step 3);
    `MergeRegister().save(root)` is there for exactly that, and nothing else writes the
    file. The fixture instance gained an empty one.
  - **C2's "removed is deliberately not reported" is now moot**, as its note predicted:
    nothing is removed, so there is no number to be wrong about.

- [x] **E2 · `semprini run` orchestration**
  **Spec:** §5.1 (pipeline and flags)
  **Deliver:** the full fetch → normalize → resolve → build → lifecycle → serialize →
  write sequence, with `--source` and `--dry-run`.
  **Verify:** on the fixture instance, two consecutive runs produce zero diff;
  `--dry-run` writes nothing (assert via filesystem snapshot); a mid-pipeline failure
  leaves `generated/` untouched rather than half-written.
  **Depends:** E1
  **Merged — [PR #12](https://github.com/JuhaKor/semprini/pull/12).**
  **Done.** 709 tests green (36 of them E2's, in `tests/test_run.py`); ruff, ruff format
  and mypy (strict) clean. Thirty-two mutations were checked against the suite — stale
  files never found, only the top level of `generated/` scanned, the report treated as
  stale, removing a stale file not counted as a change, the report written on every run,
  the manifest left out of the `unchanged()` comparison, a dry run saving the registry /
  writing the files / removing stale output, a partial run fetching every source, empty
  directories left behind, the previous state not rebased for a namespace move, the move
  writing the lock before the map, the move written before the run, a move combined with
  `--source`, a partial run rebuilding a shared object, a reference not required to be
  written, `plan_namespace_change` rebasing nothing, the run reporting no sources, what was
  deprecated not reported, the merge register not read, the previous state not carried into
  the build, the run reading a clock of its own, everything rebased rather than only the
  old base, lifecycle judged against the fetched source alone, a partial run judged as a
  full one, plus the five the review's fixes brought with them (below) — and 31 of the 32
  fail it.

  **The survivor is recorded rather than covered**, because covering it would mean
  asserting about a corrupt instance. `_check_references_are_written` counts only the
  blocks that *describe* a node; loosening it to every block a node appears in changes the
  answer solely when the previous output held a `sem:relatesTo` shortcut whose subject has
  no defining block anywhere — and lifecycle carries forward every node the previous run
  described, so that state can only be reached by hand-editing `generated/`, which §6.1
  check 2 catches on its own. The narrower rule is what the error message claims, so it
  stays.

  **A note on running such a battery on Windows**, since it cost a false result before it
  cost a real one: the harness restored each file from text it re-read at the top of every
  iteration, so one restore that silently did not take became the next iteration's
  "original" and baked itself in — after which every later mutation was being tested
  against the wrong code, and reported 27/27. Read the pristine sources once, restore all
  of them after every iteration, assert the restore took, and check the working tree is
  clean at the end.

  **The three obligations C1 and C2 handed over are all closed.**
  - **Stale output is removed** (§4.3). Anything under `generated/` the run did not
    produce is deleted, nested files included, and `.report.md` is the one exemption —
    it is written only when something moved, so a run that produced no report has not
    stopped producing the committed one. **Deletion is safe on a partial run too**, which
    is what C1 could not assume: every out-of-scope object comes back from lifecycle as a
    carried node and so *is* produced, meaning a file that is not produced holds nothing
    the run kept. The case it actually catches is output whose partitioning changed —
    a scheme that became a taxonomy moves `concepts-x.ttl` to `taxonomy-x.ttl` — plus
    anything a person put there by hand.
  - **`build()`'s partial-run guard is gone**, replaced by the narrow refusal decided
    before the task started: an object the ID map records against **two** sources when
    only one was fetched. Everything else is assembled from the fetched model plus
    lifecycle's carried nodes. Nothing in v1 produces a cross-source object, so this costs
    an instance nothing today; the message says to run in full.
  - **Removing a stale file counts as a change**, which the handover note did not
    anticipate: a run can produce byte-identical files and still have deleted output, and
    comparing only what was produced would leave the committed report describing a
    directory that no longer exists. `unchanged()`'s docstring said "E2 owns it" and now
    says whose question it is and why the caller folds the answer in.

  **Decisions taken** (all implemented and now in the spec):
  - **Nothing is written until every stage has succeeded.** The whole pipeline —
    fetch, lifecycle, build, manifest, report — completes in memory, and the last four
    lines write. That is what makes `--dry-run` the same run minus its writes rather than
    a rehearsal, and it is why a failing compile leaves no state in which `generated/`
    describes one run and `mappings/` another. §5.1 says so now.
  - **`identity.force_namespace_change()` became `plan_namespace_change()` and no longer
    writes.** It wrote the map and lock immediately, which for a once-ever migration is
    the worst possible moment: a compile that then failed left an instance whose map had
    moved and whose output had not, and that state has **no way out** — a second
    `--force-namespace-change` is refused as a move to the base IRI already locked, and a
    plain run refuses the old IRIs still in the output. The run now saves both with its
    files, map before lock. B4 said the flag was "declared but not wired"; it is wired.
  - **A namespace move rebases the previous generated state** before lifecycle reads it.
    Without that every node already written is an IRI the ID map has never heard of, which
    §5.4 refuses — and if it did not, every deprecated node in the instance would be
    dropped, since a deprecated node exists nowhere else. Rebasing also keeps
    `dcterms:modified` still, so the commit is every IRI and no dates and the report shows
    nothing new and nothing changed: exactly the claim a reviewer of that commit has to be
    able to check. **The move cannot be combined with `--source`** — the commit would make
    two claims at once and the first could not be checked through the second.
  - **A cross-reference must point at a node the run writes**, not merely at an IRI the ID
    map holds. This is the "known limitation, deliberately left" C1 recorded, and the
    partial-run case it was waiting on turns out to *want* the strict rule: what makes it
    answerable is that both legitimate sources of a node are in hand once the blocks
    exist — the model, and the nodes lifecycle retained — so a reference to a deprecated
    object or to an out-of-scope one passes, while a row that outlived its node does not.
  - **`tools/build_fixture_instance.py` is now a thin caller of `run.run()`** with the
    date and both versions pinned. The stand-in and the command cannot drift, which
    matters because every other fixture-based test in the suite is evidence about whatever
    that tool executes. `test_the_fixture_instance_is_what_a_run_produces` pins both at
    once.
  - **`RunResult` is the return value, and the CLI only prints it.** Exit codes still come
    from `cli.exit_code_for` alone, so `IdentityError`/`BuildError`/`LifecycleError`/
    `ManifestError` all map to 1 with no new mapping — B4 and C2 both left "whoever wires
    the first command that reaches one owns this", and the answer is that `IssueError`
    already covered it. `SourceUnreachableError` is exit 3, asserted end to end.

  **A code review found four issues; all are fixed**, with a test and a mutation each. The
  first was a real defect that would have made the migration this task wired up impossible
  to perform, and it is worth remembering why nothing caught it:
  - **The namespace move left `mappings/merges.csv` behind.** The ID map and the previous
    generated state were rebased; the merge register was not, so every row still named the
    old base, `MergeRegister.check_against()` found none of those IRIs in the moved map,
    and the run refused itself. Nothing was corrupted — the refusal happens before any
    write — but the once-ever migration could not be performed at all on an instance that
    had ever recorded a merge, which is any instance old enough to need one. The fixture's
    register is *empty*, which is exactly why six passing move tests said nothing about it:
    **an empty file is not a fixture, it is an absent one**. `MergeRegister.rebased()` now
    exists and the move writes the register back — the only circumstance in which a compile
    writes that file, and `test_an_ordinary_run_never_writes_the_merge_register` pins the
    other half.
  - **`MergeConflictError` escaped as a traceback.** It subclasses plain `ValueError`, not
    `IssueError`, so the CLI's handler did not catch it and two sources disagreeing about
    an object would have printed a stack trace instead of exit 1 with a message. Only a
    third-party adapter can reach it today (neither bundled one stamps another source's ref
    onto its objects), which is precisely why it would have been found by an adopter rather
    than by us. `SourceConflictError` now wraps it at the fetch loop, naming the source
    being merged in — the same thing the Ellie adapter already does at its own boundary.
  - **One broken cross-reference was reported twice.** A relationship's ends are resolved
    on two paths — once for the statement, once to key the `sem:relatesTo` shortcut by
    entity pair — and both recorded a reference. Deduplicated; the issue list is read in CI,
    where one problem shown as two costs someone a search for the second.
  - **Stale removal sat between `write_all()` and `registry.save()`.** A failure while
    deleting — a locked file, a read-only directory — would have left `generated/` holding
    IRIs the ID map did not, which the next run refuses and only deleting `generated/`
    recovers from. Identity is now saved immediately after the files it describes, and the
    deletion, which has nothing to do with identity, goes last.

  **Notes for later sessions:**
  - **`.report.md` is not a function of the instance's inputs**, and `tests/test_run.py`
    has a `governed()` helper that excludes it from whole-instance comparisons for that
    reason. An instance compiled from scratch and the same instance compiled incrementally
    hold identical Turtle, manifest and ID map, and different prose — the report describes
    a *run*, and the committed one describes the run that last changed the fixture.
  - **A stale `.ttl` file is read as previous state before it is judged stale.** If it
    holds subjects the ID map knows, lifecycle carries them forward and the file is
    reproduced rather than deleted; if it holds subjects the map does not, the run is
    refused (§5.4). So deletion reaches exactly the files that carry nothing — which is
    correct, and worth knowing before someone "fixes" the order.
  - **F2 gets its exit-1 mapping for free** and should still call `Manifest.verify()`,
    `check_versions()`, `IdMap.check_append_only()` and `MergeRegister.check_against()`
    rather than re-deriving them.
  - **G2's workflow templates now have a command to call**: `semprini run` for the compile
    workflow, and its report is `generated/.report.md` (§6.2). The compile job needs the
    package installed — a manifest is refused from a source tree — and nothing in the YAML
    needs to know any of the above (§6.3).

---

## Phase F — Validation

- [ ] **F1 · Core SHACL shapes**
  **Spec:** §6.1.5
  **Deliver:** `src/semprini/shapes/` covering every constraint listed, with the
  missing-definition rule as a warning.
  **Verify:** each constraint has a conforming and a violating fixture; the fixture
  instance conforms; warnings do not fail the run.
  **Depends:** D2
  **F1 owns the `skos:broader` cycle rule, and nothing before it can.** D3 refuses an
  entity that is its own supertype, which is a cycle of one; a cycle of two or more is
  currently emitted into `generated/` unnoticed. An adapter cannot catch it — it sees one
  source, and inheritance drawn across two of them closes a loop neither one holds — so
  the check has to run on the merged graph. Cover both hierarchies: taxonomy values and
  entities, which §6.1.5 now says may both carry `skos:broader`.

- [ ] **F2 · `semprini check` pipeline**
  **Spec:** §6.1 items 1–7
  **Deliver:** the full check sequence, including the version-drift check (§7) and the
  determinism re-serialization check.
  **Verify:** the fixture instance passes; a purpose-built failing fixture exists for
  **each** of the seven checks, each producing the documented exit code; drift is
  detected when the manifest's recorded version differs from the running one.
  **Depends:** E2, F1
  **Call the checks, do not re-derive them.** `IdMap.check_append_only` and
  `check_sources_are_configured` (B4), `Manifest.verify` and `check_versions` (C2), and
  `MergeRegister.load(...).check_against(id_map)` (E1) each return `Issue`s or raise an
  `IssueError` the CLI already maps. Getting the base revision out of git is the one part
  of check 6 nothing implements yet.

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
  **Step 3's empty `merges.csv`** is `lifecycle.MergeRegister().save(root)` — the one
  writer of that file, since every row in it is a steward's decision (E1). A missing file
  is a legal empty register, so this is about the tree matching §4.2, not about a run
  failing without it.

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
  **Also:** every previously released ontology version must keep resolving at
  `/ontology/X.Y.Z/` — see A2's known gap. The site build currently publishes only the
  current version, so a bump would 404 a path w3id promises is permanent. Verify by
  publishing a second ontology version and confirming the first still resolves.
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
| ~~1~~ | ~~w3id namespace registration~~ — **resolved:** PR #6488 merged, `https://w3id.org/semprini/ontology` live and verified | ~~A2~~; nothing now. G5 must still keep every released `/ontology/X.Y.Z/` resolving |
| 2 | Confirm Apache-2.0 / CC BY 4.0 | A1 (the licence files are written there) |
| 3 | Distribution channel | G5 |
| 4 | Which adapters ship bundled | ~~D3~~ (Ellie and Excel are both bundled and registered); G4 |
| ~~5~~ | ~~Default language tag(s)~~ — **resolved in B3:** one per instance, applied only where a label carries no tag of its own | ~~B3~~; C1 applies it |
| 6 | When missing-definition becomes blocking | per instance; H1 |
| ~~7~~ | ~~Ellie pagination and rate limits~~ — **resolved by scope:** the adapter reads exported files, so v1 makes no API call | ~~D3~~; whoever builds the API mode |
| 8 | Whether `init` creates the remote repository | G1 |

## Sequencing notes

- ~~**A2 is submitted and now purely a waiting game.**~~ Done: the namespace is registered
  and live, and §11 #1 — the project's one blocking decision — is resolved. Phase A is
  complete. G5 inherits the one obligation A2 leaves behind: every released
  `/ontology/X.Y.Z/` must keep resolving.
- ~~**The compiler now emits RDF.**~~ Done, and `generated/` is now machine-owned in
  practice rather than by convention: C2's manifest hashes every file the compiler writes
  and refuses to be written by an uninstalled one. Phase C is complete.
- ~~**D1 next.**~~ Done: the plane now has a plugin interface, discovery that imports
  nothing, and a contract an outside author can run against their own adapter.
- ~~**D2 next.**~~ Done, and the loop is closed: a committed synthetic instance compiles
  from a workbook to Turtle and recompiles to the same bytes, minting nothing. Both
  switches D1 left off are on — `excel-taxonomy` is a registered entry point, so the
  unknown-adapter check judges real names, and `tests/fixtures/acme/` is a complete
  instance.
- ~~**D3 next.**~~ Done, and **Phase D is complete**: both bundled adapters exist, the
  fixture instance compiles two sources whose objects reference each other, and v1 needs
  no network access or credential to compile anything. §11 #7 is resolved by scope and
  #4 is settled for the bundled pair.
- ~~**E1 next.**~~ Done: an object can no longer leave an instance. What a source deletes
  is retained and marked deprecated, what a partial run did not look at is carried
  untouched, and a steward's merge register turns a bare deprecation into one that names
  the survivor. **E2 next**, and it is now genuinely only orchestration: the pipeline is
  complete end to end in `tools/build_fixture_instance.py`, and what is left is the CLI
  around it, stale-file deletion, and the one partial-run case E1 left open.
- ~~**B1 before everything downstream.**~~ Done. Determinism could not be retrofitted:
  once an instance holds generated files, every serializer change becomes a migration
  (§7). It now is one — a change to `serialize.py`'s output is a major bump.
- **F3, G3 and D3 are the three tasks most likely to overrun.** Each has a genuinely
  hard core — defining "additive only", proving migrations preserve identity, and
  an external API's real behaviour versus its documentation.

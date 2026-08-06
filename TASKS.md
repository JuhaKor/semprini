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
  **Status — reviewed, fixed, and open as
  [PR #4](https://github.com/JuhaKor/semprini/pull/4).** Merge is the one step left.
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
  **Two obligations C1 hands over, both found in its review:**
  1. **Stale files are never removed.** `build.write_all()` writes the files a run
     produces and touches nothing else, so a scheme that disappears from its source leaves
     `concepts-<slug>.ttl` in the instance for ever — its objects stay in the committed
     output, `read_previous()` unions them back in, and C2's manifest check will find a
     file it did not write. §4.3 says `generated/` is "overwritten wholesale", so the spec
     is right and the implementation is short. Deleting correctly needs the run's scope,
     which is why it is here and not in C1: a `--source X` run must **not** delete the
     files it did not regenerate, and E1 decides whether a vanished scheme's objects are
     deprecated (and so still emitted) rather than dropped.
  2. **`build()` refuses a partial run outright** — `BuildError` when
     `context.only_source` is set. `write_all` rewrites each file whole, so building from
     one source's objects would delete every other source's statements from the files it
     touched and refresh `dcterms:modified` on every node they co-describe. Removing that
     guard is E2's first step, and it must be replaced by a real answer: either merge the
     fetched subset with the previous state before building, or make writing per-file.

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
| 4 | Which adapters ship bundled | D3, G4 |
| ~~5~~ | ~~Default language tag(s)~~ — **resolved in B3:** one per instance, applied only where a label carries no tag of its own | ~~B3~~; C1 applies it |
| 6 | When missing-definition becomes blocking | per instance; H1 |
| 7 | Ellie pagination and rate limits | D3 |
| 8 | Whether `init` creates the remote repository | G1 |

## Sequencing notes

- ~~**A2 is submitted and now purely a waiting game.**~~ Done: the namespace is registered
  and live, and §11 #1 — the project's one blocking decision — is resolved. Phase A is
  complete. G5 inherits the one obligation A2 leaves behind: every released
  `/ontology/X.Y.Z/` must keep resolving.
- **The compiler now emits RDF.** C1 done means the first output an instance would commit
  exists and is pinned by golden files, so from here every task changes bytes somebody
  could already be governing. **C2 next**: the manifest is what makes `generated/`
  machine-owned in practice rather than by convention (§4.3), and D2 and E2 both wait on
  it.
- ~~**B1 before everything downstream.**~~ Done. Determinism could not be retrofitted:
  once an instance holds generated files, every serializer change becomes a migration
  (§7). It now is one — a change to `serialize.py`'s output is a major bump.
- **F3, G3 and D3 are the three tasks most likely to overrun.** Each has a genuinely
  hard core — defining "additive only", proving migrations preserve identity, and
  an external API's real behaviour versus its documentation.

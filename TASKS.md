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

- [x] **F1 · Core SHACL shapes**
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
  **Merged — [PR #13](https://github.com/JuhaKor/semprini/pull/13).**

  **Done.** 792 tests green (83 of them F1's); ruff, ruff format and mypy (strict) clean;
  the shapes ship inside the wheel, and `core_shapes()` loads them from a bare venv
  install with no source tree present. Fifty-three mutations were checked against the
  suite — `sh:uniqueLang` dropped, an untagged label or definition tolerated, a label,
  status, membership, scheme type or attribute owner made optional, any status or scheme
  type value accepted, two statuses tolerated, schemes exempted from the node rules, an
  undeclared scheme accepted, `sem:enumerates` pointing anywhere, the missing-definition
  rule made blocking, relationships asked for definitions, an attribute owned by two
  entities or by a non-entity, either relationship end unchecked, an entity specializing
  anything, a taxonomy hierarchy crossing schemes, attributes and relationships forming
  hierarchies, only a self-loop counted as a cycle, notations compared globally instead of
  per scheme or not at all, a notation as prose, active nodes hanging off deprecated ones,
  the taxonomy target selecting by class alone, advanced features off, warnings treated as
  errors and the reverse, the core shapes judging overlays, the overlay rules judging
  `generated/`, the overlay or local shapes never applied, local shapes seeing one graph,
  overlays read non-recursively, an unreadable overlay skipped, inference materialized
  into the validated graph, results unsorted or undeduplicated, one message taken instead
  of all, the IRI policy skipped, its patterns unanchored, and schemes given a UUID — and
  each fails it. **Three survived the first run and each was a real hole in the tests, not
  a harmless mutation**: nothing exercised a node carrying two `rdf:type`s (so the
  taxonomy target's filters were untested), the local-shape test used `sh:targetNode`,
  which selects a node whether or not the data mentions it and so proved nothing about
  which graphs are validated, and every IRI-policy test called the shapes directly rather
  than through `check_shapes`, which therefore did not have to apply them.

  **A fourth was caught only by running the battery twice**, and it generalizes: the
  ordering mutation passed one run and failed the next. Issues are collected in a set, so
  an in-process assertion that three of them come out sorted passes by luck one time in
  six — the test *looked* like it pinned the order while mostly agreeing with chance.
  Ordering is now asserted across three subprocesses with different `PYTHONHASHSEED`s,
  which is what C2 established for choosing among rdflib's objects and is the only way to
  test a promise about hashing. **A mutation battery that runs once tells you less than it
  appears to** wherever a set is involved.

  **A review round found five things, and four of them were worth fixing.** Recorded
  because three are traps a later task can walk into again:
  - **`sem:BusinessTerm` fell through every hierarchy rule** — not in the entity rule, not
    a taxonomy value, not in the flat list — so a glossary term could be `skos:broader`
    than a scheme. Nothing emits business terms yet, which is exactly why it would have
    gone unnoticed until a glossary adapter landed. Refused now: relaxing this when that
    adapter arrives is additive, tightening later would refuse committed content. **Every
    class-by-class list in the shapes is a place the fifth class can be forgotten.**
  - **A validator re-parses a `sh:sparql` constraint once per focus node**, so the cost of
    a SPARQL rule is the length of its *text*, not the work its query does. The taxonomy
    rule cost ~17 ms per value and was 63% of check 5 on a 2 000-value taxonomy; the same
    query as a `sh:SPARQLTarget` is parsed once for the whole graph. The two SPARQL rules
    now select the offending nodes in a target and forbid the `skos:broader` they were
    selected for, which took check 5 on 2 000 values from 54 s to 15 s. Same verdicts,
    pinned by the cross-scheme, non-concept-parent and three cycle-length tests.
    **Prefer a target to a per-node constraint whenever the rule can be phrased either
    way**; per-node SPARQL is a per-node parse.
  - **A deep `skos:broader` chain crashed the run** rather than reporting: rdflib walks
    `broader+` recursively, and around a thousand links it raises `RecursionError` out of
    the one rule that exists to catch hierarchies gone wrong. `shacl()` now names the
    depth as the finding, and §6.1.5 says so.
  - **The issue order was not total.** Sorting by location and message left a pair tied
    when only severity differed — reachable as soon as a local shape restates a core rule
    more leniently — and issues are collected in sets, so the pair came out by hashing.
    `Issue.sort_key` now carries all three fields, alongside the `sort_key` properties
    `Text` and `SemanticObject` already have, and is where F2 should sort from. Note the
    testing shape of this: the deterministic test is in `test_model.py` against the key
    itself, because a test that sorts a real pair of issues passes half the time by luck.
  - Not fixed: the reviewer read `Kind.ENTITY`'s IRI message as ungrammatical (`a entity`,
    `a taxonomy-value`). True, and the fix was not a better article but a written-out
    phrase per rule — the `c:` rule covers entities, attributes *and* business terms, and
    naming only the first sends an operator to the wrong rule.

  **The one decision everything else follows from: the core shapes judge `generated/`
  alone.** §6.1.5 said which constraints to check but not what to check them against, and
  the obvious reading — the union a consumer loads — is wrong. `overlays/external/` holds
  curated subsets of standard vocabularies (§4.2): SKOS concepts with no `sem:status`, no
  scheme of this instance's and nobody to deprecate them. Judging those against the
  compiler's own guarantees would report dozens of violations at an organization for using
  overlays exactly as the layout invites. So there are three graphs and three shape sets —
  core over `generated/`, the overlay rules over `overlays/` alone (which file a statement
  came from is the whole question, and their union no longer knows), local shapes over
  both, since an organization's rules are about an organization's whole graph. §6.1.5 now
  says all of this, and §4.3's "validated against the same core shapes" line, which said
  the opposite, is corrected.

  Decisions, for later sessions:
  - **API, for F2:** `check_shapes(repo_root, *, base_iri) -> tuple[Issue, ...]` is check 5
    end to end. It returns issues and raises only when a *file* cannot be read
    (`ValidationError`, an `IssueError`, so exit 1 is already mapped). Warnings come back
    as `Severity.WARNING` and blocking is F2's decision, not this module's. The parts are
    public too — `core_shapes()`, `instance_shapes(base_iri)`, `overlay_shapes(base_iri)`,
    `read_overlays()`, `read_local_shapes()`, `shacl(data, shapes)` — so F3 can ask what
    the core shapes constrain without re-parsing them.
  - **Shape IRIs live in `https://w3id.org/semprini/shapes#`**, the path A2's catch-all
    already reserves. Not `sem:`: that namespace resolves to the metamodel document and
    A3 fixed its inventory, so a shape IRI there would be a published term the ontology
    does not declare. A test refuses any shape subject under `sem:`.
  - **The shapes require SHACL advanced features**, and `shacl()` is the one call site
    that passes `advanced=True`. A taxonomy value is a plain `skos:Concept` (§3.2), so it
    is selected by a SPARQL target rather than `sh:targetClass`: every `sem:` class is a
    `skos:Concept`, so the class-based form starts matching entities the moment anyone
    loads `sem.ttl` beside the data or turns on an RDFS reasoner — and the taxonomy rules
    would then be enforced on inheritance they were never written for.
    `test_the_shapes_do_not_depend_on_the_metamodel_being_loaded` pins it. The cost is
    that a third party running `pyshacl` without `-a` gets *fewer* violations rather than
    an error; the shapes README says so, and §6.3 makes `semprini check` the contract.
  - **`sh:in`, not a Python constant, for `sem:status` and `sem:schemeType`** — but the
    allowed values are `build.STATUS_ACTIVE`/`STATUS_DEPRECATED` and `SchemeType`, in a
    second file. Nothing yet stops those from drifting apart; the check that would catch
    it is the fixture instance conforming, which is real but indirect.
  - **`UUID_PATTERN` (identity) and `SLUG_PATTERN` (config) are now public**, and
    `validate.LOCAL_NAME_PATTERNS` maps a `Kind` to one of them. The IRI policy is the
    other half of §3.4.2's minting rules — what a local name may *look like* against what
    `mint_local_name` *produces* — and `test_the_iri_policy_matches_what_identity_mints`
    runs every object of the shared sample model through both. Both patterns are written
    without `(?:` so they stay valid in the XPath regex dialect `sh:pattern` is defined
    against.
  - **Five constraints are wider than §6.1.5's list, and the spec now carries them all**:
    `sem:status` and `skos:prefLabel` are required on *every* node, schemes included (§3.5
    applies to every object, which C1 already implemented); labels and definitions must
    carry a language tag (§5.5 rule 6); a scheme needs exactly one `sem:schemeType` from
    the allowed pair and a `sem:enumerates` must name an entity (§3.3); a notation is
    untagged (§5.5 rule 6); and an attribute, relationship, business term or scheme
    carrying `skos:broader` is refused, since the metamodel has two hierarchies and no
    others.
  - **Check 5 is the slow one, and mostly not because of these shapes.** After the target
    rewrite, a 2 000-value taxonomy costs ~15 s, of which ~10 s is pyshacl evaluating
    ordinary core-SHACL property shapes — roughly 7 ms per node, linear in the graph. A
    50 000-concept taxonomy therefore puts check 5 in the minutes on every pull request.
    Nothing in the shapes will fix that; if it becomes a complaint, the lever is F2's
    (pyshacl options, or checking only what a PR changed), not another rewrite here.
  - **The fixture instance was left untouched** — it still has no `overlays/` or
    `shapes/local/`, and every overlay test writes into the throwaway copy the `instance`
    fixture makes. **G1's scaffold creates both directories**; a missing one is a legal
    empty graph here, not an error.
  - **`sem:sourceRef` is deliberately not required.** Nothing in §6.1.5 asks for it, and
    an overlay-declared `x:` term typed as a `sem:Entity` has no source to name.
  - **F3's job is untouched by this.** Local shapes are loaded and applied; nothing yet
    checks that one is additive, and a local shape that weakens a core constraint is
    silently obeyed today — the core shape still runs, so the effect is a shape that adds
    nothing rather than one that licenses anything, but the rejection §6.1.5 requires is
    still F3's to write.

- [x] **F2 · `semprini check` pipeline**
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
  **Merged — [PR #14](https://github.com/JuhaKor/semprini/pull/14).**

  **Done.** 846 tests green (55 of them F2's); ruff, ruff format and mypy (strict) clean;
  the wheel still installs into a bare venv with pip and `semprini check` passes there on
  the fixture instance, which check 7 newly depends on — it reads the packaged `sem.ttl`
  at run time.
  Thirty-eight mutations were checked against the suite, twice — syntax errors in
  `generated/` ignored, the ontology copy never parsed, overlays and local shapes not
  parsed, checks 4–7 answered from content that did not parse, a check that did not run
  counted as passed, warnings failing the command and errors not failing it, issues listed
  unsorted, manifest hashes never recomputed, an unreadable manifest ignored, version drift
  never checked, the namespace lock not verified, subjects not compared against the base
  IRI, the shapes never applied or applied to an empty graph, unconfigured source names
  tolerated, a generated subject missing from the ID map tolerated, the merge register
  never checked, the append-only comparison never made, the base taken as the branch tip,
  the repository path prefix ignored, a missing base revision reported as a pass, an
  unreadable base map treated as empty, a git failure escaping as a traceback, each of the
  three base-revision candidates not consulted, re-serialized bytes never compared, line
  endings translated on the way in, a graph the serializer refuses skipped silently, the
  ontology copy never compared and compared when it should not be, a skipped check losing
  its note when it also found something, `check` always exiting 0, printing nothing,
  ignoring `--base`, and output not surviving a narrow console — and each fails it.

  **Five survived the first run, and four were real holes in the tests**: nothing asserted
  that a *skipped* check is not a passing one; the lock test went through `main`, which
  verifies the lock when it loads configuration, so `check`'s own call was untested; no
  fixture had a damaged ID map at the *base* revision, where treating it as empty makes
  the comparison trivially pass; and the ordering test was in-process, which F1 had already
  written down as the way this exact assertion passes by luck.

  **The fifth survivor was a design defect the battery found rather than a test hole**, and
  it is worth remembering because it is self-concealing: `summary()` sorted the issues a
  second time, so removing the real sort in `_outcome` changed nothing anyone could
  observe. A guarantee enforced twice is a guarantee whose enforcement cannot be tested
  through the output that carries it. There is now one sort, where the outcome is built.

  Decisions, for later sessions:
  - **All seven checks live in `validate.py`**, which §4.1 already names as "SHACL +
    structural checks (6.1)". **API:** `check(settings, *, base=None, compiler=None,
    ontology=None) -> CheckResult`, with `CheckOutcome` per check carrying `issues` and
    `skipped`. The version arguments exist so a test can pin what the fixture instance's
    manifest records; production callers pass neither. `check_shapes` gained optional
    pre-parsed graphs, since four of the seven checks ask about the same bytes and an
    instance big enough for check 5 to be slow is one that feels four more parses.
  - **A check that could not run is never reported as one that passed.** `CheckOutcome`
    carries `skipped`, and the summary says "not run" with the reason. It does not fail the
    command — an instance with no git history is an ordinary instance — which is precisely
    why it has to be said out loud. A check can be both: check 6 answers three questions
    from the working tree and a fourth only from git, so findings and the skip note are
    printed together. The first version suppressed the note whenever there were findings,
    which made one state report two ways depending on unrelated failures.
  - **Check 1 gates checks 4–7, and nothing else.** Content that does not parse cannot be
    asked what those ask, and answering from the files that happened to load invents a
    second problem on top of the real one. Checks 2 and 3 still run: they are bytes and
    versions, and the operator learns everything the instance can be told in one round.
  - **The append-only comparison is the one thing outside the working tree.** `--base
    <rev>`, else `$GITHUB_BASE_REF`, else `origin/HEAD`, and always the **merge base** with
    `HEAD` rather than the branch tip — a tip comparison reports rows another pull request
    merged since this one forked as rows this change deleted. **There is deliberately no
    fallback guess at `main`**: a check that quietly measures the wrong branch is worse
    than one that says it measured nothing. `--base` is what makes this portable to GitLab
    or Azure DevOps (§6.3), and it is now in §5.1's CLI listing.
  - **G2 owns two things this implies.** `validate.yml` must check out enough history for a
    base revision to resolve — a single-commit checkout, several platforms' default,
    silently turns the append-only half off — and §6.2 now says so.
  - **G1 owes every instance a `.gitattributes` pinning `eol=lf`.** Found by a test failing
    on Windows, not by reading: a clone with `core.autocrlf=true` rewrites every generated
    file on checkout and check 7 correctly fails on content nobody touched. §4.2, §4.3 and
    §5.7 now say it, and `templates/instance/` has to carry it.
  - **`ontology.ttl` is compared against the packaged metamodel, not re-serialized** — it
    is copied verbatim (§4.2) and round-tripping it would strip the term comments that are
    the vocabulary's published documentation. Skipped when check 3 found the ontology
    version drifting, since the committed copy is then expected to differ.
  - **The CLI now prints through `cli._say`**, which replaces characters the stream cannot
    encode instead of raising. Not decoration: a SHACL message quotes the node it is about,
    a label is whatever a modeller typed, and a redirected stream on Windows still encodes
    as cp1252 — so an arrow in a relationship's verb or any CJK label would turn a report
    about someone's instance into a traceback about ours, on a *passing* check as readily
    as a failing one. The earlier suspicion that the shapes' own em dash was the trigger
    was wrong: cp1252 holds an em dash. The hazard is source-supplied text.
  - **"No collisions" (§6.1 check 6) is what loading the map already enforces** — a
    duplicate source ref, or one IRI recorded under two kinds, is refused by `IdMap.loads`.
    The stronger question, two *objects* resolving to one IRI, is answerable only over a
    fetched model (§5.4), and `check` does not fetch. Nothing more is needed here; a run
    asks it.
  - **F3 has its seam.** Local shapes are loaded and applied as check 5 (F1), and `check`
    changes nothing about that; the additive-only rejection still belongs to F3, which
    should report through the same `CheckOutcome` for check 5 rather than adding an eighth.

- [x] **F3 · Additive-only enforcement for local shapes**
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
  **Merged — [PR #15](https://github.com/JuhaKor/semprini/pull/15).**

  **Done.** 877 tests green (26 of them F3's); ruff, ruff format and mypy (strict) clean;
  the wheel still installs into a bare venv with pip and `semprini check` passes there on
  the fixture instance. Twenty-six mutations were checked against the suite, twice — a
  statement about a core IRI tolerated, only one of the two core namespaces protected
  (each way round), only the core IRIs that exist today protected rather than the
  namespaces, a core IRI refused in object position too, no-op constraints tolerated, only
  `sh:minCount` of the three caught, an ordinary cardinality refused, the relaxed path not
  named / chosen by rdflib iteration order / taken last in string order, a `sh:rule`
  tolerated, a core-shape reference tolerated, a refusal downgraded to a warning, refusals
  not reported at all, a refused file applied anyway, one refused file switching off every
  other file, refusals unsorted, a shape file keyed by name rather than by path, the local
  shapes read as one graph again, an unusable shapes graph escaping as a traceback, an
  unusable local shape swallowed, the file responsible not named, the files that do load
  left unvalidated when another one fails, and a library's newlines kept — and each fails
  it.

  **The battery's own guard earned its keep on the last run.** A test added after the
  first two rounds was failing, and a battery run against a failing baseline reports
  *every* mutation as caught — the one result it exists to be unable to fake. The harness
  now runs the unmutated suite first and refuses to start otherwise. Worth writing down
  because the failure is silent and looks like success.

  **The premise the task was written on turned out to be false, and that shaped
  everything.** SHACL validation is conjunctive: adding a shape can only ever add
  violations, so a local file *cannot* weaken a core constraint by being present, and the
  core shapes are a separate `shacl()` call over their own graph besides. Nothing an
  adopter writes in `shapes/local/` has ever licensed data the core shapes forbid. What
  they can do is reach back into what the plane defines and believe they have changed it.
  So the rule is about ownership and honesty rather than about safety, and it is four
  refusals — all in §6.1.5 now, since the spec's own wording named the wrong mechanism
  ("targets a `sem:` term and weakens a core constraint"): *targeting* `sem:Entity` is how
  every legitimate local rule says what it is about, and a test guards that it stays legal.
  1. **A statement whose subject is a core IRI** — the `sem:` namespace or
     `https://w3id.org/semprini/shapes#`. This is the one that matters: it catches
     `core.ttl` copied into `shapes/local/` and edited, which is what an adopter would
     actually try, along with `sem:Entity a sh:NodeShape` (SHACL's implicit class target,
     which turns a metamodel class into a shape) and `shp:Node sh:deactivated true`. Whole
     namespaces, not the inventory of the day, so the release that adds a term cannot
     break a file that claimed its IRI first.
  2. **A constraint parameter that constrains nothing** — `sh:minCount 0`,
     `sh:uniqueLang false`, `sh:closed false`. Each is a no-op in SHACL, so refusing it
     blocks no rule anyone meant, and each is precisely what "make the core rule optional"
     looks like written down.
  3. **`sh:rule`**, which derives triples into the graph being validated. Verified against
     pyshacl rather than assumed: a rule supplying `sem:status` makes a shape demanding
     `sem:status` pass on data that has none. It cannot reach the core check, but it lets
     a steward's own rules pass against statements no file in the instance holds.
  4. **A reference to a core shape, in any position**, which is the first thing an adopter
     tries after refusal 1 — see the crash below for why it is a refusal and not a hint.

  **A refused file's rules are not applied; the other files' still are.** Reporting a
  shape as forbidden and then obeying it would leave the verdict resting on a file the
  plane says it will not honour, and one steward's mistake must not switch off an
  organization's rules. Both halves are tested, and the first needed repairing: the
  refused file's rule originally had no target, so it would not have fired either way and
  the test asserted nothing.

  **A malformed local shape crashed `semprini check` with a traceback, and does not now.**
  Found by a test, not by reading: five of six ordinary mistakes in a hand-written shapes
  file — a property shape with no path, two paths on one, a reference to a shape that is
  not there, a pattern that is not a regex, a `sh:select` that is not a query — raise out
  of **three different libraries** (pyshacl, `re`, pyparsing), and check 1 has nothing to
  say about any of them because they parse perfectly well as Turtle. `shacl()` now catches
  broadly and the breadth is deliberate: an enumeration of exception types is a promise
  this project cannot keep about a validator evaluating arbitrary user-written SPARQL and
  regexes, and every gap in it is a traceback in an adopter's CI. §6.1.5 says so.

  Decisions, for later sessions:
  - **API:** `check_additive(files) -> tuple[Issue, ...]` and `read_local_shape_files()`,
    which returns one graph per file keyed by path from the instance root
    (`shapes/local/regions.ttl`). Local shapes are read per file rather than unioned
    because a shape is accepted or refused **as a file** — that is what a rejection names
    and what stops being applied. `read_local_shapes()` survives as their union.
    `check_shapes`'s `local` parameter is now that mapping rather than a `Graph`; **F2's
    handover note said `Graph | None` and this supersedes it.**
  - **The failure of a file that will not load is attributed by re-running.** A validator
    says "these shapes are broken" about the whole graph it was handed, in a message that
    often names nothing at all — the `sh:target` case names neither file nor shape. So the
    union is tried once and, only when it fails, each file is run alone to find which one
    is responsible; the files that do load are validated in that same pass, so one run
    still reports everything. Where every file loads alone and only their union does not —
    two files sharing a shape IRI, which is constructible and tested — the finding is
    reported against `shapes/local/` itself.
  - **Rejection is reported as check 5**, per F2's seam, not as an eighth check: it is a
    fact about the shapes that check applies. A test pins that no other check reports an
    error for it, since an instance told two checks failed goes looking for a second cause.
  - **Only an error refuses a file.** Every refusal is one today, so that filter changes
    nothing and no test can reach it — it is there because a rule added later at warning
    severity would otherwise silently switch off the file it is about. Recorded rather
    than removed, deliberately, and the comment says as much.
  - **The path a no-op constraint was written against is chosen with `min`, not
    `Graph.value`** — rdflib picks arbitrarily among several, and a property shape with
    two paths is malformed but perfectly possible to write. Note the assertion pinning
    this is the weaker kind: a `Graph.value` regression is caught only when hashing
    happens to offer the other path, so the `max` mutation is the one that catches it
    deterministically.
  - **A message names a term prefixed only for the two namespaces the plane owns**; a
    `skos:` path appears in full. Fine as it stands, but if these messages are ever
    widened, the display table is a second concern from `_CORE_NAMESPACES`, which decides
    the *rule*.
  - **G1's scaffold should create `shapes/local/` with a README** pointing at §6.1.5's
    four refusals: an adopter meets this rule when their file is rejected, which is the
    worst moment to first read about it. An absent directory remains a legal empty graph.

---

## Phase G — Distribution and operations

- [x] **G1 · Instance scaffold and `semprini init`**
  **Spec:** §4.2, §5.7
  **Deliver:** `templates/instance/` and the `init` command, all six steps.
  **Verify:** init into a temp directory then `semprini check` passes on the fresh, empty
  instance; re-running init where `namespace.lock` exists refuses; a socket guard
  asserts init makes **no** network calls; the generated tree matches §4.2 exactly.
  **Depends:** F2
  **Merged — [PR #16](https://github.com/JuhaKor/semprini/pull/16).**
  **Step 3's empty `merges.csv`** is `lifecycle.MergeRegister().save(root)` — the one
  writer of that file, since every row in it is a steward's decision (E1). A missing file
  is a legal empty register, so this is about the tree matching §4.2, not about a run
  failing without it.

  **Done.** 913 tests green (39 of them G1's); ruff, ruff format and mypy (strict) clean.
  The wheel was rebuilt and installed into a bare venv, and the whole task was verified
  *from that install* rather than from the source tree: `semprini init` creates the
  seventeen-file tree, `semprini check` reports seven checks passed on it, and a second
  `init` exits 2. Thirty-two mutations were checked against the suite, twice — an existing
  instance bootstrapped over, only the lock protected rather than every file beside it, a
  second bootstrap reported as an ordinary overwrite, the tree written as it is rendered,
  only the first bad argument reported, the base IRI judged by a looser rule than the
  serializer's, the instance id not held to the slug rule, any language tag accepted, a
  source tree allowed to bootstrap, an unresolved placeholder left in the file, the
  templates copied rather than rendered, a template read without translating its line
  endings, the instance written with CRLF, the files ordered by name rather than by path,
  the workflows not materialized / written outside `.github/` / installing the latest
  version rather than this one, a workflow template that is not valid YAML, a pull request
  opened with no report in it, `generated/` left for the first run to create, the ontology
  copy tidied up on the way through, the merge register omitted, the ID map created without
  its header, the lock dated from a clock rather than from its argument, the lock recording
  the compiler version as the ontology version, the frozen base IRI differing from the
  configured one, the target directory not created, a configured source written into a
  fresh instance, `--dir` and `--language` ignored, a refusal exiting 1, and `init`
  reporting itself unimplemented — and each fails it.

  **Two of those survived the first run, and both were the same mistake in the tests
  rather than in the code.** The pinned `TODAY` was set to the day the file was written, so
  a scaffold that ignored its injected date passed every assertion about it; and the
  compiler and ontology versions are both `0.1.0` today, so asserting the lock's
  `ontology_version` said nothing about *which* version it recorded. The date constant is
  now deliberately not today's, with a comment saying why, and a second test pins the lock
  with the two versions set to different numbers. Worth writing down because neither test
  looked weak: both asserted a specific value and both were right.

  **Review found four defects, all of them in the templates rather than in the scaffold —
  the files this repository's suite never executes.** Fixed in the same PR, and the lesson
  generalizes to every task that ships something into an instance: `compile.yml` failed on
  any week the compile changed nothing, because `create-pull-request` validates `body-path`
  before it looks for a commit and no report is written when nothing moved; `validate.yml`
  never ran on a compile pull request, since GitHub fires no `pull_request` event for one
  opened with `GITHUB_TOKEN`, so against the protected main `init` recommends its required
  check could never report; the config template told adopters to set `token_env`, which
  both bundled adapters refuse outright; and `### Ontology 0.1.0` had been dropped from the
  changelog. The first two are now a conditional pull request step and a `semprini check`
  step inside `compile.yml`, both written into §6.2. Final state: **918 tests green, 38
  mutations, all caught.**

  Decisions, for later sessions:
  - **Everything `init` materializes lives inside the package** — `src/semprini/templates/instance/`
    and `src/semprini/workflows/<platform>/` — not at the repository root where §4.1 put
    them. An adopter installs a wheel and never sees this repository, so a scaffold at the
    root is absent from the one place `init` runs; `ontology/sem.ttl` and `shapes/core.ttl`
    are inside the package for the same reason. Verified against a built wheel: poetry-core
    ships dotfiles and `.gitkeep`s in a package directory. **§4.1 now says this.**
  - **Workflows are held one directory per CI platform**, and `WORKFLOW_DIRS` maps the
    platform to the path its files go to. That is the whole GitHub-specific surface of the
    scaffold: **G2's GitLab or Azure port adds a directory and a line**, and touches nothing
    else. `WORKFLOW_PLATFORM` is the only reason `init` knows what GitHub is.
  - **Placeholders are `%%name%%`, not `{{ name }}`.** The workflow templates are full of
    GitHub's own `${{ ... }}` expressions; a colliding syntax would either eat one or make
    "is every placeholder resolved?" unanswerable. An unknown placeholder raises rather
    than passing through — a literal `%%og%%` in an adopter's README is traceable to
    nobody. A test asserts no `%%...%%` survives into a created instance.
  - **`init` writes `generated/`, and what it writes is exactly what a run would.**
    `test_a_run_straight_after_a_bootstrap_writes_nothing` is the strongest statement
    available about the scaffold and the one to keep: without it, an adopter's first
    scheduled compile opens a pull request fixing up files nobody edited, before they have
    configured a single source. It is also what makes `semprini check` green on an instance
    that has never compiled.
  - **Refusals are wider than §5.7's rule and are exit 2.** The lock is the case that
    matters and keeps its own message; every other file `init` would overwrite is refused
    too. `ScaffoldError` subclasses `ConfigError`: every way this command refuses is about
    the invocation or the directory it names, and it writes no content, so it can never
    produce a validation failure. **§5.7 now says all of this**, along with "nothing is
    written until every refusal has been made" — `create()` renders and checks, `write()`
    writes, and a test asserts the split rather than trusting it.
  - **`--language <tag>` is new, and is in §5.1's listing.** Unlike the base IRI it is not
    frozen, so it is a convenience rather than a decision; without it an organization whose
    vocabulary is not English tags every label `en` on its first run and changes them all
    on the second.
  - **A source tree cannot bootstrap an instance.** Checked in `scaffold` with a message
    naming the pin, ahead of `Manifest.create`'s identical refusal, which stays as the
    backstop. The consequence for **G5**: the release process is the first thing that can
    produce a bootstrappable install, and `semprini init` from a tagged release is already
    one of its verification steps.
  - **The instance README, the `overlays/` README and the `shapes/local/` README are
    content, not scaffolding.** The last of these is F3's handover, and names all four
    refusals plus the legal `sh:targetClass sem:Entity` form. **G4 should treat these three
    as part of the documentation it is auditing**, since they are what an adopter reads
    first and they are versioned with the compiler rather than with the docs site.
  - **Superseded by G2 (2026-08-14) — the action is being removed and the trade below was
    reversed.** The record of why it was made stands; read the rest of this bullet as
    history, not as the current shape of the file. `compile.yml` now opens its pull
    request with `git` plus `gh pr create`, §6.3 forbids a third-party action in a shipped
    workflow, and the `compile/<date>` line moves inside that step. The two review
    findings named below are unchanged and still the reason the conditional and the
    `semprini check` step exist.
  - **`compile.yml` uses `peter-evans/create-pull-request`** and one shell line computing
    the date for the `compile/<date>` branch §6.2 names. That date line is the only logic
    in either file, and **G2's mechanical §6.3 guard has to decide whether it passes** —
    it names a branch rather than checking anything, but a guard written as "install, run,
    open a PR, nothing else" will see it. The alternative, `gh pr create` in a `run:` block,
    is more logic in YAML and no third-party action; the trade was made for fewer lines,
    not for fewer dependencies. **Two more things for that guard to judge**, both added
    after review: the `if: hashFiles('generated/.report.md') != ''` guarding the pull
    request step, and a `semprini check --base ${{ github.sha }}` step before it. The first
    is unavoidable — create-pull-request validates `body-path` on every invocation, so
    without it the weeks where nothing changed are the weeks the job fails. The second is
    there because a pull request opened with `GITHUB_TOKEN` fires no `pull_request` event,
    so `validate.yml` never runs on a compile PR and its required check never reports; both
    go away for an instance that gives the action a PAT, and the file says so.
  - `semprini init` does **not** run `git init` and creates no remote (§11 #8, resolved).
    Both are printed as next steps, along with branch protection and the Actions setting
    that lets the scheduled compile open a pull request at all — which is the kind of thing
    an adopter discovers from a failing job three weeks later.

- [x] **G2 · Workflow templates and CI portability**
  **Spec:** §6.2, §6.3
  **Deliver:** `workflows/` templates for `compile.yml` and `validate.yml`, materialized
  by `init`.
  **Verify:** a test asserts each workflow contains no logic beyond installing the
  pinned version, invoking `semprini`, and (for compile) opening a PR — the mechanical guard
  on §6.3. Run both against a scratch instance repository on GitHub and confirm a compile
  PR body carries the run report.
  **Depends:** G1
  **Merged — [PR #17](https://github.com/JuhaKor/semprini/pull/17).**
  **G1 already delivered both files**, at `src/semprini/workflows/github/`, materialized
  into `.github/workflows/` and pinned to the plane version — inside the package, since a
  scaffold at the repository root is absent from the wheel `init` runs from. What is left
  is the third-party dependency below, the §6.3 guard, and the run against a real
  instance.

  **Decided before starting (2026-08-14), and both are already in §6.2/§6.3:**
  - **`peter-evans/create-pull-request` goes; the PR step becomes `git` plus
    `gh pr create`.** It is the only non-`actions/` dependency anywhere in the project, it
    ships into every instance `init` creates, and it runs there with `contents: write` on
    that organization's knowledge graph — pinned to `@v7`, a moving tag, so its code can
    change without a diff anyone reviews. That is the one thing this design refuses
    everywhere else, and pinning to a commit SHA would have kept the line count while
    still running someone else's code. The cost is real and was G1's reason for choosing
    the action: the step grows to roughly fifteen lines of shell. **§6.3 now states the
    rule** — the PR step uses the platform's own CLI and a workflow may contain no other
    logic — so the guard below enforces something written down rather than something
    inferred. Three of those lines are not obvious and each has a reason: `git commit`
    exits non-zero with nothing staged, `--force` on the push and a `gh pr list` check
    cover dispatching the workflow twice in one day, and a runner has no default
    `user.email`. §6.2 gained the empty-staging-area case.
  - **The guard is not "no multi-line `run:` blocks".** That rule was available while the
    action existed and is not any more. It becomes: exactly one PR-opening step, invoking
    nothing but `git` and `gh` — no Python, no RDF, no second tool, no reading of
    `generated/` beyond handing the report path to `gh` — and every other step is
    checkout, setup-python, a pinned `pip install`, or a `semprini` subcommand. G1's
    question about the `compile/<date>` shell line answers itself: it moves inside the PR
    step, where it belongs.
  - **A container is the wrong test, and is replaced by a scratch instance repository.**
    Every defect G1's review found in these files was a GitHub *runtime* behaviour, not a
    shell bug — a `GITHUB_TOKEN`-opened PR firing no `pull_request` event cannot be
    reproduced under `act` at all, which mocks both the token and the event model. The
    move to `gh pr create` adds more of exactly that surface: real API auth, the
    `permissions:` block, and the repository setting **"Allow GitHub Actions to create and
    approve pull requests"**, which is off by default and fails the step no matter how
    correct the YAML is — the kind of thing G1 noted an adopter discovers from a failing
    job three weeks later. It also puts a report through a real PR body, which C2 escapes
    pipes and newlines for and which nothing has ever checked.
    `juhakor/semprini-scratch-instance` **exists and has that setting on.**

  **One deviation the scratch run cannot avoid:** `pip install semprini==%%version%%`
  fails, because nothing is published and the channel is still open (§11 #3, G5). The
  scratch instance substitutes `pip install git+https://github.com/JuhaKor/semprini@<sha>`
  — one line, pinned, no logic, so the guard still passes against it — and the real line
  stays untested until **G5**. Say so in the task report rather than implying it was
  covered.

  **Decided: GitHub only, and no second platform directory ships in v1.** The seam is
  `scaffold.WORKFLOW_DIRS` and a port costs one line plus a directory, but a port that
  cannot be run against a real instance is untested template text, and §6.3's portability
  claim is about the *cost* of porting — which the seam and the guard demonstrate without
  a second directory existing. The first adopter on another platform contributes one.
  **§6.3 now says this**, so an adopter reading the spec finds out before looking for a
  `gitlab/` that is not there. G2 therefore adds no platform: `WORKFLOW_DIRS` and
  `WORKFLOW_PLATFORM` are untouched.

  **Done.** 947 tests green (29 of them the guard's); ruff, ruff format and mypy (strict) clean.
  Twenty-two mutations were checked against the suite, twice — a third-party action back in
  a shipped workflow, an action floating on a branch rather than a pinned major, a second
  tool reading `generated/` in the pull request step, a python one-liner deciding whether to
  propose, a step that neither installs the plane nor invokes it, a push straight to main,
  a push to main hidden behind a shell keyword, an empty staging area left to fail, a second
  dispatch in one day left to fail on the push, a second pull request requested for a branch
  that already has one, a failed pull request query read as there being none, a commit
  attempted with no committer identity, a shell syntax error, and nine against the guard's
  own shell reader — and each fails it.
  - **`compile.yml` now opens its pull request with `git` and `gh`**, in one step of roughly
    twenty lines. `peter-evans/create-pull-request` is gone, and with it the project's only
    dependency on a repository nobody here controls. Three of those lines exist for what the
    action did invisibly, and each has both a test and a mutation: an empty staging area
    (`git diff --cached --quiet`), a runner with no committer identity (`git config user.*`),
    and a workflow dispatched twice in one day, which meets its own branch and its own open
    pull request (`git push --force` plus a `gh pr list` check).
  - **The §6.3 guard is `tests/test_workflows.py`**, and it reads the shipped templates
    rather than a bootstrapped instance — so a platform directory added by a later port is
    guarded by the fact of existing. `PLATFORM_CLI` there is the second half of
    `scaffold.WORKFLOW_DIRS`'s seam: a `gitlab/` directory must name `glab` or the guard
    fails, rather than silently being held to GitHub's CLI.
  - **The guard has its own tests, and they are the load-bearing ones.** It works by
    extracting every command word from a `run:` block, and an extractor that quietly
    returned nothing would pass every workflow ever written while looking identical from the
    test names. `test_the_guard_sees_the_command_in` pins the ways a second tool could reach
    a runner without being the first word on a line — inside `$(...)`, inside double quotes,
    after `&&`, past a line continuation — and the two ways the guard could report a command
    nobody wrote, which is what would get it worked around later. Seven of the eighteen
    mutations are aimed there.
  - **`bash -n` parses the pull request step in the suite.** This is the one place in the
    project where shell ships to somebody else, nothing here executes it, and an adopter
    meets a missing `fi` as a red job weeks later. The test skips where no shell is
    installed, which is worth knowing before reading a survivor in that battery.
  - **Two spec edits**, both because the code now enforces them: §6.3 admits `date` in the
    pull-request step — the `compile/<date>` branch name of §6.2 requires one and no CI
    platform provides it — and says the rule is mechanically enforced by the plane's suite;
    §6.2 gained the dispatched-twice-in-one-day case beside the empty-staging-area one.
  - G1's battery had one anchor in `compile.yml` (`body-path:`) and it was updated in the
    same change; both batteries are green.

  **Review found six issues; all are fixed**, with a test and a mutation each. Two were in
  the guard itself, which is worse than a defect in the workflow would have been — a guard
  that passes everything looks exactly like one that works:
  - **A push to `main` behind any shell keyword was invisible.** The protected-branch test
    read a segment's raw words while the command extractor stepped over keywords and
    assignments, so `if ...; then git push --force origin HEAD:main; fi` produced a segment
    beginning `then`: the assertion skipped it, and the allowlist test saw only `git`. Both
    readers now go through one `invocation()`. Two readers of the same text, one of which
    normalizes it, was one reader too many.
  - **Backtick command substitution was a fourth way in.** The module enumerated the ways a
    second tool could reach a runner without being the first word on a line, and listed
    three; `` git commit -m `curl ...` `` reported only `git`.

  The rest were narrower. The action pattern accepted only `@vN`, so pinning to a commit
  SHA — the stronger pin, and the answer to the moving-tag problem that removed the
  third-party action in the first place — would have failed the rule meant to encourage it.
  `gh pr list` was tested inline inside `[ -z ... ]`, where `set -e` cannot see it fail, so
  an API blip read as "no pull request is open" and would have been answered with a
  duplicate `gh pr create`; the query is captured on its own line now. And two comments
  claimed more than they delivered: `if: hashFiles('generated/.report.md')` stops doing
  anything once the first compile pull request merges — the report is a tracked file from
  then on, and the empty-staging check is what keeps the quiet weeks green — and the force
  push silently discards a commit a steward pushed onto a compile branch by hand. Both now
  say so, and `compile.yml` gained a `concurrency:` group, since two runs racing for one
  dated branch would force-push over each other.

  **The scratch instance run — done, on `JuhaKor/semprini-scratch-instance`.** *(That
  repository has since been reset: it is private again and holds one commit, a fresh
  instance pinned to `66ea15e`, with the ruleset dormant and the Actions setting still on.
  Nothing in it is evidence — this entry is. **G5 and H1 can reuse it**; re-point the
  install line at a current sha, or at the published version once there is one.)*
  Bootstrapped by `semprini init` from this branch's wheel, with the two synthetic sources of
  `tests/fixtures/acme/` and the pinned `pip install semprini==0.1.0` substituted for
  `pip install git+https://github.com/JuhaKor/semprini@710777a`, since nothing is published
  yet (§11 #3). **The real install line therefore remains untested until G5** — say so, do
  not imply it was covered. The guard was run against the substituted files as well, since
  the claim that the substitution keeps them legal is about a file this suite never sees.
  What the runner established that no test here can:
  1. **The pull request opens, and its body is the report byte for byte** — 2787 bytes,
     compared against `generated/.report.md` on the branch. C2's pipe and newline escaping
     survives a real pull request body, which nothing had ever checked. The first compile
     proposed 46 new nodes across three Turtle files plus the ID map.
  2. **A `permissions:` block escalates over a read-only default.** The repository's
     `default_workflow_permissions` is `read`; the workflow asks for `contents: write` and
     `pull-requests: write` and gets them, so an adopter does not have to change that
     setting. The one they do have to change is
     `can_approve_pull_request_reviews`, which `init` already prints.
  3. **The re-dispatch path works as designed.** A second dispatch the same day force-pushed
     (`+ d70c4dd...773c8b8 (forced update)`) and found the open pull request, so it updated
     it in place and asked for no second one.
  4. **A no-op compile is green and silent.** After merging the first pull request, a third
     dispatch changed nothing, exited at the empty staging area and opened nothing — the
     case that was *red* before G1's review. It also confirmed this task's own finding 5:
     the step was **not** skipped, because `generated/.report.md` is a committed file from
     the first merge onward, so `if: hashFiles(...)` is true and the staging check is the
     only thing keeping quiet weeks green.
  5. **Check 6 resolves on the default shallow checkout.** `semprini check --base
     ${{ github.sha }}` inside `compile.yml` reported `6. identity: ok` rather than "not
     run", so only `validate.yml` needs `fetch-depth: 0`.
  6. **The output is byte-identical across platforms.** The runner's `generated/` was
     recompiled on this Windows machine and `git status` came back empty — §5.5 rule 5's
     claim, checked end to end for the first time. And 3.12, the supported floor, is what
     the runner used; this machine has only 3.14.

  **One spec claim was wrong, and the scratch run is what caught it.** §6.2, `compile.yml`'s
  comment, the CHANGELOG and a test docstring all said GitHub *fires no `pull_request`
  event* for a pull request its own token opened. It does fire one: the run is created with
  actor `github-actions[bot]` and parked, `conclusion: action_required`, with **no jobs** —
  run `32021357478` on the scratch instance. The conclusion built on it is unchanged and
  better supported: `validate.yml` does not report on a compile pull request, so
  `compile.yml` validates before it proposes. But what a steward sees on that pull request
  is a check that is **pending**, not one that is missing, and all four places now say so.
  **Now measured, on a protected main.** The scratch instance was made public (branch
  protection is not available on a private repository on this account) and given a ruleset:
  pull requests required, `check` from `validate.yml` required, zero approvals. Then, in
  order: a steward-style source edit on a branch went `BLOCKED` → `CLEAN` when its check
  passed, which is the control case; a compile pull request opened by the workflow
  (`#3`) came up with **an empty check rollup — zero check runs on the head commit** and
  `mergeable_state: blocked`, so the parked run contributes nothing and the PR cannot be
  merged; approving that run (`POST /actions/runs/<id>/approve`, or the Actions tab) made it
  execute, pass, and the PR went `CLEAN`. So **on a protected main every compile pull
  request costs one click**, and that is now in §6.2, in the workflow comment, in the
  CHANGELOG and — the place a steward will actually meet it — in the instance README, which
  says what to do and that `compile.yml` has already run the same check on the same files,
  so the approval is a click rather than a judgement. The escape is a PAT or app token on
  the pull-request step, which is written down in all four.

  **What that sequence is really evidence for:** the inference held, and it was still right
  to refuse to write it down. The mechanism it would have been written on top of — "no
  event fires" — was wrong, and a spec sentence explaining a real behaviour by a wrong
  mechanism survives until someone acts on the explanation rather than the behaviour.

- [x] **G3 · Versioning, drift and migrations**
  **Spec:** §7
  **Deliver:** `src/semprini/migrate/`, the migration registry, and `semprini migrate --to`.
  **Verify:** a synthetic output-affecting change ships a migration that takes the
  fixture instance from vN to vN+1 deterministically; migrations never mint new IRIs for
  existing objects and never drop ID-map rows (asserted, not assumed); post-migration
  `semprini check` passes including drift.
  **Depends:** F2
  **Merged — [PR #18](https://github.com/JuhaKor/semprini/pull/18).** CI green on 3.12 and 3.14
  and on the wheel job; 3.12 is the supported floor and cannot be checked on the development
  machine, so the runner is the only place this package has been exercised on it.
  **Done.** 1015 tests green (61 of them G3's); ruff, ruff format and mypy (strict) clean; the
  wheel still installs into a bare venv with pip and `semprini migrate` runs from it. Forty-five
  mutations were checked against the suite, over two rounds — the snapshot taken after the steps
  rather than before, the snapshot holding the ID map itself rather than a copy of its rows, a
  minted IRI tolerated, a dropped node tolerated, a moved `dcterms:modified` tolerated, the date
  compared per file rather than over the union, the ID map not held to being append-only, an
  appended row tolerated, only the first violation reported, a file name escaping `generated/`,
  a file that is not Turtle, the ontology copy rewritten by a step, a serializer refusal escaping
  as a traceback, a step returning the wrong type, a step's exception escaping unnamed, steps run
  newest first, the already-applied step run again, a step beyond the target run anyway, two
  steps for one release resolved by taking one, a downgrade performed, versions compared as
  strings, any version string accepted, a step shipping with no summary, `--to` free to name any
  version, the manifest restamped with the old versions, an ontology version that moved alone
  read as nothing to do, no up-to-date case at all, `generated/` migrated without being checked
  against its manifest, the ontology copy left as the previous release wrote it, the report
  deleted as stale after being written, stale output left behind, the ID map not saved, no report
  written, the report treated as stale by whoever did not produce it, `generated/` scanned one
  level deep, and the ontology re-serialized rather than copied — and each fails it. The nine
  from review are listed with the findings below.

  **Two of those survived the first run, and both were real test gaps**, not battery noise.
  Nothing had constructed a step that **mutated the ID map it was handed** — the easier of the
  two ways past a naive comparison, since `IdMap.append` is public and the map has no removal
  method at all; and nothing had constructed an instance whose **ontology version alone** had
  drifted, which is the one drift no other command can clear. Both now have a test.

  **Review found six issues; all are fixed**, with a test and a mutation each (9 more mutations,
  45/45 now caught, and `tests/test_manifest.py` joined the battery's `TESTS`). Two are worth
  remembering:
  - **The drift message I had just improved could advise a command guaranteed to be refused.**
    Check 3's finding said `run semprini migrate --to <the running version>` unconditionally,
    but migrations only move forward. The reachable state is not exotic — it is the *procedure
    this task's own README section prescribes*: migrate, commit, and the pull request's CI still
    installs the old pinned version, so check 3 fires in reverse and tells the operator to
    migrate backwards, which exits 1. The advice now branches on which of the two versions is
    the newer, and an unorderable version gets the one sentence true either way rather than a
    guess dressed as an instruction. **A message is behaviour when it tells someone what to
    run** — and the previous wording, "recompile the instance", was at least executable in that
    state, so this was a regression introduced by an improvement.
  - **The write order made one crash unrecoverable, and only in this command.** `write_all`
    restamps the manifest, so a crash between it and `id_map.save()` left an instance already
    recording the new version — and the up-to-date test then answers "nothing to migrate" on the
    re-run, losing a step's ID-map edit silently. A compile has the same window and recovers,
    because a re-run re-derives everything from the sources; a migration has no equivalent. Fixed
    by writing the map **first**, which is safe here and is not for a compile: a compile writes
    files first because it mints, and `generated/` holding an IRI the map has never heard of is
    what that order exists to prevent. A migration mints nothing, so the hazard the order guards
    against cannot arise while the one it creates can.

  The rest were narrower, and three of them were claims that outran what the code enforced:
  nothing held a step to preserving ID-map row **order** — `check_append_only` looks rows up by
  ref and the new-row check is a set difference, so the same rows shuffled passed both and would
  have been saved as a rewritten identity registry, in the one command whose whole claim is a
  diff about nothing but the upgrade; the report asserted the rows were "none removed, rewritten
  or added" while the guards deliberately permit a `note` edit, so on the one occasion it
  mattered the committed, PR-facing report would have contradicted the diff beside it (it now
  counts and names them); the up-to-date test compared recorded ontology *versions* while check 7
  compares the copied metamodel as **bytes**, so a release that edited `sem.ttl` without moving
  its version would have left every instance failing the one check this command is the only cure
  for, with the command saying there was nothing to do; and `build.stale`'s docstring still said
  "one command passes it" after this task made it two. Version parsing moved to
  `semprini.version_parts()` in the process — the drift check needs the ordering too, and two
  answers to "does 0.10.0 come after 0.9.0" would have shown up in exactly one of the two places.

  **Decisions taken** (all implemented and now in the spec):
  - **A migration reads `generated/` and the ID map, never the sources.** That is what makes the
    diff provably about the upgrade: the command has no way to bring in a content change even
    when the release would also compile the sources differently. Two consequences are now
    written into §7, because both are the kind of thing that gets re-decided wrongly by whoever
    touches this next. *A migration is not a recompile* — the next scheduled compile reconciles
    content, in its own pull request. And **a recompile is not a migration**, which is the reason
    this module exists rather than being a convenience: a node no source reports any more is
    re-emitted verbatim from the previous run's file (§3.5), so a recompile carries its *old*
    statements forward — a term rename done by recompiling reaches every active node and misses
    every deprecated one.
  - **One version per step, and the range rule:** a step declares the release that introduced
    its change and runs when the instance was compiled with something older
    (`recorded < version <= target`). The alternative — a step declaring both ends of a hop —
    forces the shipped steps into an unbroken chain, and a patch release nobody wrote a step for
    then becomes a gap that stalls every adopter sitting on it. Under this rule a patch release
    costs nothing and an adopter three releases behind runs three steps in order.
  - **`--to` must be the installed compiler version.** Not a choice of how far to go: the steps
    live in the package, and the manifest records the release that wrote the files, so a partial
    migration has no version to record. Requiring the operator to name it is the point — a
    workflow that pinned one version and installed another is caught before a byte is rewritten.
    Downgrades are refused; steps are written in one direction only.
  - **A release that changes no output still has something to do.** With no step in range the
    command re-serializes the committed graphs, refreshes the copied metamodel and restamps the
    manifest — which clears the drift check without touching a source or a credential. Migrating
    an instance already current writes nothing, so a workflow may call it unconditionally.
  - **Four refusals, and they are the task.** §7's promise is about code a future release has not
    written, so it is checked after the steps run and before anything is written: the subject set
    of `generated/` unchanged; every `dcterms:modified` unchanged; the ID map gaining no row,
    losing none, having none rewritten and coming back in the same order; every produced file a
    `.ttl` directly inside `generated/`. B4's `check_append_only` is **called, not re-derived**,
    as that task asked — which is also what leaves a step able to write the `note` column and
    nothing else, and there is a test for that one legal edit so the guard is not mistaken for
    "the map must be identical". Order is checked separately because neither of the other two map
    checks can see it (review finding; see above).
  - **The comparison is a snapshot, taken before any step runs.** The one thing here that could
    have been wrong silently: an rdflib graph and an `IdMap` are both mutable, so a step that
    edited what it was handed rather than returning something new would leave all four refusals
    comparing an object with itself, and every one of them would pass on a migration that had
    just minted an IRI. `InstanceState.with_graphs()` exists so a step replaces rather than
    edits, but the guard does not depend on a step using it.
  - **`dcterms:modified` is never touched.** The date records when the instance's *knowledge* of
    an object changed; how that knowledge is written down is not knowledge. A migration that
    refreshed the dates would put every node in the diff and hide what it actually did.
  - **A migration refuses a `generated/` that disagrees with its manifest.** It rewrites what the
    compiler wrote, and restamping somebody's hand edit as the new release's output would
    destroy the hash that would have caught it (§4.3).
  - **`.report.md` becomes a migration report**, and §5.6 now says so. Its rule was already "the
    committed report is the report of whatever produced the files beside it"; a compile report
    left in place would name a release that has not written a byte in the directory and would
    state a version the manifest beside it contradicts. §5.6's own §4.3 interaction is unchanged:
    the report is still not hashed.
  - **`migrate` writes; `check` judges.** The command deliberately runs none of §6.1's checks —
    they are `semprini check`'s, CI runs them on the resulting pull request, and a migration
    reporting them would be answering for its own work. The consequence is recorded as a test:
    a step that returns the state untouched is a migration that did not do what its summary
    says, nothing here can know that, and what stops it is the shapes refusing the result.
  - **`migrate/` is three modules**: `steps.py` is data (what this release ships), `registry.py`
    resolves which of it an upgrade needs, `apply.py` is the only part that touches a disk.
    §4.1 now lists them.

  **`MIGRATIONS` is empty, and that is the deliverable.** Nothing has been released, so no
  instance in existence was compiled by an earlier version of this compiler and a step "from" a
  version nobody ran would be fiction. `steps.py` documents how to add one and the three things
  to know first; `test_this_release_ships_no_migration` fails the moment one lands, so adding it
  is deliberate. The vN→vN+1 proof runs a **test-only** step through the real registry: a copy of
  the fixture instance doctored to what a fictional 0.0.9 writing `sem:legacyStatus` would have
  left, migrated to the installed release, landing **byte-identical to the committed fixture** —
  compared against a file this repository already trusts rather than against a golden file the
  migration itself produced, since the second proves only that it is repeatable. Say it that way
  in any release note: the machinery is exercised end to end, and no real upgrade has been
  performed by it, because there is no real upgrade yet.

  **Four small seams opened in other modules**, each because a second copy would have been the
  alternative: `semprini.version_parts()` (migrations order steps by version and the drift check
  needs to know which of two versions is newer), `build.stale()` / `build.remove()` (a run and a migration both own `generated/`
  wholesale — `run._stale` now passes `keep=(REPORT_FILE,)`, and the `.report.md` exemption
  rationale stayed at that call site), `build.ontology_file()` (both write the verbatim copy),
  `report.table()` (both render Markdown tables, and C2 bounded pipe- and newline-escaping at
  the render points — a migration report with its own renderer would have been a second answer
  to what happens to a `|`), and `manifest.is_generated_file_name()` (both compose a path under
  `generated/` from a name they were handed). `tests/test_run.py`'s ordering test now patches
  `build.remove` rather than `run._remove`.

  **The CLI surface is complete**, and `cli._UNIMPLEMENTED` is gone with it — `migrate` was the
  last stub. The dispatch tail is now an `AssertionError`, so a subcommand added without a
  dispatch fails loudly rather than exiting non-zero with no explanation, and
  `tests/test_cli.py` asserts the declared surface *and* invokes every subcommand to check that
  none reports itself absent.

  **Two adopter-facing texts changed**, and they matter more than the module: check 3's message
  now says `run semprini migrate --to <version>` where it said "recompile the instance", and the
  instance README gained an **Upgrading the compiler** section. A command nobody is told about
  is a command nobody runs, and the state it resolves — drift red, no way forward that does not
  touch the sources — is one an adopter would otherwise fix by hand-editing `generated/`.

  Notes for later sessions:
  - **`X.Y.Z` only.** A version that cannot be compared is refused rather than guessed at,
    including `0.0.0+source` — C2's rule that a source tree identifies no release, reaching the
    one other place that records which release wrote an instance's files. A release candidate
    therefore cannot be a migration target; **G5 owns** deciding whether that matters, and the
    escape is cheap (an rc adopter migrates to the final release).
  - **A migration does not touch `mappings/merges.csv` or `mappings/namespace.lock`.** The
    register's rows name IRIs, which no migration moves; the lock records what the instance
    bootstrapped against, and §3.4.4 makes upgrading the metamodel the manifest's business.
    Moving a base IRI remains `run --force-namespace-change`.
  - **The `note`-column allowance is the only legal ID-map edit today.** A future metamodel
    migration that reclassified objects would need the `kind` column and would be refused —
    deliberately: that is a change to this guard, in a release whose CHANGELOG says so, not
    something a step gets to do quietly.
  - Nothing in this task ran a migration against a real instance on GitHub, unlike G2. The
    scratch instance is the place to do it if G5 wants that evidence, and the honest version of
    the claim until then is "exercised end to end in the suite".

- [x] **G4 · Project documentation**
  **Spec:** §8, §9.2, §5.2
  **Deliver:** `README.md` stating the two-licence split prominently, `CONTRIBUTING.md`
  covering §9.2 including the four non-negotiables, and an adapter authoring guide
  pointing at the D1 contract test suite.
  **Verify:** a fresh reader can install the package, bootstrap an instance and compile
  the fixture using only the README — walk it through literally, on a clean machine.
  **Depends:** G1
  **Merged — [PR #19](https://github.com/JuhaKor/semprini/pull/19).** CI green on 3.12, 3.14 and
  the wheel job. A docs-only change, so CI proves only that nothing here broke the package; the
  claim this task rests on is the clean-venv walkthrough below, which no CI job runs.
  **Done.** Three documents: `README.md` rewritten from 40 lines to a full one, plus new
  `CONTRIBUTING.md` and `docs/writing-an-adapter.md`. Prose-only by decision — no mutation
  battery, since there is no code here to mutate and the testable claims are the commands and
  outputs, which were checked by running them rather than by asserting them.

  **Written to a house style the task owner set**: active voice, short sentences, simple
  tenses, no noun clusters, imperative instructions. That is a deliberate break from the
  register of `CLAUDE.md`, the spec and the instance README template, all of which are dense
  and subordinate-clause-heavy. Those are addressed to somebody already inside the project.
  These three are the ones a stranger reads first, and the two registers should not be
  reconciled by making these harder.

  **The verification was a literal walkthrough, and it is the reason to trust the README.**
  A clean venv, `pip install` of the built wheel (not the editable dev install), then every
  command in the README typed as written:
  - `semprini version` / `adapters` / `init` / `run --dry-run` / `run` / `check` /
    `check --base HEAD` all behave as the README says, including the 17-file scaffold listing
    and the seven-check output.
  - The fixture recompiled to **byte-identical** output on this Windows laptop from an
    installed wheel — `generated/ is up to date; 5 files unchanged`, `git status` clean. The
    README's determinism claim is a thing the reader reproduces, not a thing they are told.
  - The adapter guide's worked example is real code that was run: a `csv-glossary` adapter,
    packaged with the `pyproject.toml` the guide prints, `pip install`ed, listed by
    `semprini adapters`, passing `check_contract()`, and compiled into an instance that then
    passed all seven checks. Nothing in that guide is written from the interface alone.

  **The walkthrough found one real trap, and the README now warns about it.** Step 5 tells the
  reader to copy `tests/fixtures/acme/sources/taxonomies/product-category.xlsx` as a starting
  point. Copied *unedited*, it carries a `Reference Entity UUID` row, so the first `run` exits 2
  demanding `enumerates_source` — a configuration key the reader has no source to point at,
  because they have not configured a modelling tool. The message is excellent and the failure is
  correct; it is still the wrong first experience. The README now says to delete that row. This
  is exactly what walking a document literally buys and reading it does not.

  Three inaccuracies were also corrected against the code before shipping: check 7 re-serializes
  the committed graph and compares bytes (it does **not** "compile twice"), check 1 covers
  `shapes/local/` as well as `generated/` and `overlays/`, and §9.1's tag format is `vYYYY.MM.DD`
  with dots.

  Notes for later sessions:
  - **`pip install semprini` does not work yet, and the README says so in a call-out.** The
    package is not on PyPI; the note tells the reader to `poetry build` from a clone and install
    the wheel. **G5 owns deleting that note** — and it is the one edit that turns the README from
    accurate-with-a-caveat into simply accurate. It appears once, in *Before you install*, and
    every later step says "or the wheel you built, see the note above".
  - **The version `0.1.0` is written into that call-out** (`dist/semprini-0.1.0-py3-none-any.whl`).
    A release bump has to update it, or delete it along with the rest of the note.
  - **`CONTRIBUTING.md` names the four non-negotiables explicitly** — reproducible output, no
    blank nodes, no changed IRI, no real organization's content — drawn from §9.2 rules 4 and 5.
    §9.2's remaining principles are covered under *How the project is governed*. A fifth
    non-negotiable would be a spec change first.
  - **The adapter guide tells authors not to upstream by default**, per §9.2 rule 2, and says
    bundling is a maintenance burden rather than a badge. If that policy ever softens, that
    section is where it is stated to the outside world.
  - Nothing here is covered by CI. `ruff format` does check Python blocks inside Markdown — it
    reformatted one block in the adapter guide — so the guide's code stays formatted, but no
    check runs the guide's example or the README's commands. Re-walking the README is a manual
    step, and G5's clean-venv install is the natural place to do it again.

- [x] **G5 · Release and distribution**
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

  **Merged as [PR #20](https://github.com/JuhaKor/semprini/pull/20), and v0.1.0 is published.**
  CI green on 3.12, 3.14 and the wheel job — the last of which now builds the wheel, installs it
  into a bare environment and bootstraps an instance from it, so the Linux runner proves the same
  thing the laptop did. **Semprini has a first release, and it is installable by anybody.**

  **Verified from outside, after publication**, which is the half no CI job can reach:
  - `https://github.com/JuhaKor/semprini/releases/download/v0.1.0/semprini-0.1.0-py3-none-any.whl`
    — the exact URL every instance's workflows fetch — resolves `200`. Both distributions are
    attached to the tag (wheel 203,750 bytes, sdist 181,779 bytes).
  - The ontology resolves at every path w3id promises, in both directions: `/ontology` and
    `/ontology/0.1.0/` each return `200 text/turtle; charset=utf-8` for an RDF `Accept` and
    `200 text/html; charset=utf-8` for a browser's, and `/ontology/0.1.0/sem.ttl` `302`s to the
    site and lands `200 text/turtle`. The versioned path is now served from
    `ontology-archive/0.1.0/sem.ttl`, so it survives the next bump — which is the whole point.

  **The channel is decided (§11 #3): tagged GitHub releases, no package index.** That is the
  spec's own fallback default, and it is now recorded as resolved in §11 and stated in §5.1 and
  §7. The consequence reaches further than the decision sounds, and it is why this task touched
  fifteen files rather than three: `pip install semprini==X` works nowhere any more, so every
  place that said it had to change — both shipped workflow templates, the instance README
  template, this repository's README, and two error messages that were telling operators to run
  a command that would now fail. The rendered install line is

      env:
        SEMPRINI_VERSION: "0.1.0"
      run: pip install "semprini @ https://github.com/.../v${SEMPRINI_VERSION}/semprini-${SEMPRINI_VERSION}-py3-none-any.whl"

  The version sits in a shell variable because the URL names it twice — tag directory and wheel
  filename, which is pip's naming rule rather than a choice — and an adopter upgrading by hand
  would otherwise edit one occurrence and not the other. One line per workflow, and
  `test_the_workflows_pin_the_plane_version` now expands that variable itself and compares the
  result with `semprini.wheel_url()`, the single definition of the URL that the workflows, the
  instance README and the release notes all render from.

  **A2's known gap is closed, and closing it produced the invariant this task is really about.**
  Released ontology versions are frozen copies under `ontology-archive/<version>/sem.ttl`, and
  `tools/build_site.py` publishes every one of them — each documented from *its own* document
  rather than from today's, since a page describing current terms under a released version's
  number is a worse answer than a 404. The current version's page lists them, which is the only
  navigation the site has and the only way somebody discovers a permanent path exists. Proven by
  `test_a_released_version_still_resolves_after_the_next_one_ships`, which fakes the second
  version rather than waiting for one — waiting is how the gap survived A2.

  The invariant: **a released ontology can no longer be edited without releasing a new version of
  it.** The archived copy and the shipped document are compared byte for byte, so any edit to
  `src/semprini/ontology/sem.ttl` fails the suite until `owl:versionInfo` moves. Nothing enforced
  that before; §7 asserted it in prose. A version number that goes *backwards* is refused too —
  that one is invisible to every other check, because the document still matches its own copy.

  **Two tools, because a release is permanent and CI has to be able to refuse one.**
  - `tools/release_check.py <tag>` compares the tag against `pyproject.toml`, the installed
    distribution, the changelog and the archive; `--notes` cuts the release notes from the
    changelog section and appends the install command. Run it before tagging. `release.yml` runs
    it again on the tag from the bare environment the wheel was installed into, so it checks the
    artifact rather than the source that produced it.
  - `tools/release_smoke.py <version>` is G5's own verification, automated: it runs the console
    script of an installed wheel, bootstraps an instance with it, and reads back what that
    instance pinned. **CI runs it on every pull request** against the built wheel, so the class
    of failure it catches — package data left out, an entry point that does not resolve, a
    placeholder that survived substitution — fails here rather than in the first repository
    somebody creates. It addresses the console script by path rather than through PATH, which is
    what makes it run at all on Windows.

  **Verified on this laptop against the artifact, not the source tree:** `poetry build`, a clean
  venv, `pip install` of the wheel, then `semprini version` (0.1.0 / 0.1.0),
  `release_check.py v0.1.0`, `release_smoke.py 0.1.0`, `semprini init` (both workflows pin
  `SEMPRINI_VERSION: "0.1.0"`, URL well-formed), and `semprini check` on the fixture instance —
  seven checks, 0 errors, 4 expected definition warnings. The wheel carries no
  `ontology-archive/`: an instance reads the one version it pinned from the package.

  **Mutation battery `g5_release`: 19 mutations, all caught.** Two were findings rather than
  confirmations. The first survivor exposed a re-sort in `build_site.build()` that no test could
  observe, because `released()` had already ordered the versions — dead code standing in for an
  invariant nobody enforced. It is gone, and the invariant it assumed (the current version is
  never older than a released one) is now a check in `release_check.py` with a test of its own.
  The second showed the ordering test could not tell a numeric sort from a lexical one: `0.9.0`
  and `0.10.0` sort the same way either way, and only a third version between them separates
  them. `g1_scaffold`'s pin mutation was rotted by the install change and has been re-anchored.

  **A code review at medium found five things, and two of them would have bitten on the very
  first ontology bump — the exact event this task exists to make safe.** All five are fixed.
  - **The site published a versioned path for the working tree's version.** Bump
    `owl:versionInfo` in a pull request, merge it, and `/ontology/<that version>/` went live on
    main weeks before any release froze it; a revert or a second bump then deleted a URL that
    had already resolved. A versioned path is now published for an **archived** version and for
    nothing else, and the in-development version's page says it has no permanent path yet
    instead of linking one that 404s.
  - **`test_the_site_holds_exactly_the_paths_the_redirects_target` hard-coded five paths**, so
    it would have failed on the first release that archived a second version. It now derives
    the expected set from the archive, and asserts the archive is not empty so the derivation
    cannot pass vacuously.
  - **Nothing compared the built wheel's filename with the one the download URL promises.**
    Every other check compared `wheel_url()` against something rendered from `wheel_url()`.
    `release_smoke.py` now takes the distribution directory and checks the artifact itself; CI
    and the release workflow both pass it.
  - A missing `ontology-archive/` raised a traceback over the top of the instruction the check
    before it had just given.
  - The two "install semprini X" messages named a version with no way to install it, in the
    very world this task creates. Both now name the URL.

  The battery grew to **22 mutations, all caught**, including one for each of the first three.

  **The release process was run for the first time, and step 4 found a documentation bug rather
  than a release bug.** `CONTRIBUTING.md` gave the verification as `curl -sI -H '...'`, which in
  PowerShell binds to `Invoke-WebRequest` and dies on the header argument before reaching the
  network — so the one step written for a human to run by hand was the one step never run on the
  maintainer's own platform. Fixed: the doc says `curl.exe` in PowerShell, uses `-L`, and now
  warns to read the last hop rather than w3id's `302`, whose `Content-Type` is `text/html` and
  means nothing. That trap was recorded in A2 and had not travelled into the instructions.

  **Notes for later sessions:**
  - **The README now describes a release that does not exist yet.** Its install URLs are right
    for v0.1.0 and resolve the moment step 2 finishes; between merge and tag they 404. The
    ordering is deliberate — the alternative is a README documenting a caveat instead of a
    product — but do not leave the gap open for long.
  - **`release.yml` runs the full suite on the tag**, duplicating CI on main. On purpose: a tag
    can be pushed at any commit, and a green branch is not proof that *this* commit was the green
    one. A release cannot be un-published into the instances that pinned it.
  - **The w3id `.htaccess` needs no change for new versions.** It already maps any `X.Y.Z`, so
    the archive is the whole mechanism. That file stays gitignored in
    `background-material/w3id/semprini/`, recorded only in A2.
  - **The first ontology bump is the moment to re-read `ontology-archive/README.md`.** Adding the
    new version's directory is a step in the release pull request, not something the tooling
    does. `release_check.py` refusing the release is the safety net, not the process.
  - Moving to a package index later changes the install line and nothing else. `wheel_url()` is
    the one place it is written down, and the version an instance pins is the same number either
    way — which is what §11 #3 now records.

---

## Phase H — Pilot

- [x] **H0 · Text normalization at the model boundary**
  **Spec:** §5.5 (a new rule 9), §5.2 (the `fetch()` contract), §5.4 (what a source key
  is), §5.6
  **Deliver:** one normalization function, applied to every text and every source key on
  the way into the internal model, plus the spec rule that licenses it. Numbered ahead of
  H1 because it is a correction to Phase B and D code rather than new capability, and
  because it has to land **before an instance holds data**: an invisible character in a
  `Concept URI` cell becomes a source key, and a source key becomes a frozen ID-map row
  (§5.4). Today that is free to fix; after H1 it is somebody's permanent IRI.

  **What was found.** Definitions compiled from an Excel taxonomy contain U+00A0 (NBSP)
  where the workbook appears to hold an ordinary space. Nothing in the pipeline creates
  one, so it is in the source — Excel reliably carries text pasted out of Word, a browser
  or a PDF. It survives because `_cell()` uses `str.strip()`, which removes NBSP at the
  *edges* only (`'\xa0'.isspace()` is `True`), and because `serialize._escape()` escapes
  U+0000–U+001F and U+007F and nothing else, so U+00A0 reaches the `.ttl` as raw bytes.

  **Why it is not cosmetic.** Three consequences, and only the first is obvious:

  - *The diff lies.* PR diffs are the governance interface (§1.2). A literal differing
    only by NBSP renders identically on GitHub: a reviewer sees a line marked changed with
    nothing visibly changed, and no way to find out why. For a repository whose whole
    review model is "read the diff", that is the worst available failure mode.
  - *It splits the ragged hierarchy, invisibly.* `_Row.path` matches on label values, so a
    parent whose L2 cell holds `Power\xa0Tools` and a child whose L2 cell holds
    `Power Tools` produce *"is narrower than 'Power Tools', which no row defines"* against
    two cells that look identical in Excel. This is exactly the defect D2 already found
    and fixed once for `"Tools"@en` versus bare `Tools` — the same class, with no visible
    tell at all. D2's lesson holds and extends: **a value that is parsed for one purpose
    must be parsed before it is used for another**, and *parsed* has to include
    *normalized*.
  - *It reaches identity.* An interior NBSP in a `Concept URI` cell yields a different
    source key, hence a different `uuid5(slug|key)`, hence a different IRI — frozen into
    `mappings/id-map.csv` on the run that mints it. Labels never feed minting
    (`identity.mint_local_name`), so prose is identity-safe; **keys are not**, and that is
    what makes this a task rather than a backlog note.

  **What to normalize, in this order** — fixed so the function is idempotent, which is the
  property that keeps recompiles byte-identical (§6.1.7):

  1. **NFC.** Argued for on its own merits, not as a side effect: composed versus
     decomposed `ä`/`ö` is the identical invisible-diff bug with a far wider blast radius,
     and this project's examples are Finnish. NFC is idempotent and changes nothing that
     renders differently. **Not NFKC** — that would fold ligatures, superscripts and units,
     which is real content damage.
  2. **Map to U+0020** every character in Unicode general category `Zs` other than U+0020
     itself, plus `Zl` and `Zp` (U+2028, U+2029). Derived from the category rather than
     enumerated, so it does not rot — but **pin the derived set in a test** as an explicit
     literal, so that a Python or Unicode-data upgrade which changes it is visible rather
     than silent.
  3. **Delete** U+200B (ZWSP), U+FEFF (ZWNBSP/BOM) and U+00AD (soft hyphen). Nastier than
     NBSP: `strip()` does not touch them even at the edges, so today they survive at *both*
     ends of a literal. **Do not delete U+200C/U+200D** — ZWNJ and ZWJ are meaningful in
     Indic and Arabic script and in emoji sequences.
  4. **Strip** again, since steps 2 and 3 can expose new edge whitespace.

  Deliberately **out of scope**, and say so in the spec rule rather than leaving it to be
  rediscovered: U+2011 non-breaking hyphen (an orthographic choice, not an artefact); tabs
  and newlines inside a cell (real, and the serializer already writes them visibly as `\t`
  and `\n`); and collapsing interior runs of whitespace. That last one is the arguable
  sub-decision — NBSP→space can leave a double space — and the case against is that a
  double space is at least *visible*, while collapsing also rewrites text somebody spaced
  deliberately. Leave it out; revisit only with an example that argues for it.

  **Where it goes.** In `model.Text` — `__post_init__`, with `object.__setattr__` since the
  dataclass is `frozen=True, slots=True` — and **not** in `excel_taxonomy._cell()`. Three
  reasons: Ellie carries the same pasted-from-Word prose, so fixing one adapter leaves the
  other broken; a third-party plugin author must not have to know that NBSP is a hazard,
  which is the extension-without-forking rule (§5.2) doing its job; and it fixes
  `_Row.path` matching for free, since the path is built from `Text.value`. `Text` already
  normalizes on construction (empty rejected, language tag validated), so this is what the
  type is for. The counter-argument — §5.2 assigns normalization to adapters — is real but
  not decisive: this is a property of the type, not of any one source.

  Three boundaries `Text` does **not** cover, and each needs the same function applied
  explicitly:

  - **Source keys.** `excel_taxonomy._local_name()` and the Ellie adapter's key handling.
    This is the identity-bearing one; it is also the one an adapter contract check can
    give teeth to.
  - **Header and property-name matching.** `_normalize_header()` lower-cases and strips.
    Header matching is strict by design (D2) and refuses the whole workbook, so a header
    typed `Concept\xa0URI` fails a taxonomy for a reason no one can see in the sheet.
  - **Emptiness.** Normalization has to happen where emptiness is *decided*, not after.
    `_as_optional_text()` treats an empty string as absent before constructing anything, so
    a cell holding only U+200B is truthy today, and would raise `ValueError` from
    `Text.__post_init__` once normalization empties it. It must become **absent**.

  Slugs, source names and language tags need nothing: `is_slug` and `is_language_tag`
  already reject every character on the list.

  **Reported, not silent.** Count normalizations and surface the count in the run report
  (§5.6) — a run with nothing to normalize says nothing. Not an issue per cell: the fix
  lives in a binary `.xlsx` a steward may not own, so it would be permanent noise. Not
  fully silent either: a compiler that quietly edits a source's words with nothing anywhere
  saying so is how people stop trusting a compiler.

  **No migration, deliberately.** Nothing is in production and no instance holds real data,
  so this ships as an ordinary minor release with no §7 step — the fixture instance's
  generated Turtle is simply regenerated and committed. Recorded because it is not the
  general answer: §7 forbids a migration from reading sources, so once instances exist this
  same fix could only ever arrive through a normal recompile PR, with an invisible diff and
  a `dcterms:modified` bump on every affected node. That is the fact that makes doing it
  now cheap and doing it later expensive.

  **Verify:**
  - Unit tests per rule: each character class mapped, deleted or preserved; U+2011,
    U+200C, U+200D, tab and newline untouched; decomposed `ä`/`ö` composed by NFC; and
    `normalize(normalize(x)) == normalize(x)` over a mixed corpus.
  - The pinned-set test above fails loudly if the derived `Zs`/`Zl`/`Zp` set changes.
  - Excel: a parent whose level cell uses NBSP and a child whose matching cell uses a space
    compile into **one** branch — the NBSP counterpart of
    `test_a_branch_spelled_two_ways_is_still_one_branch`.
  - Excel: a header written `Concept\xa0URI` is matched, not refused.
  - Identity: a `Concept URI` carrying an NBSP mints the same IRI as the clean spelling,
    and does so *before* the ID map is written — assert on the map row, not only on the IRI.
  - A cell containing only U+200B yields an absent field, not an error and not a
    one-character literal.
  - Ellie: the same guarantee through its own fixture, proving the fix is not adapter-local.
  - The fixture workbook gains a definition that deliberately carries an NBSP, so the
    committed instance exercises this rather than only the unit tests;
    `tests/fixtures/acme/` recompiles byte-identically and mints nothing new.
  - `testing.py`'s adapter-contract suite gains the check, and G4's worked example adapter
    still passes it.
  - The run report shows the count when there is one and stays silent when there is not.
  - Spec updated in the same change: §5.5 rule 9 is the rule's home, with a sentence in
    §5.2 and a note in §5.4 that a source key is normalized before it is a key.
  - A battery at `tools/mutations/h0_normalize.py` — at minimum: NFC dropped, one character
    class dropped, deletion done as a space-map, normalization applied after the empty check
    rather than before, keys left unnormalized, headers left unnormalized, the report count
    not reported, and the function made non-idempotent.

  **Depends:** B2, D2, D3 — all done. **Blocks H1.**

  **Done.** 1071 tests green (34 of them H0's); ruff, ruff format and mypy (strict) clean; the
  wheel installs into a bare venv with pip and `semprini check` passes there on the fixture
  instance. Twenty-five mutations were checked against the suite, twice — nothing normalized at
  all, composition dropped, NFD instead of NFC, NFKC applied, only U+00A0 mapped, the invisible
  characters spaced rather than deleted, ZWJ deleted too, the trailing strip dropped,
  normalization made non-idempotent, a text and a key each normalized after emptiness is judged,
  absence decided on the raw string, an object's stored keys left raw while its refs are
  normalized, a spreadsheet cell and a header each left unnormalized, a row judged blank on its
  raw cells, an Ellie field left unnormalized, a model id matched before normalization, a
  notation left unnormalized, the contract check switched off, the count never incremented,
  every value counted, the count never reported, reported when there was nothing to report, and
  the tally shared across sources instead of reset per source — and each fails it.

  **The battery found the two tests that were missing**, which is the whole reason it exists: a
  row of nothing but invisible characters, and an export whose `modelId` (rather than the
  *config*'s id) carries one. Both mutations survived the first run against a suite that already
  had eleven normalization tests in it.

  **The fixture instance carries the characters and compiles to byte-identical output.** That is
  the guarantee stated as an artefact rather than as prose: `product-category.xlsx` now holds an
  NBSP in a level cell that would split the power-tools branch, a soft hyphen inside
  `ont:Sanders` that would mint a second IRI, and an NBSP in prose — and `generated/`, the
  manifest, the report and the ID map are unchanged, byte for byte, from what was committed
  before this task. `test_the_fixture_workbook_carries_invisible_characters_on_purpose` is what
  stops a later regeneration from quietly dropping them and leaving the guarantee untested.

  Notes for later sessions:

  - **Two gaps found while implementing, beyond the reported one.** `skos:notation`
    (`TaxonomyValue.code`) is a plain string that reaches a literal without passing through
    `Text`, and was unnormalized; and `_read_row` normalized the identity cell twice, because
    the blank-row check re-read the raw row. The second was only visible because the run report
    counts — a count is a weak assertion about behaviour and turned out to be a sharp one about
    structure. `_read_row` now reads each cell once, into a list.
  - **The count is per source and lives in `SourceSummary.note`**, filled by `run._note`. The
    honest consequence, written into `tests/test_run.py::_source_notes`: a report is not
    rewritten when nothing moved (§5.6), and normalization by design moves nothing — so a
    steady-state compile of a source full of invisible characters says nothing at all, and the
    note is read on the compile that changes something else. Judged the right trade against a
    warning that would fire forever on a binary file the steward may not own.
  - **`counting_normalizations()` is a `ContextVar`, and report-only.** Nothing it observes
    reaches the output, so a caller that never counts compiles the same bytes as one that does
    — pinned by `test_counting_changes_nothing_about_the_result`. It counts only values the
    function actually changed, so merging (which re-normalizes routinely) adds nothing.
  - **`_SPACES` is pinned, not derived at import.** Deriving it means walking the whole code
    space. `test_the_space_set_is_exactly_what_unicode_calls_a_separator` re-derives it from
    `unicodedata` and demands the pinned set back, so a Python or Unicode-data upgrade that
    changes the answer is a failing test. Current answer is Unicode 16.0.0's 19 characters.
  - **Write the escapes, never the characters.** Both `model.py` sets and every test are written
    as `\uXXXX`. A source file that contained the literal characters would be a file no reviewer
    could check — the exact failure this task is about, committed into the fix for it.
  - **`build_fixture_workbook.py` had drifted from the workbook it claims to generate.** The
    script wrote a blank `Reference Entity UUID`; the committed `.xlsx` had it filled in by hand
    when D3 landed, so regenerating silently dropped `sem:enumerates` from the fixture. Fixed
    here — the script now writes the UUID — and worth knowing that the drift was invisible until
    something regenerated the workbook, since nothing compares the two.
  - **No migration ships**, because no instance holds data (§7 forbids a migration from reading
    sources anyway). Recorded in `CHANGELOG.md` under Unreleased, including the part an adopter
    would feel if this shipped later: literals lose the invisible character and `dcterms:modified`
    moves on the nodes affected, in an ordinary compile PR whose diff shows nothing.

- [ ] **H1 · First instance bootstrap**
  **Spec:** §5.7, §6.2, §9.1
  **Deliver:** a real instance repository for the pilot organization: base IRI decided,
  Ellie allowlist populated one validated model at a time, stewards and CODEOWNERS
  assigned, branch protection on.
  **Verify:** the scheduled compile opens a PR whose report a steward can review
  unaided; a deliberate source change appears as a readable diff on the next run; main
  is tagged per §9.1 rule 7.
  **Depends:** D3, G5, H0

---

## Decision gates

Open decisions from spec §11 and the task each one blocks. Anything not listed here can
be deferred without stalling the build.

| §11 | Decision | Blocks |
|---|---|---|
| ~~1~~ | ~~w3id namespace registration~~ — **resolved:** PR #6488 merged, `https://w3id.org/semprini/ontology` live and verified | ~~A2~~; nothing now. G5 discharged the obligation it left: every released version is published from `ontology-archive/` and goes on resolving |
| 2 | Confirm Apache-2.0 / CC BY 4.0 | A1 (the licence files are written there) |
| ~~3~~ | ~~Distribution channel~~ — **resolved:** tagged GitHub releases carrying a wheel and an sdist; no package index. The tag is the address an instance installs from, so `pip install semprini` resolves nothing and no unreleased version is installable by accident | ~~G5~~ |
| ~~4~~ | ~~Which adapters ship bundled~~ — **resolved:** Ellie and Excel ship and are registered (D3); G4's adapter guide states the policy publicly — bundling is a maintenance commitment, and a third-party adapter is never second-class | ~~D3~~; ~~G4~~ |
| ~~5~~ | ~~Default language tag(s)~~ — **resolved in B3:** one per instance, applied only where a label carries no tag of its own | ~~B3~~; C1 applies it |
| 6 | When missing-definition becomes blocking | per instance; H1 |
| ~~7~~ | ~~Ellie pagination and rate limits~~ — **resolved by scope:** the adapter reads exported files, so v1 makes no API call | ~~D3~~; whoever builds the API mode |
| ~~8~~ | ~~Whether `init` creates the remote repository~~ — **resolved in G1:** it stays offline, creates nothing remote and prints the steps instead | ~~G1~~ |

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
- ~~**F3, G3 and D3 are the three tasks most likely to overrun.**~~ All three are done. G3's
  hard core turned out to be exactly where it was expected: proving that a migration preserves
  identity rather than asserting it. The proof is a snapshot taken before any step runs, and
  the mutation that shows why is a one-line reordering.
- ~~**G1 done: the plane can now create the thing it compiles.**~~ Done, and **G2 with it,
  which completes Phase G's CI half.** No third-party code ships into an adopter's CI any
  more, the §6.3 rule is enforced mechanically against the files that ship rather than
  intended in prose, and — for the first time in this project — both workflows have been
  run against a real instance on GitHub. That run is where the value was: it proved the
  report survives a real pull request body, that a no-op compile is green and silent, and
  that output is byte-identical between the Linux runner and a Windows laptop; and it
  falsified a mechanism this repository had asserted in four places since G1.
- ~~**G4 next.**~~ Done, and **Phase G is one task from complete**. The project now has front
  doors: a README that takes a stranger from "what is this" to a compiled instance on GitHub, a
  `CONTRIBUTING.md` that states the four things a contribution may never do, and an adapter guide
  whose worked example was packaged, installed and compiled rather than written from the
  interface. The README was verified the way the task asked — walked literally on a clean install
  — and that walk found a trap in the first-source step that reading it would not have. **G5 next**,
  and it inherits one edit from here: the "not on PyPI yet" call-out in *Before you install*, which
  a published release deletes.
- ~~**G3 next.**~~ Done, and **the compiler is now feature-complete**: every subcommand of §5.1
  does something, and an adopter can bootstrap an instance, compile it, validate it and carry it
  across a plane upgrade without leaving the CLI. What is left in Phase G is documentation and
  release, not capability. **G4 next** — and note that G4's verification ("a fresh reader can
  install, bootstrap and compile using only the README") is now the first task in the project
  whose subject is a reader rather than a test, so budget for actually walking it.
  G5 inherits two things beyond its own scope: A2's known gap (every released
  `/ontology/X.Y.Z/` must keep resolving), and the question of whether a release candidate
  needs to be a migration target, which G3 refused by requiring `X.Y.Z`.

- ~~**G5 next.**~~ Done, and **Phase G is complete**. v0.1.0 is published and verified from
  outside. The project has a release process, a channel (§11 #3: tagged GitHub releases, no
  index), and the last of A2's debts is paid — every ontology version ever published now keeps
  resolving, from frozen copies rather than from a working tree that has moved on. The invariant
  that fell out of it is worth more than the mechanism: a released ontology document cannot be
  edited under its own version number, because the shipped copy and the archived one are
  compared byte for byte. §7 had asserted that in prose since v0.1 and nothing checked it.

  ~~**H0 next.**~~ Done, and it reached further than the report that prompted it. The visible
  half was a definition compiled with an NBSP where the workbook looks like it holds a space.
  The half that mattered was identity: the same class of character in a `Concept URI` cell
  minted a different IRI and froze it in the ID map, and `skos:notation` had the same gap. It
  was numbered ahead of the pilot for exactly that reason — while no instance holds data the
  fix costs a regenerated fixture, and afterwards §7 makes it a recompile PR whose diff nobody
  can see. What it records for later is that this project had no defence against a character
  that renders as another one, and determinism is a promise about bytes.

  **H1 follows, and it is the first task whose subject is a real organization.** The thing it
  was waiting for now exists: an instance pins a version, and there is a released version to
  pin. Everything else H1 needs is in place: `semprini init` produces the tree, both workflows
  have been run against a real instance on GitHub (G2), and the compiler is feature-complete
  (G3). What H1 adds is the things only a pilot can settle — a real base IRI, an Ellie allowlist
  filled one validated model at a time, named stewards, and §11 #6, the last open decision,
  which is per instance and needs somebody's actual data to answer.

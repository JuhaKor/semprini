# Changelog

Two version numbers are released independently (spec §7): the **compiler** — this
package, semantically versioned — and the **ontology**, the `sem:` metamodel's own
`owl:versionInfo`. A metamodel change is breaking for adopters even when the Python API
is untouched, so every entry below names which of the two moved.

Both numbers are recorded in each instance's `generated/.manifest.json` and enforced by
the drift check (§6.1). A release that changes emitted output ships a migration
(`semprini migrate --to <version>`), so an upgrade is always a reviewable diff.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Compiler 0.1.0

#### Added

- Package skeleton, `pyproject.toml` (Poetry) and the `semprini` console script.
- `semprini version`, reporting the compiler and ontology versions.
- The exit-code contract of §5.1: `0` success · `1` validation or compile failure ·
  `2` configuration or namespace-lock error · `3` a configured source was unreachable.
  Every other subcommand parses its arguments and exits `1` pending its own task.
- Apache-2.0 (`LICENSE`) for code and CC BY 4.0 (`LICENSE-DOCS`) for the ontology,
  shapes and specification, © Datakor Consulting Oy.
- The canonical Turtle serializer of §5.5 (`semprini.serialize`): fixed prefix block,
  sorted subjects and predicates, one triple per line, LF and UTF-8, and a refusal to
  emit blank nodes. `rdflib`'s own Turtle output is never used for anything an instance
  commits. Also `namespaces()`, which derives the per-kind instance namespaces of §3.1
  from a base IRI — the one place those suffixes are written down.
- The internal model of §5.2 (`semprini.model`): frozen `Entity`, `Attribute`,
  `Relationship`, `Scheme` and `TaxonomyValue` dataclasses identified by their
  `source_refs`, `merge_models()` merging objects that share a source ref, `RunContext`,
  and `Issue`/`Severity`. Objects that two sources disagree about raise rather than
  resolving to one side.
- Instance configuration loading (`semprini.config`): `config/semprini.yaml` is parsed
  and validated, and every rejection names the offending key and exits `2`. Unknown keys
  and duplicate YAML keys are errors, not extras. Credentials written into the file are
  **refused** at any depth — a source names an environment variable (`token_env`) and the
  value is read from the environment at fetch time, never stored on a config object.
  `run`, `check` and `migrate` now validate configuration before anything else, so a
  broken instance fails with a key rather than with a traceback.
- `PyYAML` as a runtime dependency (§5.1). Instances continue to install with plain pip.
- Identity management (`semprini.identity`): the persistent ID map, IRI minting and the
  namespace lock (§3.4, §5.4). `mappings/id-map.csv` is append-only and authoritative
  over the minting formula, so a taxonomy code, a minting rule or a compiler version can
  change without moving an IRI an instance has already published. Minting derives from
  the permanent UUIDv5 namespace `8865c94a-2211-5f26-8887-6d6d5cbaa1e0`, and is stable
  across machines and processes.
- The namespace lock (`mappings/namespace.lock`) is now enforced: `run`, `check` and
  `migrate` compare `config/semprini.yaml`'s base IRI and instance id against it and exit
  `2` on a mismatch, or when the lock is missing. Moving an instance to a new base IRI is
  `semprini run --force-namespace-change` — a migration that rewrites the ID map and the
  lock together, keeping every local name — and not a configuration edit.
- Identity failures raise `IdentityError`, each naming the source ref that caused it: an
  IRI collision, two objects resolving onto one IRI, an object the ID map already holds
  two IRIs for, a source key that changes kind, a row removed or edited against the base
  revision, and a `source_name` in the map that configuration no longer declares. These
  are compile failures (exit `1`) once a command reaches them — `semprini check` reports
  the append-only and source-name checks in §6.1 check 6, which arrives with its own task;
  today no command compiles, so none of them is reachable from the CLI yet.
- The graph builder (`semprini.build`): the internal model becomes one rdflib graph per
  file of `generated/`, partitioned by scheme (§4.2). An object is written exactly once,
  in the file of its lexicographically first scheme, and `dcterms:modified` is carried
  forward from the previous output unless a node's other statements actually changed — so
  recompiling unchanged sources produces byte-identical files and no diff. `ontology.ttl`
  is copied verbatim, never re-serialized. The stage refuses, naming the source ref, an
  object in no scheme or in the wrong kind of scheme, a renamed or malformed scheme slug,
  a cross-reference to something the run did not resolve, and a `sem:enumerates` IRI the
  instance never minted.
- `generated/.manifest.json` (§4.3, §7): a `sha256` hash of every file the compiler
  writes, plus the compiler and ontology versions that wrote them. No timestamps and
  sorted keys, so two runs of one input produce the same bytes. It detects a hand-edited
  generated file, a deleted one, and a file the compiler did not write — the last being
  how stale output from a scheme that no longer exists gets caught. **A manifest is
  refused when the compiler is running from a source tree**, since `0.0.0+source`
  identifies no release and would make the version-drift check pass between two unrelated
  working trees.
- `generated/.report.md` (§5.6): the reviewer's summary an instance's compile workflow
  pastes into its PR — versions, counts per class and per file, what is new, changed and
  deprecated, objects with no definition, and objects of one class sharing a name.
  Everything in it is derived from the graphs the run produced and the state they
  replaced, so it cannot disagree with the files beside it. **The report is rewritten only
  when the run changed something**: a scheduled compile that finds nothing new now leaves
  the instance byte-identical instead of opening a pull request whose only content is a
  report saying nothing changed.
- The adapter plugin interface (`semprini.adapters`): `BaseAdapter`, entry-point
  discovery for the group `semprini.adapters`, and `semprini adapters`, which lists what
  is installed with the distribution that provides each one (§5.2). A source system is
  added by installing a package and naming it in `config/semprini.yaml` — no fork, and no
  privileged path for the bundled adapters, which arrive by the same route. Discovery
  imports nothing, so one broken plugin never hides the others and no command runs
  third-party code merely to validate a configuration name.
- A source whose `adapter:` names nothing installed is now a configuration error (exit
  `2`) reported with its key, rather than a failure much later in the run. So are the
  refusals discovery makes: an entry point that does not import, does not yield a
  `BaseAdapter`, leaves `fetch()` unimplemented, calls itself something other than the
  name it is registered under, or is claimed by two installed distributions at once.
- **The adapter contract ships as an executable check** (`semprini.testing.check_contract`)
  that a third-party author runs against their own adapter, from their own test suite,
  with no pytest dependency and no base class to inherit. It catches an adapter that
  writes to disk, mints IRIs, invents `sem:` terms, edits the configuration it was given,
  returns a different model each run, attributes objects to the wrong source, or answers
  a dead source with a partial model instead of raising — and reports every violation at
  once rather than the first. "Writes to disk" includes deleting and renaming, and is
  watched on the failure paths too: an adapter that saves what it managed to download
  before giving up is caught on precisely the run that was supposed to change nothing.
- `SourceUnreachableError`, which an adapter raises when its source cannot be read, is
  mapped to exit `3` in the one place the CLI maps errors to codes. That is the code that
  tells a scheduled compile to retry rather than open an issue, and it now means the same
  thing whichever subcommand produced it.
- **The bundled Excel taxonomy adapter** (`excel-taxonomy`): one workbook is one taxonomy
  is one configured source, read from the ragged `L1..Ln` sheet the pilot's workbooks use.
  Identity comes from the `Concept URI` column and never from the labels, so a taxonomy
  can be re-worded without minting a single new IRI. Every problem in a workbook is
  reported at once — a taxonomy is edited in bulk, so its mistakes arrive in bulk.
- **The bundled Ellie adapter** (`ellie`): reads domain models exported from Ellie as
  JSON and committed under `sources/ellie/`, behind an allowlist keyed by Ellie's model
  id. Nothing outside the allowlist is read, and an export whose `modelId` disagrees with
  the id it is listed under is refused — a file copied over the wrong path would otherwise
  replace a scheme's entire contents and read as ordinary change. Both export shapes are
  accepted, with and without the outer `model` wrapper. **One Ellie instance is one
  source**, so an entity appearing in two domain models resolves to one node carrying two
  `skos:inScheme` triples; two Ellie instances are two sources, since their UUID spaces
  are unrelated. Entities, attributes and relationships become `sem:Entity`,
  `sem:Attribute` + `sem:attributeOf`, and reified `sem:Relationship` nodes, and each
  model becomes a glossary scheme. **Supertype relationships become `skos:broader`
  between the two entities** rather than reified relationships — Ellie gives those rows
  no name or verb, so reifying one would mean inventing a label no modeller wrote.
  A relationship's verb label reads source → target unless its `direction` says
  `"source"` — an absent direction included, which is what a single-label relationship
  usually exports. Two more exports are refused rather than compiled: one whose supertype
  relationship names a narrower entity the model does not hold (the inheritance would
  otherwise vanish silently, since it is carried *by* that entity), and one stating no
  `entities` key at all, which is a truncated download rather than an empty model and
  would deprecate every object the model holds. Problems in several exports are reported
  together, a file that will not parse included, so two broken models cost one CI round
  trip rather than two. Entity synonyms become `skos:altLabel` and the examples field one `skos:example`.
  `progressStatus`, source-system and ownership fields, relationship cardinality and
  every attribute metadata field but `Description` are deliberately **not** carried yet:
  each needs a metamodel term that does not exist, and adding one is a version bump.
- **v1 makes no network call.** Both bundled adapters read files that are committed with
  the instance and reviewed with it, so a compile needs no credential and no outbound
  access, and an adapter's configured path may not lead outside the repository. A direct
  Ellie API mode is a later mode of the same adapter, and will re-use every IRI, since
  identity is keyed by the Ellie UUID either way.
- **`semprini run` compiles an instance end to end** (§5.1): fetch every configured
  source, apply the lifecycle rules, resolve identity, build, serialize, write
  `generated/` and append to `mappings/id-map.csv`. Nothing is written until every stage
  has succeeded, so a source that is down or a register that contradicts itself leaves the
  instance exactly as it was rather than half-written. Two runs of unchanged sources
  produce zero diff — no rewritten dates, and no report saying nothing happened.
- `--dry-run` performs the whole compile and writes nothing at all, the ID map included,
  and reports the same bytes a real run would have committed.
- `--source <name>` fetches one source and compiles it against the previous state: every
  object outside that scope is carried forward exactly as it stands, so a partial run
  still writes the whole directory and deprecates nothing it did not look at. An object
  two sources describe is refused (exit `1`) rather than rebuilt from half its evidence.
- **Output the run did not produce is removed** (§4.3). `generated/` is machine-owned, and
  a file left behind is read as current by anything loading the directory from Git —
  including a nested one, which the manifest check would fail on the next PR. `.report.md`
  is the exception, since it is written only when something moved; removing a stale file
  counts as something moving, so that run rewrites the report.
- `--force-namespace-change` now performs the move (§3.4.4): the ID map, the merge
  register, the namespace lock and every generated file are rewritten in one commit, with
  local names unchanged.
  The move is computed with the run and written with its output, so a compile that fails
  afterwards leaves nothing half-moved; the previous generated state is rebased before the
  lifecycle rules read it, so deprecated nodes travel with everything else and no
  `dcterms:modified` moves. It cannot be combined with `--source`.
- Two configured sources that describe one object and disagree about it now fail with a
  message naming the source, not a traceback: which side wins is a stewardship decision
  and the compiler settles neither (§5.2). Reachable through third-party adapters, since
  neither bundled one stamps another source's key onto its objects.
- A cross-reference must now point at a node the run actually **writes**, not merely at an
  IRI the ID map has heard of. A row outlives its node — an object whose source was
  reconfigured away leaves one behind — and the triple would otherwise reach a governed
  file pointing at nothing, where no SHACL shape can see it.
- A taxonomy workbook that names a reference entity now states which configured source
  issued that key, as `enumerates_source`. It is required exactly when the workbook's
  `Reference Entity UUID` cell is filled: the ID map is keyed by `(source name, source
  key)`, so `sem:enumerates` could not previously resolve to an entity another source
  defined. Naming the taxonomy's own source there is refused as a configuration error —
  it is the mistake the setting exists to undo, and it would otherwise surface two stages
  later as an unresolvable reference pointing at the workbook rather than at the config.
- **The core SHACL shapes ship with the compiler** (§6.1.5): every constraint the
  specification lists, as a document an instance validates against without writing a rule
  of its own. Labels, statuses and scheme membership on every generated node; exactly one
  owner for an attribute and two ends for a relationship; hierarchies that stay within one
  class and one taxonomy, and contain **no cycles of any length** — which nothing earlier
  in the pipeline can detect, since an adapter sees one source and inheritance drawn
  across two of them closes a loop neither one holds; unique codes within a scheme;
  nothing active left hanging off a deprecated node; and IRIs that are under the
  instance's namespace for their kind, which is what catches a hand edit to `generated/`.
  A **missing definition is a warning**, reported without failing the run, as §6.1.5
  requires until an instance turns it on.
- Each of the three graphs is judged by the rules that apply to it: the core shapes read
  `generated/`, the overlay rules read `overlays/`, and an instance's own `shapes/local/`
  reads both. An organization can therefore keep a curated subset of an external
  vocabulary in `overlays/external/` without its concepts being asked for a `sem:status`
  nobody could give them — while an overlay that renames, deprecates or re-files a
  generated node is still refused, because `generated/` is the compiler's.
- **`semprini check` validates an instance end to end** (§6.1): syntax, manifest
  integrity, version drift, the namespace lock, SHACL, identity and determinism, in that
  order, reading the instance and writing nothing. Every problem is reported in one run,
  grouped under the check that found it — CI is where these are read, and one problem per
  round trip is the difference between one fix and five. Missing definitions and anything
  else a shape reports as a warning appear without failing the command; an error exits `1`
  and a base IRI that disagrees with the namespace lock exits `2`.
- Two of the seven checks answer questions no other stage can. **Determinism does not trust
  the manifest**: it re-serializes what is committed and compares the bytes, line endings
  included, so a hand edit that also recomputes its hash is still caught — and so is a
  `generated/` file whose line endings a clone rewrote. **The ID map's append-only rule is
  compared against the base revision** in git — the merge base, never the branch tip, so
  rows another pull request merged in the meantime are not reported as rows this one
  deleted. Where no base revision can be resolved, that half reports itself **not run**
  rather than passing quietly, and `--base <rev>` names one on any CI platform.
- **An instance must commit a `.gitattributes` pinning `eol=lf`.** Without it, a clone on a
  machine with `core.autocrlf=true` — the Windows default — rewrites every generated file
  on checkout, and the determinism check correctly fails on content nobody touched.
  `semprini init` writes it; an instance created before then should add it.
- **An organization's own shapes are enforced as additive** (§3.6, §6.1.5). Write rules
  about anything, target `sem:` classes, be stricter than the plane is — but a file in
  `shapes/local/` that makes a statement *about* a `sem:` term or about a core shape is
  rejected and not applied, and so is one that relaxes a constraint to nothing
  (`sh:minCount 0`), derives statements with a `sh:rule`, or references a core shape it
  cannot see. The refusal names the file. Copying the core shapes into `shapes/local/` and
  editing them was the way an adopter would expect to change a rule; it never had any
  effect on validation, and now it says so instead of passing quietly.
- **A local shape that is not usable SHACL is reported, not raised.** These files are
  written by hand, and a property shape with no path, a pattern that is not a regex or a
  `sh:select` that is not a query used to reach an operator as a traceback from inside
  pyshacl, `re` or a SPARQL parser — naming no file, on content that parses perfectly well
  as Turtle. It is now an error against the file responsible, the files that do load are
  validated in the same run, and where only the union of them fails, the directory is
  named.
- **`semprini init` creates an instance repository** (§4.2, §5.7): the whole tree, its
  configuration, an empty ID map and merge register, the frozen `mappings/namespace.lock`,
  a verbatim copy of the pinned metamodel with its manifest, and the two CI workflows
  pinned to the plane version that produced them. It then prints what to do next. The
  fresh instance passes `semprini check` with no findings, and a run against it writes
  nothing — so an adopter's first pull request is theirs, not a compile fixing up its own
  scaffold.
- `semprini init --language <tag>` sets the instance's `default_language` at bootstrap
  (§5.5 rule 6). It is an ordinary setting and, unlike the base IRI, can be changed later.
- **`init` never overwrites.** It refuses a directory holding a `mappings/namespace.lock`,
  because the base IRI frozen there is a decision that cannot be taken twice — and it
  refuses on any other file it would have written, since nothing in the scaffold is safe
  to clobber. Every refusal is exit `2` and leaves the directory exactly as it was: the
  tree is rendered in memory before anything reaches the disk.
- **`init` makes no network calls and creates no remote repository** (§11 #8, now
  resolved). Creating the repository, protecting `main` and allowing Actions to open pull
  requests are steps it prints rather than performs.
- A source tree cannot bootstrap an instance: the scaffold pins the plane version in two
  workflows and in a manifest, and `0.0.0+source` identifies no release (§4.3, §7).

#### Added

- The metamodel namespace **resolves**: `https://w3id.org/semprini/ontology` content-negotiates
  to the ontology document (`text/turtle`) or to its documentation, and
  `https://w3id.org/semprini/ontology/0.1.0/` serves that version frozen. Registered on
  w3id.org, so resolution depends on no organization's domain remaining registered. An
  agent, query or SHACL shape written against `sem:` can now dereference it.

- The metamodel vocabulary: the four `sem:` classes of §3.2 and the ten properties of
  §3.3, each with an `rdfs:label` and an `rdfs:comment`. `sem:isAbout` and
  `sem:represents` are declared but reserved — the compiler emits neither.
- Terms are typed in RDFS (`rdfs:Class`, `rdf:Property`, `rdfs:domain`, `rdfs:range`).
  OWL appears only on the document node, which carries `owl:versionInfo`: the metamodel
  is SKOS-based, constraints are stated once in SHACL (§6.1.5), and OWL typing would
  license entailments nothing validates.

#### Removed

- The `0.0.0` placeholder document, which declared no vocabulary. The
  `https://w3id.org/semprini/ontology#` namespace still has to resolve before any
  instance mints IRIs against it (§11 #1, task A2).

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

### Ontology 0.1.0

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

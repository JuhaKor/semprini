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
- Identity failures are compile failures (exit `1`), each naming the source ref that
  caused it: an IRI collision, an object the ID map already holds two IRIs for, a source
  key that changes kind, a row removed or rewritten against the base revision, and a
  `source_name` in the map that configuration no longer declares.

### Ontology 0.1.0

#### Added

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

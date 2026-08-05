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

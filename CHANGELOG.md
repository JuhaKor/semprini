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

### Ontology 0.0.0

- Placeholder metamodel document. It declares no vocabulary and must not be used to
  mint IRIs; the classes of §3.2 and properties of §3.3 arrive in task A3, and the
  `https://w3id.org/semprini/ontology#` namespace must resolve before any instance
  mints against it (§11 #1).

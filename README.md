# Semprini

Semprini turns the business models and taxonomies an organization already maintains — in
modelling tools and spreadsheets — into a governed knowledge graph. A compiler reads those
sources and generates RDF into a Git repository, so the organization's shared vocabulary lives
somewhere reviewable, versioned and machine-readable instead of scattered across tools.

This repository is the product itself: an openly licensed Python package, an ontology and the
scaffolding that comes with it. It is not anyone's knowledge graph. An organization installs
the package and runs `semprini init` to create its *own* repository, which holds its sources,
configuration and generated RDF. One plane, many instances.

The build has just started: the package skeleton installs and `semprini version` works, while the
compiler itself is still being written. Start with [`TASKS.md`](TASKS.md) for the build order, and
read [`docs/rdf-repo-and-compiler-spec.md`](docs/rdf-repo-and-compiler-spec.md) — the authoritative
specification — for what is being built.

## Licensing

Two licences, by kind of artifact. The compiler, adapters, CLI, workflow templates and instance
scaffold are **Apache-2.0** ([`LICENSE`](LICENSE)). The `sem:` metamodel ontology, the core SHACL
shapes and the specification are **CC BY 4.0** ([`LICENSE-DOCS`](LICENSE-DOCS)) — vocabularies are
documents, and adopters must be able to quote and extend them. Copyright © 2026 Datakor Consulting Oy.

Content produced by an instance belongs to the adopting organization and carries no licence from
this project.

## Development

Dependencies are managed with [Poetry](https://python-poetry.org/); the published wheel is plain, so
instances install it with `pip` and never need Poetry.

```bash
poetry install
poetry run pytest
poetry run ruff check . && poetry run mypy
```

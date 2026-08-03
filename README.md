# Semprini

Semprini turns the business models and taxonomies an organization already maintains — in
modelling tools and spreadsheets — into a governed knowledge graph. A compiler reads those
sources and generates RDF into a Git repository, so the organization's shared vocabulary lives
somewhere reviewable, versioned and machine-readable instead of scattered across tools.

This repository is the product itself: an openly licensed Python package, an ontology and the
scaffolding that comes with it. It is not anyone's knowledge graph. An organization installs
the package and runs `semprini init` to create its *own* repository, which holds its sources,
configuration and generated RDF. One plane, many instances.

Nothing is implemented yet. Start with [`TASKS.md`](TASKS.md) for the build order, and read
[`docs/rdf-repo-and-compiler-spec.md`](docs/rdf-repo-and-compiler-spec.md) — the authoritative
specification — for what is actually being built.

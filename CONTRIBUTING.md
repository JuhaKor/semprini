# Contributing to Semprini

Thank you for wanting to help. This page tells you what Semprini will accept, what it will
not, and how to get a change merged.

Read [`README.md`](README.md) first if you have not. It explains what Semprini is and how the
pieces fit together.

## The four non-negotiables

Start here. These four rules outrank everything else on this page. A change that breaks one of
them will not be merged, however good the rest of it is, and however much we like the idea.

### 1. Never make the output non-reproducible

Compile the same sources twice and Semprini must write the same bytes. Adopters review changes
to their vocabulary as pull request diffs, so a diff has to show real change and nothing else.

This rules out more than it first looks like. Do not write a timestamp into a generated file.
Do not write a run identifier, a hostname or a file path. Do not iterate a `set` and serialize
in whatever order it hands you. Do not depend on the platform's line endings, or on a locale's
sort order.

### 2. Never put a blank node into a generated file

Blank nodes have no stable name, so two runs label them differently and the diff fills with
noise. They also cannot be referred to from another file, or from another system.

Generated RDF names every node. If a design seems to need a blank node, it needs a minted IRI
instead.

### 3. Never change an existing IRI

An IRI is permanent. Once Semprini has minted one and an instance has committed it, that IRI
means that object for ever. Other systems link to it. Older tags of an instance quote it.

So a change may not re-mint, re-key or renumber anything. It may not change how existing rows in
`mappings/id-map.csv` are read. If you want to change the minting rule, remember what makes that
safe: the map is authoritative over the formula, so a new rule applies to new objects only, and
every row already written keeps winning.

Deleting an IRI is the same offence. When a source drops an object, Semprini deprecates it and
keeps it.

### 4. Never bring a real organization's content into this repository

Semprini is a product, not a deployment. No adopting organization is named here. No adopter's
model, taxonomy, glossary or export is used as a test fixture, not even a small one, not even
with the names changed.

Test fixtures are invented. `tests/fixtures/acme` is a synthetic hardware company, and new
fixtures follow it.

The same rule keeps instance content out of the tree in general. Do not add `generated/`,
`overlays/`, `sources/`, `mappings/` or `config/` directories to this repository. Those belong
to an instance.

## How the project is governed

Four principles decide what belongs in the core and what does not.

**The metamodel is the compatibility surface.** Every instance in the world shares `sem:`, so
changing it changes everybody's data at once. Adding a term is welcome and is a minor version
bump. Removing or redefining one is a major event, and it ships with a migration.

**You do not have to upstream your adapter.** The plugin interface exists precisely so that you
can ship an adapter yourself, from your own repository, under your own licence, on your own
release schedule. See [`docs/writing-an-adapter.md`](docs/writing-an-adapter.md). The bundled
adapters are simply the ones this project commits to maintaining and testing — they get no
privileges the interface does not give you.

**A local extension that keeps recurring is a candidate for the core.** Each instance has its
own `x:` namespace for terms of its own, and using it needs nobody's permission. That is the
easy path, on purpose. When several organizations independently invent the same `x:` term, tell
us — that is evidence, and promoting it to `sem:` is the considered path.

**Extension must never require a fork.** If your change would force an adopter to fork Semprini
to use their own source system, express their own terms or add their own validation rules, then
it is the wrong change. New sources are plugins. Organization-specific terms go in `x:`. Local
shapes are additive.

## Getting set up

You need Python 3.12 or newer. This repository uses [Poetry](https://python-poetry.org/) and
commits `poetry.lock`.

```sh
git clone https://github.com/JuhaKor/semprini.git
cd semprini
poetry install
```

Run everything CI runs:

```sh
poetry run pytest
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy
```

CI runs the suite on Python 3.12 and 3.14. It also builds the wheel, installs it into a bare
virtual environment and runs `semprini version` from it, because adopters install the wheel with
plain `pip` and must never need Poetry.

## Making a change

### Change the specification in the same pull request

[`docs/rdf-repo-and-compiler-spec.md`](docs/rdf-repo-and-compiler-spec.md) is authoritative. The
code implements the specification; it does not define it.

So if you change what Semprini does, edit the specification in the same pull request. When the
two disagree, the specification wins and the code is the bug.

### Prove your tests would notice a break

A test looks identical whether or not it asserts anything. So verify a change by breaking the
code on purpose and confirming that the suite goes red.

Use the runner in this repository. Do not write your own.

```sh
python tools/mutate.py f3_validate --list      # check the anchors, run no tests
python tools/mutate.py f3_validate             # run the battery
python tools/mutate.py f3_validate --rounds 2  # repeat, to rule out a lucky ordering
```

A battery is data, not a script: one module per area in `tools/mutations/`, defining `TESTS` and
`MUTATIONS`. Each mutation is a tuple of a description, a file path, a fragment to find and what
to replace it with. The fragment must appear in that file exactly once.

Add a battery for what you write. The runner copies the tree per worker, so it never edits your
working copy, and it runs the mutations in parallel.

Batteries are deliberately not in CI. They anchor to exact source fragments, so refactoring rots
them, and a rotted anchor blocking every unrelated pull request would get them all deleted
within a month. They are an on-demand tool for whoever is working on the code they anchor to.

### Keep the logic in the CLI

Every check and every side effect belongs in the Python. None of it belongs in workflow YAML.

The shipped workflows install a pinned version and run one command. That is what lets an adopter
on GitLab or Azure DevOps port a short configuration file instead of reimplementing your check —
and it is what makes `semprini check` reach the same verdict on a laptop as it does in CI.

### Write the pull request for the person who reads it

**Open the description with a plain-language summary.** Not a longer commit message. Say what an
adopter or a steward can now do that they could not before, and why that matters to them.
Somebody who does not read Python has to be able to tell what changed and decide whether it is
what they wanted.

Put the consequences in that summary rather than in the detail below it. If a secret can no
longer be committed, say so. If a run now fails earlier than it used to, say so. If a decision
now freezes something permanently, say so.

The technical account follows underneath: what you verified, what you decided, what the next
person needs to know.

### Update the changelog

Add an entry to [`CHANGELOG.md`](CHANGELOG.md), under `## [Unreleased]`. Say which version it
lands in, and mark whether the change is a patch, a minor addition or a major break.

Major means an adopter has work to do. A change to the serialized output is major, and it must
ship with a migration that carries existing instances across.

## Cutting a release

Only a maintainer does this. It is written down because a release here is permanent in a way
most projects' releases are not: there is no package index, so the tag is the address instances
install from, and the ontology it publishes is served at a URL this project promises will
resolve for ever.

Two version numbers move independently — the compiler and the ontology (§7). A release always
moves the compiler. It moves the ontology only when `sem.ttl` changed.

**1. Open a release pull request.** In one commit:

- bump `version` in `pyproject.toml`;
- move this release's entries out of `## [Unreleased]` into a dated `## [X.Y.Z] — YYYY-MM-DD`
  heading, and leave *Unreleased* saying `Nothing yet.`;
- if the ontology version changed, copy `src/semprini/ontology/sem.ttl` to
  `ontology-archive/<new ontology version>/sem.ttl`. Never edit a directory already in there.

Then check it, before anyone reviews it:

```sh
python tools/release_check.py v0.2.0
```

That compares the tag against `pyproject.toml`, the changelog and the ontology archive, and
names whatever disagrees. Run it again after review, and merge.

**2. Tag the merged commit.**

```sh
git switch main && git pull
git tag v0.2.0 && git push origin v0.2.0
```

The tag has to be `vX.Y.Z`. The workflows an instance runs build their download URL out of it,
so a tag spelled any other way is an install line that 404s.

**3. The tag publishes itself.** `release.yml` runs the suite, builds the wheel and the sdist,
installs the wheel into a bare virtual environment, runs `release_check.py` and
`release_smoke.py` against that installation, and creates the GitHub release with the changelog
section as its notes. Nothing is published if any of that fails.

Merging step 1 also redeploys the site, which is what makes the new ontology version resolve at
`https://w3id.org/semprini/ontology/X.Y.Z/`.

**4. Prove the release exists, from outside.** Two commands, once:

```sh
pip install "semprini @ https://github.com/JuhaKor/semprini/releases/download/v0.2.0/semprini-0.2.0-py3-none-any.whl"
curl -sI -H 'Accept: text/turtle' https://w3id.org/semprini/ontology/0.2.0/sem.ttl
```

Nothing in CI can check either one: the asset does not exist until the release is published, and
the site is deployed by a different workflow. Check the *previous* ontology version still
resolves too — that is the promise the archive exists to keep.

### A released ontology is frozen

Once `ontology-archive/X.Y.Z/` exists, `src/semprini/ontology/sem.ttl` cannot change under that
same version number. The test suite fails until `owl:versionInfo` moves, because the archived
copy and the shipped copy are compared byte for byte.

This is deliberate, and it is the whole mechanism. Somebody may already have fetched the
document at its permanent path and compared their instance against it. Changing a term needs a
new version, a changelog entry and a decision — not a line edited in passing.

## Reporting a bug

Open an issue. Please include:

- what you ran, and what you expected
- what happened instead, with the exact message and exit code
- the output of `semprini version`
- a small synthetic reproduction, if you can make one

Never paste your organization's real content into an issue. Reduce it to an invented example
first — see non-negotiable 4.

If you have found a security problem, do not open a public issue. Email
`juha.korpela@datakor.fi` instead.

## Exit codes

Semprini's exit codes are part of its published contract. CI acts on them, so they mean the same
thing whichever subcommand returns them. Keep them that way.

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | validation or compile failure |
| 2 | configuration error, including a bad argument or a namespace lock conflict |
| 3 | a configured source was unreachable |

Code 3 exists to be distinguished from code 1. A source that was briefly down deserves a retry.
A source that answered with unusable data is a failure and needs a person.

## Licensing your contribution

Semprini uses two licences, one per kind of artifact — see the licensing section of
[`README.md`](README.md).

Contributing code means licensing it under **Apache-2.0**. Contributing to the ontology, the
core shapes or the specification means licensing it under **CC BY 4.0**. Pick the licence that
matches what you are changing; if a pull request touches both, both apply, each to its own part.

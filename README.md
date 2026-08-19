# Semprini

Semprini turns the business models and taxonomies you already maintain into a knowledge
graph you can govern.

## What Semprini is

Most organizations already describe their own business somewhere. A modelling tool holds the
entities and how they relate. A spreadsheet holds a product taxonomy. A glossary holds the
definitions. Each tool works well on its own. None of them talks to the others.

The result is familiar. Nobody can query the whole picture. Nobody can say what the word
"customer" officially means. Nobody can see what changed last quarter, or who approved it.

Semprini solves that. It reads those sources, translates them into RDF, and writes the result
into a Git repository. Your vocabulary now lives in one place. You can query it, publish it to
other systems, and read its history. Every change arrives as a pull request, so a person
reviews it before it lands.

Three design choices carry most of the value:

- **The compiler is deterministic.** Run it twice on the same sources and you get the same
  bytes. So a diff shows real change and nothing else, and you can review a compile the way
  you review code.
- **Identifiers are permanent.** Semprini mints an opaque IRI for every concept and never
  changes it. Rename the concept, re-code it, move it to another domain — the IRI stays. Links
  from other systems keep working.
- **Machines own one directory, people own another.** The compiler writes `generated/` and
  nobody edits it by hand. Stewards write `overlays/`. Continuous integration enforces the
  split, so the two never quietly overwrite each other.

## One plane, many instances

**This repository is the product, not anyone's knowledge graph.** It builds the *plane*: the
`semprini` Python package, the `sem:` metamodel ontology, the core validation rules and the
templates that come with them.

You install the package and run `semprini init`. That creates your *instance*: a separate Git
repository that holds your configuration, your sources and your generated RDF. Your instance
contains no Python. This repository contains no customer content.

| | The plane (this repository) | Your instance |
|---|---|---|
| Holds | the compiler, the metamodel, the shapes, the templates | your sources, your configuration, your RDF |
| Written by | this project | you |
| Contains Python | yes | no |
| How many | one | one per organization |

Every instance shares the same `sem:` metamodel. So a query, an agent or a validation rule
written against one instance works against all of them, and two organizations can align their
concepts without agreeing on anything else first.

## Licensing

Semprini ships under **two licences**, one for each kind of artifact.

| Artifact | Licence |
|---|---|
| Compiler, adapters, CLI, workflow templates, instance scaffold | **Apache-2.0** — see [`LICENSE`](LICENSE) |
| The `sem:` metamodel ontology, the core SHACL shapes, the specification | **CC BY 4.0** — see [`LICENSE-DOCS`](LICENSE-DOCS) |

The split is deliberate. Code gets a permissive licence with a patent grant, which is what
enterprise legal review expects. A vocabulary is a document rather than a program, so it gets a
documents licence — you must be able to quote `sem:` terms in your own documentation and extend
them in your own vocabularies, the way SKOS and Dublin Core allow.

**What your instance produces is yours.** The generated RDF carries no licence from this
project and no obligation back to it. Only the `sem:` terms it references belong to us, and
CC BY lets you use those with attribution.

Copyright © 2026 Datakor Consulting Oy.

## Before you install

Semprini needs **Python 3.12 or newer**. Check what you have:

```sh
python --version
```

> **The package is not on PyPI yet.** Publishing it is the next task in
> [`TASKS.md`](TASKS.md). Until then, build the wheel from a clone of this repository:
>
> ```sh
> git clone https://github.com/JuhaKor/semprini.git
> cd semprini
> pip install poetry
> poetry build
> ```
>
> That writes `dist/semprini-0.1.0-py3-none-any.whl`. Wherever the steps below say
> `pip install semprini`, install that file instead:
>
> ```sh
> pip install /path/to/semprini/dist/semprini-0.1.0-py3-none-any.whl
> ```
>
> You need Poetry to build the wheel. Nobody needs it to *use* Semprini.

## Try it first

Compile the example instance before you create your own. It takes a few minutes, and it proves
your installation works.

The example lives in this repository at `tests/fixtures/acme`. It is entirely synthetic — an
invented hardware company with one small domain model and one small taxonomy. No customer's
content is ever used as a test fixture here.

```sh
git clone https://github.com/JuhaKor/semprini.git
cd semprini

python -m venv venv
source venv/bin/activate     # on Windows: venv\Scripts\activate

pip install semprini         # or the wheel you built, see the note above
semprini version
semprini adapters
```

`semprini adapters` lists the source adapters you have installed. Two ship with the package:
`ellie` and `excel-taxonomy`.

Now compile the example:

```sh
cd tests/fixtures/acme
semprini run
```

You should see this:

```
generated/ is up to date; 5 files unchanged
```

That message is the point. Somebody compiled the RDF in `tests/fixtures/acme/generated/`
earlier, on another machine and another operating system. Your run produced the same bytes, so
it wrote nothing and `git status` stays clean. Determinism is not a claim in this README — you
just reproduced it.

Look at what a compiled instance holds:

```sh
cat generated/taxonomy-product-category.ttl
cat generated/.report.md
cat mappings/id-map.csv
```

Then validate it, which is exactly what continuous integration runs:

```sh
semprini check
```

The example reports four warnings, because four of its concepts carry no definition. Warnings
do not fail a run. Each instance decides for itself when a missing definition becomes blocking.

## Deploy your own instance

Eight steps, start to finish. Do them in order.

### Step 1 — Choose your base IRI

Every IRI your instance mints starts with this. **Semprini freezes it at bootstrap and you
cannot change it later**, so decide carefully now.

Pick a domain your organization owns and intends to keep for decades. Use a dedicated
subdomain, and end it with a slash:

```
https://semantics.acme.com/
```

Three points to weigh:

- The domain must outlive the tools. Do not use the hostname of the modelling tool, the wiki or
  the cloud tenant you happen to use today.
- The IRIs do not have to resolve on day one. Many organizations serve them later. Choose as if
  they will.
- Semprini writes no names, codes or domain labels into the identifier itself. IRIs stay
  opaque, which is what lets you reorganize your business without breaking your graph.

Choose a short slug for your instance too, such as `acme`. Semprini freezes that alongside the
base IRI.

### Step 2 — Install the compiler

Work in a virtual environment.

```sh
mkdir acme-semantics
cd acme-semantics

python -m venv venv
source venv/bin/activate     # on Windows: venv\Scripts\activate

pip install semprini         # or the wheel you built, see the note above
semprini version
```

Note the compiler version it prints. Your instance pins it.

### Step 3 — Create the instance

```sh
semprini init --base-iri https://semantics.acme.com/ --org acme --language en
```

The command writes seventeen files and prints them. It makes no network call and creates
nothing remote. Use `--language` to set the language tag Semprini applies to labels that arrive
without one. It defaults to `en`, and unlike the base IRI you can change it later.

Here is what you now have:

| Path | Who writes it | What it holds |
|---|---|---|
| `config/semprini.yaml` | you | which sources this instance compiles |
| `sources/` | you | the source files themselves — exported models, taxonomy workbooks |
| `overlays/` | stewards | the only hand-written RDF |
| `shapes/local/` | stewards | extra validation rules of your own |
| `generated/` | **the compiler alone** | the RDF, a manifest of hashes, the last run report |
| `mappings/` | the compiler, by appending | the identity registry, the merge register, the frozen base IRI |
| `.github/workflows/` | you, rarely | two thin workflows, pinned to the compiler version |

Read the `README.md` that `init` wrote. It is your instance's own documentation, and it states
the rules your stewards work under.

### Step 4 — Put it on GitHub

```sh
git init -b main
git add .
git commit -m "Bootstrap the semantic layer"
git remote add origin git@github.com:acme/acme-semantics.git
git push -u origin main
```

Then set three things in the repository's settings. They are not optional — they are what turns
a folder of RDF into a governed one.

1. **Protect `main`.** Require pull requests. Require the `validate` check to pass. Require at
   least one review.
2. **Let GitHub Actions open pull requests.** Find the setting under *Settings → Actions →
   General → Workflow permissions*. The scheduled compile opens one, and it cannot without this.
3. **Assign reviewers with `CODEOWNERS`.** Give each domain's files to that domain's steward.
   Give `mappings/`, `shapes/local/` and `config/` to whoever owns the repository.

### Step 5 — Add your first source

Open `config/semprini.yaml` and fill in the `sources:` list. Add **one** source first, compile
it, and review the result before you add a second.

A taxonomy workbook is the easiest place to start. Save it under `sources/taxonomies/`, commit
it, and describe it like this:

```yaml
sources:
  - adapter: excel-taxonomy
    name: product-category
    config:
      path: sources/taxonomies/product-category.xlsx
      scheme_slug: product-category
```

The workbook needs two sheets. Copy
[`tests/fixtures/acme/sources/taxonomies/product-category.xlsx`](tests/fixtures/acme/sources/taxonomies/product-category.xlsx)
from this repository and edit it, rather than building one from a blank file.

- Sheet `Concept Scheme` is a two-column table of properties and values. `Scheme Name` is
  required. Delete the `Reference Entity UUID` row unless you also compile the model that owns
  that entity — the row says which entity this taxonomy enumerates, and Semprini refuses the
  run when it cannot resolve it.
- Sheet `Taxonomy` holds one concept per row. Give every row a `Concept URI`, which is its
  permanent key. Fill the level columns `L1`, `L2`, `L3`… to express the hierarchy. A row's
  parent is the row whose labels are its own, minus the last one.

To compile an Ellie model instead, export it from Ellie, save the JSON under `sources/ellie/`,
and list it in an allowlist:

```yaml
sources:
  - adapter: ellie
    name: ellie-main
    config:
      base_url: https://acme.ellie.ai/api/v1
      models:
        - id: 70337
          path: sources/ellie/storefront.json
          scheme_slug: storefront
```

Semprini reads nothing you have not listed. List every model of one Ellie instance under **one**
source, because Ellie's identifiers are unique across the instance — that is what lets the same
entity appear in two models and stay one concept.

Two rules about `name:`, and both are permanent:

- **Choose it once and never change it.** Semprini writes it into every identity record, so
  renaming a source detaches every concept it owns.
- **Name the source, not the tool.** Call it `product-category`, never `excel-product-category`.
  The day that taxonomy arrives in another format, a name that mentions Excel forces you to
  re-mint every IRI in it.

Semprini never wants a credential in this file. Both adapters that ship today read files you
have already committed. If you later install an adapter that calls an API, it names an
environment variable and reads the value from the environment. Paste a token into the
configuration and the run refuses to start.

### Step 6 — Compile

Rehearse first:

```sh
semprini run --dry-run
```

That runs the whole pipeline and writes nothing. Then compile for real:

```sh
semprini run
```

Semprini prints what it wrote, how many concepts are new, how many changed, how many it
deprecated, and how many identifiers it minted. Read `generated/.report.md` for the long
version.

### Step 7 — Review and commit

```sh
semprini check
```

`semprini check` runs seven checks and writes nothing. Run it before every commit. It is the
same command your continuous integration runs, so it reaches the same verdict on your laptop as
it does in the cloud.

Check 6 reports itself as *not run* until the repository has a revision to compare against. That
is correct on a repository you have not committed to yet. Pass `--base HEAD` once you have.

Then read the diff before you commit it. This is the moment the whole design exists to serve:
the change to your organization's vocabulary sits in front of you, in a form a person can read.

```sh
git add .
git commit -m "Compile the product category taxonomy"
git push
```

### Step 8 — Hand it to CI

`semprini init` already wrote both workflows. You do not have to configure them.

- `validate.yml` runs `semprini check` on every pull request.
- `compile.yml` recompiles every Monday, and opens a pull request **only if something moved**. A
  week in which nothing changed produces no pull request and no noise.

Change the schedule if you want a different cadence. Edit the `cron:` line in `compile.yml`. A
run that finds nothing costs only the run.

Both workflows pin the compiler version that created the instance. Upgrading is a deliberate
edit to those two lines, reviewed like any other change.

From here on the loop runs itself. Somebody edits a model in Ellie. Monday's compile notices,
opens a pull request, and describes it. A steward reads the diff and merges it. Tag `main`
afterwards — `git tag v2026.08.19` — because tags are the snapshots you can cite.

## How it works

### The pipeline

`semprini run` is one pass with a strict rule: **nothing reaches the disk until everything is
known.**

```
config/semprini.yaml
        |
        v
   [ adapters ]     read each source, return plain objects, write nothing
        |
        v
   [ identity ]     look each object up in mappings/id-map.csv, mint an IRI if it is new
        |
        v
   [ lifecycle ]    compare against the last run: what is new, what changed, what is gone
        |
        v
   [ build ]        assemble the RDF, split it into one file per scheme
        |
        v
   [ serialize ]    write canonical Turtle: fixed prefixes, sorted, no blank nodes
        |
        v
   generated/  +  mappings/id-map.csv
```

A source that fails, a register that contradicts itself, a model that will not compile — any of
them stops the run before it writes a byte, and your instance stays exactly as it was. That is
also why `--dry-run` rehearses rather than approximates. It is the same pipeline without the
last step.

### The metamodel

Everything Semprini generates uses one small vocabulary, `sem:`, published at
`https://w3id.org/semprini/ontology#`. It builds on SKOS, so ordinary SKOS tools already
understand most of a Semprini graph.

| Term | Represents |
|---|---|
| `sem:Entity` | a business concept — "Customer" |
| `sem:Attribute` | an attribute with its own identity — "Customer number" |
| `sem:Relationship` | a named relationship between two entities |
| `sem:BusinessTerm` | a free-form glossary term |
| `skos:ConceptScheme` | a domain glossary, or a taxonomy |
| `skos:Concept` | a value inside a taxonomy — "Drills" |

Attributes get their own nodes because your source tools give them identity, owners and
definitions. Relationships get their own nodes because they carry a name and a verb. Semprini
also emits a `sem:relatesTo` shortcut between the two entities, so a simple traversal does not
have to walk through the relationship node.

The `sem:` namespace resolves through [w3id.org](https://w3id.org/), a community-run permanent
identifier service. So resolution does not depend on any one company's domain surviving.

### The namespaces

Two groups, and the division is what lets one implementation serve many organizations.

**Fixed, identical everywhere:**

| Prefix | Namespace |
|---|---|
| `sem:` | `https://w3id.org/semprini/ontology#` |

**Yours, chosen once at bootstrap:**

| Prefix | Namespace | Holds |
|---|---|---|
| `c:` | `{base}concepts/` | entities, attributes, terms |
| `r:` | `{base}relationships/` | relationships |
| `sch:` | `{base}schemes/` | glossaries and taxonomies |
| `v:` | `{base}values/` | taxonomy values |
| `x:` | `{base}ext#` | your own extension terms |

Semprini partitions your IRIs by **kind of thing**, never by business domain. Kinds do not
change. Domains reorganize every few years, and an IRI that named a domain would break when
they did. Which domain a concept belongs to is data — `skos:inScheme` — so you can move it
freely.

### Identity

`mappings/id-map.csv` records which source object owns which IRI. It has six columns: the IRI,
the kind, the source name, the source key, the date Semprini first saw the object, and a note
column that is yours to write in.

**The map is the authority, not the formula that fills it.** Semprini mints a new IRI with a
UUIDv5 rule, but once a row exists, the row wins. That is what lets you change codes, change
minting rules and upgrade the compiler without breaking a single link.

The file is **append-only**. Delete or edit a row and `semprini check` fails the pull request.
It is not a merge conflict to settle by picking a side — it is the guarantee that an IRI still
means what it meant three years ago.

When a source drops an object, Semprini does not delete it. It marks the object `deprecated`
and keeps it. If a steward records the replacement in `mappings/merges.csv`, the deprecated node
points at its survivor with `dcterms:isReplacedBy`, so links into it still lead somewhere.

Semprini decides what to deprecate from **all** your sources at once, never from one. That is
why a partial run — `semprini run --source product-category` — deliberately skips deprecation
outside its own scope.

### Determinism

Pull requests are the governance interface here. That only works if a diff is honest, so
`generated/` follows strict rules:

- a fixed prefix block, in a fixed order
- subjects and predicates sorted
- no blank nodes anywhere
- no timestamps, no comments, no run identifiers
- LF line endings, always

`semprini check` audits this rather than trusting it. It reads the committed RDF, re-serializes
it, and demands the same bytes back. So a hand edit that also recomputes the hash still fails.
Any change to this format is a **major** version bump, and it ships with a migration.

Semprini writes each object exactly once, in the file of its first scheme in alphabetical order,
even when the object belongs to several. Repeating it into every scheme's file would load to the
same graph, but one renamed label would then show up as four changed hunks instead of one.

### Validation

`semprini check` runs seven checks in this order, and writes nothing.

| # | Check | Fails when |
|---|---|---|
| 1 | syntax | a file under `generated/`, `overlays/` or `shapes/local/` will not parse |
| 2 | manifest integrity | somebody edited, added or removed a generated file by hand |
| 3 | version drift | a different release compiled `generated/` than the one now running |
| 4 | namespace lock | the configured base IRI no longer matches the frozen one |
| 5 | SHACL | the RDF breaks the core shapes, or your own local ones |
| 6 | identity | somebody deleted or edited a row in `mappings/id-map.csv` |
| 7 | determinism | a generated file is not the bytes the canonical serializer writes |

The cheap checks run first, and the slow SHACL run comes late. Check 6 needs a revision to
compare against. In CI it uses the pull request's base branch, and locally you pass
`--base <rev>`. Without one it reports itself as *not run* rather than passing quietly.

**Every check lives in the CLI, and none of them lives in the workflow files.** Both shipped
workflows install a pinned version and run one command. So porting Semprini to GitLab or Azure
DevOps means writing a few lines of YAML rather than reimplementing anything — and `semprini
check` reaches the same verdict on your laptop as it does in CI.

Your own rules go in `shapes/local/`. They may only add constraints. Semprini rejects a local
shape that switches a core one off, because your instance's data must keep answering to the
shared vocabulary.

### Adapters

Adapters are plugins. Semprini finds them through the `semprini.adapters` entry-point group, so
you add a new source system by installing a package and naming it in `config/semprini.yaml`. No
fork. No patch to this project.

Two adapters ship with the package today:

| Adapter | Reads |
|---|---|
| `ellie` | Ellie domain models, exported as JSON |
| `excel-taxonomy` | a taxonomy workbook, one file per taxonomy |

Both read files you commit to your own repository, which is why a compile needs no network
access and no credential.

Discovery imports nothing. Listing what is installed is a question about metadata, and answering
it by importing every plugin would run third-party code on every command. So one broken plugin
never hides the others.

Writing your own adapter is a supported path rather than a fork. See
[`docs/writing-an-adapter.md`](docs/writing-an-adapter.md).

### Versions and upgrades

The compiler and the ontology carry separate version numbers. `semprini version` prints both.

Your instance pins the compiler in three places: both workflow files and
`generated/.manifest.json`. When you install a new release, `semprini check` fails with a clear
message until you bring the instance across. That is deliberate. It stops a new release's
reformatting from arriving mixed into somebody's content change.

Upgrade in its own pull request:

```sh
pip install semprini==<new version>
semprini migrate --to <new version>
```

The migration rewrites `generated/` into what the new release would have written, **without
reading your sources**. So the diff shows the upgrade and nothing else. The migration refuses to
mint an IRI, refuses to lose a row from the identity map, and refuses to move a modification
date. Review the diff, run `semprini check`, then update the pinned version in both workflows.

Most releases change no output at all, and then the migration only restamps the version. Run it
either way. It costs nothing, and being wrong about which kind of release you are on is
expensive.

## Documentation

| Document | For |
|---|---|
| [`docs/rdf-repo-and-compiler-spec.md`](docs/rdf-repo-and-compiler-spec.md) | the authoritative specification — every rule in this README, in full |
| [`docs/writing-an-adapter.md`](docs/writing-an-adapter.md) | connecting a new source system |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | contributing to Semprini itself |
| [`CHANGELOG.md`](CHANGELOG.md) | what changed in each release |
| [`TASKS.md`](TASKS.md) | the build order, and what is done so far |

When this README and the specification disagree, the specification wins. Tell us, and we will
fix the README.

## Working on Semprini itself

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) first. It states the four things a contribution may
never do.

This repository uses [Poetry](https://python-poetry.org/) and commits `poetry.lock`. The
published wheel is plain, so nobody installing Semprini needs Poetry.

```sh
poetry install
poetry run pytest
poetry run ruff check . && poetry run mypy
```

Verify a change by breaking the code on purpose and checking that the suite notices:

```sh
python tools/mutate.py f3_validate --list
python tools/mutate.py f3_validate
```

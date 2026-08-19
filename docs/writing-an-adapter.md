# Writing an adapter

An adapter connects one source system to Semprini. It reads that source and hands back plain
objects. Everything else — identifiers, RDF, files, validation, history — stays on Semprini's
side.

**You do not need to fork Semprini, and you do not need our permission.** Adapters are ordinary
Python packages. Publish yours yourself, under any licence, on your own release schedule. The
two adapters that ship with Semprini use the same interface you are about to use, and they get
no privileges you do not get.

This guide walks through a complete working adapter, then explains each rule it follows.

## What an adapter must do

Four obligations. Semprini relies on all four, and the contract test suite checks all four.

| Obligation | Why |
|---|---|
| **Write nothing** | A run that fails halfway must leave the instance exactly as it was. That is impossible if your adapter already wrote something. |
| **Mint no identifiers** | You return source keys. Semprini looks them up in the identity map and decides what each object is called. |
| **Raise when the source fails** | Never return the part you managed to read. A partial model looks exactly like a source that shrank, and Semprini would deprecate everything missing from it. |
| **Contribute data only** | Return labels, definitions and structure. Never IRIs in the instance's namespace, and never terms of your own in `sem:`. |

## The interface

```python
class BaseAdapter(ABC):
    name: str  # the entry-point name, for example "ellie"

    def __init__(self, source_name: str, config: Mapping[str, Any], ctx: RunContext): ...

    @abstractmethod
    def fetch(self) -> InternalModel: ...

    def validate_config(self) -> list[Issue]:  # `semprini check` calls this
        return []

    def summary(self) -> str:  # one line for the run report
        return ""
```

Subclass it and set four things.

**`name`** is the entry-point name you register under. It must match exactly. An instance writes
`adapter: csv-glossary` in its configuration, so a class that calls itself something else would
make every error message name a thing nobody can find. Use lower case, digits, `-` and `_`.

**`__init__`** must stay cheap and free of side effects. Semprini constructs every configured
adapter during `semprini check` purely to call `validate_config()`, and that must not open a
connection. Do the work in `fetch()`.

**`fetch()`** reads the source and returns an `InternalModel`. Give every object at least one
source ref under `self.source_name`.

**`validate_config()`** checks your `config:` subtree without reading the source. Return every
problem, not just the first. An operator fixing a fresh configuration should not have to
discover the mistakes one CI run at a time.

Three things are handed to you:

| | What it is |
|---|---|
| `self.source_name` | the source's configured `name` — what goes into `sem:sourceRef` and the identity map |
| `self.config` | your `config:` subtree, passed through untouched, deeply read-only |
| `self.ctx` | what the run knows: `base_iri`, `instance_id`, `repo_root`, `default_language`, `only_source`, `dry_run` |

`self.ctx` carries no identity map. Minting is not something you can do by accident.

## A complete example

Here is a whole adapter. It reads a glossary from a CSV file with three columns: `key`, `label`
and `definition`.

Put it in `glossary.py`:

```python
"""A minimal adapter: one CSV file of glossary terms."""

from __future__ import annotations

import csv
from pathlib import Path

from semprini.adapters import BaseAdapter, SourceUnreachableError
from semprini.model import (
    Entity,
    InternalModel,
    Issue,
    Scheme,
    SchemeType,
    Severity,
)


class GlossaryAdapter(BaseAdapter):
    """A glossary held in one CSV file: key, label, definition."""

    name = "csv-glossary"

    _count = 0

    def validate_config(self) -> list[Issue]:
        issues: list[Issue] = []
        for key in ("path", "scheme_slug", "scheme_name"):
            if not self.config.get(key):
                issues.append(Issue(Severity.ERROR, f"{key} is required", key))
        path = str(self.config.get("path", ""))
        if path.startswith("/") or ".." in Path(path).parts:
            issues.append(Issue(Severity.ERROR, "path must stay inside the repository", "path"))
        return issues

    def fetch(self) -> InternalModel:
        path = self.ctx.repo_root / str(self.config["path"])
        try:
            rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
        except OSError as error:
            raise SourceUnreachableError(f"cannot read {path}: {error}") from error

        slug = str(self.config["scheme_slug"])
        scheme = Scheme(
            source_refs={self.source_name: slug},
            pref_label=str(self.config["scheme_name"]),
            slug=slug,
            scheme_type=SchemeType.GLOSSARY,
        )
        entities = tuple(
            Entity(
                source_refs={self.source_name: row["key"]},
                pref_label=row["label"],
                definition=row.get("definition") or None,
                schemes=(slug,),
            )
            for row in rows
        )
        self._count = len(entities)
        return InternalModel(entities=entities, schemes=(scheme,))

    def summary(self) -> str:
        return f"{self._count} terms"
```

Three details in there are worth naming.

The class docstring's first line appears in `semprini adapters`. Write one. Semprini leaves the
column blank rather than inheriting `BaseAdapter`'s sentence, because an inherited description
reads as the adapter describing itself.

`fetch()` raises `SourceUnreachableError` when the file will not open. That is exit code 3,
which CI treats as "retry later". Every other failure is exit code 1, which means a person has
to look. Keep the distinction sharp: a source that was down is not the same as a source that
answered with nonsense.

`summary()` reports what this fetch actually read. It lands in the run report next to the object
count, and it is where a reviewer notices that a file held 40 rows where it used to hold 400.

## Register it

Declare an entry point in the `semprini.adapters` group. In `pyproject.toml`:

```toml
[project]
name = "semprini-csv-glossary"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["semprini"]

[project.entry-points."semprini.adapters"]
csv-glossary = "glossary:GlossaryAdapter"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
py-modules = ["glossary"]
```

Install it and check that Semprini can see it:

```sh
pip install .
semprini adapters
```

```
csv-glossary    semprini-csv-glossary 0.1.0  A glossary held in one CSV file: key, label, definition.
ellie           semprini 0.1.0               An Ellie instance: exported domain models, one concept scheme each.
excel-taxonomy  semprini 0.1.0               A taxonomy workbook: one file, one concept scheme, a ragged label hierarchy.
```

Semprini refuses an entry point that does not import, does not yield a `BaseAdapter` subclass,
leaves `fetch()` unimplemented, or declares a `name` other than the one it is registered under.
It also refuses two installed packages that claim the same name, rather than picking one by
order — `adapter: csv-glossary` must not mean different things on a laptop and in CI.

Discovery imports nothing. Listing what is installed reads package metadata only, so one broken
plugin never hides the others. `semprini adapters` is the exception: it imports everything on
purpose, because "does this installation actually work" is the question it exists to answer.

## Run the contract test

**Do this before you ship anything.** Every obligation above is negative, which means a broken
adapter looks exactly like a working one until an instance has already committed the damage.

Semprini ships the contract as executable code. It needs no pytest and no base class to inherit,
so it runs under whatever your project already uses.

```python
from glossary import GlossaryAdapter
from semprini.testing import check_contract


def test_the_adapter_meets_the_contract():
    check_contract(
        GlossaryAdapter,
        settings={"path": "terms.csv", "scheme_slug": "glossary", "scheme_name": "Glossary"},
        unreachable={"path": "not-there.csv", "scheme_slug": "glossary", "scheme_name": "Glossary"},
    )
```

`check_contract` collects every violation instead of stopping at the first, then raises
`AdapterContractError` with all of them.

You supply two configurations, and **both are required**.

- `settings` makes your adapter work.
- `unreachable` makes its source impossible to read.

The second one is required on purpose. Every source can fail. An adapter nobody ever asked what
it does when its source is down is exactly the adapter that one day answers "deprecate
everything".

The write guard is a guard and not a proof. It intercepts the ordinary ways Python opens a file
for writing. An adapter determined to write around it can. An adapter that writes *by accident*
— a cache, a debug dump, a temporary file beside the source — gets caught, and that is the
failure this exists to catch.

## What you return

`fetch()` returns an `InternalModel`, which holds five tuples:

```python
InternalModel(
    entities=(),  # Entity
    attributes=(),  # Attribute
    relationships=(),  # Relationship
    schemes=(),  # Scheme
    taxonomy_values=(),  # TaxonomyValue
)
```

Every object shares these fields:

| Field | Meaning |
|---|---|
| `source_refs` | source name → that source's key for this object. **Required.** |
| `pref_label` | `skos:prefLabel`. **Required.** |
| `definition` | `skos:definition`. `None` and empty both emit no triple. |
| `alt_labels` | `skos:altLabel` — synonyms |
| `hidden_labels` | `skos:hiddenLabel` — misspellings and retired names |
| `scope_notes` | `skos:scopeNote` |
| `examples` | `skos:example` |

Each kind adds a little:

| Kind | Adds |
|---|---|
| `Entity` | `schemes`, `broader` |
| `Attribute` | `schemes`, `entity` |
| `Relationship` | `schemes`, `source`, `target` |
| `TaxonomyValue` | `schemes`, `code`, `parent` |
| `Scheme` | `slug`, `scheme_type`, `enumerates` |

Point at other objects with a `SourceRef(source, key)`, never with an IRI. Semprini resolves
those references after identity resolution, which is what lets two adapters describe the same
real-world concept and have it become one node.

A label may be a plain string or a `Text(value, language)`. A plain string means the source
stated no language, and Semprini applies the instance's configured default. A `Text` keeps the
language it carries.

## Choosing source keys

Your source key is half of what makes an IRI permanent. Semprini keys its identity map on
`(source name, source key)`, so the key you return must identify the same thing next year.

Prefer a key the source system guarantees: a UUID, a primary key, a stable code. Avoid anything
a user can retype. A key derived from a label re-mints an IRI the day somebody fixes a typo, and
the old IRI gets deprecated for no reason at all.

Two rules for the people configuring your adapter, both worth putting in your README:

- **A source's `name` is permanent.** Semprini writes it into every identity record.
- **A source's `name` must not mention the tool.** `product-category`, never
  `excel-product-category`. The day that content arrives in another format, a name that
  mentions the old tool forces a re-mint of everything in it.

## Errors and exit codes

| Raise | Exit code | Use it when |
|---|---|---|
| `SourceUnreachableError` | 3 | the source could not be read at all: a missing file, a refused connection, a server error |
| `AdapterError` | 1 | the source answered, and what it said cannot be compiled |
| `Issue` list from `validate_config()` | 2 | the configuration is wrong |

Validate your configuration before you read anything. Then a run that skipped `semprini check`
still fails with the offending key, rather than with a traceback — or worse, with an absolute
path quietly overriding the repository root.

Keep configured paths inside the instance repository. A file outside it is content nobody
reviewed, and reviewing the source alongside its generated RDF is the whole point of committing
sources.

## Should you upstream it?

Usually no, and that is not a brush-off.

Ship your adapter yourself. You keep your own release schedule, your own licence and your own
dependencies, and nobody waits on us to merge anything. The interface exists so that a
third-party adapter is never second-class.

The bundled adapters are simply the ones this project commits to maintaining and testing
forever. That is a burden, not a badge. If you believe your source system belongs in that set,
open an issue and let us talk about it.

Whichever way you go, read [`CONTRIBUTING.md`](../CONTRIBUTING.md). The four non-negotiables
apply to your adapter as much as to ours: your output must be reproducible, it must carry no
blank nodes, it must never change an existing IRI, and it must never smuggle a real
organization's content into a shared repository.

## Reference

- [`docs/rdf-repo-and-compiler-spec.md`](rdf-repo-and-compiler-spec.md) §5.2 — the adapter
  interface, in full and authoritative
- [`docs/rdf-repo-and-compiler-spec.md`](rdf-repo-and-compiler-spec.md) §5.3 — the two bundled
  adapters, as worked examples
- `semprini.adapters.base` — `BaseAdapter`, documented in place
- `semprini.model` — every class you return
- `semprini.testing` — `check_contract`, and what each check is for

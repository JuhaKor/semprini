# %%org%% — semantic layer

The business vocabulary of %%org%%, compiled into RDF and governed through pull requests.
Created by `semprini init` from [Semprini](https://github.com/JuhaKor/semprini) %%version%%.

Every IRI this repository mints lives under `%%base_iri%%`. That base is **frozen** — see
*Three rules* below.

## What is in here, and who writes it

| Directory | Written by | Holds |
|---|---|---|
| `generated/` | **the compiler, and nothing else** | the RDF: one file per scheme, plus a copy of the metamodel, a manifest of content hashes and the last run's report |
| `overlays/` | stewards, by hand | the only hand-written RDF: imported vocabularies, this organization's own `x:` terms, and axioms the sources cannot express |
| `sources/` | stewards | the source files themselves — exported models and Excel taxonomies — committed so that a source edit and its RDF are reviewed in one pull request |
| `mappings/` | the compiler, appending | which source object owns which IRI (`id-map.csv`), which objects a steward has merged (`merges.csv`), and the frozen base IRI (`namespace.lock`) |
| `shapes/local/` | stewards | extra SHACL rules for this organization, on top of the ones the compiler enforces — see the README there |
| `config/` | stewards | `semprini.yaml`: which sources this instance compiles |

## Three rules

**Never hand-edit `generated/`.** It is overwritten wholesale on every run, and
`semprini check` fails any pull request that edits it without the compiler. Something to
add by hand belongs in `overlays/`.

**The base IRI is frozen.** `mappings/namespace.lock` records it, and every command
refuses to run against a different one. Editing `base_iri` in `config/semprini.yaml` does
not move anything: the IRIs already minted stay where they are. Moving a whole instance to
a new base is `semprini run --force-namespace-change`, expected to happen once, if ever.

**`mappings/id-map.csv` is append-only.** It is what makes an IRI mean the same object for
ever, across renames, re-codings and compiler upgrades. A deleted or edited row is a
failing check, not a merge conflict to resolve by picking a side. Its `note` column is
yours to write in.

**Credentials are never written to `config/semprini.yaml`.** A source names an environment
variable and the value is read at fetch time; a token pasted into the file is refused.

## Working on it

```sh
pip install semprini==%%version%%

semprini check      # every validation, writing nothing — the same thing CI runs
semprini run        # fetch every configured source, compile, write generated/
semprini run --dry-run    # what a run would write, without writing it
semprini adapters   # which source adapters are installed
```

Both workflows in `.github/workflows/` pin the plane version above. Upgrading the compiler
is a deliberate edit to those files, reviewed like any other change.

## Reviewing a compile pull request

The scheduled compile opens one when — and only when — something moved. Its description is
`generated/.report.md`: what is new, what changed, what was deprecated, and which warnings
the run raised. The diff is the governance interface, so read it as prose: a renamed label
is one changed line, and an object that a source deleted appears as a status change to
`deprecated` rather than as a deletion.

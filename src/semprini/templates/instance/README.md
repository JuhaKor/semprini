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
pip install "semprini @ %%wheel_url%%"

semprini check      # every validation, writing nothing — the same thing CI runs
semprini run        # fetch every configured source, compile, write generated/
semprini run --dry-run    # what a run would write, without writing it
semprini adapters   # which source adapters are installed
```

Semprini is published as a release asset rather than through a package index, so it is
installed by URL: `pip install semprini` finds nothing, and no version this project has not
released can arrive here by accident. Both workflows in `.github/workflows/` install the
same version from the same address, each on a `SEMPRINI_VERSION` line of its own. Upgrading
the compiler is a deliberate edit to those two lines, reviewed like any other change.

### Upgrading the compiler

`semprini check` fails after an upgrade until this repository is brought to the new version,
and it says so: *"generated/ was compiled with compiler X, but Y is running"*. That is
deliberate — it stops a new release's reflow from arriving mixed into somebody's content
change. Bring it over in its own pull request:

```sh
# from https://github.com/JuhaKor/semprini/releases — the wheel attached to that release
pip install "semprini @ https://github.com/JuhaKor/semprini/releases/download/vNEW/semprini-NEW-py3-none-any.whl"
semprini migrate --to <new version>    # the same version; it refuses any other
```

Substitute the version for `NEW` in both places, then set `SEMPRINI_VERSION` to it in both
workflow files.

The migration rewrites `generated/` into what the new release would have written, **without
reading your sources**, so the diff is about the upgrade and nothing else. It will not mint an
IRI, lose an ID-map row or move a `dcterms:modified` date — it refuses rather than do any of
those — and `generated/.report.md` becomes a migration report saying what it did. Review the
diff, run `semprini check`, then update the pinned version in both workflow files.

Most releases change no output, and then the migration is only a restamp. Either way, run it:
it is the same command, and being wrong about which kind of release you are on costs nothing.

## Reviewing a compile pull request

The scheduled compile opens one when — and only when — something moved. Its description is
`generated/.report.md`: what is new, what changed, what was deprecated, and which warnings
the run raised. The diff is the governance interface, so read it as prose: a renamed label
is one changed line, and an object that a source deleted appears as a status change to
`deprecated` rather than as a deletion.

One thing to expect on a protected `main`, because it looks like a fault and is not.
GitHub does not run a workflow on a pull request its own token opened: it creates the run
and parks it, so `validate` reports nothing on a compile pull request and a required check
that never reports leaves the pull request unmergeable. Open the run from the **Actions**
tab and approve it, and the check runs and passes as usual. `compile.yml` has already run
`semprini check` on exactly these files before proposing them, so the approval is a click
rather than a judgement. To be rid of the click, give the pull-request step in
`compile.yml` a token of its own — a PAT or a GitHub App installation token — in place of
`${{ github.token }}`; the check then runs on the pull request itself, and the
`semprini check` step in that workflow becomes redundant.

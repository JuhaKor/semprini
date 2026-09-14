# Simplification candidates

A survey of the source tree taken on 2026-09-07, before the pilot (TASKS.md H1) starts.
Nothing here is implemented. Each item names the files it touches, the spec sections that
would change with it, and a rough size, so that a later session can pick one up cold.

The core idea is not in question and none of these touch it: deterministic canonical
Turtle, the ID map as the authority over minting, machine-owned `generated/` beside
hand-written `overlays/`, and a pull request as the unit of review. What follows is the
material *around* that core, in three forms — features built for futures that have not
arrived, the same invariant re-checked at several layers, and prose.

## The shape of the tree

| Measure | Value |
|---|---|
| Source lines under `src/semprini/` | 11,447 |
| Of which code | 5,811 |
| Of which docstrings and attribute docs | 3,162 |
| Of which comments | 663 |
| Test lines under `tests/` | 16,363 (928 tests) |
| Lines under `tools/` | 2,852 |
| Exception classes | 19 |
| Places that validate a scheme slug | 5 |
| Occurrences of `Path.cwd() if repo_root is None` | 17 |
| Occurrences of `X if Y is None else Z` | 48 |
| Definitions of `_count(number, noun)` | 3 |

Measured with a small `ast`/`tokenize` script over the source tree; re-run it after any of
the work below to see what moved.

## Why now

No instance exists yet. Every item in section A is a behaviour the spec currently promises,
and removing a promised behaviour after an organization holds data under it is a migration
(spec §7). Before H1 it costs a regenerated fixture and a spec edit. H0 was scheduled ahead of
the pilot for exactly this reason, and the same reasoning applies here.

---

## A. Speculative features

Built for a future the project has not reached. Each is spec-mandated today, so the spec
section changes in the same PR (CLAUDE.md: a behaviour change edits the spec in the same
change).

### A1. Partial runs: `--source <name>`

The single largest source of intricacy in the compiler. It exists so that one source can be
recompiled without fetching the others, and everything outside the fetched scope must then
be carried forward verbatim rather than deprecated.

What it drives:

- `lifecycle.py`: `_verbatim`, `_ends`, `_derivable`, `_retained_shortcuts`, the
  `frozen_pairs` / `handled` bookkeeping in `plan()`, and the `fetched` scope test.
- `build.py`: `_Builder._check_partial_scope`, and the "objects two sources describe"
  refusal.
- `model.py`: `RunContext.only_source`.
- `config.py`: `InstanceConfig.run_context()` validating `--source` against the roster.
- `cli.py`, `run.py`: the flag, the refusal to combine it with a namespace move.
- Tests: about 25 references across `test_lifecycle.py`, `test_build.py`, `test_run.py`.

Why it is not earning its keep: both bundled adapters read committed files, so a full
compile costs seconds, and a full compile is the only way deprecation is ever judged
correctly (spec §5.4 says so). The spec's own note — "loosening this later is easy, and
tightening it once instances hold files built under a guess is not" — cuts the other way
too: adding the flag back later is easy.

Without it, `lifecycle.plan()` reduces to: every subject in the previous output that no
object in the model resolves to is deprecated, keeping its file and statements, with the
merge register supplying `dcterms:isReplacedBy`. The `sem:relatesTo` retention rule
disappears entirely, since the build stage re-derives every shortcut from a full model.

Spec: §5.1 (the `--source` paragraph), §5.4 ("Scope" and the shortcut paragraph), §6.1
check 6's mention. Estimated removal: 300–400 source lines, 1,000+ test lines.

### A2. Moving the base IRI: `--force-namespace-change`

Spec §3.4.4 calls it "expected to be a once-ever event". It carries:

- `identity.py`: `plan_namespace_change`.
- `run.py`: `_move_namespace`, `_rebased`, `_rebased_term`, the write-ordering comments about
  lock-after-map.
- `lifecycle.py`: `MergeRegister.rebased`, `_rebased_iri`.
- `cli.py`: the flag and the bypass in `_load_config`.
- Tests: about 16 references in `test_run.py` and `test_identity.py`.

Alternative: document that the base IRI is permanent and that an organization wanting a new
one creates a new instance. Or keep the rebase as a documented manual procedure (three
`sed` invocations over `mappings/` and `generated/`, then a normal compile). Estimated
removal: about 250 source lines.

Spec: §3.4.4, §5.1 (the flag).

### A3. Credential handling in configuration

`config.py` carries `_reject_inline_credentials`, `_scan_for_credentials`,
`_key_segments` (with camelCase splitting), `_CREDENTIAL_WORDS`, `_CREDENTIAL_PAIRS`,
`_suggested_variable`, `_is_variable_name`, and `SourceConfig.secret()`. The Ellie adapter
adds a bespoke error for a `token_env` key it does not read.

Evidence that nothing needs it yet: `.secret()` has no caller outside `tests/test_config.py`
(25 test references to credentials there); `requests` is a declared dependency
(`pyproject.toml`) imported nowhere under `src/`, `tools/` or `tests/`.

Alternative: keep the rule as one sentence in the spec and the instance README ("a
credential is named by an environment variable, never written into configuration"), and add
the guard with the first adapter that calls a network service. Drop `requests` from
dependencies until then. Estimated removal: about 150 source lines.

Spec: §5.1 (the credentials paragraph — keep the rule, drop "this is enforced").

### A4. The migration framework

`src/semprini/migrate/` is 942 lines and `MIGRATIONS = ()`. What `semprini migrate` does
today is: refuse a manifest mismatch, re-serialize every committed graph, refresh the
ontology copy, restamp the manifest, write a migration report. The snapshot-and-four-refusals
machinery in `apply.py` (`_Snapshot`, `_check_identity`, the row-order check,
`_notes_changed`), the `registry.py` planner, and the `MigrationReport` renderer all guard
steps that do not exist.

Alternative: keep `migrate --to` as the re-serialize-and-restamp it currently is, in about
fifty lines beside `run.py`, and reintroduce the step registry and the identity guards in
the release that ships the first real step. G3's verification (the mutation battery in
`tools/mutations/g3_migrate.py`) can be restored from git history at that point.

Spec: §7 keeps its promises about what a migration may not do; the "enforced" sentences
move to the release that enforces them. Estimated removal: 600–700 source lines, most of
`tests/test_migrate.py` (1,181 lines).

### A5. Reserved prefixes and classes in the output

- `serialize.py` emits `a:` (`assets/`) and `d:` (`docs/`) in every file's prefix block
  "reserved for later versions". No triple uses them; `x:` is emitted too and no generated
  triple can use it by rule.
- `validate._IRI_POLICY_TARGETS` and `shapes/core.ttl` target `sem:BusinessTerm`, which the
  builder never emits and no adapter produces.

Removing a prefix from the canonical block after an instance exists is a serialization
change, hence a major version and a migration (spec §7). Removing it now costs one
regeneration of `tests/fixtures/acme/generated/`. Spec §3.1 and §5.5 rule 1 change.

### A6. The adapter contract checker and its write guard

`testing.py` (502 lines) ships in the wheel for third-party adapter authors. It does real
work for the two bundled adapters' own tests, so it is not dead. The part worth questioning
is `_no_writes`, which monkeypatches `builtins.open`, `io.open`, `os.open` and six `os`
calls to record writes. A `tmp_path` snapshot before and after `fetch()` catches the same
accidental writes with a tenth of the code and no global patching. Low priority; note it
for when `testing.py` is next touched.

---

## B. Duplication and layered defence

Mechanical refactors that change no behaviour. Best done under the mutation batteries.

### B1. One error class

Nineteen exception classes. Fifteen subclass `IssueError` and differ only in `noun`
(`ConfigError` → `NamespaceLockError`, `ScaffoldError`; `IdentityError` → `BuildError`;
`LifecycleError`, `ManifestError`, `MigrationError`, `ValidationError`,
`AdapterContractError`, `SourceConflictError`). `cli.exit_code_for` distinguishes exactly
three outcomes. One `SempriniError(issues, *, noun, exit_code)` replaces them, with
`SourceUnreachableError` kept distinct for exit 3 and `MergeConflictError` kept as the
internal signal it is.

Touches every module; see `grep -rn 'class .*Error' src/semprini`.

### B2. One kind table

Adding a kind today edits eight tables:

| Table | File |
|---|---|
| `_KIND_PREFIXES` | `model.py` |
| `_INSTANCE_SUFFIXES` | `serialize.py` |
| `_CLASSES` | `build.py` |
| `_file_name()` prefixes | `build.py` |
| `_IRI_POLICY_TARGETS` | `validate.py` |
| `LOCAL_NAME_PATTERNS` | `validate.py` |
| `_CLASS_NAMES` | `report.py` |
| `_WANT_DEFINITIONS` | `report.py` |

A single `Kind` enum carrying prefix, namespace suffix, file-name prefix, RDF class,
local-name pattern, display name and wants-definition collapses them.

### B3. One CSV register base

`IdMap` and `MergeRegister` each implement `load`, `loads`, `_row_from_csv`, `dumps`, `save`
with the same structure, the same `utf-8-sig` handling, the same header check and the same
"trailing blank line" branch. The `utf-8-sig` rationale comment appears eleven times across
the tree. One `CsvRegister` base with a row type and a column tuple removes about 150
lines.

### B4. Require the repository root

`Path.cwd() if repo_root is None else Path(repo_root)` appears seventeen times, and the
`repo_root: Path | None = None` convention is on nearly every `load`/`save`/`read`.
`InstanceConfig.repo_root` already exists and the CLI already resolves it once. Make the
root a required positional argument below the CLI layer and delete the defaulting.

### B5. Stop threading test pins through every signature

`compiler: str | None`, `ontology: str | None` and `today: datetime.date | None` are
injected through `run.run`, `build.build`, `report.create`, `Manifest.create`,
`validate.check`, `migrate.migrate`, `scaffold.create` and `Registry.__init__`, solely so
`tools/build_fixture_instance.py` can pin the fixture's versions and date. One small
`Environment` object (versions plus a clock) built once by the CLI, or one module-level
override the fixture builder sets, replaces every one of those parameters.

### B6. Validate at the boundary, then trust

The same invariant is checked at several layers, each with its own message:

- **Scheme slug**: adapter `validate_config()` (both adapters), `identity._checked_slug`,
  `build._scheme_index`, `manifest.is_generated_file_name`, and the SHACL IRI-policy shape.
- **Namespace lock**: `cli._load_config`, then `Registry.load`, then `validate.check`. Three
  times per `run` or `check`.
- **Path escape**: `config.escapes_the_instance` in both adapters, `is_generated_file_name`
  in both `Manifest.__post_init__` and `manifest._files`, and again in
  `migrate.apply._rendered`.
- **Empty text**: `Text.__post_init__`, `_has_content`, `_as_optional_text`,
  `SemanticObject.__post_init__`, plus each adapter's own `_plain` / `_cell` /
  `_optional_text`. A string is normalized up to three times on the way in (adapter, then
  `Text`, then `SourceRef`), which is also why `counting_normalizations` needs a context
  variable to count only the first change.

Check each once where the value enters (adapter configuration for slugs and paths, the CLI
for the lock, `Text`/`SourceRef` for text) and remove the later layers.

### B7. Runtime checks on the project's own output

These guard one stage of this codebase against another, in the same process, on every run:

- `build._Builder._check_carried_are_gone` — lifecycle handed build a node the model also
  holds.
- `build._Builder._check_nothing_is_written_twice` — build's own partitioning put one
  triple in two files.
- `migrate.apply._applied` — a step returned something other than an `InstanceState`,
  under `mypy --strict`.
- `manifest.Manifest.create` — the caller passed the manifest to itself.

Each is a test, not a runtime check. Convert to `assert` or move into the suite.

### B8. Test-only public API

No caller under `src/` or `tools/`: `serialize.write`, `build.read_previous`,
`InternalModel.merge`, `validate.read_local_shapes`. `_count` is defined in `run.py`,
`validate.py` and `migrate/apply.py`. `_root` in `validate.py` duplicates the B4 pattern.

### B9. Smaller structural candidates

- **Additive-only shapes** (`validate.check_additive`, about 200 lines with its helpers).
  Four refusals; the first (no statement whose subject is in the `sem:` or `shp:`
  namespace) carries nearly all the value. Refusals 2–4 (no-op constraint parameters,
  `sh:rule`, references to core shapes) defend against adopters who have not appeared.
- **Git base discovery** for check 6 (`_base_id_map`, `_base_revision`, `_base_candidates`,
  `_git`, `_git_output`, `--show-prefix` for monorepos; about 100 lines). Requiring
  `--base` and having `validate.yml` pass `${{ github.event.pull_request.base.sha }}`
  removes the discovery and the "not run" state with it. Spec §6.1 check 6, §6.3.
- **Three block types for "statements about a subject in a file"**: `lifecycle._PreviousBlock`,
  `build._Block`, `build.CarriedNode`. One type would do once A1 is gone.
- **Two result/report pairs**: `RunResult`/`RunReport` and `MigrationResult`/
  `MigrationReport`. Moot if A4 is taken.
- **Deterministic issue ordering**: `Issue.sort_key`, `validate._sort_key`, and the
  set-then-sort idiom at every collection point. Keep one sort at the render point in
  `CheckResult.summary` and drop the rest.

---

## C. A real inconsistency — **done**

Three docstrings (`adapters/base.py` on `__init__` and `validate_config`,
`adapters/discovery.py` on `create`, `model.py` on `Issue`) say `semprini check` constructs
every configured adapter to call `validate_config()`. It does not: `validate.py` never
imports `adapters`, and `adapters.create` has one caller, in `run._fetch`. Each bundled
adapter compensates by calling its own `validate_config()` at the top of `fetch()`.

**Resolved by making `check` do what the docstrings claim.** `semprini check` now has an
eighth check, *source configuration* (spec §6.1 check 8): it constructs every configured
adapter and collects `validate_config()`. The in-`fetch` calls stay — spec §5.3 requires an
adapter to validate its own settings before reading anything, so a run that skipped `check`
still fails with the offending key. Battery: `tools/mutations/c_source_config.py`.

---

## D. Prose

- `src/semprini/` holds 3,825 lines of docstrings and comments against 5,811 of code. Most
  argue design rationale at line level and cite spec sections (`validate.py` alone cites
  "spec" 77 times). The spec is authoritative already, so the argument is duplicated, and
  it rots when code moves — the mutation batteries exist partly to catch that rot.
  Trimming docstrings to the contract (what it takes, what it returns, what it raises) and
  pointing at the spec for the why would remove roughly a quarter of the tree with no
  behaviour change. Attribute docstrings explaining `hash=False` are repeated on four
  dataclasses; one sentence in a shared place covers them.
- `TASKS.md` is 3,048 lines, most of it completed phases. Archive A–G into
  `docs/history/` and keep the open pilot tasks and decision gates at the top level.

---

## Suggested order

1. ~~**C** — the `validate_config` inconsistency.~~ Done: check 8, spec §6.1.
2. **A1–A5**, one PR each, spec edits included, while no instance holds data. A1 first: it
   is the largest and it simplifies lifecycle and build for everything after it.
3. **B1, B2, B3** as mechanical refactors under the mutation batteries
   (`python tools/mutate.py <battery> --list` first; anchors will move).
4. **B4–B9** opportunistically, whenever the file in question is open for another reason.
5. **D** last, since it is safe at any time and easiest once the code has settled.

After A1 and A4 land, re-run the line count. The expectation is a source tree near 7,000
lines and a test suite near 11,000, with every core guarantee (determinism check, ID map
append-only, manifest integrity, no blank nodes, deprecation-not-deletion) unchanged.

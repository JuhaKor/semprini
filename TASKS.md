# TASKS.md — implementation plan

Build order for Semprini. One task per working session; each is
independently implementable and verifiable, and later tasks assume earlier ones are
done and green.

**How to use this file**

- `docs/rdf-repo-and-compiler-spec.md` is authoritative. Tasks name the sections they
  implement and deliberately do not restate them. If a task and the spec disagree, the
  spec wins; if the spec turns out to be wrong, fix the spec in the same change.
- Work tasks in order unless a task says otherwise. Tick the box, and record anything
  the next session needs to know (deviations, discovered constraints) under the task.
- **Verify** is the definition of done. A task is finished when its verification is
  automated and passing in the plane's own test suite — not when the code exists.
- Some tasks are blocked by an open decision from spec §11; those are listed under
  *Decision gates* at the end.
- Completed phases A–G are archived verbatim in `docs/history/tasks-phases-a-g.md`,
  with the sequencing notes written while they were open. This file holds only what
  is still open. A task there is history; do not reopen one by editing the archive.

---

## Phase H — Pilot

- [x] **H0 · Text normalization at the model boundary**
  **Spec:** §5.5 (a new rule 9), §5.2 (the `fetch()` contract), §5.4 (what a source key
  is), §5.6
  **Deliver:** one normalization function, applied to every text and every source key on
  the way into the internal model, plus the spec rule that licenses it. Numbered ahead of
  H1 because it is a correction to Phase B and D code rather than new capability, and
  because it has to land **before an instance holds data**: an invisible character in a
  `Concept URI` cell becomes a source key, and a source key becomes a frozen ID-map row
  (§5.4). Today that is free to fix; after H1 it is somebody's permanent IRI.

  **What was found.** Definitions compiled from an Excel taxonomy contain U+00A0 (NBSP)
  where the workbook appears to hold an ordinary space. Nothing in the pipeline creates
  one, so it is in the source — Excel reliably carries text pasted out of Word, a browser
  or a PDF. It survives because `_cell()` uses `str.strip()`, which removes NBSP at the
  *edges* only (`'\xa0'.isspace()` is `True`), and because `serialize._escape()` escapes
  U+0000–U+001F and U+007F and nothing else, so U+00A0 reaches the `.ttl` as raw bytes.

  **Why it is not cosmetic.** Three consequences, and only the first is obvious:

  - *The diff lies.* PR diffs are the governance interface (§1.2). A literal differing
    only by NBSP renders identically on GitHub: a reviewer sees a line marked changed with
    nothing visibly changed, and no way to find out why. For a repository whose whole
    review model is "read the diff", that is the worst available failure mode.
  - *It splits the ragged hierarchy, invisibly.* `_Row.path` matches on label values, so a
    parent whose L2 cell holds `Power\xa0Tools` and a child whose L2 cell holds
    `Power Tools` produce *"is narrower than 'Power Tools', which no row defines"* against
    two cells that look identical in Excel. This is exactly the defect D2 already found
    and fixed once for `"Tools"@en` versus bare `Tools` — the same class, with no visible
    tell at all. D2's lesson holds and extends: **a value that is parsed for one purpose
    must be parsed before it is used for another**, and *parsed* has to include
    *normalized*.
  - *It reaches identity.* An interior NBSP in a `Concept URI` cell yields a different
    source key, hence a different `uuid5(slug|key)`, hence a different IRI — frozen into
    `mappings/id-map.csv` on the run that mints it. Labels never feed minting
    (`identity.mint_local_name`), so prose is identity-safe; **keys are not**, and that is
    what makes this a task rather than a backlog note.

  **What to normalize, in this order** — fixed so the function is idempotent, which is the
  property that keeps recompiles byte-identical (§6.1.7):

  1. **NFC.** Argued for on its own merits, not as a side effect: composed versus
     decomposed `ä`/`ö` is the identical invisible-diff bug with a far wider blast radius,
     and this project's examples are Finnish. NFC is idempotent and changes nothing that
     renders differently. **Not NFKC** — that would fold ligatures, superscripts and units,
     which is real content damage.
  2. **Map to U+0020** every character in Unicode general category `Zs` other than U+0020
     itself, plus `Zl` and `Zp` (U+2028, U+2029). Derived from the category rather than
     enumerated, so it does not rot — but **pin the derived set in a test** as an explicit
     literal, so that a Python or Unicode-data upgrade which changes it is visible rather
     than silent.
  3. **Delete** U+200B (ZWSP), U+FEFF (ZWNBSP/BOM) and U+00AD (soft hyphen). Nastier than
     NBSP: `strip()` does not touch them even at the edges, so today they survive at *both*
     ends of a literal. **Do not delete U+200C/U+200D** — ZWNJ and ZWJ are meaningful in
     Indic and Arabic script and in emoji sequences.
  4. **Strip** again, since steps 2 and 3 can expose new edge whitespace.

  Deliberately **out of scope**, and say so in the spec rule rather than leaving it to be
  rediscovered: U+2011 non-breaking hyphen (an orthographic choice, not an artefact); tabs
  and newlines inside a cell (real, and the serializer already writes them visibly as `\t`
  and `\n`); and collapsing interior runs of whitespace. That last one is the arguable
  sub-decision — NBSP→space can leave a double space — and the case against is that a
  double space is at least *visible*, while collapsing also rewrites text somebody spaced
  deliberately. Leave it out; revisit only with an example that argues for it.

  **Where it goes.** In `model.Text` — `__post_init__`, with `object.__setattr__` since the
  dataclass is `frozen=True, slots=True` — and **not** in `excel_taxonomy._cell()`. Three
  reasons: Ellie carries the same pasted-from-Word prose, so fixing one adapter leaves the
  other broken; a third-party plugin author must not have to know that NBSP is a hazard,
  which is the extension-without-forking rule (§5.2) doing its job; and it fixes
  `_Row.path` matching for free, since the path is built from `Text.value`. `Text` already
  normalizes on construction (empty rejected, language tag validated), so this is what the
  type is for. The counter-argument — §5.2 assigns normalization to adapters — is real but
  not decisive: this is a property of the type, not of any one source.

  Three boundaries `Text` does **not** cover, and each needs the same function applied
  explicitly:

  - **Source keys.** `excel_taxonomy._local_name()` and the Ellie adapter's key handling.
    This is the identity-bearing one; it is also the one an adapter contract check can
    give teeth to.
  - **Header and property-name matching.** `_normalize_header()` lower-cases and strips.
    Header matching is strict by design (D2) and refuses the whole workbook, so a header
    typed `Concept\xa0URI` fails a taxonomy for a reason no one can see in the sheet.
  - **Emptiness.** Normalization has to happen where emptiness is *decided*, not after.
    `_as_optional_text()` treats an empty string as absent before constructing anything, so
    a cell holding only U+200B is truthy today, and would raise `ValueError` from
    `Text.__post_init__` once normalization empties it. It must become **absent**.

  Slugs, source names and language tags need nothing: `is_slug` and `is_language_tag`
  already reject every character on the list.

  **Reported, not silent.** Count normalizations and surface the count in the run report
  (§5.6) — a run with nothing to normalize says nothing. Not an issue per cell: the fix
  lives in a binary `.xlsx` a steward may not own, so it would be permanent noise. Not
  fully silent either: a compiler that quietly edits a source's words with nothing anywhere
  saying so is how people stop trusting a compiler.

  **No migration, deliberately.** Nothing is in production and no instance holds real data,
  so this ships as an ordinary minor release with no §7 step — the fixture instance's
  generated Turtle is simply regenerated and committed. Recorded because it is not the
  general answer: §7 forbids a migration from reading sources, so once instances exist this
  same fix could only ever arrive through a normal recompile PR, with an invisible diff and
  a `dcterms:modified` bump on every affected node. That is the fact that makes doing it
  now cheap and doing it later expensive.

  **Verify:**
  - Unit tests per rule: each character class mapped, deleted or preserved; U+2011,
    U+200C, U+200D, tab and newline untouched; decomposed `ä`/`ö` composed by NFC; and
    `normalize(normalize(x)) == normalize(x)` over a mixed corpus.
  - The pinned-set test above fails loudly if the derived `Zs`/`Zl`/`Zp` set changes.
  - Excel: a parent whose level cell uses NBSP and a child whose matching cell uses a space
    compile into **one** branch — the NBSP counterpart of
    `test_a_branch_spelled_two_ways_is_still_one_branch`.
  - Excel: a header written `Concept\xa0URI` is matched, not refused.
  - Identity: a `Concept URI` carrying an NBSP mints the same IRI as the clean spelling,
    and does so *before* the ID map is written — assert on the map row, not only on the IRI.
  - A cell containing only U+200B yields an absent field, not an error and not a
    one-character literal.
  - Ellie: the same guarantee through its own fixture, proving the fix is not adapter-local.
  - The fixture workbook gains a definition that deliberately carries an NBSP, so the
    committed instance exercises this rather than only the unit tests;
    `tests/fixtures/acme/` recompiles byte-identically and mints nothing new.
  - `testing.py`'s adapter-contract suite gains the check, and G4's worked example adapter
    still passes it.
  - The run report shows the count when there is one and stays silent when there is not.
  - Spec updated in the same change: §5.5 rule 9 is the rule's home, with a sentence in
    §5.2 and a note in §5.4 that a source key is normalized before it is a key.
  - A battery at `tools/mutations/h0_normalize.py` — at minimum: NFC dropped, one character
    class dropped, deletion done as a space-map, normalization applied after the empty check
    rather than before, keys left unnormalized, headers left unnormalized, the report count
    not reported, and the function made non-idempotent.

  **Depends:** B2, D2, D3 — all done. **Blocks H1.**

  **Done.** 1071 tests green (34 of them H0's); ruff, ruff format and mypy (strict) clean; the
  wheel installs into a bare venv with pip and `semprini check` passes there on the fixture
  instance. Twenty-five mutations were checked against the suite, twice — nothing normalized at
  all, composition dropped, NFD instead of NFC, NFKC applied, only U+00A0 mapped, the invisible
  characters spaced rather than deleted, ZWJ deleted too, the trailing strip dropped,
  normalization made non-idempotent, a text and a key each normalized after emptiness is judged,
  absence decided on the raw string, an object's stored keys left raw while its refs are
  normalized, a spreadsheet cell and a header each left unnormalized, a row judged blank on its
  raw cells, an Ellie field left unnormalized, a model id matched before normalization, a
  notation left unnormalized, the contract check switched off, the count never incremented,
  every value counted, the count never reported, reported when there was nothing to report, and
  the tally shared across sources instead of reset per source — and each fails it.

  **The battery found the two tests that were missing**, which is the whole reason it exists: a
  row of nothing but invisible characters, and an export whose `modelId` (rather than the
  *config*'s id) carries one. Both mutations survived the first run against a suite that already
  had eleven normalization tests in it.

  **The fixture instance carries the characters and compiles to byte-identical output.** That is
  the guarantee stated as an artefact rather than as prose: `product-category.xlsx` now holds an
  NBSP in a level cell that would split the power-tools branch, a soft hyphen inside
  `ont:Sanders` that would mint a second IRI, and an NBSP in prose — and `generated/`, the
  manifest, the report and the ID map are unchanged, byte for byte, from what was committed
  before this task. `test_the_fixture_workbook_carries_invisible_characters_on_purpose` is what
  stops a later regeneration from quietly dropping them and leaving the guarantee untested.

  Notes for later sessions:

  - **Two gaps found while implementing, beyond the reported one.** `skos:notation`
    (`TaxonomyValue.code`) is a plain string that reaches a literal without passing through
    `Text`, and was unnormalized; and `_read_row` normalized the identity cell twice, because
    the blank-row check re-read the raw row. The second was only visible because the run report
    counts — a count is a weak assertion about behaviour and turned out to be a sharp one about
    structure. `_read_row` now reads each cell once, into a list.
  - **The count is per source and lives in `SourceSummary.note`**, filled by `run._note`. The
    honest consequence, written into `tests/test_run.py::_source_notes`: a report is not
    rewritten when nothing moved (§5.6), and normalization by design moves nothing — so a
    steady-state compile of a source full of invisible characters says nothing at all, and the
    note is read on the compile that changes something else. Judged the right trade against a
    warning that would fire forever on a binary file the steward may not own.
  - **`counting_normalizations()` is a `ContextVar`, and report-only.** Nothing it observes
    reaches the output, so a caller that never counts compiles the same bytes as one that does
    — pinned by `test_counting_changes_nothing_about_the_result`. It counts only values the
    function actually changed, so merging (which re-normalizes routinely) adds nothing.
  - **`_SPACES` is pinned, not derived at import.** Deriving it means walking the whole code
    space. `test_the_space_set_is_exactly_what_unicode_calls_a_separator` re-derives it from
    `unicodedata` and demands the pinned set back, so a Python or Unicode-data upgrade that
    changes the answer is a failing test. Current answer is Unicode 16.0.0's 19 characters.
  - **Write the escapes, never the characters.** Both `model.py` sets and every test are written
    as `\uXXXX`. A source file that contained the literal characters would be a file no reviewer
    could check — the exact failure this task is about, committed into the fix for it.
  - **`build_fixture_workbook.py` had drifted from the workbook it claims to generate.** The
    script wrote a blank `Reference Entity UUID`; the committed `.xlsx` had it filled in by hand
    when D3 landed, so regenerating silently dropped `sem:enumerates` from the fixture. Fixed
    here — the script now writes the UUID — and worth knowing that the drift was invisible until
    something regenerated the workbook, since nothing compares the two.
  - **No migration ships**, because no instance holds data (§7 forbids a migration from reading
    sources anyway). Recorded in `CHANGELOG.md` under Unreleased, including the part an adopter
    would feel if this shipped later: literals lose the invisible character and `dcterms:modified`
    moves on the nodes affected, in an ordinary compile PR whose diff shows nothing.

- [ ] **H1 · First instance bootstrap**
  **Spec:** §5.7, §6.2, §9.1
  **Deliver:** a real instance repository for the pilot organization: base IRI decided,
  Ellie allowlist populated one validated model at a time, stewards and CODEOWNERS
  assigned, branch protection on.
  **Verify:** the scheduled compile opens a PR whose report a steward can review
  unaided; a deliberate source change appears as a readable diff on the next run; main
  is tagged per §9.1 rule 7.
  **Depends:** D3, G5, H0

- [ ] **H2 · Point the local flow at the run report**
  **Spec:** §5.6 — the report is unchanged; only who gets told about it moves.
  **Deliver:** `semprini run`'s console summary ends by naming `generated/.report.md`, the
  New/Changed/Deprecated counts it holds, and the one line that turns it into a pull request
  description — `gh pr create --body-file generated/.report.md`, which is exactly what
  `compile.yml` already does. No subcommand is added: `semprini report` would be `cat` with
  a §5.1 surface change behind it.
  **Why:** §5.6 calls the report "the reviewer's summary", and every run writes it, local
  ones included — but only `compile.yml` has ever used it. A steward who compiles locally
  and opens a pull request by hand is holding that summary inside their own commit with
  nothing to tell them it is there, and reviews a source edit, several Turtle files and a
  manifest as one undifferentiated diff. Cheap, and it helps whichever way H3 goes.
  **Verify:** a test asserts the summary names the report path, the three counts and the
  `gh` line after a run that wrote something, and names none of them after a `--dry-run` or
  a run that changed nothing — a no-op rewrites no report (§5.6) and leaves nothing to
  propose, so pointing at the committed one would invite a pull request describing a run
  that did not happen.
  **Depends:** nothing. Worth landing before H1's stewards start rather than after.

- [ ] **H3 · Decide who compiles a source change**
  **Spec:** §1.2, §4.2, §6.2, §6.3 — a decision here edits all four in the same change.
  **The question:** an instance ships two steward flows and documents neither as the
  primary one. A steward can compile locally and commit the source and its Turtle together
  (§4.2), or commit the source alone and let the scheduled compile propose the Turtle in
  its own pull request (§6.2). Both work. They are governed differently, and the difference
  is written down nowhere an adopter would find it.

  **Established while framing this (2026-08-28), and worth not rediscovering:**
  - **The scheduled compile is a no-op on a v1 instance whose sources have not changed.**
    Both bundled adapters read files under `sources/`; Ellie's `base_url` is provenance —
    which instance the UUIDs belong to — and fetches nothing (`adapters/ellie.py`). Nothing
    in the output is time-driven either: `dcterms:modified` is carried from content rather
    than stamped per run (`build.py`), and deprecation fires on absence from sources, not
    on a clock. So `compile.yml` today can only ever find work where someone committed a
    source without recompiling. It is infrastructure for the Ellie API mode, shipped ahead
    of it — not a check on stewards.
  - **Nothing compares `generated/` to `sources/`.** None of §6.1's checks recompiles
    from the sources, so a source committed without a recompile passes CI clean. Under the
    §4.2 flow that is a real hazard with no mechanical guard; under a compile-in-CI flow it
    cannot arise at all.

  **The trade-off, recorded:**
  - **Source and Turtle in one pull request** — the flow §4.2 already justifies. One review
    sees cause and effect, and that matters most where it is least visible: an `.xlsx`
    taxonomy is a binary blob in a diff, so the generated Turtle beside it is the only
    reviewable account of what the workbook edit did. Costs: the steward needs Python and a
    pinned Semprini install, and a forgotten recompile is silent.
  - **Source only, compile follows on schedule.** The steward needs no Python at all — a
    real widening of who can take part — and the stale-compile hazard disappears. Costs:
    whoever approves the workbook approves a change whose effect they cannot see, and that
    effect arrives days later as a bot pull request, plausibly to a different reviewer,
    where the natural reading is "the machine did what machines do" rather than "did we
    mean this?". §1.2 makes the pull request diff the governance interface, and this
    separates the diff from the decision that caused it. Between the two merges, `main`
    also holds sources that `generated/` does not describe, and no check notices.
  - **Compile on the source pull request's own branch** — the option that is not a
    compromise. CI compiles against the branch and pushes `generated/` into that same pull
    request: one review, cause and effect together, no local Python. Costs to design around
    rather than wave away — the push needs a credential that is not `GITHUB_TOKEN`, or the
    pushed commit contributes no `validate` run (the parked `action_required` mechanism
    §6.2 already documents); the reviewer waits for the bot before reviewing; a fork's pull
    request cannot do it, which is likely fine for an internal instance. It is a third
    workflow, not an edit to `compile.yml` — the dated branch and force-push there solve a
    different problem. The weekly schedule then keeps only the job it was built for,
    upstream drift, and stays a cheap no-op until the API adapter lands.

  **For whoever picks this up:** do not settle it on this repository's own reasoning. H1 is
  the evidence — whether the pilot's stewards can install Python decides most of it — and
  the Ellie API mode forces the question anyway, so designing both cases together costs
  less than designing them twice.
  **Deliver:** the decision, written into the spec sections above in the same change; one
  flow named as primary in `templates/instance/README.md` with the other stated as the
  exception; and whatever workflow the decision implies.
  **Verify:** if the flow stays as §4.2 has it, a test that the instance README names one
  primary flow, and nothing else changes. If the compile moves into CI, a scratch instance
  on GitHub where a source-only pull request gains its Turtle from the workflow and
  `validate` reports on the pushed commit — the same real-instance run G2 used, since that
  is the only way the token behaviour is established rather than assumed.
  **Depends:** H1 for evidence; H2 is independent and helps either way.

---

## Decision gates

Open decisions from spec §11 and the task each one blocks. Anything not listed here can
be deferred without stalling the build.

| §11 | Decision | Blocks |
|---|---|---|
| ~~1~~ | ~~w3id namespace registration~~ — **resolved:** PR #6488 merged, `https://w3id.org/semprini/ontology` live and verified | ~~A2~~; nothing now. G5 discharged the obligation it left: every released version is published from `ontology-archive/` and goes on resolving |
| 2 | Confirm Apache-2.0 / CC BY 4.0 | A1 (the licence files are written there) |
| ~~3~~ | ~~Distribution channel~~ — **resolved:** tagged GitHub releases carrying a wheel and an sdist; no package index. The tag is the address an instance installs from, so `pip install semprini` resolves nothing and no unreleased version is installable by accident | ~~G5~~ |
| ~~4~~ | ~~Which adapters ship bundled~~ — **resolved:** Ellie and Excel ship and are registered (D3); G4's adapter guide states the policy publicly — bundling is a maintenance commitment, and a third-party adapter is never second-class | ~~D3~~; ~~G4~~ |
| ~~5~~ | ~~Default language tag(s)~~ — **resolved in B3:** one per instance, applied only where a label carries no tag of its own | ~~B3~~; C1 applies it |
| 6 | When missing-definition becomes blocking | per instance; H1 |
| ~~7~~ | ~~Ellie pagination and rate limits~~ — **resolved by scope:** the adapter reads exported files, so v1 makes no API call | ~~D3~~; whoever builds the API mode |
| ~~8~~ | ~~Whether `init` creates the remote repository~~ — **resolved in G1:** it stays offline, creates nothing remote and prints the steps instead | ~~G1~~ |

## Sequencing notes

- **H1 next, and it is the first task whose subject is a real organization.** The thing it
  was waiting for now exists: an instance pins a version, and there is a released version to
  pin. Everything else H1 needs is in place: `semprini init` produces the tree, both workflows
  have been run against a real instance on GitHub (G2), and the compiler is feature-complete
  (G3). What H1 adds is the things only a pilot can settle — a real base IRI, an Ellie allowlist
  filled one validated model at a time, named stewards, and §11 #6, the last open decision,
  which is per instance and needs somebody's actual data to answer.

- **H3 is a decision, not a build, and H1 is what informs it.** The plane ships two steward
  flows — compile locally and commit source with Turtle, or commit the source and let the
  scheduled compile follow — and names neither as primary. H2 helps under both and can land
  immediately. Nothing else should be built on either flow until the pilot says which one
  its stewards can actually run, and the Ellie API mode will reopen the question regardless.

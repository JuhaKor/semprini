"""Migrations, and the four things they may not do (spec 7).

The load-bearing test here is one: a doctored copy of the fixture instance, compiled by a
release that wrote `sem:legacyStatus`, migrates to the current release and lands **byte for
byte** on the committed fixture. That is the whole promise of spec 7 in one assertion —
deterministic, identity-preserving, and checkable against a file this repository already
trusts, rather than against the migration's own idea of what it should have produced.

Everything else in this file is the other half of the task: proving the refusals bite. A
migration is code a future release writes, and spec 7's promise about it — never mint an IRI
for an existing object, never remove an ID-map row — is worth what enforces it. So each way
of breaking that promise is written as a step here and demanded to be refused, with nothing
written.
"""

from __future__ import annotations

import datetime
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import cast

import pytest
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, XSD

from conftest import FIXTURE_INSTANCE
from semprini import adapters, build, config, migrate, ontology_version, scaffold, validate
from semprini.build import GENERATED_DIR, ONTOLOGY_FILE, OutputFile
from semprini.cli import ExitCode, main
from semprini.config import InstanceConfig
from semprini.identity import ID_MAP_PATH, IdMap, IdMapRow
from semprini.manifest import MANIFEST_FILE, Manifest, ManifestError
from semprini.migrate import InstanceState, Migration, MigrationError, parse_version, plan
from semprini.migrate.registry import Step
from semprini.model import Kind
from semprini.report import REPORT_FILE
from semprini.serialize import SEM_NAMESPACE

OLD_VERSION = "0.0.9"
"""What the doctored fixture's manifest says compiled it — a release before this one.

Fictional, deliberately: nothing has been released, so no instance in existence was compiled
by an earlier version. The version has to come from somewhere, and inventing one here is
honest in a way inventing one in `migrate/steps.py` would not be (see that module)."""

LEGACY_STATUS = URIRef(f"{SEM_NAMESPACE}legacyStatus")
"""The term the fictional earlier release wrote where this one writes ``sem:status``."""

INVENTED = URIRef("https://semantics.example.com/concepts/invented")
SMUGGLED = URIRef("https://semantics.example.com/concepts/smuggled")
"""IRIs no source reported and the ID map has never heard of — what a step may not mint."""


# --------------------------------------------------------------------------- the fixtures


def _current() -> str:
    """The compiler version installed, which is the only version ``--to`` may name."""
    from semprini import compiler_version

    return compiler_version()


def _restamped(root: Path, *, compiler: str, ontology: str | None = None) -> None:
    """Rewrite the manifest for the files as they now are.

    Every doctored instance needs this: a migration refuses to run against a ``generated/``
    that disagrees with its manifest, so a test that doctored the Turtle and left the hashes
    alone would be testing that refusal rather than whatever it meant to test.
    """
    directory = root / GENERATED_DIR
    files = [
        OutputFile(name=path.name, text=path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.ttl"))
    ]
    recorded = ontology_version() if ontology is None else ontology
    stamped = Manifest.create(files, compiler=compiler, ontology=recorded).to_file()
    (directory / stamped.name).write_text(stamped.text, encoding="utf-8", newline="\n")


def _to_legacy_status(root: Path) -> None:
    """Rewrite the instance's Turtle as the fictional earlier release would have written it.

    ``ontology.ttl`` is left alone: it is a verbatim copy of the metamodel, so the earlier
    release copied whatever it carried and the migration refreshes it wholesale (spec 4.2).
    """
    for path in sorted((root / GENERATED_DIR).glob("*.ttl")):
        if path.name == ONTOLOGY_FILE:
            continue
        path.write_text(
            path.read_text(encoding="utf-8").replace("sem:status", "sem:legacyStatus"),
            encoding="utf-8",
            newline="\n",
        )


@pytest.fixture
def old_instance(tmp_path: Path) -> Path:
    """A copy of the fixture instance as the fictional 0.0.9 left it."""
    root = tmp_path / "acme"
    shutil.copytree(FIXTURE_INSTANCE, root)
    _to_legacy_status(root)
    _restamped(root, compiler=OLD_VERSION)
    return root


@pytest.fixture
def unmigrated_instance(tmp_path: Path) -> Path:
    """A copy whose *only* difference is the version that compiled it.

    The release-with-no-output-change case: nothing to rewrite, but the drift check (spec 6.1
    check 3) is red until the manifest is restamped.
    """
    root = tmp_path / "acme"
    shutil.copytree(FIXTURE_INSTANCE, root)
    _restamped(root, compiler=OLD_VERSION)
    return root


def settings_for(root: Path) -> InstanceConfig:
    return config.load(root, known_adapters=adapters.adapter_names() or None)


def committed(name: str) -> bytes:
    return (FIXTURE_INSTANCE / GENERATED_DIR / name).read_bytes()


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file of the instance, so that "nothing was written" can be asserted."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ------------------------------------------------------------------------------ the steps


def _mapped(graph: Graph, predicate: URIRef, replacement: URIRef) -> Graph:
    fresh = Graph()
    for subject, found, object_ in graph:
        fresh.add((subject, replacement if found == predicate else found, object_))
    return fresh


def _rename_legacy_status(state: InstanceState) -> InstanceState:
    return state.with_graphs(
        {
            name: _mapped(graph, LEGACY_STATUS, build.SEM_STATUS)
            for name, graph in state.graphs.items()
        }
    )


RENAME = Migration(
    version="0.1.0",
    summary="`sem:legacyStatus` is written as `sem:status`",
    apply=_rename_legacy_status,
)
"""The synthetic output-affecting change this task is verified against.

A term rename is the migration spec 7's change table calls major and the one a recompile
provably cannot do on its own: a node no source reports any more is re-emitted verbatim from
the previous run's file (spec 3.5), so recompiling would rewrite every active node and miss
every deprecated one."""


def _first(state: InstanceState) -> str:
    """The lexicographically first generated file — for a step that has to pick one."""
    return sorted(state.graphs)[0]


def _step(summary: str, apply: object) -> Migration:
    """A step at the current version, so that ``plan`` selects it for a 0.0.9 instance."""
    return Migration(version=_current(), summary=summary, apply=cast(Step, apply))


# --------------------------------------------------------- the migration that must work


def test_a_migration_lands_on_exactly_what_the_new_release_writes(old_instance: Path) -> None:
    """The whole of spec 7 in one assertion.

    An instance compiled by an earlier release is migrated and comes out byte-identical to
    the committed fixture — which is what ``semprini run`` produces from the same sources on
    this release. Compared against a file this repository already trusts rather than against
    a golden file the migration itself generated, since the second proves only that the
    migration is repeatable.
    """
    result = migrate.migrate(settings_for(old_instance), to=_current(), migrations=(RENAME,))

    assert result.migrated
    assert result.steps == (RENAME,)
    for name in ("concepts-storefront.ttl", "relationships-storefront.ttl", ONTOLOGY_FILE):
        assert (old_instance / GENERATED_DIR / name).read_bytes() == committed(name)
    assert (old_instance / GENERATED_DIR / MANIFEST_FILE).read_bytes() == committed(MANIFEST_FILE)


def test_the_id_map_comes_out_untouched(old_instance: Path) -> None:
    # Not merely "no row lost": the file itself is unchanged, so the migration contributes no
    # line to the diff an adopter reviews (spec 5.4).
    before = (old_instance / ID_MAP_PATH).read_bytes()

    migrate.migrate(settings_for(old_instance), to=_current(), migrations=(RENAME,))

    assert (old_instance / ID_MAP_PATH).read_bytes() == before
    assert before == (FIXTURE_INSTANCE / ID_MAP_PATH).read_bytes()


def test_the_migrated_instance_passes_every_check(old_instance: Path) -> None:
    """Including drift, which is the check the migration exists to clear (spec 6.1 check 3).

    The point of the whole command: before it, this instance fails CI under the new release
    and no amount of reviewing fixes that; after it, the instance is committable.
    """
    settings = settings_for(old_instance)
    assert not validate.check(settings).ok  # drift, before

    migrate.migrate(settings, to=_current(), migrations=(RENAME,))

    result = validate.check(settings)
    assert result.ok, result.summary()
    assert result.errors == ()


def test_migrating_the_same_instance_twice_produces_the_same_bytes(tmp_path: Path) -> None:
    """Deterministic, like every other thing this compiler writes (spec 5.5).

    Two copies rather than two runs on one, so that the second migration is a real migration
    and not the no-op the first one leaves behind.
    """
    outputs = []
    for attempt in ("first", "second"):
        root = tmp_path / attempt
        shutil.copytree(FIXTURE_INSTANCE, root)
        _to_legacy_status(root)
        _restamped(root, compiler=OLD_VERSION)
        migrate.migrate(settings_for(root), to=_current(), migrations=(RENAME,))
        outputs.append(snapshot(root))

    assert outputs[0] == outputs[1]


def test_a_migrated_instance_finds_nothing_left_to_migrate(old_instance: Path) -> None:
    """Idempotent, so that a retry after a failure is safe and a workflow may call it blind."""
    settings = settings_for(old_instance)
    migrate.migrate(settings, to=_current(), migrations=(RENAME,))
    before = snapshot(old_instance)

    result = migrate.migrate(settings, to=_current(), migrations=(RENAME,))

    assert not result.migrated
    assert result.files == ()
    assert "nothing to migrate" in "\n".join(result.summary())
    assert snapshot(old_instance) == before


def test_a_release_that_changes_no_output_still_restamps(unmigrated_instance: Path) -> None:
    """The common upgrade: no step, but the drift check is red until the manifest moves.

    Handled by the same command rather than by a second one, because an adopter cannot tell
    from the outside which kind of release they are upgrading to — that is the release notes'
    job, and being wrong about it would leave them running the command that does nothing.
    """
    settings = settings_for(unmigrated_instance)
    turtle = {
        path.name: path.read_bytes() for path in (unmigrated_instance / GENERATED_DIR).glob("*.ttl")
    }

    result = migrate.migrate(settings, to=_current(), migrations=())

    assert result.migrated
    assert result.steps == ()
    assert {
        path.name: path.read_bytes() for path in (unmigrated_instance / GENERATED_DIR).glob("*.ttl")
    } == turtle
    assert (unmigrated_instance / GENERATED_DIR / MANIFEST_FILE).read_bytes() == committed(
        MANIFEST_FILE
    )
    assert validate.check(settings).ok


# ----------------------------------------------------------------------------- the report


def test_the_id_map_is_written_before_the_files(
    old_instance: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The opposite order to a run's, and deliberately (spec 5.4, 7).

    A run writes the files first because it *mints*: ``generated/`` holding an IRI the map has
    never heard of is a state only deleting ``generated/`` recovers from. A migration mints
    nothing, so that hazard does not exist — and the other one does. The manifest is written
    with the files, so a crash between the two calls would leave an instance already recording
    the new version, and the next run of the command would answer "nothing to migrate": whatever
    the step did to the map would be lost with no trace. In this order the same crash leaves an
    unstamped manifest, which a re-run migrates as though nothing had happened.
    """
    order: list[str] = []
    original_save, original_write = IdMap.save, build.write_all

    def save(self: IdMap, repo_root: Path | None = None) -> Path:
        order.append("map")
        return original_save(self, repo_root)

    def write_all(files: object, repo_root: Path | None = None) -> object:
        order.append("files")
        return original_write(files, repo_root)  # type: ignore[arg-type]

    monkeypatch.setattr(IdMap, "save", save)
    monkeypatch.setattr(build, "write_all", write_all)

    migrate.migrate(settings_for(old_instance), to=_current(), migrations=(RENAME,))

    assert order == ["map", "files"]


def test_a_metamodel_that_moved_without_a_version_bump_is_still_something_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Check 7 compares the copied metamodel as **bytes**, so this guard has to as well.

    A release that edited `sem.ttl` without moving its `owl:versionInfo` — a corrected term
    comment, say — leaves every instance red on the one check `semprini migrate` is the only
    cure for. Judged on the recorded version alone, the command would answer "nothing to
    migrate" and there would be no way out. A hand edit cannot reach here: the manifest
    verification refuses that first.
    """
    root = tmp_path / "acme"
    shutil.copytree(FIXTURE_INSTANCE, root)
    stale_copy = "# an earlier metamodel, same version\n"
    (root / GENERATED_DIR / ONTOLOGY_FILE).write_text(stale_copy, encoding="utf-8", newline="\n")
    _restamped(root, compiler=_current())
    settings = settings_for(root)
    assert not validate.check(settings).ok

    result = migrate.migrate(settings, to=_current(), migrations=())

    assert result.migrated
    assert (root / GENERATED_DIR / ONTOLOGY_FILE).read_bytes() == committed(ONTOLOGY_FILE)
    assert validate.check(settings).ok


def test_an_instance_that_has_never_compiled_can_still_be_migrated(tmp_path: Path) -> None:
    """Bootstrap, then upgrade before the first compile — an ordinary sequence.

    `semprini init` writes a manifest and the metamodel copy and nothing else (spec 5.7), so
    this instance has a recorded version and no content. It has to come out restamped rather
    than raise on a directory with no Turtle in it.
    """
    root = tmp_path / "fresh"
    scaffold.init(root, base_iri="https://semantics.example.com/", org="acme")
    _restamped(root, compiler=OLD_VERSION)

    result = migrate.migrate(settings_for(root), to=_current(), migrations=())

    assert result.migrated
    assert result.report is not None and result.report.files == ()
    assert "no generated content yet" in (root / GENERATED_DIR / REPORT_FILE).read_text(
        encoding="utf-8"
    )
    assert Manifest.load(root).check_versions() == ()


def test_an_ontology_version_that_moved_alone_is_still_something_to_do(tmp_path: Path) -> None:
    """Both recorded versions are compared, not only the compiler's (spec 6.1 check 3).

    Spec 7 says an ontology change implies a compiler change, so this state arrives through a
    hand-edited manifest — one whose hashes are honest and whose version claim is not. Check 3
    reports it, and if the up-to-date test looked at the compiler alone the instance would be
    left with the one drift no command could clear.
    """
    root = tmp_path / "acme"
    shutil.copytree(FIXTURE_INSTANCE, root)
    _restamped(root, compiler=_current(), ontology="0.0.1")
    settings = settings_for(root)
    assert not validate.check(settings).ok

    result = migrate.migrate(settings, to=_current(), migrations=())

    assert result.migrated
    assert result.from_ontology == "0.0.1"
    assert result.to_ontology == ontology_version()
    assert validate.check(settings).ok


def test_the_report_is_the_migration_that_produced_the_files(old_instance: Path) -> None:
    """``.report.md`` describes whatever last wrote the files beside it (spec 5.6).

    A compile report left in place would name a release that has not written a byte in the
    directory, and would state a version the manifest next to it contradicts.
    """
    migrate.migrate(settings_for(old_instance), to=_current(), migrations=(RENAME,))

    written = (old_instance / GENERATED_DIR / REPORT_FILE).read_text(encoding="utf-8")

    assert written.startswith("# Migration report")
    assert f"compiler **{OLD_VERSION}**" in written
    assert f"compiler **{_current()}**" in written
    assert RENAME.summary in written
    assert "does not read the sources" in written
    assert written != (FIXTURE_INSTANCE / GENERATED_DIR / REPORT_FILE).read_text(encoding="utf-8")


def test_the_report_is_not_hashed_by_the_manifest(old_instance: Path) -> None:
    # The manifest's own rule (spec 4.3, 5.6), and the migration writes both, so it is the
    # one place they could be made to disagree.
    result = migrate.migrate(settings_for(old_instance), to=_current(), migrations=(RENAME,))

    recorded = Manifest.load(old_instance)
    assert REPORT_FILE not in recorded.files
    assert recorded.verify(old_instance) == ()
    assert result.report is not None


def test_a_report_carrying_a_pipe_does_not_break_its_table(old_instance: Path) -> None:
    # A step summary is prose, and this file is pasted verbatim into a pull request
    # description (spec 6.2) — the same escaping the run report needs, through the same
    # renderer rather than a second copy of it.
    step = _step("renames `a|b` to `c`", _rename_legacy_status)

    migrate.migrate(settings_for(old_instance), to=_current(), migrations=(step,))

    line = next(
        text
        for text in (old_instance / GENERATED_DIR / REPORT_FILE)
        .read_text(encoding="utf-8")
        .splitlines()
        if "renames" in text
    )
    assert r"a\|b" in line
    # Three column delimiters and no fourth: the pipe in the summary is escaped, so it does
    # not end the column it is in.
    assert line.replace(r"\|", "").count("|") == 3


def test_the_report_says_when_no_step_was_needed(unmigrated_instance: Path) -> None:
    migrate.migrate(settings_for(unmigrated_instance), to=_current(), migrations=())

    written = (unmigrated_instance / GENERATED_DIR / REPORT_FILE).read_text(encoding="utf-8")
    assert "re-serialized unchanged and the manifest restamped" in written


def test_the_report_carries_no_date(old_instance: Path) -> None:
    # For the reason nothing else the compiler writes does (spec 5.5 rule 8): a file that
    # moved because a day passed is a diff nobody caused.
    migrate.migrate(settings_for(old_instance), to=_current(), migrations=(RENAME,))

    written = (old_instance / GENERATED_DIR / REPORT_FILE).read_text(encoding="utf-8")
    assert str(datetime.date.today().year) not in written


# ------------------------------------------------------------ what a migration may not do


def _mints(state: InstanceState) -> InstanceState:
    """A step that does its job and also writes one node nobody asked for."""
    renamed = _rename_legacy_status(state)
    name = _first(renamed)
    fresh = Graph()
    fresh += renamed.graphs[name]
    fresh.add((INVENTED, build.SEM_STATUS, Literal("active")))
    return state.with_graphs({**renamed.graphs, name: fresh})


def test_a_step_that_mints_an_iri_is_refused(old_instance: Path) -> None:
    """The promise spec 7 makes, and the one a buggy step is likeliest to break."""
    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("mints", _mints),)
        )

    assert "never mints an IRI" in str(raised.value)
    assert "concepts/invented" in str(raised.value)


def test_a_step_that_drops_a_node_is_refused(old_instance: Path) -> None:
    """An IRI is never deleted (spec 3.5) — least of all by the upgrade nobody is reading."""

    def drop(state: InstanceState) -> InstanceState:
        renamed = _rename_legacy_status(state)
        name = _first(renamed)
        graph = renamed.graphs[name]
        victim = sorted({str(subject) for subject in graph.subjects()})[0]
        fresh = Graph()
        for triple in graph:
            if str(triple[0]) != victim:
                fresh.add(triple)
        return state.with_graphs({**renamed.graphs, name: fresh})

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("drops", drop),)
        )

    assert "no longer written to generated/" in str(raised.value)


def test_a_step_that_moves_a_modified_date_is_refused(old_instance: Path) -> None:
    """``dcterms:modified`` says when the instance's knowledge changed (spec 3.3).

    How that knowledge is written down is not knowledge, so a migration that refreshed the
    dates would put every node in the diff and hide what it actually did.
    """

    def touch(state: InstanceState) -> InstanceState:
        renamed = _rename_legacy_status(state)
        name = _first(renamed)
        fresh = Graph()
        for subject, predicate, object_ in renamed.graphs[name]:
            if predicate == DCTERMS.modified:
                object_ = Literal("2099-01-01", datatype=XSD.date)
            fresh.add((subject, predicate, object_))
        return state.with_graphs({**renamed.graphs, name: fresh})

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("touches", touch),)
        )

    assert "dcterms:modified" in str(raised.value)
    assert "2099-01-01" in str(raised.value)


def test_a_step_that_removes_an_id_map_row_is_refused(old_instance: Path) -> None:
    def forget(state: InstanceState) -> InstanceState:
        kept = IdMap(state.id_map.rows[:-1])
        return InstanceState(graphs=_rename_legacy_status(state).graphs, id_map=kept)

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("forgets", forget),)
        )

    assert "append-only" in str(raised.value)


def test_a_step_that_appends_an_id_map_row_is_refused(old_instance: Path) -> None:
    def append(state: InstanceState) -> InstanceState:
        grown = IdMap(state.id_map.rows)
        grown.append(
            IdMapRow(
                iri="https://semantics.example.com/concepts/invented",
                kind=Kind.ENTITY,
                source_name="ellie-main",
                source_key="invented",
                first_seen=datetime.date(2026, 8, 6),
            )
        )
        return InstanceState(graphs=_rename_legacy_status(state).graphs, id_map=grown)

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("appends", append),)
        )

    assert "the ID map gained a row" in str(raised.value)


def test_a_step_that_rewrites_an_id_map_row_is_refused(old_instance: Path) -> None:
    def rewrite(state: InstanceState) -> InstanceState:
        rows = list(state.id_map.rows)
        rows[0] = IdMapRow(
            iri=rows[0].iri,
            kind=rows[0].kind,
            source_name=rows[0].source_name,
            source_key=rows[0].source_key,
            first_seen=datetime.date(1999, 1, 1),
            note=rows[0].note,
        )
        return InstanceState(graphs=_rename_legacy_status(state).graphs, id_map=IdMap(rows))

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("rewrites", rewrite),)
        )

    assert "was rewritten" in str(raised.value)
    assert "first_seen" in str(raised.value)


def test_a_step_may_write_in_the_note_column(old_instance: Path) -> None:
    """The one ID-map edit left legal, and the proof the guard is not "must be identical".

    ``note`` is the column stewards own (spec 5.4), and B4's append-only check ignores it, so
    a migration that had a reason to annotate a row can. Nothing shipped does; the point is
    that the rule enforced here is the rule spec 7 states, not a stricter one that happened
    to be easier to check.
    """

    def annotate(state: InstanceState) -> InstanceState:
        rows = list(state.id_map.rows)
        rows[0] = IdMapRow(
            iri=rows[0].iri,
            kind=rows[0].kind,
            source_name=rows[0].source_name,
            source_key=rows[0].source_key,
            first_seen=rows[0].first_seen,
            note="annotated by the migration",
        )
        return InstanceState(graphs=_rename_legacy_status(state).graphs, id_map=IdMap(rows))

    migrate.migrate(
        settings_for(old_instance), to=_current(), migrations=(_step("annotates", annotate),)
    )

    reloaded = IdMap.load(old_instance)
    assert reloaded.rows[0].note == "annotated by the migration"
    assert reloaded.check_append_only(IdMap.load(FIXTURE_INSTANCE)) == ()
    # And the report says so. It claimed the rows were untouched before this was reviewed,
    # which on the one occasion it mattered would have contradicted the diff beside it.
    written = (old_instance / GENERATED_DIR / REPORT_FILE).read_text(encoding="utf-8")
    assert "except the `note` column of 1 row" in written


def test_the_report_says_the_map_was_untouched_when_it_was(old_instance: Path) -> None:
    migrate.migrate(settings_for(old_instance), to=_current(), migrations=(RENAME,))

    written = (old_instance / GENERATED_DIR / REPORT_FILE).read_text(encoding="utf-8")
    assert "none added, none removed, none reordered, none altered" in written


def test_a_step_that_only_reorders_the_id_map_is_refused(old_instance: Path) -> None:
    """Neither of the two checks above can see order, and the file's order is its history.

    ``check_append_only`` looks a row up by its ref and the new-row check is a set difference,
    so the same rows shuffled pass both — and would then be saved as a rewritten
    ``mappings/id-map.csv``. A whole-file diff in the identity registry, in the one command
    whose entire claim is that its diff is about nothing but the upgrade.
    """

    def shuffle(state: InstanceState) -> InstanceState:
        reversed_rows = IdMap(tuple(reversed(state.id_map.rows)))
        return InstanceState(graphs=_rename_legacy_status(state).graphs, id_map=reversed_rows)

    before = (old_instance / ID_MAP_PATH).read_bytes()

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("shuffles", shuffle),)
        )

    assert "in a different order" in str(raised.value)
    assert (old_instance / ID_MAP_PATH).read_bytes() == before


def test_a_reordering_is_reported_once_not_twice(old_instance: Path) -> None:
    # A removal changes the order too, and the check that knows what was removed says so
    # better. Two issues about one edit would have an adopter looking for two problems.
    def forget(state: InstanceState) -> InstanceState:
        kept = IdMap(state.id_map.rows[:-1])
        return InstanceState(graphs=_rename_legacy_status(state).graphs, id_map=kept)

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("forgets", forget),)
        )

    assert "in a different order" not in str(raised.value)


def test_a_step_that_edits_what_it_was_handed_is_still_checked(old_instance: Path) -> None:
    """The one refusal that could have passed on a technicality.

    An ``rdflib`` graph is mutable, so a step that edits the graphs it was given and returns
    the same state would leave a naive before/after comparison comparing an object with
    itself — and every check in this module would pass on a migration that had just minted an
    IRI. The comparison is taken as a snapshot before any step runs, so it does not depend on
    a step behaving.
    """

    def mutate(state: InstanceState) -> InstanceState:
        state.graphs[_first(state)].add((SMUGGLED, build.SEM_STATUS, Literal("active")))
        return state

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("mutates", mutate),)
        )

    assert "concepts/smuggled" in str(raised.value)


def test_a_step_that_appends_to_the_map_it_was_handed_is_still_checked(old_instance: Path) -> None:
    """The same hole, on the other mutable thing a step is given.

    :class:`~semprini.identity.IdMap` has a public ``append``, so this is the *easier* of the
    two ways to smuggle something past a naive comparison: the map has no removal method, and
    appending to the one you were handed is what an author reaching for it would write. The
    snapshot rebuilds the map from its rows — which are frozen — so the comparison holds.
    """

    def append_in_place(state: InstanceState) -> InstanceState:
        state.id_map.append(
            IdMapRow(
                iri=str(SMUGGLED),
                kind=Kind.ENTITY,
                source_name="ellie-main",
                source_key="smuggled",
                first_seen=datetime.date(2026, 8, 6),
            )
        )
        return _rename_legacy_status(state)

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance),
            to=_current(),
            migrations=(_step("appends in place", append_in_place),),
        )

    assert "the ID map gained a row" in str(raised.value)
    assert IdMap.load(old_instance).rows == IdMap.load(FIXTURE_INSTANCE).rows


def test_every_violation_is_reported_at_once(old_instance: Path) -> None:
    # Read in CI, where one problem per round trip is the difference between one fix and
    # five (spec 6.1) — and a migration reporting only the first would have an adopter
    # believing the second was caused by the fix for the first.
    def two(state: InstanceState) -> InstanceState:
        name = _first(state)
        fresh = Graph()
        fresh += state.graphs[name]
        for local in ("first", "second"):
            fresh.add(
                (
                    URIRef(f"https://semantics.example.com/concepts/{local}"),
                    build.SEM_STATUS,
                    Literal("active"),
                )
            )
        return state.with_graphs({**state.graphs, name: fresh})

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(settings_for(old_instance), to=_current(), migrations=(_step("two", two),))

    assert len(raised.value.issues) >= 2
    assert "concepts/first" in str(raised.value)
    assert "concepts/second" in str(raised.value)


# --------------------------------------------------------------- what a step may not write


def test_a_file_name_that_escapes_generated_is_refused(old_instance: Path) -> None:
    """The escape C1 refuses for a scheme slug and C2 for a manifest key (spec 4.3).

    One directory, bounded in every module that composes a path into it out of a name it was
    handed — and a migration is handed its file names by a step.
    """

    def escape(state: InstanceState) -> InstanceState:
        renamed = _rename_legacy_status(state)
        return state.with_graphs(
            {**renamed.graphs, "../../pwned.ttl": renamed.graphs[_first(renamed)]}
        )

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("escapes", escape),)
        )

    assert "not a .ttl file directly inside generated/" in str(raised.value)
    assert not (old_instance.parent.parent / "pwned.ttl").exists()


def test_a_file_name_that_is_not_turtle_is_refused(old_instance: Path) -> None:
    # generated/ holds Turtle, a manifest and a report. A fourth kind of file would be
    # written, recorded, and then never read by anything that parses the directory.
    def json_(state: InstanceState) -> InstanceState:
        renamed = _rename_legacy_status(state)
        return state.with_graphs(
            {**renamed.graphs, "concepts.json": renamed.graphs[_first(renamed)]}
        )

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("writes json", json_),)
        )

    assert "concepts.json" in str(raised.value)


def test_a_step_may_not_rewrite_the_ontology_copy(old_instance: Path) -> None:
    """It is copied from the metamodel this compiler carries, never transformed (spec 4.2).

    A step that rewrote it would be editing the vocabulary's published documentation, and
    check 7 compares the committed copy against the packaged one byte for byte.
    """

    def rewrite(state: InstanceState) -> InstanceState:
        renamed = _rename_legacy_status(state)
        return state.with_graphs({**renamed.graphs, ONTOLOGY_FILE: renamed.graphs[_first(renamed)]})

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("rewrites", rewrite),)
        )

    assert "refreshed rather than rewritten" in str(raised.value)


def test_a_graph_the_serializer_refuses_is_reported_as_such(old_instance: Path) -> None:
    def blank(state: InstanceState) -> InstanceState:
        renamed = _rename_legacy_status(state)
        name = _first(renamed)
        graph = renamed.graphs[name]
        fresh = Graph()
        fresh += graph
        fresh.add((sorted(graph.subjects(), key=str)[0], build.SEM_SOURCE, BNode()))
        return state.with_graphs({**renamed.graphs, name: fresh})

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("blank node", blank),)
        )

    assert "cannot be serialized" in str(raised.value)


def test_the_ontology_copy_is_refreshed_from_the_installed_metamodel(old_instance: Path) -> None:
    """Half of what an ontology version bump means (spec 7).

    The committed copy came from whatever the earlier release carried; the migration replaces
    it with this one's, which is what check 7 compares against.
    """
    copy = old_instance / GENERATED_DIR / ONTOLOGY_FILE
    copy.write_text("# an older metamodel\n", encoding="utf-8", newline="\n")
    _restamped(old_instance, compiler=OLD_VERSION)

    result = migrate.migrate(settings_for(old_instance), to=_current(), migrations=(RENAME,))

    assert copy.read_bytes() == committed(ONTOLOGY_FILE)
    assert result.report is not None
    assert result.report.ontology_refreshed


def test_a_step_that_renames_a_file_removes_the_old_one(old_instance: Path) -> None:
    """``generated/`` is the migration's output and nothing else (spec 4.3).

    A file left behind would be loaded by every consumer that reads the directory from Git,
    and would fail the manifest's own unrecorded-file check on the adopter's next PR.
    """

    def rename(state: InstanceState) -> InstanceState:
        renamed = dict(_rename_legacy_status(state).graphs)
        renamed["concepts-shopfront.ttl"] = renamed.pop("concepts-storefront.ttl")
        return state.with_graphs(renamed)

    result = migrate.migrate(
        settings_for(old_instance), to=_current(), migrations=(_step("renames a file", rename),)
    )

    assert result.stale == ("concepts-storefront.ttl",)
    assert not (old_instance / GENERATED_DIR / "concepts-storefront.ttl").exists()
    assert (old_instance / GENERATED_DIR / "concepts-shopfront.ttl").is_file()
    assert (old_instance / GENERATED_DIR / REPORT_FILE).is_file()
    assert Manifest.load(old_instance).verify(old_instance) == ()


# ------------------------------------------------------------------ nothing half-performed


@pytest.mark.parametrize(
    "step",
    [
        pytest.param(_mints, id="mints"),
        pytest.param(lambda state: None, id="returns nothing"),
        pytest.param(lambda state: 1 / 0, id="raises"),
    ],
)
def test_nothing_is_written_when_a_migration_is_refused(old_instance: Path, step: object) -> None:
    """A refused migration leaves the instance exactly as it was.

    The property :mod:`semprini.run` has, for the same reason: an instance half-migrated by a
    release nobody can name is worse than one that is merely out of date. Asserted over the
    whole tree, not only ``generated/`` — the manifest, the report and the ID map are written
    by three separate calls, and any one of them landing alone is the state this promises
    cannot happen.
    """
    before = snapshot(old_instance)

    with pytest.raises(MigrationError):
        migrate.migrate(settings_for(old_instance), to=_current(), migrations=(_step("bad", step),))

    assert snapshot(old_instance) == before


def test_a_migration_that_changed_nothing_is_check_s_problem(old_instance: Path) -> None:
    """The division of labour, and the one thing this module deliberately does not judge.

    A step that returns the state untouched is a migration that did not do what its summary
    says, and nothing here can know that — the framework has no independent account of what
    the step meant to achieve, and inventing one would mean writing every migration twice.
    What such a step cannot do is leave a *committable* instance behind: the term the earlier
    release wrote is not one the metamodel declares, so the shapes refuse it (spec 6.1 check
    5). `migrate` writes, `semprini check` judges.
    """
    settings = settings_for(old_instance)

    migrate.migrate(
        settings, to=_current(), migrations=(_step("does nothing", lambda state: state),)
    )

    assert not validate.check(settings).ok


def test_a_step_that_raises_is_reported_with_its_version(old_instance: Path) -> None:
    # A traceback through rdflib in an adopter's repository says nothing about which upgrade
    # failed; the step is known here, so it is named here.
    def boom(state: InstanceState) -> InstanceState:
        raise RuntimeError("the step is broken")

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance), to=_current(), migrations=(_step("raises", boom),)
        )

    assert f"the migration to {_current()} failed" in str(raised.value)
    assert "the step is broken" in str(raised.value)
    assert "nothing was written" in str(raised.value)


def test_a_step_that_returns_the_wrong_thing_is_refused(old_instance: Path) -> None:
    with pytest.raises(MigrationError) as raised:
        migrate.migrate(
            settings_for(old_instance),
            to=_current(),
            migrations=(_step("returns a dict", lambda state: {}),),
        )

    assert "rather than an InstanceState" in str(raised.value)


# ------------------------------------------------------------------- the version arguments


def test_the_target_must_be_the_version_installed(old_instance: Path) -> None:
    """A migration is performed by the release it upgrades to (spec 7).

    Its steps only exist in that release, and the manifest records the release that wrote the
    files — so a ``--to`` naming anything else is a workflow that pinned one version and
    installed another, caught before a byte is rewritten.
    """
    before = snapshot(old_instance)

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(settings_for(old_instance), to="9.9.9", migrations=(RENAME,))

    assert "Install semprini==9.9.9" in str(raised.value)
    assert snapshot(old_instance) == before


def test_a_downgrade_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "acme"
    shutil.copytree(FIXTURE_INSTANCE, root)
    _restamped(root, compiler="9.9.9")

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(settings_for(root), to=_current(), compiler=_current(), migrations=())

    assert "cannot be migrated back" in str(raised.value)


def test_a_target_that_is_not_a_version_is_refused(old_instance: Path) -> None:
    with pytest.raises(MigrationError) as raised:
        migrate.migrate(settings_for(old_instance), to="latest", compiler="latest", migrations=())

    assert "not a version of the form X.Y.Z" in str(raised.value)


def test_a_recorded_version_that_is_not_a_version_is_refused(old_instance: Path) -> None:
    # A hand-edited manifest, which is the only way this happens — and the message says which
    # value it is about, since the operator has two versions to think about.
    _restamped(old_instance, compiler="0.0.9")
    text = (old_instance / GENERATED_DIR / MANIFEST_FILE).read_text(encoding="utf-8")
    (old_instance / GENERATED_DIR / MANIFEST_FILE).write_text(
        text.replace('"0.0.9"', '"nightly"'), encoding="utf-8", newline="\n"
    )

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(settings_for(old_instance), to=_current(), migrations=(RENAME,))

    assert MANIFEST_FILE in str(raised.value)
    assert "nightly" in str(raised.value)


def test_a_source_tree_cannot_migrate_anything() -> None:
    """``0.0.0+source`` identifies no release, so there is no telling what the target is.

    The rule C2 established for the manifest, reaching the one other place that records which
    release wrote an instance's files (spec 7).
    """
    from semprini import UNINSTALLED_VERSION

    with pytest.raises(MigrationError) as raised:
        parse_version(UNINSTALLED_VERSION, what="--to")

    assert "not a version of the form X.Y.Z" in str(raised.value)


# ------------------------------------------------------------------------ manifest hygiene


def test_a_hand_edited_generated_file_is_refused(old_instance: Path) -> None:
    """A migration will not launder a hand edit into a new manifest (spec 4.3).

    It rewrites what the compiler wrote. Migrating a directory that disagrees with its
    manifest would restamp somebody's edit as this release's output, and the hash that would
    have caught it is the one being replaced.
    """
    edited = old_instance / GENERATED_DIR / "concepts-storefront.ttl"
    edited.write_text(edited.read_text(encoding="utf-8") + "\n", encoding="utf-8", newline="\n")
    before = snapshot(old_instance)

    with pytest.raises(MigrationError) as raised:
        migrate.migrate(settings_for(old_instance), to=_current(), migrations=(RENAME,))

    assert "does not match its manifest" in str(raised.value)
    assert "concepts-storefront.ttl" in str(raised.value)
    assert snapshot(old_instance) == before


def test_a_missing_manifest_is_refused(old_instance: Path) -> None:
    (old_instance / GENERATED_DIR / MANIFEST_FILE).unlink()

    with pytest.raises(ManifestError):
        migrate.migrate(settings_for(old_instance), to=_current(), migrations=(RENAME,))


# ------------------------------------------------------------------------------- the plan


def _versions(migrations: Iterable[Migration]) -> list[str]:
    return [migration.version for migration in migrations]


def _at(version: str) -> Migration:
    return Migration(version=version, summary=f"to {version}", apply=lambda state: state)


def test_every_step_after_the_recorded_version_runs_in_order() -> None:
    """An adopter three releases behind runs all three, oldest first."""
    steps = [_at("0.4.0"), _at("0.2.0"), _at("0.3.0")]

    selected = plan(steps, recorded=(0, 1, 0), target=(0, 4, 0))

    assert _versions(selected) == ["0.2.0", "0.3.0", "0.4.0"]


def test_a_step_at_the_recorded_version_has_already_run() -> None:
    # The instance was compiled *by* that release, so its migration is history.
    assert plan([_at("0.2.0")], recorded=(0, 2, 0), target=(0, 3, 0)) == ()


def test_a_step_beyond_the_target_waits() -> None:
    assert _versions(plan([_at("0.2.0"), _at("0.9.0")], recorded=(0, 1, 0), target=(0, 2, 0))) == [
        "0.2.0"
    ]


def test_a_patch_release_nobody_migrated_is_not_a_gap() -> None:
    """The reason a step declares one version rather than a hop between two.

    Under a chain of hops, an adopter sitting on 0.1.1 — a release that changed no output and
    so shipped no step — would find no step starting there, and the upgrade would stall on a
    version that needed nothing.
    """
    assert _versions(plan([_at("0.2.0")], recorded=(0, 1, 1), target=(0, 2, 0))) == ["0.2.0"]


def test_versions_are_ordered_numerically_not_alphabetically() -> None:
    steps = [_at("0.10.0"), _at("0.9.0")]

    assert _versions(plan(steps, recorded=(0, 8, 0), target=(0, 10, 0))) == ["0.9.0", "0.10.0"]


def test_two_steps_for_one_release_are_refused() -> None:
    # Their order would decide what an adopter's files come out as, and there is none.
    with pytest.raises(MigrationError) as raised:
        plan([_at("0.2.0"), _at("0.2.0")], recorded=(0, 1, 0), target=(0, 2, 0))

    assert "two migrations are registered" in str(raised.value)


def test_a_step_needs_a_summary() -> None:
    # It is what the report tells an adopter their files were rewritten for.
    with pytest.raises(MigrationError) as raised:
        Migration(version="0.2.0", summary="  ", apply=lambda state: state)

    assert "has no summary" in str(raised.value)


def test_a_step_version_must_be_a_version() -> None:
    with pytest.raises(MigrationError):
        Migration(version="next", summary="whatever", apply=lambda state: state)


def test_this_release_ships_no_migration() -> None:
    """Nothing has been released, so no instance was compiled by an earlier version.

    Asserted rather than left implicit: the first real entry belongs to the first release that
    changes emitted output, and this test is what makes adding one a deliberate act — it fails,
    and whoever wrote the step says why in this file.
    """
    assert migrate.MIGRATIONS == ()


# --------------------------------------------------------------------------------- the CLI


def test_the_cli_migrates_and_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Through ``main`` with the shipped steps, which is what an adopter actually runs."""
    root = tmp_path / "acme"
    shutil.copytree(FIXTURE_INSTANCE, root)
    _restamped(root, compiler=OLD_VERSION)
    monkeypatch.chdir(root)

    assert main(["migrate", "--to", _current()]) == ExitCode.OK

    out = capsys.readouterr().out
    assert f"from compiler {OLD_VERSION} to {_current()}" in out
    assert "review the diff, then run `semprini check`" in out
    assert (root / GENERATED_DIR / MANIFEST_FILE).read_bytes() == committed(MANIFEST_FILE)


def test_the_cli_reports_nothing_to_do_and_exits_0(
    instance: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["migrate", "--to", _current()]) == ExitCode.OK
    assert "nothing to migrate" in capsys.readouterr().out


def test_the_cli_maps_a_migration_error_to_exit_1(
    instance: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 1, not 2: exit 2 tells an operator to go and edit a configuration file, and
    nothing a migration reports is fixed by editing one (spec 5.1)."""
    assert main(["migrate", "--to", "9.9.9"]) == ExitCode.FAILURE

    err = capsys.readouterr().err
    assert "semprini:" in err
    assert "Install semprini==9.9.9" in err


def test_the_cli_checks_the_namespace_lock_first(instance: Path) -> None:
    # Migrating an instance whose configured base IRI disagrees with its lock would rewrite
    # every file under a namespace the instance does not have (spec 3.4.4).
    path = instance / "config" / "semprini.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "https://semantics.example.com/", "https://elsewhere.example.com/"
        ),
        encoding="utf-8",
    )

    assert main(["migrate", "--to", _current()]) == ExitCode.CONFIG


def test_a_broken_configuration_is_exit_2_before_anything_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["migrate", "--to", _current()]) == ExitCode.CONFIG

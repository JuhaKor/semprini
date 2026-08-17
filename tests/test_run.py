"""``semprini run`` end to end, on a whole instance (spec 5.1).

Every module below this one is tested against a model or a graph. This file is the only
place the promise an adopting organization actually depends on is asserted: *point the
compiler at a repository and it either leaves it exactly as it was or changes it for a
reason you can read in the diff*.

Three properties carry that, and each has a way of failing that no unit test can see.

*A run that finds nothing writes nothing* — not even a report saying so, because a
scheduled compile whose only output is "0 new" trains reviewers to skim (spec 5.6).

*A run that fails writes nothing at all.* Fetching, lifecycle, building and hashing all
complete before the first byte lands, so a source that is down or a register that
contradicts itself leaves the instance untouched rather than half-written.

*What is not this run's output does not stay.* ``generated/`` is machine-owned (spec 4.3):
a file left behind is read as current by every consumer that loads the directory from Git.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS
from tools.build_fixture_instance import COMPILER, INSTANCE, ONTOLOGY, TODAY

from semprini import adapters, build, config, identity, lifecycle, run
from semprini.cli import ExitCode, main
from semprini.identity import ID_MAP_PATH, NAMESPACE_LOCK_PATH, IdMap, IdMapRow, NamespaceLock
from semprini.model import Entity, InternalModel, Kind, Scheme, SchemeType, merge_models
from semprini.report import REPORT_FILE

BASE = "https://semantics.example.com/"
ELLIE = "ellie-main"
EXCEL = "product-category"
WAREHOUSE = "33ef202c-aa23-11ee-9167-0242ac1e0003"
"""An entity of the fixture's Ellie export, removed below to make a deprecation happen."""

DELIVERY = "07666880-aa23-11ee-94e1-0242ac1e0003"
"""Another, kept — the surviving object when a merge is recorded."""


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file of the instance, by path and content — the whole repository state."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def governed(root: Path) -> dict[str, bytes]:
    """The instance without its report.

    ``.report.md`` describes a *run*, not a state (spec 5.6): it says what moved since the
    output it replaced, so an instance compiled from scratch and the same instance
    compiled one source at a time hold identical Turtle and different prose. Everything
    else here is a function of the inputs alone, and is compared as such.
    """
    return {
        name: content for name, content in snapshot(root).items() if not name.endswith(REPORT_FILE)
    }


def compile_(root: Path, **overrides: Any) -> run.RunResult:
    """A run with the date and both versions pinned, as the fixture instance was built.

    Pinned so that an assertion against the committed bytes is about this task's behaviour
    and not about which release happens to be installed (spec 7).
    """
    settings = config.load(root)
    arguments: dict[str, Any] = {"today": TODAY, "compiler": COMPILER, "ontology": ONTOLOGY}
    arguments.update(overrides)
    return run.run(settings, **arguments)


def graph_of(root: Path, name: str) -> Graph:
    graph = Graph()
    graph.parse(root / build.GENERATED_DIR / name, format="turtle")
    return graph


def drop_entity(root: Path, entity_id: str) -> None:
    """Remove one entity, and every relationship touching it, from the Ellie export.

    A source deleting an object is the event the whole lifecycle exists for (spec 3.5),
    and it is not reproducible any other way: the compiler has to see the object gone from
    a real fetch, not be told it is gone.
    """
    path = root / "sources/ellie/storefront.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    model = document["model"]
    model["entities"] = [item for item in model["entities"] if item["id"] != entity_id]
    model["relationships"] = [
        item
        for item in model["relationships"]
        if entity_id not in (item["sourceEntity"]["id"], item["targetEntity"]["id"])
    ]
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")


def record_merge(root: Path, deprecated: str, replaced_by: str) -> None:
    """Write the one row a steward writes by hand (spec 5.4)."""
    (root / lifecycle.MERGES_PATH).write_text(
        "deprecated_iri,replaced_by_iri,date,note\n"
        f"{deprecated},{replaced_by},2026-08-06,merged into the survivor\n",
        encoding="utf-8",
        newline="\n",
    )


# ------------------------------------------------------------------ the committed instance


def test_the_fixture_instance_is_what_a_run_produces(tmp_path: Path) -> None:
    """The tool that regenerates the fixture is ``semprini run`` and nothing else.

    Both are asserted at once because they must not be two implementations: a stand-in
    that drifted from the command would make every other fixture-based test evidence about
    code no instance executes.
    """
    root = tmp_path / "acme"
    shutil.copytree(INSTANCE, root)

    result = compile_(root)

    assert snapshot(root) == snapshot(INSTANCE)
    assert not result.changed
    assert result.summary() == ("generated/ is up to date; 5 files unchanged",)


def test_two_consecutive_runs_produce_zero_diff(instance: Path) -> None:
    """The property a scheduled compile depends on (spec 4.3).

    Through the CLI and the installed versions rather than the pinned ones, since that is
    what CI executes — and the comparison is between the two runs, not against the
    committed bytes, so a release of the plane cannot make this test lie.
    """
    assert main(["run"]) == ExitCode.OK
    after_first = snapshot(instance)

    assert main(["run"]) == ExitCode.OK

    assert snapshot(instance) == after_first


def test_a_run_that_changes_nothing_leaves_the_report_alone(instance: Path) -> None:
    """A no-op compile must produce no diff at all — including the prose (spec 5.6).

    The report says how many objects were new, so rewriting it on an unchanged run would
    open a pull request whose entire content is a report saying nothing happened.
    """
    committed = (instance / build.GENERATED_DIR / REPORT_FILE).read_bytes()

    result = compile_(instance)

    assert result.report is None
    assert (instance / build.GENERATED_DIR / REPORT_FILE).read_bytes() == committed


def test_a_new_compiler_version_rewrites_the_report_with_the_manifest(instance: Path) -> None:
    """The manifest is part of "did anything change", not merely part of the output.

    It carries the two version numbers (spec 4.3), so a recompile after a plane upgrade
    produces identical Turtle and a different manifest. Comparing the Turtle alone would
    commit a manifest saying 0.2.0 produced these files beside a report whose header says
    0.1.0 did — the one disagreement the report is supposed to be incapable of.
    """
    result = compile_(instance, compiler="0.2.0")

    assert result.changed
    assert result.report is not None
    assert result.report.compiler_version == "0.2.0"
    assert "0.2.0" in (instance / build.GENERATED_DIR / REPORT_FILE).read_text(encoding="utf-8")
    assert (result.report.new, result.report.changed) == ((), ())


def test_a_first_compile_writes_the_whole_directory(instance: Path) -> None:
    """An instance whose ``generated/`` was never written, or was thrown away."""
    shutil.rmtree(instance / build.GENERATED_DIR)

    result = compile_(instance)

    assert sorted(file.name for file in result.files) == [
        ".manifest.json",
        ".report.md",
        "concepts-storefront.ttl",
        "ontology.ttl",
        "relationships-storefront.ttl",
        "taxonomy-product-category.ttl",
    ]
    # Byte for byte what is committed, the report aside: the committed one describes the
    # run that last changed the fixture, and this instance has no history to compare with.
    assert governed(instance) == governed(INSTANCE)


def test_the_report_names_every_source_the_run_fetched(instance: Path) -> None:
    """Only the run knows which adapters it invoked; nothing in the graphs says (spec 5.6)."""
    shutil.rmtree(instance / build.GENERATED_DIR)

    result = compile_(instance)

    assert result.report is not None
    assert [source.name for source in result.report.sources] == [ELLIE, EXCEL]
    assert [source.adapter for source in result.report.sources] == ["ellie", "excel-taxonomy"]
    assert all(source.objects for source in result.report.sources)


# ----------------------------------------------------------------------------- dry runs


def test_a_dry_run_writes_nothing(instance: Path) -> None:
    """Asserted against the whole instance, not against ``generated/``: the ID map is the
    file a dry run would damage most quietly, since a minted row it never wrote out would
    be minted again — differently — by the next run that did."""
    shutil.rmtree(instance / build.GENERATED_DIR)
    before = snapshot(instance)

    result = compile_(instance, dry_run=True)

    assert snapshot(instance) == before
    assert result.changed
    assert len(result.files) == 6


def test_a_dry_run_carries_the_bytes_a_real_run_would_commit(instance: Path) -> None:
    """``--dry-run`` is the same pipeline minus the writes, so what it produces can be
    compared with what a real run commits — which is what makes it worth trusting."""
    shutil.rmtree(instance / build.GENERATED_DIR)

    dry = compile_(instance, dry_run=True)
    real = compile_(instance)

    assert {file.name: file.text for file in dry.files} == {
        file.name: file.text for file in real.files
    }


def test_a_dry_run_deletes_nothing_either(instance: Path) -> None:
    """Removing stale output is a write like any other (spec 4.3), and the whole point of
    a dry run is to find out what one would do to a directory without doing it."""
    (instance / build.GENERATED_DIR / "leftover.txt").write_text("stale", encoding="utf-8")
    before = snapshot(instance)

    result = compile_(instance, dry_run=True)

    assert result.stale == ("leftover.txt",)
    assert "would remove 1 file no longer produced" in result.summary()
    assert snapshot(instance) == before


def test_a_dry_run_says_it_wrote_nothing(instance: Path) -> None:
    shutil.rmtree(instance / build.GENERATED_DIR)

    lines = compile_(instance, dry_run=True).summary()

    assert lines[0].startswith("would write 6 files")
    assert lines[-1] == "dry run: nothing was written"


def test_the_cli_passes_dry_run_through(instance: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shutil.rmtree(instance / build.GENERATED_DIR)
    before = snapshot(instance)

    assert main(["run", "--dry-run"]) == ExitCode.OK

    assert snapshot(instance) == before
    assert "dry run: nothing was written" in capsys.readouterr().out


# -------------------------------------------------------------------------- failing runs


def test_an_unreachable_source_exits_3_and_writes_nothing(
    instance: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one failure CI retries rather than investigates (spec 5.2)."""
    (instance / "sources/taxonomies/product-category.xlsx").unlink()
    before = snapshot(instance)

    assert main(["run"]) == ExitCode.UNREACHABLE

    assert snapshot(instance) == before
    assert capsys.readouterr().err


def test_a_mid_pipeline_failure_leaves_the_instance_untouched(
    instance: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A merge register naming an IRI nothing minted: a real, ordinary way to fail late.

    It is reached after both sources have been fetched and read, which is the case worth
    pinning — nothing is written until every stage has succeeded, so there is no state in
    which ``generated/`` describes one run and ``mappings/`` another.
    """
    (instance / lifecycle.MERGES_PATH).write_text(
        "deprecated_iri,replaced_by_iri,date,note\n"
        f"{BASE}concepts/does-not-exist,{BASE}concepts/{WAREHOUSE},2026-08-06,typo\n",
        encoding="utf-8",
        newline="\n",
    )
    before = snapshot(instance)

    assert main(["run"]) == ExitCode.FAILURE

    assert snapshot(instance) == before
    assert "not in the ID map" in capsys.readouterr().err


def test_two_sources_that_disagree_fail_with_a_message(
    instance: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Which side wins is a stewardship decision, not the compiler's (spec 5.2).

    ``merge_models`` refuses to pick one and raises a plain ``ValueError``, which the CLI
    would print as a traceback — the run names the source it was merging in instead. Only a
    third-party adapter can reach this today, since neither bundled one stamps another
    source's ref onto its objects, so the adapters here are stubs of exactly that shape.
    """

    class Conflicting:
        """Two sources claiming one Ellie UUID, and disagreeing about its label."""

        def __init__(self, label: str) -> None:
            self.label = label

        def fetch(self) -> InternalModel:
            return merge_models(
                InternalModel(
                    schemes=(
                        Scheme(
                            source_refs={ELLIE: "1234"},
                            pref_label="Storefront",
                            slug="storefront",
                            scheme_type=SchemeType.GLOSSARY,
                        ),
                    ),
                    entities=(
                        Entity(
                            source_refs={ELLIE: WAREHOUSE},
                            pref_label=self.label,
                            schemes=("storefront",),
                        ),
                    ),
                )
            )

        def summary(self) -> str:
            return ""

    labels = iter(["Warehouse", "Depot"])
    monkeypatch.setattr(adapters, "create", lambda source, ctx: Conflicting(next(labels)))
    before = snapshot(instance)

    assert main(["run"]) == ExitCode.FAILURE

    err = capsys.readouterr().err
    assert "product-category" in err and "disagree" in err
    assert "Traceback" not in err
    assert snapshot(instance) == before


def test_generated_output_the_id_map_does_not_know_stops_the_run(instance: Path) -> None:
    """Exit 1, not a silent re-mint: a deleted row or a hand-edited file (spec 5.4)."""
    rows = [row for row in IdMap.load(instance) if row.kind is not Kind.SCHEME]
    IdMap(rows).save(instance)
    before = snapshot(instance)

    assert main(["run"]) == ExitCode.FAILURE

    assert snapshot(instance) == before


# ------------------------------------------------------------------------- partial runs


def test_a_partial_run_carries_every_source_it_did_not_fetch(instance: Path) -> None:
    """``--source X`` compiles one source and must still write the whole directory.

    Files are rewritten whole, so the objects of every other source have to arrive from
    somewhere: lifecycle supplies them verbatim (spec 5.4), and the test of that is that a
    run which fetched one of two sources changes nothing at all.
    """
    result = compile_(instance, only_source=ELLIE)

    assert not result.changed
    assert snapshot(instance) == snapshot(INSTANCE)


def test_a_partial_run_does_not_deprecate_what_it_did_not_look_at(instance: Path) -> None:
    """The rule ``--source`` exists to keep: a run that did not look cannot conclude.

    The other source is not merely unfetched here, it is *gone* — a full run would deprecate
    all nine of its objects. The scoped one carries them forward untouched instead.
    """
    (instance / "sources/taxonomies/product-category.xlsx").unlink()

    compile_(instance, only_source=ELLIE)

    taxonomy = graph_of(instance, "taxonomy-product-category.ttl")
    statuses = {str(status) for status in taxonomy.objects(None, build.SEM_STATUS)}
    assert statuses == {build.STATUS_ACTIVE}
    assert (instance / build.GENERATED_DIR / "taxonomy-product-category.ttl").read_bytes() == (
        INSTANCE / build.GENERATED_DIR / "taxonomy-product-category.ttl"
    ).read_bytes()


def test_a_partial_run_refuses_an_object_two_sources_describe(instance: Path) -> None:
    """The case carry-forward cannot cover: the model holds the object rebuilt from one
    source's statements, and writing it would delete the other's (spec 5.4)."""
    shared = f"{BASE}concepts/{WAREHOUSE}"
    id_map = IdMap.load(instance)
    id_map.append(
        IdMapRow(
            iri=shared,
            kind=Kind.ENTITY,
            source_name=EXCEL,
            source_key="warehouse",
            first_seen=TODAY,
        )
    )
    id_map.save(instance)
    before = snapshot(instance)

    with pytest.raises(build.BuildError, match="which this --source ellie-main run did not fetch"):
        compile_(instance, only_source=ELLIE)

    assert snapshot(instance) == before


def test_a_partial_run_is_idempotent(instance: Path) -> None:
    """Two partial runs of the same source, like two full ones, produce zero diff."""
    assert main(["run", "--source", EXCEL]) == ExitCode.OK
    after_first = snapshot(instance)

    assert main(["run", "--source", EXCEL]) == ExitCode.OK

    assert snapshot(instance) == after_first


# --------------------------------------------------------------------------- deprecation


def test_an_object_a_source_deleted_is_deprecated_in_place(instance: Path) -> None:
    """The lifecycle promise, through a whole run (spec 3.5): retained, not removed."""
    drop_entity(instance, WAREHOUSE)

    result = compile_(instance)

    assert f"{BASE}concepts/{WAREHOUSE}" in result.deprecated
    concepts = graph_of(instance, "concepts-storefront.ttl")
    assert (
        URIRef(f"{BASE}concepts/{WAREHOUSE}"),
        URIRef(f"{build.SEM}status"),
        None,
    ) in concepts
    assert build.STATUS_DEPRECATED in (
        instance / build.GENERATED_DIR / "concepts-storefront.ttl"
    ).read_text(encoding="utf-8")
    # The row stays: deprecation is a status, not a tombstone, and the object is active
    # again under the same IRI if its source restores it.
    assert any(row.source_key == WAREHOUSE for row in IdMap.load(instance))


def test_deprecating_is_done_once_and_then_stays_put(instance: Path) -> None:
    """The second run must not re-date what the first deprecated (spec 3.3)."""
    drop_entity(instance, WAREHOUSE)
    compile_(instance)
    after_first = snapshot(instance)

    second = compile_(instance, today=TODAY.replace(year=TODAY.year + 1))

    assert not second.changed
    assert snapshot(instance) == after_first


# ------------------------------------------------------------------------- stale output


def test_output_the_run_did_not_produce_is_removed(instance: Path) -> None:
    """``generated/`` is the run's output and nothing else (spec 4.3).

    A file left behind is read as current by anything that loads the directory, and it
    fails the manifest's unrecorded-file check on the next PR.
    """
    generated = instance / build.GENERATED_DIR
    (generated / "leftover.txt").write_text("stale", encoding="utf-8")
    (generated / "old").mkdir()
    (generated / "old" / "concepts-retired.ttl").write_text("", encoding="utf-8")

    result = compile_(instance)

    assert result.stale == ("leftover.txt", "old/concepts-retired.ttl")
    assert governed(instance) == governed(INSTANCE)
    assert not (generated / "old").exists()


def test_removing_stale_output_is_a_change_the_report_describes(instance: Path) -> None:
    """A run can produce byte-identical files and still have changed the instance.

    Comparing only what was produced would leave the committed report describing a
    directory that no longer exists, which is the one thing it must never do (spec 5.6).
    """
    (instance / build.GENERATED_DIR / "leftover.txt").write_text("stale", encoding="utf-8")

    result = compile_(instance)

    assert result.changed
    assert result.report is not None
    assert "removed 1 file no longer produced" in result.summary()


def test_the_id_map_is_saved_before_stale_output_is_removed(
    instance: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing may come between the files and the map that names their IRIs.

    Deleting a stale file can fail — a locked file, a directory somebody made read-only —
    and if it did so between the two, ``generated/`` would hold IRIs the ID map does not.
    That is a state the next run refuses (spec 5.4) and only deleting ``generated/``
    recovers from, in exchange for a step that has nothing to do with identity.
    """
    order: list[str] = []
    original_save, original_remove = IdMap.save, build.remove

    def save(self: IdMap, repo_root: Path | None = None) -> Path:
        order.append("map")
        return original_save(self, repo_root)

    def remove(stale: Any, root: Path | None = None) -> None:
        order.append("remove")
        original_remove(stale, root)

    monkeypatch.setattr(IdMap, "save", save)
    monkeypatch.setattr(build, "remove", remove)
    (instance / build.GENERATED_DIR / "leftover.txt").write_text("stale", encoding="utf-8")

    compile_(instance)

    assert order == ["map", "remove"]


def test_the_report_is_never_stale(instance: Path) -> None:
    """It is written on different terms — only when something moved — so a run that
    produced no report has not stopped producing the one that is committed."""
    result = compile_(instance)

    assert result.report is None
    assert result.stale == ()
    assert (instance / build.GENERATED_DIR / REPORT_FILE).exists()


# --------------------------------------------------------------------- the namespace move


def move_to(root: Path, base_iri: str) -> None:
    path = root / config.CONFIG_PATH
    path.write_text(
        path.read_text(encoding="utf-8").replace(BASE, base_iri), encoding="utf-8", newline="\n"
    )


MOVED = "https://vocab.example.org/"


def test_a_namespace_move_rewrites_every_iri_and_nothing_else(instance: Path) -> None:
    """Spec 3.4.4: the ID map, the lock and every generated file, in one commit.

    The claim a reviewer of that commit has to be able to check is "every IRI moved and no
    content did", so the run's own report is part of the assertion: nothing new, nothing
    changed. The previous state is rebased before lifecycle sees it, which is also what
    keeps ``dcterms:modified`` from moving on every node in the instance.
    """
    dates = {
        str(subject): str(date)
        for subject, date in graph_of(instance, "concepts-storefront.ttl").subject_objects(
            DCTERMS.modified
        )
    }
    move_to(instance, MOVED)

    result = compile_(instance, force_namespace_change=True)

    assert result.changed
    assert result.report is not None
    assert (result.report.new, result.report.changed, result.report.deprecated) == ((), (), ())
    assert NamespaceLock.load(instance).base_iri == MOVED
    assert all(row.iri.startswith(MOVED) for row in IdMap.load(instance))
    moved = graph_of(instance, "concepts-storefront.ttl")
    assert all(str(subject).startswith(MOVED) for subject in moved.subjects(unique=True))
    assert {
        str(subject).replace(MOVED, BASE): str(date)
        for subject, date in moved.subject_objects(DCTERMS.modified)
    } == dates


def test_a_namespace_move_keeps_the_local_names(instance: Path) -> None:
    """The object keeps its identity and changes only where it lives (spec 3.4.4)."""
    before = [row.iri for row in IdMap.load(instance)]
    move_to(instance, MOVED)

    compile_(instance, force_namespace_change=True)

    assert [row.iri for row in IdMap.load(instance)] == [iri.replace(BASE, MOVED) for iri in before]


def test_a_move_carries_a_deprecated_node_with_it(instance: Path) -> None:
    """The reason the previous state is rebased rather than discarded.

    A node no source reports any more exists only in ``generated/``. Read against the
    moved map without rebasing, its IRI is one the ID map has never heard of — which is a
    refused run at best, and the silent deletion of every deprecated object at worst.
    """
    drop_entity(instance, WAREHOUSE)
    compile_(instance)
    move_to(instance, MOVED)

    compile_(instance, force_namespace_change=True)

    concepts = graph_of(instance, "concepts-storefront.ttl")
    assert (
        URIRef(f"{MOVED}concepts/{WAREHOUSE}"),
        URIRef(f"{build.SEM}status"),
        None,
    ) in concepts
    assert build.STATUS_DEPRECATED in (
        instance / build.GENERATED_DIR / "concepts-storefront.ttl"
    ).read_text(encoding="utf-8")


def test_a_moved_instance_then_compiles_like_any_other(instance: Path) -> None:
    """The move is a migration, and the run after it is an ordinary run."""
    move_to(instance, MOVED)
    compile_(instance, force_namespace_change=True)

    after = compile_(instance)

    assert not after.changed


def test_a_move_cannot_be_combined_with_a_partial_run(instance: Path) -> None:
    """Exit 2: the commit would make two claims at once and neither could be checked."""
    move_to(instance, MOVED)

    assert main(["run", "--force-namespace-change", "--source", ELLIE]) == ExitCode.CONFIG
    assert NamespaceLock.load(instance).base_iri == BASE


def test_a_dry_run_of_a_move_writes_nothing(instance: Path) -> None:
    """Including the map and the lock: the migration is computed, not performed."""
    move_to(instance, MOVED)
    before = snapshot(instance)

    result = compile_(instance, force_namespace_change=True, dry_run=True)

    assert snapshot(instance) == before
    assert all(
        MOVED in file.text
        for file in result.files
        if file.name.endswith(".ttl") and file.name != build.ONTOLOGY_FILE
    )


def test_a_failed_move_leaves_the_instance_where_it_was(instance: Path) -> None:
    """Nothing is written until the compile succeeds, which is what makes the move
    recoverable: an instance whose map had moved and whose output had not could neither
    move again — the flag refuses a base IRI already locked — nor compile."""
    move_to(instance, MOVED)
    (instance / "sources/taxonomies/product-category.xlsx").unlink()
    before = snapshot(instance)

    assert main(["run", "--force-namespace-change"]) == ExitCode.UNREACHABLE

    assert snapshot(instance) == before
    assert (instance / ID_MAP_PATH).read_bytes() == before[ID_MAP_PATH.as_posix()]
    assert (instance / NAMESPACE_LOCK_PATH).read_bytes() == before[NAMESPACE_LOCK_PATH.as_posix()]


def test_the_move_writes_the_map_before_the_lock(
    instance: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Order matters on the one file pair that must never disagree (spec 3.4.4).

    If the lock were written first and the map's write then failed, the instance would say
    it lives in the new namespace while every row still named the old one — and the next
    run would mint a second IRI for every object. The other order leaves it recoverable.
    """
    written: list[str] = []
    original_map, original_lock = IdMap.save, NamespaceLock.save

    def save_map(self: IdMap, repo_root: Path | None = None) -> Path:
        written.append("map")
        return original_map(self, repo_root)

    def save_lock(self: NamespaceLock, repo_root: Path | None = None) -> Path:
        written.append("lock")
        return original_lock(self, repo_root)

    monkeypatch.setattr(IdMap, "save", save_map)
    monkeypatch.setattr(NamespaceLock, "save", save_lock)
    move_to(instance, MOVED)

    compile_(instance, force_namespace_change=True)

    assert written == ["map", "lock"]


def test_a_namespace_move_takes_the_merge_register_with_it(instance: Path) -> None:
    """The register is the one file holding IRIs a person typed (spec 5.4).

    Left behind, every row would name an IRI the moved map has never heard of and the run
    would refuse itself — so this migration could not be performed at all on an instance
    that had ever recorded a merge, which is every instance old enough to need one.
    """
    drop_entity(instance, WAREHOUSE)
    record_merge(instance, f"{BASE}concepts/{WAREHOUSE}", f"{BASE}concepts/{DELIVERY}")
    compile_(instance)
    move_to(instance, MOVED)

    compile_(instance, force_namespace_change=True)

    register = lifecycle.MergeRegister.load(instance)
    assert [(row.deprecated_iri, row.replaced_by_iri) for row in register] == [
        (f"{MOVED}concepts/{WAREHOUSE}", f"{MOVED}concepts/{DELIVERY}")
    ]
    assert register.rows[0].note == "merged into the survivor"
    assert (
        URIRef(f"{MOVED}concepts/{WAREHOUSE}"),
        DCTERMS.isReplacedBy,
        URIRef(f"{MOVED}concepts/{DELIVERY}"),
    ) in graph_of(instance, "concepts-storefront.ttl")


def test_an_ordinary_run_never_writes_the_merge_register(instance: Path) -> None:
    """Every row in it is a steward's decision; only the namespace move rewrites one.

    Written with spacing a person would leave and the compiler would normalize away, so
    "unchanged" means untouched rather than merely re-rendered the same.
    """
    (instance / lifecycle.MERGES_PATH).write_text(
        "deprecated_iri,replaced_by_iri,date,note\n", encoding="utf-8", newline="\n"
    )
    (instance / lifecycle.MERGES_PATH).write_bytes(
        (instance / lifecycle.MERGES_PATH).read_bytes() + b"\n"
    )
    before = (instance / lifecycle.MERGES_PATH).read_bytes()

    compile_(instance)

    assert (instance / lifecycle.MERGES_PATH).read_bytes() == before


def test_planning_a_move_is_what_the_run_calls(instance: Path) -> None:
    """The moved map and lock reach the disk through the run, not through identity."""
    move_to(instance, MOVED)
    lock, moved = identity.plan_namespace_change(
        config.load(instance), ontology_version=ONTOLOGY, today=TODAY
    )

    assert lock.base_iri == MOVED
    assert all(row.iri.startswith(MOVED) for row in moved)
    assert NamespaceLock.load(instance).base_iri == BASE

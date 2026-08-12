"""``semprini check`` end to end, on a whole instance (spec 6.1).

The command an adopting organization's CI runs on every pull request, and the only thing
standing between a hand edit and a governed file. Two claims are asserted here and nowhere
else.

*A green check means the instance is committable.* Every one of the seven checks has a
purpose-built failing fixture below, so a check that stopped checking would show up as a
test that stopped failing — which is the failure mode a validation suite is most prone to
and least able to notice.

*A check that could not run says so.* The ID map's append-only rule is a claim about a
change, so it needs the base revision, and there is not always one. Reporting "ok" for a
comparison that never happened is the one outcome worse than reporting nothing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tools.build_fixture_instance import COMPILER, ONTOLOGY

from semprini import build, config, lifecycle, validate
from semprini.cli import ExitCode, main
from semprini.identity import ID_MAP_PATH, NAMESPACE_LOCK_PATH, NamespaceLockError
from semprini.manifest import MANIFEST_FILE, Manifest
from semprini.model import Issue, Severity
from semprini.validate import CHECKS, CheckOutcome, CheckResult

GENERATED = build.GENERATED_DIR
CONCEPTS = "concepts-storefront.ttl"
TAXONOMY = "taxonomy-product-category.ttl"


# ------------------------------------------------------------------------- helpers


def check(root: Path, **overrides: Any) -> CheckResult:
    """Check the instance at ``root`` with both versions pinned, as it was compiled.

    Pinned for the reason a run pins them: an assertion about this task's behaviour must
    not move when the plane is released (spec 7). The drift check has its own test, which
    is where an unpinned version belongs.
    """
    arguments: dict[str, Any] = {"compiler": COMPILER, "ontology": ONTOLOGY}
    arguments.update(overrides)
    return validate.check(config.load(root), **arguments)


def outcome(result: CheckResult, number: int) -> CheckOutcome:
    (found,) = [item for item in result.outcomes if item.number == number]
    return found


def failed(result: CheckResult, number: int) -> tuple[Issue, ...]:
    """The errors of one check, asserting that it is the check that found them.

    Checks overlap by design — a subject outside the instance's namespace is refused by
    check 4 and again by check 5's IRI policy — so a test names the check it is about and
    the others are free to agree.
    """
    errors = outcome(result, number).errors
    assert errors, f"check {number} ({CHECKS[number - 1]}) reported nothing"
    return errors


def read(path: Path) -> str:
    """A file exactly as it is on disk, line endings included."""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def edit(path: Path, change: Callable[[str], str]) -> None:
    write(path, change(read(path)))


def rehash(root: Path) -> None:
    """Recompute ``.manifest.json`` for whatever is in ``generated/`` now.

    What lets a test fail exactly one check. Editing a generated file trips the manifest
    (check 2) whatever else it does, so a fixture built to exercise SHACL or determinism
    would otherwise be indistinguishable from a fixture built to exercise hashing — and a
    test that fails for the wrong reason passes for the wrong reason too.
    """
    files = [
        build.OutputFile(name=path.name, text=read(path))
        for path in sorted((root / GENERATED).glob("*.ttl"))
    ]
    write(
        root / GENERATED / MANIFEST_FILE,
        Manifest.create(files, compiler=COMPILER, ontology=ONTOLOGY).dumps(),
    )


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=root, capture_output=True, text=True, check=True
    )
    return completed.stdout.strip()


def commit(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "--no-gpg-sign", "-m", message)
    return git(root, "rev-parse", "HEAD")


LINE_ENDINGS = """\
# An instance's committed files are LF, and CI compares them byte for byte (spec 6.1
# check 7). Without this, a Windows checkout with core.autocrlf=true rewrites every
# generated file's line endings and the determinism check fails on content nobody
# touched. **G1's scaffold owes every instance this file.**
* text=auto eol=lf
*.xlsx binary
"""


def init_repo(root: Path) -> None:
    """Make ``root`` a git repository holding one commit, as an instance really is.

    The ``.gitattributes`` is not decoration. It was written here because its absence
    failed :func:`test_the_base_is_the_merge_base_and_not_the_branch_tip` on Windows:
    ``core.autocrlf`` rewrote the ID map on checkout. That is not a test artefact — it is
    what an adopting organization's clone does to `generated/` on the first pull request,
    and check 7 is right to fail it.
    """
    write(root / ".gitattributes", LINE_ENDINGS)
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.email", "steward@example.com")
    git(root, "config", "user.name", "Steward")
    git(root, "config", "commit.gpgsign", "false")


@pytest.fixture
def repository(instance: Path) -> Path:
    """The fixture instance as a git repository with one commit on ``main``.

    Check 6's append-only half is the only part of ``semprini check`` that reads anything
    outside the working tree, and a real repository is the only way to test it: the
    question is what git says about a revision, and a stubbed git would be a test of the
    stub.
    """
    init_repo(instance)
    commit(instance, "the instance as compiled")
    return instance


# --------------------------------------------------------------- the committed instance


def test_the_fixture_instance_passes(instance: Path) -> None:
    result = check(instance)

    assert result.ok
    assert not result.errors
    assert main(["check"]) == ExitCode.OK


def test_every_check_is_reported_in_order(instance: Path) -> None:
    # The listing is the contract an operator reads, so a check silently dropped from the
    # sequence must be visible as a missing line rather than as one fewer thing failing.
    result = check(instance)

    assert [item.number for item in result.outcomes] == [1, 2, 3, 4, 5, 6, 7]
    assert [item.name for item in result.outcomes] == list(CHECKS)
    assert len(CHECKS) == 7


def test_warnings_are_reported_and_do_not_fail_the_command(instance: Path) -> None:
    # The missing-definition rule of spec 6.1.5 is reported, not blocking, until an
    # instance's steward workflows are ready for it.
    result = check(instance)

    assert result.warnings
    assert all(issue.severity is Severity.WARNING for issue in result.warnings)
    assert result.ok
    assert "warning" in "\n".join(result.summary())


def test_check_writes_nothing(instance: Path) -> None:
    # `semprini check` runs on pull requests, where it may not have permission to write and
    # certainly has no business doing so: "validate only, no writes" (spec 5.1).
    before = snapshot(instance)

    assert main(["check"]) == ExitCode.OK

    assert snapshot(instance) == before


def test_the_summary_says_which_check_found_what(instance: Path) -> None:
    edit(instance / GENERATED / CONCEPTS, lambda text: text + "\n")
    rehash(instance)

    lines = check(instance).summary()

    assert any(line.startswith("7. determinism: 1 error") for line in lines)
    assert any(line.startswith("1. syntax: ok") for line in lines)
    assert lines[-1] == "1 error, 4 warnings"


# ------------------------------------------------------------------------ check 1: syntax


def test_unparseable_generated_output_fails_check_1(instance: Path) -> None:
    edit(instance / GENERATED / CONCEPTS, lambda text: text + "\nthis is not turtle .\n")

    result = check(instance)

    assert not result.ok
    assert CONCEPTS in str(failed(result, 1)[0])
    assert main(["check"]) == ExitCode.FAILURE


def test_an_unparseable_overlay_fails_check_1(instance: Path) -> None:
    # Hand-written RDF is where a syntax error is likely rather than suspicious (spec 4.2),
    # and it must be named as a file rather than surface as an rdflib traceback.
    (instance / "overlays" / "ext").mkdir(parents=True)
    write(instance / "overlays" / "ext" / "terms.ttl", "@prefix x: <http://x/> .\nx:a x:b .\n")

    assert "terms.ttl" in str(failed(check(instance), 1)[0])


def test_an_unparseable_local_shape_fails_check_1(instance: Path) -> None:
    (instance / "shapes" / "local").mkdir(parents=True)
    write(instance / "shapes" / "local" / "rules.ttl", "@prefix sh: <http://sh#> .\n(\n")

    assert "rules.ttl" in str(failed(check(instance), 1)[0])


def test_an_unparseable_ontology_copy_fails_check_1(instance: Path) -> None:
    # Skipped by `read_previous_files` — it is the metamodel, and no subject in it is an
    # instance's to date or deprecate — so it needs parsing here or nothing parses it.
    edit(instance / GENERATED / build.ONTOLOGY_FILE, lambda text: text + "\nbroken .\n")

    assert failed(check(instance), 1)


def test_the_checks_that_need_parsed_content_are_not_run_when_it_does_not_parse(
    instance: Path,
) -> None:
    # Answering checks 4 to 7 from the files that happened to load would invent problems on
    # top of the real one: a subject reported as missing from the ID map because the file
    # naming it is the broken one.
    edit(instance / GENERATED / CONCEPTS, lambda text: "@prefix nonsense\n" + text)

    result = check(instance)

    assert [item.number for item in result.outcomes if item.skipped] == [4, 5, 6, 7]
    assert all("check 1" in (item.skipped or "") for item in result.outcomes if item.skipped)
    # The manifest is bytes and versions, so checks 2 and 3 answer without a parser and
    # still run — the operator learns everything this instance can be told in one round.
    assert outcome(result, 2).issues
    assert outcome(result, 3).skipped is None


# ------------------------------------------------------------- check 2: manifest integrity


def test_a_hand_edited_generated_file_fails_check_2(instance: Path) -> None:
    # The check that makes "generated/ is machine-owned" enforceable rather than a
    # convention (spec 4.3): a corrected label is invisible in a PR that also holds a real
    # change, and the next compile would silently revert it.
    edit(instance / GENERATED / CONCEPTS, lambda text: text.replace("Delivery", "Shipment"))

    assert CONCEPTS in str(failed(check(instance), 2)[0])


def test_an_unrecorded_file_fails_check_2(instance: Path) -> None:
    write(instance / GENERATED / "notes.txt", "left behind by a steward\n")

    assert "notes.txt" in str(failed(check(instance), 2)[0])


def test_a_recorded_file_that_is_gone_fails_check_2(instance: Path) -> None:
    (instance / GENERATED / TAXONOMY).unlink()

    assert TAXONOMY in str(failed(check(instance), 2)[0])


def test_a_missing_manifest_fails_check_2_and_stops_check_3(instance: Path) -> None:
    (instance / GENERATED / MANIFEST_FILE).unlink()

    result = check(instance)

    assert failed(result, 2)
    # Not "ok": there are no recorded versions to compare against, and a version check that
    # passes because it had nothing to read is the shape of green this command must not have.
    assert outcome(result, 3).skipped is not None
    assert not result.ok


def test_a_malformed_manifest_fails_check_2(instance: Path) -> None:
    write(instance / GENERATED / MANIFEST_FILE, "{ not json\n")

    assert failed(check(instance), 2)


# ----------------------------------------------------------------- check 3: version drift


def test_a_newer_compiler_fails_check_3(instance: Path) -> None:
    # Drift is not a defect in the output — the files are exactly what the recorded version
    # produced. It says the instance has not been recompiled since the plane was upgraded,
    # which is a separate reviewable PR precisely so an upgrade's reflow never arrives
    # mixed into a content change (spec 7).
    result = check(instance, compiler="0.2.0")

    assert "0.2.0" in str(failed(result, 3)[0])
    assert outcome(result, 2).passed


def test_a_newer_ontology_fails_check_3(instance: Path) -> None:
    assert "0.2.0" in str(failed(check(instance, ontology="0.2.0"), 3)[0])


def test_the_ontology_copy_is_not_reported_twice_when_the_version_drifted(
    instance: Path,
) -> None:
    # With the ontology version drifted the committed copy is *expected* to differ from the
    # one this compiler carries, so check 7 says nothing about it and check 3 says it once.
    edit(instance / GENERATED / build.ONTOLOGY_FILE, lambda text: text.replace("0.1.0", "0.2.0"))
    rehash(instance)

    result = check(instance, ontology="0.2.0")

    assert failed(result, 3)
    assert outcome(result, 7).passed


# ---------------------------------------------------------------- check 4: namespace lock


def test_a_base_iri_that_disagrees_with_the_lock_exits_2(instance: Path) -> None:
    # Exit 2 rather than 1, and raised rather than collected: the lock is frozen
    # configuration, and an edited base IRI would silently mint a parallel universe of
    # IRIs (spec 3.4.4).
    edit(
        instance / "config" / "semprini.yaml",
        lambda text: text.replace("https://semantics.example.com/", "https://elsewhere.test/"),
    )

    assert main(["check"]) == ExitCode.CONFIG


def test_a_missing_lock_exits_2(instance: Path) -> None:
    (instance / NAMESPACE_LOCK_PATH).unlink()

    assert main(["check"]) == ExitCode.CONFIG


def test_the_lock_is_checked_by_check_itself_and_not_only_by_the_cli(instance: Path) -> None:
    # The CLI verifies the lock when it loads configuration, so a `check` that had stopped
    # doing so would still exit 2 through `main` and look fine. Asserted here directly, so
    # that any caller of `check` gets the whole of check 4 rather than the half that reads
    # graphs.
    edit(
        instance / "config" / "semprini.yaml",
        lambda text: text.replace("https://semantics.example.com/", "https://elsewhere.test/"),
    )

    with pytest.raises(NamespaceLockError):
        check(instance)


def test_a_subject_outside_the_instance_namespace_fails_check_4(instance: Path) -> None:
    # A lock nothing compares content against would let an instance drift into a second
    # namespace one hand-edited subject at a time.
    edit(
        instance / GENERATED / CONCEPTS,
        lambda text: text.replace("c:07666880-aa23-11ee-94e1-0242ac1e0003", "<https://other/x>"),
    )
    rehash(instance)

    assert "https://other/x" in str(failed(check(instance), 4)[0])


# ------------------------------------------------------------------------- check 5: SHACL


def test_a_node_without_a_label_fails_check_5(instance: Path) -> None:
    # Removing a whole statement leaves a canonically serialized file, which is what lets
    # this fixture fail check 5 alone.
    edit(
        instance / GENERATED / CONCEPTS,
        lambda text: "\n".join(
            line for line in text.splitlines(keepends=True) if "skos:prefLabel" not in line
        ).replace("\n\n\n", "\n\n"),
    )
    rehash(instance)

    assert failed(check(instance), 5)


def test_an_overlay_may_not_restate_a_generated_label(instance: Path) -> None:
    (instance / "overlays" / "patches").mkdir(parents=True)
    write(
        instance / "overlays" / "patches" / "labels.ttl",
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        "<https://semantics.example.com/concepts/07666880-aa23-11ee-94e1-0242ac1e0003> "
        'skos:prefLabel "Renamed by hand"@en .\n',
    )

    assert failed(check(instance), 5)


def test_the_shapes_see_the_content_the_checks_read(instance: Path) -> None:
    # The graphs are parsed once and passed in, so a defect reaches check 5 exactly as it
    # reaches the rest: passing pre-read graphs must not quietly validate something else.
    settings = config.load(instance)
    direct = validate.check_shapes(instance, base_iri=settings.base_iri)

    assert set(outcome(check(instance), 5).issues) == set(direct)


# ------------------------------------------------------------------------ check 6: identity


def test_a_generated_subject_missing_from_the_id_map_fails_check_6(instance: Path) -> None:
    # A deleted row or a hand-edited file: the compiler cannot say which source the node
    # came from, and dropping it would be the deletion the whole mechanism prevents. Asked
    # without reference to git, so it holds for a local run too (spec 5.4).
    edit(
        instance / ID_MAP_PATH,
        lambda text: (
            "\n".join(
                line
                for line in text.splitlines()
                if "07666880-aa23-11ee-94e1-0242ac1e0003" not in line
            )
            + "\n"
        ),
    )

    assert "07666880" in str(failed(check(instance), 6)[0])


def test_an_unconfigured_source_name_fails_check_6(instance: Path) -> None:
    # Renaming a source in configuration breaks identity resolution — every lookup misses
    # and every object mints again — so it is a procedure that rewrites the column, not a
    # config edit (spec 5.4).
    edit(
        instance / "config" / "semprini.yaml",
        lambda text: text.replace("name: ellie-main", "name: ellie-primary"),
    )

    assert "ellie-main" in str(failed(check(instance), 6)[0])


def test_a_merge_register_naming_an_unminted_iri_fails_check_6(instance: Path) -> None:
    # The one file in an instance where a person types an IRI, so it is validated strictly
    # (spec 5.4).
    write(
        instance / lifecycle.MERGES_PATH,
        "deprecated_iri,replaced_by_iri,date,note\n"
        "https://semantics.example.com/concepts/nope,"
        "https://semantics.example.com/concepts/also-nope,2026-08-06,typed by hand\n",
    )

    assert failed(check(instance), 6)


def test_a_malformed_id_map_fails_check_6(instance: Path) -> None:
    edit(instance / ID_MAP_PATH, lambda text: text.replace("iri,kind", "iri,type"))

    assert failed(check(instance), 6)


# --------------------------------------------------- check 6: append-only, against git


def test_a_rewritten_row_fails_check_6_against_the_base_revision(repository: Path) -> None:
    # An edited row is a lost IRI written differently: every column but `note` is immutable
    # (spec 5.4). The IRI itself is untouched here, so this is the append-only rule failing
    # on its own rather than the unmapped-subject check firing again.
    edit(repository / ID_MAP_PATH, lambda text: text.replace("2026-08-06", "2020-01-01", 1))

    assert "was rewritten" in str(failed(check(repository, base="HEAD"), 6)[0])


def test_a_removed_row_fails_check_6_against_the_base_revision(repository: Path) -> None:
    edit(
        repository / ID_MAP_PATH,
        lambda text: (
            "\n".join(line for line in text.splitlines() if "schemes/product-category" not in line)
            + "\n"
        ),
    )

    assert any(
        "no longer maps" in str(issue) for issue in failed(check(repository, base="HEAD"), 6)
    )


def test_an_edited_note_is_allowed(repository: Path) -> None:
    # `note` is the one field stewards own, and a check that refused an annotation would
    # teach them not to annotate.
    edit(repository / ID_MAP_PATH, lambda text: text.replace(",2026-08-06,\n", ",2026-08-06,ok\n"))

    assert check(repository, base="HEAD").ok


def test_appending_a_row_is_allowed(repository: Path) -> None:
    edit(
        repository / ID_MAP_PATH,
        lambda text: (
            text + "https://semantics.example.com/concepts/00000000-0000-5000-8000-000000000000,"
            "entity,ellie-main,new-key,2026-08-07,\n"
        ),
    )

    assert outcome(check(repository, base="HEAD"), 6).passed


def test_the_base_is_the_merge_base_and_not_the_branch_tip(repository: Path) -> None:
    """A row another pull request merged into the base branch is not this branch's to have.

    The case that decides between comparing against the fork point and against the tip. A
    tip comparison would report every row merged since this branch forked as a row this
    change deleted, and a check that fails on other people's work is a check people learn
    to force past.
    """
    git(repository, "checkout", "-b", "compile/2026-08-07")
    fork_point_row = read(repository / ID_MAP_PATH)
    git(repository, "checkout", "main")
    edit(
        repository / ID_MAP_PATH,
        lambda text: (
            text + "https://semantics.example.com/concepts/11111111-1111-5111-8111-111111111111,"
            "entity,ellie-main,merged-elsewhere,2026-08-07,\n"
        ),
    )
    commit(repository, "another pull request, already merged")
    git(repository, "checkout", "compile/2026-08-07")

    assert read(repository / ID_MAP_PATH) == fork_point_row
    assert outcome(check(repository, base="main"), 6).passed


def test_a_base_revision_holding_no_id_map_is_an_empty_map(instance: Path) -> None:
    # The first pull request of an instance's life: everything in the map is an addition,
    # and the check that protects it must not fail on the commit that creates it.
    init_repo(instance)
    mappings = read(instance / ID_MAP_PATH)
    (instance / ID_MAP_PATH).unlink()
    first = commit(instance, "an instance without an ID map")
    write(instance / ID_MAP_PATH, mappings)

    assert outcome(check(instance, base=first), 6).passed


def test_the_instance_may_be_a_subdirectory_of_the_repository(instance: Path) -> None:
    # git addresses a blob from the repository root, and an instance is not always one: a
    # monorepo holding several is an ordinary layout, and the path prefix is what makes
    # `<rev>:mappings/id-map.csv` name this instance's map rather than nothing.
    root = instance.parent
    init_repo(root)
    commit(root, "a repository holding an instance among other things")
    edit(instance / ID_MAP_PATH, lambda text: text.replace("2026-08-06", "2020-01-01", 1))

    assert git(instance, "rev-parse", "--show-prefix") == f"{instance.name}/"
    assert "was rewritten" in str(failed(check(instance, base="HEAD"), 6)[0])


def test_the_append_only_check_reports_itself_not_run_without_a_base_revision(
    instance: Path,
) -> None:
    # An instance that is not a git repository is an ordinary instance — `semprini init`
    # creates no repository (spec 5.7) — so this must not fail, and must not claim to have
    # compared anything either.
    result = check(instance)

    assert result.ok
    # Not "passed": a comparison that never happened and a comparison that found nothing
    # are indistinguishable in an exit code, and the whole value of this command is that a
    # green run means something.
    assert not outcome(result, 6).passed
    assert not outcome(result, 6).issues
    # Says what to do about it: an operator who wanted the comparison has one flag to pass.
    assert "--base" in (outcome(result, 6).skipped or "")
    assert "not run" in "\n".join(result.summary())


def test_an_unresolvable_base_revision_reports_itself_not_run(repository: Path) -> None:
    result = check(repository, base="no-such-branch")

    assert "no-such-branch" in (outcome(result, 6).skipped or "")
    assert not outcome(result, 6).passed
    assert result.ok


def test_an_unreadable_id_map_at_the_base_revision_reports_itself_not_run(
    repository: Path,
) -> None:
    """A base revision whose ID map is damaged is no base revision.

    The tempting shortcut is to treat it as an empty map, which makes the comparison
    trivially pass — and "every row was added" is exactly the wrong answer when the file
    that would say otherwise is the one that cannot be read. The *current* map is checked
    on its own terms either way, so nothing goes unexamined.
    """
    edit(repository / ID_MAP_PATH, lambda text: text.replace("iri,kind", "iri,type"))
    damaged = commit(repository, "a damaged ID map")
    git(repository, "revert", "--no-edit", "--no-gpg-sign", damaged)

    result = check(repository, base=damaged)

    assert "could not be read" in (outcome(result, 6).skipped or "")
    assert not outcome(result, 6).passed


def test_the_other_identity_questions_are_answered_without_a_base_revision(
    instance: Path,
) -> None:
    # "Not run" is about the append-only comparison alone. The three questions the working
    # tree can answer are still answered, and a failure among them is reported as a failure
    # rather than hidden behind the check that could not run.
    edit(
        instance / "config" / "semprini.yaml",
        lambda text: text.replace("name: ellie-main", "name: ellie-primary"),
    )

    result = check(instance)

    assert failed(result, 6)
    assert not result.ok
    # Neither half hides the other: the finding is what an operator fixes, and the part
    # that did not run is what they would otherwise assume had passed.
    assert outcome(result, 6).skipped is not None
    printed = "\n".join(result.summary())
    assert "not run: no base revision" in printed
    assert "which is not configured" in printed


def test_a_pull_request_base_branch_is_discovered_from_the_environment(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The one platform default. Everywhere else passes --base, which is what keeps the
    # check portable (spec 6.3).
    monkeypatch.setenv(validate.ENVIRONMENT_BASE_REF, "main")
    git(repository, "checkout", "-b", "compile/2026-08-07")
    edit(repository / ID_MAP_PATH, lambda text: text.replace("2026-08-06", "2020-01-01", 1))

    assert "was rewritten" in str(failed(check(repository), 6)[0])


def test_a_clone_finds_its_base_revision_without_being_told(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # What CI has after `git clone`: no environment variable, but `origin/HEAD` naming the
    # default branch. Cloned rather than faked, because "does git know a base revision" is
    # exactly the question and a stub would answer it by construction.
    monkeypatch.delenv(validate.ENVIRONMENT_BASE_REF, raising=False)
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "--quiet", str(repository), str(clone))
    edit(clone / ID_MAP_PATH, lambda text: text.replace("2026-08-06", "2020-01-01", 1))

    assert "was rewritten" in str(failed(check(clone), 6)[0])


def test_git_failures_are_never_a_traceback(
    instance: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # git missing, not a repository, an unknown revision and a shallow clone all mean one
    # thing to check 6, and none of them may reach an operator as a subprocess traceback.
    def missing(*arguments: Any, **keywords: Any) -> None:
        raise OSError("git: command not found")

    monkeypatch.setattr(subprocess, "run", missing)

    assert check(instance).ok


# -------------------------------------------------------------------- check 7: determinism


def test_a_reformatted_file_fails_check_7(instance: Path) -> None:
    # The check that does not trust the manifest: every other guarantee about generated/ is
    # recorded in a file the compiler also wrote, so a hand edit that recomputes the hash
    # defeats it. This one re-derives the bytes from the graph.
    edit(instance / GENERATED / CONCEPTS, lambda text: text + "\n")
    rehash(instance)

    result = check(instance)

    assert CONCEPTS in str(failed(result, 7)[0])
    assert outcome(result, 2).passed


def test_rewritten_line_endings_fail_check_7(instance: Path) -> None:
    # A file whose endings an editor or a misconfigured git rewrote parses to precisely the
    # right statements and is precisely not the bytes any run wrote (spec 5.5 rule 5).
    edit(instance / GENERATED / TAXONOMY, lambda text: text.replace("\n", "\r\n"))
    rehash(instance)

    assert TAXONOMY in str(failed(check(instance), 7)[0])


def test_a_blank_node_fails_check_7(instance: Path) -> None:
    # Legal RDF the canonical serializer refuses (spec 5.5), so no run could have written
    # this file — reported as a finding rather than raised out of the serializer.
    edit(
        instance / GENERATED / CONCEPTS,
        lambda text: (
            text + '\nc:07666880-aa23-11ee-94e1-0242ac1e0003 skos:note [ skos:note "x" ] .\n'
        ),
    )
    rehash(instance)

    assert failed(check(instance), 7)


def test_an_edited_ontology_copy_fails_check_7(instance: Path) -> None:
    # `ontology.ttl` is copied verbatim and is the one generated file the serializer did not
    # produce, so it is compared against the metamodel this compiler carries instead.
    edit(
        instance / GENERATED / build.ONTOLOGY_FILE,
        lambda text: text.replace("rdfs:comment", "rdfs:label", 1),
    )
    rehash(instance)

    assert build.ONTOLOGY_FILE in str(failed(check(instance), 7)[0])


def test_reordered_statements_fail_check_7(instance: Path) -> None:
    # Same graph, different bytes: subjects and predicates are sorted (spec 5.5 rules 2 and
    # 3), and a diff is only a governance interface while the order is not a choice.
    def reorder(text: str) -> str:
        header, _, body = text.partition("\n\n")
        blocks = body.split("\n\n")
        return header + "\n\n" + "\n\n".join(list(reversed(blocks)))

    edit(instance / GENERATED / TAXONOMY, reorder)
    rehash(instance)

    assert failed(check(instance), 7)


# ------------------------------------------------------------------------ the CLI surface


@pytest.mark.parametrize(
    ("break_it", "expected"),
    [
        pytest.param(
            lambda root: edit(root / GENERATED / CONCEPTS, lambda text: text + "\nnope .\n"),
            ExitCode.FAILURE,
            id="a validation failure is exit 1",
        ),
        pytest.param(
            lambda root: (root / NAMESPACE_LOCK_PATH).unlink(),
            ExitCode.CONFIG,
            id="a namespace-lock error is exit 2",
        ),
        pytest.param(
            lambda root: edit(
                root / "config" / "semprini.yaml", lambda text: text.replace("base_iri", "base")
            ),
            ExitCode.CONFIG,
            id="a configuration error is exit 2",
        ),
    ],
)
def test_the_cli_maps_each_failure_to_its_published_exit_code(
    instance: Path, break_it: Callable[[Path], None], expected: ExitCode
) -> None:
    break_it(instance)

    assert main(["check"]) == expected


def test_the_base_revision_can_be_given_on_the_command_line(repository: Path) -> None:
    edit(repository / ID_MAP_PATH, lambda text: text.replace("2026-08-06", "2020-01-01", 1))

    assert main(["check", "--base", "HEAD"]) == ExitCode.FAILURE


def test_the_findings_are_what_the_command_prints(
    instance: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # What a reviewer reads on a pull request is this output and nothing else, so a
    # warning the check found and did not print is a warning nobody acts on. The narrow
    # console this passes through is `test_cli.py`'s.
    assert main(["check"]) == ExitCode.OK
    printed = capsys.readouterr().out

    assert "no skos:definition" in printed
    assert printed.rstrip().endswith("0 errors, 4 warnings")


_SUMMARY_SCRIPT = """
import sys

from semprini import config, validate

result = validate.check(config.load(sys.argv[1]), compiler="0.1.0", ontology="0.1.0")
sys.stdout.write("\\n".join(result.summary()))
"""


def _summary_in_a_subprocess(root: Path, hash_seed: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", _SUMMARY_SCRIPT, str(root)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
        check=True,
    )
    return completed.stdout


def test_the_summary_is_the_same_on_every_machine(instance: Path) -> None:
    """Two runs of one check print the same lines in the same order.

    Out of process because that is the only way to vary ``PYTHONHASHSEED``, and it is the
    only way to test this at all: issues are collected in sets, so without the explicit
    sort they come out following string hashing — identical all day on one machine and
    different on the next. An in-process assertion that four warnings are sorted agrees
    with chance often enough to look like a passing test, which is exactly how it survived
    the first mutation run of this file.

    CI output that reorders between runs is output nobody can diff, and the diff is the
    governance interface (spec 1.2).
    """
    first = _summary_in_a_subprocess(instance, "0")
    second = _summary_in_a_subprocess(instance, "12345")
    third = _summary_in_a_subprocess(instance, "98765")

    assert first == second == third
    # Guards the guard: three identical empty outputs would also pass the line above.
    assert first.count("  - ") == 4

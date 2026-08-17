"""``semprini init`` — the instance scaffold of spec 5.7.

What is being pinned here is mostly *absence*: that a refusal writes nothing, that no
placeholder survives into an adopter's repository, that nothing reaches the network, and
that a run immediately after a bootstrap produces no diff. A scaffold is the one thing in
this project nobody re-runs to check — an adopter bootstraps once, commits it, and lives
with whatever it wrote.
"""

from __future__ import annotations

import datetime
import re
import socket
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml

from semprini import (
    ONTOLOGY_PATH,
    UNINSTALLED_VERSION,
    compiler_version,
    config,
    identity,
    lifecycle,
    manifest,
    ontology_version,
    run,
    scaffold,
)
from semprini.cli import ExitCode, main
from semprini.scaffold import ScaffoldError

BASE_IRI = "https://semantics.example.com/"
ORG = "acme"
TODAY = datetime.date(2026, 3, 17)
"""Deliberately not the day this runs. A fixed date that happened to be today's would let
a scaffold that ignored its injected date pass every assertion about it — which is exactly
what the mutation battery caught the first time this file was written."""

# Spec 4.2's tree, as `init` materializes it. `generated/.report.md` is deliberately absent
# — it is written only by a run that changed something (spec 5.6) — and so are the source
# files and overlays a steward has not written yet, which is what the keep files stand in
# for.
EXPECTED_TREE = {
    ".gitattributes",
    ".github/workflows/compile.yml",
    ".github/workflows/validate.yml",
    "README.md",
    "config/semprini.yaml",
    "generated/.manifest.json",
    "generated/ontology.ttl",
    "mappings/id-map.csv",
    "mappings/merges.csv",
    "mappings/namespace.lock",
    "overlays/README.md",
    "overlays/ext/.gitkeep",
    "overlays/external/.gitkeep",
    "overlays/patches/.gitkeep",
    "shapes/local/README.md",
    "sources/ellie/.gitkeep",
    "sources/taxonomies/.gitkeep",
}


@pytest.fixture
def bootstrapped(tmp_path: Path) -> Path:
    """A fresh instance, created the way an adopter creates one."""
    root = tmp_path / "acme-semantics"
    scaffold.init(root, base_iri=BASE_IRI, org=ORG, today=TODAY)
    return root


def tree(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


# ------------------------------------------------------------------- what it produces


def test_the_tree_matches_the_spec(bootstrapped: Path) -> None:
    assert tree(bootstrapped) == EXPECTED_TREE


def test_a_fresh_instance_passes_every_check(
    bootstrapped: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The verification this whole task exists for (spec 5.7).

    An adopter's very first CI run is against an instance that has compiled nothing, and it
    has to be green: a bootstrap whose output fails validation would teach them on day one
    that a red check is normal.
    """
    monkeypatch.chdir(bootstrapped)

    assert main(["check"]) == ExitCode.OK

    out = capsys.readouterr().out
    assert "checks passed" in out
    # Check 6's append-only half needs a base revision and there is no git history yet.
    # Reported as not run rather than passed, which is the honest answer and does not fail.
    assert "6. identity: not run" in out


def test_a_run_straight_after_a_bootstrap_writes_nothing(
    bootstrapped: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strongest statement available about what `init` wrote.

    `generated/` after a bootstrap has to be *exactly* what the compiler would have
    produced, byte for byte — the ontology copy and the manifest recording it. Otherwise an
    adopter's first scheduled compile opens a pull request that changes files nobody edited,
    which is the empty diff spec 5.6 exists to prevent, arriving before they have configured
    a single source.
    """
    monkeypatch.chdir(bootstrapped)
    before = {path: path.read_bytes() for path in bootstrapped.rglob("*") if path.is_file()}

    result = run.run(config.load(bootstrapped), today=TODAY)

    assert not result.changed
    assert result.report is None
    assert result.stale == ()
    assert {path: path.read_bytes() for path in bootstrapped.rglob("*") if path.is_file()} == before


def test_the_configuration_it_writes_loads(bootstrapped: Path) -> None:
    settings = config.load(bootstrapped)

    assert settings.base_iri == BASE_IRI
    assert settings.instance_id == ORG
    assert settings.default_language == config.DEFAULT_LANGUAGE
    # A fresh instance compiles nothing until somebody configures a source (spec 5.7 step 2).
    assert settings.sources == ()


def test_the_lock_freezes_what_the_configuration_says(bootstrapped: Path) -> None:
    # Raises on any disagreement, which is the whole point of writing both in one command.
    lock = identity.verify_namespace_lock(config.load(bootstrapped))

    assert lock.base_iri == BASE_IRI
    assert lock.instance_id == ORG
    assert lock.ontology_version == ontology_version()
    assert lock.date == TODAY


def test_the_lock_records_the_metamodel_version_and_not_the_compiler_s(tmp_path: Path) -> None:
    """Pinned with the two versions deliberately different.

    They are the same number today, so every assertion about the lock's `ontology_version`
    passes just as happily against the compiler's — and the lock is what a future migration
    reads to know which metamodel this instance was frozen against (spec 7).
    """
    root = tmp_path / "instance"
    scaffold.init(root, base_iri=BASE_IRI, org=ORG, compiler="9.9.9", ontology="0.4.2", today=TODAY)

    assert identity.NamespaceLock.load(root).ontology_version == "0.4.2"


def test_the_manifest_describes_the_directory_it_was_written_beside(bootstrapped: Path) -> None:
    recorded = manifest.Manifest.load(bootstrapped)

    assert recorded.verify(bootstrapped) == ()
    assert recorded.check_versions() == ()
    assert set(recorded.files) == {"ontology.ttl"}


def test_the_ontology_copy_is_the_packaged_metamodel(bootstrapped: Path) -> None:
    """Copied verbatim, never re-serialized (spec 4.2): the term comments are the
    vocabulary's published documentation, and check 7 compares this file against the
    packaged one byte for byte."""
    copied = (bootstrapped / "generated" / "ontology.ttl").read_text(encoding="utf-8")

    assert copied == ONTOLOGY_PATH.read_text(encoding="utf-8")


def test_the_registers_are_created_with_their_headers(bootstrapped: Path) -> None:
    """Empty, but present: a missing file is a legal empty register, so this is about the
    tree matching spec 4.2 and about a steward finding the columns already named."""
    id_map = identity.IdMap.load(bootstrapped)
    merges = lifecycle.MergeRegister.load(bootstrapped)

    assert len(id_map) == 0
    assert len(merges) == 0
    header = (bootstrapped / "mappings" / "id-map.csv").read_text(encoding="utf-8")
    assert header == ",".join(identity.ID_MAP_COLUMNS) + "\n"


def test_every_file_is_written_with_lf(bootstrapped: Path) -> None:
    """The instance's own `.gitattributes` promises LF (spec 4.3), and the machine that
    creates the instance must not be the one machine that disagrees."""
    with_cr = [
        path.relative_to(bootstrapped).as_posix()
        for path in bootstrapped.rglob("*")
        if path.is_file() and b"\r" in path.read_bytes()
    ]

    assert with_cr == []


def test_the_gitattributes_pins_lf(bootstrapped: Path) -> None:
    written = (bootstrapped / ".gitattributes").read_text(encoding="utf-8")

    assert "eol=lf" in written
    # A workbook rewritten as text is a corrupt workbook.
    assert "*.xlsx binary" in written


def test_no_placeholder_survives_into_the_instance(bootstrapped: Path) -> None:
    """A template placeholder that reached an adopter's repository would be traced back
    here by nobody: it would read as something they were meant to fill in."""
    leftovers = {
        path.relative_to(bootstrapped).as_posix()
        for path in bootstrapped.rglob("*")
        if path.is_file() and re.search(r"%%\w+%%", path.read_text(encoding="utf-8"))
    }

    assert leftovers == set()


def test_the_arguments_reach_the_files_that_describe_the_instance(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    scaffold.init(root, base_iri="https://vocab.example.org/", org="northwind", today=TODAY)

    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "northwind" in readme
    assert "https://vocab.example.org/" in readme
    assert (root / "shapes" / "local" / "README.md").read_text(encoding="utf-8").count(
        "northwind"
    ) >= 1


def test_the_workflows_pin_the_plane_version(bootstrapped: Path) -> None:
    """Both of them, and the version that created the instance (spec 5.7 step 5).

    An unpinned install would silently upgrade the compiler under an instance on some
    unrelated Monday, and a serialization change is a major version bump with a migration
    (spec 7) — the diff would arrive as a rewritten `generated/` nobody asked for.
    """
    pin = f"pip install semprini=={compiler_version()}"

    for name in scaffold.WORKFLOWS:
        assert pin in (bootstrapped / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_the_workflows_are_valid_yaml(bootstrapped: Path) -> None:
    """Parsed, not merely written.

    Nothing else in this project reads these files: a broken one ships, is committed, and
    fails on an adopter's first pull request with a syntax error from a CI platform rather
    than from anything here. Note that GitHub's own `${{ ... }}` expressions have to survive
    substitution untouched, which is why the scaffold's placeholders are `%%name%%`.
    """
    for name in scaffold.WORKFLOWS:
        text = (bootstrapped / ".github" / "workflows" / name).read_text(encoding="utf-8")
        document = yaml.safe_load(text)

        assert isinstance(document, dict)
        assert list(document["jobs"])


Step = dict[str, Any]


def compile_steps(root: Path) -> list[Step]:
    document = yaml.safe_load(
        (root / ".github" / "workflows" / "compile.yml").read_text(encoding="utf-8")
    )
    steps: list[Step] = document["jobs"]["compile"]["steps"]
    return steps


def step_index(steps: list[Step], predicate: Callable[[Step], bool]) -> int:
    return next(index for index, step in enumerate(steps) if predicate(step))


def proposes(step: Step) -> bool:
    return "gh pr create" in step.get("run", "")


def test_the_compile_workflow_opens_a_pull_request_carrying_the_report(
    bootstrapped: Path,
) -> None:
    """Spec 6.2: the run report is the pull request's description, on a `compile/<date>`
    branch. What a steward reviews is the report beside the diff it describes."""
    (opener,) = [step for step in compile_steps(bootstrapped) if proposes(step)]

    assert "--body-file generated/.report.md" in opener["run"]
    assert 'branch="compile/$today"' in opener["run"]


def test_the_compile_workflow_guards_the_report_it_describes_itself_with(
    bootstrapped: Path,
) -> None:
    """A run that changed nothing writes no report (spec 5.6) and leaves nothing to commit,
    and both of those would otherwise be a failure: `gh pr create` has no `--body-file` to
    read, and `git commit` exits non-zero on an empty staging area. Ungated, the weeks where
    nothing moved are the ones the scheduled job fails on."""
    (opener,) = [step for step in compile_steps(bootstrapped) if proposes(step)]

    assert "generated/.report.md" in opener["if"]
    assert "git diff --cached --quiet" in opener["run"]


def test_the_compile_workflow_survives_being_dispatched_twice_in_one_day(
    bootstrapped: Path,
) -> None:
    """The branch is named after the date, so the second run of a day finds its own branch
    on the remote with a pull request already open against it. A plain push is rejected and
    a second `gh pr create` is an error; force-pushing updates the pull request in place,
    which is the behaviour the third-party action used to provide invisibly."""
    (opener,) = [step for step in compile_steps(bootstrapped) if proposes(step)]

    assert "git push --force" in opener["run"]
    assert "gh pr list" in opener["run"]


def test_the_compile_workflow_gives_the_commit_an_author(bootstrapped: Path) -> None:
    """A runner has no committer identity configured, and `git commit` refuses without one
    — the third run in this file's history to fail on something the action did for us."""
    (opener,) = [step for step in compile_steps(bootstrapped) if proposes(step)]

    assert "git config user.name" in opener["run"]
    assert "git config user.email" in opener["run"]


def test_the_compile_workflow_validates_what_it_is_about_to_propose(
    bootstrapped: Path,
) -> None:
    """GitHub fires no `pull_request` event for a pull request opened with GITHUB_TOKEN,
    so validate.yml never runs on a compile PR — and against the protected main that
    `init` tells an adopter to set up, its required check would never report. Without this
    step the compiler's own output is the one diff in an instance nobody validated (6.2).
    """
    steps = compile_steps(bootstrapped)

    checked = step_index(steps, lambda step: step.get("run", "").startswith("semprini check"))
    proposed = step_index(steps, proposes)
    # A check after the pull request is opened validates nothing anyone is waiting on.
    assert checked < proposed


def test_nothing_it_writes_advertises_a_setting_every_adapter_refuses(
    bootstrapped: Path,
) -> None:
    """`token_env` configures nothing today: both bundled adapters read files that are
    already in the repository, and each rejects the key rather than accept a credential it
    would never reach for. An adopter who copies guidance setting it meets exit code 2 on
    their first run, so no template, README, workflow or printed next step may show it
    being assigned until an adapter that calls an API ships.

    The assignment form is what is banned, not the name: saying that the key is refused is
    exactly what these files should do, and `token_env: SOMETHING` is the copyable line
    that turns that into a first run nobody can complete."""
    written = [path for path in sorted(bootstrapped.rglob("*")) if path.is_file()]
    documents = [path for path in written if path.suffix in {".yaml", ".yml", ".md"}]
    assert documents  # the glob finding nothing would pass every assertion below

    for path in documents:
        assert "token_env:" not in path.read_text(encoding="utf-8"), path

    rendered = scaffold.create(
        bootstrapped.parent / "other", base_iri=BASE_IRI, org=ORG, today=TODAY
    )
    assert not any("token_env:" in line for line in rendered.summary())


def test_the_local_shapes_readme_names_every_refusal(bootstrapped: Path) -> None:
    """An adopter meets the additive-only rule when their file is rejected, which is the
    worst moment to read about it for the first time (spec 6.1.5)."""
    written = (bootstrapped / "shapes" / "local" / "README.md").read_text(encoding="utf-8")

    for refusal in ("sh:minCount 0", "sh:uniqueLang false", "sh:closed false", "sh:rule"):
        assert refusal in written
    assert "https://w3id.org/semprini/ontology#" in written
    # Targeting a sem: class is how a legitimate local rule says what it is about, and the
    # README has to say so or the first thing an adopter does is avoid the one legal form.
    assert "sh:targetClass sem:Entity" in written


def test_a_template_checked_out_with_crlf_is_still_written_with_lf(tmp_path: Path) -> None:
    """The templates live in a git repository like anything else, and a clone on a machine
    with ``core.autocrlf=true`` holds them with CRLF. Read as text rather than as bytes so
    that what reaches an instance is LF either way — an instance whose ``.gitattributes``
    promises LF must not be created with the opposite by whichever machine ran ``init``.
    """
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "note.md").write_bytes(b"one\r\ntwo\r\n")

    rendered = list(scaffold._templated(templates, PurePosixPath(), {}))

    assert [file.text for file in rendered] == ["one\ntwo\n"]


def test_the_listing_is_sorted(tmp_path: Path) -> None:
    """What ``init`` prints is a list of what it created, and filesystem order would put
    that list in a different order on a different platform."""
    rendered = scaffold.create(tmp_path / "instance", base_iri=BASE_IRI, org=ORG, today=TODAY)

    paths = [file.path for file in rendered.files]
    assert paths == sorted(paths)


def test_the_default_language_is_configurable(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    scaffold.init(root, base_iri=BASE_IRI, org=ORG, default_language="fi", today=TODAY)

    assert config.load(root).default_language == "fi"


def test_the_target_directory_is_created_if_it_is_missing(tmp_path: Path) -> None:
    root = tmp_path / "does" / "not" / "exist"

    scaffold.init(root, base_iri=BASE_IRI, org=ORG, today=TODAY)

    assert tree(root) == EXPECTED_TREE


def test_two_bootstraps_of_one_instance_are_byte_identical(tmp_path: Path) -> None:
    """Nothing in a scaffold may depend on the machine or the moment beyond the date, which
    is injected — a set iterated in hash order or a clock read twice would show up here."""
    first = scaffold.create(tmp_path / "a", base_iri=BASE_IRI, org=ORG, today=TODAY)
    second = scaffold.create(tmp_path / "b", base_iri=BASE_IRI, org=ORG, today=TODAY)

    assert [(file.path, file.text) for file in first.files] == [
        (file.path, file.text) for file in second.files
    ]


# --------------------------------------------------------------------------- refusals


def test_a_second_bootstrap_is_refused(bootstrapped: Path) -> None:
    """Spec 5.7's named refusal, and the one that matters: the lock is a decision that
    cannot be taken twice."""
    before = {path: path.read_bytes() for path in bootstrapped.rglob("*") if path.is_file()}

    with pytest.raises(ScaffoldError) as raised:
        scaffold.init(bootstrapped, base_iri="https://elsewhere.example.com/", org="other")

    assert "already holds an instance" in str(raised.value)
    assert {path: path.read_bytes() for path in bootstrapped.rglob("*") if path.is_file()} == before


def test_a_file_already_present_is_never_overwritten(tmp_path: Path) -> None:
    """The lock is not the only file worth protecting: a directory holding a steward's
    README and no lock is a repository somebody started by hand, not an empty one."""
    root = tmp_path / "instance"
    root.mkdir()
    (root / "README.md").write_text("ours", encoding="utf-8")

    with pytest.raises(ScaffoldError) as raised:
        scaffold.init(root, base_iri=BASE_IRI, org=ORG)

    assert "README.md" in str(raised.value)
    assert tree(root) == {"README.md"}
    assert (root / "README.md").read_text(encoding="utf-8") == "ours"


def test_a_bad_base_iri_and_a_bad_org_are_reported_together(tmp_path: Path) -> None:
    """Both, in one run. A bootstrap command is retyped by hand, and one mistake per
    attempt is the most annoying way to learn there were two."""
    root = tmp_path / "instance"

    with pytest.raises(ScaffoldError) as raised:
        scaffold.init(root, base_iri="semantics.example.com", org="Acme Corp")

    message = str(raised.value)
    assert "--base-iri" in message
    assert "--org" in message
    assert not root.exists()


@pytest.mark.parametrize(
    "base_iri",
    [
        "ftp://semantics.example.com/",
        "https://semantics.example.com",  # no trailing separator
        "https://semantics example.com/",  # a space, which Turtle forbids in an IRI
    ],
)
def test_a_base_iri_the_serializer_could_not_write_is_refused(
    tmp_path: Path, base_iri: str
) -> None:
    """Checked here rather than at the first compile, because the lock would have frozen
    it in between (spec 3.4)."""
    with pytest.raises(ScaffoldError):
        scaffold.init(tmp_path / "instance", base_iri=base_iri, org=ORG)


def test_a_target_that_is_not_a_directory_is_refused(tmp_path: Path) -> None:
    """Named, rather than raising an OSError from inside a write that has already begun."""
    target = tmp_path / "instance"
    target.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ScaffoldError, match="not a directory"):
        scaffold.init(target, base_iri=BASE_IRI, org=ORG)


def test_a_missing_template_directory_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A partial install, not an empty scaffold.

    The templates ship inside the wheel (spec 4.1). Read as an empty directory, their
    absence would produce an instance with no configuration, no workflows and no
    `.gitattributes` — and nothing downstream would trace any of that back to here.
    """
    monkeypatch.setattr(scaffold, "INSTANCE_TEMPLATES", Path("no", "such", "directory"))

    with pytest.raises(ScaffoldError, match="missing from this installation"):
        scaffold.create(base_iri=BASE_IRI, org=ORG)


def test_a_bad_language_tag_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ScaffoldError) as raised:
        scaffold.init(tmp_path / "instance", base_iri=BASE_IRI, org=ORG, default_language="English")

    assert "language tag" in str(raised.value)


def test_a_source_tree_cannot_bootstrap_an_instance(tmp_path: Path) -> None:
    """The scaffold pins the plane version in two workflows and in a manifest, and
    `0.0.0+source` identifies no release (spec 4.3, 7): the workflows could not install and
    the drift check would pass between two unrelated working trees."""
    root = tmp_path / "instance"

    with pytest.raises(ScaffoldError) as raised:
        scaffold.init(root, base_iri=BASE_IRI, org=ORG, compiler=UNINSTALLED_VERSION)

    assert UNINSTALLED_VERSION in str(raised.value)
    assert not root.exists()


def test_an_unknown_placeholder_in_a_template_is_refused() -> None:
    """A bug in this package rather than in anything an adopter did — and one that would
    otherwise ship a literal `%%og%%` into a new instance's README."""
    with pytest.raises(ValueError, match="no value"):
        scaffold._render("hello %%og%%", {"org": "acme"})


# ------------------------------------------------------------------------ side effects


def test_it_makes_no_network_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec 5.7 step 6, and decision 11 #8: `init` stays offline and creates no remote.

    Guarded at the socket rather than at any HTTP library, so it holds whatever a future
    step might reach for. A bootstrap that phoned home would be doing it with the
    organization's brand-new base IRI in hand.
    """

    def refuse(*arguments: object, **keywords: object) -> None:
        raise AssertionError("semprini init opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    scaffold.init(tmp_path / "instance", base_iri=BASE_IRI, org=ORG, today=TODAY)


def test_nothing_is_written_before_every_refusal_has_been_made(tmp_path: Path) -> None:
    """`create` renders the whole tree and checks the target; `write` is what touches the
    disk. A refusal therefore cannot leave a half-created instance behind — which would be
    a directory holding a namespace lock and nothing else, and so an instance no second
    `init` would agree to finish."""
    root = tmp_path / "instance"
    root.mkdir()

    rendered = scaffold.create(root, base_iri=BASE_IRI, org=ORG, today=TODAY)

    assert tree(root) == set()
    rendered.write()
    assert tree(root) == EXPECTED_TREE


# ------------------------------------------------------------------------------- CLI


def test_init_through_the_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "instance"

    assert main(["init", "--base-iri", BASE_IRI, "--org", ORG, "--dir", str(root)]) == ExitCode.OK

    out = capsys.readouterr().out
    assert "created an instance" in out
    assert BASE_IRI in out
    assert tree(root) == EXPECTED_TREE


def test_init_defaults_to_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Commands operate on the working directory (spec 5.1), and `--dir` is optional."""
    monkeypatch.chdir(tmp_path)

    assert main(["init", "--base-iri", BASE_IRI, "--org", ORG]) == ExitCode.OK

    assert tree(tmp_path) == EXPECTED_TREE


def test_a_refused_bootstrap_exits_2(
    bootstrapped: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2, like every other refusal about the invocation or the directory it names:
    nothing was written and there is nothing to validate."""
    code = main(["init", "--base-iri", BASE_IRI, "--org", ORG, "--dir", str(bootstrapped)])

    assert code == ExitCode.CONFIG
    assert "already holds an instance" in capsys.readouterr().err


def test_the_cli_passes_the_language_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert main(["init", "--base-iri", BASE_IRI, "--org", ORG, "--language", "sv"]) == ExitCode.OK

    assert config.load(tmp_path).default_language == "sv"

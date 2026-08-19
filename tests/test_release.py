"""What a release must agree about before it is published (task G5, spec 7, 11 #3).

Semprini has no package index behind it. A release is a tag, a wheel attached to it, and a
URL built out of the version — so the tag is not a label somebody can move afterwards: it is
the install line in every instance created while it was current, and the directory the
ontology's permanent path is served from. `tools/release_check.py` is what refuses an
incoherent one, and this is what keeps that tool honest.

The load-bearing assertion is the first one. Everything else here can be fixed by publishing
again; a released ontology document that changed cannot, because somebody may already have
fetched it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tools import release_check, release_smoke

from semprini import ONTOLOGY_PATH, ontology_version, wheel_url

ARCHIVE = release_check.ARCHIVE


def test_the_current_ontology_version_is_archived_byte_for_byte() -> None:
    """The site publishes `/ontology/X.Y.Z/` from the archive and the wheel ships the other
    copy, so two documents under one version number is the failure to make impossible.

    It also has the effect the specification asks for and nothing until now enforced: **a
    released ontology cannot be edited without releasing a new version of it** (spec 7). Once
    a version is archived, editing `src/semprini/ontology/sem.ttl` fails this test until
    `owl:versionInfo` moves — which is a version bump, a changelog entry and a considered act
    rather than a line changed in passing.
    """
    frozen = ARCHIVE / ontology_version() / "sem.ttl"

    assert frozen.is_file(), (
        f"ontology {ontology_version()} is not archived; if the ontology changed, bump "
        f"owl:versionInfo — if it was released, copy it to {frozen}"
    )
    assert frozen.read_bytes() == ONTOLOGY_PATH.read_bytes()


def test_an_ontology_edit_under_a_released_version_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the test above: that it fails when it should.

    An assertion that two identical files are identical passes whether or not it compares
    anything, so the edit is actually made — to a copy, since the real one is what everything
    else here reads.
    """
    edited = tmp_path / "sem.ttl"
    edited.write_bytes(ONTOLOGY_PATH.read_bytes() + b"\n# a term nobody released\n")
    monkeypatch.setattr(release_check, "ONTOLOGY_PATH", edited)

    (problem,) = release_check.check_the_ontology_is_archived()
    assert "differs from the ontology this release ships" in problem


def test_an_unarchived_ontology_version_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A release that has not frozen its ontology publishes a version whose own permanent
    path disappears at the next bump. That is the gap task A2 left open, and it closes by
    being refused here rather than noticed later."""
    monkeypatch.setattr(release_check, "ontology_version", lambda: "9.9.9")

    (problem,) = release_check.check_the_ontology_is_archived()
    assert "ontology 9.9.9 is not archived" in problem


def test_an_ontology_version_that_went_backwards_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A released version newer than the one being shipped means `owl:versionInfo` moved
    backwards — a botched revert, or a merge that took the wrong side.

    Nothing else catches it: the shipped document matches its own archived copy, so every
    other check passes. It matters because the site trusts that ordering — the current
    version heads the published list — and because a release that reissues a superseded
    vocabulary under the current namespace is the one mistake the archive cannot undo.
    """
    archive = tmp_path / "ontology-archive"
    for version in (ontology_version(), "9.9.9"):
        (archive / version).mkdir(parents=True)
        (archive / version / "sem.ttl").write_bytes(ONTOLOGY_PATH.read_bytes())
    monkeypatch.setattr(release_check, "ARCHIVE", archive)

    (problem,) = release_check.check_the_ontology_is_archived()
    assert "is older than 9.9.9" in problem


def test_the_archive_holds_nothing_but_version_directories() -> None:
    assert release_check.check_the_archive_is_well_formed() == []


def test_no_archive_at_all_is_reported_rather_than_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The maintainer gets the instruction, not a traceback.

    The check above walks the archive, and walking one that does not exist raises. That is
    the state a first release is in before anybody has copied the ontology into place — and
    the check before it has already said exactly what to do about it, which a stack trace
    would replace with nothing.
    """
    monkeypatch.setattr(release_check, "ARCHIVE", tmp_path / "nothing-here")

    assert release_check.check_the_archive_is_well_formed() == []

    problems = release_check.check("v0.1.0")
    assert any("is not archived" in problem for problem in problems)


def test_a_malformed_archive_entry_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And the same check, shown failing.

    The site build refuses these too, but it runs *after* the release is published — so a
    directory nobody can serve is a broken permanent identifier by the time the build says
    so. Catching it on the tag is the difference between a red job and a 404.
    """
    archive = tmp_path / "ontology-archive"
    (archive / "latest").mkdir(parents=True)
    (archive / "latest" / "sem.ttl").write_text("", encoding="utf-8")
    (archive / "0.0.1").mkdir()
    (archive / "0.0.1" / "notes.md").write_text("", encoding="utf-8")
    (archive / "stray.ttl").write_text("", encoding="utf-8")
    monkeypatch.setattr(release_check, "ARCHIVE", archive)

    problems = release_check.check_the_archive_is_well_formed()

    assert any("latest is not named for a version" in problem for problem in problems)
    assert any("0.0.1 holds" in problem for problem in problems)
    assert any("stray.ttl is not a version directory" in problem for problem in problems)


def test_a_release_tag_is_v_and_three_numbers() -> None:
    """The tag builds the download URL, so a tag spelled any other way names a 404 rather
    than looking untidy."""
    for tag in ("0.1.0", "v0.1", "v0.1.0-rc1", "release-0.1.0", "v01.1.0"):
        (problem,) = release_check.check(tag)
        assert "is not a release tag" in problem


def test_a_tag_that_disagrees_with_the_package_is_refused() -> None:
    """`pyproject.toml` names the wheel and becomes `semprini version`; the tag names the
    directory it is downloaded from. An instance pins the URL, so a disagreement between them
    is a workflow that installs one version and records another."""
    problems = release_check.check("v9.9.9")

    assert any("pyproject.toml says" in problem for problem in problems)


@pytest.fixture
def changelog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A changelog mid-cycle: one release out, one version's entries still unreleased.

    Synthetic rather than the project's own, because the interesting states are ones the real
    file is only in for the length of one pull request — and because a test that reads the
    real changelog asserts today's history rather than the format.
    """
    written = tmp_path / "CHANGELOG.md"
    written.write_text(
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "### Compiler 0.2.0\n\n"
        "- something not decided yet\n\n"
        "## [0.1.0] — 2026-08-19\n\n"
        "### Compiler 0.1.0\n\n"
        "- the first release\n\n"
        "## [0.0.1] — 2026-01-01\n\n"
        "- an older one\n",
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setattr(release_check, "CHANGELOG", written)
    return written


def test_a_version_still_filed_under_unreleased_is_refused(changelog: Path) -> None:
    """`### Compiler 0.2.0` under `## [Unreleased]` is work in progress, not a release. The
    notes are cut from the dated section, so a release without one is a release where nobody
    decided what shipped — and it would publish the next version's half-finished entries."""
    (problem,) = release_check.check_the_changelog_records_the_release("0.2.0")
    assert "no released section for 0.2.0" in problem

    assert release_check.check_the_changelog_records_the_release("0.1.0") == []


def test_the_notes_are_one_section_and_how_to_install_it(changelog: Path) -> None:
    """What a GitHub release page shows. Somebody arriving there has no instance and no
    README in front of them, and with no package index there is nothing they can guess."""
    notes = release_check.notes("0.1.0")

    assert "- the first release" in notes
    assert wheel_url("0.1.0") in notes

    # Cut at the next heading in both directions. Running on would publish the whole history
    # under one version; starting early would publish the next version's unfinished entries
    # as though they had shipped.
    assert "an older one" not in notes
    assert "not decided yet" not in notes


def test_the_real_changelog_records_the_first_release() -> None:
    """0.1.0 is out, and its section is what its release page shows. A released section is
    never edited back into `[Unreleased]`, so this one holds for ever."""
    assert release_check.check_the_changelog_records_the_release("0.1.0") == []
    assert "### Compiler 0.1.0" in release_check.notes("0.1.0")


def test_the_wheel_a_release_publishes_is_named_what_the_url_promises(tmp_path: Path) -> None:
    """The one half of the download URL that nothing else compares against anything.

    Everywhere else, `wheel_url()` is checked against something rendered from `wheel_url()`.
    The file that is actually built is outside that loop: if a packaging change ever named
    the distribution differently, the release would publish an asset under one name while
    every instance fetched another, and the first symptom would be a 404 in somebody else's
    weekly compile.
    """
    assert release_smoke.check_the_built_wheel_is_named_as_promised("0.1.0", tmp_path) != []

    (tmp_path / "semprini-0.1.0-py3-none-any.whl").write_bytes(b"")
    assert release_smoke.check_the_built_wheel_is_named_as_promised("0.1.0", tmp_path) == []

    # ...and a wheel built under a name pip would still install locally, but that no
    # instance's workflow would ever ask for.
    (tmp_path / "semprini-0.1.0-py3-none-any.whl").unlink()
    (tmp_path / "semprini_0.1.0_py3_none_any.whl").write_bytes(b"")
    (problem,) = release_smoke.check_the_built_wheel_is_named_as_promised("0.1.0", tmp_path)
    assert "the download URL and the artifact disagree" in problem

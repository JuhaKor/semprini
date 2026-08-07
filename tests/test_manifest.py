"""``generated/.manifest.json`` (spec 4.3, 6.1 checks 2 and 3, 7).

The manifest is the only thing standing between "generated/ is machine-owned" as a rule
and as a fact, so the tests here are mostly about the ways it could fail to notice
something: a file quietly edited, a file quietly added, a file quietly removed, and an
upgrade quietly reflowing every file in the next content PR.

The second theme is that the manifest is itself a governed file. It has to be
byte-identical across two runs of one input, or every scheduled compile opens a pull
request whose only content is a manifest saying nothing changed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sample import GOLDEN, VERSIONS, by_name, compile_
from semprini import UNINSTALLED_VERSION, build, compiler_version, ontology_version
from semprini.build import OutputFile
from semprini.manifest import MANIFEST_FILE, Manifest, ManifestError, digest


def manifest(files: tuple[OutputFile, ...] | None = None) -> Manifest:
    return Manifest.create(
        compile_() if files is None else files,
        compiler=VERSIONS["compiler"],
        ontology=VERSIONS["ontology"],
    )


def written(root: Path) -> Manifest:
    """Compile the sample model into ``root`` and write its manifest beside it."""
    files = compile_()
    recorded = manifest(files)
    build.write_all((*files, recorded.to_file()), root)
    return recorded


# ------------------------------------------------------------------------- golden output


def test_the_golden_manifest_matches() -> None:
    """The file a reviewer would actually read.

    Its hashes are of the golden Turtle beside it, so this fails if either the
    serializer's output or the way a hash is recorded changes — both of which are
    output-affecting changes an adopter has to be told about (spec 7).
    """
    assert manifest().dumps() == (GOLDEN / MANIFEST_FILE).read_text(encoding="utf-8")


def test_the_recorded_hashes_are_of_the_golden_files() -> None:
    """Recomputed from the committed Turtle, not from the same call that wrote them."""
    recorded = manifest()

    for name, hash_ in recorded.files.items():
        assert hash_ == digest((GOLDEN / name).read_bytes()), name


# ------------------------------------------------------------------------- determinism


def test_two_runs_of_one_input_produce_the_same_manifest() -> None:
    """Byte-identical, or a scheduled no-op compile opens an empty pull request."""
    assert manifest().dumps() == manifest().dumps()


def test_the_manifest_carries_no_timestamps() -> None:
    """Spec 4.3 requires reproducibility, and a date is the usual way to lose it.

    Checked against the year rather than a pattern: what must never appear is *today*,
    whenever today is.
    """
    import datetime

    assert str(datetime.date.today().year) not in manifest().dumps()


def test_the_manifest_ends_in_exactly_one_newline() -> None:
    text = manifest().dumps()

    assert text.endswith("}\n")
    assert not text.endswith("\n\n")


def test_the_manifest_is_sorted_by_file_name() -> None:
    """A re-ordered JSON object would make one changed file look like a rewritten file."""
    names = list(json.loads(manifest().dumps())["files"])

    assert names == sorted(names)


def test_a_manifest_round_trips() -> None:
    assert Manifest.loads(manifest().dumps()) == manifest()


# ------------------------------------------------------------------------- what it records


def test_every_produced_file_is_recorded() -> None:
    files = compile_()

    assert sorted(manifest(files).files) == sorted(by_name(files))


def test_the_ontology_copy_is_recorded_too() -> None:
    """It is a file in generated/, and a hand-edited metamodel is exactly as damaging as
    a hand-edited concept file — arguably more, since every instance shares it."""
    assert "ontology.ttl" in manifest().files


def test_the_versions_are_the_running_ones_by_default() -> None:
    """Injection exists for the golden files; production callers pass neither (spec 7)."""
    recorded = Manifest.create(compile_())

    assert recorded.compiler_version == compiler_version()
    assert recorded.ontology_version == ontology_version()


def test_a_manifest_is_refused_from_an_uninstalled_source_tree() -> None:
    """``0.0.0+source`` identifies no release, so it pins nothing and drift between two
    working trees would pass the check silently (spec 7)."""
    with pytest.raises(ManifestError, match="identifies no release"):
        Manifest.create(compile_(), compiler=UNINSTALLED_VERSION)


def test_the_manifest_refuses_to_record_itself() -> None:
    """Whatever it recorded would be stale the moment it was written."""
    with pytest.raises(ManifestError, match="must not be passed"):
        Manifest.create((OutputFile(name=MANIFEST_FILE, text="{}"),))


def test_the_manifest_does_not_record_the_report() -> None:
    """``.report.md`` is prose about a run, and is written on different terms (spec 5.6):
    recording it would make the manifest change on runs that changed nothing."""
    with pytest.raises(ManifestError, match="must not be passed"):
        Manifest.create((OutputFile(name=".report.md", text="# hi\n"),))


def test_a_file_produced_twice_is_refused() -> None:
    """Two files of one name means one of them was silently discarded."""
    duplicate = OutputFile(name="concepts-sales.ttl", text="# one\n")

    with pytest.raises(ManifestError, match="produced twice"):
        Manifest.create((duplicate, duplicate))


# ------------------------------------------------------------------------- integrity


def test_an_untouched_instance_verifies(tmp_path: Path) -> None:
    assert written(tmp_path).verify(tmp_path) == ()


def test_a_hand_edited_generated_file_is_detected(tmp_path: Path) -> None:
    """The whole reason the manifest exists (spec 4.3, 6.1 check 2)."""
    recorded = written(tmp_path)
    edited = tmp_path / "generated" / "concepts-sales.ttl"
    edited.write_text(edited.read_text(encoding="utf-8").replace("Order", "Purchase"), "utf-8")

    issues = recorded.verify(tmp_path)

    assert len(issues) == 1
    assert "does not match the manifest" in issues[0].message
    assert issues[0].location is not None
    assert "concepts-sales.ttl" in issues[0].location


def test_an_edit_that_keeps_the_length_is_detected(tmp_path: Path) -> None:
    """A hash, not a size: the plausible hand edit is a corrected label, not a longer
    file."""
    recorded = written(tmp_path)
    edited = tmp_path / "generated" / "concepts-sales.ttl"
    edited.write_text(edited.read_text(encoding="utf-8").replace("Order", "Ordre"), "utf-8")

    assert len(recorded.verify(tmp_path)) == 1


def test_a_deleted_generated_file_is_detected(tmp_path: Path) -> None:
    recorded = written(tmp_path)
    (tmp_path / "generated" / "concepts-sales.ttl").unlink()

    issues = recorded.verify(tmp_path)

    assert len(issues) == 1
    assert "missing" in issues[0].message


def test_a_file_the_compiler_did_not_write_is_detected(tmp_path: Path) -> None:
    """Stale output is as damaging as an edit: a consumer loading generated/ from Git
    would read statements no source still makes (spec 4.3)."""
    recorded = written(tmp_path)
    (tmp_path / "generated" / "concepts-retired.ttl").write_text("# left behind\n", "utf-8")

    issues = recorded.verify(tmp_path)

    assert len(issues) == 1
    assert "not recorded in the manifest" in issues[0].message


def test_a_stale_file_in_a_subdirectory_is_detected(tmp_path: Path) -> None:
    """``generated/`` is flat (spec 4.2), but anyone parsing the directory reads a nested
    file too — so a check that only looked at the top level would pass exactly the stale
    output the unrecorded-file rule exists to catch."""
    recorded = written(tmp_path)
    buried = tmp_path / "generated" / "old" / "concepts-retired.ttl"
    buried.parent.mkdir()
    buried.write_text("# left behind\n", "utf-8")

    issues = recorded.verify(tmp_path)

    assert len(issues) == 1
    assert "not recorded in the manifest" in issues[0].message


def test_the_report_and_the_manifest_are_not_reported_as_unrecorded(tmp_path: Path) -> None:
    """Both live in generated/ and neither is hashed; flagging them would make every
    instance fail its own integrity check."""
    recorded = written(tmp_path)
    (tmp_path / "generated" / ".report.md").write_text("# Compile report\n", "utf-8")

    assert recorded.verify(tmp_path) == ()


def test_every_integrity_problem_is_reported_at_once(tmp_path: Path) -> None:
    """These are read in CI, where one problem per round trip is the difference between
    one fix and three."""
    recorded = written(tmp_path)
    (tmp_path / "generated" / "concepts-sales.ttl").unlink()
    (tmp_path / "generated" / "stray.ttl").write_text("# stray\n", "utf-8")
    edited = tmp_path / "generated" / "concepts-finance.ttl"
    edited.write_text(edited.read_text(encoding="utf-8") + "\n", "utf-8")

    assert len(recorded.verify(tmp_path)) == 3


def test_verification_of_a_missing_directory_reports_every_recorded_file(
    tmp_path: Path,
) -> None:
    issues = manifest().verify(tmp_path)

    assert len(issues) == len(manifest().files)
    assert all("missing" in issue.message for issue in issues)


# ------------------------------------------------------------------------- version drift


def test_matching_versions_do_not_drift() -> None:
    assert manifest().check_versions(compiler="0.1.0", ontology="0.1.0") == ()


@pytest.mark.parametrize(
    ("running", "expected"),
    [
        ({"compiler": "0.2.0"}, "compiler 0.1.0"),
        ({"ontology": "0.2.0"}, "ontology 0.1.0"),
    ],
)
def test_a_newer_running_version_is_drift(running: dict[str, str], expected: str) -> None:
    """An upgrade is a separate "recompile with <version>" pull request, never a reflow
    mixed into a content change (spec 7)."""
    versions = {"compiler": "0.1.0", "ontology": "0.1.0", **running}

    issues = manifest().check_versions(**versions)

    assert len(issues) == 1
    assert expected in issues[0].message


def test_both_versions_can_drift_at_once() -> None:
    assert len(manifest().check_versions(compiler="0.2.0", ontology="0.2.0")) == 2


def test_drift_is_checked_against_the_running_versions_by_default() -> None:
    """The golden manifest pins 0.1.0; the check with no arguments reads the package."""
    recorded = Manifest.create(compile_())

    assert recorded.check_versions() == ()


# ------------------------------------------------------------------------- reading


def test_a_manifest_is_read_from_the_instance(tmp_path: Path) -> None:
    recorded = written(tmp_path)

    assert Manifest.load(tmp_path) == recorded


def test_a_missing_manifest_is_an_error(tmp_path: Path) -> None:
    """Not "nothing to check": treating it as absent would turn the integrity check off
    by deleting a file."""
    with pytest.raises(ManifestError, match="missing"):
        Manifest.load(tmp_path)


def test_a_manifest_that_is_not_json_is_an_error() -> None:
    with pytest.raises(ManifestError, match="not valid JSON"):
        Manifest.loads("{oops")


def test_a_manifest_that_is_not_an_object_is_an_error() -> None:
    with pytest.raises(ManifestError, match="must be a JSON object"):
        Manifest.loads("[]")


def test_a_manifest_that_is_not_utf8_is_an_error(tmp_path: Path) -> None:
    """The ordinary Windows editor mistake, and a traceback is not a fix instruction."""
    directory = tmp_path / "generated"
    directory.mkdir()
    (directory / MANIFEST_FILE).write_bytes(b'{"compiler_version": "\xff"}')

    with pytest.raises(ManifestError, match="not valid UTF-8"):
        Manifest.load(tmp_path)


def test_an_unreadable_manifest_is_an_error(tmp_path: Path) -> None:
    """A directory where the file should be: reported, not raised as an OSError."""
    (tmp_path / "generated" / MANIFEST_FILE).mkdir(parents=True)

    with pytest.raises(ManifestError, match="cannot read the manifest"):
        Manifest.load(tmp_path)


@pytest.mark.parametrize("key", ["compiler_version", "files", "ontology_version"])
def test_a_missing_key_is_an_error(key: str) -> None:
    document = json.loads(manifest().dumps())
    del document[key]

    with pytest.raises(ManifestError, match=f"missing key '{key}'"):
        Manifest.loads(json.dumps(document))


def test_an_unknown_key_is_an_error() -> None:
    """Rejected for the reason configuration rejects one (spec 5.1): it is either a typo
    or a newer manifest this version cannot honestly check."""
    document = json.loads(manifest().dumps())
    document["generated_at"] = "2026-08-06"

    with pytest.raises(ManifestError, match="unknown key 'generated_at'"):
        Manifest.loads(json.dumps(document))


@pytest.mark.parametrize("value", ["", 7, None, ["0.1.0"]])
def test_a_version_that_is_not_a_string_is_an_error(value: object) -> None:
    document = json.loads(manifest().dumps())
    document["compiler_version"] = value

    with pytest.raises(ManifestError, match="compiler_version must be a non-empty string"):
        Manifest.loads(json.dumps(document))


def test_files_that_is_not_an_object_is_an_error() -> None:
    document = json.loads(manifest().dumps())
    document["files"] = ["concepts-sales.ttl"]

    with pytest.raises(ManifestError, match="files must be a JSON object"):
        Manifest.loads(json.dumps(document))


@pytest.mark.parametrize(
    "value",
    [
        "deadbeef",
        "md5:" + "a" * 32,
        "sha256:" + "A" * 64,
        "sha256:" + "a" * 63,
        42,
    ],
)
def test_a_value_that_is_not_a_digest_is_an_error(value: object) -> None:
    """A hash the compiler cannot have written is a hand-edited manifest, which is the
    one edit that would disable every other check here."""
    document = json.loads(manifest().dumps())
    document["files"]["concepts-sales.ttl"] = value

    with pytest.raises(ManifestError, match="not a sha256 digest"):
        Manifest.loads(json.dumps(document))


@pytest.mark.parametrize(
    "name",
    ["../../secrets.txt", "old/concepts-retired.ttl", "C:\\Windows\\win.ini", "/etc/passwd", ".."],
)
def test_a_recorded_name_that_is_not_a_file_in_generated_is_an_error(name: str) -> None:
    """A recorded name becomes a path segment under ``generated/``, so one that escapes it
    would have verification read and hash a file outside the machine-owned directory the
    manifest is meant to bound (spec 4.3) — the same escape the build stage refuses for a
    scheme slug."""
    document = json.loads(manifest().dumps())
    document["files"][name] = document["files"].pop("concepts-sales.ttl")

    with pytest.raises(ManifestError, match="not a file name in generated/"):
        Manifest.loads(json.dumps(document))


@pytest.mark.parametrize("name", [".manifest.json", ".report.md"])
def test_a_recorded_name_the_compiler_never_records_is_an_error(name: str) -> None:
    """Neither is hashed (spec 4.3), so a manifest holding one was written by hand."""
    document = json.loads(manifest().dumps())
    document["files"][name] = document["files"]["concepts-sales.ttl"]

    with pytest.raises(ManifestError, match="never recorded by the compiler"):
        Manifest.loads(json.dumps(document))


def test_a_manifest_cannot_be_constructed_with_an_escaping_name() -> None:
    """The guard is on the class, not only on the parser.

    Enforced where a manifest is *built* rather than where ``verify`` composes a path from
    it: written the other way round, this test passed a hand-built ``Manifest`` straight
    past the parser and had verification open a file outside the instance.
    """
    with pytest.raises(ManifestError, match="not a file name in generated/"):
        Manifest(
            compiler_version="0.1.0",
            ontology_version="0.1.0",
            files={"../secrets.txt": digest(b"token\n")},
        )


def test_every_parse_problem_is_reported_at_once() -> None:
    document = {"files": {"a.ttl": "nope"}, "surprise": 1}

    with pytest.raises(ManifestError) as raised:
        Manifest.loads(json.dumps(document))

    assert len(raised.value.issues) == 4  # two missing keys, one unknown, one bad digest


def test_a_parse_error_names_the_file(tmp_path: Path) -> None:
    directory = tmp_path / "generated"
    directory.mkdir()
    (directory / MANIFEST_FILE).write_text("{}", encoding="utf-8")

    with pytest.raises(ManifestError, match=MANIFEST_FILE):
        Manifest.load(tmp_path)


# ------------------------------------------------------------------------- writing


def test_the_manifest_is_written_by_the_same_writer_as_the_turtle(tmp_path: Path) -> None:
    """Through ``build.write_all``, so that nothing can disagree about encoding or line
    endings — the platform default would translate every LF on Windows (spec 5.5 rule 5).
    """
    written(tmp_path)
    raw = (tmp_path / "generated" / MANIFEST_FILE).read_bytes()

    assert b"\r\n" not in raw
    assert raw.decode("utf-8") == manifest().dumps()


def test_the_manifest_file_carries_no_graph() -> None:
    """It is not RDF, and must never be round-tripped through the serializer."""
    assert manifest().to_file().graph is None


def test_a_hashed_file_matches_its_bytes_on_disk(tmp_path: Path) -> None:
    """``digest`` is fed the text an ``OutputFile`` carries, and ``write_all`` writes the
    bytes; these tests are only worth anything if the two agree."""
    recorded = written(tmp_path)

    for name, hash_ in recorded.files.items():
        assert hash_ == digest((tmp_path / "generated" / name).read_bytes()), name

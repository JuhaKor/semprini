"""The Pages site that the w3id namespace redirects to (task A2, spec 3.1).

These paths are load-bearing: `https://w3id.org/semprini/ontology#Entity` is permanent,
and the drafted `.htaccess` redirects each of the paths below to this site. A rename
here breaks a permanent identifier, so the set is asserted rather than assumed.

So is every version that has ever been published, which is the part task G5 added. The
`.htaccess` maps `/ontology/X.Y.Z` for any three numbers, so the promise those URLs carry is
kept by this build and by nothing else: a version the site stops emitting is a permanent
identifier that starts returning 404.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import Graph
from tools import build_site

from semprini import ONTOLOGY_PATH, ontology_version

BUILDER = Path(__file__).resolve().parent.parent / "tools" / "build_site.py"
SEM = "https://w3id.org/semprini/ontology#"

OLDER = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sem: <https://w3id.org/semprini/ontology#> .

<https://w3id.org/semprini/ontology> a owl:Ontology ;
    owl:versionInfo "0.0.1" .

sem:Relic a rdfs:Class ;
    rdfs:label "Relic" ;
    rdfs:comment "A term that existed in 0.0.1 and does not exist now." .
"""
"""A released version that no longer resembles the current one.

`sem:Relic` is the whole point: it lets a test tell which document a page was generated
from, which is not a distinction a copy of the real ontology could make.
"""


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("site") / "_site"
    subprocess.run([sys.executable, str(BUILDER), str(output)], check=True)
    return output


@pytest.fixture
def with_an_older_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The site as it will look after the first ontology bump, built now.

    The archive is faked rather than added to, because the failure this guards against only
    happens on the *second* released version and the project has one. Waiting for the real
    bump to find out is how the gap survived A2 in the first place.
    """
    archive = tmp_path / "ontology-archive"
    (archive / "0.0.1").mkdir(parents=True)
    (archive / "0.0.1" / "sem.ttl").write_text(OLDER, encoding="utf-8", newline="\n")
    (archive / ontology_version()).mkdir()
    (archive / ontology_version() / "sem.ttl").write_bytes(ONTOLOGY_PATH.read_bytes())
    monkeypatch.setattr(build_site, "ARCHIVE", archive)

    output = tmp_path / "_site"
    build_site.build(output)
    return output


def test_the_site_holds_exactly_the_paths_the_redirects_target(site: Path) -> None:
    """The negotiated paths, plus one pair per released version — and nothing else.

    Derived from the archive rather than written out, because the set grows by two files at
    every ontology release. A hard-coded list would fail on the first bump: the release pull
    request that archives a version is precisely the thing this build exists to serve.
    """
    expected = {"index.html", "ontology/index.html", "ontology/sem.ttl"}
    for version, _ in build_site.released():
        expected |= {f"ontology/{version}/index.html", f"ontology/{version}/sem.ttl"}

    published = {path.relative_to(site).as_posix() for path in site.rglob("*") if path.is_file()}

    assert published == expected
    # ...and the archive is not empty, or the loop above asserted nothing at all.
    assert f"ontology/{ontology_version()}/sem.ttl" in published


def test_a_released_version_still_resolves_after_the_next_one_ships(
    with_an_older_release: Path,
) -> None:
    """The gap A2 left open, closed (task G5).

    Publishing 0.1.0 used to delete `/ontology/0.0.1/` — a URL w3id.org promises resolves for
    ever, and which somebody outside this project may already have written into a query or a
    pinned dependency. Both paths exist now, and the old one still serves the old document.
    """
    older = with_an_older_release / "ontology" / "0.0.1"

    assert (older / "sem.ttl").read_text(encoding="utf-8") == OLDER
    assert (with_an_older_release / "ontology" / ontology_version() / "sem.ttl").read_bytes() == (
        ONTOLOGY_PATH.read_bytes()
    )


def test_a_frozen_page_documents_its_own_document(with_an_older_release: Path) -> None:
    """Not the current one. A page describing today's terms under a released version's number
    is a worse answer than a 404, because it looks like an answer — and somebody comparing
    their instance against the version it pinned would be reading the wrong vocabulary."""
    older = (with_an_older_release / "ontology" / "0.0.1" / "index.html").read_text("utf-8")
    current = (with_an_older_release / "ontology" / "index.html").read_text("utf-8")

    assert 'id="Relic"' in older
    assert 'id="Entity"' not in older
    assert 'id="Relic"' not in current


def test_the_current_page_lists_every_published_version(with_an_older_release: Path) -> None:
    """A permanent path nobody can discover is one nobody uses. The list is on the current
    page only: a frozen page that grew links to releases made after it would not be frozen."""
    current = (with_an_older_release / "ontology" / "index.html").read_text("utf-8")
    older = (with_an_older_release / "ontology" / "0.0.1" / "index.html").read_text("utf-8")

    for version in ("0.0.1", ontology_version()):
        assert f"/ontology/{version}/" in current
    assert "Published versions" not in older


def test_versions_are_listed_newest_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Numerically, so `0.0.10` comes before `0.0.9` rather than after it.

    Only an ordering on a page, and it would be invisible for another nine releases — which
    is exactly why it is asserted now rather than discovered by a reader who concludes the
    list is stale and stops trusting the documents it links to.
    """
    # Three versions, because two cannot tell the two wrong answers apart: sorting `0.0.9`
    # and `0.0.10` as text happens to produce the right order, and only a third version
    # between them separates a numeric comparison from a lexical one. All older than the
    # current one, which is the only arrangement a release would ever leave behind.
    archive = tmp_path / "ontology-archive"
    for version in ("0.0.2", "0.0.9", "0.0.10"):
        (archive / version).mkdir(parents=True)
        (archive / version / "sem.ttl").write_text(
            OLDER.replace("0.0.1", version), encoding="utf-8", newline="\n"
        )
    # The current version is archived too: only a released version is published at all, so an
    # archive without it describes a site with no current version on the list.
    (archive / ontology_version()).mkdir()
    (archive / ontology_version() / "sem.ttl").write_bytes(ONTOLOGY_PATH.read_bytes())
    monkeypatch.setattr(build_site, "ARCHIVE", archive)

    assert [name for name, _ in build_site.released()] == [
        ontology_version(),
        "0.0.10",
        "0.0.9",
        "0.0.2",
    ]

    build_site.build(tmp_path / "_site")
    listed = (tmp_path / "_site" / "ontology" / "index.html").read_text("utf-8")

    assert listed.index(f"/ontology/{ontology_version()}/") < listed.index("/ontology/0.0.10/")
    assert listed.index("/ontology/0.0.10/") < listed.index("/ontology/0.0.9/")
    assert listed.index("/ontology/0.0.9/") < listed.index("/ontology/0.0.2/")


def test_an_unreleased_version_gets_no_permanent_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A versioned path is published for an archived version and for nothing else.

    The case: `owl:versionInfo` is bumped in a pull request and merged, and the release that
    freezes it is still weeks away. Publishing `/ontology/<that version>/` straight from the
    working tree would put a URL behind a permanent identifier that a later revert — or a
    second bump before the release — silently deletes. Nothing else in this project would
    notice: `release_check.py` only runs on a tag, by which time the path has been live on
    main for weeks and may already have been dereferenced.

    So the in-development version is documented at `/ontology/`, which is not permanent and
    never was, and the page says so rather than linking a path that does not exist.
    """
    archive = tmp_path / "ontology-archive"
    (archive / "0.0.1").mkdir(parents=True)
    (archive / "0.0.1" / "sem.ttl").write_text(OLDER, encoding="utf-8", newline="\n")
    monkeypatch.setattr(build_site, "ARCHIVE", archive)

    output = tmp_path / "_site"
    build_site.build(output)

    assert not (output / "ontology" / ontology_version()).exists()
    assert (output / "ontology" / "0.0.1" / "sem.ttl").is_file()
    assert (output / "ontology" / "sem.ttl").read_bytes() == ONTOLOGY_PATH.read_bytes()

    current = (output / "ontology" / "index.html").read_text("utf-8")
    assert "has no permanent path yet" in current
    assert f'href="{ontology_version()}/"' not in current


def test_a_directory_that_is_not_a_version_stops_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refused rather than skipped. A silently ignored directory is a version somebody
    believed they had published, discovered by whoever dereferences it."""
    archive = tmp_path / "ontology-archive"
    (archive / "latest").mkdir(parents=True)
    (archive / "latest" / "sem.ttl").write_text(OLDER, encoding="utf-8", newline="\n")
    monkeypatch.setattr(build_site, "ARCHIVE", archive)

    with pytest.raises(SystemExit, match="not named for a version"):
        build_site.build(tmp_path / "_site")


def test_the_published_turtle_is_the_packaged_turtle(site: Path) -> None:
    # Byte-for-byte, both copies: what an instance pins and what the namespace resolves
    # to must be the same document, and the site build is the only place they could
    # diverge.
    packaged = ONTOLOGY_PATH.read_bytes()
    assert (site / "ontology" / "sem.ttl").read_bytes() == packaged
    assert (site / "ontology" / ontology_version() / "sem.ttl").read_bytes() == packaged


def test_every_term_is_documented_at_its_own_fragment(site: Path) -> None:
    # sem:Entity is a hash IRI: a browser resolving it arrives at the documentation page
    # with #Entity, and lands nowhere useful unless that id exists. Read from the
    # ontology rather than a list, so a term added later is covered without an edit.
    graph = Graph()
    graph.parse(ONTOLOGY_PATH, format="turtle")
    declared = {
        str(subject).removeprefix(SEM)
        for subject in graph.subjects()
        if str(subject).startswith(SEM)
    }
    assert declared, "no sem: terms found — the ontology or this test is broken"

    page = (site / "ontology" / "index.html").read_text(encoding="utf-8")
    for name in declared:
        assert f'id="{name}"' in page, name


def test_the_frozen_version_is_reachable_from_the_current_one(site: Path) -> None:
    current = (site / "ontology" / "index.html").read_text(encoding="utf-8")
    assert f'href="{ontology_version()}/"' in current

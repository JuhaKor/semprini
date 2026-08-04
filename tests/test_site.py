"""The Pages site that the w3id namespace redirects to (task A2, spec 3.1).

These paths are load-bearing: `https://w3id.org/semprini/ontology#Entity` is permanent,
and the drafted `.htaccess` redirects each of the paths below to this site. A rename
here breaks a permanent identifier, so the set is asserted rather than assumed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import Graph

from semprini import ONTOLOGY_PATH, ontology_version

BUILDER = Path(__file__).resolve().parent.parent / "tools" / "build_site.py"
SEM = "https://w3id.org/semprini/ontology#"


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("site") / "_site"
    subprocess.run([sys.executable, str(BUILDER), str(output)], check=True)
    return output


def test_the_site_holds_exactly_the_paths_the_redirects_target(site: Path) -> None:
    version = ontology_version()
    published = {path.relative_to(site).as_posix() for path in site.rglob("*") if path.is_file()}
    assert published == {
        "index.html",
        "ontology/index.html",
        "ontology/sem.ttl",
        f"ontology/{version}/index.html",
        f"ontology/{version}/sem.ttl",
    }


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

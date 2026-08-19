"""G5's battery: break the release machinery, and demand the suite notices.

Everything here guards something that cannot be taken back. A wheel published under a tag is
what instances install for as long as they pin it; an ontology document published at
`/ontology/X.Y.Z/` is a permanent identifier somebody outside this project may already have
fetched. There is no release to amend afterwards, so the checks that refuse an incoherent one
have to bite *before* the tag — and a check that quietly stopped comparing anything would look
exactly like one that works.

The mutations fall into three groups.

**The site publishes fewer versions than it has.** This is the gap task A2 left open, and the
first mutation below is precisely the code as it stood before G5: build the versioned path from
`sem.ttl` alone. It publishes a working site — with one URL missing, which is the failure that
would otherwise be found by whoever dereferenced it.

**The release check stops checking.** Each of these leaves `tools/release_check.py` printing
that the release is coherent while one of the four version statements disagrees.

**An instance is pinned to nothing, or to the wrong address.** With no package index the
version is only useful as part of a URL, so a workflow naming the right version at the wrong
address is a compile that 404s every Monday in somebody else's repository.

Two things are deliberately not mutated. The archive's contents — a frozen `sem.ttl` — cannot
be mutated meaningfully, because a battery that edited one would be doing the exact thing the
freeze exists to prevent, and `test_the_current_ontology_version_is_archived_byte_for_byte`
already fails on any edit to either copy. And `pages.yml` is not here: nothing in this project
executes it, so no mutation of it can be caught by the suite. It is reviewed, not tested.
"""

from __future__ import annotations

TESTS: tuple[str, ...] = (
    "tests/test_site.py",
    "tests/test_release.py",
    "tests/test_scaffold.py",
)

SITE = "tools/build_site.py"
CHECK = "tools/release_check.py"
PACKAGE = "src/semprini/__init__.py"
COMPILE = "src/semprini/workflows/github/compile.yml"
README = "src/semprini/templates/instance/README.md"
SMOKE = "tools/release_smoke.py"

# (description, file, old, new). `old` is a verbatim fragment of the file it anchors to and
# appears in it exactly once.
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    # ------------------------------------------- the site publishes fewer versions than it has
    (
        "the site publishes only the current ontology version, as it did before G5",
        SITE,
        "    sources = dict(released())",
        "    sources = {version: ONTOLOGY_PATH}",
    ),
    (
        # Found by review, not by this battery: publishing the working tree's version at a
        # permanent path means a bump that is reverted, or re-bumped before its release,
        # deletes a URL that resolved on main for weeks.
        "a version living only in the working tree is published at a permanent path",
        SITE,
        "    if version in sources:",
        "    if True:",
    ),
    (
        "a released version's page is generated from today's ontology",
        SITE,
        "        if name != version:",
        "        if False:",
    ),
    (
        "a released version's Turtle is re-derived from the shipped document",
        SITE,
        '        (ontology_dir / name / "sem.ttl", sources[name]) for name in published',
        '        (ontology_dir / name / "sem.ttl", ONTOLOGY_PATH) for name in published',
    ),
    (
        "an archive directory nobody can serve is skipped instead of refused",
        SITE,
        '            raise SystemExit(f"{directory} is not named for a version")',
        "            continue",
    ),
    (
        "versions are listed lexically, so 0.10.0 sorts before 0.9.0",
        SITE,
        "    return [(name, document) for _, name, document in sorted(found, reverse=True)]",
        "    return [(name, document) for _, name, document in sorted(found, key=str, reverse=True)]",  # noqa: E501
    ),
    (
        "the published list runs oldest first",
        SITE,
        "    sources = dict(released())",
        "    sources = dict(reversed(released()))",
    ),
    (
        "the current version's page links no other version",
        SITE,
        "    if not versions:",
        "    if True:",
    ),
    # ------------------------------------------------------ the release check stops checking
    (
        "an archived ontology is accepted without comparing it to the shipped one",
        CHECK,
        "    if frozen.read_bytes() != ONTOLOGY_PATH.read_bytes():",
        "    if False:",
    ),
    (
        "a missing archive entry is accepted, so a version is published that will stop resolving",
        CHECK,
        "    if not frozen.is_file():",
        "    if False and not frozen.is_file():",
    ),
    (
        "the changelog is searched for the version anywhere, so [Unreleased] entries count",
        CHECK,
        r'    return re.compile(rf"^## \[{re.escape(version)}\][ ]+[-—][ ]+\d{{4}}-\d{{2}}-\d{{2}}\s*$", re.M)',  # noqa: E501
        "    return re.compile(re.escape(version))",
    ),
    (
        "the release notes run on past the section into every earlier release",
        CHECK,
        '    end = re.search(r"^## ", after, re.M)',
        "    end = None",
    ),
    (
        "the tag is not compared with the packaged version",
        CHECK,
        "    if declared != version:",
        "    if False:",
    ),
    (
        "a tag with a suffix is accepted, and names a download directory that does not exist",
        CHECK,
        r'TAG = re.compile(r"\Av(?P<version>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\Z")',  # noqa: E501
        r'TAG = re.compile(r"\Av(?P<version>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))")',  # noqa: E501
    ),
    (
        "a malformed archive directory is reported as well formed",
        CHECK,
        '        if not TAG.match(f"v{entry.name}"):',
        "        if False:",
    ),
    (
        "an ontology version that went backwards is published as though it were the newest",
        CHECK,
        "    if ahead:",
        "    if False:",
    ),
    (
        "a missing archive raises instead of leaving the instruction the check above gave",
        CHECK,
        "    if not ARCHIVE.is_dir():",
        "    if False:",
    ),
    (
        "the wheel a release publishes is never compared with the URL instances fetch",
        SMOKE,
        "    if (dist / expected).is_file():",
        "    if True:",
    ),
    # ------------------------------------- an instance is pinned to nothing, or to the wrong URL
    (
        "the download URL names the tag but not the wheel's own version",
        PACKAGE,
        '    return f"{PROJECT_URL}/releases/download/v{version}/semprini-{version}-py3-none-any.whl"',  # noqa: E501
        '    return f"{PROJECT_URL}/releases/download/v{version}/semprini-py3-none-any.whl"',
    ),
    (
        "the download URL points at the latest release rather than the pinned one",
        PACKAGE,
        '    return f"{PROJECT_URL}/releases/download/v{version}/semprini-{version}-py3-none-any.whl"',  # noqa: E501
        '    return f"{PROJECT_URL}/releases/latest/download/semprini-{version}-py3-none-any.whl"',
    ),
    (
        "the compile workflow installs whatever release is current",
        COMPILE,
        '          SEMPRINI_VERSION: "%%version%%"',
        '          SEMPRINI_VERSION: "latest"',
    ),
    (
        "the instance README tells its stewards to install from an index that does not exist",
        README,
        'pip install "semprini @ %%wheel_url%%"',
        "pip install semprini",
    ),
)

"""G3's battery: break the migration, and break the guards that hold it to its promise.

Two kinds of mutation, and the second kind is why this file is longer than the module it
tests. Breaking the migration asks whether the byte-identity test bites. Breaking a *guard*
asks whether the tests that describe the guard bite — and those are the tests most likely to
be asserting nothing, because each one has to construct a misbehaving migration in order to
be refused by one. A guard that had been quietly disabled would leave every one of them
passing for the wrong reason: no exception raised, no files written, no way to tell the
difference from the outside without looking.

The mutation worth the whole file is `the snapshot is taken after the steps run`. An rdflib
graph and an IdMap are mutable, so a step that edits what it was handed rather than returning
something new would leave the before/after comparison comparing an object with itself — and
all four of spec 7's refusals would pass on a migration that had just minted an IRI. It is a
one-line reordering, it looks correct, and exactly one test in the suite fails on it.

Two mutations are deliberately absent. Nothing mutates `MIGRATIONS` in `steps.py`: it is
empty by design, and "this release ships no migration" is a statement about the release
rather than about code that could be wrong. And nothing mutates `report.table`'s cell
escaping — that is C2's guard, mutated in its own battery, and reached from here only because
the migration report renders through it rather than through a second copy.
"""

from __future__ import annotations

TESTS: tuple[str, ...] = (
    "tests/test_migrate.py",
    "tests/test_run.py",
    "tests/test_cli.py",
)
"""`test_run.py` because the stale-file and ontology-copy helpers moved into `build.py` for
the migration to share, and a run is the other caller of both; `test_cli.py` for the surface,
which G3 completed."""

APPLY = "src/semprini/migrate/apply.py"
REGISTRY = "src/semprini/migrate/registry.py"
BUILD = "src/semprini/build.py"

# (description, file, old, new). `old` is a verbatim fragment of the file it anchors to and
# appears in it exactly once.
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    # ------------------------------------------- the four refusals of spec 7, one at a time
    (
        "the snapshot is taken after the steps run, so nothing is really compared",
        APPLY,
        """    before = _Snapshot.of(after)
    for step in steps:
        after = _applied(step, after)""",
        """    for step in steps:
        after = _applied(step, after)
    before = _Snapshot.of(after)""",
    ),
    (
        "the snapshot holds the ID map itself rather than a copy of its rows",
        APPLY,
        "            id_map=IdMap(state.id_map.rows, origin=state.id_map.origin),",
        "            id_map=state.id_map,",
    ),
    (
        "a minted IRI is tolerated",
        APPLY,
        "        for iri in sorted(now - was)",
        "        for iri in ()",
    ),
    (
        "a node dropped from generated/ is tolerated",
        APPLY,
        "        for iri in sorted(was - now)",
        "        for iri in ()",
    ),
    (
        "a moved dcterms:modified date is tolerated",
        APPLY,
        "        if before_dates.get(iri, frozenset()) != after_dates.get(iri, frozenset())",
        "        if False",
    ),
    (
        "the date comparison reads the file each subject is written in, not the union",
        APPLY,
        "    for graph in graphs.values():\n        for subject, object_ in graph.subject_objects(DCTERMS.modified):",  # noqa: E501
        "    for graph in list(graphs.values())[:1]:\n        for subject, object_ in graph.subject_objects(DCTERMS.modified):",  # noqa: E501
    ),
    (
        "the ID map is not held to being append-only",
        APPLY,
        "    issues.extend(after.id_map.check_append_only(before.id_map))",
        "    issues.extend(())",
    ),
    (
        "a row appended to the ID map is tolerated",
        APPLY,
        "        for ref in sorted(row.ref for row in after.id_map if row.ref not in known)",
        "        for ref in ()",
    ),
    (
        "only the first violation is reported",
        APPLY,
        "    if issues:\n        raise MigrationError(issues)\n\n\ndef _subjects(",
        "    if issues:\n        raise MigrationError(issues[:1])\n\n\ndef _subjects(",
    ),
    # ----------------------------------------------------- what a step is allowed to write
    (
        "a file name that escapes generated/ is written",
        APPLY,
        'if not manifest.is_generated_file_name(name) or not name.endswith(".ttl"):',
        'if not name.endswith(".ttl"):',
    ),
    (
        "a step may add a file that is not Turtle",
        APPLY,
        'if not manifest.is_generated_file_name(name) or not name.endswith(".ttl"):',
        "if not manifest.is_generated_file_name(name):",
    ),
    (
        "a step may rewrite the verbatim ontology copy",
        APPLY,
        "        if name == ONTOLOGY_FILE:",
        "        if False:",
    ),
    (
        "a graph the canonical serializer refuses escapes as a traceback",
        APPLY,
        "        except ValueError as error:\n            # A blank node or a literal subject",
        "        except TypeError as error:\n            # A blank node or a literal subject",
    ),
    (
        "a step that returns something other than a state is left to fail later",
        APPLY,
        "    if not isinstance(result, InstanceState):",
        "    if False:",
    ),
    (
        "a step that raises escapes as its own exception, naming no version",
        APPLY,
        "    try:\n        result = step.apply(state)\n    except Exception as error:",
        "    try:\n        result = step.apply(state)\n    except _Unraised as error:",
    ),
    # ------------------------------------------------------- which steps run, and in which order
    (
        "steps run newest first",
        REGISTRY,
        "        migration for version, migration in sorted(seen.items()) if recorded < version <= target",  # noqa: E501
        "        migration\n        for version, migration in sorted(seen.items(), reverse=True)\n        if recorded < version <= target",  # noqa: E501
    ),
    (
        "the step of the release that already compiled the instance runs again",
        REGISTRY,
        "if recorded < version <= target",
        "if recorded <= version <= target",
    ),
    (
        "a step beyond the target version runs anyway",
        REGISTRY,
        "if recorded < version <= target",
        "if recorded < version",
    ),
    (
        "two steps for one release are resolved by taking one",
        REGISTRY,
        "        if version in seen:",
        "        if False:",
    ),
    (
        "a downgrade is performed",
        REGISTRY,
        "    if target < recorded:",
        "    if False:",
    ),
    (
        "versions are compared as strings, so 0.10.0 precedes 0.9.0",
        REGISTRY,
        "    return int(major), int(minor), int(patch)",
        "    return major, minor, patch  # type: ignore[return-value]",
    ),
    (
        "any version string is accepted, including one identifying no release",
        REGISTRY,
        r'_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")',
        r'_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")',
    ),
    (
        "a step ships without a summary, so the report says nothing about it",
        REGISTRY,
        "        if not self.summary.strip():",
        "        if False:",
    ),
    # ------------------------------------------------------------ the versions on the files
    (
        "--to may name a version that is not the one installed",
        APPLY,
        "    if to != running_compiler:",
        "    if False:",
    ),
    (
        "the restamped manifest records the version that used to be recorded",
        APPLY,
        "    files += (Manifest.create(files, compiler=compiler, ontology=ontology).to_file(),)",
        "    files += (\n        Manifest.create(\n            files, compiler=recorded.compiler_version, ontology=recorded.ontology_version\n        ).to_file(),\n    )",  # noqa: E501
    ),
    (
        "an ontology version that moved on its own is read as nothing to do",
        APPLY,
        "    if from_compiler == target and recorded.ontology_version == running_ontology:",
        "    if from_compiler == target:",
    ),
    (
        "there is no up-to-date case, so migrating twice rewrites the instance",
        APPLY,
        "    if from_compiler == target and recorded.ontology_version == running_ontology:",
        "    if False:",
    ),
    (
        "generated/ is migrated without first being checked against its manifest",
        APPLY,
        "    mismatched = recorded.verify(root)",
        "    mismatched = ()",
    ),
    # -------------------------------------------------------------- what reaches the disk
    (
        "the ontology copy is left as the previous release wrote it",
        APPLY,
        "    files: list[OutputFile] = [build.ontology_file()]",
        "    files: list[OutputFile] = []",
    ),
    (
        "the report the migration wrote is then deleted as stale",
        APPLY,
        "    stale = build.stale(files, root, keep=(REPORT_FILE,))",
        "    stale = build.stale(files, root)",
    ),
    (
        "a file the migration no longer produces is left in generated/",
        APPLY,
        "    build.remove(stale, root)",
        "    build.remove((), root)",
    ),
    (
        "the ID map is not written, so a step that touched it loses the change",
        APPLY,
        "    after.id_map.save(root)",
        "    pass",
    ),
    (
        "no report is written, so the committed one names a release that wrote nothing",
        APPLY,
        "    files += (run_report.to_file(),)",
        "    files = files",
    ),
    # ------------------------------------ the two helpers a run and a migration now share
    (
        "the report is treated as stale output by whoever did not produce it",
        BUILD,
        "    produced = {file.name for file in files} | set(keep)",
        "    produced = {file.name for file in files}",
    ),
    (
        "generated/ is scanned one level deep, so a nested leftover survives",
        BUILD,
        '        for path in sorted(directory.rglob("*"))\n        if path.is_file() and (name := path.relative_to(directory).as_posix()) not in produced',  # noqa: E501
        '        for path in sorted(directory.glob("*"))\n        if path.is_file() and (name := path.relative_to(directory).as_posix()) not in produced',  # noqa: E501
    ),
    (
        "the ontology is re-serialized rather than copied",
        BUILD,
        '    return OutputFile(name=ONTOLOGY_FILE, text=ONTOLOGY_PATH.read_text(encoding="utf-8"))',
        '    graph = Graph()\n    graph.parse(ONTOLOGY_PATH, format="turtle")\n    return OutputFile(\n        name=ONTOLOGY_FILE, text=serialize.serialize(graph, "https://semantics.example.com/")\n    )',  # noqa: E501
    ),
)

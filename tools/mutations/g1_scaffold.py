"""G1's battery: break the instance scaffold on purpose, demand the suite notices.

A scaffold is the one artefact in this project nobody re-runs to check — an adopter
bootstraps once and lives with what was written — so most of what the tests assert is
absence, and a test asserting absence looks identical whether or not it is asserting
anything.

Two notes on what is *not* in here. Nothing mutates the network guard, because a mutation
that opens a socket is not a plausible alternative implementation of anything; the guard
earns its keep against a later change, not against this code. And the platform-newline
mutation is written as an explicit CRLF rather than as ``newline=None``, which would fail
only on Windows and would report a survivor on the CI that runs Linux.
"""

from __future__ import annotations

TESTS: tuple[str, ...] = ("tests/test_scaffold.py", "tests/test_cli.py", "tests/test_check.py")

SCAFFOLD = "src/semprini/scaffold.py"
CLI = "src/semprini/cli.py"
CONFIG_TEMPLATE = "src/semprini/templates/instance/config/semprini.yaml"
WORKFLOW = "src/semprini/workflows/github/validate.yml"

# (description, file, old, new). `old` is a verbatim fragment of the file it anchors to and
# is never reformatted or rewrapped — a line over the limit is silenced with a per-line
# ruff directive rather than split, since a split anchor is one nobody can compare against
# the source it was copied from.
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    # ------------------------------------------------------------------ what it refuses
    (
        "an existing instance is bootstrapped over",
        SCAFFOLD,
        "    _check_nothing_is_overwritten(root, files)",
        "    pass  # _check_nothing_is_overwritten(root, files)",
    ),
    (
        "only the namespace lock is protected, not the files beside it",
        SCAFFOLD,
        """    existing = [file.path for file in files if (root / Path(file.path)).exists()]""",
        """    existing: list[PurePosixPath] = []""",
    ),
    (
        "a second bootstrap is reported as an ordinary overwrite",
        SCAFFOLD,
        """    if (root / NAMESPACE_LOCK_PATH).exists():""",
        """    if False and (root / NAMESPACE_LOCK_PATH).exists():""",
    ),
    (
        "the tree is written as it is rendered, so a refusal leaves half an instance",
        SCAFFOLD,
        """    _check_nothing_is_overwritten(root, files)
    return Scaffold(root=root, files=files, base_iri=base_iri, instance_id=org, version=version)""",
        """    rendered = Scaffold(
        root=root, files=files, base_iri=base_iri, instance_id=org, version=version
    )
    rendered.write()
    _check_nothing_is_overwritten(root, files)
    return rendered""",
    ),
    (
        "only the first bad argument is reported",
        SCAFFOLD,
        """    if not is_slug(org):
        issues.append(""",
        """    if issues:
        raise ScaffoldError(issues)
    if not is_slug(org):
        issues.append(""",
    ),
    (
        "the base IRI is judged by a looser rule than the serializer's",
        SCAFFOLD,
        """    try:
        # The serializer's own rule, so a base IRI accepted here cannot fail when the
        # instance writes its first file (spec 5.5).
        namespaces(base_iri)
    except ValueError as error:
        issues.append(Issue(Severity.ERROR, str(error), "--base-iri"))""",
        """    if not base_iri.startswith("http"):
        issues.append(Issue(Severity.ERROR, f"not an http IRI: {base_iri!r}", "--base-iri"))""",
    ),
    (
        "the instance id is not held to the slug rule",
        SCAFFOLD,
        "    if not is_slug(org):",
        "    if False and not is_slug(org):",
    ),
    (
        "any language tag is accepted",
        SCAFFOLD,
        "    if not is_language_tag(default_language):",
        "    if False and not is_language_tag(default_language):",
    ),
    (
        "a target that is a file is written into anyway",
        SCAFFOLD,
        "    if root.exists() and not root.is_dir():",
        "    if False and root.exists() and not root.is_dir():",
    ),
    (
        "a missing template directory is read as an empty one",
        SCAFFOLD,
        "    if not directory.is_dir():",
        "    if False and not directory.is_dir():",
    ),
    (
        "a source tree may bootstrap an instance",
        SCAFFOLD,
        "    _check_the_plane_is_installed(version)",
        "    pass  # _check_the_plane_is_installed(version)",
    ),
    (
        "an unresolved placeholder is left in the file it was written into",
        SCAFFOLD,
        """        if name not in values:
            raise ValueError(""",
        """        if name not in values:
            return match.group(0)
        if False:
            raise ValueError(""",
    ),
    # ------------------------------------------------------------------ what it writes
    (
        "the templates are copied rather than rendered",
        SCAFFOLD,
        """        yield ScaffoldFile(prefix / relative, _render(path.read_text(encoding="utf-8"), values))""",  # noqa: E501
        """        yield ScaffoldFile(prefix / relative, path.read_text(encoding="utf-8"))""",
    ),
    (
        "a template is read without translating its line endings",
        SCAFFOLD,
        """        yield ScaffoldFile(prefix / relative, _render(path.read_text(encoding="utf-8"), values))""",  # noqa: E501
        """        with path.open(encoding="utf-8", newline="") as handle:
            yield ScaffoldFile(prefix / relative, _render(handle.read(), values))""",
    ),
    (
        "the instance is written with CRLF line endings",
        SCAFFOLD,
        """            path.write_text(file.text, encoding="utf-8", newline="\\n")""",
        """            path.write_text(file.text, encoding="utf-8", newline="\\r\\n")""",
    ),
    (
        "the files are ordered by name rather than by path",
        SCAFFOLD,
        """            key=lambda file: file.path,""",
        """            key=lambda file: file.path.name,""",
    ),
    (
        "the workflows are not materialized",
        SCAFFOLD,
        """                *_templated(WORKFLOW_TEMPLATES / WORKFLOW_PLATFORM, WORKFLOW_DIR, values),""",  # noqa: E501
        """""",
    ),
    (
        "the workflows are written outside .github/",
        SCAFFOLD,
        """WORKFLOW_DIRS: Mapping[str, PurePosixPath] = {"github": PurePosixPath(".github/workflows")}""",  # noqa: E501
        """WORKFLOW_DIRS: Mapping[str, PurePosixPath] = {"github": PurePosixPath("workflows")}""",
    ),
    (
        "a workflow template that is not valid YAML ships anyway",
        WORKFLOW,
        """on:
  pull_request:""",
        """on:
  pull_request: [""",
    ),
    (
        "the compile workflow opens a pull request with no report in it",
        "src/semprini/workflows/github/compile.yml",
        "          body-path: generated/.report.md",
        "",
    ),
    (
        "the workflows install the latest plane version rather than this one",
        WORKFLOW,
        "      - run: pip install semprini==%%version%%",
        "      - run: pip install semprini",
    ),
    (
        "generated/ is left for the first run to create",
        SCAFFOLD,
        """                *_generated(compiler=version, ontology=metamodel),""",
        """""",
    ),
    (
        "the ontology copy is tidied up on the way through",
        SCAFFOLD,
        """    copy = OutputFile(name=ONTOLOGY_FILE, text=ONTOLOGY_PATH.read_text(encoding="utf-8"))""",  # noqa: E501
        """    kept = [
        line
        for line in ONTOLOGY_PATH.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    copy = OutputFile(name=ONTOLOGY_FILE, text="\\n".join(kept) + "\\n")""",
    ),
    (
        "the merge register is left for a steward to create",
        SCAFFOLD,
        """    yield ScaffoldFile(PurePosixPath(MERGES_PATH.as_posix()), MergeRegister().dumps())""",  # noqa: E501
        """""",
    ),
    (
        "the ID map is created empty rather than with its header",
        SCAFFOLD,
        """    yield ScaffoldFile(PurePosixPath(ID_MAP_PATH.as_posix()), IdMap().dumps())""",
        """    yield ScaffoldFile(PurePosixPath(ID_MAP_PATH.as_posix()), "")""",
    ),
    (
        "the lock records the day it was written rather than the date it was given",
        SCAFFOLD,
        """    lock = NamespaceLock(base_iri=base_iri, instance_id=org, ontology_version=ontology, date=today)""",  # noqa: E501
        """    lock = NamespaceLock(
        base_iri=base_iri,
        instance_id=org,
        ontology_version=ontology,
        date=datetime.date.today(),
    )""",
    ),
    (
        "the lock records the compiler version as the ontology version",
        SCAFFOLD,
        """        *_identity(base_iri=base_iri, org=org, ontology=metamodel, today=date),""",
        """        *_identity(base_iri=base_iri, org=org, ontology=version, today=date),""",
    ),
    (
        "the configured base IRI and the frozen one are allowed to differ",
        SCAFFOLD,
        """        "base_iri": base_iri,
        "org": org,""",
        """        "base_iri": base_iri.rstrip("/") + "/v1/",
        "org": org,""",
    ),
    (
        "the target directory is not created",
        SCAFFOLD,
        """            path.parent.mkdir(parents=True, exist_ok=True)""",
        """""",
    ),
    (
        "a configured source is written into the fresh instance",
        CONFIG_TEMPLATE,
        "sources: []",
        """sources:
  - adapter: excel-taxonomy
    name: product-category
    config:
      path: sources/taxonomies/product-category.xlsx
      scheme_slug: product-category""",
    ),
    # --------------------------------------------------------------------------- the CLI
    (
        "--dir is ignored and the instance lands in the working directory",
        CLI,
        """        Path(arguments.dir) if arguments.dir else None,""",
        """        None,""",
    ),
    (
        "--language is ignored",
        CLI,
        """        default_language=arguments.language,""",
        """        default_language=config.DEFAULT_LANGUAGE,""",
    ),
    (
        "a refused bootstrap exits 1 rather than 2",
        SCAFFOLD,
        "class ScaffoldError(ConfigError):",
        """from semprini.model import IssueError


class ScaffoldError(IssueError):""",
    ),
    (
        "init reports itself unimplemented",
        CLI,
        """    if arguments.command == "init":
        return _init(arguments)""",
        """""",
    ),
)

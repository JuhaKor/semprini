"""F3's battery: break the additive-only rule on purpose, demand the suite notices.

A shapes check looks identical whether or not it is asserting anything, so each mutation
below is a plausible alternative implementation. Run with `--rounds 2`: issues are
collected in sets, and an ordering assertion can pass by luck once.
"""

from __future__ import annotations

TESTS: tuple[str, ...] = ("tests/test_validate.py", "tests/test_check.py")

VALIDATE = "src/semprini/validate.py"

# (description, file, old, new). `old` is a verbatim fragment of the file it anchors to and
# is never reformatted or rewrapped — a line over the limit is silenced with a per-line
# ruff directive rather than split, since a split anchor is one nobody can compare against
# the source it was copied from.
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        "a statement about a core IRI is tolerated",
        VALIDATE,
        """    for subject in sorted(set(graph.subjects()), key=str):
        if isinstance(subject, URIRef) and (core := _core_prefix(str(subject))):
            yield Issue(Severity.ERROR, _owned_by_the_plane(core, subject), name)""",
        """    for subject in sorted(set(graph.subjects()), key=str):
        if False and isinstance(subject, URIRef) and (core := _core_prefix(str(subject))):
            yield Issue(Severity.ERROR, _owned_by_the_plane(core, subject), name)""",
    ),
    (
        "only the metamodel namespace is protected, not the core shapes",
        VALIDATE,
        """_CORE_NAMESPACES: Sequence[tuple[str, str]] = (
    ("sem", SEM),
    ("shp", SHAPES_NAMESPACE),
)""",
        """_CORE_NAMESPACES: Sequence[tuple[str, str]] = (("sem", SEM),)""",
    ),
    (
        "only the core shapes are protected, not the metamodel",
        VALIDATE,
        """_CORE_NAMESPACES: Sequence[tuple[str, str]] = (
    ("sem", SEM),
    ("shp", SHAPES_NAMESPACE),
)""",
        """_CORE_NAMESPACES: Sequence[tuple[str, str]] = (("shp", SHAPES_NAMESPACE),)""",
    ),
    (
        "only the core IRIs that exist today are protected, not the namespaces",
        VALIDATE,
        """    for prefix, namespace in _CORE_NAMESPACES:
        if iri.startswith(namespace):
            return prefix
    return None""",
        """    declared = {str(subject) for subject in core_shapes().subjects()}
    for prefix, namespace in _CORE_NAMESPACES:
        if iri.startswith(namespace) and iri in declared:
            return prefix
    return None""",
    ),
    (
        "a core IRI is refused in any position, not only as a subject",
        VALIDATE,
        "    for subject in sorted(set(graph.subjects()), key=str):\n"
        "        if isinstance(subject, URIRef) and (core := _core_prefix(str(subject))):",
        "    for subject in sorted(set(graph.subjects()) | set(graph.objects()), key=str):\n"
        "        if isinstance(subject, URIRef) and (core := _core_prefix(str(subject))):",
    ),
    (
        "a constraint that constrains nothing is tolerated",
        VALIDATE,
        """    for predicate, value, written in _CONSTRAINS_NOTHING:
        for subject in graph.subjects(predicate, value):""",
        """    for predicate, value, written in ():
        for subject in graph.subjects(predicate, value):""",
    ),
    (
        "only sh:minCount 0 is caught, not the other two no-ops",
        VALIDATE,
        """    (SH.minCount, Literal(0), "sh:minCount 0"),
    (SH.uniqueLang, Literal(False), "sh:uniqueLang false"),
    (SH.closed, Literal(False), "sh:closed false"),""",
        """    (SH.minCount, Literal(0), "sh:minCount 0"),""",
    ),
    (
        "any cardinality is refused, not only the no-op one",
        VALIDATE,
        """    (SH.minCount, Literal(0), "sh:minCount 0"),""",
        """    (SH.minCount, Literal(1), "sh:minCount 1"),""",
    ),
    (
        "the relaxed path is not named",
        VALIDATE,
        """    path = min(graph.objects(subject, SH.path), key=str, default=None)
    about = f" on {_short(path)}" if isinstance(path, URIRef) else \"\"""",
        """    path = min(graph.objects(subject, SH.path), key=str, default=None)
    about = \"\"""",
    ),
    (
        "the relaxed path is chosen by rdflib iteration order",
        VALIDATE,
        "    path = min(graph.objects(subject, SH.path), key=str, default=None)",
        "    path = graph.value(subject, SH.path)",
    ),
    (
        "the relaxed path is the last in string order rather than the first",
        VALIDATE,
        "    path = min(graph.objects(subject, SH.path), key=str, default=None)",
        "    path = max(graph.objects(subject, SH.path), key=str, default=None)",
    ),
    (
        "a SHACL rule is tolerated",
        VALIDATE,
        "    for subject in set(graph.subjects(SH.rule, None)):",
        "    for subject in set():",
    ),
    (
        "a reference to a core shape is tolerated",
        VALIDATE,
        "    for object_ in sorted({value for value in graph.objects() if _is_core_shape(value)}, key=str):",  # noqa: E501
        "    for object_ in sorted({value for value in () if _is_core_shape(value)}, key=str):",
    ),
    (
        "a refusal is a warning rather than an error",
        VALIDATE,
        "            yield Issue(Severity.ERROR, _owned_by_the_plane(core, subject), name)",
        "            yield Issue(Severity.WARNING, _owned_by_the_plane(core, subject), name)",
    ),
    (
        "refusals are not reported",
        VALIDATE,
        """    not_additive = check_additive(local)
    issues += not_additive""",
        """    not_additive = check_additive(local)""",
    ),
    (
        "a refused file's rules are applied anyway",
        VALIDATE,
        "    refused = {issue.location for issue in not_additive if issue.severity is Severity.ERROR}",  # noqa: E501
        "    refused: set[str | None] = set()",
    ),
    (
        "one refused file switches off every other file's rules",
        VALIDATE,
        "    applied = {name: graph for name, graph in files.items() if name not in refused}",
        "    applied = {} if any(name in refused for name in files) else dict(files)",
    ),
    (
        "refusals are not sorted",
        VALIDATE,
        """    issues: list[Issue] = []
    for name, graph in files.items():
        issues.extend(_not_additive(name, graph))
    return tuple(sorted(set(issues), key=_sort_key))""",
        """    issues: list[Issue] = []
    for name, graph in files.items():
        issues.extend(_not_additive(name, graph))
    return tuple(set(issues))""",
    ),
    (
        "a local shape file is keyed by its name rather than by its path",
        VALIDATE,
        "        name = path.relative_to(root).as_posix()",
        "        name = path.name",
    ),
    (
        "the local shapes are read as one graph again",
        VALIDATE,
        """    local = read_local_shape_files(repo_root) if local is None else local""",
        """    local = read_local_shape_files(repo_root) if local is None else local
    local = {"shapes/local": build.union_of(local.values())}""",
    ),
    (
        "an unusable shapes graph escapes as a traceback",
        VALIDATE,
        """    except Exception as error:""",
        """    except ZeroDivisionError as error:""",
    ),
    (
        "an unusable local shape is swallowed instead of reported",
        VALIDATE,
        """    except ValidationError as union_failed:
        issues: list[Issue] = []""",
        """    except ValidationError as union_failed:
        return ()
        issues: list[Issue] = []""",
    ),
    (
        "the file that cannot be applied is not named",
        VALIDATE,
        """        issues: list[Issue] = []
        blamed = False""",
        """        issues: list[Issue] = []
        blamed = True""",
    ),
    (
        "the files that do load are not validated when another one fails",
        VALIDATE,
        "                issues.extend(shacl(data, graph))",
        "                shacl(data, graph)",
    ),
    (
        "a library's message keeps its newlines",
        VALIDATE,
        '    return " ".join(str(error).split())',
        "    return str(error)",
    ),
    (
        "a core term is named by its full IRI rather than its prefixed name",
        VALIDATE,
        """    text = str(value)
    for prefix, namespace in _CORE_NAMESPACES:
        if text.startswith(namespace):
            return f"{prefix}:{text[len(namespace) :]}\"""",
        """    text = str(value)
    for prefix, namespace in ():
        if text.startswith(namespace):
            return f"{prefix}:{text[len(namespace) :]}\"""",
    ),
)

"""The eight checks behind ``semprini check`` (spec 6.1), all in the CLI (spec 6.3). Every check
runs and collects, so one run reports everything; checks 4 to 7 are reported as not run when
check 1 finds Turtle that does not parse. Each check calls the module that owns the rule rather
than re-deriving it. Check 6 is the only one that needs git. Three graphs are kept apart. The
generated graph, without ``ontology.ttl``, is judged by the core shapes and the IRI policy. The
overlay graph is judged only on what an overlay may not restate about a generated node; the core
shapes are not applied to it, since ``overlays/external/`` holds standard vocabularies (spec
4.2). Local shapes are applied to both together and must be additive (spec 3.6, 6.1.5); a refused
file's rules are not applied.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Container, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pyshacl import validate as _run_shacl
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, SH
from rdflib.term import IdentifiedNode, Node

from semprini import ONTOLOGY_PATH, adapters, build, lifecycle, ontology_version, serialize
from semprini.config import SLUG_PATTERN, InstanceConfig, SourceConfig
from semprini.identity import (
    ID_MAP_PATH,
    UUID_PATTERN,
    IdentityError,
    IdMap,
    verify_namespace_lock,
)
from semprini.manifest import Manifest, ManifestError
from semprini.model import Issue, IssueError, Kind, RunContext, Severity

__all__ = [
    "CHECKS",
    "LOCAL_NAME_PATTERNS",
    "LOCAL_SHAPES_DIR",
    "OVERLAYS_DIR",
    "SHAPES_DIR",
    "SHAPES_NAMESPACE",
    "CheckOutcome",
    "CheckResult",
    "ValidationError",
    "check",
    "check_additive",
    "check_shapes",
    "core_shapes",
    "instance_shapes",
    "overlay_shapes",
    "read_local_shape_files",
    "read_local_shapes",
    "read_overlays",
    "shacl",
]

SHAPES_DIR = Path(__file__).parent / "shapes"
"""The core shapes shipped with the compiler (spec 6.1.5); every ``.ttl`` here is loaded."""

SHAPES_NAMESPACE = "https://w3id.org/semprini/shapes#"
"""Where the core shapes' own IRIs live; the w3id path reserved for them."""

OVERLAYS_DIR = Path("overlays")
"""The only hand-written RDF an instance has (spec 4.2, 4.3)."""

LOCAL_SHAPES_DIR = Path("shapes") / "local"

SEM = serialize.SEM_NAMESPACE
SKOS_CONCEPT_SCHEME = URIRef("http://www.w3.org/2004/02/skos/core#ConceptScheme")
SKOS_IN_SCHEME = URIRef("http://www.w3.org/2004/02/skos/core#inScheme")
SKOS_PREF_LABEL = URIRef("http://www.w3.org/2004/02/skos/core#prefLabel")
SEM_STATUS = URIRef(f"{SEM}status")

TAXONOMY_VALUE_TARGET = URIRef(f"{SHAPES_NAMESPACE}TaxonomyValueTarget")
"""The SPARQL target ``core.ttl`` defines for a plain ``skos:Concept``. The IRI-policy
shape references it, which is why :func:`instance_shapes` needs :func:`core_shapes`."""

LOCAL_NAME_PATTERNS: Mapping[Kind, str] = {
    Kind.ENTITY: UUID_PATTERN,
    Kind.ATTRIBUTE: UUID_PATTERN,
    Kind.RELATIONSHIP: UUID_PATTERN,
    Kind.TAXONOMY_VALUE: UUID_PATTERN,
    Kind.SCHEME: SLUG_PATTERN,
}
"""What a local name looks like, per kind (spec 3.4.2)."""

_PROTECTED_OF_A_GENERATED_NODE: Sequence[tuple[URIRef, str]] = (
    (SKOS_PREF_LABEL, "skos:prefLabel"),
    (SEM_STATUS, "sem:status"),
    (SKOS_IN_SCHEME, "skos:inScheme"),
)
"""What an overlay may never restate for a generated node (spec 6.1.5)."""


class ValidationError(IssueError):
    """A file the checks cannot read — CLI exit code 1 (spec 5.1). Violations are returned, not
    raised.
    """

    noun = "validation error"


def core_shapes() -> Graph:
    """The shapes shipped with the compiler (spec 6.1.5), parsed afresh on each call."""
    graph = Graph()
    for path in sorted(SHAPES_DIR.glob("*.ttl")):
        graph.parse(path, format="turtle")
    return graph


def instance_shapes(base_iri: str) -> Graph:
    """The IRI policy for one instance (spec 3.1, 3.4.2, 6.1.5): every generated subject is
    in its kind's namespace with a minted local name. Apply together with :func:`core_shapes`."""
    namespaces = serialize.namespaces(base_iri)
    graph = Graph()
    for kind, classes, described in _IRI_POLICY_TARGETS:
        namespace = namespaces[kind.prefix]
        shape = URIRef(f"{SHAPES_NAMESPACE}IriPolicy-{kind.value}")
        pattern = f"^{re.escape(namespace)}{LOCAL_NAME_PATTERNS[kind]}$"
        _add_all(
            graph,
            shape,
            (RDF.type, SH.NodeShape),
            (SH.nodeKind, SH.IRI),
            (SH.pattern, Literal(pattern)),
            (
                SH.message,
                Literal(
                    f"{described} is minted as <{namespace}> plus an opaque local name; "
                    f"this IRI is not (spec 3.1, 3.4.2)"
                ),
            ),
        )
        for target in classes:
            graph.add((shape, SH.targetClass, target))
        if kind is Kind.TAXONOMY_VALUE:
            graph.add((shape, SH.target, TAXONOMY_VALUE_TARGET))
    return graph


def overlay_shapes(base_iri: str) -> Graph:
    """What an overlay may not say about a generated node (spec 6.1.5). Apply to the overlay graph
    alone.
    """
    namespaces = serialize.namespaces(base_iri)
    generated = "|".join(
        re.escape(namespaces[prefix]) for prefix in sorted({kind.prefix for kind in Kind})
    )
    graph = Graph()
    for predicate, name in _PROTECTED_OF_A_GENERATED_NODE:
        shape = URIRef(f"{SHAPES_NAMESPACE}Overlay-{name.replace(':', '-')}")
        forbidden = _blank(graph, (SH.pattern, Literal(f"^({generated})")))
        _add_all(
            graph,
            shape,
            (RDF.type, SH.NodeShape),
            (SH.targetSubjectsOf, predicate),
            (SH["not"], forbidden),
            (
                SH.message,
                Literal(
                    f"an overlay may not restate the {name} of a generated node: it is "
                    f"the compiler's to write, and generated/ is machine-owned "
                    f"(spec 4.3, 6.1.5)"
                ),
            ),
        )
    return graph


def read_overlays(repo_root: Path | None = None) -> Graph:
    """Parse every ``.ttl`` under ``overlays/``, recursively, into one graph (spec 4.2)."""
    root = _root(repo_root)
    return build.union_of(_parse_files(root / OVERLAYS_DIR, "overlay", root).values())


def read_local_shape_files(repo_root: Path | None = None) -> Mapping[str, Graph]:
    """The instance's own shapes, one graph per file, keyed by path from the instance root.

    Per file because a local shape is accepted or refused as a file (spec 6.1.5).
    """
    root = _root(repo_root)
    return _parse_files(root / LOCAL_SHAPES_DIR, "local shape", root)


def read_local_shapes(repo_root: Path | None = None) -> Graph:
    """Every local shape as one graph."""
    return build.union_of(read_local_shape_files(repo_root).values())


def check_additive(files: Mapping[str, Graph]) -> tuple[Issue, ...]:
    """Refuse a local shape that is not additive (spec 3.6, 6.1.5).

    Four refusals: a statement whose subject is a ``sem:`` term or a core shape (naming
    one as an object is fine); a constraint parameter at its no-op value, such as
    ``sh:minCount 0``; a ``sh:rule``; and a reference to a core shape in any position,
    since local shapes are validated as their own graph. Returned as issues, not raised.
    """
    issues: list[Issue] = []
    for name, graph in files.items():
        issues.extend(_not_additive(name, graph))
    return tuple(sorted(set(issues), key=_sort_key))


def shacl(data: Graph, shapes: Graph) -> tuple[Issue, ...]:
    """Validate ``data`` against ``shapes``, as deduplicated, sorted issues.

    ``sh:Violation`` is an error and anything softer a warning (spec 6.1.5); pyshacl's
    ``conforms`` flag is ignored. Raises :class:`ValidationError` for a shapes graph that
    cannot be applied.
    """
    try:
        _, report, _ = _run_shacl(
            data,
            shacl_graph=shapes,
            # The core shapes use a SPARQL target, an advanced feature; without this it matches
            # nothing.
            advanced=True,
            # Nothing reaches the network (spec 6.3).
            do_owl_imports=False,
            inference="none",
            js=False,
        )
    except RecursionError as error:
        # rdflib walks skos:broader+ recursively.
        raise ValidationError(
            [
                Issue(
                    Severity.ERROR,
                    "the skos:broader hierarchy is too deep to check for cycles "
                    "(about a thousand levels); a hierarchy that deep is a defect in the "
                    "source, not a taxonomy",
                )
            ]
        ) from error
    except Exception as error:
        # Broad on purpose: unusable SHACL raises from pyshacl, `re` and pyparsing alike.
        raise ValidationError(
            [Issue(Severity.ERROR, f"cannot be applied as SHACL: {_one_line(error)}")]
        ) from error
    issues = {
        Issue(
            _severity(report, result),
            _message(report, result),
            str(_one(report, result, SH.focusNode)),
        )
        for result in report.subjects(RDF.type, SH.ValidationResult)
    }
    return tuple(sorted(issues, key=lambda issue: issue.sort_key))


def check_shapes(
    repo_root: Path | None = None,
    *,
    base_iri: str,
    generated: Graph | None = None,
    overlays: Graph | None = None,
    local: Mapping[str, Graph] | None = None,
) -> tuple[Issue, ...]:
    """Check 5 of spec 6.1: core shapes, IRI policy, overlays, local shapes.

    Returns every violation and warning, sorted; raises only for a file that cannot be
    read. The graphs may be passed in already parsed, or are read from ``repo_root``.
    A local shape file :func:`check_additive` refuses has its rules left unapplied.
    """
    generated = (
        build.union_of(build.read_previous_files(repo_root).values())
        if generated is None
        else generated
    )
    overlays = read_overlays(repo_root) if overlays is None else overlays
    local = read_local_shape_files(repo_root) if local is None else local

    issues = list(shacl(generated, core_shapes() + instance_shapes(base_iri)))
    if len(overlays):
        issues += shacl(overlays, overlay_shapes(base_iri))

    not_additive = check_additive(local)
    issues += not_additive
    # Only an error refuses a file.
    refused = {issue.location for issue in not_additive if issue.severity is Severity.ERROR}
    issues += _apply_local(generated + overlays, local, refused)
    return tuple(sorted(set(issues), key=lambda issue: issue.sort_key))


def _apply_local(
    data: Graph, files: Mapping[str, Graph], refused: Container[str | None]
) -> tuple[Issue, ...]:
    """Run the local shapes that were not refused, naming a file that cannot be run.

    The union is tried once; only when it fails is each file run alone to find which one
    is responsible, and the files that do load are still validated. Reported as issues.
    """
    applied = {name: graph for name, graph in files.items() if name not in refused}
    union = build.union_of(applied.values())
    if not len(union):
        return ()
    try:
        return shacl(data, union)
    except ValidationError as union_failed:
        issues: list[Issue] = []
        blamed = False
        for name, graph in sorted(applied.items()):
            try:
                issues.extend(shacl(data, graph))
            except ValidationError as error:
                blamed = True
                issues.extend(Issue(issue.severity, issue.message, name) for issue in error.issues)
        if not blamed:
            # Every file loads alone but the union does not; no single file is the answer.
            issues.extend(
                Issue(issue.severity, issue.message, LOCAL_SHAPES_DIR.as_posix())
                for issue in union_failed.issues
            )
        return tuple(issues)


# --------------------------------------------------------------- the check sequence

CHECKS: Sequence[str] = (
    "syntax",
    "manifest integrity",
    "version drift",
    "namespace lock",
    "SHACL",
    "identity",
    "determinism",
    "source configuration",
)
"""The eight checks of spec 6.1, in the order they run and numbered from 1."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckOutcome:
    """What one of the eight checks found."""

    number: int
    name: str
    issues: tuple[Issue, ...] = ()
    skipped: str | None = None
    """Why the check did not run, if it did not. Neither a pass nor a failure; said out loud."""

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(issue for issue in self.issues if issue.severity is not Severity.ERROR)

    @property
    def passed(self) -> bool:
        return not self.errors and self.skipped is None


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Every check's verdict, and whether the instance is committable."""

    outcomes: tuple[CheckOutcome, ...]

    @property
    def issues(self) -> tuple[Issue, ...]:
        return tuple(issue for outcome in self.outcomes for issue in outcome.issues)

    @property
    def errors(self) -> tuple[Issue, ...]:
        return tuple(issue for outcome in self.outcomes for issue in outcome.errors)

    @property
    def warnings(self) -> tuple[Issue, ...]:
        return tuple(issue for outcome in self.outcomes for issue in outcome.warnings)

    @property
    def ok(self) -> bool:
        """Whether the command succeeds. Warnings do not fail it (spec 6.1.5)."""
        return not self.errors

    def summary(self) -> tuple[str, ...]:
        """The result as an operator reads it, every check listed. Not ASCII-only: the lines
        quote labels this project did not write, and :func:`semprini.cli._say` copes."""
        lines: list[str] = []
        for outcome in self.outcomes:
            counted = ", ".join(
                _count(len(found), noun)
                for found, noun in ((outcome.errors, "error"), (outcome.warnings, "warning"))
                if found
            )
            if counted:
                headline = counted
            elif outcome.skipped is not None:
                headline = f"not run ({outcome.skipped})"
            else:
                headline = "ok"
            lines.append(f"{outcome.number}. {outcome.name}: {headline}")
            if counted and outcome.skipped is not None:
                # Check 6 can both find something and be unable to finish.
                lines.append(f"  - not run: {outcome.skipped}")
            # Not sorted again here: an outcome sorts its issues when built, and a second
            # sort would make that untestable through the output.
            lines.extend(f"  - {issue}" for issue in outcome.issues)
        errors, warnings = len(self.errors), len(self.warnings)
        if not errors and not warnings:
            lines.append(f"{len(self.outcomes)} checks passed")
        else:
            lines.append(f"{_count(errors, 'error')}, {_count(warnings, 'warning')}")
        return tuple(lines)


def check(
    settings: InstanceConfig,
    *,
    base: str | None = None,
    compiler: str | None = None,
    ontology: str | None = None,
) -> CheckResult:
    """Run every check of spec 6.1 against the instance ``settings`` describes. Writes nothing.

    ``base`` is the git revision check 6 compares the ID map against; omitted, it is
    discovered. ``compiler`` and ``ontology`` let the fixture builder pin the versions
    (spec 7). Raises only for a configuration or namespace-lock error (exit 2); every
    finding comes back as an :class:`~semprini.model.Issue`.
    """
    root = settings.repo_root
    # Exit 2, not a finding (spec 3.4); done here so every caller gets the whole of check 4.
    verify_namespace_lock(settings)

    content, syntax = _read_content(root)
    outcomes = [_outcome(1, syntax)]

    recorded, manifest_issues = _load_manifest(root)
    outcomes.append(_outcome(2, manifest_issues + (recorded.verify(root) if recorded else ())))
    outcomes.append(
        _outcome(3, recorded.check_versions(compiler=compiler, ontology=ontology))
        if recorded
        else _skipped(3, "the manifest could not be read")
    )

    if syntax:
        # Checks 4-7 ask about parsed content; answering from the files that did load
        # would invent a second problem. Check 8 reads configuration, not RDF.
        unparsed = "the instance's Turtle does not parse (check 1)"
        outcomes.extend(_skipped(number, unparsed) for number in (4, 5, 6, 7))
        outcomes.append(_outcome(8, _check_source_config(settings)))
        return CheckResult(tuple(outcomes))

    generated = build.union_of(content.generated.values())
    outcomes.append(_outcome(4, _check_namespace(generated, settings.base_iri)))
    outcomes.append(
        _outcome(
            5,
            check_shapes(
                root,
                base_iri=settings.base_iri,
                generated=generated,
                overlays=content.overlays,
                local=content.local,
            ),
        )
    )
    outcomes.append(_check_identity(root, generated, settings, base=base))
    running = ontology_version() if ontology is None else ontology
    drifted = recorded is not None and recorded.ontology_version != running
    outcomes.append(
        _outcome(7, _check_determinism(root, content, settings.base_iri, ontology_drifted=drifted))
    )
    outcomes.append(_outcome(8, _check_source_config(settings)))
    return CheckResult(tuple(outcomes))


# ------------------------------------------------------------- the individual checks


@dataclass(frozen=True, slots=True, kw_only=True)
class _Content:
    """Every RDF file of the instance, parsed once. ``generated`` excludes ``ontology.ttl`` (spec
    4.2).
    """

    generated: Mapping[str, Graph]
    ontology: str | None
    """``generated/ontology.ttl`` as committed, or ``None`` if it is absent."""

    overlays: Graph
    local: Mapping[str, Graph]
    """The local shapes per file (spec 6.1.5)."""


def _read_content(root: Path) -> tuple[_Content, tuple[Issue, ...]]:
    """Check 1: parse every ``.ttl`` the instance holds, and keep what parsed (spec 4.2, 4.3)."""
    issues: list[Issue] = []
    generated: Mapping[str, Graph] = {}
    try:
        generated = build.read_previous_files(root)
    except build.BuildError as error:
        issues.extend(error.issues)

    ontology: str | None = None
    ontology_path = root / build.GENERATED_DIR / build.ONTOLOGY_FILE
    try:
        # Untranslated bytes, for check 7.
        ontology = _committed(ontology_path)
        Graph().parse(data=ontology, format="turtle")
    except FileNotFoundError:
        # Check 2 reports a recorded file that is missing.
        ontology = None
    except (OSError, UnicodeDecodeError, SyntaxError) as error:
        ontology = None
        issues.append(Issue(Severity.ERROR, f"cannot read the ontology copy: {error}", "generated"))

    overlays = Graph()
    try:
        overlays = read_overlays(root)
    except ValidationError as error:
        issues.extend(error.issues)

    local: Mapping[str, Graph] = {}
    try:
        local = read_local_shape_files(root)
    except ValidationError as error:
        issues.extend(error.issues)

    content = _Content(generated=generated, ontology=ontology, overlays=overlays, local=local)
    return content, tuple(sorted(set(issues), key=_sort_key))


def _load_manifest(root: Path) -> tuple[Manifest | None, tuple[Issue, ...]]:
    """Check 2, first half: the manifest, or the issues that stop checks 2 and 3 saying more."""
    try:
        return Manifest.load(root), ()
    except ManifestError as error:
        return None, error.issues


def _check_namespace(generated: Graph, base_iri: str) -> tuple[Issue, ...]:
    """Check 4, second half: every generated subject lives under the instance's base IRI.

    The first half is :func:`~semprini.identity.verify_namespace_lock`. Weaker than check
    5's IRI policy, and holds even for a subject no shape targets.
    """
    issues: list[Issue] = []
    for subject in set(generated.subjects()):
        if isinstance(subject, URIRef) and str(subject).startswith(base_iri):
            continue
        issues.append(
            Issue(
                Severity.ERROR,
                f"is a subject of generated/ but does not live under the instance's base "
                f"IRI <{base_iri}>; every IRI the compiler mints does (spec 3.4)",
                str(subject),
            )
        )
    return tuple(sorted(issues, key=_sort_key))


def _check_identity(
    root: Path, generated: Graph, settings: InstanceConfig, *, base: str | None
) -> CheckOutcome:
    """Check 6: the ID map, the merge register, and what ``generated/`` says about both (spec 5.4).
    The map loads without contradiction, every source name is configured, every generated subject
    is mapped, the register names known IRIs, and, when git can supply the base revision, no row
    was removed or edited. Only the last needs git and can report itself not run.
    """
    issues: list[Issue] = []
    try:
        id_map = IdMap.load(root)
    except IdentityError as error:
        return _outcome(6, error.issues)

    issues.extend(id_map.check_sources_are_configured([source.name for source in settings.sources]))
    issues.extend(_check_subjects_are_mapped(generated, id_map))
    try:
        issues.extend(lifecycle.MergeRegister.load(root).check_against(id_map))
    except lifecycle.LifecycleError as error:
        issues.extend(error.issues)

    committed, skipped = _base_id_map(root, base)
    if committed is None:
        # The other questions were answered; this one is recorded as not run.
        return CheckOutcome(
            number=6,
            name=CHECKS[5],
            issues=tuple(sorted(set(issues), key=_sort_key)),
            skipped=skipped,
        )
    issues.extend(id_map.check_append_only(committed))
    return _outcome(6, tuple(issues))


def _check_subjects_are_mapped(generated: Graph, id_map: IdMap) -> tuple[Issue, ...]:
    """Every subject in ``generated/`` is an IRI the ID map holds (spec 5.4)."""
    known = {row.iri for row in id_map}
    return tuple(
        sorted(
            (
                Issue(
                    Severity.ERROR,
                    f"is a subject of generated/ but is in no row of "
                    f"{ID_MAP_PATH.as_posix()}; a row was deleted or a generated file was "
                    f"hand-edited, and the compiler cannot say which source the node came "
                    f"from (spec 5.4)",
                    str(subject),
                )
                for subject in set(generated.subjects())
                if str(subject) not in known
            ),
            key=_sort_key,
        )
    )


def _check_determinism(
    root: Path, content: _Content, base_iri: str, *, ontology_drifted: bool
) -> tuple[Issue, ...]:
    """Check 7: re-serialize what is committed and demand the same bytes (spec 5.5).

    ``ontology.ttl`` is compared against the packaged metamodel instead, and not at all
    when check 3 found the ontology version drifting (spec 4.2).
    """
    issues: list[Issue] = []
    for name, graph in sorted(content.generated.items()):
        location = (build.GENERATED_DIR / name).as_posix()
        try:
            expected = serialize.serialize(graph, base_iri)
        except ValueError as error:
            # A blank node or a literal subject (spec 5.5 rules 2 and 7).
            issues.append(
                Issue(Severity.ERROR, f"cannot be produced by the compiler: {error}", location)
            )
            continue
        if expected != _committed(root / build.GENERATED_DIR / name):
            issues.append(
                Issue(
                    Severity.ERROR,
                    "parses to the right statements but is not the bytes the canonical "
                    "serializer produces; generated/ is written by the compiler and "
                    "reformatted by nothing else (spec 5.5)",
                    location,
                )
            )

    if (
        content.ontology is not None
        and not ontology_drifted
        and content.ontology != ONTOLOGY_PATH.read_text(encoding="utf-8")
    ):
        issues.append(
            Issue(
                Severity.ERROR,
                "is not the metamodel this compiler carries; it is a verbatim copy of "
                "the pinned ontology and is written by nothing else (spec 4.2)",
                (build.GENERATED_DIR / build.ONTOLOGY_FILE).as_posix(),
            )
        )
    return tuple(sorted(issues, key=_sort_key))


def _check_source_config(settings: InstanceConfig) -> tuple[Issue, ...]:
    """Check 8: every configured adapter's ``validate_config()``, each source asked independently
    (spec 5.2, 6.1).

    Ordinary findings, exit 1, not the exit 2 of a configuration error.
    """
    context = settings.run_context(dry_run=True)
    return tuple(issue for source in settings.sources for issue in _asked_of(source, context))


def _asked_of(source: SourceConfig, context: RunContext) -> tuple[Issue, ...]:
    """One source's ``validate_config()``, with every way a plugin can misbehave turned
    into an issue against the source that configured it."""
    try:
        adapter = adapters.create(source, context)
    except adapters.AdapterError as error:
        return (Issue(Severity.ERROR, _one_line(error), source.name),)
    except Exception as error:
        return (
            Issue(
                Severity.ERROR,
                f"adapter {source.adapter!r} could not be constructed: {_one_line(error)}",
                source.name,
            ),
        )

    try:
        reported = adapter.validate_config()
    except Exception as error:
        return (
            Issue(
                Severity.ERROR,
                f"adapter {source.adapter!r} raised while validating its configuration "
                f"instead of reporting: {_one_line(error)}",
                source.name,
            ),
        )

    if not isinstance(reported, list):
        return (_not_issues(source, type(reported).__name__),)
    for item in reported:
        if not isinstance(item, Issue):
            return (_not_issues(source, f"a list holding {type(item).__name__}"),)
    return tuple(
        Issue(issue.severity, issue.message, issue.location or source.name) for issue in reported
    )


def _not_issues(source: SourceConfig, returned: str) -> Issue:
    """One adapter broke the return type of ``validate_config()`` (spec 5.2)."""
    return Issue(
        Severity.ERROR,
        f"adapter {source.adapter!r} returned {returned} from validate_config(), "
        f"which must be a list of issues",
        source.name,
    )


def _committed(path: Path) -> str:
    """A generated file exactly as it is on disk, line endings untranslated (spec 5.5 rule 5)."""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


# --------------------------------------------------------- the base revision, from git

ENVIRONMENT_BASE_REF = "GITHUB_BASE_REF"
"""The pull request's target branch, as GitHub Actions sets it. A default only; ``--base``
is the portable route (spec 6.3)."""


def _base_id_map(root: Path, requested: str | None) -> tuple[IdMap | None, str]:
    """The ID map as the base revision holds it, or ``None`` and the reason there is none.

    A base revision that predates the map yields an empty map, not a failure.
    """
    revision = _base_revision(root, requested)
    if revision is None:
        asked = f"{requested!r}" if requested else f"${ENVIRONMENT_BASE_REF} or origin/HEAD"
        return None, (
            f"no base revision to compare the ID map against ({asked}); pass --base <rev>, "
            f"or fetch enough history for CI to resolve one"
        )

    # git addresses a blob from the repository root, which in a monorepo is not the instance.
    prefix = _git(root, "rev-parse", "--show-prefix")
    path = f"{(prefix or '').strip()}{ID_MAP_PATH.as_posix()}"
    committed = _git_output(root, "show", f"{revision}:{path}")
    if committed is None:
        # Resolvable revision, no ID map in it: the instance did not exist yet there.
        return IdMap(origin=f"{revision}:{path}"), ""
    try:
        return IdMap.loads(committed.decode("utf-8-sig"), origin=f"{revision}:{path}"), ""
    except (IdentityError, UnicodeDecodeError) as error:
        return None, f"the ID map at {revision} could not be read ({error})"


def _base_revision(root: Path, requested: str | None) -> str | None:
    """The merge base with the first resolvable candidate, or ``None``. The merge base, not
    the tip: rows another pull request added since the fork are not this change's."""
    for candidate in _base_candidates(root, requested):
        if _git(root, "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}") is None:
            continue
        merge_base = _git(root, "merge-base", "HEAD", candidate)
        # An unresolvable merge base means unrelated histories, or a HEAD with no commits
        # behind it; the named revision is then the honest thing to compare against.
        return (merge_base or candidate).strip() or candidate
    return None


def _base_candidates(root: Path, requested: str | None) -> Iterable[str]:
    """What to try, most explicit first. Never a guess at ``main`` or ``master``."""
    if requested:
        yield requested
        return
    branch = os.environ.get(ENVIRONMENT_BASE_REF, "").strip()
    if branch:
        yield f"origin/{branch}"
        yield branch
    yield "origin/HEAD"


def _git_output(root: Path, *arguments: str) -> bytes | None:
    """Run git in the instance, returning its raw output, or ``None`` for any failure."""
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None  # git is not installed, or root is not a directory
    if completed.returncode != 0:
        return None
    return completed.stdout


def _git(root: Path, *arguments: str) -> str | None:
    """:func:`_git_output` for the calls whose output is a revision or a path."""
    output = _git_output(root, *arguments)
    return None if output is None else output.decode("utf-8", errors="replace")


# ------------------------------------------------------------------------ internals


def _outcome(number: int, issues: Sequence[Issue]) -> CheckOutcome:
    return CheckOutcome(
        number=number,
        name=CHECKS[number - 1],
        issues=tuple(sorted(set(issues), key=_sort_key)),
    )


def _skipped(number: int, why: str) -> CheckOutcome:
    return CheckOutcome(number=number, name=CHECKS[number - 1], skipped=why)


def _sort_key(issue: Issue) -> tuple[str, str, str]:
    """The order every listing of issues in this module uses (spec 6.1.5)."""
    return issue.sort_key


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _one_line(error: Exception) -> str:
    """A library's message as one line, since an issue becomes one Markdown bullet (spec 6.2)."""
    return " ".join(str(error).split())


_IRI_POLICY_TARGETS: Sequence[tuple[Kind, tuple[URIRef, ...], str]] = (
    (
        Kind.ENTITY,
        (URIRef(f"{SEM}Entity"), URIRef(f"{SEM}Attribute"), URIRef(f"{SEM}BusinessTerm")),
        "an entity, an attribute or a business term",
    ),
    (Kind.RELATIONSHIP, (URIRef(f"{SEM}Relationship"),), "a relationship"),
    (Kind.SCHEME, (SKOS_CONCEPT_SCHEME,), "a scheme"),
    (Kind.TAXONOMY_VALUE, (), "a taxonomy value"),
)
"""Which classes each kind's IRI rule targets, and how its message names them (spec 3.1).
A taxonomy value has no class of its own and arrives through the SPARQL target."""


def _root(repo_root: Path | None) -> Path:
    return Path.cwd() if repo_root is None else Path(repo_root)


def _parse_files(directory: Path, what: str, root: Path) -> Mapping[str, Graph]:
    """Every ``.ttl`` below ``directory``, one graph each, keyed by POSIX path from ``root``.

    An absent directory is no files. Raises :class:`ValidationError` for a file that does not parse.
    """
    if not directory.is_dir():
        return {}
    issues: list[Issue] = []
    files: dict[str, Graph] = {}
    for path in sorted(directory.rglob("*.ttl")):
        name = path.relative_to(root).as_posix()
        try:
            graph = Graph()
            graph.parse(path, format="turtle")
        except (OSError, UnicodeDecodeError, SyntaxError) as error:
            issues.append(Issue(Severity.ERROR, f"cannot read {what}: {error}", str(path)))
        else:
            files[name] = graph
    if issues:
        raise ValidationError(issues)
    return files


# ------------------------------------------------------- what makes a local shape additive

_CORE_NAMESPACES: Sequence[tuple[str, str]] = (
    ("sem", SEM),
    ("shp", SHAPES_NAMESPACE),
)
"""The two namespaces an instance does not own (spec 3.2, 3.3, 3.6), and the prefixes a
message names them by. Whole namespaces, not the terms that exist today."""

_CONSTRAINS_NOTHING: Sequence[tuple[URIRef, Literal, str]] = (
    (SH.minCount, Literal(0), "sh:minCount 0"),
    (SH.uniqueLang, Literal(False), "sh:uniqueLang false"),
    (SH.closed, Literal(False), "sh:closed false"),
)
"""Constraint parameters at the value that makes them a no-op."""


def _not_additive(name: str, graph: Graph) -> Iterable[Issue]:
    """The findings for one local shape file, in the order :func:`check_additive` lists."""
    for subject in sorted(set(graph.subjects()), key=str):
        if isinstance(subject, URIRef) and (core := _core_prefix(str(subject))):
            yield Issue(Severity.ERROR, _owned_by_the_plane(core, subject), name)

    for predicate, value, written in _CONSTRAINS_NOTHING:
        for subject in graph.subjects(predicate, value):
            yield Issue(Severity.ERROR, _relaxes(graph, subject, written), name)

    for subject in set(graph.subjects(SH.rule, None)):
        yield Issue(
            Severity.ERROR,
            f"{_short(subject)} carries a sh:rule, which derives statements the instance "
            f"does not hold: a shape judges the graph and does not write to it, and "
            f"hand-written statements belong in overlays/ (spec 4.2, 6.1.5)",
            name,
        )

    for object_ in sorted({value for value in graph.objects() if _is_core_shape(value)}, key=str):
        yield Issue(
            Severity.ERROR,
            f"references the core shape {_short(object_)}, which is not part of this "
            f"graph: local shapes are validated on their own, so the reference matches "
            f"everything or stops the validator outright, and never means what it reads "
            f"as — state the rule here, over your own terms (spec 6.1.5)",
            name,
        )


def _owned_by_the_plane(prefix: str, subject: URIRef) -> str:
    """Why a statement about a core IRI is refused."""
    if prefix == "sem":
        return (
            f"makes a statement about {_short(subject)}, a metamodel term: an instance "
            f"never redefines, narrows or retargets a core term, because every instance's "
            f"data answers to the same shared vocabulary. A class or property of your own "
            f"belongs in this instance's x: namespace (spec 3.6 rule 2)"
        )
    return (
        f"makes a statement about {_short(subject)}, a core shape: local shapes are "
        f"additive, so they state their own rules under their own IRIs and cannot edit, "
        f"extend or switch off one the compiler ships (spec 6.1.5)"
    )


def _relaxes(graph: Graph, subject: Node, written: str) -> str:
    """Why a no-op constraint is refused, naming the path it was written against.

    ``min`` rather than ``Graph.value``, which picks arbitrarily among several paths.
    """
    path = min(graph.objects(subject, SH.path), key=str, default=None)
    about = f" on {_short(path)}" if isinstance(path, URIRef) else ""
    return (
        f"sets {written}{about}, which constrains nothing: SHACL validation is the sum of "
        f"every shape, so a local file can add a rule but cannot remove one, and the core "
        f"rule applies whatever this file says (spec 6.1.5)"
    )


def _core_prefix(iri: str) -> str | None:
    """``sem`` or ``shp`` if ``iri`` is the plane's, else ``None``."""
    for prefix, namespace in _CORE_NAMESPACES:
        if iri.startswith(namespace):
            return prefix
    return None


def _is_core_shape(value: Node) -> bool:
    return isinstance(value, URIRef) and str(value).startswith(SHAPES_NAMESPACE)


def _short(value: Node) -> str:
    """How a message names a term: a core IRI prefixed, a blank node by what it is, anything else in
    full.
    """
    if isinstance(value, BNode):
        return "an unnamed shape"
    text = str(value)
    for prefix, namespace in _CORE_NAMESPACES:
        if text.startswith(namespace):
            return f"{prefix}:{text[len(namespace) :]}"
    return f"<{text}>"


def _severity(report: Graph, result: Node) -> Severity:
    """``sh:Violation`` is an error; ``sh:Warning`` and ``sh:Info`` are not (spec 6.1.5)."""
    if _one(report, result, SH.resultSeverity) == SH.Violation:
        return Severity.ERROR
    return Severity.WARNING


def _message(report: Graph, result: Node) -> str:
    """Every ``sh:resultMessage``, joined in sorted order."""
    messages = sorted(str(value) for value in report.objects(result, SH.resultMessage))
    return "; ".join(messages) if messages else "constraint violated"


def _one(report: Graph, result: Node, predicate: URIRef) -> Node:
    """The single value SHACL guarantees, chosen deterministically if it is not single."""
    values = sorted(report.objects(result, predicate), key=str)
    if not values:
        raise ValidationError(  # pragma: no cover - SHACL requires both of these
            [Issue(Severity.ERROR, f"validation result carries no {predicate}")]
        )
    return values[0]


def _add_all(graph: Graph, subject: IdentifiedNode, *statements: tuple[URIRef, Node]) -> None:
    for predicate, object_ in statements:
        graph.add((subject, predicate, object_))


def _blank(graph: Graph, *statements: tuple[URIRef, Node]) -> Node:
    """A blank node carrying ``statements``. Fine in a shapes graph, which is never serialized (spec
    5.5).
    """
    node = BNode()
    _add_all(graph, node, *statements)
    return node

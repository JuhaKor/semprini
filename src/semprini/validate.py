"""SHACL and structural checks behind ``semprini check`` (spec 6.1).

This module is ``semprini check``: all seven checks of spec 6.1, in order, and the one
place that decides whether an instance is committable. Every check lives here rather than
in workflow YAML (spec 6.3), so an adopter on GitLab or Azure DevOps ports a config file
instead of reimplementing the checks, and a failure reproduces identically on a laptop
and in CI.

Two properties shape the sequence.

*One run reports everything wrong with the instance.* These are read in CI, where one
problem per round trip is the difference between one fix and five, so every check runs
and every check collects rather than raising at the first violation. The exception is
check 1: content that does not parse cannot be asked any of the questions checks 4 to 7 ask,
so those are reported as not run rather than answered from a graph that is missing files.

*The checks call the modules that own them, and re-derive nothing.* Append-only and
configured sources belong to the ID map, hashes and versions to the manifest, the merge
register to lifecycle, the shapes to this module. A second implementation of any of them
would drift from the one a run enforces, and the way it would drift is the worst
available: ``semprini check`` passing on an instance ``semprini run`` refuses.

The one check that needs something outside the instance is the ID map's append-only
comparison (check 6): "append-only" is a claim about a *change*, so it needs the base
revision, and that comes from git. Everything else answers from the working tree alone.

Three graphs, deliberately kept apart.

*The generated graph* — ``generated/`` without ``ontology.ttl`` — is what the core shapes
judge. It is the compiler's own output, so every rule of spec 6.1.5 applies to it without
exception, and the IRI-policy shapes apply to it alone: a generated subject that is not
under the instance's namespaces is a defect, while an overlay's own ``x:`` term is the
whole point of spec 3.6.

*The overlay graph* — every ``.ttl`` under ``overlays/`` — is judged only on what spec
6.1.5 forbids an overlay to do: restate the label, the status or the scheme membership of
a generated node. The core shapes are **not** applied to it, because ``overlays/external/``
holds curated subsets of standard vocabularies (spec 4.2) whose concepts carry no
``sem:status`` and are nobody's to deprecate. Judging them against the compiler's own
guarantees would report dozens of violations for using overlays exactly as intended.

*Local shapes* — ``shapes/local/`` — are the organization's own rules, and are applied to
the generated and overlay graphs together, which is the data as its stewards see it.
Whether a local shape is additive, and so allowed at all, is task F3's.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pyshacl import validate as _run_shacl
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, SH
from rdflib.term import IdentifiedNode, Node

from semprini import ONTOLOGY_PATH, build, lifecycle, ontology_version, serialize
from semprini.config import SLUG_PATTERN, InstanceConfig
from semprini.identity import (
    ID_MAP_PATH,
    UUID_PATTERN,
    IdentityError,
    IdMap,
    verify_namespace_lock,
)
from semprini.manifest import Manifest, ManifestError
from semprini.model import Issue, IssueError, Kind, Severity

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
    "check_shapes",
    "core_shapes",
    "instance_shapes",
    "overlay_shapes",
    "read_local_shapes",
    "read_overlays",
    "shacl",
]

SHAPES_DIR = Path(__file__).parent / "shapes"
"""The core shapes shipped with the compiler (spec 6.1.5). Every ``.ttl`` in here is
loaded, so splitting the file later costs nothing."""

SHAPES_NAMESPACE = "https://w3id.org/semprini/shapes#"
"""Where the core shapes' own IRIs live.

Not the ``sem:`` namespace: that one resolves to the metamodel document, whose term
inventory is fixed by spec 3.2/3.3, and a shape IRI there would be a term the published
ontology does not declare. ``/semprini/shapes`` is the path the w3id entry already
reserves for them (task A2)."""

OVERLAYS_DIR = Path("overlays")
"""Hand-written RDF — the only kind an instance has (spec 4.2, 4.3)."""

LOCAL_SHAPES_DIR = Path("shapes") / "local"

SEM = serialize.SEM_NAMESPACE
SKOS_CONCEPT_SCHEME = URIRef("http://www.w3.org/2004/02/skos/core#ConceptScheme")
SKOS_IN_SCHEME = URIRef("http://www.w3.org/2004/02/skos/core#inScheme")
SKOS_PREF_LABEL = URIRef("http://www.w3.org/2004/02/skos/core#prefLabel")
SEM_STATUS = URIRef(f"{SEM}status")

TAXONOMY_VALUE_TARGET = URIRef(f"{SHAPES_NAMESPACE}TaxonomyValueTarget")
"""The SPARQL target ``core.ttl`` defines for a plain ``skos:Concept``.

Referenced by the generated IRI-policy shape rather than restated, since a second copy of
that query would be a second answer to "what is a taxonomy value". It is the one reason
:func:`instance_shapes` must be applied together with :func:`core_shapes`."""

LOCAL_NAME_PATTERNS: Mapping[Kind, str] = {
    Kind.ENTITY: UUID_PATTERN,
    Kind.ATTRIBUTE: UUID_PATTERN,
    Kind.RELATIONSHIP: UUID_PATTERN,
    Kind.TAXONOMY_VALUE: UUID_PATTERN,
    Kind.SCHEME: SLUG_PATTERN,
}
"""What a local name looks like, per kind — the other half of spec 3.4.2's minting rules.

Read from the two modules that own the definitions rather than spelled again here: a
scheme takes the slug ``config`` validates, everything else takes a UUID identity mints.
"""

_PROTECTED_OF_A_GENERATED_NODE: Sequence[tuple[URIRef, str]] = (
    (SKOS_PREF_LABEL, "skos:prefLabel"),
    (SEM_STATUS, "sem:status"),
    (SKOS_IN_SCHEME, "skos:inScheme"),
)
"""What an overlay may add statements *about* a generated node but never restate for one
(spec 6.1.5). These three decide what the node is called, whether it is still current,
and which domain it belongs to — the answers the compiler owns."""


class ValidationError(IssueError):
    """Content that cannot be validated at all — CLI exit code 1 (spec 5.1).

    Raised for a file the checks cannot read, never for a constraint a graph fails:
    violations are returned as :class:`~semprini.model.Issue`s, so one run reports every
    problem rather than the first (spec 6.1).
    """

    noun = "validation error"


def core_shapes() -> Graph:
    """The shapes shipped with the compiler (spec 6.1.5).

    Parsed on each call rather than cached: a shared, mutable graph handed to several
    callers is a trap, and the file is small enough that the copy costs less than the
    class of bug it removes.
    """
    graph = Graph()
    for path in sorted(SHAPES_DIR.glob("*.ttl")):
        graph.parse(path, format="turtle")
    return graph


def instance_shapes(base_iri: str) -> Graph:
    """The IRI policy, which only exists once an instance has a base IRI (spec 6.1.5).

    IRIs are opaque and permanent (spec 3.1, 3.4), and these shapes are what says so about
    the output: a generated subject lives under this instance's namespace for its kind,
    and its local name is the UUID or slug spec 3.4.2 mints. A subject that is neither is
    either a hand edit or a compiler defect, and both are things ``generated/`` exists to
    make impossible to commit unnoticed.

    Applied **together with** :func:`core_shapes` — the taxonomy-value shape reuses the
    SPARQL target defined there.
    """
    # Validates the base IRI the same way a run does, so a shapes graph is never built
    # around something that could not have minted the IRIs it is about to judge.
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
    """What an overlay may not say about a generated node (spec 6.1.5).

    Applied to the overlay graph **alone**, which is the only way the question can be
    asked: "this label was written by hand" is a fact about the file a statement came
    from, and their union no longer knows it.

    An overlay adds freely otherwise — that is what overlays are for (spec 4.2) — and may
    say anything at all about its own ``x:`` terms (spec 3.6). Only the three properties
    that decide what a generated node *is* are refused.
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
    """Parse every ``.ttl`` under ``overlays/`` into one graph (spec 4.2).

    Recursive, because overlays are filed by provenance — ``external/``, ``ext/``,
    ``patches/`` — and a steward adding a directory is doing what the layout invites.
    """
    return _parse_tree(_dir(repo_root, OVERLAYS_DIR), "overlay")


def read_local_shapes(repo_root: Path | None = None) -> Graph:
    """Parse the instance's own shapes, which are applied alongside the core ones."""
    return _parse_tree(_dir(repo_root, LOCAL_SHAPES_DIR), "local shape")


def shacl(data: Graph, shapes: Graph) -> tuple[Issue, ...]:
    """Validate ``data`` against ``shapes``, as issues rather than as a report.

    ``sh:Violation`` becomes an error and everything softer a warning, so that the
    missing-definition rule of spec 6.1.5 reports without failing a run. pyshacl's own
    ``conforms`` flag is deliberately ignored: it answers "were there any results at all",
    which would make a warning block a compile.

    Results are deduplicated and sorted. A node reached by two shapes with the same
    message is one problem, and CI output that reorders between runs is output nobody can
    diff.
    """
    try:
        _, report, _ = _run_shacl(
            data,
            shacl_graph=shapes,
            # The core shapes select taxonomy values with a SPARQL target, which is a
            # SHACL advanced feature. Without this, that target matches nothing and the
            # rules built on it pass silently — every constraint they carry would be
            # reported as clean.
            advanced=True,
            # Nothing here reaches the network: no ontology is fetched, no owl:imports is
            # followed. A check that dialled out would fail differently on a laptop and in
            # CI, which is exactly what spec 6.3 promises it cannot do.
            do_owl_imports=False,
            inference="none",
            js=False,
        )
    except RecursionError as error:
        # rdflib walks skos:broader+ recursively, so a chain around a thousand deep
        # exhausts the stack — in the cycle rule, which is the one thing an unreadable
        # traceback here would be hiding. Named instead: the depth is the finding.
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
    local: Graph | None = None,
) -> tuple[Issue, ...]:
    """Check 5 of spec 6.1, end to end: core shapes, IRI policy, overlays, local shapes.

    Returns every violation and warning found, sorted; raises only when a file cannot be
    read. Whether the result fails the command is the caller's decision — warnings do
    not (spec 6.1.5), and :func:`check` owns the exit code.

    The three graphs may be passed in already parsed. :func:`check` does, because it has
    read them for check 1 and four of the seven checks ask questions about the same
    bytes: an instance large enough for check 5 to be slow is one where parsing
    ``generated/`` four more times is felt. Omitted, they are read from ``repo_root`` as
    before, which is what a caller wanting check 5 alone means.
    """
    generated = (
        build.union_of(build.read_previous_files(repo_root).values())
        if generated is None
        else generated
    )
    overlays = read_overlays(repo_root) if overlays is None else overlays
    local = read_local_shapes(repo_root) if local is None else local

    issues = list(shacl(generated, core_shapes() + instance_shapes(base_iri)))
    if len(overlays):
        issues += shacl(overlays, overlay_shapes(base_iri))
    if len(local):
        # The org's own rules see the org's whole graph, generated and hand-written
        # together: a local shape about an x: term would otherwise be unable to see it.
        issues += shacl(generated + overlays, local)
    return tuple(sorted(set(issues), key=lambda issue: issue.sort_key))


# --------------------------------------------------------------- the check sequence

CHECKS: Sequence[str] = (
    "syntax",
    "manifest integrity",
    "version drift",
    "namespace lock",
    "SHACL",
    "identity",
    "determinism",
)
"""The seven checks of spec 6.1, in the order they run and numbered from 1.

Named here rather than in each function so that the sequence is readable in one place and
so that "check 4" means the same thing in this module, in the spec and in what an operator
reads. Order is not arbitrary: check 1 is what makes checks 4 to 7 answerable at all, and the
cheap file-level checks come before the SHACL run, which is the slow one (6.1.5).
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckOutcome:
    """What one of the seven checks found."""

    number: int
    name: str
    issues: tuple[Issue, ...] = ()
    skipped: str | None = None
    """Why the check did not run, if it did not.

    A check that could not be performed is never reported as a check that passed: the two
    are indistinguishable in an exit code, and the whole value of this command is that a
    green run means something. It does not fail the command either — a fresh instance with
    no git history is an ordinary instance, not a broken one — so it is said out loud.
    """

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
        """The result as an operator reads it, one check per section.

        Every check is listed, passing ones included: a check silently dropped from the
        sequence has to be visible as a missing line rather than as one fewer thing
        failing.

        These lines carry text this project did not write — a shape's message quotes the
        node it is about, and a label is whatever a modeller typed — so they cannot be
        kept ASCII the way a run's summary is. Printing them safely on a console that
        cannot encode them is :func:`semprini.cli._say`'s.
        """
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
                # A check can both find something and be unable to finish — check 6
                # answers three questions from the working tree and a fourth only from
                # git. Neither half may hide the other: the findings are what an operator
                # fixes, and the part that did not run is what they would otherwise assume
                # had passed.
                lines.append(f"  - not run: {outcome.skipped}")
            # Printed in the order the outcome holds them, not sorted again here. An
            # outcome sorts its issues when it is built, and a second sort at the render
            # point would make the ordering guarantee untestable through the only output
            # anyone reads — which is how a mutation of the real sort survived this suite.
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
    """Run every check of spec 6.1 against the instance ``settings`` describes.

    Reads the instance and writes nothing: ``semprini check`` is what runs on every pull
    request, so it must be safe to point at a repository it is not allowed to modify, and
    it must reach the same verdict as the run that produced the files.

    ``base`` is the git revision the ID map's append-only rule is judged against (check 6);
    omitted, it is discovered. ``compiler`` and ``ontology`` are injected for the same
    reason a run injects them — the plane's own fixture instance pins the versions its
    committed manifest records — and a production caller passes neither (spec 7).

    Raises only for a configuration or namespace-lock error, which is exit 2 and a
    different category from anything the checks find; everything else comes back as an
    :class:`~semprini.model.Issue`.
    """
    root = settings.repo_root
    # Ahead of check 1, and raising rather than collecting: the lock is frozen
    # configuration (spec 3.4), so a base IRI that disagrees with it is exit 2 and is not
    # a finding about content. The CLI has already done this when loading configuration;
    # done here too, so that any caller of `check` gets the whole of check 4 rather than
    # only the half that reads graphs.
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
        # Checks 4-7 all ask questions about the parsed content, and it did not parse.
        # Answering them from the files that happened to load would report a subject as
        # missing from the ID map because the file naming it is the one that is broken —
        # a second, invented problem on top of the real one.
        unparsed = "the instance's Turtle does not parse (check 1)"
        outcomes.extend(_skipped(number, unparsed) for number in (4, 5, 6, 7))
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
    # Asked of the recorded version rather than read out of check 3's messages: a check
    # that parsed another check's prose would break the day someone reworded it.
    running = ontology_version() if ontology is None else ontology
    drifted = recorded is not None and recorded.ontology_version != running
    outcomes.append(
        _outcome(7, _check_determinism(root, content, settings.base_iri, ontology_drifted=drifted))
    )
    return CheckResult(tuple(outcomes))


# ------------------------------------------------------------- the individual checks


@dataclass(frozen=True, slots=True, kw_only=True)
class _Content:
    """Every RDF file of the instance, parsed once and asked several questions.

    ``generated`` is keyed by file name and excludes ``ontology.ttl``: the determinism
    check compares file against file, and the metamodel copy is the one generated file the
    serializer did not produce (spec 4.2).
    """

    generated: Mapping[str, Graph]
    ontology: str | None
    """``generated/ontology.ttl`` as committed, or ``None`` if it is absent."""

    overlays: Graph
    local: Graph


def _read_content(root: Path) -> tuple[_Content, tuple[Issue, ...]]:
    """Check 1: parse every ``.ttl`` the instance holds, and keep what parsed.

    The three trees are the three kinds of RDF an instance has (spec 4.2): what the
    compiler wrote, what stewards wrote, and the shapes they wrote to judge it by. A
    syntax error in any of them is reported with the file named — including in
    ``generated/``, where it is not a typo but evidence that something other than the
    compiler has written there (spec 4.3).
    """
    issues: list[Issue] = []
    generated: Mapping[str, Graph] = {}
    try:
        generated = build.read_previous_files(root)
    except build.BuildError as error:
        issues.extend(error.issues)

    ontology: str | None = None
    ontology_path = root / build.GENERATED_DIR / build.ONTOLOGY_FILE
    try:
        # Read untranslated: check 7 compares this against what a run would have written,
        # and a copy whose line endings were rewritten is a copy no run produced.
        ontology = _committed(ontology_path)
        Graph().parse(data=ontology, format="turtle")
    except FileNotFoundError:
        # Absent rather than broken: the manifest records it, so check 2 reports it as a
        # recorded file that is missing, which says the actionable thing.
        ontology = None
    except (OSError, UnicodeDecodeError, SyntaxError) as error:
        ontology = None
        issues.append(Issue(Severity.ERROR, f"cannot read the ontology copy: {error}", "generated"))

    overlays, local = Graph(), Graph()
    for reader, target in ((read_overlays, "overlays"), (read_local_shapes, "local")):
        try:
            parsed = reader(root)
        except ValidationError as error:
            issues.extend(error.issues)
        else:
            if target == "overlays":
                overlays = parsed
            else:
                local = parsed

    content = _Content(generated=generated, ontology=ontology, overlays=overlays, local=local)
    return content, tuple(sorted(set(issues), key=_sort_key))


def _load_manifest(root: Path) -> tuple[Manifest | None, tuple[Issue, ...]]:
    """Check 2, first half: the manifest itself has to be readable before it can be used.

    A missing or malformed manifest is returned as issues rather than raised, so that the
    checks that do not depend on it still run and the operator sees the whole picture. It
    does stop checks 2 and 3 from saying anything more: an instance whose manifest cannot
    be parsed has no recorded hashes to compare against and no recorded versions to
    compare with.
    """
    try:
        return Manifest.load(root), ()
    except ManifestError as error:
        return None, error.issues


def _check_namespace(generated: Graph, base_iri: str) -> tuple[Issue, ...]:
    """Check 4, second half: every generated subject lives under the instance's base IRI.

    The first half — that the configured base IRI matches ``mappings/namespace.lock`` — is
    :func:`~semprini.identity.verify_namespace_lock`, and is exit 2 rather than a finding.
    This half is what makes the lock mean anything about content: a lock nothing is
    compared against would let an instance's files drift into a second namespace one
    hand-edited subject at a time.

    Deliberately weaker than check 5's IRI policy, which also demands the namespace of the
    subject's *kind* and the local name spec 3.4.2 mints. Both are in spec 6.1 and both are
    reported: this one holds even for a subject no shape targets, since it asks nothing
    about what the node is.
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
    """Check 6: the ID map, the merge register, and what ``generated/`` says about both.

    Four questions, three of which the working tree answers on its own:

    *Is every row still there, unedited?* Only a comparison with the base revision can
    say, so it is the one check that needs git — and the one that can report itself not
    run.

    *Does the map contradict itself?* A duplicate source ref, or one IRI recorded under
    two kinds, is refused when the file is parsed (spec 5.4), so loading it is the check.

    *Does ``generated/`` hold an IRI the map does not?* That is a deleted row or a hand
    edit, and the compiler could not say which source the node came from (spec 5.4). It is
    checked here without reference to git, so it holds for a local run too.

    *Is every ``source_name`` still configured, and does the merge register name IRIs that
    exist?* The map and the register own both answers; this asks them.
    """
    issues: list[Issue] = []
    try:
        id_map = IdMap.load(root)
    except IdentityError as error:
        # Nothing below can be asked of a map that would not parse, and every one of those
        # questions would answer "no" for the same single reason.
        return _outcome(6, error.issues)

    issues.extend(id_map.check_sources_are_configured([source.name for source in settings.sources]))
    issues.extend(_check_subjects_are_mapped(generated, id_map))
    try:
        issues.extend(lifecycle.MergeRegister.load(root).check_against(id_map))
    except lifecycle.LifecycleError as error:
        issues.extend(error.issues)

    committed, skipped = _base_id_map(root, base)
    if committed is None:
        # Recorded on the check rather than as an issue of its own: the other three
        # questions were answered, and what an operator needs to know is which one was
        # not. It does not fail the command — an instance can legitimately have no base
        # revision, and a check that refused to run in a fresh clone would be a check
        # people learn to skip — but it is never reported as a check that passed.
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
    """Check 7: re-serialize what is committed and demand the same bytes.

    The check that does not trust the manifest. Every other guarantee about ``generated/``
    is recorded in a file the compiler also wrote, so a hand edit that recomputes the hash
    defeats it; this one re-derives the content from the graph and compares. It is what
    makes spec 5.5's determinism auditable by an adopter rather than merely asserted.

    ``ontology.ttl`` is compared against the packaged metamodel instead of re-serialized:
    it is copied verbatim and is deliberately not serializer output (spec 4.2), so
    round-tripping it through the canonical serializer would strip the term comments that
    are the vocabulary's published documentation. The comparison is skipped when check 3
    found the recorded ontology version drifting from the running one — the committed copy
    is then *expected* to differ, and saying so twice adds nothing.

    The committed text is read here rather than carried from check 1, because this is the
    one check whose question is about bytes: everything else asks about statements, and a
    file read for its statements is a file whose bytes nobody looked at.
    """
    issues: list[Issue] = []
    for name, graph in sorted(content.generated.items()):
        location = (build.GENERATED_DIR / name).as_posix()
        try:
            expected = serialize.serialize(graph, base_iri)
        except ValueError as error:
            # A blank node or a literal subject: legal RDF that the canonical serializer
            # refuses (spec 5.5 rules 7 and 2), so no run could have written this file.
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


def _committed(path: Path) -> str:
    """A generated file exactly as it is on disk, newlines included.

    ``newline=""`` so that Python does not translate a CRLF into an LF on the way in: a
    file whose line endings were rewritten — by an editor, or by a ``git`` configured to
    normalize them — parses to precisely the right statements and is precisely not the
    bytes any run wrote (spec 5.5 rule 5). Read with the translation on, this check would
    pass on a file no compiler could produce.
    """
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


# --------------------------------------------------------- the base revision, from git

ENVIRONMENT_BASE_REF = "GITHUB_BASE_REF"
"""The pull request's target branch, as GitHub Actions sets it.

The one platform this project reads an environment variable from, and only as a default:
``--base`` is what an adopter on GitLab or Azure DevOps passes, which is why the check is
portable at all (spec 6.3). Read as a *branch name* and looked up on ``origin``, since a
CI checkout has the base branch as a remote ref rather than a local one.
"""


def _base_id_map(root: Path, requested: str | None) -> tuple[IdMap | None, str]:
    """The ID map as the base revision holds it, for check 6's append-only comparison.

    "Append-only" is a claim about a change rather than about a state, so this is the one
    question in ``semprini check`` the working tree cannot answer. When there is no base
    revision to compare against — no git, no history, no remote — the answer is *no
    answer*, and the check reports itself not run rather than passing quietly.

    A base revision that predates the instance's ID map is not a failure: the map is
    absent there, which is an empty map, which every current map is an append to. That is
    the first pull request of an instance's life, and it must not fail the check that
    exists to protect what it is creating.
    """
    revision = _base_revision(root, requested)
    if revision is None:
        asked = f"{requested!r}" if requested else f"${ENVIRONMENT_BASE_REF} or origin/HEAD"
        return None, (
            f"no base revision to compare the ID map against ({asked}); pass --base <rev>, "
            f"or fetch enough history for CI to resolve one"
        )

    # git addresses a blob from the *repository* root, and an instance is not always one:
    # a monorepo holding several instances is an ordinary layout, and the prefix is what
    # makes `<rev>:mappings/id-map.csv` name this instance's map rather than nothing.
    prefix = _git(root, "rev-parse", "--show-prefix")
    path = f"{(prefix or '').strip()}{ID_MAP_PATH.as_posix()}"
    committed = _git_output(root, "show", f"{revision}:{path}")
    if committed is None:
        # Resolvable revision, no ID map in it: the instance did not exist yet there.
        return IdMap(origin=f"{revision}:{path}"), ""
    try:
        # utf-8-sig for the reason `IdMap.load` uses it: stewards open this file in Excel,
        # which writes a byte-order mark, and the committed revision holds whatever they
        # committed.
        return IdMap.loads(committed.decode("utf-8-sig"), origin=f"{revision}:{path}"), ""
    except (IdentityError, UnicodeDecodeError) as error:
        return None, f"the ID map at {revision} could not be read ({error})"


def _base_revision(root: Path, requested: str | None) -> str | None:
    """Resolve the revision the ID map is compared against, or ``None`` if there is none.

    The merge base rather than the branch tip, and deliberately so: another pull request
    merged into the base branch since this one forked adds rows this branch has never seen,
    and comparing against the tip would report every one of them as a row this change
    deleted. The fork point is the only revision this change is responsible for.
    """
    for candidate in _base_candidates(root, requested):
        if _git(root, "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}") is None:
            continue
        merge_base = _git(root, "merge-base", "HEAD", candidate)
        # An unresolvable merge base means unrelated histories, or a HEAD with no commits
        # behind it; the named revision is then the honest thing to compare against.
        return (merge_base or candidate).strip() or candidate
    return None


def _base_candidates(root: Path, requested: str | None) -> Iterable[str]:
    """What to try, most explicit first.

    Deliberately short, and deliberately without a guess at ``main`` or ``master``. A
    guessed branch that happens to exist would let the check report a comparison it did not
    make — against a branch this change was never proposed for — and the failure mode of a
    check that quietly measures the wrong thing is worse than one that says it measured
    nothing.
    """
    if requested:
        yield requested
        return
    branch = os.environ.get(ENVIRONMENT_BASE_REF, "").strip()
    if branch:
        yield f"origin/{branch}"
        yield branch
    yield "origin/HEAD"


def _git_output(root: Path, *arguments: str) -> bytes | None:
    """Run git in the instance, returning its raw output, or ``None`` if it failed.

    Every failure is one answer — "git cannot tell us" — and they are not distinguishable
    in a way this module would act on differently: git missing, not a repository, an
    unknown revision and a shallow clone all mean the same thing to check 6. What must not
    happen is any of them reaching an operator as a traceback about ``subprocess``.

    Bytes rather than text, because one caller is reading a committed CSV whose encoding
    is the instance's business and not the console's.
    """
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
    """Where every listing of issues in this module sorts from (spec 6.1.5).

    Issues are collected in sets — one problem found by two checks is one problem — so an
    order that ties on any field comes out by string hashing, and CI output that reorders
    between runs is output nobody can diff.
    """
    return issue.sort_key


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


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
"""Which classes each kind's IRI rule targets, and how its message names them.

``Kind.ENTITY`` covers attributes and business terms too: spec 3.1 partitions the IRI
space by kind of *thing*, and all three are concepts minted in ``c:`` — the same reason
``Kind.prefix`` maps them together. A taxonomy value has no class of its own and arrives
through the SPARQL target instead.

The phrase is written out rather than derived from ``Kind``: these messages are what an
operator reads when a run refuses an IRI, and the enum's own spelling would produce "a
entity" and "a taxonomy-value" — and would claim the ``c:`` rule is about entities when it
is equally about the other two.
"""


def _dir(repo_root: Path | None, relative: Path) -> Path:
    return (Path.cwd() if repo_root is None else Path(repo_root)) / relative


def _parse_tree(directory: Path, what: str) -> Graph:
    """Every ``.ttl`` below ``directory``, as one graph.

    An absent directory is an empty graph, not an error: an instance with no overlays and
    no local shapes is an ordinary instance, and spec 4.2's layout is a place to put
    them rather than an obligation to have any.
    """
    graph = Graph()
    if not directory.is_dir():
        return graph
    issues: list[Issue] = []
    for path in sorted(directory.rglob("*.ttl")):
        try:
            graph.parse(path, format="turtle")
        except (OSError, UnicodeDecodeError, SyntaxError) as error:
            # Hand-written RDF is where a syntax error is *likely* (spec 4.2), so it is
            # named and collected rather than left to surface as an rdflib traceback.
            issues.append(Issue(Severity.ERROR, f"cannot read {what}: {error}", str(path)))
    if issues:
        raise ValidationError(issues)
    return graph


def _severity(report: Graph, result: Node) -> Severity:
    """``sh:Violation`` is an error; ``sh:Warning`` and ``sh:Info`` are not (spec 6.1.5)."""
    if _one(report, result, SH.resultSeverity) == SH.Violation:
        return Severity.ERROR
    return Severity.WARNING


def _message(report: Graph, result: Node) -> str:
    """Every ``sh:resultMessage``, joined in a fixed order.

    Sorted rather than taken one at a time: a shape may carry several messages, rdflib
    holds them in a set, and picking "the" message would follow string hashing — the same
    trap the run report hit when choosing among a node's labels.
    """
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
    """A blank node carrying ``statements``.

    Fine here, unlike anywhere else in this project: spec 5.5's no-blank-nodes rule
    governs an instance's generated Turtle, and a shapes graph is neither serialized nor
    committed.
    """
    node = BNode()
    _add_all(graph, node, *statements)
    return node

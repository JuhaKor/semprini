"""SHACL and structural checks behind ``semprini check`` (spec 6.1).

This module owns **check 5**: the core shapes of spec 6.1.5, the instance-specific rules
that can only be written once the base IRI is known, and the run that applies them. Task
F2 puts it in sequence with the other six and maps the result to an exit code; every
check lives here rather than in workflow YAML (spec 6.3), so failures reproduce
identically on a laptop and in CI.

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

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from pyshacl import validate as _run_shacl
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, SH
from rdflib.term import IdentifiedNode, Node

from semprini import build, serialize
from semprini.config import SLUG_PATTERN
from semprini.identity import UUID_PATTERN
from semprini.model import Issue, IssueError, Kind, Severity

__all__ = [
    "LOCAL_NAME_PATTERNS",
    "LOCAL_SHAPES_DIR",
    "OVERLAYS_DIR",
    "SHAPES_DIR",
    "SHAPES_NAMESPACE",
    "ValidationError",
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
    for kind, classes in _IRI_POLICY_TARGETS:
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
                    f"a {kind} is minted as <{namespace}> plus an opaque local name; "
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
    _, report, _ = _run_shacl(
        data,
        shacl_graph=shapes,
        # The core shapes select taxonomy values with a SPARQL target, which is a SHACL
        # advanced feature. Without this, that target matches nothing and the rules built
        # on it pass silently — every constraint they carry would be reported as clean.
        advanced=True,
        # Nothing here reaches the network: no ontology is fetched, no owl:imports is
        # followed. A check that dialled out would fail differently on a laptop and in CI,
        # which is exactly what spec 6.3 promises it cannot do.
        do_owl_imports=False,
        inference="none",
        js=False,
    )
    issues = {
        Issue(
            _severity(report, result),
            _message(report, result),
            str(_one(report, result, SH.focusNode)),
        )
        for result in report.subjects(RDF.type, SH.ValidationResult)
    }
    return tuple(sorted(issues, key=lambda issue: (issue.location or "", issue.message)))


def check_shapes(repo_root: Path | None = None, *, base_iri: str) -> tuple[Issue, ...]:
    """Check 5 of spec 6.1, end to end: core shapes, IRI policy, overlays, local shapes.

    Returns every violation and warning found, sorted; raises only when a file cannot be
    read. Whether the result fails the command is the caller's decision — warnings do
    not (spec 6.1.5), and task F2 owns the exit code.
    """
    generated = build.union_of(build.read_previous_files(repo_root).values())
    overlays = read_overlays(repo_root)
    local = read_local_shapes(repo_root)

    issues = list(shacl(generated, core_shapes() + instance_shapes(base_iri)))
    if len(overlays):
        issues += shacl(overlays, overlay_shapes(base_iri))
    if len(local):
        # The org's own rules see the org's whole graph, generated and hand-written
        # together: a local shape about an x: term would otherwise be unable to see it.
        issues += shacl(generated + overlays, local)
    return tuple(sorted(set(issues), key=lambda issue: (issue.location or "", issue.message)))


# ------------------------------------------------------------------------ internals

_IRI_POLICY_TARGETS: Sequence[tuple[Kind, tuple[URIRef, ...]]] = (
    (
        Kind.ENTITY,
        (URIRef(f"{SEM}Entity"), URIRef(f"{SEM}Attribute"), URIRef(f"{SEM}BusinessTerm")),
    ),
    (Kind.RELATIONSHIP, (URIRef(f"{SEM}Relationship"),)),
    (Kind.SCHEME, (SKOS_CONCEPT_SCHEME,)),
    (Kind.TAXONOMY_VALUE, ()),
)
"""Which classes each kind's IRI rule targets.

``Kind.ENTITY`` covers attributes and business terms too: spec 3.1 partitions the IRI
space by kind of *thing*, and all three are concepts minted in ``c:`` — the same reason
``Kind.prefix`` maps them together. A taxonomy value has no class of its own and arrives
through the SPARQL target instead.
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

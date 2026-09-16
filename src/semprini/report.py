"""``generated/.report.md`` — the reviewer's summary of a run (spec 5.6).

Pasted into the pull request the compile workflow opens (spec 6.2). Everything in it is
derived from the graphs the run produced and the state they replace, never from what an
adapter said it fetched, and it is not rewritten when nothing changed.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import chain

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, SKOS

from semprini import compiler_version, ontology_version
from semprini.build import STATUS_DEPRECATED, OutputFile, statements_by_subject
from semprini.model import RunContext
from semprini.serialize import SEM_NAMESPACE, is_safe_local_name

__all__ = [
    "REPORT_FILE",
    "ClassCount",
    "FileCount",
    "NameClash",
    "NodeRef",
    "RunReport",
    "SourceSummary",
    "create",
    "table",
]

REPORT_FILE = ".report.md"

LISTING_LIMIT = 20
"""How many nodes a listing names before it stops; the count above it is always complete."""

# The classes the builder emits (spec 3.2).
_CLASS_NAMES: Mapping[URIRef, str] = {
    URIRef(f"{SEM_NAMESPACE}Entity"): "sem:Entity",
    URIRef(f"{SEM_NAMESPACE}Attribute"): "sem:Attribute",
    URIRef(f"{SEM_NAMESPACE}Relationship"): "sem:Relationship",
    SKOS.Concept: "skos:Concept",
    SKOS.ConceptScheme: "skos:ConceptScheme",
}

# The classes spec 6.1's missing-definition warning names.
_WANT_DEFINITIONS = (
    URIRef(f"{SEM_NAMESPACE}Entity"),
    URIRef(f"{SEM_NAMESPACE}Attribute"),
    SKOS.Concept,
)

_STATUS = URIRef(f"{SEM_NAMESPACE}status")


@dataclass(frozen=True, slots=True, order=True)
class NodeRef:
    """One node as the report names it: its label, then its shortened IRI as a tie-break."""

    label: str

    iri: str
    """Shortened against the instance's prefixes where possible."""

    def __str__(self) -> str:
        return f"{_inline(self.label)} — `{self.iri}`"


@dataclass(frozen=True, slots=True, order=True)
class ClassCount:
    term: str
    objects: int


@dataclass(frozen=True, slots=True, order=True)
class FileCount:
    name: str
    subjects: int
    """Nodes this file defines, meaning carries a label for (spec 4.2)."""

    triples: int


@dataclass(frozen=True, slots=True, order=True)
class NameClash:
    """Several nodes of one class sharing a label (spec 5.3, 5.6). A warning, not an error."""

    label: str
    term: str
    nodes: tuple[NodeRef, ...]


@dataclass(frozen=True, slots=True)
class SourceSummary:
    """What one configured source contributed (spec 5.6). Supplied by :func:`semprini.run.run`."""

    name: str
    """The source's configured ``name``, as it appears in ``sem:sourceRef`` (spec 5.1)."""

    adapter: str
    objects: int
    note: str = ""
    """Anything the adapter wants a reviewer to know."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RunReport:
    """Everything spec 5.6 requires the report to say, before it is prose."""

    compiler_version: str
    ontology_version: str
    classes: tuple[ClassCount, ...] = ()
    files: tuple[FileCount, ...] = ()
    new: tuple[NodeRef, ...] = ()
    changed: tuple[NodeRef, ...] = ()
    """Nodes this run says something different about, excluding the ones it deprecated,
    so that the three categories partition the nodes (spec 5.6)."""

    deprecated: tuple[NodeRef, ...] = ()
    """Nodes this run moved to ``sem:status "deprecated"`` (spec 3.5), read from the graphs."""

    missing_definitions: tuple[NodeRef, ...] = ()
    name_clashes: tuple[NameClash, ...] = ()
    sources: tuple[SourceSummary, ...] = ()

    @property
    def warnings(self) -> int:
        """How many warnings the run raised."""
        return len(self.missing_definitions) + len(self.name_clashes)

    def render(self) -> str:
        """The report as Markdown, ending in exactly one newline. No timestamps (spec 5.5)."""
        return "\n".join(chain.from_iterable(self._sections())).rstrip("\n") + "\n"

    def to_file(self) -> OutputFile:
        """The report as one of the run's output files."""
        return OutputFile(name=REPORT_FILE, text=self.render())

    # ------------------------------------------------------------------ rendering

    def _sections(self) -> Iterator[list[str]]:
        yield [
            "# Compile report",
            "",
            f"Compiler **{self.compiler_version}** · ontology **{self.ontology_version}**.",
            "",
        ]
        yield self._contents()
        yield self._changes()
        yield self._warnings()
        yield self._sources()

    def _contents(self) -> list[str]:
        lines = ["## Contents", ""]
        lines += table(
            ("Class", "Objects"),
            [(count.term, str(count.objects)) for count in self.classes],
            empty="This run compiled nothing.",
        )
        lines += [""]
        lines += table(
            ("File", "Nodes", "Triples"),
            [(f"`{c.name}`", str(c.subjects), str(c.triples)) for c in self.files],
            empty="No files were written.",
        )
        lines += [
            "",
            "`ontology.ttl` is a verbatim copy of the pinned metamodel and is not counted above.",
            "",
        ]
        return lines

    def _changes(self) -> list[str]:
        lines = ["## Changes", ""]
        lines += table(
            ("Change", "Nodes"),
            [
                ("New", str(len(self.new))),
                ("Changed", str(len(self.changed))),
                ("Deprecated", str(len(self.deprecated))),
            ],
        )
        lines += [""]
        if not (self.new or self.changed or self.deprecated):
            lines += ["Nothing changed: this run reproduced the committed output.", ""]
            return lines
        for title, nodes in (
            ("New", self.new),
            ("Changed", self.changed),
            ("Deprecated", self.deprecated),
        ):
            if nodes:
                lines += _listing(f"### {title}", nodes)
        return lines

    def _warnings(self) -> list[str]:
        lines = ["## Warnings", ""]
        if not self.warnings:
            lines += ["None.", ""]
            return lines
        if self.missing_definitions:
            lines += _listing(
                "### Missing definitions",
                self.missing_definitions,
                note=(
                    "Reported, not blocking, in v1 — an instance switches this to blocking "
                    "when its steward workflows are ready (spec 6.1)."
                ),
            )
        if self.name_clashes:
            lines += [
                f"### Same name, different IRI ({len(self.name_clashes)})",
                "",
                "One label, several objects. Each is a distinct object to every source "
                "that reported it; only a steward can say whether they are the same "
                "thing.",
                "",
            ]
            lines += [
                f"- **{_inline(clash.label)}** ({clash.term}) — "
                + ", ".join(f"`{node.iri}`" for node in clash.nodes)
                for clash in self.name_clashes[:LISTING_LIMIT]
            ]
            lines += _more(len(self.name_clashes))
            lines += [""]
        return lines

    def _sources(self) -> list[str]:
        lines = ["## Sources", ""]
        lines += table(
            ("Source", "Adapter", "Objects", "Notes"),
            [(s.name, f"`{s.adapter}`", str(s.objects), s.note) for s in self.sources],
            empty="No per-source summary was recorded.",
        )
        lines += [""]
        return lines


def _listing(heading: str, nodes: Sequence[NodeRef], *, note: str = "") -> list[str]:
    lines = [f"{heading} ({len(nodes)})", ""]
    if note:
        lines += [note, ""]
    lines += [f"- {node}" for node in nodes[:LISTING_LIMIT]]
    lines += _more(len(nodes))
    lines += [""]
    return lines


def _more(total: int) -> list[str]:
    if total <= LISTING_LIMIT:
        return []
    return ["", f"…and {total - LISTING_LIMIT} more."]


def table(header: Sequence[str], rows: Sequence[Sequence[str]], *, empty: str = "") -> list[str]:
    """One Markdown table, every cell escaped. Shared with the migration report (spec 7)."""
    if not rows and empty:
        return [empty]
    return [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
        *("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows),
    ]


def _inline(text: str) -> str:
    """Free text as one line of Markdown: a newline in a label would end its bullet list."""
    return " ".join(text.split())


def _cell(text: str) -> str:
    """Free text inside a table cell, where a bare ``|`` would end the column."""
    return _inline(text).replace("|", "\\|")


# --------------------------------------------------------------------------- derivation


def create(
    files: Sequence[OutputFile],
    *,
    context: RunContext,
    previous: Graph | None = None,
    sources: Sequence[SourceSummary] = (),
    compiler: str | None = None,
    ontology: str | None = None,
) -> RunReport:
    """Derive the report from what a run produced (spec 5.6).

    ``files`` are the run's output files and ``previous`` the state they replace, the
    same graph the builder dated against. ``sources`` is supplied by the run.
    ``compiler`` and ``ontology`` let a test pin the versions.
    """
    graphs = {file.name: file.graph for file in files if file.graph is not None}
    union = Graph()
    for graph in graphs.values():
        union += graph
    prefixes = context.namespaces

    labels = _labels(union)
    types = _types(union, labels)
    deprecated = frozenset(_deprecated(union, previous))

    return RunReport(
        compiler_version=compiler_version() if compiler is None else compiler,
        ontology_version=ontology_version() if ontology is None else ontology,
        classes=_classes(types),
        files=tuple(
            sorted(
                FileCount(
                    name=name,
                    subjects=len(set(g.subjects(SKOS.prefLabel))),
                    triples=len(g),
                )
                for name, g in graphs.items()
            )
        ),
        new=_nodes(_new(union, previous), labels, prefixes),
        changed=_nodes(
            (subject for subject in _changed(union, previous) if subject not in deprecated),
            labels,
            prefixes,
        ),
        deprecated=_nodes(deprecated, labels, prefixes),
        missing_definitions=_nodes(_undefined(union, types), labels, prefixes),
        name_clashes=_clashes(labels, types, prefixes),
        sources=tuple(sources),
    )


def _labels(graph: Graph) -> Mapping[URIRef, str]:
    """Every node the run defines (carries a ``skos:prefLabel`` for), with its report label (spec
    4.2).
    """
    labels: dict[URIRef, str] = {}
    for subject, object_ in graph.subject_objects(SKOS.prefLabel):
        if not isinstance(subject, URIRef):  # pragma: no cover - the serializer refuses these
            continue
        # min(), not the first rdflib yields: iteration order must not reach the report.
        labels[subject] = min(str(object_), labels.get(subject, str(object_)))
    return labels


def _types(graph: Graph, labels: Mapping[URIRef, str]) -> Mapping[URIRef, URIRef]:
    """The one class each node is counted as; ``min`` over its types, for determinism."""
    types: dict[URIRef, URIRef] = {}
    for subject in labels:
        for object_ in graph.objects(subject, RDF.type):
            if isinstance(object_, URIRef):
                types[subject] = min(object_, types.get(subject, object_))
    return types


def _classes(types: Mapping[URIRef, URIRef]) -> tuple[ClassCount, ...]:
    counts = {term: 0 for term in _CLASS_NAMES.values()}
    for term in types.values():
        name = _CLASS_NAMES.get(term, str(term))
        counts[name] = counts.get(name, 0) + 1
    # Every class is listed even at zero.
    return tuple(ClassCount(term=term, objects=count) for term, count in sorted(counts.items()))


def _new(current: Graph, previous: Graph | None) -> Iterable[URIRef]:
    before = statements_by_subject(previous) if previous is not None else {}
    return (subject for subject in statements_by_subject(current) if subject not in before)


def _changed(current: Graph, previous: Graph | None) -> Iterable[URIRef]:
    """Nodes this run says something different about, by the same rule that dates them."""
    if previous is None:
        return ()
    before = statements_by_subject(previous)
    return (
        subject
        for subject, statements in statements_by_subject(current).items()
        if subject in before and before[subject] != statements
    )


def _deprecated(current: Graph, previous: Graph | None) -> Iterable[URIRef]:
    """Nodes newly marked deprecated by this run (spec 3.5)."""
    if previous is None:
        return ()
    before = frozenset(_deprecations(previous))
    return (subject for subject in _deprecations(current) if subject not in before)


def _deprecations(graph: Graph) -> Iterable[URIRef]:
    return (
        subject
        for subject in graph.subjects(_STATUS, Literal(STATUS_DEPRECATED))
        if isinstance(subject, URIRef)
    )


def _undefined(graph: Graph, types: Mapping[URIRef, URIRef]) -> Iterable[URIRef]:
    return (
        subject
        for subject, term in types.items()
        if term in _WANT_DEFINITIONS and (subject, SKOS.definition, None) not in graph
    )


def _clashes(
    labels: Mapping[URIRef, str],
    types: Mapping[URIRef, URIRef],
    prefixes: Mapping[str, str],
) -> tuple[NameClash, ...]:
    """Nodes of one class whose labels differ only by case, if at all."""
    groups: dict[tuple[URIRef, str], list[URIRef]] = {}
    for subject, label in labels.items():
        term = types.get(subject)
        if term is None:  # pragma: no cover - the builder types every node it defines
            continue
        groups.setdefault((term, label.casefold()), []).append(subject)
    return tuple(
        sorted(
            NameClash(
                label=min(labels[subject] for subject in subjects),
                term=_CLASS_NAMES.get(term, str(term)),
                nodes=_nodes(subjects, labels, prefixes),
            )
            for (term, _), subjects in groups.items()
            if len(subjects) > 1
        )
    )


def _nodes(
    subjects: Iterable[URIRef],
    labels: Mapping[URIRef, str],
    prefixes: Mapping[str, str],
) -> tuple[NodeRef, ...]:
    return tuple(
        sorted(
            NodeRef(iri=_short(str(subject), prefixes), label=labels.get(subject, ""))
            for subject in subjects
        )
    )


def _short(iri: str, prefixes: Mapping[str, str]) -> str:
    """``https://…/concepts/7f3a…`` as ``c:7f3a…`` where the prefixes allow it. Display only."""
    for prefix, namespace in sorted(prefixes.items(), key=lambda item: -len(item[1])):
        if iri.startswith(namespace):
            local = iri[len(namespace) :]
            if is_safe_local_name(local):
                return f"{prefix}:{local}"
    return iri

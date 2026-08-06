"""``generated/.report.md`` — the reviewer's summary of a run (spec 5.6).

The compile workflow pastes this file into the pull request it opens (spec 6.2), so it is
the only part of a compile most people will ever read. Everything here is written for
that reader: someone deciding whether a diff of a few hundred Turtle lines is the change
they expected.

Two rules keep it honest.

*It says only what the output says.* Counts, new and changed nodes and the warning
categories are all derived from the graphs the run produced and the state it replaced —
never from what an adapter believed it fetched. A report that could disagree with the
files beside it would be worse than no report.

*It is not rewritten when nothing changed.* A run that produces byte-identical output
leaves this file alone. Written unconditionally, a no-op compile would rewrite "12 new"
to "0 new" and open a pull request containing nothing else — which is exactly the empty
diff the whole design exists to avoid (spec 1.2, 4.3). The report next to a set of
generated files is therefore always the report of the run that produced them, which is
also what a reviewer wants it to be.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import chain

from rdflib import Graph, URIRef
from rdflib.namespace import RDF, SKOS

from semprini import compiler_version, ontology_version
from semprini.build import OutputFile, statements_by_subject
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
]

REPORT_FILE = ".report.md"

LISTING_LIMIT = 20
"""How many nodes a listing names before it stops counting them out.

A cap rather than a complete list because the report's destination is a pull request
description: a first compile of a large instance would otherwise paste thousands of lines
into it and bury the counts that matter. The count above each listing is always complete.
"""

# The classes the builder emits (spec 3.2), in the order a reader thinks about them:
# the schemes an instance is organized into, then what is in them.
_CLASS_NAMES: Mapping[URIRef, str] = {
    URIRef(f"{SEM_NAMESPACE}Entity"): "sem:Entity",
    URIRef(f"{SEM_NAMESPACE}Attribute"): "sem:Attribute",
    URIRef(f"{SEM_NAMESPACE}Relationship"): "sem:Relationship",
    SKOS.Concept: "skos:Concept",
    SKOS.ConceptScheme: "skos:ConceptScheme",
}

# Missing definitions are reported for exactly the classes spec 6.1's warning names —
# entities, attributes and taxonomy concepts. A relationship's label is its verb and a
# scheme's is its title; neither is a term a steward is expected to define.
_WANT_DEFINITIONS = (
    URIRef(f"{SEM_NAMESPACE}Entity"),
    URIRef(f"{SEM_NAMESPACE}Attribute"),
    SKOS.Concept,
)


@dataclass(frozen=True, slots=True, order=True)
class NodeRef:
    """One node as the report names it: its label, and its IRI shortened.

    Ordered by label first, because that is the column a reader scans; the IRI breaks
    ties, so two nodes sharing a label still have one fixed order (spec 5.5's determinism
    applies to this file too).
    """

    label: str

    iri: str
    """Shortened against the instance's prefixes where possible — ``c:7f3a…`` rather than
    the full IRI, because a reviewer reads this in a pull request and the prefixed form is
    the one that also appears in the Turtle beside it."""

    def __str__(self) -> str:
        return f"{self.label} — `{self.iri}`"


@dataclass(frozen=True, slots=True, order=True)
class ClassCount:
    term: str
    objects: int


@dataclass(frozen=True, slots=True, order=True)
class FileCount:
    name: str
    subjects: int
    """Nodes this file *defines* — the ones it carries a label for. A file may mention a
    node it does not define; the ``sem:relatesTo`` shortcut does (spec 4.2)."""

    triples: int


@dataclass(frozen=True, slots=True, order=True)
class NameClash:
    """Several nodes of one class sharing a label (spec 5.3, 5.6).

    Not an error: two source systems legitimately call two different things "Account". It
    is reported because it is the one ambiguity a reviewer can resolve and the compiler
    cannot — identity comes from source keys, so two same-named objects stay two objects
    however obvious the duplication looks to a human.
    """

    label: str
    term: str
    nodes: tuple[NodeRef, ...]


@dataclass(frozen=True, slots=True)
class SourceSummary:
    """What one configured source contributed (spec 5.6).

    Supplied by the caller rather than derived here: only the run knows which adapters it
    invoked and what they said. **E2** fills these in as it fetches.
    """

    name: str
    """The source's configured ``name``, as it appears in ``sem:sourceRef`` (spec 5.1)."""

    adapter: str
    objects: int
    note: str = ""
    """Anything the adapter wants a reviewer to know: models fetched, rows read, a
    deprecation warning from the source system."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RunReport:
    """Everything spec 5.6 requires the report to say, before it is prose."""

    compiler_version: str
    ontology_version: str
    classes: tuple[ClassCount, ...] = ()
    files: tuple[FileCount, ...] = ()
    new: tuple[NodeRef, ...] = ()
    changed: tuple[NodeRef, ...] = ()
    deprecated: tuple[NodeRef, ...] = ()
    """Nodes this run deprecated (spec 3.5). Supplied by the caller: deprecation is
    evaluated against the union of all configured sources, which is **E1**'s, not
    something the emitted graphs reveal."""

    missing_definitions: tuple[NodeRef, ...] = ()
    name_clashes: tuple[NameClash, ...] = ()
    sources: tuple[SourceSummary, ...] = ()

    @property
    def warnings(self) -> int:
        """How many warnings the run raised — what a reviewer scans for first."""
        return len(self.missing_definitions) + len(self.name_clashes)

    def render(self) -> str:
        """The report as Markdown, ending in exactly one newline.

        Deterministic in the same sense the Turtle is (spec 5.5): no timestamps, no run
        identifiers, nothing that varies between two runs of one input.
        """
        return "\n".join(chain.from_iterable(self._sections())).rstrip("\n") + "\n"

    def to_file(self) -> OutputFile:
        """The report as one of the run's output files, written by the same writer as the
        Turtle so that nothing can disagree about encoding or line endings."""
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
        lines += _table(
            ("Class", "Objects"),
            [(count.term, str(count.objects)) for count in self.classes],
            empty="This run compiled nothing.",
        )
        lines += [""]
        lines += _table(
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
        lines += _table(
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
                f"- **{clash.label}** ({clash.term}) — "
                + ", ".join(f"`{node.iri}`" for node in clash.nodes)
                for clash in self.name_clashes[:LISTING_LIMIT]
            ]
            lines += _more(len(self.name_clashes))
            lines += [""]
        return lines

    def _sources(self) -> list[str]:
        lines = ["## Sources", ""]
        lines += _table(
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


def _table(header: Sequence[str], rows: Sequence[Sequence[str]], *, empty: str = "") -> list[str]:
    if not rows and empty:
        return [empty]
    return [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
        *("| " + " | ".join(row) + " |" for row in rows),
    ]


# --------------------------------------------------------------------------- derivation


def create(
    files: Sequence[OutputFile],
    *,
    context: RunContext,
    previous: Graph | None = None,
    sources: Sequence[SourceSummary] = (),
    deprecated: Sequence[NodeRef] = (),
    compiler: str | None = None,
    ontology: str | None = None,
) -> RunReport:
    """Derive the report from what a run produced (spec 5.6).

    ``files`` are the run's output files as :func:`semprini.build.build` returned them,
    and ``previous`` the state they replace — the same graph the builder used to carry
    ``dcterms:modified`` forward, so that "changed" in the report and a refreshed date in
    the Turtle can never tell different stories.

    ``sources`` and ``deprecated`` are supplied rather than derived: neither the fetch
    summary nor deprecation is visible in the emitted graphs. ``compiler`` and ``ontology``
    are injected only so that a test can pin them.
    """
    graphs = {file.name: file.graph for file in files if file.graph is not None}
    union = Graph()
    for graph in graphs.values():
        union += graph
    prefixes = context.namespaces

    labels = _labels(union)
    types = dict(_types(union, labels))

    return RunReport(
        compiler_version=compiler_version() if compiler is None else compiler,
        ontology_version=ontology_version() if ontology is None else ontology,
        classes=_classes(types),
        files=tuple(
            sorted(
                FileCount(
                    name=name,
                    subjects=sum(1 for subject in labels if (subject, SKOS.prefLabel, None) in g),
                    triples=len(g),
                )
                for name, g in graphs.items()
            )
        ),
        new=_nodes(_new(union, previous), labels, prefixes),
        changed=_nodes(_changed(union, previous), labels, prefixes),
        deprecated=tuple(sorted(deprecated)),
        missing_definitions=_nodes(_undefined(union, types), labels, prefixes),
        name_clashes=_clashes(labels, types, prefixes),
        sources=tuple(sources),
    )


def _labels(graph: Graph) -> Mapping[URIRef, str]:
    """Every node the run *defines*, with the label the report calls it by.

    Carrying a ``skos:prefLabel`` is what defines a node: a file may state something about
    a node it does not define — the ``sem:relatesTo`` shortcut does (spec 4.2) — and the
    report counts a node once, where it lives.
    """
    labels: dict[URIRef, str] = {}
    for subject, object_ in graph.subject_objects(SKOS.prefLabel):
        if not isinstance(subject, URIRef):  # pragma: no cover - the serializer refuses these
            continue
        # Sorted rather than "the first one rdflib yields": a node with labels in several
        # languages must not have its report entry decided by iteration order.
        labels[subject] = min(str(object_), labels.get(subject, str(object_)))
    return labels


def _types(graph: Graph, labels: Mapping[URIRef, str]) -> Iterator[tuple[URIRef, URIRef]]:
    for subject in labels:
        for object_ in graph.objects(subject, RDF.type):
            if isinstance(object_, URIRef):
                yield subject, object_


def _classes(types: Mapping[URIRef, URIRef]) -> tuple[ClassCount, ...]:
    counts = {term: 0 for term in _CLASS_NAMES.values()}
    for term in types.values():
        name = _CLASS_NAMES.get(term, str(term))
        counts[name] = counts.get(name, 0) + 1
    # Every class the metamodel defines is listed even at zero: "0 relationships" is
    # information — it says the run found none, not that the report forgot to look.
    return tuple(ClassCount(term=term, objects=count) for term, count in sorted(counts.items()))


def _new(current: Graph, previous: Graph | None) -> Iterable[URIRef]:
    before = statements_by_subject(previous) if previous is not None else {}
    return (subject for subject in statements_by_subject(current) if subject not in before)


def _changed(current: Graph, previous: Graph | None) -> Iterable[URIRef]:
    """Nodes this run says something different about than the committed output does.

    Compared through :func:`semprini.build.statements_by_subject`, which is also what
    decides whether ``dcterms:modified`` is carried forward — one definition of "changed",
    so the report and the dates in the Turtle cannot disagree.
    """
    if previous is None:
        return ()
    before = statements_by_subject(previous)
    return (
        subject
        for subject, statements in statements_by_subject(current).items()
        if subject in before and before[subject] != statements
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
    """Nodes of one class whose labels differ only by case, if at all.

    Compared case-insensitively because "Customer" and "customer" are the same ambiguity
    to the steward who has to resolve them, and within one class because a taxonomy value
    sharing a name with the entity it classifies is ordinary rather than suspicious.
    """
    groups: dict[tuple[URIRef, str], list[URIRef]] = {}
    for subject, label in labels.items():
        term = types.get(subject)
        if term is None:  # pragma: no cover - the builder types every node it defines
            continue
        groups.setdefault((term, label.casefold()), []).append(subject)
    return tuple(
        sorted(
            NameClash(
                # The labels differ only in case, so any of them names the group; the
                # smallest is chosen rather than an arbitrary one.
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
    """``https://…/concepts/7f3a…`` as ``c:7f3a…`` where the prefixes allow it.

    Display only, and deliberately separate from the serializer's own abbreviation (spec
    5.5): that one decides what parses, this one decides what reads well in a pull
    request. It leans on the same safe-local-name rule so the two cannot claim a term is
    abbreviable when the other would not write it that way.
    """
    for prefix, namespace in sorted(prefixes.items(), key=lambda item: -len(item[1])):
        if iri.startswith(namespace):
            local = iri[len(namespace) :]
            if is_safe_local_name(local):
                return f"{prefix}:{local}"
    return iri

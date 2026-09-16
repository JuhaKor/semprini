"""Internal model → the graphs that become ``generated/`` (spec 3.2, 3.3, 4.2).

Chooses statements and files, nothing else: IRIs come from the registry (spec 5.4) and
bytes from the canonical serializer (spec 5.5). Output is partitioned by scheme, every
triple is written in exactly one file (spec 4.2), and ``dcterms:modified`` is carried
forward unless a node's other statements changed (spec 3.3).
"""

from __future__ import annotations

import datetime
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF, SKOS, XSD
from rdflib.term import Node

from semprini import ONTOLOGY_PATH, serialize
from semprini.config import is_slug
from semprini.identity import IdentityError, Registry
from semprini.model import (
    Attribute,
    Entity,
    InternalModel,
    Issue,
    Kind,
    Relationship,
    RunContext,
    Scheme,
    SchemeMember,
    SchemeType,
    SemanticObject,
    Severity,
    SourceRef,
    TaxonomyValue,
    Text,
)

__all__ = [
    "GENERATED_DIR",
    "ONTOLOGY_FILE",
    "STATUS_ACTIVE",
    "STATUS_DEPRECATED",
    "BuildError",
    "CarriedNode",
    "OutputFile",
    "build",
    "ontology_file",
    "read_previous",
    "read_previous_files",
    "remove",
    "stale",
    "statements_by_subject",
    "unchanged",
    "union_of",
    "write_all",
]

GENERATED_DIR = Path("generated")
"""Machine-owned, overwritten wholesale on every run (spec 4.3)."""

ONTOLOGY_FILE = "ontology.ttl"
"""A verbatim copy of the pinned metamodel (spec 4.2)."""

SEM = serialize.SEM_NAMESPACE

# The metamodel terms this module emits (spec 3.3).
SEM_ATTRIBUTE_OF = URIRef(f"{SEM}attributeOf")
SEM_ENUMERATES = URIRef(f"{SEM}enumerates")
SEM_RELATES_TO = URIRef(f"{SEM}relatesTo")
SEM_SCHEME_TYPE = URIRef(f"{SEM}schemeType")
SEM_SOURCE = URIRef(f"{SEM}source")
SEM_SOURCE_REF = URIRef(f"{SEM}sourceRef")
SEM_STATUS = URIRef(f"{SEM}status")
SEM_TARGET = URIRef(f"{SEM}target")

SEM_ENTITY = URIRef(f"{SEM}Entity")
SEM_ATTRIBUTE = URIRef(f"{SEM}Attribute")
SEM_RELATIONSHIP = URIRef(f"{SEM}Relationship")

STATUS_ACTIVE = "active"
"""The status of every node built from the model. Deprecation is :mod:`semprini.lifecycle`'s
decision and arrives as :class:`CarriedNode`s (spec 3.5, 5.4)."""

STATUS_DEPRECATED = "deprecated"
"""The status lifecycle gives a node no source reports any more (spec 3.5)."""

_CLASSES: Mapping[type[SemanticObject], URIRef] = {
    Entity: SEM_ENTITY,
    Attribute: SEM_ATTRIBUTE,
    Relationship: SEM_RELATIONSHIP,
    TaxonomyValue: SKOS.Concept,
    Scheme: SKOS.ConceptScheme,
}


class BuildError(IdentityError):
    """The model cannot be expressed as RDF — CLI exit code 1 (spec 5.1)."""

    noun = "build error"


@dataclass(frozen=True, slots=True)
class OutputFile:
    """One file of ``generated/``, rendered to its exact bytes but not yet written (spec 5.1, 6.1
    check 7).
    """

    name: str
    text: str
    graph: Graph | None = None
    """The graph ``text`` was serialized from; ``None`` for the verbatim ontology copy."""

    @property
    def path(self) -> Path:
        return GENERATED_DIR / self.name


@dataclass(frozen=True, slots=True, kw_only=True)
class CarriedNode:
    """One node's statements as the previous run wrote them, re-emitted (spec 3.5).

    Produced by :func:`semprini.lifecycle.plan`, which makes every judgement; this stage
    only writes them.
    """

    file: str
    """The ``generated/`` file that held these statements; a deprecated node stays put."""

    subject: URIRef
    statements: frozenset[tuple[URIRef, Node]]
    """Without ``dcterms:modified``, which is recomputed like every other node's (spec 3.3)."""

    defines: bool
    """Whether this block describes the node, carrying its label; only that block is dated (spec
    4.2).
    """


def build(
    model: InternalModel,
    *,
    registry: Registry,
    context: RunContext,
    previous: Graph | None = None,
    today: datetime.date | None = None,
    carried: Sequence[CarriedNode] = (),
) -> tuple[OutputFile, ...]:
    """Turn a resolved model into the files ``generated/`` should hold (spec 4.2).

    ``previous`` is the union of the current generated graphs, used to carry
    ``dcterms:modified`` forward (spec 3.3); ``None`` on a first compile. ``today`` is the
    only clock. ``carried`` are the nodes lifecycle retained (spec 3.5), written and dated
    by the same rules. Raises :class:`BuildError` with every problem found.
    """
    builder = _Builder(
        model=model,
        registry=registry,
        context=context,
        previous=_Previous(previous),
        today=datetime.date.today() if today is None else today,
        carried=tuple(carried),
    )
    return builder.build()


def read_previous_files(repo_root: Path | None = None) -> Mapping[str, Graph]:
    """Parse each generated Turtle file into its own graph, keyed by file name (spec 3.5).

    ``ontology.ttl`` is skipped. Raises :class:`BuildError` for a file that does not parse.
    """
    root = Path.cwd() if repo_root is None else Path(repo_root)
    directory = root / GENERATED_DIR
    graphs: dict[str, Graph] = {}
    if not directory.is_dir():
        return graphs
    issues: list[Issue] = []
    for path in sorted(directory.glob("*.ttl")):
        if path.name == ONTOLOGY_FILE:
            continue
        graph = Graph()
        try:
            graph.parse(path, format="turtle")
        except (OSError, UnicodeDecodeError, SyntaxError) as error:
            # rdflib's BadSyntax subclasses SyntaxError.
            issues.append(
                Issue(Severity.ERROR, f"cannot read generated output: {error}", str(path))
            )
            continue
        graphs[path.name] = graph
    if issues:
        raise BuildError(issues)
    return graphs


def union_of(graphs: Iterable[Graph]) -> Graph:
    """Every graph loaded together."""
    union = Graph()
    for graph in graphs:
        union += graph
    return union


def read_previous(repo_root: Path | None = None) -> Graph:
    """Parse the instance's current generated output into one graph (spec 3.3)."""
    return union_of(read_previous_files(repo_root).values())


def statements_by_subject(graph: Graph) -> dict[URIRef, set[tuple[URIRef, Node]]]:
    """Group a graph's statements by subject, excluding ``dcterms:modified``.

    The one definition of "what is said about this node", shared by the date
    carry-forward and the run report (spec 5.6).
    """
    statements: dict[URIRef, set[tuple[URIRef, Node]]] = {}
    for subject, predicate, object_ in graph:
        if not isinstance(subject, URIRef) or not isinstance(predicate, URIRef):
            continue
        if predicate == DCTERMS.modified:
            continue
        statements.setdefault(subject, set()).add((predicate, object_))
    return statements


def unchanged(files: Sequence[OutputFile], repo_root: Path | None = None) -> bool:
    """Whether every produced file is already on disk with exactly these bytes (spec 5.6).

    Pass the manifest too: a plane upgrade changes it and nothing else. Files the run did
    not produce are :func:`stale`'s question.
    """
    root = Path.cwd() if repo_root is None else Path(repo_root)
    for file in files:
        try:
            found = (root / file.path).read_bytes()
        except OSError:
            return False
        if found != file.text.encode("utf-8"):
            return False
    return True


def stale(
    files: Sequence[OutputFile], repo_root: Path | None = None, *, keep: Collection[str] = ()
) -> tuple[str, ...]:
    """Files under ``generated/``, recursively, that were not among ``files`` (spec 4.3).

    ``keep`` names files that are never stale; both callers pass ``.report.md`` (spec 5.6).
    """
    root = Path.cwd() if repo_root is None else Path(repo_root)
    directory = root / GENERATED_DIR
    if not directory.is_dir():
        return ()
    produced = {file.name for file in files} | set(keep)
    return tuple(
        name
        for path in sorted(directory.rglob("*"))
        if path.is_file() and (name := path.relative_to(directory).as_posix()) not in produced
    )


def remove(names: Sequence[str], repo_root: Path | None = None) -> None:
    """Delete named files from ``generated/``, then any directory their removal emptied."""
    root = Path.cwd() if repo_root is None else Path(repo_root)
    directory = root / GENERATED_DIR
    for name in names:
        (directory / name).unlink()
    for path in sorted(directory.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def ontology_file() -> OutputFile:
    """The pinned metamodel as one of ``generated/``'s files, copied verbatim, never
    re-serialized (spec 4.2). Shared with migrations (spec 7)."""
    return OutputFile(name=ONTOLOGY_FILE, text=ONTOLOGY_PATH.read_text(encoding="utf-8"))


def write_all(files: Sequence[OutputFile], repo_root: Path | None = None) -> tuple[Path, ...]:
    """Write every file into ``<repo_root>/generated/`` with LF line endings (spec 5.5 rule 5)."""
    root = Path.cwd() if repo_root is None else Path(repo_root)
    directory = root / GENERATED_DIR
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for file in files:
        path = root / file.path
        path.write_text(file.text, encoding="utf-8", newline="\n")
        written.append(path)
    return tuple(written)


class _Previous:
    """The previous generated state, asked only what ``dcterms:modified`` needs to know."""

    def __init__(self, graph: Graph | None) -> None:
        self._statements: dict[URIRef, set[tuple[URIRef, Node]]] = {}
        self._modified: dict[URIRef, Literal] = {}
        if graph is None:
            return
        self._statements = statements_by_subject(graph)
        for subject, object_ in graph.subject_objects(DCTERMS.modified):
            if isinstance(subject, URIRef) and isinstance(object_, Literal):
                self._modified[subject] = object_

    def modified(self, subject: URIRef, statements: set[tuple[URIRef, Node]]) -> Literal | None:
        """The date to carry forward, or ``None`` if this node's content changed."""
        if self._statements.get(subject) != statements:
            return None
        return self._modified.get(subject)


@dataclass(frozen=True, slots=True)
class _Builder:
    model: InternalModel
    registry: Registry
    context: RunContext
    previous: _Previous
    today: datetime.date
    carried: tuple[CarriedNode, ...] = ()
    issues: list[Issue] = field(default_factory=list)
    """Problems found so far; raised together."""

    references: list[_Reference] = field(default_factory=list)
    """Every cross-reference that resolved, checked against the whole output in
    :meth:`_check_references_are_written`."""

    def build(self) -> tuple[OutputFile, ...]:
        resolved = self.registry.resolve(self.model)

        # Two batches: the second decides files and needs the scheme index clean.
        schemes = self._scheme_index()
        self._check_memberships(schemes)
        self._check_enumerated_entities()
        self._check_carried_are_gone(resolved)
        self._raise_collected()

        blocks = self._blocks(resolved, schemes) + self._carried_blocks()
        self._check_nothing_is_written_twice(blocks)
        # Raises before any graph is built, so _reference()'s placeholder never reaches a file.
        self._check_references_are_written(blocks)
        self._raise_collected()

        # Per subject across every file, since "did this node change" is about the node.
        emitted: dict[URIRef, set[tuple[URIRef, Node]]] = {}
        for block in blocks:
            emitted.setdefault(block.subject, set()).update(block.statements)

        graphs: dict[str, Graph] = {}
        for block in blocks:
            graph = graphs.setdefault(block.name, Graph())
            for predicate, object_ in block.statements:
                graph.add((block.subject, predicate, object_))
            if block.defines:
                graph.add(
                    (
                        block.subject,
                        DCTERMS.modified,
                        self._modified(block.subject, emitted[block.subject]),
                    )
                )

        files = [
            OutputFile(
                name=name,
                text=serialize.serialize(graph, self.context.base_iri),
                graph=graph,
            )
            for name, graph in sorted(graphs.items())
        ]
        return (self._ontology(), *files)

    def _blocks(
        self,
        resolved: Mapping[SemanticObject, str],
        schemes: Mapping[str, _SchemeEntry],
    ) -> tuple[_Block, ...]:
        """Every statement this run emits, tagged with the file it belongs in."""
        blocks: list[_Block] = []
        shortcuts: dict[tuple[URIRef, URIRef], str] = {}
        for object_ in self.model.objects:
            name = self._file_name(object_, schemes)
            blocks.append(
                _Block(
                    name=name,
                    subject=URIRef(resolved[object_]),
                    statements=self._statements(object_, resolved, schemes),
                    defines=True,
                )
            )
            if isinstance(object_, Relationship):
                # The sem:relatesTo shortcut lives with its relationship (spec 3.2), once per
                # entity pair, in the lexicographically first of their files.
                pair = (
                    self._reference(object_, object_.source, "source"),
                    self._reference(object_, object_.target, "target"),
                )
                shortcuts[pair] = min(name, shortcuts.get(pair, name))
        blocks.extend(
            _Block(
                name=name,
                subject=source,
                statements={(SEM_RELATES_TO, target)},
                defines=False,
            )
            for (source, target), name in sorted(shortcuts.items())
        )
        return tuple(blocks)

    def _carried_blocks(self) -> tuple[_Block, ...]:
        """The retained nodes, as blocks of the files they were already written in."""
        return tuple(
            _Block(
                name=node.file,
                subject=node.subject,
                statements=set(node.statements),
                defines=node.defines,
            )
            for node in self.carried
        )

    # ------------------------------------------------------------------ file partitioning

    def _ontology(self) -> OutputFile:
        """The pinned metamodel, copied verbatim (spec 4.2); see :func:`ontology_file`."""
        return ontology_file()

    def _file_name(self, object_: SemanticObject, schemes: Mapping[str, _SchemeEntry]) -> str:
        if isinstance(object_, Scheme):
            prefix = "taxonomy" if object_.scheme_type is SchemeType.TAXONOMY else "concepts"
            return f"{prefix}-{object_.slug}.ttl"

        slug = self._home_scheme(object_)
        entry = schemes[slug]
        if isinstance(object_, Relationship):
            return f"relationships-{slug}.ttl"
        if entry.scheme_type is SchemeType.TAXONOMY:
            return f"taxonomy-{slug}.ttl"
        return f"concepts-{slug}.ttl"

    def _home_scheme(self, object_: SemanticObject) -> str:
        """The one scheme whose file an object is written in: the lexicographically first."""
        assert isinstance(object_, SchemeMember)
        return sorted(object_.schemes)[0]

    # ------------------------------------------------------------------ statements

    def _statements(
        self,
        object_: SemanticObject,
        resolved: Mapping[SemanticObject, str],
        schemes: Mapping[str, _SchemeEntry],
    ) -> set[tuple[URIRef, Node]]:
        statements: set[tuple[URIRef, Node]] = {
            (RDF.type, _CLASSES[type(object_)]),
            (SKOS.prefLabel, self._text(object_.pref_label)),
            (SEM_STATUS, Literal(STATUS_ACTIVE)),
        }
        statements.update((SEM_SOURCE_REF, Literal(str(ref))) for ref in object_.refs)
        statements.update((SKOS.altLabel, self._text(label)) for label in object_.alt_labels)
        statements.update((SKOS.hiddenLabel, self._text(label)) for label in object_.hidden_labels)
        statements.update((SKOS.scopeNote, self._text(note)) for note in object_.scope_notes)
        statements.update((SKOS.example, self._text(example)) for example in object_.examples)
        if object_.definition is not None:
            statements.add((SKOS.definition, self._text(object_.definition)))

        if isinstance(object_, Scheme):
            statements.update(self._scheme_statements(object_))
        else:
            assert isinstance(object_, SchemeMember)
            statements.update(
                (SKOS.inScheme, URIRef(schemes[slug].iri)) for slug in object_.schemes
            )
        if isinstance(object_, Entity):
            # skos:broader only; the inverse would state one fact twice (spec 3.3, 5.5 rule 4).
            statements.update(
                (SKOS.broader, self._reference(object_, ref, "broader")) for ref in object_.broader
            )
        if isinstance(object_, Attribute):
            statements.add((SEM_ATTRIBUTE_OF, self._reference(object_, object_.entity, "entity")))
        if isinstance(object_, Relationship):
            statements.add((SEM_SOURCE, self._reference(object_, object_.source, "source")))
            statements.add((SEM_TARGET, self._reference(object_, object_.target, "target")))
        if isinstance(object_, TaxonomyValue):
            statements.update(self._taxonomy_statements(object_, resolved, schemes))
        return statements

    def _scheme_statements(self, scheme: Scheme) -> Iterator[tuple[URIRef, Node]]:
        yield (SEM_SCHEME_TYPE, Literal(str(scheme.scheme_type)))
        if scheme.enumerates is not None:
            # Resolvable by now: _check_enumerated_entities ran first. Re-checked, not asserted.
            iri = self.registry.iri(scheme.enumerates)
            if iri is None:  # pragma: no cover - guarded by _check_enumerated_entities
                raise BuildError(
                    [Issue(Severity.ERROR, f"scheme {scheme.slug!r} enumerates an unresolved ref")]
                )
            self.references.append(
                _Reference(about=scheme, ref=scheme.enumerates, role="enumerates", iri=URIRef(iri))
            )
            yield (SEM_ENUMERATES, URIRef(iri))

    def _taxonomy_statements(
        self,
        value: TaxonomyValue,
        resolved: Mapping[SemanticObject, str],
        schemes: Mapping[str, _SchemeEntry],
    ) -> Iterator[tuple[URIRef, Node]]:
        if value.code is not None:
            yield (SKOS.notation, Literal(value.code))
        if value.parent is not None:
            yield (SKOS.broader, self._reference(value, value.parent, "parent"))
        else:
            # skos:topConceptOf only; the inverse would state one fact twice (spec 5.5 rule 4).
            for slug in sorted(value.schemes):
                yield (SKOS.topConceptOf, URIRef(schemes[slug].iri))

    def _modified(self, subject: URIRef, statements: set[tuple[URIRef, Node]]) -> Literal:
        """This node's ``dcterms:modified``, carried forward unless its content moved."""
        carried = self.previous.modified(subject, statements)
        if carried is not None:
            return carried
        return Literal(self.today, datatype=XSD.date)

    # ------------------------------------------------------------------ resolution

    def _text(self, value: str | Text) -> Literal:
        """A label, definition or note as a tagged literal; the default language applies
        only to an untagged value (spec 5.5 rule 6)."""
        text = value if isinstance(value, Text) else Text(value)
        return Literal(text.value, lang=text.language or self.context.default_language)

    def _reference(self, object_: SemanticObject, ref: SourceRef, role: str) -> URIRef:
        """The IRI of another object this one points at (spec 5.2).

        Answers only whether the instance ever minted an IRI for ``ref``; whether the run
        writes that node is :meth:`_check_references_are_written`'s question. A dangling
        ref is recorded and a placeholder returned, which :meth:`build` raises on before
        any graph is built.
        """
        iri = self.registry.iri(ref)
        if iri is None:
            self._issue(
                f"{object_.kind} {object_.refs[0]} names {ref} as its {role}, but no such "
                f"object was compiled; a reference must be to something the run resolved",
                object_,
            )
            return URIRef(f"urn:semprini:unresolved:{ref}")
        self.references.append(_Reference(about=object_, ref=ref, role=role, iri=URIRef(iri)))
        return URIRef(iri)

    def _scheme_index(self) -> Mapping[str, _SchemeEntry]:
        """Slug → the scheme's IRI and type, with the slug itself checked.

        The slug names the scheme's file as well as its IRI (spec 3.4.2, 4.2), and only the
        IRI is frozen by the ID map, so a renamed or malformed slug is refused here.
        """
        index: dict[str, _SchemeEntry] = {}
        for scheme in self.model.schemes:
            iri = self.registry.iri(scheme.refs[0])
            if iri is None:  # pragma: no cover - resolve() covers every scheme first
                self._issue(f"scheme {scheme.slug!r} has no IRI", scheme)
                continue
            if not is_slug(scheme.slug):
                self._issue(
                    f"scheme slug {scheme.slug!r} is not a slug; use lower-case letters, "
                    f"digits, '-' and '_' — it names a file in generated/ as well as an "
                    f"IRI (spec 3.4.2, 4.2)",
                    scheme,
                )
                continue
            frozen = self.context.iri(Kind.SCHEME, scheme.slug)
            if iri != frozen:
                self._issue(
                    f"scheme {scheme.refs[0]} is minted as {iri} but now reports the slug "
                    f"{scheme.slug!r}; a slug is assigned once and opaque thereafter "
                    f"(spec 3.4.2) — renaming it would move the scheme's file while its "
                    f"IRI stayed where it is",
                    scheme,
                )
                continue
            index[scheme.slug] = _SchemeEntry(iri=iri, scheme_type=scheme.scheme_type)
        return index

    def _check_memberships(self, index: Mapping[str, _SchemeEntry]) -> None:
        """Every object is in a scheme, and in the right kind of one; both decide its file."""
        for object_ in self.model.objects:
            if isinstance(object_, Scheme):
                continue
            assert isinstance(object_, SchemeMember)
            if not object_.schemes:
                self._issue(
                    f"{object_.kind} {object_.refs[0]} is in no scheme; every object "
                    f"belongs to a glossary or a taxonomy, which is also what decides "
                    f"the file it is written to (spec 4.2)",
                    object_,
                )
                continue
            for slug in sorted(object_.schemes):
                entry = index.get(slug)
                if entry is None:
                    self._issue(
                        f"{object_.kind} {object_.refs[0]} is in scheme {slug!r}, which "
                        f"no source defined",
                        object_,
                    )
                    continue
                wanted = (
                    SchemeType.TAXONOMY
                    if isinstance(object_, TaxonomyValue)
                    else SchemeType.GLOSSARY
                )
                if entry.scheme_type is not wanted:
                    self._issue(
                        f"{object_.kind} {object_.refs[0]} is in {slug!r}, which is a "
                        f"{entry.scheme_type}; a {object_.kind} belongs in a {wanted}",
                        object_,
                    )

    def _check_enumerated_entities(self) -> None:
        """``sem:enumerates`` must name a compiled object, and it must
        be an entity (spec 3.3, 5.3).
        """
        known = {row.iri: row.kind for row in self.registry.id_map}
        for scheme in self.model.schemes:
            if scheme.enumerates is None:
                continue
            iri = self.registry.iri(scheme.enumerates)
            kind = known.get(iri) if iri is not None else None
            if kind is None:
                self._issue(
                    f"scheme {scheme.slug!r} enumerates {scheme.enumerates}, which no run "
                    f"has compiled; the source that defines that entity must be "
                    f"configured and compiled first",
                    scheme,
                )
            elif kind is not Kind.ENTITY:
                self._issue(
                    f"scheme {scheme.slug!r} enumerates {scheme.enumerates}, which is a "
                    f"{kind}; a taxonomy provides the values of an entity (spec 3.3)",
                    scheme,
                )

    def _check_carried_are_gone(self, resolved: Mapping[SemanticObject, str]) -> None:
        """A retained node must be one the model no longer describes (spec 3.5).

        Defining blocks only: a carried ``sem:relatesTo`` shortcut about a live entity is
        legitimate (spec 4.2).
        """
        live = {iri: object_ for object_, iri in resolved.items()}
        for subject in sorted({str(node.subject) for node in self.carried if node.defines}):
            object_ = live.get(subject)
            if object_ is not None:
                self._issue(
                    f"{subject} is carried forward as no longer reported, but this run "
                    f"compiled {object_.kind} {object_.refs[0]} onto the same IRI; a node "
                    f"is either built from the model or retained from the previous output",
                    object_,
                )

    def _check_references_are_written(self, blocks: Sequence[_Block]) -> None:
        """Every cross-reference must point at a node this run writes, from the model or
        retained by lifecycle (spec 3.5). An ID-map row can outlive its node."""
        described = {block.subject for block in blocks if block.defines}
        # Deduplicated: a relationship's ends are each resolved twice.
        for reference in sorted(set(self.references), key=lambda item: (str(item.iri), item.role)):
            if reference.iri in described:
                continue
            self._issue(
                f"{reference.about.kind} {reference.about.refs[0]} names {reference.ref} as "
                f"its {reference.role}, which the ID map maps to {reference.iri} — but "
                f"nothing in this run's output describes that node; a reference must point "
                f"at an object the run wrote",
                reference.about,
            )

    def _check_nothing_is_written_twice(self, blocks: Sequence[_Block]) -> None:
        """No statement may be written into two files (spec 4.2, 5.5 rule 4)."""
        seen: dict[tuple[URIRef, URIRef, Node], str] = {}
        for block in sorted(blocks, key=lambda item: item.name):
            for predicate, object_ in sorted(block.statements, key=lambda item: str(item)):
                statement = (block.subject, predicate, object_)
                first = seen.setdefault(statement, block.name)
                if first != block.name:
                    raise BuildError(
                        [
                            Issue(
                                Severity.ERROR,
                                f"{block.subject} {predicate} {object_} is written in both "
                                f"{first} and {block.name}; a statement belongs to exactly "
                                f"one file (spec 4.2)",
                                block.name,
                            )
                        ]
                    )

    # ------------------------------------------------------------------ issue collection

    def _issue(self, message: str, about: SemanticObject) -> None:
        """Record a problem against the object that carries it, and keep going."""
        self.issues.append(Issue(Severity.ERROR, message, str(about.refs[0])))

    def _raise_collected(self) -> None:
        if self.issues:
            raise BuildError(self.issues)


@dataclass(frozen=True, slots=True)
class _Block:
    """Statements about one subject, tagged with the file they are written in. One
    subject may span two files (spec 4.2)."""

    name: str
    """The ``generated/`` file this block belongs in (spec 4.2)."""

    subject: URIRef
    statements: set[tuple[URIRef, Node]] = field(hash=False)
    """A set, hence ``hash=False`` (see :mod:`semprini.model`)."""

    defines: bool
    """Whether this block describes its subject rather than merely mentioning it. Only a
    defining block carries ``dcterms:modified``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class _Reference:
    """One resolved cross-reference."""

    about: SemanticObject
    """The object that points."""

    ref: SourceRef
    role: str
    iri: URIRef


@dataclass(frozen=True, slots=True)
class _SchemeEntry:
    iri: str
    scheme_type: SchemeType

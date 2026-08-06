"""Internal model → the graphs that become ``generated/`` (spec 3.2, 3.3, 4.2).

The stage where the compiler stops thinking in source systems and starts thinking in RDF.
Everything upstream — adapters, merging, identity — exists to hand this module objects
that already know what they are and which IRI they own; everything downstream is bytes.

Three things here are load-bearing.

*One triple is written in exactly one place.* Output is partitioned by scheme (spec 4.2),
and an object belongs to the file of its first scheme rather than to every file it could
appear in. Duplicating a subject across files would still load to the same graph, but it
would make one changed label several changed hunks, and PR diffs are the governance
interface (spec 1.2).

*``dcterms:modified`` reflects content, not runs.* A node's date is carried forward from
the previous output unless its other statements actually changed (spec 3.3). Without that,
every scheduled compile would rewrite every date and produce a diff no human caused —
which would train reviewers to skim exactly the file they are meant to read.

*Nothing here decides identity or bytes.* IRIs come from the registry (spec 5.4) and
ordering from the canonical serializer (spec 5.5); this module chooses statements and
files, and nothing else.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF, SKOS, XSD
from rdflib.term import Node

from semprini import ONTOLOGY_PATH, serialize
from semprini.identity import IdentityError, Registry
from semprini.model import (
    Attribute,
    Entity,
    InternalModel,
    Issue,
    Relationship,
    RunContext,
    Scheme,
    SchemeMember,
    SchemeType,
    SemanticObject,
    Severity,
    SourceRef,
    TaxonomyValue,
)

__all__ = [
    "GENERATED_DIR",
    "ONTOLOGY_FILE",
    "BuildError",
    "OutputFile",
    "build",
    "read_previous",
    "write_all",
]

GENERATED_DIR = Path("generated")
"""Machine-owned, overwritten wholesale on every run (spec 4.3)."""

ONTOLOGY_FILE = "ontology.ttl"
"""A verbatim copy of the pinned metamodel, so that a consumer can load an instance from
Git alone without installing the package (spec 4.2)."""

SEM = serialize.SEM_NAMESPACE

# The metamodel terms this module emits (spec 3.3). Written out rather than reached
# through a namespace object so that a typo is an import-time name error here, not a
# silently invented IRI in an instance's committed output.
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
"""Every node this module emits is active. Deprecation is evaluated against the union of
all configured sources and belongs to lifecycle, not to building (spec 3.5, 5.4)."""

_CLASSES: Mapping[type[SemanticObject], URIRef] = {
    Entity: SEM_ENTITY,
    Attribute: SEM_ATTRIBUTE,
    Relationship: SEM_RELATIONSHIP,
    TaxonomyValue: SKOS.Concept,
    Scheme: SKOS.ConceptScheme,
}


class BuildError(IdentityError):
    """The model cannot be expressed as RDF — CLI exit code 1 (spec 5.1).

    An :class:`~semprini.identity.IdentityError` because it is the same category of
    failure and the same exit code: the run reached a state no output can honestly
    represent, and it names the source ref that caused it rather than failing in the file.
    """

    noun = "build error"


@dataclass(frozen=True, slots=True)
class OutputFile:
    """One file of ``generated/``, rendered but not yet written.

    Rendered here rather than at write time so that ``--dry-run`` and the determinism
    check see exactly the bytes a real run would commit, without a filesystem in the way
    (spec 5.1, 6.1 check 7).
    """

    name: str
    text: str
    graph: Graph | None = None
    """The graph ``text`` was serialized from — ``None`` for the verbatim ontology copy,
    which is not serializer output and must never be round-tripped through one (spec 3.1:
    the published document carries its term comments)."""

    @property
    def path(self) -> Path:
        return GENERATED_DIR / self.name


def build(
    model: InternalModel,
    *,
    registry: Registry,
    context: RunContext,
    previous: Graph | None = None,
    today: datetime.date | None = None,
) -> tuple[OutputFile, ...]:
    """Turn a resolved model into the files ``generated/`` should hold (spec 4.2).

    ``previous`` is the union of the instance's current generated graphs, used only to
    carry ``dcterms:modified`` forward (spec 3.3); pass ``None`` on a first compile.
    ``today`` is injected so that a test pins it and so that nothing but this stage reads
    a clock.
    """
    builder = _Builder(
        model=model,
        registry=registry,
        context=context,
        previous=_Previous(previous),
        today=datetime.date.today() if today is None else today,
    )
    return builder.build()


def read_previous(repo_root: Path | None = None) -> Graph:
    """Parse the instance's current generated output into one graph (spec 3.3).

    One graph, not one per file, because a subject's statements are deliberately spread
    across files — a ``sem:relatesTo`` shortcut sits with the relationship that produced
    it, not with the entity it is about — and "did this node change" is a question about
    the node, not about a file.

    ``generated/ontology.ttl`` is skipped: it is the metamodel, identical in every
    deployment, and none of its subjects is an instance's to date.
    """
    root = Path.cwd() if repo_root is None else Path(repo_root)
    graph = Graph()
    directory = root / GENERATED_DIR
    if not directory.is_dir():
        # A first compile, or an instance whose generated/ has not been created yet.
        return graph
    for path in sorted(directory.glob("*.ttl")):
        if path.name == ONTOLOGY_FILE:
            continue
        graph.parse(path, format="turtle")
    return graph


def write_all(files: Sequence[OutputFile], repo_root: Path | None = None) -> tuple[Path, ...]:
    """Write every file into ``<repo_root>/generated/``.

    Writes with an explicit LF, like every other file the compiler owns: the platform
    default would make the same graph produce different bytes on different machines and
    fail the determinism check (spec 5.5 rule 5).
    """
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
        for subject, predicate, object_ in graph:
            if not isinstance(subject, URIRef) or not isinstance(predicate, URIRef):
                continue
            if predicate == DCTERMS.modified:
                if isinstance(object_, Literal):
                    self._modified[subject] = object_
                continue
            self._statements.setdefault(subject, set()).add((predicate, object_))

    def modified(self, subject: URIRef, statements: set[tuple[URIRef, Node]]) -> Literal | None:
        """The date to carry forward, or ``None`` if this node's content changed.

        Compared against everything *except* the date itself, which is the only way the
        answer can be stable: comparing a node to its own previous state including its
        date would make every run that touched it disagree with every run that did not.
        """
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

    def build(self) -> tuple[OutputFile, ...]:
        resolved = self.registry.resolve(self.model)
        schemes = self._scheme_index()
        self._check_enumerated_entities_exist()

        blocks = self._blocks(resolved, schemes)

        # What this run says about each subject, gathered across every file it is written
        # in. A subject is deliberately not confined to one file — a sem:relatesTo
        # shortcut is a statement about an entity that lives with the relationship which
        # produced it — and "did this node change" is a question about the node. Comparing
        # one file's share of a subject would refresh dcterms:modified on every run for
        # every entity that happens to be one end of a relationship.
        emitted: dict[URIRef, set[tuple[URIRef, Node]]] = {}
        for block in blocks:
            emitted.setdefault(block.subject, set()).update(block.statements)

        graphs: dict[str, Graph] = {}
        for block in blocks:
            graph = graphs.setdefault(block.name, Graph())
            for predicate, object_ in block.statements:
                graph.add((block.subject, predicate, object_))
            if block.defines:
                # Only the block that *defines* a node dates it: a shortcut states
                # something about an entity, it does not describe it.
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
                # The shortcut lives with the relationship that produced it, not with the
                # entity it is about: the two change together, and a reviewer reading a
                # relationship diff sees both halves in one hunk (spec 3.2).
                blocks.append(
                    _Block(
                        name=name,
                        subject=self._reference(object_, object_.source, "source"),
                        statements={
                            (SEM_RELATES_TO, self._reference(object_, object_.target, "target"))
                        },
                        defines=False,
                    )
                )
        return tuple(blocks)

    # ------------------------------------------------------------------ file partitioning

    def _ontology(self) -> OutputFile:
        """The pinned metamodel, copied verbatim (spec 4.2).

        Copied, never re-serialized: ``sem.ttl`` is hand-written and its term comments are
        the vocabulary's published documentation, which the canonical serializer would
        strip (spec 5.5 rule 5 governs an instance's own output, not this).
        """
        return OutputFile(name=ONTOLOGY_FILE, text=ONTOLOGY_PATH.read_text(encoding="utf-8"))

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
        """The one scheme whose file an object is written in.

        An object in several schemes carries several ``skos:inScheme`` triples but is
        written once, in the lexicographically first of them. Sorted rather than "the
        first one given", so that the file an object lands in cannot depend on the order
        an adapter happened to report its schemes in.
        """
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
        if object_.definition is not None:
            statements.add((SKOS.definition, self._text(object_.definition)))

        if isinstance(object_, Scheme):
            statements.update(self._scheme_statements(object_))
        else:
            assert isinstance(object_, SchemeMember)
            statements.update(
                (SKOS.inScheme, URIRef(schemes[slug].iri)) for slug in object_.schemes
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
            yield (SEM_ENUMERATES, URIRef(scheme.enumerates))

    def _taxonomy_statements(
        self,
        value: TaxonomyValue,
        resolved: Mapping[SemanticObject, str],
        schemes: Mapping[str, _SchemeEntry],
    ) -> Iterator[tuple[URIRef, Node]]:
        yield (SKOS.notation, Literal(value.code))
        if value.parent is not None:
            yield (SKOS.broader, self._reference(value, value.parent, "parent"))
        else:
            # A value with no parent is a top concept of its own taxonomy. Only
            # skos:topConceptOf is emitted, not its skos:hasTopConcept inverse: both would
            # state one fact in two files, and one changed fact must be one changed line
            # (spec 5.5 rule 4).
            for slug in sorted(value.schemes):
                yield (SKOS.topConceptOf, URIRef(schemes[slug].iri))

    def _modified(self, subject: URIRef, statements: set[tuple[URIRef, Node]]) -> Literal:
        """This node's ``dcterms:modified`` — carried forward unless its content moved."""
        carried = self.previous.modified(subject, statements)
        if carried is not None:
            return carried
        return Literal(self.today, datatype=XSD.date)

    # ------------------------------------------------------------------ resolution

    def _text(self, value: str) -> Literal:
        """A label or definition as a literal, with a language tag (spec 5.5 rule 6).

        The instance's ``default_language`` is applied per value rather than to all of
        them, so that a source which already knows its languages does not have to discard
        them. No v1 adapter produces a tagged label — the internal model carries plain
        strings — so today every value takes the default; the seam is here because rule 6
        is a promise about what happens when one does.
        """
        return Literal(value, lang=self.context.default_language)

    def _reference(self, object_: SemanticObject, ref: SourceRef, role: str) -> URIRef:
        """The IRI of another object this one points at.

        An adapter has no IRIs, so it points with source refs (spec 5.2); resolving them
        is the core's job and a dangling one is a compile failure rather than a triple
        pointing at nothing.

        Resolution goes through the registry, which also knows IRIs minted on *previous*
        runs — so what is actually refused is "an IRI this instance has never minted",
        not the stricter "an object this run compiled" the message describes. The gap is
        deliberate and not this task's to close: a ``--source X`` partial run (spec 5.4)
        legitimately references objects outside the fetched scope, so tightening this
        needs the partial-run case in view. **E2 owns it.**
        """
        iri = self.registry.iri(ref)
        if iri is None:
            raise BuildError(
                [
                    Issue(
                        Severity.ERROR,
                        f"{object_.kind} {object_.refs[0]} names {ref} as its {role}, but "
                        f"no such object was compiled; a reference must be to something "
                        f"the run resolved",
                        str(object_.refs[0]),
                    )
                ]
            )
        return URIRef(iri)

    def _scheme_index(self) -> Mapping[str, _SchemeEntry]:
        """Slug → the scheme's IRI and type, with every membership checked.

        Two rules are enforced here rather than left to SHACL, because both decide which
        *file* an object is written to and so cannot wait for validation: a scheme an
        object claims to be in must exist, and a taxonomy value belongs in a taxonomy
        while an entity, attribute or relationship belongs in a glossary.
        """
        index = {
            scheme.slug: _SchemeEntry(
                iri=self.registry.iri(scheme.refs[0]) or "", scheme_type=scheme.scheme_type
            )
            for scheme in self.model.schemes
        }
        issues: list[Issue] = []
        for object_ in self.model.objects:
            if isinstance(object_, Scheme):
                continue
            assert isinstance(object_, SchemeMember)
            if not object_.schemes:
                issues.append(
                    Issue(
                        Severity.ERROR,
                        f"{object_.kind} {object_.refs[0]} is in no scheme; every object "
                        f"belongs to a glossary or a taxonomy, which is also what decides "
                        f"the file it is written to (spec 4.2)",
                        str(object_.refs[0]),
                    )
                )
                continue
            for slug in sorted(object_.schemes):
                entry = index.get(slug)
                if entry is None:
                    issues.append(
                        Issue(
                            Severity.ERROR,
                            f"{object_.kind} {object_.refs[0]} is in scheme {slug!r}, which "
                            f"no source defined",
                            str(object_.refs[0]),
                        )
                    )
                    continue
                wanted = (
                    SchemeType.TAXONOMY
                    if isinstance(object_, TaxonomyValue)
                    else SchemeType.GLOSSARY
                )
                if entry.scheme_type is not wanted:
                    issues.append(
                        Issue(
                            Severity.ERROR,
                            f"{object_.kind} {object_.refs[0]} is in {slug!r}, which is a "
                            f"{entry.scheme_type}; a {object_.kind} belongs in a {wanted}",
                            str(object_.refs[0]),
                        )
                    )
        if issues:
            raise BuildError(issues)
        return index

    def _check_enumerated_entities_exist(self) -> None:
        """``sem:enumerates`` is configured by hand, so its target is checked (spec 5.3).

        A taxonomy pointing at an entity IRI that no run ever minted is a typo in
        ``config/semprini.yaml``, and it would otherwise reach the output as a triple
        pointing into empty space.
        """
        known = {row.iri for row in self.registry.id_map}
        issues = [
            Issue(
                Severity.ERROR,
                f"scheme {scheme.slug!r} enumerates {scheme.enumerates}, which is not an "
                f"IRI this instance has minted; check the 'enumerates' setting",
                str(scheme.refs[0]),
            )
            for scheme in self.model.schemes
            if scheme.enumerates is not None and scheme.enumerates not in known
        ]
        if issues:
            raise BuildError(issues)


@dataclass(frozen=True, slots=True)
class _Block:
    """Statements about one subject, tagged with the file they are written in.

    The unit of partitioning, and deliberately not "a subject". One subject legitimately
    spans two files — a ``sem:relatesTo`` shortcut is a statement about an entity that
    lives with the relationship which produced it — so a file is a property of the
    statements, not of the node they are about.
    """

    name: str
    """The ``generated/`` file this block belongs in (spec 4.2)."""

    subject: URIRef
    statements: set[tuple[URIRef, Node]] = field(hash=False)
    """Excluded from the generated ``__hash__``, not from ``__eq__``: a set is unhashable,
    and a frozen dataclass that cannot be hashed is a trap for the next caller that puts
    one in a set — the same pattern ``SemanticObject.source_refs`` follows."""

    defines: bool
    """Whether this block *describes* its subject, as opposed to merely stating something
    about it. Only a defining block carries ``dcterms:modified``: a node is dated once, in
    the file that introduces it, however many files mention it."""


@dataclass(frozen=True, slots=True)
class _SchemeEntry:
    iri: str
    scheme_type: SchemeType

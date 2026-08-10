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
from collections.abc import Iterable, Iterator, Mapping, Sequence
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
    "read_previous",
    "read_previous_files",
    "statements_by_subject",
    "unchanged",
    "union_of",
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
"""The status of every node this stage builds from the model: a source still reports it.

Deprecation is not decided here. Whether an object is gone is a question about the *union*
of all configured sources and about the state this run replaces (spec 3.5, 5.4), which is
:mod:`semprini.lifecycle`'s to answer; it arrives as :class:`CarriedNode`s."""

STATUS_DEPRECATED = "deprecated"
"""The status lifecycle gives a node no source reports any more (spec 3.5). Written here
beside its opposite so that the two values have one definition between them."""

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


@dataclass(frozen=True, slots=True, kw_only=True)
class CarriedNode:
    """One node's statements as the previous run wrote them, re-emitted (spec 3.5).

    A node no source reports any more is **retained**, not dropped: whatever published its
    IRI still points at it, so the compiler goes on writing its last-known statements and
    marks it deprecated. It is not in the model — no adapter returned it — so it cannot be
    built from one, and it arrives here already decided.

    :func:`semprini.lifecycle.plan` produces these, which is where every judgement lives:
    whether the node is really gone (a question about the union of all configured sources,
    never one of them), whether this run is even entitled to ask (spec 5.4's partial-run
    rule), and what the merge register says replaces it. This stage only writes them.
    """

    file: str
    """The ``generated/`` file that held these statements. A deprecated node stays where
    it was, so its deprecation is one changed line rather than a move between files."""

    subject: URIRef
    statements: frozenset[tuple[URIRef, Node]]
    """Without ``dcterms:modified``: the date is recomputed like every other node's, so a
    node whose statements did not move keeps the date it had (spec 3.3)."""

    defines: bool
    """Whether this is the block that *describes* the node — the one carrying its label,
    and so the one dated. A node's statements can span two files (spec 4.2)."""


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

    ``previous`` is the union of the instance's current generated graphs, used only to
    carry ``dcterms:modified`` forward (spec 3.3); pass ``None`` on a first compile.
    ``today`` is injected so that a test pins it and so that nothing but this stage reads
    a clock.

    ``carried`` are the nodes lifecycle decided to retain (spec 3.5) — deprecated objects
    and, on a partial run, objects outside the fetched scope. They are written alongside
    what the model produced and are dated by the same rule, so a deprecation is a changed
    ``sem:status`` line and nothing else.

    A partial run is **refused**, loudly, rather than quietly building from part of a
    model. ``write_all`` rewrites each file whole, so building a ``--source X`` run this
    way would drop every other source's statements from the files it touched and refresh
    ``dcterms:modified`` on every node they co-describe — silent deletion of governed
    content. Making a partial run work is **E2's** (spec 5.4): it has to decide whether
    the fetched subset is merged with the previous state before building, or whether
    writing becomes per-file.
    """
    if context.only_source is not None:
        raise BuildError(
            [
                Issue(
                    Severity.ERROR,
                    f"this compiler cannot build a partial run (--source "
                    f"{context.only_source!r}): generated files are written whole, so a "
                    f"model holding one source's objects would delete the others' "
                    f"statements from every file it rewrote",
                    "--source",
                )
            ]
        )
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
    """Parse each of the instance's generated Turtle files into its own graph.

    Keyed by file name, because lifecycle needs to know *where* a statement was written:
    a node it retains stays in the file that held it (spec 3.5), and a node that moved
    between files would otherwise be deleted from one and added to another with nothing
    in the diff tying the two hunks together.

    ``generated/ontology.ttl`` is skipped: it is the metamodel, identical in every
    deployment, and none of its subjects is an instance's to date or to deprecate.
    """
    root = Path.cwd() if repo_root is None else Path(repo_root)
    directory = root / GENERATED_DIR
    graphs: dict[str, Graph] = {}
    if not directory.is_dir():
        # A first compile, or an instance whose generated/ has not been created yet.
        return graphs
    issues: list[Issue] = []
    for path in sorted(directory.glob("*.ttl")):
        if path.name == ONTOLOGY_FILE:
            continue
        graph = Graph()
        try:
            graph.parse(path, format="turtle")
        except (OSError, UnicodeDecodeError, SyntaxError) as error:
            # Reported as an issue rather than left to surface as an rdflib traceback:
            # unparseable output in generated/ is exactly the hand-edit spec 4.3 exists to
            # catch, and the operator needs the file named. rdflib raises its own
            # ``BadSyntax``, which subclasses SyntaxError.
            issues.append(
                Issue(Severity.ERROR, f"cannot read generated output: {error}", str(path))
            )
            continue
        graphs[path.name] = graph
    if issues:
        raise BuildError(issues)
    return graphs


def union_of(graphs: Iterable[Graph]) -> Graph:
    """Every graph loaded together — what a consumer of the instance sees.

    Public because a run needs the previous state both ways at once: per file for
    lifecycle, and unioned for ``dcterms:modified`` and the report. Parsing the directory
    twice to get both would be the kind of waste that only shows up on the instances big
    enough to care.
    """
    union = Graph()
    for graph in graphs:
        union += graph
    return union


def read_previous(repo_root: Path | None = None) -> Graph:
    """Parse the instance's current generated output into one graph (spec 3.3).

    One graph, because a subject's statements are deliberately spread across files — a
    ``sem:relatesTo`` shortcut sits with the relationship that produced it, not with the
    entity it is about — and "did this node change" is a question about the node, not
    about a file. Lifecycle asks the other question and reads
    :func:`read_previous_files` instead.
    """
    return union_of(read_previous_files(repo_root).values())


def statements_by_subject(graph: Graph) -> dict[URIRef, set[tuple[URIRef, Node]]]:
    """Group a graph's statements by subject, **excluding** ``dcterms:modified``.

    The one definition of "what is said about this node", shared by the
    ``dcterms:modified`` carry-forward below and by the run report's new/changed counts
    (spec 5.6). Two answers to one question would eventually disagree, and the way they
    would disagree is the worst available: a report saying nothing changed beside a file
    whose dates all moved.

    The date is excluded because including it makes the comparison meaningless — a node
    compared against its own previous state *including* its date differs from itself
    whenever the previous run happened to be a different day.
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
    """Whether every produced file is already on disk with exactly these bytes.

    What decides whether a run writes ``generated/.report.md`` at all (spec 5.6), and so
    whether a scheduled compile that found nothing new opens a pull request containing
    only a report saying it found nothing new.

    **Pass the manifest's own file, not only the Turtle.** It carries the compiler and
    ontology versions (spec 4.3), so a recompile after a plane upgrade produces identical
    Turtle and a *different* manifest — a real change, and one whose report must be
    rewritten. Comparing the Turtle alone would commit a manifest saying 0.2.0 produced
    these files beside a report whose header says 0.1.0 did, which is exactly the
    disagreement the report is supposed to be incapable of.

    A file the run did *not* produce is not consulted: removing stale output is a
    different question, and one that needs the run's scope to answer (spec 4.3) — a
    ``--source X`` run legitimately regenerates part of the directory. **E2 owns it.**
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
        self._statements = statements_by_subject(graph)
        for subject, object_ in graph.subject_objects(DCTERMS.modified):
            if isinstance(subject, URIRef) and isinstance(object_, Literal):
                self._modified[subject] = object_

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
    carried: tuple[CarriedNode, ...] = ()
    issues: list[Issue] = field(default_factory=list)
    """Problems found so far. Collected rather than raised one at a time: these are read
    in CI, where one problem per run costs a round trip each (spec 5.2)."""

    def build(self) -> tuple[OutputFile, ...]:
        resolved = self.registry.resolve(self.model)

        # Two batches, and the split is forced rather than chosen: everything below
        # decides which *file* an object is written to, so the second batch cannot run
        # until the first is clean — _file_name would raise KeyError on a scheme no
        # source defined. Within each batch every problem is reported.
        schemes = self._scheme_index()
        self._check_memberships(schemes)
        self._check_enumerated_entities()
        self._check_carried_are_gone(resolved)
        self._raise_collected()

        blocks = self._blocks(resolved, schemes) + self._carried_blocks()
        self._check_nothing_is_written_twice(blocks)
        # Cross-references are collected while blocks are built, not raised at the first
        # dangling one. Nothing is assembled or written until after this, so the
        # placeholder _reference() returns for a broken ref cannot escape into a file.
        self._raise_collected()

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
                # The shortcut lives with the relationship that produced it, not with the
                # entity it is about: the two change together, and a reviewer reading a
                # relationship diff sees both halves in one hunk (spec 3.2).
                #
                # Keyed by the pair, because sem:relatesTo says only *that* two entities
                # are related — several relationships between one pair derive the same
                # triple. Written once, in the lexicographically first of their files, so
                # that deleting one of them does not show a removed relatesTo line for a
                # fact that still holds, and so the choice cannot depend on model order.
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
        """The retained nodes, as blocks of the files they were already written in.

        Deliberately not re-derived from anything: these statements are what the previous
        run wrote, and re-deciding them would mean compiling an object out of a model that
        no longer contains it.
        """
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
            # Inheritance, stated with the reused SKOS property rather than a sem: term
            # (spec 3.3): every entity is a skos:Concept, and a specialization of one is
            # narrower than it. Only this direction is emitted — skos:narrower would state
            # the same fact a second time, in the other entity's file (spec 5.5 rule 4).
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
            # Resolvable by now: _check_enumerated_entities ran in the earlier batch and
            # build() raised if it did not resolve. Re-checked rather than asserted, since
            # `python -O` strips an assert and the fallthrough would be URIRef(None) — a
            # TypeError from inside rdflib instead of a build error naming the scheme.
            iri = self.registry.iri(scheme.enumerates)
            if iri is None:  # pragma: no cover - guarded by _check_enumerated_entities
                raise BuildError(
                    [Issue(Severity.ERROR, f"scheme {scheme.slug!r} enumerates an unresolved ref")]
                )
            yield (SEM_ENUMERATES, URIRef(iri))

    def _taxonomy_statements(
        self,
        value: TaxonomyValue,
        resolved: Mapping[SemanticObject, str],
        schemes: Mapping[str, _SchemeEntry],
    ) -> Iterator[tuple[URIRef, Node]]:
        if value.code is not None:
            # Untagged and plain: a notation is a code, not prose in a language.
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

    def _text(self, value: str | Text) -> Literal:
        """A label, definition or note as a literal, tagged (spec 5.5 rule 6).

        The instance's ``default_language`` is applied per value rather than to all of
        them, so that a source which already knows its languages does not have to discard
        them: a value that arrived carrying a tag keeps it, and only an untagged one takes
        the default. The Excel taxonomy adapter states tags per cell (spec 5.3), so both
        branches are reachable.
        """
        text = value if isinstance(value, Text) else Text(value)
        return Literal(text.value, lang=text.language or self.context.default_language)

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
        needs the partial-run case in view. **E2 owns it**, together with the guard in
        :func:`build` that refuses such a run outright today.

        A dangling ref is recorded and a placeholder returned rather than raised on the
        spot, so that a model with several of them reports them all in one run. The
        placeholder never reaches a file: :meth:`build` raises as soon as the blocks are
        assembled, before a single graph is built.
        """
        iri = self.registry.iri(ref)
        if iri is None:
            self._issue(
                f"{object_.kind} {object_.refs[0]} names {ref} as its {role}, but no such "
                f"object was compiled; a reference must be to something the run resolved",
                object_,
            )
            return URIRef(f"urn:semprini:unresolved:{ref}")
        return URIRef(iri)

    def _scheme_index(self) -> Mapping[str, _SchemeEntry]:
        """Slug → the scheme's IRI and type, with the slug itself checked.

        A scheme slug is assigned once and opaque thereafter (spec 3.4.2), and it names
        two things: the local name of the scheme's IRI, and the file every member of that
        scheme is written to (spec 4.2). Only the first is frozen by the ID map, so
        nothing but this check stops the second from moving underneath it — identity
        validates a slug on the run that *mints* it, and every later run gets its answer
        from the map without looking at the slug again.

        Both failures are reachable from an ordinary edit of ``config/semprini.yaml``.
        Renaming ``scheme_slug`` silently moves ``concepts-<slug>.ttl`` to a new file
        while the scheme's IRI stays what it always was — the ID map and the output then
        disagree about what the scheme is called. And a slug that is not a slug at all is
        a path: ``../../x`` composes a filename that resolves outside ``generated/``
        entirely, which is a machine-owned directory the manifest is supposed to bound
        (spec 4.3).
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
        """Every object is in a scheme, and in the right kind of one.

        Enforced here rather than left to SHACL because both decide which *file* an
        object is written to, and so cannot wait for validation.
        """
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
        """``sem:enumerates`` names another source's object, so its target is checked.

        A taxonomy pointing at something no run ever compiled would otherwise reach the
        output as a triple pointing into empty space. This is the ordinary case while an
        instance is being brought up rather than an exotic one: a workbook names the
        entity by its key in the modelling tool (spec 5.3), so a taxonomy compiled before
        that tool's source is configured has nothing to point at yet, and the message has
        to be plain enough to say so.

        The *kind* is checked too, from the ID map's own column: ``sem:enumerates`` runs
        scheme → **entity** (spec 3.3), and a key copied from the wrong place is a
        plausible mistake that would otherwise produce a well-formed, wrong statement.
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
        """A retained node must be one the model no longer *describes* (spec 3.5).

        Carrying a node the run also compiled would write one subject twice — the model's
        statements and the previous run's, unioned into one graph — so the node would wear
        two labels and be marked both active and deprecated, and the file would be
        internally contradictory rather than merely wrong. Lifecycle selects carried nodes
        precisely from what the model does *not* contain, so this catches a caller that
        assembled the two halves from different runs.

        Only *defining* blocks are checked. A block that merely states something about a
        live node is the ``sem:relatesTo`` shortcut, whose subject is an entity the run
        compiled while the relationship it derives from was retained (spec 4.2) — that is
        a legitimate pairing, and :meth:`_check_nothing_is_written_twice` is what keeps it
        from producing the same triple twice.
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

    def _check_nothing_is_written_twice(self, blocks: Sequence[_Block]) -> None:
        """No statement may be written into two files (spec 4.2, 5.5 rule 4).

        The invariant the whole partitioning scheme rests on: one changed fact is one
        changed line, which it stops being the moment a triple lives in two places. It is
        checked rather than assumed because the model and the retained nodes are assembled
        from different evidence — a shortcut the previous run wrote and this one also
        derives would otherwise appear in both files, and the second copy would only show
        up as a diff hunk nobody could explain.
        """
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

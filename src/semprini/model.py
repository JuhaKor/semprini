"""The internal model adapters return and the core consumes (spec 5.1, 5.2).

This is the seam between the two halves of the compiler. An adapter knows a source
system and nothing else: it returns these objects, each carrying the key its source uses,
and never touches identity, files or RDF (spec 5.2). Everything downstream — identity
resolution, graph building, lifecycle — reads only what is here, which is what lets a
third-party adapter be a first-class citizen.

Three properties are load-bearing:

*Immutability.* Adapters run one after another over shared state and must not be able to
reach back into what an earlier one returned, so every object is a frozen dataclass whose
collections are tuples and whose ``source_refs`` is a read-only mapping.

*Identity lives in ``source_refs``, not in a field called "id".* An object is identified
by the ``(source name, source key)`` pairs that produced it, so the same real-world
concept seen by two sources merges onto one object — and later onto one IRI, since the ID
map is keyed by exactly that pair (spec 5.4). Cross-object references are ``SourceRef``s
for the same reason: an adapter has no IRIs to point with.

*Merging is deterministic and refuses to guess.* Set-valued fields union; a scalar the
two sides disagree on raises ``MergeConflictError`` rather than picking one, because a silently
chosen label would land in a governed file with nothing in the diff to explain it.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar

from semprini import serialize

__all__ = [
    "Attribute",
    "Entity",
    "InternalModel",
    "Issue",
    "Kind",
    "MergeConflictError",
    "Relationship",
    "RunContext",
    "Scheme",
    "SchemeMember",
    "SchemeType",
    "SemanticObject",
    "Severity",
    "SourceRef",
    "TaxonomyValue",
    "merge_models",
]


class Kind(StrEnum):
    """What a semantic object is, and therefore which namespace it is minted in.

    Recorded in the ID map's ``kind`` column (spec 5.4) and used by identity to choose a
    namespace — the IRI space is partitioned by kind of thing, permanently (spec 3.1).
    """

    ENTITY = "entity"
    ATTRIBUTE = "attribute"
    RELATIONSHIP = "relationship"
    SCHEME = "scheme"
    TAXONOMY_VALUE = "taxonomy-value"

    @property
    def prefix(self) -> str:
        """The prefix of the namespace this kind is minted in (spec 3.1)."""
        return _KIND_PREFIXES[self]


# Entities, attributes and business terms share `c:` — spec 3.1 partitions by kind of
# thing, and all three are concepts in the SKOS sense.
_KIND_PREFIXES = {
    Kind.ENTITY: "c",
    Kind.ATTRIBUTE: "c",
    Kind.RELATIONSHIP: "r",
    Kind.SCHEME: "sch",
    Kind.TAXONOMY_VALUE: "v",
}


class SchemeType(StrEnum):
    """The value of ``sem:schemeType`` (spec 3.3)."""

    GLOSSARY = "glossary"
    TAXONOMY = "taxonomy"


class Severity(StrEnum):
    """Whether an issue fails a run or only appears in the report (spec 5.6, 6.1)."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Issue:
    """One problem found while validating configuration or content (spec 5.2, 6.1).

    Returned by ``BaseAdapter.validate_config()`` and collected by ``semprini check``, so
    that a configuration mistake is reported with the key that caused it rather than as a
    traceback.
    """

    severity: Severity
    message: str
    location: str | None = None
    """Where the problem is — a config key, a file and row, a source key."""

    def __str__(self) -> str:
        where = f" ({self.location})" if self.location else ""
        return f"{self.severity}: {self.message}{where}"


@dataclass(frozen=True, slots=True, order=True)
class SourceRef:
    """One source's key for an object: the pair the ID map is keyed by (spec 5.4).

    Its string form is exactly the value of ``sem:sourceRef`` (spec 3.3), so the RDF and
    the identity registry cannot drift into telling different stories.
    """

    source: str
    """The source's configured ``name`` — assigned once and never reused (spec 5.1)."""

    key: str
    """The key that source uses for the object: a UUID, a code, a slug."""

    def __post_init__(self) -> None:
        if not self.source or not self.key:
            raise ValueError(f"a source ref needs both a source name and a key, got {self!r}")
        if ":" in self.source:
            # The string form would otherwise be ambiguous to split back apart, and the
            # ID map's CSV columns and sem:sourceRef would disagree about the boundary.
            raise ValueError(f"a source name may not contain ':', got {self.source!r}")

    def __str__(self) -> str:
        return f"{self.source}:{self.key}"


class MergeConflictError(ValueError):
    """Two sources describe one object and disagree about a value.

    Raised rather than resolved: picking a side would put an arbitrary statement into a
    governed file, and the diff would show a change no source made. Which side wins is a
    stewardship decision, not the compiler's (spec 1.2).
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticObject:
    """Fields every semantic object carries, whatever its kind.

    Keyword-only so that adapters name what they set: these classes gain fields over
    time, and positional construction would make that a breaking change for every
    third-party adapter (spec 5.2).
    """

    kind: ClassVar[Kind]

    # Field names whose values union on merge instead of having to agree.
    UNION_FIELDS: ClassVar[tuple[str, ...]] = ("alt_labels",)

    source_refs: Mapping[str, str] = field(hash=False)
    """Source name → that source's key. Several entries means several sources produced
    this object, and it will resolve to one IRI (spec 5.2).

    Excluded from the generated ``__hash__`` (but not from ``__eq__``): a mapping is
    unhashable, and hashing it would leave a class advertised as frozen that cannot go in
    a set or key a dict — which is exactly what identity resolution does with these
    (spec 5.4). Hashing a subset of the compared fields keeps the two consistent."""

    pref_label: str
    """``skos:prefLabel``. Untagged here — the instance's configured language is applied
    when the graph is built, since an adapter does not know it (spec 5.5 rule 6)."""

    definition: str | None = None
    """``skos:definition``. ``None`` and empty both emit no triple (spec 5.3)."""

    alt_labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_refs:
            # An object with no source ref cannot be looked up, minted, or deprecated:
            # it would be invisible to every later stage.
            raise ValueError(f"{type(self).__name__} must carry at least one source ref")
        if not self.pref_label:
            raise ValueError(f"{type(self).__name__} must carry a prefLabel")
        # Constructed and discarded for its validation: an unusable pair must be refused
        # where the adapter built it, not several stages later where the message could
        # only name the pair and not the object that carries it.
        for source, key in self.source_refs.items():
            SourceRef(source, key)
        object.__setattr__(self, "source_refs", MappingProxyType(dict(self.source_refs)))
        object.__setattr__(self, "alt_labels", tuple(self.alt_labels))
        # Empty and absent are the same statement — neither emits a skos:definition
        # triple (spec 5.3) — so they are made one state here rather than two that
        # every later comparison has to know are equivalent.
        object.__setattr__(self, "definition", self.definition or None)

    @property
    def refs(self) -> tuple[SourceRef, ...]:
        """The source refs as pairs, in a stable order."""
        return tuple(sorted(SourceRef(source, key) for source, key in self.source_refs.items()))

    @property
    def sort_key(self) -> str:
        """A stable order for objects of one kind, independent of how they arrived."""
        return str(self.refs[0])


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemeMember(SemanticObject):
    """An object that can belong to schemes (everything except a scheme itself)."""

    UNION_FIELDS: ClassVar[tuple[str, ...]] = ("alt_labels", "schemes")

    schemes: tuple[str, ...] = ()
    """Slugs of the schemes this object is in — ``skos:inScheme``. Several means the
    object appears in several domain models, which costs it nothing (spec 5.3)."""

    def __post_init__(self) -> None:
        # Named explicitly rather than through super(): @dataclass(slots=True) rebuilds
        # the class, and the zero-argument form has bitten that combination before.
        SemanticObject.__post_init__(self)
        object.__setattr__(self, "schemes", tuple(self.schemes))


@dataclass(frozen=True, slots=True, kw_only=True)
class Entity(SchemeMember):
    """A business entity or concept — ``sem:Entity`` (spec 3.2)."""

    kind: ClassVar[Kind] = Kind.ENTITY


@dataclass(frozen=True, slots=True, kw_only=True)
class Attribute(SchemeMember):
    """An attribute with its own identity — ``sem:Attribute`` (spec 3.2)."""

    kind: ClassVar[Kind] = Kind.ATTRIBUTE

    entity: SourceRef
    """The entity this is an attribute of — ``sem:attributeOf``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Relationship(SchemeMember):
    """A named relationship between two entities — ``sem:Relationship`` (spec 3.2).

    Reified because it carries a verb and an identity of its own; the ``sem:relatesTo``
    shortcut between the two ends is emitted by the compiler, not carried here.
    """

    kind: ClassVar[Kind] = Kind.RELATIONSHIP

    source: SourceRef
    """The source end — ``sem:source``."""

    target: SourceRef
    """The target end — ``sem:target``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TaxonomyValue(SchemeMember):
    """A taxonomy value node — a plain ``skos:Concept`` in a taxonomy scheme (spec 3.2)."""

    kind: ClassVar[Kind] = Kind.TAXONOMY_VALUE

    code: str
    """``skos:notation`` — the business code. Mutable in the source: the ID map keeps the
    IRI stable when it changes (spec 3.4)."""

    parent: SourceRef | None = None
    """The broader value — ``skos:broader``. ``None`` means a top concept."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Scheme(SemanticObject):
    """A glossary or a taxonomy — ``skos:ConceptScheme`` (spec 3.2)."""

    kind: ClassVar[Kind] = Kind.SCHEME

    slug: str
    """Assigned once at scheme creation and opaque thereafter: renaming the glossary does
    not change it (spec 3.4)."""

    scheme_type: SchemeType

    enumerates: str | None = None
    """IRI of the entity whose values this taxonomy provides — ``sem:enumerates``. An
    IRI rather than a ``SourceRef`` because it is configured by hand in the instance
    (spec 5.3); that it exists in the ID map is checked when the graph is built."""

    def __post_init__(self) -> None:
        SemanticObject.__post_init__(self)
        if not self.slug:
            raise ValueError("a scheme must carry a slug")


@dataclass(frozen=True, slots=True)
class InternalModel:
    """What one adapter fetched, or what several adapters fetched taken together.

    Kept as separate tuples per kind rather than one heterogeneous list: every later
    stage works one kind at a time — a file per kind, a namespace per kind — and the type
    checker then knows what it has.
    """

    entities: tuple[Entity, ...] = ()
    attributes: tuple[Attribute, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    schemes: tuple[Scheme, ...] = ()
    taxonomy_values: tuple[TaxonomyValue, ...] = ()

    # The per-kind fields, so that walking every kind is one list to keep in step rather
    # than five call sites that each have to remember a kind added later.
    KIND_FIELDS: ClassVar[tuple[str, ...]] = (
        "entities",
        "attributes",
        "relationships",
        "schemes",
        "taxonomy_values",
    )

    def __post_init__(self) -> None:
        # The same coercion the objects do: an adapter handing over a list would leave
        # the model holding something it can mutate afterwards, and two models built
        # from the same objects would compare unequal for holding list against tuple.
        for name in self.KIND_FIELDS:
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def objects(self) -> tuple[SemanticObject, ...]:
        """Every object, kind by kind.

        A tuple rather than a generator: a property that reads like a collection but
        empties after one pass is a trap for callers that walk it twice.
        """
        return tuple(item for name in self.KIND_FIELDS for item in getattr(self, name))

    def __len__(self) -> int:
        return sum(len(getattr(self, name)) for name in self.KIND_FIELDS)

    def merge(self, other: InternalModel) -> InternalModel:
        """Combine with another model, merging objects that share a source ref."""
        return merge_models(self, other)

    def normalized(self) -> InternalModel:
        """This model with its own duplicates merged and its objects in a stable order.

        An adapter that reports the same object twice — the same entity in two domain
        models, say — is normal, not an error (spec 5.3).
        """
        return merge_models(self)


def merge_models(*models: InternalModel) -> InternalModel:
    """Merge models into one, combining objects that share a source ref (spec 5.2).

    Merging is by identity, not by position: two objects belong together when any source
    ref is common to them, and that relation is followed transitively, so an object known
    to source A and one known to source B become one as soon as a third object ties them
    together. The result is ordered by source ref, so the same inputs in any order give
    the same model — the determinism the generated files inherit (spec 5.5).
    """
    merged = InternalModel(
        entities=_merge_objects([o for m in models for o in m.entities]),
        attributes=_merge_objects([o for m in models for o in m.attributes]),
        relationships=_merge_objects([o for m in models for o in m.relationships]),
        schemes=_merge_objects([o for m in models for o in m.schemes]),
        taxonomy_values=_merge_objects([o for m in models for o in m.taxonomy_values]),
    )
    _check_refs_are_unique_across_kinds(merged)
    return merged


def _merge_objects[ObjectT: SemanticObject](objects: Sequence[ObjectT]) -> tuple[ObjectT, ...]:
    """Group objects of one kind by shared source ref and combine each group."""
    groups: list[list[ObjectT]] = []
    by_ref: dict[SourceRef, int] = {}

    for object_ in objects:
        # Every group this object touches becomes one group: identity is transitive, and
        # an object can be the thing that reveals two earlier ones were always the same.
        refs = object_.refs
        indices = sorted({by_ref[ref] for ref in refs if ref in by_ref})
        if not indices:
            target = len(groups)
            groups.append([object_])
        else:
            target, *absorbed = indices
            groups[target].append(object_)
            for index in absorbed:
                # Only the moved members are re-indexed: the target group's own members
                # already point at it, and re-walking them per arrival would make merging
                # one object reported n times cost n² ref lookups.
                for member in groups[index]:
                    for ref in member.refs:
                        by_ref[ref] = target
                groups[target].extend(groups[index])
                groups[index] = []
        for ref in refs:
            by_ref[ref] = target

    combined = [_combine(group) for group in groups if group]
    return tuple(sorted(combined, key=lambda object_: object_.sort_key))


def _combine[ObjectT: SemanticObject](group: Sequence[ObjectT]) -> ObjectT:
    first, *rest = group
    result = first
    for other in rest:
        result = _combine_pair(result, other)
    return result


def _combine_pair[ObjectT: SemanticObject](first: ObjectT, second: ObjectT) -> ObjectT:
    if type(first) is not type(second):
        raise MergeConflictError(
            f"{first.refs[0]} identifies both a {type(first).__name__} and a "
            f"{type(second).__name__}; one source key is one object"
        )

    # Any, because the combination rules are driven by the field list rather than
    # written out per class: five kinds each gaining fields over time is five places to
    # forget one, and forgetting one here means a merged object silently losing data.
    values: dict[str, Any] = {}
    for descriptor in dataclasses.fields(first):
        name = descriptor.name
        left, right = getattr(first, name), getattr(second, name)
        if name == "source_refs":
            values[name] = _combined_refs(first, second)
        elif name in first.UNION_FIELDS:
            values[name] = tuple(sorted(set(left) | set(right)))
        elif left is None or right is None:
            # One source knowing something the other does not is the ordinary case — a
            # definition in one tool and none in the other. Empty descriptions never
            # reach here: they are already None (spec 5.3).
            values[name] = left if left is not None else right
        elif left != right:
            raise MergeConflictError(
                f"{first.refs[0]} and {second.refs[0]} are the same object but disagree "
                f"about {name}: {left!r} and {right!r}"
            )
        else:
            values[name] = left
    return type(first)(**values)


def _combined_refs(first: SemanticObject, second: SemanticObject) -> Mapping[str, str]:
    combined = dict(first.source_refs)
    for source, key in second.source_refs.items():
        if combined.get(source, key) != key:
            raise MergeConflictError(
                f"source {source!r} gives one object two keys: {combined[source]!r} and {key!r}"
            )
        combined[source] = key
    return combined


def _check_refs_are_unique_across_kinds(model: InternalModel) -> None:
    """No source ref may name objects of two kinds.

    The ID map is keyed by ``(source_name, source_key)`` alone — ``kind`` is a recorded
    column, not part of the key (spec 5.4) — so the same pair used for an entity and for a
    scheme would resolve to one row and one IRI for two different things.
    """
    seen: dict[SourceRef, SemanticObject] = {}
    for object_ in model.objects:
        for ref in object_.refs:
            other = seen.setdefault(ref, object_)
            if other.kind is not object_.kind:
                raise MergeConflictError(
                    f"{ref} identifies both a {other.kind} and a {object_.kind}; "
                    f"the ID map is keyed by source and key alone"
                )


_LANGUAGE_TAG = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*")


@dataclass(frozen=True, slots=True, kw_only=True)
class RunContext:
    """Everything a run knows about the instance it is compiling (spec 5.1, 5.2).

    Handed to every adapter, and deliberately read-only: an adapter reads the instance's
    settings, and mints, writes and fetches nothing it was not configured to (spec 5.2).
    The ID map is **not** here — identity resolution is the core's job.
    """

    base_iri: str
    """Frozen by the namespace lock; every content IRI is minted under it (spec 3.4)."""

    instance_id: str

    repo_root: Path = field(default_factory=Path.cwd)
    """The instance repository. Commands operate on the working directory (spec 5.1)."""

    default_language: str = "en"
    """Applied to ``skos:prefLabel`` and ``skos:definition`` when the graph is built
    (spec 5.5 rule 6). Which tags an instance may configure is still open (spec 11 #5)."""

    only_source: str | None = None
    """``--source <name>``: a partial run, which must skip deprecation outside its
    scope (spec 5.4)."""

    dry_run: bool = False

    def __post_init__(self) -> None:
        if not self.instance_id:
            raise ValueError("an instance id is required")
        if not _LANGUAGE_TAG.fullmatch(self.default_language):
            # An unusable tag would otherwise surface as unparseable Turtle at the end
            # of a long run, rather than as a configuration error at the start.
            raise ValueError(f"not a language tag: {self.default_language!r}")
        # Validates the base IRI the same way the serializer does, at the start of a run
        # rather than when the first file is written.
        serialize.namespaces(self.base_iri)

    @property
    def namespaces(self) -> Mapping[str, str]:
        """The instance's prefix block (spec 3.1)."""
        return serialize.namespaces(self.base_iri)

    def iri(self, kind: Kind, local_name: str) -> str:
        """The IRI a local name has in ``kind``'s namespace.

        Composition only — deciding *which* local name an object gets is identity's job
        (spec 3.4, 5.4), and adapters do neither.
        """
        return f"{self.namespaces[kind.prefix]}{local_name}"

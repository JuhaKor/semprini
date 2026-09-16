"""The internal model adapters return and the core consumes (spec 5.1, 5.2). Every object is a
frozen dataclass with tuple collections and a read-only ``source_refs`` mapping. An object is
identified by its ``(source name, source key)`` pairs, which is what the ID map is keyed by (spec
5.4); cross-references are ``SourceRef``s. Merging unions set-valued fields and raises
``MergeConflictError`` on a scalar disagreement. Throughout this package a frozen dataclass that
holds a mapping declares the field with ``hash=False``: a mapping is unhashable, and the class
must still go in a set. ``__eq__`` is unaffected.
"""

from __future__ import annotations

import dataclasses
import re
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
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
    "IssueError",
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
    "Text",
    "counting_normalizations",
    "is_language_tag",
    "merge_models",
    "normalize_text",
]


class Kind(StrEnum):
    """What a semantic object is, hence which namespace it is minted in (spec 3.1, 5.4)."""

    ENTITY = "entity"
    ATTRIBUTE = "attribute"
    RELATIONSHIP = "relationship"
    SCHEME = "scheme"
    TAXONOMY_VALUE = "taxonomy-value"

    @property
    def prefix(self) -> str:
        """The prefix of the namespace this kind is minted in (spec 3.1)."""
        return _KIND_PREFIXES[self]


# Entities and attributes share `c:` (spec 3.1).
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
    """One problem found while validating configuration or content (spec 5.2, 6.1)."""

    severity: Severity
    message: str
    location: str | None = None
    """Where the problem is: a config key, a file and row, a source key."""

    def __str__(self) -> str:
        where = f" ({self.location})" if self.location else ""
        return f"{self.severity}: {self.message}{where}"

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """A total order over issues: location, message, then severity, so that set
        iteration order never reaches a report."""
        return (self.location or "", self.message, self.severity)


class IssueError(ValueError):
    """An error that carries every :class:`Issue` behind it, not just the first.

    Subclasses differ only in ``noun`` and in the exit code the CLI maps them to (spec 5.1).
    """

    noun: ClassVar[str] = "error"
    """What the plural line calls them, as in "3 configuration errors"."""

    def __init__(self, issues: Sequence[Issue], *, origin: str | None = None) -> None:
        self.issues = tuple(issues)
        self.origin = origin
        """The file the issues are about, where one file is responsible for all of them."""
        super().__init__(self._message())

    def _message(self) -> str:
        where = f"{self.origin}: " if self.origin else ""
        if len(self.issues) == 1:
            return f"{where}{self.issues[0]}"
        listed = "\n".join(f"  - {issue}" for issue in self.issues)
        return f"{where}{len(self.issues)} {self.noun}s\n{listed}"


_SPACES = frozenset(
    "\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005"
    "\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
)
"""Every character of Unicode category ``Zs``, ``Zl`` or ``Zp``; ``test_model.py`` re-derives it."""

_REMOVED = frozenset("\u200b\ufeff\u00ad")
"""Zero-width space, zero-width no-break space and the soft hyphen: deleted, not spaced.

U+200C and U+200D are not here; the zero-width joiners carry meaning in several scripts.
"""

_TRANSLATION: Mapping[int, str | None] = {
    **{ord(character): " " for character in _SPACES},
    **{ord(character): None for character in _REMOVED},
}

_NORMALIZATIONS: ContextVar[list[int] | None] = ContextVar("_NORMALIZATIONS", default=None)


def normalize_text(value: str) -> str:
    """Text as the compiler holds it: NFC, ordinary spaces, no invisible characters, stripped.

    Applied to every text and every source key on the way in (spec 5.5 rule 9), in that
    order so that it is idempotent. Not NFKC. Leaves interior whitespace runs, tabs,
    newlines and the non-breaking hyphen alone: they are content.
    """
    normalized = unicodedata.normalize("NFC", value).translate(_TRANSLATION)
    if normalized != value:
        tally = _NORMALIZATIONS.get()
        if tally is not None:
            tally[0] += 1
    return normalized.strip()


@contextmanager
def counting_normalizations() -> Iterator[list[int]]:
    """Count the values :func:`normalize_text` changed inside the block, for the run report (spec
    5.6).

    Report-only; the output does not depend on whether anyone counts.
    """
    tally = [0]
    token = _NORMALIZATIONS.set(tally)
    try:
        yield tally
    finally:
        _NORMALIZATIONS.reset(token)


@dataclass(frozen=True, slots=True, order=True)
class SourceRef:
    """One source's key for an object: the pair the ID map is keyed by (spec 5.4).

    Its string form is the value of ``sem:sourceRef`` (spec 3.3).
    """

    source: str
    """The source's configured ``name`` (spec 5.1)."""

    key: str
    """The key that source uses for the object: a UUID, a code, a slug."""

    def __post_init__(self) -> None:
        # Normalized before emptiness is judged (spec 5.5 rule 9). The source name is a
        # slug already validated by configuration loading.
        object.__setattr__(self, "key", normalize_text(self.key))
        if not self.source or not self.key:
            raise ValueError(f"a source ref needs both a source name and a key, got {self!r}")
        if ":" in self.source:
            raise ValueError(f"a source name may not contain ':', got {self.source!r}")

    def __str__(self) -> str:
        return f"{self.source}:{self.key}"


@dataclass(frozen=True, slots=True)
class Text:
    """A label, definition or note, and the language it is written in (spec 5.5 rule 6).

    A plain ``str`` is accepted wherever a ``Text`` is and becomes ``Text(value)``.
    ``language=None`` means the source did not say; the instance's default is applied when
    the graph is built (spec 11 #5). Two texts differing only in language are not equal,
    so a scalar field holding one label per language is a merge conflict: a known v1 limit.
    """

    value: str
    language: str | None = None

    def __post_init__(self) -> None:
        # The one place every text passes through (spec 5.5 rule 9).
        object.__setattr__(self, "value", normalize_text(self.value))
        if not self.value:
            # Callers decide absence on the normalized value first (spec 5.3).
            raise ValueError("text must not be empty")
        if self.language is not None and not is_language_tag(self.language):
            raise ValueError(f"not a language tag: {self.language!r}")

    def __str__(self) -> str:
        return self.value

    @property
    def sort_key(self) -> tuple[str, str]:
        """A total order over texts, tagged and untagged alike."""
        return (self.value, self.language or "")


def _as_text(value: str | Text) -> Text:
    return value if isinstance(value, Text) else Text(value)


def _has_content(value: str | Text) -> bool:
    """Whether a value survives normalization as something worth emitting (spec 5.5 rule 9)."""
    return True if isinstance(value, Text) else bool(normalize_text(value))


def _as_optional_text(value: str | Text | None) -> Text | None:
    """Normalize to a text or to absent, treating empty as absent (spec 5.3)."""
    if value is None:
        return None
    return _as_text(value) if _has_content(value) else None


def _as_texts(values: Sequence[str | Text]) -> tuple[Text, ...]:
    """Normalize a set-valued text field, dropping empties rather than emitting them."""
    return tuple(_as_text(value) for value in values if _has_content(value))


def _union_sort_key(value: object) -> tuple[str, str]:
    """Order a set-valued field's members, whether they are texts or plain strings."""
    return value.sort_key if isinstance(value, Text) else (str(value), "")


class MergeConflictError(ValueError):
    """Two sources describe one object and disagree about a value; the compiler never picks a side
    (spec 1.2).
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticObject:
    """Fields every semantic object carries, whatever its kind. Keyword-only, so that
    adding a field breaks no adapter (spec 5.2)."""

    kind: ClassVar[Kind]

    # Field names whose values union on merge instead of having to agree.
    UNION_FIELDS: ClassVar[tuple[str, ...]] = (
        "alt_labels",
        "hidden_labels",
        "scope_notes",
        "examples",
    )

    source_refs: Mapping[str, str] = field(hash=False)
    """Source name → that source's key. Several entries resolve to one IRI (spec 5.2)."""

    pref_label: str | Text
    """``skos:prefLabel``. A plain string carries no language of its own (spec 5.5 rule 6)."""

    definition: str | Text | None = None
    """``skos:definition``. ``None`` and empty both emit no triple (spec 5.3)."""

    alt_labels: tuple[str | Text, ...] = ()
    """``skos:altLabel``."""

    hidden_labels: tuple[str | Text, ...] = ()
    """``skos:hiddenLabel``."""

    scope_notes: tuple[str | Text, ...] = ()
    """``skos:scopeNote``."""

    examples: tuple[str | Text, ...] = ()
    """``skos:example``. Set-valued, unlike ``definition`` (spec 3.3)."""

    def __post_init__(self) -> None:
        if not self.source_refs:
            raise ValueError(f"{type(self).__name__} must carry at least one source ref")
        if not _has_content(self.pref_label):
            # Judged after normalization, so the message names the object (spec 5.5 rule 9).
            raise ValueError(f"{type(self).__name__} must carry a prefLabel")
        # Rebuilt from SourceRefs so that the mapping holds the normalized keys too.
        refs = [SourceRef(source, key) for source, key in self.source_refs.items()]
        object.__setattr__(
            self, "source_refs", MappingProxyType({ref.source: ref.key for ref in refs})
        )
        object.__setattr__(self, "pref_label", _as_text(self.pref_label))
        for name in ("alt_labels", "hidden_labels", "scope_notes", "examples"):
            object.__setattr__(self, name, _as_texts(getattr(self, name)))
        # Empty and absent are one state: neither emits a triple (spec 5.3).
        object.__setattr__(self, "definition", _as_optional_text(self.definition))

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

    UNION_FIELDS: ClassVar[tuple[str, ...]] = (*SemanticObject.UNION_FIELDS, "schemes")

    schemes: tuple[str, ...] = ()
    """Slugs of the schemes this object is in: ``skos:inScheme`` (spec 5.3)."""

    def __post_init__(self) -> None:
        # Explicit rather than super(): @dataclass(slots=True) rebuilds the class.
        SemanticObject.__post_init__(self)
        object.__setattr__(self, "schemes", tuple(self.schemes))


@dataclass(frozen=True, slots=True, kw_only=True)
class Entity(SchemeMember):
    """A business entity or concept — ``sem:Entity`` (spec 3.2)."""

    kind: ClassVar[Kind] = Kind.ENTITY

    UNION_FIELDS: ClassVar[tuple[str, ...]] = (*SchemeMember.UNION_FIELDS, "broader")

    broader: tuple[SourceRef, ...] = ()
    """Entities this one specializes: ``skos:broader`` (spec 3.3). Set-valued and unioned
    on merge, like scheme membership (spec 5.3)."""

    def __post_init__(self) -> None:
        SchemeMember.__post_init__(self)
        object.__setattr__(self, "broader", tuple(self.broader))
        if any(ref in self.refs for ref in self.broader):
            raise ValueError(f"{self.refs[0]} cannot be broader than itself")


@dataclass(frozen=True, slots=True, kw_only=True)
class Attribute(SchemeMember):
    """An attribute with its own identity — ``sem:Attribute`` (spec 3.2)."""

    kind: ClassVar[Kind] = Kind.ATTRIBUTE

    entity: SourceRef
    """The entity this is an attribute of: ``sem:attributeOf``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Relationship(SchemeMember):
    """A named relationship between two entities — ``sem:Relationship`` (spec 3.2).

    The ``sem:relatesTo`` shortcut between the ends is emitted by the compiler, not carried here.
    """

    kind: ClassVar[Kind] = Kind.RELATIONSHIP

    source: SourceRef
    """The source end: ``sem:source``."""

    target: SourceRef
    """The target end: ``sem:target``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TaxonomyValue(SchemeMember):
    """A taxonomy value node — a plain ``skos:Concept`` in a taxonomy scheme (spec 3.2)."""

    kind: ClassVar[Kind] = Kind.TAXONOMY_VALUE

    code: str | None = None
    """``skos:notation``, when the source states one. Never part of identity (spec 3.4)."""

    parent: SourceRef | None = None
    """The broader value: ``skos:broader``. ``None`` means a top concept."""

    def __post_init__(self) -> None:
        SchemeMember.__post_init__(self)
        # A code is not a Text (spec 5.5 rule 6) but is normalized like one.
        object.__setattr__(self, "code", (normalize_text(self.code) if self.code else "") or None)


@dataclass(frozen=True, slots=True, kw_only=True)
class Scheme(SemanticObject):
    """A glossary or a taxonomy — ``skos:ConceptScheme`` (spec 3.2)."""

    kind: ClassVar[Kind] = Kind.SCHEME

    slug: str
    """Assigned once at scheme creation and opaque thereafter (spec 3.4)."""

    scheme_type: SchemeType

    enumerates: SourceRef | None = None
    """The entity whose values this taxonomy provides: ``sem:enumerates`` (spec 5.3).
    Resolved, and checked to name an entity, when the graph is built."""

    def __post_init__(self) -> None:
        SemanticObject.__post_init__(self)
        if not self.slug:
            raise ValueError("a scheme must carry a slug")


@dataclass(frozen=True, slots=True)
class InternalModel:
    """What one adapter fetched, or several taken together, one tuple per kind."""

    entities: tuple[Entity, ...] = ()
    attributes: tuple[Attribute, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    schemes: tuple[Scheme, ...] = ()
    taxonomy_values: tuple[TaxonomyValue, ...] = ()

    KIND_FIELDS: ClassVar[tuple[str, ...]] = (
        "entities",
        "attributes",
        "relationships",
        "schemes",
        "taxonomy_values",
    )

    def __post_init__(self) -> None:
        for name in self.KIND_FIELDS:
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def objects(self) -> tuple[SemanticObject, ...]:
        """Every object, kind by kind."""
        return tuple(item for name in self.KIND_FIELDS for item in getattr(self, name))

    def __len__(self) -> int:
        return sum(len(getattr(self, name)) for name in self.KIND_FIELDS)

    def merge(self, other: InternalModel) -> InternalModel:
        """Combine with another model, merging objects that share a source ref."""
        return merge_models(self, other)

    def normalized(self) -> InternalModel:
        """This model with its own duplicates merged and its objects
        in a stable order (spec 5.3).
        """
        return merge_models(self)


def merge_models(*models: InternalModel) -> InternalModel:
    """Merge models into one, combining objects that share a source ref (spec 5.2).

    Shared refs are followed transitively. The result is ordered by source ref, so the
    same inputs in any order give the same model (spec 5.5).
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
        # Every group this object touches becomes one group.
        refs = object_.refs
        indices = sorted({by_ref[ref] for ref in refs if ref in by_ref})
        if not indices:
            target = len(groups)
            groups.append([object_])
        else:
            target, *absorbed = indices
            groups[target].append(object_)
            for index in absorbed:
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

    values: dict[str, Any] = {}
    for descriptor in dataclasses.fields(first):
        name = descriptor.name
        left, right = getattr(first, name), getattr(second, name)
        if name == "source_refs":
            values[name] = _combined_refs(first, second)
        elif name in first.UNION_FIELDS:
            values[name] = tuple(sorted(set(left) | set(right), key=_union_sort_key))
        elif left is None or right is None:
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
    """No source ref may name objects of two kinds: the ID map is keyed by the pair alone (spec
    5.4).
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


def is_language_tag(value: str) -> bool:
    """Whether ``value`` is a well-formed BCP 47 tag. Well-formed, not registered (spec 11 #5)."""
    return _LANGUAGE_TAG.fullmatch(value) is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class RunContext:
    """Everything a run knows about the instance it is compiling (spec 5.1, 5.2).

    Handed read-only to every adapter. The ID map is not here.
    """

    base_iri: str
    """Frozen by the namespace lock (spec 3.4)."""

    instance_id: str

    repo_root: Path = field(default_factory=Path.cwd)
    """The instance repository (spec 5.1)."""

    default_language: str = "en"
    """Applied to every text that carries no language of its own (spec 5.5 rule 6, 11 #5)."""

    dry_run: bool = False

    def __post_init__(self) -> None:
        if not self.instance_id:
            raise ValueError("an instance id is required")
        if not is_language_tag(self.default_language):
            raise ValueError(f"not a language tag: {self.default_language!r}")
        # The serializer's own base-IRI check, at the start of the run.
        serialize.namespaces(self.base_iri)

    @property
    def namespaces(self) -> Mapping[str, str]:
        """The instance's prefix block (spec 3.1)."""
        return serialize.namespaces(self.base_iri)

    def iri(self, kind: Kind, local_name: str) -> str:
        """The IRI a local name has in ``kind``'s namespace. Composition only (spec 3.4, 5.4)."""
        return f"{self.namespaces[kind.prefix]}{local_name}"

"""Bundled Ellie adapter (spec 5.3).

Reads domain models exported from one Ellie instance as JSON, one file per model, the
body of ``GET /api/v1/models/{id}``. One Ellie instance is one configured source, since
entity UUIDs are unique across an instance and the same entity may appear in several
models. The ``models:`` list is an allowlist; a listed model that cannot be read fails
the run, and a file whose ``modelId`` disagrees with its entry is refused.

Two mappings are decisions rather than transcriptions. A supertype relationship, which
Ellie gives no name or labels, becomes ``skos:broader`` between its ends rather than a
``sem:Relationship`` (spec 3.3). Metadata the metamodel cannot hold, such as
``progressStatus`` and an attribute's ``Data type``, is not carried (spec 3.1, 3.3).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from semprini.adapters.base import AdapterError, BaseAdapter, SourceUnreachableError
from semprini.config import ConfigError, escapes_the_instance, is_slug
from semprini.model import (
    Attribute,
    Entity,
    InternalModel,
    Issue,
    MergeConflictError,
    Relationship,
    Scheme,
    SchemeType,
    Severity,
    SourceRef,
    normalize_text,
)

__all__ = ["EllieAdapter", "EllieContentError"]

_SETTINGS = frozenset({"base_url", "models"})
_MODEL_SETTINGS = frozenset({"id", "path", "scheme_slug"})

# The end types that mark a relationship as inheritance (spec 5.3).
_SUPERTYPE = "superType"
_SUBTYPE = "subType"

# The metadata this adapter reads; anything else in `metadata` is ignored.
_DESCRIPTION = "Description"
_SYNONYMS = "Synonyms"
_EXAMPLES = "Examples"

_SOURCE = "source"
"""The one label direction that reads target → source. Everything else, an absent
direction included, reads source → target."""


class EllieContentError(AdapterError):
    """An export was read but says something the compiler cannot act on — exit code 1 (spec 5.1).

    Collects every problem across every configured model.
    """

    def __init__(self, issues: Sequence[Issue]) -> None:
        self.issues = tuple(issues)
        if len(self.issues) == 1:
            super().__init__(str(self.issues[0]))
            return
        listed = "\n".join(f"  - {issue}" for issue in self.issues)
        super().__init__(f"{len(self.issues)} problems\n{listed}")


@dataclass(frozen=True, slots=True)
class _ModelEntry:
    """One allowlisted model, as configured."""

    model_id: str
    path: str
    slug: str


@dataclass(frozen=True, slots=True)
class _ModelRead:
    """What one export turned out to hold, for the run report (spec 5.6)."""

    model_id: str
    name: str
    entities: int
    attributes: int
    relationships: int


class EllieAdapter(BaseAdapter):
    """An Ellie instance: exported domain models, one concept scheme each.

    The line above is what ``semprini adapters`` prints beside this adapter's name.

    Settings:

    ``base_url``
        The Ellie instance these models were exported from, such as
        ``https://<slug>.ellie.ai/api/v1``. Recorded, not called; it appears in the run report.
    ``models``
        The allowlist. Each entry carries ``id`` (Ellie's model id), ``path`` (the exported
        JSON, relative to the instance repository) and ``scheme_slug`` (the permanent slug
        of the scheme the model becomes).
    """

    name = "ellie"

    _read: tuple[_ModelRead, ...] = ()
    """What the last fetch read, for :meth:`summary`."""

    # --------------------------------------------------------------------- the contract

    def fetch(self) -> InternalModel:
        # Spec 5.3: an adapter validates its own settings before reading anything.
        issues = [issue for issue in self.validate_config() if issue.severity is Severity.ERROR]
        if issues:
            raise ConfigError(issues)

        problems: list[Issue] = []
        parts: list[InternalModel] = []
        read: list[_ModelRead] = []
        for entry in self._entries():
            try:
                document = self._document(entry)
            except EllieContentError as error:
                # Batched; SourceUnreachableError is not caught (spec 5.1).
                problems.extend(error.issues)
                continue
            part = _read_model(document, source=self.source_name, entry=entry, issues=problems)
            if part is not None:
                parts.append(part.model)
                read.append(part.summary)
        if problems:
            raise EllieContentError(problems)

        model = InternalModel(
            entities=tuple(o for part in parts for o in part.entities),
            attributes=tuple(o for part in parts for o in part.attributes),
            relationships=tuple(o for part in parts for o in part.relationships),
            schemes=tuple(o for part in parts for o in part.schemes),
        )
        self._read = tuple(read)
        try:
            # An entity in several models is one object with several schemes (spec 5.3).
            return model.normalized()
        except MergeConflictError as error:
            raise EllieContentError(
                [
                    Issue(
                        Severity.ERROR,
                        f"two exported models describe one object differently: {error}",
                        self.source_name,
                    )
                ]
            ) from error

    def validate_config(self) -> list[Issue]:
        issues: list[Issue] = []
        where = f"sources.{self.source_name}.config"

        base_url = self.config.get("base_url")
        if not base_url:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "an Ellie source needs a 'base_url' naming the instance its UUIDs "
                    "belong to, e.g. https://acme.ellie.ai/api/v1",
                    f"{where}.base_url",
                )
            )
        elif not str(base_url).startswith(("http://", "https://")):
            issues.append(Issue(Severity.ERROR, f"not a URL: {base_url!r}", f"{where}.base_url"))

        self._validate_models(where, issues)
        for key in sorted(set(self.config) - _SETTINGS):
            issues.append(
                Issue(Severity.ERROR, f"unknown setting {key!r}", f"{where}.{key}")
                if key != "token_env"
                else Issue(
                    Severity.ERROR,
                    "this adapter reads exported files and does not call the API yet, so "
                    "'token_env' would configure nothing; remove it until the API mode "
                    "ships",
                    f"{where}.token_env",
                )
            )
        return issues

    def summary(self) -> str:
        if not self._read:
            return ""
        models = "; ".join(
            f"{item.model_id} {item.name!r} ({item.entities} entities, "
            f"{item.attributes} attributes, {item.relationships} relationships)"
            for item in self._read
        )
        return f"{self.config['base_url']}: {models}"

    # ------------------------------------------------------------------------ internals

    def _validate_models(self, where: str, issues: list[Issue]) -> None:
        models = self.config.get("models")
        if not models:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "an Ellie source needs a 'models' list; nothing is read that is not "
                    "listed (spec 5.3)",
                    f"{where}.models",
                )
            )
            return
        if isinstance(models, str) or not isinstance(models, Sequence):
            issues.append(Issue(Severity.ERROR, "'models' must be a list", f"{where}.models"))
            return

        seen_ids: dict[str, int] = {}
        seen_slugs: dict[str, int] = {}
        for index, model in enumerate(models):
            at = f"{where}.models[{index}]"
            if not isinstance(model, Mapping):
                issues.append(Issue(Severity.ERROR, "each model must be a mapping", at))
                continue

            model_id = model.get("id")
            if _plain(model_id) == "":
                issues.append(Issue(Severity.ERROR, "a model needs Ellie's 'id'", f"{at}.id"))
            else:
                # Compared as normalized text on both sides: it is the scheme's source key (spec
                # 5.4).
                first = seen_ids.setdefault(_plain(model_id), index)
                if first != index:
                    issues.append(
                        Issue(
                            Severity.ERROR,
                            f"model id {model_id!r} is already listed at models[{first}]",
                            f"{at}.id",
                        )
                    )

            path = model.get("path")
            if not path:
                issues.append(
                    Issue(
                        Severity.ERROR,
                        "a model needs a 'path' to its exported JSON",
                        f"{at}.path",
                    )
                )
            elif escapes_the_instance(str(path)):
                issues.append(
                    Issue(
                        Severity.ERROR,
                        f"path must be inside the instance repository, got {path!r}",
                        f"{at}.path",
                    )
                )

            slug = model.get("scheme_slug")
            if not slug:
                issues.append(
                    Issue(Severity.ERROR, "a model needs a 'scheme_slug'", f"{at}.scheme_slug")
                )
            elif not is_slug(str(slug)):
                issues.append(
                    Issue(
                        Severity.ERROR,
                        f"not a slug: {slug!r} (lower-case letters, digits, '-' and '_')",
                        f"{at}.scheme_slug",
                    )
                )
            else:
                first = seen_slugs.setdefault(str(slug), index)
                if first != index:
                    issues.append(
                        Issue(
                            Severity.ERROR,
                            f"scheme slug {slug!r} is already used by models[{first}]",
                            f"{at}.scheme_slug",
                        )
                    )

            for key in sorted(set(model) - _MODEL_SETTINGS):
                issues.append(Issue(Severity.ERROR, f"unknown setting {key!r}", f"{at}.{key}"))

    def _entries(self) -> tuple[_ModelEntry, ...]:
        """The allowlist, after :meth:`validate_config` has passed."""
        models: Sequence[Mapping[str, Any]] = self.config["models"]
        return tuple(
            _ModelEntry(
                model_id=_plain(model["id"]),
                path=str(model["path"]),
                slug=str(model["scheme_slug"]),
            )
            for model in models
        )

    def _document(self, entry: _ModelEntry) -> Mapping[str, Any]:
        """One export, read and unwrapped."""
        path = self.ctx.repo_root / entry.path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            # Exit 3; a listed model that cannot be read fails the run (spec 5.3).
            raise SourceUnreachableError(
                f"source {self.source_name!r}: cannot read model {entry.model_id} "
                f"at {path}: {error}"
            ) from error
        except UnicodeDecodeError as error:
            raise EllieContentError(
                [Issue(Severity.ERROR, f"not UTF-8 text: {error}", entry.path)]
            ) from error

        try:
            document = json.loads(text)
        except json.JSONDecodeError as error:
            raise EllieContentError(
                [Issue(Severity.ERROR, f"not readable JSON: {error}", entry.path)]
            ) from error
        return _unwrap(document, entry)


def _unwrap(document: Any, entry: _ModelEntry) -> Mapping[str, Any]:
    """The model object, whether or not the export wraps it in ``model``.

    A document that is neither shape is refused rather than read as an empty model (spec 5.4).
    """
    if not isinstance(document, Mapping):
        raise EllieContentError(
            [
                Issue(
                    Severity.ERROR,
                    f"the export is a JSON {type(document).__name__}, not an object",
                    entry.path,
                )
            ]
        )
    if "modelId" in document or "entities" in document:
        return document
    inner = document.get("model")
    if isinstance(inner, Mapping):
        return inner
    found = ", ".join(sorted(str(key) for key in document)) or "no keys at all"
    raise EllieContentError(
        [
            Issue(
                Severity.ERROR,
                f"the export holds neither a model nor a 'model' wrapper around one; found {found}",
                entry.path,
            )
        ]
    )


# ------------------------------------------------------------------------- the export


@dataclass(frozen=True, slots=True)
class _Part:
    model: InternalModel
    summary: _ModelRead


def _read_model(
    document: Mapping[str, Any],
    *,
    source: str,
    entry: _ModelEntry,
    issues: list[Issue],
) -> _Part | None:
    """One export as internal-model objects, or ``None`` if it cannot be read at all."""
    where = entry.path
    stated = _plain(document.get("modelId"))
    if stated != entry.model_id:
        issues.append(
            Issue(
                Severity.ERROR,
                f"this export is model {stated or '(none stated)'}, but the configuration "
                f"lists it as {entry.model_id}",
                where,
            )
        )
        return None

    name = _plain(document.get("name"))
    if not name:
        issues.append(Issue(Severity.ERROR, f"model {entry.model_id} has no name", where))
        return None

    if "entities" not in document:
        # An empty list is an empty model; an absent key is a truncated file (spec 5.4).
        issues.append(
            Issue(
                Severity.ERROR,
                f"model {entry.model_id} states no 'entities' at all; an export of an "
                f"empty model states an empty list, so this file looks truncated",
                where,
            )
        )
        return None

    scheme = Scheme(
        # Keyed by Ellie's model id, not the slug (spec 5.4).
        source_refs={source: entry.model_id},
        pref_label=name,
        definition=_plain(document.get("description")) or None,
        slug=entry.slug,
        scheme_type=SchemeType.GLOSSARY,
    )

    relationships, broader = _read_relationships(
        document, source=source, entry=entry, issues=issues
    )
    entities, attributes = _read_entities(
        document, source=source, entry=entry, broader=broader, issues=issues
    )
    return _Part(
        model=InternalModel(
            entities=entities,
            attributes=attributes,
            relationships=relationships,
            schemes=(scheme,),
        ),
        summary=_ModelRead(
            model_id=entry.model_id,
            name=name,
            entities=len(entities),
            attributes=len(attributes),
            relationships=len(relationships),
        ),
    )


def _read_relationships(
    document: Mapping[str, Any],
    *,
    source: str,
    entry: _ModelEntry,
    issues: list[Issue],
) -> tuple[tuple[Relationship, ...], Mapping[str, tuple[SourceRef, ...]]]:
    """The model's relationships, with inheritance separated out as ``skos:broader`` per narrower
    entity.
    """
    relationships: list[Relationship] = []
    broader: dict[str, list[SourceRef]] = {}
    for index, raw in enumerate(_items(document, "relationships", entry, issues)):
        where = f"{entry.path}#relationships[{index}]"
        key = _plain(raw.get("id"))
        source_end = _mapping(raw.get("sourceEntity"))
        target_end = _mapping(raw.get("targetEntity"))
        source_id = _plain(source_end.get("id"))
        target_id = _plain(target_end.get("id"))
        if not key or not source_id or not target_id:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "a relationship needs an 'id' and both entity ends",
                    where,
                )
            )
            continue

        if _plain(source_end.get("startType")) == _SUPERTYPE or (
            _plain(target_end.get("endType")) == _SUBTYPE
        ):
            # Inheritance: the target is a specialization of the source (spec 3.3).
            if source_id == target_id:
                issues.append(Issue(Severity.ERROR, f"{source_id} is its own supertype", where))
                continue
            broader.setdefault(target_id, []).append(SourceRef(source, source_id))
            continue

        labels = _labels(raw)
        forward = [label for label, direction in labels if direction.casefold() != _SOURCE]
        # Ellie's own `name` when a modeller filled it in; the forward verb otherwise.
        preferred = _plain(raw.get("name")) or (forward[0] if forward else "")
        if not preferred:
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"relationship {key} has neither a name nor a label reading from "
                    f"source to target, so it has no preferred label",
                    where,
                )
            )
            continue
        relationships.append(
            Relationship(
                source_refs={source: key},
                pref_label=preferred,
                definition=_plain(raw.get("description")) or None,
                alt_labels=tuple(label for label, _ in labels if label != preferred),
                schemes=(entry.slug,),
                source=SourceRef(source, source_id),
                target=SourceRef(source, target_id),
            )
        )
    return tuple(relationships), {key: tuple(refs) for key, refs in broader.items()}


def _read_entities(
    document: Mapping[str, Any],
    *,
    source: str,
    entry: _ModelEntry,
    broader: Mapping[str, tuple[SourceRef, ...]],
    issues: list[Issue],
) -> tuple[tuple[Entity, ...], tuple[Attribute, ...]]:
    entities: list[Entity] = []
    attributes: list[Attribute] = []
    held: set[str] = set()
    for index, raw in enumerate(_items(document, "entities", entry, issues)):
        where = f"{entry.path}#entities[{index}]"
        key = _plain(raw.get("id"))
        name = _plain(raw.get("name"))
        if not key or not name:
            issues.append(Issue(Severity.ERROR, "an entity needs an 'id' and a 'name'", where))
            continue
        metadata = _mapping(raw.get("metadata"))
        held.add(key)
        entities.append(
            Entity(
                source_refs={source: key},
                pref_label=name,
                definition=_plain(metadata.get(_DESCRIPTION)) or None,
                alt_labels=_synonyms(metadata.get(_SYNONYMS)),
                # Unsplit, unlike the synonyms: Examples is one prose cell.
                examples=tuple(filter(None, (_plain(metadata.get(_EXAMPLES)),))),
                schemes=(entry.slug,),
                broader=broader.get(key, ()),
            )
        )
        attributes.extend(
            _read_attributes(raw, source=source, entry=entry, owner=key, issues=issues)
        )
    # A supertype relationship whose narrower entity the model does not hold is carried by
    # nothing, so nothing downstream would notice it.
    for orphan in sorted(set(broader) - held):
        issues.append(
            Issue(
                Severity.ERROR,
                f"a supertype relationship makes {orphan} a specialization, but the model "
                f"holds no such entity",
                entry.path,
            )
        )
    return tuple(entities), tuple(attributes)


def _read_attributes(
    entity: Mapping[str, Any],
    *,
    source: str,
    entry: _ModelEntry,
    owner: str,
    issues: list[Issue],
) -> list[Attribute]:
    """One entity's attributes as ``sem:Attribute`` nodes (spec 3.2). Only ``Description`` is
    carried.
    """
    attributes: list[Attribute] = []
    raw_attributes = entity.get("attributes")
    if not isinstance(raw_attributes, Sequence) or isinstance(raw_attributes, str):
        return attributes
    for index, raw in enumerate(raw_attributes):
        where = f"{entry.path}#entities.{owner}.attributes[{index}]"
        if not isinstance(raw, Mapping):
            issues.append(Issue(Severity.ERROR, "an attribute must be an object", where))
            continue
        key = _plain(raw.get("id"))
        name = _plain(raw.get("name"))
        if not key or not name:
            issues.append(Issue(Severity.ERROR, "an attribute needs an 'id' and a 'name'", where))
            continue
        metadata = _mapping(raw.get("metadata"))
        attributes.append(
            Attribute(
                source_refs={source: key},
                pref_label=name,
                definition=_plain(metadata.get(_DESCRIPTION)) or None,
                schemes=(entry.slug,),
                entity=SourceRef(source, owner),
            )
        )
    return attributes


def _items(
    document: Mapping[str, Any], key: str, entry: _ModelEntry, issues: list[Issue]
) -> list[Mapping[str, Any]]:
    """A top-level array of objects. Missing is empty; malformed is refused."""
    raw = document.get(key)
    if raw is None:
        return []
    if isinstance(raw, str) or not isinstance(raw, Sequence):
        issues.append(Issue(Severity.ERROR, f"{key!r} is not a list", entry.path))
        return []
    items: list[Mapping[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            issues.append(
                Issue(Severity.ERROR, "expected an object", f"{entry.path}#{key}[{index}]")
            )
            continue
        items.append(item)
    return items


def _labels(relationship: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """The relationship's verb phrases as ``(name, direction)``, in the export's order."""
    raw = relationship.get("labels")
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        return ()
    labels: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = _plain(item.get("name"))
        if name:
            labels.append((name, _plain(item.get("direction"))))
    return tuple(labels)


def _synonyms(raw: object) -> tuple[str, ...]:
    """``"Shipment, Dispatch, Consignment"`` → three ``skos:altLabel``s."""
    text = _plain(raw)
    if not text:
        return ()
    return tuple(part for part in (piece.strip() for piece in text.split(",")) if part)


def _mapping(value: object) -> Mapping[str, Any]:
    """A nested JSON object, or an empty one where the export omitted it."""
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _plain(value: object) -> str:
    """A JSON scalar as normalized text (spec 5.5 rule 9); ``null``
    and absent both become ``""``.
    """
    if value is None:
        return ""
    return normalize_text(str(value))

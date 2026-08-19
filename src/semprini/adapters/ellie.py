"""Bundled Ellie adapter (spec 5.3).

Reads domain models **exported** from an Ellie instance as JSON — one file per model,
committed under ``sources/ellie/`` and reviewed with the instance like any other source.
A direct call to Ellie's REST API is a later mode of this same adapter, and deliberately
not a second adapter: identity is keyed by ``(source name, Ellie UUID)``, so a source that
switched adapters would re-mint every IRI it owns (spec 5.4). The exported document is the
response body of ``GET /api/v1/models/{id}``, which is why the switch will change how the
bytes arrive and nothing about what they mean.

**One Ellie instance is one configured source.** Entity UUIDs are unique across an
instance, not within a model — that is precisely what lets the same entity appear in two
domain models and resolve to one node with two ``skos:inScheme`` triples (spec 5.3). So
the models of one instance must share a source name, or the same entity would take two
identities; and two Ellie instances must *not*, or their UUID spaces would be assumed to
be one. This is the opposite arrangement to the Excel adapter, and for the opposite
reason: a workbook's keys are unique only within the file.

**The allowlist is the ``models:`` list.** Nothing is read that is not listed, and a
listed model that cannot be read fails the run rather than being skipped, because a model
that silently went missing would look exactly like a model whose contents were all deleted
— and the compiler would deprecate every object in it (spec 5.4). Each entry states the
model's Ellie ``id`` as well as its ``path``, and a file whose ``modelId`` disagrees is
refused: an export copied over the wrong file is otherwise a scheme quietly changing what
it contains.

Two mappings are worth stating here because they are decisions rather than transcriptions:

*Inheritance becomes ``skos:broader``.* Ellie draws a supertype relationship as an
ordinary relationship whose ends are typed ``superType``/``subType`` — and gives it no
name and no verb labels. Reifying it as a ``sem:Relationship`` would mean inventing a
label no modeller wrote; ``skos:broader`` between the two entities says exactly the fact
the modeller stated, using a reused SKOS term that costs the metamodel no new vocabulary
(spec 3.3).

*Only what the metamodel can hold is carried.* ``progressStatus``, ``Source systems``,
``Administrated by``, relationship cardinality and the attribute metadata beyond
``Description`` are read by nobody yet. Each would need a term that does not exist, and
inventing one per Ellie field is what the removal of ``sem:ellieId`` ruled out (spec 3.3).
They are deferred rather than dismissed — an attribute's ``Data type`` and ``Semantic
link`` in particular are what ``sem:represents`` is reserved for (spec 3.1).
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

# The cardinality values that mean inheritance rather than an association. Ellie states
# them on the two ends of an otherwise ordinary relationship (spec 5.3).
_SUPERTYPE = "superType"
_SUBTYPE = "subType"

# Entity and attribute metadata this adapter reads. Everything else in `metadata` is
# tolerated and ignored: an export is a working document that gains fields with each
# release of the tool, so an unknown one is not an error the way an unknown *config* key
# is (spec 5.1).
_DESCRIPTION = "Description"
_SYNONYMS = "Synonyms"
_EXAMPLES = "Examples"

_SOURCE = "source"
"""The one label direction that reads *backwards*, target → source — "Order line *is part
of* Order". Everything else, ``"target"`` included and an absent direction with it, reads
source → target. Stated as the exception rather than as a list of accepted values on
purpose: a relationship carrying a single label often omits `direction` altogether, and
holding out for the literal string ``"target"`` would discard the only verb the modeller
wrote and then fail the run for having no label."""


class EllieContentError(AdapterError):
    """An export was read but says something the compiler cannot act on.

    Exit code 1, not 3: the file was perfectly readable and its content is wrong, which is
    a modeller's problem rather than a retry (spec 5.1).

    Every problem across every configured model is collected into one of these. An export
    is machine-written, so its mistakes are not the bulk edits a workbook produces — but
    one broken cross-reference usually means several, and they are read in CI, where one
    problem per round trip costs a run each.
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
        The Ellie instance these models were exported from, ``https://<slug>.ellie.ai/api/v1``.
        Recorded rather than called in this mode: UUIDs are unique *within* an instance,
        so which instance a source's keys belong to is part of what the source name means
        (spec 5.4), and it appears in the run report so a reviewer can see it. The later
        API mode reads it and adds a ``token_env`` beside it, leaving identity untouched.
    ``models``
        The allowlist. Each entry carries ``id`` (Ellie's model id), ``path`` (the
        exported JSON, relative to the instance repository) and ``scheme_slug`` (the
        permanent slug of the ``skos:ConceptScheme`` the model becomes — its IRI local
        name and its output file, both frozen by the ID map on the run that mints them).
    """

    name = "ellie"

    _read: tuple[_ModelRead, ...] = ()
    """What the last fetch read, for :meth:`summary`. Empty until then — an adapter is
    constructed by ``semprini check`` without ever fetching (spec 6.1)."""

    # --------------------------------------------------------------------- the contract

    def fetch(self) -> InternalModel:
        # Its own configuration, checked before it is used: `validate_config()` is on no
        # compile path (spec 6.1 calls it, a run does not), so without this a run that
        # skipped `semprini check` would reach the files with settings nobody validated.
        # Exit 2, the same as any other configuration error.
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
                # Batched with the rest rather than raised here: a file that will not parse
                # is exactly as much a content problem as a file that parses and says the
                # wrong thing, and stopping on the first would hand the operator one
                # problem per CI round trip. `SourceUnreachableError` is deliberately not
                # caught — that is exit 3, a retry rather than an edit (spec 5.1).
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
            # An entity in several models is one object with several schemes (spec 5.3),
            # and merging it here rather than leaving it to the run loop means this
            # adapter returns the same model however many files described it — which is
            # what the contract's two fetches compare.
            return model.normalized()
        except MergeConflictError as error:
            # Reachable only from hand-edited exports: Ellie's own cross-model reuse gives
            # one UUID one set of statements. Re-raised as a content error so it reaches
            # the operator as an issue naming the source, not as a traceback.
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
                # Compared as text throughout: it is the scheme's source key, and the ID
                # map's columns are text (spec 5.4). YAML gives an int, an export gives an
                # int, and a quoted id in either must not mint a second scheme. Read
                # through `_plain` on both sides so that the allowlist and the export are
                # compared after the same normalization — an id pasted into the config
                # with an invisible character would otherwise match no file at all.
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
                    # Two models in one file: the second would overwrite the first's
                    # output and the ID map would hold two source keys for one IRI.
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
            # The one failure that is exit 3, and the one spec 5.3 insists must fail the
            # run rather than be skipped: a listed model that cannot be read is not an
            # empty model, and treating it as one would deprecate everything in it.
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

    Both shapes occur, so both are accepted — but on **structure**, not on the presence of
    a key. A document that is neither is refused by name rather than read as a model with
    no entities, which would compile to an empty scheme and deprecate everything the model
    used to hold (spec 5.4). That is the same failure the Excel adapter's strict headers
    exist to prevent: a lenient reader does not fail, it produces a different graph.
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
        # The allowlist is keyed by Ellie's model id (spec 5.3), so the file has to be the
        # model the configuration named. An export copied over the wrong path otherwise
        # replaces a scheme's whole contents and the run reports it as ordinary change.
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
        # An empty `entities` list is a model that genuinely holds nothing and is read as
        # such; an *absent* one is a truncated file. The two are worth separating because
        # reading the second as the first deprecates every object the model holds (spec
        # 5.4) — the same failure `_unwrap` refuses a wrapper-shaped document for.
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
        # Keyed by Ellie's model id, not by the slug: the slug is this instance's name for
        # the scheme and the id is the source's, and the ID map is keyed by the source's
        # (spec 5.4). Renaming the model in Ellie then costs no identity.
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
    """The model's relationships, with its inheritance separated out.

    Read before the entities because inheritance is stated *as* a relationship and lands
    on the narrower entity as ``skos:broader``, which has to be known before that entity
    is constructed.
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
            # Inheritance: the target is a specialization of the source. No reified
            # relationship is emitted for it — Ellie gives these rows no name and no
            # labels, so a sem:Relationship would need a prefLabel nobody wrote, and
            # skos:broader already states the fact once (spec 3.3).
            if source_id == target_id:
                issues.append(Issue(Severity.ERROR, f"{source_id} is its own supertype", where))
                continue
            broader.setdefault(target_id, []).append(SourceRef(source, source_id))
            continue

        labels = _labels(raw)
        forward = [label for label, direction in labels if direction.casefold() != _SOURCE]
        # Ellie's own `name` first, when a modeller filled it in; the reading verb
        # otherwise. A name appearing later re-labels the node without re-minting it, so
        # preferring it costs no identity (spec 5.4).
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
                # Unsplit, unlike the synonyms: Ellie's Examples field is one prose cell —
                # "Drill, hammer, spanner" is a sentence a modeller wrote, and cutting it
                # on its commas would invent three statements where the source made one.
                examples=tuple(filter(None, (_plain(metadata.get(_EXAMPLES)),))),
                schemes=(entry.slug,),
                broader=broader.get(key, ()),
            )
        )
        attributes.extend(
            _read_attributes(raw, source=source, entry=entry, owner=key, issues=issues)
        )
    # Inheritance lands *on* the narrower entity, so a supertype relationship pointing at
    # an entity this model does not hold has nowhere to go — and, unlike every other
    # cross-reference, nothing downstream would notice: the build stage checks the refs an
    # object carries, and this one was never carried. Reported here or not at all.
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
    """One entity's attributes — ``sem:Attribute`` nodes pointing back at it.

    First-class nodes rather than RDF properties, because Ellie gives them identity and a
    description of their own (spec 3.2). Only ``Description`` is carried; the rest of an
    attribute's metadata — ``PK``, ``Data type``, ``Semantic link`` — has no home in the
    metamodel yet.
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
    """A top-level array of objects, refusing anything that is not one.

    A missing array is an empty one — a model may genuinely hold no relationships — but a
    *malformed* one is refused rather than skipped, since silently reading nothing is how
    a whole model's worth of objects disappears from an instance in one run.
    """
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
    """``"Shipment, Dispatch, Consignment"`` → three ``skos:altLabel``s.

    Comma-separated is what the field holds; a synonym containing a comma is not something
    the format can express, and guessing otherwise would emit one label nobody wrote
    instead of the several they did.
    """
    text = _plain(raw)
    if not text:
        return ()
    return tuple(part for part in (piece.strip() for piece in text.split(",")) if part)


def _mapping(value: object) -> Mapping[str, Any]:
    """A nested JSON object, or an empty one where the export omitted it.

    An absent ``metadata`` block and an empty one say the same thing, and neither is worth
    a separate branch at every field that reads out of one.
    """
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _plain(value: object) -> str:
    """A JSON scalar as trimmed text; ``null`` and absent both become ``""``.

    Ellie writes ``null`` where a field is unset and ``""`` where it was cleared, and the
    difference is not one the graph can hold: an empty description emits no
    ``skos:definition`` either way (spec 5.3).

    Normalized as well as trimmed (spec 5.5 rule 9). A modelling tool holds prose typed
    and pasted by people exactly as a spreadsheet does, and the keys read through here are
    identifiers: an invisible character in one mints a second IRI for one entity.
    """
    if value is None:
        return ""
    return normalize_text(str(value))

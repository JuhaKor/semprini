"""ID map, IRI minting and the namespace lock (spec 3.4, 5.4).

The ID map, not the minting formula, is authoritative: minting happens once per object,
on the run that first sees it. The base IRI is frozen by ``mappings/namespace.lock``.
:class:`NamespaceLockError` is a configuration error (exit 2); :class:`IdentityError` is a
compile failure (exit 1).
"""

from __future__ import annotations

import csv
import datetime
import io
import json
import re
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from semprini import serialize
from semprini.config import ConfigError, InstanceConfig, is_slug
from semprini.model import (
    InternalModel,
    Issue,
    IssueError,
    Kind,
    Scheme,
    SemanticObject,
    Severity,
    SourceRef,
    TaxonomyValue,
)

__all__ = [
    "ID_MAP_COLUMNS",
    "ID_MAP_PATH",
    "NAMESPACE_LOCK_PATH",
    "NAMESPACE_SEMPRINI",
    "IdMap",
    "IdMapRow",
    "IdentityError",
    "NamespaceLock",
    "NamespaceLockError",
    "Registry",
    "mint_local_name",
    "verify_namespace_lock",
]

ID_MAP_PATH = Path("mappings") / "id-map.csv"
"""The persistent identity registry (spec 4.2, 5.4), relative to the instance root."""

NAMESPACE_LOCK_PATH = Path("mappings") / "namespace.lock"
"""The frozen base IRI (spec 3.4, 4.2), relative to the instance root."""

ID_MAP_COLUMNS = ("iri", "kind", "source_name", "source_key", "first_seen", "note")
"""Exactly the columns of spec 5.4, in that order; checked on load."""

NAMESPACE_SEMPRINI = UUID("8865c94a-2211-5f26-8887-6d6d5cbaa1e0")
"""The UUIDv5 namespace every minted local name derives from (spec 3.4.2).

``uuid5(NAMESPACE_URL, "https://w3id.org/semprini/ontology#")``, written down once.
Permanent for every instance in existence.
"""

UUID_PATTERN = r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}"
"""What a minted local name looks like, for everything but a scheme (spec 3.4.2).

Lower case only. Also used as ``sh:pattern`` (spec 6.1.5), so written without ``(?:``.
"""

_ISO_DATE = "%Y-%m-%d"

# A UUID as a source writes one: canonical 8-4-4-4-12, either case.
_CANONICAL_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


class IdentityError(IssueError):
    """Identity the compiler refuses to act on — CLI exit code 1 (spec 5.1, 6.1 check 6)."""

    noun = "identity error"


class NamespaceLockError(ConfigError):
    """The base IRI does not match the lock — CLI exit code 2 (spec 3.4, 5.1)."""

    noun = "namespace-lock error"


@dataclass(frozen=True, slots=True, kw_only=True)
class IdMapRow:
    """One row of ``mappings/id-map.csv``: one source's key for one IRI (spec 5.4).

    An object known to two sources has two rows carrying one IRI.
    """

    iri: str
    kind: Kind
    """Recorded, not part of the key (spec 5.4). A source key changing kind is refused."""

    source_name: str
    source_key: str
    first_seen: datetime.date
    """The run date this IRI was minted on (spec 5.5 rule 8 keeps dates out of ``generated/``)."""

    note: str = ""
    """Free text for stewards; the compiler writes none and preserves what it finds."""

    @property
    def ref(self) -> SourceRef:
        return SourceRef(self.source_name, self.source_key)

    @property
    def values(self) -> tuple[str, ...]:
        return (
            self.iri,
            str(self.kind),
            self.source_name,
            self.source_key,
            self.first_seen.strftime(_ISO_DATE),
            self.note,
        )


class IdMap:
    """``mappings/id-map.csv`` in memory: append-only, keyed by source and key (spec 5.4).

    :meth:`append` refuses a duplicate key or a kind clash, :meth:`check_append_only`
    compares against a base revision (spec 6.1 check 6), and nothing removes a row.
    """

    def __init__(self, rows: Iterable[IdMapRow] = (), *, origin: str | None = None) -> None:
        self.origin = origin
        """Where these rows were read from, for error messages."""

        self._rows: list[IdMapRow] = []
        self._by_ref: dict[SourceRef, IdMapRow] = {}
        self._by_iri: dict[str, list[IdMapRow]] = {}
        for row in rows:
            self.append(row)

    # ------------------------------------------------------------------ reading

    @classmethod
    def load(cls, repo_root: Path | None = None) -> IdMap:
        """Read ``<repo_root>/mappings/id-map.csv``. A missing file is an empty map."""
        path = (Path.cwd() if repo_root is None else Path(repo_root)) / ID_MAP_PATH
        try:
            # utf-8-sig: Excel saves CSV with a byte-order mark.
            text = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return cls(origin=str(path))
        except UnicodeDecodeError:
            raise IdentityError(
                [Issue(Severity.ERROR, "the ID map is not valid UTF-8", str(path))]
            ) from None
        except OSError as error:
            raise IdentityError(
                [Issue(Severity.ERROR, f"cannot read the ID map: {error}", str(path))]
            ) from None
        return cls.loads(text, origin=str(path))

    @classmethod
    def loads(cls, text: str, *, origin: str | None = None) -> IdMap:
        """Parse an ID map held in a string, reporting every bad row at once."""
        reader = csv.reader(io.StringIO(text, newline=""))
        try:
            header = next(reader)
        except StopIteration:
            raise IdentityError(
                [Issue(Severity.ERROR, "the ID map is empty; it must carry a header row")],
                origin=origin,
            ) from None

        if tuple(header) != ID_MAP_COLUMNS:
            raise IdentityError(
                [
                    Issue(
                        Severity.ERROR,
                        f"unexpected columns {header}; the ID map's columns are "
                        f"{list(ID_MAP_COLUMNS)}, in that order",
                    )
                ],
                origin=origin,
            )

        issues: list[Issue] = []
        rows: list[IdMapRow] = []
        for number, values in enumerate(reader, start=2):
            if not values:
                continue  # A trailing blank line; every writer leaves one.
            row = _row_from_csv(values, f"row {number}", issues)
            if row is not None:
                rows.append(row)
        if issues:
            raise IdentityError(issues, origin=origin)

        try:
            return cls(rows, origin=origin)
        except IdentityError as error:
            raise IdentityError(error.issues, origin=origin) from None

    # ------------------------------------------------------------------ lookup

    @property
    def rows(self) -> tuple[IdMapRow, ...]:
        """Every row, in file order."""
        return tuple(self._rows)

    def __len__(self) -> int:
        return len(self._rows)

    def __iter__(self) -> Iterator[IdMapRow]:
        return iter(self._rows)

    def row(self, ref: SourceRef) -> IdMapRow | None:
        """The row for one source's key, or ``None`` if that key has never been seen."""
        return self._by_ref.get(ref)

    def iri(self, ref: SourceRef) -> str | None:
        row = self._by_ref.get(ref)
        return None if row is None else row.iri

    def owners(self, iri: str) -> tuple[IdMapRow, ...]:
        """Every row that claims ``iri``, one per source that knows the object."""
        return tuple(self._by_iri.get(iri, ()))

    def source_names(self) -> frozenset[str]:
        return frozenset(row.source_name for row in self._rows)

    # ------------------------------------------------------------------ appending

    def append(self, row: IdMapRow) -> None:
        """Add a row (spec 5.4).

        Raises :class:`IdentityError` if the key is already mapped, even identically, or
        if rows sharing the IRI disagree about its kind.
        """
        existing = self._by_ref.get(row.ref)
        if existing is not None:
            raise IdentityError(
                [
                    Issue(
                        Severity.ERROR,
                        f"{row.ref} is already mapped to {existing.iri} "
                        f"({existing.kind}); it cannot also map to {row.iri} ({row.kind})",
                        str(row.ref),
                    )
                ]
            )
        claimed = self._by_iri.setdefault(row.iri, [])
        if claimed and claimed[0].kind is not row.kind:
            raise IdentityError(
                [
                    Issue(
                        Severity.ERROR,
                        f"{row.iri} is recorded as a {claimed[0].kind} by "
                        f"{claimed[0].ref} and as a {row.kind} by {row.ref}; one IRI is "
                        f"one object",
                        str(row.ref),
                    )
                ]
            )
        self._rows.append(row)
        self._by_ref[row.ref] = row
        claimed.append(row)

    # ------------------------------------------------------------------ checks

    def check_append_only(self, base: IdMap) -> tuple[Issue, ...]:
        """Compare against the base revision of the same file (spec 5.4, 6.1 check 6).

        A vanished row or an edited one is an issue. Every column is compared except
        ``note``, which stewards own.
        """
        issues: list[Issue] = []
        for row in base:
            current = self._by_ref.get(row.ref)
            if current is None:
                issues.append(
                    Issue(
                        Severity.ERROR,
                        f"the ID map no longer maps {row.ref} to {row.iri}; the map is "
                        f"append-only and IRIs are never removed or reused (spec 3.4)",
                        str(row.ref),
                    )
                )
                continue
            edited = [
                f"{column} was {getattr(row, column)!r} and is now {getattr(current, column)!r}"
                for column in ("iri", "kind", "first_seen")
                if getattr(current, column) != getattr(row, column)
            ]
            if edited:
                issues.append(
                    Issue(
                        Severity.ERROR,
                        f"the ID map row for {row.ref} was rewritten ({'; '.join(edited)}); "
                        f"an existing row is never edited, only appended to (spec 5.4)",
                        str(row.ref),
                    )
                )
        return tuple(issues)

    def check_sources_are_configured(self, configured: Collection[str]) -> tuple[Issue, ...]:
        """Every ``source_name`` in the map must still be a configured source (spec 5.4)."""
        unknown = sorted(self.source_names() - frozenset(configured))
        listed = ", ".join(sorted(configured)) or "none"
        return tuple(
            Issue(
                Severity.ERROR,
                f"the ID map holds rows for source {name!r}, which is not configured "
                f"(configured: {listed}); renaming a source requires rewriting the "
                f"source_name column, not editing configuration",
                f"{ID_MAP_PATH.as_posix()}:{name}",
            )
            for name in unknown
        )

    # ------------------------------------------------------------------ writing

    def dumps(self) -> str:
        """Render the map as CSV, LF-terminated on every platform (spec 5.5 rule 5)."""
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(ID_MAP_COLUMNS)
        writer.writerows(row.values for row in self._rows)
        return buffer.getvalue()

    def save(self, repo_root: Path | None = None) -> Path:
        """Write the map to ``<repo_root>/mappings/id-map.csv``."""
        path = (Path.cwd() if repo_root is None else Path(repo_root)) / ID_MAP_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.dumps(), encoding="utf-8", newline="\n")
        return path


def _row_from_csv(values: Sequence[str], location: str, issues: list[Issue]) -> IdMapRow | None:
    """Build one row, appending an issue instead of raising."""
    if len(values) != len(ID_MAP_COLUMNS):
        issues.append(
            Issue(
                Severity.ERROR,
                f"expected {len(ID_MAP_COLUMNS)} columns, found {len(values)}",
                location,
            )
        )
        return None

    iri, kind, source_name, source_key, first_seen, note = values
    for column, value in (("iri", iri), ("source_name", source_name), ("source_key", source_key)):
        if not value.strip():
            issues.append(Issue(Severity.ERROR, f"'{column}' must not be empty", location))
            return None
    try:
        parsed_kind = Kind(kind)
    except ValueError:
        issues.append(
            Issue(
                Severity.ERROR,
                f"unknown kind {kind!r}; expected one of: "
                f"{', '.join(sorted(str(k) for k in Kind))}",
                location,
            )
        )
        return None
    try:
        parsed_date = datetime.datetime.strptime(first_seen, _ISO_DATE).date()
    except ValueError:
        issues.append(
            Issue(
                Severity.ERROR,
                f"'first_seen' must be a date (YYYY-MM-DD), got {first_seen!r}",
                location,
            )
        )
        return None
    try:
        SourceRef(source_name, source_key)
    except ValueError as error:
        issues.append(Issue(Severity.ERROR, str(error), location))
        return None

    return IdMapRow(
        iri=iri,
        kind=parsed_kind,
        source_name=source_name,
        source_key=source_key,
        first_seen=parsed_date,
        note=note,
    )


# ---------------------------------------------------------------------------- minting


def mint_local_name(object_: SemanticObject) -> str:
    """The local name a new object gets, per spec 3.4.2; used once per object (spec 5.4).

    A scheme takes its slug. A source-provided UUID is used as is, lower-cased. Anything
    else is a UUIDv5 under :data:`NAMESPACE_SEMPRINI` over the scheme slug and row key for
    a taxonomy value, and over the source ref otherwise.
    """
    if isinstance(object_, Scheme):
        return _checked_slug(object_.slug, object_)

    ref = object_.refs[0]
    if isinstance(object_, TaxonomyValue):
        if not object_.schemes:
            raise IdentityError(
                [
                    Issue(
                        Severity.ERROR,
                        "a taxonomy value must belong to a scheme before it can be "
                        "minted: its IRI derives from the scheme slug (spec 3.4.2)",
                        str(ref),
                    )
                ]
            )
        # Sorted: arrival order must not reach an IRI.
        name = f"{sorted(object_.schemes)[0]}|{ref.key}"
        return str(uuid5(NAMESPACE_SEMPRINI, name))

    source_uuid = _as_uuid(ref.key)
    if source_uuid is not None:
        return str(source_uuid)
    return str(uuid5(NAMESPACE_SEMPRINI, str(ref)))


def _as_uuid(key: str) -> UUID | None:
    """``key`` as a UUID if written in canonical form, else ``None``.

    Narrower than ``UUID()``: a bare 32-digit code is a business code, not a UUID (spec 3.4.2).
    """
    if _CANONICAL_UUID.fullmatch(key) is None:
        return None
    try:
        return UUID(key)
    except ValueError:  # pragma: no cover - the pattern already guarantees this parses
        return None


def _checked_slug(name: str, object_: SemanticObject) -> str:
    """Refuse a scheme slug that is not a slug; it would be frozen into an IRI and a file name (spec
    3.4.2, 4.2).
    """
    if not is_slug(name):
        raise IdentityError(
            [
                Issue(
                    Severity.ERROR,
                    f"scheme slug {name!r} cannot become an IRI local name; use lower-case "
                    f"letters, digits, '-' and '_' — and remember it is permanent once "
                    f"minted (spec 3.4.2)",
                    str(object_.refs[0]),
                )
            ]
        )
    return name


# ---------------------------------------------------------------------------- registry


class Registry:
    """Resolves objects to IRIs: the ID map first, minting only on a miss (spec 5.4).

    New rows accumulate in memory and reach the file only in :meth:`save`.
    """

    def __init__(
        self,
        id_map: IdMap,
        base_iri: str,
        *,
        repo_root: Path | None = None,
        today: datetime.date | None = None,
    ) -> None:
        self.id_map = id_map
        self.base_iri = base_iri
        self.repo_root = Path.cwd() if repo_root is None else Path(repo_root)
        """The instance :meth:`save` writes back to."""

        self.today = datetime.date.today() if today is None else today
        """The date new rows record as ``first_seen``. Injected so that a test can pin it."""

        self._namespaces = serialize.namespaces(base_iri)
        self._minted: list[IdMapRow] = []

    @classmethod
    def load(cls, config: InstanceConfig, *, today: datetime.date | None = None) -> Registry:
        """The registry for a configured instance, with its namespace lock verified (spec 3.4)."""
        verify_namespace_lock(config)
        return cls(
            IdMap.load(config.repo_root),
            config.base_iri,
            repo_root=config.repo_root,
            today=today,
        )

    @property
    def minted(self) -> tuple[IdMapRow, ...]:
        """Rows this run added (spec 5.6)."""
        return tuple(self._minted)

    def iri(self, ref: SourceRef) -> str | None:
        """The IRI known for one source ref, or ``None``."""
        return self.id_map.iri(ref)

    def resolve(self, model: InternalModel) -> Mapping[SemanticObject, str]:
        """Resolve every object in ``model``, minting and recording what is new.

        Walks the model in its own, already deterministic, order (spec 5.5). Raises
        :class:`IdentityError` if two objects resolve to one IRI.
        """
        resolved = {object_: self.iri_for(object_) for object_ in model.objects}
        self._check_iris_are_unique(resolved)
        return resolved

    def _check_iris_are_unique(self, resolved: Mapping[SemanticObject, str]) -> None:
        """Refuse two objects that resolved to one IRI (spec 5.4).

        Happens when the cross-reference that once merged two source keys onto one IRI
        has since left the sources. The steward settles it; the compiler does not.
        """
        claimants: dict[str, list[SemanticObject]] = {}
        for object_, iri in resolved.items():
            claimants.setdefault(iri, []).append(object_)

        issues = [
            Issue(
                Severity.ERROR,
                f"{len(objects)} separate {objects[0].kind}s resolve to {iri} "
                f"({', '.join(str(o.refs[0]) for o in objects)}); the ID map records them "
                f"as one object but the sources now describe several — reconcile them in "
                f"the sources, or record the merge in mappings/merges.csv",
                str(objects[0].refs[0]),
            )
            for iri, objects in sorted(claimants.items())
            if len(objects) > 1
        ]
        if issues:
            raise IdentityError(issues)

    def iri_for(self, object_: SemanticObject) -> str:
        """The IRI for one object, minted and recorded if it has none yet."""
        known = {ref: row for ref in object_.refs if (row := self.id_map.row(ref)) is not None}
        self._check_kind(object_, known)

        iris = {row.iri for row in known.values()}
        if len(iris) > 1:
            # The sources say one object, the map says two; a steward picks (spec 5.4).
            raise IdentityError(
                [
                    Issue(
                        Severity.ERROR,
                        f"the sources report one {object_.kind} but the ID map already "
                        f"holds {len(iris)} IRIs for it ({', '.join(sorted(iris))}); "
                        f"record the merge in mappings/merges.csv rather than letting "
                        f"one of them be chosen here",
                        str(object_.refs[0]),
                    )
                ]
            )

        iri = iris.pop() if iris else self._mint(object_)
        for ref in object_.refs:
            if ref not in known:
                row = IdMapRow(
                    iri=iri,
                    kind=object_.kind,
                    source_name=ref.source,
                    source_key=ref.key,
                    first_seen=self.today,
                )
                self.id_map.append(row)
                self._minted.append(row)
        return iri

    def _mint(self, object_: SemanticObject) -> str:
        iri = self._namespaces[object_.kind.prefix] + mint_local_name(object_)
        owners = self.id_map.owners(iri)
        if owners:
            # Two schemes given one slug, or two taxonomy rows given one code.
            raise IdentityError(
                [
                    Issue(
                        Severity.ERROR,
                        f"minting {object_.kind} {object_.refs[0]} produced {iri}, which "
                        f"already belongs to {', '.join(str(row.ref) for row in owners)}; "
                        f"two source keys cannot share one IRI (spec 5.4)",
                        str(object_.refs[0]),
                    )
                ]
            )
        return iri

    def _check_kind(self, object_: SemanticObject, known: Mapping[SourceRef, IdMapRow]) -> None:
        for ref, row in known.items():
            if row.kind is not object_.kind:
                raise IdentityError(
                    [
                        Issue(
                            Severity.ERROR,
                            f"{ref} was recorded as a {row.kind} and now describes a "
                            f"{object_.kind}; one source key is one object, and its IRI "
                            f"is already minted in the {row.kind} namespace",
                            str(ref),
                        )
                    ]
                )

    def save(self, repo_root: Path | None = None) -> Path:
        """Write the ID map back to the instance it was read from (spec 5.1)."""
        return self.id_map.save(self.repo_root if repo_root is None else repo_root)


# ----------------------------------------------------------------------- namespace lock


@dataclass(frozen=True, slots=True, kw_only=True)
class NamespaceLock:
    """``mappings/namespace.lock`` — the frozen base IRI (spec 3.4.4). Written once at
    bootstrap, compared on every run."""

    base_iri: str
    instance_id: str
    ontology_version: str
    """The metamodel version when the lock was written. Recorded, not compared (spec 6.1 check 3).
    """

    date: datetime.date

    @classmethod
    def load(cls, repo_root: Path | None = None) -> NamespaceLock:
        """Read the lock, or explain that the instance has none (exit code 2)."""
        path = (Path.cwd() if repo_root is None else Path(repo_root)) / NAMESPACE_LOCK_PATH
        try:
            text = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            # Deleting the file must not be a way around a permanent decision.
            raise NamespaceLockError(
                [
                    Issue(
                        Severity.ERROR,
                        "no namespace lock; an instance's base IRI is frozen at bootstrap "
                        "(spec 3.4) — run 'semprini init' to create one",
                        str(path),
                    )
                ]
            ) from None
        except (OSError, UnicodeDecodeError) as error:
            raise NamespaceLockError(
                [Issue(Severity.ERROR, f"cannot read the namespace lock: {error}", str(path))]
            ) from None
        return cls.loads(text, origin=str(path))

    @classmethod
    def loads(cls, text: str, *, origin: str | None = None) -> NamespaceLock:
        try:
            document: Any = json.loads(text)
        except json.JSONDecodeError as error:
            raise NamespaceLockError(
                [Issue(Severity.ERROR, f"the namespace lock is not valid JSON: {error}")],
                origin=origin,
            ) from None
        if not isinstance(document, dict):
            raise NamespaceLockError(
                [Issue(Severity.ERROR, "the namespace lock must be a JSON object")], origin=origin
            )

        issues: list[Issue] = []
        values: dict[str, str] = {}
        for key in ("base_iri", "instance_id", "ontology_version", "date"):
            value = document.get(key)
            if not isinstance(value, str) or not value:
                issues.append(Issue(Severity.ERROR, f"'{key}' is required", key))
            else:
                values[key] = value
        if issues:
            raise NamespaceLockError(issues, origin=origin)

        try:
            written = datetime.datetime.strptime(values["date"], _ISO_DATE).date()
        except ValueError:
            raise NamespaceLockError(
                [
                    Issue(
                        Severity.ERROR,
                        f"'date' must be YYYY-MM-DD, got {values['date']!r}",
                        "date",
                    )
                ],
                origin=origin,
            ) from None
        return cls(
            base_iri=values["base_iri"],
            instance_id=values["instance_id"],
            ontology_version=values["ontology_version"],
            date=written,
        )

    def dumps(self) -> str:
        """Render the lock as JSON, in a fixed key order with a trailing newline."""
        document = {
            "base_iri": self.base_iri,
            "instance_id": self.instance_id,
            "ontology_version": self.ontology_version,
            "date": self.date.strftime(_ISO_DATE),
        }
        return json.dumps(document, indent=2, ensure_ascii=False) + "\n"

    def save(self, repo_root: Path | None = None) -> Path:
        path = (Path.cwd() if repo_root is None else Path(repo_root)) / NAMESPACE_LOCK_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.dumps(), encoding="utf-8", newline="\n")
        return path

    def verify(self, config: InstanceConfig) -> None:
        """Compare the lock to configuration, aborting on any mismatch (spec 3.4.4)."""
        issues: list[Issue] = []
        if config.base_iri != self.base_iri:
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"the base IRI is {config.base_iri!r} but this instance minted its "
                    f"IRIs under {self.base_iri!r}; the base IRI is permanent — an "
                    f"instance that needs a different one is a new instance",
                    "semprini.base_iri",
                )
            )
        if config.instance_id != self.instance_id:
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"the instance id is {config.instance_id!r} but the namespace lock "
                    f"was written for {self.instance_id!r}",
                    "semprini.instance_id",
                )
            )
        if issues:
            raise NamespaceLockError(issues, origin=NAMESPACE_LOCK_PATH.as_posix())


def verify_namespace_lock(config: InstanceConfig) -> NamespaceLock:
    """Load the instance's lock and check it against configuration (spec 6.1 check 4)."""
    lock = NamespaceLock.load(config.repo_root)
    lock.verify(config)
    return lock

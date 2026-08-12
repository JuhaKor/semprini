"""ID map, IRI minting and the namespace lock (spec 3.4, 5.4).

Identity is the one thing an instance can never redo. Generated files are rewritten on
every run and a bad serialization is a migration away from being fixed, but an IRI that
has been published is permanent: it is what a query, a dashboard or another organization's
`skos:exactMatch` points at. Everything here exists to make that survivable.

*The ID map, not the formula, is authoritative* (spec 5.4). Minting is a fallback used
once per object, on the run that first sees it; from then on the answer comes from
``mappings/id-map.csv``. That is what lets a taxonomy code change, a minting rule be
rewritten, or a compiler be upgraded without any of it reaching the IRIs an instance has
already published.

*The base IRI is frozen* (spec 3.4). ``mappings/namespace.lock`` records what the instance
minted under, and every run compares it to ``config/semprini.yaml``. Without that check an
edited base IRI would not fail — it would quietly mint a parallel universe of IRIs beside
an ID map still holding the old ones, and the two would never be reconciled.

Two error types, because the CLI's exit codes distinguish them (spec 5.1):
:class:`NamespaceLockError` is a configuration error (exit 2) and subclasses
:class:`~semprini.config.ConfigError` for exactly that reason; :class:`IdentityError` is a
compile failure (exit 1), which is what spec 6.1 check 6 reports.
"""

from __future__ import annotations

import csv
import datetime
import io
import json
import re
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
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
    "plan_namespace_change",
    "verify_namespace_lock",
]

ID_MAP_PATH = Path("mappings") / "id-map.csv"
"""The persistent identity registry (spec 4.2, 5.4), relative to the instance root."""

NAMESPACE_LOCK_PATH = Path("mappings") / "namespace.lock"
"""The frozen base IRI (spec 3.4, 4.2), relative to the instance root."""

ID_MAP_COLUMNS = ("iri", "kind", "source_name", "source_key", "first_seen", "note")
"""Exactly the columns of spec 5.4, in that order. The header is checked on load: a
column quietly renamed or reordered would make every lookup miss and every object mint a
second IRI."""

NAMESPACE_SEMPRINI = UUID("8865c94a-2211-5f26-8887-6d6d5cbaa1e0")
"""The UUIDv5 namespace every minted local name derives from (spec 3.4.2).

Its value is ``uuid5(NAMESPACE_URL, "https://w3id.org/semprini/ontology#")`` — derived
once, then written down. **It is permanent for every instance in existence.** Changing it
would mint a different IRI for every object first seen after the change, while the ID map
went on holding the old ones; that is why it is a literal here and not a computation
someone could adjust in passing.
"""

UUID_PATTERN = r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}"
"""What a minted local name looks like, for everything but a scheme (spec 3.4.2).

Lower case only, unlike :data:`_CANONICAL_UUID` below: that one reads what a *source*
wrote and normalizes it, while this describes what :func:`mint_local_name` produced and
froze. The SHACL IRI policy (spec 6.1.5) is written against it, so the two halves of
"an IRI is opaque" — how a local name is minted and what one is allowed to look like —
have one definition between them. Written without ``(?:`` so that it stays valid in the
XPath regex dialect SHACL's ``sh:pattern`` is defined against.
"""

_ISO_DATE = "%Y-%m-%d"

# A UUID as a source is expected to write one: the canonical 8-4-4-4-12 form. Case is
# tolerated and normalized away, since a source that switches to upper case must not mint
# a second IRI for one object.
_CANONICAL_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


class IdentityError(IssueError):
    """Identity the compiler refuses to act on — CLI exit code 1 (spec 5.1, 6.1 check 6).

    A compile failure rather than a configuration error: a collision, a lost row or a
    malformed ID map means the repository's identity state and the sources disagree, and
    no amount of editing ``config/semprini.yaml`` addresses it.
    """

    noun = "identity error"


class NamespaceLockError(ConfigError):
    """The base IRI does not match the lock — CLI exit code 2 (spec 3.4, 5.1).

    A :class:`~semprini.config.ConfigError` on purpose: the exit-code contract makes
    "configuration or namespace-lock error" one category, and the lock *is* frozen
    configuration — the one setting an instance may not edit after bootstrap.
    """

    noun = "namespace-lock error"


@dataclass(frozen=True, slots=True, kw_only=True)
class IdMapRow:
    """One row of ``mappings/id-map.csv``: one source's key for one IRI (spec 5.4).

    A row, not an object: an object known to two sources has two rows carrying one IRI,
    which is how ``sem:sourceRef`` and the registry end up telling the same story
    (spec 3.3).
    """

    iri: str
    kind: Kind
    """Recorded, not part of the key — the map is keyed by ``(source_name, source_key)``
    alone (spec 5.4). Kept so that a reader can tell what a row is about, and so that a
    source key changing kind is caught rather than silently reusing an IRI."""

    source_name: str
    source_key: str
    first_seen: datetime.date
    """The run date this IRI was minted on. The only date in an instance's committed
    state, and deliberately nowhere near ``generated/`` — output carries no run
    timestamps (spec 5.5 rule 8)."""

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

    Append-only is enforced rather than documented — :meth:`append` refuses a duplicate
    key or an IRI already owned by someone else, and :meth:`check_append_only` compares
    against the base revision so that a row deleted in an editor fails CI (spec 6.1
    check 6). Nothing here removes a row; there is no method that could.
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
        """Read ``<repo_root>/mappings/id-map.csv``.

        A missing file is an empty map, not an error: the first run of a freshly
        initialized instance mints everything it sees.
        """
        path = (Path.cwd() if repo_root is None else Path(repo_root)) / ID_MAP_PATH
        try:
            # utf-8-sig, not utf-8: stewards open this CSV in Excel, which saves it with a
            # byte-order mark. Left in place the BOM joins the first column name, and the
            # header check then reports two lists of columns that look identical. It is a
            # no-op for a file that has none.
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
            # An empty file, as opposed to an absent one: `semprini init` writes headers
            # (spec 5.7 step 3), so a file with none is damaged.
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

        # Built row by row so that the append-only guards apply to a file someone edited
        # by hand exactly as they apply to a run: a pasted duplicate is caught on load.
        try:
            return cls(rows, origin=origin)
        except IdentityError as error:
            raise IdentityError(error.issues, origin=origin) from None

    # ------------------------------------------------------------------ lookup

    @property
    def rows(self) -> tuple[IdMapRow, ...]:
        """Every row, in file order — append order, which is the file's history."""
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
        """Every row that claims ``iri`` — one per source that knows the object."""
        return tuple(self._by_iri.get(iri, ()))

    def source_names(self) -> frozenset[str]:
        return frozenset(row.source_name for row in self._rows)

    # ------------------------------------------------------------------ appending

    def append(self, row: IdMapRow) -> None:
        """Add a row, refusing anything that would break identity (spec 5.4).

        Two rules, and they are the reason this is a method and not a list append. One
        ``(source_name, source_key)`` maps to one IRI for ever — even a byte-identical
        second row is refused rather than absorbed, because collapsing it would delete a
        line from the next compile PR that nobody asked to have deleted. And rows sharing
        an IRI must agree on what kind of thing it is: several rows on one IRI are the
        several sources of one object, which :class:`Registry` establishes before
        recording them, and one object has one kind.
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

        A row that vanished is an IRI that has lost its meaning: whatever published it
        still points at it, and the next run would mint a second IRI for the same object.
        A row that was edited is the same failure written differently.

        Every column is compared except ``note``, which is the one field stewards own and
        are expected to edit. ``kind`` matters as much as ``iri`` here: it is what
        :class:`Registry` checks a source key against when it arrives describing something
        else, so a rewritten ``kind`` disables that guard — and for an object no source
        reports any more, this is the only place it would ever be noticed.
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
        """Every ``source_name`` in the map must still be a configured source (spec 5.4).

        Renaming a source in ``config/semprini.yaml`` breaks identity resolution — every
        lookup misses and every object mints again — so the rename is a deliberate
        procedure that rewrites this column, not a config edit.
        """
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
        """Render the map as CSV — LF-terminated, whatever platform wrote it."""
        buffer = io.StringIO(newline="")
        # csv's own default is CRLF, which would make the same map two different files on
        # two machines and put a whole-file diff in front of a reviewer (spec 5.5 rule 5).
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
    """Build one row, appending an issue instead of raising, so every bad row is seen."""
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
        # Rejected rather than carried through as text: a kind this compiler does not
        # know means the file was written by a version that mints differently, and
        # guessing would put the wrong namespace in front of the next new object.
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
    """The local name a new object gets, per spec 3.4.2.

    Used **once** per object, on the run that first sees it; the ID map answers every
    time after that (spec 5.4). That is the whole point of this being a fallback: the
    rules below can change without any instance's existing IRIs moving.

    Three rules, one per row of spec 3.4.2:

    - A source that provides a stable UUID has already done the work — the UUID is used
      as the local name, normalized to its canonical lower-case form so that a source
      switching to upper case does not mint a second IRI.
    - A scheme takes its slug, assigned once at creation and opaque thereafter: renaming
      the glossary does not rename the scheme.
    - Anything else derives a UUIDv5 from :data:`NAMESPACE_SEMPRINI`, over the scheme
      slug and the source's row key for a taxonomy value, and over the source name and
      key otherwise. Deriving rather than randomizing is what makes two machines
      compiling the same input agree.
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
        # Sorted, not "the first one given": arrival order must not reach an IRI. A value
        # in several taxonomies is unusual, and the map freezes whichever answer the
        # first run gave anyway.
        name = f"{sorted(object_.schemes)[0]}|{ref.key}"
        return str(uuid5(NAMESPACE_SEMPRINI, name))

    source_uuid = _as_uuid(ref.key)
    if source_uuid is not None:
        return str(source_uuid)
    return str(uuid5(NAMESPACE_SEMPRINI, str(ref)))


def _as_uuid(key: str) -> UUID | None:
    """``key`` as a UUID if it is written as one, else ``None``.

    Deliberately narrower than ``UUID()``, which also accepts ``urn:uuid:`` prefixes,
    braces and bare 32-hex. Two of those matter. A 32-digit numeric business code is not
    a UUID, and reading one as though it were would freeze a local name the source never
    issued; and the spec's rule is about what the *source* provides (spec 3.4.2), which a
    canonical UUID is evidence of and an arbitrary hex string is not. Anything not in this
    form is still minted — it takes the derived UUIDv5 path, which is equally stable.
    """
    if _CANONICAL_UUID.fullmatch(key) is None:
        return None
    try:
        return UUID(key)
    except ValueError:  # pragma: no cover - the pattern already guarantees this parses
        return None


def _checked_slug(name: str, object_: SemanticObject) -> str:
    """Refuse a scheme slug that must not be frozen into an IRI.

    A slug reaches here straight from an adapter's own configuration, unvalidated by
    ``config`` because the ``config:`` subtree belongs to the adapter (spec 5.2). It is
    held to the same shape as every other slug in an instance — an instance id, a source
    name — for two reasons beyond the IRI itself: ``Sales`` and ``sales`` would otherwise
    be two permanent IRIs for one taxonomy that no collision check could tell apart, and
    the slug names a file in ``generated/`` (spec 4.2), where a case-insensitive
    filesystem would make that same pair one file.
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

    Held for the length of a run. Rows accumulate in memory and reach the file only when
    :meth:`save` is called, so a ``--dry-run`` or a failure part-way through leaves the
    instance's identity state exactly as it was.
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
        """The instance :meth:`save` writes back to — remembered rather than resolved
        again at save time, so that the map cannot be read from one instance and written
        to another."""

        self.today = datetime.date.today() if today is None else today
        """The date new rows record as ``first_seen``. Injected so that a test pins it —
        and so that nothing else in the compiler reads a clock."""

        self._namespaces = serialize.namespaces(base_iri)
        self._minted: list[IdMapRow] = []

    @classmethod
    def load(cls, config: InstanceConfig, *, today: datetime.date | None = None) -> Registry:
        """The registry for a configured instance, with its namespace lock verified.

        Verification happens here rather than being left to the caller: a registry that
        minted under a base IRI the lock does not name is the failure the lock exists to
        prevent, and there must be no way to obtain one (spec 3.4).
        """
        verify_namespace_lock(config)
        return cls(
            IdMap.load(config.repo_root),
            config.base_iri,
            repo_root=config.repo_root,
            today=today,
        )

    @property
    def minted(self) -> tuple[IdMapRow, ...]:
        """Rows this run added — what the run report counts as new objects (spec 5.6)."""
        return tuple(self._minted)

    def iri(self, ref: SourceRef) -> str | None:
        """The IRI known for one source ref, or ``None``."""
        return self.id_map.iri(ref)

    def resolve(self, model: InternalModel) -> Mapping[SemanticObject, str]:
        """Resolve every object in ``model``, minting and recording what is new.

        Walks the model in its own order, which :func:`~semprini.model.merge_models` has
        already made independent of the order adapters ran in — so two machines mint the
        same IRIs and append the same rows in the same order (spec 5.5).

        The result is checked to be **injective**: distinct objects get distinct IRIs.
        :meth:`iri_for` cannot see that on its own — a lookup that hits returns a recorded
        IRI without ever consulting another object — so the one place the question can be
        asked is here, over the whole model.
        """
        resolved = {object_: self.iri_for(object_) for object_ in model.objects}
        self._check_iris_are_unique(resolved)
        return resolved

    def _check_iris_are_unique(self, resolved: Mapping[SemanticObject, str]) -> None:
        """Refuse two objects that resolved to one IRI (spec 5.4).

        Reachable only through the ID map, and only from a history that was once correct:
        several rows share an IRI exactly when several sources described one object, which
        is legitimate and is what :meth:`iri_for` records. If the cross-reference that
        merged them later disappears from the sources — a mapping table edited, an
        adapter's alias dropped — those rows are still there and the two objects that
        arrive now both resolve onto the one IRI. Nothing downstream would notice: the
        graph builder would emit a single node wearing two labels, and the collision would
        look like a modelling mistake rather than a lost identity.

        The merge register is where a steward says these are one object, or the sources
        are where they say they are two; the compiler decides neither (spec 5.4).
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
            # Sorted so that the report is the same on every machine, whatever order the
            # model happened to be walked in.
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
            # The sources agree this is one object; the map already says it is two. Only
            # a steward can say which IRI survives, and the merge register is where that
            # is recorded (spec 5.4) — the compiler must not pick.
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
            # Two different objects claiming one IRI: two schemes given one slug, two
            # taxonomy rows given one code. Caught here rather than in the output, where
            # it would look like one object that mysteriously has two labels.
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
        """Write the ID map back to the instance it was read from (spec 5.1).

        Defaults to :attr:`repo_root` rather than to the working directory: reading one
        instance's map and writing it into another would lose every row the run appended
        and silently re-mint them on the next one.
        """
        return self.id_map.save(self.repo_root if repo_root is None else repo_root)


# ----------------------------------------------------------------------- namespace lock


@dataclass(frozen=True, slots=True, kw_only=True)
class NamespaceLock:
    """``mappings/namespace.lock`` — the frozen base IRI (spec 3.4.4).

    Written once at bootstrap and compared on every subsequent run. It is the only file
    an instance holds whose purpose is to refuse a change.
    """

    base_iri: str
    instance_id: str
    ontology_version: str
    """The metamodel version in force when the lock was written. Recorded, not compared:
    upgrading the ontology is expected and is what the manifest's drift check governs
    (spec 6.1 check 3). Rewriting the base IRI is not."""

    date: datetime.date

    @classmethod
    def load(cls, repo_root: Path | None = None) -> NamespaceLock:
        """Read the lock, or explain that the instance has none (exit code 2)."""
        path = (Path.cwd() if repo_root is None else Path(repo_root)) / NAMESPACE_LOCK_PATH
        try:
            # utf-8-sig for the same reason as the ID map: an editor's byte-order mark
            # would otherwise reach json.loads and be reported as invalid JSON at
            # character 0, which says nothing about how to fix it.
            text = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            # Refused, not assumed absent: without the lock nothing stops a base IRI
            # edit, and "delete the file" must not be a way around a permanent decision.
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
                    f"IRIs under {self.base_iri!r}; changing it is a migration, not a "
                    f"configuration edit — see 'semprini run --force-namespace-change'",
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


def plan_namespace_change(
    config: InstanceConfig,
    *,
    ontology_version: str,
    today: datetime.date | None = None,
) -> tuple[NamespaceLock, IdMap]:
    """Move an instance to a new base IRI — ``--force-namespace-change`` (spec 3.4.4).

    Expected to be a once-ever event, and a migration rather than a configuration edit.
    Every IRI in the ID map is rewritten from the old base to the new one, keeping its
    local name, so identity survives the move: the same object keeps the same UUID, in a
    new namespace.

    **Nothing is written.** The moved lock and map are returned for the run to save
    alongside the regenerated files (spec 5.1), which is what puts the whole move into one
    reviewable commit — and what keeps a compile that fails afterwards from leaving an
    instance whose map says it has moved and whose ``generated/`` says it has not. That
    state has no way out: a second ``--force-namespace-change`` is refused as a move to
    the base IRI already locked, and a plain run refuses the old IRIs still in the output.
    The caller writes the map first and the lock second, so an interrupted write leaves
    the instance saying it still lives in the old namespace, which a re-run recovers from.

    Generated files are not rewritten here either: they are machine-owned and the run
    regenerates them wholesale (spec 4.3), rebasing the previous state it carries forward
    so that deprecated nodes move with everything else.

    The flag moves the **base IRI and nothing else** (spec 3.4.4). An instance id that has
    also drifted is refused rather than re-frozen: this is the one invocation that
    suspends the lock's checks, and it must not become the way any other locked value gets
    quietly adopted. A move that would change nothing is refused too — rewriting the lock
    then only discards the record of when the namespace was actually frozen.

    Raises :class:`IdentityError` if the map holds an IRI outside the old base: it is not
    this function's to move, and silently leaving it behind would split the instance
    across two namespaces.
    """
    lock = NamespaceLock.load(config.repo_root)
    if config.instance_id != lock.instance_id:
        raise NamespaceLockError(
            [
                Issue(
                    Severity.ERROR,
                    f"the instance id is {config.instance_id!r} but the namespace lock was "
                    f"written for {lock.instance_id!r}; --force-namespace-change moves the "
                    f"base IRI and nothing else",
                    "semprini.instance_id",
                )
            ],
            origin=NAMESPACE_LOCK_PATH.as_posix(),
        )
    if config.base_iri == lock.base_iri:
        raise NamespaceLockError(
            [
                Issue(
                    Severity.ERROR,
                    f"the base IRI is already {lock.base_iri!r}; there is nothing to move, "
                    f"and --force-namespace-change is not a way to refresh the lock",
                    "semprini.base_iri",
                )
            ],
            origin=NAMESPACE_LOCK_PATH.as_posix(),
        )
    old_map = IdMap.load(config.repo_root)

    issues = [
        Issue(
            Severity.ERROR,
            f"{row.iri} is not under the locked base IRI {lock.base_iri!r}, so it cannot "
            f"be moved to the new one",
            str(row.ref),
        )
        for row in old_map
        if not row.iri.startswith(lock.base_iri)
    ]
    if issues:
        raise IdentityError(issues, origin=ID_MAP_PATH.as_posix())

    moved = IdMap(
        replace(row, iri=config.base_iri + row.iri[len(lock.base_iri) :]) for row in old_map
    )
    changed = NamespaceLock(
        base_iri=config.base_iri,
        instance_id=config.instance_id,
        ontology_version=ontology_version,
        date=datetime.date.today() if today is None else today,
    )
    return changed, moved

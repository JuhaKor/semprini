"""Deprecation, carry-forward and the merge register (spec 3.5, 5.4). A node no configured source
reports any more is retained with its last-known statements and marked deprecated; nothing here
deletes. Deprecation is judged against the union of all configured sources, so removing a source
deprecates what it owned. The merge register is a steward's statement; the compiler emits
``dcterms:isReplacedBy`` from it and infers nothing.
"""

from __future__ import annotations

import csv
import datetime
import io
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, SKOS
from rdflib.term import Node

from semprini.build import (
    SEM_STATUS,
    STATUS_ACTIVE,
    STATUS_DEPRECATED,
    CarriedNode,
)
from semprini.identity import IdMap, Registry
from semprini.model import InternalModel, Issue, IssueError, Severity

__all__ = [
    "MERGES_COLUMNS",
    "MERGES_PATH",
    "LifecycleError",
    "LifecyclePlan",
    "MergeRegister",
    "MergeRow",
    "plan",
]

MERGES_PATH = Path("mappings") / "merges.csv"
"""The hand-maintained merge register (spec 4.2, 5.4), relative to the instance root."""

MERGES_COLUMNS = ("deprecated_iri", "replaced_by_iri", "date", "note")
"""Exactly the columns of spec 5.4, in that order; checked on load."""

_ISO_DATE = "%Y-%m-%d"

# Statements this stage derives rather than carries (spec 3.3).
_DERIVED = frozenset({SEM_STATUS, DCTERMS.isReplacedBy, DCTERMS.modified})


class LifecycleError(IssueError):
    """Lifecycle state the compiler refuses to act on — CLI exit code 1 (spec 5.1)."""

    noun = "lifecycle error"


# ------------------------------------------------------------------------ merge register


@dataclass(frozen=True, slots=True, kw_only=True)
class MergeRow:
    """One row of ``mappings/merges.csv``: two objects a steward says are one (spec 5.4)."""

    deprecated_iri: str
    replaced_by_iri: str
    date: datetime.date
    """When the merge was recorded. Steward-supplied; never read by the compiler."""

    note: str = ""

    @property
    def values(self) -> tuple[str, ...]:
        return (
            self.deprecated_iri,
            self.replaced_by_iri,
            self.date.strftime(_ISO_DATE),
            self.note,
        )


class MergeRegister:
    """``mappings/merges.csv`` in memory (spec 5.4).

    Construction raises :class:`LifecycleError` for a self-replacement, a deprecated IRI
    with two successors, or a cycle.
    """

    def __init__(self, rows: Iterable[MergeRow] = (), *, origin: str | None = None) -> None:
        self.origin = origin
        self._rows = tuple(rows)
        self._by_deprecated: dict[str, MergeRow] = {}

        issues: list[Issue] = []
        for row in self._rows:
            if row.deprecated_iri == row.replaced_by_iri:
                issues.append(
                    Issue(
                        Severity.ERROR,
                        f"{row.deprecated_iri} is recorded as replaced by itself; a merge "
                        f"names the object that survived, which cannot be the one that "
                        f"did not",
                        row.deprecated_iri,
                    )
                )
                continue
            existing = self._by_deprecated.get(row.deprecated_iri)
            if existing is not None:
                issues.append(
                    Issue(
                        Severity.ERROR,
                        f"{row.deprecated_iri} is recorded as replaced by both "
                        f"{existing.replaced_by_iri} and {row.replaced_by_iri}; a "
                        f"deprecated object has one successor",
                        row.deprecated_iri,
                    )
                )
                continue
            self._by_deprecated[row.deprecated_iri] = row
        issues.extend(self._cycles())
        if issues:
            raise LifecycleError(issues, origin=origin)

    # ------------------------------------------------------------------ reading

    @classmethod
    def load(cls, repo_root: Path | None = None) -> MergeRegister:
        """Read ``<repo_root>/mappings/merges.csv``. A missing file is an empty register."""
        path = (Path.cwd() if repo_root is None else Path(repo_root)) / MERGES_PATH
        try:
            # utf-8-sig: Excel saves CSV with a byte-order mark.
            text = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return cls(origin=str(path))
        except UnicodeDecodeError:
            raise LifecycleError(
                [Issue(Severity.ERROR, "the merge register is not valid UTF-8", str(path))]
            ) from None
        except OSError as error:
            raise LifecycleError(
                [Issue(Severity.ERROR, f"cannot read the merge register: {error}", str(path))]
            ) from None
        return cls.loads(text, origin=str(path))

    @classmethod
    def loads(cls, text: str, *, origin: str | None = None) -> MergeRegister:
        """Parse a register held in a string, reporting every bad row at once."""
        reader = csv.reader(io.StringIO(text, newline=""))
        try:
            header = next(reader)
        except StopIteration:
            raise LifecycleError(
                [Issue(Severity.ERROR, "the merge register is empty; it must carry a header row")],
                origin=origin,
            ) from None

        if tuple(header) != MERGES_COLUMNS:
            raise LifecycleError(
                [
                    Issue(
                        Severity.ERROR,
                        f"unexpected columns {header}; the merge register's columns are "
                        f"{list(MERGES_COLUMNS)}, in that order",
                    )
                ],
                origin=origin,
            )

        issues: list[Issue] = []
        rows: list[MergeRow] = []
        for number, values in enumerate(reader, start=2):
            if not values:
                continue  # A trailing blank line; every writer leaves one.
            row = _row_from_csv(values, f"row {number}", issues)
            if row is not None:
                rows.append(row)
        if issues:
            raise LifecycleError(issues, origin=origin)
        try:
            return cls(rows, origin=origin)
        except LifecycleError as error:
            raise LifecycleError(error.issues, origin=origin) from None

    # ------------------------------------------------------------------ lookup

    @property
    def rows(self) -> tuple[MergeRow, ...]:
        return self._rows

    def __len__(self) -> int:
        return len(self._rows)

    def __iter__(self) -> Iterator[MergeRow]:
        return iter(self._rows)

    def replacement(self, iri: str) -> str | None:
        """The successor this register names for ``iri``, or ``None``. The row's own
        statement, never the end of a chain."""
        row = self._by_deprecated.get(iri)
        return None if row is None else row.replaced_by_iri

    # ------------------------------------------------------------------ checks

    def check_against(self, id_map: IdMap) -> tuple[Issue, ...]:
        """Both IRIs of every row must be known to the ID map (spec 5.4)."""
        issues: list[Issue] = []
        for row in self._rows:
            for column, iri in (
                ("deprecated_iri", row.deprecated_iri),
                ("replaced_by_iri", row.replaced_by_iri),
            ):
                if not id_map.owners(iri):
                    issues.append(
                        Issue(
                            Severity.ERROR,
                            f"the merge register names {iri} as its {column}, which is not "
                            f"in the ID map; a merge is recorded between two objects this "
                            f"instance has minted",
                            f"{MERGES_PATH.as_posix()}:{iri}",
                        )
                    )
        return tuple(issues)

    def _cycles(self) -> list[Issue]:
        """One issue per cycle in the register. A cycle names no survivor; a chain is fine."""
        issues: list[Issue] = []
        reported: set[frozenset[str]] = set()
        for start in sorted(self._by_deprecated):
            path: list[str] = []
            seen: set[str] = set()
            current = start
            while current in self._by_deprecated and current not in seen:
                seen.add(current)
                path.append(current)
                current = self._by_deprecated[current].replaced_by_iri
            if current not in seen:
                continue
            cycle = path[path.index(current) :]
            if frozenset(cycle) in reported:
                continue
            reported.add(frozenset(cycle))
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"the merge register is circular: {' → '.join([*cycle, current])}; "
                    f"every object in the loop is replaced by another that is itself "
                    f"deprecated, so the register names no survivor",
                    min(cycle),
                )
            )
        return issues

    # ------------------------------------------------------------------ writing

    def dumps(self) -> str:
        """Render the register as CSV, LF-terminated on every platform."""
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(MERGES_COLUMNS)
        writer.writerows(row.values for row in self._rows)
        return buffer.getvalue()

    def save(self, repo_root: Path | None = None) -> Path:
        """Write the register to ``<repo_root>/mappings/merges.csv``. Used by ``semprini init``
        only (spec 5.7); no compile writes it."""
        path = (Path.cwd() if repo_root is None else Path(repo_root)) / MERGES_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.dumps(), encoding="utf-8", newline="\n")
        return path


def _row_from_csv(values: Sequence[str], location: str, issues: list[Issue]) -> MergeRow | None:
    """Build one row, appending an issue instead of raising."""
    if len(values) != len(MERGES_COLUMNS):
        issues.append(
            Issue(
                Severity.ERROR,
                f"expected {len(MERGES_COLUMNS)} columns, found {len(values)}",
                location,
            )
        )
        return None

    # Stripped, because a person typed these. The note is left as written.
    deprecated_iri, replaced_by_iri, date = (value.strip() for value in values[:3])
    note = values[3]
    for column, value in (
        ("deprecated_iri", deprecated_iri),
        ("replaced_by_iri", replaced_by_iri),
    ):
        if not value:
            issues.append(Issue(Severity.ERROR, f"'{column}' must not be empty", location))
            return None
    try:
        parsed_date = datetime.datetime.strptime(date, _ISO_DATE).date()
    except ValueError:
        issues.append(
            Issue(Severity.ERROR, f"'date' must be a date (YYYY-MM-DD), got {date!r}", location)
        )
        return None
    return MergeRow(
        deprecated_iri=deprecated_iri,
        replaced_by_iri=replaced_by_iri,
        date=parsed_date,
        note=note,
    )


# ----------------------------------------------------------------------------- planning


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecyclePlan:
    """What lifecycle decided, handed to the build stage (spec 3.5)."""

    carried: tuple[CarriedNode, ...] = ()
    """Every node retained from the previous output, all deprecated. Passed to
    :func:`semprini.build.build` as ``carried``."""

    deprecated: tuple[str, ...] = ()
    """IRIs this run moved from active to deprecated, sorted."""


def plan(
    model: InternalModel,
    *,
    registry: Registry,
    previous: Mapping[str, Graph],
    merges: MergeRegister | None = None,
) -> LifecyclePlan:
    """Decide what happens to every node the previous run wrote (spec 3.5, 5.4).

    ``previous`` is :func:`semprini.build.read_previous_files`, per file, because a
    retained node stays in the file that held it. A node no object in ``model`` resolves
    to is deprecated, whatever source used to own it. Nothing is minted here.

    Raises :class:`LifecycleError` for a register row the ID map does not know, a
    merged-away object the sources still report, or a generated node with no ID-map row.
    """
    register = MergeRegister() if merges is None else merges
    issues = list(register.check_against(registry.id_map))

    live = {
        iri
        for object_ in model.objects
        for ref in object_.refs
        if (iri := registry.iri(ref)) is not None
    }
    issues.extend(_check_merges_are_gone(register, live))

    index = _index(previous)
    carried: list[CarriedNode] = []
    deprecated: list[str] = []
    for subject in sorted(index, key=str):
        blocks = index[subject]
        if not any(block.defines for block in blocks):
            # A sem:relatesTo shortcut (spec 4.2); build re-derives it from its relationship.
            continue
        iri = str(subject)
        if iri in live:
            continue

        if not registry.id_map.owners(iri):
            # A deleted row or a hand-edited file (spec 4.3); refused, never dropped.
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"{iri} is in the generated output but not in the ID map; an IRI is "
                    f"never removed from the map (spec 3.4), and without its row nothing "
                    f"can say which source it came from",
                    blocks[0].file,
                )
            )
            continue

        carried.extend(_deprecate(subject, blocks, register.replacement(iri)))
        if any(block.was_active for block in blocks):
            deprecated.append(iri)

    if issues:
        raise LifecycleError(issues)
    return LifecyclePlan(carried=tuple(carried), deprecated=tuple(deprecated))


def _check_merges_are_gone(register: MergeRegister, live: Collection[str]) -> list[Issue]:
    """A merged-away object must be gone from the sources (spec 5.4)."""
    return [
        Issue(
            Severity.ERROR,
            f"the merge register says {row.deprecated_iri} was replaced by "
            f"{row.replaced_by_iri}, but the sources still describe it; remove the object "
            f"in the source system, or remove the register row",
            f"{MERGES_PATH.as_posix()}:{row.deprecated_iri}",
        )
        for row in register
        if row.deprecated_iri in live
    ]


def _deprecate(
    subject: URIRef, blocks: Sequence[_PreviousBlock], replacement: str | None
) -> Iterator[CarriedNode]:
    """Re-emit a node's last-known statements with its status changed (spec 3.5).

    Only the statements in ``_DERIVED`` are replaced, on the block that defines the node (spec 4.2).
    """
    for block in blocks:
        statements = {(p, o) for p, o in block.statements if p not in _DERIVED}
        if block.defines:
            statements.add((SEM_STATUS, Literal(STATUS_DEPRECATED)))
            if replacement is not None:
                statements.add((DCTERMS.isReplacedBy, URIRef(replacement)))
        yield CarriedNode(
            file=block.file,
            subject=subject,
            statements=frozenset(statements),
            defines=block.defines,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class _PreviousBlock:
    """What one generated file said about one subject on the previous run."""

    file: str
    statements: frozenset[tuple[URIRef, Node]]
    defines: bool
    """Whether this block carries the node's ``skos:prefLabel``, which is what defines a node (spec
    4.2).
    """

    @property
    def was_active(self) -> bool:
        return (SEM_STATUS, Literal(STATUS_ACTIVE)) in self.statements


def _index(previous: Mapping[str, Graph]) -> Mapping[URIRef, tuple[_PreviousBlock, ...]]:
    """The previous output as blocks, grouped by subject and ordered by file name."""
    blocks: dict[URIRef, list[_PreviousBlock]] = {}
    for name in sorted(previous):
        statements: dict[URIRef, set[tuple[URIRef, Node]]] = {}
        for subject, predicate, object_ in previous[name]:
            if not isinstance(subject, URIRef) or not isinstance(predicate, URIRef):
                # A hand-edited file (spec 5.5 rule 7); check 2 reports it.
                continue
            statements.setdefault(subject, set()).add((predicate, object_))
        for subject, found in sorted(statements.items(), key=lambda item: str(item[0])):
            blocks.setdefault(subject, []).append(
                _PreviousBlock(
                    file=name,
                    statements=frozenset(found),
                    defines=any(predicate == SKOS.prefLabel for predicate, _ in found),
                )
            )
    return {subject: tuple(items) for subject, items in blocks.items()}

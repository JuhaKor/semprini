"""Deprecation, carry-forward and the merge register (spec 3.5, 5.4).

The stage that decides what happens to an object when its source stops mentioning it. The
answer is never "delete": an IRI that has been published is pointed at by queries,
dashboards and other organizations' `skos:exactMatch` triples, so a node is retained with
its last-known statements and marked `sem:status "deprecated"` (spec 3.5). Deletion is the
one operation this project has no way to undo, which is why nothing here can perform one.

Three rules carry the weight.

*Deprecation is judged against the union of all configured sources* (spec 5.4). Never
against one source, and never against one model — an entity that vanished from the sales
model but is still in the finance model has not been deleted, it has moved, and it loses
one `skos:inScheme` triple. The unit of the question is the object, and the evidence is
every source the instance configures.

*A run that did not look cannot conclude.* A `--source X` run fetched one source, so it
knows nothing about objects any other source owns. Those are carried forward **exactly as
they are** rather than skipped: skipping would leave them out of the files this run
rewrites, which is not "no deprecation" but silent deletion — the loudest possible version
of the thing this module exists to prevent.

*The register is a steward's statement, not the compiler's inference.* Sources usually
implement a merge by deleting one of the two objects, which on its own is indistinguishable
from a deletion. ``mappings/merges.csv`` is where a steward says which object survived; the
compiler emits `dcterms:isReplacedBy` from it and infers nothing.
"""

from __future__ import annotations

import csv
import datetime
import io
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, SKOS
from rdflib.term import Node

from semprini.build import (
    SEM_RELATES_TO,
    SEM_SOURCE,
    SEM_STATUS,
    SEM_TARGET,
    STATUS_ACTIVE,
    STATUS_DEPRECATED,
    CarriedNode,
)
from semprini.identity import IdMap, Registry
from semprini.model import InternalModel, Issue, IssueError, RunContext, Severity

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
"""Exactly the columns of spec 5.4, in that order. Checked on load for the reason the ID
map's are: a column quietly renamed or reordered would make the register silently do
nothing, and its whole purpose is to be consulted on the day an object disappears."""

_ISO_DATE = "%Y-%m-%d"

# Statements this stage derives rather than carries. sem:status is what deprecation
# changes; dcterms:isReplacedBy comes from the register as it reads *now*, so removing a
# row removes a triple; and dcterms:modified is recomputed for every node the run writes,
# which is what lets a carried node keep the date it had (spec 3.3).
_DERIVED = frozenset({SEM_STATUS, DCTERMS.isReplacedBy, DCTERMS.modified})


class LifecycleError(IssueError):
    """Lifecycle state the compiler refuses to act on — CLI exit code 1 (spec 5.1).

    A compile failure rather than a configuration error: a malformed merge register, a
    register row for an IRI nothing knows, or generated output holding a node the ID map
    has never heard of all mean the repository's committed state disagrees with itself,
    and no edit of ``config/semprini.yaml`` addresses any of them.
    """

    noun = "lifecycle error"


# ------------------------------------------------------------------------ merge register


@dataclass(frozen=True, slots=True, kw_only=True)
class MergeRow:
    """One row of ``mappings/merges.csv``: two objects a steward says are one (spec 5.4)."""

    deprecated_iri: str
    replaced_by_iri: str
    date: datetime.date
    """When the merge was recorded. Steward-supplied and never read by the compiler — it
    is here so a reviewer reading the register three years later knows when someone
    decided this, which the generated output cannot tell them."""

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
    """``mappings/merges.csv`` in memory, validated as it is built (spec 5.4).

    Hand-maintained, unlike the ID map, so every way of getting it wrong is a way a person
    can get it wrong: naming one object twice, pointing a row at itself, or writing a chain
    that closes on itself. Each is refused at construction, because a register that cannot
    name a survivor is worse than no register — it would deprecate an object and leave
    nothing to redirect its consumers to.
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
        """Read ``<repo_root>/mappings/merges.csv``.

        A missing file is an empty register, not an error: an instance that has never
        merged two concepts has nothing to record, and one bootstrapped before this file
        existed must still compile.
        """
        path = (Path.cwd() if repo_root is None else Path(repo_root)) / MERGES_PATH
        try:
            # utf-8-sig for the ID map's reason: stewards edit this in Excel, which writes
            # a byte-order mark, and left in place it joins the first column name and makes
            # the header error print two column lists that look identical.
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
            # An empty file, as opposed to an absent one: `semprini init` writes headers
            # (spec 5.7 step 3), so a file with none has been damaged.
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
        """The successor this register names for ``iri``, or ``None``.

        Exactly what the row says, never the end of a chain. If a steward recorded A → B
        and later B → C, then A's successor is B: that is the statement they made, and
        rewriting it to C would put a triple in a governed file that no row in the register
        supports. A consumer that wants the survivor follows the chain, which is well
        defined because a circular register is refused.
        """
        row = self._by_deprecated.get(iri)
        return None if row is None else row.replaced_by_iri

    # ------------------------------------------------------------------ checks

    def check_against(self, id_map: IdMap) -> tuple[Issue, ...]:
        """Both IRIs of every row must be known to the ID map (spec 5.4).

        The register is the one file in an instance where a person types an IRI by hand, so
        a mistyped one is the expected failure rather than an exotic one — and an unchecked
        row would deprecate nothing, or point a successor at an IRI this instance never
        minted, with nothing in the diff to show either.
        """
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
        """Refuse a register whose rows lead back to where they started.

        A cycle names no survivor: every object in it is deprecated in favour of another
        object that is itself deprecated, so a consumer following `dcterms:isReplacedBy`
        never arrives anywhere. Rows that merely *chain* — A → B, B → C — are fine and are
        left alone.
        """
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
            # One issue per cycle, not one per member: every IRI in a cycle finds the same
            # cycle, and reporting it n times would bury the n other problems in the file.
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

    # ------------------------------------------------------------------ rebasing

    def rebased(self, old_base: str, new_base: str) -> MergeRegister:
        """The same decisions, with every IRI under ``old_base`` moved (spec 3.4.4).

        The register travels with the ID map through a namespace move, and it is the one
        file in an instance where a person typed those IRIs. Left behind, every row would
        name an IRI the moved map has never heard of, and the next run would refuse it —
        so the migration ``--force-namespace-change`` exists to perform could not be
        performed at all on an instance that had ever recorded a merge.

        This is the only circumstance in which a compile writes this file, and it changes
        no decision: a row still says the same two objects are one, in the namespace they
        now live in. An IRI outside the old base is left exactly as it is, so a row that
        was already wrong stays wrong and is reported by :meth:`check_against` rather than
        quietly acquiring a new namespace.
        """
        return MergeRegister(
            (
                replace(
                    row,
                    deprecated_iri=_rebased_iri(row.deprecated_iri, old_base, new_base),
                    replaced_by_iri=_rebased_iri(row.replaced_by_iri, old_base, new_base),
                )
                for row in self._rows
            ),
            origin=self.origin,
        )

    # ------------------------------------------------------------------ writing

    def dumps(self) -> str:
        """Render the register as CSV — LF-terminated, whatever platform wrote it."""
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(MERGES_COLUMNS)
        writer.writerows(row.values for row in self._rows)
        return buffer.getvalue()

    def save(self, repo_root: Path | None = None) -> Path:
        """Write the register to ``<repo_root>/mappings/merges.csv``.

        Here for ``semprini init``, which creates the file with its headers (spec 5.7).
        Every row in it is a steward's decision, so the only compile that writes it is a
        namespace move, which rewrites the IRIs in those rows without touching what they
        say (spec 3.4.4, :meth:`rebased`).
        """
        path = (Path.cwd() if repo_root is None else Path(repo_root)) / MERGES_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.dumps(), encoding="utf-8", newline="\n")
        return path


def _rebased_iri(iri: str, old_base: str, new_base: str) -> str:
    return new_base + iri[len(old_base) :] if iri.startswith(old_base) else iri


def _row_from_csv(values: Sequence[str], location: str, issues: list[Issue]) -> MergeRow | None:
    """Build one row, appending an issue instead of raising, so every bad row is seen."""
    if len(values) != len(MERGES_COLUMNS):
        issues.append(
            Issue(
                Severity.ERROR,
                f"expected {len(MERGES_COLUMNS)} columns, found {len(values)}",
                location,
            )
        )
        return None

    # Stripped, unlike the ID map's columns, because these are the one pair of IRIs in an
    # instance that a person types rather than the compiler writes. A trailing space would
    # otherwise match nothing in the ID map and be reported as an unknown IRI, which is
    # true and unhelpful. The note is left exactly as written.
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
    """Every node retained from the previous output: deprecated ones, and — on a partial
    run — ones this run had no evidence about. Passed to
    :func:`semprini.build.build` as ``carried``."""

    deprecated: tuple[str, ...] = ()
    """IRIs this run moved from active to deprecated, sorted. A node that was already
    deprecated is not listed: it did not change, and the run report counts changes."""


def plan(
    model: InternalModel,
    *,
    registry: Registry,
    context: RunContext,
    previous: Mapping[str, Graph],
    sources: Collection[str],
    merges: MergeRegister | None = None,
) -> LifecyclePlan:
    """Decide what happens to every node the previous run wrote (spec 3.5, 5.4).

    Runs **before** the build stage and after the sources have been fetched: it compares
    what the sources now report against what ``generated/`` currently holds, and produces
    the nodes build must retain. ``previous`` is
    :func:`semprini.build.read_previous_files` — per file, because a retained node stays
    in the file that held it.

    ``sources`` is every configured source's name. Together with ``context.only_source``
    it decides the run's *scope*: a full run has looked at everything and may conclude an
    object is gone, while a ``--source X`` run has looked at one source and may only
    conclude it about objects that source alone owns.

    Deliberately reads the ID map without resolving the model, so nothing is minted here.
    An object new to this run has no IRI yet, and a node in the previous output always
    has one — that asymmetry is exactly what makes "absent from the sources" answerable.
    """
    register = MergeRegister() if merges is None else merges
    issues = list(register.check_against(registry.id_map))

    fetched = (
        frozenset({context.only_source}) if context.only_source is not None else frozenset(sources)
    )
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
    handled: set[URIRef] = set()
    frozen_pairs: set[tuple[URIRef, URIRef]] = set()
    for subject in sorted(index, key=str):
        blocks = index[subject]
        if not any(block.defines for block in blocks):
            # Something stated *about* a node rather than a description of it — the
            # sem:relatesTo shortcut (spec 4.2). Its fate follows the relationship it was
            # derived from, not its own, so it is dealt with in the second pass below.
            continue
        iri = str(subject)
        if iri in live:
            continue

        owners = registry.id_map.owners(iri)
        if not owners:
            # Generated output holding a node the ID map does not: the row was deleted or
            # the file was hand-edited (spec 4.3). Refused rather than dropped, because
            # dropping it is the deletion this whole module exists to make impossible —
            # and refused here rather than left to spec 6.1 check 6, which needs git to
            # compare against a base revision and this does not.
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

        handled.add(subject)
        if all(row.source_name in fetched for row in owners):
            replacement = register.replacement(iri)
            carried.extend(_deprecate(subject, blocks, replacement))
            if any(block.was_active for block in blocks):
                deprecated.append(iri)
        else:
            # Out of scope: this run fetched none of the sources that own the node, or not
            # all of them, so it has no evidence either way. Carried unchanged rather than
            # skipped — build rewrites each file whole, so a node left out of the plan is
            # a node deleted from the instance (spec 5.4).
            carried.extend(_verbatim(subject, blocks))
            frozen_pairs.update(_ends(blocks))

    carried.extend(_retained_shortcuts(index, handled, frozen_pairs, _derivable(model, registry)))

    if issues:
        raise LifecycleError(issues)
    return LifecyclePlan(carried=tuple(carried), deprecated=tuple(deprecated))


def _derivable(model: InternalModel, registry: Registry) -> set[tuple[URIRef, URIRef]]:
    """The entity pairs this run's own relationships will produce a shortcut for."""
    pairs = set()
    for relationship in model.relationships:
        source = registry.iri(relationship.source)
        target = registry.iri(relationship.target)
        if source is not None and target is not None:
            pairs.add((URIRef(source), URIRef(target)))
    return pairs


def _ends(blocks: Sequence[_PreviousBlock]) -> set[tuple[URIRef, URIRef]]:
    """The ``(sem:source, sem:target)`` pair of a relationship node, if it is one."""
    statements = {(p, o) for block in blocks for p, o in block.statements}
    sources = [o for p, o in statements if p == SEM_SOURCE and isinstance(o, URIRef)]
    targets = [o for p, o in statements if p == SEM_TARGET and isinstance(o, URIRef)]
    return {(source, target) for source in sources for target in targets}


def _retained_shortcuts(
    index: Mapping[URIRef, tuple[_PreviousBlock, ...]],
    handled: Collection[URIRef],
    frozen_pairs: Collection[tuple[URIRef, URIRef]],
    derivable: Collection[tuple[URIRef, URIRef]],
) -> Iterator[CarriedNode]:
    """Keep a ``sem:relatesTo`` shortcut whose relationship this run did not judge.

    The shortcut is the one statement written away from the node it is about (spec 4.2):
    its subject is the source entity, but it lives in the relationship's file. So when the
    entity is still reported and the *relationship* is out of scope, neither of the rules
    above reaches it — the entity is rebuilt from the model, which no longer contains the
    relationship, and the shortcut would be quietly dropped while the relationship it
    derives from was carried forward as active. That is a governed triple deleted by a run
    that explicitly concluded nothing.

    Two cases are deliberately **not** retained. A pair the model still has a relationship
    for is re-derived by the build stage, and writing it here as well would put one triple
    in two files. And a pair whose only relationship was *deprecated* is gone on purpose:
    ``sem:relatesTo`` carries no status of its own, so leaving it would assert a live
    relation between two entities on the strength of a retired one.
    """
    for subject in sorted(index, key=str):
        if subject in handled:
            # Its blocks were carried whole, shortcuts included.
            continue
        for block in index[subject]:
            if block.defines:
                continue
            targets = sorted(
                (
                    object_
                    for predicate, object_ in block.statements
                    if predicate == SEM_RELATES_TO
                    and isinstance(object_, URIRef)
                    and (subject, object_) in frozen_pairs
                    and (subject, object_) not in derivable
                ),
                key=str,
            )
            if targets:
                yield CarriedNode(
                    file=block.file,
                    subject=subject,
                    statements=frozenset((SEM_RELATES_TO, target) for target in targets),
                    defines=False,
                )


def _check_merges_are_gone(register: MergeRegister, live: Collection[str]) -> list[Issue]:
    """A merged-away object must actually be gone from the sources.

    The register records a merge the source tool has already performed by deleting one of
    the objects (spec 5.4). If the sources still report it, the two disagree, and the
    compiler is not the one to settle it: deprecating an object every source still
    describes would override the sources from a one-line CSV edit, while ignoring the row
    would make the register silently inert. The run stops and says which it is.
    """
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

    Everything the previous run said is kept, so the node goes on answering the queries it
    always did; only the three statements this stage owns are replaced. `sem:status` and
    `dcterms:isReplacedBy` go on the block that *describes* the node — a node is described
    once however many files mention it (spec 4.2).
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


def _verbatim(subject: URIRef, blocks: Sequence[_PreviousBlock]) -> Iterator[CarriedNode]:
    """Re-emit a node exactly as it stands, `sem:status` included.

    Only `dcterms:modified` is dropped, and only because the build stage recomputes it for
    every node it writes: the statements are unchanged, so it computes the same date back.
    """
    for block in blocks:
        yield CarriedNode(
            file=block.file,
            subject=subject,
            statements=frozenset((p, o) for p, o in block.statements if p != DCTERMS.modified),
            defines=block.defines,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class _PreviousBlock:
    """What one generated file said about one subject on the previous run."""

    file: str
    statements: frozenset[tuple[URIRef, Node]]
    defines: bool
    """Whether this block carries the node's ``skos:prefLabel`` — which is what it means
    for a file to *define* a node rather than merely mention it (spec 4.2)."""

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
                # The serializer refuses to write either (spec 5.5 rule 7), so this is a
                # hand-edited file; spec 6.1 check 2 is what reports it, and reading past
                # it here keeps this stage from deciding it on the strength of a triple.
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

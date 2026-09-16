"""Bundled Excel taxonomy adapter (spec 5.3).

One workbook is one taxonomy and one configured source. The hierarchy is ragged: a
value's depth is its position across the ``L1..Ln`` preferred-label columns, and a value
at depth *k* is narrower than the row whose path is its first *k-1* labels. A cycle
cannot be expressed; the error conditions are dangling parents, duplicates and skipped
levels. Identity comes from the ``Concept URI`` column, never from labels (spec 5.4).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from semprini.adapters.base import AdapterError, BaseAdapter, SourceUnreachableError
from semprini.config import ConfigError, escapes_the_instance, is_slug
from semprini.model import (
    InternalModel,
    Issue,
    Scheme,
    SchemeType,
    Severity,
    SourceRef,
    TaxonomyValue,
    Text,
    is_language_tag,
    normalize_text,
)

__all__ = ["ExcelTaxonomyAdapter"]

SCHEME_SHEET = "Concept Scheme"
TAXONOMY_SHEET = "Taxonomy"

_SETTINGS = frozenset({"path", "scheme_slug", "enumerates_source"})

# Scheme-sheet rows this adapter reads; every other row is documentation for the maintainer.
_SCHEME_NAME = "scheme name"
_SCHEME_DESCRIPTION = "description"
_SCHEME_LANGUAGE = "language"
_SCHEME_ENUMERATES = "reference entity uuid"

_CONCEPT_URI = "concept uri"
_DEFINITION = "definition"
_ALT_LABELS = "alternative labels"
_HIDDEN_LABELS = "hidden labels"
_SCOPE_NOTE = "scope note"
_EXAMPLE = "example"

# The value columns carried into the model; any other column is ignored.
_VALUE_COLUMNS = (_DEFINITION, _ALT_LABELS, _HIDDEN_LABELS, _SCOPE_NOTE, _EXAMPLE)

_LEVEL_HEADER = re.compile(r"^l(\d+)\s*-\s*preferred label")

# A cell written in Turtle's literal syntax: "Computers & Tablets"@en (spec 5.5 rule 6).
_LITERAL = re.compile(r'^\s*"([^"]*)"(?:@([A-Za-z0-9-]+))?\s*$', re.DOTALL)


class TaxonomyContentError(AdapterError):
    """A workbook was read but says something the compiler cannot act on — exit code 1 (spec 5.1).

    Collects every problem in the workbook.
    """

    def __init__(self, path: Path, issues: Sequence[Issue]) -> None:
        self.issues = tuple(issues)
        listed = "\n".join(f"  - {issue}" for issue in self.issues)
        count = f"{len(self.issues)} problem" + ("s" if len(self.issues) != 1 else "")
        super().__init__(f"{path}: {count}\n{listed}")


class ExcelTaxonomyAdapter(BaseAdapter):
    """A taxonomy workbook: one file, one concept scheme, a ragged label hierarchy.

    The line above is what ``semprini adapters`` prints beside this adapter's name.

    Settings:

    ``path``
        The workbook, relative to the instance repository (spec 4.2).
    ``scheme_slug``
        The scheme's permanent slug (spec 3.4.2, 4.2).
    ``enumerates_source``
        The configured source that issued the ``Reference Entity UUID``, normally the
        modelling tool's. Required exactly when that cell is filled (spec 5.4).
    """

    name = "excel-taxonomy"

    _fetched: int | None = None
    """How many values the last fetch read, for :meth:`summary`."""

    # --------------------------------------------------------------------- the contract

    def fetch(self) -> InternalModel:
        # Spec 5.3: an adapter validates its own settings before reading anything.
        issues = [issue for issue in self.validate_config() if issue.severity is Severity.ERROR]
        if issues:
            raise ConfigError(issues)

        path = self._path()
        workbook = self._open(path)
        try:
            metadata = _read_scheme_sheet(self._sheet(workbook, SCHEME_SHEET, path), path)
            language = metadata.get(_SCHEME_LANGUAGE)
            if language is not None and not is_language_tag(language):
                raise TaxonomyContentError(
                    path,
                    [
                        Issue(
                            Severity.ERROR,
                            f"not a language tag: {language!r}",
                            f"{SCHEME_SHEET}!Language",
                        )
                    ],
                )
            sheet = self._sheet(workbook, TAXONOMY_SHEET, path)
            rows = _read_taxonomy_sheet(sheet, path, language)
        finally:
            workbook.close()

        slug = str(self.config["scheme_slug"])
        values = _build_values(rows, path, source=self.source_name, slug=slug, language=language)
        self._fetched = len(values)
        return InternalModel(
            schemes=(self._scheme(metadata, slug, language),), taxonomy_values=values
        )

    def validate_config(self) -> list[Issue]:
        issues: list[Issue] = []
        where = f"sources.{self.source_name}.config"

        raw = self.config.get("path")
        if not raw:
            issues.append(
                Issue(Severity.ERROR, "a taxonomy source needs a 'path'", f"{where}.path")
            )
        elif escapes_the_instance(str(raw)):
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"path must be inside the instance repository, got {raw!r}",
                    f"{where}.path",
                )
            )

        slug = self.config.get("scheme_slug")
        if not slug:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "a taxonomy source needs a 'scheme_slug'",
                    f"{where}.scheme_slug",
                )
            )
        elif not is_slug(str(slug)):
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"not a slug: {slug!r} (lower-case letters, digits, '-' and '_')",
                    f"{where}.scheme_slug",
                )
            )

        owner = self.config.get("enumerates_source")
        if owner is not None and not is_slug(str(owner)):
            # Only the shape is checkable here; a misspelt name is reported by the build stage.
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"not a source name: {owner!r} (lower-case letters, digits, '-' and '_')",
                    f"{where}.enumerates_source",
                )
            )
        elif owner is not None and str(owner) == self.source_name:
            issues.append(
                Issue(
                    Severity.ERROR,
                    "'enumerates_source' names this source itself; it names the source "
                    "whose model defines the reference entity, not the taxonomy",
                    f"{where}.enumerates_source",
                )
            )

        for key in sorted(set(self.config) - _SETTINGS):
            issues.append(Issue(Severity.ERROR, f"unknown setting {key!r}", f"{where}.{key}"))
        return issues

    def summary(self) -> str:
        if self._fetched is None:
            return ""
        return f"{self._fetched} values from {Path(str(self.config['path'])).name}"

    # ------------------------------------------------------------------------ internals

    def _scheme(self, metadata: Mapping[str, str], slug: str, language: str | None) -> Scheme:
        enumerates = metadata.get(_SCHEME_ENUMERATES)
        owner = str(self.config.get("enumerates_source") or "")
        if enumerates and not owner:
            # Exit 2: only the workbook knows whether the cell is filled.
            raise ConfigError(
                [
                    Issue(
                        Severity.ERROR,
                        f"the workbook names {enumerates!r} as the entity this taxonomy "
                        f"enumerates, so 'enumerates_source' must name the configured "
                        f"source that issued that key — the modelling tool's source, not "
                        f"this one",
                        f"sources.{self.source_name}.config.enumerates_source",
                    )
                ]
            )
        return Scheme(
            # Keyed by the slug, not the file name, so the workbook can move (spec 5.4).
            source_refs={self.source_name: slug},
            pref_label=_text(metadata[_SCHEME_NAME], language),
            definition=_optional_text(metadata.get(_SCHEME_DESCRIPTION), language),
            slug=slug,
            scheme_type=SchemeType.TAXONOMY,
            # Keyed under the modelling tool's source, whose row the entity carries (spec 5.4).
            enumerates=SourceRef(owner, enumerates) if enumerates else None,
        )

    def _path(self) -> Path:
        return self.ctx.repo_root / str(self.config["path"])

    def _open(self, path: Path) -> Any:
        try:
            return load_workbook(path, data_only=True, read_only=False)
        except OSError as error:
            raise SourceUnreachableError(
                f"source {self.source_name!r}: cannot read {path}: {error}"
            ) from error
        except Exception as error:  # openpyxl raises its own types for a corrupt file
            raise AdapterError(
                f"source {self.source_name!r}: {path} is not a readable workbook: {error}"
            ) from error

    def _sheet(self, workbook: Any, title: str, path: Path) -> Worksheet:
        if title not in workbook.sheetnames:
            raise TaxonomyContentError(
                path, [Issue(Severity.ERROR, f"the workbook has no {title!r} sheet")]
            )
        sheet: Worksheet = workbook[title]
        return sheet


# --------------------------------------------------------------------------- the sheets


def _normalize_header(value: object) -> str:
    """A header cell as a key: first line only, normalized, lower-cased (spec 5.5 rule 9).

    The second line of a header carries the column's SKOS mapping as documentation.
    """
    if value is None:
        return ""
    return normalize_text(str(value).split("\n", 1)[0]).lower()


def _cell(value: object) -> str:
    """A cell as normalized text (spec 5.5 rule 9). Keys and path cells never reach ``Text``,
    so normalization happens here."""
    return "" if value is None else normalize_text(str(value))


def _read_scheme_sheet(sheet: Worksheet, path: Path) -> Mapping[str, str]:
    """The vertical Property/Value table, as normalized property → value."""
    metadata = {
        _normalize_header(row[0]): _cell(row[1])
        for row in sheet.iter_rows(min_row=2, max_col=2, values_only=True)
        if row and row[0] is not None
    }
    metadata = {key: value for key, value in metadata.items() if value}
    if not metadata.get(_SCHEME_NAME):
        raise TaxonomyContentError(
            path,
            [Issue(Severity.ERROR, "no 'Scheme Name' row", f"{SCHEME_SHEET}!A")],
        )
    return metadata


class _Row:
    """One taxonomy row, already split into the parts the model needs."""

    __slots__ = ("key", "label", "number", "path", "values")

    def __init__(
        self,
        number: int,
        key: str,
        path: tuple[str, ...],
        label: Text,
        values: Mapping[str, str],
    ):
        self.number = number
        self.key = key
        self.path = path
        """The label values of this row's level cells, ancestors first. Values, not raw
        cells: ``"Tools"@en`` and a bare ``Tools`` are one branch."""

        self.label = label
        """This row's own preferred label: the deepest level cell, with its language."""

        self.values = values


def _read_taxonomy_sheet(sheet: Worksheet, path: Path, language: str | None) -> Sequence[_Row]:
    """Read the sheet into rows, refusing a header this adapter cannot act on.

    Header matching is strict: a sheet with misnamed level columns would otherwise read
    as an empty taxonomy and deprecate everything in it.
    """
    header = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
    columns: dict[str, int] = {}
    levels: list[tuple[int, int]] = []
    for index, raw in enumerate(header):
        name = _normalize_header(raw)
        if not name:
            continue
        columns.setdefault(name, index)
        match = _LEVEL_HEADER.match(name)
        if match:
            levels.append((int(match.group(1)), index))
    levels.sort()

    found = ", ".join(sorted(columns)) or "no headers at all"
    if _CONCEPT_URI not in columns:
        raise TaxonomyContentError(
            path,
            [
                Issue(
                    Severity.ERROR,
                    f"the {TAXONOMY_SHEET!r} sheet has no 'Concept URI' column, which is "
                    f"where a value's permanent identity comes from; found {found}",
                    f"{TAXONOMY_SHEET}!1",
                )
            ],
        )
    if not levels:
        raise TaxonomyContentError(
            path,
            [
                Issue(
                    Severity.ERROR,
                    f"the {TAXONOMY_SHEET!r} sheet has no 'L1 - Preferred Label' column, so "
                    f"it states no hierarchy and no labels; found {found}",
                    f"{TAXONOMY_SHEET}!1",
                )
            ],
        )
    declared = [number for number, _ in levels]
    if declared != list(range(1, len(declared) + 1)):
        # A missing level column would read every value one level too shallow.
        raise TaxonomyContentError(
            path,
            [
                Issue(
                    Severity.ERROR,
                    f"the {TAXONOMY_SHEET!r} sheet's level columns are "
                    f"{', '.join(f'L{number}' for number in declared)}; they must run "
                    f"L1..L{len(declared)} with none missing, or every value's depth is "
                    f"read one level out",
                    f"{TAXONOMY_SHEET}!1",
                )
            ],
        )

    issues: list[Issue] = []
    rows: list[_Row] = []
    for number, raw_row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
        level_columns = [index for _, index in levels]
        row = _read_row(raw_row, number, columns, level_columns, language, issues)
        if row is not None:
            rows.append(row)
    if issues:
        raise TaxonomyContentError(path, issues)
    return rows


def _read_row(
    raw: Sequence[object],
    number: int,
    columns: Mapping[str, int],
    level_columns: Sequence[int],
    language: str | None,
    issues: list[Issue],
) -> _Row | None:
    # Read once, so the normalization count is a count of cells.
    row = [_cell(item) for item in raw]

    def value(name: str) -> str:
        index = columns.get(name)
        return row[index] if index is not None and index < len(row) else ""

    cells = [row[index] if index < len(row) else "" for index in level_columns]
    key = _local_name(value(_CONCEPT_URI))
    if not any(row):
        # A wholly blank row is punctuation; a row with anything in it is judged.
        return None
    where = f"{TAXONOMY_SHEET}!{number}"
    if not key:
        issues.append(Issue(Severity.ERROR, "no 'Concept URI', so this row has no identity", where))
        return None

    filled = [index for index, cell in enumerate(cells) if cell]
    if not filled:
        issues.append(Issue(Severity.ERROR, f"{key!r} has no preferred label", where))
        return None
    if filled != list(range(len(filled))):
        # Depth is the position of the last filled cell; L1+L3 is not depth 2.
        missing = ", ".join(f"L{index + 1}" for index in range(filled[-1]) if index not in filled)
        issues.append(Issue(Severity.ERROR, f"{key!r} skips a level: {missing} is empty", where))
        return None

    # Parsed before matching: "Tools"@en and a bare Tools are one branch.
    labels = [_text(cell, language) for cell in cells[: filled[-1] + 1]]
    values = {name: value(name) for name in _VALUE_COLUMNS}
    return _Row(number, key, tuple(text.value for text in labels), labels[-1], values)


def _local_name(reference: str) -> str:
    """``ont:Laptops`` → ``Laptops``. The prefix is no part of the identity (spec 5.4)."""
    return reference.rsplit(":", 1)[-1].strip()


# ------------------------------------------------------------------------ the model


def _build_values(
    rows: Sequence[_Row], path: Path, *, source: str, slug: str, language: str | None
) -> tuple[TaxonomyValue, ...]:
    """Turn rows into values, resolving the ragged hierarchy into ``skos:broader``."""
    issues: list[Issue] = []
    by_path: dict[tuple[str, ...], _Row] = {}
    by_key: dict[str, _Row] = {}

    for row in rows:
        where = f"{TAXONOMY_SHEET}!{row.number}"
        clash = by_key.get(row.key)
        if clash is not None:
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"{row.key!r} is already the identity of row {clash.number}; one "
                    f"identifier is one value",
                    where,
                )
            )
        else:
            by_key[row.key] = row
        twin = by_path.get(row.path)
        if twin is not None:
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"{' / '.join(row.path)!r} is already the path of row {twin.number}; "
                    f"two values cannot sit in one place in the hierarchy",
                    where,
                )
            )
        else:
            by_path[row.path] = row

    values: list[TaxonomyValue] = []
    for row in rows:
        parent: SourceRef | None = None
        if len(row.path) > 1:
            above = by_path.get(row.path[:-1])
            if above is None:
                issues.append(
                    Issue(
                        Severity.ERROR,
                        f"{row.key!r} is narrower than {' / '.join(row.path[:-1])!r}, which "
                        f"no row defines",
                        f"{TAXONOMY_SHEET}!{row.number}",
                    )
                )
                continue
            parent = SourceRef(source, above.key)
        scope_note = _optional_text(row.values[_SCOPE_NOTE], language)
        example = _optional_text(row.values[_EXAMPLE], language)
        values.append(
            TaxonomyValue(
                source_refs={source: row.key},
                pref_label=row.label,
                definition=_optional_text(row.values[_DEFINITION], language),
                schemes=(slug,),
                parent=parent,
                alt_labels=_texts(row.values[_ALT_LABELS], language),
                hidden_labels=_texts(row.values[_HIDDEN_LABELS], language),
                scope_notes=(scope_note,) if scope_note is not None else (),
                examples=(example,) if example is not None else (),
            )
        )

    if issues:
        raise TaxonomyContentError(path, issues)
    return tuple(values)


def _texts(raw: str, language: str | None) -> tuple[Text, ...]:
    """A semicolon-separated label cell. Only the label columns are split; notes and examples are
    prose.
    """
    return tuple(_text(part, language) for part in _split(raw) if part)


def _split(raw: str) -> Iterator[str]:
    """Split on semicolons outside a quoted literal, so ``"A; B"@fi; "C"@fi`` is two labels."""
    depth = 0
    current: list[str] = []
    for character in raw:
        if character == '"':
            depth = 1 - depth
        if character == ";" and depth == 0:
            yield "".join(current).strip()
            current = []
        else:
            current.append(character)
    yield "".join(current).strip()


def _text(raw: str, language: str | None) -> Text:
    """A cell as a text: its own tag, else the scheme's language, else none (spec 5.5 rule 6).

    A cell is literal syntax only when the quoted part holds no further quotation mark, so
    prose such as ``"Smart" tools "here"`` is left alone.
    """
    match = _LITERAL.match(raw)
    if match is None:
        return Text(raw, language)
    value, tag = match.group(1), match.group(2)
    return Text(value, tag or language)


def _optional_text(raw: str | None, language: str | None) -> Text | None:
    return _text(raw, language) if raw else None

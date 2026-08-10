"""The bundled Excel taxonomy adapter, and the fixture instance it compiles (spec 5.3).

Two things are under test and they answer different questions.

The *fixture instance* tests are the first end-to-end proof the plane has: a committed
instance — config, workbook, ID map, generated Turtle — recompiles to itself byte for
byte and mints nothing new. That is spec 5.4 and 5.5 in one assertion, and it is the
reason D2 chose Excel before Ellie: no network, so the whole pipeline can be exercised.

The *adapter* tests are mostly about refusal. A ragged sheet encodes its hierarchy in
column positions, which means the ways it goes wrong are quiet: a renamed header reads as
an empty taxonomy rather than a broken one, a skipped level attaches a value to the wrong
parent, a missing identity column silently drops a row. Each of those compiles happily
and produces a *wrong instance*, so each has a test here.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook
from tools.build_fixture_instance import INSTANCE, TODAY, compile_instance

from semprini import adapters, build, config
from semprini.adapters.base import SourceUnreachableError
from semprini.adapters.excel_taxonomy import ExcelTaxonomyAdapter, TaxonomyContentError
from semprini.config import ConfigError
from semprini.model import RunContext, Text
from semprini.testing import check_contract

CONTEXT = RunContext(base_iri="https://semantics.example.com/", instance_id="acme")

HEADER = (
    "Concept URI\n(local identifier)",
    "L1 - Preferred Label\n(skos:prefLabel)",
    "L2 - Preferred Label (skos:prefLabel)",
    "L3 - Preferred Label (skos:prefLabel)",
    "Definition\n(skos:definition)",
    "Alternative Labels\n(skos:altLabel; semicolon-sep)",
    "Hidden Labels\n(skos:hiddenLabel)",
    "Scope Note\n(skos:scopeNote)",
    "Example\n(skos:example)",
)

SCHEME = [
    ("Property", "Value"),
    ("Scheme Name", "Sizes"),
    ("Language", "en"),
]


def workbook(
    path: Path,
    rows: list[tuple[str, ...]],
    *,
    scheme: list[tuple[str, ...]] | None = None,
    header: tuple[str, ...] = HEADER,
    taxonomy_sheet: str = "Taxonomy",
) -> Path:
    """A workbook in the pilot's shape, with only the parts a test cares about filled in."""
    book = Workbook()
    first = book.active
    assert first is not None
    first.title = "Concept Scheme"
    for row in scheme if scheme is not None else SCHEME:
        first.append(row)
    sheet = book.create_sheet(taxonomy_sheet)
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path


def fetch(path: Path, **settings: Any) -> Any:
    settings.setdefault("path", path.name)
    settings.setdefault("scheme_slug", "sizes")
    ctx = RunContext(base_iri=CONTEXT.base_iri, instance_id="acme", repo_root=path.parent)
    return ExcelTaxonomyAdapter("sizes", settings, ctx).fetch()


def value(model: Any, key: str) -> Any:
    (found,) = [item for item in model.taxonomy_values if item.source_refs["sizes"] == key]
    return found


# ------------------------------------------------------------------ the fixture instance


def test_the_fixture_instance_recompiles_to_exactly_what_is_committed(tmp_path: Path) -> None:
    """The end-to-end guarantee, on a real instance rather than a hand-built model.

    Config, workbook, ID map and generated Turtle are all committed; compiling them again
    must reproduce the same bytes. A failure here is either the adapter changing what it
    reads or the compiler changing what it writes, and spec 5.5 makes the second a major
    version bump with a migration.
    """
    root = tmp_path / "acme"
    shutil.copytree(INSTANCE, root)

    compile_instance(root)

    for committed in sorted((INSTANCE / "generated").iterdir()):
        assert (root / "generated" / committed.name).read_bytes() == committed.read_bytes(), (
            f"{committed.name} changed; regenerate with tools/build_fixture_instance.py"
        )
    assert (root / "mappings/id-map.csv").read_bytes() == (
        INSTANCE / "mappings/id-map.csv"
    ).read_bytes()


def test_recompiling_mints_no_new_iris(tmp_path: Path) -> None:
    """Every IRI comes from the committed ID map, not from the minting formula.

    The formula and the map agreeing today is what makes this pass; the map being
    *authoritative* is what would keep it passing if the formula changed (spec 5.4). A
    run that appended a row would mean an object silently changed identity.
    """
    root = tmp_path / "acme"
    shutil.copytree(INSTANCE, root)
    before = (root / "mappings/id-map.csv").read_text(encoding="utf-8").splitlines()

    compile_instance(root)

    assert (root / "mappings/id-map.csv").read_text(encoding="utf-8").splitlines() == before


def test_the_fixture_instance_loads_with_the_bundled_adapter_installed() -> None:
    """B3 left the unknown-adapter check switched off until an adapter shipped.

    The fixture configures ``excel-taxonomy``; now that the entry point is registered,
    the name is judged against the installation for real rather than skipped.
    """
    settings = config.load(INSTANCE, known_adapters=adapters.adapter_names())

    assert [source.adapter for source in settings.sources] == ["ellie", "excel-taxonomy"]
    assert {"ellie", "excel-taxonomy"} <= set(adapters.adapter_names())


def test_the_bundled_adapter_meets_the_contract(tmp_path: Path) -> None:
    """The call a third-party author would write, against the adapter this task ships.

    Note it fetches twice, so anything order- or state-dependent in the reader shows up
    here rather than in an instance.
    """
    path = workbook(
        tmp_path / "sizes.xlsx", [("ont:Small", '"Small"@en', "", "", "", "", "", "", "")]
    )

    check_contract(
        ExcelTaxonomyAdapter,
        settings={"path": path.name, "scheme_slug": "sizes"},
        unreachable={"path": "not-there.xlsx", "scheme_slug": "sizes"},
        context=RunContext(base_iri=CONTEXT.base_iri, instance_id="contract", repo_root=tmp_path),
        source_name="sizes",
    )


# ------------------------------------------------------------------ the ragged hierarchy


def test_depth_comes_from_the_position_of_the_last_filled_level(tmp_path: Path) -> None:
    path = workbook(
        tmp_path / "t.xlsx",
        [
            ("ont:Tools", '"Tools"@en', "", "", "", "", "", "", ""),
            ("ont:Power", '"Tools"@en', '"Power"@en', "", "", "", "", "", ""),
            ("ont:Drills", '"Tools"@en', '"Power"@en', '"Drills"@en', "", "", "", "", ""),
        ],
    )

    model = fetch(path)

    assert value(model, "Tools").parent is None
    assert str(value(model, "Power").parent) == "sizes:Tools"
    assert str(value(model, "Drills").parent) == "sizes:Power"
    # The deepest filled cell is the value's own label; the ones before it are its
    # ancestors' labels, repeated for the reader's benefit and not its own.
    assert value(model, "Drills").pref_label == Text("Drills", "en")


def test_a_row_whose_parent_path_no_row_defines_is_refused(tmp_path: Path) -> None:
    path = workbook(
        tmp_path / "t.xlsx",
        [
            ("ont:Tools", '"Tools"@en', "", "", "", "", "", "", ""),
            ("ont:Drills", '"Tools"@en', '"Power"@en', '"Drills"@en', "", "", "", "", ""),
        ],
    )

    with pytest.raises(TaxonomyContentError) as raised:
        fetch(path)

    assert "'Drills'" in str(raised.value)
    assert "Tools / Power" in str(raised.value)
    assert "Taxonomy!3" in str(raised.value)


def test_a_row_that_skips_a_level_is_refused(tmp_path: Path) -> None:
    """The bug the prototype had, and the reason header order is read rather than counted.

    Collecting the non-empty cells and discarding their columns reads L1+L3 as depth 2,
    which silently attaches the value to the wrong parent and produces a taxonomy that is
    well-formed and wrong.
    """
    path = workbook(
        tmp_path / "t.xlsx",
        [
            ("ont:Tools", '"Tools"@en', "", "", "", "", "", "", ""),
            ("ont:Drills", '"Tools"@en', "", '"Drills"@en', "", "", "", "", ""),
        ],
    )

    with pytest.raises(TaxonomyContentError) as raised:
        fetch(path)

    assert "skips a level: L2 is empty" in str(raised.value)
    assert "Taxonomy!3" in str(raised.value)


def test_two_rows_in_one_place_in_the_hierarchy_are_refused(tmp_path: Path) -> None:
    path = workbook(
        tmp_path / "t.xlsx",
        [
            ("ont:Tools", '"Tools"@en', "", "", "", "", "", "", ""),
            ("ont:Tools2", '"Tools"@en', "", "", "", "", "", "", ""),
        ],
    )

    with pytest.raises(TaxonomyContentError) as raised:
        fetch(path)

    assert "already the path of row 2" in str(raised.value)


def test_two_rows_with_one_identity_are_refused(tmp_path: Path) -> None:
    """The identity column is what the ID map is keyed by (spec 5.4).

    Two rows sharing it would resolve to one IRI wearing two labels — the exact
    corruption the registry's injectivity check exists to stop, caught a stage earlier
    where the message can name the row.
    """
    path = workbook(
        tmp_path / "t.xlsx",
        [
            ("ont:Tools", '"Tools"@en', "", "", "", "", "", "", ""),
            ("ont:Tools", '"Implements"@en', "", "", "", "", "", "", ""),
        ],
    )

    with pytest.raises(TaxonomyContentError) as raised:
        fetch(path)

    assert "already the identity of row 2" in str(raised.value)


def test_a_row_with_no_identity_is_refused_rather_than_skipped(tmp_path: Path) -> None:
    """The prototype skipped these silently.

    For a taxonomy that means a value quietly vanishing on the next compile — and since
    nothing in the sources says it was removed, the compiler would deprecate it.
    """
    path = workbook(
        tmp_path / "t.xlsx",
        [
            ("ont:Tools", '"Tools"@en', "", "", "", "", "", "", ""),
            ("", '"Drills"@en', "", "", "", "", "", "", ""),
        ],
    )

    with pytest.raises(TaxonomyContentError) as raised:
        fetch(path)

    assert "no 'Concept URI'" in str(raised.value)


def test_a_wholly_blank_row_is_punctuation_not_a_value(tmp_path: Path) -> None:
    path = workbook(
        tmp_path / "t.xlsx",
        [
            ("ont:Tools", '"Tools"@en', "", "", "", "", "", "", ""),
            ("", "", "", "", "", "", "", "", ""),
        ],
    )

    assert len(fetch(path).taxonomy_values) == 1


def test_every_problem_in_a_workbook_is_reported_at_once(tmp_path: Path) -> None:
    # A taxonomy is edited in bulk — a re-export, a re-levelled branch — so its mistakes
    # come in bulk, and one per CI run costs a steward a round trip each.
    path = workbook(
        tmp_path / "t.xlsx",
        [
            ("ont:Tools", '"Tools"@en', "", "", "", "", "", "", ""),
            ("", '"Orphan"@en', "", "", "", "", "", "", ""),
            ("ont:Skip", '"Tools"@en', "", '"Skipped"@en', "", "", "", "", ""),
        ],
    )

    with pytest.raises(TaxonomyContentError) as raised:
        fetch(path)

    assert len(raised.value.issues) == 2
    assert "2 problems" in str(raised.value)


# ------------------------------------------------------------------ headers and columns


def test_a_sheet_with_no_identity_column_is_refused(tmp_path: Path) -> None:
    path = workbook(
        tmp_path / "t.xlsx",
        [("Tools", "", "")],
        header=("Name", "L1 - Preferred Label", "Definition"),
    )

    with pytest.raises(TaxonomyContentError) as raised:
        fetch(path)

    assert "no 'Concept URI' column" in str(raised.value)
    # The operator's next move is to fix a header, so the message says what it found.
    assert "definition" in str(raised.value)


def test_a_sheet_with_no_level_columns_is_refused(tmp_path: Path) -> None:
    """The failure that would otherwise be silent, and the reason matching is strict.

    A sheet whose level columns are named something else does not read as a broken
    taxonomy — it reads as an *empty* one, which compiles to a scheme with no values and
    deprecates everything that used to be in it.
    """
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:Tools", "Tools", "")],
        header=("Concept URI", "Level 1", "Definition"),
    )

    with pytest.raises(TaxonomyContentError) as raised:
        fetch(path)

    assert "no 'L1 - Preferred Label' column" in str(raised.value)


def test_columns_with_no_home_in_the_metamodel_are_tolerated(tmp_path: Path) -> None:
    # A workbook is a working document and gains columns for reasons of its own. Notes
    # and the provenance columns are read by nobody and must not fail the run.
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:Tools", '"Tools"@en', "", "", "", "", "", "", "", "a note", "PIM", "2026-01-05")],
        header=(*HEADER, "Notes", "Source System", "Date Extracted\n(YYYY-MM-DD)"),
    )

    assert len(fetch(path).taxonomy_values) == 1


def test_a_header_is_matched_on_its_first_line_only(tmp_path: Path) -> None:
    # These sheets carry the SKOS mapping on a second line, which is documentation for
    # whoever fills the sheet in and no part of the column's name.
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:Tools", '"Tools"@en', "", "", "A definition.", "", "", "", "")],
    )

    assert value(fetch(path), "Tools").definition == Text("A definition.", "en")


def test_a_missing_sheet_is_named(tmp_path: Path) -> None:
    path = workbook(tmp_path / "t.xlsx", [], taxonomy_sheet="Concepts")

    with pytest.raises(TaxonomyContentError, match="no 'Taxonomy' sheet"):
        fetch(path)


def test_a_scheme_sheet_without_a_name_is_refused(tmp_path: Path) -> None:
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:Tools", '"Tools"@en', "", "", "", "", "", "", "")],
        scheme=[("Property", "Value"), ("Language", "en")],
    )

    with pytest.raises(TaxonomyContentError, match="no 'Scheme Name' row"):
        fetch(path)


# ------------------------------------------------------------------ identity and values


def test_the_prefix_on_a_concept_uri_is_not_part_of_the_identity(tmp_path: Path) -> None:
    # The prefix is a convenience for whoever writes the sheet; the source key should not
    # change because a workbook adopted a different one (spec 5.4).
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:Tools", '"Tools"@en', "", "", "", "", "", "", "")],
    )

    assert dict(value(fetch(path), "Tools").source_refs) == {"sizes": "Tools"}


def test_a_scheme_is_keyed_by_its_slug_not_by_its_file_name(tmp_path: Path) -> None:
    # The path lives in the configuration precisely so a workbook can be moved or renamed
    # without re-keying every object in it.
    path = workbook(tmp_path / "t.xlsx", [("ont:S", '"S"@en', "", "", "", "", "", "", "")])

    (scheme,) = fetch(path).schemes
    assert dict(scheme.source_refs) == {"sizes": "sizes"}


def test_a_taxonomy_value_carries_no_notation(tmp_path: Path) -> None:
    """This format states no business code anywhere (spec 5.3).

    Deriving one from the identity column would emit a ``skos:notation`` the source never
    said, and stewards would then maintain a code the compiler invented.
    """
    path = workbook(tmp_path / "t.xlsx", [("ont:Tools", '"Tools"@en', "", "", "", "", "", "", "")])

    assert value(fetch(path), "Tools").code is None


def test_the_reused_skos_columns_are_carried(tmp_path: Path) -> None:
    path = workbook(
        tmp_path / "t.xlsx",
        [
            (
                "ont:Tools",
                '"Tools"@en',
                "",
                "",
                "A definition.",
                "Implements; Kit",
                "Toolz",
                "A scope note.",
                "An example.",
            )
        ],
    )

    tools = value(fetch(path), "Tools")

    assert tools.alt_labels == (Text("Implements", "en"), Text("Kit", "en"))
    assert tools.hidden_labels == (Text("Toolz", "en"),)
    assert tools.scope_notes == (Text("A scope note.", "en"),)
    assert tools.examples == (Text("An example.", "en"),)


def test_prose_columns_are_not_split_on_punctuation(tmp_path: Path) -> None:
    # Only the label columns are semicolon-separated, as the sheet's own headers say. An
    # example reading "Drill, hammer, spanner" is one statement, not three.
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:T", '"T"@en', "", "", "", "", "", "", "Drill; hammer, spanner")],
    )

    assert value(fetch(path), "T").examples == (Text("Drill; hammer, spanner", "en"),)


def test_an_empty_cell_states_nothing(tmp_path: Path) -> None:
    path = workbook(tmp_path / "t.xlsx", [("ont:T", '"T"@en', "", "", "", "", "", "", "")])

    tools = value(fetch(path), "T")
    assert tools.definition is None
    assert tools.alt_labels == () and tools.scope_notes == () and tools.examples == ()


# ------------------------------------------------------------------ language


def test_a_cell_that_states_a_language_keeps_it(tmp_path: Path) -> None:
    # Spec 5.5 rule 6: a value that arrives tagged is never overwritten.
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:T", '"Työkalut"@fi', "", "", "", "", "", "", "")],
    )

    assert value(fetch(path), "T").pref_label == Text("Työkalut", "fi")


def test_a_bare_cell_takes_the_language_the_workbook_declares(tmp_path: Path) -> None:
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:T", "Tools", "", "", "", "", "", "", "")],
        scheme=[("Property", "Value"), ("Scheme Name", "Sizes"), ("Language", "sv")],
    )

    assert value(fetch(path), "T").pref_label == Text("Tools", "sv")


def test_a_workbook_that_declares_no_language_leaves_it_to_the_instance(tmp_path: Path) -> None:
    """The third level: unstated here means the instance's ``default_language``.

    Applied when the graph is built, which is the only place that knows it — an adapter
    reads a source and does not decide an instance's conventions (spec 11 #5).
    """
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:T", "Tools", "", "", "", "", "", "", "")],
        scheme=[("Property", "Value"), ("Scheme Name", "Sizes")],
    )

    assert value(fetch(path), "T").pref_label == Text("Tools", None)


def test_a_language_that_is_not_a_tag_is_refused(tmp_path: Path) -> None:
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:T", "Tools", "", "", "", "", "", "", "")],
        scheme=[("Property", "Value"), ("Scheme Name", "Sizes"), ("Language", "English")],
    )

    with pytest.raises(TaxonomyContentError, match="not a language tag"):
        fetch(path)


# ------------------------------------------------------------------ enumerates


def test_the_reference_entity_is_a_source_ref_not_an_iri(tmp_path: Path) -> None:
    """An adapter has no IRIs to point with (spec 5.2).

    The workbook names the entity by its key in the modelling tool, and resolving that
    against the ID map is the core's job.
    """
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:T", '"T"@en', "", "", "", "", "", "", "")],
        scheme=[
            ("Property", "Value"),
            ("Scheme Name", "Sizes"),
            ("Reference Entity UUID", "7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21"),
        ],
    )

    (scheme,) = fetch(path, enumerates_source="ellie-main").schemes
    # Keyed under the *modelling tool's* source, not this taxonomy's: the ID map is keyed
    # by (source name, source key), and that UUID is a row of the Ellie source (spec 5.4).
    assert str(scheme.enumerates) == "ellie-main:7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21"


def test_a_reference_entity_without_a_source_says_which_key_is_missing(tmp_path: Path) -> None:
    """The workbook states a UUID; which configured source issued it is this instance's.

    Without ``enumerates_source`` the reference would be looked up under the taxonomy's
    own source name, where an entity's key can never be found — a dangling
    ``sem:enumerates`` reported two stages later as "no run has compiled this", naming a
    source ref nobody wrote.
    """
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:T", '"T"@en', "", "", "", "", "", "", "")],
        scheme=[
            ("Property", "Value"),
            ("Scheme Name", "Sizes"),
            ("Reference Entity UUID", "7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21"),
        ],
    )

    with pytest.raises(ConfigError, match="enumerates_source"):
        fetch(path)


def test_a_taxonomy_that_enumerates_nothing_needs_no_source(tmp_path: Path) -> None:
    """The setting is required by the cell, not by the adapter.

    A taxonomy that points at no entity must not be made to configure a source it does
    not use — most taxonomies do not, and an unused required key is one more thing to get
    wrong at bootstrap.
    """
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:T", '"T"@en', "", "", "", "", "", "", "")],
        scheme=[("Property", "Value"), ("Scheme Name", "Sizes")],
    )

    assert fetch(path).schemes[0].enumerates is None


def test_a_source_name_that_is_not_a_slug_is_refused(tmp_path: Path) -> None:
    path = workbook(tmp_path / "t.xlsx", [("ont:T", '"T"@en', "", "", "", "", "", "", "")])

    adapter = ExcelTaxonomyAdapter(
        "sizes",
        {"path": path.name, "scheme_slug": "sizes", "enumerates_source": "Ellie Main"},
        RunContext(base_iri=CONTEXT.base_iri, instance_id="acme", repo_root=tmp_path),
    )

    assert [issue.location for issue in adapter.validate_config()] == [
        "sources.sizes.config.enumerates_source"
    ]


def test_a_source_naming_itself_is_refused(tmp_path: Path) -> None:
    """The mistake this setting exists to undo, and the only wrong value checkable here.

    ``enumerates_source`` names the source whose *model* defines the reference entity. A
    workbook naming itself looks up its own UUID under its own keys, which can never hit —
    the reference then fails at build, two stages later, reported against the workbook's
    UUID rather than against the configuration line that is wrong.
    """
    path = workbook(tmp_path / "t.xlsx", [("ont:T", '"T"@en', "", "", "", "", "", "", "")])

    adapter = ExcelTaxonomyAdapter(
        "sizes",
        {"path": path.name, "scheme_slug": "sizes", "enumerates_source": "sizes"},
        RunContext(base_iri=CONTEXT.base_iri, instance_id="acme", repo_root=tmp_path),
    )

    (issue,) = adapter.validate_config()
    assert issue.location == "sources.sizes.config.enumerates_source"
    assert "names this source itself" in issue.message


def test_a_blank_reference_entity_enumerates_nothing(tmp_path: Path) -> None:
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:T", '"T"@en', "", "", "", "", "", "", "")],
        scheme=[("Property", "Value"), ("Scheme Name", "Sizes"), ("Reference Entity UUID", "")],
    )

    (scheme,) = fetch(path).schemes
    assert scheme.enumerates is None


def test_enumerating_an_entity_no_source_compiled_says_what_to_do(tmp_path: Path) -> None:
    """The ordinary case while an instance is being brought up, not an exotic one.

    A taxonomy compiled before the modelling tool's source is configured has nothing to
    point at, so the message has to name the fix rather than the internals.
    """
    from semprini.identity import IdMap, Registry

    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:T", '"T"@en', "", "", "", "", "", "", "")],
        scheme=[
            ("Property", "Value"),
            ("Scheme Name", "Sizes"),
            ("Reference Entity UUID", "7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21"),
        ],
    )

    with pytest.raises(build.BuildError, match="which no run has compiled"):
        build.build(
            fetch(path, enumerates_source="ellie-main"),
            registry=Registry(IdMap(), CONTEXT.base_iri, today=TODAY),
            context=CONTEXT,
            today=TODAY,
        )


# ------------------------------------------------------------------ failure and config


def test_a_workbook_that_is_not_there_is_unreachable(tmp_path: Path) -> None:
    """Exit code 3, and the distinction matters to CI.

    A source that cannot be read is retried; a source that answers with wrong data is
    investigated (spec 5.1). Every content failure above is the second kind.
    """
    with pytest.raises(SourceUnreachableError, match="cannot read"):
        fetch(tmp_path / "not-there.xlsx")


def test_a_file_that_is_not_a_workbook_is_a_compile_failure(tmp_path: Path) -> None:
    path = tmp_path / "t.xlsx"
    path.write_text("this is not a spreadsheet", encoding="utf-8")

    with pytest.raises(Exception, match="not a readable workbook"):
        fetch(path)


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({"scheme_slug": "sizes"}, "needs a 'path'"),
        ({"path": "t.xlsx"}, "needs a 'scheme_slug'"),
        ({"path": "t.xlsx", "scheme_slug": "Sizes"}, "not a slug"),
        ({"path": "/etc/passwd", "scheme_slug": "sizes"}, "inside the instance repository"),
        # Both flavours, so the guard does not depend on which platform CI runs: a
        # committed config travels, and only one of these is absolute on any given one.
        ({"path": r"C:\keys\secrets.xlsx", "scheme_slug": "sizes"}, "inside the instance"),
        ({"path": "../../elsewhere.xlsx", "scheme_slug": "sizes"}, "inside the instance"),
        ({"path": "t.xlsx", "scheme_slug": "sizes", "codes_are_stable": True}, "unknown setting"),
    ],
)
def test_configuration_problems_are_reported_with_their_key(
    settings: dict[str, Any], expected: str
) -> None:
    issues = ExcelTaxonomyAdapter("sizes", settings, CONTEXT).validate_config()

    assert any(expected in issue.message for issue in issues)
    assert all(
        issue.location and issue.location.startswith("sources.sizes.config") for issue in issues
    )


def test_a_working_configuration_reports_nothing() -> None:
    settings = {
        "path": "sources/taxonomies/product-category.xlsx",
        "scheme_slug": "product-category",
    }

    assert ExcelTaxonomyAdapter("product-category", settings, CONTEXT).validate_config() == []


def test_the_summary_says_what_was_read(tmp_path: Path) -> None:
    workbook(tmp_path / "sizes.xlsx", [("ont:T", '"T"@en', "", "", "", "", "", "", "")])
    ctx = RunContext(base_iri=CONTEXT.base_iri, instance_id="acme", repo_root=tmp_path)
    adapter = ExcelTaxonomyAdapter("sizes", {"path": "sizes.xlsx", "scheme_slug": "sizes"}, ctx)

    assert adapter.summary() == ""
    adapter.fetch()
    assert adapter.summary() == "1 values from sizes.xlsx"


def test_a_branch_spelled_two_ways_is_still_one_branch(tmp_path: Path) -> None:
    """Hierarchy is matched on label *values*, not on raw cells.

    A workbook that tags some cells and leaves others bare is entirely ordinary — the
    fixture's own does it. Matching the raw text would make ``"Tools"@en`` and ``Tools``
    two branches, and every row under the second spelling would be reported as an orphan
    pointing at a parent the reviewer can plainly see in the sheet.
    """
    path = workbook(
        tmp_path / "t.xlsx",
        [
            ("ont:Tools", '"Tools"@en', "", "", "", "", "", "", ""),
            ("ont:Hand", "Tools", '"Hand tools"@en', "", "", "", "", "", ""),
            ("ont:Spanners", '"Tools"@en', "Hand tools", "Spanners", "", "", "", "", ""),
        ],
    )

    model = fetch(path)

    assert str(value(model, "Hand").parent) == "sizes:Tools"
    assert str(value(model, "Spanners").parent) == "sizes:Hand"


def test_prose_columns_are_not_split_either_when_they_are_scope_notes(tmp_path: Path) -> None:
    # The paired half of the test above. Both prose columns go through the same helper,
    # and testing one of them left the other free to be split by a passing suite.
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:T", '"T"@en', "", "", "", "", "", "Covers A; excludes B", "")],
    )

    assert value(fetch(path), "T").scope_notes == (Text("Covers A; excludes B", "en"),)


def test_every_hierarchy_problem_is_reported_at_once(tmp_path: Path) -> None:
    """Collection is per stage, and the stages fail for different reasons.

    The row reader catches malformed rows and the hierarchy resolver catches rows that do
    not fit together. A test that only exercised the first would leave the second free to
    stop at its first orphan.
    """
    path = workbook(
        tmp_path / "t.xlsx",
        [
            ("ont:A", '"Tools"@en', '"Power"@en', "", "", "", "", "", ""),
            ("ont:B", '"Tools"@en', '"Hand"@en', "", "", "", "", "", ""),
        ],
    )

    with pytest.raises(TaxonomyContentError) as raised:
        fetch(path)

    assert len(raised.value.issues) == 2
    assert "'A'" in str(raised.value) and "'B'" in str(raised.value)


# ------------------------------------------------------------------ review findings


def test_level_columns_must_start_at_l1(tmp_path: Path) -> None:
    """A sheet whose levels start at L2 is not a shallower taxonomy — it is a wrong one.

    Depth is read from a cell's position among the level columns, so if the reader
    tolerated this, every value would come out one level too shallow: the run would
    succeed, every `skos:broader` would move, and the diff would read as a deliberate
    re-levelling nobody performed.
    """
    path = workbook(
        tmp_path / "t.xlsx",
        [
            ("ont:A", "Tools", "", "", "", "", "", ""),
            ("ont:B", "Tools", "Power", "", "", "", "", ""),
        ],
        header=(
            "Concept URI",
            "L2 - Preferred Label",
            "L3 - Preferred Label",
            "Definition",
            "Alternative Labels",
            "Hidden Labels",
            "Scope Note",
            "Example",
        ),
    )

    with pytest.raises(TaxonomyContentError, match=r"must run L1\.\.L2"):
        fetch(path)


def test_a_missing_middle_level_column_is_refused(tmp_path: Path) -> None:
    # The same shift, arriving the way it really would: a re-export that dropped L2. The
    # rows are individually well-formed, so only the header can catch it.
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:A", "Tools", "Drills", "", "", "", "", "")],
        header=(
            "Concept URI",
            "L1 - Preferred Label",
            "L3 - Preferred Label",
            "Definition",
            "Alternative Labels",
            "Hidden Labels",
            "Scope Note",
            "Example",
        ),
    )

    with pytest.raises(TaxonomyContentError, match="L1, L3"):
        fetch(path)


def test_a_semicolon_inside_a_quoted_label_does_not_split_it(tmp_path: Path) -> None:
    """Splitting before parsing looks equivalent and is not.

    A naive split cuts ``"A; B"@fi`` in half, leaving two fragments that still carry
    stray quotation marks and lose the language the cell stated — wrong RDF rather than
    an error, which is the worst outcome available for a governed file.
    """
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:T", '"T"@en', "", "", "", '"A; B"@fi; "C"@fi', "", "", "")],
    )

    assert value(fetch(path), "T").alt_labels == (Text("A; B", "fi"), Text("C", "fi"))


def test_prose_that_merely_begins_and_ends_with_a_quote_is_left_alone(tmp_path: Path) -> None:
    # A greedy match would take the outer characters off and write the rest into a
    # governed file, having silently edited a steward's sentence.
    path = workbook(
        tmp_path / "t.xlsx",
        [("ont:T", '"T"@en', "", "", '"Smart" tools "here"', "", "", "", "")],
    )

    assert value(fetch(path), "T").definition == Text('"Smart" tools "here"', "en")


def test_a_half_finished_row_is_refused_rather_than_dropped(tmp_path: Path) -> None:
    """A row with content but no identity yet is work in progress, not punctuation.

    Dropping it silently is how a value a steward believes they added never appears —
    and on a later run, when they fix it, arrives as brand new.
    """
    path = workbook(
        tmp_path / "t.xlsx",
        [
            ("ont:Tools", '"Tools"@en', "", "", "", "", "", "", ""),
            ("", "", "", "", "A definition somebody wrote.", "", "", "", ""),
        ],
    )

    with pytest.raises(TaxonomyContentError, match="no 'Concept URI'"):
        fetch(path)


def test_fetch_validates_its_own_configuration_first(tmp_path: Path) -> None:
    """`validate_config()` is on no compile path, so `fetch()` runs it itself.

    Otherwise a run that skipped `semprini check` reaches the workbook with a setting
    nobody validated — and an absolute path silently wins over the repository root.
    """
    ctx = RunContext(base_iri=CONTEXT.base_iri, instance_id="acme", repo_root=tmp_path)
    adapter = ExcelTaxonomyAdapter("sizes", {"path": "/etc/passwd", "scheme_slug": "sizes"}, ctx)

    with pytest.raises(ConfigError) as raised:
        adapter.fetch()

    assert "inside the instance repository" in str(raised.value)
    assert any(issue.location == "sources.sizes.config.path" for issue in raised.value.issues)


def test_a_missing_setting_is_an_issue_rather_than_a_traceback(tmp_path: Path) -> None:
    adapter = ExcelTaxonomyAdapter("sizes", {"path": "t.xlsx"}, CONTEXT)

    with pytest.raises(ConfigError, match="needs a 'scheme_slug'"):
        adapter.fetch()

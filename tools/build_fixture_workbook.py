"""Regenerate the synthetic taxonomy workbook the fixture instance holds.

The fixture instance carries a real ``.xlsx``, because that is what an adopting instance
carries and the suite has to compile the same thing they do. A binary file is not
reviewable in a PR, though, so its content lives here in text and the workbook is
generated from it. Edit this script, run it, and commit both.

    poetry run python tools/build_fixture_workbook.py

Nothing verifies that the committed workbook matches this file byte for byte — an
``.xlsx`` is a zip and would not compare equal across runs anyway. What keeps the two
honest is the golden Turtle: every label, definition, note and example below appears in
``tests/fixtures/acme/generated/``, so a workbook edited without this script fails
``tests/test_excel_taxonomy.py``.

Everything here is invented. No adopting organization's content ever enters this
repository (spec 9.2 rule 5).
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKBOOK = REPO_ROOT / "tests/fixtures/acme/sources/taxonomies/product-category.xlsx"

# The vertical Property/Value table. 'Reference Entity UUID' is deliberately **blank**:
# it names an entity in a modelling tool, and the fixture instance configures no such
# source, so a value here would refuse to compile until D3 ships the Ellie adapter.
SCHEME_SHEET = [
    ("Property", "Value", "SKOS Mapping", "Notes"),
    ("Scheme Name", "Product category taxonomy", "dcterms:title", "The name of your taxonomy"),
    ("Reference Entity UUID", "", "sem:enumerates", "The entity this taxonomy enumerates"),
    (
        "Description",
        "A small synthetic taxonomy of hardware product categories, used by the plane's "
        "own test suite.",
        "dcterms:description",
        "What the taxonomy is for",
    ),
    ("Language", "en", "dcterms:language", "Default tag for cells that state none"),
    # Rows below are tolerated and ignored — documentation for whoever maintains the
    # workbook, with no home in the metamodel (spec 5.3).
    ("Creator", "Acme data governance", "dcterms:creator", "Person or team responsible"),
    ("Date Created", "2026-01-05", "dcterms:created", "YYYY-MM-DD"),
    ("Version", "1.0", "owl:versionInfo", "Version identifier"),
    ("Domain", "Product catalogue", "dcterms:subject", "Subject domain"),
]

TAXONOMY_HEADER = (
    "Concept URI\n(local identifier)",
    "L1 - Preferred Label\n(skos:prefLabel)",
    "L2 - Preferred Label (skos:prefLabel)",
    "L3 - Preferred Label (skos:prefLabel)",
    "Definition\n(skos:definition)",
    "Alternative Labels\n(skos:altLabel; semicolon-sep)",
    "Hidden Labels\n(skos:hiddenLabel)",
    "Scope Note\n(skos:scopeNote)",
    "Example\n(skos:example)",
    # Read by nobody, present on purpose: the adapter must tolerate columns it has no
    # home for rather than refuse the workbook (spec 5.3).
    "Notes",
    "Source System",
    "Date Extracted\n(YYYY-MM-DD)",
)

# One row per value. Depth is the position of the last filled L cell, and a row's parent
# is whichever row holds its first n-1 labels — so the order here is also the hierarchy.
TAXONOMY_ROWS = [
    (
        "ont:Tools",
        '"Tools"@en',
        "",
        "",
        "Implements used to work material by hand or by power.",
        "Implements",
        "Toolz",
        "Covers the implement itself, never the consumable it drives.",
        "Drill, hammer, spanner",
        "Top concept",
        "PIM",
        "2026-01-05",
    ),
    (
        "ont:PowerTools",
        '"Tools"@en',
        '"Power tools"@en',
        "",
        "Tools driven by an electric motor or compressed air.",
        "Powered tools; Electric tools",
        "",
        "",
        "",
        "",
        "PIM",
        "2026-01-05",
    ),
    (
        "ont:Drills",
        '"Tools"@en',
        '"Power tools"@en',
        '"Drills"@en',
        "Power tools that bore holes by rotating a bit.",
        "Drivers",
        "Drils",
        "Includes drivers, which share the same chuck.",
        "Cordless drill, hammer drill",
        "",
        "PIM",
        "2026-01-05",
    ),
    (
        "ont:Sanders",
        '"Tools"@en',
        '"Power tools"@en',
        '"Sanders"@en',
        "Power tools that abrade a surface smooth.",
        "",
        "",
        "",
        "",
        "",
        "PIM",
        "2026-01-05",
    ),
    (
        "ont:HandTools",
        '"Tools"@en',
        '"Hand tools"@en',
        "",
        "Tools worked entirely by hand.",
        "Manual tools",
        "",
        "",
        "",
        "",
        "PIM",
        "2026-01-05",
    ),
    (
        # No literal syntax and no tag: falls back to the scheme's 'Language' row, which
        # is what makes both branches of spec 5.5 rule 6 reachable through one workbook.
        "ont:Spanners",
        '"Tools"@en',
        '"Hand tools"@en',
        "Spanners",
        "Hand tools that grip and turn a nut or bolt head.",
        "Wrenches",
        "",
        "",
        "",
        "",
        "PIM",
        "2026-01-05",
    ),
    (
        "ont:Fasteners",
        '"Fasteners"@en',
        "",
        "",
        "Hardware that joins two things together.",
        "",
        "",
        "Excludes adhesives, which are consumables.",
        "Screw, bolt, rivet",
        "A second top concept",
        "PIM",
        "2026-01-05",
    ),
    (
        "ont:Screws",
        '"Fasteners"@en',
        '"Screws"@en',
        "",
        "Threaded fasteners driven into material.",
        "",
        "Screwes",
        "",
        "",
        "",
        "PIM",
        "2026-01-05",
    ),
    # A wholly blank row: spreadsheet punctuation, and not a value.
    ("", "", "", "", "", "", "", "", "", "", "", ""),
]


def build() -> None:
    workbook = Workbook()
    scheme = workbook.active
    assert scheme is not None
    scheme.title = "Concept Scheme"
    for metadata_row in SCHEME_SHEET:
        scheme.append(metadata_row)

    taxonomy = workbook.create_sheet("Taxonomy")
    taxonomy.append(TAXONOMY_HEADER)
    for row in TAXONOMY_ROWS:
        taxonomy.append(row)

    WORKBOOK.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(WORKBOOK)
    print(f"wrote {WORKBOOK.relative_to(REPO_ROOT)} ({len(TAXONOMY_ROWS) - 1} values)")


if __name__ == "__main__":
    build()

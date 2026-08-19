"""H0's battery: stop normalizing, and demand the suite notices.

The reason this task has a battery at all is that its failures are the ones a person cannot
see. Every mutation below leaves a compiler that runs, produces valid Turtle and passes any
check a reviewer could perform by reading a diff — because the difference between the right
output and the wrong output is a character that renders as nothing, or as a space.

Four groups.

**Normalization stops happening.** Drop a step, or the whole function, and the invisible
character reaches the literal. The NFC step is worth its own mutations: it is the one a reader
is most likely to think is decoration, and it is the one with the widest blast radius, since
composed and decomposed vowels are ordinary in every language this project's examples use.

**Normalization happens too late.** Emptiness and identity are both *decided* somewhere, and a
normalization applied after the decision is worse than none at all: it means a cell of nothing
but a zero-width space raises from `Text` rather than being absent, and a key that should have
been refused keys an ID-map row instead.

**It reaches only some of the boundaries.** `Text` catches labels and definitions. Source keys,
spreadsheet headers, Ellie's model ids and `skos:notation` reach none of them on their own, and
each was a real gap before this task. A mutation that switches one off leaves the other tests
green.

**The count lies.** Report-only, so a wrong count breaks no output — which is exactly why a
test has to hold it. The idempotence mutation belongs here too: a function that keeps changing
its own result would make every recompile a diff, and nothing else in the suite would say why.
"""

from __future__ import annotations

TESTS: tuple[str, ...] = (
    "tests/test_model.py",
    "tests/test_excel_taxonomy.py",
    "tests/test_ellie.py",
    "tests/test_adapter_contract.py",
    "tests/test_run.py",
)

MODEL = "src/semprini/model.py"
EXCEL = "src/semprini/adapters/excel_taxonomy.py"
ELLIE = "src/semprini/adapters/ellie.py"
TESTING = "src/semprini/testing.py"
RUN = "src/semprini/run.py"

# (description, file, old, new). `old` is a verbatim fragment of the file it anchors to and
# appears in it exactly once.
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    # ------------------------------------------------- normalization stops happening
    (
        "nothing is normalized at all",
        MODEL,
        '    normalized = unicodedata.normalize("NFC", value).translate(_TRANSLATION)',
        "    normalized = value",
    ),
    (
        "composition is dropped, so two spellings of one vowel are two literals",
        MODEL,
        '    normalized = unicodedata.normalize("NFC", value).translate(_TRANSLATION)',
        "    normalized = value.translate(_TRANSLATION)",
    ),
    (
        "NFD is applied instead of NFC, decomposing what the source composed",
        MODEL,
        '    normalized = unicodedata.normalize("NFC", value).translate(_TRANSLATION)',
        '    normalized = unicodedata.normalize("NFD", value).translate(_TRANSLATION)',
    ),
    (
        "NFKC is applied, which folds ligatures and superscripts as well",
        MODEL,
        '    normalized = unicodedata.normalize("NFC", value).translate(_TRANSLATION)',
        '    normalized = unicodedata.normalize("NFKC", value).translate(_TRANSLATION)',
    ),
    (
        "only U+00A0 is mapped, leaving every other separator in place",
        MODEL,
        r'    "\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005"',
        r'    "\u0020\u00a0"',
    ),
    (
        "the invisible characters are mapped to a space rather than deleted",
        MODEL,
        "    **{ord(character): None for character in _REMOVED},",
        '    **{ord(character): " " for character in _REMOVED},',
    ),
    (
        "the zero-width joiner is deleted too, rewriting words in several scripts",
        MODEL,
        r'_REMOVED = frozenset("\u200b\ufeff\u00ad")',
        r'_REMOVED = frozenset("\u200b\ufeff\u00ad\u200d")',
    ),
    (
        "the trailing strip is dropped, so an exposed edge space survives",
        MODEL,
        "    return normalized.strip()",
        "    return normalized",
    ),
    (
        "normalization is not idempotent, so every recompile is a diff",
        MODEL,
        "    return normalized.strip()",
        '    return normalized.strip() + ("" if normalized == value else " ")',
    ),
    # ------------------------------------------------- normalization happens too late
    (
        "a text is normalized after emptiness is judged",
        MODEL,
        '        object.__setattr__(self, "value", normalize_text(self.value))\n        if not self.value:',  # noqa: E501
        "        if not self.value:",
    ),
    (
        "a key is normalized after emptiness is judged",
        MODEL,
        '        object.__setattr__(self, "key", normalize_text(self.key))\n        if not self.source or not self.key:',  # noqa: E501
        "        if not self.source or not self.key:",
    ),
    (
        "absence is decided on the raw string rather than the normalized one",
        MODEL,
        "    return True if isinstance(value, Text) else bool(normalize_text(value))",
        "    return True if isinstance(value, Text) else bool(value)",
    ),
    (
        "an object's stored keys are the raw ones while its refs are normalized",
        MODEL,
        '            self, "source_refs", MappingProxyType({ref.source: ref.key for ref in refs})',
        '            self, "source_refs", MappingProxyType(dict(self.source_refs))',
    ),
    # ------------------------------------------------- some boundaries are missed
    (
        "a spreadsheet cell is trimmed but not normalized",
        EXCEL,
        '    return "" if value is None else normalize_text(str(value))',
        '    return "" if value is None else str(value).strip()',
    ),
    (
        "a spreadsheet header is trimmed but not normalized",
        EXCEL,
        r'    return normalize_text(str(value).split("\n", 1)[0]).lower()',
        r'    return str(value).split("\n", 1)[0].strip().lower()',
    ),
    (
        "a row is judged blank on its raw cells, so invisible punctuation is a value",
        EXCEL,
        "    if not any(row):",
        "    if not any(str(item) for item in raw if item is not None):",
    ),
    (
        "an Ellie field is trimmed but not normalized",
        ELLIE,
        "    return normalize_text(str(value))",
        "    return str(value).strip()",
    ),
    (
        "an allowlisted model id is matched before normalization",
        ELLIE,
        '    stated = _plain(document.get("modelId"))',
        '    stated = str(document.get("modelId", "")).strip()',
    ),
    (
        "a notation reaches skos:notation unnormalized",
        MODEL,
        '        object.__setattr__(self, "code", (normalize_text(self.code) if self.code else "") or None)',  # noqa: E501
        '        object.__setattr__(self, "code", self.code or None)',
    ),
    (
        "the contract stops checking what an adapter returned",
        TESTING,
        "            if value == normalize_text(value):\n                continue",
        "            if True:\n                continue",
    ),
    # ------------------------------------------------- the count lies
    (
        "the count is never incremented",
        MODEL,
        "            tally[0] += 1",
        "            tally[0] += 0",
    ),
    (
        "every value is counted, normalized or not",
        MODEL,
        "    if normalized != value:\n        tally = _NORMALIZATIONS.get()",
        "    if True:\n        tally = _NORMALIZATIONS.get()",
    ),
    (
        "the count is never reported",
        RUN,
        "                note=_note(adapter.summary(), normalizations[0]),",
        "                note=adapter.summary(),",
    ),
    (
        "the report says so even when there is nothing to say",
        RUN,
        "    if not normalizations:\n        return summary",
        "    if False:\n        return summary",
    ),
    (
        "the count is shared across sources instead of being reset per source",
        RUN,
        "        with counting_normalizations() as normalizations:\n            fetched = adapter.fetch()",  # noqa: E501
        "        normalizations = [0]\n        fetched = adapter.fetch()",
    ),
)

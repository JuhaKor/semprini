"""A synthetic adapter that reaches the compiler only by being installed (spec 5.2).

Nothing in ``semprini`` imports this module or mentions its name. It becomes visible to
``semprini adapters`` because a distribution on ``sys.path`` declares a
``semprini.adapters`` entry point — the same and only route a third party's adapter
takes. That is the point of it: the plugin promise of spec 1.2 is a claim about
installation, and a test that monkeypatched a registry would prove nothing about it.

Its "source system" is a JSON document, which gives it an honest unreachable case — a
file that is not there is this adapter's version of an API that will not answer — and
lets it double as the worked example an adapter author copies. It is also the fixture
the contract suite (:mod:`semprini.testing`) is checked against, so it must stay
scrupulously correct: it reads, it returns, it raises, and it writes nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from semprini.adapters import AdapterError, BaseAdapter, SourceUnreachableError
from semprini.model import Entity, InternalModel, Issue, Scheme, SchemeType, Severity

__all__ = ["DummyAdapter"]

_SETTINGS = frozenset({"path"})


class DummyAdapter(BaseAdapter):
    """A JSON document standing in for a source system (the plane's own test fixture).

    The first line above is what ``semprini adapters`` prints beside this adapter's
    name, so it says what the adapter reads rather than how it works. Everything from
    here down is for whoever opens the file, and belongs to no listing.

    Settings: ``path``, the document to read. It holds one scheme and its entities; see
    the README beside this package.
    """

    name = "dummy"

    _fetched: int | None = None
    """How many entities the last fetch read, for :meth:`summary`. ``None`` until then —
    an adapter is constructed by ``semprini check`` without ever fetching (spec 6.1)."""

    def fetch(self) -> InternalModel:
        document = self._read()
        scheme = document["scheme"]
        slug = str(scheme["slug"])
        entities = tuple(
            Entity(
                source_refs={self.source_name: str(entry["key"])},
                pref_label=str(entry["label"]),
                definition=entry.get("definition"),
                schemes=(slug,),
            )
            for entry in document.get("entities", ())
        )
        self._fetched = len(entities)
        return InternalModel(
            schemes=(
                Scheme(
                    source_refs={self.source_name: slug},
                    pref_label=str(scheme["label"]),
                    slug=slug,
                    scheme_type=SchemeType.GLOSSARY,
                ),
            ),
            entities=entities,
        )

    def validate_config(self) -> list[Issue]:
        issues = []
        where = f"sources.{self.source_name}.config"
        if not self.config.get("path"):
            issues.append(Issue(Severity.ERROR, "a dummy source needs a 'path'", f"{where}.path"))
        for key in sorted(set(self.config) - _SETTINGS):
            issues.append(Issue(Severity.ERROR, f"unknown setting {key!r}", f"{where}.{key}"))
        return issues

    def summary(self) -> str:
        if self._fetched is None:
            return ""
        return f"{self._fetched} entities from {Path(str(self.config['path'])).name}"

    def _read(self) -> dict[str, Any]:
        path = Path(str(self.config["path"]))
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            # The only failure that is exit 3: the source could not be read at all
            # (spec 5.1). Malformed content, below, is a compile failure instead.
            raise SourceUnreachableError(
                f"source {self.source_name!r}: cannot read {path}: {error}"
            ) from error
        try:
            document = json.loads(text)
        except ValueError as error:
            raise AdapterError(
                f"source {self.source_name!r}: {path} is not valid JSON: {error}"
            ) from error
        if not isinstance(document, dict):
            raise AdapterError(f"source {self.source_name!r}: {path} is not a JSON object")
        return document

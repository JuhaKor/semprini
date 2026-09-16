"""``BaseAdapter`` — the plugin contract (spec 5.2).

An adapter knows one source and nothing else; identity, files, RDF and lifecycle stay on
the core's side. Four obligations, all checked by :func:`semprini.testing.check_contract`:
``fetch()`` writes nothing; it mints no IRIs and returns source keys only (spec 5.4); an
unreadable source raises :class:`SourceUnreachableError` rather than returning a partial
model (spec 5.4); and it contributes data only, never ``sem:`` terms of its own (spec 3.6).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar

from semprini.model import InternalModel, Issue, RunContext

__all__ = [
    "AdapterError",
    "AdapterLoadError",
    "BaseAdapter",
    "SourceUnreachableError",
]


class AdapterError(Exception):
    """Something an adapter, or the plugin machinery around it, could not do.

    Exit code 1 unless a subclass says otherwise (spec 5.1). Not an
    :class:`~semprini.model.IssueError`: a failed fetch is one exception, not a list of
    configuration issues, and :meth:`BaseAdapter.validate_config` covers the latter.
    """


class SourceUnreachableError(AdapterError):
    """A configured source could not be read — exit code 3 (spec 5.1, 5.2).

    For an unreadable file, a refused connection or a server error: something CI retries
    rather than investigates. A source that answers with wrong data is a compile failure.
    """


class AdapterLoadError(AdapterError):
    """An installed entry point does not yield a usable adapter (spec 5.2). Raised by discovery."""


class BaseAdapter(ABC):
    """One source system, normalized into the internal model (spec 5.2)."""

    name: ClassVar[str]
    """The entry-point name this adapter is registered under, such as ``"ellie"``.

    :meth:`~semprini.adapters.AdapterEntry.load` refuses an adapter whose ``name`` differs
    from its registration; an alias is a subclass with its own ``name``.
    """

    def __init__(self, source_name: str, config: Mapping[str, Any], ctx: RunContext) -> None:
        """Construct the adapter for one configured source.

        Cheap and side-effect-free: ``semprini check`` constructs every configured adapter
        only to call :meth:`validate_config`. Do the work in :meth:`fetch`.
        """
        self.source_name = source_name
        """The source's configured ``name``, as it appears in ``sem:sourceRef`` and the
        ID map (spec 5.1, 5.4). Not the adapter's name."""

        self.config = config
        """The source's own ``config:`` subtree, uninterpreted and deeply read-only (spec 5.2)."""

        self.ctx = ctx
        """What the run knows about the instance (spec 5.1). Read-only; carries no ID map."""

    @abstractmethod
    def fetch(self) -> InternalModel:
        """Read the source and return it as internal-model objects.

        Every object carries at least one source ref under :attr:`source_name`, keyed by
        something the source keeps stable across runs: the ID map freezes the IRI that
        key was given (spec 5.4).

        Raises :class:`SourceUnreachableError` if the source cannot be read. Never
        returns a partial model.
        """

    def validate_config(self) -> list[Issue]:
        """Check this source's ``config:`` subtree without reading the source (spec 6.1).

        Returns every problem, each located by its dotted key. Empty by default.
        """
        return []

    def summary(self) -> str:
        """One line for the run report on what this fetch read; ``SourceSummary.note`` (spec 5.6).

        Called after :meth:`fetch`. Empty by default.
        """
        return ""

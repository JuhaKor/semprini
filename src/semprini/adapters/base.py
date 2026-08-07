"""``BaseAdapter`` — the plugin contract (spec 5.2).

This is the whole surface a source system has to meet to become part of a knowledge
plane. It is deliberately small: an adapter knows one source and nothing else, and every
hard problem — identity, files, RDF, lifecycle — stays on the core's side of the seam.
That asymmetry is what lets a third-party adapter be a first-class citizen (spec 5.2):
there is nothing an adapter could do better by being bundled, so nobody has to fork the
plane to add a source.

Four obligations the core relies on, all four checked by
:func:`semprini.testing.check_contract`:

*No writes.* ``fetch()`` reads its source and returns objects. A run that fails midway
must leave the instance exactly as it found it, which is impossible if an adapter has
already written something.

*No minting.* An adapter has no IRIs to give. It returns source keys, and identity
resolution turns them into IRIs against the ID map, which is the only thing entitled to
decide what an object is called (spec 5.4).

*Failures raise.* A source that cannot be read raises :class:`SourceUnreachableError`;
it never returns the part it managed to fetch. A partial model is indistinguishable from
a source that legitimately shrank, and the compiler would deprecate everything missing
from it (spec 5.4).

*Data only.* An adapter contributes labels, definitions and structure — never IRIs in
the instance's namespace, and never ``sem:`` terms of its own (spec 3.6).
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

    Exit code 1 unless a subclass says otherwise (spec 5.1); the mapping lives in
    :func:`semprini.cli.exit_code_for`.

    Deliberately *not* an :class:`~semprini.model.IssueError`, which everything else in
    this project raises. Configuration problems are reported in bulk, because an
    operator fixing a YAML file in CI should see all of them at once — and that is what
    :meth:`BaseAdapter.validate_config` returns issues for. A source failing halfway
    through a fetch is the opposite situation: there is one thing wrong, the adapter
    author is holding the exception that explains it, and requiring them to wrap it in
    an issue list to re-raise it would buy nobody anything.
    """


class SourceUnreachableError(AdapterError):
    """A configured source could not be read — exit code 3 (spec 5.1, 5.2).

    The one failure CI treats differently from a compile error: the models were fine and
    the network was not, so a scheduled compile that hits this is retried rather than
    investigated, and nothing about the instance needs to change. Reserve it for exactly
    that — an unreadable file, a refused connection, an API that answered with a server
    error. A source that answers with *wrong* data is a compile failure, not this.
    """


class AdapterLoadError(AdapterError):
    """An installed entry point does not yield a usable adapter (spec 5.2).

    Raised by discovery, not by adapters: it means the plugin is broken or ambiguous as
    *installed*, before any source has been read.
    """


class BaseAdapter(ABC):
    """One source system, normalized into the internal model (spec 5.2)."""

    name: ClassVar[str]
    """The entry-point name this adapter is registered under — ``"ellie"``.

    It must equal that name, and :meth:`~semprini.adapters.AdapterEntry.load` refuses
    the adapter if it does not: an instance writes ``adapter: ellie`` in its
    configuration, and a class that calls itself something else would have every message
    about it name a thing the operator cannot find in any file. Registering one class
    under two names is therefore not available; an alias is a subclass that sets its own
    ``name``.
    """

    def __init__(self, source_name: str, config: Mapping[str, Any], ctx: RunContext) -> None:
        """Construct the adapter for one configured source.

        Cheap and side-effect-free by contract: ``semprini check`` constructs every
        configured adapter only to call :meth:`validate_config`, and must not open a
        connection to do it. Do the work in :meth:`fetch`.
        """
        self.source_name = source_name
        """The source's configured ``name`` — what appears in ``sem:sourceRef`` and in
        the ID map's ``source_name`` column, not the adapter's name (spec 5.1, 5.4).
        Every object returned carries a source ref under it."""

        self.config = config
        """The source's own ``config:`` subtree, passed through uninterpreted by
        :mod:`semprini.config` (spec 5.2). Read-only, and read-only in the deep sense —
        nested mappings and lists are frozen too, because a later stage and the run
        report both read the same object."""

        self.ctx = ctx
        """What the run knows about the instance: base IRI, language, whether this is a
        partial or a dry run (spec 5.1). Read-only, and carries no ID map — minting is
        not something an adapter is able to do by accident."""

    @abstractmethod
    def fetch(self) -> InternalModel:
        """Read the source and return it as internal-model objects.

        Every object carries at least one source ref under :attr:`source_name`, keyed by
        whatever the source calls the object — a UUID, a code, a path. That key is
        permanent in the sense that matters: the ID map remembers which IRI it was given
        (spec 5.4), so the key must identify the same thing next run, and must not be
        derived from something a user can edit unless the source guarantees otherwise.

        Raises :class:`SourceUnreachableError` if the source cannot be read. Never
        returns a partial model.
        """

    def validate_config(self) -> list[Issue]:
        """Check this source's ``config:`` subtree, without reading the source.

        Called by ``semprini check`` (spec 6.1). Returns every problem rather than the
        first, each with the dotted key that caused it, so an operator fixing a fresh
        configuration is not made to discover them one CI run at a time. The default is
        no opinion, which is right for an adapter whose configuration is a single URL.
        """
        return []

    def summary(self) -> str:
        """One line for the run report, describing what this fetch actually read.

        Becomes ``SourceSummary.note`` (spec 5.6), beside the source name and its object
        count. This is where a reviewer learns that a model was renamed in the source
        system, or that a workbook had 40 rows where it used to have 400 — the counts
        alone would not say. Called after :meth:`fetch`, so an adapter can report what
        it saw. Empty by default.
        """
        return ""

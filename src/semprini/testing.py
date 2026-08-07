"""The adapter contract, as an executable test (spec 5.2).

Spec 5.2 promises that a new source system is added by installing a package — no fork,
no patch. That promise is empty unless an author outside this project can find out
whether their adapter actually holds up its end, and the obligations it has to meet are
mostly *negative*: it must not write, must not mint, must not quietly return half a
source. Nothing about a passing adapter looks different from a failing one until an
instance has already committed the damage.

So the contract ships as code. An adapter author writes one test::

    from semprini.testing import check_contract
    from my_package import MyAdapter

    def test_my_adapter_meets_the_contract(tmp_path):
        check_contract(
            MyAdapter,
            settings={"path": str(fixture)},
            unreachable={"path": str(tmp_path / "not-there")},
        )

and gets every check below. It is deliberately framework-free — no pytest import, no
base class to inherit — so that it runs under whatever the author's project already
uses, and so that this module can be part of the shipped wheel rather than of this
repository's test suite.

Two of the checks need something only the author can supply: a ``settings`` mapping that
makes the adapter work, and an ``unreachable`` one that makes its source impossible to
read. The second is required rather than optional. Every source can fail — a file that
is not there, a host that does not answer — and an adapter that has never been asked
what it does when its source is down is exactly the adapter that will one day answer
"deprecate everything" (spec 5.4).

The write guard is a guard and not a proof: it intercepts the ways Python ordinarily
opens a file for writing. An adapter determined to write behind it can, but an adapter
that writes *by accident* — a cache, a debug dump, a temporary file next to the source —
is caught, and that is the failure this is here for.
"""

from __future__ import annotations

import builtins
import io
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from typing import Any

from semprini import serialize
from semprini.adapters.base import AdapterError, BaseAdapter, SourceUnreachableError
from semprini.config import is_slug
from semprini.model import (
    InternalModel,
    Issue,
    IssueError,
    RunContext,
    Scheme,
    SemanticObject,
    Severity,
)

__all__ = ["AdapterContractError", "check_contract"]

CONTRACT_BASE_IRI = "https://semantics.example.com/"
"""The base IRI the default context mints under — an RFC 2606 example domain, so an
adapter that leaks it into a test report has leaked nothing real."""

_WRITE_MODES = frozenset("wax+")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

_GUARDED_OS_CALLS = ("mkdir", "rmdir", "remove", "unlink", "rename", "replace")
"""Every :mod:`os` call that changes the filesystem without opening a file.

Names, not objects: ``os.remove`` and ``os.unlink`` are separate attributes bound to
separate functions, and :mod:`pathlib` reaches each of these by its own name."""


class AdapterContractError(IssueError):
    """An adapter does not meet the contract of spec 5.2.

    Carries every violation found, not the first: an author fixing a new adapter should
    see the whole list once rather than one per run, for the same reason a configuration
    error does (spec 5.1).
    """

    noun = "contract violation"


def check_contract(
    adapter: type[BaseAdapter],
    *,
    settings: Mapping[str, Any],
    unreachable: Mapping[str, Any],
    context: RunContext | None = None,
    source_name: str = "contract-source",
) -> None:
    """Run every contract check against ``adapter``, or raise :class:`AdapterContractError`.

    ``settings`` is a working ``config:`` subtree for the adapter and ``unreachable`` one
    whose source cannot be read. ``context`` defaults to a synthetic instance; pass one
    only if the adapter reads something from it that the default does not provide.
    """
    issues: list[Issue] = []
    _check_the_class(adapter, issues)
    if issues:
        # Nothing below can run against something that is not an adapter, and a hundred
        # consequential failures would bury the one that explains them.
        raise AdapterContractError(issues)

    ctx = context if context is not None else _default_context()
    _check_construction_and_fetch(adapter, settings, ctx, source_name, issues)
    _check_unreachable_raises(adapter, unreachable, ctx, source_name, issues)
    if issues:
        raise AdapterContractError(issues, origin=adapter.__name__)


def _default_context() -> RunContext:
    return RunContext(base_iri=CONTRACT_BASE_IRI, instance_id="contract")


# ------------------------------------------------------------------ the checks


def _check_the_class(adapter: type[BaseAdapter], issues: list[Issue]) -> None:
    if not (isinstance(adapter, type) and issubclass(adapter, BaseAdapter)):
        _fail(issues, "subclass", f"{adapter!r} is not a subclass of BaseAdapter")
        return
    missing: frozenset[str] = getattr(adapter, "__abstractmethods__", frozenset())
    if missing:
        _fail(issues, "subclass", f"does not implement {', '.join(sorted(missing))}")
    name = getattr(adapter, "name", None)
    if not isinstance(name, str) or not name:
        _fail(issues, "name", "has no 'name' — the entry-point name it is registered under")
    elif not is_slug(name):
        # It is written by hand into config/semprini.yaml and read back out of the ID
        # map, so it stays to characters that need no escaping or quoting anywhere.
        _fail(issues, "name", f"name {name!r} is not a slug (lower case, digits, '-', '_')")


def _check_construction_and_fetch(
    adapter: type[BaseAdapter],
    settings: Mapping[str, Any],
    ctx: RunContext,
    source_name: str,
    issues: list[Issue],
) -> None:
    before = _snapshot(settings)
    writes: list[str] = []
    try:
        with _no_writes() as writes:
            instance = adapter(source_name, settings, ctx)
    except Exception as error:
        _report_writes(issues, writes, "construction", "being constructed")
        _fail(issues, "construction", f"could not be constructed: {error!r}")
        return
    _report_writes(issues, writes, "construction", "being constructed")

    try:
        with _no_writes() as writes:
            model = instance.fetch()
    except Exception as error:
        # Reported before the failure itself: a fetch that wrote and *then* failed is the
        # case the no-writes rule exists for — a run that fails midway has to leave the
        # instance exactly as it found it, and a half-written cache is how it does not.
        _report_writes(issues, writes, "no-writes", "fetch()")
        _fail(issues, "fetch", f"raised on a configuration that should work: {error!r}")
        return
    _report_writes(issues, writes, "no-writes", "fetch()")

    if not isinstance(model, InternalModel):
        _fail(issues, "fetch", f"fetch() returned {type(model).__name__}, not an InternalModel")
        return

    _check_source_refs(model, source_name, issues)
    _check_nothing_is_minted(model, ctx, issues)
    _check_it_normalizes(model, issues)
    _check_it_repeats(instance, model, issues)
    _check_settings_are_untouched(settings, before, issues)
    _check_validate_config(instance, issues)
    _check_summary(instance, issues)


def _check_source_refs(model: InternalModel, source_name: str, issues: list[Issue]) -> None:
    """Every object is attributable to the source that produced it (spec 5.2, 5.4)."""
    for object_ in model.objects:
        if source_name not in object_.source_refs:
            _fail(
                issues,
                "source-refs",
                f"{type(object_).__name__} {object_.pref_label!r} carries no source ref "
                f"under {source_name!r} (it has: {', '.join(sorted(object_.source_refs))}); "
                f"identity is keyed by the configured source name",
            )


def _check_nothing_is_minted(model: InternalModel, ctx: RunContext, issues: list[Issue]) -> None:
    """No adapter-supplied value is an IRI in the instance's or the metamodel's space.

    ``Scheme.enumerates`` is the one exception, and it is not really one: that IRI is
    configured by hand in the instance and passed through (spec 5.3), so the adapter is
    relaying a decision rather than making one.
    """
    for object_ in model.objects:
        for name, value in _strings(object_):
            if isinstance(object_, Scheme) and name == "enumerates":
                continue
            if ctx.base_iri in value:
                _fail(
                    issues,
                    "no-minting",
                    f"{type(object_).__name__}.{name} contains the instance's base IRI "
                    f"({value!r}); IRIs come from the ID map, never from an adapter",
                )
            if serialize.SEM_NAMESPACE in value:
                _fail(
                    issues,
                    "no-minting",
                    f"{type(object_).__name__}.{name} contains a sem: IRI ({value!r}); "
                    f"an adapter contributes data, never metamodel terms",
                )


def _check_it_normalizes(model: InternalModel, issues: list[Issue]) -> None:
    """The model the adapter returned is internally consistent.

    An adapter may report one object twice — the same entity in two domain models is
    ordinary (spec 5.3) — but the two reports have to agree, and one source key may not
    name two different things.
    """
    try:
        model.normalized()
    except Exception as error:
        _fail(issues, "consistency", f"the model it returned does not merge with itself: {error}")


def _check_it_repeats(instance: BaseAdapter, model: InternalModel, issues: list[Issue]) -> None:
    """Two fetches of an unchanged source agree.

    Determinism is the property the whole plane rests on (spec 5.5): a compile that
    reordered or renamed something per run would put a diff in front of a steward that
    no one caused.
    """
    writes: list[str] = []
    try:
        with _no_writes() as writes:
            again = instance.fetch()
    except Exception as error:
        _report_writes(issues, writes, "no-writes", "a second fetch()")
        _fail(issues, "repeatable", f"a second fetch() raised where the first did not: {error!r}")
        return
    _report_writes(issues, writes, "no-writes", "a second fetch()")
    if again != model:
        _fail(
            issues,
            "repeatable",
            "two fetches of the same source returned different models; output has to be "
            "byte-identical across runs, and it cannot be if the input is not",
        )


def _check_settings_are_untouched(
    settings: Mapping[str, Any], before: Any, issues: list[Issue]
) -> None:
    if _snapshot(settings) != before:
        _fail(
            issues,
            "no-mutation",
            "it edited the configuration it was given; the run report and later stages "
            "read the same object (spec 5.2)",
        )


def _check_validate_config(instance: BaseAdapter, issues: list[Issue]) -> None:
    """``validate_config()`` reports, rather than raising, and reads nothing."""
    try:
        with _no_writes() as writes:
            reported = instance.validate_config()
    except Exception as error:
        _fail(
            issues, "validate-config", f"validate_config() raised instead of reporting: {error!r}"
        )
        return
    if writes:
        _fail(issues, "validate-config", f"validate_config() wrote to {writes[0]}")
    if not isinstance(reported, Sequence) or isinstance(reported, str | bytes):
        _fail(issues, "validate-config", f"validate_config() returned {type(reported).__name__}")
        return
    if any(not isinstance(item, Issue) for item in reported):
        _fail(
            issues, "validate-config", "validate_config() returned something that is not an Issue"
        )
        return
    errors = [item for item in reported if item.severity is Severity.ERROR]
    if errors:
        _fail(
            issues,
            "validate-config",
            f"validate_config() rejects the settings this check was given: {errors[0]}",
        )


def _check_summary(instance: BaseAdapter, issues: list[Issue]) -> None:
    """The report line is one line — it is rendered into a Markdown table (spec 5.6)."""
    try:
        summary = instance.summary()
    except Exception as error:
        # Collected like every other violation rather than escaping as a traceback: an
        # author running this wants the list, not the first thing that went wrong.
        _fail(issues, "summary", f"summary() raised: {error!r}")
        return
    if not isinstance(summary, str):
        _fail(issues, "summary", f"summary() returned {type(summary).__name__}, not a string")
    elif "\n" in summary:
        _fail(issues, "summary", "summary() returned more than one line")


def _check_unreachable_raises(
    adapter: type[BaseAdapter],
    unreachable: Mapping[str, Any],
    ctx: RunContext,
    source_name: str,
    issues: list[Issue],
) -> None:
    """A source that cannot be read raises, and returns nothing at all (spec 5.2).

    Guarded too, and for the sharpest version of the reason: an adapter that writes what
    it managed to download before giving up leaves a file behind on precisely the run
    that was supposed to change nothing.
    """
    writes: list[str] = []
    try:
        with _no_writes() as writes:
            model = adapter(source_name, unreachable, ctx).fetch()
    except SourceUnreachableError:
        _report_writes(issues, writes, "no-writes", "a fetch from an unreadable source")
        return
    except AdapterError as error:
        _report_writes(issues, writes, "no-writes", "a fetch from an unreadable source")
        _fail(
            issues,
            "unreachable-raises",
            f"an unreadable source raised {type(error).__name__} rather than "
            f"SourceUnreachableError, so CI cannot tell a broken source from broken data "
            f"(exit 3 versus exit 1): {error}",
        )
        return
    except Exception as error:
        _report_writes(issues, writes, "no-writes", "a fetch from an unreadable source")
        _fail(
            issues,
            "unreachable-raises",
            f"an unreadable source raised {type(error).__name__}, which reaches the "
            f"operator as a traceback: {error!r}",
        )
        return
    _report_writes(issues, writes, "no-writes", "a fetch from an unreadable source")
    _fail(
        issues,
        "unreachable-raises",
        f"an unreadable source returned a model of {len(model)} objects instead of "
        f"raising; everything missing from it would be deprecated (spec 5.4)",
    )


# ------------------------------------------------------------------ machinery


def _fail(issues: list[Issue], check: str, message: str) -> None:
    issues.append(Issue(Severity.ERROR, message, check))


def _report_writes(issues: list[Issue], writes: list[str], check: str, what: str) -> None:
    """Report anything written during a guarded call, whatever else that call did.

    Its own function because every guarded block has a failure path as well as a success
    one, and the failure path is where a write matters most: the check that only looked
    at the success path certified an adapter that wrote a partial file and then raised.
    """
    if writes:
        _fail(issues, check, f"{what} wrote to {writes[0]}; adapters never write")


def _strings(object_: SemanticObject) -> Iterator[tuple[str, str]]:
    """Every string an adapter chose, field by field, however it is nested.

    Recursive through dataclasses, because a :class:`~semprini.model.SourceRef` is one —
    and ``Attribute.entity``, ``Relationship.source``/``target`` and
    ``TaxonomyValue.parent`` are exactly the fields an author is tempted to write an IRI
    into, since each of them names another object.
    """
    for descriptor in fields(object_):
        yield from (
            (descriptor.name, found) for found in _strings_in(getattr(object_, descriptor.name))
        )


def _strings_in(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _strings_in(key)
            yield from _strings_in(item)
    elif isinstance(value, Sequence):
        for item in value:
            yield from _strings_in(item)
    elif is_dataclass(value) and not isinstance(value, type):
        for descriptor in fields(value):
            yield from _strings_in(getattr(value, descriptor.name))


def _snapshot(value: Any) -> Any:
    """A comparable copy of a settings tree, so mutation of it can be detected."""
    if isinstance(value, Mapping):
        return {key: _snapshot(item) for key, item in value.items()}
    if isinstance(value, str | bytes):
        return value
    if isinstance(value, Sequence):
        return [_snapshot(item) for item in value]
    return value


@contextmanager
def _no_writes() -> Iterator[list[str]]:
    """Record any attempt to open a file for writing, and let it happen anyway.

    Recording rather than blocking: an adapter that is refused a write may take a
    confusing second path, and what the author needs to see is the one line naming the
    file it tried to write.

    ``io.open`` is patched as well as ``builtins.open`` even though they are the same
    function, because :mod:`pathlib` holds its own reference — ``Path.write_text`` would
    otherwise pass straight through. For the same reason the :mod:`os` calls are patched
    by name from :data:`_GUARDED_OS_CALLS` rather than one at a time: ``os.remove`` and
    ``os.unlink`` are two attributes bound to two different objects, so patching one
    leaves ``Path.unlink()`` — deletion, the most damaging thing an adapter could do to
    an instance — entirely unrecorded.
    """
    written: list[str] = []
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
    originals = {name: getattr(os, name) for name in _GUARDED_OS_CALLS}

    def guarded_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if _WRITE_MODES & set(mode):
            written.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    def guarded_os_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> Any:
        if flags & _WRITE_FLAGS:
            written.append(str(path))
        return real_os_open(path, flags, *args, **kwargs)

    def guarded(real: Any) -> Any:
        def record(path: Any, *args: Any, **kwargs: Any) -> Any:
            written.append(str(path))
            return real(path, *args, **kwargs)

        return record

    builtins.open = guarded_open
    io.open = guarded_open
    os.open = guarded_os_open
    for name, real in originals.items():
        setattr(os, name, guarded(real))
    try:
        yield written
    finally:
        builtins.open, io.open, os.open = real_open, real_io_open, real_os_open
        for name, real in originals.items():
            setattr(os, name, real)

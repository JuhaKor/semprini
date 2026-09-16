"""The adapter contract, as an executable test (spec 5.2).

Ships in the wheel and imports no test framework. An adapter author writes one test::

    from semprini.testing import check_contract
    from my_package import MyAdapter

    def test_my_adapter_meets_the_contract(tmp_path):
        check_contract(
            MyAdapter,
            settings={"path": str(fixture)},
            unreachable={"path": str(tmp_path / "not-there")},
        )

and gets every check below. ``settings`` must make the adapter work and ``unreachable``
must make its source unreadable; the second is required because an adapter that returns
a partial model would deprecate everything missing from it (spec 5.4).

The write guard intercepts the ordinary ways Python opens a file for writing. It catches
an accidental write, not a determined one.
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
    SemanticObject,
    Severity,
    normalize_text,
)

__all__ = ["AdapterContractError", "check_contract"]

CONTRACT_BASE_IRI = "https://semantics.example.com/"
"""The base IRI the default context mints under; an RFC 2606 example domain."""

_WRITE_MODES = frozenset("wax+")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

_GUARDED_OS_CALLS = ("mkdir", "rmdir", "remove", "unlink", "rename", "replace")
"""Every :mod:`os` call that changes the filesystem without opening a file. Names, because
``os.remove`` and ``os.unlink`` are separate attributes and :mod:`pathlib` uses each."""


class AdapterContractError(IssueError):
    """An adapter does not meet the contract of spec 5.2. Carries every violation found."""

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
        _report_writes(issues, writes, "no-writes", "fetch()")
        _fail(issues, "fetch", f"raised on a configuration that should work: {error!r}")
        return
    _report_writes(issues, writes, "no-writes", "fetch()")

    if not isinstance(model, InternalModel):
        _fail(issues, "fetch", f"fetch() returned {type(model).__name__}, not an InternalModel")
        return

    _check_source_refs(model, source_name, issues)
    _check_nothing_is_minted(model, ctx, issues)
    _check_text_is_normalized(model, issues)
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
    """No adapter-supplied value is an IRI in the instance's or the metamodel's space."""
    for object_ in model.objects:
        for name, value in _strings(object_):
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


def _check_text_is_normalized(model: InternalModel, issues: list[Issue]) -> None:
    """Nothing an adapter returned still carries an invisible or decomposed character (spec 5.5 rule
    9).

    Catches a plain ``str`` field that bypassed ``Text`` and ``SourceRef``. The offending
    characters are named by code point.
    """
    for object_ in model.objects:
        for name, value in _strings(object_):
            if value == normalize_text(value):
                continue
            odd = sorted(
                {character for character in value if normalize_text(character) != character}
            )
            listed = ", ".join(f"U+{ord(character):04X}" for character in odd)
            _fail(
                issues,
                "normalized-text",
                f"{type(object_).__name__}.{name} is not normalized ({value!r} carries "
                f"{listed or 'a decomposed character'}); pass source text through "
                f"model.normalize_text, or build it as a Text or SourceRef, so that a "
                f"character nobody can see cannot become an identifier or split a label",
            )


def _check_it_normalizes(model: InternalModel, issues: list[Issue]) -> None:
    """The model the adapter returned merges with itself (spec 5.3)."""
    try:
        model.normalized()
    except Exception as error:
        _fail(issues, "consistency", f"the model it returned does not merge with itself: {error}")


def _check_it_repeats(instance: BaseAdapter, model: InternalModel, issues: list[Issue]) -> None:
    """Two fetches of an unchanged source agree (spec 5.5)."""
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
    """The report line is one line; it is rendered into a Markdown table (spec 5.6)."""
    try:
        summary = instance.summary()
    except Exception as error:
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
    """A source that cannot be read raises :class:`SourceUnreachableError` and writes nothing (spec
    5.2).
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
    """Report anything written during a guarded call, on its failure path as well as its success
    path.
    """
    if writes:
        _fail(issues, check, f"{what} wrote to {writes[0]}; adapters never write")


def _strings(object_: SemanticObject) -> Iterator[tuple[str, str]]:
    """Every string an adapter chose, field by field, recursing into nested dataclasses."""
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

    ``io.open`` is patched as well as ``builtins.open`` because :mod:`pathlib` holds its
    own reference, and the :mod:`os` calls by name for the same reason.
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

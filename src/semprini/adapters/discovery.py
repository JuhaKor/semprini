"""Finding installed adapters (spec 5.2).

Adapters are discovered through the ``semprini.adapters`` entry-point group, never
imported by name. Listing reads metadata only; a plugin is imported in
:meth:`AdapterEntry.load`, at the point it is used.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points

from semprini.adapters.base import AdapterLoadError, BaseAdapter
from semprini.config import SourceConfig
from semprini.model import RunContext

__all__ = [
    "ENTRY_POINT_GROUP",
    "AdapterEntry",
    "adapter_names",
    "ambiguities",
    "create",
    "discover",
    "load_adapter",
]

ENTRY_POINT_GROUP = "semprini.adapters"
"""The entry-point group every adapter registers in."""


@dataclass(frozen=True, slots=True)
class AdapterEntry:
    """One installed adapter registration, before anything is imported."""

    name: str
    """The entry-point name, which is what an instance writes as ``adapter:``."""

    value: str
    """``module:attribute``, for naming a broken plugin precisely."""

    distribution: str | None = None
    """Which installed distribution provides it; ``None`` outside the metadata machinery."""

    version: str | None = None

    @property
    def provider(self) -> str:
        """How to name the distribution in a message an operator has to act on."""
        if self.distribution is None:
            return "an unknown distribution"
        if self.version is None:
            return self.distribution
        return f"{self.distribution} {self.version}"

    def load(self) -> type[BaseAdapter]:
        """Import the adapter class (spec 5.2).

        Raises :class:`AdapterLoadError`, naming the distribution, if the import fails, the
        object is not a concrete :class:`BaseAdapter` subclass, or its ``name`` differs from
        the registration.
        """
        try:
            loaded = EntryPoint(self.name, self.value, ENTRY_POINT_GROUP).load()
        except Exception as error:
            # Broad on purpose: a third party's module body can fail in any way.
            raise AdapterLoadError(
                f"adapter {self.name!r} from {self.provider} could not be imported "
                f"({self.value}): {error}"
            ) from error

        if not (isinstance(loaded, type) and issubclass(loaded, BaseAdapter)):
            raise AdapterLoadError(
                f"adapter {self.name!r} from {self.provider} is {loaded!r}, "
                f"which is not a BaseAdapter subclass ({self.value})"
            )
        if inspect.isabstract(loaded):
            missing = ", ".join(sorted(loaded.__abstractmethods__))
            raise AdapterLoadError(
                f"adapter {self.name!r} from {self.provider} does not implement {missing} "
                f"({self.value})"
            )
        declared = getattr(loaded, "name", None)
        if declared != self.name:
            raise AdapterLoadError(
                f"adapter {self.name!r} from {self.provider} calls itself {declared!r}; "
                f"an adapter's name is the name it is registered under, since that is "
                f"what an instance writes in config/semprini.yaml ({self.value})"
            )
        return loaded


def discover() -> tuple[AdapterEntry, ...]:
    """Every adapter registration this installation offers, in a stable order.

    Duplicate names are kept; :func:`load_adapter` and :func:`ambiguities` report them.
    """
    found = [_entry(point) for point in entry_points(group=ENTRY_POINT_GROUP)]
    return tuple(
        sorted(found, key=lambda entry: (entry.name, entry.distribution or "", entry.value))
    )


def _entry(point: EntryPoint) -> AdapterEntry:
    distribution = point.dist
    return AdapterEntry(
        name=point.name,
        value=point.value,
        distribution=None if distribution is None else distribution.name,
        version=None if distribution is None else distribution.version,
    )


def adapter_names() -> frozenset[str]:
    """The names an instance may write as ``adapter:`` on this
    installation (spec 5.1). No imports.
    """
    return frozenset(entry.name for entry in discover())


def load_adapter(name: str) -> type[BaseAdapter]:
    """The adapter class registered under ``name``.

    Raises :class:`AdapterLoadError` if nothing is registered under it, if more than one
    distribution is, or if what is registered cannot be used.
    """
    available = discover()
    matching = [entry for entry in available if entry.name == name]
    if not matching:
        installed = ", ".join(sorted({entry.name for entry in available})) or "none"
        raise AdapterLoadError(
            f"no adapter named {name!r} is installed (installed: {installed}); "
            f"an adapter is added by installing the distribution that provides it"
        )
    if len(matching) > 1:
        raise AdapterLoadError(_ambiguity(name, matching))
    return matching[0].load()


def _ambiguity(name: str, matching: Sequence[AdapterEntry]) -> str:
    providers = ", ".join(entry.provider for entry in matching)
    return (
        f"adapter {name!r} is registered by more than one installed distribution "
        f"({providers}); uninstall one, since configuration cannot say which is meant"
    )


def ambiguities(entries: Iterable[AdapterEntry]) -> tuple[str, ...]:
    """One message per entry-point name that more than one distribution claims.

    The same words :func:`load_adapter` fails with, so ``semprini adapters`` reports the
    clash a run would hit.
    """
    grouped: dict[str, list[AdapterEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.name, []).append(entry)
    return tuple(
        _ambiguity(name, group) for name, group in sorted(grouped.items()) if len(group) > 1
    )


def create(source: SourceConfig, ctx: RunContext) -> BaseAdapter:
    """The adapter instance for one configured source (spec 5.1, 5.2). Nothing is fetched."""
    return load_adapter(source.adapter)(source.name, source.settings, ctx)

"""Finding installed adapters (spec 5.2).

Adapters are **discovered, not imported**. Nothing in the compiler names an adapter
module: a distribution declares a ``semprini.adapters`` entry point, and installing it is
what makes ``adapter: <name>`` a thing an instance may write. The adapters bundled with
the plane arrive by exactly this route, so there is no privileged path a third party is
kept off (spec 5.2).

Discovery therefore never imports anything on its own. Listing what is installed is a
question about metadata, and answering it by importing every plugin would run arbitrary
third-party code every time a configuration is loaded. Import happens in
:meth:`AdapterEntry.load`, at the point where an adapter is actually going to be used —
or in ``semprini adapters``, whose whole job is to report whether the installation works.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points

from semprini.adapters.base import AdapterLoadError, BaseAdapter
from semprini.config import SourceConfig
from semprini.model import RunContext

__all__ = [
    "ENTRY_POINT_GROUP",
    "AdapterEntry",
    "adapter_names",
    "create",
    "discover",
    "load_adapter",
]

ENTRY_POINT_GROUP = "semprini.adapters"
"""The entry-point group every adapter registers in — bundled or third-party."""


@dataclass(frozen=True, slots=True)
class AdapterEntry:
    """One installed adapter registration, before anything is imported."""

    name: str
    """The entry-point name, which is what an instance writes as ``adapter:``."""

    value: str
    """``module:attribute`` — kept so that a broken plugin can be reported precisely
    enough to fix, rather than as "something called ellie does not work"."""

    distribution: str | None = None
    """Which installed distribution provides it. ``None`` only for an entry point that
    reached us outside the metadata machinery, which in practice means a test."""

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
        """Import the adapter class, refusing anything unusable (spec 5.2).

        Every refusal here is an installation problem rather than a data problem, and
        each one is worth a specific message: the operator's next action is to reinstall
        or uninstall something, and they need to know which distribution to blame.
        """
        try:
            loaded = EntryPoint(self.name, self.value, ENTRY_POINT_GROUP).load()
        except Exception as error:
            # Deliberately broad: this is the moment a third party's module body runs,
            # and it can fail in any way a Python module can. Whatever it raises, the
            # operator's problem is the same one and it is not a Semprini traceback.
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

    Duplicate names are kept rather than resolved. Two distributions claiming one name
    is a genuine ambiguity — ``adapter: ellie`` would mean different things on two
    machines — so it is reported where it can be fixed rather than silently decided
    here (see :func:`load_adapter`).
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
    """The names an instance may write as ``adapter:`` on this installation.

    What :mod:`semprini.config` validates a source's ``adapter`` against (spec 5.1).
    Names only, and no imports: a typo in one source's configuration must not depend on
    an unrelated plugin being importable.
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
        providers = ", ".join(entry.provider for entry in matching)
        raise AdapterLoadError(
            f"adapter {name!r} is registered by more than one installed distribution "
            f"({providers}); uninstall one, since configuration cannot say which is meant"
        )
    return matching[0].load()


def create(source: SourceConfig, ctx: RunContext) -> BaseAdapter:
    """The adapter instance for one configured source (spec 5.1, 5.2).

    Construction only — nothing is fetched, and nothing may be: ``semprini check``
    constructs adapters purely to call ``validate_config()`` (spec 6.1).
    """
    return load_adapter(source.adapter)(source.name, source.settings, ctx)

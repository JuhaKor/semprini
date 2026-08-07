"""Source adapters (spec 5.2, 5.3).

Adapters are discovered through the ``semprini.adapters`` entry-point group, not
imported by name, so any installed distribution can add a source without forking the
plane. Bundled adapters are ordinary plugins that happen to ship here.

This is the import an adapter author writes against — ``BaseAdapter`` and the errors
they raise — and the one the compiler uses to find them. It deliberately imports no
adapter module: the bundled ones are found the same way a third party's is.
"""

from __future__ import annotations

from semprini.adapters.base import (
    AdapterError,
    AdapterLoadError,
    BaseAdapter,
    SourceUnreachableError,
)
from semprini.adapters.discovery import (
    ENTRY_POINT_GROUP,
    AdapterEntry,
    adapter_names,
    create,
    discover,
    load_adapter,
)

__all__ = [
    "ENTRY_POINT_GROUP",
    "AdapterEntry",
    "AdapterError",
    "AdapterLoadError",
    "BaseAdapter",
    "SourceUnreachableError",
    "adapter_names",
    "create",
    "discover",
    "load_adapter",
]

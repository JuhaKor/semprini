"""Source adapters (spec 5.2, 5.3).

The import an adapter author writes against, and the one the compiler discovers adapters
through. It imports no adapter module: bundled adapters are found through the
``semprini.adapters`` entry-point group like any third party's.
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
    ambiguities,
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
    "ambiguities",
    "create",
    "discover",
    "load_adapter",
]

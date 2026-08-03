"""``BaseAdapter`` — the plugin contract (spec 5.2).

Filled by task D1, together with entry-point discovery and the shared contract test
suite third-party authors run against their own adapters. Adapters fetch and normalize;
they never write to disk and never mint IRIs.
"""

from __future__ import annotations

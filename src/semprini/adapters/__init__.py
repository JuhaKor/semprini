"""Source adapters (spec 5.2, 5.3).

Adapters are discovered through the ``semprini.adapters`` entry-point group, not
imported by name, so any installed distribution can add a source without forking the
plane. Bundled adapters are ordinary plugins that happen to ship here.
"""

from __future__ import annotations

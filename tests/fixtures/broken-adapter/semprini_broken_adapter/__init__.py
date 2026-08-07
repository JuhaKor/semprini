"""A plugin that fails on import, for the case an operator will actually hit.

A third-party adapter is ordinary Python: it can be installed against the wrong version
of something, or import a dependency that is not there. What matters is that one broken
plugin is reported as a broken plugin — naming the distribution to uninstall — rather
than surfacing as a traceback from inside the compiler, or worse, quietly making every
other adapter undiscoverable.
"""

from __future__ import annotations

raise RuntimeError("this adapter is broken on purpose")

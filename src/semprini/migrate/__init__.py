"""Version-to-version migrations (spec 7).

Filled by task G3. A release that changes emitted output ships a migration here, so an
upgrade is always a reviewable diff rather than an unexplained reflow. Migrations never
mint new IRIs for existing objects and never remove ID-map rows.
"""

from __future__ import annotations

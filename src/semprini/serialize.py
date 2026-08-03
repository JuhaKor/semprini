"""Canonical Turtle serialization (spec 5.5).

Filled by task B1, and the linchpin of the design: reviewable PR diffs, safe upgrades
and the CI determinism check all reduce to this module being correct. Fixed prefix
block, sorted subjects and predicates, no blank nodes, no timestamps, byte-determinism.
"""

from __future__ import annotations

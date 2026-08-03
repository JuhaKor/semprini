"""SHACL and structural checks behind ``semprini check`` (spec 6.1).

Filled by task F2 over the shapes of task F1. Every check lives here rather than in
workflow YAML (spec 6.3), so failures reproduce identically on a laptop and in CI.
"""

from __future__ import annotations

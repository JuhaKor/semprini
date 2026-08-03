"""The internal model adapters return and the core consumes (spec 5.1, 5.2).

Filled by task B2: ``InternalModel``, the ``Concept`` / ``Attribute`` / ``Relationship``
/ ``Scheme`` / ``TaxonomyValue`` dataclasses, ``source_refs`` and ``RunContext``.
Immutable where practical — adapters must not mutate shared state.
"""

from __future__ import annotations

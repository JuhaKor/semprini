"""The migrations this release ships (spec 7). Empty until a release changes emitted output.

**How to add one.** A step is a pure function from the committed state to the state the new
release would have written. The framework re-serializes, refreshes the ontology copy,
restamps the manifest, writes the report, and refuses the whole migration if the step
minted an IRI, dropped a node, moved a ``dcterms:modified`` date or touched the ID map
beyond its ``note`` column. A step is usually a few lines:

.. code-block:: python

    def _rename_status(state: InstanceState) -> InstanceState:
        return state.with_graphs(
            {
                name: _replace_predicate(graph, _SEM_LEGACY_STATUS, _SEM_STATUS)
                for name, graph in state.graphs.items()
            }
        )

    MIGRATIONS = (
        Migration(
            version="0.2.0",
            summary="`sem:legacyStatus` is written as `sem:status`",
            apply=_rename_status,
        ),
    )

A step never reads the sources: if the new output cannot be derived from the old, ship no
step and say so in the CHANGELOG. A recompile is not a substitute either, because deprecated
nodes are carried forward verbatim (spec 3.5) and would keep their old statements.
"""

from __future__ import annotations

from semprini.migrate.registry import Migration

__all__ = ["MIGRATIONS"]

MIGRATIONS: tuple[Migration, ...] = ()
"""Every migration this release ships; :func:`~semprini.migrate.registry.plan` orders them."""

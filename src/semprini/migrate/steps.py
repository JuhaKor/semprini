"""The migrations this release ships, in release order (spec 7).

Empty, and that is a statement rather than a gap: nothing has been released yet, so no
instance in existence was compiled by an earlier version of this compiler, and a step
"from" a version nobody ran would be fiction. The machinery around it is what this task
delivers; the first real entry belongs to the first release that changes emitted output.

**How to add one.** A step is a pure function from the committed state to the state the new
release would have written, and the framework does everything around it — it re-serializes,
refreshes the ontology copy, restamps the manifest, writes the report, and refuses the whole
migration if the step minted an IRI, dropped a node, moved a ``dcterms:modified`` date or
touched the ID map beyond its ``note`` column. So a step is usually a few lines:

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

Three things to know before writing one.

*A migration is not a recompile.* It rewrites what is committed without reading the
sources, which is what lets an adopter review the upgrade as a diff that provably changed
no content. The next scheduled compile is what reconciles content, and it will replace the
migration report with its own.

*Reaching for the sources is the tell that a step is wrong.* If the new output cannot be
derived from the old, the release is asking adopters to recompile rather than to migrate,
and the honest answer is to ship no step and say so in the CHANGELOG.

*A recompile is not a substitute for a migration either*, which is the reason this module
exists at all. Nodes no source reports any more are re-emitted verbatim from the previous
run's files (spec 3.5), so a compile carries their **old** statements forward untouched. A
term rename applied by recompiling would therefore reach every active node and quietly miss
every deprecated one.
"""

from __future__ import annotations

from semprini.migrate.registry import Migration

__all__ = ["MIGRATIONS"]

MIGRATIONS: tuple[Migration, ...] = ()
"""Every migration this release ships, in any order — :func:`~semprini.migrate.registry.plan`
sorts them by version and refuses two for one release."""

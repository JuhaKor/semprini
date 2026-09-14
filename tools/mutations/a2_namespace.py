"""A2's battery: the namespace lock with its one bypass gone — demand it still bites.

Removing `--force-namespace-change` took away the only invocation that was allowed to
disagree with `mappings/namespace.lock`, and with it the plumbing that let a run proceed
under a base IRI the lock did not name. What is left is a check that every command runs
before touching anything, and a check that is never expected to fire on a healthy instance
is the easiest kind to break silently: comment it out, and every test that compiles the
fixture still passes.

Three groups.

**The lock stops checking.** Either half of the comparison — base IRI, instance id — or
the load that precedes it. Each has to be reached from the CLI, since the flag that used to
skip the call is gone and nothing else may take its place.

**The refusal comes too late.** The lock is verified while loading configuration, before a
source is fetched or a byte is written. A verification that happens after the write leaves
`generated/` under one base and the lock under another, which is the state the whole file
exists to prevent.

**The register is written after all.** The move was the one compile that wrote
`mappings/merges.csv`; now none does. A save that crept back into the write phase would
re-render a steward's file on every run.
"""

from __future__ import annotations

TESTS: tuple[str, ...] = (
    "tests/test_identity.py",
    "tests/test_run.py",
    "tests/test_cli.py",
)

IDENTITY = "src/semprini/identity.py"
CLI = "src/semprini/cli.py"
RUN = "src/semprini/run.py"

# (description, file, old, new). `old` is a verbatim fragment of the file it anchors to and
# appears in it exactly once.
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    # ------------------------------------------------------- the lock stops checking
    (
        "a base IRI that disagrees with the lock is accepted",
        IDENTITY,
        "        if config.base_iri != self.base_iri:",
        "        if False:",
    ),
    (
        "an instance id that disagrees with the lock is accepted",
        IDENTITY,
        "        if config.instance_id != self.instance_id:",
        "        if False:",
    ),
    (
        "the lock is loaded and never compared",
        IDENTITY,
        "    lock = NamespaceLock.load(config.repo_root)\n    lock.verify(config)\n",
        "    lock = NamespaceLock.load(config.repo_root)\n",
    ),
    (
        "a missing lock is treated as an instance with nothing to check",
        IDENTITY,
        "        except FileNotFoundError:\n            # Refused, not assumed absent",
        "        except FileNotFoundError:\n            raise SystemExit(0)\n"
        "            # Refused, not assumed absent",
    ),
    (
        "the refusal names the flag that no longer exists instead of the way out",
        IDENTITY,
        '                    f"IRIs under {self.base_iri!r}; the base IRI is permanent — an "\n'
        '                    f"instance that needs a different one is a new instance",',
        '                    f"IRIs under {self.base_iri!r}; changing it is a migration, not a "\n'
        '                    f"configuration edit — see semprini run --force-namespace-change",',
    ),
    # ------------------------------------------------------- the refusal comes too late
    (
        "the CLI loads configuration without verifying the lock",
        CLI,
        "    identity.verify_namespace_lock(loaded)\n    return loaded\n",
        "    return loaded\n",
    ),
    (
        "the run builds its registry without the lock, so a mismatch reaches minting",
        RUN,
        "    registry = Registry.load(settings, today=today)\n",
        "    from semprini.identity import IdMap\n\n"
        "    registry = Registry(\n"
        "        IdMap.load(root), settings.base_iri, repo_root=root, today=today\n"
        "    )\n",
    ),
    # ------------------------------------------------------- the register is written after all
    (
        "the merge register is re-rendered on every run",
        RUN,
        "        registry.save(root)\n        build.remove(stale, root)\n",
        "        registry.save(root)\n        merges.save(root)\n"
        "        build.remove(stale, root)\n",
    ),
)

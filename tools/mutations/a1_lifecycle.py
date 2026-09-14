"""A1's battery: break the reduced lifecycle stage, and demand the suite notices.

Removing `--source` left `lifecycle.plan()` with one question per node — does any
configured source still report it — and that is exactly the shape a test suite is worst
at. The module's whole output on a healthy instance is *nothing moved*: two runs of
unchanged sources produce zero diff, so a plan that silently decided nothing and a plan
that decided correctly look identical from the outside on every run but one.

Four groups.

**An object leaves the instance.** The failure the module exists to make impossible.
Dropping a node from the plan is not "no deprecation" but deletion, because `generated/`
is rewritten whole; keeping it but discarding its statements is the quieter version of the
same thing. Both have to fail loudly, and they are the reason the deprecation tests assert
what *survives* rather than what is emitted.

**Nothing is ever deprecated.** The opposite failure, and the cheaper one to ship: a
compiler that never concludes an object is gone passes every test that compiles unchanged
sources. Only a test that deletes something from a source can tell.

**A refusal stops refusing.** An IRI in the output that the ID map has never heard of, and
a merge register row for an object the sources still describe, are both states where the
compiler must stop rather than guess. Neither arises from the bundled adapters, so the
`raise` is reached only by a test that manufactures it.

**The decision loses its shape.** Which block carries `dcterms:isReplacedBy`, whether
`dcterms:modified` is re-derived rather than carried, and whether subjects are judged in
sorted order — each is invisible on a passing run and each is a diff an adopter would have
to explain.
"""

from __future__ import annotations

TESTS: tuple[str, ...] = (
    "tests/test_lifecycle.py",
    "tests/test_run.py",
    "tests/test_build.py",
)

LIFECYCLE = "src/semprini/lifecycle.py"
BUILD = "src/semprini/build.py"

# (description, file, old, new). `old` is a verbatim fragment of the file it anchors to and
# appears in it exactly once.
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    # ------------------------------------------------- an object leaves the instance
    (
        "a deprecated node is dropped from the plan, and so deleted from the instance",
        LIFECYCLE,
        "        carried.extend(_deprecate(subject, blocks, register.replacement(iri)))",
        "        _deprecate(subject, blocks, register.replacement(iri))",
    ),
    (
        "a deprecated node keeps its status and loses everything else it said",
        LIFECYCLE,
        "        statements = {(p, o) for p, o in block.statements if p not in _DERIVED}",
        "        statements: set[tuple[URIRef, Node]] = set()",
    ),
    (
        "only the defining block is retained, so a file that merely mentions the node "
        "loses what it said",
        LIFECYCLE,
        "    for block in blocks:\n"
        "        statements = {(p, o) for p, o in block.statements if p not in _DERIVED}",
        "    for block in blocks:\n"
        "        if not block.defines:\n"
        "            continue\n"
        "        statements = {(p, o) for p, o in block.statements if p not in _DERIVED}",
    ),
    (
        "a retained node is written to one file rather than the ones that held it",
        LIFECYCLE,
        "        yield CarriedNode(\n            file=block.file,",
        '        yield CarriedNode(\n            file="concepts-sales.ttl",',
    ),
    (
        "build stops checking that a carried node is not also compiled",
        BUILD,
        "        self._check_carried_are_gone(resolved)",
        "        pass",
    ),
    # ------------------------------------------------------ nothing is ever deprecated
    (
        "every previous node is treated as still reported",
        LIFECYCLE,
        "        iri = str(subject)\n        if iri in live:\n            continue",
        "        iri = str(subject)\n        if True:\n            continue",
    ),
    (
        "the node is retained but its status is left active",
        LIFECYCLE,
        "            statements.add((SEM_STATUS, Literal(STATUS_DEPRECATED)))",
        "            statements.add((SEM_STATUS, Literal(STATUS_ACTIVE)))",
    ),
    (
        "the run reports no deprecations even when it made them",
        LIFECYCLE,
        "        if any(block.was_active for block in blocks):\n            deprecated.append(iri)",
        "        if False:\n            deprecated.append(iri)",
    ),
    (
        "a node that was already deprecated is reported as newly deprecated every run",
        LIFECYCLE,
        "        if any(block.was_active for block in blocks):",
        "        if True:",
    ),
    (
        "a defining block is required in every file, so a node described in one and "
        "mentioned in another is never judged",
        LIFECYCLE,
        "        if not any(block.defines for block in blocks):",
        "        if not all(block.defines for block in blocks):",
    ),
    # ------------------------------------------------------- a refusal stops refusing
    (
        "an IRI in the output that the ID map has never heard of is deprecated instead of refused",
        LIFECYCLE,
        "        if not registry.id_map.owners(iri):",
        "        if False:",
    ),
    (
        "a register row for an object the sources still describe is silently inert",
        LIFECYCLE,
        "    issues.extend(_check_merges_are_gone(register, live))",
        "    _check_merges_are_gone(register, live)",
    ),
    (
        "the register is not checked against the ID map, so a mistyped IRI does nothing",
        LIFECYCLE,
        "    issues = list(register.check_against(registry.id_map))",
        "    issues: list[Issue] = []",
    ),
    (
        "issues are collected and never raised",
        LIFECYCLE,
        "    if issues:\n        raise LifecycleError(issues)",
        "    if False:\n        raise LifecycleError(issues)",
    ),
    # --------------------------------------------------- the decision loses its shape
    (
        "isReplacedBy is written onto every block rather than the one describing the node",
        LIFECYCLE,
        "        if block.defines:\n"
        "            statements.add((SEM_STATUS, Literal(STATUS_DEPRECATED)))",
        "        if True:\n            statements.add((SEM_STATUS, Literal(STATUS_DEPRECATED)))",
    ),
    (
        "the merge register's successor is never emitted",
        LIFECYCLE,
        "            if replacement is not None:\n"
        "                statements.add((DCTERMS.isReplacedBy, URIRef(replacement)))",
        "            if False:\n"
        "                statements.add((DCTERMS.isReplacedBy, URIRef(replacement)))",
    ),
    (
        "the register is read but the row is looked up under the wrong IRI",
        LIFECYCLE,
        "register.replacement(iri)))",
        "register.replacement(iri + '#')))",
    ),
    (
        "dcterms:modified is carried forward rather than re-derived, so a deprecation "
        "keeps the date it had",
        LIFECYCLE,
        "_DERIVED = frozenset({SEM_STATUS, DCTERMS.isReplacedBy, DCTERMS.modified})",
        "_DERIVED = frozenset({SEM_STATUS, DCTERMS.isReplacedBy})",
    ),
    (
        "subjects are judged in set order, so the reported deprecations are unordered",
        LIFECYCLE,
        "    for subject in sorted(index, key=str):",
        "    for subject in index:",
    ),
    # `_index`'s own `for name in sorted(previous)` is deliberately not mutated here: it
    # is an equivalent mutant, not a gap. `build.read_previous_files` builds its mapping
    # from `sorted(directory.glob(...))`, and a dict keeps insertion order, so no real
    # caller can present an unsorted one. The sort stays as the guarantee for a caller
    # that does — every test passing a dict literal is one — but nothing observable
    # changes when it goes, and a battery that reported it would cry wolf every run.
    (
        "a block counts as defining on any statement, not the label",
        LIFECYCLE,
        "                    defines=any(predicate == SKOS.prefLabel for predicate, _ in found),",
        "                    defines=bool(found),",
    ),
)

"""Canonical Turtle serialization (spec 5.5).

The linchpin of the design: reviewable PR diffs, safe upgrades and the CI determinism
check all reduce to this module being correct. ``rdflib``'s own Turtle output is not
deterministic — prefixes, subject order and blank-node labels all vary between runs —
so the compiler never uses it for anything an instance commits.

Two properties are load-bearing, and every choice below serves one of them:

*Byte-determinism.* The same graph serializes to the same bytes in any process, on any
platform, whatever order the triples were added in. That is what lets CI recompile from
a cached fetch snapshot and demand an identical file (spec 6.1).

*Diff legibility.* A reviewer reads the output as governance, so one changed fact is one
changed line: predicates with several objects repeat the predicate rather than sharing a
comma list, and blocks are separated so an added subject is an added hunk.

A change to anything here changes every instance's generated files, which makes it a
major version bump with a migration (spec 7).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from pathlib import Path

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, SKOS
from rdflib.term import Node

__all__ = [
    "CANONICAL_PREFIXES",
    "SEM_NAMESPACE",
    "namespaces",
    "serialize",
    "write",
]

SEM_NAMESPACE = "https://w3id.org/semprini/ontology#"
_SKOS_NAMESPACE = "http://www.w3.org/2004/02/skos/core#"
_DCTERMS_NAMESPACE = "http://purl.org/dc/terms/"
_XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema#"
_XSD_STRING = URIRef(f"{_XSD_NAMESPACE}string")

# Namespaces identical in every deployment (spec 3.1).
_FIXED_NAMESPACES = {
    "sem": SEM_NAMESPACE,
    "skos": _SKOS_NAMESPACE,
    "dcterms": _DCTERMS_NAMESPACE,
    "xsd": _XSD_NAMESPACE,
}

# Namespaces derived from the instance's base IRI (spec 3.1). The instance IRI space is
# partitioned by kind of thing, so the suffix is part of the identity contract: changing
# one would re-mint every IRI under it.
_INSTANCE_SUFFIXES = {
    "c": "concepts/",
    "r": "relationships/",
    "sch": "schemes/",
    "v": "values/",
    "x": "ext#",
    "a": "assets/",
    "d": "docs/",
}

# Spec 5.5 rule 1: a fixed block, in the order spec 3.1 introduces the namespaces —
# the metamodel, the per-instance content namespaces, the reused standard vocabularies,
# then the two reserved for later versions. Emitted whether or not a file uses them, so
# that adding the first triple in a namespace is not also a change to the prefix block.
CANONICAL_PREFIXES = ("sem", "c", "r", "sch", "v", "x", "skos", "dcterms", "xsd", "a", "d")

_INDENT = "  "

# Local names that can be written after a prefix without escaping. Deliberately
# narrower than Turtle's PN_LOCAL: minted local names are UUIDs and slugs, and anything
# unusual falls back to the unambiguous <full IRI> form rather than risking a rule this
# module gets subtly wrong.
_SAFE_LOCAL_NAME = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_.\-]*[A-Za-z0-9_\-])?")

_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}

# Predicates with a fixed position, ahead of the lexicographic tail (rule 3): the type
# says what the block is, the label says which thing it is, and a reader scanning a diff
# wants both before the detail.
_PREDICATE_RANK = {RDF.type: 0, SKOS.prefLabel: 1}
_TAIL_RANK = max(_PREDICATE_RANK.values()) + 1


def namespaces(base_iri: str) -> Mapping[str, str]:
    """Return the prefix block for ``base_iri``, in canonical order (spec 3.1, 5.5).

    Also the one place the per-kind namespace suffixes are written down: identity
    (spec 3.4) mints into these same namespaces and reads them from here.
    """
    _check_base_iri(base_iri)
    resolved = {**_FIXED_NAMESPACES, **{p: base_iri + s for p, s in _INSTANCE_SUFFIXES.items()}}
    return {prefix: resolved[prefix] for prefix in CANONICAL_PREFIXES}


def serialize(graph: Graph, base_iri: str) -> str:
    """Serialize ``graph`` as canonical Turtle (spec 5.5).

    Raises ``ValueError`` for a graph the rules cannot express: a blank node (rule 7), a
    literal or blank node in subject position, or a base IRI that is not a usable
    namespace root.
    """
    prefixes = namespaces(base_iri)
    lines = [f"@prefix {prefix}: <{namespace}> ." for prefix, namespace in prefixes.items()]
    for block in _blocks(graph, prefixes):
        # Blank line before every block, which also separates the first block from the
        # prefixes. Subjects are whole hunks in a diff rather than run together.
        lines.append("")
        lines.append(block)

    return "\n".join(lines) + "\n"


def write(path: Path, graph: Graph, base_iri: str) -> None:
    """Write canonical Turtle to ``path`` as UTF-8 with LF line endings (rule 5).

    ``newline`` is not a detail: the platform default would translate every line ending
    on Windows and make the same graph produce different bytes on different machines.
    """
    path.write_text(serialize(graph, base_iri), encoding="utf-8", newline="\n")


def _check_base_iri(base_iri: str) -> None:
    if not base_iri.startswith(("http://", "https://")):
        raise ValueError(f"base IRI must be an http(s) IRI, got {base_iri!r}")
    if not base_iri.endswith("/"):
        # Every per-instance namespace is the base plus a suffix (spec 3.1); without the
        # separator the two would run together into a different namespace entirely.
        raise ValueError(f"base IRI must end with '/', got {base_iri!r}")


def _rejected(node: Node, position: str) -> ValueError:
    """Explain why a node cannot be written, before anything is written.

    Blank-node labels are not stable across runs, so a single one would make the
    determinism check fail somewhere far from its cause (rule 7). Whatever seems to need
    one needs a minted IRI instead (spec 3.4).
    """
    if isinstance(node, BNode):
        return ValueError(
            f"generated output may contain no blank nodes (spec 5.5 rule 7): "
            f"{node.n3()} in {position} position"
        )
    return ValueError(f"cannot serialize {node.n3()} in {position} position")


def _checked_iri(node: Node, position: str) -> URIRef:
    if isinstance(node, URIRef):
        return node
    raise _rejected(node, position)


def _checked_object(node: Node) -> URIRef | Literal:
    if isinstance(node, URIRef | Literal):
        return node
    raise _rejected(node, "object")


def _blocks(graph: Graph, prefixes: Mapping[str, str]) -> Iterator[str]:
    """Yield one Turtle block per subject, subjects sorted by IRI (rule 2)."""
    by_subject: dict[URIRef, list[tuple[URIRef, URIRef | Literal]]] = {}
    for subject, predicate, object_ in graph:
        by_subject.setdefault(_checked_iri(subject, "subject"), []).append(
            (_checked_iri(predicate, "predicate"), _checked_object(object_))
        )

    for subject in sorted(by_subject, key=str):
        statements = [
            f"{_predicate(predicate, prefixes)} {_term(object_, prefixes)}"
            for predicate, object_ in sorted(
                by_subject[subject], key=lambda pair: _statement_key(*pair)
            )
        ]
        head = f"{_iri(subject, prefixes)} {statements[0]}"
        rest = [_INDENT + statement for statement in statements[1:]]
        yield " ;\n".join([head, *rest]) + " ."


def _statement_key(
    predicate: URIRef, object_: URIRef | Literal
) -> tuple[int, str, tuple[int, str, str, str]]:
    """Order within a subject block (rule 3).

    One triple per line means a predicate with several objects repeats the predicate, so
    the objects have to be ordered too — otherwise insertion order would leak into the
    file and two runs could disagree.
    """
    rank = _PREDICATE_RANK.get(predicate, _TAIL_RANK)
    return (rank, str(predicate), _object_key(object_))


def _object_key(object_: URIRef | Literal) -> tuple[int, str, str, str]:
    """A total order over objects: IRIs first, then literals by value, tag, datatype.

    "Sorted lexicographically" (rule 3) settles IRIs but not a mix of IRIs and typed or
    tagged literals, and an undefined comparison there is exactly the kind of thing that
    stays stable for a year and then reorders a file for no reason.
    """
    if isinstance(object_, URIRef):
        return (0, str(object_), "", "")
    return (1, str(object_), object_.language or "", str(object_.datatype or ""))


def _predicate(predicate: URIRef, prefixes: Mapping[str, str]) -> str:
    return "a" if predicate == RDF.type else _iri(predicate, prefixes)


def _term(node: URIRef | Literal, prefixes: Mapping[str, str]) -> str:
    if isinstance(node, URIRef):
        return _iri(node, prefixes)
    return _literal(node, prefixes)


def _iri(node: URIRef, prefixes: Mapping[str, str]) -> str:
    """Write an IRI prefixed where the prefix block allows it, else in full."""
    iri = str(node)
    best: tuple[str, str] | None = None
    for prefix, namespace in prefixes.items():
        if not iri.startswith(namespace):
            continue
        if not _SAFE_LOCAL_NAME.fullmatch(iri[len(namespace) :]):
            continue
        # Longest namespace wins, so a nested namespace never loses to its parent and
        # the choice does not depend on the block's order.
        if best is None or len(namespace) > len(prefixes[best[0]]):
            best = (prefix, iri[len(namespace) :])

    return f"{best[0]}:{best[1]}" if best is not None else f"<{iri}>"


def _literal(node: Literal, prefixes: Mapping[str, str]) -> str:
    text = f'"{_escape(str(node))}"'
    if node.language:
        return f"{text}@{node.language}"
    if node.datatype is not None and node.datatype != _XSD_STRING:
        return f"{text}^^{_iri(node.datatype, prefixes)}"
    # A plain literal and an xsd:string literal are the same RDF term; writing both the
    # short way keeps two equal graphs from producing two different files.
    return text


def _escape(text: str) -> str:
    """Escape a literal for a single-line quoted string.

    Newlines are escaped rather than written as a triple-quoted literal: rule 4's one
    triple per line is what makes a diff readable, and a multi-line literal would break
    it for every triple that follows.
    """
    escaped = []
    for character in text:
        if character in _ESCAPES:
            escaped.append(_ESCAPES[character])
        elif character < " " or character == "\x7f":
            escaped.append(f"\\u{ord(character):04X}")
        else:
            escaped.append(character)
    return "".join(escaped)

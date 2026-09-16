"""Canonical Turtle serialization (spec 5.5). ``rdflib``'s own Turtle output is not deterministic,
so nothing an instance commits uses it. The same graph serializes to the same bytes on any
platform in any insertion order, one triple per line. A change to anything here is a major
version bump with a migration (spec 7).
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
    "is_safe_local_name",
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

# Namespaces derived from the instance's base IRI (spec 3.1). Part of the identity
# contract: changing a suffix would re-mint every IRI under it.
_INSTANCE_SUFFIXES = {
    "c": "concepts/",
    "r": "relationships/",
    "sch": "schemes/",
    "v": "values/",
    "x": "ext#",
    "a": "assets/",
    "d": "docs/",
}

# Spec 5.5 rule 1: a fixed block in spec 3.1's order, emitted whether or not a file uses it.
CANONICAL_PREFIXES = ("sem", "c", "r", "sch", "v", "x", "skos", "dcterms", "xsd", "a", "d")

_INDENT = "  "

# Local names that can follow a prefix without escaping. Narrower than Turtle's PN_LOCAL;
# anything unusual is written as a full <IRI> instead.
_SAFE_LOCAL_NAME = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_.\-]*[A-Za-z0-9_\-])?")

# Characters Turtle's IRIREF production forbids. rdflib does not validate a URIRef on
# construction, so one can reach here.
_UNSAFE_IRI_CHARACTER = re.compile(r"[\x00-\x20<>\"{}|^`\\]")

_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}

# Predicates with a fixed position ahead of the lexicographic tail (rule 3).
_PREDICATE_RANK = {RDF.type: 0, SKOS.prefLabel: 1}
_TAIL_RANK = max(_PREDICATE_RANK.values()) + 1


def namespaces(base_iri: str) -> Mapping[str, str]:
    """The prefix block for ``base_iri``, in canonical order (spec 3.1, 5.5).

    The one definition of the per-kind namespaces; identity (spec 3.4) mints into them.
    Raises ``ValueError`` for a base IRI that is not a usable namespace root.
    """
    _check_base_iri(base_iri)
    resolved = {**_FIXED_NAMESPACES, **{p: base_iri + s for p, s in _INSTANCE_SUFFIXES.items()}}
    return {prefix: resolved[prefix] for prefix in CANONICAL_PREFIXES}


def is_safe_local_name(name: str) -> bool:
    """Whether ``name`` can follow a prefix without escaping. Identity (spec 3.4) refuses to mint
    anything else.
    """
    return _SAFE_LOCAL_NAME.fullmatch(name) is not None


def serialize(graph: Graph, base_iri: str) -> str:
    """Serialize ``graph`` as canonical Turtle (spec 5.5).

    Raises ``ValueError`` for a graph the rules cannot express: a blank node (rule 7), a
    literal or blank node in subject position, or a base IRI that is not a usable
    namespace root.
    """
    prefixes = namespaces(base_iri)
    lines = [f"@prefix {prefix}: <{namespace}> ." for prefix, namespace in prefixes.items()]
    for block in _blocks(graph, prefixes):
        lines.append("")
        lines.append(block)

    return "\n".join(lines) + "\n"


def write(path: Path, graph: Graph, base_iri: str) -> None:
    """Write canonical Turtle to ``path`` as UTF-8 with LF line endings (rule 5)."""
    path.write_text(serialize(graph, base_iri), encoding="utf-8", newline="\n")


def _check_base_iri(base_iri: str) -> None:
    if not base_iri.startswith(("http://", "https://")):
        raise ValueError(f"base IRI must be an http(s) IRI, got {base_iri!r}")
    if not base_iri.endswith("/"):
        raise ValueError(f"base IRI must end with '/', got {base_iri!r}")
    unsafe = _UNSAFE_IRI_CHARACTER.search(base_iri)
    if unsafe is not None:
        # A namespace is written unescaped in the prefix block, so it is refused, not repaired.
        raise ValueError(
            f"base IRI may not contain {unsafe.group()!r}, which Turtle forbids in an IRI: "
            f"{base_iri!r}"
        )


def _rejected(node: Node, position: str) -> ValueError:
    """The error for a node that cannot be written: a blank node (rule 7) or a literal subject."""
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
    by_subject: dict[URIRef, set[tuple[URIRef, URIRef | Literal]]] = {}
    for subject, predicate, object_ in graph:
        by_subject.setdefault(_checked_iri(subject, "subject"), set()).add(
            (_checked_iri(predicate, "predicate"), _plain(_checked_object(object_)))
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


def _plain(object_: URIRef | Literal) -> URIRef | Literal:
    """Collapse an ``xsd:string`` literal onto the plain literal it equals.

    ``rdflib`` keeps the two as separate triples; both write as ``"value"``, and the block
    would otherwise carry one statement twice.
    """
    if isinstance(object_, Literal) and not object_.language and object_.datatype == _XSD_STRING:
        return Literal(str(object_))
    return object_


def _statement_key(
    predicate: URIRef, object_: URIRef | Literal
) -> tuple[int, str, tuple[int, str, str, str]]:
    """Order within a subject block (rule 3): ranked predicates, then predicate, then object."""
    rank = _PREDICATE_RANK.get(predicate, _TAIL_RANK)
    return (rank, str(predicate), _object_key(object_))


def _object_key(object_: URIRef | Literal) -> tuple[int, str, str, str]:
    """A total order over objects: IRIs first, then literals by value, tag, datatype."""
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
        if not is_safe_local_name(iri[len(namespace) :]):
            continue
        # Longest namespace wins, independent of the block's order.
        if best is None or len(namespace) > len(prefixes[best[0]]):
            best = (prefix, iri[len(namespace) :])

    if best is not None:
        return f"{best[0]}:{best[1]}"
    # Escaped rather than refused: lossless, and the file still parses.
    return f"<{_UNSAFE_IRI_CHARACTER.sub(_as_uchar, iri)}>"


def _literal(node: Literal, prefixes: Mapping[str, str]) -> str:
    text = f'"{_escape(str(node))}"'
    if node.language:
        return f"{text}@{node.language}"
    if node.datatype is not None:
        return f"{text}^^{_iri(node.datatype, prefixes)}"
    # An xsd:string literal arrives already collapsed by _plain().
    return text


def _escape(text: str) -> str:
    """Escape a literal for a single-line quoted string (rule 4)."""
    escaped = []
    for character in text:
        if character in _ESCAPES:
            escaped.append(_ESCAPES[character])
        elif character < " " or character == "\x7f":
            escaped.append(_as_uchar(character))
        else:
            escaped.append(character)
    return "".join(escaped)


def _as_uchar(character: str | re.Match[str]) -> str:
    """Write one character as Turtle's ``\\uXXXX`` escape, valid in an IRI or a string."""
    text = character if isinstance(character, str) else character.group()
    return f"\\u{ord(text):04X}"

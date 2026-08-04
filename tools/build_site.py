"""Builds the project's GitHub Pages site — the hosting behind the w3id namespace (A2).

`https://w3id.org/semprini/ontology#Entity` is a permanent identifier: w3id stores no
content, it only redirects to the site this script produces. The five paths it emits are
exactly the five the drafted `.htaccess` redirects to, so this file and that one change
together or the namespace breaks.

Everything is derived from `src/semprini/ontology/sem.ttl` — the Turtle is copied byte
for byte and the documentation is generated from the same graph. Nothing about the
vocabulary is restated here, because a second copy of an ontology drifts from the first.

Not part of the shipped package: instances never build this site. Spec 6.3's "no logic
in workflow YAML" governs the templates an adopter ports to another CI system, not this
repository's own site build — which is precisely why the logic lives here in Python
rather than in `pages.yml`.

Usage: ``python tools/build_site.py [output-directory]`` (default ``_site``).
"""

from __future__ import annotations

import html
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import RDF, RDFS

from semprini import ONTOLOGY_PATH, ontology_version

ONTOLOGY_IRI = "https://w3id.org/semprini/ontology"
SEM = f"{ONTOLOGY_IRI}#"
REPO_URL = "https://github.com/JuhaKor/semprini"

# Rendering only. The ontology declares no prefixes of its own beyond these, and an IRI
# with no entry here is shown in full rather than guessed at.
PREFIXES = {
    SEM: "sem:",
    "http://www.w3.org/2004/02/skos/core#": "skos:",
    "http://www.w3.org/2001/XMLSchema#": "xsd:",
    "http://www.w3.org/2000/01/rdf-schema#": "rdfs:",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf:",
    "http://purl.org/dc/terms/": "dcterms:",
}

STYLE = """
:root { color-scheme: light dark; --fg: #16181d; --bg: #fff; --muted: #5c6370;
        --line: #d8dce3; --accent: #1a4fa0; --code-bg: #f4f5f7; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #e6e8ec; --bg: #14161a; --muted: #9aa1ad; --line: #2c313a;
          --accent: #8ab4f8; --code-bg: #1d2026; }
}
* { box-sizing: border-box; }
body { margin: 0 auto; max-width: 52rem; padding: 2.5rem 1.25rem 5rem;
       background: var(--bg); color: var(--fg); line-height: 1.6;
       font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
h1 { font-size: 1.9rem; line-height: 1.25; margin: 0 0 .35rem; }
h2 { font-size: 1.25rem; margin: 2.75rem 0 .75rem; padding-bottom: .35rem;
     border-bottom: 1px solid var(--line); }
h3 { font-size: 1rem; margin: 2rem 0 .4rem; font-family: ui-monospace, SFMono-Regular,
     Consolas, monospace; scroll-margin-top: 1rem; }
a { color: var(--accent); }
p, li { max-width: 46rem; }
.lede { color: var(--muted); font-size: 1.05rem; margin: 0 0 1.5rem; }
.banner { border: 1px solid var(--line); border-left: 3px solid var(--accent);
          padding: .8rem 1rem; margin: 1.5rem 0; font-size: .93rem; }
code, .iri { font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
             font-size: .88em; background: var(--code-bg); padding: .12em .35em;
             border-radius: 3px; word-break: break-all; }
dl.facts { display: grid; grid-template-columns: max-content 1fr; gap: .15rem .9rem;
           margin: .5rem 0 0; font-size: .9rem; }
dt { color: var(--muted); }
dd { margin: 0; }
.term { border-bottom: 1px solid var(--line); padding-bottom: 1.25rem; }
.term p { margin: .35rem 0 0; }
footer { margin-top: 4rem; padding-top: 1rem; border-top: 1px solid var(--line);
         color: var(--muted); font-size: .87rem; }
"""


@dataclass(frozen=True)
class Term:
    """One `sem:` class or property, as the documentation page shows it."""

    name: str
    label: str
    comment: str
    facts: tuple[tuple[str, str], ...]


def curie(node: object) -> str:
    text = str(node)
    for namespace, prefix in PREFIXES.items():
        if text.startswith(namespace):
            return prefix + text.removeprefix(namespace)
    return text


def _facts(
    graph: Graph, term: URIRef, predicates: dict[str, URIRef]
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (caption, ", ".join(sorted(curie(o) for o in graph.objects(term, predicate))))
        for caption, predicate in predicates.items()
        if (term, predicate, None) in graph
    )


def _terms(graph: Graph, rdf_type: URIRef, predicates: dict[str, URIRef]) -> list[Term]:
    # Alphabetical, not the order of the spec's tables: the graph carries no order, and
    # hard-coding one here would be a third transcription of those tables to keep in
    # step with the ontology and the inventory test.
    terms = []
    for subject in sorted(graph.subjects(RDF.type, rdf_type), key=str):
        if not str(subject).startswith(SEM):
            continue
        terms.append(
            Term(
                name=str(subject).removeprefix(SEM),
                label=str(graph.value(subject, RDFS.label)),
                # The line breaks in sem.ttl are source formatting, not content: keeping
                # them would wrap the prose at the Turtle file's width on every screen.
                comment=" ".join(str(graph.value(subject, RDFS.comment)).split()),
                facts=_facts(graph, URIRef(str(subject)), predicates),
            )
        )
    return terms


def render_terms(terms: list[Term]) -> str:
    blocks = []
    for term in terms:
        facts = "".join(
            f'<dt>{html.escape(caption)}</dt><dd><span class="iri">{html.escape(value)}</span></dd>'
            for caption, value in term.facts
        )
        blocks.append(
            # The id is the IRI's fragment, so a browser following sem:Entity through
            # w3id lands on this term rather than the top of the page.
            '<div class="term">\n'
            f'<h3 id="{html.escape(term.name)}">sem:{html.escape(term.name)}</h3>\n'
            f"<p><strong>{html.escape(term.label)}</strong></p>\n"
            f"<p>{html.escape(term.comment)}</p>\n"
            + (f'<dl class="facts">{facts}</dl>\n' if facts else "")
            + "</div>"
        )
    return "\n".join(blocks)


def page(title: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n"
        f"{body}\n"
        "<footer>\n"
        "<p>Semprini is © Datakor Consulting Oy. The compiler is licensed "
        f'<a href="{REPO_URL}/blob/main/LICENSE">Apache-2.0</a>; the metamodel ontology, '
        "the core SHACL shapes and the specification are licensed "
        f'<a href="{REPO_URL}/blob/main/LICENSE-DOCS">CC BY 4.0</a>.</p>\n'
        f'<p><a href="{REPO_URL}">Source repository</a></p>\n'
        "</footer>\n</body>\n</html>\n"
    )


def home_page(version: str) -> str:
    return page(
        "Semprini",
        "<h1>Semprini</h1>\n"
        '<p class="lede">A compiler that turns the business models and taxonomies an '
        "organization already maintains into a governed RDF knowledge graph, reviewed "
        "as ordinary pull requests.</p>\n"
        "<p>Every deployment binds to one shared metamodel, the <code>sem:</code> "
        "vocabulary, so an agent, query or SHACL shape written against it works against "
        "any instance. Content each organization owns lives in namespaces that "
        "organization chooses.</p>\n"
        "<h2>The metamodel</h2>\n"
        f'<p><a href="ontology/">Vocabulary documentation</a> — version {html.escape(version)}, '
        'or the <a href="ontology/sem.ttl">Turtle document</a> directly.</p>\n'
        f'<p>The namespace is <span class="iri">{ONTOLOGY_IRI}#</span>, served through '
        "w3id.org so that resolution depends on no single organization's domain.</p>\n"
        "<h2>The project</h2>\n"
        f'<p>The <a href="{REPO_URL}">source repository</a> holds the compiler, the '
        f'ontology and the <a href="{REPO_URL}/blob/main/docs/rdf-repo-and-compiler-spec.md">'
        "implementation specification</a>.</p>",
    )


def ontology_page(graph: Graph, version: str, *, frozen: bool) -> str:
    classes = _terms(graph, RDFS.Class, {"Subclass of": RDFS.subClassOf})
    properties = _terms(graph, RDF.Property, {"Domain": RDFS.domain, "Range": RDFS.range})

    if frozen:
        banner = (
            f'<div class="banner">This is version <strong>{html.escape(version)}</strong>, '
            "frozen at its release. The "
            f'<a href="{ONTOLOGY_IRI}">current version</a> may differ.</div>'
        )
    else:
        banner = (
            '<div class="banner">This page documents the current version, '
            f"<strong>{html.escape(version)}</strong>, which is also available "
            f'<a href="{version}/">at its own permanent path</a>.</div>'
        )

    return page(
        f"Semprini metamodel {version}",
        f"<h1>Semprini metamodel</h1>\n"
        f'<p class="lede">The shared <code>sem:</code> vocabulary — {len(classes)} classes '
        f"and {len(properties)} properties, identical in every deployment.</p>\n"
        f"{banner}\n"
        f'<dl class="facts">\n'
        f'<dt>Namespace</dt><dd><span class="iri">{ONTOLOGY_IRI}#</span></dd>\n'
        f"<dt>Version</dt><dd>{html.escape(version)}</dd>\n"
        f'<dt>Document</dt><dd><a href="sem.ttl">sem.ttl</a> (Turtle)</dd>\n'
        f"</dl>\n"
        "<p>Terms are SKOS-based and typed in RDFS. Constraints on instance data are "
        "stated once, as SHACL shapes shipped with the compiler, rather than restated "
        "here as OWL axioms.</p>\n"
        f"<h2>Classes</h2>\n{render_terms(classes)}\n"
        f"<h2>Properties</h2>\n{render_terms(properties)}",
    )


def build(output: Path) -> list[Path]:
    version = ontology_version()
    graph = Graph()
    graph.parse(ONTOLOGY_PATH, format="turtle")

    if output.exists():
        shutil.rmtree(output)
    ontology_dir = output / "ontology"
    frozen_dir = ontology_dir / version
    frozen_dir.mkdir(parents=True)

    written = []
    for path, text in (
        (output / "index.html", home_page(version)),
        (ontology_dir / "index.html", ontology_page(graph, version, frozen=False)),
        (frozen_dir / "index.html", ontology_page(graph, version, frozen=True)),
    ):
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)

    # Copied, never re-serialized: the bytes an instance pins must be the bytes the
    # namespace resolves to.
    for path in (ontology_dir / "sem.ttl", frozen_dir / "sem.ttl"):
        shutil.copyfile(ONTOLOGY_PATH, path)
        written.append(path)

    return written


def main(argv: list[str]) -> int:
    output = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / "_site"
    for path in build(output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

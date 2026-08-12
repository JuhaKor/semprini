# Core SHACL shapes

The constraints of spec §6.1.5, shipped with the compiler and applied to every instance by
`semprini check`. `core.ttl` holds them all today; every `.ttl` in this directory is
loaded, so splitting the file later changes nothing.

Their own IRIs are in `https://w3id.org/semprini/shapes#` — never in `sem:`, which
resolves to the metamodel document and whose term inventory is fixed by §3.2/§3.3.

**They need SHACL advanced features.** A taxonomy value is a plain `skos:Concept` in this
metamodel, so it is selected by a SPARQL target rather than by `sh:targetClass` — the
class-based form would silently start matching entities the moment a validator ran with
`sem.ttl` loaded or an RDFS reasoner switched on, since every `sem:` class is a
`skos:Concept`. `semprini check` passes `advanced=True`; a validator run without it
reports *fewer* violations rather than failing, so run them through the CLI.

Three graphs, judged separately (§6.1.5): the core shapes here apply to `generated/`
alone, which is what the compiler guarantees; `overlays/` is judged only on what it may
not restate about a generated node, because it legitimately holds curated subsets of
external vocabularies; and an instance's own `shapes/local/` sees both together.

Licensed CC BY 4.0 (`LICENSE-DOCS`), not Apache-2.0 — shapes are vocabulary, like the
`sem:` ontology, so adopters can quote and extend them. An instance adds its own rules in
`shapes/local/`, which may only be **additive**: local shapes never weaken a core
constraint and never redefine a `sem:` term (§3.6, §6.1.5).

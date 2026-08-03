# Core SHACL shapes

The constraints of spec §6.1.5, shipped with the compiler and applied to every instance.
Written in task F1; this directory is a placeholder until then.

Licensed CC BY 4.0 (`LICENSE-DOCS`), not Apache-2.0 — shapes are vocabulary, like the
`sem:` ontology, so adopters can quote and extend them. An instance adds its own rules in
`shapes/local/`, which may only be **additive**: local shapes never weaken a core
constraint and never redefine a `sem:` term (§3.6, §6.1.5).

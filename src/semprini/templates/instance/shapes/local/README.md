# Local shapes

SHACL this organization adds on top of the rules the compiler already enforces. Every
`.ttl` file here is read by `semprini check` and applied to `generated/` and `overlays/`
together. An empty directory is a legal empty rule set — delete nothing to switch it off.

Use it for the rules only %%org%% can state: that every concept in a particular scheme
carries a definition, that a code matches a pattern you own, that a relationship type is
one of a fixed few.

## Additive only, and what that means

A file here can add constraints. It cannot take any away, and it may not reach back into
what the plane defines and appear to change it. Four things are **refused**, with the file
and the term named (spec 6.1.5):

1. **A statement about a term the plane owns** — any subject in `https://w3id.org/semprini/ontology#`
   or `https://w3id.org/semprini/shapes#`. This is what catches the core shapes copied into
   this directory and edited, which is the natural thing to try. It also catches
   `sem:Entity a sh:NodeShape`, which SHACL reads as an implicit class target and which
   would turn a metamodel class into a shape of yours.
2. **A constraint that constrains nothing** — `sh:minCount 0`, `sh:uniqueLang false`,
   `sh:closed false`. Each is a no-op in SHACL and each is exactly what "make the core rule
   optional" looks like written down, so none of them blocks a rule anyone meant.
3. **`sh:rule`**, which derives triples into the graph being validated. It cannot weaken
   the core check, but it lets your own rules pass against statements no file here holds.
4. **A reference to a core shape**, in any position.

A refused file's rules are not applied; every other file's still are. So one mistake in one
file does not switch off the organization's rules, and a verdict never rests on a file the
plane said it would not honour.

**Targeting a `sem:` class is legal and expected** — `sh:targetClass sem:Entity` is how a
local rule says what it is about. What is refused is writing *statements about* those
terms.

## Writing one

```turtle
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix sem:  <https://w3id.org/semprini/ontology#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

<%%base_iri%%shapes/DefinedEntity>
    a sh:NodeShape ;
    sh:targetClass sem:Entity ;
    sh:property [
        sh:path skos:definition ;
        sh:minCount 1 ;
        sh:severity sh:Warning ;
        sh:message "Every entity needs a definition." ;
    ] .
```

`sh:severity sh:Warning` reports without failing the check — the way to introduce a rule
the vocabulary does not satisfy yet. Drop it, and the rule blocks the pull request.

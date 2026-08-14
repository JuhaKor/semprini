# Overlays

The only hand-written RDF in this repository. Everything under `generated/` is the
compiler's and is overwritten on every run; anything a person wants to say goes here, and
is loaded alongside the generated files by every consumer and every check.

| Directory | For |
|---|---|
| `external/` | curated subsets of standard vocabularies this organization reuses |
| `ext/` | %%org%%'s own terms, in its `x:` namespace |
| `patches/` | statements the sources cannot express — an alignment, an extra axiom |

Three rules.

**Never redefine a `sem:` term.** The metamodel is shared by every Semprini instance in
existence, and a local redefinition would mean an instance's RDF says something different
from what its vocabulary claims. Organization-specific terms are minted in the `x:`
namespace, `%%base_iri%%ext#`, and are yours alone.

**Never restate what the compiler generates.** An overlay that repeats a label already in
`generated/` makes one changed fact two changed places, and the second one will not follow
when the source changes.

**Keep it reviewable.** These files are read by people, so they may be commented and
grouped however is clearest — the byte-for-byte determinism rules apply to `generated/`
and not here.

# Released ontology versions

One directory per **released** version of the `sem:` metamodel, each holding the
`sem.ttl` exactly as that release shipped it.

## Why this exists

`https://w3id.org/semprini/ontology/0.1.0/` is a permanent identifier. w3id.org stores no
content: it redirects to this project's GitHub Pages site, and `tools/build_site.py` is
what puts a document at that path. The site build used to derive every page from
`src/semprini/ontology/sem.ttl` alone, so publishing a new ontology version would have
deleted the previous version's path — a URL this project promises resolves for ever, and
which people outside it may already have written into a query or a pinned dependency.

These copies are what the versioned paths are built from, so a released version goes on
resolving after the working tree has moved on.

## The rules

**A directory here is frozen the moment it is published.** Editing one changes a document
somebody may have already fetched and compared against. If a term needs to change, the
change goes in `src/semprini/ontology/sem.ttl` under a **new** version (spec §7).

**The current version's copy must be byte-identical to the shipped ontology.** That is
asserted in `tests/test_release.py`, and it is the whole point of the archive: once
`0.1.0/sem.ttl` is here, editing `src/semprini/ontology/sem.ttl` fails the suite until
`owl:versionInfo` is bumped. You cannot change a released ontology without releasing a new
version of it, because the check is mechanical rather than a rule anyone has to remember.

**A version is added by the release that publishes it**, not by the change that writes the
terms. `python tools/release_check.py <tag>` refuses a release whose ontology version is
not archived — see *Cutting a release* in `CONTRIBUTING.md`.

Nothing here ships in the wheel. Instances read the ontology from the installed package;
these copies exist only so that the site can publish every version it has ever published.

# `semprini-dummy-adapter` — a third-party adapter, for the plane's own tests

A complete, separately *installed* distribution that contributes one adapter to the
`semprini.adapters` entry-point group. It exists to prove mechanically what spec §5.2
promises in prose: a source system is added by installing a package, and the compiler
finds it without knowing its name.

## Why it is committed rather than built

The directory is a distribution as it looks **after** installation — the importable
package beside its `.dist-info` metadata — so a test makes it discoverable by putting
this directory on `sys.path` and nothing else. `importlib.metadata` then finds it by the
same scan that finds every pip-installed package, so discovery is exercised for real
rather than monkeypatched.

Building and `pip install`ing it per test run would exercise pip, need a build backend
and a writable environment, and take seconds rather than microseconds — and would test
the same one line of `importlib.metadata`. Nothing here is imported by the compiler or
named in it; `entry_points.txt` is the only thing that connects the two.

## What it is a worked example of

`semprini_dummy_adapter/__init__.py` is the shape a real adapter takes: a `fetch()` that
reads and returns, a `validate_config()` that reports rather than raises, a `summary()`
line for the run report, and a source failure raised as `SourceUnreachableError` so CI
sees exit 3 rather than a compile error. It passes `semprini.testing.check_contract` in
`tests/test_adapter_contract.py`, which is the same call an adapter author writes.

Its source system is one JSON document:

```json
{
  "scheme": { "slug": "dummy", "label": "Dummy glossary" },
  "entities": [{ "key": "e1", "label": "Customer", "definition": "Someone who buys." }]
}
```

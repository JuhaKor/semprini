"""This repository's own tooling: site build, fixture regeneration.

A package rather than loose scripts so that the test suite can import what it verifies —
`build_fixture_instance` both regenerates the committed fixture instance and is what the
suite recompiles it with, and those must be the same code.
"""

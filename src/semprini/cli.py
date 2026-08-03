"""The whole CLI surface (spec 5.1).

Every check and every side effect lives here rather than in workflow YAML (spec 6.3),
so an adopter on another CI platform ports a config file instead of reimplementing
logic, and ``semprini check`` behaves identically on a laptop and in CI.

Exit codes are part of the published contract — see :class:`ExitCode`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from enum import IntEnum

from semprini import compiler_version, ontology_version

__all__ = ["ExitCode", "build_parser", "main"]

_PROGRAM = "semprini"


class ExitCode(IntEnum):
    """Exit codes any CI system can act on (spec 5.1)."""

    OK = 0
    FAILURE = 1
    """Validation or compile failure."""

    CONFIG = 2
    """Configuration or namespace-lock error. argparse also exits 2 on bad arguments."""

    UNREACHABLE = 3
    """A configured source was unreachable."""


# Subcommands whose implementation lands in a later task. Listed with the task that
# fills each one so that a stub is never mistaken for a missing feature.
_UNIMPLEMENTED = {
    "init": "task G1",
    "run": "task E2",
    "check": "task F2",
    "migrate": "task G3",
    "adapters": "task D1",
}


def build_parser() -> argparse.ArgumentParser:
    """Build the full argument parser of spec 5.1.

    The complete surface is declared now, stubs included, so that ``--help`` documents
    the contract and later tasks add behaviour rather than syntax.
    """
    parser = argparse.ArgumentParser(
        prog=_PROGRAM,
        description=(
            "Compile modelled business vocabularies into a governed RDF knowledge graph. "
            "Commands operate on the instance repository in the working directory."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", metavar="<command>")

    init = subcommands.add_parser("init", help="bootstrap an instance repository")
    init.add_argument("--base-iri", required=True, metavar="<IRI>")
    init.add_argument("--org", required=True, metavar="<slug>")
    init.add_argument("--dir", metavar="<path>")

    run = subcommands.add_parser("run", help="fetch, compile, write")
    run.add_argument("--source", metavar="<name>")
    run.add_argument("--dry-run", action="store_true")

    subcommands.add_parser("check", help="validate only, no writes")

    migrate = subcommands.add_parser("migrate", help="apply migrations")
    migrate.add_argument("--to", required=True, metavar="<version>")

    subcommands.add_parser("adapters", help="list discovered plugins")
    subcommands.add_parser("version", help="compiler + ontology versions")

    return parser


def _version() -> int:
    try:
        ontology = ontology_version()
    except (OSError, ValueError) as error:
        print(f"{_PROGRAM}: cannot read the bundled ontology: {error}", file=sys.stderr)
        return ExitCode.FAILURE

    print(f"compiler {compiler_version()}")
    print(f"ontology {ontology}")
    return ExitCode.OK


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``semprini`` console script."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command is None:
        # No command is a usage error, not a success: CI must be able to tell the
        # difference between "nothing to do" and "invoked wrongly".
        parser.print_help(sys.stderr)
        return ExitCode.CONFIG

    if arguments.command == "version":
        return _version()

    task = _UNIMPLEMENTED[arguments.command]
    print(
        f"{_PROGRAM}: '{arguments.command}' is not implemented in "
        f"{compiler_version()} (arrives in {task})",
        file=sys.stderr,
    )
    return ExitCode.FAILURE

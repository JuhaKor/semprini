"""The whole CLI surface (spec 5.1). All logic lives here, never in workflow YAML (spec 6.3).

Exit codes are part of the published contract; see :class:`ExitCode`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from enum import IntEnum
from pathlib import Path
from typing import TextIO

from semprini import (
    adapters,
    compiler_version,
    config,
    identity,
    migrate,
    ontology_version,
    run,
    scaffold,
    validate,
)
from semprini.adapters import AdapterError, AdapterLoadError, BaseAdapter, SourceUnreachableError
from semprini.model import IssueError

__all__ = ["ExitCode", "build_parser", "exit_code_for", "main"]

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


# Subcommands that read a configured instance and fail on a broken configuration first.
_NEEDS_CONFIG = frozenset({"run", "check", "migrate"})


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser of spec 5.1."""
    parser = argparse.ArgumentParser(
        prog=_PROGRAM,
        description=(
            "Compile modelled business vocabularies into a governed RDF knowledge graph. "
            "Commands operate on the instance repository in the working directory."
        ),
    )
    subcommands = parser.add_subparsers(dest="command", metavar="<command>")

    init = subcommands.add_parser("init", help="bootstrap an instance repository")
    init.add_argument(
        "--base-iri",
        required=True,
        metavar="<IRI>",
        help="the namespace root every IRI is minted under; frozen permanently (spec 3.4)",
    )
    init.add_argument(
        "--org",
        required=True,
        metavar="<slug>",
        help="this instance's id, frozen alongside the base IRI",
    )
    init.add_argument("--dir", metavar="<path>", help="where to create it; defaults to '.'")
    init.add_argument(
        "--language",
        default=config.DEFAULT_LANGUAGE,
        metavar="<tag>",
        help=(
            "the language applied to labels that arrive without one "
            f"(default {config.DEFAULT_LANGUAGE}); an ordinary setting, not frozen"
        ),
    )

    run = subcommands.add_parser("run", help="fetch, compile, write")
    run.add_argument("--dry-run", action="store_true")

    check = subcommands.add_parser("check", help="validate only, no writes")
    check.add_argument(
        "--base",
        metavar="<rev>",
        help=(
            "the git revision the ID map is compared against for the append-only check "
            "(spec 6.1 check 6); defaults to the pull request's base branch where CI "
            "names one, and the check reports itself not run when there is none"
        ),
    )

    migrate = subcommands.add_parser("migrate", help="apply migrations")
    migrate.add_argument(
        "--to",
        required=True,
        metavar="<version>",
        help=(
            "the compiler version being upgraded to, which must be the one installed "
            "(spec 7); a migration is performed by the release it upgrades to, so naming "
            "it catches a workflow that pinned one version and installed another"
        ),
    )

    subcommands.add_parser("adapters", help="list discovered plugins")
    subcommands.add_parser("version", help="compiler + ontology versions")

    return parser


def _say(text: str, *, stream: TextIO | None = None) -> None:
    """Print one line, replacing characters a console cannot encode rather than failing.

    Much of the output quotes labels nobody in this project wrote, and a redirected
    Windows stream still encodes as strict cp1252.
    """
    output = sys.stdout if stream is None else stream
    try:
        print(text, file=output)
    except UnicodeEncodeError:
        encoding = output.encoding or "ascii"
        print(text.encode(encoding, errors="replace").decode(encoding), file=output)


def _version() -> int:
    try:
        ontology = ontology_version()
    except (OSError, SyntaxError, ValueError) as error:
        # SyntaxError covers rdflib's BadSyntax on a corrupt sem.ttl.
        _say(f"{_PROGRAM}: cannot read the bundled ontology: {error}", stream=sys.stderr)
        return ExitCode.FAILURE

    _say(f"compiler {compiler_version()}")
    _say(f"ontology {ontology}")
    return ExitCode.OK


def _adapters() -> int:
    """List the installed adapter plugins (spec 5.1, 5.2).

    Reads no configuration. The one command that imports every discovered plugin, since
    whether an adapter is usable cannot be answered from metadata.
    """
    entries = adapters.discover()
    if not entries:
        _say("no adapters are installed")
        return ExitCode.OK

    rows: list[tuple[str, str, str]] = []
    broken: list[str] = []
    for entry in entries:
        try:
            loaded = entry.load()
        except AdapterError as error:
            broken.append(str(error))
            rows.append((entry.name, entry.provider, "-- not loadable, see below --"))
        else:
            rows.append((entry.name, entry.provider, _summary(loaded)))

    name_width = max(len(row[0]) for row in rows)
    provider_width = max(len(row[1]) for row in rows)
    for name, provider, summary in rows:
        _say(f"{name:<{name_width}}  {provider:<{provider_width}}  {summary}".rstrip())

    # A name two distributions claim is unusable even though both plugins import.
    broken.extend(adapters.ambiguities(entries))

    if broken:
        if len(broken) == 1:
            raise AdapterLoadError(broken[0])
        listed = "\n".join(f"  - {message}" for message in broken)
        raise AdapterLoadError(f"{len(broken)} installed adapters could not be loaded\n{listed}")
    return ExitCode.OK


def _summary(adapter: type[BaseAdapter]) -> str:
    """The first line of the adapter's own docstring; empty rather than inherited from
    ``BaseAdapter``.
    """
    lines = (adapter.__doc__ or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def _init(arguments: argparse.Namespace) -> int:
    """``semprini init`` — bootstrap an instance repository (spec 5.1, 5.7)."""
    result = scaffold.init(
        Path(arguments.dir) if arguments.dir else None,
        base_iri=arguments.base_iri,
        org=arguments.org,
        default_language=arguments.language,
    )
    for line in result.summary():
        _say(line)
    return ExitCode.OK


def _run(arguments: argparse.Namespace, settings: config.InstanceConfig) -> int:
    """``semprini run`` — fetch, compile, write (spec 5.1)."""
    result = run.run(settings, dry_run=arguments.dry_run)
    for line in result.summary():
        _say(line)
    return ExitCode.OK


def _check(arguments: argparse.Namespace, settings: config.InstanceConfig) -> int:
    """``semprini check`` — every check of spec 6.1, nothing written (spec 5.1). Warnings do not
    fail it.
    """
    result = validate.check(settings, base=arguments.base)
    for line in result.summary():
        _say(line)
    return ExitCode.OK if result.ok else ExitCode.FAILURE


def _migrate(arguments: argparse.Namespace, settings: config.InstanceConfig) -> int:
    """``semprini migrate`` — rewrite what is committed for a new release (spec 5.1, 7).

    Runs none of ``semprini check``'s checks; CI runs them on the resulting pull request.
    """
    result = migrate.migrate(settings, to=arguments.to)
    for line in result.summary():
        _say(line)
    return ExitCode.OK


def _load_config(arguments: argparse.Namespace) -> config.InstanceConfig:
    """Load the instance's configuration and verify its namespace lock (exit code 2, spec 5.1)."""
    installed = adapters.adapter_names()
    # None skips the adapter-name check: an installation with no adapters cannot judge one.
    loaded = config.load(known_adapters=installed or None)
    identity.verify_namespace_lock(loaded)
    return loaded


def exit_code_for(error: Exception) -> ExitCode:
    """The published exit code for an error (spec 5.1). Anything unrecognized is a failure."""
    if isinstance(error, config.ConfigError):
        return ExitCode.CONFIG
    if isinstance(error, SourceUnreachableError):
        return ExitCode.UNREACHABLE
    return ExitCode.FAILURE


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``semprini`` console script."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command is None:
        parser.print_help(sys.stderr)
        return ExitCode.CONFIG

    try:
        return _dispatch(arguments)
    except (IssueError, AdapterError) as error:
        _say(f"{_PROGRAM}: {error}", stream=sys.stderr)
        return exit_code_for(error)


def _dispatch(arguments: argparse.Namespace) -> int:
    if arguments.command == "version":
        return _version()

    if arguments.command == "adapters":
        return _adapters()

    if arguments.command == "init":
        return _init(arguments)

    if arguments.command in _NEEDS_CONFIG:
        settings = _load_config(arguments)
        if arguments.command == "run":
            return _run(arguments, settings)
        if arguments.command == "check":
            return _check(arguments, settings)
        if arguments.command == "migrate":
            return _migrate(arguments, settings)

    # argparse rejects undeclared subcommands, so only a forgotten dispatch reaches here.
    raise AssertionError(f"no dispatch for subcommand {arguments.command!r}")

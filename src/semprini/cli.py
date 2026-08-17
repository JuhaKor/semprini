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


# Subcommands that operate on a configured instance, and therefore fail on a broken
# configuration before doing anything else. `init` is excluded — it writes the
# configuration — and `adapters` and `version` describe the installation, not an
# instance.
_NEEDS_CONFIG = frozenset({"run", "check", "migrate"})


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
    run.add_argument("--source", metavar="<name>")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument(
        "--force-namespace-change",
        action="store_true",
        help=(
            "move the instance to a new base IRI, rewriting the ID map, the namespace "
            "lock and every generated file (spec 3.4); expected to be a once-ever event"
        ),
    )

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
    """Print one line, degrading rather than failing on a console that cannot spell it.

    Much of what ``semprini check`` prints is text nobody in this project wrote: a SHACL
    message quotes the node it is about, and a node's label is whatever a modeller typed
    into a workbook. On Windows a *redirected* stream still encodes as cp1252 with strict
    errors, and cp1252 holds Latin-1 plus a little punctuation and nothing else — so an
    arrow in a relationship's verb or any CJK label raises ``UnicodeEncodeError`` and
    turns a report about someone's instance into a traceback about ours. It lands on a
    *passing* check as readily as a failing one, since warnings are printed too.

    Replaced rather than avoided: keeping our own strings ASCII (which spec 5.6's report
    does) cannot help here, because the text is not all ours. A replaced character is a
    legible line with a ``?`` in it; the alternative is no output and exit 1.
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
        # SyntaxError covers rdflib's BadSyntax on a corrupt sem.ttl — a malformed
        # bundled document is a compile failure with a message, not a traceback.
        _say(f"{_PROGRAM}: cannot read the bundled ontology: {error}", stream=sys.stderr)
        return ExitCode.FAILURE

    _say(f"compiler {compiler_version()}")
    _say(f"ontology {ontology}")
    return ExitCode.OK


def _adapters() -> int:
    """List the installed adapter plugins (spec 5.1, 5.2).

    Describes the *installation*, not an instance, so it reads no configuration and
    works outside an instance repository. This is the one command that deliberately
    imports every discovered plugin: "is this adapter actually usable" is the question
    it exists to answer, and it cannot be answered from metadata alone.
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

    # A name two distributions claim is an installation that does not work, even though
    # every plugin in it imports: `adapter: <name>` cannot be resolved, so the run would
    # fail where the listing said everything was fine.
    broken.extend(adapters.ambiguities(entries))

    if broken:
        if len(broken) == 1:
            raise AdapterLoadError(broken[0])
        listed = "\n".join(f"  - {message}" for message in broken)
        raise AdapterLoadError(f"{len(broken)} installed adapters could not be loaded\n{listed}")
    return ExitCode.OK


def _summary(adapter: type[BaseAdapter]) -> str:
    """The adapter's one-line self-description — the first line of its own docstring.

    ``__doc__`` rather than ``inspect.getdoc``, which walks the MRO: an adapter that
    documents nothing would otherwise be listed as "One source system, normalized into
    the internal model", which is ``BaseAdapter``'s docstring and reads as the adapter
    describing itself. An empty column is honest; an inherited sentence is not.
    """
    lines = (adapter.__doc__ or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def _init(arguments: argparse.Namespace) -> int:
    """``semprini init`` — bootstrap an instance repository (spec 5.1, 5.7).

    The one command that writes an instance instead of reading one, so it is also the one
    that does not load configuration first: it creates the file every other command reads.
    """
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
    """``semprini run`` — fetch, compile, write (spec 5.1).

    Every decision belongs to :func:`semprini.run.run`; this reports what it did. The
    split is the one spec 6.3 requires between the compiler and the surface an operator
    sees, and it is why a run behaves identically on a laptop and in CI.
    """
    result = run.run(
        settings,
        only_source=arguments.source,
        dry_run=arguments.dry_run,
        force_namespace_change=arguments.force_namespace_change,
    )
    for line in result.summary():
        _say(line)
    return ExitCode.OK


def _check(arguments: argparse.Namespace, settings: config.InstanceConfig) -> int:
    """``semprini check`` — every check of spec 6.1, and nothing written (spec 5.1).

    The command CI runs on every pull request, so what it prints is what a reviewer reads:
    each check by number and name, its findings underneath, and one line saying whether
    the instance is committable. Warnings appear and do not fail it (spec 6.1.5).
    """
    result = validate.check(settings, base=arguments.base)
    for line in result.summary():
        _say(line)
    return ExitCode.OK if result.ok else ExitCode.FAILURE


def _migrate(arguments: argparse.Namespace, settings: config.InstanceConfig) -> int:
    """``semprini migrate`` — rewrite what is committed for a new release (spec 5.1, 7).

    Writes; the operator then reviews the diff and runs ``semprini check``, which is what
    says whether the migrated instance is committable. This command deliberately does not
    run those checks itself: they are ``semprini check``'s, CI already runs them on the
    resulting pull request, and a migration that reported them would be answering for its
    own work.
    """
    result = migrate.migrate(settings, to=arguments.to)
    for line in result.summary():
        _say(line)
    return ExitCode.OK


def _load_config(arguments: argparse.Namespace) -> config.InstanceConfig:
    """Load the instance's configuration and check its namespace lock (exit code 2).

    Raises rather than returning a code: :func:`main` maps every error to its exit code
    in one place, which is the CI contract (5.1). ``NamespaceLockError`` is a
    ``ConfigError``, so both land there as exit 2 — spec 5.1 makes them one category, and
    the lock is the one configured value an instance may not edit.
    """
    installed = adapters.adapter_names()
    # Passing `None` skips the adapter-name check. An installation with no adapters at
    # all cannot judge a name — checking against an empty set would reject every valid
    # configuration — and that is a real state only until the bundled adapters register
    # themselves (D2, D3). From then on every installation has some, and a misspelled
    # `adapter:` is exit 2 naming the key.
    loaded = config.load(known_adapters=installed or None)
    if arguments.command == "run":
        # Validates --source against the configured sources: a typo would otherwise
        # compile nothing and exit 0, which reads as success.
        loaded.run_context(only_source=arguments.source, dry_run=arguments.dry_run)
    if not getattr(arguments, "force_namespace_change", False):
        # The one invocation allowed to disagree with the lock — moving the base IRI
        # is what it is for (3.4). Every other run aborts on a mismatch rather than
        # minting a second set of IRIs beside the ID map's.
        identity.verify_namespace_lock(loaded)
    return loaded


def exit_code_for(error: Exception) -> ExitCode:
    """The published exit code for an error (spec 5.1).

    One place, because the codes are contract: an adopter's CI branches on them, and a
    command that invented its own mapping would make "3" mean something different
    depending on which subcommand produced it. Everything unrecognized is a failure
    rather than a configuration error, since exit 2 tells an operator to go and edit a
    file and being wrong about that costs them a search.
    """
    if isinstance(error, config.ConfigError):
        return ExitCode.CONFIG
    if isinstance(error, SourceUnreachableError):
        # The source was down, not wrong: a scheduled compile that hits this is retried,
        # and nothing about the instance needs a human (spec 5.2).
        return ExitCode.UNREACHABLE
    return ExitCode.FAILURE


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``semprini`` console script."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command is None:
        # No command is a usage error, not a success: CI must be able to tell the
        # difference between "nothing to do" and "invoked wrongly".
        parser.print_help(sys.stderr)
        return ExitCode.CONFIG

    try:
        return _dispatch(arguments)
    except (IssueError, AdapterError) as error:
        # Every error the compiler raises deliberately carries what an operator has to
        # know; a traceback would carry it too, plus forty lines of this package's
        # internals for them to read past.
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
        # A command that will read the instance owes the operator the configuration error
        # first, with the key that caused it.
        settings = _load_config(arguments)
        if arguments.command == "run":
            return _run(arguments, settings)
        if arguments.command == "check":
            return _check(arguments, settings)
        if arguments.command == "migrate":
            return _migrate(arguments, settings)

    # Unreachable: argparse rejects any subcommand not declared above, and every declared
    # one is dispatched. An assertion rather than a message about an unimplemented feature —
    # there are none left — so that adding a subcommand and forgetting to dispatch it fails
    # loudly instead of exiting non-zero with no explanation.
    raise AssertionError(f"no dispatch for subcommand {arguments.command!r}")

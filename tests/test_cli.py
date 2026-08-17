"""The CLI surface and exit-code contract of spec 5.1.

Exit codes are published contract, not implementation detail: an adopter's CI branches
on them, so each one is pinned by a test.
"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
from pathlib import Path

import pytest

from semprini import cli, compiler_version, ontology_version
from semprini.cli import ExitCode, main

SUBCOMMANDS = {"init", "run", "check", "migrate", "adapters", "version"}
"""Spec 5.1's whole CLI surface — and, since G3, with no stub left among them.

Subcommands stopped being stubs one task at a time: `adapters` in D1, `run` in E2, `check`
in F2, `init` in G1, `migrate` in G3. `cli._UNIMPLEMENTED` and the test that walked it are
gone with the last of them."""


def _subcommands(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("the parser declares no subcommands")


def test_version_reports_both_version_numbers(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == ExitCode.OK

    out = capsys.readouterr().out
    assert out == f"compiler {compiler_version()}\nontology {ontology_version()}\n"


def test_corrupt_ontology_reports_a_message_rather_than_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # rdflib raises BadSyntax, which subclasses SyntaxError rather than ValueError.
    # Exercised through the real parser so the caught type stays honest as A3 rewrites
    # the bundled document.
    corrupt = tmp_path / "sem.ttl"
    corrupt.write_text("this is not turtle {", encoding="utf-8")
    monkeypatch.setattr(cli, "ontology_version", lambda: ontology_version(corrupt))

    assert main(["version"]) == ExitCode.FAILURE

    captured = capsys.readouterr()
    assert "cannot read the bundled ontology" in captured.err
    assert captured.out == ""


def test_no_arguments_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    # Not exit 0: CI must distinguish "nothing to do" from "invoked wrongly".
    assert main([]) == ExitCode.CONFIG
    assert "usage:" in capsys.readouterr().err


def test_unknown_command_exits_2() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["compile"])
    assert raised.value.code == ExitCode.CONFIG


def test_missing_required_argument_exits_2() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["migrate"])  # --to is required
    assert raised.value.code == ExitCode.CONFIG


def test_the_declared_surface_is_the_one_the_spec_lists() -> None:
    # A seventh subcommand arriving without a spec edit is caught here, and so is a
    # subcommand quietly disappearing — an adopter's CI invokes these by name (spec 6.3).
    assert _subcommands(cli.build_parser()) == SUBCOMMANDS


@pytest.mark.parametrize("command", sorted(SUBCOMMANDS))
def test_no_subcommand_reports_itself_unimplemented(
    command: str, instance: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every subcommand does something. G3 was the last stub (spec 5.1).

    Invoked for real inside the fixture instance rather than inspected, because "not a stub"
    is a claim about what running it does. Each is given the arguments it requires and is
    asked only not to report itself absent; what each one *does* is its own task's tests.
    """
    required = {
        "init": ["--base-iri", "https://semantics.example.com/", "--org", "acme", "--dir", "new"],
        "migrate": ["--to", compiler_version()],
    }

    main([command, *required.get(command, [])])

    assert "not implemented" not in capsys.readouterr().err


def test_output_degrades_rather_than_failing_on_a_narrow_console() -> None:
    """A console that cannot encode a character must not turn output into a traceback.

    ``semprini check`` prints text nobody here wrote: SHACL messages quote the node they
    are about, and a node's label is whatever a modeller typed into a workbook. On Windows
    a *redirected* stream encodes as cp1252 with strict errors, and cp1252 holds Latin-1
    plus a handful of punctuation and nothing else — so an arrow in a relationship's verb,
    a Greek letter in a unit, or any CJK label raises ``UnicodeEncodeError`` and turns a
    report about someone's instance into a traceback about ours.

    Keeping our own strings ASCII, which the run report does, cannot help: the text is not
    all ours.
    """
    written: list[str] = []

    class NarrowConsole(io.StringIO):
        encoding = "cp1252"

        def write(self, text: str) -> int:
            text.encode(self.encoding)  # raises UnicodeEncodeError, as the real one does
            written.append(text)
            return len(text)

    cli._say("Order → Customer", stream=NarrowConsole())

    assert "".join(written).startswith("Order ? Customer")


def test_help_exits_0() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["--help"])
    assert raised.value.code == ExitCode.OK


CONSOLE_SCRIPT = shutil.which("semprini")


@pytest.mark.skipif(CONSOLE_SCRIPT is None, reason="package is not installed")
def test_console_script_is_installed() -> None:
    """The wheel must expose a working `semprini` entry point, not just an importable module."""
    # Invoke the resolved path rather than the bare name: on Windows the entry point is
    # semprini.exe, and PATH lookup differs between shutil.which and CreateProcess.
    assert CONSOLE_SCRIPT is not None
    completed = subprocess.run(
        [CONSOLE_SCRIPT, "version"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == ExitCode.OK
    assert completed.stdout.startswith("compiler ")

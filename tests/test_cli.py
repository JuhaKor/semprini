"""The CLI surface and exit-code contract of spec 5.1.

Exit codes are published contract, not implementation detail: an adopter's CI branches
on them, so each one is pinned by a test.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from semprini import compiler_version, ontology_version
from semprini.cli import ExitCode, main

# Stub subcommands, with the arguments each requires, until its own task lands.
STUB_INVOCATIONS = [
    ["init", "--base-iri", "https://semantics.example.com/", "--org", "example"],
    ["run"],
    ["run", "--source", "taxonomies", "--dry-run"],
    ["check"],
    ["migrate", "--to", "0.2.0"],
    ["adapters"],
]


def test_version_reports_both_version_numbers(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == ExitCode.OK

    out = capsys.readouterr().out
    assert out == f"compiler {compiler_version()}\nontology {ontology_version()}\n"


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


@pytest.mark.parametrize("argv", STUB_INVOCATIONS, ids=lambda argv: " ".join(argv))
def test_unimplemented_commands_exit_1(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    # Exit 1, not 2: the invocation is well formed, the feature is absent.
    assert main(argv) == ExitCode.FAILURE

    err = capsys.readouterr().err
    assert "not implemented" in err
    assert argv[0] in err


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

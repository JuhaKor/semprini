"""Adapter discovery and the ``semprini adapters`` command (spec 5.2, 5.1).

The claim under test is spec 1.2's: a source system is added by *installing a package*.
So the adapter these tests find is a real distribution laid out as pip would leave it
(``tests/fixtures/dummy-adapter/``), reached by putting it on ``sys.path`` and nothing
else. Nothing here patches a registry — a passing test would then prove only that the
patch worked.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import DUMMY_MODULE
from semprini import adapters, cli, config, identity
from semprini.adapters import AdapterEntry, AdapterError, AdapterLoadError, SourceUnreachableError
from semprini.adapters import discovery as discovery_module
from semprini.cli import ExitCode, exit_code_for, main
from semprini.model import InternalModel, Issue, RunContext, Severity

CONTEXT = RunContext(base_iri="https://semantics.example.com/", instance_id="acme")

UNINSTALLED = "no-such-adapter"
"""A name no distribution provides, for the tests about *not* finding one.

Deliberately fictional. These tests used to name ``ellie``, which stopped being an
uninstalled adapter the moment D3 registered its entry point — and a test whose premise
quietly becomes false does not fail loudly, it stops testing what it says it does."""


def dummy_entry() -> AdapterEntry:
    """The one entry the dummy distribution contributes."""
    (entry,) = (item for item in adapters.discover() if item.name == "dummy")
    return entry


# ------------------------------------------------------------------ discovery


def test_an_adapter_is_found_only_because_its_distribution_is_installed(
    installed_dummy_adapter: Path,
) -> None:
    # The whole plugin promise in one assertion: nothing in semprini names this adapter,
    # and it is discovered anyway.
    assert "dummy" in adapters.adapter_names()


def test_nothing_is_discovered_without_it() -> None:
    # The paired half: without the distribution on the path the name is unknown, so the
    # test above cannot be passing for some other reason.
    assert "dummy" not in adapters.adapter_names()


def test_an_entry_names_the_distribution_that_provides_it(installed_dummy_adapter: Path) -> None:
    entry = dummy_entry()

    assert entry.name == "dummy"
    assert entry.value == "semprini_dummy_adapter:DummyAdapter"
    # An operator whose two plugins disagree has to be told which package to uninstall.
    assert entry.distribution == "semprini-dummy-adapter"
    assert entry.version == "1.0.0"
    assert entry.provider == "semprini-dummy-adapter 1.0.0"


def test_discovery_imports_nothing(installed_dummy_adapter: Path) -> None:
    """Listing what is installed must not run third-party module bodies.

    Configuration loading asks for the installed names on every command; importing every
    plugin to answer that would run arbitrary code from every installed distribution
    each time anyone types ``semprini check``.
    """
    assert DUMMY_MODULE not in sys.modules

    adapters.discover()
    adapters.adapter_names()

    assert DUMMY_MODULE not in sys.modules


def test_loading_is_what_imports(installed_dummy_adapter: Path) -> None:
    loaded = adapters.load_adapter("dummy")

    assert DUMMY_MODULE in sys.modules
    assert loaded.name == "dummy"
    assert loaded.__name__ == "DummyAdapter"


def test_entries_come_back_in_a_stable_order(
    installed_dummy_adapter: Path, installed_broken_adapter: None
) -> None:
    names = [entry.name for entry in adapters.discover()]

    assert names == sorted(names)


# ------------------------------------------------------------------ refusals


def test_an_unknown_name_lists_what_is_installed(installed_dummy_adapter: Path) -> None:
    with pytest.raises(AdapterLoadError) as raised:
        adapters.load_adapter(UNINSTALLED)

    message = str(raised.value)
    assert f"{UNINSTALLED!r}" in message
    # The operator's next action is to install something; the message has to say what is
    # there now, or a typo and a missing package look identical.
    assert "installed: dummy" in message


def test_a_plugin_that_cannot_be_imported_names_its_distribution(
    installed_broken_adapter: None,
) -> None:
    with pytest.raises(AdapterLoadError) as raised:
        adapters.load_adapter("broken")

    message = str(raised.value)
    assert "semprini-broken-adapter 0.3.0" in message
    assert "broken on purpose" in message
    assert "semprini_broken_adapter:BrokenAdapter" in message


def test_one_broken_plugin_does_not_hide_the_others(
    installed_dummy_adapter: Path, installed_broken_adapter: None
) -> None:
    # Discovery is metadata only, so a plugin that explodes on import cannot take the
    # rest of the installation down with it.
    assert {"broken", "dummy"} <= adapters.adapter_names()
    assert adapters.load_adapter("dummy").name == "dummy"


def test_two_distributions_claiming_one_name_are_refused(
    monkeypatch: pytest.MonkeyPatch, installed_dummy_adapter: Path
) -> None:
    """An ambiguous name is reported, never silently resolved.

    ``adapter: dummy`` would otherwise mean one thing on a laptop and another in CI,
    depending on installation order — the one failure mode a compiler this deterministic
    cannot tolerate.
    """
    rival = AdapterEntry(
        name="dummy",
        value="other_package:DummyAdapter",
        distribution="someone-elses-adapter",
        version="2.0.0",
    )
    monkeypatch.setattr(discovery_module, "discover", lambda: (dummy_entry(), rival))

    with pytest.raises(AdapterLoadError) as raised:
        adapters.load_adapter("dummy")

    message = str(raised.value)
    assert "semprini-dummy-adapter 1.0.0" in message
    assert "someone-elses-adapter 2.0.0" in message


def test_an_entry_point_that_is_not_a_class_is_refused() -> None:
    with pytest.raises(AdapterLoadError, match="not a BaseAdapter subclass"):
        AdapterEntry(name="dumps", value="json:dumps").load()


def test_a_class_that_is_not_an_adapter_is_refused() -> None:
    with pytest.raises(AdapterLoadError, match="not a BaseAdapter subclass"):
        AdapterEntry(name="decoder", value="json:JSONDecoder").load()


def test_an_adapter_that_does_not_implement_fetch_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = tmp_path / "half_finished_adapter.py"
    module.write_text(
        "from semprini.adapters import BaseAdapter\n\n\nclass Half(BaseAdapter):\n"
        '    name = "half"\n',
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(AdapterLoadError, match="does not implement fetch"):
        AdapterEntry(name="half", value="half_finished_adapter:Half").load()


def test_an_adapter_registered_under_another_name_is_refused(
    installed_dummy_adapter: Path,
) -> None:
    """An adapter's ``name`` is the name it is registered under (spec 5.2).

    An instance writes ``adapter: <name>`` in its configuration; a class calling itself
    something else would have every message about it name a thing that appears in no
    file the operator can open.
    """
    entry = AdapterEntry(name="taxonomies", value="semprini_dummy_adapter:DummyAdapter")

    with pytest.raises(AdapterLoadError, match="calls itself 'dummy'"):
        entry.load()


def test_an_unknown_name_with_nothing_installed_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    # Discovery is emptied rather than left to the ambient installation: since D2
    # registered `excel-taxonomy`, a real install always offers at least one adapter, and
    # a test that depended on finding none would have been silently testing something
    # else the moment the first bundled adapter landed.
    monkeypatch.setattr(discovery_module, "discover", tuple)

    with pytest.raises(AdapterLoadError, match="installed: none"):
        adapters.load_adapter("dummy")


# ------------------------------------------------------------------ construction


def test_create_builds_the_adapter_for_a_configured_source(
    installed_dummy_adapter: Path, dummy_source: Path
) -> None:
    source = config.SourceConfig(
        adapter="dummy", name="fixtures", settings={"path": str(dummy_source)}
    )

    adapter = adapters.create(source, CONTEXT)

    # The source's own name, not the adapter's: it is what lands in sem:sourceRef and in
    # the ID map (spec 5.4).
    assert adapter.source_name == "fixtures"
    assert adapter.config["path"] == str(dummy_source)
    assert adapter.ctx is CONTEXT
    assert {str(ref) for ref in adapter.fetch().entities[0].refs} == {"fixtures:e1"}


def test_creating_an_uninstalled_adapter_fails_before_anything_is_fetched() -> None:
    source = config.SourceConfig(adapter=UNINSTALLED, name="whatever", settings={})

    with pytest.raises(AdapterLoadError):
        adapters.create(source, CONTEXT)


def test_an_adapter_reports_what_it_read_for_the_run_report(
    installed_dummy_adapter: Path, dummy_source: Path
) -> None:
    # The slot report.SourceSummary.note fills (spec 5.6): counts alone would not tell a
    # reviewer that a source shrank because a model was renamed.
    source = config.SourceConfig(
        adapter="dummy", name="fixtures", settings={"path": str(dummy_source)}
    )
    adapter = adapters.create(source, CONTEXT)

    assert adapter.summary() == ""

    adapter.fetch()

    assert adapter.summary() == "2 entities from source.json"


# ------------------------------------------------------------------ the command


def test_adapters_lists_what_is_installed(
    installed_dummy_adapter: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["adapters"]) == ExitCode.OK

    out = capsys.readouterr().out
    # One adapter, one line: the adapter's own self-description is its docstring, and
    # pasting a whole docstring into the table would break the column it sits in. The
    # bundled excel-taxonomy is listed alongside it, so the dummy's line is picked out
    # rather than assumed to be the only one.
    (line,) = [entry for entry in out.splitlines() if entry.startswith("dummy ")]
    # Split rather than matched against fixed spacing: the name column widens to fit the
    # longest name, so asserting the exact gap would pin the *other* adapters installed.
    assert line.split()[:4] == ["dummy", "semprini-dummy-adapter", "1.0.0", "A"]
    assert line.endswith(
        "A JSON document standing in for a source system (the plane's own test fixture)."
    )
    assert any(entry.startswith("excel-taxonomy ") for entry in out.splitlines())


def test_adapters_describes_the_installation_not_an_instance(
    installed_dummy_adapter: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No config/semprini.yaml here at all: `adapters` answers a question about the
    # machine, and must work before an instance exists (spec 5.1).
    monkeypatch.chdir(tmp_path)

    assert main(["adapters"]) == ExitCode.OK


def test_adapters_with_nothing_installed_says_so(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only reachable now by emptying discovery — the plane ships excel-taxonomy — but the
    # branch still runs on an installation whose entry points are stripped, and an empty
    # listing that printed nothing at all would read as a crash. Patched on the package,
    # which is the name the command resolves; the module attribute is a different binding
    # and patching it here would leave the command reading the real installation.
    monkeypatch.setattr(adapters, "discover", tuple)

    assert main(["adapters"]) == ExitCode.OK
    assert capsys.readouterr().out == "no adapters are installed\n"


def test_a_broken_plugin_is_reported_and_exits_1(
    installed_dummy_adapter: Path,
    installed_broken_adapter: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["adapters"]) == ExitCode.FAILURE

    captured = capsys.readouterr()
    # The working adapters are still listed: the command's job is to describe the
    # installation, and "one of your plugins is broken" is part of that description.
    assert "dummy" in captured.out
    assert "broken" in captured.out
    assert "semprini-broken-adapter 0.3.0" in captured.err
    # One broken plugin reads as one message, not as a list of one.
    assert "1 installed adapters" not in captured.err


def test_several_broken_plugins_are_reported_together(
    installed_broken_adapter: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    second = AdapterEntry(
        name="also-broken",
        value="semprini_broken_adapter:Other",
        distribution="another",
        version="9",
    )
    monkeypatch.setattr(adapters, "discover", lambda: (*discovery_module.discover(), second))

    assert main(["adapters"]) == ExitCode.FAILURE

    err = capsys.readouterr().err
    assert "2 installed adapters could not be loaded" in err
    assert "semprini-broken-adapter 0.3.0" in err
    assert "another 9" in err


def test_a_duplicate_name_fails_the_listing_too(
    installed_dummy_adapter: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An installation where `adapter: dummy` cannot be resolved is a broken one.

    Every plugin in it imports perfectly, so loading each entry in turn says nothing is
    wrong — while the run that reads the configuration fails. The command exists to
    report whether the installation works, so it has to ask the same question
    `load_adapter` does.
    """
    rival = AdapterEntry(
        name="dummy",
        value="semprini_dummy_adapter:DummyAdapter",
        distribution="someone-elses-adapter",
        version="2.0.0",
    )
    both = (dummy_entry(), rival)
    monkeypatch.setattr(adapters, "discover", lambda: both)

    assert main(["adapters"]) == ExitCode.FAILURE

    captured = capsys.readouterr()
    # Both rows are still listed — the operator needs to see the two claimants.
    assert [line.split()[1] for line in captured.out.splitlines()] == [
        "semprini-dummy-adapter",
        "someone-elses-adapter",
    ]
    assert "more than one installed distribution" in captured.err
    assert "someone-elses-adapter 2.0.0" in captured.err


def test_an_adapter_that_documents_nothing_is_listed_without_a_description() -> None:
    class Undocumented(adapters.BaseAdapter):
        name = "undocumented"

        def fetch(self) -> InternalModel:
            return InternalModel()

    # BaseAdapter has a docstring, and an MRO-walking lookup would print it here as
    # though this adapter had described itself.
    assert adapters.BaseAdapter.__doc__
    assert cli._summary(Undocumented) == ""


# ------------------------------------------------------------------ exit codes


def test_a_configured_adapter_that_is_not_installed_exits_2(
    instance: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The check B3 left for this task to wire up.

    A source naming an adapter nobody installed is a configuration error, reported with
    its key. The fixture instance used to be the example, because it configured
    ``excel-taxonomy`` before that adapter existed; now that D2 ships it, the case needs
    a name that really is absent.
    """
    config = instance / "config" / "semprini.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("adapter: excel-taxonomy", "adapter: collibra"),
        encoding="utf-8",
        newline="\n",
    )

    assert main(["check"]) == ExitCode.CONFIG

    err = capsys.readouterr().err
    assert "collibra" in err
    assert "sources[1].adapter" in err


def test_the_name_check_is_skipped_when_no_adapter_is_installed(instance: Path) -> None:
    # Checking against an empty set would reject every valid configuration, so an
    # installation with no adapters at all does not judge names (B3's reasoning). Exit 1
    # is `check` reporting itself unimplemented, i.e. configuration loaded cleanly.
    assert main(["check"]) == ExitCode.FAILURE


def test_exit_code_for_maps_each_error_to_its_published_code() -> None:
    # One mapping, in one place: a subcommand that invented its own would make "3" mean
    # different things depending on which one produced it (spec 5.1).
    assert exit_code_for(config.ConfigError([Issue(Severity.ERROR, "bad")])) is ExitCode.CONFIG
    assert exit_code_for(identity.NamespaceLockError([Issue(Severity.ERROR, "moved")])) is (
        ExitCode.CONFIG
    )
    assert exit_code_for(SourceUnreachableError("the API is down")) is ExitCode.UNREACHABLE
    assert exit_code_for(AdapterError("something else")) is ExitCode.FAILURE
    assert exit_code_for(identity.IdentityError([Issue(Severity.ERROR, "collision")])) is (
        ExitCode.FAILURE
    )


def test_an_unreachable_source_exits_3(installed_dummy_adapter: Path, tmp_path: Path) -> None:
    """The shape E2's fetch loop takes, with the source down.

    Exit 3 is what tells a scheduled compile to retry rather than open an issue, so it
    has to survive the trip from the adapter's ``raise`` to the process's return code —
    which is this call and the mapping above, and nothing in between.
    """
    source = config.SourceConfig(
        adapter="dummy", name="fixtures", settings={"path": str(tmp_path / "not-there.json")}
    )
    adapter = adapters.create(source, CONTEXT)

    with pytest.raises(SourceUnreachableError) as raised:
        adapter.fetch()

    assert exit_code_for(raised.value) == ExitCode.UNREACHABLE


def test_the_cli_still_reports_configuration_errors_with_their_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The handler moved into main() with the error mapping; what an operator sees must
    # not have (spec 5.1).
    monkeypatch.chdir(tmp_path)

    assert main(["check"]) == ExitCode.CONFIG
    assert "semprini:" in capsys.readouterr().err


def test_the_adapters_command_is_no_longer_a_stub() -> None:
    assert "adapters" not in cli._UNIMPLEMENTED

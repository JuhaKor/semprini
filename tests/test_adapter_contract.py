"""The shared adapter contract suite (spec 5.2, task D1).

Two things are under test, and the second is the one that matters. That
``check_contract`` passes the dummy adapter is table stakes; that it *fails* an adapter
which writes, mints, or swallows a dead source is the whole reason it ships. A contract
suite everything passes is worse than none — it certifies adapters nobody checked.

So every check has a purpose-built violator below. They are deliberately plausible
mistakes rather than absurd ones: an adapter that caches its download next to the source
file, one that helpfully builds the IRI it expects the object to get, one that catches
its own connection error and returns what it had. Each is the mistake an adapter author
makes once.
"""

from __future__ import annotations

import builtins
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest

from semprini.adapters import AdapterError, BaseAdapter, SourceUnreachableError
from semprini.model import (
    Attribute,
    Entity,
    InternalModel,
    Issue,
    RunContext,
    Scheme,
    SchemeType,
    Severity,
    SourceRef,
)
from semprini.testing import CONTRACT_BASE_IRI, AdapterContractError, check_contract

CONTEXT = RunContext(base_iri=CONTRACT_BASE_IRI, instance_id="contract")


def entity(key: str = "e1", label: str = "Customer", **extra: Any) -> Entity:
    return Entity(source_refs={"contract-source": key}, pref_label=label, **extra)


class WellBehaved(BaseAdapter):
    """Everything an adapter is supposed to be, in twelve lines."""

    name = "well-behaved"

    def fetch(self) -> InternalModel:
        if self.config.get("down"):
            raise SourceUnreachableError("the source is down")
        return InternalModel(entities=(entity(),))


def violations(error: pytest.ExceptionInfo[AdapterContractError]) -> set[str | None]:
    """Which named checks failed, so a test pins the diagnosis and not just the failure."""
    return {issue.location for issue in error.value.issues}


def check(adapter: type[BaseAdapter], **settings: Any) -> None:
    check_contract(adapter, settings=settings, unreachable={"down": True}, context=CONTEXT)


# ------------------------------------------------------------------ the good case


def test_the_installed_dummy_adapter_meets_the_contract(
    installed_dummy_adapter: Path, dummy_source: Path, tmp_path: Path
) -> None:
    """The call an adapter author writes, against the adapter a third party would ship.

    Also proves the suite tolerates what adapters legitimately do: the dummy *reads* a
    file during fetch, which the write guard must not mistake for a write.
    """
    from semprini_dummy_adapter import DummyAdapter

    check_contract(
        DummyAdapter,
        settings={"path": str(dummy_source)},
        unreachable={"path": str(tmp_path / "not-there.json")},
    )


def test_a_well_behaved_adapter_passes() -> None:
    check(WellBehaved)


def test_the_default_context_needs_no_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An adapter author has no Semprini instance and should not need one to run this.
    monkeypatch.chdir(tmp_path)
    check_contract(WellBehaved, settings={}, unreachable={"down": True})


# ------------------------------------------------------------------ writes


def test_an_adapter_that_writes_is_caught(tmp_path: Path) -> None:
    class Cacheing(BaseAdapter):
        """Writes its download next to the source, which is how this mistake really looks."""

        name = "cacheing"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            Path(self.config["cache"]).write_text("{}", encoding="utf-8")
            return InternalModel(entities=(entity(),))

    with pytest.raises(AdapterContractError) as raised:
        check(Cacheing, cache=str(tmp_path / "cache.json"))

    assert violations(raised) == {"no-writes"}
    assert "cache.json" in str(raised.value)


def test_a_write_through_the_low_level_call_is_caught(tmp_path: Path) -> None:
    class Sneaky(BaseAdapter):
        """os.open bypasses builtins.open, and an adapter using it writes just as much."""

        name = "sneaky"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            import os

            handle = os.open(str(self.config["cache"]), os.O_WRONLY | os.O_CREAT)
            os.close(handle)
            return InternalModel(entities=(entity(),))

    with pytest.raises(AdapterContractError) as raised:
        check(Sneaky, cache=str(tmp_path / "touched"))

    assert violations(raised) == {"no-writes"}


def test_making_a_directory_is_a_write(tmp_path: Path) -> None:
    class Nesting(BaseAdapter):
        """Creates its cache directory before deciding it does not need one."""

        name = "nesting"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            os.mkdir(str(self.config["cache"]))
            return InternalModel(entities=(entity(),))

    with pytest.raises(AdapterContractError) as raised:
        check(Nesting, cache=str(tmp_path / "cache"))

    # Also "repeatable", and rightly so: the second fetch trips over the directory the
    # first one left behind, which is the concrete reason adapters do not write.
    assert violations(raised) == {"no-writes", "repeatable"}


def test_deleting_a_file_is_a_write(tmp_path: Path) -> None:
    """Deletion is the most damaging thing an adapter could do to an instance.

    ``Path.unlink()`` reaches ``os.unlink``, which is a *different* attribute from
    ``os.remove`` bound to a different function — so guarding one and not the other left
    the worst case unrecorded.
    """
    victim = tmp_path / "doomed.json"
    victim.write_text("{}", encoding="utf-8")

    class Tidying(BaseAdapter):
        """Cleans up after itself, on a file it did not create."""

        name = "tidying-up"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            Path(self.config["victim"]).unlink()
            return InternalModel(entities=(entity(),))

    with pytest.raises(AdapterContractError) as raised:
        check(Tidying, victim=str(victim))

    assert "no-writes" in violations(raised)
    assert "doomed.json" in str(raised.value)


def test_renaming_a_file_is_a_write(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")

    class Moving(BaseAdapter):
        """Rotates the file it just read, which no adapter is entitled to do."""

        name = "moving"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            Path(self.config["path"]).rename(str(self.config["path"]) + ".done")
            return InternalModel(entities=(entity(),))

    with pytest.raises(AdapterContractError) as raised:
        check(Moving, path=str(source))

    assert "no-writes" in violations(raised)


def test_a_write_before_a_failure_is_reported(tmp_path: Path) -> None:
    """The case the no-writes rule exists for, and the easiest one to miss.

    A run that fails midway has to leave the instance exactly as it found it. An adapter
    that saves what it downloaded and *then* discovers the source is incomplete is how it
    does not — and reporting only the failure would hide the file it left behind.
    """

    class HalfWay(BaseAdapter):
        """Writes what it got, then fails."""

        name = "half-way"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            Path(self.config["partial"]).write_text("{}", encoding="utf-8")
            raise RuntimeError("the rest of the model is missing")

    with pytest.raises(AdapterContractError) as raised:
        check(HalfWay, partial=str(tmp_path / "partial.json"))

    assert violations(raised) == {"no-writes", "fetch"}
    assert "partial.json" in str(raised.value)


def test_a_write_while_the_source_is_down_is_caught(tmp_path: Path) -> None:
    class Salvaging(BaseAdapter):
        """Saves the part it managed to download before giving up — correctly raising."""

        name = "salvaging"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                Path(self.config["partial"]).write_text("{}", encoding="utf-8")
                raise SourceUnreachableError("the source is down")
            return InternalModel(entities=(entity(),))

    with pytest.raises(AdapterContractError) as raised:
        check_contract(
            Salvaging,
            settings={"partial": str(tmp_path / "partial.json")},
            unreachable={"down": True, "partial": str(tmp_path / "partial.json")},
            context=CONTEXT,
        )

    # It raises the right exception, so nothing else is wrong with it — but the run that
    # was supposed to change nothing left a file behind.
    assert violations(raised) == {"no-writes"}


def test_a_write_on_the_first_fetch_alone_is_caught(tmp_path: Path) -> None:
    """Writing once, on the first fetch, and never again.

    Its own test because every other violator here writes on *every* fetch, so the
    second-fetch guard alone would catch them and the check on the successful first
    fetch could be deleted without a test noticing.
    """

    class WarmingOnce(BaseAdapter):
        """Populates a cache the first time it runs, then reads it happily forever."""

        name = "warming-once"
        calls = 0

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            type(self).calls += 1
            if type(self).calls == 1:
                Path(self.config["cache"]).write_text("{}", encoding="utf-8")
            return InternalModel(entities=(entity(),))

    with pytest.raises(AdapterContractError) as raised:
        check(WarmingOnce, cache=str(tmp_path / "once.json"))

    assert violations(raised) == {"no-writes"}
    assert "once.json" in str(raised.value)


def test_a_write_on_the_second_fetch_is_caught(tmp_path: Path) -> None:
    class Warming(BaseAdapter):
        """Writes a cache the second time it is asked, which the first fetch never shows."""

        name = "warming"
        calls = 0

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            type(self).calls += 1
            if type(self).calls > 1:
                Path(self.config["cache"]).write_text("{}", encoding="utf-8")
            return InternalModel(entities=(entity(),))

    with pytest.raises(AdapterContractError) as raised:
        check(Warming, cache=str(tmp_path / "warm.json"))

    assert violations(raised) == {"no-writes"}


def test_a_write_while_being_constructed_is_caught(tmp_path: Path) -> None:
    class Eager(BaseAdapter):
        """Constructing an adapter must be free — `semprini check` does it to validate."""

        name = "eager"

        def __init__(self, source_name: str, config: Any, ctx: RunContext) -> None:
            super().__init__(source_name, config, ctx)
            Path(config["log"]).write_text("hello\n", encoding="utf-8")

        def fetch(self) -> InternalModel:
            return InternalModel(entities=(entity(),))

    with pytest.raises(AdapterContractError) as raised:
        check(Eager, log=str(tmp_path / "adapter.log"))

    assert "construction" in violations(raised)


def test_reading_is_not_a_write(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"label": "Customer"}), encoding="utf-8")

    class Reader(BaseAdapter):
        """Reads its source, which is the one thing every adapter has to be allowed to do."""

        name = "reader"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            document = json.loads(Path(self.config["path"]).read_text(encoding="utf-8"))
            return InternalModel(entities=(entity(label=str(document["label"])),))

    check(Reader, path=str(source))


# ------------------------------------------------------------------ minting


def test_an_adapter_that_mints_an_iri_is_caught() -> None:
    class Helpful(BaseAdapter):
        """Builds the IRI it expects the object to get — the ID map's job, not its own."""

        name = "helpful"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            return InternalModel(
                entities=(entity(alt_labels=(f"{CONTRACT_BASE_IRI}concepts/e1",)),)
            )

    with pytest.raises(AdapterContractError) as raised:
        check(Helpful)

    assert violations(raised) == {"no-minting"}
    assert "base IRI" in str(raised.value)


def test_an_adapter_that_invents_a_metamodel_term_is_caught() -> None:
    class Inventive(BaseAdapter):
        """Puts a sem: term in its data; the metamodel is not an adapter's to extend."""

        name = "inventive"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            return InternalModel(
                entities=(entity(definition="see https://w3id.org/semprini/ontology#Entity"),)
            )

    with pytest.raises(AdapterContractError) as raised:
        check(Inventive)

    assert violations(raised) == {"no-minting"}


def test_a_minted_iri_in_a_cross_reference_is_caught() -> None:
    """The likeliest place to mint one, and the last place a string scan looks.

    ``Attribute.entity``, ``Relationship.source``/``target`` and ``TaxonomyValue.parent``
    are ``SourceRef``s — an author who thinks "the entity this belongs to" reaches for an
    IRI here more readily than anywhere else, and a scan that walked only strings and
    tuples walked straight past a dataclass.
    """

    class Pointing(BaseAdapter):
        """Points its attribute at the IRI it expects the entity to have."""

        name = "pointing"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            return InternalModel(
                entities=(entity(),),
                attributes=(
                    Attribute(
                        source_refs={"contract-source": "a1"},
                        pref_label="Name",
                        entity=SourceRef("contract-source", f"{CONTRACT_BASE_IRI}concepts/e1"),
                    ),
                ),
            )

    with pytest.raises(AdapterContractError) as raised:
        check(Pointing)

    assert violations(raised) == {"no-minting"}
    assert "Attribute.entity" in str(raised.value)


def test_a_scheme_points_at_its_entity_with_a_source_ref() -> None:
    # sem:enumerates used to hold an IRI the instance configured by hand, and the minting
    # check had to carve out an exception for it. It is a SourceRef now (spec 5.3), so
    # there is nothing an adapter may return that is allowed to look like an IRI, and the
    # rule reads the same for every field.
    class Taxonomy(BaseAdapter):
        """Names the entity its taxonomy enumerates by that source's own key."""

        name = "taxonomy"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            return InternalModel(
                schemes=(
                    Scheme(
                        source_refs={"contract-source": "sizes"},
                        pref_label="Sizes",
                        slug="sizes",
                        scheme_type=SchemeType.TAXONOMY,
                        enumerates=SourceRef("contract-source", "1e5c"),
                    ),
                )
            )

    check(Taxonomy)


def test_an_enumerates_that_smuggles_an_iri_through_is_caught() -> None:
    # A SourceRef's key is free text, so the escape is still reachable by an author who
    # pastes an IRI into it. The recursive scan walks into dataclasses (it has to, for
    # Attribute.entity), so it is caught by the same rule as everything else.
    class Smuggling(BaseAdapter):
        """Puts a minted IRI in the key of the source ref its scheme enumerates."""

        name = "smuggling"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            return InternalModel(
                schemes=(
                    Scheme(
                        source_refs={"contract-source": "sizes"},
                        pref_label="Sizes",
                        slug="sizes",
                        scheme_type=SchemeType.TAXONOMY,
                        enumerates=SourceRef(
                            "contract-source", f"{CONTRACT_BASE_IRI}concepts/1e5c"
                        ),
                    ),
                )
            )

    with pytest.raises(AdapterContractError) as raised:
        check(Smuggling)

    assert violations(raised) == {"no-minting"}


# ------------------------------------------------------------------ failures and drift


def test_an_adapter_that_returns_a_partial_model_is_caught() -> None:
    class Forgiving(BaseAdapter):
        """Catches its own connection error and returns what it had — deprecating the rest."""

        name = "forgiving"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                return InternalModel()
            return InternalModel(entities=(entity(),))

    with pytest.raises(AdapterContractError) as raised:
        check(Forgiving)

    assert violations(raised) == {"unreachable-raises"}
    assert "deprecated" in str(raised.value)


def test_the_wrong_exception_type_is_caught() -> None:
    class Muddled(BaseAdapter):
        """Raises, but not the type that means exit 3 — so CI cannot tell down from wrong."""

        name = "muddled"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise AdapterError("could not connect")
            return InternalModel(entities=(entity(),))

    with pytest.raises(AdapterContractError) as raised:
        check(Muddled)

    assert violations(raised) == {"unreachable-raises"}
    assert "exit 3 versus exit 1" in str(raised.value)


def test_a_raw_exception_reaching_the_operator_is_caught() -> None:
    class Unwrapped(BaseAdapter):
        """Lets its HTTP library's exception escape, which reaches CI as a traceback."""

        name = "unwrapped"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise TimeoutError("timed out")
            return InternalModel(entities=(entity(),))

    with pytest.raises(AdapterContractError) as raised:
        check(Unwrapped)

    assert violations(raised) == {"unreachable-raises"}


def test_an_adapter_whose_output_varies_between_fetches_is_caught() -> None:
    class Drifting(BaseAdapter):
        """Labels objects from something that changes — a counter, a clock, a set's order."""

        name = "drifting"
        seen = 0

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            type(self).seen += 1
            return InternalModel(entities=(entity(label=f"Customer {type(self).seen}"),))

    with pytest.raises(AdapterContractError) as raised:
        check(Drifting)

    assert violations(raised) == {"repeatable"}


# ------------------------------------------------------------------ the rest of the contract


def test_an_object_attributed_to_another_source_is_caught() -> None:
    class Misattributing(BaseAdapter):
        """Keys its objects by the adapter's name rather than the configured source's."""

        name = "misattributing"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            return InternalModel(
                entities=(Entity(source_refs={"misattributing": "e1"}, pref_label="Customer"),)
            )

    with pytest.raises(AdapterContractError) as raised:
        check(Misattributing)

    assert violations(raised) == {"source-refs"}


def test_a_model_that_contradicts_itself_is_caught() -> None:
    class Contradictory(BaseAdapter):
        """Reports one source key twice with two labels — a merge nothing can resolve."""

        name = "contradictory"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            return InternalModel(entities=(entity(), entity(label="Client")))

    with pytest.raises(AdapterContractError) as raised:
        check(Contradictory)

    assert violations(raised) == {"consistency"}


def test_an_adapter_that_edits_its_configuration_is_caught() -> None:
    class Tidying(BaseAdapter):
        """Normalizes its own settings in place; the run report reads that same object."""

        name = "tidying"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            self.config["base_url"] = str(self.config["base_url"]).rstrip("/")  # type: ignore[index]
            return InternalModel(entities=(entity(),))

    with pytest.raises(AdapterContractError) as raised:
        check(Tidying, base_url="https://example.com/")

    assert violations(raised) == {"no-mutation"}


def test_validate_config_that_raises_is_caught() -> None:
    class Shouty(BaseAdapter):
        """Raises on a bad key instead of reporting it, so the operator sees one at a time."""

        name = "shouty"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            return InternalModel(entities=(entity(),))

        def validate_config(self) -> list[Issue]:
            raise ValueError("no base_url configured")

    with pytest.raises(AdapterContractError) as raised:
        check(Shouty)

    assert violations(raised) == {"validate-config"}


def test_validate_config_rejecting_the_supplied_settings_is_caught() -> None:
    class Fussy(BaseAdapter):
        """Says the settings are wrong while fetching happily from them — one of the two lies."""

        name = "fussy"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            return InternalModel(entities=(entity(),))

        def validate_config(self) -> list[Issue]:
            return [Issue(Severity.ERROR, "something is wrong", "sources.x.config")]

    with pytest.raises(AdapterContractError) as raised:
        check(Fussy)

    assert violations(raised) == {"validate-config"}


def test_a_warning_from_validate_config_is_not_a_violation() -> None:
    class Cautious(BaseAdapter):
        """Warns about a setting without refusing it — exactly what warnings are for."""

        name = "cautious"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            return InternalModel(entities=(entity(),))

        def validate_config(self) -> list[Issue]:
            return [Issue(Severity.WARNING, "codes_are_stable is not set", "sources.x.config")]

    check(Cautious)


def test_a_multi_line_summary_is_caught() -> None:
    class Verbose(BaseAdapter):
        """Returns a paragraph where the report has a table cell (spec 5.6)."""

        name = "verbose"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            return InternalModel(entities=(entity(),))

        def summary(self) -> str:
            return "read 3 models\nrenamed: Sales"

    with pytest.raises(AdapterContractError) as raised:
        check(Verbose)

    assert violations(raised) == {"summary"}


def test_a_summary_that_raises_is_a_violation_not_a_traceback() -> None:
    class Fragile(BaseAdapter):
        """Its report line assumes a fetch that never happened."""

        name = "fragile"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                raise SourceUnreachableError("the source is down")
            return InternalModel(entities=(entity(),))

        def summary(self) -> str:
            raise AttributeError("no models were recorded")

    with pytest.raises(AdapterContractError) as raised:
        check(Fragile)

    # Collected like every other check: an author running this wants the whole list, not
    # whichever violation happened to raise first.
    assert violations(raised) == {"summary"}


def test_something_that_is_not_an_adapter_is_refused_before_anything_runs() -> None:
    with pytest.raises(AdapterContractError) as raised:
        check_contract(
            dict,  # type: ignore[arg-type]
            settings={},
            unreachable={},
            context=CONTEXT,
        )

    assert violations(raised) == {"subclass"}


def test_an_adapter_whose_name_is_not_a_slug_is_refused() -> None:
    class Shouted(BaseAdapter):
        """A name that would have to be quoted in YAML and escaped in the ID map."""

        name = "Ellie Models!"

        def fetch(self) -> InternalModel:
            return InternalModel()

    with pytest.raises(AdapterContractError) as raised:
        check(Shouted)

    assert violations(raised) == {"name"}


def test_every_violation_is_reported_at_once() -> None:
    class Hopeless(BaseAdapter):
        """Several mistakes at once, which is what a first draft actually looks like."""

        name = "hopeless"

        def fetch(self) -> InternalModel:
            if self.config.get("down"):
                return InternalModel()
            return InternalModel(
                entities=(entity(alt_labels=(f"{CONTRACT_BASE_IRI}concepts/e1",)),)
            )

        def summary(self) -> str:
            return "one\ntwo"

    with pytest.raises(AdapterContractError) as raised:
        check(Hopeless)

    # An author fixing a new adapter should see the list once, not one per run — the
    # same reason a configuration error carries every issue (spec 5.1).
    assert violations(raised) == {"no-minting", "summary", "unreachable-raises"}
    assert "Hopeless" in str(raised.value)


@pytest.mark.parametrize(
    ("module", "attribute"),
    [
        (builtins, "open"),
        (io, "open"),
        (os, "open"),
        (os, "mkdir"),
        (os, "rmdir"),
        (os, "remove"),
        (os, "unlink"),
        (os, "rename"),
        (os, "replace"),
    ],
)
def test_the_guard_puts_the_interpreter_back(module: Any, attribute: str) -> None:
    """The write guard patches file opening process-wide; a leak outlives the check.

    Asserting the functions are the same objects, not merely that writing still works:
    the guard calls through, so a leaked patch keeps working perfectly while quietly
    recording every write the rest of the test session makes.
    """
    before = getattr(module, attribute)

    check(WellBehaved)

    assert getattr(module, attribute) is before


def test_the_guard_is_removed_even_when_a_check_fails(tmp_path: Path) -> None:
    class Exploding(BaseAdapter):
        """Raises from inside the guarded block, which is where a leak would start."""

        name = "exploding"

        def fetch(self) -> InternalModel:
            raise RuntimeError("boom")

    before = builtins.open
    with pytest.raises(AdapterContractError):
        check(Exploding)

    assert builtins.open is before

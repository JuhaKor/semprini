"""Identity: the ID map, minting and the namespace lock (spec 3.4, 5.4).

Identity is the one decision an instance cannot take back. A wrong label is fixed by the
next run; a wrong IRI is published, cited and permanent. So the tests here are less about
"does it compute the right string" than about the four ways that permanence can be lost:

- an IRI **moves** — the map is edited, a row is dropped, the base IRI is changed;
- an IRI is **shared** — two source keys collide onto one;
- an IRI is **duplicated** — a lookup misses and the same object mints a second identity;
- an IRI **differs between machines** — minting depends on something other than its input.

Each of those has tests below, and the minting formulas are pinned to literal values on
purpose: an assertion that recomputes the formula would agree with any change to it,
including one that silently re-mints every object in every instance in existence.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

from semprini import config, identity, serialize
from semprini.cli import ExitCode, main
from semprini.config import InstanceConfig
from semprini.identity import (
    ID_MAP_COLUMNS,
    ID_MAP_PATH,
    NAMESPACE_LOCK_PATH,
    NAMESPACE_SEMPRINI,
    IdentityError,
    IdMap,
    IdMapRow,
    NamespaceLock,
    NamespaceLockError,
    Registry,
)
from semprini.model import (
    Attribute,
    Entity,
    InternalModel,
    Kind,
    Relationship,
    Scheme,
    SchemeType,
    SemanticObject,
    SourceRef,
    TaxonomyValue,
)

BASE = "https://semantics.example.com/"
TODAY = datetime.date(2026, 8, 6)
SOURCE = "ellie-main"

# A UUID as a source system hands one over, and the same UUID shouted.
CUSTOMER_UUID = "7f3a9b12-04c1-4a8e-9d1f-2b6f8f7f3d21"
ORDER_UUID = "0d9e4c77-1c1e-4a41-9f0c-6a3a0b2f5c10"


def entity(key: str = CUSTOMER_UUID, *, source: str = SOURCE, label: str = "Customer") -> Entity:
    return Entity(source_refs={source: key}, pref_label=label, schemes=("sales",))


def scheme(slug: str = "sales", *, key: str = "1234", source: str = SOURCE) -> Scheme:
    return Scheme(
        source_refs={source: key},
        pref_label="Sales domain model",
        slug=slug,
        scheme_type=SchemeType.GLOSSARY,
    )


def value(
    key: str = "PT-DR", *, slug: str = "product-category", code: str = "PT-DR"
) -> TaxonomyValue:
    return TaxonomyValue(
        source_refs={"taxonomies": key}, pref_label="Drills", code=code, schemes=(slug,)
    )


def registry(rows: tuple[IdMapRow, ...] = ()) -> Registry:
    return Registry(IdMap(rows), BASE, today=TODAY)


def row(
    iri: str, kind: Kind = Kind.ENTITY, *, source: str = SOURCE, key: str = CUSTOMER_UUID
) -> IdMapRow:
    return IdMapRow(iri=iri, kind=kind, source_name=source, source_key=key, first_seen=TODAY)


# ------------------------------------------------------------------------------- minting


def test_the_namespace_constant_is_the_derivation_it_documents() -> None:
    """The one value that can never change without re-minting every future IRI.

    Pinned two ways — the literal below, and the derivation the docstring claims — so
    that neither the constant nor its stated provenance can drift from the other.
    """
    assert uuid.UUID("8865c94a-2211-5f26-8887-6d6d5cbaa1e0") == NAMESPACE_SEMPRINI
    assert uuid.uuid5(uuid.NAMESPACE_URL, serialize.SEM_NAMESPACE) == NAMESPACE_SEMPRINI


def test_a_source_uuid_is_used_as_the_local_name() -> None:
    """Spec 3.4.2: a source that already mints opaque stable ids has done the work."""
    assert identity.mint_local_name(entity()) == CUSTOMER_UUID


def test_a_source_uuid_is_normalized_to_its_canonical_form() -> None:
    """The same UUID in upper case is the same UUID, and must not mint a second IRI."""
    assert identity.mint_local_name(entity(key=CUSTOMER_UUID.upper())) == CUSTOMER_UUID
    assert identity.mint_local_name(entity(key=CUSTOMER_UUID.replace("-", ""))) == CUSTOMER_UUID


def test_a_source_key_that_is_not_a_uuid_derives_one() -> None:
    expected = str(uuid.uuid5(NAMESPACE_SEMPRINI, f"{SOURCE}:customer"))

    assert identity.mint_local_name(entity(key="customer")) == expected
    # Pinned as a literal too: recomputing the formula would accept any change to it.
    assert expected == "7c98e825-7c20-57ef-9ab9-1a05de712efd"


def test_a_scheme_takes_its_slug() -> None:
    """Spec 3.4.2: assigned once at creation, opaque thereafter."""
    assert identity.mint_local_name(scheme(slug="sales")) == "sales"


def test_a_taxonomy_value_derives_from_its_scheme_and_row_key() -> None:
    expected = str(uuid.uuid5(NAMESPACE_SEMPRINI, "product-category|PT-DR"))

    assert identity.mint_local_name(value()) == expected
    assert expected == "9ba03ae3-5f30-5a06-b5d0-d210799f9c1f"


def test_a_taxonomy_value_is_minted_from_its_key_not_its_code() -> None:
    """Spec 3.5: a changed code changes ``skos:notation``, never the IRI.

    The adapter decides what the stable row key is (spec 3.4.2) and puts it in the source
    ref; the code is business data that moves.
    """
    assert identity.mint_local_name(value(key="row-7", code="PT-DR")) == identity.mint_local_name(
        value(key="row-7", code="PT-DRILLS")
    )


def test_a_taxonomy_value_ignores_the_order_its_schemes_arrived_in() -> None:
    both = TaxonomyValue(
        source_refs={"taxonomies": "PT-DR"},
        pref_label="Drills",
        code="PT-DR",
        schemes=("tools", "product-category"),
    )
    reversed_ = TaxonomyValue(
        source_refs={"taxonomies": "PT-DR"},
        pref_label="Drills",
        code="PT-DR",
        schemes=("product-category", "tools"),
    )

    assert identity.mint_local_name(both) == identity.mint_local_name(reversed_)


def test_a_taxonomy_value_with_no_scheme_cannot_be_minted() -> None:
    """Its IRI derives from the scheme slug, so there is no answer to give."""
    orphan = TaxonomyValue(source_refs={"taxonomies": "PT-DR"}, pref_label="Drills", code="PT-DR")

    with pytest.raises(IdentityError, match="must belong to a scheme"):
        identity.mint_local_name(orphan)


def test_a_slug_that_cannot_be_written_as_a_local_name_is_refused() -> None:
    """A scheme slug comes from the adapter's own config subtree, unvalidated until here.

    The ID map would freeze whatever it produced, so a slug that the serializer would
    have to write as a full ``<IRI>`` is refused before it can be recorded.
    """
    with pytest.raises(IdentityError, match="cannot be an IRI local name"):
        identity.mint_local_name(scheme(slug="product category"))


@pytest.mark.parametrize(
    ("object_", "prefix"),
    [
        (entity(), "c"),
        (
            Attribute(
                source_refs={SOURCE: ORDER_UUID},
                pref_label="Customer number",
                entity=SourceRef(SOURCE, CUSTOMER_UUID),
            ),
            "c",
        ),
        (
            Relationship(
                source_refs={SOURCE: ORDER_UUID},
                pref_label="places",
                source=SourceRef(SOURCE, CUSTOMER_UUID),
                target=SourceRef(SOURCE, ORDER_UUID),
            ),
            "r",
        ),
        (scheme(), "sch"),
        (value(), "v"),
    ],
    ids=["entity", "attribute", "relationship", "scheme", "taxonomy-value"],
)
def test_each_kind_is_minted_in_its_own_namespace(object_: SemanticObject, prefix: str) -> None:
    """Spec 3.1: the IRI space is partitioned by kind of thing, permanently."""
    iri = registry().iri_for(object_)

    assert iri.startswith(serialize.namespaces(BASE)[prefix])


# ------------------------------------------------------------------ resolution and reuse


def test_a_known_source_key_reuses_its_iri() -> None:
    """The lookup hit of spec 5.4 — and no new row for an object already recorded."""
    known = registry((row(f"{BASE}concepts/legacy-id"),))

    assert known.iri_for(entity()) == f"{BASE}concepts/legacy-id"
    assert known.minted == ()
    assert len(known.id_map) == 1


def test_the_id_map_beats_the_minting_formula() -> None:
    """Spec 5.4's central rule, stated as a test.

    The recorded IRI bears no relation to what minting would produce, and it still wins:
    that is what lets minting rules, codes and compiler versions change without touching
    identity.
    """
    recorded = f"{BASE}concepts/f0000000-0000-5000-8000-000000000001"
    known = registry((row(recorded),))

    assert known.iri_for(entity()) == recorded
    assert recorded != BASE + "concepts/" + identity.mint_local_name(entity())


def test_an_unknown_object_mints_and_appends_exactly_one_row() -> None:
    fresh = registry()

    iri = fresh.iri_for(entity())

    assert iri == f"{BASE}concepts/{CUSTOMER_UUID}"
    assert len(fresh.id_map) == 1
    assert fresh.id_map.rows[0] == IdMapRow(
        iri=iri,
        kind=Kind.ENTITY,
        source_name=SOURCE,
        source_key=CUSTOMER_UUID,
        first_seen=TODAY,
    )
    assert fresh.minted == fresh.id_map.rows


def test_resolving_the_same_object_twice_appends_one_row() -> None:
    fresh = registry()

    assert fresh.iri_for(entity()) == fresh.iri_for(entity())
    assert len(fresh.id_map) == 1


def test_an_object_known_to_two_sources_gets_one_iri_and_a_row_each() -> None:
    """Spec 5.2: the same real-world concept seen by two adapters merges onto one IRI."""
    shared = Entity(
        source_refs={SOURCE: CUSTOMER_UUID, "collibra": "CUST"},
        pref_label="Customer",
        schemes=("sales",),
    )
    fresh = registry()

    iri = fresh.iri_for(shared)

    assert {r.source_name for r in fresh.id_map} == {SOURCE, "collibra"}
    assert {r.iri for r in fresh.id_map} == {iri}


def test_a_second_source_joins_an_iri_already_minted() -> None:
    known = registry((row(f"{BASE}concepts/{CUSTOMER_UUID}"),))
    shared = Entity(
        source_refs={SOURCE: CUSTOMER_UUID, "collibra": "CUST"},
        pref_label="Customer",
        schemes=("sales",),
    )

    iri = known.iri_for(shared)

    assert iri == f"{BASE}concepts/{CUSTOMER_UUID}"
    assert [r.source_name for r in known.minted] == ["collibra"]


def test_two_source_keys_colliding_on_one_iri_are_refused() -> None:
    """Spec 5.4: CI fails if a run would produce an IRI collision.

    Two schemes configured with one slug is the realistic way to arrive here, and it must
    not resolve to one node wearing two labels.
    """
    fresh = registry()
    fresh.iri_for(scheme(slug="sales", key="1234"))

    with pytest.raises(IdentityError, match="already belongs to"):
        fresh.iri_for(scheme(slug="sales", key="9999"))


def test_an_object_whose_refs_hold_two_iris_is_refused() -> None:
    """The sources say one object; the map already minted two. Only a steward can choose."""
    known = registry(
        (
            row(f"{BASE}concepts/{CUSTOMER_UUID}"),
            row(f"{BASE}concepts/{ORDER_UUID}", source="collibra", key="CUST"),
        )
    )
    merged = Entity(
        source_refs={SOURCE: CUSTOMER_UUID, "collibra": "CUST"},
        pref_label="Customer",
        schemes=("sales",),
    )

    with pytest.raises(IdentityError, match=r"merges\.csv"):
        known.iri_for(merged)


def test_a_source_key_that_changes_kind_is_refused() -> None:
    """The map is keyed by source and key alone; a kind change would reuse another
    kind's IRI (spec 5.4)."""
    known = registry((row(f"{BASE}schemes/sales", Kind.SCHEME, key="1234"),))

    with pytest.raises(IdentityError, match="recorded as a scheme"):
        known.iri_for(entity(key="1234"))


def test_resolve_covers_every_object_in_the_model() -> None:
    model = InternalModel(entities=(entity(),), schemes=(scheme(),), taxonomy_values=(value(),))
    fresh = registry()

    resolved = fresh.resolve(model)

    assert set(resolved) == set(model.objects)
    assert len(set(resolved.values())) == 3
    assert len(fresh.id_map) == 3


def test_a_second_run_over_an_unchanged_model_appends_nothing() -> None:
    """The property every scheduled compile depends on: no diff from a no-op run."""
    model = InternalModel(entities=(entity(),), schemes=(scheme(),), taxonomy_values=(value(),))
    first = registry()
    first.resolve(model)

    second = Registry(IdMap(first.id_map.rows), BASE, today=datetime.date(2027, 1, 1))
    second.resolve(model)

    assert second.minted == ()
    assert second.id_map.dumps() == first.id_map.dumps()


def test_nothing_reaches_the_file_until_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What makes ``--dry-run`` and a mid-pipeline failure safe (spec 5.1).

    The working directory is moved to the temp path as well as the save target: commands
    operate on the working directory (spec 5.1), so a stray write with no argument lands
    there, and a test that only watched its own argument would call that "wrote nothing".
    """
    monkeypatch.chdir(tmp_path)
    fresh = registry()
    fresh.iri_for(entity())

    assert list(tmp_path.iterdir()) == []

    fresh.save(tmp_path)

    assert (tmp_path / ID_MAP_PATH).exists()


def test_registry_load_verifies_the_namespace_lock(instance: Path) -> None:
    """There must be no way to obtain a registry that mints under an unlocked base IRI."""
    loaded = config.load(instance)
    changed = InstanceConfig(
        base_iri="https://elsewhere.example.com/",
        instance_id=loaded.instance_id,
        repo_root=instance,
    )

    with pytest.raises(NamespaceLockError):
        Registry.load(changed)


# ------------------------------------------------------------------------ the ID map file


def test_the_map_round_trips() -> None:
    rows = (
        row(f"{BASE}concepts/{CUSTOMER_UUID}"),
        IdMapRow(
            iri=f"{BASE}schemes/sales",
            kind=Kind.SCHEME,
            source_name=SOURCE,
            source_key="1234",
            first_seen=datetime.date(2026, 1, 2),
            note="renamed from 'Sales', 2026-03; slug kept",
        ),
    )

    assert IdMap.loads(IdMap(rows).dumps()).rows == rows


def test_the_map_is_written_with_lf_endings(tmp_path: Path) -> None:
    """The same trap the serializer has: a platform default would make one map two files."""
    IdMap((row(f"{BASE}concepts/{CUSTOMER_UUID}"),)).save(tmp_path)

    written = (tmp_path / ID_MAP_PATH).read_bytes()

    assert b"\r" not in written
    assert written.endswith(b"\n")


def test_the_header_is_exactly_the_spec_columns() -> None:
    assert IdMap().dumps() == ",".join(ID_MAP_COLUMNS) + "\n"


def test_a_missing_map_is_an_empty_map(tmp_path: Path) -> None:
    """A freshly initialized instance mints everything it sees."""
    assert len(IdMap.load(tmp_path)) == 0


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(IdentityError, match="header"):
        IdMap.loads("")


def test_renamed_or_reordered_columns_are_refused() -> None:
    with pytest.raises(IdentityError, match="columns"):
        IdMap.loads("iri,kind,source,source_key,first_seen,note\n")


def test_every_bad_row_is_reported_at_once() -> None:
    """One problem per run costs a CI round trip each (the rule config already follows)."""
    with pytest.raises(IdentityError) as raised:
        IdMap.loads(
            textwrap.dedent(f"""\
            {",".join(ID_MAP_COLUMNS)}
            {BASE}concepts/a,entity,{SOURCE},a,not-a-date,
            {BASE}concepts/b,widget,{SOURCE},b,2026-08-06,
            ,entity,{SOURCE},c,2026-08-06,
            """)
        )

    assert len(raised.value.issues) == 3
    assert [issue.location for issue in raised.value.issues] == ["row 2", "row 3", "row 4"]


def test_an_unknown_kind_is_refused() -> None:
    """A kind this version does not know means the file was written by one that mints
    differently; guessing would put the wrong namespace on the next new object."""
    error = _rejected(f"{BASE}concepts/a,widget,{SOURCE},a,2026-08-06,")

    assert "unknown kind" in str(error)


def test_a_short_row_is_refused() -> None:
    error = _rejected(f"{BASE}concepts/a,entity,{SOURCE},a")

    assert "expected 6 columns" in str(error)


def test_a_row_with_no_iri_is_refused() -> None:
    error = _rejected(f",entity,{SOURCE},a,2026-08-06,")

    assert "'iri' must not be empty" in str(error)


def test_a_source_name_holding_a_colon_is_refused() -> None:
    """It would make ``sem:sourceRef`` ambiguous to split back apart (spec 3.3)."""
    error = _rejected(f"{BASE}concepts/a,entity,ellie:main,a,2026-08-06,")

    assert "':'" in str(error)


def test_a_duplicate_key_in_the_file_is_refused() -> None:
    """Even a byte-identical repeat: collapsing it would delete a line from the next PR."""
    error = _rejected(
        f"{BASE}concepts/a,entity,{SOURCE},a,2026-08-06,",
        f"{BASE}concepts/a,entity,{SOURCE},a,2026-08-06,",
    )

    assert "already mapped" in str(error)


def test_one_iri_recorded_as_two_kinds_is_refused() -> None:
    error = _rejected(
        f"{BASE}concepts/a,entity,{SOURCE},a,2026-08-06,",
        f"{BASE}concepts/a,attribute,{SOURCE},b,2026-08-06,",
    )

    assert "one IRI is one object" in str(error)


def test_a_note_holding_a_comma_survives_a_round_trip() -> None:
    noted = IdMapRow(
        iri=f"{BASE}concepts/{CUSTOMER_UUID}",
        kind=Kind.ENTITY,
        source_name=SOURCE,
        source_key=CUSTOMER_UUID,
        first_seen=TODAY,
        note='merged, see PR #12 — "the second Customer"',
    )

    assert IdMap.loads(IdMap((noted,)).dumps()).rows == (noted,)


def test_rows_keep_the_order_the_file_holds_them_in() -> None:
    """Append-only means the file is a history: existing lines never move."""
    rows = tuple(row(f"{BASE}concepts/{n}", key=f"key-{n}") for n in ("c", "a", "b"))

    assert IdMap.loads(IdMap(rows).dumps()).rows == rows


def _rejected(*lines: str) -> IdentityError:
    """Load an ID map body expecting it to be refused, and return the refusal."""
    with pytest.raises(IdentityError) as raised:
        IdMap.loads("\n".join([",".join(ID_MAP_COLUMNS), *lines]) + "\n")
    return raised.value


# ------------------------------------------------------------------- append-only checks


def test_a_removed_row_is_detected_against_the_base_revision() -> None:
    """Spec 6.1 check 6. A dropped row is an IRI that lost its meaning, and the next run
    would mint a second one for the same object."""
    base = IdMap((row(f"{BASE}concepts/{CUSTOMER_UUID}"), row(f"{BASE}concepts/x", key="x")))
    current = IdMap((row(f"{BASE}concepts/{CUSTOMER_UUID}"),))

    issues = current.check_append_only(base)

    assert len(issues) == 1
    assert issues[0].location == f"{SOURCE}:x"
    assert "append-only" in issues[0].message


def test_a_rewritten_row_is_detected() -> None:
    base = IdMap((row(f"{BASE}concepts/{CUSTOMER_UUID}"),))
    current = IdMap((row(f"{BASE}concepts/something-else"),))

    issues = current.check_append_only(base)

    assert len(issues) == 1
    assert "never rewritten" in issues[0].message


def test_appending_rows_is_not_a_violation() -> None:
    base = IdMap((row(f"{BASE}concepts/{CUSTOMER_UUID}"),))
    current = IdMap((row(f"{BASE}concepts/{CUSTOMER_UUID}"), row(f"{BASE}concepts/x", key="x")))

    assert current.check_append_only(base) == ()


def test_a_source_name_absent_from_configuration_is_an_error() -> None:
    """Spec 5.4: renaming a configured source breaks every lookup in the map."""
    map_ = IdMap((row(f"{BASE}concepts/{CUSTOMER_UUID}"),))

    assert map_.check_sources_are_configured({SOURCE}) == ()
    issues = map_.check_sources_are_configured({"ellie-primary"})
    assert len(issues) == 1
    assert SOURCE in issues[0].message


# ------------------------------------------------------------------------ namespace lock


def lock(base_iri: str = BASE, instance_id: str = "acme") -> NamespaceLock:
    return NamespaceLock(
        base_iri=base_iri, instance_id=instance_id, ontology_version="0.1.0", date=TODAY
    )


def test_the_lock_round_trips() -> None:
    assert NamespaceLock.loads(lock().dumps()) == lock()


def test_the_lock_is_written_with_lf_endings(tmp_path: Path) -> None:
    lock().save(tmp_path)

    written = (tmp_path / NAMESPACE_LOCK_PATH).read_bytes()

    assert b"\r" not in written
    assert written.endswith(b"\n")


def test_the_fixture_instance_is_locked_to_its_configured_base_iri(instance: Path) -> None:
    loaded = config.load(instance)

    assert identity.verify_namespace_lock(loaded).base_iri == loaded.base_iri


def test_a_missing_lock_is_refused(tmp_path: Path) -> None:
    """Deleting the file must not be a way around a permanent decision."""
    with pytest.raises(NamespaceLockError, match="no namespace lock"):
        NamespaceLock.load(tmp_path)


def test_a_changed_base_iri_is_refused() -> None:
    """Spec 3.4.4: the failure the lock exists to prevent."""
    with pytest.raises(NamespaceLockError, match="migration, not a configuration edit"):
        lock().verify(InstanceConfig(base_iri="https://elsewhere.example.com/", instance_id="acme"))


def test_a_changed_instance_id_is_refused() -> None:
    with pytest.raises(NamespaceLockError, match="instance id"):
        lock().verify(InstanceConfig(base_iri=BASE, instance_id="acme-new"))


def test_the_ontology_version_is_recorded_but_not_compared() -> None:
    """Upgrading the metamodel is expected; the manifest's drift check governs it, not
    this file (spec 6.1 check 3)."""
    old = NamespaceLock(
        base_iri=BASE, instance_id="acme", ontology_version="0.0.1-alpha", date=TODAY
    )

    old.verify(InstanceConfig(base_iri=BASE, instance_id="acme"))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("not json", "not valid JSON"),
        ("[]", "must be a JSON object"),
        ('{"instance_id": "acme", "ontology_version": "0.1.0", "date": "2026-08-06"}', "base_iri"),
        (
            '{"base_iri": "x", "instance_id": "acme", "ontology_version": "0.1.0",'
            ' "date": "the sixth"}',
            "YYYY-MM-DD",
        ),
    ],
    ids=["not-json", "not-an-object", "missing-key", "bad-date"],
)
def test_an_unusable_lock_is_refused(text: str, expected: str) -> None:
    with pytest.raises(NamespaceLockError, match=expected):
        NamespaceLock.loads(text)


# --------------------------------------------------------------------- the CLI contract


@pytest.mark.parametrize(
    "argv", [["run"], ["check"], ["migrate", "--to", "0.2.0"]], ids=lambda argv: argv[0]
)
def test_a_base_iri_mismatch_exits_2(argv: list[str], instance: Path) -> None:
    """Spec 5.1: a namespace-lock error is exit 2, the same code as a configuration error.

    Every command that reads the instance checks it — a mismatch must not be something a
    run can walk past on the way to minting.
    """
    _rewrite_base_iri(instance, "https://elsewhere.example.com/")

    assert main(argv) == ExitCode.CONFIG


def test_a_missing_lock_exits_2(instance: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (instance / NAMESPACE_LOCK_PATH).unlink()

    assert main(["run"]) == ExitCode.CONFIG
    assert "no namespace lock" in capsys.readouterr().err


def test_the_mismatch_message_names_the_key_and_the_way_out(
    instance: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _rewrite_base_iri(instance, "https://elsewhere.example.com/")

    main(["check"])

    err = capsys.readouterr().err
    assert "base_iri" in err
    assert "--force-namespace-change" in err


def test_force_namespace_change_is_the_one_run_the_lock_does_not_stop(
    instance: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 1 ("not implemented", task E2) rather than 2: the lock check was skipped."""
    _rewrite_base_iri(instance, "https://elsewhere.example.com/")

    assert main(["run", "--force-namespace-change"]) == ExitCode.FAILURE
    assert "not implemented" in capsys.readouterr().err


def _rewrite_base_iri(root: Path, base_iri: str) -> None:
    path = root / config.CONFIG_PATH
    path.write_text(
        path.read_text(encoding="utf-8").replace(BASE, base_iri), encoding="utf-8", newline="\n"
    )


# ------------------------------------------------------------------ moving the namespace


def test_force_namespace_change_rewrites_map_and_lock_together(instance: Path) -> None:
    """Spec 3.4.4. Local names survive the move — the same object, in a new namespace."""
    IdMap(
        (
            row(f"{BASE}concepts/{CUSTOMER_UUID}"),
            IdMapRow(
                iri=f"{BASE}schemes/sales",
                kind=Kind.SCHEME,
                source_name=SOURCE,
                source_key="1234",
                first_seen=TODAY,
                note="keep me",
            ),
        )
    ).save(instance)
    moved_to = "https://vocab.example.org/"
    _rewrite_base_iri(instance, moved_to)

    changed, moved = identity.force_namespace_change(
        config.load(instance), ontology_version="0.1.0", today=TODAY
    )

    assert changed.base_iri == moved_to
    assert [r.iri for r in moved] == [
        f"{moved_to}concepts/{CUSTOMER_UUID}",
        f"{moved_to}schemes/sales",
    ]
    # Written, not merely returned: the two files must never disagree.
    assert NamespaceLock.load(instance) == changed
    assert IdMap.load(instance).rows == moved.rows
    assert moved.rows[1].note == "keep me"
    assert moved.rows[1].first_seen == TODAY


def test_the_moved_instance_then_verifies_against_its_new_lock(instance: Path) -> None:
    _rewrite_base_iri(instance, "https://vocab.example.org/")
    identity.force_namespace_change(config.load(instance), ontology_version="0.1.0", today=TODAY)

    identity.verify_namespace_lock(config.load(instance))


def test_an_iri_outside_the_locked_base_stops_the_move(instance: Path) -> None:
    """Leaving it behind would split the instance across two namespaces."""
    IdMap((row("https://somewhere.else/concepts/x", key="x"),)).save(instance)
    _rewrite_base_iri(instance, "https://vocab.example.org/")

    with pytest.raises(IdentityError, match="not under the locked base IRI"):
        identity.force_namespace_change(config.load(instance), ontology_version="0.1.0")


# --------------------------------------------------------- determinism across processes

_MINT_SCRIPT = """
import datetime, json, random, sys
from semprini.identity import IdMap, Registry
from semprini.model import Entity, InternalModel, Scheme, SchemeType, TaxonomyValue, merge_models

seed = int(sys.argv[1])
entities = [
    Entity(source_refs={"ellie-main": f"entity-{n}"}, pref_label=f"E{n}", schemes=("sales",))
    for n in range(12)
]
schemes = [
    Scheme(
        source_refs={"ellie-main": f"model-{n}"},
        pref_label=f"S{n}",
        slug=f"scheme-{n}",
        scheme_type=SchemeType.GLOSSARY,
    )
    for n in range(6)
]
values = [
    TaxonomyValue(
        source_refs={"taxonomies": f"row-{n}"},
        pref_label=f"V{n}",
        code=f"C{n}",
        schemes=("product-category",),
    )
    for n in range(12)
]
shuffle = random.Random(seed).shuffle
for group in (entities, schemes, values):
    shuffle(group)

model = merge_models(
    InternalModel(entities=tuple(entities), schemes=tuple(schemes), taxonomy_values=tuple(values))
)
registry = Registry(
    IdMap(), "https://semantics.example.com/", today=datetime.date(2026, 8, 6)
)
registry.resolve(model)
json.dump([list(row.values) for row in registry.id_map], sys.stdout)
"""


def _mint_in_a_subprocess(*, hash_seed: str, shuffle_seed: int) -> str:
    environment = {**os.environ, "PYTHONHASHSEED": hash_seed}
    completed = subprocess.run(
        [sys.executable, "-c", _MINT_SCRIPT, str(shuffle_seed)],
        capture_output=True,
        text=True,
        env=environment,
        check=True,
    )
    return completed.stdout


def test_minting_is_stable_across_processes() -> None:
    """Two machines compiling the same sources must mint the same IRIs — and record them
    in the same order, since the ID map is committed and diffed (spec 5.1, 5.5).

    Run out of process because that is the only way to vary ``PYTHONHASHSEED``: set
    inside a running interpreter it does nothing, and a dependency on set or dict
    iteration order is exactly the bug that would otherwise survive a whole test suite
    and then reorder a file on someone else's laptop.
    """
    first = _mint_in_a_subprocess(hash_seed="0", shuffle_seed=1)
    second = _mint_in_a_subprocess(hash_seed="12345", shuffle_seed=2)
    third = _mint_in_a_subprocess(hash_seed="98765", shuffle_seed=3)

    assert first == second == third
    # Guards the guard: three identical empty outputs would also pass the line above.
    rows = json.loads(first)
    assert len(rows) == 30
    assert len({recorded[0] for recorded in rows}) == 30

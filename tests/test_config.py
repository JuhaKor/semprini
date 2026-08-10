"""Instance configuration loading and validation (spec 5.1).

Two things are being pinned here. First, that every rejection names the key that caused
it: the audience is an operator reading a CI log, and "configuration error" without a key
costs a round trip per mistake. Second, that a credential can neither be written into the
file nor end up inside a loaded configuration object — the file is committed to a
repository and the object is printed into reports.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from semprini import config
from semprini.cli import ExitCode, main
from semprini.config import ConfigError, SourceConfig

VALID = """
    semprini:
      base_iri: https://semantics.example.com/
      instance_id: acme
      default_language: en

    sources:
      - adapter: ellie
        name: ellie-main
        config:
          base_url: https://acme.ellie.ai/api/v1
          token_env: ELLIE_API_TOKEN
          models:
            - id: 1234
              scheme_slug: sales
    """

ADAPTERS = frozenset({"ellie", "excel-taxonomy"})


def load_text(text: str, *, known_adapters: frozenset[str] | None = None) -> config.InstanceConfig:
    return config.loads(
        textwrap.dedent(text), origin="config/semprini.yaml", known_adapters=known_adapters
    )


def rejection(text: str, *, known_adapters: frozenset[str] | None = None) -> ConfigError:
    """Load ``text`` expecting it to be refused, and return the refusal."""
    with pytest.raises(ConfigError) as raised:
        load_text(text, known_adapters=known_adapters)
    return raised.value


# ---------------------------------------------------------------- loading what is valid


def test_the_fixture_instance_loads(instance: Path) -> None:
    loaded = config.load(instance)

    assert loaded.base_iri == "https://semantics.example.com/"
    assert loaded.instance_id == "acme"
    assert loaded.default_language == "en"
    assert [source.name for source in loaded.sources] == ["ellie-main", "product-category"]
    assert [source.adapter for source in loaded.sources] == ["ellie", "excel-taxonomy"]
    # One Ellie instance is one source, holding its allowlist of models; one workbook is
    # one source, so its settings are flat — a path and the scheme slug (spec 5.3).
    ellie, taxonomy = loaded.sources
    assert [model["id"] for model in ellie.settings["models"]] == [70337]
    assert taxonomy.settings["scheme_slug"] == "product-category"
    assert taxonomy.settings["path"] == "sources/taxonomies/product-category.xlsx"


def test_the_spec_example_loads() -> None:
    """The configuration printed in spec 5.1 must be one the compiler accepts."""
    loaded = load_text(VALID, known_adapters=ADAPTERS)

    assert loaded.sources[0].adapter == "ellie"
    assert loaded.sources[0].settings["models"][0]["id"] == 1234


def test_an_instance_with_no_sources_loads() -> None:
    """`semprini init` writes an empty sources list (spec 5.7 step 2); it must load."""
    loaded = load_text("""
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        """)

    assert loaded.sources == ()
    # Omitted rather than absent: the language has a default (spec 11 #5).
    assert loaded.default_language == config.DEFAULT_LANGUAGE


def test_adapter_settings_are_read_only() -> None:
    """An adapter may read its configuration and must not be able to edit it (spec 5.2).

    Written inline rather than read from the fixture instance: this is about how *any*
    adapter's subtree is frozen, and the fixture's own is now flat, so leaning on it would
    stop exercising the nested case the moment its shape changed — which is exactly what
    happened when D2 gave each workbook its own source.
    """
    settings = (
        load_text("""
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: excel-taxonomy
            name: taxonomies
            config:
              files:
                - path: sources/taxonomies/a.xlsx
    """)
        .sources[0]
        .settings
    )

    assert isinstance(settings["files"], tuple)
    with pytest.raises(TypeError):
        settings["files"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        settings["files"][0]["path"] = "elsewhere"


def test_a_missing_configuration_names_the_path_and_the_remedy(tmp_path: Path) -> None:
    error = None
    try:
        config.load(tmp_path)
    except ConfigError as raised:
        error = raised

    assert error is not None
    assert "semprini.yaml" in str(error)
    assert "semprini init" in str(error)


# --------------------------------------------------------------- rejecting what is not

MALFORMED = [
    pytest.param(
        """
        semprini:
          instance_id: acme
        """,
        "semprini.base_iri",
        id="missing base IRI",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com
          instance_id: acme
        """,
        "semprini.base_iri",
        id="base IRI without a trailing slash",
    ),
    pytest.param(
        """
        semprini:
          base_iri: semantics.example.com/
          instance_id: acme
        """,
        "semprini.base_iri",
        id="base IRI that is not http(s)",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com/
        """,
        "semprini.instance_id",
        id="missing instance id",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: Acme Corp
        """,
        "semprini.instance_id",
        id="instance id that is not a slug",
    ),
    pytest.param(
        """
        sources: []
        """,
        "semprini",
        id="missing semprini section",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
          defualt_language: en
        """,
        "semprini.defualt_language",
        id="misspelled key",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
          default_language: english
        """,
        "semprini.default_language",
        id="not a language tag",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sorces: []
        """,
        "sorces",
        id="misspelled top-level key",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          adapter: ellie
        """,
        "sources",
        id="sources that is not a list",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: ellie
            name: ellie-main
          - adapter: excel-taxonomy
            name: ellie-main
        """,
        "sources[1].name",
        id="duplicate source name",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: ellie
        """,
        "sources[0].name",
        id="source without a name",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: ellie
            name: ellie-main
            confg: {}
        """,
        "sources[0].confg",
        id="misspelled source key",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: ellie
            name: ellie-main
            config:
              token: sk-live-1a2b3c4d
        """,
        "sources[0].config.token",
        id="credential written inline",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: ellie
            name: ellie-main
            config:
              auth:
                api_key: sk-live-1a2b3c4d
        """,
        "sources[0].config.auth.api_key",
        id="credential nested in the adapter's own subtree",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: excel-taxonomy
            name: taxonomies
            config:
              files:
                - path: sources/taxonomies/a.xlsx
                  password: hunter2
        """,
        "sources[0].config.files[0].password",
        id="credential inside a list of mappings",
    ),
    pytest.param(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: ellie
            name: ellie-main
            config:
              token_env: sk-live-1a2b3c4d
        """,
        "sources[0].config.token_env",
        id="credential pasted into the variable-name field",
    ),
]


@pytest.mark.parametrize(("text", "location"), MALFORMED)
def test_malformed_configuration_is_rejected_by_key(text: str, location: str) -> None:
    error = rejection(text)

    assert location in str(error), str(error)
    assert any(issue.location == location for issue in error.issues), error.issues


def test_an_unknown_adapter_is_rejected_when_the_installed_set_is_known() -> None:
    error = rejection(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: colibra
            name: glossary
        """,
        known_adapters=ADAPTERS,
    )

    assert "sources[0].adapter" in str(error)
    assert "colibra" in str(error)
    # The remedy is in the message: which adapters this installation actually has.
    assert "excel-taxonomy" in str(error)


def test_adapters_are_not_checked_when_the_installed_set_is_unknown() -> None:
    """Discovery is task D1's; until it lands, checking against nothing would reject all."""
    loaded = load_text(
        """
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: not-installed-anywhere
            name: glossary
        """
    )

    assert loaded.sources[0].adapter == "not-installed-anywhere"


def test_every_error_is_reported_at_once() -> None:
    """One run must surface every mistake, not the first (spec 5.1: exit 2 with a message)."""
    error = rejection(
        """
        semprini:
          base_iri: not-an-iri
          instance_id: Acme Corp
          default_language: english
        """
    )

    assert {issue.location for issue in error.issues} == {
        "semprini.base_iri",
        "semprini.instance_id",
        "semprini.default_language",
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("semprini: [", "not valid YAML", id="syntax error"),
        pytest.param("", "empty", id="empty file"),
        pytest.param("- a\n- list\n", "must be a mapping", id="not a mapping"),
    ],
)
def test_unusable_documents_are_rejected(text: str, expected: str) -> None:
    assert expected in str(rejection(text))


def test_a_duplicate_yaml_key_is_rejected() -> None:
    """YAML's own rule is last-one-wins, which would silently discard a configured value."""
    error = rejection("""
        semprini:
          base_iri: https://semantics.example.com/
          base_iri: https://semantics.elsewhere.example/
          instance_id: acme
        """)

    assert "duplicate key" in str(error)
    assert "base_iri" in str(error)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("semprini:\n  ? [a, b]\n  : c\n", id="unhashable key"),
        pytest.param("semprini:\n  ? {a: b}\n  : c\n", id="mapping as a key"),
    ],
)
def test_an_unusable_yaml_key_is_still_a_configuration_error(text: str) -> None:
    """The duplicate-key scan must not turn a YAML problem into an escaping TypeError."""
    assert "not valid YAML" in str(rejection(text))


def test_yaml_merge_keys_still_work() -> None:
    """Anchors are how an operator shares settings between sources; SafeLoader allows
    them, and overriding a merged value is the entire point of a merge."""
    loaded = load_text("""
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - &defaults
            adapter: ellie
            name: ellie-main
            config:
              base_url: https://acme.ellie.ai/api/v1
          - <<: *defaults
            name: ellie-archive
        """)

    assert [source.name for source in loaded.sources] == ["ellie-main", "ellie-archive"]
    assert loaded.sources[1].settings["base_url"] == "https://acme.ellie.ai/api/v1"


def test_a_file_that_is_not_utf8_is_a_configuration_error(instance: Path) -> None:
    """An editor saving in the system codepage is an ordinary mistake, not a traceback."""
    (instance / config.CONFIG_PATH).write_bytes(
        "semprini:\n  instance_id: acme\n  base_iri: https://sem\xe4ntics.example.com/\n".encode(
            "latin-1"
        )
    )

    with pytest.raises(ConfigError) as raised:
        config.load(instance)

    assert "UTF-8" in str(raised.value)


def test_a_yaml_error_reports_where() -> None:
    """A syntax error must point at a line: YAML indentation mistakes are invisible."""
    error = rejection("semprini:\n  instance_id: acme\n    base_iri: https://x.example/\n")

    assert "line 3" in str(error)


# ------------------------------------------------------------------------- credentials


def test_keys_that_merely_look_credential_shaped_are_left_alone() -> None:
    """The rule must not reject legitimate configuration: it is matched per key segment."""
    loaded = load_text("""
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: ellie
            name: ellie-main
            config:
              base_url: https://acme.ellie.ai/api/v1
              source_key_column: code
              keychain_path: ignored
              env: staging
              token_env: ELLIE_API_TOKEN
        """)

    assert loaded.sources[0].settings["token_env"] == "ELLIE_API_TOKEN"
    # `env` on its own is an ordinary setting, not a variable name to be shaped.
    assert loaded.sources[0].settings["env"] == "staging"


@pytest.mark.parametrize(
    "key", ["accessToken", "clientSecret", "apiKey", "bearerToken", "adminPassword"]
)
def test_a_camel_case_credential_key_is_rejected_too(key: str) -> None:
    """The guard must depend on what a key means, not on an adapter author's style."""
    error = rejection(f"""
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: ellie
            name: ellie-main
            config:
              {key}: sk-live-1a2b3c4d
        """)

    assert f"sources[0].config.{key}" in str(error)


def test_a_camel_case_variable_name_is_accepted() -> None:
    loaded = load_text("""
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: ellie
            name: ellie-main
            config:
              tokenEnv: ELLIE_API_TOKEN
        """)

    assert loaded.sources[0].secret("tokenEnv", environ={"ELLIE_API_TOKEN": "x"}) == "x"


def test_a_credential_nested_in_lists_of_lists_is_rejected() -> None:
    """Every container is descended: a secret is no less committed two lists down."""
    error = rejection("""
        semprini:
          base_iri: https://semantics.example.com/
          instance_id: acme
        sources:
          - adapter: ellie
            name: ellie-main
            config:
              matrix:
                - - token: sk-live-1a2b3c4d
        """)

    assert "sources[0].config.matrix[0][0].token" in str(error)


def test_a_source_is_hashable(instance: Path) -> None:
    """Frozen has to mean usable in a set: the ID map and lifecycle both group sources."""
    source = config.load(instance).sources[0]
    same = config.load(instance).sources[0]

    assert source == same
    assert len({source, same}) == 1


def test_a_credential_is_read_from_the_environment_and_never_stored() -> None:
    loaded = load_text(VALID, known_adapters=ADAPTERS)
    source = loaded.sources[0]

    assert source.secret(environ={"ELLIE_API_TOKEN": "sk-live-1a2b3c4d"}) == "sk-live-1a2b3c4d"
    # The configuration holds the variable's name and nothing else — these objects are
    # printed into run reports and exception messages.
    assert "sk-live-1a2b3c4d" not in repr(loaded)
    assert "sk-live-1a2b3c4d" not in repr(source.settings)


def test_a_source_that_configures_no_credential_has_none() -> None:
    source = SourceConfig(adapter="excel-taxonomy", name="taxonomies", settings={})

    assert source.secret(environ={}) is None


@pytest.mark.parametrize("environ", [{}, {"ELLIE_API_TOKEN": ""}], ids=["unset", "empty"])
def test_an_unset_credential_is_a_configuration_error(environ: dict[str, str]) -> None:
    """Exit 2, not 3: the operator forgot a secret, the source is not unreachable."""
    source = load_text(VALID, known_adapters=ADAPTERS).sources[0]

    with pytest.raises(ConfigError) as raised:
        source.secret(environ=environ)

    assert "ELLIE_API_TOKEN" in str(raised.value)
    assert "ellie-main" in str(raised.value)


def test_the_default_credential_lookup_reads_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELLIE_API_TOKEN", "sk-live-from-the-environment")
    source = load_text(VALID, known_adapters=ADAPTERS).sources[0]

    assert source.secret() == "sk-live-from-the-environment"


# ---------------------------------------------------------------------- the run context


def test_the_run_context_carries_the_configured_instance(instance: Path) -> None:
    loaded = config.load(instance)

    context = loaded.run_context(only_source="product-category", dry_run=True)

    assert context.base_iri == loaded.base_iri
    assert context.instance_id == "acme"
    assert context.default_language == "en"
    assert context.repo_root == instance
    assert context.only_source == "product-category"
    assert context.dry_run is True


def test_an_unknown_source_is_a_configuration_error(instance: Path) -> None:
    """`--source` with a typo would otherwise compile nothing and exit 0."""
    loaded = config.load(instance)

    with pytest.raises(ConfigError) as raised:
        loaded.run_context(only_source="product-categories")

    assert "product-categories" in str(raised.value)
    # And what *is* configured, or a typo and a source nobody added look identical.
    assert "configured: ellie-main, product-category" in str(raised.value)


# -------------------------------------------------------------------------- through CLI


@pytest.mark.parametrize("command", [["run"], ["check"], ["migrate", "--to", "0.2.0"]])
def test_a_broken_configuration_exits_2_naming_the_key(
    command: list[str], instance: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (instance / config.CONFIG_PATH).write_text(
        textwrap.dedent("""
            semprini:
              base_iri: https://semantics.example.com/
              instance_id: acme
            sources:
              - adapter: excel-taxonomy
                name: taxonomies
                config:
                  api_key: sk-live-1a2b3c4d
            """),
        encoding="utf-8",
    )

    assert main(command) == ExitCode.CONFIG

    err = capsys.readouterr().err
    assert "sources[0].config.api_key" in err
    # The remedy, not just the refusal.
    assert "environment variable" in err


def test_an_unknown_source_argument_exits_2(
    instance: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["run", "--source", "taxonomy"]) == ExitCode.CONFIG
    assert "taxonomy" in capsys.readouterr().err


def test_commands_that_do_not_read_an_instance_ignore_a_broken_configuration(
    instance: Path,
) -> None:
    """`init` writes the configuration; `version` and `adapters` describe the installation."""
    (instance / config.CONFIG_PATH).write_text("semprini: [", encoding="utf-8")

    assert main(["version"]) == ExitCode.OK
    # Not exit 2: `adapters` answers a question about the machine, and an instance whose
    # configuration is broken is exactly when an operator asks it (spec 5.1).
    assert main(["adapters"]) == ExitCode.OK

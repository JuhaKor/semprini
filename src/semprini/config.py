"""Instance configuration — ``config/semprini.yaml`` (spec 5.1).

The first thing every command does, and therefore the first thing that can go wrong. A
mistake here is a *configuration* error (exit code 2), reported with the key that caused
it: an instance operator editing YAML in a CI log deserves ``sources[1].name`` and not a
traceback from three stages later.

Two rules shape the module.

*Credentials never enter configuration* (spec 5.1). A source names an environment
variable — ``token_env`` — and the value is read from the environment at fetch time by
:meth:`SourceConfig.secret`. Nothing in this module stores a secret, so a config object
is safe to log, and a config file with a token written into it is **rejected** rather
than quietly honoured.

*Everything reportable is reported.* Validation collects issues rather than raising at
the first one, so an operator fixing a fresh config sees every problem in one run
instead of one per attempt.
"""

from __future__ import annotations

import itertools
import os
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from semprini import serialize
from semprini.model import Issue, RunContext, Severity, is_language_tag

__all__ = [
    "CONFIG_PATH",
    "DEFAULT_LANGUAGE",
    "ConfigError",
    "InstanceConfig",
    "SourceConfig",
    "load",
    "loads",
]

CONFIG_PATH = Path("config") / "semprini.yaml"
"""Where an instance keeps its configuration (spec 4.2). Commands operate on the
working directory (spec 5.1), so this is always relative to the repository root."""

DEFAULT_LANGUAGE = "en"
"""Applied where a label carries no language of its own (spec 5.5 rule 6, 11 #5)."""

_TOP_LEVEL_KEYS = frozenset({"semprini", "sources"})
_INSTANCE_KEYS = frozenset({"base_iri", "instance_id", "default_language"})
_SOURCE_KEYS = frozenset({"adapter", "name", "config"})

# A slug: what an instance id and a source name may look like. Both end up in file
# names, IRIs and the ID map's columns, so they stay to characters that need no
# escaping anywhere (spec 5.4).
_SLUG = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")

# The shape of an environment variable name, as opposed to the value of one. A
# `token_env` holding `sk-live-...` is a credential written into configuration by an
# operator who misread the field, which is the mistake this catches.
_ENV_VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Key segments that name a credential rather than an address. Matched per segment so
# `base_url` and `source_key` pass while `api_key` and `auth_token` do not.
_CREDENTIAL_WORDS = frozenset(
    {"token", "secret", "password", "passwd", "pwd", "credential", "credentials", "apikey"}
)
_CREDENTIAL_PAIRS = frozenset({("api", "key"), ("access", "key"), ("private", "key")})

# The escape hatch, and the only one: a key ending in `_env` names an environment
# variable, so `token_env` is exactly how a credential is *supposed* to be configured.
_ENV_SUFFIX = "env"

# Key separators. `accessToken` has to split the same way `access_token` does, or the
# guard would depend on an adapter author's naming style rather than on what the key
# means.
_KEY_SEPARATOR = re.compile(r"[-_]")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

_MERGE_TAG = "tag:yaml.org,2002:merge"


class ConfigError(ValueError):
    """Configuration the compiler refuses to run on — CLI exit code 2 (spec 5.1).

    Carries every issue found, not just the first: a half-fixed config file that fails
    again on the next key wastes a CI round trip per mistake.
    """

    def __init__(self, issues: Sequence[Issue], *, origin: str | None = None) -> None:
        self.issues = tuple(issues)
        self.origin = origin
        super().__init__(self._message())

    def _message(self) -> str:
        where = f"{self.origin}: " if self.origin else ""
        if len(self.issues) == 1:
            return f"{where}{self.issues[0]}"
        listed = "\n".join(f"  - {issue}" for issue in self.issues)
        return f"{where}{len(self.issues)} configuration errors\n{listed}"


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceConfig:
    """One entry of the ``sources:`` list (spec 5.1)."""

    adapter: str
    """Entry-point name of an installed adapter — the ``semprini.adapters`` group
    (spec 5.2)."""

    name: str
    """The source name. Appears in ``sem:sourceRef`` and in the ID map, and is assigned
    once and **never** changed or reused (spec 5.1, 5.4)."""

    settings: Mapping[str, Any] = field(default_factory=dict, hash=False)
    """The adapter's own ``config:`` subtree, passed through uninterpreted (spec 5.2).

    Deep-frozen — nested mappings are read-only and nested sequences are tuples — so an
    adapter cannot edit configuration that a later stage, or the run report, still reads.

    Excluded from the generated ``__hash__`` (but not from ``__eq__``) for the same
    reason as ``SemanticObject.source_refs``: a mapping is unhashable, and hashing it
    would leave a class advertised as frozen that cannot go in a set or key a dict.
    """

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", _freeze(dict(self.settings)))

    def secret(
        self, setting: str = "token_env", *, environ: Mapping[str, str] | None = None
    ) -> str | None:
        """Read the credential whose *variable name* is configured under ``setting``.

        Returns ``None`` when the source configures no such variable — plenty of sources
        need no credential. Raises :class:`ConfigError` when one is named but unset in
        the environment, since that is a configuration mistake (exit 2) and not an
        unreachable source (exit 3).

        The value is returned, never stored: it exists only in the caller's frame, so no
        config object, run report or exception message can leak it.
        """
        variable = self.settings.get(setting)
        if variable is None:
            return None
        environment = os.environ if environ is None else environ
        value = environment.get(str(variable))
        if not value:
            raise ConfigError(
                [
                    Issue(
                        Severity.ERROR,
                        f"environment variable {variable!r} is unset or empty; it holds "
                        f"the credential for source {self.name!r}",
                        # Named, not indexed: a source knows its name and not its
                        # position in a list it was loaded from.
                        f"sources.{self.name}.config.{setting}",
                    )
                ]
            )
        return value


@dataclass(frozen=True, slots=True, kw_only=True)
class InstanceConfig:
    """A validated ``config/semprini.yaml`` (spec 5.1)."""

    base_iri: str
    instance_id: str
    default_language: str = DEFAULT_LANGUAGE
    sources: tuple[SourceConfig, ...] = ()
    repo_root: Path = field(default_factory=Path.cwd)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sources", tuple(self.sources))

    def source(self, name: str) -> SourceConfig:
        """The configured source called ``name``."""
        for source in self.sources:
            if source.name == name:
                return source
        configured = ", ".join(source.name for source in self.sources) or "none"
        raise ConfigError(
            [
                Issue(
                    Severity.ERROR,
                    f"no source named {name!r} is configured (configured: {configured})",
                    "sources",
                )
            ]
        )

    def run_context(self, *, only_source: str | None = None, dry_run: bool = False) -> RunContext:
        """The :class:`~semprini.model.RunContext` this configuration describes.

        ``only_source`` is checked against the configured sources here: ``--source`` with
        a typo would otherwise compile nothing at all and exit 0, which reads as success.
        """
        if only_source is not None:
            self.source(only_source)
        return RunContext(
            base_iri=self.base_iri,
            instance_id=self.instance_id,
            repo_root=self.repo_root,
            default_language=self.default_language,
            only_source=only_source,
            dry_run=dry_run,
        )


def load(
    repo_root: Path | None = None, *, known_adapters: Collection[str] | None = None
) -> InstanceConfig:
    """Load and validate ``<repo_root>/config/semprini.yaml``.

    Raises :class:`ConfigError` — the CLI's exit code 2 — for anything unusable.
    """
    root = Path.cwd() if repo_root is None else Path(repo_root)
    path = root / CONFIG_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(
            [
                Issue(
                    Severity.ERROR,
                    f"no instance configuration at {path}; run 'semprini init' to create one",
                    CONFIG_PATH.as_posix(),
                )
            ]
        ) from None
    except UnicodeDecodeError:
        # A ValueError, not an OSError, so the handler below would miss it — and an
        # editor that saved the file in the system codepage is an ordinary mistake, not
        # a reason to show a traceback.
        raise ConfigError(
            [
                Issue(
                    Severity.ERROR,
                    "the configuration is not valid UTF-8; save it as UTF-8 and try again",
                    str(path),
                )
            ]
        ) from None
    except OSError as error:
        raise ConfigError(
            [Issue(Severity.ERROR, f"cannot read the configuration: {error}", str(path))]
        ) from None
    return loads(text, origin=str(path), repo_root=root, known_adapters=known_adapters)


def loads(
    text: str,
    *,
    origin: str | None = None,
    repo_root: Path | None = None,
    known_adapters: Collection[str] | None = None,
) -> InstanceConfig:
    """Validate configuration held in a string.

    ``known_adapters`` is injected rather than discovered: entry-point discovery is the
    adapter subsystem's job (spec 5.2, task D1), and this module must not grow a second
    copy of it. Passing ``None`` skips the adapter-name check — which is what a bare
    ``semprini check`` does today, since no adapter is registered yet.
    """
    document = _parse(text, origin)
    issues: list[Issue] = []

    _reject_unknown_keys(document, _TOP_LEVEL_KEYS, "", issues)
    instance = _section(document, "semprini", issues)
    _reject_unknown_keys(instance, _INSTANCE_KEYS, "semprini", issues)

    base_iri = _base_iri(instance, issues)
    instance_id = _slug(instance, "instance_id", "semprini.instance_id", issues)
    language = _language(instance, issues)
    sources = _sources(document, known_adapters, issues)

    if issues:
        raise ConfigError(issues, origin=origin)
    # Both are None only in cases that appended an issue, so with none left this holds.
    assert base_iri is not None and instance_id is not None
    return InstanceConfig(
        base_iri=base_iri,
        instance_id=instance_id,
        default_language=language,
        sources=sources,
        repo_root=Path.cwd() if repo_root is None else repo_root,
    )


class _StrictLoader(yaml.SafeLoader):
    """``SafeLoader`` that refuses duplicate mapping keys.

    YAML's own rule is last-one-wins, so two ``name:`` keys in one source would silently
    discard the first — in a file whose whole purpose is to say which sources exist.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            if key_node.tag == _MERGE_TAG:
                # `<<: *anchor` is not a key: SafeConstructor expands it, and overriding
                # a merged value with an explicit one is the whole point of a merge, so
                # it must not read here as a duplicate.
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
            except TypeError:
                # An unhashable key (`? [a, b]`). SafeConstructor refuses it with a
                # proper YAML error; raising TypeError here would escape every handler.
                continue
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _parse(text: str, origin: str | None) -> Mapping[str, Any]:
    try:
        # _StrictLoader extends SafeLoader: no arbitrary object construction, ever.
        document = yaml.load(text, Loader=_StrictLoader)
    except yaml.YAMLError as error:
        raise ConfigError(
            [Issue(Severity.ERROR, f"not valid YAML: {_yaml_message(error)}")], origin=origin
        ) from None
    if document is None:
        raise ConfigError([Issue(Severity.ERROR, "the configuration is empty")], origin=origin)
    if not isinstance(document, dict):
        raise ConfigError(
            [Issue(Severity.ERROR, "the configuration must be a mapping")], origin=origin
        )
    return document


def _yaml_message(error: yaml.YAMLError) -> str:
    problem = getattr(error, "problem", None)
    mark = getattr(error, "problem_mark", None)
    if problem is None:
        return str(error)
    where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark is not None else ""
    return f"{problem}{where}"


def _section(document: Mapping[str, Any], key: str, issues: list[Issue]) -> Mapping[str, Any]:
    value = document.get(key)
    if value is None:
        issues.append(Issue(Severity.ERROR, f"the '{key}:' section is required", key))
        return {}
    if not isinstance(value, dict):
        issues.append(Issue(Severity.ERROR, f"'{key}:' must be a mapping", key))
        return {}
    return value


def _reject_unknown_keys(
    mapping: Mapping[str, Any], allowed: Collection[str], prefix: str, issues: list[Issue]
) -> None:
    """Unknown keys are errors, not extras.

    A misspelled key that is merely ignored is the worst kind of configuration bug: the
    run succeeds and does the wrong thing.
    """
    for key in mapping:
        if key not in allowed:
            listed = ", ".join(sorted(allowed))
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"unknown key {key!r}; expected one of: {listed}",
                    f"{prefix}.{key}" if prefix else str(key),
                )
            )


def _base_iri(instance: Mapping[str, Any], issues: list[Issue]) -> str | None:
    location = "semprini.base_iri"
    value = instance.get("base_iri")
    if value is None:
        issues.append(Issue(Severity.ERROR, "a base IRI is required", location))
        return None
    if not isinstance(value, str):
        issues.append(Issue(Severity.ERROR, "the base IRI must be a string", location))
        return None
    try:
        # Validated by the serializer's own rule, so a base IRI that loads here cannot
        # fail when the first file is written (spec 3.1, 5.5).
        serialize.namespaces(value)
    except ValueError as error:
        issues.append(Issue(Severity.ERROR, str(error), location))
        return None
    return value


def _slug(mapping: Mapping[str, Any], key: str, location: str, issues: list[Issue]) -> str | None:
    """A validated slug, or ``None`` — reported, and not to be used further."""
    value = mapping.get(key)
    if value is None:
        issues.append(Issue(Severity.ERROR, f"'{key}' is required", location))
        return None
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        issues.append(
            Issue(
                Severity.ERROR,
                f"must be a slug — lower-case letters, digits, '-' or '_' — got {value!r}",
                location,
            )
        )
        return None
    return value


def _language(instance: Mapping[str, Any], issues: list[Issue]) -> str:
    value = instance.get("default_language", DEFAULT_LANGUAGE)
    if not isinstance(value, str) or not is_language_tag(value):
        issues.append(
            Issue(
                Severity.ERROR,
                f"not a language tag: {value!r}",
                "semprini.default_language",
            )
        )
        return DEFAULT_LANGUAGE
    return value


def _sources(
    document: Mapping[str, Any], known_adapters: Collection[str] | None, issues: list[Issue]
) -> tuple[SourceConfig, ...]:
    raw = document.get("sources")
    if raw is None:
        # A fresh instance has no sources at all (spec 5.7 step 2) and must still load.
        return ()
    if not isinstance(raw, list):
        issues.append(Issue(Severity.ERROR, "'sources:' must be a list", "sources"))
        return ()

    sources: list[SourceConfig] = []
    seen: dict[str, int] = {}
    for index, entry in enumerate(raw):
        location = f"sources[{index}]"
        if not isinstance(entry, dict):
            issues.append(Issue(Severity.ERROR, "each source must be a mapping", location))
            continue
        _reject_unknown_keys(entry, _SOURCE_KEYS, location, issues)

        name = _slug(entry, "name", f"{location}.name", issues)
        adapter = _slug(entry, "adapter", f"{location}.adapter", issues)
        if adapter is not None and known_adapters is not None and adapter not in known_adapters:
            installed = ", ".join(sorted(known_adapters)) or "none"
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"unknown adapter {adapter!r}; installed adapters: {installed}",
                    f"{location}.adapter",
                )
            )
        if name is not None:
            if name in seen:
                # Two sources under one name would share ID-map rows and sem:sourceRef
                # values, so their objects would merge into each other (spec 5.4).
                issues.append(
                    Issue(
                        Severity.ERROR,
                        f"duplicate source name {name!r}, already used by sources[{seen[name]}]",
                        f"{location}.name",
                    )
                )
            else:
                seen[name] = index

        settings = entry.get("config") or {}
        if not isinstance(settings, dict):
            issues.append(
                Issue(Severity.ERROR, "'config:' must be a mapping", f"{location}.config")
            )
            settings = {}
        _reject_inline_credentials(settings, f"{location}.config", issues)
        if name is not None and adapter is not None:
            sources.append(SourceConfig(adapter=adapter, name=name, settings=settings))
    return tuple(sources)


def _reject_inline_credentials(
    settings: Mapping[str, Any], prefix: str, issues: list[Issue]
) -> None:
    """Refuse a credential written into the file, at any depth (spec 5.1).

    Keyed on the *name*, not on the value: no heuristic recognizes every token, but the
    operator who pastes one has to put it under a key that says what it is. The one legal
    way to configure a credential — a ``*_env`` key naming an environment variable — is
    checked too, since a token pasted into ``token_env`` is the same mistake wearing the
    right key.
    """
    for key, value in settings.items():
        location = f"{prefix}.{key}"
        segments = _key_segments(key)
        names_a_credential = any(segment in _CREDENTIAL_WORDS for segment in segments) or any(
            pair in _CREDENTIAL_PAIRS for pair in itertools.pairwise(segments)
        )
        # `token_env` names a variable; a bare `env: staging` is an ordinary setting that
        # happens to share the word, and must not be forced into variable-name shape.
        names_a_variable = len(segments) > 1 and segments[-1] == _ENV_SUFFIX
        if names_a_credential and not names_a_variable:
            issues.append(
                Issue(
                    Severity.ERROR,
                    f"credentials are never written to configuration; name an environment "
                    f"variable instead — '{key}_env: {_suggested_variable(key)}'",
                    location,
                )
            )
        elif names_a_variable and not _is_variable_name(value):
            issues.append(
                Issue(
                    Severity.ERROR,
                    "must be the NAME of an environment variable, not its value",
                    location,
                )
            )
        else:
            _scan_for_credentials(value, location, issues)


def _scan_for_credentials(value: Any, location: str, issues: list[Issue]) -> None:
    """Follow a value into whatever nests below it.

    Every container is descended, not only a mapping directly under a mapping: a
    credential is no less committed for sitting two lists down.
    """
    if isinstance(value, dict):
        _reject_inline_credentials(value, location, issues)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_for_credentials(item, f"{location}[{index}]", issues)


def _key_segments(key: Any) -> list[str]:
    """The words a configuration key is made of, however it is punctuated."""
    spaced = _CAMEL_BOUNDARY.sub("_", str(key))
    return [segment for segment in _KEY_SEPARATOR.split(spaced.lower()) if segment]


def _is_variable_name(value: Any) -> bool:
    return isinstance(value, str) and _ENV_VAR_NAME.fullmatch(value) is not None


def _suggested_variable(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(key)).upper() or "SECRET"


def _freeze(value: Any) -> Any:
    """Make a parsed YAML subtree read-only, recursively."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value

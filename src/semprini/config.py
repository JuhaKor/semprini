"""Instance configuration — ``config/semprini.yaml`` (spec 5.1).

A mistake here is a configuration error (exit code 2) located by the key that caused it,
and every problem is reported at once. Credentials never enter configuration: a source
names an environment variable and :meth:`SourceConfig.secret` reads it at fetch time.
"""

from __future__ import annotations

import itertools
import os
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any

import yaml

from semprini import serialize
from semprini.model import Issue, IssueError, RunContext, Severity, is_language_tag

__all__ = [
    "CONFIG_PATH",
    "DEFAULT_LANGUAGE",
    "ConfigError",
    "InstanceConfig",
    "SourceConfig",
    "escapes_the_instance",
    "is_slug",
    "load",
    "loads",
]

CONFIG_PATH = Path("config") / "semprini.yaml"
"""Where an instance keeps its configuration, relative to the repository root (spec 4.2, 5.1)."""

DEFAULT_LANGUAGE = "en"
"""Applied where a label carries no language of its own (spec 5.5 rule 6, 11 #5)."""

_TOP_LEVEL_KEYS = frozenset({"semprini", "sources"})
_INSTANCE_KEYS = frozenset({"base_iri", "instance_id", "default_language"})
_SOURCE_KEYS = frozenset({"adapter", "name", "config"})

SLUG_PATTERN = r"[a-z0-9]+([-_][a-z0-9]+)*"
"""What an instance id, a source name and a scheme slug may look like (spec 5.4). Also
used as ``sh:pattern`` (spec 6.1.5), so written without ``(?:``."""

_SLUG = re.compile(SLUG_PATTERN)

# The shape of an environment variable name, as opposed to the value of one.
_ENV_VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Key segments that name a credential. Per segment, so `source_key` passes and `api_key` does not.
_CREDENTIAL_WORDS = frozenset(
    {"token", "secret", "password", "passwd", "pwd", "credential", "credentials", "apikey"}
)
_CREDENTIAL_PAIRS = frozenset({("api", "key"), ("access", "key"), ("private", "key")})

# A key ending in `_env` names an environment variable, which is how a credential is configured.
_ENV_SUFFIX = "env"

# Key separators; `accessToken` splits the same way `access_token` does.
_KEY_SEPARATOR = re.compile(r"[-_]")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

_MERGE_TAG = "tag:yaml.org,2002:merge"


def is_slug(value: str) -> bool:
    """Whether ``value`` is a slug: lower-case letters, digits, ``-`` and ``_`` (spec 3.4.2)."""
    return _SLUG.fullmatch(value) is not None


def escapes_the_instance(raw: str) -> bool:
    """Whether a configured path could reach outside the instance repository (spec 4.2, 5.3).

    Judged under both POSIX and Windows path rules, since the configuration travels.
    """
    for flavour in (PurePosixPath, PureWindowsPath):
        candidate = flavour(raw)
        if candidate.is_absolute() or candidate.root or candidate.drive:
            return True
        if ".." in candidate.parts:
            return True
    return False


class ConfigError(IssueError):
    """Configuration the compiler refuses to run on — CLI exit code 2 (spec 5.1)."""

    noun = "configuration error"


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceConfig:
    """One entry of the ``sources:`` list (spec 5.1)."""

    adapter: str
    """Entry-point name of an installed adapter (spec 5.2)."""

    name: str
    """The source name, as it appears in ``sem:sourceRef`` and the ID map; never changed
    or reused (spec 5.1, 5.4)."""

    settings: Mapping[str, Any] = field(default_factory=dict, hash=False)
    """The adapter's own ``config:`` subtree, uninterpreted and deep-frozen (spec 5.2)."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "settings", _freeze(dict(self.settings)))

    def secret(
        self, setting: str = "token_env", *, environ: Mapping[str, str] | None = None
    ) -> str | None:
        """Read the credential whose variable name is configured under ``setting``.

        Returns ``None`` when no variable is configured. Raises :class:`ConfigError` when
        one is named but unset. The value is returned, never stored.
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

    def run_context(self, *, dry_run: bool = False) -> RunContext:
        """The :class:`~semprini.model.RunContext` this configuration describes."""
        return RunContext(
            base_iri=self.base_iri,
            instance_id=self.instance_id,
            repo_root=self.repo_root,
            default_language=self.default_language,
            dry_run=dry_run,
        )


def load(
    repo_root: Path | None = None, *, known_adapters: Collection[str] | None = None
) -> InstanceConfig:
    """Load and validate ``<repo_root>/config/semprini.yaml``. Raises :class:`ConfigError`."""
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
    """Validate configuration held in a string. Raises :class:`ConfigError`.

    ``known_adapters`` is injected rather than discovered (spec 5.2); ``None`` skips the
    adapter-name check.
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
    """``SafeLoader`` that refuses duplicate mapping keys instead of letting the last one win."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            if key_node.tag == _MERGE_TAG:
                # `<<: *anchor` is expanded by SafeConstructor and is not a duplicate.
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
            except TypeError:
                # An unhashable key; SafeConstructor refuses it with a proper YAML error.
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
    """Unknown keys are errors, not extras."""
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
        serialize.namespaces(value)
    except ValueError as error:
        issues.append(Issue(Severity.ERROR, str(error), location))
        return None
    return value


def _slug(mapping: Mapping[str, Any], key: str, location: str, issues: list[Issue]) -> str | None:
    """A validated slug, or ``None`` after reporting."""
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

    Judged by key name, not value. A ``*_env`` key must hold a variable name.
    """
    for key, value in settings.items():
        location = f"{prefix}.{key}"
        segments = _key_segments(key)
        names_a_credential = any(segment in _CREDENTIAL_WORDS for segment in segments) or any(
            pair in _CREDENTIAL_PAIRS for pair in itertools.pairwise(segments)
        )
        # A bare `env: staging` is an ordinary setting, not a variable name.
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
    """Follow a value into every container nested below it."""
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

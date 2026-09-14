"""Check 8's battery: stop asking the adapters, and demand the suite notices.

The step is three lines of real work wrapped in refusals, and every one of those refusals
guards against code this project did not write. That is the shape a test suite is worst at:
a `try` whose `except` never fires on the bundled adapters looks identical whether it
reports the failure or swallows it.

Three groups.

**The check stops running.** Dropped from either path through `check`, or asking only the
first source, leaves a command that still prints seven green lines — and a configuration
mistake that reaches the first compile after the pull request merges, which is the round
trip the check exists to prevent.

**A broken plugin is swallowed.** Each `except` returns issues that name the source. Turn
one into `return ()` and a third-party adapter that raises from construction, or from
`validate_config()`, is reported as a clean instance. The `isinstance` guard belongs here
too: `validate_config()` returning a string is iterable, so a lenient version reports one
issue per character rather than one defect.

**The finding loses its address.** An issue with no location, and no fallback to the source
name, tells an operator that something is wrong somewhere in their configuration.
"""

from __future__ import annotations

TESTS: tuple[str, ...] = (
    "tests/test_check.py",
    "tests/test_cli.py",
)

VALIDATE = "src/semprini/validate.py"

# (description, file, old, new). `old` is a verbatim fragment of the file it anchors to and
# appears in it exactly once.
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    # ------------------------------------------------------- the check stops running
    (
        "check 8 never runs on a healthy instance",
        VALIDATE,
        "    outcomes.append(_outcome(8, _check_source_config(settings)))\n"
        "    return CheckResult(tuple(outcomes))",
        "    return CheckResult(tuple(outcomes))",
    ),
    (
        "check 8 is dropped when the Turtle does not parse, so both are not reported",
        VALIDATE,
        "        outcomes.append(_outcome(8, _check_source_config(settings)))\n"
        "        return CheckResult(tuple(outcomes))",
        "        return CheckResult(tuple(outcomes))",
    ),
    (
        "only the first configured source is asked",
        VALIDATE,
        "for source in settings.sources for issue in _asked_of",
        "for source in settings.sources[:1] for issue in _asked_of",
    ),
    (
        "the adapters are constructed and their verdict thrown away",
        VALIDATE,
        "    return tuple(issue for source in settings.sources for issue in _asked_of",
        "    return ()  # type: ignore[unreachable]\n"
        "    return tuple(issue for source in () for issue in _asked_of",
    ),
    # ----------------------------------------------------- a broken plugin is swallowed
    (
        "an adapter that raises from construction is reported as clean",
        VALIDATE,
        '                f"adapter {source.adapter!r} could not be constructed: '
        '{_one_line(error)}",\n'
        "                source.name,\n"
        "            ),\n"
        "        )",
        "            ),\n        )[:0]",
    ),
    (
        "an adapter that raises instead of reporting is reported as clean",
        VALIDATE,
        '                f"adapter {source.adapter!r} raised while validating its '
        'configuration "\n'
        '                f"instead of reporting: {_one_line(error)}",\n'
        "                source.name,\n"
        "            ),\n"
        "        )",
        "            ),\n        )[:0]",
    ),
    (
        "validate_config() may return anything, and a string is read one issue per character",
        VALIDATE,
        "    if not isinstance(reported, list):",
        "    if False and isinstance(reported, list):",
    ),
    (
        "only the container is checked, so a list holding something else reaches the report",
        VALIDATE,
        "        if not isinstance(item, Issue):",
        "        if False:",
    ),
    # -------------------------------------------------- the finding loses its address
    (
        "an issue with no location is not named by its source",
        VALIDATE,
        "issue.location or source.name) for issue in reported",
        "issue.location) for issue in reported",
    ),
    (
        "an adapter's own location is overwritten by the source name",
        VALIDATE,
        "issue.location or source.name) for issue in reported",
        "source.name) for issue in reported",
    ),
)

"""The mechanical guard on spec 6.3: what a shipped workflow is allowed to contain.

Every check and every side effect lives in the CLI, so a workflow may only install the
pinned plane version, invoke `semprini`, and — in exactly one step — open a pull request
with `git` and the platform's own CLI. The rule exists because these files are not this
repository's CI: `semprini init` copies them into every instance an organization creates,
where they run with write access to that organization's `generated/` and `mappings/`. Logic
that drifts into them is logic an adopter on GitLab has to reimplement rather than port, and
a dependency that appears in them is a dependency every adopter inherits.

Nothing else in this project executes these files, which is why the guard is written against
what they *say* rather than what they do. It is deliberately conservative: the segmenter
below is not a shell parser, and anything it cannot classify surfaces as an unexpected
command word and fails, rather than being waved through. `test_the_guard_sees_...` are the
tests that keep it honest — a command-word extractor that quietly returned nothing would
pass every workflow ever written.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from semprini import scaffold

PLATFORM_CLI = {"github": "gh"}
"""The one command each platform's pull-request step may invoke besides `git` (spec 6.3).

Declared per platform rather than as a single name, so a port contributing a `gitlab/`
directory has to say `glab` here — inheriting `gh` would let a workflow ship with a tool
that is not on the runner.
"""

BUILTINS = frozenset({"set", "exit", "[", "test", ":"})
"""Shell builtins the pull-request step may use. Deliberately short: a word that is not
here fails the guard, which is a decision someone makes on purpose rather than a line that
arrives in a workflow unnoticed."""

DATE = "date"
"""Allowed alongside the platform CLI, and only there. Spec 6.2 names the compile branch
`compile/<date>` and a CI platform offers no date of its own, so the one alternative is a
step that computes it — which is the logic 6.3 exists to keep out of these files."""

KEYWORDS = frozenset(
    {"if", "then", "elif", "else", "fi", "while", "until", "do", "done", "case", "esac", "!"}
)

ACTION = re.compile(r"^actions/[a-z0-9-]+@(v\d+|[0-9a-f]{40})$")
"""A first-party action, pinned to a major version or to a commit. Spec 6.3 forbids any
other. The commit form is the stronger pin and the answer to the moving-tag problem that
removed the third-party action, so the rule must not be the thing standing in its way."""

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

Step = dict[str, Any]


# ------------------------------------------------------------------ reading the templates


def workflows() -> list[tuple[str, Path]]:
    """Every shipped workflow, as `(platform, path)`. A platform directory added by a later
    port is guarded by that fact alone."""
    found = [
        (directory.name, path)
        for directory in sorted(scaffold.WORKFLOW_TEMPLATES.iterdir())
        if directory.is_dir()
        for path in sorted(directory.glob("*.yml"))
    ]
    assert found, "the guard found no workflows to guard"
    return found


def steps(path: Path) -> list[Step]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [step for job in document["jobs"].values() for step in job["steps"]]


# --------------------------------------------------------- what counts as a command word


def segments(script: str) -> list[str]:
    """Split a shell script at every point a new command can begin.

    Not a shell parser, and not trying to be one: it tracks quoting far enough to see a
    command substitution in either spelling — including one inside double quotes, which is
    where a second tool would hide most easily — and treats `;`, `|`, `&`, parentheses and
    newlines as breaks.
    A line continued with a backslash is joined, since that is one command; a comment is
    dropped here rather than downstream, because prose that happens to contain a semicolon
    would otherwise arrive as a command nobody wrote.
    """
    found: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0

    def flush() -> None:
        nonlocal current
        found.append("".join(current))
        current = []

    while index < len(script):
        char, pair = script[index], script[index : index + 2]
        if quote == "'":
            if char == "'":
                quote = None
            current.append(char)
            index += 1
        elif pair == "$(":
            flush()
            index += 2
        elif char == "`":
            # The older spelling of the same thing, and active inside double quotes too.
            flush()
            index += 1
        elif char == '"':
            quote = None if quote == '"' else '"'
            current.append(char)
            index += 1
        elif char == "'" and quote is None:
            quote = "'"
            current.append(char)
            index += 1
        elif quote is None and pair == "\\\n":
            current.append(" ")
            index += 2
        elif quote is None and char == "#" and (not current or current[-1].isspace()):
            while index < len(script) and script[index] != "\n":
                index += 1
        elif quote is None and char in ";|&\n()":
            flush()
            index += 1
        else:
            current.append(char)
            index += 1

    flush()
    return [segment for segment in found if segment.strip()]


def invocation(segment: str) -> list[str]:
    """The command a segment runs, and its arguments.

    A leading keyword or variable assignment is stepped over and whatever comes next is the
    command. Quotes are removed rather than treated as boundaries, so that a quoted
    assignment stays one word — `branch="compile/$today"` runs nothing. Erring towards
    *more* commands than the shell would actually run is the safe direction for a rule
    about what may execute in an adopter's repository.

    Every reader of a segment goes through here. A caller that looked at the raw words
    instead would see `then git push ...` and not recognize the push, which is exactly how
    a rule about what may run gets bypassed by a line someone reformatted.
    """
    tokens = segment.replace('"', "").replace("'", "").split()
    for index, token in enumerate(tokens):
        if token in KEYWORDS or ASSIGNMENT.match(token):
            continue
        return tokens[index:]
    return []


def command_words(script: str) -> set[str]:
    """Every command this script invokes."""
    return {words[0] for segment in segments(script) if (words := invocation(segment))}


def opens_a_pull_request(platform: str, step: Step) -> bool:
    return f"{PLATFORM_CLI[platform]} pr create" in step.get("run", "")


# --------------------------------------------------------------------------- the guard


def test_every_platform_directory_declares_its_cli() -> None:
    """The seam of spec 6.3, kept honest. A port that adds a directory without naming its
    CLI would have the rest of this file silently guard it against GitHub's."""
    assert {platform for platform, _ in workflows()} <= set(PLATFORM_CLI)


def test_the_shipped_workflows_are_the_two_the_spec_names() -> None:
    for platform in PLATFORM_CLI:
        directory = scaffold.WORKFLOW_TEMPLATES / platform
        assert {path.name for path in directory.glob("*")} == set(scaffold.WORKFLOWS)


@pytest.mark.parametrize(("platform", "path"), workflows(), ids=lambda value: str(value))
def test_every_action_is_first_party_and_pinned(platform: str, path: Path) -> None:
    """A third-party action in a shipped workflow is code that runs in every adopter's
    instance, with write access to their graph, and that changes without a diff anyone
    reviews — which is the one thing this design refuses everywhere else (spec 6.3)."""
    for step in steps(path):
        if "uses" in step:
            assert ACTION.match(step["uses"]), step["uses"]


@pytest.mark.parametrize(("platform", "path"), workflows(), ids=lambda value: str(value))
def test_every_step_installs_the_plane_invokes_it_or_opens_the_pull_request(
    platform: str, path: Path
) -> None:
    """The whole of spec 6.3, stated mechanically.

    Anything else — a `jq` reading `generated/`, a Python one-liner, a second tool — is
    logic that an adopter on another platform would have to reimplement rather than port,
    and it belongs in the CLI where `semprini check` reaches the same verdict on a laptop.
    """
    for step in steps(path):
        if "uses" in step:
            continue
        words = command_words(step["run"])
        if opens_a_pull_request(platform, step):
            continue
        assert words <= {"pip", "semprini"}, (path.name, sorted(words))


@pytest.mark.parametrize(("platform", "path"), workflows(), ids=lambda value: str(value))
def test_at_most_one_step_opens_a_pull_request(platform: str, path: Path) -> None:
    """Spec 6.2 asks for one pull request per compile, and spec 6.3 isolates the one
    platform-specific step. Two of them is two places to port and two ways to disagree."""
    assert len([step for step in steps(path) if opens_a_pull_request(platform, step)]) <= 1


def test_the_compile_workflow_is_the_one_that_opens_it() -> None:
    for platform, path in workflows():
        opening = [step for step in steps(path) if opens_a_pull_request(platform, step)]
        assert bool(opening) == (path.name == "compile.yml"), path.name


@pytest.mark.parametrize(("platform", "path"), workflows(), ids=lambda value: str(value))
def test_the_pull_request_step_runs_nothing_but_git_and_the_platform_cli(
    platform: str, path: Path
) -> None:
    """Spec 6.3: the price of dropping the third-party action is a dozen lines of shell, and
    this is the bound on them. `semprini` is absent on purpose — a step that both proposes a
    pull request and decides something about the graph is the seam the CLI owns."""
    allowed = BUILTINS | {"git", DATE, PLATFORM_CLI[platform]}

    for step in steps(path):
        if opens_a_pull_request(platform, step):
            assert command_words(step["run"]) <= allowed, sorted(command_words(step["run"]))


@pytest.mark.parametrize(("platform", "path"), workflows(), ids=lambda value: str(value))
def test_no_workflow_pushes_to_a_protected_branch(platform: str, path: Path) -> None:
    """Spec 6.2: the compile never pushes to main. It pushes the `compile/` branch it just
    created and proposes it, which is what leaves a steward the review."""
    for step in steps(path):
        for segment in segments(step.get("run", "")):
            words = invocation(segment)
            if words[:2] == ["git", "push"]:
                assert "$branch" in words, segment


@pytest.mark.skipif(shutil.which("bash") is None, reason="no shell to parse with")
@pytest.mark.parametrize(("platform", "path"), workflows(), ids=lambda value: str(value))
def test_the_pull_request_step_is_a_script_a_shell_can_parse(platform: str, path: Path) -> None:
    """The one place in this project where shell ships to somebody else.

    Nothing here executes it and no adopter reads it before their first scheduled compile,
    so an unbalanced quote or a missing `fi` surfaces weeks later as a red job in someone
    else's repository. `bash -n` parses without running, which is the whole of what can be
    checked from here — the runner's behaviour is what the scratch instance is for.
    """
    for step in steps(path):
        if opens_a_pull_request(platform, step):
            parsed = subprocess.run(
                ["bash", "-n"], input=step["run"], text=True, capture_output=True, check=False
            )
            assert parsed.returncode == 0, parsed.stderr


# ------------------------------------------------------- keeping the guard itself honest


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("semprini run", {"semprini"}),
        # The shipped install line: a URL, because there is no package index (spec 11 #3),
        # with the version in a shell variable so that one edit upgrades the file. A guard
        # that stopped recognizing it would stop guarding the step that reaches the network.
        (
            'pip install "semprini @ https://github.com/JuhaKor/semprini/releases/download/'
            'v${SEMPRINI_VERSION}/semprini-${SEMPRINI_VERSION}-py3-none-any.whl"',
            {"pip"},
        ),
        # The ways a second tool could reach a runner without being the first word on a
        # line. A guard that missed any of them would pass the workflow that used it.
        ('today="$(curl https://example.invalid)"', {"curl"}),
        ("git commit -m `curl https://example.invalid`", {"git", "curl"}),
        ("if git diff --quiet; then curl https://example.invalid; fi", {"git", "curl"}),
        ("git add generated && jq . generated/.manifest.json", {"git", "jq"}),
        ("gh pr create \\\n  --body-file generated/.report.md", {"gh"}),
        ("if git diff --cached --quiet; then\n  exit 0\nfi", {"git", "exit"}),
        ("python -c 'import semprini'", {"python"}),
        # ...and the two ways it could report a command nobody wrote, which would make the
        # guard something a later session works around rather than reads.
        ('branch="compile/$today"', set()),
        ("# it is open; force-pushing updates it\ngit status", {"git"}),
    ],
)
def test_the_guard_sees_the_command_in(script: str, expected: set[str]) -> None:
    assert command_words(script) == expected


def test_the_guard_reads_the_shipped_compile_step() -> None:
    """The end of the loop: the words the guard actually extracts from the file that ships.

    Pinned as an exact set rather than a subset, so a tool added to that step has to be
    added here too — which is the moment to ask whether spec 6.3 still permits it.
    """
    (path,) = [path for _, path in workflows() if path.name == "compile.yml"]
    (opener,) = [step for step in steps(path) if opens_a_pull_request("github", step)]

    assert command_words(opener["run"]) == {"set", "date", "git", "[", "exit", "gh"}

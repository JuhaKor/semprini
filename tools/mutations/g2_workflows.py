"""G2's battery: break the shipped workflows, and break the guard that reads them.

Two kinds of mutation live here, and the second kind is the point. Breaking `compile.yml`
asks whether the guard bites; breaking the guard's own shell segmenter asks whether the
tests that describe it bite. A command-word extractor that quietly returned nothing would
pass every workflow ever written — including one that installed a second tool into an
adopter's instance — and it would look exactly like a working one from the test names.

Nothing in this project executes these workflow files: they run in instances, on a runner,
weeks later. The suite is the only thing standing between a wrong line here and an
adopter's scheduled compile, which is why the anchors below are worth the cost of rotting
whenever the pull-request step is reworded.

One mutation is caught by `bash -n` alone — a missing `;` before a `then` — and the test
that catches it skips where no shell is installed. Run this battery somewhere with one, or
that mutation reports a survivor that is really an absent tool.

Two mutations are deliberately absent. The step ordering — validate before propose — is
G1's, and is uncovered there for the reason recorded in that battery. And nothing mutates
`BUILTINS` or `PLATFORM_CLI`: widening an allowlist is a change to the rule rather than to
the code, and the guard cannot be asked to catch someone editing what it is told to
enforce. `test_the_guard_reads_the_shipped_compile_step` pins the other side of that — the
step's exact word set — so a tool arriving in the file is caught even if the allowlist grew
to admit it in the same edit.
"""

from __future__ import annotations

TESTS: tuple[str, ...] = ("tests/test_workflows.py", "tests/test_scaffold.py")

COMPILE = "src/semprini/workflows/github/compile.yml"
VALIDATE = "src/semprini/workflows/github/validate.yml"
GUARD = "tests/test_workflows.py"

# (description, file, old, new). `old` is a verbatim fragment of the file it anchors to and
# is never reformatted or rewrapped — a line over the limit is silenced with a per-line
# ruff directive rather than split, since a split anchor is one nobody can compare against
# the source it was copied from.
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    # ------------------------------------------------- what may run in an adopter's repo
    (
        "a third-party action is back in a shipped workflow",
        COMPILE,
        "      - uses: actions/checkout@v4",
        "      - uses: peter-evans/checkout@v4",
    ),
    (
        "an action floats on a branch instead of a pinned major version",
        COMPILE,
        "      - uses: actions/setup-python@v5",
        "      - uses: actions/setup-python@main",
    ),
    (
        "a second tool reads generated/ in the pull request step",
        COMPILE,
        "          git add generated mappings",
        "          git add generated mappings\n          jq . generated/.manifest.json",
    ),
    (
        "a python one-liner decides whether to propose",
        COMPILE,
        "          set -euo pipefail",
        '          set -euo pipefail\n          python -c "print(1)"',
    ),
    (
        "a step neither installs the plane nor invokes it",
        VALIDATE,
        "      - run: semprini check",
        "      - run: pytest",
    ),
    (
        "the compile pushes straight to main",
        COMPILE,
        '          git push --force origin "$branch"',
        "          git push --force origin HEAD:main",
    ),
    # ------------------------------------ the three lines the action used to handle for us
    (
        "an empty staging area is left to fail the run",
        COMPILE,
        """          if git diff --cached --quiet; then
            exit 0
          fi
""",
        "",
    ),
    (
        "a second dispatch on one day is left to fail on the push",
        COMPILE,
        '          git push --force origin "$branch"',
        '          git push origin "$branch"',
    ),
    (
        "a second pull request is requested for a branch that already has one",
        COMPILE,
        """          open_pull_request="$(gh pr list --head "$branch" --state open --json number --jq '.[].number')"
          if [ -z "$open_pull_request" ]; then""",  # noqa: E501
        "          if true; then",
    ),
    (
        "a failed pull request query reads as there being none",
        COMPILE,
        """          open_pull_request="$(gh pr list --head "$branch" --state open --json number --jq '.[].number')"
          if [ -z "$open_pull_request" ]; then""",  # noqa: E501
        """          if [ -z "$(gh pr list --head "$branch" --state open --json number --jq '.[].number')" ]; then""",  # noqa: E501
    ),
    (
        "a push to main hides behind a shell keyword",
        COMPILE,
        """          if git diff --cached --quiet; then
            exit 0
          fi""",
        """          if git diff --cached --quiet; then exit 0; else git push --force origin HEAD:main; fi""",  # noqa: E501
    ),
    (
        "the commit is attempted without a committer identity",
        COMPILE,
        '          git config user.name "github-actions[bot]"\n',
        "",
    ),
    (
        "the pull request step ships a shell syntax error",
        COMPILE,
        "          if git diff --cached --quiet; then",
        "          if git diff --cached --quiet then",
    ),
    # ------------------------------------------------------- the guard's own shell reader
    (
        "the guard cannot see inside a command substitution",
        GUARD,
        '        elif pair == "$(":',
        '        elif False and pair == "$(":',
    ),
    (
        "the guard cannot see inside the older spelling of one",
        GUARD,
        '        elif char == "`":',
        '        elif False and char == "`":',
    ),
    (
        "a command behind a shell keyword is read as the keyword",
        GUARD,
        """        if token in KEYWORDS or ASSIGNMENT.match(token):
            continue
        return tokens[index:]""",
        """        if ASSIGNMENT.match(token):
            continue
        return tokens[index:]""",
    ),
    (
        "the guard stops at the first command of a chain",
        GUARD,
        '        elif quote is None and char in ";|&\\n()":',
        '        elif quote is None and char in ";|\\n()":',
    ),
    (
        "the guard reads prose in a comment as commands",
        GUARD,
        '        elif quote is None and char == "#" and (not current or current[-1].isspace()):',
        '        elif False and char == "#" and (not current or current[-1].isspace()):',
    ),
    (
        "the guard splits a continued line into two commands",
        GUARD,
        '        elif quote is None and pair == "\\\\\\n":',
        '        elif False and pair == "\\\\\\n":',
    ),
    (
        "the guard reports no commands at all",
        GUARD,
        "    return {words[0] for segment in segments(script) if (words := invocation(segment))}",
        "    return set()",
    ),
    (
        "a quoted assignment is reported as the command it names",
        GUARD,
        """    tokens = segment.replace('"', "").replace("'", "").split()""",
        """    tokens = segment.replace('"', " ").replace("'", " ").split()""",
    ),
    (
        "the guard finds no workflows to guard",
        GUARD,
        "        if directory.is_dir()",
        "        if False",
    ),
)

"""Run a mutation battery: break the implementation on purpose, demand the suite notices.

A test looks identical whether or not it is asserting anything — a determinism test that
compares a value with itself passes for ever. Every task in `TASKS.md` therefore records a
battery of plausible-but-wrong alternative implementations, and the suite has to fail on
each one. This is the runner for those batteries; the batteries themselves are data, in
`tools/mutations/`.

    python tools/mutate.py f3_validate
    python tools/mutate.py f3_validate --rounds 2 --workers 8
    python tools/mutate.py f3_validate --only "sorted"

Two properties matter more than speed, and the speed comes from the first of them:

**The repository is never edited.** Each worker gets its own copy of the tree in a
temporary directory and mutates that. An interrupted run cannot leave a broken source file
behind, which the obvious in-place implementation does every time it is killed mid-test.

**A run that cannot prove it is testing the copy refuses to start.** The virtualenv holds
a `.pth` pointing at *this* repository's `src`, so a worker whose `PYTHONPATH` were wrong
would import the real, unmutated module — and every mutation would then be reported as a
survivor. That failure is loud rather than silent, but it wastes a whole run, so each
worker is asked where it imports `semprini` from before any mutation is applied.

Batteries rot, deliberately and visibly: a mutation is anchored to an exact fragment of
source, so a refactor that moves the fragment reports `NOT APPLIED` rather than passing.
That is a finding about the battery, not about the code, and it is why these are run on
demand and are not part of CI.
"""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Copied per worker. `.git` and the caches are the bulk of the tree and no test reads them;
# `background-material` is gitignored and belongs to no test either.
SKIP = shutil.ignore_patterns(
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "background-material",
    "venv",
)


@dataclass(frozen=True)
class Mutation:
    """One plausible-but-wrong implementation.

    `old` must appear exactly once in `path`, so that what was changed is never in doubt.
    """

    description: str
    path: str
    old: str
    new: str


@dataclass(frozen=True)
class Battery:
    tests: tuple[str, ...]
    mutations: tuple[Mutation, ...]


@dataclass(frozen=True)
class Result:
    description: str
    verdict: str  # "caught", "SURVIVED", "NOT APPLIED", "AMBIGUOUS"

    @property
    def ok(self) -> bool:
        return self.verdict == "caught"


def load(name: str) -> Battery:
    """Import a battery from `tools/mutations/<name>.py`."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        module = importlib.import_module(f"tools.mutations.{name}")
    except ModuleNotFoundError as missing:
        if missing.name != f"tools.mutations.{name}":
            raise
        here = REPO / "tools" / "mutations"
        available = sorted(path.stem for path in here.glob("*.py") if path.stem != "__init__")
        raise SystemExit(
            f"no battery named {name!r}; available: {', '.join(available) or 'none'}"
        ) from None
    return Battery(tuple(module.TESTS), tuple(Mutation(*row) for row in module.MUTATIONS))


class Worker:
    """One copy of the repository, reused across the mutations dispatched to it."""

    def __init__(self, root: Path, battery: Battery) -> None:
        self.root = root
        self.battery = battery

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        # The virtualenv's `semprini.pth` points at the real `src`. PYTHONPATH is searched
        # before site-packages' `.pth` additions, so this is what makes the copy win.
        env["PYTHONPATH"] = os.pathsep.join([str(self.root / "src"), str(self.root)])
        return env

    def verify_isolation(self) -> None:
        """Refuse to run unless this worker imports `semprini` from its own copy."""
        found = subprocess.run(
            [sys.executable, "-c", "import semprini; print(semprini.__file__)"],
            cwd=self.root,
            env=self._env(),
            capture_output=True,
            text=True,
        )
        imported = Path(found.stdout.strip() or "<none>")
        if not found.stdout.strip() or self.root not in imported.parents:
            raise SystemExit(
                f"worker {self.root} imports semprini from {imported}, not from its own copy — "
                "every mutation would be reported as a survivor. Aborting."
            )

    def run_tests(self) -> bool:
        """True if the suite passes in this worker's copy."""
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                *self.battery.tests,
                "-x",
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
            ],
            cwd=self.root,
            env=self._env(),
            capture_output=True,
            text=True,
        )
        return completed.returncode == 0

    def apply(self, mutation: Mutation) -> Result:
        target = self.root / mutation.path
        original = target.read_text(encoding="utf-8")
        mutated = original.replace(mutation.old, mutation.new)
        target.write_text(mutated, encoding="utf-8", newline="")
        try:
            survived = self.run_tests()
        finally:
            target.write_text(original, encoding="utf-8", newline="")
        return Result(mutation.description, "SURVIVED" if survived else "caught")


def preflight(battery: Battery) -> list[Result]:
    """Check every anchor against the real tree before copying anything.

    A battery whose anchors have rotted is worth knowing about in a second rather than
    after a worker has run the suite for each of them.
    """
    problems: list[Result] = []
    for mutation in battery.mutations:
        source = (REPO / mutation.path).read_text(encoding="utf-8")
        found = source.count(mutation.old)
        if found == 0:
            problems.append(Result(mutation.description, "NOT APPLIED"))
        elif found > 1:
            problems.append(Result(mutation.description, "AMBIGUOUS"))
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("battery", help="a module name under tools/mutations/")
    parser.add_argument("--rounds", type=int, default=1, help="repeat, to defeat an ordering fluke")
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    parser.add_argument("--only", default="", help="run only mutations whose description matches")
    parser.add_argument("--list", action="store_true", help="check the anchors only, then stop")
    arguments = parser.parse_args(argv)

    battery = load(arguments.battery)
    if arguments.only:
        battery = Battery(
            battery.tests,
            tuple(m for m in battery.mutations if arguments.only.lower() in m.description.lower()),
        )
    if not battery.mutations:
        raise SystemExit("no mutations selected")

    rotted = preflight(battery)
    if arguments.list:
        for mutation in battery.mutations:
            broken = next((r for r in rotted if r.description == mutation.description), None)
            print(f"  {broken.verdict if broken else 'ok':>11}: {mutation.description}")
        return 1 if rotted else 0
    if rotted:
        print(f"{len(rotted)} anchor(s) no longer match the source — the battery has rotted:")
        for result in rotted:
            print(f"  {result.verdict}: {result.description}")
        return 2

    workers_wanted = max(1, min(arguments.workers, len(battery.mutations)))
    with tempfile.TemporaryDirectory(prefix="semprini-mutate-") as scratch:
        print(f"copying the tree for {workers_wanted} worker(s)...", flush=True)
        workers = []
        for index in range(workers_wanted):
            root = Path(scratch) / f"w{index}"
            shutil.copytree(REPO, root, ignore=SKIP)
            worker = Worker(root, battery)
            worker.verify_isolation()
            workers.append(worker)

        # A battery run against a failing baseline reports every mutation as caught, which
        # is exactly the result it is supposed to be unable to fake.
        print("baseline...", flush=True)
        if not workers[0].run_tests():
            print("BASELINE FAILS - every mutation would look caught. Fix the suite first.")
            return 2

        available = list(workers)
        lock = threading.Lock()
        printing = threading.Lock()

        def run(mutation: Mutation) -> Result:
            with lock:
                worker = available.pop()
            try:
                result = worker.apply(mutation)
            finally:
                with lock:
                    available.append(worker)
            with printing:
                print(f"  {result.verdict}: {result.description}", flush=True)
            return result

        survivors: list[Result] = []
        for round_number in range(1, arguments.rounds + 1):
            print(f"--- round {round_number} of {arguments.rounds} ---", flush=True)
            with ThreadPoolExecutor(max_workers=workers_wanted) as pool:
                survivors += [r for r in pool.map(run, battery.mutations) if not r.ok]

    print()
    if survivors:
        print(f"{len(survivors)} survivor(s):")
        for result in survivors:
            print(f"  - {result.description}")
        return 1
    print(f"all {len(battery.mutations)} mutations caught, {arguments.rounds} round(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The contract, judged from an installed wheel by projects shaped like a stranger's.

Run by the `build` job in `.github/workflows/publish.yml`, against the wheel
an upload job will upload, and by hand the same way:

    python .github/strangers/arms.py --python <interpreter> --bare <interpreter> \\
        --work <directory>

`--python` is the interpreter of a fresh virtual environment that holds the
wheel installed with its `conformance` extra and nothing else of this tree.
`--bare` is the interpreter of a second one that holds the wheel with no
extra. `--work` is a directory outside the tree. Each arm is a directory
beside this file holding a stranger's `test_format.py`; it is copied into
`--work` with the files in `common/`, and pytest runs there, under
`--python`, as a stranger's CI would run it.

Each arm is decided by its exit code first, so the job is red whenever a
refusal does not fire, and then by what its report attributes the outcome to,
because a count is not an attribution: a run can exit 1 for a reason that is
not the format's defect. A wrong format must fail exactly the contract arms
its defect is for, each with the exception expected, and pass every other
one. For the three formats the package ships, what is expected is read from
the installed wheel, each format's `expected_reds`; this repository's own
suite holds those to a literal. The refusing arms run before the passing one,
and the passing arm is trusted only in a run where every refusing arm was
seen to refuse. An arm that did not run, ran no test it should have, or
skipped one is a failure, never a pass.

Before any arm, two positive controls. The first: `--python` imports
`crosslink` from outside this tree, has pytest, and has neither of the other
extras' distributions, so the arms show the `conformance` extra is enough.
The second: `--bare` imports `crosslink`, has no pytest, and cannot import
`crosslink.conformance` for want of exactly that, so the extra is seen to be
what carries the contract's one dependency.

This script imports nothing from `crosslink`; it reads the runs it starts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
TREE = HERE.parents[1]
COMMON = HERE / "common"

#: Read from the outer environment by pytest, so never passed on.
SCRUBBED = ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH")

#: The class every arm's `test_format.py` wires the contract to.
SUBJECT = "test_format.TestStrangerFormat"

#: The formats the package ships built to fail, by the arm that runs each.
SHIPPED = {
    "refuses-malformed": "AFormatThatRefusesMalformedInput",
    "swallows-silently": "AFormatThatSwallowsSilently",
    "unstable-fingerprint": "AFormatWithAnUnstableFingerprint",
}

#: One row per test in a run's JUnit report: test -> "passed", "skipped" or
#: "failed:<the exception's class>".
Rows = dict[str, str]

PROBE = (
    "import importlib.util, json, crosslink, pytest\n"
    "from crosslink import conformance_calibration as shipped\n"
    "print(json.dumps({\n"
    "    'crosslink': crosslink.__file__,\n"
    "    'pytest': pytest.__version__,\n"
    "    'others': sorted(n for n in ('ration', 'anthropic') if importlib.util.find_spec(n)),\n"
    "    'expected_reds': {n: dict(getattr(shipped, n).expected_reds) for n in %r},\n"
    "}))\n"
) % (sorted(SHIPPED.values()),)

BARE_PROBE = (
    "import importlib.util, json, crosslink\n"
    "found = {'crosslink': crosslink.__file__, 'pytest': importlib.util.find_spec('pytest') is not None}\n"
    "try:\n"
    "    import crosslink.conformance\n"
    "    found['contract'] = 'imported'\n"
    "except ModuleNotFoundError as error:\n"
    "    found['contract'] = 'no module ' + str(error.name)\n"
    "print(json.dumps(found))\n"
)


@dataclass(frozen=True)
class Arm:
    directory: str
    exit_code: int
    says: tuple[str, ...]
    #: The arms the contract must fail this format on, given the probe's
    #: answer, each with the exception's class. None for an arm that runs no
    #: test.
    reds: Callable[[Mapping[str, Mapping[str, str]]], Mapping[str, str]] | None


def shipped(directory: str) -> Callable[[Mapping[str, Mapping[str, str]]], Mapping[str, str]]:
    return lambda expected: expected[SHIPPED[directory]]


ARMS = (
    Arm("refuses-malformed", 1, ("failed",), shipped("refuses-malformed")),
    Arm("swallows-silently", 1, ("failed",), shipped("swallows-silently")),
    Arm("unstable-fingerprint", 1, ("failed",), shipped("unstable-fingerprint")),
    # The stranger's own defect, which the package has never seen, so what is
    # expected is written here.
    Arm(
        "truncated-key",
        1,
        ("failed",),
        lambda _: {"test_a_composite_key_keeps_every_column_and_their_order": "AssertionError"},
    ),
    # pytest exits 5 when it collected nothing. A run that judged no format
    # is not a pass, and the code is how a stranger's CI is told.
    Arm("uncollected", 5, ("no tests ran",), None),
    # Last, so it is read only after every refusal above has been seen.
    Arm("correct", 0, ("passed",), lambda _: {}),
)


def kind_of(failure: ET.Element) -> str:
    """The class of the exception a failed test ended in, from its report."""
    message = failure.get("message", "")
    named = re.match(r"([A-Za-z_][\w.]*(?:Error|Exception))\b", message)
    if named:
        return named.group(1).rsplit(".", 1)[-1]
    # pytest reports a bare `assert` by its rewritten expression.
    return "AssertionError" if message.startswith("assert") else f"unread ({message[:40]!r})"


def read_report(junit: Path) -> tuple[Rows, list[str]]:
    """The subject's rows, and every test the report holds that is not the subject's."""
    rows: Rows = {}
    strays: list[str] = []
    if not junit.is_file():
        return rows, strays
    for case in ET.parse(junit).getroot().iter("testcase"):
        name = case.get("name", "")
        outcome = "passed"
        for child in case:
            if child.tag in ("failure", "error"):
                outcome = f"failed:{kind_of(child)}"
                break
            if child.tag == "skipped":
                outcome = "skipped"
        if case.get("classname") == SUBJECT and name not in rows:
            rows[name] = outcome
        else:
            strays.append(f"{case.get('classname')}::{name}")
    return rows, strays


def judge(rows: Rows, strays: list[str], reds: Mapping[str, str] | None) -> list[str]:
    problems = [f"the report holds tests that are not the stranger's contract class: {strays[:5]}"] if strays else []
    if reds is None:
        return problems + ([f"tests ran: {sorted(rows)[:5]}"] if rows else [])
    if not rows:
        return [*problems, "the report records no test, so nothing was judged"]
    failed = {test: outcome.removeprefix("failed:") for test, outcome in rows.items() if outcome.startswith("failed:")}
    unjudged = sorted(test for test, outcome in rows.items() if outcome == "skipped")
    if unjudged:
        problems.append(f"tests were skipped, and a skip is not a pass: {unjudged[:5]}")
    if failed != dict(reds):
        missing = sorted(set(reds) - set(failed))
        extra = sorted(set(failed) - set(reds))
        wrong = sorted(f"{t}: {failed[t]}, expected {reds[t]}" for t in set(failed) & set(reds) if failed[t] != reds[t])
        problems.append(f"the contract's reds are not the ones built: not failed {missing}; failed unexpectedly {extra}; failed otherwise {wrong}")
    if not any(outcome == "passed" for outcome in rows.values()):
        problems.append("no arm of the contract passed, so a red is not attributed to the defect")
    return problems


def pytest_run(python: Path, project: Path) -> tuple[int, str]:
    env = {key: value for key, value in os.environ.items() if key not in SCRUBBED}
    env["PYTHONIOENCODING"] = "utf-8"
    junit = project / "report.xml"
    command = [str(python), "-m", "pytest", "-p", "no:cacheprovider", "-rA", f"--junitxml={junit}"]
    print(f"$ (cd {project}) {' '.join(command)}", flush=True)
    done = subprocess.run(
        command, cwd=project, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=1200, check=False,
    )
    return done.returncode, done.stdout + done.stderr


def run_arm(arm: Arm, python: Path, work: Path, expected: Mapping[str, Mapping[str, str]]) -> tuple[list[str], Rows]:
    project = work / arm.directory
    if project.exists():
        shutil.rmtree(project)
    shutil.copytree(HERE / arm.directory, project)
    for shared in COMMON.iterdir():
        shutil.copy2(shared, project / shared.name)
    code, output = pytest_run(python, project)
    print(f"::group::{arm.directory}: the run's output", flush=True)
    print(output, flush=True)
    print("::endgroup::", flush=True)
    problems = []
    if code != arm.exit_code:
        problems.append(f"exited {code}, expected {arm.exit_code}")
    problems += [f"the output does not say {text!r}" for text in arm.says if text not in output]
    rows, strays = read_report(project / "report.xml")
    reds = None if arm.reds is None else arm.reds(expected)
    for test, outcome in sorted(rows.items()):
        print(f"  {arm.directory}: {test} {outcome}")
    return problems + judge(rows, strays, reds), rows


def probe(python: Path, work: Path, program: str) -> tuple[dict[str, object], list[str]]:
    done = subprocess.run(
        [str(python), "-I", "-c", program], cwd=work, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    print(done.stdout + done.stderr, flush=True)
    if done.returncode != 0:
        return {}, [f"the probe exited {done.returncode}"]
    try:
        found = json.loads(done.stdout)
    except json.JSONDecodeError:
        return {}, ["the probe did not answer in JSON"]
    where = Path(str(found.get("crosslink", TREE))).resolve()
    if where.is_relative_to(TREE):
        return found, [f"`crosslink` imports from this tree ({where}), not from an installed wheel"]
    return found, []


def control(python: Path, work: Path) -> tuple[list[str], dict[str, dict[str, str]]]:
    found, problems = probe(python, work, PROBE)
    if found.get("others"):
        problems.append(f"the environment holds {found['others']}, so the arms would not show the `conformance` extra is enough")
    expected = found.get("expected_reds")
    expected = expected if isinstance(expected, dict) else {}
    for name in SHIPPED.values():
        if not expected.get(name):
            problems.append(f"the wheel's `{name}` names no arm it must fail, so its arm would expect nothing")
    if len({json.dumps(reds, sort_keys=True) for reds in expected.values()}) != len(SHIPPED):
        problems.append("two of the wheel's wrong formats expect the same reds, so one arm could stand in for another")
    return problems, expected


def bare_control(python: Path, work: Path) -> list[str]:
    found, problems = probe(python, work, BARE_PROBE)
    if found.get("pytest") is not False:
        problems.append("the environment with no extra has pytest, so it shows nothing about the extra")
    if found.get("contract") != "no module pytest":
        problems.append(f"importing `crosslink.conformance` with no extra gave {found.get('contract')!r}, expected 'no module pytest'")
    return problems


def across(ran: Mapping[str, Rows], expected: Mapping[str, Mapping[str, str]]) -> list[str]:
    """What only the arms together show: the passing arm ran every test a wrong format failed."""
    correct = set(ran.get("correct", {}))
    problems = []
    for directory, rows in ran.items():
        if directory in ("correct", "uncollected"):
            continue
        absent = sorted(set(rows) - correct)
        if absent:
            problems.append(f"the passing arm never ran tests `{directory}` ran: {absent[:5]}")
    if correct != set(ran.get("unstable-fingerprint", {})):
        problems.append("the passing arm and `unstable-fingerprint` wire the same contract and ran different tests")
    tier_two = {test for name in SHIPPED.values() for test in expected.get(name, {})} - set(ran.get("refuses-malformed", {}))
    if not tier_two:
        problems.append("no expected red is a tier-2 arm, so tier 2 was not seen refusing")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--bare", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    args = parser.parse_args(argv)
    work: Path = args.work.resolve()
    if work.is_relative_to(TREE):
        print(f"::error::--work {work} is inside the tree; the arms run outside it.")
        return 2
    work.mkdir(parents=True, exist_ok=True)

    first, expected = control(args.python, work)
    verdicts = {"control": first, "control, no extra": bare_control(args.bare, work)}
    ran: dict[str, Rows] = {}
    if not any(verdicts.values()):
        for arm in ARMS:
            verdicts[arm.directory], ran[arm.directory] = run_arm(arm, args.python, work, expected)
        verdicts["across the arms"] = across(ran, expected)

    for name, problems in verdicts.items():
        print(f"{'ok  ' if not problems else 'RED '} {name}")
        for problem in problems:
            print(f"::error::{name}: {problem}")
    refusals = [arm.directory for arm in ARMS if arm.exit_code != 0]
    if any(verdicts.get(name, ["not run"]) for name in ["control", "control, no extra", *refusals]):
        print("A refusing arm did not refuse as built, so the passing arm is not trusted.")
    # Every arm by name, so one that never ran is a failure and not an absence.
    every = ["control", "control, no extra", *(arm.directory for arm in ARMS), "across the arms"]
    not_run = [name for name in every if name not in verdicts]
    for name in not_run:
        print(f"::error::{name}: did not run")
    return 0 if not not_run and not any(verdicts.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

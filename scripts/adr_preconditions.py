#!/usr/bin/env python3
"""Refuse a record whose status says one thing while this tree says another.

An architecture record carries two claims that nothing else compares: what was
decided, and how much of it may be built. This reads the numbered records in
one directory and every other tracked file in the same checkout, and refuses
three things:

1. **Shape.** A record with no `## Do not implement until` section, or with a
   `Status:` that is not one of the three the template offers.
2. **Coherence.** A record that is `Accepted` while holding an unticked
   precondition and no `**Implementable now:**` line. A record settled in one
   half and deferred in the other must say which half is live.
3. **Citation.** A record cited outside the record directory while it is
   `Proposed`, or while it holds an unticked precondition. A citation stands
   in for an implementation: it is the one signal available without asking a
   person what they built.

What counts as a citation: the letters ADR, an optional hyphen or space, and a
record's four digits; or a path to the record's file, written as the record
directory's name, a slash and the four digits. Only a number this directory
holds is counted, so a line that cites some other project's record under a
number held here is read as a citation of the record here. The letters are
matched in either case.

What is not counted, so that a reader does not take a green for more than it
is: a number that follows another without its own letters ("ADRs 0003 and
0005" cites the first alone), a citation in a file that is not UTF-8 or
ASCII text, and a precondition written as anything but a `- [ ]` list item.

What is read: the files git tracks in this checkout, from the working tree.
The record directory itself is left out, since a record citing its neighbour
is the corpus working. History files (`CHANGELOG.md`, `*.history.md`) are left
out too: their entries quote what was once said and are not rewritten, so a
red one could not be cleared. A file holding a NUL byte is skipped as binary.

What is not read: anything outside this checkout. No token, no network, no
other repository. A citation of one of these records from somewhere else is
not seen, and every verdict says so.

Rule 3 has no allow-list. A tree that cites a gated record in order to say it
is waiting on it reads red, and the remedy is to word the line without the
number until the record is ready.

Exit codes
----------
0   every record is coherent and no gated record is cited in this tree
1   a violation
2   the check could not run: no such directory, no records, a numbered file
    in the directory that is not named as a record, not a git work tree, or
    a tracked file that could not be read. Blind is not empty.

Usage
-----
    python3 scripts/adr_preconditions.py docs/adr
    python3 scripts/adr_preconditions.py --self-test

Everything this prints is ASCII.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SECTION = "Do not implement until"
IMPLEMENTABLE = "Implementable now:"

#: The statuses the template offers. Anything else is a typo, and a typo in
#: this field must not be tolerated: an unrecognised status would otherwise
#: fall through every rule below and read as compliant.
VALID_STATUSES = ("Accepted", "Proposed", "Superseded")

HISTORY_NAME = "CHANGELOG.md"
HISTORY_SUFFIX = ".history.md"

NOT_SEEN = (
    "History files (CHANGELOG.md, *.history.md) were not read, and a citation "
    "from outside this checkout is not seen."
)

_STATUS = re.compile(r"^-[ \t]*\*\*Status:\*\*[ \t]*(?P<status>.+?)[ \t]*$")
_HEADING = re.compile(r"^##[ \t]+(?P<title>.+?)[ \t]*$")
_BOX = re.compile(r"^[ \t]*-[ \t]*\[(?P<mark>[ xX])\]")
_FENCE = re.compile(r"^[ \t]*(?:```|~~~)")
_RECORD_FILE = re.compile(r"^(?P<number>\d{4})-.+\.md$")
_BY_NUMBER = re.compile(r"(?<![A-Za-z])ADR[- \t]?(?P<number>\d{4})(?!\d)", re.IGNORECASE)


class Refusal(Exception):
    """The check could not read what it judges. Exit 2, never a pass."""


@dataclass
class Record:
    """One record, parsed only as far as the three rules need."""

    number: int
    path: Path
    status: str | None = None
    has_section: bool = False
    states_implementable: bool = False
    open_preconditions: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"ADR-{self.number:04d}"

    @property
    def is_gated(self) -> bool:
        """Held back by its own terms: not accepted, or holding an open box."""
        return self.status == "Proposed" or bool(self.open_preconditions)


def parse(path: Path, text: str) -> Record:
    """Read one record's status and its preconditions.

    Fence-aware on purpose: the template quotes the section's own format, and
    a record may quote a box in a fenced block. A parser that scored fences
    would read a quoted example as a real open precondition.
    """
    match = _RECORD_FILE.match(path.name)
    record = Record(number=int(match["number"]) if match else -1, path=path)
    in_fence = False
    in_section = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        status = _STATUS.match(line)
        if status and record.status is None:
            record.status = status["status"]
        heading = _HEADING.match(line)
        if heading:
            # A section ends where the next one begins.
            in_section = heading["title"] == SECTION
            record.has_section = record.has_section or in_section
            continue
        if in_section:
            _read_section_line(record, line)
    return record


def _read_section_line(record: Record, line: str) -> None:
    if f"**{IMPLEMENTABLE}**" in line:
        record.states_implementable = True
    box = _BOX.match(line)
    if box and box["mark"] == " ":
        record.open_preconditions.append(line.split("]", 1)[1].strip())


def load_records(adr_dir: Path) -> list[Record]:
    """Every numbered record in the directory. Number 0000 is the template."""
    records = []
    for path in sorted(adr_dir.glob("*.md")):
        match = _RECORD_FILE.match(path.name)
        if not match and path.name[0].isdigit():
            # Read as no record, it would be a record nothing checks.
            raise Refusal(f"{path.name} in {adr_dir} starts with a digit and is not named NNNN-<title>.md")
        if match and int(match["number"]) != 0:
            records.append(parse(path, path.read_text(encoding="utf-8")))
    return records


def _git(cwd: Path, *args: str) -> str:
    # GIT_DIR and GIT_INDEX_FILE outrank `-C`, and git exports them to a
    # hook. Left in, the check would read a repository nobody named, and the
    # self-test would stage its fixtures into the caller's index.
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    try:
        done = subprocess.run(
            ["git", "-C", str(cwd), *args],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as error:
        raise Refusal(f"could not run git: {error}") from error
    if done.returncode != 0:
        said = done.stderr.strip() or f"exit {done.returncode}"
        raise Refusal(f"git {' '.join(args)} failed in {cwd}: {said}")
    return done.stdout


def tracked_outside(adr_dir: Path) -> tuple[Path, list[str]]:
    """The checkout's root, and every tracked path a citation may live in.

    The file set is asked of git rather than walked, so `.git` and anything
    ignored or untracked is out by construction, and a directory that is not a
    work tree is refused rather than read as a tree with no citations.
    """
    root = Path(_git(adr_dir, "rev-parse", "--show-toplevel").strip())
    prefix = _git(adr_dir, "rev-parse", "--show-prefix").strip()
    if not prefix:
        # Leaving the record directory out would leave the whole tree out.
        raise Refusal(f"{adr_dir} is the checkout's root, so there is no tree outside it to read")
    paths = []
    for path in _git(root, "ls-files", "-z").split("\0"):
        name = path.rsplit("/", 1)[-1]
        if not path or path.startswith(prefix):
            continue
        if name == HISTORY_NAME or name.endswith(HISTORY_SUFFIX):
            continue
        paths.append(path)
    return root, paths


def citations_in(text: str, by_path: re.Pattern[str], held: set[int]) -> list[tuple[int, int]]:
    """(line number, record number) for each citation of a held record."""
    found = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        numbers = {int(m["number"]) for m in _BY_NUMBER.finditer(line)}
        numbers |= {int(m["number"]) for m in by_path.finditer(line)}
        found.extend((line_no, n) for n in sorted(numbers & held))
    return found


def gather(adr_dir: Path, held: set[int]) -> tuple[dict[int, list[str]], int]:
    """Where each held record is cited in this checkout, and how many files were read."""
    root, paths = tracked_outside(adr_dir)
    by_path = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(adr_dir.resolve().name)}/(?P<number>\d{{4}})-")
    cited: dict[int, list[str]] = {}
    read = 0
    for path in paths:
        try:
            data = (root / path).read_bytes()
        except OSError as error:
            raise Refusal(f"could not read the tracked file {path}: {error}") from error
        read += 1
        if b"\0" in data:
            continue
        text = data.decode("utf-8", errors="replace")
        for line_no, number in citations_in(text, by_path, held):
            cited.setdefault(number, []).append(f"{path}:{line_no}")
    return cited, read


def judge(record: Record, where: list[str]) -> list[str]:
    """The failures one record earns, given where it is cited."""
    if record.status not in VALID_STATUSES:
        return [
            f"{record.name}: status is {record.status!r}, which is not one of "
            f"{list(VALID_STATUSES)}. An unrecognised status falls through every "
            "rule and reads as compliant."
        ]
    if record.status == "Superseded":
        # A dead record instructs nobody. Its preconditions went with it.
        return []
    failures = []
    opened = len(record.open_preconditions)
    if not record.has_section:
        failures.append(f"{record.name}: no '## {SECTION}' section. Every record carries one.")
    if record.status == "Accepted" and opened and not record.states_implementable:
        failures.append(
            f"{record.name}: Accepted with {opened} open precondition(s) and no "
            f"'{IMPLEMENTABLE}' line. A record settled in one half and deferred "
            "in the other must say which half is live."
        )
    if record.is_gated and where:
        reason = "is still Proposed" if record.status == "Proposed" else f"holds {opened} open precondition(s)"
        places = "".join(f"\n    {place}" for place in where)
        failures.append(f"{record.name} {reason}, and is cited outside the record directory:{places}")
    return failures


def run(adr_dir: Path) -> tuple[int, list[str]]:
    """The exit code and the lines to print for one record directory."""
    if not adr_dir.is_dir():
        raise Refusal(f"not a directory: {adr_dir}")
    try:
        records = load_records(adr_dir)
    except (OSError, UnicodeDecodeError) as error:
        raise Refusal(f"could not read the records: {error}") from error
    if not records:
        raise Refusal(f"no records found in {adr_dir}. A run that checks nothing must not report success.")
    cited, read = gather(adr_dir, {r.number for r in records})
    failures = [f for r in records for f in judge(r, cited.get(r.number, []))]
    count = sum(len(places) for places in cited.values())
    scope = f"{len(records)} record(s) checked against {count} citation(s) in {read} tracked file(s)"
    if not failures:
        return 0, [f"OK - {scope}; nothing gated is cited. {NOT_SEEN}"]
    out = [f"FAIL - {scope}; a record's status does not match what this tree says.", ""]
    for failure in failures:
        out.extend([f"  {failure}", ""])
    out.append("  Either the record is ready and should say so, or the work is ahead")
    out.append("  of the decision and should stop.")
    out.extend(["", f"  {NOT_SEEN}"])
    return 1, out


# --- the self-test -------------------------------------------------------------
#
# Each case is a throwaway git repository built to have one defect, or built
# not to, and the verdict the check must give on it. The record numbers are
# ones no real corpus here holds, and every citation is assembled at run time,
# so this file cites no record of the tree it is checked into.

_N = 9001


def _cite(number: int = _N) -> str:
    return f"ADR-{number:04d}"


def _record(status: str = "Accepted", box: str = "x", implementable: bool = True, section: bool = True) -> str:
    lines = ["# A record", "", f"- **Status:** {status}", "", "## Decision", "", "Something.", ""]
    if section:
        lines += [f"## {SECTION}", ""]
        if implementable:
            lines += [f"**{IMPLEMENTABLE}** the first half.", ""]
        lines += [f"- [{box}] a precondition", ""]
    return "\n".join(lines)


@dataclass
class Case:
    name: str
    code: int
    says: tuple[str, ...]
    record: str = ""
    tracked: dict[str, str] = field(default_factory=dict)
    untracked: dict[str, str] = field(default_factory=dict)
    is_repository: bool = True


def _cases() -> list[Case]:
    cited = {"README.md": f"See {_cite()} for the rule.\n"}
    fenced = _record() + "\n```markdown\n- [ ] a quoted box\n```\n"
    return [
        Case("accepted, ticked and cited is clean", 0, ("against 1 citation(s)",), _record(), cited),
        Case("Proposed and cited is refused", 1, (f"{_cite()} is still Proposed", "README.md:1"), _record("Proposed"), cited),
        Case(
            "an unticked box and cited is refused",
            1,
            (f"{_cite()} holds 1 open precondition(s)", "README.md:1"),
            _record(box=" "),
            cited,
        ),
        Case("Proposed and uncited is clean", 0, ("against 0 citation(s)",), _record("Proposed"), {"README.md": "Nothing.\n"}),
        Case(
            "a neighbour record and the history files are not citations",
            0,
            ("against 0 citation(s)",),
            _record("Proposed"),
            {
                "docs/adr/9002-other.md": _record() + f"\nBuilds on {_cite()}.\n",
                "CHANGELOG.md": f"{_cite()} was cited here once.\n",
                "docs/NOTES.history.md": f"> {_cite()} said so.\n",
                "src/CHANGELOG.md": f"{_cite()}\n",
            },
        ),
        Case(
            "a path to the record's file is a citation",
            1,
            ("is still Proposed", "docs/GUIDE.md:1"),
            _record("Proposed"),
            {"docs/GUIDE.md": f"[the rule](adr/{_N:04d}-a-record.md)\n"},
        ),
        Case(
            "the spaced, the joined and the lowercase forms are citations",
            1,
            ("a.txt:1", "a.txt:2", "a.txt:3"),
            _record("Proposed"),
            {"a.txt": f"ADR {_N:04d}\nADR{_N:04d}\n{_cite().lower()}\n"},
        ),
        Case(
            "a number this directory does not hold is not counted",
            0,
            ("against 0 citation(s)",),
            _record("Proposed"),
            {"README.md": f"{_cite(_N + 5)} and {_cite()}7 are elsewhere.\n"},
        ),
        Case(
            "an untracked file is not read",
            0,
            ("against 0 citation(s)",),
            _record("Proposed"),
            {"README.md": "Nothing.\n"},
            {"scratch.md": f"{_cite()}\n"},
        ),
        Case(
            "a binary file is skipped",
            0,
            ("against 0 citation(s) in 1 tracked",),
            _record("Proposed"),
            {"blob.bin": f"\0{_cite()}\n"},
        ),
        Case(
            "Accepted with an open box and no implementable line is refused",
            1,
            (f"no '{IMPLEMENTABLE}' line",),
            _record(box=" ", implementable=False),
        ),
        Case("a record with no section is refused", 1, (f"no '## {SECTION}' section",), _record(section=False)),
        Case("an unknown status is refused", 1, ("status is 'Acceptd'",), _record("Acceptd"), cited),
        Case("a box inside a fence is not a precondition", 0, ("nothing gated is cited",), fenced, cited),
        Case("a superseded record instructs nobody", 0, ("nothing gated is cited",), _record("Superseded", box=" "), cited),
        Case("a directory holding only the template is refused", 2, ("no records found",)),
        Case(
            "a numbered file not named as a record is refused",
            2,
            ("9003_stray.md",),
            _record(),
            {"docs/adr/9003_stray.md": _record("Proposed"), **cited},
        ),
        Case("a directory that is not a work tree is refused", 2, ("git rev-parse",), _record(), cited, is_repository=False),
    ]


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))


def _stage(case: Case, root: Path) -> Path:
    adr_dir = root / "docs" / "adr"
    files = {"docs/adr/0000-template.md": _record("Proposed | Accepted | Superseded", box=" "), **case.tracked}
    if case.record:
        files[f"docs/adr/{_N:04d}-a-record.md"] = case.record
    _write(root, files)
    if case.is_repository:
        _git(root, "init", "--quiet")
        _git(root, "add", "--all")
    _write(root, case.untracked)
    return adr_dir


def _verdict(adr_dir: Path) -> tuple[int, str]:
    try:
        code, lines = run(adr_dir)
    except Refusal as refusal:
        return 2, str(refusal)
    return code, "\n".join(lines)


def _decoy_is_untouched() -> bool:
    """With GIT_DIR and GIT_INDEX_FILE exported at a decoy, the verdict holds and the decoy's index does not move."""
    case = _cases()[1]
    names = ("GIT_DIR", "GIT_INDEX_FILE")
    prior = {name: os.environ.get(name) for name in names}
    with tempfile.TemporaryDirectory() as tmp:
        decoy = Path(tmp) / "decoy"
        _write(decoy, {"keep.txt": "kept\n"})
        _git(decoy, "init", "--quiet")
        _git(decoy, "add", "--all")
        before = _git(decoy, "ls-files", "--stage")
        os.environ.update({"GIT_DIR": str(decoy / ".git"), "GIT_INDEX_FILE": str(decoy / ".git" / "index")})
        try:
            code, _ = _verdict(_stage(case, Path(tmp) / "subject"))
        except Refusal:
            code = -1
        finally:
            for name, value in prior.items():
                os.environ.pop(name, None)
                if value is not None:
                    os.environ[name] = value
        after = _git(decoy, "ls-files", "--stage")
    return code == case.code and bool(before) and before == after


def self_test() -> int:
    wrong = 0
    cases = _cases()
    for case in cases:
        with tempfile.TemporaryDirectory() as tmp:
            code, said = _verdict(_stage(case, Path(tmp)))
        missing = [s for s in case.says if s not in said]
        ok = code == case.code and not missing
        wrong += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} exit {code} (want {case.code}): {case.name}")
        if not ok:
            print(f"       missing {missing!r} in:\n{said}")
    held = _decoy_is_untouched()
    wrong += 0 if held else 1
    print(f"  {'ok  ' if held else 'FAIL'} an exported GIT_DIR and GIT_INDEX_FILE are not followed")
    refused = sum(1 for c in cases if c.code == 1)
    quiet = sum(1 for c in cases if c.code == 0)
    if wrong:
        print(f"SELF-TEST FAILED - {wrong} check(s) gave the wrong verdict.")
        return 1
    print(f"Self-test OK - {len(cases)} case(s): {refused} refused, {quiet} quiet, {len(cases) - refused - quiet} could not run.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refuse a record cited in this tree while it is gated.")
    parser.add_argument("adr_dir", nargs="?", help="directory holding the numbered records")
    parser.add_argument("--self-test", action="store_true", help="stage each refusal and each quiet case, and judge them")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.adr_dir:
        parser.error("name the record directory, or pass --self-test")
    try:
        code, lines = run(Path(args.adr_dir))
    except Refusal as refusal:
        print(f"adr_preconditions: {refusal}", file=sys.stderr)
        return 2
    for line in lines:
        print(line, file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

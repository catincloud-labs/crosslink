# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""This tree is ASCII, and here is the thing that checks it.

Two separate reasons, and they fail differently, so both are asserted here.

**The encoding one.** An exception message, a log line and a command's output
are read in terminals whose encoding nobody here controls. A character a
browser renders is not thereby one a console at cp1252 prints, so a character
that survives review is not automatically one that survives a traceback.

**The register one.** This tree is written to be read by strangers. Em-dashes
and decorative emoji are a recognisable machine-written signature, and a
package asking to be read should not carry one.

The second reason is a style rule, and a style rule with no control is a
suggestion. This is the control. It is modelled on the test of the same name
in ``dagster-dex``, which shares this package's read side
(``src/crosslink/PROVENANCE.md``), and it reads files the same way: as bytes,
line by line, so a file that is not UTF-8 is reported and never skipped.

**What is skipped, and how to see whether that is anything.** A tracked path
that matches one of four patterns is skipped; the patterns are the three
constants below the imports. A published copy of this tree tracks no path
they match. Whether the checkout in front of you tracks one is one
command::

    git ls-files -- deploy RUNBOOK.md tests/test_producer_follow.py '*.history.md'

Where that prints nothing, nothing is skipped, and the test below is the
whole tree with no exemption. ``test_the_skip_is_exactly_the_four_paths``
holds the rule to those four, so a fifth cannot be added by widening a
pattern. There is no skip by file type: a tracked binary file would be
reported, and that report is where tracking one gets decided.

**What it reads.** The working copy of each tracked file, and each file's
name. It does not read the index, so a change staged and then undone on disk
is not seen until it is committed and checked out.
"""

from __future__ import annotations

import ast
import os
import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent

# Paths skipped where tracked; the module docstring says how to see
# whether any is. A prefix ends in "/" and matches a directory's files, a name
# matches one file, and the suffix matches a file of that kind anywhere.
_SKIPPED_PREFIXES = ("deploy/",)
_SKIPPED_NAMES = ("RUNBOOK.md", "tests/test_producer_follow.py")
_SKIPPED_SUFFIX = ".history.md"


def _is_skipped(name: str) -> bool:
    return (
        name.startswith(_SKIPPED_PREFIXES)
        or name in _SKIPPED_NAMES
        or name.endswith(_SKIPPED_SUFFIX)
    )


def _tracked_files(repo: pathlib.Path = REPO) -> list[str]:
    """Ask git, rather than walking the tree.

    A walk would pick up ``.venv``, build artifacts and anything else
    untracked, and would then be asserting something about a working directory
    rather than about what this repository holds.

    ``-z`` makes git print each name as it is stored. Without it, git quotes a
    name holding a byte above 0x7F, a quote, a backslash or a control
    character, and the quoted string names no file on disk, so the file it
    stands for would never be read.
    """

    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    return [os.fsdecode(name) for name in out.stdout.split(b"\0") if name]


def _checked_files() -> list[str]:
    return [name for name in _tracked_files() if not _is_skipped(name)]


def _offenders_in(name: str, path: pathlib.Path) -> list[str]:
    """Every line of one tracked file that is not ASCII, read as bytes.

    The file is split on LF and each line decoded on its own. A valid
    multi-byte UTF-8 sequence never contains 0x0A, so the split never cuts a
    character, and one undecodable line cannot hide another line.

    A line that decodes is reported by the characters it holds, ``U+2014``. A
    line that does not is reported by each byte above 0x7F and that byte's
    offset in the file, counted from 0: the em dash as cp1252 writes it is a
    lone 0x97, and a check that skipped an undecodable file would pass the
    very character it was written to refuse. A file that cannot be read is
    reported too: an unreadable file is not a clean one.
    """

    try:
        data = path.read_bytes()
    except OSError as exc:
        return [f"{name}: unreadable ({type(exc).__name__})"]
    offenders: list[str] = []
    start = 0
    for lineno, raw in enumerate(data.split(b"\n"), 1):
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError:
            shown = ", ".join(
                f"0x{byte:02X} at byte {start + i}"
                for i, byte in enumerate(raw)
                if byte > 127
            )
            offenders.append(f"{name}:{lineno}: {shown} (not UTF-8)")
        else:
            bad = {c for c in line if ord(c) > 127}
            if bad:
                shown = ", ".join(f"U+{ord(c):04X}" for c in sorted(bad))
                offenders.append(f"{name}:{lineno}: {shown}")
        start += len(raw) + 1
    return offenders


@pytest.mark.skipif(
    subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--git-dir"], capture_output=True
    ).returncode
    != 0,
    reason="not a git checkout, so there is no file list to check",
)
def test_every_tracked_file_is_ascii():
    """The whole repository, not a hand-maintained list of files to watch.

    Asserting over ``git ls-files`` rather than a literal list is what makes
    this hold for a file nobody has written yet. A list would have to be
    updated by the same person who is about to paste an em-dash into a new
    document. It also means the test sees a new file only once it is tracked:
    ``git add`` it before reading a green here as a statement about it.
    """

    offenders: list[str] = []
    for name in _checked_files():
        if not name.isascii():
            offenders.append(f"{name!r}: the file's name is not ASCII")
        offenders.extend(_offenders_in(name, REPO / name))

    assert not offenders, (
        "non-ASCII characters in tracked files; this tree is ASCII "
        "(see tests/test_ascii_only.py for both reasons):\n  "
        + "\n  ".join(offenders)
    )


def test_the_skip_is_exactly_the_four_paths():
    """The skip names four paths and matches nothing else.

    A skip rule is the part of a check most likely to be widened by the
    change it would otherwise refuse. Both arms are pinned: each of the four
    is skipped, and their near neighbours are not.
    """

    for skipped in (
        "deploy/any.yml",
        "deploy/nested/any.sh",
        "RUNBOOK.md",
        "tests/test_producer_follow.py",
        "README.history.md",
        "docs/design/write-path.history.md",
    ):
        assert _is_skipped(skipped), skipped
    for checked in (
        "README.md",
        "CHANGELOG.md",
        "docs/RUNBOOK.md",
        "deployment.md",
        "src/deploy/any.py",
        "tests/test_produce.py",
        "docs/history.md",
        "docs/adr/0001-the-project-seam-is-tiered-and-a-tier-is-checked-not-claimed.md",
        ".github/workflows/checks.yml",
        "tests/test_ascii_only.py",
        "docs/notes.pdf",
        "src/crosslink/data.GZ",
        "logo.png",
    ):
        assert not _is_skipped(checked), checked


def test_runtime_messages_are_ascii():
    """Every string this package can raise or print.

    The narrowest and most load-bearing of the checks. A docstring's em-dash
    is a style question; an exception message's em-dash lands in a traceback,
    in a terminal, in an issue report, rendered by an encoding nobody chose.

    Walks the AST rather than grepping, so it sees the string literals as the
    compiler does and cannot be fooled by one spanning several source lines.
    """

    src_root = REPO / "src" / "crosslink"
    offenders: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and not node.value.isascii()
            ):
                offenders.append(
                    f"{path.relative_to(REPO)}:{node.lineno}: {node.value[:60]!r}"
                )

    assert not offenders, (
        "non-ASCII in runtime string literals. These reach terminals through "
        "tracebacks and CLI output, where the encoding is not ours to choose:\n  "
        + "\n  ".join(offenders)
    )


def test_the_check_can_actually_fail():
    """Calibration: the predicate must reject a known-bad input.

    A checker that has silently stopped detecting anything passes every
    commit, which is the one failure the checks above cannot observe about
    themselves.

    The bad characters are written as escapes rather than literally, so this
    file stays ASCII and does not fail the very check it calibrates. The rule
    is about what a reader and a terminal receive, and an escape sequence is
    neither.
    """

    assert not f"an em-dash {chr(0x2014)} here".isascii()
    assert not f"an emoji {chr(0x1F534)} here".isascii()
    assert not f"a warning sign {chr(0x26A0)} here".isascii()
    assert "a plain hyphen - here".isascii()


def _plant(count: int, planted: dict[int, bytes]) -> bytes:
    """``count`` lines of 20 ASCII bytes each, with the numbered lines replaced.

    Twenty bytes a line is what lets an offset below be counted by hand.
    """

    return b"".join(
        planted.get(n, b"line %02d: plain text\n" % n) for n in range(1, count + 1)
    )


# Five arms. Bytes above 0x7F are written as escapes, so this file stays ASCII.
# Arm 3: fifteen lines of 20 bytes (300), then 14 bytes into line 16: byte 314.
# Arm 4: two lines (40), a 23-byte line 3 (63), 33 more lines (723), then 34
# bytes into line 37: byte 757.
# Arm 5: fifteen lines (300), then 14 bytes into line 16 the three bytes of a
# U+2014 at 314 to 316, then " and", then a lone byte at 321.
_ARM_ASCII = _plant(20, {})
_ARM_VALID = _plant(20, {16: b"line 16: plain\xe2\x80\x94 text\n"})
_ARM_LONE = _plant(20, {16: b"line 16: plain\x97 text\n"})
_ARM_BOTH = _plant(
    40,
    {
        3: b"line 03: plain\xe2\x80\x94 text\n",
        37: b"line 37: plain text, then a byte: \x97\n",
    },
)
_ARM_MIXED = _plant(20, {16: b"line 16: plain\xe2\x80\x94 and\x97 text\n"})


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        pytest.param(_ARM_ASCII, [], id="1-ascii"),
        pytest.param(_ARM_VALID, ["plant.txt:16: U+2014"], id="2-valid-u2014"),
        pytest.param(
            _ARM_LONE,
            ["plant.txt:16: 0x97 at byte 314 (not UTF-8)"],
            id="3-lone-0x97",
        ),
        pytest.param(
            _ARM_BOTH,
            [
                "plant.txt:3: U+2014",
                "plant.txt:37: 0x97 at byte 757 (not UTF-8)",
            ],
            id="4-valid-then-lone",
        ),
        pytest.param(
            _ARM_MIXED,
            [
                "plant.txt:16: 0xE2 at byte 314, 0x80 at byte 315, "
                "0x94 at byte 316, 0x97 at byte 321 (not UTF-8)"
            ],
            id="5-mixed-line",
        ),
    ],
)
def test_the_file_check_reports_every_arm(tmp_path, data, expected):
    """Calibration of the file check, through the function the real test calls.

    ``test_the_check_can_actually_fail`` calibrates ``str.isascii`` on strings
    built in memory, so it never reaches a read and could not see the read
    skip a file. These arms write bytes to disk and go through
    ``_offenders_in``, the same call the whole-repository test makes for each
    tracked file.

    Arm 3 is the em dash as cp1252 writes it, a lone 0x97, which is the
    likeliest way one reaches a tree from a Windows editor or clipboard. Arm 4
    is why the check reads line by line: one undecodable line late in a file
    must not hide a valid U+2014 earlier in it. Arm 5 is a line that holds
    both, and pins two things: every byte above 0x7F on an undecodable line is
    listed, not just the first, and a valid U+2014 on such a line is listed as
    its three bytes, because "(not UTF-8)" describes the line.
    """

    path = tmp_path / "plant.txt"
    path.write_bytes(data)
    assert _offenders_in("plant.txt", path) == expected


def test_the_arms_put_each_byte_where_its_offset_says():
    """The offsets above are counted by hand, so count them a second way.

    The check finds a line and an offset by splitting on LF and summing line
    lengths. This finds them with ``bytes.index`` and a count of the LFs
    before the byte, so a fixture edited out from under its expected offset
    goes red here rather than having the expectation edited to match.
    """

    assert _ARM_ASCII.isascii()
    assert _ARM_VALID[: _ARM_VALID.index(b"\xe2\x80\x94")].count(b"\n") == 15
    assert _ARM_LONE.index(b"\x97") == 314
    assert _ARM_LONE[:314].count(b"\n") == 15
    assert _ARM_BOTH[: _ARM_BOTH.index(b"\xe2\x80\x94")].count(b"\n") == 2
    assert _ARM_BOTH.index(b"\x97") == 757
    assert _ARM_BOTH[:757].count(b"\n") == 36
    assert _ARM_MIXED.index(b"\xe2\x80\x94") == 314
    assert _ARM_MIXED.index(b"\x97") == 321
    assert _ARM_MIXED[:321].count(b"\n") == 15


def test_an_unreadable_tracked_file_is_an_offender(tmp_path):
    """A file the check cannot read is not a file the check found clean.

    ``git ls-files`` lists the index, not the working tree, so it can list a
    path that does not read as a file: a tracked file deleted and not yet
    staged with ``git rm``, or a submodule, whose path is a directory.
    """

    gone = tmp_path / "gone.txt"
    assert _offenders_in("gone.txt", gone) == [
        "gone.txt: unreadable (FileNotFoundError)"
    ]


def test_a_name_git_would_quote_is_listed_as_it_is(tmp_path):
    """A tracked file whose name holds a byte above 0x7F is read, not lost.

    By default ``git ls-files`` quotes such a name and escapes its bytes,
    which names no file on disk, so the file would be skipped as unreadable
    and its contents never read. The name is built with ``chr``, so this file
    stays ASCII. The name itself is an offender too, and the tree-wide test
    reports it; this arm is about the contents being reached.
    """

    name = f"caf{chr(0xE9)}.txt"
    (tmp_path / name).write_bytes(b"line \x97\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", name], check=True)
    listed = _tracked_files(tmp_path)
    assert listed == [name]
    assert [o for n in listed for o in _offenders_in(n, tmp_path / n)] == [
        f"{name}:1: 0x97 at byte 5 (not UTF-8)"
    ]

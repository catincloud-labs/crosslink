# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Each load-time check in `src` refuses a wrong fact, and none goes unplanted.

A module that holds a fact by construction checks it when it loads, with an
explicit `raise`. A check nobody has seen fire is not shown to be a check, so
each one has a row in `PLANTS`: the module's own source with one fact made
wrong, which must make the import raise with that check's message. The clean
source runs first, so a check that raises on everything is caught too.

The second case reads the population a different way from the table: it walks
every module under `src/crosslink`, reads the message of every `raise` in a
top-level statement other than a `def`, a `class` or the `__main__` guard, and
requires that set, module by module, to equal the messages the table plants.
A check added with no plant is red here, and so is a new arm of an existing
check with its own message, or a plant whose check is gone.

This file is the coding standard's rule 5 reader for `src`, declared in
`power-of-ten.json`:

Measures: scripts/check_power_of_ten.py, rule 5

`serve`, `produce` and `conformance` import `ration` or pytest when they load,
so this file needs the `service` and `test` extras, as the suite does.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "crosslink"


class Plant(NamedTuple):
    id: str
    module: str
    fact: str
    wrong: str
    message: str


# Every module in the package declares `__all__`, and each checks it.
_EXPORTING = (
    "__init__", "conformance", "conformance_calibration", "context", "dbt",
    "declarations", "deliver", "delta", "findings", "generate", "model",
    "produce", "project", "protocol", "serve", "service", "verify", "wire",
)

PLANTS = (
    Plant(
        "serve-two-layers-one-string",
        "serve",
        'LAYER_COMPARER = "comparer"',
        'LAYER_COMPARER = "frame"',
        "serve: two layers are one string, so a line cannot say which layer refused",
    ),
    Plant(
        "serve-two-own-controls-one-string",
        "serve",
        'BODY_TOO_LARGE = "body-too-large"',
        'BODY_TOO_LARGE = "length-required"',
        "serve: the comparer's own controls are not three strings apart from the frame's",
    ),
    Plant(
        "serve-an-own-control-is-a-frame-control",
        "serve",
        'BODY_TOO_LARGE = "body-too-large"',
        'BODY_TOO_LARGE = "oversized"',
        "serve: the comparer's own controls are not three strings apart from the frame's",
    ),
    Plant(
        "serve-the-ceiling-below-a-whole-frame",
        "serve",
        "MAX_BODY_BYTES = framing.HEADER_SIZE + framing.MAX_BODY_LENGTH",
        "MAX_BODY_BYTES = framing.MAX_BODY_LENGTH",
        "serve: the ceiling refuses a frame whose body is within the frame's maximum",
    ),
    Plant(
        "serve-the-ceiling-past-what-a-length-reads",
        "serve",
        "MAX_BODY_BYTES = framing.HEADER_SIZE + framing.MAX_BODY_LENGTH",
        "MAX_BODY_BYTES = 10 ** 18",
        "serve: a request declaring the ceiling's own length would be refused as unreadable",
    ),
    Plant(
        "produce-two-events-one-string",
        "produce",
        'EVENT_UNREACHABLE = "unreachable"',
        'EVENT_UNREACHABLE = "answered"',
        "produce: two events are one string, so a line cannot say how the run ended",
    ),
    Plant(
        "produce-an-answer-maximum-of-nothing",
        "produce",
        "MAX_ANSWER_BYTES = framing.MAX_BODY_LENGTH",
        "MAX_ANSWER_BYTES = 0",
        "produce: the answer's maximum admits no answer",
    ),
    Plant(
        "wire-two-controls-one-string",
        "wire",
        'DIGEST_MISMATCH = "digest-mismatch"',
        'DIGEST_MISMATCH = "malformed-envelope"',
        "wire: two decode controls are one string, so a refusal cannot say which check failed",
    ),
    Plant(
        "wire-an-envelope-field-decode-does-not-read",
        "wire",
        "_ENVELOPE_FIELDS = tuple(f.name for f in dataclass_fields(Envelope))",
        '_ENVELOPE_FIELDS = tuple(f.name for f in dataclass_fields(Envelope)) + ("signature",)',
        "wire: the envelope's fields are not the names decode_envelope reads",
    ),
    Plant(
        "wire-a-payload-field-decode-reads-is-gone",
        "wire",
        "_PAYLOAD_FIELDS = tuple(f.name for f in dataclass_fields(FingerprintPayload))",
        "_PAYLOAD_FIELDS = tuple(f.name for f in dataclass_fields(FingerprintPayload))[:-1]",
        "wire: the payload's fields are not the names decode_envelope reads",
    ),
    Plant(
        "findings-two-kinds-one-string",
        "findings",
        'UNKNOWN_READER = "unknown-reader"',
        'UNKNOWN_READER = "dangling-declared-key"',
        "findings: two finding kinds are one string, so a consumer keying by kind merges them",
    ),
    Plant(
        "service-two-verdict-kinds-one-string",
        "service",
        'DRIFT = "drift"',
        'DRIFT = "baseline"',
        "service: two verdict kinds or the refusal are one string, so an answer cannot say which",
    ),
) + tuple(
    Plant(
        f"{module.strip('_')}-an-export-not-defined",
        module,
        "__all__ = [",
        '__all__ = ["_not_defined_anywhere", ',
        f"{'crosslink' if module == '__init__' else module}: a name in __all__ is not defined in the module",
    )
    for module in _EXPORTING
)


def _load(module: str, source: str) -> None:
    """Run ``source`` as a fresh copy of ``crosslink.<module>``.

    Registered in ``sys.modules`` while it runs, because a dataclass looks its
    own module up there, and removed after, so the real module is untouched.
    """

    name = f"crosslink._load_time_check_{module}"
    spec = importlib.util.spec_from_loader(name, loader=None)
    assert spec is not None
    copy = importlib.util.module_from_spec(spec)
    copy.__package__ = "crosslink"
    sys.modules[name] = copy
    try:
        exec(compile(source, str(PACKAGE / f"{module}.py"), "exec"), copy.__dict__)
    finally:
        del sys.modules[name]


def _source(module: str) -> str:
    return (PACKAGE / f"{module}.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("plant", PLANTS, ids=[plant.id for plant in PLANTS])
def test_a_planted_wrong_fact_makes_the_import_raise(plant: Plant) -> None:
    source = _source(plant.module)
    # The clean arm first: the module's own source loads.
    _load(plant.module, source)
    # The fact must be in the source exactly once, or the plant planted nothing.
    assert source.count(plant.fact) == 1, plant.fact
    with pytest.raises(RuntimeError, match=f"^{re.escape(plant.message)}$"):
        _load(plant.module, source.replace(plant.fact, plant.wrong))


def _is_main_guard(node: ast.stmt) -> bool:
    """``if __name__ == "__main__":``, which runs the entry point rather than checking a fact."""

    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        and len(node.test.comparators) == 1
        and isinstance(node.test.comparators[0], ast.Constant)
        and node.test.comparators[0].value == "__main__"
    )


def _raised_at_load(path: Path) -> set[str]:
    """The message of every ``raise`` in a top-level statement other than a
    ``def``, a ``class`` or the ``__main__`` guard, each arm of a compound
    check read on its own.

    A ``raise`` whose message is not a string constant is read as its line,
    which no plant can match, so it reads red rather than going uncounted.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if _is_main_guard(node):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Raise):
                continue
            exc = inner.exc
            if (
                isinstance(exc, ast.Call)
                and exc.args
                and isinstance(exc.args[0], ast.Constant)
                and isinstance(exc.args[0].value, str)
            ):
                found.add(exc.args[0].value)
            else:
                found.add(f"<a raise with no constant message, line {inner.lineno}>")
    return found


def test_every_load_time_check_in_src_has_a_plant() -> None:
    modules = sorted(PACKAGE.rglob("*.py"))
    # The positive control: a walk that found nothing would pass the loop.
    assert len(modules) > 5, modules
    raised = {}
    for path in modules:
        found = _raised_at_load(path)
        if found:
            # Keyed by the path under the package, so two modules sharing a
            # stem in different subpackages stay two.
            raised[path.relative_to(PACKAGE).with_suffix("").as_posix()] = found
    planted: dict[str, set[str]] = {}
    for plant in PLANTS:
        planted.setdefault(plant.module, set()).add(plant.message)
    assert raised == planted


def test_the_main_guard_is_read_as_the_entry_point_and_nothing_else() -> None:
    """The one shape the walk skips, read on both arms: the guard itself is
    skipped, and a check that merely sits beside it is not."""

    guarded = ast.parse('if __name__ == "__main__":\n    raise SystemExit(0)\n').body[0]
    unguarded = ast.parse('if __name__ == "other":\n    raise SystemExit(0)\n').body[0]
    assert _is_main_guard(guarded)
    assert not _is_main_guard(unguarded)

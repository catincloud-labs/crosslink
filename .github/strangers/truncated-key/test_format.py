"""A stranger who believes a format is correct, and it is not.

The defect is the stranger's own and ships nowhere in the package: a correct
format whose declared keys keep only their first column. A truncated key
still looks like a declared grain, so nothing raises and no note is owed. The
contract must fail it on the one arm that reads a composite key whole, and
nowhere else.
"""

from __future__ import annotations

from dataclasses import replace

from stranger import a_correct_format

from crosslink import ProjectDeclarations
from crosslink.conformance import ProjectSourceContract


class TruncatingFormat:
    format = "stranger-truncating"

    def __init__(self, declarations, semantics, sources):
        self._core = a_correct_format(declarations, semantics, sources)

    def declarations(self) -> ProjectDeclarations:
        whole = self._core.declarations()
        keys = tuple(replace(key, columns=key.columns[:1]) for key in whole.declared_keys)
        return replace(whole, declared_keys=keys)


class TestStrangerFormat(ProjectSourceContract):
    def make_project(self, declarations, semantics, sources):
        return TruncatingFormat(declarations, semantics, sources)

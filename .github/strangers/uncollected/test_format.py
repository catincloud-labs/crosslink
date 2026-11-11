"""A stranger whose format is correct and whose run judges nothing.

The class below is wired like the passing arm's and is not named `Test...`,
so pytest collects no test from it. A run that judged nothing must not read
as a pass: pytest exits 5, and the arm is asserted on that code.
"""

from __future__ import annotations

from stranger import a_correct_format

from crosslink.conformance import FingerprintedProjectContract


class StrangerFormat(FingerprintedProjectContract):
    def make_project(self, declarations, semantics, sources):
        return a_correct_format(declarations, semantics, sources)

"""A stranger with a correct format, judged by the tier-2 contract.

The whole of the wiring is `make_project`: the stranger's format inherits
every arm. This is the last arm, read only after each wrong format above was
seen failing.
"""

from __future__ import annotations

from stranger import a_correct_format

from crosslink.conformance import FingerprintedProjectContract


class TestStrangerFormat(FingerprintedProjectContract):
    def make_project(self, declarations, semantics, sources):
        return a_correct_format(declarations, semantics, sources)

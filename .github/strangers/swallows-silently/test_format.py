"""A stranger whose format skips what it cannot read and leaves no note.

The format is the package's `AFormatThatSwallowsSilently`, wired to the tier
it claims under a stranger's test class. It never raises, so only the arms
that demand a note may fail: the ones its `expected_reds` names.
"""

from __future__ import annotations

from crosslink.conformance import ProjectSourceContract
from crosslink.conformance_calibration import AFormatThatSwallowsSilently


class TestStrangerFormat(ProjectSourceContract):
    def make_project(self, declarations, semantics, sources):
        return AFormatThatSwallowsSilently(declarations, semantics, sources)

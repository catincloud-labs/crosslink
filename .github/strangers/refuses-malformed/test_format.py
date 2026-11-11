"""A stranger whose format raises on a malformed declaration.

The format is the package's `AFormatThatRefusesMalformedInput`, wired to the
tier it claims under a stranger's test class. The contract must fail it on
the arms that format's `expected_reds` names, each with the exception named
there, and pass it on every other arm.
"""

from __future__ import annotations

from crosslink.conformance import ProjectSourceContract
from crosslink.conformance_calibration import AFormatThatRefusesMalformedInput


class TestStrangerFormat(ProjectSourceContract):
    def make_project(self, declarations, semantics, sources):
        return AFormatThatRefusesMalformedInput(declarations, semantics, sources)

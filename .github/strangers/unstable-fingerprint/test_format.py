"""A stranger whose format claims tier 2 and never fingerprints alike twice.

The format is the package's `AFormatWithAnUnstableFingerprint`, wired to the
tier-2 contract under a stranger's test class. Every tier-1 arm must pass,
and the arms its `expected_reds` names must fail.
"""

from __future__ import annotations

from crosslink.conformance import FingerprintedProjectContract
from crosslink.conformance_calibration import AFormatWithAnUnstableFingerprint


class TestStrangerFormat(FingerprintedProjectContract):
    def make_project(self, declarations, semantics, sources):
        return AFormatWithAnUnstableFingerprint(declarations, semantics, sources)

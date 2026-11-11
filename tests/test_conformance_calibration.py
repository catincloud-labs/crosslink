# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The conformance suite, observed red before it is trusted.

ADR-0001's falsifier names the failure this file exists to prevent: a suite
every candidate passes trivially is the capability-flag design wearing a
suite's name. A negative that is a bad *input* does not answer it: something
has to build a bad *format* and watch the contract refuse it, because a
control observed only to pass has not been shown to be a control.

Three deliberately non-conforming formats ship in the package, in
``crosslink.conformance_calibration``, each a thin wrapper around a real
``DagsterProject`` so each is wrong in **exactly one way** - a subject wrong
in two ways proves only that the suite catches one of them. This file wires
each to its tier, and each calibration test runs every contract arm directly
and asserts the exact red/green **partition**: which arms failed, and with
what. That is stronger than asserting the reds alone, in both directions -
a wrapper that is accidentally wrong twice fails an arm outside its expected
set, and a contract arm that quietly stops discriminating leaves its
expected red missing. Either way the calibration itself goes red, which is
the property a calibration is for.

The wrong formats ship beside the contract so that an implementer outside
this repository can watch it refuse them.
This file keeps the exact split under this repository's CI, written out as
a literal, and holds each format's shipped ``expected_reds`` to the same
literal, so neither side can move alone. It changes neither
``conformance.py`` nor the ``make_project`` hook: each wiring below is a
subclass that supplies it.

This file is the observation ADR-0001's first falsifier waits on: a
deliberately wrong format observed to fail the suite.

Measures: crosslink ADR-0001, What would falsify this (first bullet)
"""

from __future__ import annotations

from crosslink.conformance import (
    FingerprintedProjectContract,
    ProjectSourceContract,
)
from crosslink.conformance_calibration import (
    AFormatThatRefusesMalformedInput,
    AFormatThatSwallowsSilently,
    AFormatWithAnUnstableFingerprint,
    a_conforming_core,
    observed_outcomes,
    reds,
)


# --- contract wirings (not collected: no Test prefix) ------------------------


class _RaisingConformance(ProjectSourceContract):
    def make_project(self, declarations, semantics, sources):
        return AFormatThatRefusesMalformedInput(declarations, semantics, sources)


class _SilentConformance(ProjectSourceContract):
    def make_project(self, declarations, semantics, sources):
        return AFormatThatSwallowsSilently(declarations, semantics, sources)


class _UnstableConformance(FingerprintedProjectContract):
    def make_project(self, declarations, semantics, sources):
        return AFormatWithAnUnstableFingerprint(declarations, semantics, sources)


class _RealConformance(FingerprintedProjectContract):
    def make_project(self, declarations, semantics, sources):
        return a_conforming_core(declarations, semantics, sources)


class TestTheSuiteGoesRedAgainstWrongFormats:
    """Each wrong format fails exactly the arms built to catch its defect."""

    def test_a_raising_format_fails_exactly_the_never_raises_arms(self):
        """The reds arrive as the subject's own ValueError surfacing
        through the arm - the contract's never-raises assertions are
        unguarded calls on purpose, so the refusal itself is the failure."""

        expected = {
            "test_malformed_input_never_raises": "ValueError",
            "test_malformed_input_is_explained_rather_than_silent": "ValueError",
            "test_a_malformed_source_declaration_never_raises_and_is_explained": "ValueError",
        }

        assert reds(observed_outcomes(_RaisingConformance())) == expected
        assert dict(AFormatThatRefusesMalformedInput.expected_reds) == expected

    def test_a_silent_format_fails_exactly_the_explained_arms(self):
        """The complement of the arm above: this subject never raises, so
        only the arms that demand a note may go red - including the
        source-with-no-system arm, whose skip is a statement that must be
        explained like any other, and the notes-agree-with-findings arm,
        whose note half a swallowing format cannot produce."""

        expected = {
            "test_malformed_input_is_explained_rather_than_silent": "AssertionError",
            "test_a_malformed_source_declaration_never_raises_and_is_explained": "AssertionError",
            "test_a_source_requires_a_system_it_cannot_invent": "AssertionError",
            "test_a_dangling_join_side_is_agreed_by_notes_and_findings": "AssertionError",
        }

        assert reds(observed_outcomes(_SilentConformance())) == expected
        assert dict(AFormatThatSwallowsSilently.expected_reds) == expected

    def test_an_unstable_fingerprint_fails_exactly_the_stability_arms(self):
        """Tier 2's defect must stay confined to tier 2: every tier-1 arm on
        this subject delegates to the conforming core and must stay green,
        or the wrapper is wrong in two ways and proves less than it
        claims."""

        expected = {
            "test_a_fingerprint_is_stable_across_calls": "AssertionError",
            "test_two_identical_projects_fingerprint_alike": "AssertionError",
        }

        assert reds(observed_outcomes(_UnstableConformance())) == expected
        assert dict(AFormatWithAnUnstableFingerprint.expected_reds) == expected

    def test_the_conforming_core_stays_green_on_every_arm(self):
        """The control's control, in the same file: the real reduction passes
        every arm the wrong formats fail, through the same runner - so a
        runner that misreported outcomes in either direction would go red
        here or above. The floor on the arm count keeps a silently shrunken
        contract from calibrating vacuously."""

        outcomes = observed_outcomes(_RealConformance())
        assert reds(outcomes) == {}
        assert len(outcomes) >= 23

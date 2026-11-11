# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The oracle's calibration: both arms observed, and the blind spot shown.

ADR-0003's second and third preconditions live here as tests. The refusal arm
is a test rather than a demo on purpose - if the harness silently stopped
discriminating, a wrong patch going green is what would say so.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from crosslink import (
    DeclaredKey,
    Delta,
    ProjectModel,
    ProjectTree,
    SetEdits,
    canonical,
    diff,
    verify,
)
from crosslink.conformance import (
    a_composite_key_declaration,
    a_single_key_declaration,
    malformed_yaml,
)


def a_tree() -> ProjectTree:
    """A small synthetic generator project: two models, one declared grain.

    The dim_date declaration carries a ``not_null`` test on purpose: the
    parser deliberately ignores it, which makes it the piece of the tree the
    reduction is blind to - the lever the blind-spot arm needs.
    """

    return ProjectTree(
        models=(
            ProjectModel(name="dim_date", layer="silver"),
            ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
        ),
        name="generator",
        declaration_sources={"schema_dim_date": a_single_key_declaration()},
    )


THE_CLAIMED_KEY = DeclaredKey(
    model="fact_orders", columns=("date", "provider"), source="combination"
)

A_STATED_DELTA = Delta(
    format="dagster",
    name="generator",
    declared_keys=SetEdits(added=(THE_CLAIMED_KEY,)),
)


def a_closing_patch(tree: ProjectTree) -> ProjectTree:
    """A hand-written patch that does exactly what the stated delta claims."""

    return replace(
        tree,
        declaration_sources={
            **tree.declaration_sources,
            "schema_fact": a_composite_key_declaration(
                model="fact_orders", columns=("date", "provider")
            ),
        },
    )


class TestBothArms:
    """The two calibration arms ADR-0003 requires observed."""

    def test_a_patch_that_closes_its_stated_delta_is_accepted(self):
        verdict = verify(a_tree(), A_STATED_DELTA, a_closing_patch)
        assert verdict.closes
        assert verdict.disagreements == ()
        assert verdict.observed == verdict.stated

    def test_an_accepted_verdict_agrees_with_the_delta_round_trip(self):
        """The harness and the delta vocabulary must be two views of one
        mechanism: the stated delta applied to the before-evidence is the
        canonical after-evidence. If these ever disagree, one of the two is
        lying about what happened."""

        verdict = verify(a_tree(), A_STATED_DELTA, a_closing_patch)
        assert verdict.stated.apply_to(verdict.before) == canonical(verdict.after)

    def test_a_patch_that_claims_a_delta_and_does_not_produce_it_is_refused(self):
        """The arm that makes this an oracle. A verifier only ever observed
        agreeing has not been shown to discriminate."""

        verdict = verify(a_tree(), A_STATED_DELTA, lambda tree: tree)
        assert not verdict.closes
        assert verdict.disagreements == ("declared_keys",)
        assert verdict.observed.is_empty

    def test_a_refusal_names_every_disagreeing_collection(self):
        """A patch that does the wrong thing entirely: the claimed key never
        appears and an unclaimed model does. The verdict must name both -
        the failed claim and the unstated surplus."""

        def wrong_patch(tree: ProjectTree) -> ProjectTree:
            return replace(
                tree, models=tree.models + (ProjectModel(name="mart_surprise"),)
            )

        verdict = verify(a_tree(), A_STATED_DELTA, wrong_patch)
        assert not verdict.closes
        assert verdict.disagreements == ("models", "declared_keys")

    def test_an_empty_claim_over_an_identity_patch_is_accepted(self):
        """The quiet corner both arms leave uncovered: claiming nothing and
        doing nothing must agree, or every no-op proposal reads as drift."""

        stated = Delta(format="dagster", name="generator")
        verdict = verify(a_tree(), stated, lambda tree: tree)
        assert verdict.closes


class TestTheBlindSpot:
    """ADR-0003's third precondition: demonstrated, not described."""

    def test_a_patch_that_closes_its_delta_and_breaks_something_else_passes(self):
        """The patch closes its stated delta exactly - and also strips the
        ``not_null`` test the parser deliberately ignores. The oracle
        accepts, because the comparison sees exactly what the reduction
        sees; the stand-in for the target project's own suite is what
        catches it. This is the structural limit ADR-0003 prices in: the
        oracle verifies the intended effect, and the target's suite is the
        second, independent verifier."""

        def a_target_suite_would_pass(tree: ProjectTree) -> bool:
            # Stand-in for the target's own tests: it asserts a property the
            # neutral model does not carry.
            return all(
                "not_null" in text for text in tree.declaration_sources.values()
            )

        def treacherous_patch(tree: ProjectTree) -> ProjectTree:
            edited = dict(tree.declaration_sources)
            edited["schema_dim_date"] = edited["schema_dim_date"].replace(
                "          - not_null\n", ""
            )
            edited["schema_fact"] = a_composite_key_declaration(
                model="fact_orders", columns=("date", "provider")
            )
            return replace(tree, declaration_sources=edited)

        tree = a_tree()
        assert a_target_suite_would_pass(tree)

        verdict = verify(tree, A_STATED_DELTA, treacherous_patch)
        assert verdict.closes, "the oracle must accept: the stated delta closed"
        assert not a_target_suite_would_pass(treacherous_patch(tree)), (
            "the second verifier is the one that catches the breakage"
        )

    def test_a_notes_only_effect_is_invisible_to_the_oracle_by_design(self):
        """Same limit, softer edge: a patch that adds a malformed file
        changes the notes and nothing else, and notes are outside the
        delta's range - so an empty claim closes. Stated here so nobody
        reads it as a bug later."""

        def add_junk(tree: ProjectTree) -> ProjectTree:
            return replace(
                tree,
                declaration_sources={
                    **tree.declaration_sources, "junk": malformed_yaml()
                },
            )

        verdict = verify(a_tree(), Delta(format="dagster", name="generator"), add_junk)
        assert verdict.closes
        assert verdict.after.notes != verdict.before.notes


class TestHarnessRefusals:
    """Where a silent answer would be an invented one."""

    def test_a_stated_delta_for_another_project_is_refused(self):
        stated = replace(A_STATED_DELTA, name="someone_else")
        with pytest.raises(ValueError, match="wrong subject"):
            verify(a_tree(), stated, a_closing_patch)

    def test_a_patch_that_renames_the_project_surfaces_as_diff_refusal(self):
        """The harness does not catch what it cannot interpret: diff refuses
        to compare across projects, and that refusal must reach the caller
        rather than be dressed up as a verdict."""

        def rename(tree: ProjectTree) -> ProjectTree:
            return replace(tree, name="other")

        with pytest.raises(ValueError, match="different projects"):
            verify(a_tree(), A_STATED_DELTA, rename)

    def test_a_mutating_patch_cannot_reach_the_callers_tree(self):
        """'Apply the patch to a copy' held against the sloppiest patch: one
        that edits its input in place. The caller's tree must be exactly
        what it was - a refused patch that had already edited the subject
        would make the sandbox a fiction."""

        def vandal(tree: ProjectTree) -> ProjectTree:
            tree.declaration_sources.clear()
            return tree

        tree = a_tree()
        verdict = verify(tree, Delta(format="dagster", name="generator"), vandal)
        assert not verdict.closes
        assert tree.declaration_sources == {"schema_dim_date": a_single_key_declaration()}
        assert tree.reduce() == verify(tree, Delta(format="dagster", name="generator"), lambda t: t).before


class TestVerdictEvidence:
    """The verdict is the verification half of the patch object: the
    evidence travels with the answer."""

    def test_the_verdict_carries_both_reductions(self):
        tree = a_tree()
        verdict = verify(tree, A_STATED_DELTA, a_closing_patch)
        assert verdict.before == tree.reduce()
        assert verdict.after == a_closing_patch(tree).reduce()

    def test_the_observed_delta_is_the_diff_of_the_evidence(self):
        verdict = verify(a_tree(), A_STATED_DELTA, a_closing_patch)
        assert verdict.observed == diff(verdict.before, verdict.after)

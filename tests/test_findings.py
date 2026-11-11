# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Authority 1 under test: contradictions found, proposals that close them.

The negative arm matters as much as the positive ones - a finder that
hallucinates contradictions makes every drift report noise, and a rejected
finding is defined (``docs/ROADMAP.md``, the authorities section) as a bug in
the reduction. The closure arms tie the module to the rest of the mechanism:
a finding's proposal is a Delta the oracle can verify unchanged.
"""

from __future__ import annotations

from crosslink import (
    DagsterProject,
    DbtProject,
    DeclaredJoin,
    DeclaredKey,
    ExternalSource,
    Metric,
    ProjectDeclarations,
    ProjectModel,
    ProjectTree,
    SemanticModel,
    verify,
)
from crosslink.conformance import a_single_key_declaration, a_source_declaration
from crosslink.findings import (
    DANGLING_DECLARED_JOIN,
    DANGLING_DECLARED_KEY,
    UNDECLARED_LINEAGE_ROOT,
    UNKNOWN_READER,
    findings,
)


def a_consistent_snapshot(**overrides) -> ProjectDeclarations:
    """Every statement agrees with every other: the zero-findings baseline.

    Populates every collection the vocabulary carries - semantic models and
    metrics included - so the negative arm asserts zero findings over the
    full vocabulary, not just the four collections the current kinds read.
    """

    base = dict(
        format="dagster",
        name="catalyst",
        models=(
            ProjectModel(name="dim_date", layer="silver"),
            ProjectModel(name="fact_costs", depends_on=("dim_date",), layer="gold"),
        ),
        sources=(
            ExternalSource(system="billing", table="costs_raw", read_by=("fact_costs",)),
        ),
        declared_keys=(DeclaredKey(model="dim_date", columns=("date",)),),
        declared_joins=(
            DeclaredJoin(
                from_model="fact_costs", from_columns=("date",),
                to_model="dim_date", to_columns=("date",),
            ),
        ),
        semantic_models=(
            SemanticModel(name="costs", model="fact_costs", measures=("total_cost",)),
        ),
        metrics=(Metric(name="daily_cost", measure="total_cost"),),
    )
    base.update(overrides)
    return ProjectDeclarations(**base)


class TestTheNegativeArm:
    def test_a_self_consistent_snapshot_yields_zero_findings(self):
        assert findings(a_consistent_snapshot()) == ()

    def test_an_empty_project_yields_zero_findings(self):
        assert findings(ProjectDeclarations(format="dagster", name="empty")) == ()


class TestEachContradiction:
    def test_an_undeclared_lineage_root_is_found_and_proposes_nothing(self):
        """A root the graph names and nothing declares. The consistent declaration would be an
        ExternalSource, whose required system only a human knows - so the
        finding carries the claim and both sites, and deliberately no
        proposal: fabricating the system to have one would move the
        invention into exactly the field required-ness exists to refuse."""

        # Direct construction, not the builder: every collection the builder
        # populates would need cancelling here, so the minimal fixture states
        # itself.
        snapshot = ProjectDeclarations(
            format="dagster",
            name="catalyst",
            models=(
                ProjectModel(name="fact_costs", depends_on=("orders_raw",)),
            ),
        )
        found = findings(snapshot)
        assert [f.kind for f in found] == [UNDECLARED_LINEAGE_ROOT]
        assert found[0].subject == "orders_raw"
        assert found[0].proposal is None
        assert len(found[0].evidence) == 2

    def test_a_root_covered_by_a_declared_source_table_is_not_a_finding(self):
        """The coverage rule, exact and stated: a dependency name matching a
        declared source's table is the project agreeing with itself."""

        snapshot = ProjectDeclarations(
            format="dagster",
            name="catalyst",
            models=(ProjectModel(name="fact_costs", depends_on=("costs_raw",)),),
            sources=(
                ExternalSource(system="billing", table="costs_raw", read_by=("fact_costs",)),
            ),
        )
        assert findings(snapshot) == ()

    def test_a_dangling_key_proposes_exactly_its_own_removal(self):
        ghost = DeclaredKey(model="ghost_model", columns=("id",))
        snapshot = a_consistent_snapshot(
            declared_keys=(DeclaredKey(model="dim_date", columns=("date",)), ghost)
        )
        found = [f for f in findings(snapshot) if f.kind == DANGLING_DECLARED_KEY]
        assert len(found) == 1
        assert found[0].subject == "ghost_model"
        assert found[0].proposal.declared_keys.removed == (ghost,)

    def test_a_dangling_join_names_the_absent_side_or_both(self):
        one_side = DeclaredJoin(
            from_model="fact_costs", from_columns=("x",),
            to_model="ghost_dim", to_columns=("x",),
        )
        both_sides = DeclaredJoin(
            from_model="ghost_a", from_columns=("x",),
            to_model="ghost_b", to_columns=("x",),
        )
        snapshot = a_consistent_snapshot(declared_joins=(one_side, both_sides))
        found = [f for f in findings(snapshot) if f.kind == DANGLING_DECLARED_JOIN]
        assert [f.subject for f in found] == ["ghost_dim", "ghost_a, ghost_b"]
        assert found[0].proposal.declared_joins.removed == (one_side,)

    def test_a_stale_reader_proposes_the_corrected_attribution(self):
        """The source itself stays - the table is still a real contract with
        the warehouse; the stale statement is the attribution."""

        source = ExternalSource(
            system="billing", table="costs_raw", read_by=("fact_costs", "renamed_away")
        )
        snapshot = a_consistent_snapshot(sources=(source,))
        found = [f for f in findings(snapshot) if f.kind == UNKNOWN_READER]
        assert len(found) == 1
        assert found[0].subject == "billing.costs_raw"
        change = found[0].proposal.sources.changed[0]
        assert change.fields == ("read_by",)
        assert change.after.read_by == ("fact_costs",)


class TestOneStatementOneFinding:
    """The delta layer's doctrine, held here too: an identical restatement is
    one statement, so it is at most one contradiction - and one proposal,
    because the second copy's proposal could never apply after the first."""

    def test_identical_restatements_collapse_to_one_finding(self):
        ghost_key = DeclaredKey(model="ghost", columns=("id",))
        ghost_join = DeclaredJoin(
            from_model="ghost", from_columns=("x",),
            to_model="dim_date", to_columns=("x",),
        )
        stale_source = ExternalSource(
            system="billing", table="stale_raw", read_by=("gone",)
        )
        snapshot = a_consistent_snapshot(
            declared_keys=(ghost_key, ghost_key),
            declared_joins=(ghost_join, ghost_join),
            sources=(stale_source, stale_source),
        )
        found = findings(snapshot)
        assert [f.kind for f in found] == [
            DANGLING_DECLARED_KEY, DANGLING_DECLARED_JOIN, UNKNOWN_READER,
        ]

    def test_applying_every_proposal_in_sequence_heals_the_snapshot(self):
        """The obvious heal-everything loop must not crash on its second
        step because a duplicate's proposal already applied."""

        ghost_key = DeclaredKey(model="ghost", columns=("id",))
        snapshot = a_consistent_snapshot(declared_keys=(ghost_key, ghost_key))
        healed = snapshot
        for finding in findings(snapshot):
            if finding.proposal is not None:
                healed = finding.proposal.apply_to(healed)
        assert findings(healed) == ()

    def test_a_duplicated_dependency_quotes_its_model_once(self):
        """`depends_on=('raw', 'raw')` is one dependent; evidence that reads
        'models (fct, fct)' misstates the project it quotes."""

        snapshot = ProjectDeclarations(
            format="dagster",
            name="catalyst",
            models=(ProjectModel(name="fct", depends_on=("raw", "raw")),),
        )
        found = findings(snapshot)
        assert len(found) == 1
        assert "model fct declares" in found[0].evidence[0]

    def test_schema_distinct_sources_get_distinct_subjects(self):
        """Consumers key findings by (kind, subject); `identifier` alone
        would collapse two real warehouse tables in different schemas."""

        raw = ExternalSource(
            system="billing", table="costs", schema_name="raw", read_by=("gone",)
        )
        staging = ExternalSource(
            system="billing", table="costs", schema_name="staging", read_by=("gone",)
        )
        snapshot = a_consistent_snapshot(sources=(raw, staging))
        subjects = [f.subject for f in findings(snapshot) if f.kind == UNKNOWN_READER]
        assert subjects == ["billing.raw.costs", "billing.staging.costs"]


class TestProposalsCloseThemselves:
    """A proposal that does not remove its own finding is not a proposal to
    restore consistency - it is a different edit wearing the claim."""

    def test_each_proposing_finding_vanishes_when_its_proposal_is_applied(self):
        snapshot = a_consistent_snapshot(
            declared_keys=(DeclaredKey(model="ghost", columns=("id",)),),
            declared_joins=(
                DeclaredJoin(
                    from_model="ghost", from_columns=("x",),
                    to_model="dim_date", to_columns=("x",),
                ),
            ),
            sources=(
                ExternalSource(system="billing", table="costs_raw", read_by=("gone",)),
            ),
        )
        for finding in findings(snapshot):
            assert finding.proposal is not None, finding.kind
            healed = finding.proposal.apply_to(snapshot)
            remaining = {
                (f.kind, f.subject) for f in findings(healed)
            }
            assert (finding.kind, finding.subject) not in remaining


class TestProposalRealizability:
    """A proposal the producing format cannot realize is a permanent red:
    the oracle refuses every patch, including the correct one. The all-stale
    case proposes what a tree can actually do; the one
    declaration-space/tree-space mismatch left is demonstrated, not hidden."""

    def test_an_entirely_stale_attribution_proposes_the_source_removal(self):
        """read_by=() is a state the declaring format cannot produce -
        attribution is keyed by the declaring reader, so removing the last
        declarer removes the source. The minimal REALIZABLE edit is the
        removal."""

        source = ExternalSource(system="billing", table="stale_raw", read_by=("gone",))
        snapshot = a_consistent_snapshot(sources=(source,))
        found = [f for f in findings(snapshot) if f.kind == UNKNOWN_READER]
        assert len(found) == 1
        assert found[0].proposal.sources.removed == (source,)
        assert found[0].proposal.sources.changed == ()

    def test_a_surviving_reader_still_gets_the_corrected_attribution(self):
        """The source itself stays when any reader survives - the table is
        still a real contract with the warehouse."""

        source = ExternalSource(
            system="billing", table="costs_raw", read_by=("fact_costs", "gone")
        )
        snapshot = a_consistent_snapshot(sources=(source,))
        found = [f for f in findings(snapshot) if f.kind == UNKNOWN_READER]
        assert found[0].proposal.sources.removed == ()
        assert found[0].proposal.sources.changed[0].after.read_by == ("fact_costs",)

    def test_the_all_stale_proposal_closes_through_the_oracle(self):
        """When every reader is stale the proposal is a removal, and it
        closes on the patch that deletes the stale declaration. A proposal
        that corrected the attribution instead could not close on that
        patch: deleting the last declarer removes the source."""

        tree = ProjectTree(
            models=(ProjectModel(name="dim_date"),),
            name="generator",
            source_declarations={"gone": a_source_declaration()},
        )
        finding = next(
            f for f in findings(tree.reduce()) if f.kind == UNKNOWN_READER
        )

        def remove_the_declaration(sandbox: ProjectTree) -> ProjectTree:
            sandbox.source_declarations.pop("gone")
            return sandbox

        verdict = verify(tree, finding.proposal, remove_the_declaration)
        assert verdict.closes
        assert findings(verdict.after) == ()

    def test_the_orphaned_columns_mismatch_is_demonstrated_not_hidden(self):
        """The stated domain restriction, live: a stale declaration that also
        contributed columns makes the natural tree patch (delete it) observe
        a WIDER delta than the proposal states - the columns leave with the
        declaration that carried them - so the oracle refuses. The refusal
        is the oracle being right about the patch, and this arm is the
        record that the mismatch is known rather than latent."""

        tree = ProjectTree(
            models=(ProjectModel(name="fact_costs"),),
            name="generator",
            source_declarations={
                "fact_costs": a_source_declaration(columns=("amount",)),
                "renamed_away": a_source_declaration(columns=("amount", "extra_col")),
            },
        )
        finding = next(
            f for f in findings(tree.reduce()) if f.kind == UNKNOWN_READER
        )
        assert finding.proposal.sources.changed  # partial-stale: a corrected attribution

        def remove_the_stale_declaration(sandbox: ProjectTree) -> ProjectTree:
            sandbox.source_declarations.pop("renamed_away")
            return sandbox

        verdict = verify(tree, finding.proposal, remove_the_stale_declaration)
        assert not verdict.closes
        assert "sources" in verdict.disagreements


class TestFormatNeutrality:
    """The same inconsistency planted in each format yields the same finding -
    the finding never saw the format, and that is the test."""

    def test_a_dangling_key_is_the_same_finding_in_both_formats(self):
        dagster = DagsterProject(
            (ProjectModel(name="dim_date"),),
            name="catalyst",
            declaration_sources={"ghost": a_single_key_declaration(model="ghost_model")},
        ).declarations()
        dbt = DbtProject(
            {
                "dbt_project.yml": "name: analytics\n",
                "models/dim_date.sql": "select 1\n",
                "models/ghost.yml": a_single_key_declaration(model="ghost_model"),
            }
        ).declarations()
        dagster_found = [f for f in findings(dagster) if f.kind == DANGLING_DECLARED_KEY]
        dbt_found = [f for f in findings(dbt) if f.kind == DANGLING_DECLARED_KEY]
        assert [f.subject for f in dagster_found] == ["ghost_model"]
        assert [f.subject for f in dbt_found] == ["ghost_model"]

    def test_an_undeclared_root_is_the_same_finding_in_both_formats(self):
        dagster = DagsterProject(
            (ProjectModel(name="fct", depends_on=("missing_raw",)),), name="catalyst"
        ).declarations()
        dbt = DbtProject(
            {
                "dbt_project.yml": "name: analytics\n",
                "models/fct.sql": "select * from {{ ref('missing_raw') }}\n",
            }
        ).declarations()
        for declared in (dagster, dbt):
            found = findings(declared)
            assert [f.kind for f in found] == [UNDECLARED_LINEAGE_ROOT]
            assert found[0].subject == "missing_raw"

    def test_an_undeclared_warehouse_read_is_the_same_finding_in_both_formats(self):
        """The flagship spelling of the flagship class: a warehouse table
        read with no declaration covering it. In dagster the class arrives
        as a depends_on entry; in dbt it arrives as a source() call no
        declaration resolves, which the reduction has to carry into this
        module's input: dropped there, the parity the docstring claims
        would go untested for the very case that motivates the kind."""

        dagster = DagsterProject(
            (ProjectModel(name="stg_orders", depends_on=("orders_raw",)),),
            name="catalyst",
        ).declarations()
        dbt = DbtProject(
            {
                "dbt_project.yml": "name: analytics\n",
                "models/stg_orders.sql": (
                    "select * from {{ source('erp', 'orders_raw') }}\n"
                ),
            }
        ).declarations()
        for declared in (dagster, dbt):
            found = findings(declared)
            assert [f.kind for f in found] == [UNDECLARED_LINEAGE_ROOT], declared.format
            assert found[0].subject == "orders_raw"
            assert found[0].proposal is None


class TestTheWholeLoop:
    def test_a_finding_delta_patch_round_through_the_oracle(self):
        """The mechanism end to end, model-free: the reduction finds the
        contradiction, the finding states the delta, a hand-written patch makes
        the edit, and the oracle verifies the patch against the finding's
        own delta - findings are the first real producer of the stated-delta
        the write path runs on."""

        tree = ProjectTree(
            models=(ProjectModel(name="dim_date"),),
            name="generator",
            declaration_sources={"ghost": a_single_key_declaration(model="ghost_model")},
        )
        finding = next(
            f for f in findings(tree.reduce()) if f.kind == DANGLING_DECLARED_KEY
        )

        def remove_the_declaration(sandbox: ProjectTree) -> ProjectTree:
            sandbox.declaration_sources.pop("ghost")
            return sandbox

        verdict = verify(tree, finding.proposal, remove_the_declaration)
        assert verdict.closes
        assert findings(verdict.after) == ()

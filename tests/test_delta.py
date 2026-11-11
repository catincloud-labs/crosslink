# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The delta vocabulary, and the arms that make it an oracle.

ADR-0003's whole mechanism rests on `diff` being trustworthy: a delta is stated
before any patch exists, and re-reduction is checked against it. So this file
carries the calibration arms the record names - `diff(C, C)` observed empty, a
mutated snapshot observed non-empty - and, deliberately, the known-negative
arms beside them: a diff observed only to agree has not been shown to
discriminate.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields, replace

import pytest

from crosslink import (
    Changed,
    DagsterProject,
    Delta,
    Freshness,
    KeyedEdits,
    SetEdits,
    canonical,
    diff,
)
from crosslink.conformance import (
    a_composite_key_declaration,
    a_join_declaration,
    a_single_key_declaration,
    a_source_declaration,
)
from crosslink.model import (
    DeclaredJoin,
    DeclaredKey,
    ExternalSource,
    Metric,
    ProjectDeclarations,
    ProjectModel,
    SemanticModel,
)


def a_snapshot(**overrides) -> ProjectDeclarations:
    """A hand-built snapshot populating all six nouns, in canonical order.

    At least two members per collection on purpose: a permutation arm over a
    single-element tuple permutes nothing and proves nothing.
    """

    base = dict(
        format="dagster",
        name="catalyst",
        models=(
            ProjectModel(name="dim_date", layer="silver"),
            ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
            ProjectModel(name="mart_revenue", depends_on=("fact_orders",), layer="platinum"),
        ),
        sources=(
            ExternalSource(system="cloudflare", table="http_requests", read_by=("dim_date",)),
            ExternalSource(
                system="sales",
                table="orders_export_v1",
                schema_name="sales",
                columns=("placed_at", "amount"),
                read_by=("fact_orders",),
            ),
        ),
        declared_keys=(
            DeclaredKey(model="dim_date", columns=("date",)),
            DeclaredKey(model="fact_orders", columns=("date", "provider")),
        ),
        declared_joins=(
            DeclaredJoin(
                from_model="fact_orders", from_columns=("date",),
                to_model="dim_date", to_columns=("date",),
            ),
            DeclaredJoin(
                from_model="mart_revenue", from_columns=("date",),
                to_model="dim_date", to_columns=("date",),
            ),
        ),
        semantic_models=(
            SemanticModel(
                name="sem_costs", model="fact_orders",
                dimensions=("date",), measures=("daily_cost",), definition_sha="aaa",
            ),
            SemanticModel(
                name="sem_pages", model="mart_revenue",
                dimensions=("date",), measures=("views",), definition_sha="bbb",
            ),
        ),
        metrics=(
            Metric(name="daily_revenue", measure="daily_cost", definition_sha="ccc"),
            Metric(name="page_views", measure="views", definition_sha="ddd"),
        ),
    )
    base.update(overrides)
    return ProjectDeclarations(**base)


def permuted(snapshot: ProjectDeclarations) -> ProjectDeclarations:
    """The same declarations with every collection's order reversed."""

    return replace(
        snapshot,
        models=tuple(reversed(snapshot.models)),
        sources=tuple(reversed(snapshot.sources)),
        declared_keys=tuple(reversed(snapshot.declared_keys)),
        declared_joins=tuple(reversed(snapshot.declared_joins)),
        semantic_models=tuple(reversed(snapshot.semantic_models)),
        metrics=tuple(reversed(snapshot.metrics)),
    )


class TestDiffIsAnOracle:
    """The calibration arms ADR-0003 names, and the negatives beside them."""

    def test_diff_of_a_snapshot_with_itself_is_empty(self):
        """An oracle that hallucinates change makes every downstream drift
        report noise. This is the record's first observed arm."""

        snapshot = a_snapshot()
        assert diff(snapshot, snapshot).is_empty

    def test_diff_of_two_empty_snapshots_is_empty(self):
        """The empty project is the state every consumer must tolerate, and it
        must not read as drift against itself."""

        left = ProjectDeclarations(format="dagster", name="catalyst")
        right = ProjectDeclarations(format="dagster", name="catalyst")
        assert diff(left, right).is_empty

    def test_a_mutated_snapshot_yields_a_nonempty_delta(self):
        """A diff that returns empty on real change is the stop-everything
        falsifier: the projection failing as an oracle."""

        snapshot = a_snapshot()
        mutated = replace(
            snapshot,
            models=(replace(snapshot.models[0], layer="bronze"),) + snapshot.models[1:],
        )
        assert not diff(snapshot, mutated).is_empty

    def test_a_single_field_mutation_names_exactly_that_field(self):
        """An oracle naming the wrong field verifies the wrong claim. Exactly
        one changed entry, whose fields tuple is exactly the mutated field."""

        snapshot = a_snapshot()
        mutated = replace(
            snapshot,
            models=(replace(snapshot.models[0], layer="bronze"),) + snapshot.models[1:],
        )
        delta = diff(snapshot, mutated)
        assert len(delta.models.changed) == 1
        assert delta.models.changed[0].fields == ("layer",)

    def test_field_naming_does_not_leak_unmutated_fields(self):
        """The known-negative for the arm above: an assertion that would pass
        for any non-empty fields tuple has not been shown to discriminate. A
        different single field names only itself, and a two-field mutation
        names both and only both."""

        snapshot = a_snapshot()
        one = replace(
            snapshot,
            models=(replace(snapshot.models[0], relation="db.dim_date"),) + snapshot.models[1:],
        )
        assert diff(snapshot, one).models.changed[0].fields == ("relation",)

        two = replace(
            snapshot,
            models=(replace(snapshot.models[0], relation="db.dim_date", layer="bronze"),)
            + snapshot.models[1:],
        )
        assert diff(snapshot, two).models.changed[0].fields == ("relation", "layer")


class TestDiffPerNoun:
    """Each noun's identity actually keys it. A noun the diff ignores is a
    noun drift can hide in."""

    def test_added_and_removed_models_land_in_their_buckets(self):
        """Conflating an add with a change would let apply invent a base
        value that never existed."""

        snapshot = a_snapshot()
        new = ProjectModel(name="fact_requests", layer="gold")
        edited = replace(snapshot, models=snapshot.models[1:] + (new,))
        delta = diff(snapshot, edited)
        assert delta.models.added == (new,)
        assert delta.models.removed == (snapshot.models[0],)
        assert delta.models.changed == ()

    def test_sources_are_identified_by_system_schema_and_table(self):
        """Two sources differing only in schema_name are two real warehouse
        tables. Keying on `.identifier` - which omits the schema - would
        collapse them into one phantom change."""

        snapshot = a_snapshot()
        moved = replace(snapshot.sources[1], schema_name="analytics")
        edited = replace(snapshot, sources=snapshot.sources[:1] + (moved,))
        delta = diff(snapshot, edited)
        assert delta.sources.added == (moved,)
        assert delta.sources.removed == (snapshot.sources[1],)
        assert delta.sources.changed == ()

    def test_a_key_with_different_columns_is_drop_and_add_not_change(self):
        """A key's content is its identity; 'the key of model X' is an
        identity the model does not have. The same limit is why a rename
        reads as drop-and-add: two snapshots record difference, not intent -
        ADR-0003 names that as the vocabulary's known falsifier, and it is
        stated rather than solved."""

        snapshot = a_snapshot()
        widened = DeclaredKey(model="dim_date", columns=("date", "region"))
        edited = replace(
            snapshot, declared_keys=(widened,) + snapshot.declared_keys[1:]
        )
        delta = diff(snapshot, edited)
        assert delta.declared_keys.added == (widened,)
        assert delta.declared_keys.removed == (snapshot.declared_keys[0],)

    def test_a_join_with_a_different_column_list_is_drop_and_add(self):
        """Joins carry the same whole-value identity contract as keys."""

        snapshot = a_snapshot()
        rewired = replace(snapshot.declared_joins[0], from_columns=("day",), to_columns=("day",))
        edited = replace(
            snapshot, declared_joins=(rewired,) + snapshot.declared_joins[1:]
        )
        delta = diff(snapshot, edited)
        assert delta.declared_joins.added == (rewired,)
        assert delta.declared_joins.removed == (snapshot.declared_joins[0],)

    def test_two_keys_on_one_model_diff_independently(self):
        """The parser can emit several single-column keys for one model.
        Keying keys by model would silently merge them, and removing one
        would read as changing the other."""

        first = DeclaredKey(model="dim_date", columns=("date",))
        second = DeclaredKey(model="dim_date", columns=("region",))
        snapshot = a_snapshot(declared_keys=(first, second))
        edited = a_snapshot(declared_keys=(first,))
        delta = diff(snapshot, edited)
        assert delta.declared_keys.removed == (second,)
        assert delta.declared_keys.added == ()

    def test_a_semantic_model_sha_change_is_a_changed_entry_naming_definition_sha(self):
        """The sha is how a semantic edit is visible at all; a diff that
        misses it is blind to every definition edit."""

        snapshot = a_snapshot()
        edited = replace(
            snapshot,
            semantic_models=(replace(snapshot.semantic_models[0], definition_sha="zzz"),)
            + snapshot.semantic_models[1:],
        )
        delta = diff(snapshot, edited)
        assert len(delta.semantic_models.changed) == 1
        assert delta.semantic_models.changed[0].fields == ("definition_sha",)

    def test_metric_added_and_removed_land_in_their_buckets(self):
        """Completes six-noun coverage; the last noun is the one a partial
        diff quietly drops."""

        snapshot = a_snapshot()
        new = Metric(name="weekly_revenue", measure="daily_cost")
        edited = replace(snapshot, metrics=snapshot.metrics[1:] + (new,))
        delta = diff(snapshot, edited)
        assert delta.metrics.added == (new,)
        assert delta.metrics.removed == (snapshot.metrics[0],)


class TestOrderingContract:
    """Producers sort; the types promise nothing. The diff must not read
    producer order as meaning - and must not erase order that IS meaning."""

    def test_permuting_every_collection_is_not_a_delta(self):
        """An order-sensitive diff reports phantom drift every time a
        producer re-sorts, which every green test on sorted fixtures would
        agree with. This is the arm that catches it."""

        snapshot = a_snapshot()
        assert diff(snapshot, permuted(snapshot)).is_empty

    def test_column_order_within_a_key_is_a_real_difference(self):
        """A key's column order is the author's statement of the grain
        (model.py says so explicitly). Sorting inside the value to make the
        permutation arm pass would erase a declaration a human wrote."""

        snapshot = a_snapshot(
            declared_keys=(DeclaredKey(model="dim_date", columns=("date", "region")),)
        )
        flipped = a_snapshot(
            declared_keys=(DeclaredKey(model="dim_date", columns=("region", "date")),)
        )
        delta = diff(snapshot, flipped)
        assert not delta.is_empty
        assert len(delta.declared_keys.added) == 1
        assert len(delta.declared_keys.removed) == 1

    def test_canonical_is_idempotent(self):
        """A canonical form that keeps moving is not a form."""

        once = canonical(permuted(a_snapshot()))
        assert canonical(once) == once

    def test_canonical_of_a_permuted_snapshot_equals_canonical_of_the_original(self):
        """The equivalence class apply relies on: same declarations, one
        canonical representative, regardless of producer order."""

        snapshot = a_snapshot()
        assert canonical(permuted(snapshot)) == canonical(snapshot)


class TestRoundTrip:
    """`apply(diff(C, D), C)` reproduces D. The record's whole mechanism -
    accept only when re-reduction closes the stated delta - rests here."""

    def test_applying_diff_of_c_and_d_to_c_reproduces_d(self):
        """The headline property, with edits touching all six nouns at once
        so no single-noun shortcut can fake it."""

        c = a_snapshot()
        d = replace(
            c,
            models=c.models[1:] + (ProjectModel(name="fact_requests", layer="gold"),),
            sources=c.sources
            + (ExternalSource(system="ga4", table="events", read_by=("mart_revenue",)),),
            declared_keys=(DeclaredKey(model="dim_date", columns=("date", "region")),)
            + c.declared_keys[1:],
            declared_joins=c.declared_joins[:1],
            semantic_models=(replace(c.semantic_models[0], definition_sha="zzz"),)
            + c.semantic_models[1:],
            metrics=c.metrics + (Metric(name="weekly_revenue", measure="daily_cost"),),
        )
        assert diff(c, d).apply_to(c) == canonical(d)

    def test_round_trip_holds_for_a_real_producer_snapshot(self):
        """Hand-built snapshots can accidentally dodge the producer's
        origin-file ordering of keys and joins; a DagsterProject reduction
        cannot. The origin names below sort the composite key's file first
        on purpose, so the producer emits keys NOT sorted by model."""

        project = DagsterProject(
            (
                ProjectModel(name="dim_date", layer="silver"),
                ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
            ),
            name="catalyst",
            declaration_sources={
                "a_first": a_composite_key_declaration(model="fact_orders"),
                "b_second": a_single_key_declaration(model="dim_date"),
                "c_third": a_join_declaration(
                    from_model="fact_orders", to_model="dim_date"
                ),
            },
            semantic_sources={},
            source_declarations={"dim_date": a_source_declaration()},
        )
        c = project.declarations()
        d = replace(
            c,
            models=c.models + (ProjectModel(name="mart_revenue", layer="platinum"),),
            declared_keys=c.declared_keys[1:],
        )
        assert diff(c, d).apply_to(c) == canonical(d)

    def test_applying_an_empty_delta_returns_the_canonical_base(self):
        """Apply's output order is canonical even when nothing changed -
        stated so no caller can come to rely on it preserving producer
        order."""

        scrambled = permuted(a_snapshot())
        applied = Delta(format="dagster", name="catalyst").apply_to(scrambled)
        assert applied == canonical(scrambled)
        assert applied != scrambled

    def test_freshness_and_notes_are_not_a_declaration_delta(self):
        """Without this stated, a freshness flip would either masquerade as
        'no change needed' or leak into the delta - and nobody chose which.
        The choice: it diffs empty, and apply carries the base's values."""

        c = a_snapshot()
        d = replace(c, freshness=Freshness.STALE, notes=("cache is old",))
        delta = diff(c, d)
        assert delta.is_empty
        applied = delta.apply_to(c)
        assert applied.freshness == c.freshness
        assert applied.notes == c.notes


class TestRefusals:
    """The known-negative arms: everywhere a silent answer would be an
    invented one, the vocabulary refuses instead."""

    def test_diff_across_different_formats_is_refused(self):
        """A delta between a dagster project and a dbt project is not a
        drift report, it is a category error."""

        with pytest.raises(ValueError, match="cannot diff across formats"):
            diff(a_snapshot(), a_snapshot(format="dbt"))

    def test_diff_across_different_project_names_is_refused(self):
        """Two different projects differ everywhere; calling that a delta
        would invent a claim nobody made."""

        with pytest.raises(ValueError, match="different projects"):
            diff(a_snapshot(), a_snapshot(name="other"))

    def test_a_duplicate_model_name_within_one_side_is_refused(self):
        """Dict-building silently keeps the last duplicate, so a diff over
        such a snapshot certifies something it never fully saw."""

        broken = a_snapshot(
            models=(
                ProjectModel(name="dim_date", layer="silver"),
                ProjectModel(name="dim_date", layer="gold"),
            )
        )
        with pytest.raises(ValueError, match="more than once"):
            diff(broken, a_snapshot())

    def test_a_conflicting_duplicate_identity_is_refused_by_canonical_too(self):
        """canonical is a standalone public entry point; without the same
        refusal diff holds, a duplicate-identity snapshot would canonicalize
        order-dependently - two 'canonical' representatives for one multiset,
        silently, because the sort keys are coarser than equality."""

        broken = a_snapshot(
            metrics=(
                Metric(name="daily_revenue", measure="daily_cost"),
                Metric(name="daily_revenue", measure="views"),
            )
        )
        with pytest.raises(ValueError, match="more than once"):
            canonical(broken)

    def test_removing_a_model_absent_from_the_base_is_refused(self):
        """The wrong-base arm. Silent success here makes apply an inventor:
        the delta was computed against a snapshot this base is not."""

        delta = Delta(
            format="dagster",
            name="catalyst",
            models=KeyedEdits(removed=(ProjectModel(name="ghost"),)),
        )
        with pytest.raises(ValueError, match="cannot remove model"):
            delta.apply_to(a_snapshot())

    def test_adding_a_model_already_present_is_refused(self):
        """The mirror arm: last-write-wins would silently overwrite a
        declaration the base already holds."""

        delta = Delta(
            format="dagster",
            name="catalyst",
            models=KeyedEdits(added=(ProjectModel(name="dim_date"),)),
        )
        with pytest.raises(ValueError, match="already present"):
            delta.apply_to(a_snapshot())

    def test_a_changed_entry_whose_before_does_not_match_the_base_is_refused(self):
        """A delta computed against yesterday's snapshot applied to today's
        must refuse, not splice the two moments together."""

        base = a_snapshot()
        stale = replace(base.models[0], layer="bronze")
        delta = Delta(
            format="dagster",
            name="catalyst",
            models=KeyedEdits(
                changed=(Changed(stale, replace(stale, layer="gold"), ("layer",)),)
            ),
        )
        with pytest.raises(ValueError, match="before-value"):
            delta.apply_to(base)

    def test_removing_a_key_absent_from_the_base_is_refused(self):
        """The set-semantics nouns run their own apply path; the keyed-noun
        refusal above does not cover it."""

        delta = Delta(
            format="dagster",
            name="catalyst",
            declared_keys=SetEdits(removed=(DeclaredKey(model="ghost", columns=("x",)),)),
        )
        with pytest.raises(ValueError, match="cannot remove declared key"):
            delta.apply_to(a_snapshot())

    def test_applying_a_delta_to_a_different_project_is_refused(self):
        """A delta is a statement about one project; without this arm an
        empty delta would apply to anything at all, and the round-trip check
        against a wrong base would pass vacuously."""

        c = a_snapshot()
        delta = diff(c, c)
        with pytest.raises(ValueError, match="not the same project"):
            delta.apply_to(a_snapshot(name="other"))
        with pytest.raises(ValueError, match="not the same project"):
            delta.apply_to(a_snapshot(format="dbt"))

    def test_a_changed_entry_migrating_identity_is_refused(self):
        """A rename mis-stated as a changed entry would apply cleanly and
        emit a snapshot holding the same identity twice - a state diff
        itself refuses to read. A changed entry keeps its identity; a rename
        is drop-and-add."""

        base = a_snapshot()
        before = base.models[0]
        after = replace(before, name="renamed_dim_date")
        delta = Delta(
            format="dagster",
            name="catalyst",
            models=KeyedEdits(changed=(Changed(before, after, ("name",)),)),
        )
        with pytest.raises(ValueError, match="drop-and-add"):
            delta.apply_to(base)

    def test_one_identity_in_two_buckets_is_refused(self):
        """Remove-and-add of one identity is a value change with the audit
        trail stripped - no before/after record. That shape is outside
        diff's image, and apply must not widen the image silently."""

        base = a_snapshot()
        delta = Delta(
            format="dagster",
            name="catalyst",
            models=KeyedEdits(
                removed=(base.models[0],),
                added=(replace(base.models[0], layer="bronze"),),
            ),
        )
        with pytest.raises(ValueError, match="more than one bucket"):
            delta.apply_to(base)

    def test_the_same_set_member_removed_and_added_is_refused(self):
        """The set-noun twin of the bucket arm: value equals identity, so
        remove-plus-add of one member is a no-op stated as an edit."""

        base = a_snapshot()
        delta = Delta(
            format="dagster",
            name="catalyst",
            declared_keys=SetEdits(
                removed=(base.declared_keys[0],), added=(base.declared_keys[0],)
            ),
        )
        with pytest.raises(ValueError, match="both removed and added"):
            delta.apply_to(base)

    def test_a_changed_entry_that_misstates_its_fields_is_refused(self):
        """The fields tuple is load-bearing public surface a drift report
        reads; stored state nothing validates is a place a hand-built
        proposal can lie."""

        before = ProjectModel(name="dim_date", layer="silver")
        after = replace(before, layer="gold")
        with pytest.raises(ValueError, match="exactly what differs"):
            Changed(before, after, ("relation",))

    def test_a_changed_entry_with_no_difference_is_refused(self):
        """diff never emits an entry whose sides agree; hand construction
        must not be able to either."""

        model = ProjectModel(name="dim_date")
        with pytest.raises(ValueError, match="before == after"):
            Changed(model, model, ())


class TestIdenticalRestatements:
    """A byte-identical restatement is one statement, everywhere the module
    indexes - the parsers gather declarations across files, and two files
    legitimately stating the same key must not read as a contradiction."""

    def test_an_identical_key_restatement_diffs_empty(self):
        """The shape the real producer emits: two declaration files stating
        the same unique key. An oracle that crashes here cannot run
        ADR-0003's own first calibration arm."""

        twice = DeclaredKey(model="dim_date", columns=("date",))
        restated = a_snapshot(declared_keys=(twice, twice))
        assert diff(restated, restated).is_empty
        assert diff(restated, a_snapshot(declared_keys=(twice,))).is_empty

    def test_an_identical_keyed_restatement_diffs_empty(self):
        """The keyed nouns collapse the same way - but only when the values
        agree byte for byte; the conflicting case stays a refusal (the arm
        above in TestRefusals)."""

        snapshot = a_snapshot()
        restated = a_snapshot(models=snapshot.models + (snapshot.models[0],))
        assert diff(restated, snapshot).is_empty

    def test_a_real_producer_restatement_diffs_empty(self):
        """The executed shape that surfaced this decision: two declaration
        files, each declaring the same key, through the actual reduction."""

        project = DagsterProject(
            (ProjectModel(name="dim_date", layer="silver"),),
            name="catalyst",
            declaration_sources={
                "file_a": a_single_key_declaration(model="dim_date"),
                "file_b": a_single_key_declaration(model="dim_date"),
            },
            semantic_sources={},
            source_declarations={},
        )
        snapshot = project.declarations()
        assert diff(snapshot, snapshot).is_empty

    def test_canonical_collapses_an_identical_restatement(self):
        """One multiset of statements, one canonical representative,
        regardless of how often a statement was repeated."""

        twice = DeclaredKey(model="dim_date", columns=("date",))
        assert canonical(a_snapshot(declared_keys=(twice, twice))) == canonical(
            a_snapshot(declared_keys=(twice,))
        )


class TestVocabularyCompleteness:
    """The mirror the Delta docstring claims, held by an assertion."""

    def test_delta_mirrors_the_declaration_collections_field_for_field(self):
        """When a seventh collection arrives, this arm goes
        red - instead of diff silently returning empty for changes in it,
        which is the oracle going blind with a green suite."""

        declaration_collections = {
            f.name for f in dataclass_fields(ProjectDeclarations)
        } - {"format", "name", "freshness", "notes"}
        delta_collections = {f.name for f in dataclass_fields(Delta)} - {
            "format",
            "name",
        }
        assert delta_collections == declaration_collections

# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""An importable contract for project formats.

Ships inside the package rather than beside it, because a contract that lives
in a repository's test tree only serves formats inside that repository. An
implementer outside it cannot run the one artifact that tells them whether they
got it right.

Use it by subclassing and supplying a constructor::

    from crosslink.conformance import FingerprintedProjectContract

    class TestMyFormat(FingerprintedProjectContract):
        def make_project(self, declarations, semantics, sources):
            return MyProject(..., declaration_sources=declarations,
                             semantic_sources=semantics,
                             source_declarations=sources)

Everything else runs for free.

**``make_project`` takes three arguments, and the third is not optional.**
External sources are a required part of this contract, deliberately, and not
an optional side-door a format may leave unimplemented: a
format's external reads are part of what it declares, and a hook that could be
skipped would let the assertions covering them go quietly unrun. A skip is not a
signal.

**The assertions here are behavioural, not structural.** A format can satisfy
every type signature and still be wrong in the way that matters: raising on an
absent or malformed project, on a read path where absence is ordinary. That is
the property a second implementation is most likely to get wrong, and a suite
that only checks shapes will pass it. Hence ``test_*_never_raises``.

Once this is depended on, the builder names and the assertions are public
surface: a format pins against them, and renaming one is a breaking change.
That is worth accepting deliberately rather than discovering later.

The formats built to fail this contract ship beside it, in
:mod:`crosslink.conformance_calibration`, so an implementer can watch it go
red in their own environment before trusting it green.

Measures: src/crosslink/protocol.py, ProjectSource
Measures: src/crosslink/protocol.py, FingerprintedProject
Measures: src/crosslink/model.py, absent_join_sides
"""

from __future__ import annotations

import pytest

from .findings import DANGLING_DECLARED_JOIN, findings
from .model import Freshness
from .protocol import FingerprintedProject, ProjectSource, tier_of

__all__ = [
    "FingerprintedProjectContract",
    "ProjectSourceContract",
    "a_composite_key_declaration",
    "a_join_declaration",
    "a_semantic_definition",
    "a_single_key_declaration",
    "a_source_declaration",
    "malformed_yaml",
]


# --- fixture builders -------------------------------------------------------


def a_single_key_declaration(model: str = "dim_date", column: str = "date") -> str:
    """A model whose grain is one column."""

    return (
        "models:\n"
        f"  - name: {model}\n"
        "    columns:\n"
        f"      - name: {column}\n"
        "        tests:\n"
        "          - unique\n"
        "          - not_null\n"
    )


def a_composite_key_declaration(
    model: str = "fact_orders",
    columns: tuple[str, ...] = ("date", "provider", "product_id", "order_type"),
) -> str:
    """A model whose grain needs more than one column.

    The default is four columns rather than two on purpose: a format that
    handles pairs by special-casing them passes a two-column test and fails
    this one.
    """

    listed = "\n".join(f"            - {c}" for c in columns)
    return (
        "models:\n"
        f"  - name: {model}\n"
        "    tests:\n"
        "      - unique_combination_of_columns:\n"
        "          combination_of_columns:\n"
        f"{listed}\n"
    )


def a_join_declaration(
    from_model: str = "fact_sessions",
    from_column: str = "date",
    to_model: str = "dim_date",
    to_column: str = "date",
) -> str:
    """A declared relationship between two models."""

    return (
        "models:\n"
        f"  - name: {from_model}\n"
        "    columns:\n"
        f"      - name: {from_column}\n"
        "        tests:\n"
        "          - relationships:\n"
        f"              to: ref('{to_model}')\n"
        f"              field: {to_column}\n"
    )


def a_semantic_definition(model: str = "mart_revenue") -> str:
    """A semantic model with one dimension, one measure, and one metric."""

    return (
        "semantic_models:\n"
        f"  - name: {model}\n"
        f"    model: ref('{model}')\n"
        "    dimensions:\n"
        "      - name: date\n"
        "        type: time\n"
        "    measures:\n"
        "      - name: daily_revenue_net\n"
        "        agg: sum\n"
        "\n"
        "metrics:\n"
        "  - name: daily_revenue\n"
        "    type: simple\n"
        "    type_params:\n"
        "      measure: daily_revenue_net\n"
    )


def a_source_declaration(
    system: str = "sales",
    table: str = "orders_export_v1",
    schema: str | None = "sales",
    columns: tuple[str, ...] = ("placed_at", "amount"),
) -> str:
    """A warehouse table the project reads but does not build.

    The default names a table that is not also a model name, on purpose: a
    format that resolved sources by matching them against its own models would
    pass a test whose source shares a model's name and fail this one.

    ``schema=None`` omits the schema line entirely - a source system that is
    its own namespace is valid input, and the contract below needs to state
    it.
    """

    schema_line = f"    schema: {schema}\n" if schema is not None else ""
    listed = "\n".join(f"          - name: {c}" for c in columns)
    return (
        "sources:\n"
        f"  - name: {system}\n"
        f"{schema_line}"
        "    tables:\n"
        f"      - name: {table}\n"
        "        columns:\n"
        f"{listed}\n"
    )


def malformed_yaml() -> str:
    """Input that is not parseable. A format must survive it, not refuse."""

    return "models:\n  - name: broken\n   columns: [oops\n"


# --- the contracts ----------------------------------------------------------


class ProjectSourceContract:
    """Tier 1. Subclass and implement :meth:`make_project`.

    External sources are asserted here rather than at tier 2, because a
    project's external reads are something it *declares* - they arrive through
    ``declarations()`` like every other statement. What tier 2 adds is a
    consumer for them, not a way to express them.
    """

    def make_project(
        self,
        declarations: dict[str, str],
        semantics: dict[str, str],
        sources: dict[str, str],
    ):
        """Build the format under test from declaration, semantic, and source text.

        ``sources`` is keyed by the model that reads the declared tables.
        """

        raise NotImplementedError  # pragma: no cover - always overridden

    # -- shape ---------------------------------------------------------------

    def test_satisfies_the_tier_one_protocol(self):
        project = self.make_project({}, {}, {})
        assert isinstance(project, ProjectSource)
        assert tier_of(project) >= 1

    def test_declares_a_stable_format_name(self):
        first = self.make_project({}, {}, {})
        second = self.make_project({"d": a_single_key_declaration()}, {}, {})
        assert first.format == second.format
        assert first.format, "a format needs a non-empty name to be resolvable"

    # -- behaviour: the half a shape check cannot reach -----------------------

    def test_an_empty_project_never_raises(self):
        declarations = self.make_project({}, {}, {}).declarations()
        assert declarations.is_empty or declarations.models

    def test_malformed_input_never_raises(self):
        """The property most likely to be got wrong, asserted directly."""

        declarations = self.make_project(
            {"broken": malformed_yaml()}, {}, {}
        ).declarations()
        assert declarations is not None

    def test_malformed_input_is_explained_rather_than_silent(self):
        """Degrading quietly still owes the reader a reason."""

        declarations = self.make_project(
            {"broken": malformed_yaml()}, {}, {}
        ).declarations()
        assert declarations.notes, "a skipped declaration must leave a note"

    def test_a_malformed_source_declaration_never_raises_and_is_explained(self):
        """Same contract on the source channel. Asserted separately because it
        is a different parser: a format can be careful on one input and not on
        the other, and one test over both would pass on either."""

        declarations = self.make_project(
            {}, {}, {"broken": malformed_yaml()}
        ).declarations()
        assert declarations is not None
        assert declarations.notes, "a skipped source declaration must leave a note"

    # -- the declared channel ------------------------------------------------

    def test_a_single_column_key_is_read(self):
        declarations = self.make_project(
            {"dim_date": a_single_key_declaration()}, {}, {}
        ).declarations()
        keys = [k for k in declarations.declared_keys if k.model == "dim_date"]
        assert [k.columns for k in keys] == [("date",)]

    def test_a_composite_key_keeps_every_column_and_their_order(self):
        """The failure this catches is silent: a truncated key still looks
        like a declared grain, and reads as a narrower one that is simply
        wrong rather than as a missing declaration."""

        declarations = self.make_project(
            {"fact": a_composite_key_declaration()}, {}, {}
        ).declarations()
        keys = [k for k in declarations.declared_keys if k.model == "fact_orders"]
        assert len(keys) == 1
        assert keys[0].columns == ("date", "provider", "product_id", "order_type")
        assert keys[0].is_composite

    def test_a_declared_join_carries_both_sides(self):
        declarations = self.make_project({"j": a_join_declaration()}, {}, {}).declarations()
        assert len(declarations.declared_joins) == 1
        join = declarations.declared_joins[0]
        assert join.from_model == "fact_sessions"
        assert join.to_model == "dim_date"
        assert join.from_columns == ("date",)
        assert join.to_columns == ("date",)

    def test_a_dangling_join_side_is_agreed_by_notes_and_findings(self):
        """The notes channel and the findings layer answer "does this join
        dangle?" with one shared rule (``model.absent_join_sides``). This arm
        is the tripwire: a producer that checks ``from_model`` alone yields
        a finding with no note for a to-side-only dangler, and the two
        surfaces disagree about the same snapshot."""

        declarations = self.make_project(
            {"j": a_join_declaration(to_model="ghost_dim")}, {}, {}
        ).declarations()
        found = [f for f in findings(declarations) if f.kind == DANGLING_DECLARED_JOIN]
        assert any("ghost_dim" in f.subject for f in found)
        assert any("ghost_dim" in note for note in declarations.notes)

    def test_semantic_models_and_metrics_are_read(self):
        declarations = self.make_project(
            {}, {"s": a_semantic_definition()}, {}
        ).declarations()
        assert [m.name for m in declarations.semantic_models] == ["mart_revenue"]
        assert [m.name for m in declarations.metrics] == ["daily_revenue"]

    # -- the source channel --------------------------------------------------

    def test_an_external_source_is_read_and_attributed_to_its_reader(self):
        declarations = self.make_project(
            {}, {}, {"orders_raw": a_source_declaration()}
        ).declarations()
        assert len(declarations.sources) == 1
        source = declarations.sources[0]
        assert source.system == "sales"
        assert source.table == "orders_export_v1"
        assert source.schema_name == "sales"
        assert source.columns == ("placed_at", "amount")
        assert "orders_raw" in source.read_by

    def test_a_source_requires_a_system_it_cannot_invent(self):
        """A source entry with no name is skipped and explained, not given a
        placeholder. The consumer identifies a source as ``system.table``, so a
        fabricated system produces a finding about a table that does not
        exist under that name."""

        declarations = self.make_project(
            {}, {}, {"reader": "sources:\n  - schema: sales\n    tables:\n      - name: t\n"}
        ).declarations()
        assert declarations.sources == ()
        assert declarations.notes

    def test_mixed_schema_presence_under_one_system_never_raises(self):
        """One schema'd and one unschema'd table under the same system is
        valid input, and it is exactly the shape a raw ``(system, schema,
        table)`` sort crashes on - ``None`` and ``str`` do not compare. The
        canonical order (``model.source_sort_key``) puts the unschema'd
        source first, and that choice is asserted so no format re-decides it
        inline."""

        declarations = self.make_project(
            {},
            {},
            {
                "reader_a": a_source_declaration(table="events", schema=None),
                "reader_b": a_source_declaration(table="requests", schema="raw"),
            },
        ).declarations()
        assert len(declarations.sources) == 2
        assert [s.schema_name for s in declarations.sources] == [None, "raw"]

    def test_one_table_declared_twice_is_one_source_with_two_readers(self):
        """Emitting it twice would be reported as two contracts with the
        warehouse, so a single missing table would raise two findings."""

        declaration = a_source_declaration()
        declarations = self.make_project(
            {}, {}, {"reader_a": declaration, "reader_b": declaration}
        ).declarations()
        assert len(declarations.sources) == 1
        assert set(declarations.sources[0].read_by) == {"reader_a", "reader_b"}

    def test_a_project_that_only_declares_sources_is_not_empty(self):
        """A project that builds nothing but names what it reads has still
        said something, and reporting it as empty discards the only statement
        it made."""

        declarations = self.make_project(
            {}, {}, {"reader": a_source_declaration()}
        ).declarations()
        assert not declarations.is_empty

    def test_the_declared_channel_is_not_vacuous(self):
        """Guards every assertion above. If the builders stopped producing
        anything, the tests would still pass while measuring nothing."""

        declarations = self.make_project(
            {"a": a_single_key_declaration(), "b": a_join_declaration()},
            {"s": a_semantic_definition()},
            {"c": a_source_declaration()},
        ).declarations()
        assert declarations.declared_keys
        assert declarations.declared_joins
        assert declarations.semantic_models
        assert declarations.sources

    def test_freshness_is_never_a_bare_boolean(self):
        """A format with no compiled artifact must say so, not say 'current'."""

        declarations = self.make_project({}, {}, {}).declarations()
        assert isinstance(declarations.freshness, Freshness)


class FingerprintedProjectContract(ProjectSourceContract):
    """Tier 2. Inherits every tier-1 assertion."""

    def test_satisfies_the_tier_two_protocol(self):
        assert isinstance(self.make_project({}, {}, {}), FingerprintedProject)
        assert tier_of(self.make_project({}, {}, {})) >= 2

    def test_a_fingerprint_is_stable_across_calls(self):
        project = self.make_project({}, {}, {})
        assert project.fingerprint() == project.fingerprint()

    def test_two_identical_projects_fingerprint_alike(self):
        left = self.make_project({"a": a_single_key_declaration()}, {}, {})
        right = self.make_project({"a": a_single_key_declaration()}, {}, {})
        assert left.fingerprint().layers == right.fingerprint().layers

    def test_fingerprinting_never_raises_on_an_empty_project(self):
        assert self.make_project({}, {}, {}).fingerprint() is not None

    def test_gaining_an_external_source_is_visible_as_drift(self):
        """A new warehouse dependency is a change in the project. A fingerprint
        that missed it would report no drift on the one axis a snapshot exists
        to watch."""

        without = self.make_project({}, {}, {}).fingerprint()
        with_source = self.make_project(
            {}, {}, {"reader": a_source_declaration()}
        ).fingerprint()
        assert without.layers != with_source.layers
        assert with_source.changed_layers(without)

    def test_repointing_a_source_to_another_schema_is_drift(self):
        """Two tables of the same name in different datasets are two different
        warehouse objects. A hash over the bare table name calls the swap no
        change - and it is the change most likely to be made by accident."""

        here = self.make_project(
            {}, {}, {"reader": a_source_declaration(schema="sales")}
        ).fingerprint()
        there = self.make_project(
            {}, {}, {"reader": a_source_declaration(schema="sales_backup")}
        ).fingerprint()
        assert here.layers != there.layers


@pytest.fixture
def _conformance_marker():  # pragma: no cover - keeps pytest importing this module happy
    """Present so this module is importable as a plugin without side effects."""

    return None

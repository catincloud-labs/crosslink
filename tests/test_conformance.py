# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""DagsterProject against the shipped contract.

The whole of the wiring is `make_project`. That is the point of shipping the
suite: a second format writes these same few lines and inherits every
assertion, rather than hand-rolling parity tests that drift from the contract
they are supposed to be checking.
"""

from __future__ import annotations

from crosslink import DagsterProject, DbtProject, ProjectModel
from crosslink.conformance import FingerprintedProjectContract
from crosslink.declarations import parse_source_declarations

MODELS = (
    ProjectModel(name="dim_date", layer="silver"),
    ProjectModel(name="dim_product", layer="silver"),
    ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
    ProjectModel(name="fact_sessions", depends_on=("dim_date",), layer="gold"),
    ProjectModel(name="mart_revenue", depends_on=("fact_orders",), layer="platinum"),
)


class TestDagsterProjectConformance(FingerprintedProjectContract):
    def make_project(self, declarations, semantics, sources):
        return DagsterProject(
            MODELS,
            name="catalyst",
            declaration_sources=declarations,
            semantic_sources=semantics,
            source_declarations=sources,
        )


class TestDbtProjectConformance(FingerprintedProjectContract):
    """The suite's first second consumer - the moment the seam stops being a
    description of one implementation.

    The contract's ``sources`` channel is keyed by the reading model, which
    the Dagster reduction takes as a declaration. dbt's truth is better than
    a declaration - a reader says so in its own SQL - so this wiring
    *generates* a reader model per channel key that ``source()``-references
    every table its file declares, and attribution is then genuinely derived
    by the format rather than replayed from the test's key. The enumeration
    uses the same parser the format uses, so a malformed source file yields
    no reader here and a note there, never a raise in either place.
    """

    def make_project(self, declarations, semantics, sources):
        # One directory per channel: a suffix scheme can collide (a
        # declarations key literally named `x_sources` would map onto the
        # sources channel's path for key `x`, and the later write would
        # silently discard one channel), while distinct directories cannot.
        files = {"dbt_project.yml": "name: analytics\nmodel-paths:\n  - models\n"}
        for key, text in declarations.items():
            files[f"models/declared/{key}.yml"] = text
        for key, text in semantics.items():
            files[f"models/semantic/{key}.yml"] = text
        for key, text in sources.items():
            files[f"models/source_decls/{key}.yml"] = text
            declared, _ = parse_source_declarations({key: text})
            reads = "\n".join(
                "select * from {{ source('%s', '%s') }}" % (s.system, s.table)
                for s in declared
            )
            if reads:
                files[f"models/{key}.sql"] = reads
        return DbtProject(files)

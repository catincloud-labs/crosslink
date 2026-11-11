"""The format a stranger builds, shared by every arm that needs a correct one.

The shape the contract's own docstring documents: a function that takes the
three channels `make_project` is handed (declaration, semantic and source
text) and returns a project. Here it is the package's `DagsterProject` over
models of the stranger's own, so an arm that wraps it is wrong only in the
way that arm adds.

`arms.py` copies this file beside each arm's `test_format.py`; it is not
imported from this tree.
"""

from __future__ import annotations

from crosslink import DagsterProject, ProjectModel

MODELS = (
    ProjectModel(name="dim_date", layer="silver"),
    ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
    ProjectModel(name="fact_sessions", depends_on=("dim_date",), layer="gold"),
)


def a_correct_format(
    declarations: dict[str, str],
    semantics: dict[str, str],
    sources: dict[str, str],
) -> DagsterProject:
    return DagsterProject(
        MODELS,
        name="stranger",
        declaration_sources=declarations,
        semantic_sources=semantics,
        source_declarations=sources,
    )

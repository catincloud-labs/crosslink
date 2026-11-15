# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The dbt reduction's own arms: the walk, the SQL side, the stated decisions.

The conformance suite already holds this format to the shared contract (see
``TestDbtProjectConformance``); what lives here is what the contract cannot
know - the tree-shaped inputs and the decisions the module docstring states.
The fixture is a staging/marts tree with a sources file, a stg model reading
a source, and a mart reading the stg model: the shape of a working dbt
project.
"""

from __future__ import annotations

import os

import pytest

from crosslink import DbtProject, Freshness, ProjectModel
from crosslink.conformance import (
    a_single_key_declaration,
    a_source_declaration,
    malformed_yaml,
)
from crosslink.model import layered_fingerprint
from crosslink.protocol import tier_of


def an_analytics_tree() -> dict[str, str]:
    """A small dbt tree: one source, one staging model reading it, one mart."""

    return {
        "dbt_project.yml": "name: analytics\nversion: '1.0'\nmodel-paths:\n  - models\n",
        "models/staging/_sources.yml": a_source_declaration(
            system="dex", table="events_raw", schema="raw", columns=("event_time", "cost")
        ),
        "models/staging/stg_events.sql": (
            "select event_time, cost\nfrom {{ source('dex', 'events_raw') }}\n"
        ),
        "models/staging/stg_events.yml": a_single_key_declaration(
            model="stg_events", column="event_time"
        ),
        "models/marts/fct_costs.sql": (
            "select event_time, sum(cost) as daily_cost\n"
            "from {{ ref('stg_events') }}\ngroup by 1\n"
        ),
    }


MODEL_PATH_SPELLINGS = (
    "models/staging",
    "./models/staging",
    "models/staging/",
    "models/./staging",
    "models//staging",
    "models/staging/.",
    "./models/./staging/./",
    "models\\.\\staging",
)


def a_tree_with_model_path(entry: str) -> dict[str, str]:
    """The analytics tree with one model-paths entry, quoted so YAML keeps
    its backslashes and dots as written."""

    tree = an_analytics_tree()
    tree["dbt_project.yml"] = f"name: analytics\nmodel-paths:\n  - '{entry}'\n"
    return tree


class TestTheTreeWalk:
    def test_models_come_from_sql_files_with_layers_from_directories(self):
        declarations = DbtProject(an_analytics_tree()).declarations()
        assert [(m.name, m.layer) for m in declarations.models] == [
            ("fct_costs", "marts"),
            ("stg_events", "staging"),
        ]

    def test_dependencies_come_from_ref_extraction(self):
        declarations = DbtProject(an_analytics_tree()).declarations()
        fct = next(m for m in declarations.models if m.name == "fct_costs")
        assert fct.depends_on == ("stg_events",)

    def test_a_two_argument_ref_names_the_model_second(self):
        """``ref('package', 'model')`` - the model is the last string, and a
        reader that took the first would depend on a package name."""

        tree = an_analytics_tree()
        tree["models/marts/fct_other.sql"] = (
            "select * from {{ ref('some_package', 'stg_events') }}\n"
        )
        declarations = DbtProject(tree).declarations()
        other = next(m for m in declarations.models if m.name == "fct_other")
        assert other.depends_on == ("stg_events",)

    def test_a_model_directly_under_the_root_has_no_layer(self):
        tree = an_analytics_tree()
        tree["models/orphan.sql"] = "select 1\n"
        declarations = DbtProject(tree).declarations()
        orphan = next(m for m in declarations.models if m.name == "orphan")
        assert orphan.layer is None

    def test_the_project_name_comes_from_dbt_project_yml(self):
        declarations = DbtProject(an_analytics_tree()).declarations()
        assert declarations.format == "dbt"
        assert declarations.name == "analytics"

    def test_the_format_reaches_tier_two_and_declines_tier_three(self):
        """Tier 3 is this format's future, not its present - and a stub
        claiming it would make ``tier_of`` answer falsely."""

        assert tier_of(DbtProject(an_analytics_tree())) == 2


class TestTheStatedDecisions:
    def test_read_by_is_derived_from_source_calls_not_file_keys(self):
        """The declaration file is named ``_sources.yml``; the reader named
        in ``read_by`` must be the model whose SQL reads the table."""

        declarations = DbtProject(an_analytics_tree()).declarations()
        assert len(declarations.sources) == 1
        source = declarations.sources[0]
        assert (source.system, source.table) == ("dex", "events_raw")
        assert source.read_by == ("stg_events",)

    def test_a_declared_source_nothing_reads_keeps_an_empty_read_by(self):
        """Derivation is honest in both directions: no reader means no
        attribution, never a fabricated one."""

        tree = an_analytics_tree()
        del tree["models/staging/stg_events.sql"]
        declarations = DbtProject(tree).declarations()
        assert declarations.sources[0].read_by == ()

    def test_freshness_is_not_applicable_because_no_artifact_was_consulted(self):
        """The tri-state describes the reduction that ran, not dbt: this one
        reads source files directly and never opens target/manifest.json,
        so fresh-or-stale would be a claim nobody checked."""

        declarations = DbtProject(an_analytics_tree()).declarations()
        assert declarations.freshness is Freshness.NOT_APPLICABLE

    def test_one_schema_file_can_feed_more_than_one_parser(self):
        """dbt schema files legitimately carry ``models:`` beside
        ``sources:`` in one document; routing is by top-level key, not by
        one-file-one-vocabulary."""

        tree = {
            "dbt_project.yml": "name: analytics\n",
            "models/everything.yml": (
                a_single_key_declaration(model="stg_events", column="event_time")
                + a_source_declaration(system="dex", table="events_raw")
            ),
            "models/stg_events.sql": "select * from {{ source('dex', 'events_raw') }}\n",
        }
        declarations = DbtProject(tree).declarations()
        assert len(declarations.declared_keys) == 1
        assert len(declarations.sources) == 1
        assert declarations.sources[0].read_by == ("stg_events",)


class TestTheExtractionEdges:
    """The regex decisions, held to dbt's actual rendering order: Jinja runs
    before SQL is parsed, so a call in a SQL comment is a real dependency and
    a call in a Jinja comment is nothing at all."""

    def test_a_jinja_commented_ref_is_not_an_edge(self):
        tree = an_analytics_tree()
        tree["models/marts/fct_drafted.sql"] = (
            "select 1\n{# not yet: {{ ref('stg_events') }} #}\n"
        )
        declarations = DbtProject(tree).declarations()
        drafted = next(m for m in declarations.models if m.name == "fct_drafted")
        assert drafted.depends_on == ()

    def test_a_sql_commented_ref_is_an_edge_because_jinja_renders_first(self):
        tree = an_analytics_tree()
        tree["models/marts/fct_commented.sql"] = (
            "-- {{ ref('stg_events') }}\nselect 1\n"
        )
        declarations = DbtProject(tree).declarations()
        commented = next(m for m in declarations.models if m.name == "fct_commented")
        assert commented.depends_on == ("stg_events",)

    def test_a_versioned_ref_still_names_its_model(self):
        tree = an_analytics_tree()
        tree["models/marts/fct_versioned.sql"] = (
            "select * from {{ ref('stg_events', v=2) }}\n"
        )
        declarations = DbtProject(tree).declarations()
        versioned = next(m for m in declarations.models if m.name == "fct_versioned")
        assert versioned.depends_on == ("stg_events",)

    def test_keyword_source_arguments_still_attribute_the_read(self):
        tree = an_analytics_tree()
        tree["models/staging/stg_events.sql"] = (
            "select * from {{ source(source_name='dex', table_name='events_raw') }}\n"
        )
        declarations = DbtProject(tree).declarations()
        assert declarations.sources[0].read_by == ("stg_events",)

    def test_mismatched_quotes_are_not_a_reference(self):
        tree = an_analytics_tree()
        tree["models/marts/fct_broken.sql"] = "select * from {{ ref('broken\") }}\n"
        declarations = DbtProject(tree).declarations()
        broken = next(m for m in declarations.models if m.name == "fct_broken")
        assert broken.depends_on == ()


class TestNothingRaises:
    def test_a_malformed_schema_file_is_noted_and_the_rest_still_parses(self):
        tree = an_analytics_tree()
        tree["models/staging/broken.yml"] = malformed_yaml()
        declarations = DbtProject(tree).declarations()
        assert any("broken.yml" in note for note in declarations.notes)
        assert declarations.declared_keys  # the good file still landed

    def test_a_missing_dbt_project_yml_degrades_to_a_named_fallback(self):
        tree = an_analytics_tree()
        del tree["dbt_project.yml"]
        declarations = DbtProject(tree).declarations()
        assert declarations.name == "unnamed"
        assert any("dbt_project.yml" in note for note in declarations.notes)
        assert declarations.models  # the walk still happened, on the default path

    def test_duplicate_model_stems_converge_on_the_first_in_path_order(self):
        """dbt refuses duplicate names at compile time; a read path cannot
        refuse, so it converges and says so - the parsers' posture."""

        tree = an_analytics_tree()
        tree["models/marts/stg_events.sql"] = "select 2\n"
        declarations = DbtProject(tree).declarations()
        stems = [m.name for m in declarations.models]
        assert stems.count("stg_events") == 1
        kept = next(m for m in declarations.models if m.name == "stg_events")
        assert kept.layer == "marts"  # models/marts sorts before models/staging
        assert any("stg_events" in note and "path order" in note for note in declarations.notes)

    def test_a_declaration_for_an_undefined_model_is_kept_with_a_note(self):
        tree = an_analytics_tree()
        tree["models/staging/ghost.yml"] = a_single_key_declaration(
            model="ghost_model", column="id"
        )
        declarations = DbtProject(tree).declarations()
        assert any(k.model == "ghost_model" for k in declarations.declared_keys)
        assert any("does not define" in note for note in declarations.notes)

    def test_a_file_named_only_dot_sql_is_skipped_with_a_note(self):
        """An empty stem is no model name, and ``ProjectModel(name="")``
        would raise - the one thing tier 1 promises never happens."""

        tree = an_analytics_tree()
        tree["models/.sql"] = "select 1\n"
        declarations = DbtProject(tree).declarations()
        assert all(m.name for m in declarations.models)
        assert any("no name before its extension" in note for note in declarations.notes)

    def test_a_non_mapping_dbt_project_yml_degrades_with_a_note(self):
        tree = an_analytics_tree()
        tree["dbt_project.yml"] = "- just\n- a list\n"
        declarations = DbtProject(tree).declarations()
        assert declarations.name == "unnamed"
        assert any("not a mapping" in note for note in declarations.notes)
        assert declarations.models  # the walk still happened, on the default path

    def test_an_unrouted_schema_file_is_noted(self):
        """The one-character typo - ``model:`` for ``models:`` - must not
        make a whole file's declarations vanish unexplained."""

        tree = an_analytics_tree()
        tree["models/staging/typo.yml"] = (
            "version: 2\nmodel:\n  - name: dim_date\n"
        )
        declarations = DbtProject(tree).declarations()
        assert any("typo.yml" in note and "none of the vocabularies" in note
                   for note in declarations.notes)

    def test_trailing_slash_and_dot_segment_model_paths_still_route(self):
        for spelling in ("models/", "./models"):
            tree = an_analytics_tree()
            tree["dbt_project.yml"] = (
                f"name: analytics\nmodel-paths:\n  - {spelling}\n"
            )
            declarations = DbtProject(tree).declarations()
            assert declarations.models, spelling

    @pytest.mark.parametrize("spelling", MODEL_PATH_SPELLINGS)
    def test_a_dot_or_empty_segment_anywhere_routes_what_the_plain_spelling_routes(
        self, spelling
    ):
        """``models/./staging`` and ``models//staging`` name the directory
        ``models/staging`` names; routing compares by prefix, so the entry is
        collapsed before it is compared, or it routes nothing and says
        nothing. The first three spellings are the controls."""

        plain = DbtProject(a_tree_with_model_path("models/staging")).declarations()
        declarations = DbtProject(a_tree_with_model_path(spelling)).declarations()
        assert [m.name for m in plain.models] == ["stg_events"]
        assert declarations.models == plain.models, spelling
        assert not any("model-paths" in note for note in declarations.notes), spelling

    @pytest.mark.parametrize("spelling", (".", "./", "./.", ".//"))
    def test_an_entry_that_collapses_to_nothing_names_the_project_root(self, spelling):
        declarations = DbtProject(a_tree_with_model_path(spelling)).declarations()
        assert any("names the project root" in note for note in declarations.notes), spelling
        assert any("default model paths" in note for note in declarations.notes), spelling

    @pytest.mark.parametrize(
        "spelling",
        ("models/./../x", "models\\.\\..", "./..", "models//..//x", "models/.\\../x"),
    )
    def test_a_dot_dot_segment_mixed_with_dot_segments_is_still_dropped(self, spelling):
        declarations = DbtProject(a_tree_with_model_path(spelling)).declarations()
        assert any("has a '..' segment" in note for note in declarations.notes), spelling

    @pytest.mark.parametrize("spelling", ("./C:/shared", ".\\C:\\shared", ".//C:/shared"))
    def test_a_drive_behind_a_dot_segment_is_still_absolute(self, spelling):
        declarations = DbtProject(a_tree_with_model_path(spelling)).declarations()
        assert any("is absolute" in note for note in declarations.notes), spelling

    def test_an_unusable_model_paths_list_falls_back_with_a_note(self):
        tree = an_analytics_tree()
        tree["dbt_project.yml"] = "name: analytics\nmodel-paths:\n  - 123\n"
        declarations = DbtProject(tree).declarations()
        assert declarations.models  # the default path carried the walk
        assert any("is not a path" in note for note in declarations.notes)
        assert any("default model paths" in note for note in declarations.notes)

    def test_an_absolute_model_paths_entry_is_dropped_with_a_note(self):
        tree = an_analytics_tree()
        tree["dbt_project.yml"] = (
            "name: analytics\nmodel-paths:\n  - C:/shared/models\n  - models\n"
        )
        declarations = DbtProject(tree).declarations()
        assert declarations.models
        assert any("is absolute" in note for note in declarations.notes)

    def test_a_model_paths_entry_with_a_dot_dot_segment_is_dropped_with_a_note(self):
        for spelling in ("../shared", "models/../../shared", "..\\shared", "./../shared/"):
            tree = an_analytics_tree()
            tree["dbt_project.yml"] = (
                f"name: analytics\nmodel-paths:\n  - '{spelling}'\n  - models\n"
            )
            tree["../shared/from_shared.sql"] = "select 1\n"
            declarations = DbtProject(tree).declarations()
            names = {m.name for m in declarations.models}
            assert "fct_costs" in names, spelling
            assert "from_shared" not in names, spelling
            assert any("has a '..' segment" in note for note in declarations.notes), spelling

    def test_a_dot_dot_segment_is_dropped_even_when_it_stays_inside_the_root(self):
        """One rule, needing no resolution of the path: the entry is dropped
        for its segment, not for where it would lead."""

        tree = an_analytics_tree()
        tree["dbt_project.yml"] = "name: analytics\nmodel-paths:\n  - models/staging/../marts\n"
        declarations = DbtProject(tree).declarations()
        assert any("has a '..' segment" in note for note in declarations.notes)
        assert any("default model paths" in note for note in declarations.notes)

    def test_a_dot_dot_inside_a_directory_name_is_not_a_segment(self):
        tree = {
            path.replace("models/", "models..v2/", 1): text
            for path, text in an_analytics_tree().items()
        }
        tree["dbt_project.yml"] = "name: analytics\nmodel-paths:\n  - models..v2\n"
        declarations = DbtProject(tree).declarations()
        assert any(m.name == "fct_costs" for m in declarations.models)
        assert not any("has a '..' segment" in note for note in declarations.notes)

    def test_a_duplicate_stem_losers_source_read_is_not_attributed(self):
        """The winner's SQL is what ships; a read stated only in the dropped
        file must not attribute to a model whose own SQL says no such
        thing."""

        tree = an_analytics_tree()
        tree["models/marts/stg_events.sql"] = "select 2\n"  # wins path order, reads nothing
        declarations = DbtProject(tree).declarations()
        assert declarations.sources[0].read_by == ()

    def test_an_undeclared_source_read_is_noted(self):
        tree = an_analytics_tree()
        tree["models/staging/stg_orders.sql"] = (
            "select * from {{ source('erp', 'orders_raw') }}\n"
        )
        declarations = DbtProject(tree).declarations()
        assert any("no declaration covers" in note and "orders_raw" in note
                   for note in declarations.notes)

    def test_an_undeclared_source_read_becomes_a_lineage_edge(self):
        """The SQL states the read; dropping it entirely would hide the
        flagship "graph reads something nothing declares" contradiction in
        exactly this format. The bare table name lands in depends_on - the
        same surface the dagster reduction gives the class."""

        tree = an_analytics_tree()
        tree["models/staging/stg_orders.sql"] = (
            "select * from {{ source('erp', 'orders_raw') }}\n"
        )
        declarations = DbtProject(tree).declarations()
        orders = next(m for m in declarations.models if m.name == "stg_orders")
        assert orders.depends_on == ("orders_raw",)

    def test_a_declared_source_read_stays_out_of_depends_on(self):
        """A resolved read is attribution (read_by), not lineage: the
        declaration carries the table, and doubling it into depends_on would
        make every declared source also look like a dangling root."""

        declarations = DbtProject(an_analytics_tree()).declarations()
        stg = next(m for m in declarations.models if m.name == "stg_events")
        assert stg.depends_on == ()
        assert declarations.sources[0].read_by == ("stg_events",)


class TestTheFingerprint:
    def test_layers_are_directories_plus_the_sources_entry(self):
        fingerprint = DbtProject(an_analytics_tree()).fingerprint()
        assert set(fingerprint.layers) == {"staging", "marts", "sources"}

    def test_repointing_a_source_to_another_schema_is_drift_here_too(self):
        """The contract asserts this through make_project; asserting it on
        the tree shape too keeps the arm meaningful if the wiring ever
        changes what it generates."""

        here = DbtProject(an_analytics_tree()).fingerprint()
        moved = an_analytics_tree()
        # columns= restates the fixture's own value: the schema must be the
        # ONLY variable, or a hash regression that drops schema_name would
        # hide behind the columns change and this arm would stay green.
        moved["models/staging/_sources.yml"] = a_source_declaration(
            system="dex", table="events_raw", schema="raw_backup",
            columns=("event_time", "cost"),
        )
        assert here.layers != DbtProject(moved).fingerprint().layers

    def test_a_real_layer_named_sources_merges_rather_than_hides_drift(self):
        """dbt layer names are user directory names, so ``models/sources/``
        is ordinary input. Its hash combines with the external-source hash;
        an overwrite would make rewiring inside that directory invisible to
        the drift report."""

        def tree(ref_target: str) -> dict[str, str]:
            return {
                "dbt_project.yml": "name: analytics\n",
                "models/_sources.yml": a_source_declaration(
                    system="dex", table="events_raw"
                ),
                "models/stg_events.sql": "select 1\n",
                "models/stg_other.sql": "select 2\n",
                "models/sources/src_view.sql": (
                    "select * from {{ ref('%s') }}\n" % ref_target
                ),
            }

        before = DbtProject(tree("stg_events")).fingerprint()
        after = DbtProject(tree("stg_other")).fingerprint()
        assert before.layers["sources"] != after.layers["sources"]

    def test_a_generator_of_models_still_censuses_them(self):
        """The shared symbol is public, so an iterable argument must not be
        exhausted by the layer grouping and leave the census empty."""

        models = (
            ProjectModel(name="dim_date", layer="silver"),
            ProjectModel(name="fct_costs", depends_on=("dim_date",), layer="gold"),
        )
        fingerprint = layered_fingerprint((m for m in models), ())
        assert fingerprint.models == ("dim_date", "fct_costs")
        assert set(fingerprint.layers) == {"silver", "gold"}


class TestFromDirectory:
    def test_a_tree_on_disk_reduces_identically_to_the_same_tree_in_memory(self, tmp_path):
        tree = an_analytics_tree()
        for path, text in tree.items():
            target = tmp_path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        from_disk = DbtProject.from_directory(tmp_path).declarations()
        from_memory = DbtProject(tree).declarations()
        assert from_disk == from_memory

    def test_an_unreadable_file_degrades_to_a_note_not_a_raise(self, tmp_path):
        """One stray non-UTF-8 file must not turn the constructor into an
        outage - the same degrade-and-note contract everything else holds."""

        tree = an_analytics_tree()
        for path, text in tree.items():
            target = tmp_path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        (tmp_path / "models" / "bad.sql").write_bytes(b"select 'caf\xe9'\n")
        declarations = DbtProject.from_directory(tmp_path).declarations()
        assert any("bad.sql" in note and "could not be read" in note
                   for note in declarations.notes)
        assert any(m.name == "fct_costs" for m in declarations.models)

    def test_the_walk_reads_nothing_outside_the_project_root(self, tmp_path):
        """A model-paths entry that climbs out of the root names a directory
        the caller never passed; its files must not reach the reduction."""

        root = tmp_path / "project"
        tree = an_analytics_tree()
        tree["dbt_project.yml"] = (
            "name: analytics\nmodel-paths:\n  - ../outside\n  - models\n"
        )
        for path, text in tree.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "from_outside.sql").write_text("select 1\n", encoding="utf-8")
        declarations = DbtProject.from_directory(root).declarations()
        names = {m.name for m in declarations.models}
        assert "fct_costs" in names
        assert "from_outside" not in names
        assert any("has a '..' segment" in note for note in declarations.notes)

    @pytest.mark.parametrize("spelling", MODEL_PATH_SPELLINGS)
    def test_a_dot_or_empty_segment_routes_on_disk_as_in_memory(self, tmp_path, spelling):
        tree = a_tree_with_model_path(spelling)
        for path, text in tree.items():
            target = tmp_path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        from_disk = DbtProject.from_directory(tmp_path).declarations()
        assert [m.name for m in from_disk.models] == ["stg_events"], spelling
        assert from_disk == DbtProject(tree).declarations(), spelling

    def test_a_slash_behind_a_dot_segment_names_a_path_inside_the_root(self, tmp_path):
        """``.//x`` is the relative ``x``, as a POSIX shell reads it, so an
        absolute directory spelled behind ``./`` is looked for under the
        root: nothing outside the root is read, and the walk does not raise."""

        root, outside, _ = a_tree_with_a_directory_either_side_of_the_root(tmp_path)
        relative = outside.as_posix()[len(outside.drive):].lstrip("/")
        (root / relative).mkdir(parents=True)
        (root / relative / "from_under_root.sql").write_text("select 3\n", encoding="utf-8")
        (root / "dbt_project.yml").write_text(
            f"name: analytics\nmodel-paths:\n  - './/{relative}'\n  - models\n",
            encoding="utf-8",
        )
        declarations = DbtProject.from_directory(root).declarations()
        names = {m.name for m in declarations.models}
        assert "fct_costs" in names
        assert "from_under_root" in names
        assert "from_outside" not in names
        assert not any("is absolute" in note for note in declarations.notes)

    def test_an_absolute_directory_behind_a_dot_segment_is_not_walked(self, tmp_path):
        """``./`` before an absolute path - a drive path on Windows, ``//``
        and a path elsewhere - leaves it absolute or relative to the root,
        never a directory outside it: nothing outside is read, and the walk
        does not raise."""

        root, outside, _ = a_tree_with_a_directory_either_side_of_the_root(tmp_path)
        (root / "dbt_project.yml").write_text(
            f"name: analytics\nmodel-paths:\n  - './{outside.as_posix()}'\n  - models\n",
            encoding="utf-8",
        )
        declarations = DbtProject.from_directory(root).declarations()
        names = {m.name for m in declarations.models}
        assert "fct_costs" in names
        assert "from_outside" not in names
        if outside.drive:
            assert any("is absolute" in note for note in declarations.notes)

    def test_a_file_link_is_read_only_where_it_resolves_inside_the_root(self, tmp_path):
        """A file link under the model path can point anywhere, and every
        platform's walk lists it. The one that leads out of the root is
        skipped with a note; the one that stays inside it is read, so the
        containment is judged by where a file resolves, not by whether it was
        reached through a link."""

        root, outside, kept = a_tree_with_a_directory_either_side_of_the_root(tmp_path)
        file_link(outside / "from_outside.sql", root / "models" / "out_file_link.sql")
        file_link(kept / "from_kept.sql", root / "models" / "in_file_link.sql")
        declarations = DbtProject.from_directory(root).declarations()
        names = {m.name for m in declarations.models}
        assert "fct_costs" in names
        assert "in_file_link" in names
        assert "out_file_link" not in names
        assert any("out_file_link" in note and "resolves outside the project root" in note
                   for note in declarations.notes)

    def test_a_directory_link_is_read_only_where_it_resolves_inside_the_root(self, tmp_path):
        """A directory link under the model path can point anywhere, and
        whether the walk descends it is the platform's: it descends a Windows
        junction and does not descend a directory symlink. So this reads
        what the walk lists, and holds the reader to it: nothing outside the
        root is ever read, a file the walk reached outside it is noted, and
        a file the walk reached inside it is read. Where the walk descends
        neither link, the two comparisons hold with nothing behind them, and
        this guards the walk while the file link's test, above, guards the
        containment."""

        root, outside, kept = a_tree_with_a_directory_either_side_of_the_root(tmp_path)
        directory_link(outside, root / "models" / "out_link")
        directory_link(kept, root / "models" / "in_link")
        walked = {path.name for path in (root / "models").rglob("*.sql")}
        declarations = DbtProject.from_directory(root).declarations()
        names = {m.name for m in declarations.models}
        assert "fct_costs" in names
        assert "from_outside" not in names
        # The two comparisons below pin the reader to this walk's descent. A
        # reader that walks another way, and contains what it reaches, fails
        # them too: read that failure as the walk having changed, not as a
        # file read from outside the root, which the line above refuses.
        assert ("from_kept" in names) == ("from_kept.sql" in walked)
        noted = any("out_link" in note and "resolves outside the project root" in note
                    for note in declarations.notes)
        assert noted == ("from_outside.sql" in walked)


def a_tree_with_a_directory_either_side_of_the_root(tmp_path):
    """The analytics tree under `project`, a directory `outside` beside it and
    a directory `kept` inside it, each holding one model no model path names.
    Returns the root and the two directories."""

    root = tmp_path / "project"
    for path, text in an_analytics_tree().items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "from_outside.sql").write_text("select 1\n", encoding="utf-8")
    kept = root / "kept"
    kept.mkdir()
    (kept / "from_kept.sql").write_text("select 2\n", encoding="utf-8")
    return root, outside, kept


def file_link(target, link) -> None:
    """A file symlink. Windows refuses one without the privilege, and has no
    junction for a file, so there the test is skipped and the directory
    link's test, which a junction serves, is the one that runs."""

    try:
        os.symlink(target, link)
    except OSError as exc:
        pytest.skip(f"a file symlink was refused here ({exc.strerror})")


def directory_link(target, link) -> None:
    """A directory symlink, or on Windows without the privilege a junction,
    which needs none. A platform that allows neither skips the test."""

    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError:
        if os.name != "nt":
            pytest.skip("this platform refused a directory symlink")
    try:
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, OSError) as exc:
        pytest.skip(f"neither a symlink nor a junction could be made here ({exc})")


ROOT_NOTE = (
    "model-paths entry {entry!r} names the project root, as dbt reads "
    "model-paths relative to the directory holding dbt_project.yml; this "
    "reader does not route the project root, so the entry is dropped"
)
DEFAULT_NOTE = (
    "model-paths lists no usable entry; the default model paths "
    "['models'] are used"
)


def a_tree_with_models_at_root_models_and_src(paths: str) -> dict[str, str]:
    """One model at the project root, one under ``models/`` and one under
    ``src/``, with ``model-paths`` set to the flow list ``paths``."""

    return {
        "dbt_project.yml": f"name: analytics\nmodel-paths: {paths}\n",
        "stg_root.sql": "select 1 as id\n",
        "models/stg_models.sql": "select 2 as id\n",
        "src/stg_src.sql": "select 3 as id\n",
    }


class TestTheProjectRootEntry:
    """``model-paths: ['.']`` names the project root to dbt. This reader
    does not route the root, whose walk would read ``dbt_project.yml``,
    ``target/`` and ``dbt_packages/``: it drops the entry with a note that
    says so, and falls back to ``models`` when nothing else is left. The
    ``['src']`` case is the control: a named directory routes its own model
    and draws no ``model-paths`` note."""

    CASES = (
        ("['.']", ["stg_models"], [ROOT_NOTE.format(entry="."), DEFAULT_NOTE]),
        ("['./']", ["stg_models"], [ROOT_NOTE.format(entry="./"), DEFAULT_NOTE]),
        ("['.', 'models']", ["stg_models"], [ROOT_NOTE.format(entry=".")]),
        ("['src']", ["stg_src"], []),
    )

    @staticmethod
    def read(declarations) -> tuple[list[str], list[str]]:
        return (
            sorted(m.name for m in declarations.models),
            [note for note in declarations.notes if "model-paths" in note],
        )

    @pytest.mark.parametrize(("paths", "models", "notes"), CASES)
    def test_in_memory(self, paths, models, notes):
        tree = a_tree_with_models_at_root_models_and_src(paths)
        assert self.read(DbtProject(tree).declarations()) == (models, notes)

    @pytest.mark.parametrize(("paths", "models", "notes"), CASES)
    def test_on_disk(self, tmp_path, paths, models, notes):
        tree = a_tree_with_models_at_root_models_and_src(paths)
        for path, text in tree.items():
            target = tmp_path / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        from_disk = DbtProject.from_directory(tmp_path).declarations()
        assert self.read(from_disk) == (models, notes)
        assert from_disk == DbtProject(tree).declarations()

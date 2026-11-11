# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""A project whose source of truth is a dbt file tree.

The second format, and the reason the seam is a seam: with one format the
tiered protocol describes one implementation, and the conformance suite
discriminates between no two formats. The schema-test vocabulary is the
input format of the parsers in ``declarations.py``, so most of what a dbt
project declares is read there - what this module adds is the tree walk and
the SQL side.

**The core takes plain data.** :class:`DbtProject` is constructed from a
mapping of relative paths to file text, so it needs neither a filesystem nor
dbt itself to build or to test. :meth:`DbtProject.from_directory` is the thin
convenience that reads a real tree, and it is the only thing here that
touches a disk. Same split as the Dagster reduction, for the same reason: the
suite runs against fixtures, not against an installation.

Three decisions here are deliberate, each stated rather than absorbed:

**References are extracted, not evaluated.** ``ref()`` and ``source()`` are
found by regex over the SQL text - no Jinja engine, no dbt dependency
(``pyproject.toml`` declares none, and says why a coupling is declared only
where code has it). An expression a regex cannot read yields a missing edge,
never a guessed one, and evaluation arrives only if a real project
demonstrates the need.

**Freshness is NOT_APPLICABLE, about this reduction rather than about dbt.**
dbt does compile an artifact (``target/manifest.json``) that could be fresh
or stale - but this reduction deliberately does not read it, so freshness of
an artifact it never consulted would be a claim nobody checked. The tri-state
describes the reduction that ran: this one reads source files directly and
has nothing to fall out of date with. A manifest-reading tier would own the
other two answers.

**``read_by`` is derived, never declared.** In the schema-test vocabulary the
Dagster reduction reads, source attribution is declared by keying the input;
in dbt the truth is better than a declaration - a model that reads a source
says so in its own SQL. So ``read_by`` comes from ``source()`` extraction,
and the "sources declared as read by models that do not exist" note the
Dagster reduction needs has no dbt equivalent: a derived reader always
exists.

Everything else is the tier-1 behavioural contract: nothing raises on bad
input. A malformed file, a missing ``dbt_project.yml``, a duplicate model
name - each becomes a note and the reduction keeps describing the rest,
because a read path that refuses a project over one bad file turns an
authoring typo into an outage.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import yaml

from .declarations import (
    parse_declarations,
    parse_semantics,
    parse_source_declarations,
)
from .model import (
    Fingerprint,
    Freshness,
    ProjectDeclarations,
    ProjectModel,
    dangling_declaration_names,
    layered_fingerprint,
)

__all__ = ["DbtProject"]

# Two-argument ref('package', 'model') names the model second; the model name
# is the last string either way. No Jinja evaluation - see the module
# docstring for why that is a decision and not a shortcut.
#
# What the patterns deliberately cover, because dbt renders Jinja before SQL
# is parsed: a call inside a SQL comment (`-- {{ ref('x') }}`) still executes
# at render time and IS a real dependency, so it matches here too. A Jinja
# comment (`{# ... #}`) is the one thing the renderer never evaluates, so
# those are stripped before extraction. Quotes must match pairwise
# (backreference), whitespace may follow the call name, a trailing
# version/v keyword on ref() is dbt >=1.5 model versioning, and source()
# accepts its documented keyword form.
_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
_REF_CALL = re.compile(
    r"\bref\s*\(\s*(['\"])([^'\"]+)\1"
    r"(?:\s*,\s*(['\"])([^'\"]+)\3)?"
    r"(?:\s*,\s*(?:v|version)\s*=\s*[^)]+?)?"
    r"\s*\)"
)
_SOURCE_CALL = re.compile(
    r"\bsource\s*\(\s*(?:source_name\s*=\s*)?(['\"])([^'\"]+)\1"
    r"\s*,\s*(?:table_name\s*=\s*)?(['\"])([^'\"]+)\3\s*\)"
)

_FALLBACK_NAME = "unnamed"
_DEFAULT_MODEL_PATHS = ("models",)


class DbtProject:
    """A dbt file tree, read as a project. Tiers 1 and 2, and not 3 - yet.

    Unlike the Dagster reduction, this format's source of truth is files
    that can genuinely receive an edit, which is what makes it the write
    path's first real target *later*. ``propose_edits`` stays absent until
    that work exists, so ``tier_of`` answers 2 honestly instead of a stub
    answering 3 falsely.
    """

    format = "dbt"

    def __init__(self, files: Mapping[str, str]) -> None:
        # Keys are relative paths; normalized to forward slashes so a tree
        # built on Windows and one built by from_directory read identically.
        self._files = {path.replace("\\", "/"): text for path, text in files.items()}
        # Degradations from_directory hit before a file could reach the tree
        # (an unreadable file has no text to carry); surfaced by declarations().
        self._walk_notes: tuple[str, ...] = ()

    # -- tier 1 ---------------------------------------------------------------

    def declarations(self) -> ProjectDeclarations:
        """What the tree declares. Never raises - see the module docstring."""

        notes: list[str] = list(self._walk_notes)
        name, model_paths = self._project_header(notes)

        sql_files, declaration_texts, semantic_texts, source_texts = self._route(
            model_paths, notes
        )

        models, kept_sql = self._models_from_sql(sql_files, model_paths, notes)

        keys, joins, parse_notes = parse_declarations(declaration_texts)
        notes.extend(parse_notes)
        semantic_models, metrics, semantic_notes = parse_semantics(semantic_texts)
        notes.extend(semantic_notes)
        declared_sources, source_notes = parse_source_declarations(source_texts)
        notes.extend(source_notes)

        # read_by is derived from the SQL, replacing the file-path attribution
        # the parser records. Matching is by (system, table): a source() call
        # names no schema - dbt resolves that from the declaration - so a
        # reader of an ambiguous pair attributes to every declaration of it.
        # Only kept models' files are harvested: a duplicate-stem loser's SQL
        # never ships, so a read stated only there must not attribute to the
        # surviving model whose own SQL says no such thing.
        readers = self._readers_by_table(kept_sql)
        sources = tuple(
            replace(
                source,
                read_by=tuple(sorted(readers.get((source.system, source.table), ()))),
            )
            for source in declared_sources
        )

        # An unresolved source() read - no declaration covers the (system,
        # table) it names - surfaces twice, deliberately. As a note, because
        # the reduction degraded (the read's schema/columns half is lost with
        # the missing declaration). And as a lineage edge on the reading
        # model, by bare table name: the SQL states the read, so dropping it
        # entirely would hide the flagship "graph reads something nothing
        # declares" contradiction in exactly this format - the dagster
        # reduction surfaces the same class as a depends_on entry, and parity
        # is the findings layer's stated test. The table name (not
        # system.table) is used because it is the name the coverage rule and
        # the dagster class share.
        declared_pairs = {(s.system, s.table) for s in declared_sources}
        unresolved_by_model: dict[str, set[str]] = {}
        for system, table in sorted(set(readers) - declared_pairs):
            reading = sorted(readers[(system, table)])
            notes.append(
                f"read via source({system!r}, {table!r}) by "
                + ", ".join(reading)
                + ", but no declaration covers that table"
            )
            for stem in reading:
                unresolved_by_model.setdefault(stem, set()).add(table)
        if unresolved_by_model:
            models = tuple(
                replace(
                    model,
                    depends_on=tuple(
                        sorted(set(model.depends_on) | unresolved_by_model[model.name])
                    ),
                )
                if model.name in unresolved_by_model
                else model
                for model in models
            )

        # The shared predicate - the dangling rule is model.py's decision,
        # made once for this note and the findings layer alike.
        known = {m.name for m in models}
        dangling = dangling_declaration_names(keys, joins, known)
        if dangling:
            notes.append(
                "declared for models the project does not define: "
                + ", ".join(dangling)
            )

        return ProjectDeclarations(
            format=self.format,
            name=name,
            models=models,
            sources=sources,
            declared_keys=tuple(keys),
            declared_joins=tuple(joins),
            semantic_models=tuple(semantic_models),
            metrics=tuple(metrics),
            freshness=Freshness.NOT_APPLICABLE,
            notes=tuple(notes),
        )

    # -- tier 2 ---------------------------------------------------------------

    def fingerprint(self) -> Fingerprint:
        """The house fingerprint - the same shared symbol the Dagster
        reduction uses, so the two formats cannot drift on what a layer's
        hash covers."""

        declared = self.declarations()
        return layered_fingerprint(declared.models, declared.sources)

    # -- construction ---------------------------------------------------------

    @classmethod
    def from_directory(cls, root: str | Path) -> DbtProject:
        """Read a real dbt tree into the plain-data core.

        Collects ``dbt_project.yml`` and every ``.sql``/``.yml``/``.yaml``
        under the project's model paths. Unreadable project files degrade the
        same way everything else does: the walk falls back to the default
        model path and the reduction notes what it could not read.
        """

        root = Path(root)
        files: dict[str, str] = {}
        walk_notes: list[str] = []

        def read_into(relative: str, found: Path) -> None:
            try:
                files[relative] = found.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                walk_notes.append(
                    f"file {relative!r} could not be read "
                    f"({exc.__class__.__name__}); skipped"
                )

        project_file = root / "dbt_project.yml"
        if project_file.is_file():
            read_into("dbt_project.yml", project_file)

        for model_path in _model_paths_of(files.get("dbt_project.yml")):
            base = root / model_path
            if not base.is_dir():
                continue
            for found in sorted(base.rglob("*")):
                # name.endswith, not Path.suffix: a file named exactly `.sql`
                # has an empty suffix, and skipping it here while the in-memory
                # walk sees it would make disk and memory trees reduce apart.
                if found.name.endswith((".sql", ".yml", ".yaml")) and found.is_file():
                    read_into(found.relative_to(root).as_posix(), found)

        project = cls(files)
        project._walk_notes = tuple(walk_notes)
        return project

    # -- the walk, in pieces --------------------------------------------------

    def _project_header(self, notes: list[str]) -> tuple[str, tuple[str, ...]]:
        text = self._files.get("dbt_project.yml")
        if text is None:
            notes.append(
                "no dbt_project.yml in the tree; the project is described "
                f"under the fallback name {_FALLBACK_NAME!r}"
            )
            return _FALLBACK_NAME, _DEFAULT_MODEL_PATHS
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            notes.append(
                "dbt_project.yml is not readable YAML "
                f"({exc.__class__.__name__}); the project is described under "
                f"the fallback name {_FALLBACK_NAME!r}"
            )
            return _FALLBACK_NAME, _DEFAULT_MODEL_PATHS
        if not isinstance(document, dict):
            notes.append(
                "dbt_project.yml is not a mapping; the project is described "
                f"under the fallback name {_FALLBACK_NAME!r} with the default "
                "model paths"
            )
            return _FALLBACK_NAME, _DEFAULT_MODEL_PATHS
        name = document.get("name")
        if not isinstance(name, str) or not name:
            notes.append(
                "dbt_project.yml declares no project name; the fallback "
                f"name {_FALLBACK_NAME!r} is used"
            )
            name = _FALLBACK_NAME
        model_paths, path_notes = _normalized_model_paths(document)
        notes.extend(path_notes)
        return name, model_paths

    def _route(
        self, model_paths: tuple[str, ...], notes: list[str]
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
        """Sort the tree's files into the parsers' channels by content.

        A dbt schema file may carry any of the vocabularies in one document -
        ``models:`` beside ``sources:`` - so routing is by top-level key,
        and one file can feed more than one parser. A file that cannot be
        read at all is noted once, here, and reaches no parser.
        """

        sql_files: dict[str, str] = {}
        declaration_texts: dict[str, str] = {}
        semantic_texts: dict[str, str] = {}
        source_texts: dict[str, str] = {}

        for path in sorted(self._files):
            if not any(path.startswith(f"{base}/") for base in model_paths):
                continue
            text = self._files[path]
            if path.endswith(".sql"):
                sql_files[path] = text
                continue
            if not path.endswith((".yml", ".yaml")):
                continue
            try:
                document = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                notes.append(
                    f"schema file {path!r} is not readable YAML "
                    f"({exc.__class__.__name__}); skipped"
                )
                continue
            if not isinstance(document, dict):
                notes.append(
                    f"schema file {path!r} is not a mapping; skipped"
                )
                continue
            routed = False
            if "models" in document:
                declaration_texts[path] = text
                routed = True
            if "sources" in document:
                source_texts[path] = text
                routed = True
            if "semantic_models" in document or "metrics" in document:
                semantic_texts[path] = text
                routed = True
            if not routed:
                notes.append(
                    f"schema file {path!r} declares none of the vocabularies "
                    "this reduction reads "
                    "(models/sources/semantic_models/metrics); skipped"
                )

        return sql_files, declaration_texts, semantic_texts, source_texts

    def _models_from_sql(
        self,
        sql_files: dict[str, str],
        model_paths: tuple[str, ...],
        notes: list[str],
    ) -> tuple[tuple[ProjectModel, ...], dict[str, str]]:
        """One model per SQL file: name from the stem, dependencies from
        ``ref()``, layer from the first directory under the model path.

        dbt itself refuses duplicate model names at compile time; a read
        path cannot, so a duplicate keeps the first file in path order and
        says so - the same converge-and-note posture the parsers take.
        Returns the models plus the kept path -> stem mapping, so read
        attribution can harvest exactly the SQL that ships and nothing a
        dropped duplicate stated.
        """

        by_name: dict[str, ProjectModel] = {}
        kept: dict[str, str] = {}
        for path in sorted(sql_files):
            stem = path.rsplit("/", 1)[-1].removesuffix(".sql")
            if not stem:
                notes.append(
                    f"file {path!r} has no name before its extension, so no "
                    "model name; skipped"
                )
                continue
            if stem in by_name:
                notes.append(
                    f"two files reduce to the model name {stem!r}; the first "
                    "in path order wins"
                )
                continue
            text = _JINJA_COMMENT.sub("", sql_files[path])
            refs = {
                m.group(4) or m.group(2) for m in _REF_CALL.finditer(text)
            }
            by_name[stem] = ProjectModel(
                name=stem,
                depends_on=tuple(sorted(refs)),
                layer=_layer_of(path, model_paths),
            )
            kept[path] = stem
        return tuple(sorted(by_name.values(), key=lambda m: m.name)), kept

    def _readers_by_table(
        self, kept_sql: dict[str, str]
    ) -> dict[tuple[str, str], set[str]]:
        readers: dict[tuple[str, str], set[str]] = {}
        for path, stem in kept_sql.items():
            text = _JINJA_COMMENT.sub("", self._files[path])
            for match in _SOURCE_CALL.finditer(text):
                readers.setdefault((match.group(2), match.group(4)), set()).add(stem)
        return readers


def _layer_of(path: str, model_paths: tuple[str, ...]) -> str | None:
    for base in model_paths:
        prefix = f"{base}/"
        if path.startswith(prefix):
            remainder = path.removeprefix(prefix)
            if "/" in remainder:
                return remainder.split("/", 1)[0]
            return None
    return None


def _normalized_model_paths(document: dict) -> tuple[tuple[str, ...], list[str]]:
    """The one reading of ``model-paths``, shared by the header parse and the
    disk walk so the two cannot decide differently.

    dbt tolerates the spellings authors actually write - ``models/``,
    ``./models`` - so they normalize rather than silently matching nothing
    (routing compares ``startswith(f"{base}/")``, which a trailing slash or
    dot-segment defeats). An entry that is not a plain relative path is
    dropped with a note, and a list that yields nothing usable falls back to
    the default with a note: a typo'd header must not empty a populated
    project unexplained.
    """

    notes: list[str] = []
    paths = document.get("model-paths")
    if paths is None:
        return _DEFAULT_MODEL_PATHS, notes
    if not isinstance(paths, list):
        notes.append(
            "dbt_project.yml's model-paths is not a list; the default "
            f"model paths {list(_DEFAULT_MODEL_PATHS)} are used"
        )
        return _DEFAULT_MODEL_PATHS, notes

    normalized: list[str] = []
    for entry in paths:
        if not isinstance(entry, str) or not entry.strip():
            notes.append(
                f"model-paths entry {entry!r} is not a path; dropped"
            )
            continue
        path = entry.strip().replace("\\", "/")
        if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
            notes.append(
                f"model-paths entry {entry!r} is absolute; dropped"
            )
            continue
        while path.startswith("./"):
            path = path[2:]
        path = path.rstrip("/")
        if path:
            normalized.append(path)
        else:
            notes.append(
                f"model-paths entry {entry!r} names no directory; dropped"
            )
    if not normalized:
        notes.append(
            "model-paths lists no usable entry; the default model paths "
            f"{list(_DEFAULT_MODEL_PATHS)} are used"
        )
        return _DEFAULT_MODEL_PATHS, notes
    return tuple(normalized), notes


def _model_paths_of(project_text: str | None) -> tuple[str, ...]:
    """The disk walk's view of model-paths: same decision, notes dropped -
    every note here re-derives in ``declarations()`` from the same header."""

    if project_text is None:
        return _DEFAULT_MODEL_PATHS
    try:
        document = yaml.safe_load(project_text)
    except yaml.YAMLError:
        return _DEFAULT_MODEL_PATHS
    if not isinstance(document, dict):
        return _DEFAULT_MODEL_PATHS
    paths, _ = _normalized_model_paths(document)
    return paths

# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""A project whose source of truth is an orchestrated asset graph.

This implements tiers 1 and 2 and deliberately not tier 3. The reason is
structural rather than a preference: the source of truth is the Python that
builds the graph, so an edit written back into this project's reduction would
be an edit to something regenerated from elsewhere - overwritten on the next
run, and misleading in review in the meantime.

**The core takes plain data.** :class:`DagsterProject` is constructed from
models and declaration text, so it needs neither an orchestrator nor an engine
to build or to test. :meth:`DagsterProject.from_asset_graph` is the thin
convenience that reduces a live graph. It reads the graph by shape and
imports no orchestrator, so importing this module costs nothing.

That split is not tidiness. It is what makes the reduction testable against
fixtures rather than against a running deployment, and it is why the conformance
suite can be run by someone who has neither.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

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
    unknown_reader_names,
)


class _AssetKey(Protocol):
    """The one attribute of an orchestrator key the reduction reads: its path,
    whose last segment is the model name."""

    @property
    def path(self) -> Sequence[str]: ...


class _AssetDefinition(Protocol):
    """What :meth:`DagsterProject.from_asset_graph` requires of a definition.

    Three attributes, named structurally, so the reduction is type-checkable
    without the orchestrator being installed or even importable. Dagster's
    ``AssetsDefinition`` satisfies it; nothing here has to say so. Deliberately
    not exported: it documents what this one method reads, not a contract this
    package asks anyone to implement.
    """

    @property
    def keys(self) -> Iterable[_AssetKey]: ...

    @property
    def asset_deps(self) -> Mapping[_AssetKey, Iterable[_AssetKey]]: ...

    @property
    def metadata_by_key(self) -> Mapping[_AssetKey, Mapping[str, Any] | None]: ...


__all__ = ["DagsterProject"]


class DagsterProject:
    """An asset graph, read as a project.

    Reaches tier 2 (:class:`~.protocol.FingerprintedProject`) and stops there.
    ``propose_edits`` is absent rather than present-and-refusing, so
    ``isinstance(project, EditableProject)`` is False and a caller finds out by
    asking rather than by receiving an empty result that looks like success.
    """

    format = "dagster"

    def __init__(
        self,
        models: Sequence[ProjectModel],
        *,
        name: str = "asset_graph",
        declaration_sources: Mapping[str, str] | None = None,
        semantic_sources: Mapping[str, str] | None = None,
        source_declarations: Mapping[str, str] | None = None,
    ) -> None:
        # The constructor refuses what from_asset_graph refuses, casefold
        # included: two models reducing to one name collide the moment
        # anything keys by it, and the filesystem hazard behind the casefold
        # does not care how the project was constructed. A conflict is an
        # error at the site that made it, never a diff-time surprise.
        ordered = tuple(sorted(models, key=lambda m: m.name))
        seen: dict[str, str] = {}
        for model in ordered:
            folded = model.name.casefold()
            if folded in seen:
                raise ValueError(
                    "two models reduce to the same name: "
                    f"{seen[folded]!r} and {model.name!r}"
                )
            seen[folded] = model.name
        self._models = ordered
        self._name = name
        self._declaration_sources = dict(declaration_sources or {})
        self._semantic_sources = dict(semantic_sources or {})
        # Keyed by the model that reads the declared tables, not by file path -
        # see parse_source_declarations. A graph cannot supply this: a model
        # that reads a warehouse table in its own SQL draws no edge, so the
        # read is invisible to the orchestrator and has to be declared.
        self._source_declarations = dict(source_declarations or {})

    # -- tier 1 ---------------------------------------------------------------

    def declarations(self) -> ProjectDeclarations:
        """What the graph and its hand-written declarations state.

        Never raises. A malformed declaration file becomes a note and is
        skipped; an empty project returns empty declarations. Both are ordinary
        states on a read path, and turning either into an exception would make a
        warehouse with no project unexplorable.

        Declarations naming a model the graph does not build are kept, with a
        note. They are a real statement by the author, and dropping them here
        would hide the far more likely cause - a renamed or removed asset - by
        making the declaration silently disappear along with it.
        """

        keys, joins, notes = parse_declarations(self._declaration_sources)
        semantic_models, metrics, semantic_notes = parse_semantics(self._semantic_sources)
        notes.extend(semantic_notes)
        sources, source_notes = parse_source_declarations(self._source_declarations)
        notes.extend(source_notes)

        # The shared predicates: what counts as dangling is decided once, in
        # model.py, for this note AND the findings layer, so the two cannot
        # disagree about a join that dangles only on its to-side.
        known = {m.name for m in self._models}
        dangling = dangling_declaration_names(keys, joins, known)
        if dangling:
            notes.append(
                "declared for models the graph does not build: "
                + ", ".join(dangling)
            )

        # A source attributed to a model that does not exist is kept for the
        # same reason a dangling key is: the table is still a real dependency of
        # this project on the warehouse, and dropping it would take a live
        # contract out of the picture along with the stale attribution. Named
        # separately from the keys above because the cause differs - a renamed
        # reader, not a renamed subject.
        unread = unknown_reader_names(sources, known)
        if unread:
            notes.append(
                "sources declared as read by models the graph does not build: "
                + ", ".join(unread)
            )

        return ProjectDeclarations(
            format=self.format,
            name=self._name,
            models=self._models,
            sources=tuple(sources),
            declared_keys=tuple(keys),
            declared_joins=tuple(joins),
            semantic_models=tuple(semantic_models),
            metrics=tuple(metrics),
            # There is no compiled artifact between the graph and this
            # reduction, so there is nothing that can fall out of date with it.
            # Reporting FRESH here would be a claim nobody checked.
            freshness=Freshness.NOT_APPLICABLE,
            notes=tuple(notes),
        )

    # -- tier 2 ---------------------------------------------------------------

    def fingerprint(self) -> Fingerprint:
        """The house fingerprint over this graph's models and declared sources.

        Every decision - dependencies in the hash, ``"unassigned"`` for
        layerless models, ``"sources"`` schema-included and omitted when
        empty - lives in :func:`~crosslink.model.layered_fingerprint`, once,
        beside the type it produces; a second format shares the symbol
        rather than a prose promise to compute it the same way.
        """

        sources, _ = parse_source_declarations(self._source_declarations)
        return layered_fingerprint(self._models, tuple(sources))

    # -- construction ---------------------------------------------------------

    @classmethod
    def from_asset_graph(
        cls,
        assets: Iterable[_AssetDefinition],
        *,
        name: str = "asset_graph",
        declaration_sources: Mapping[str, str] | None = None,
        semantic_sources: Mapping[str, str] | None = None,
        source_declarations: Mapping[str, str] | None = None,
    ) -> DagsterProject:
        """Reduce a live Dagster asset graph to a project.

        Reads only the orchestrator's public surface - ``keys``, ``asset_deps``,
        ``metadata_by_key`` - so nothing here depends on an internal module path
        that can move between releases. Held to the same standard this package
        asks of its own consumers.

        **Duplicates are detected against the raw definitions, never a built
        graph.** ``AssetGraph.from_assets`` collapses two definitions sharing a
        key into one node without complaint, so by the time a graph exists the
        collision is already invisible and a check against it can never fire.

        The comparison is case-folded because downstream consumers key models by
        name, and two names differing only in case collide the moment anything
        writes them to a case-insensitive filesystem - silently dropping one.

        A duplicate is an error rather than a note: one of the two models is
        about to disappear, and every declaration keyed by that name would then
        attach to whichever happened to survive.

        ``source_declarations`` is passed through untouched. Nothing about it
        can be read off ``assets`` - a model that reads a warehouse table in its
        own SQL has no dependency edge to find - so the reduction neither
        derives it nor validates it against the graph beyond noting a reader it
        does not build.
        """

        definitions = list(assets)

        flat_keys = [key.path[-1] for d in definitions for key in d.keys]
        seen: dict[str, str] = {}
        for model_name in flat_keys:
            folded = model_name.casefold()
            if folded in seen:
                raise ValueError(
                    f"two assets reduce to the same model name: "
                    f"{seen[folded]!r} and {model_name!r}"
                )
            seen[folded] = model_name

        models: list[ProjectModel] = []
        for definition in definitions:
            deps_by_key = definition.asset_deps
            metadata_by_key = definition.metadata_by_key
            for key in definition.keys:
                layer = (metadata_by_key.get(key) or {}).get("layer")
                models.append(
                    ProjectModel(
                        name=key.path[-1],
                        depends_on=tuple(
                            sorted(p.path[-1] for p in deps_by_key.get(key, ()))
                        ),
                        layer=str(layer).lower() if layer else None,
                    )
                )

        return cls(
            models,
            name=name,
            declaration_sources=declaration_sources,
            semantic_sources=semantic_sources,
            source_declarations=source_declarations,
        )

# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""What a project declares, in a vocabulary that is not dbt's.

This is the neutral model. It exists because the alternative - reusing the
model a dbt-shaped engine already has - quietly imports dbt's accidents along
with its substance, and a second project format then has to answer questions
that only make sense for the first one.

Four decisions here are deliberate departures, each one earned:

**A key is always a tuple of columns.** Not a column with a composite variant
bolted on beside it. A single-column grain is the ``n == 1`` case, never a
different kind of thing. Modelling it the other way around is what makes a
composite grain inexpressible until someone widens the type, and widening it
later means every reader has two shapes to handle forever.

**There is no project directory.** A project is identified by its format and
its name. A path is one format's way of locating itself, not a property every
project has, and putting it in the shared model makes every path-free format
carry a field it can only ever leave empty - or worse, populate with something
misleading to keep a consumer happy.

**Freshness is a tri-state, not a boolean.** See :class:`Freshness`. This is the
one easiest to get wrong: a boolean cannot distinguish "current" from
"there is no such thing here", so a format with no compiled artifact reports
itself indistinguishable from one that just compiled.

**A required field is a refusal to invent.** :class:`ExternalSource` requires a
source system, because the consumer requires one; making it optional here would
only move the invention into the boundary code, where a fabricated value is
indistinguishable from a declared one. Where the consumer requires something a
project genuinely may not have - a file path - the field is optional here and
the loss is reported rather than filled in.
"""

from __future__ import annotations

import hashlib
from collections.abc import Container, Iterable
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "DeclaredJoin",
    "DeclaredKey",
    "ExternalSource",
    "Fingerprint",
    "Freshness",
    "Metric",
    "ProjectDeclarations",
    "ProjectModel",
    "SemanticModel",
    "absent_join_sides",
    "dangling_declaration_names",
    "definition_hash",
    "layered_fingerprint",
    "source_identity",
    "source_sort_key",
    "unknown_reader_names",
]


def definition_hash(text: str) -> str:
    """The content hash used throughout. Ours, so nothing here depends on a
    particular engine's hashing choice remaining what it is today."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Freshness(str, Enum):
    """Whether a derived artifact still describes the project it came from.

    ``NOT_APPLICABLE`` is the member that justifies this being an enum rather
    than a ``bool``. A format that compiles to an intermediate artifact can be
    ``FRESH`` or ``STALE``; a format that reduces its source graph directly has
    no such artifact and is neither. Collapsing that third case into ``False``
    makes "nothing to be stale about" report identically to "checked, and it is
    current" - which reads as an assurance nobody actually made.

    The same shape, in the other direction, is what makes a cache served past
    its window look like a healthy one.
    """

    FRESH = "fresh"
    STALE = "stale"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class ProjectModel:
    """One node the project builds, and what it reads to build it.

    ``relation`` is the physical table when the project knows it, and ``None``
    when it does not. Absence is honest here: a format that never resolves
    physical names should say so rather than guessing one from the model name,
    because a guessed relation is indistinguishable from a declared one at the
    point it is consumed.
    """

    name: str
    depends_on: tuple[str, ...] = ()
    relation: str | None = None
    layer: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("a model needs a name")


@dataclass(frozen=True)
class ExternalSource:
    """A warehouse object the project reads but does not build.

    The project's outer edge. Everything in ``models`` is something the project
    produces; this is the boundary where it stops and depends on something
    somebody else keeps honoring.

    **Why this cannot be derived from the graph.** An orchestrated graph knows
    its own nodes and the edges between them. A node that reads a warehouse
    table directly - in SQL inside its body, because the source system has no
    other interface - has no edge to draw, so the read is invisible to any
    amount of graph traversal. It is genuinely extra information, and it has to
    be declared. A format that inferred sources from dependencies would report
    none of them and look like it had checked.

    ``system`` is the source system this table belongs to, and it is
    **required**. That is a deliberate refusal: the consumer requires it too, so
    making it optional here would only move the moment of invention one layer
    down, into the boundary code, where it would be a fabricated value nobody
    could tell from a declared one. If a format does not know its source
    systems, the honest outcome is that it declares no sources.

    ``read_by`` names the models that read this table. It lives here rather than
    in a separate mapping so that two models declaring the same table converge
    on one source with two readers, instead of two sources that a downstream
    consumer would count - and report - twice.

    ``declared_in`` is optional provenance: where the declaration was written,
    when that is a place. It is optional precisely because a project need not
    have files, and requiring it would be the same mistake the paragraph above
    declines to make.
    """

    system: str
    table: str
    schema_name: str | None = None
    columns: tuple[str, ...] = ()
    read_by: tuple[str, ...] = ()
    declared_in: str | None = None

    def __post_init__(self) -> None:
        if not self.system:
            raise ValueError(f"external source {self.table!r} names no source system")
        if not self.table:
            raise ValueError("an external source needs a table name")

    @property
    def identifier(self) -> str:
        """``system.table`` - how a consumer names this source in a finding."""

        return f"{self.system}.{self.table}"


def source_identity(source: ExternalSource) -> tuple[str, str | None, str]:
    """What makes two source declarations the same source.

    ``(system, schema_name, table)`` - and not :attr:`ExternalSource.identifier`,
    which omits the schema: two real warehouse tables in different schemas
    would collapse into one. This is a shared symbol on purpose: the parser
    keys its convergence with it and the delta layer keys its diff with it, so
    the two definitions of "the same table" cannot drift apart - a wider
    identity lands here once, for both.
    """

    return (source.system, source.schema_name, source.table)


def source_sort_key(source: ExternalSource) -> tuple[str, bool, str, str]:
    """The one canonical order for a source collection, ``None``-safe.

    ``schema_name`` is ``str | None``, and comparing ``None`` with ``str`` is
    a ``TypeError`` - so the key spells out None-ness, and an unschema'd
    source never compares against a schema'd one. (None-first, then name) is a
    choice made once, here, for every producer and consumer that sorts
    sources; a second inline sort key is where the crash on valid input
    comes back.
    """

    return (source.system, source.schema_name is not None, source.schema_name or "", source.table)


def absent_join_sides(join: DeclaredJoin, known: Container[str]) -> tuple[str, ...]:
    """The sides of one declared join the project does not define - both of
    them, deduplicated (a self-join names one side), sorted.

    A shared symbol on purpose: a producer that checked ``from_model`` only,
    beside a findings layer that checks both sides, would have the notes
    channel and the findings channel disagree about one snapshot. The rule for
    "does this join dangle?" is decided here, once.
    """

    return tuple(
        sorted({side for side in (join.from_model, join.to_model) if side not in known})
    )


def dangling_declaration_names(
    declared_keys: Iterable[DeclaredKey],
    declared_joins: Iterable[DeclaredJoin],
    known: Container[str],
) -> tuple[str, ...]:
    """Every model name that keys or joins declare and the project does not
    define, sorted - the producers' note payload, built from the same per-item
    rules the findings layer applies, so the two surfaces cannot drift.
    """

    return tuple(
        sorted(
            {k.model for k in declared_keys if k.model not in known}
            | {side for j in declared_joins for side in absent_join_sides(j, known)}
        )
    )


def unknown_reader_names(
    sources: Iterable[ExternalSource], known: Container[str]
) -> tuple[str, ...]:
    """Every reader a source attributes that the project does not define,
    sorted - the same membership rule the findings layer's stale-reader kind
    applies, shared for the same reason as the predicates above.
    """

    return tuple(
        sorted({reader for s in sources for reader in s.read_by if reader not in known})
    )


@dataclass(frozen=True)
class DeclaredKey:
    """The grain a model is declared to be unique at.

    ``columns`` is ordered and non-empty. Order is preserved because it is the
    author's statement of the key, and reordering it silently would make two
    declarations that a human wrote differently compare equal.
    """

    model: str
    columns: tuple[str, ...]
    source: str = "declaration"

    def __post_init__(self) -> None:
        if not self.columns:
            raise ValueError(f"declared key for {self.model!r} has no columns")

    @property
    def is_composite(self) -> bool:
        return len(self.columns) > 1


@dataclass(frozen=True)
class DeclaredJoin:
    """A declared relationship between two models.

    Both sides are column tuples for the same reason keys are: a join on a
    composite key is not a different kind of join.
    """

    from_model: str
    from_columns: tuple[str, ...]
    to_model: str
    to_columns: tuple[str, ...]
    source: str = "declaration"

    def __post_init__(self) -> None:
        if not self.from_columns or not self.to_columns:
            raise ValueError(f"join {self.from_model}->{self.to_model} is missing columns")
        if len(self.from_columns) != len(self.to_columns):
            raise ValueError(
                f"join {self.from_model}->{self.to_model} has "
                f"{len(self.from_columns)} columns on one side and "
                f"{len(self.to_columns)} on the other"
            )


@dataclass(frozen=True)
class SemanticModel:
    """A semantic model: the dimensions and measures declared over one model."""

    name: str
    model: str
    dimensions: tuple[str, ...] = ()
    measures: tuple[str, ...] = ()
    definition_sha: str = ""


@dataclass(frozen=True)
class Metric:
    """A metric declared over a measure."""

    name: str
    measure: str | None = None
    kind: str = "simple"
    definition_sha: str = ""


@dataclass(frozen=True)
class Fingerprint:
    """A project's content fingerprint, per layer.

    ``layers`` maps a layer name to a hash over that layer's contents. What
    counts as a layer is the format's business - a medallion tier, a directory,
    a package - because the engine comparing two fingerprints only needs them
    to be computed the same way twice, not to agree with another format.

    Per layer rather than one hash for the whole project, because a single hash
    answers "did anything change" and nothing else, and the useful question on
    a drift report is which part.
    """

    layers: dict[str, str] = field(default_factory=dict)
    models: tuple[str, ...] = ()

    def changed_layers(self, other: Fingerprint) -> tuple[str, ...]:
        """Layers whose hash differs, including ones added or removed.

        A layer present on one side and absent on the other counts as changed:
        that is a real difference, and treating a missing layer as "unchanged"
        is how a deleted one disappears from a drift report entirely.
        """

        names = set(self.layers) | set(other.layers)
        return tuple(
            sorted(n for n in names if self.layers.get(n) != other.layers.get(n))
        )


def layered_fingerprint(
    models: tuple[ProjectModel, ...], sources: tuple[ExternalSource, ...]
) -> Fingerprint:
    """The house fingerprint shape, shared so it is decided once.

    Nothing *requires* two formats to fingerprint alike - the contract only
    asks that each computes its own the same way twice - but every decision
    below is format-neutral, and a second inline copy is a drift channel:
    the two would agree until one was edited. The decisions, each visible in
    the hash:

    - Dependencies are part of a layer's hash, because a rewiring that moves
      no model between layers still changes what the layer computes.
    - Models with no layer group under ``"unassigned"`` rather than being
      dropped - a model outside every layer is exactly what a drift report
      should surface.
    - External sources hash under ``"sources"``, schema included (the same
      table name in another dataset is another warehouse object), and the
      entry is omitted entirely when no sources are declared, so a project
      that declares none fingerprints over its model layers alone, with no
      ``"sources"`` entry of its own.

    ``"sources"`` and ``"unassigned"`` are names a real layer could
    collide with. A model layer literally named ``"sources"`` gets its hash
    combined with the external-source hash - combined, not overwritten, so a
    change on either side still changes the entry. Models whose layer is
    literally ``"unassigned"`` group with the layerless; that one is
    indistinguishable by construction. The caveat travels with this function
    now, once.
    """

    models = tuple(models)
    by_layer: dict[str, list[ProjectModel]] = {}
    for model in models:
        by_layer.setdefault(model.layer or "unassigned", []).append(model)

    layers = {
        layer: definition_hash(
            "\n".join(
                f"{m.name}({','.join(m.depends_on)})"
                for m in sorted(members, key=lambda m: m.name)
            )
        )
        for layer, members in by_layer.items()
    }

    if sources:
        source_hash = definition_hash(
            "\n".join(
                f"{s.system}.{s.schema_name or ''}.{s.table}"
                for s in sorted(sources, key=source_sort_key)
            )
        )
        if "sources" in layers:
            source_hash = definition_hash(f"{layers['sources']}\n{source_hash}")
        layers["sources"] = source_hash

    return Fingerprint(layers=layers, models=tuple(m.name for m in models))


@dataclass(frozen=True)
class ProjectDeclarations:
    """Everything a project declares about itself, in one value.

    ``notes`` carries analyst-readable caveats. It is the one piece of the
    dbt-shaped model worth keeping verbatim: a consumer that degrades quietly
    still owes the reader a reason, and a note is how the reason travels
    without becoming an exception.
    """

    format: str
    name: str
    models: tuple[ProjectModel, ...] = ()
    sources: tuple[ExternalSource, ...] = ()
    declared_keys: tuple[DeclaredKey, ...] = ()
    declared_joins: tuple[DeclaredJoin, ...] = ()
    semantic_models: tuple[SemanticModel, ...] = ()
    metrics: tuple[Metric, ...] = ()
    freshness: Freshness = Freshness.NOT_APPLICABLE
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        """No declarations of any kind. The state every consumer must tolerate.

        Sources count. A project that builds nothing but names the warehouse
        objects it reads has still said something, and calling that empty would
        discard the only statement it made.
        """

        return not (
            self.models
            or self.sources
            or self.declared_keys
            or self.declared_joins
            or self.semantic_models
            or self.metrics
        )

    def model_names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.models)

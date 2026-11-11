# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""A typed delta between two declaration snapshots.

This is the delta of ADR-0003: what should be declared minus what is declared,
stated in the neutral model's own vocabulary before any patch exists. It is a
statement *about two* :class:`~crosslink.model.ProjectDeclarations` values, so
it lives beside the model rather than in it - the way the conformance suite
does - and it is deliberately independent of where either snapshot came from.

Five decisions here are deliberate, each stated rather than absorbed:

**The diff is order-insensitive across collections, and only there.** The
model's tuples are ordered because producers sort them, not because the types
promise anything - so a diff that read tuple order as meaning would report
phantom drift every time a producer re-sorted. Collections are compared by
identity instead. But order *within* a value - a key's columns, a join's
column lists, a model's ``depends_on`` - is the author's statement
(:class:`~crosslink.model.DeclaredKey` says so explicitly) and a permutation
there is a real change, named as that field.

**Apply emits the canonical order.** An order-insensitive delta cannot know
what order a producer wrote, so :meth:`Delta.apply_to` can only emit one
order: each collection sorted by its identity. :func:`canonical` makes that
form public, which is what lets the round-trip property be stated exactly -
``diff(C, D).apply_to(C) == canonical(D)`` - instead of hedged.

**A rename reads as drop-and-add.** Two snapshots record difference, not
intent: nothing in them says the model that vanished and the model that
appeared are the same one under a new name. ADR-0003 names this as the
vocabulary's known falsifier - an edit two snapshots cannot represent takes a
superseding record, not a workaround - so the limit is stated here and not
solved here.

**An identical restatement is one statement.** The parsers gather declarations
across files, and two files may legitimately state the same key - byte for
byte - twice. Everywhere this module indexes a collection (:func:`diff`,
:meth:`Delta.apply_to`, :func:`canonical`) such a restatement collapses:
repetition of one statement is not a contradiction, and an oracle that crashes
on real producer output cannot calibrate. The same identity declared with
*different* values stays a refusal - that snapshot contradicts itself, and
choosing a survivor would be invention.

**Freshness and notes are not declarations.** The delta ranges over the six
nouns a project declares - models, sources, keys, joins, semantic models,
metrics. ``freshness`` is a property of a reduction moment and ``notes`` are
consumer prose; two snapshots differing only there diff empty, and
:meth:`Delta.apply_to` carries the base's values through unchanged. The
round-trip property therefore holds over snapshots that agree on both - a
domain, stated rather than hidden.

Everything else is the house refusal to invent: a diff across two different
projects, a snapshot declaring the same identity twice with different values,
and a delta applied to a different project - or to a base whose values
contradict what the delta recorded - are all errors, never guesses.
"""

from __future__ import annotations

from dataclasses import dataclass, fields as dataclass_fields, is_dataclass, replace

from .model import (
    DeclaredJoin,
    DeclaredKey,
    ExternalSource,
    Metric,
    ProjectDeclarations,
    ProjectModel,
    SemanticModel,
    source_identity,
    source_sort_key,
)

__all__ = [
    "Changed",
    "Delta",
    "KeyedEdits",
    "SetEdits",
    "canonical",
    "diff",
]


# Identity: what makes a declaration the same declaration in both snapshots.
# Source identity and its canonical order are shared symbols
# (model.source_identity / model.source_sort_key): the parser converges and
# sorts with the same two functions this module diffs with, so the two
# layers' definitions of "the same table" cannot drift apart.
# Model identity is the EXACT name, deliberately: from_asset_graph refuses
# names that collide casefolded, but that is the dagster producer's
# write-safety rule (case-insensitive filesystems drop one of the pair on
# write), not a statement about identity in the neutral model. A tier-3 write
# path re-checks producer constraints before writing; the delta layer does
# not import them.
def _model_key(m: ProjectModel) -> tuple:
    return (m.name,)


def _semantic_key(s: SemanticModel) -> tuple:
    return (s.name,)


def _metric_key(m: Metric) -> tuple:
    return (m.name,)


# Sort keys: the canonical across-collection order. The source order lives in
# model.source_sort_key, beside the identity it orders.
def _key_sort_key(k: DeclaredKey) -> tuple:
    return (k.model, k.columns, k.source)


def _join_sort_key(j: DeclaredJoin) -> tuple:
    return (j.from_model, j.from_columns, j.to_model, j.to_columns, j.source)


@dataclass(frozen=True)
class Changed[T]:
    """One declaration present in both snapshots with a different value.

    ``fields`` names exactly the fields where ``before != after``, in the
    declaring dataclass's field order. It is the delta's answer to "what
    changed" at a granularity a drift report can act on - and it never
    special-cases a field: a reordered ``depends_on`` is a changed
    ``depends_on``, because order within a value is the author's statement.

    Both invariants are checked at construction, because a hand-built entry
    is the expected input path for a proposal: a ``Changed`` with no actual
    difference, or whose ``fields`` misstate the difference, is refused -
    the tuple is load-bearing in drift reports, and stored state nothing
    validates is a place a proposal can lie.
    """

    before: T
    after: T
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.before == self.after:
            raise ValueError("a changed entry needs a difference: before == after")
        derived = _changed_fields(self.before, self.after)
        if self.fields != derived:
            raise ValueError(
                f"a changed entry's fields must name exactly what differs: "
                f"stated {self.fields!r}, actual {derived!r}"
            )


@dataclass(frozen=True)
class KeyedEdits[T]:
    """Edits to a collection whose members carry an identity.

    Members present on one side only land in ``added`` or ``removed``; a
    member present on both sides with a different value is ``changed``. Used
    for the four nouns with a declared identity: models, sources, semantic
    models, metrics.
    """

    added: tuple[T, ...] = ()
    removed: tuple[T, ...] = ()
    changed: tuple[Changed[T], ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


@dataclass(frozen=True)
class SetEdits[T]:
    """Edits to a collection whose members ARE their identity.

    Declared keys and joins have no name apart from their content - the
    parser can emit several keys for one model, so "the key of model X" is an
    identity this model does not have and this module refuses to invent. A
    key with different columns is a different key: drop-and-add, with no
    ``changed`` bucket to pretend otherwise.
    """

    added: tuple[T, ...] = ()
    removed: tuple[T, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed)


@dataclass(frozen=True)
class Delta:
    """The difference between two declaration snapshots, noun for noun.

    Mirrors :class:`~crosslink.model.ProjectDeclarations` field for field so
    nothing about the shape has to be learned twice (a test holds the mirror
    to ``dataclasses.fields``, so a seventh noun cannot arrive unseen).
    ``is_empty`` means no *declaration* differs - a freshness or notes
    difference is deliberately not a delta (see the module docstring).

    ``format`` and ``name`` bind the delta to the one project it is a
    statement about - the same boundary :func:`diff` refuses to compare
    across. Without them an empty delta would apply to any project at all,
    and the round-trip check ADR-0003 rests on could pass vacuously against
    the wrong base.
    """

    format: str
    name: str
    models: KeyedEdits[ProjectModel] = KeyedEdits()
    sources: KeyedEdits[ExternalSource] = KeyedEdits()
    declared_keys: SetEdits[DeclaredKey] = SetEdits()
    declared_joins: SetEdits[DeclaredJoin] = SetEdits()
    semantic_models: KeyedEdits[SemanticModel] = KeyedEdits()
    metrics: KeyedEdits[Metric] = KeyedEdits()

    @property
    def is_empty(self) -> bool:
        return (
            self.models.is_empty
            and self.sources.is_empty
            and self.declared_keys.is_empty
            and self.declared_joins.is_empty
            and self.semantic_models.is_empty
            and self.metrics.is_empty
        )

    def apply_to(self, base: ProjectDeclarations) -> ProjectDeclarations:
        """The base snapshot with this delta applied, in canonical order.

        Refuses - with :class:`ValueError`, never a guess - when the base is
        visibly not the snapshot this delta was computed against: a different
        project's ``format`` or ``name``, an added identity already present,
        a removed or changed entry whose recorded value does not match what
        the base holds. Silent success there would make apply an inventor,
        and the round-trip property worthless. It also refuses delta shapes
        :func:`diff` can never emit: a changed entry migrating to a new
        identity (a rename is drop-and-add), and one identity named in more
        than one bucket (a value change is a changed entry with its audit
        trail, never a remove-and-add without one).

        The output's collections are canonically sorted (the delta cannot
        know a producer's order), and the base's ``freshness`` and ``notes``
        travel through unchanged: this delta does not range over them.
        """

        if (base.format, base.name) != (self.format, self.name):
            raise ValueError(
                f"cannot apply a delta computed for "
                f"{self.format!r}/{self.name!r} to "
                f"{base.format!r}/{base.name!r}: not the same project"
            )
        return replace(
            base,
            models=_apply_keyed(self.models, base.models, _model_key, _model_key, "model"),
            sources=_apply_keyed(
                self.sources, base.sources, source_identity, source_sort_key, "source"
            ),
            declared_keys=_apply_set(
                self.declared_keys, base.declared_keys, _key_sort_key, "declared key"
            ),
            declared_joins=_apply_set(
                self.declared_joins, base.declared_joins, _join_sort_key, "declared join"
            ),
            semantic_models=_apply_keyed(
                self.semantic_models, base.semantic_models, _semantic_key, _semantic_key,
                "semantic model",
            ),
            metrics=_apply_keyed(self.metrics, base.metrics, _metric_key, _metric_key, "metric"),
        )


def _changed_fields(before: object, after: object) -> tuple[str, ...]:
    # `dataclasses.fields` refuses a non-dataclass with a TypeError of its own;
    # the guard says the same thing in this module's words and is what lets the
    # type checker see a dataclass instance, not a bare object, in the walk.
    if not is_dataclass(before) or isinstance(before, type):
        raise TypeError("a changed entry compares two dataclass instances")
    return tuple(
        f.name
        for f in dataclass_fields(before)
        if getattr(before, f.name) != getattr(after, f.name)
    )


def _index(items: tuple, key, noun: str) -> dict:
    # An identical restatement collapses (one statement, stated twice); the
    # same identity with a different value is a self-contradiction and refuses.
    indexed: dict = {}
    for item in items:
        k = key(item)
        if k in indexed and indexed[k] != item:
            raise ValueError(
                f"snapshot declares {noun} {k!r} more than once, with different values"
            )
        indexed[k] = item
    return indexed


def _keyed_diff(left: tuple, right: tuple, key, sort_key, noun: str) -> KeyedEdits:
    # The Fingerprint.changed_layers shape: union of identities, compare via
    # .get, emit sorted - which is also what makes two equal diffs compare ==.
    before = _index(left, key, noun)
    after = _index(right, key, noun)
    added = sorted((after[k] for k in after.keys() - before.keys()), key=sort_key)
    removed = sorted((before[k] for k in before.keys() - after.keys()), key=sort_key)
    changed = sorted(
        (
            Changed(before[k], after[k], _changed_fields(before[k], after[k]))
            for k in before.keys() & after.keys()
            if before[k] != after[k]
        ),
        key=lambda c: sort_key(c.after),
    )
    return KeyedEdits(tuple(added), tuple(removed), tuple(changed))


def _set_diff(left: tuple, right: tuple, sort_key) -> SetEdits:
    # A set noun's members ARE their value, so a duplicate can only ever be
    # the same statement twice - it collapses, and there is no conflicting
    # case to refuse.
    before = frozenset(left)
    after = frozenset(right)
    return SetEdits(
        tuple(sorted(after - before, key=sort_key)),
        tuple(sorted(before - after, key=sort_key)),
    )


def _apply_keyed(edits: KeyedEdits, base: tuple, key, sort_key, noun: str) -> tuple:
    current = _index(base, key, noun)
    removed_keys = {key(i) for i in edits.removed}
    changed_keys = {key(c.before) for c in edits.changed}
    added_keys = {key(i) for i in edits.added}
    colliding = (removed_keys & added_keys) | (changed_keys & (removed_keys | added_keys))
    if colliding:
        named = ", ".join(sorted(repr(k) for k in colliding))
        raise ValueError(
            f"delta names {noun} {named} in more than one bucket: a value "
            f"change is a changed entry, never a remove-and-add"
        )
    for item in edits.removed:
        k = key(item)
        if current.get(k) != item:
            raise ValueError(f"cannot remove {noun} {k!r}: the base does not hold that value")
        del current[k]
    for change in edits.changed:
        k = key(change.before)
        if key(change.after) != k:
            raise ValueError(
                f"cannot change {noun} {k!r} into {key(change.after)!r}: a "
                f"changed entry keeps its identity, a rename is drop-and-add"
            )
        if current.get(k) != change.before:
            raise ValueError(f"cannot change {noun} {k!r}: the base does not hold the recorded before-value")
        current[k] = change.after
    for item in edits.added:
        k = key(item)
        if k in current:
            raise ValueError(f"cannot add {noun} {k!r}: already present in the base")
        current[k] = item
    return tuple(sorted(current.values(), key=sort_key))


def _apply_set(edits: SetEdits, base: tuple, sort_key, noun: str) -> tuple:
    both = set(edits.removed) & set(edits.added)
    if both:
        raise ValueError(
            f"delta lists the same {noun} as both removed and added: that is "
            f"a no-op stated as an edit"
        )
    current = set(base)
    for item in edits.removed:
        if item not in current:
            raise ValueError(f"cannot remove {noun} {item!r}: not present in the base")
        current.remove(item)
    for item in edits.added:
        if item in current:
            raise ValueError(f"cannot add {noun} {item!r}: already present in the base")
        current.add(item)
    return tuple(sorted(current, key=sort_key))


def _canonical_keyed(items: tuple, key, sort_key, noun: str) -> tuple:
    return tuple(sorted(_index(items, key, noun).values(), key=sort_key))


def canonical(snapshot: ProjectDeclarations) -> ProjectDeclarations:
    """The snapshot with each collection sorted by its identity.

    Holds the same identity discipline as :func:`diff` and
    :meth:`Delta.apply_to` - an identical restatement collapses, a
    conflicting duplicate identity refuses - because this is a standalone
    public entry point, and without that a duplicate-carrying snapshot would
    canonicalize order-dependently: two "canonical" representatives for one
    multiset, silently. Touches nothing else - not the values, not their
    inner tuples, not ``freshness`` or ``notes`` - and is idempotent. This is
    the one order :meth:`Delta.apply_to` can emit, made public so the
    round-trip property is statable exactly rather than "up to ordering".
    """

    return replace(
        snapshot,
        models=_canonical_keyed(snapshot.models, _model_key, _model_key, "model"),
        sources=_canonical_keyed(snapshot.sources, source_identity, source_sort_key, "source"),
        declared_keys=tuple(sorted(frozenset(snapshot.declared_keys), key=_key_sort_key)),
        declared_joins=tuple(sorted(frozenset(snapshot.declared_joins), key=_join_sort_key)),
        semantic_models=_canonical_keyed(
            snapshot.semantic_models, _semantic_key, _semantic_key, "semantic model"
        ),
        metrics=_canonical_keyed(snapshot.metrics, _metric_key, _metric_key, "metric"),
    )


def diff(left: ProjectDeclarations, right: ProjectDeclarations) -> Delta:
    """The typed delta from ``left`` to ``right``: ADR-0003's ``delta = D - C``.

    Permutation-invariant across every collection: producers sort, the types
    do not promise it, and a diff that read producer order as meaning would
    report phantom drift on every re-sort. Order *within* a value stays a
    real difference.

    Refuses to compare across projects: differing ``format`` or ``name`` is
    a :class:`ValueError`, because a delta between two different projects is
    an invented claim. ``freshness`` and ``notes`` are outside the delta's
    range - two snapshots differing only there diff empty.
    """

    if left.format != right.format:
        raise ValueError(
            f"cannot diff across formats: {left.format!r} != {right.format!r}"
        )
    if left.name != right.name:
        raise ValueError(
            f"cannot diff two different projects: {left.name!r} != {right.name!r}"
        )
    return Delta(
        format=left.format,
        name=left.name,
        models=_keyed_diff(left.models, right.models, _model_key, _model_key, "model"),
        sources=_keyed_diff(
            left.sources, right.sources, source_identity, source_sort_key, "source"
        ),
        declared_keys=_set_diff(left.declared_keys, right.declared_keys, _key_sort_key),
        declared_joins=_set_diff(
            left.declared_joins, right.declared_joins, _join_sort_key
        ),
        semantic_models=_keyed_diff(
            left.semantic_models, right.semantic_models, _semantic_key, _semantic_key,
            "semantic model",
        ),
        metrics=_keyed_diff(left.metrics, right.metrics, _metric_key, _metric_key, "metric"),
    )

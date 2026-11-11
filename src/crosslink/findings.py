# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Self-consistency findings: the project contradicting itself, computed.

Authority 1 of the desired-state fork, shipped alone on purpose. A finding
here is never an opinion about what the project *should* declare - it is a
claim that two of the project's own statements disagree: a dependency on
something nothing defines, a key declared for a model that does not exist, a
source attributed to a reader nobody built. Computed, not judged, defensible
to anyone - and a finding the project's owner rejects is treated as a bug in
this reduction, which is the property that makes the authority decidable and
this module falsifiable.

Every finding is computed from one :class:`~crosslink.model.ProjectDeclarations`
value and nothing else - no warehouse access, no orchestrator import, no
file tree. Format neutrality is not a feature here, it is the test: the same
inconsistency planted in any format's fixture yields the same finding,
because the finding never saw the format.

**A finding proposes the minimal edit that restores consistency in
declaration space - when that edit is statable without invention.** A
dangling key proposes its own removal; a stale reader proposes the corrected
attribution. The undeclared lineage root deliberately proposes nothing: the
consistent declaration would be an :class:`~crosslink.model.ExternalSource`,
and a source requires a system only a human knows - fabricating one to have
a proposal would move the invention into exactly the field whose required-ness
exists to refuse it. A finding without a proposal is still a finding; ADR-0003
says a proposal whose effect cannot be stated is not yet a proposal, and this
is that, stated.

The proposal is an offer, not a verdict. The minimal consistent edit removes
the stale statement; the *cause* is often a renamed model, whose real fix is
a rename the delta vocabulary reads as drop-and-add. Deciding which is
acceptance's job - merge/reject is the objective function, expressed by the
owner at review, never written down in advance by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .delta import Changed, Delta, KeyedEdits, SetEdits
from .model import ProjectDeclarations, absent_join_sides

__all__ = [
    "DANGLING_DECLARED_JOIN",
    "DANGLING_DECLARED_KEY",
    "Finding",
    "UNDECLARED_LINEAGE_ROOT",
    "UNKNOWN_READER",
    "findings",
]

UNDECLARED_LINEAGE_ROOT = "undeclared-lineage-root"
DANGLING_DECLARED_KEY = "dangling-declared-key"
DANGLING_DECLARED_JOIN = "dangling-declared-join"
UNKNOWN_READER = "unknown-reader"


@dataclass(frozen=True)
class Finding:
    """One self-contradiction, with its evidence and - where statable - the
    minimal edit that would restore consistency.

    ``evidence`` is exactly two sites: the two statements of the project
    that disagree, quoted. A claim with one site is an opinion about what
    ought to exist; two sites is what makes it a contradiction the project
    owns rather than a judgment this module made.

    ``proposal`` is a :class:`~crosslink.delta.Delta` bound to the project
    it was computed from, so the oracle harness can verify a patch against
    it unchanged - or ``None``, when any consistent edit would require
    information the reduction does not have (see the module docstring).

    One stated domain restriction: a proposal is the minimal edit in
    DECLARATION space, and the reduction may have merged tree-level
    provenance the declaration space cannot see. The known case: a stale
    reader's declaration also contributed columns. The proposal corrects
    ``read_by`` alone; the natural tree patch (delete the stale declaration)
    also drops those columns, so the oracle observes a wider delta and
    refuses. That refusal is the oracle being right about the patch not
    matching the stated delta - the patch author must either restate the
    orphaned columns under a surviving declaration or accept the wider
    delta as a different edit. Demonstrated, not hidden, in the tests.
    """

    kind: str
    subject: str
    claim: str
    evidence: tuple[str, str]
    proposal: Delta | None = None


def findings(declared: ProjectDeclarations) -> tuple[Finding, ...]:
    """Every self-contradiction in one snapshot, deterministically ordered.

    Pure over its input: two equal snapshots yield equal findings, and a
    self-consistent snapshot yields none - the negative arm the tests hold,
    because a finder that hallucinates contradictions makes every drift
    report noise.
    """

    # The model's own definition of the names this project defines - the
    # membership test every kind hinges on stays the model's decision, not a
    # fourth inline copy of it.
    known = set(declared.model_names())
    found: list[Finding] = []

    # Undeclared lineage roots: the graph names a dependency this project
    # neither builds nor declares. Matching a root against declared sources
    # is by exact table name - the one link the two statements share; a
    # subtler resolution rule would be a judgment, and this authority does
    # not make those. The accepted cost: a dangling
    # dependency that merely shares a declared source's table name reads as
    # covered. The candidate cross-check (require the source's read_by to
    # intersect the root's dependents) embeds read-attribution semantics into
    # root coverage and makes the claim prose false in the mixed case - a
    # judgment wearing a rule's clothes.
    dependents_of: dict[str, set[str]] = {}
    for model in declared.models:
        for upstream in model.depends_on:
            if upstream not in known:
                dependents_of.setdefault(upstream, set()).add(model.name)
    declared_tables = {source.table for source in declared.sources}
    for root in sorted(set(dependents_of) - declared_tables):
        dependents = sorted(dependents_of[root])
        stated = ", ".join(dependents)
        plural = len(dependents) > 1
        found.append(
            Finding(
                kind=UNDECLARED_LINEAGE_ROOT,
                subject=root,
                claim=(
                    f"the graph reads {root!r} and nothing declares it: it is "
                    "neither a model this project builds nor a table any "
                    "declared source names"
                ),
                evidence=(
                    (
                        f"models ({stated}) declare a dependency on {root!r}"
                        if plural
                        else f"model {stated} declares a dependency on {root!r}"
                    ),
                    f"no model is named {root!r} and no declared source "
                    f"names a table {root!r}",
                ),
                # No proposal, deliberately: the consistent declaration is an
                # ExternalSource, and its required system is exactly the field
                # a computed proposal would have to invent.
                proposal=None,
            )
        )

    # dict.fromkeys on each collection below: the delta layer's doctrine is
    # that an identical restatement is one statement, and a finder that
    # reports one contradiction twice hands out two proposals of which only
    # the first can apply.
    for key in dict.fromkeys(declared.declared_keys):
        if key.model not in known:
            found.append(
                Finding(
                    kind=DANGLING_DECLARED_KEY,
                    subject=key.model,
                    claim=(
                        f"a key is declared for {key.model!r} and the project "
                        "defines no such model"
                    ),
                    evidence=(
                        f"declared_keys holds {key!r}",
                        f"no model is named {key.model!r}",
                    ),
                    proposal=Delta(
                        format=declared.format,
                        name=declared.name,
                        declared_keys=SetEdits(removed=(key,)),
                    ),
                )
            )

    for join in dict.fromkeys(declared.declared_joins):
        # The shared per-join rule from model.py - the same one the producers'
        # notes aggregate, so a join the note calls dangling is a join this
        # kind finds, and vice versa.
        absent = absent_join_sides(join, known)
        if absent:
            absent_stated = " or ".join(repr(side) for side in absent)
            found.append(
                Finding(
                    kind=DANGLING_DECLARED_JOIN,
                    subject=", ".join(absent),
                    claim=(
                        f"a join is declared between {join.from_model!r} and "
                        f"{join.to_model!r} and the project does not define "
                        + absent_stated
                    ),
                    evidence=(
                        f"declared_joins holds {join!r}",
                        "no model is named " + absent_stated,
                    ),
                    proposal=Delta(
                        format=declared.format,
                        name=declared.name,
                        declared_joins=SetEdits(removed=(join,)),
                    ),
                )
            )

    for source in dict.fromkeys(declared.sources):
        stale = tuple(reader for reader in source.read_by if reader not in known)
        if stale:
            surviving = tuple(r for r in source.read_by if r in known)
            # The subject carries the schema when there is one: consumers key
            # findings by (kind, subject), and `identifier` alone would
            # collapse two real warehouse tables in different schemas - the
            # exact collapse source_identity exists to prevent.
            subject = (
                f"{source.system}.{source.schema_name}.{source.table}"
                if source.schema_name
                else source.identifier
            )
            # Which minimal edit is proposed depends on whether any reader
            # survives. When every reader is stale, a corrected attribution
            # would be read_by=() - a state the declaring format cannot
            # produce, because attribution is keyed by the declaring reader:
            # removing the last declarer removes the source. Proposing it
            # would hand the oracle a delta no tree patch can realize, so the
            # all-stale case proposes the removal instead - the source line
            # was the stale statement, and the table's reality in the
            # warehouse is not this snapshot's to assert.
            if surviving:
                corrected = replace(source, read_by=surviving)
                proposal = Delta(
                    format=declared.format,
                    name=declared.name,
                    sources=KeyedEdits(
                        changed=(Changed(source, corrected, ("read_by",)),)
                    ),
                )
            else:
                proposal = Delta(
                    format=declared.format,
                    name=declared.name,
                    sources=KeyedEdits(removed=(source,)),
                )
            found.append(
                Finding(
                    kind=UNKNOWN_READER,
                    subject=subject,
                    claim=(
                        f"source {source.identifier!r} is declared as read by "
                        + ", ".join(repr(r) for r in stale)
                        + ", which the project does not define"
                    ),
                    evidence=(
                        f"sources holds {source!r}",
                        "no model is named "
                        + " or ".join(repr(r) for r in stale),
                    ),
                    proposal=proposal,
                )
            )

    return tuple(found)

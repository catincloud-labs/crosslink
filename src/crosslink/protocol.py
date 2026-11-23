# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The project seam, tiered - a proposal, expressed as something that runs.

The seam is tiered, the way a storage protocol is tiered, and each tier is a
superset of the one above:

    ProjectSource        declarations()                    - what the project declares
    FingerprintedProject   + fingerprint()                 - a hash per layer, to compare
    EditableProject        + propose_edits()               - edits offered for review

A format implements only those tiers it is able to serve, and
:func:`tier_of` reads which by ``isinstance``, never from a declared flag.
ADR-0001 is the record for both: why one method cannot carry a project's
channels, and why a tier is checked rather than claimed. This module is the
seam that record decides, and does not argue it again.

One reason the record does not give is this module's to keep. Before the
tiers, a generated project was safe from having edits written into it only
where some naming convention happened not to match - safe by coincidence
rather than by contract. Declining a tier makes that safety structural.

**Non-goal: this does not describe how a project is constructed.** Finding and
constructing a project is its own contract, on purpose: formats are keyed by
different things (a directory, a graph in memory, a service), and choosing
whichever key the first format happened to use would not settle that.
See :mod:`crosslink.context` for the shape that question takes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import ProjectDeclarations

__all__ = [
    "EditableProject",
    "FingerprintedProject",
    "ProjectFingerprint",
    "ProjectSource",
    "tier_of",
]


@runtime_checkable
class ProjectSource(Protocol):
    """Tier 1: a project that can state what it declares.

    ``format`` is a stable identifier for the project format, not for the
    instance - ``"dagster"``, ``"dbt"``. It is what a registry would resolve.
    """

    format: str

    def declarations(self) -> ProjectDeclarations:
        """What the project declares: models, keys, joins, semantics.

        **This must not raise.** A project that is absent, ambiguous, or
        unreadable returns empty declarations carrying a note that says why.
        Exploration runs against warehouses with no project at all, so absence
        is an ordinary state rather than an error, and a format that raises
        here turns a normal condition into an outage.

        This is the tier's real contract, and it is behavioural rather than
        structural - which is why a conformance suite that only checks shapes
        will not catch a format that gets it wrong.
        """
        ...


class ProjectFingerprint(Protocol):
    """The per-layer content fingerprint of a project at one moment.

    Deliberately minimal and format-neutral: a mapping from a layer name to a
    stable hash, plus the model names that layer covers. What counts as a layer
    is the format's business.
    """

    layers: dict[str, str]
    models: tuple[str, ...]


@runtime_checkable
class FingerprintedProject(ProjectSource, Protocol):
    """Tier 2: adds the snapshot channel.

    A fingerprint is what makes drift detectable: compare a vouched-for one
    against the current one and the difference is the change. A format reaching
    only tier 1 still contributes declared keys and joins; it simply cannot be
    a drift baseline.
    """

    def fingerprint(self) -> ProjectFingerprint:
        """The project's current content fingerprint. Must not raise."""
        ...


@runtime_checkable
class EditableProject(FingerprintedProject, Protocol):
    """Tier 3: the write path.

    Implemented only by formats whose source of truth can actually receive an
    edit. ADR-0001 says why a reduction of a live graph cannot, and why that
    is a missing tier rather than a ``writeback`` flag set to false.
    """

    def propose_edits(self, edits: object) -> object:
        """Propose edits as reviewable diffs. Never writes without review."""
        ...


def tier_of(project: object) -> int:
    """The highest tier ``project`` satisfies, or 0 for none.

    Checked structurally rather than declared, so a format cannot claim a tier
    it does not implement. Note the deliberate ordering: tiers are nested, so
    the test runs from the most specific down.
    """

    if isinstance(project, EditableProject):
        return 3
    if isinstance(project, FingerprintedProject):
        return 2
    if isinstance(project, ProjectSource):
        return 1
    return 0


# What `__all__` holds by construction, checked when the module loads: every
# name it exports is defined here. An explicit `raise`, never `assert`, which
# `python -O` strips; its plant is in `tests/test_load_time_checks.py`.
if [name for name in __all__ if name not in globals()]:
    raise RuntimeError("protocol: a name in __all__ is not defined in the module")

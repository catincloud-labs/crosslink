# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The service's semantics: compare two envelopes, say what drifted.

The codec (:mod:`crosslink.wire`) decides what an envelope *is*; this module
decides what a service *does* with two of them. Separate on purpose - a codec
is syntax, a verdict is semantics, and the two evolve on different clocks.
This is also where the delta and proposal payload kinds will be handled, when
their gates open (ADR-0004's consequences); nothing here builds them early.

The long-lived ``serve()`` is not here. It is beside this module, as
:mod:`crosslink.serve`: a process that binds a socket and holds a baseline is
a different thing from the pure comparison it calls, and that process imports
the frame codec, which this module and the package root must not.

``observe`` is pure: no persistence, no leases, no held state - "borrows,
never holds" applied to compute. Whoever calls it owns the previous envelope
and whatever storage it came from; the service the v1 arc ships is
read/compute only, and this function is the whole of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Fingerprint
from .wire import Envelope, FingerprintPayload, WireRefusal

__all__ = [
    "BASELINE",
    "DRIFT",
    "DriftVerdict",
    "IDENTITY_MISMATCH",
    "NO_DRIFT",
    "observe",
]

# The comparer's own refusal control. Deliberately not a decode control: each
# envelope in a mismatched pair is individually valid, so only the code that
# sees the pair can refuse the pairing.
IDENTITY_MISMATCH = "identity-mismatch"

# The three verdict kinds. A baseline is its own kind because it is not a
# drift claim: "nothing to compare against" and "compared, and nothing moved"
# are different statements, and collapsing them makes the first observation of
# a project read as an assurance nobody made.
BASELINE = "baseline"
NO_DRIFT = "no-drift"
DRIFT = "drift"


@dataclass(frozen=True)
class DriftVerdict:
    """What one comparison concluded, and on what evidence.

    Not named ``Verdict``: :mod:`crosslink.verify` already exports one, and a
    drift verdict and a proposal verdict are different claims that must not
    share a name.

    The load-bearing case is ``kind=DRIFT`` with empty ``changed_layers`` and
    ``digest_changed=True``: the layered fingerprint saw nothing move, but
    the snapshot digest did - undifferentiated drift in the four nouns the
    layers cannot see (keys, joins, semantic models, metrics). That is its
    own distinguishable shape, never folded into "no-drift": a comparer that
    reports only what its coarser instrument saw is the layered blindness
    rebuilt one level up.

    ``previous_emitted_at`` / ``new_emitted_at`` are carried verbatim from the
    envelopes, informational like their sources: material for the log line
    reading this verdict, never part of the decision.
    """

    kind: str
    changed_layers: tuple[str, ...]
    digest_changed: bool
    previous_emitted_at: str | None
    new_emitted_at: str


def _fingerprint(payload: FingerprintPayload) -> Fingerprint:
    return Fingerprint(layers=dict(payload.layers), models=tuple(payload.models))


def observe(previous: Envelope | None, new: Envelope) -> DriftVerdict | WireRefusal:
    """Compare a new fingerprint envelope against the previous one, if any.

    ``previous is None`` is the first observation of a project and returns a
    :data:`BASELINE` verdict. Two envelopes from different projects - the
    self-described format/name pairs disagree - are refused rather than
    compared, because a drift claim between two different projects is an
    invented claim (the same rule ``diff`` enforces for snapshots).

    The comparison reuses the shipped primitives rather than restating them:
    :meth:`Fingerprint.changed_layers` for the "which part" answer, and the
    payloads' snapshot digests for the four nouns the layers cannot see.
    """

    if previous is None:
        return DriftVerdict(
            kind=BASELINE,
            changed_layers=(),
            digest_changed=False,
            previous_emitted_at=None,
            new_emitted_at=new.emitted_at,
        )

    before = (previous.project_format, previous.project_name)
    after = (new.project_format, new.project_name)
    if before != after:
        return WireRefusal(
            IDENTITY_MISMATCH,
            f"cannot compare {after[0]}/{after[1]} against a previous "
            f"envelope from {before[0]}/{before[1]}: a drift claim between "
            f"two different projects is an invented claim",
        )

    changed = _fingerprint(previous.payload).changed_layers(_fingerprint(new.payload))
    digest_changed = (
        previous.payload.snapshot_digest != new.payload.snapshot_digest
    )
    return DriftVerdict(
        kind=DRIFT if changed or digest_changed else NO_DRIFT,
        changed_layers=changed,
        digest_changed=digest_changed,
        previous_emitted_at=previous.emitted_at,
        new_emitted_at=new.emitted_at,
    )

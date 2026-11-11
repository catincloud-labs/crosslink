# ADR-0001 - The project seam is tiered, and a tier is checked, not claimed

- **Status:** Accepted
- **Date:** 2026-08-27
- **Supersedes:** -
- **Superseded by:** -

> **Reworded for publication, 2026-11-11.** This record's text was reworded
> once, when it moved to the public repository. The passages reworded pointed
> at private history: where the design came from, an example from a private
> system, and a register of issues. Two clauses that had gone stale keep their
> words and carry a dated marker. Characters outside ASCII were replaced. Its
> status, its decision and its constraints did not change. The original stands
> in the private repository's history.

The design predates this record: the tiers shipped with the fork and were
reasoned out in the prototype before that. This record exists because the
reasoning lived only in a docstring, and an unwritten decision holds exactly
as long as the sessions that remember it.

## Context

A project format is read through channels with different consumers and
different requirements. A single-method seam cannot carry that, whichever
method it names: pin it to the read view and the declared keys never arrive;
pin it to the declarations and the per-layer fingerprint has nowhere to come
from.

The write path sharpens it. A project reduced from a running asset graph
**must not** receive edits - its source of truth is the code that produced the
graph, and writing to the reduction edits an artifact that is regenerated from
something else.

A capability flag - `writeback: bool` - was the obvious alternative shape, and
it is a claim the engine has to interpret, trust, and branch on. Nothing stops
a format from setting it wrong, and the declaration and the enforcement are
two separate objects that can disagree.

## Decision

**The project seam is three nested `runtime_checkable` protocols -
`declarations()`, `+ fingerprint()`, `+ propose_edits()` - and a format's tier
is decided by `isinstance`, never by a declared flag.**

The constraint downstream: a format implements the tiers it can serve and
simply does not implement the rest. Declining a tier is structural - a format
that cannot receive edits cannot accidentally claim it can, because the
declaration and the enforcement are the same object. Nothing in this
repository may branch on a capability field, and nothing may add one.

The seam lives in `src/crosslink/protocol.py`; `tier_of` is the one reader of
the tier structure and tests from the most specific tier down.

## Alternatives considered

- **Capability flags.** Would have bought a simpler protocol and free
  extensibility (a new capability is a new field). Lost because a flag is a
  second copy of a fact the type system already holds, and two copies of a
  fact is one fact and one lie waiting to happen - a format carrying
  `writeback=True` without the method fails at call time, in production,
  instead of at `isinstance`, in a test.
- **One protocol, optional methods checked with `hasattr`.** Functionally
  close to what `runtime_checkable` does, but it puts the check at every call
  site instead of in one `tier_of`, and call sites drift.

## What this costs

- **Behavioural contracts are invisible to `isinstance`.** The tier-1 contract
  that `declarations()` must not raise on an absent or malformed project is
  the tier's real content, and no structural check can see it. The conformance
  suite (`src/crosslink/conformance.py`) exists to carry that half, which
  makes the suite's own power to discriminate load-bearing - see the falsifier
  below.
- **`runtime_checkable` checks names, not signatures.** A format with a
  `propose_edits` attribute of the wrong shape still passes `isinstance`. The
  residual is accepted and is part of what the conformance suite must catch.
- A new capability is a new tier or a new protocol - deliberately more
  ceremony than adding a flag, which is the point.

## Do not implement until

**Implementable now:** everything this record decides is built. Tiers 1 and 2
are implemented by `DagsterProject`; tier 3 is declared and deliberately
unimplemented there - `docs/ROADMAP.md` carries the sequencing for the format
that will implement it.

- [x] `tier_of` and the tier protocols refuse each tier a format lacks -
  **closed by:** the suite's tier tests
  (`tests/test_project.py::TestTiers`, asserting `DagsterProject` reaches
  tier 2 and structurally lacks tier 3), **run** 2026-08-27: 50 passed.

## What would falsify this

- A format observed holding a tier it cannot serve - `isinstance` true,
  behaviour absent - **in a way the conformance suite passes**. A suite every
  candidate passes trivially is the flag design wearing a suite's name. Until
  a deliberately wrong format has been observed to fail the suite, this
  falsifier is unwatched.

  **DEAD 2026-11-11.** The last sentence above was read against
  `tests/test_conformance_calibration.py`, the test that answered it: that
  test ran the suite over three deliberately wrong formats and asserted which
  arms each one failed. The falsifier was watched from the day that test
  landed.
- A consumer found branching on a declared capability field. There should be
  nothing to branch on; finding one means the flag design arrived anyway.

## Consequences

- The read tiers are cheap for a new format and the write tier is expensive,
  which is the intended gradient: tier 1-2 formats accumulate, tier 3 is
  earned.
- Adding `propose_edits` to `DagsterProject` is a **breaking act, on
  purpose** - `tests/test_project.py` asserts its absence, because the Dagster
  reduction's source of truth is regenerated. The first tier-3 format is a
  format whose source of truth is files.
- The conformance suite is a deliverable, not a formality, and its negative
  calibration is owed work.

  **DEAD 2026-11-11.** The clause *"its negative calibration is owed work"*
  was read against `tests/test_conformance_calibration.py`, the test that
  answered it: the calibration was that test, and was no longer owed.

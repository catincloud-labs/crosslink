# ADR-0004 - The first wire payload is a fingerprint

- **Status:** Accepted
- **Date:** 2026-09-01
- **Supersedes:** -
- **Superseded by:** -

> **Reworded for publication, 2026-11-11.** This record's text was reworded
> once, when it moved to the public repository. The passages reworded said who
> ruled and where, pointed at pull requests by number and at a commit, leaned
> on a check outside this repository, and owed a later decision to a private
> repository. Each ticked box keeps its observation, and the pull request its
> closing clause names stands in the private repository's history. Characters
> outside ASCII were replaced. Its status, its decision and its constraints
> did not change. The original stands in the private repository's history.

Recorded here because the decision is this repository's to carry: the wire
layer lives in this repository (the placement record in `docs/ROADMAP.md`),
so what that layer carries first is this corpus's decision.

## Context

The write path is complete - all five steps built, two formats - and the
parked list is the frontier. The wire *placement* question was already
settled: the layer lives here. The wire *format* stayed parked on its original
trigger - the first fingerprint, delta, or proposal crossing a process
boundary on a network - because a format designed before its first real
payload is designed against guesses.

The trigger now fires by decision rather than by accident: the next arc is
the library=>service gap (axis A in
`docs/ROADMAP.md` - long-lived, addressable, no human in the request path),
and the arc names its first payload instead of waiting for one. The
doctrine survives intact: the format is still designed against a real
payload; what changed is that the payload is chosen. The shape is
drift-watch: a reducer runs near the project tree and emits a compact
reduction fingerprint; the service holds the standing objective, compares,
and decides.

What was true in this tree when this decision was recorded (**read**
2026-09-01):

- The fingerprint already exists as a type: `definition_hash` (sha256) and
  `Fingerprint` in `src/crosslink/model.py`, whose `changed_layers` is
  already the compare primitive, and `layered_fingerprint(models, sources)`
  is the shared house shape, pinned by the conformance suite. It covers
  models and sources only - four of the six declaration nouns (keys, joins,
  semantic models, metrics) are outside it, by that function's own scope.
- `delta.canonical(snapshot)` in `src/crosslink/delta.py` is deterministic
  and idempotent - a determinism source a content digest can stand on.
- No serializer and no schema version exist anywhere in the tree. The one
  serialize-then-hash precedent (`src/crosslink/declarations.py`) hashes
  yaml because yaml was that function's *input*, not because yaml is a wire
  choice.

## Decision

**The first wire payload is a fingerprint, carried in a versioned envelope
to a service that only reads and compares.**

The constraints this places on everything downstream:

- **The v1 service is read/compute only.** It holds no credential, mints no
  identity, and writes nothing. Delivery stays operator-ambient; the
  delivery record's reopened privilege question arrives only when the
  proposal payload travels, and that payload is sequenced last.
- **The envelope is versioned, and the version moves with the types in one
  commit.** Schema and format live in one repository for exactly this
  reason (the placement record's first ground); a version bump in a
  different commit from the shape change it names is the two-versions
  failure arriving by schedule.
- **Refusals are first-class and typed.** Bytes off a network are data, not
  programmer error: a decoder returns a refusal value, it does not raise.
- **No coordination state on the wire.** No sequence numbers, no
  generations, no fencing tokens - a consumer-trusted ordering claim is
  coordination state, and coordination state belongs to the substrate.
  Ordering is the caller's knowledge, not a wire claim.
- **Later payloads are new payload kinds inside this envelope, not new
  envelopes.** Delta and proposal, when their gates open, arrive as kind
  values; the schema version moves only when the envelope's own shape does.

## Alternatives considered

- **Clone-and-reduce.** The service clones the repository and reduces
  locally; nothing new travels. Buys zero new serialization surface - the
  strongest version of "don't build a format yet". Lost because GitHub
  becomes someone else's wire: no payload of ours ever crosses a boundary,
  the design trigger never fires, and the protocol layer this arc exists to
  force into existence never comes to exist.
- **Delta-first.** Ship the richer payload first. Buys the "what changed,
  exactly" answer in one step. Lost because a delta format without an
  observed drift is designed against guesses - the exact failure the
  trigger doctrine exists to prevent. The fingerprint verdict is what
  *produces* observed drifts; the delta format gets designed against those.
- **Layered-fingerprint-only payload.** Carry only the shipped
  `Fingerprint`. Buys full reuse, no new digest. Lost because it is blind
  on four of the six nouns: a project could change every declared key and
  the payload would swear nothing moved.
- **Whole-digest-only payload.** One digest over the canonical snapshot.
  Buys the smallest possible payload. Lost because it discards the "which
  part" answer - the reason `Fingerprint` is per-layer, per its own
  docstring - and orphans the conformance-pinned primitive. The payload
  therefore carries both halves: the layered fingerprint answers "which
  part", the snapshot digest cures its blindness.

## What this costs

- **A second serialization surface that must move with the model.** Every
  shape change to the declaration types now owes the codec a look, in the
  same commit - a standing tax on every future model edit.
- **A schema version stewarded forever.** Version 1 is a number a peer can
  hold against this repository from now on; retiring a version is an estate
  event, not a refactor.
- **Deliberate redundancy in the payload.** Both halves travel - the
  layered fingerprint and the snapshot digest overlap on models and
  sources. Priced as the cure for the layered blindness, and cheap in
  bytes; but it is two answers to "did it change", and they must never be
  allowed to disagree silently.

## Do not implement until

**Implementable now:** the versioned envelope and the fingerprint payload -
the codec - and then the compare/decide half with its network traversal:
the two boxes below, in that order. Nothing beyond the fingerprint kind:
no delta payload, no proposal payload, no service identity, no long-lived
deployment (the gates in Consequences).

- [x] envelope v1 round-trips and refuses typed - **closed by:** the pasted
  green output of `pytest tests/test_wire.py -q` in the envelope pull
  request. Observed 2026-09-01: `12 passed`, the round-trip arms
  (equality, determinism, the escaping dialect) and the calibration arms
  asserting the exact refusal control for each of eight wrong-byte shapes,
  with the whole closed control set observed firing; full suite `292
  passed` on that branch.
- [x] a fingerprint envelope crossed a process boundary on a network and a
  verdict came back - **closed by:** the traversal test's observed drift
  verdict naming the changed layer. Observed 2026-09-01: the verdict
  decoded from the HTTP response body after a POST to
  `127.0.0.1` - `{"changed_layers": ["gold"], "digest_changed": true,
  "kind": "drift"}` - naming the rewired gold layer, with the refusal arm
  observed beside it (garbage bytes answered 422, `malformed-envelope`);
  `pytest tests/test_service.py -q` at `7 passed`, full suite `299 passed` -
  re-observed identical after the self-review pass reworked the codec
  underneath it.

## What would falsify this

- The fingerprint verdict proving useless without an immediate full
  re-inspection in every observed case - the payload demoted to a doorbell
  that only ever rings for a clone. That would mean the smallest honest
  payload was too small, and the delta payload was the real v1.
- The envelope failing to stay useful without a consumer-trusted ordering
  field - sequence or generation demands leaking into the wire. That would
  mean "ordering is the caller's knowledge" was wrong, and it takes a
  superseding record, not a field addition.

## Consequences

- **The sequencing gates are prose, deliberately, and this bullet is the
  price tag.** The gates: the delta payload waits on an observed drift
  verdict from a real project whose observer wanted the "what changed,
  exactly" answer; the proposal payload waits on the delta payload having
  shipped *and* the delivery record's privilege question re-answered for
  the no-operator case; no service identity is minted until delivery has no
  operator at the call site. As unticked boxes these would gate this record
  indefinitely. Their control is therefore review, and the trade - prose gate
  instead of machine-checked box - is taken with eyes open.
- `docs/ROADMAP.md` carries the arc's sequencing and keeps the delta and
  proposal payloads on the parked list, proposal last.
- The compare/decide half lands beside the codec but not inside it: a codec
  is syntax, a verdict is the service's semantics, and the two evolve on
  different clocks.
- Whether a deployed long-lived service is part of any larger system is a
  separate decision - nothing here claims it.

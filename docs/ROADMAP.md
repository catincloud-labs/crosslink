# Roadmap

**Living document.** Everything here is expected to change. Where a decision
has hardened it moves to `docs/adr/` and this file cites it rather than
restating it - a bare `ADR-NNNN` below names a record in this repository's
corpus.

## What the product is

An orchestrator's worker and its scheduler answer two of three questions, and
neither has a way to ask the third:

| | answers | reacts to |
| --- | --- | --- |
| worker | **how** work runs | being told |
| scheduler | **when** work runs | time and events |
| **this product** | **what the work is** | the gap between declared intent and observed reality |

A worker and a scheduler both operate on a fixed definition; neither can
change the definition. That hole is the product. Its mechanism is
decided in three records: the tiered seam (ADR-0001), proposals against code
(ADR-0002), and verification against the reduction (ADR-0003).

"Agentic" is three independent axes, not a ladder, and they are decided one at
a time:

- **A - autonomous**: long-lived, addressable, no human in the request path.
  The library->service gap. The arc is open - ADR-0004 names the first wire
  payload - and the v1 service is read/compute only: no credential, no
  minted identity, no writes.
- **B - goal-directed**: holds a standing objective, chooses actions. Can be
  entirely rule-based, and the first shipped objective is (see the authorities
  section below).
- **C - model-driven**: an LLM generates proposals. Deliberately the last,
  swappable component - ADR-0003 makes every stage before it provable on
  hand-written patches. Built, as step 5 below records; the swappability is
  structural (a proposer is a callable), not a promise.

A + B is already a product. C is an enhancement to specific steps, not a
prerequisite.

## The write path, in five steps

The order is fixed by the mechanism (ADR-0003), not by preference; the fuzzy
part goes last.

1. **Reduction** - built. Tiers 1-2 ship in `src/crosslink/`
   (`DagsterProject`); `src/crosslink/PROVENANCE.md` says where the read
   side comes from.
2. **Desired-state specification** - built, in its agreed direction:
   `src/crosslink/findings.py` computes self-consistency findings from
   the reduction alone, each carrying its claim, both evidence sites, and -
   where statable without invention - a proposed `Delta` the verifier checks
   unchanged. The parked "who owns the invariants" question came due here,
   and the authorities section below is its answer.
3. **Delta computation** - built. `delta = D - C` in neutral-model terms:
   `src/crosslink/delta.py` ships the typed delta between two
   declaration snapshots, deliberately independent of where `D` came from.
4. **The verifier** - built. Sandbox apply -> rebuild -> re-reduce -> compare
   against the stated delta: `src/crosslink/verify.py`, proven entirely on
   hand-written patches; its calibration arms ticked ADR-0003's remaining
   preconditions.
5. **Patch generation** - built. `src/crosslink/generate.py` ships
   search against the oracle: a proposer proposes tree edits, the unchanged
   verifier judges them, a refusal feeds back - disagreements or the
   sandbox's error, verbatim - and the search is bounded, returning its full
   trace whether or not an attempt was accepted. The proposer is a callable,
   so the loop is proven on scripted proposers with no network anywhere near
   it; the Claude-backed proposer is one adapter behind that seam, its SDK
   an optional extra. If the model disappoints, the system still accepts
   human patches and proves they did what was intended.

Of the steps after the reduction, 3 and 4 wait on no other decision:
a delta is computable before anyone decides where desired states come from.
Every step above is built, and so is the second format below. The
conformance calibration is `tests/test_conformance_calibration.py`. That
test is the observation the first falsifier in ADR-0001's *What would
falsify this* waits on: the record, immutable, calls the
falsifier *unwatched* until a deliberately wrong format has been observed to
fail the suite, so this is the living sentence that says it is watched: run
that file and a wrong format fails the suite.

## Who sets the objective - three authorities, and the agreed direction

The old dichotomy (ship opinions vs take config) was false. There are at least
three sources of normative authority, and the design decision is the
precedence among them:

1. **Self-consistency** - not normative at all. *"Your graph reads a table
   nothing declares"* is a claim that the project contradicts itself:
   computed, not judged, defensible to anyone. A rejected finding here is a
   bug in our reduction - it teaches something.
2. **Revealed convention** - inferred from the project's own behaviour (90%
   of models declare a key => the other 10% are candidates). Statistics and
   taste; the better product answer and the weaker systems answer.
3. **Explicit policy** - config, as a thin override on top, never the primary
   input.

A fourth lurks behind delivery: **acceptance is the config** - when proposals
arrive as pull requests, merge/reject *is* the user expressing their objective
function, with nobody writing it down in advance.

**Decided, and this section is where the decision is written down: ship 1
alone, defer 2 indefinitely, keep 3 thin.** Choosing the decidable authority converts the invariants
question from judgment into verification. The refusal is visible in the
artefact itself: the undeclared-root finding in `src/crosslink/findings.py`
proposes nothing rather than fabricate a source system.

## Delivery - decided: the deliverer borrows, never holds

The privilege question came due at the delivery adapter. **Decided, and
this section is where the decision is written down: no credential is minted,
stored, or scoped at this layer.**
The adapter (`src/crosslink/deliver.py`) receives a callable that opens
the pull request and runs its git half under the operator's ambient
identity, per act - it cannot hold what its signature never receives - and
the emitted-files mode is the always-available, zero-authority floor. A held
write token was refused for product reasons before security ones: acceptance
is the config (the fourth authority above), and a proposer able to accept
its own proposal severs that channel. With the holding refused,
fork-versus-direct dissolves into the operator's choice of remote. The
question reopens the moment delivery has no operator at the call site - that
is the wire-layer tripwire below, not this record.

## The wire layer - decided: it lives here

The placement question was parked with a trigger - the first
fingerprint, delta, or proposal crossing a process boundary on a network.
Half of it came due before the trigger fired: whether a transport shared
with other systems must ever carry this product's payloads is a placement
question, not a design question.
**Decided, and this section is where the decision is written down: the wire
layer lives in this repository. Placement only; the format itself was left
parked on the original trigger, restated below.**

Three reasons, in load-bearing order:

1. **A wire format is a statement about the types it carries, and the types
   live here.** Framing, versioning, and integrity for a delta are decisions
   about what a delta *is*; when the type changes shape, the format must
   change in the same commit or two versions of the same schema are in
   service at once. One repository means schema and format move together; a wire
   layer beside the coordination substrate would restate these types and
   drift from them.
2. **Grouping by "both put bytes on a wire" is decomposition by technology.**
   The grouping this decision takes is by who owns the state. Coordination traffic - leases,
   generations, who may act - is state the substrate owns, and its protocols
   belong beside it. Payload traffic - what this product says to its own
   peers - is state these types own. The two travel for different reasons
   and evolve on different clocks; a shared transport layer would couple
   them for no reason deeper than sockets.
3. **The shared alternative has one consumer, and a name is a claim.** "A
   shared concern with more than one future consumer" describes no consumer
   that exists; a layer extracted for a second consumer that never arrives
   is a costume, and extraction *out* of a working link layer, if that
   consumer ever materializes, is the cheap direction. Meanwhile the
   repository is named for exactly this: a crosslink is the link between
   peers, and a repo named for the link that houses everything but the link
   would have its architecture decided by inertia - the outcome parking the
   question was meant to prevent, arrived at from the other side.

What this record does **not** decide: no framing, no serialization library,
no service scaffolding - a wire format designed before its first real
payload is designed against guesses, so the record left the format to the
design trigger (first payload reopens it before that work is scoped). And
nothing here makes this repository the default home for anything beyond it:
the coordination substrate's protocols are explicitly *not* claimed by this
record. The delivery record above already points its reopened privilege
question at this layer - a service identity, if one ever exists, is minted
where the wire is answered, which is why placement had to be priced rather
than inherited.

**The design trigger fired by decision.** The trigger restated
above was fired by decision rather than by accident: ADR-0004 names the
fingerprint as the first wire payload - a versioned envelope to a service
that only reads and compares. Everything else in this section stands
unmoved: the placement grounds, the substrate's unclaimed protocols, and
the delivery record's tripwire. The delta and proposal payloads stay on the
parked list below, their gates stated in ADR-0004's consequences.

## What is deliberately not being decided yet

- **The delta and proposal payloads.** The wire format itself is no longer
  parked - ADR-0004 opened it, scoped to the fingerprint payload. The delta
  payload waits on an observed drift verdict from a real project whose
  observer wanted the "what changed, exactly" answer; the proposal payload
  travels last, after the delta payload has shipped *and* the delivery
  record's privilege question is re-answered for the no-operator case.
- **dex interop** (`dex.py` and its mapping functions) - parked, as
  `src/crosslink/PROVENANCE.md` says; an unused mapping acquires callers.

## The second format

Built: `src/crosslink/dbt.py` ships `DbtProject` at tiers 1-2, the
conformance suite's first second consumer. It was scheduled ahead of any
tier-3 work for three reasons that are about evidence rather than features:
with one format the seam was a description of one implementation, not a
seam; the conformance suite had never discriminated between formats; and a
dbt project is the natural first tier-3 candidate later, because its source
of truth is files that can genuinely receive an edit - where the Dagster
reduction rightly declines (ADR-0001's consequences). The parsing half
already existed: `declarations.py` reads the dbt schema-test vocabulary, and
the format work was the tree walk and the SQL side.

# ADR-0003 - A proposal is verified against the reduction it claims to change

- **Status:** Accepted
- **Date:** 2026-08-27
- **Supersedes:** -
- **Superseded by:** -

> **Reworded for publication, 2026-11-11.** This record's text was reworded
> once, when it moved to the public repository. The passages reworded said who
> worked the decision out, and pointed at a register of issues and at pull
> requests by number. Each ticked box keeps its observation, and the pull
> request its closing clause names stands in the private repository's history.
> Characters outside ASCII were replaced. Its status, its decision and its
> constraints did not change. The original stands in the private repository's
> history.

Worked out on 2026-08-02 and recorded now. Two decisions made the same day
travel together here because they are one mechanism seen from two sides: how
a proposal is judged, and what a proposal *is*.

## Context

A write path without a reduction is close to intractable: an agent proposes a
patch to someone's code and nobody can say, mechanically, whether the patch
did what was meant. Review absorbs the whole burden, which is the "LLM writes
a patch and we hope" shape.

The reduction changes the arithmetic, because it is a projection. What the
project *should* declare (`D`) and what it declares now (`C = reduce(graph)`)
are both expressible in the neutral model, so the intended effect of a change
is computable **before any patch exists**:

    delta = D - C            stated in neutral-model terms, in advance
    apply P in a sandbox => graph'
    C' = reduce(graph')
    accept P only if C' closes delta

The question is never *"is this good code?"* but *"does the re-reduction
produce the delta that was already specified?"* - the same family as
compiler-in-the-loop generation, not freeform authoring.

This also reframes what the valuable half of the product is. The read side
alone is mildly useful; the write side alone cannot tell whether it worked.
**The read side is the acceptance test for the write side** - the value is the
loop, not either arm.

## Decision

**A proposal is a patch object carrying a stated delta, and it is accepted only
when applying it in a sandbox and re-reducing closes that delta.**

The constraints downstream:

- **delta before patch.** A proposal whose intended effect cannot be stated in
  neutral-model terms is not yet a proposal.
- **`propose_edits` returns the patch object** - diff, rationale, and the
  verification evidence from the sandbox run. Rendering it as a GitHub pull
  request (or anything else) is an **adapter**, one file, so the core stays
  testable with no network and no credential.
- **The patch generator is the swappable last component.** Every stage before
  it runs on hand-written patches, so the verifier is provable before a
  single prompt exists; a model that disappoints leaves a system that still
  accepts human patches and proves they did what was intended.

## Alternatives considered

- **Freeform generation judged by human review.** Buys immediate breadth -
  any change is proposable. Lost because it puts the whole correctness burden
  on review, produces no machine-checkable claim, and makes the product's
  quality equal to the model's, which is a foundation that moves monthly.
- **Verify by running the target's test suite alone.** Buys reuse of an
  existing oracle. Lost as the *primary* check because a test suite verifies
  what its authors thought to assert, not the intended delta - the two checks
  answer different questions, which is why both appear below.

## What this costs

- **Necessary, not sufficient - stated, not hoped away.** The oracle verifies
  the intended effect and is structurally blind to unintended ones: a patch
  can close delta and break something else. The target project's own test suite
  and CI are the second, independent verifier, and a target without one is a
  target this product serves badly.
- Sandbox rebuilds are the steady-state cost of every verification, paid per
  proposal, for every supported format.
- The delivery adapter touches a real security surface - something holding
  write access to a target repository is a high-value credential. That fork
  (held token, fork-based proposing, or emitted patches a human applies) is
  deliberately **not** decided by this record; it is an argument to settle
  before any token exists.

## Do not implement until

**Implementable now:** the delta vocabulary and the verifier harness, and
nothing model-driven. The patch generator (the LLM stage) may not be built
until the verifier below has been observed in both arms.

- [x] a typed delta and `diff(ProjectDeclarations, ProjectDeclarations)` exist,
  with `diff(C, C)` observed empty and a mutated snapshot observed non-empty -
  **closed by:** the delta-vocabulary pull request merging with those arms
  green. Observed 2026-08-28: `diff(C, C).is_empty = True`,
  `diff(C, D).is_empty = False` with
  `changed[0].fields = ('layer',)` for a single-field mutation, and the
  suite at `89 passed` (50 before the vocabulary, 39 of the new arms).
- [x] the verifier observed in both arms on hand-written patches - one that
  closes its stated delta accepted, and one that claims to and does not refused -
  **closed by:** the oracle-harness pull request merging with its calibration
  run green. Observed 2026-08-28: the closing patch's verdict
  `closes = True` with `observed == stated` and
  `stated.apply_to(before) == canonical(after)`; the non-producing patch's
  verdict `closes = False` with `disagreements = ('declared_keys',)`; suite
  at `101 passed`.
- [x] the blind spot demonstrated rather than described - a patch that closes
  delta while breaking something else passes the oracle and is caught only by the
  second verifier - **closed by:** the same pull request's documented
  negative arm. Observed 2026-08-28: a patch closing its stated delta while
  stripping a `not_null` test the parser deliberately ignores gets
  `closes = True`, and the stand-in for the target project's own suite is
  what fails.

## What would falsify this

- A patch accepted by the oracle whose applied effect differs from its stated
  delta - the projection failing as an oracle, which is a defect in the reduction
  and a stop-everything finding.
- The delta vocabulary proving unable to express a real, wanted change (an edit
  two snapshots cannot represent - e.g. a rename that diff reads as
  drop-and-add losing intent). That is not a bug but a limit of the design,
  and it takes a superseding record, not a workaround.

## Consequences

- The build order is fixed by the mechanism: delta, then verifier, then
  findings that *emit* deltas, then - last - generation. `docs/ROADMAP.md`
  carries it.
- Delivery is an adapter, so the choice of forum (pull request first, because
  a PR's CI run is exactly the second verifier this record requires) never
  reaches the core.
- The verification evidence travels **in** the patch object, so whatever
  renders a proposal can show its before/after delta - a machine-generated
  answer to the "how do we know it worked" question this repository's own
  pull-request template asks.

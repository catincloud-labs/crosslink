# ADR-0002 - Proposals are made against code, not the declarative layer

- **Status:** Accepted
- **Date:** 2026-08-27
- **Supersedes:** -
- **Superseded by:** -

> **Reworded for publication, 2026-11-11.** This record's text was reworded
> once, when it moved to the public repository. The passages reworded said who
> decided and when, and rested the claim that the declarative route is
> occupied ground on a private service and deployment. That claim now rests on
> a public project, read on the date the passage gives. Characters outside
> ASCII were replaced. Its status, its decision and its constraints did not
> change. The original stands in the private repository's history.

Recorded for the same reason as ADR-0001: the decision was load-bearing and
unwritten.

## Context

The reduction mixes two kinds of content, and only one of them is derived:

- **Structure** - models, refs, lineage - is derived from the graph. It is not
  writable: editing it edits an artifact that is regenerated from code.
- **Declarations** - keys, joins, sources, semantics - have a completely
  different source of truth: hand-written YAML, already in git, already
  reviewable. For *reading* the two arrive on one channel; for *writing* they
  could not be more different.

So the tractable write path exists and is declarative: propose edits to the
declaration files and never touch code. That route was **explicitly rejected
as already-solved ground, not as technically wrong** - and a public project
shows the point. dex (`https://github.com/exmergo/dex`, **read** 2026-11-11
at its tag `v1.17.6`) ships `dex maintain reconcile`. That repository's
`packages/dex-core/README.md` says the command *"proposes mechanical fixes
and advisory changes as plans for review"*, and its top-level
`references/command-contract.md` says it proposes the edits that reconcile
detected drift as a stored plan. The declarative reconcile loop is not merely
tractable; it is shipped, by a project this repository does not own. Building
it here would re-solve occupied ground.

What nothing owns is the other half: a change to the **code that produces the
graph**, proposed with its intended effect stated in advance and verified
against the re-reduction. That is the half this repository exists for.

## Decision

**crosslink proposes changes to the code that produces a project's graph; the
declarative layer is never the primary target of a proposal.**

The constraint downstream: the verifier must apply a proposal to **source**
and rebuild - never patch a reduction artifact and compare artifacts. A
proposal whose effect can be achieved without a rebuild is in the declarative
subset, and the declarative subset is not the product.

## Alternatives considered

- **Declarative-only.** Would have bought a shippable product quickly: the
  edit surface is YAML, application is file writes, verification is a
  re-parse. Lost on two grounds. First, it is solved - by prior projects of
  the author's, and now observably by dex-core's reconcile. Second, the
  findings that matter most are the ones whose fix is in code:
  `gcp_billing_raw`-class findings (a lineage root appearing from
  nowhere) are *stated* declaratively but *caused* in the generator, and a
  declarative-only proposer can document the symptom without ever reaching
  the cause.
- **Both from day one.** Deferred rather than refused: a code proposal that
  happens to only touch declaration files is an ordinary, easy case of the
  code path, not a second mode. Building a dedicated declarative mode first
  would anchor the design on the easy case.

## What this costs

- **The hard path, knowingly.** Proposals must survive a sandbox rebuild, so
  the verifier needs real project-construction infrastructure, and every
  supported format needs a rebuild recipe. The horizon (12+ months to a true
  1.0.0) was accepted with this.
- A declarative competitor can ship faster and look similar in a demo. The
  differentiation only shows when a fix requires code - the record accepts
  being slower to demo parity.

## Do not implement until

**Implementable now:** the rule itself - from merge it constrains how issues
and pull requests are scoped, and it is the reading against which the delta
vocabulary and the verifier are designed. Nothing else is authorised by this
record; the build sequencing lives in `docs/ROADMAP.md`.

## What would falsify this

- A shipped `propose_edits` whose output, across real use, only ever edits
  declared YAML while the generator code that produces the graph is reachable -
  the declarative product wearing this record's name.
- Twelve months of real findings in which no accepted proposal needed a code
  change. That would mean the declarative subset was sufficient after all and
  this record bought the hard path for nothing.

## Consequences

- The verifier (ADR-0003) is obligatory rather than nice-to-have: without a
  rebuild-and-re-reduce loop, code proposals cannot be checked at all.
- The distinction between structure and declarations stays load-bearing and
  must survive in the model: a proposal's *stated effect* is expressed over
  declarations (the neutral model), while its *patch* lands in code.
- Interoperation with dex-core's declarative reconcile is a boundary, not a
  rivalry: its plans target declaration files, crosslink's proposals target
  generators. Nothing here forbids a future adapter between them, and nothing
  plans one.

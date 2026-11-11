# ADR-NNNN - A decision, stated as a sentence

- **Status:** Proposed | Accepted | Superseded
- **Date:** YYYY-MM-DD
- **Supersedes:** - *(or `ADR-NNNN`, linked)*
- **Superseded by:** - *(or `ADR-NNNN`, linked - added when it happens; this is
  the one edit an accepted ADR is allowed)*

> Copy this file to `NNNN-kebab-title.md`, zero-padded to four digits, and
> delete this blockquote. The section headings below are the shape; the
> parenthetical guidance under each is not meant to survive into the ADR.
>
> The records written from this template are this repository's own. A bare
> `ADR-NNNN` in this repository names a record in **this** `docs/adr/`; a
> record in another repository's corpus is cited with its repository named.

## Context

*(What was true that forced a choice. Facts, not intentions - and where a fact
comes from another repository, cite the file and say whether it was **read** or
**run**. Those are different claims. If a number appears here, it is a number
someone measured, and the measurement is named.)*

## Decision

*(One sentence, in bold. If it takes a paragraph, two decisions are being made
and they want two records.)*

*(Then the constraint it places on everything downstream - the thing a future
session should check its work against.)*

## Alternatives considered

*(At least one, argued as though it might have won. An ADR whose alternatives
were never real reads as a justification rather than a decision, and a reader
can tell. Say what each alternative would have bought, then why it lost.)*

## What this costs

*(Every real decision has a price. Omitting it is the most common way these
documents become untrustworthy. Money, work now owed, a class of problem
newly reachable, something that gets harder to verify.)*

## Do not implement until

*(Required. What may be built the moment this merges, and what may not - because
`Status: Accepted` says a decision was made and says nothing about whether the
estate is authorised to act on it.)*

*(State the live half explicitly. An empty answer and an unstated one read
identically, and "nothing yet" is a real and respectable answer.)*

**Implementable now:** *(what this record authorises today)*

- [ ] *(a precondition)* - **closed by:** `(the observable that closes it)`

*(Tick a box only when the observable has actually been observed. An unticked
box means the `adr preconditions` check in `.github/workflows/checks.yml`
refuses a citation of this record outside `docs/adr/`, so the boxes are
load-bearing rather than decorative.)*

## What would falsify this

*(The observation that would mean this was wrong - concrete enough that someone
could notice it. Not "if it turns out badly"; something like "if X has been
able to happen for a year and never has.")*

## Consequences

*(What is now settled downstream, and what is now owed. Point at
`docs/ROADMAP.md` for sequencing rather than restating it - the roadmap is
allowed to change without this decision looking reversed.)*

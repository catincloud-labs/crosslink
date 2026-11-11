---
name: Defect or finding
about: Something is wrong, or a check is not doing what it claims
title: ""
---

<!--
Do not pair a close/fix/resolve verb directly with an issue reference unless
you mean to close it, since that fires from an issue body too. Write "part of" or
"refs".
-->

## TL;DR

<!-- Two or three sentences. What is broken, and what it costs. -->

## Evidence

<!--
Verbatim output (the command and what it printed), not a description of it.
If the defect is in a check, the useful evidence is usually a DIFFERENCE: the
same input with the check armed and disarmed, or the number moved. A single
passing run proves almost nothing about a guard.
-->

## Mechanism

<!--
Where it goes wrong, as `file.py:123`, at a stated version or commit. "Read
from source" and "reproduced live" are different claims: say which this is.
A well-reasoned comment in the code is not evidence that the code does what
the comment says.
-->

## If this silently stopped working, what would tell us?

<!--
If the honest answer is "nothing", that is the more important half of the
report and belongs at the top.
-->

## Attribution

<!--
Ours, or a dependency's? A claim about code we did not write needs the file,
the line, and the pinned version it was read at, and whether it was
reproduced or only read.
-->

## Why this is being filed rather than fixed in passing

<!--
Scope, risk, a dependency on work in flight: whatever it is, say it. Without
this line the next reader re-derives the whole decision.
-->

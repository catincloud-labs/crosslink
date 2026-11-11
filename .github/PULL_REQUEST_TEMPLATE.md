<!--
Delete any section that genuinely does not apply. An empty heading is worse
than no heading.
-->

## What changes

<!-- One paragraph, in terms of observable behaviour after the merge. -->

## Why

<!-- The problem this solves and how you know it is real. Link the issue. -->

## Verification

<!--
Verbatim output, not a description of output: the command and what it
printed. "Tests pass" is not verification; the count is.

If the change is a check, a guard, or a control, show it FAILING without the
fix as well. A check that has never been observed to fail has not been shown
to be a check. Read the count rather than the colour: a skip is not a pass.

The pr-hygiene gate reads the Dev value from the SAME line as the label, so
start the summary right after `**Dev:**` (command and result, on that line);
put the verbatim output in a fenced block below it.
-->

**Dev:**

## Issue references

<!--
A closing verb immediately followed by `#N` auto-closes that issue on merge,
whether or not you meant it, and backticks do not protect it - only adjacency
fires. "Part of #N" and "refs #N" are safe. When you DO mean to close
something, list the exact set in the `Autoclose:` trailer so the effect is
stated rather than inferred.
-->

Part of #

Autoclose: none

## Checklist

- [ ] Conventional commit subject (`feat:`, `fix:`, `docs:`, `chore:`, ...)
- [ ] Branched off `main`, not committed to it directly
- [ ] Claims changed in `.md` files match the tree, not another document
- [ ] Exactly one `deploy:` label, required; a `review:` clock, applied by hand and read by no guard.

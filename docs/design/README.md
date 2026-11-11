# Design documents: the header convention

A document in this directory **describes** the current shape of a subsystem
and never decides. Every decision it touches cites the record that made it,
in `docs/adr/`, or the section of `docs/ROADMAP.md` that states it; nothing
is settled by appearing on a page here.

No check reads the header below. It is a convention for a reader deciding how
far to trust a page, and for whoever changes the code a page describes.

## The header

Three bullets, first in the file after the title, each running on to lines
indented two spaces:

```markdown
- **Status:** living
- **Describes:** `path/one.py`, `a/directory/`, `tests/test_*.py`, and prose
- **Reviewed:** 2026-10-30 - what this re-read covered
```

- **Status** is `living`, `frozen` or `dead`, as the first word; what follows
  on the line is yours. A `living` page is kept true, as the two sections
  below say. A `frozen` one is a dated inventory whose dates read as
  true-when-written. A `dead` one names its successor and why.
- **Describes** names what the page is about. Every backticked path on it is
  a file, a directory or a glob in this tree that the page makes claims
  about. A name, a unit or prose may sit beside the paths: keep those, they
  tell a reader what the page covers.
- **Reviewed** is the claim that someone judged the page against the tree: a
  date, and one clause saying what that re-read covered. It may also name
  the commit of this repository the page was judged at, in backticks. It
  reads as *when the page was last judged*, never as *current*. A re-read
  replaces the date and the clause with its own, and a change that did not
  re-read the page does not re-stamp it.

## When the code a page describes moves

A change that falsifies a claim on a living page edits the page in the same
pull request. Whether that happened is something a reader can check:

```bash
git log --since=<the Reviewed date> --oneline -- <a Describes path>
```

A commit listed there that did not also touch the page is a change the page
has not been judged against. An empty listing says only that the named paths
did not move.

## When a sentence on a page dies

A design page is a living document, and `AGENTS.md`, *Living documents and
records*, says what happens to a sentence found dead on one: it is rewritten
to what is true at `main`, and the old text moves, dated, to the page's
history home.

## What the header cannot tell you

Whether the claims are true: a quiet page is one whose named paths did not
move, and no more than that. Whether the Describes list is complete. And
anything about code outside this repository, which a page here does not
describe.

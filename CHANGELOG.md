# Changelog

**No release has been cut, so this is not yet a release log.** It is the
history home of every living document here that has no `<name>.history.md`
tracked beside it (`AGENTS.md`, *Living documents and records*). When
a sentence in such a document is found dead, the change that finds it
rewrites the sentence where it stood and moves the old text here, quoted,
under a heading that names the document and the section it came from, with
the date it was read and what it was read against. This lead is living; the
entries below it are the record: read each as of when it was written.

## `docs/design/write-path.md`, *What the oracle can say*

Read 2026-11-11 against `generate()` in `src/crosslink/generate.py` at
`e3255f0`. The last cell of the table's *wrong subject* row, the one under
*What `generate` does with it*, read:

> records the attempt with the error text; the search continues

`generate()` compares the stated delta's `(format, name)` with the tree's
before its loop starts and raises `ValueError` to its caller, so no proposal
is requested and no attempt is recorded. The page's own sequence diagram and
its *`Delta` is bound to a project* bullet already said so.

## `docs/design/write-path.md`, *The seam the path hangs off*

Read 2026-11-11 against the table directly above the sentence, in the same
file at `e3255f0`, whose last row reads `no` in both format columns:

> Both cells in the last row are empty **by design** (ADR-0001's consequences):

## `AGENTS.md`, *Repo conventions*

Read 2026-11-11 against `.github/workflows/` at `e3255f0`. The bullet on the
checks opened:

> - **The checks are two workflows, and each guard they run is a script in this tree.** The release path is two more, in the next bullet, so `.github/workflows/` holds four files. The suite and the Markdown lint are the two that are not: `pytest` and `markdownlint-cli2`, each named in the job that runs it. `.github/workflows/checks.yml` (count its jobs with

and closed:

> change nor a `name:` be added - the file says why). None of the four workflows calls an action from another repository of this organisation, and none reads a secret but the run's own token.

No claim in it was false of the tree. A sentence about the release path
stood between the lead and *the two that are not*, which left that phrase
pointing at the release workflows, and the sentence naming the two workflow
files had no verb.

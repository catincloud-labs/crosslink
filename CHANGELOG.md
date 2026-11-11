# Changelog

**This is not a release log.** A release's summary is on its GitHub
release, which `gh release view <tag> --repo catincloud-labs/crosslink`
prints. This file is the history home of every living document here that has
no `<name>.history.md` tracked beside it (`AGENTS.md`, *Living documents and
records*). When a sentence in such a document is found dead, the change that
finds it rewrites the sentence where it stood and moves the old text here,
quoted, under a heading that names the document and the section it came
from, with the date it was read and what it was read against. This lead is
living; the entries below it are the record: read each as of when it was
written.

## `docs/design/write-path.md`, *What the oracle can say*

Read 2026-11-11 against `generate()` in `src/crosslink/generate.py` at
`e3255f0`. The last cell of the table's *wrong subject* row, the one under
*What `generate` does with it*, read:

> records the attempt with the error text; the search continues

`generate()` compares the stated delta's `(format, name)` with the tree's
before its loop starts and raises `ValueError` to its caller, so no proposal
is requested and no attempt is recorded. The page's own sequence diagram and
its *`Delta` is bound to a project* bullet already said so.

Read the same day against `TreeEdit.apply` in the same file at `e3255f0`.
The last cell of the *renamed subject* row, directly below, read:

> the same: the error text on the attempt; the search continues

*The same* pointed at the cell quoted above. `generate()` does record a
`ValueError` from `verify()` that way, but `TreeEdit.apply` builds its
result with the tree's own name, so no edit `generate()` judges renames the
project: the outcome is reached by a patch handed to `verify()` directly.

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

## `README.md`, *Installing*

Read 2026-11-11 against <https://pypi.org/pypi/catincloud-crosslink/json>,
which answered 200 and listed one release, `0.1.0`, with a wheel and an
sdist. The sentence between the warning against the bare name and the
clone commands read:

> No release has been uploaded yet. Until one is, install from a clone:

## `README.md`, *Releases*

Read 2026-11-11 against three things. `git ls-remote --tags` on this
repository listed `refs/tags/v0.1.0`, peeling to `b9b7856`. The PyPI
answer is the one quoted in the entry above. `gh release view v0.1.0`
printed a release published that day. The section opened:

> No release has been cut: no `v*` tag exists, and nothing is on PyPI under this project's name. *Installing*, above, says what to do until one is.

## `CONTRIBUTING.md`, *What is deliberately not here yet*

Read 2026-11-11 against `git tag -l 'v*'` in a clone fetched that day,
which printed `v0.1.0`. The section, the file's last, read whole:

> A release. None has been cut: `git tag` prints nothing, and `README.md`, *Installing*, says what to do until one exists.

Its heading went with it: the section is now *Releases*.

## `CHANGELOG.md`, the lead

Read 2026-11-11 against the same tag and the same GitHub release. The lead
opened with the line below, quoted as far as the text that was replaced; the
sentence it breaks off in ran on unchanged:

> **No release has been cut, so this is not yet a release log.** It is the

The lead said the file was not yet a release log, and it is still not one:
no entry here describes a release.

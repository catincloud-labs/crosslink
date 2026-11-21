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

## `SECURITY.md`, *The surface, stated honestly*, the `crosslink.serve` bullet

Read 2026-11-20 against `src/crosslink/serve.py` at the change that keeps
the comparer's sequence ledgers in a file beside the baseline, so that a
restart no longer forgets them. Two sentences moved. The bullet's last two
sentences read:

> A restart forgets the sequence ledgers, so a replay against a restarted comparer is not caught; the docstring states that cost. The one file it keeps is the baseline, at the path it is given, written through a temporary file beside it.

## `docs/design/write-path.md`, *The comparer as a process*

Read 2026-11-20 against `src/crosslink/serve.py` at the same change. The
section's last paragraph ended:

> The ledgers are memory only - a restart forgets them, the cost `ration.frame`'s docstring states and `serve.py`'s own docstring prices - and that forgetting is also the by-hand clear for the epoch hazard: a store that loses its data restarts the producer's epoch below what the ledger accepted. One refusal moves state and is stated as such: a frame of a registered kind the comparer does not serve has passed every frame check, so its sequence is consumed.

The last sentence was already false at `main` before that change: a frame
that passes the frame checks consumes its sequence whatever the envelope and
the comparer then decide, so an envelope refusal and an `identity-mismatch`
moved the ledger too.

Read the same day against `Comparer.receive` in `src/crosslink/serve.py` at
the same change. The section's second paragraph read, in its second
sentence:

> Every request leaves exactly one JSON line on stdout, and the line carries `layer` as a field of its own beside `control` - so a `crc-mismatch` and a `digest-mismatch` differ in two fields and cannot land as one signal in the log, and `unknown-payload-kind`, the one control name all three layers use, is told apart by `layer` alone.

It was already false at `main` before that change: a baseline write that
failed raised out of the request before its line was written. That change
adds a ledger write that can fail the same way.

## `docs/design/write-path.md`, *The producer as a process*

Read 2026-11-20 against `src/crosslink/serve.py` at the same change. The
paragraph on the epoch read, in its third sentence:

> That holds while the store keeps its data: a store that loses it is the epoch hazard named above, and its clear is the comparer's restart.

## `docs/design/reduction-side.md`, *The dbt format (`dbt.py`)*, the walk paragraph's line range

Read 2026-11-15 against `src/crosslink/dbt.py` at the change that made
`_normalized_model_paths` say, in its note for an entry that collapses to
nothing, that dbt reads the entry as the project root and that this reader
does not route it. That change lengthened the note and the docstring, so
the function's line range moved from l.445-512 to l.445-518. One clause
moved. The walk paragraph's second clause read:

> `_normalized_model_paths` (l.445-512) is the one reading of `model-paths`, shared with the disk walk so the two cannot decide differently, dropping every `.` segment and every empty segment but a leading one (which makes the entry absolute) so `./models`, `models/` and `models/./staging` route as `models` and `models/staging` do, and dropping, each with a note, an absolute entry, one with a `..` segment, whether or not it would leave the root, and one that collapses to nothing;

## `docs/design/reduction-side.md`, *The dbt format (`dbt.py`)*, the walk paragraph

Read 2026-11-14 against `src/crosslink/dbt.py` at the change that made
`_normalized_model_paths` drop every `.` segment and empty segment of a
`model-paths` entry, where it had stripped only a leading `./` and trailing
slashes. That change lengthened the function, so its line range moved, and
the normalisation the walk paragraph named was no longer all of it. One
sentence moved. The walk paragraph's second clause read:

> `_normalized_model_paths` (l.445-506) is the one reading of `model-paths`, shared with the disk walk so the two cannot decide differently, normalising `./models` and `models/` and dropping, each with a note, an absolute entry and one with a `..` segment, whether or not it would leave the root;

An entry such as `models/./staging`, `models//staging` or
`models/staging/.` had been accepted, its files read from disk, and every
one of them dropped at routing with no note.

## `docs/design/reduction-side.md`, *The dbt format (`dbt.py`)*

Read 2026-11-14 against `src/crosslink/dbt.py` at the change that made
`_normalized_model_paths` drop a `model-paths` entry with a `..` segment
and made `from_directory` skip a file that resolves outside the project
root. That change added lines from `from_directory` on, so every line
range after l.245 moved; it also added the link containment the first
sentence did not state, and the `..` drop the walk sentence did not. Four
sentences moved. The section's first paragraph ended:

> It takes `{relative path: text}` (l.116-122, backslashes normalised to forward slashes so a tree built on Windows reads identically); `from_directory` (l.232-271) is the only thing that touches a disk, and an unreadable file becomes a walk note surfaced by `declarations()` rather than a raise (l.245-252).

The *References are extracted* bullet ended:

> A call inside a SQL comment still renders and *is* a dependency, so it matches; a Jinja comment `{# ... #}` never renders, so it is stripped first (`_JINJA_COMMENT`, l.88, applied at l.400 and l.417).

The *`read_by`* bullet read:

> **`read_by` is derived, never declared** - a model that reads a source says so in its own SQL, so attribution comes from `source()` extraction over the *kept* models' files only (l.145-159, `_readers_by_table` l.412-420), and the "read by models that do not exist" note the Dagster format needs has no dbt equivalent (l.36-42).

The walk paragraph read:

> The walk in pieces: `_project_header` (l.275-308) reads `dbt_project.yml` and falls back to the name `"unnamed"` and `("models",)` with a note on every failure shape (missing, unreadable, not a mapping, no name); `_normalized_model_paths` (l.434-486) is the one reading of `model-paths`, shared with the disk walk so the two cannot decide differently, normalising `./models` and `models/` and dropping absolute entries with a note; `_route` (l.310-365) sorts files under the model paths into the parsers' channels **by top-level key**, so one schema file carrying `models:` beside `sources:` feeds two parsers, and a file declaring none of the four vocabularies is noted; `_models_from_sql` (l.367-410) makes one model per SQL file - name from the stem, dependencies from `ref()`, layer from the first directory under the model path (`_layer_of`, l.423-431) - and on a **duplicate stem keeps the first in path order with a note** (l.394-399), the converge-and- note posture rather than the Dagster format's refusal, because dbt itself refuses duplicates at compile time and a read path cannot.

An entry such as `../outside`, or a link in the tree pointing outside
it, had made the disk walk read the files of a directory outside the
project root.

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

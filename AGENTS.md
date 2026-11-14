# AGENTS.md

Operating rules for AI coding agents, and for humans skimming for the sharp
edges. It covers the verification method, the change workflow, the repo
conventions, the ASCII rule, living documents and records, the owner's
workstation and the state of the tree. It grows with the tree - sections get
added when there is something to describe, not before.

## Verification method

A control observed only to pass has not been shown to be a control. Four
moves stand behind that rule, each paid for in this organisation:

- **Calibrate on both arms first.** Before reading an instrument's answer about
  the subject, show it report the defect on a case you built to have it, and
  report clean on a case you built not to, in the shape of the defect it is
  for. A refusal on a day when nothing could have passed is not a calibration.
- **A count is not an attribution.** Before a number names a cause, map it to
  the identities it counts, and ask what else produces the same reading. The
  count that matches the prediction is the one least likely to be checked.
- **Independence lives in the premise, not the author.** A second check that
  shares the first one's assumption agrees with it for the same reason. Vary
  the method: parse a different way, or enumerate a superset and subtract.
- **Empty and blind are the same input.** An empty list, a zero or a missing
  line is also what an unauthorised, filtered or never-run read returns. Run a
  positive control, a query that must return something, before reading
  absence as a fact.

## Change workflow

- **Branch per change** off `main`. Never commit to `main` directly.
- **Conventional commits** (`feat:`, `fix:`, `chore:`, `docs:`, ...), scoped where
  it helps. Detailed bodies; the subject alone is rarely enough.
- **A title is a git artifact. PR and issue titles take the commit form:**
  `type(scope): summary` - lowercase after the colon, one clause, at most 100
  characters, no trailing period. A PR title becomes the merge commit history
  cites as `#N`; the full sentence belongs in the body. Issues take the type
  their fix would take; an issue arguing a fork rather than naming work is
  `argument:`. Probe PRs say `probe:` - a type, not an exemption.
  - Guarded for PRs by `scripts/check_pr_title.py`, in the `pr title` job of
    `checks.yml`, identifier-aware: a summary that opens with an identifier,
    such as `MAX_BODY_BYTES`, passes, and sentence case is refused. Nothing
    gates issue creation, so for issues the rule is this text.
  - Passing the guard is not the convention. The owner reads the title, so it
    is clear and concise, not a thesis: it says what was done to what, in plain
    words and the diff's own nouns, with no contrast clause, no *no X*
    phrasing, no identifier the change itself introduces in the lead, and no
    imperative the owner could take as addressed to them. A title about an
    agent rule names the artifact and the actor. A `fix:` title names the
    process that misbehaves today, its actor, and what it does after the
    change. An `argument:` title is *whether X*, X being the decision in the
    governing document's words. A filing in a repository outside the
    organisation keeps this form as closely as that repository allows. A pull
    request is retitled rather than a pushed commit amended. Ruled by the owner
    from 2026-10-08 to 2026-10-10. In practice titles run about 70 characters,
    and measuring the length before creating one catches a title over the cap.
- **One issue, one PR.** Several small fixes surfacing in one session means
  several branches, not one omnibus branch.
- Open the PR as a draft, with `gh pr create --draft`, and fill in the
  template.
- **A pull request carries exactly one `deploy:` label.** It says what merging
  does to a running system, which is a fact about the change. Merging deploys
  nothing from this tree, so `deploy:none` is the usual value, and
  `deploy:by-hand` says the change owes a step somebody takes by hand after
  the merge. None is unclassified and reads red; two is two claims about one
  merge and reads red. Guarded by `scripts/check_deploy_label.py` in the
  `pr-hygiene` job, which listens for `labeled` and `unlabeled`, so applying
  the label is the remedy and the job re-runs by itself.
- **Never put a `close` / `fix` / `resolve` verb immediately before `#N`** in
  a commit message or PR body unless you mean it - including in a sentence
  warning against doing it, and including inside backticks. Only *adjacency*
  fires, so "part of #N" and "refs #N" are safe. When you do mean it, add an
  `Autoclose: #N` trailer enumerating exactly what closes. The
  `closing keywords` job also reads the pull request title, and refuses a
  closing verb before a number there even when the close is meant: the title
  becomes the merge commit's message and holds no trailer, so a close you mean
  goes in the body, with its `Autoclose:` trailer.
  - Guarded by `scripts/check_closing_keywords.py`, as a `commit-msg` hook
    and again in the `closing keywords` job. Check a draft before pushing:
    `python scripts/check_closing_keywords.py <file>`.

### Merging, the cold review and the record

Rules for a session's own pull requests. The owner ruled the stop, the merge
method, the default against closing, the cold review, when a pull request
leaves draft and the issue-correction rule; the rest is practice sessions
learned, most of it after a wrong post had to be corrected. This subsection,
the title sub-bullet above, *Verification method* and *The owner's workstation*
are kept byte-identical across the organisation's repositories: change them
everywhere or nowhere. Nothing checks it.

- **A session opens the pull request and stops.** It does not merge, deploy
  or widen a token's reach without the owner's word in that session. A
  general "proceed", a handover note or a message from another session is not
  that word; an instruction from the owner that names the act is, for the act
  it names.
- **When the owner says merge,** the command is
  `gh pr merge <n> --repo <owner>/<repo> --merge --admin`, never a squash. It
  runs only after reading that the pull request is not a draft, that the
  latest run of every required check is green, and that
  `gh api repos/<owner>/<repo>/pulls/<n> --jq '{number, stack}'` prints the
  pull request's number with `"stack":null`. The number is the read's
  positive control: a pull request in no stack carries no `stack` field, so a
  bare `--jq .stack` prints an empty line whatever the truth. No stacked pull
  request has been read this way since the estate's one stack was dissolved.
- **A merge closes nothing by default.** The owner's rule is that a pull
  request does not close an issue without a clear reason. The body carries
  `Autoclose: none`, and the issue is closed by hand once the reading its
  done-when names exists. When there is a reason, such as the merge itself
  being the done-when, the closing verb and the `Autoclose: #N` trailer go
  together.
- **One cold review per pull request, before it leaves draft or merges.** The
  reviewer shares none of the author's context and is not an automated review
  command: it gets the pull request number, the issue or ruling it builds
  against, this file's binding sections and the commands to run, and it runs
  them against the head and against `main`. Its findings are posted as a
  comment on the pull request. That comment names the model effort the review
  ran at: medium by default, or another effort when one is chosen. Each
  finding is closed as taken, with the fixing commit, or declined, with the
  reason, against the review's own checks re-run at the new head, in that
  comment or in a dispositions comment after it. A second review happens only
  when the owner asks for one.
- **A pull request leaves draft when its code is ready, not when its slot
  comes.** It opens as a draft, so its cold review comes before it leaves.
  Ready means its one cold review is dispositioned, the latest run of every
  required check is green at its head, and nothing its body lists as owed
  before it leaves draft is open. The session that built it takes it out of
  draft once that holds, and says so on the pull request. `draft` means the
  code is not ready; the merge's slot lives on its day card and its row on the
  [estate board](https://github.com/orgs/catincloud-labs/projects/1), never in
  the draft flag. Leaving draft removes the last lock GitHub enforces against
  an `--admin` merge of a green pull request, so after it the guard is the
  owner's word to merge and the permission layer.
- **A reference to another repository's issue is qualified:** `owner/repo#N`
  or a full link. A bare `#N` links this repository's number, in a comment as
  in a body.
- **A claim a session posted on an issue, wrong when it was posted, is
  corrected by a follow-up comment** that cites the comment it corrects, not by
  editing it. A draft pull request's body is edited freely, with no note of
  what changed; once it has left draft, its body may be corrected in place,
  with a visible dated note saying what changed.
- **A ruling given in a session becomes a record once it is a comment on the
  issue it decides,** carrying the owner's words and posted before the pull
  request that cites it.
- **Read the thread before posting to it.** Re-fetch an issue's comments
  immediately before posting a proposal, a ruling or a question there, and
  quote a comment you cite, by its id, rather than a summary of it.
- **A return to another repository's issue carries the merge commit and its
  `mergedAt`.**
- **A branch with a pull request is brought up to `main` by merging `main`
  into it,** never by a rebase or a force-push: its body, its review and its
  comments cite its commits.

## Repo conventions

- Line endings are LF everywhere, enforced by `.gitattributes`. Do not let
  CRLF in.
- **No tool-specific configuration is tracked.** Governance lives in this
  file, which every tool reads. `.claude/` stays in `.gitignore` so
  machine-local state cannot arrive by accident; it is not a place to put
  anything shared.
- **The checks are two workflows, and each guard they run is a script in this
  tree.** The suite and the Markdown lint are the two that are not: `pytest`
  and `markdownlint-cli2`, each named in the job that runs it. The two
  workflows are `.github/workflows/checks.yml` (count its jobs with
  `sed -n '/^jobs:/,$p' .github/workflows/checks.yml | grep -c '^  [a-z0-9-]*:$'`
  or read the file, never a number written here; the class carries digits
  because `tests-3-13` has them, and a class without digits misses that job)
  and
  `.github/workflows/pr-hygiene.yml` (the verification-section gate and the
  deploy-label guard, which is why it listens for `labeled`; its
  rendered job name is the required-check context, so neither its job id may
  change nor a `name:` be added - the file says why). The release path is
  two more workflows, in the next bullet, so `.github/workflows/` holds four
  files. None of the four calls an action from another repository of this
  organisation, and none reads a secret but the run's own token.
- **The release path is `.github/workflows/publish.yml`, and nothing uploads
  from a private repository.** That file's name and its upload jobs'
  environments, `pypi` and `testpypi`, are what the trusted publishers on PyPI
  and TestPyPI are registered against: rename the file or an environment and
  the index refuses the upload. `.github/workflows/release.yml` holds the tag
  checks and is called by it. Read the jobs from the two files, never from a
  list written here. `rehearse` and `publish` run only where the repository
  is public. A session never cuts or pushes a `v*` tag, and never creates an
  environment or a publisher: those are the owner's.
  `.github/allowed_signers` names the key a release tag is signed by, and a
  tag signed by a key it does not name does not verify.
  The version is written twice, in `pyproject.toml` and as `__version__` in
  `src/crosslink/__init__.py`, and they move together: the `build` job
  refuses a wheel where they differ.
- **Every `check_*.py` under `scripts/` is a vendored copy,** with its
  self-test and its requirements file where it has them. Never edit one here.
  Each is the file this organisation's other public repositories carry under
  the same name (compare blob ids with `dagster-dex`'s `scripts/`), so a
  local edit is drift, and a defect in one is fixed at its source and
  vendored again.
  `scripts/adr_preconditions.py` is this tree's own: it reads `docs/adr/` and
  this tree's citations of those records, and nothing else.
- **The suite imports `ration`,** from the release the public
  `catincloud-labs/ration` uploads to PyPI. `pyproject.toml`'s `service`
  extra pins the distribution `catincloud-ration`, which imports as `ration`,
  to one exact version (`pyproject.toml` says why an index requirement),
  `tests/test_serve.py` and `tests/test_produce.py` import it, and both
  `tests` jobs install the extra from the package index, with no
  credential. There is no skip: a suite that cannot import the codec the
  comparer runs is red.
- **`src` is held to a coding standard, read by
  `scripts/check_power_of_ten.py`** in the `power of ten` job: cyclomatic
  ceiling 15, the type checker's default, no recursion, no `while True`, no
  `global`, no blind `except`. The check is the **one reader of
  suppressions**: a deviation is a `noqa` or a `type: ignore[code]` that
  names the rule with its reason on the same line, and one that is unused or
  gives no reason is red.
- Enable the hook per clone - it does not install itself:
  `git config core.hooksPath .githooks`. `scripts/check_hook_mode.py`, in the
  `closing keywords` job, refuses a tracked `.githooks/commit-msg` whose
  index mode is not `100755`, the mode git on Linux and macOS needs to run
  it.
- Markdown is linted by the `markdown` job with `.github/markdownlint.json`,
  passed by path. Two rules are off, both deliberately: `MD013` (line length)
  and `MD041` (first line must be a top-level heading). `MD041` is off
  because the GitHub templates under `.github/` correctly do not start with
  an H1 - the PR or issue title is the heading - and that is the shape GitHub
  expects, not a defect to fix. A `.markdownlint.json` at the root would not
  be read: the config is named on the command line.
- **A false comment in a code or configuration file is rewritten, and its
  old text is cut.** This covers a comment or a docstring in any file that is
  not Markdown: `.py`, `.toml`, `.yml`, `.sh`, `.json` and the like. When one
  is found false, the change that finds it rewrites it to what is true at
  `main` and deletes the old text. The old text is not kept beside the new,
  under a marker or as a correction in place (*this used to say*), and it is
  not moved to `CHANGELOG.md` or any other history home: it stays in git
  history, and the pull request that rewrites it says in its body what was
  cut. A `.md` file is a document, and a false sentence in one follows
  *Living documents and records* below instead. A vendored `check_*.py` under
  `scripts/` is not edited here, so a false comment in one is cut at its
  source and vendored again. A marker or an in-place correction in any other
  file that is not Markdown is rewritten by the next change that touches its
  sentence, by the same rule. This lists the markers written with the word
  `DEAD`, from anywhere in the checkout, and prints nothing when there are
  none: `git grep -n -w DEAD -- ':/' ':(top,exclude)*.md'`. A correction
  written in prose has no fixed form, and no command lists it.
- **This repository's records,** for *Living documents and records* below,
  are the accepted ADRs in `docs/adr/` (not `0000-template.md`) and the
  entries of its history homes: `CHANGELOG.md`, and any `*.history.md` that
  is tracked.

## This repository is ASCII

**No em-dash, no emoji, no character above U+007F, in a tracked file or in
its name.** Guarded by `tests/test_ascii_only.py`, which reads the working
copy of every file `git ls-files` reports, so it holds for files nobody has
written yet, once they are tracked.

Two reasons, and they fail differently:

- **Encoding.** An exception message, a log line and a command's output are
  read in terminals whose encoding nobody here controls. A character that a
  browser renders is not thereby one a console at cp1252 prints.
- **Register.** This tree is written to be read by strangers. Em-dashes and
  severity emoji are a recognisable machine-written signature, and a package
  asking to be read should not carry one.

Use `-` for an em-dash, or restructure: a colon, a comma or parentheses
usually say it better. Use `->` or `=>` for an arrow and `...` for an
ellipsis. A string that has to hold such a character, as a test of non-ASCII
input does, writes it as an escape.

The test skips a tracked path that matches one of four patterns, held in its
code. A published copy of this tree tracks no path they match, and the test's
docstring gives the command that shows it. It skips nothing by file type.

## Living documents and records

- **Every tracked document is a record or living.** A record is an accepted
  ADR, an entry in a history home, a dated snapshot, or a document whose own
  `Status:` says frozen. A history home's lead, which says what the file
  holds, is living; its entries are the record. Every other tracked document
  is living. A document here is a `.md` file; a comment or docstring in any
  other file is code, and a false one follows the rule in *Repo conventions*
  above: rewritten, its old text cut, nothing moved to a history home.
- **A living document states the present.** When a sentence in one is found
  dead, the change that finds it rewrites the sentence to what is true at
  `main`. In the same commit, the dead text moves to the document's history
  home as a blockquote, under a heading that names the document and the
  section it came from, with the date it was read and what it was read
  against. It moves verbatim, except that line breaks may be joined and
  leading indentation a blockquote cannot carry is dropped. A caution that
  goes false is a dead sentence like any other.
- **The history home is `CHANGELOG.md`,** unless a `<name>.history.md` is
  tracked beside the document, which is then its home.
- **A marker is written only in a record,** whose text is not rewritten. It
  opens its own line with `**DEAD YYYY-MM-DD.**`, the date it was read, then
  what it was read against and what killed the clause. It states the past
  only: the past tense for the world, the present only for what a named
  commit or test holds and what the marker quotes, and no forecast (*yet*,
  *until*, *next*). A clause takes at most one marker: a clause in an ADR
  that dies again is a superseding ADR's work, as a dead decision always is.
- **A living document carries no marker.** A sentence there is either true or
  rewritten, so a correction in place (*this used to say*) is the thing this
  section replaces.

## The owner's workstation

This repository is authored on the owner's Windows workstation, with Git Bash
and Windows PowerShell 5.1 side by side. Each trap below was read there on
2026-10-12 and has been paid for at least once; re-read one before relying on
it.

- **A command handed to the owner runs in either shell.** One command per
  block; paths as `C:/...`; no `&&`, `||`, `;` chains, `$VAR`, `$(...)`,
  heredocs, `2>/dev/null` or line continuations. A command that needs Git Bash
  says so on the line above it, or comes with its PowerShell twin. A Windows
  command with `/flag` arguments (`schtasks`, `reg`) is marked as PowerShell. A
  handed-over `gh` command names `--repo <owner>/<repo>`, and a handed-over
  `ssh` command reaches one host.
- **Never run `python -`,** which reads its program from standard input. Here
  it can hang until it is killed, with an empty heredoc or `</dev/null` as its
  input, or end silently having done nothing, and a script fed to it is
  decoded as cp1252. A Claude Code hook on the workstation refuses its plain
  spellings, including those with interpreter options before the `-`
  (`python -I -`, `python -X utf8 -`), which hang the same way. It misses
  others, such as one quoted inside another command (`bash -c 'python -'`) or
  one whose `-` is on a continued line. Write a script,
  a commit message or a pull request body to a file and use it by path
  (`python <file>`, `git commit -F <file>`, `gh pr create --body-file <file>`).
  A heredoc through an agent's shell can halve backslashes, so text that holds
  one goes through a file too.
- **Git Bash rewrites path-shaped arguments.** Set `MSYS_NO_PATHCONV=1` on the
  one command that passes a `rev:path`, a `/`-leading pattern or a `/flag`.
  Never export it: it breaks `/c/...` paths for the rest of the shell. A
  rewritten argument fails quietly, so a probe through it can print an empty
  answer that looks real.
- **Git Bash `grep` cannot see a carriage return,** so a CR count from it is
  wrong in either direction. Check line endings with `git ls-files --eol` or a
  byte count in Python, and have Python write LF explicitly: bytes, or
  `newline` set to a line feed.
- **`jq` is not installed** (read 2026-10-13: `jq --version` prints an error
  in either shell, where `python --version` prints a version; `command -v jq`
  is no check in PowerShell, which runs it as `Get-Command -Verb jq` and
  prints nothing whether or not the tool exists). `gh --jq` works
  because it is built into `gh`; everything else filters with `--jq`, `grep` or
  Python.
- **Python's default encoding here is cp1252,** so Python that prints
  non-ASCII runs as `python -X utf8`. A PowerShell 5.1 `Get-Content` and
  `Set-Content` round trip turns LF into CRLF, and mangles UTF-8 once either
  side names an encoding: never round-trip a tracked file through it.
- **An agent's permission layer may refuse an act** (a secret read, an `ssh`, a
  merge, a scheduled task). Do not retry it in another form: hand the owner the
  exact command, one per block, and read the result back after it runs.

## State

The read side under `src/crosslink/` shares its origin with the public
`dagster-dex`, and nothing imports across the two;
`src/crosslink/PROVENANCE.md` says what is shared and how to see it. This
repository holds that code as its own source and not as a dependency:
`pyproject.toml` requires no `dagster-dex` distribution.

Tier 3 is declared and deliberately unimplemented.

`docs/design/` holds this repository's design documents. A document there
**describes and never decides**: every decision it touches cites the record
that made it. Its `Reviewed:` line reads as *when it was last judged*, never
as *current*, and a change that falsifies a claim in one edits the page in
the same pull request (`docs/design/README.md`). List the directory for what
exists.

CI runs the suite on every pull request and every push to `main`, from
`.github/workflows/checks.yml`.

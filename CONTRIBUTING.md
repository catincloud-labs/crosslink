# Contributing

This document is short by design - it describes how work is done here, and
stops where the tooling stops.

## Getting set up

```bash
git clone https://github.com/catincloud-labs/crosslink.git
cd crosslink
```

Commits from this repository should author as **you**. If the global git
identity on this machine is not the one you want on this work, set it
per-clone rather than changing your global config, which other repositories
depend on:

```bash
git config --local user.name  "Your Name"
git config --local user.email "you@example.com"
```

## Running the tests

```bash
uv run --frozen --python 3.12 --extra test --extra service pytest -q
```

`--extra test` uses the `test` extra declared in `pyproject.toml` rather than
injecting pytest ad hoc, `--frozen` runs against the committed `uv.lock`
without re-resolving, and `--python 3.12` is the floor `pyproject.toml`
declares. CI (`.github/workflows/checks.yml`) runs this same command in its
`tests` job, so the local run is the same run - an unpinned environment
would make the two quietly diverge, which is why `--frozen` is not optional
here. A second job, `tests (3.13)`, runs it with `--python 3.13`.

`--extra service` pins `catincloud-ration`, the distribution the public
`catincloud-labs/ration` uploads to PyPI, to one exact version
(`pyproject.toml` names it, and says why). It imports as `ration`.
Resolving it needs no credential.
Without the extra, `tests/test_serve.py` and `tests/test_produce.py` fail
to collect. That is a red and
not a skip, on purpose: a suite that cannot import the codec the comparer
runs has not exercised the comparer.

## Workflow

1. **Branch off `main`.** One logical change per branch, even when several
   small fixes surface in the same session. Do not stack branches without a
   real dependency between them - a stacked branch makes a red check ambiguous
   about which change caused it.
2. **Conventional commit subjects** (`feat:`, `fix:`, `docs:`, `chore:`, ...),
   with a body explaining why, not just what.
3. **Open a PR as a draft,** with `gh pr create --draft`. The template asks how
   the change was verified; answer it with the command and its output rather
   than a summary of the output.
4. Never commit directly to `main`.

### The auto-close trap

GitHub's reference parser closes an issue when a closing verb (`close`, `fix`,
`resolve`, and their variants) is immediately followed by `#N`, anywhere in a
commit message or PR body. It does not read the surrounding sentence, and a
code span does not protect it - a line explaining that you are *not* closing
`#N` will close `#N`.

Only adjacency fires. Write "part of #N" or "refs #N". When you do intend to
close something, say so explicitly in the `Autoclose:` trailer of the PR body,
so the effect is stated as data rather than inferred from prose.

The `closing keywords` check also reads the pull request title, and refuses
a closing verb before a number there even when the close is meant. The title
becomes the merge commit's message and holds no trailer, so a close you mean
goes in the PR body, with its `Autoclose:` trailer.

## Filing something

Two issue templates exist:

- **Change or chore** - proposed work.
- **Defect or finding** - something is wrong, or a check does not do what it
  claims.

The second asks what would tell you if the thing silently stopped working.
That question is the point of the template; if the honest answer is
"nothing", that is the most important line in the report. The first asks the
same of a change before it is made: how we would know it worked.

## Releases

A release is the owner's to cut, and no pull request cuts one. `README.md`,
*Releases*, says what a release is and how to check one, and
`git tag -l 'v*'` lists the tags that exist.

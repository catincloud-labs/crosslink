# crosslink

A project format reduced from an orchestrated asset graph - and the write path
back to it.

Copyright 2026 David Anaya. Apache-2.0.

## What this is

Modern transformation tooling assumes a project is a directory of files. An orchestrated
asset graph is not that - it is a live object graph whose source of truth is the code
that builds it. The two describe the same warehouse and cannot read each other.

Reducing the graph into something a project-shaped consumer can **read** is
solved, and that reduction is half of what this package contains. The way
back is the harder half: when a consumer wants to change something, the
change cannot be applied to the reduction, because the reduction is
regenerated from code. So a change is proposed against the code (ADR-0002)
and verified against the reduction it claims to change (ADR-0003); the
Status section below says which steps of that path are built.

Closing that loop is what this repository is for. The interesting property is that the
two halves need each other - the reduction is what makes a proposed change *checkable*.
Apply a candidate change, rebuild, re-reduce, and compare against the delta you asked
for. The read side is the acceptance test for the write side.

## What it offers, and what it does not

Three things: the package; the contract a project format is judged by,
`crosslink.conformance`, with the formats built to fail it,
`crosslink.conformance_calibration`, shipped beside it; and the suite under
`tests/`.

The calibration is evidence about the contract, not about your format: it
shows the contract refusing three formats that are wrong on purpose. A format
conforms only when the contract has judged that format. Where this README and
the contract disagree, the contract and its calibration are right.

No guarantee and no support are promised. The write path ships as a mechanism,
and nothing here says what it will do against a repository of yours.

## Installing

The distribution is named `catincloud-crosslink`, and it imports as
`crosslink`:

```bash
pip install catincloud-crosslink
```

**Do not `pip install crosslink`.** That name on PyPI belongs to an unrelated
project, which installs a top-level `crosslink` package of its own, so the two
cannot share an environment and the wrong one imports without complaint.

The command above installs the newest release. The project's page on PyPI,
<https://pypi.org/project/catincloud-crosslink/>, lists every release that
has been uploaded.

To install the tree as it stands at a commit, which is not a release,
install from a clone:

```bash
git clone https://github.com/catincloud-labs/crosslink.git
cd crosslink
pip install .
```

## Status

The read side is in place and passes its suite - and so is every step of the
write path `docs/ROADMAP.md` sequences: reduction, self-consistency findings,
the typed delta, the oracle harness, bounded patch generation, and the delivery
adapter that renders a verified proposal as a pull request. What is still not
implemented is the format-side half of tier 3: no format yet *receives* an edit
through `propose_edits()`. The machinery that produces and proves a proposal
exists; the contract it would hand the proposal to is declared only.

| tier | contract | state |
| --- | --- | --- |
| 1 | `declarations()` - what the project declares | implemented - `DagsterProject`, `DbtProject` |
| 2 | `+ fingerprint()` - what it looks like right now | implemented - both formats |
| 3 | `+ propose_edits()` - what may be written back | **declared only** - no format serves it |

Tier 3 is the point of the project and is deliberately the last thing standing.

## Records

Design decisions live in `docs/adr/` - immutable once merged; to change one,
add a new record that supersedes it and link both directions. Each record
carries a `## Do not implement until` section, and its checkboxes are
load-bearing: the `adr preconditions` check refuses a citation of a record
whose boxes are open, so tick one only when the named observable has been
observed.

The four records under `docs/adr/` were reworded once, on 2026-11-11, for
publication: passages that pointed at private history were cut or rewritten,
characters outside ASCII were replaced, and no status, decision or constraint
changed. Each record says so in a dated note at its head, and the originals
stand in the private repository's history.

A bare `ADR-NNNN` in this repository names a record in **this** `docs/adr/`.
A record in another repository's corpus is always cited with its repository
named.

## Layout

```text
src/crosslink/
  __init__.py      the package surface - what `import crosslink` exports
  model.py         the neutral project model
  protocol.py      the tiered seam - tier 3 is declared here
  context.py       how a project is located and built
  declarations.py  declared keys, joins, semantics, sources
  project.py       reduction from an asset graph - DagsterProject
  dbt.py           the second format - DbtProject, tiers 1 and 2
  conformance.py   an importable contract for project formats
  conformance_calibration.py  formats built to fail that contract, shipped beside it
  findings.py      self-consistency findings, computed from one snapshot
  delta.py         the typed delta between two declaration snapshots
  verify.py        the oracle harness: sandbox apply, re-reduce, compare
  generate.py      bounded search against the oracle; the proposer is a callable
  deliver.py       a verified proposal rendered as a pull request, or as files
  wire.py          the versioned envelope and the fingerprint payload it carries
  service.py       the comparer: two envelopes in, a drift verdict out
  serve.py         the comparer as a process: framed fingerprints in, verdicts out
  produce.py       the producer as a process: a graph reduced, published, framed, posted
  PROVENANCE.md    what this shares with dagster-dex, and what each left out
tests/
docs/
  adr/             the records
  design/          what the subsystems look like today
  ROADMAP.md       what is built, what is decided, what is parked
```

Derive the list rather than trusting it - `git ls-files src/crosslink docs` -
and read a module's own docstring for what it is; the glosses above are those
docstrings' first sentences, shortened.

The read side shares its origin with the public `dagster-dex`, and depends on
it nowhere - see `src/crosslink/PROVENANCE.md` for what is shared and how to
see it.

## Releases

The first release was cut on 2026-11-11. `git tag -l 'v*'` in a clone lists
the release tags, the PyPI page *Installing* links lists the uploads, and
`gh release list --repo catincloud-labs/crosslink` lists the GitHub
releases. *Installing*, above, says how to install one.

A release is a signed `v*` tag, the upload of that tagged tree to PyPI as
`catincloud-crosslink`, and the GitHub release for the tag.
`.github/workflows/publish.yml` makes the upload and the GitHub release, from
the tag and from nothing else, only after all of these have passed in the same
run:

- `.github/workflows/release.yml`, which it calls, has verified the tag's SSH
  signature against `.github/allowed_signers`, read the tag's name as exactly
  `v` and the version `pyproject.toml` carries at the tagged commit, and run
  the suite there;
- `.github/release/check-dist.py` has read the wheel and the sdist it is about
  to upload: the distribution's name, its licence expression, no requirement
  that names a URL, and the package's own `__version__` equal to the wheel's;
- the stranger-shaped projects in `.github/strangers/` have judged that wheel
  from a fresh environment: each format built to fail the contract fails
  exactly the arms its defect is for, and a correct one passes them all.

Each of those checks is also run on inputs built wrong on purpose, on every
pull request and before every release, and the run fails unless each one is
refused. Each uploaded file carries a PEP 740 attestation. After the upload
the same run reads each file's provenance back from the index, and a
provenance that names any publisher but that workflow, in this repository, in
its `pypi` environment, turns the run red and withholds the GitHub release.
The version in `pyproject.toml` at a commit no tag names is not a release.

A release installs as *Installing* says, by the distribution name and never
by the bare one. To judge a format of your own against the contract, install
the `conformance` extra:

```bash
pip install "catincloud-crosslink[conformance]"
```

It adds pytest, the one dependency of the contract the package ships as
`crosslink.conformance`; without it that module does not import.

A tag is checked from a clone at that tag, with the scripts the workflow runs:

```bash
bash .github/release/verify-tag.sh <tag> .github/allowed_signers
bash .github/release/check-version.sh <tag>
```

A bare `git verify-tag` is not the same check: it passes a signature made for
another tag and moved to this one. The first script's exit 0 shows that a key
`.github/allowed_signers` names signed a tag object carrying this tag's own
name. That file travels in the same tree as the tag it vouches for, so it says
nothing on its own about who holds the key.

The metadata says `Development Status :: 3 - Alpha`, and it means it: while
the major version is 0, a release may change what the contract decides.

## Running the tests

```bash
uv run --frozen --python 3.12 --extra test --extra service pytest -q
```

That is the command CI's `tests` job runs, against the tracked `uv.lock`
(`.github/workflows/checks.yml`). The `service` extra pins
`catincloud-ration`, the distribution the public `catincloud-labs/ration`
uploads to PyPI and which imports as `ration`, to one exact version. It needs
no credential. Without the extra, `tests/test_serve.py` and
`tests/test_produce.py` fail to collect, which is a red rather than a skip on
purpose: a suite that cannot import the codec the comparer runs has not
exercised the comparer.

Where there is no project environment to freeze, the same suite runs with
versions named on the command line, which are not the lock's:

```bash
uv run --no-project --python 3.12 --with-editable . --with pytest==8.4.1 \
    --with 'catincloud-ration==<version>' \
    python -m pytest tests -q
```

`<version>` is the one `pyproject.toml`'s `service` extra names. Never a bare
`--with ration`, which takes PyPI's unrelated project of that name. This form
re-resolves everything else, so it bypasses the lock that `CONTRIBUTING.md`
calls mandatory: it is the recipe for a machine with no checkout to trust,
not a second way to run CI.

Nothing orchestrator-side is installed by either form, and that is the point: the package imports
no orchestrator at all. `from_asset_graph` is duck-typed, so the coupling is to a shape
rather than to a distribution. If a future change makes the suite need an orchestrator to
pass, that is a coupling worth noticing rather than absorbing.

## Running the comparer

The long-lived half of the wire is `crosslink.serve`: a
process that holds the last accepted fingerprint envelope as its standing
objective and answers framed envelopes with drift verdicts, one JSON line per
request on stdout. It needs the `service` extra, because it decodes the frame
before the envelope and the frame codec lives in `ration`.

```bash
uv run --frozen --extra service python -m crosslink.serve \
    --sender example --baseline ./baseline.json --bind 127.0.0.1:8100
```

`--sender` names each producer the process keeps a sequence ledger for (the
`POST` path is `/<sender>`); `--baseline` is where the accepted bytes are
kept so that a restart does not re-baseline, and its directory has to exist
and be writable or the process refuses to start; `--bind` defaults to
loopback. Where it runs, and behind what, is its deployment's to decide: the
module offers no TLS and no authentication, and its docstring says so.

## Running the producer

The other half is `crosslink.produce`: one run reduces an asset
graph, publishes its payload digest to a topic in a `ration` store, frames
the envelope at the start of the epoch that publication returned, and posts
it to a comparer. It writes one JSON line and exits; the cadence belongs to
whoever deploys it.

The reduction can be watched with no store and no comparer. The suite's own
graph is four definitions and a carve (`tests/test_produce.py`), and
`--dry-run` reduces it and prints the line:

```bash
PYTHONPATH=tests uv run --frozen --python 3.12 --extra test --extra service \
    python -m crosslink.produce \
    --load test_produce:GRAPH --carve test_produce:carve \
    --name example \
    --publish-topic example-fingerprint --publisher example-producer \
    --post http://127.0.0.1:8100/example --dry-run
```

`--load` names the graph and `--carve` a function of the reduced tree's own
that drops the definitions it does not want fingerprinted; both are module
paths passed as arguments, so the source names no module of the tree it
reduces. The line that comes back says `"event": "reduced"` and counts three
models; drop `--carve` and it counts four. `--declared`, `--semantic` and
`--sources` each name a directory of `*.yml` declarations, read by filename
stem.

A run without `--dry-run` needs three more things: the tree it reduces on
`PYTHONPATH`, `RATION_DSN` in the environment, and a Postgres driver
(`psycopg`) that neither this package nor `ration` declares as a dependency. Without the
driver a real run stops at the store with `ModuleNotFoundError`, after the
reduction. The suite does not prove that path: it injects
`ration.memory.MemoryStore`.

## Naming

Three names, and they are not interchangeable:

- **`crosslink`** is the repository and the import name.
- **`catincloud-crosslink`** is the distribution name, the one to install.
- **`crosslink` on PyPI** is someone else's project. See *Installing*.

# Security policy

## Reporting a vulnerability

**Use GitHub's private vulnerability reporting**, from the *Security* tab of
this repository, or directly at
[Report a vulnerability](https://github.com/catincloud-labs/crosslink/security/advisories/new).
That opens a private advisory only the maintainer can see. Please do not open
a public issue for a security problem: an issue is world-readable the moment
it is filed, and it cannot be made private afterwards.

There is deliberately **no email address here.** A published address is
permanent and gets harvested; private reporting gives the same channel without
one.

## What to expect

This is maintained by one person. I aim to acknowledge a report within **a
week**, and I would rather say that plainly than publish a response time I
cannot hold to. If a report is valid I will work with you on a fix and credit
you in the advisory unless you would prefer otherwise.

There is no support commitment beyond that, and no long-term support branch.
The README says what this package offers and what it does not.

## The surface, stated honestly

The most useful thing this file can do is tell you where to look rather than
assert that it is safe.

- **The library parses YAML you supply** (declaration, semantic and source
  documents, and the files of a dbt project you point it at) with
  `yaml.safe_load`. The package root imports neither `crosslink.serve` nor
  `crosslink.produce`, nor the frame codec they use.
- **`crosslink.serve` binds a socket and decodes bytes another node sent.**
  That is the network-facing surface. A request is judged in a stated order,
  frame before envelope before comparison, and its module docstring gives
  that order and every refusal. The address it binds is `DEFAULT_BIND` unless
  the deployment passes another, and a body larger than `MAX_BODY_BYTES` is
  refused; both are in `src/crosslink/serve.py`. It has **no TLS and no
  authentication**: the frame gives integrity, ordering and versioning, and
  securing the network it crosses is the deployment's. The sender segment of
  the path is addressing, never a credential. A restart forgets the sequence
  ledgers, so a replay against a restarted comparer is not caught; the
  docstring states that cost. The one file it keeps is the baseline, at the
  path it is given, written through a temporary file beside it.
- **`crosslink.produce` imports the modules you name** with `--load` and
  `--carve`, so whoever controls its command line controls an import. It
  reads the store's DSN from the `RATION_DSN` environment variable per run
  and writes it nowhere, connects to that store, and sends one `POST` to the
  address given as `--post`.
- **`crosslink.deliver` runs `git` as a subprocess,** in an ephemeral clone,
  under whatever identity the environment already carries. No parameter in
  that module accepts a credential: the forge half of a pull request is a
  callable you supply. Its other mode writes files into a directory you name,
  and refuses one that is not empty.

If you find any of the above to be untrue, that is itself worth reporting.

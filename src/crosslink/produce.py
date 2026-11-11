# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The producer as a process: one reduction of a live asset graph, published, framed and posted.

:mod:`crosslink.serve` is the comparer that answers framed fingerprints; this
module is what sends them, from beside the tree it reduces. One invocation
is one run and one frame. The cadence -- once at start and then on a
schedule, say -- is the deployment's to keep, so "at start" and "daily" are
the same command line.

## One run, in order

1. **Load.** ``--load MODULE:NAME`` names the iterable of asset definitions,
   imported by path. The module path is an argument, never a literal here:
   the producer lives in this repository and runs beside the tree it
   reduces, so that tree does not depend on this package, and this package
   names the tree only where a deployment passes it in.
2. **Carve.** ``--carve MODULE:NAME``, optional, names a callable applied once
   to the loaded iterable. It is for a tree that defines more than it
   wants fingerprinted, such as a graph holding another project's models:
   without the carve the fingerprint carries those models too, and it differs
   by design from any reduction that leaves them out
   (``tests/test_produce.py`` shows both). The carve is the tree's rule and is
   applied by the tree's function, so there is one statement of it, and it is
   not here.
3. **Reduce.** :meth:`~crosslink.project.DagsterProject.from_asset_graph`,
   with ``--declared``, ``--semantic`` and ``--sources`` each read one
   way: ``*.yml`` directly under the directory, sorted, as
   ``{filename stem: text}``, UTF-8 with universal newlines. Anything else
   that reduces the same graph has to read the same inputs the same way, or
   two reductions of one graph measure their readers instead of the graph. A
   directory that is named and
   missing refuses the run: silently reading it as empty would ship a
   fingerprint whose ``sources`` layer vanished because of a mount.

   **Read, and not cross-checked.** This reduction does not check a
   declaration file against the graph, and it does not check the carve's
   result. A declaration for a model the graph lacks moves the digest, one
   filed under the wrong stem reduces byte-identically to the same
   declaration filed correctly, and a surviving model may depend on a carved
   one. Keeping those states out is the reduced tree's own suite's work; the
   producer does not refuse them itself.
4. **Publish.** The envelope's payload digest, to ``--publish-topic``, through
   ``ration.publish.publish``, fenced from the generation ``current`` reads,
   as the writer ``--publisher`` names. **The generation it returns is the
   frame's epoch** -- the source ``ration.frame``'s docstring names: the
   store's version is monotonic per key and never reused,
   so every run's epoch is above every earlier run's without this process
   persisting anything, and a frame from any earlier run is
   ``sequence-replayed`` at the comparer. Every run publishes, an unchanged
   graph included; the pointer advancing with every run is a liveness signal, and a
   publisher succeeding itself is the routine case ``publish.py`` is built
   around. A refusal is not retried (``publish.py``: the move after a refusal
   is a decision, not a loop); with one producer it is a topology fact, and
   the run ends ``superseded`` without framing anything.
5. **Frame and post.** ``Sequence.start(epoch)``, kind ``FINGERPRINT``, one
   ``POST`` to ``--post``. No retry within a run: the next run is a fresh
   epoch, and the comparer accepts it whatever became of this one's.

## What the run says

Every run that reduces and then stops (``--dry-run``) or reaches its store
writes exactly one JSON line on stdout, and exits with a status that says
whether the comparer took the frame: ``reduced`` for
``--dry-run`` (exit 0); ``answered`` with the comparer's ``status`` and its
``answer`` (exit 0 only on 200 -- a ``drift`` verdict is the comparer's news,
not a producer failure); ``superseded`` and ``unreachable`` (exit 1). The line
carries counts, layer names and digests, never a model name: the comparer's
lines keep the body out, and so do these. A reduction that raises -- an
import that fails, two assets reducing to one name -- raises here too, as a
traceback and no line: the graph is this process's own input, and the encode
posture applies. So does a store that cannot be used, after the reduction and
before anything is framed: ``Unreachable`` propagates, as ``publish.py``
propagates it so that a store that is gone never reads as a topic never
published, and so does a missing driver's ``ImportError``.

**One line is what this process writes, not what the stream holds.**
Importing the tree may print lines of its own to stdout, and a tree is free
to do that on purpose. A reader finds this process's line by parsing it,
never by position.

The request says nothing about which software sent it. ``User-Agent`` is
``producer/1``, the comparer's ``server_version`` convention, rather than the
standard library's default, which names the interpreter; the envelope already
carries only ``producer_version``.

## The store, and what the suite cannot prove

``RATION_DSN``, from the environment, read per run and written nowhere. Unset
refuses the run unless ``--dry-run``, and does not disarm it: without a
store this process has no epoch, and a frame with an invented epoch is the
defect the comparer's ledger exists to refuse. ``ration.postgres`` is imported
only when a store is opened, because its driver is a dependency of neither
``ration`` nor this package's ``service`` extra: whoever deploys the producer
installs it, and the suite injects ``ration.memory.MemoryStore``.
What the stub cannot prove -- a real store answering -- is a deployed run's to
prove, in its first line, or in the traceback that stands in its place
(above).

The epoch inherits one hazard, stated where the comparer states it: a store
that loses its data restarts
generations below what the comparer ledgered, and every frame is
``sequence-replayed`` until the comparer is restarted by hand.
``crosslink.serve``'s docstring prices that remedy.

## Deliberately absent

A schedule or a loop (the deployment's), retries (above), TLS and
authentication (the frame is integrity, ordering and versioning, and securing
the network it crosses is the deployment's), and an object-store copy of the
envelope: the pointer's artefact is the payload digest, and the bytes cross
in the frame.
"""

from __future__ import annotations

import argparse
import http.client
import importlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import IO, Any

from ration import frame as framing
from ration import publish

from .project import DagsterProject
from .wire import Envelope, encode_envelope, fingerprint_envelope

__all__ = [
    "DSN_VARIABLE",
    "EVENT_ANSWERED",
    "EVENT_REDUCED",
    "EVENT_SUPERSEDED",
    "EVENT_UNREACHABLE",
    "POST_TIMEOUT_SECONDS",
    "USER_AGENT",
    "main",
    "post",
    "publish_epoch",
    "read_declarations",
    "reduce_graph",
    "resolve",
]

# The four lines a run that reduces can end on, one per `event`.
EVENT_REDUCED = "reduced"
EVENT_ANSWERED = "answered"
EVENT_SUPERSEDED = "superseded"
EVENT_UNREACHABLE = "unreachable"

# The environment variable that names the store.
DSN_VARIABLE = "RATION_DSN"

# Not the interpreter, and not a product name: the comparer's convention.
USER_AGENT = "producer/1"

# The comparer holds a stalled request's thread for 30 s; this side waits as long.
POST_TIMEOUT_SECONDS = 30.0

# How much of a non-HTTP listener's first line an `unreachable` line carries.
_DETAIL_LIMIT = 200

# MODULE:NAME -- a dotted module path and one attribute of it.
_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_SPEC = re.compile(rf"({_IDENTIFIER}(?:\.{_IDENTIFIER})*):({_IDENTIFIER})")


def resolve(spec: str) -> Any:
    """The object ``MODULE:NAME`` names, imported. Raises what the import raises."""

    match = _SPEC.fullmatch(spec)
    if match is None:
        raise ValueError(f"{spec!r} is not MODULE:NAME")
    return getattr(importlib.import_module(match.group(1)), match.group(2))


def read_declarations(directory: Path | None) -> dict[str, str]:
    """``{filename stem: text}`` for every ``*.yml`` directly under ``directory``, sorted.

    ``read_text``'s universal newlines normalise a CRLF checkout to LF on
    the way in, which is part of the reading the module docstring states.
    ``None`` -- the flag not given -- is no declarations.
    """

    if directory is None:
        return {}
    return {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(directory.glob("*.yml"))
    }


def reduce_graph(
    assets: Iterable[Any],
    *,
    name: str,
    declared: Mapping[str, str],
    semantic: Mapping[str, str],
    sources: Mapping[str, str],
) -> Envelope:
    """The v1 fingerprint envelope for a graph and its three declaration inputs."""

    project = DagsterProject.from_asset_graph(
        assets,
        name=name,
        declaration_sources=declared,
        semantic_sources=semantic,
        source_declarations=sources,
    )
    return fingerprint_envelope(project.declarations(), project.fingerprint())


def publish_epoch(
    store: Any, topic: str, artefact: str, publisher: str
) -> tuple[int, int | None]:
    """Advance ``topic`` to ``artefact``; ``(generation read, generation published)``.

    The second is ``None`` when the store refused the advance -- something
    published past the reading. ``Unreachable`` propagates, for
    ``publish.current``'s reason: a store that is gone must not read as a
    topic never published.
    """

    standing = publish.current(store, topic)
    read = standing.generation if standing is not None else publish.UNPUBLISHED
    publication = publish.publish(store, topic, artefact, publisher, generation=read)
    return read, publication.generation if publication is not None else None


def _answer_body(raw: bytes) -> object:
    # The comparer answers JSON; anything between the two that does not is
    # reported as the text it sent rather than swallowed.
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", errors="replace")


def post(url: str, body: bytes, timeout: float = POST_TIMEOUT_SECONDS) -> tuple[int, object] | str:
    """``POST`` one frame: ``(status, answer)``, or why nothing answered.

    Any HTTP status is an answer, a refusal included -- the comparer said
    something, and the line says what. Only a request that got no HTTP
    response at all (refused connection, timeout, a name that does not
    resolve, or a listener that answered in something other than HTTP, which
    is what a wrong port looks like) is the string.
    """

    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/octet-stream", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, _answer_body(response.read())
    except urllib.error.HTTPError as error:
        return error.code, _answer_body(error.read())
    except OSError as error:
        return " ".join(str(error).split())
    except http.client.HTTPException as error:
        # Not an OSError, so the clause above misses it. Its text is the first
        # thing the listener sent, whatever that was, so it is bounded.
        return " ".join(f"{type(error).__name__}: {error}".split())[:_DETAIL_LIMIT]


def _open_store(dsn: str) -> Any:
    # Lazy on purpose: see the module docstring for whose driver this needs.
    from ration.postgres import PostgresStore

    return PostgresStore(dsn)


def _emit(out: IO[str], record: dict[str, object], code: int) -> int:
    out.write(json.dumps(record, sort_keys=True) + "\n")
    out.flush()
    return code


def _run(
    args: argparse.Namespace,
    dsn: str | None,
    open_store: Callable[[str], Any],
    out: IO[str],
) -> int:
    assets = resolve(args.load)
    if args.carve is not None:
        carve = resolve(args.carve)
        if not callable(carve):
            raise TypeError(f"--carve {args.carve} names {type(carve).__name__}, not a callable")
        assets = carve(assets)
    envelope = reduce_graph(
        assets,
        name=args.name,
        declared=read_declarations(args.declared),
        semantic=read_declarations(args.semantic),
        sources=read_declarations(args.sources),
    )
    data = encode_envelope(envelope)
    base: dict[str, object] = {
        "project": envelope.project_name,
        "models": len(envelope.payload.models),
        "layers": sorted(envelope.payload.layers),
        "payload_digest": envelope.payload_digest,
        "envelope_size": len(data),
    }
    # `main` refused a missing store unless --dry-run; the second test only
    # says so to the type checker.
    if args.dry_run or dsn is None:
        return _emit(out, {"event": EVENT_REDUCED, **base}, 0)

    read, epoch = publish_epoch(
        open_store(dsn), args.publish_topic, envelope.payload_digest, args.publisher
    )
    base["topic"] = args.publish_topic
    if epoch is None:
        return _emit(out, {"event": EVENT_SUPERSEDED, **base, "read_generation": read}, 1)

    base["epoch"] = epoch
    frame = framing.encode(framing.FINGERPRINT, framing.Sequence.start(epoch), data)
    answer = post(args.post, frame)
    if isinstance(answer, str):
        return _emit(out, {"event": EVENT_UNREACHABLE, **base, "detail": answer}, 1)
    status, body = answer
    record = {"event": EVENT_ANSWERED, **base, "status": status, "answer": body}
    return _emit(out, record, 0 if status == 200 else 1)


def _spec(text: str) -> str:
    if _SPEC.fullmatch(text) is None:
        raise argparse.ArgumentTypeError(f"{text!r} is not MODULE:NAME")
    return text


def _nonempty(text: str) -> str:
    if not text.strip():
        raise argparse.ArgumentTypeError("must not be empty")
    return text


def _url(text: str) -> str:
    parts = urllib.parse.urlsplit(text)
    try:
        # `.port` is where a port that is not a number, or is out of range, is
        # found. Left to the request, it is found after the publication.
        port = parts.port
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{text!r}: {error}") from None
    if parts.scheme not in ("http", "https") or not parts.netloc or port == 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not an http(s) URL")
    return text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m crosslink.produce",
        description=(
            "The producer: reduce an asset graph, publish its fingerprint's digest, "
            "and post the framed envelope to a comparer. One run, one frame."
        ),
    )
    parser.add_argument("--load", required=True, type=_spec, metavar="MODULE:NAME",
                        help="the iterable of asset definitions to reduce")
    parser.add_argument("--carve", type=_spec, metavar="MODULE:NAME",
                        help="a callable applied once to the loaded iterable")
    parser.add_argument("--name", required=True, type=_nonempty,
                        help="the project's name on the wire")
    for flag, what in (("--declared", "keys and joins"), ("--semantic", "semantic models"),
                       ("--sources", "source declarations")):
        parser.add_argument(flag, type=Path, metavar="DIR",
                            help=f"the directory of *.yml {what}, read by filename stem")
    parser.add_argument("--publish-topic", required=True, type=_nonempty, metavar="TOPIC",
                        help="the topic the payload digest is published to")
    parser.add_argument("--publisher", required=True, type=_nonempty, metavar="NAME",
                        help="the writer the publication names, stable across runs")
    parser.add_argument("--post", required=True, type=_url, metavar="URL",
                        help="the comparer's /<sender> URL")
    parser.add_argument("--dry-run", action="store_true",
                        help=f"reduce and encode only: no store, no {DSN_VARIABLE}, no request")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    open_store: Callable[[str], Any] = _open_store,
    out: IO[str] | None = None,
) -> int:
    """``python -m crosslink.produce --load MODULE:NAME --name NAME ... --post URL``.

    Every refusal the command line can earn is decided before the graph is
    imported, which is the slow step: a missing directory or store should not
    cost the tree's whole import first.
    """

    parser = _parser()
    args = parser.parse_args(argv)
    for flag in ("declared", "semantic", "sources"):
        directory = getattr(args, flag)
        if directory is not None and not directory.is_dir():
            parser.error(f"--{flag} {directory} is not a directory")
    env = os.environ if environ is None else environ
    dsn = env.get(DSN_VARIABLE, "").strip() or None
    if dsn is None and not args.dry_run:
        parser.error(
            f"{DSN_VARIABLE} is not set: the frame's epoch is the publication's "
            f"generation, so a run with no store has nothing to frame with "
            f"(--dry-run reduces without one)"
        )
    return _run(args, dsn, open_store, out if out is not None else sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())

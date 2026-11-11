# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The comparer as a process: a long-lived entry point that answers framed fingerprints.

:mod:`crosslink.service` decides what a service *does* with two envelopes and
holds no state; this module is the process around it. It binds an address,
holds the standing objective, and answers one ``POST`` at a time. Nothing in
the library imports it: the package root stays YAML-only, and the frame codec
this module needs arrives through the ``[service]`` extra (``pyproject.toml``
says what that extra pins, and why).

## The order, and why the order is the contract

A request is judged in three layers, in a stated order, and each layer's
refusal is its own:

1. **The frame** (``ration.frame``): decoded against the sender's ledger
   before anything looks at the body. A frame refusal --
   ``truncated``, ``crc-mismatch``, ``sequence-replayed`` and the rest --
   answers 400, and the body is never parsed. The ledger is per sender, keyed
   by the ``POST`` path's one segment, and the set of senders is the caller's:
   a segment naming no configured sender is refused as ``unknown-sender``
   before the frame is read, so a stranger cannot allocate ledgers by
   inventing names.
2. **The envelope** (:mod:`crosslink.wire`; ADR-0004): the frame's body,
   decoded only once the frame passed. ``malformed-envelope``,
   ``digest-mismatch`` and the rest answer 422.
3. **The comparer** (:func:`crosslink.service.observe`): the envelope against
   the standing objective. ``identity-mismatch`` answers 422; a verdict
   answers 200.

**Every refusal and every verdict is one JSON line on stdout, and the line
carries ``layer`` as a field of its own.** The failure this is for is a
``crc-mismatch`` and a ``digest-mismatch`` landing as one signal in the log
record. Here they differ in two fields, ``layer`` and ``control``; and
``unknown-payload-kind`` -- the one control name the frame, the envelope and
this module all use -- is told apart by ``layer`` alone, never inferred from
the control. The body is never logged: a refusal's ``detail`` is the codec's
own prose, which carries header numbers only.

One refusal here moves state, and it is stated rather than discovered: a
frame of a kind the registry names but this comparer does not serve (an
``explore-*`` kind) has passed every frame check, so the frame's own rule
applies and its sequence is consumed. The sender's next frame is the following
count. Every other refusal leaves the ledger and the baseline exactly as they
were.

## The baseline is bytes, and it is on disk

The standing objective is the last **accepted** envelope, kept as the exact
bytes that arrived and written to ``baseline_path`` before the verdict is
answered -- so a restart starts from the objective it had rather than from
nothing, and the first ``POST`` after a restart is a ``no-drift``, not a
``baseline``. A refused request never touches it. The write is a temp file
beside the target and ``os.replace``, so a crash mid-write leaves the old
baseline whole rather than half of a new one. A baseline file that does not
decode refuses to *start* rather than being ignored: the comparer's own state
is its own data, and a wrong one raises (the encode posture), because a
silent re-baseline is the failure persisting the file exists to prevent. Delete
the file by hand to mean a fresh baseline; a baseline path whose directory
does not exist, or is one this process cannot write in, refuses to start for
the same reason, at start and not at the first verdict. The second is probed
with the write a verdict makes -- a temp file created beside the target and
removed -- not inferred from permission bits. Without the probe, a
root-owned directory under an unprivileged process starts, prints
``listening``, and fails only at the first accepted envelope, after the
sender has already spent a publication on it.

## What is held in memory only, and what that costs

The sequence ledgers. A restart forgets them, and the frame's own rule is that
the first frame a fresh ledger sees is trusted for ordering: a replay against
a restarted comparer is not caught -- the cost ``ration.frame``'s docstring
states and leaves to its consumer, which here is this module. The same
forgetting is the by-hand clear the epoch hazard needs: the producer's epoch
is a store generation, so a store that loses its data restarts the epoch
below what this ledger accepted,
every frame is refused ``sequence-replayed``, and the remedy is a restart
here once the producer is known to be the live one. Persisting the ledger
would turn that remedy into a file edit; v1 keeps it a restart, stated.

## Deliberately absent

TLS, authentication and retries: the frame is integrity, ordering and
versioning, and securing the network it crosses is the deployment's. Any
minted identity:
the sender segment is addressing -- which ledger -- and never a credential, the
objection the envelope's own docstring raises. A baseline per project: v1 has
one producer and one project, and a second project is refused
``identity-mismatch``, which is the reopen signal. A signal handler: a
SIGTERM ends the process, and every accepted baseline is already on disk. A
health route: with a caller as infrequent as one producer, the process being
up is the liveness.
Each is a later change, not an oversight.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import IO

from ration import frame as framing

from .service import DriftVerdict, observe
from .wire import Envelope, WireRefusal, decode_envelope

__all__ = [
    "BODY_TOO_LARGE",
    "Comparer",
    "DEFAULT_BIND",
    "LAYER_COMPARER",
    "LAYER_ENVELOPE",
    "LAYER_FRAME",
    "LENGTH_REQUIRED",
    "MAX_BODY_BYTES",
    "Outcome",
    "UNKNOWN_SENDER",
    "main",
    "make_server",
    "serve",
]

# The three layers a request is judged in, in this order. A field of every log
# line and every refusal body, never inferred from the control.
LAYER_FRAME = "frame"
LAYER_ENVELOPE = "envelope"
LAYER_COMPARER = "comparer"

# The controls this module adds to the closed sets it composes. All three are
# the comparer's own: neither the frame nor the envelope is consulted for them,
# and each is decided before a byte of the body is read.
UNKNOWN_SENDER = "unknown-sender"
LENGTH_REQUIRED = "length-required"
BODY_TOO_LARGE = "body-too-large"

# One mebibyte. A fingerprint envelope carries layer names, model names and
# digests, never data, so the ceiling sits far above any this package builds,
# and a request declaring more is refused before any of it is read.
MAX_BODY_BYTES = 1 << 20

# Loopback unless told otherwise: a deployment passes the address to bind,
# and a caller that passes none gets this.
DEFAULT_BIND = "127.0.0.1:8100"

# A sender name: lowercase, digits and hyphens, bounded, so the ledger key and
# the log line are bounded too. The path is exactly one such segment.
_SENDER = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_PATH = re.compile(r"/([a-z0-9][a-z0-9-]{0,62})")
_DIGITS = re.compile(r"[0-9]{1,18}")


@dataclass(frozen=True)
class Outcome:
    """What one request came to: the status answered, the body answered, the line logged."""

    status: int
    response: dict[str, object]
    record: dict[str, object]


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _refused(
    status: int, layer: str, control: str, reason: str, base: dict[str, object]
) -> Outcome:
    response: dict[str, object] = {"layer": layer, "control": control, "reason": reason}
    record: dict[str, object] = {
        **base,
        "event": "refused",
        "layer": layer,
        "control": control,
        "detail": _one_line(reason),
    }
    return Outcome(status, response, record)


def _answered(verdict: DriftVerdict, base: dict[str, object]) -> Outcome:
    body: dict[str, object] = asdict(verdict)
    return Outcome(200, body, {**base, "event": "verdict", **body})


def _probe_writable(path: Path) -> None:
    # The first step of `_write_atomically`, taken once at start and undone.
    # The check is the operation a verdict would fail at, so whatever refuses
    # that -- ownership, a read-only mount, a full disk -- refuses here too;
    # `os.access` answers for the real uid rather than the effective one, and
    # cannot see a full disk.
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    except OSError as error:
        raise ValueError(
            f"the baseline directory {path.parent} cannot be written by this "
            f"process ({error.strerror}); a comparer that cannot persist refuses "
            f"to start rather than at its first verdict"
        ) from error
    os.close(fd)
    os.unlink(tmp)


def _load_baseline(path: Path) -> Envelope | None:
    if not path.parent.is_dir():
        raise ValueError(
            f"the baseline directory {path.parent} does not exist; a comparer "
            f"that cannot persist refuses to start rather than at its first verdict"
        )
    _probe_writable(path)
    if not path.exists():
        return None
    decoded = decode_envelope(path.read_bytes())
    if isinstance(decoded, WireRefusal):
        raise ValueError(
            f"the baseline at {path} does not decode ({decoded.control}: "
            f"{decoded.reason}); delete it to mean a fresh baseline"
        )
    return decoded


def _write_atomically(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Comparer:
    """The state the process holds, and the decision it takes per request.

    Separate from the HTTP shell so that the decision is testable without a
    socket and the shell holds nothing: :meth:`receive` is the whole of it,
    and :meth:`decline` is how the shell reports a request it refused before
    reading a body, so that every request still leaves exactly one line.

    One lock serialises requests. A ledger judges and then advances, and a
    baseline is read and then replaced; two requests from one sender
    interleaving those steps would be the reader-records-first violator the
    frame's own suite refuses.
    """

    def __init__(
        self,
        ledgers: Mapping[str, framing.SequenceLedger],
        baseline_path: Path,
        out: IO[str] | None = None,
    ) -> None:
        for name in ledgers:
            if not _SENDER.fullmatch(name):
                raise ValueError(f"sender name {name!r} is not one a path can address")
        self._ledgers = dict(ledgers)
        self._baseline_path = baseline_path
        self._out: IO[str] = out if out is not None else sys.stdout
        self._lock = threading.Lock()
        self._previous = _load_baseline(baseline_path)

    @property
    def previous(self) -> Envelope | None:
        """The standing objective, or ``None`` before the first accepted envelope."""
        return self._previous

    @property
    def senders(self) -> tuple[str, ...]:
        return tuple(sorted(self._ledgers))

    def receive(self, sender: str, body: bytes) -> Outcome:
        """Judge one request's body for one sender: frame, then envelope, then compare."""
        with self._lock:
            outcome = self._judge(sender, body)
            self._emit(outcome.record)
        return outcome

    def decline(
        self, sender: str | None, status: int, control: str, reason: str, size: int
    ) -> Outcome:
        """A refusal the shell decided before reading a body, logged like any other."""
        base: dict[str, object] = {"sender": sender, "size": size}
        outcome = _refused(status, LAYER_COMPARER, control, reason, base)
        with self._lock:
            self._emit(outcome.record)
        return outcome

    def note(self, event: str, **fields: object) -> None:
        """One line that is neither a verdict nor a refusal: the process saying what it did."""
        with self._lock:
            self._emit({"event": event, **fields})

    def _judge(self, sender: str, body: bytes) -> Outcome:
        base: dict[str, object] = {"sender": sender, "size": len(body)}
        ledger = self._ledgers.get(sender)
        if ledger is None:
            return _refused(
                404, LAYER_COMPARER, UNKNOWN_SENDER,
                "the path names no configured sender", base,
            )
        frame = framing.decode(body, ledger)
        if isinstance(frame, framing.FrameRefusal):
            return _refused(400, LAYER_FRAME, frame.control, frame.reason, base)
        base.update(epoch=frame.sequence.epoch, count=frame.sequence.count)
        if frame.kind != framing.FINGERPRINT:
            return _refused(
                422, LAYER_COMPARER, framing.UNKNOWN_PAYLOAD_KIND,
                f"payload kind {frame.kind_name!r} is not a kind this comparer serves",
                base,
            )
        envelope = decode_envelope(frame.body)
        if isinstance(envelope, WireRefusal):
            return _refused(422, LAYER_ENVELOPE, envelope.control, envelope.reason, base)
        verdict = observe(self._previous, envelope)
        if isinstance(verdict, WireRefusal):
            return _refused(422, LAYER_COMPARER, verdict.control, verdict.reason, base)
        _write_atomically(self._baseline_path, frame.body)
        self._previous = envelope
        return _answered(verdict, base)

    def _emit(self, record: dict[str, object]) -> None:
        self._out.write(json.dumps(record, sort_keys=True) + "\n")
        self._out.flush()


class _Handler(BaseHTTPRequestHandler):
    """The HTTP shell: read one ``POST``, hand its body to the comparer, answer JSON.

    ``make_server`` subclasses this per server and sets the two class
    attributes, so two servers in one process never share a comparer.
    """

    comparer: Comparer
    max_body: int

    # What the response header says about this process: not the interpreter
    # version, and not a product name.
    server_version = "comparer/1"
    sys_version = ""
    # A sender that stalls mid-request holds a thread for this long, not forever.
    timeout = 30

    def do_POST(self) -> None:
        match = _PATH.fullmatch(self.path)
        if match is None:
            self._answer(self.comparer.decline(
                None, 404, UNKNOWN_SENDER, "the path is not /<sender>", 0
            ))
            return
        sender = match.group(1)
        declared = self.headers.get("Content-Length")
        if declared is None or _DIGITS.fullmatch(declared) is None:
            self._answer(self.comparer.decline(
                sender, 411, LENGTH_REQUIRED, "Content-Length is missing or not a number", 0
            ))
            return
        length = int(declared)
        if length > self.max_body:
            self._answer(self.comparer.decline(
                sender, 413, BODY_TOO_LARGE,
                f"Content-Length {length} is above the ceiling of {self.max_body}", length,
            ))
            return
        self._answer(self.comparer.receive(sender, self.rfile.read(length)))

    def _answer(self, outcome: Outcome) -> None:
        body = json.dumps(outcome.response, sort_keys=True).encode("utf-8")
        self.send_response(outcome.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        # The structured line the comparer writes is the log; the access line
        # the stdlib would print beside it is a second, unstructured record of
        # the same request, and one record per request is the point.
        pass


def make_server(
    bind: tuple[str, int], comparer: Comparer, max_body: int = MAX_BODY_BYTES
) -> ThreadingHTTPServer:
    """A server bound to ``bind`` and answering for ``comparer``; not yet serving."""

    class Handler(_Handler):
        pass

    Handler.comparer = comparer
    Handler.max_body = max_body
    server = ThreadingHTTPServer(bind, Handler)
    server.daemon_threads = True
    return server


def serve(
    bind: tuple[str, int],
    senders: Iterable[str],
    baseline_path: Path,
    out: IO[str] | None = None,
) -> None:
    """Hold the standing objective at ``baseline_path`` and answer ``senders`` on ``bind``, forever.

    One ledger per sender, fresh at start (the module docstring prices that).
    The first line written says what the process holds, so a restart's
    ``objective: held`` is the observable that it did not re-baseline.
    """

    comparer = Comparer(
        {name: framing.SequenceLedger() for name in senders}, baseline_path, out
    )
    server = make_server(bind, comparer)
    # The host is what was asked for and the port is what was got: a bind on
    # port 0 is answered with the port the kernel chose.
    comparer.note(
        "listening",
        bind=f"{bind[0]}:{server.server_port}",
        senders=list(comparer.senders),
        baseline=str(baseline_path),
        objective="held" if comparer.previous is not None else "none",
    )
    server.serve_forever()


def _parse_bind(text: str, parser: argparse.ArgumentParser) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    if not host or _DIGITS.fullmatch(port) is None or int(port) > 65535:
        parser.error(f"--bind wants HOST:PORT, not {text!r}")
    return host, int(port)


def main(
    argv: list[str] | None = None,
    run: Callable[[tuple[str, int], list[str], Path], None] = serve,
) -> int:
    """``python -m crosslink.serve --sender NAME --baseline FILE [--bind HOST:PORT]``."""

    parser = argparse.ArgumentParser(
        prog="python -m crosslink.serve",
        description="The comparer: answer framed fingerprint envelopes with drift verdicts.",
    )
    parser.add_argument(
        "--bind", default=DEFAULT_BIND, metavar="HOST:PORT",
        help=f"the address to listen on (default {DEFAULT_BIND})",
    )
    parser.add_argument(
        "--sender", action="append", required=True, metavar="NAME",
        help="a sender this comparer keeps a ledger for; repeat for several",
    )
    parser.add_argument(
        "--baseline", required=True, type=Path, metavar="FILE",
        help="where the accepted envelope's bytes are kept across restarts",
    )
    args = parser.parse_args(argv)
    run(_parse_bind(args.bind, parser), list(args.sender), args.baseline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

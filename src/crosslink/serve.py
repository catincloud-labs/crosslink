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

A sender's sequence is consumed once its frame passes every frame check,
whatever the envelope and the comparer then decide, because that is the
frame's own rule: an envelope refusal, an ``identity-mismatch`` and a frame of
a kind the registry names but this comparer does not serve (an ``explore-*``
kind) each leave the ledger moved, and the sender's next frame is the
following count. A refusal at the frame layer, or one decided before the
frame is read, leaves the ledger exactly as it was. No refusal touches the
baseline.

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

## The sequence ledgers are on disk beside it

Each sender's ledger -- the last sequence accepted from it -- is kept in one
file beside the baseline, at :func:`ledger_path` (the baseline's file name
with ``.ledger`` appended), so a restart starts from the sequences it had.
Without the file, the frame's own rule that the first frame a fresh ledger
sees is trusted for ordering would let a replay against a restarted comparer
through: the cost ``ration.frame``'s docstring states and leaves to its
consumer, which here is this module.

The file gets the baseline's care. It is written through a temp file beside
it and ``os.replace``, before the answer, whenever a frame passes the frame
checks. A request's frame is decoded against a copy of its sender's ledger,
and the copy's move is kept in memory only once it is on disk, so a write
that fails leaves memory and disk agreeing. It is written before the
baseline, so an envelope in the baseline always has its sequence in the
ledger: a crash between the two writes leaves a consumed sequence whose
envelope was never kept, and the sender's next frame is accepted. A ledger
file that does not decode refuses to start, as a baseline does and for the
same reason: a silent reset is the replay the file exists to refuse. Its
directory is the baseline's, so the start probe above covers both files. An
entry for a sender this process was not started with is carried forward
unchanged, so dropping a ``--sender`` for a while clears nothing.

## The epoch hazard, and what clears it

The producer's epoch is a store generation, so a store that loses its data
restarts the epoch below what this ledger accepted, and every frame is
refused ``sequence-replayed`` (``sequence-duplicate`` for the one frame whose
generation lands exactly on the ledgered sequence). That standing refusal is
the evidence that the store lost its data, and a restart does not clear it:
a deploy tool that recreates this process has judged nothing, and the
refusal stands. The remedy is removing the ledger file while the comparer is
stopped, once the producer is known to be the live one; at the next start
each sender's first frame is trusted for ordering again. The file is read at
start only, and a running comparer writes back what it holds at its next
accepted frame from any sender, so a removal under a running process clears
nothing. Removing the file clears every sender's ledger.

## Deliberately absent

TLS, authentication and retries: the frame is integrity, ordering and
versioning, and securing the network it crosses is the deployment's. Any
minted identity:
the sender segment is addressing -- which ledger -- and never a credential, the
objection the envelope's own docstring raises. A baseline per project: v1 has
one producer and one project, and a second project is refused
``identity-mismatch``, which is the reopen signal. A signal handler: a
SIGTERM ends the process, and every accepted baseline and every consumed
sequence is already on disk. A
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
    "LEDGER_SUFFIX",
    "LENGTH_REQUIRED",
    "MAX_BODY_BYTES",
    "Outcome",
    "UNKNOWN_SENDER",
    "ledger_path",
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

# The ledger file is the baseline's file name with this appended, in the
# baseline's directory, so one directory holds the comparer's whole state.
LEDGER_SUFFIX = ".ledger"

# The ledger file's first field. A file naming any other format does not
# decode, so a later layout is refused by this one rather than misread.
_LEDGER_FORMAT = "crosslink-ledger/1"
_LEDGER_KEYS = frozenset({"format", "senders"})
_SEQUENCE_KEYS = frozenset({"epoch", "count"})


def ledger_path(baseline_path: Path) -> Path:
    """Where the sequence ledgers are kept for the baseline at ``baseline_path``: beside it."""
    return baseline_path.with_name(baseline_path.name + LEDGER_SUFFIX)


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
            f"process ({error.strerror}); a comparer that cannot persist its "
            f"baseline and its ledger refuses to start rather than at its first verdict"
        ) from error
    os.close(fd)
    os.unlink(tmp)


def _check_directory(path: Path) -> None:
    # One directory holds the baseline and the ledger, so one check covers both.
    if not path.parent.is_dir():
        raise ValueError(
            f"the baseline directory {path.parent} does not exist; a comparer "
            f"that cannot persist its baseline and its ledger refuses to start "
            f"rather than at its first verdict"
        )
    _probe_writable(path)


class _Undecodable(ValueError):
    """A ledger file's bytes are not a ledger; the reason is what was wrong."""


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise _Undecodable("an object names one key twice")
    return dict(pairs)


def _sequence_from(name: str, value: object) -> framing.Sequence:
    if not isinstance(value, dict) or set(value) != _SEQUENCE_KEYS:
        raise _Undecodable(f"sender {name!r} is not an object of exactly epoch and count")
    try:
        return framing.Sequence(value["epoch"], value["count"])
    except (TypeError, ValueError) as error:
        raise _Undecodable(f"sender {name!r}: {error}") from error


def _decode_ledger(data: bytes) -> dict[str, framing.Sequence]:
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _Undecodable(f"not JSON: {error}") from error
    if not isinstance(document, dict) or set(document) != _LEDGER_KEYS:
        raise _Undecodable("not an object of exactly format and senders")
    if document["format"] != _LEDGER_FORMAT:
        raise _Undecodable(f"format {document['format']!r} is not {_LEDGER_FORMAT!r}")
    senders = document["senders"]
    if not isinstance(senders, dict):
        raise _Undecodable("senders is not an object")
    held: dict[str, framing.Sequence] = {}
    for name, value in senders.items():
        if not _SENDER.fullmatch(name):
            raise _Undecodable(f"sender name {name!r} is not one a path can address")
        held[name] = _sequence_from(name, value)
    return held


def _encode_ledger(held: Mapping[str, framing.Sequence]) -> bytes:
    senders = {
        name: {"epoch": sequence.epoch, "count": sequence.count}
        for name, sequence in held.items()
    }
    document = {"format": _LEDGER_FORMAT, "senders": senders}
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _load_ledger(path: Path) -> dict[str, framing.Sequence]:
    if not path.exists():
        return {}
    try:
        return _decode_ledger(path.read_bytes())
    except _Undecodable as error:
        raise ValueError(
            f"the ledger at {path} does not decode ({error}); delete it to mean "
            f"fresh ledgers, which trust each sender's next frame for ordering"
        ) from error


def _ledger_at(sequence: framing.Sequence | None) -> framing.SequenceLedger:
    ledger = framing.SequenceLedger()
    if sequence is not None:
        ledger.advance(sequence)
    return ledger


def _load_baseline(path: Path) -> Envelope | None:
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

    ``senders`` names the senders this process answers. Each one's ledger is
    read from :func:`ledger_path` beside ``baseline_path``, and a sender the
    file does not name starts fresh.
    """

    def __init__(
        self,
        senders: Iterable[str],
        baseline_path: Path,
        out: IO[str] | None = None,
    ) -> None:
        if isinstance(senders, str):
            raise TypeError("senders is a collection of names, not one name")
        if isinstance(senders, Mapping):
            # A mapping of names to ledgers would iterate as its names, and the
            # ledgers in it would be dropped without a word.
            raise TypeError(
                "senders is a collection of names; each sender's ledger is read "
                "from the file beside the baseline, not passed in"
            )
        names = frozenset(senders)
        for name in names:
            if not _SENDER.fullmatch(name):
                raise ValueError(f"sender name {name!r} is not one a path can address")
        self._senders = names
        self._baseline_path = baseline_path
        self._ledger_path = ledger_path(baseline_path)
        self._out: IO[str] = out if out is not None else sys.stdout
        self._lock = threading.Lock()
        _check_directory(baseline_path)
        self._previous = _load_baseline(baseline_path)
        # Every entry the file holds, a sender not configured here included:
        # what is written back is this, so nothing on disk is dropped.
        self._held = _load_ledger(self._ledger_path)

    @property
    def previous(self) -> Envelope | None:
        """The standing objective, or ``None`` before the first accepted envelope."""
        return self._previous

    @property
    def senders(self) -> tuple[str, ...]:
        return tuple(sorted(self._senders))

    @property
    def ledger_path(self) -> Path:
        """The file the sequence ledgers are kept in, beside the baseline."""
        return self._ledger_path

    @property
    def ledger(self) -> dict[str, framing.Sequence]:
        """The last sequence accepted from each configured sender that has one."""
        with self._lock:
            return {name: self._held[name] for name in self._senders if name in self._held}

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
        if sender not in self._senders:
            return _refused(
                404, LAYER_COMPARER, UNKNOWN_SENDER,
                "the path names no configured sender", base,
            )
        # Decoded against a copy: the copy's move is kept only once it is on disk.
        frame = framing.decode(body, _ledger_at(self._held.get(sender)))
        if isinstance(frame, framing.FrameRefusal):
            return _refused(400, LAYER_FRAME, frame.control, frame.reason, base)
        self._consume(sender, frame.sequence)
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

    def _consume(self, sender: str, sequence: framing.Sequence) -> None:
        # Written before the baseline and before anything is answered; held in
        # memory only once the write returned, so a failed write moves nothing.
        held = {**self._held, sender: sequence}
        _write_atomically(self._ledger_path, _encode_ledger(held))
        self._held = held

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

    One ledger per sender, read from the file beside the baseline (the module
    docstring says what clears it). The first line written says what the
    process holds, so a restart's ``objective: held`` is the observable that
    it did not re-baseline, and its ``ledgered`` the one that it did not
    forget a sender's sequence.
    """

    comparer = Comparer(senders, baseline_path, out)
    server = make_server(bind, comparer)
    # The host is what was asked for and the port is what was got: a bind on
    # port 0 is answered with the port the kernel chose.
    comparer.note(
        "listening",
        bind=f"{bind[0]}:{server.server_port}",
        senders=list(comparer.senders),
        baseline=str(baseline_path),
        objective="held" if comparer.previous is not None else "none",
        ledger=str(comparer.ledger_path),
        ledgered=sorted(comparer.ledger),
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
        help=(
            "where the accepted envelope's bytes are kept across restarts; the "
            f"sequence ledgers are kept beside it, in FILE{LEDGER_SUFFIX}"
        ),
    )
    args = parser.parse_args(argv)
    run(_parse_bind(args.bind, parser), list(args.sender), args.baseline)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

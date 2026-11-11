# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The comparer, and the traversal that makes the wire layer real.

The pure arms pin `observe`'s verdict shapes - baseline, no-drift, drift that
names its layers, and the load-bearing digest-only case - plus the refusal
only a comparer can make. Then the traversal: a fingerprint envelope crosses a
process-boundary HTTP hop on localhost and the verdict that comes back over
the wire names the mutated layer. That arm is ADR-0004's second precondition
observed, and it is stdlib end to end: `http.server` for framing (raw sockets
would reinvent it), `urllib.request` to post. The HTTP shell here is
harness-only: the shipped process is `crosslink.serve`, and
`tests/test_serve.py` proves that one.

Fixtures ride in from test_wire and test_delta (the test_deliver precedent).
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from test_delta import a_snapshot
from test_wire import an_envelope

from crosslink import (
    WireRefusal,
    decode_envelope,
    encode_envelope,
    fingerprint_envelope,
)
from crosslink.model import layered_fingerprint
from crosslink.service import (
    BASELINE,
    DRIFT,
    IDENTITY_MISMATCH,
    NO_DRIFT,
    DriftVerdict,
    observe,
)


def a_drifted_snapshot():
    """The base snapshot with one model rewired inside the gold layer.

    Dependencies are part of a layer's hash, so this moves exactly one layer
    while every model keeps its name and place.
    """

    snapshot = a_snapshot()
    return replace(
        snapshot,
        models=tuple(
            replace(m, depends_on=()) if m.name == "fact_orders" else m
            for m in snapshot.models
        ),
    )


class TestObserve:
    def test_no_previous_envelope_is_a_baseline_not_a_drift_claim(self):
        """"Nothing to compare against" and "compared, and nothing moved" are
        different statements; the first observation must not read as the
        second."""

        verdict = observe(None, an_envelope())
        assert isinstance(verdict, DriftVerdict)
        assert verdict.kind == BASELINE
        assert verdict.changed_layers == ()
        assert verdict.digest_changed is False
        assert verdict.previous_emitted_at is None

    def test_the_same_project_twice_is_no_drift(self):
        snapshot = a_snapshot()
        fingerprint = layered_fingerprint(snapshot.models, snapshot.sources)
        earlier = fingerprint_envelope(
            snapshot, fingerprint, emitted_at="2026-09-01T00:00:00+00:00"
        )
        later = fingerprint_envelope(
            snapshot, fingerprint, emitted_at="2026-09-01T06:00:00+00:00"
        )
        verdict = observe(earlier, later)
        assert isinstance(verdict, DriftVerdict)
        assert verdict.kind == NO_DRIFT
        assert verdict.changed_layers == ()
        assert verdict.digest_changed is False
        assert verdict.previous_emitted_at == "2026-09-01T00:00:00+00:00"
        assert verdict.new_emitted_at == "2026-09-01T06:00:00+00:00"

    def test_drift_names_the_changed_layer(self):
        verdict = observe(an_envelope(), an_envelope(a_drifted_snapshot()))
        assert isinstance(verdict, DriftVerdict)
        assert verdict.kind == DRIFT
        assert verdict.changed_layers == ("gold",)
        assert verdict.digest_changed is True

    def test_digest_only_drift_is_drift_with_no_layer_named(self):
        """The load-bearing case: the layered fingerprint saw nothing move,
        the snapshot digest did - undifferentiated drift in the four unlayered
        nouns, its own verdict shape, never folded into no-drift."""

        keys_changed = a_snapshot(declared_keys=a_snapshot().declared_keys[:1])
        verdict = observe(an_envelope(), an_envelope(keys_changed))
        assert isinstance(verdict, DriftVerdict)
        assert verdict.kind == DRIFT
        assert verdict.changed_layers == ()
        assert verdict.digest_changed is True

    def test_two_projects_are_refused_not_compared(self):
        """A drift claim between two different projects is an invented claim -
        the comparer's own refusal, since each envelope alone is valid."""

        refusal = observe(an_envelope(), an_envelope(a_snapshot(name="elsewhere")))
        assert isinstance(refusal, WireRefusal)
        assert refusal.control == IDENTITY_MISMATCH


class _DriftWatchHandler(BaseHTTPRequestHandler):
    """The harness-only shell of the drift-watch shape: hold the previous
    envelope, decode what arrives, observe, answer with the verdict."""

    previous = None  # set on the subclass each test builds

    def do_POST(self):
        data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        decoded = decode_envelope(data)
        result = (
            decoded
            if isinstance(decoded, WireRefusal)
            else observe(type(self).previous, decoded)
        )
        status = 422 if isinstance(result, WireRefusal) else 200
        body = json.dumps(asdict(result), sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the suite's output clean
        pass


class TestTheTraversal:
    """ADR-0004's second precondition: a fingerprint envelope crosses a
    process boundary on a network and a verdict comes back."""

    def _serving(self):
        handler = type(
            "Handler", (_DriftWatchHandler,), {"previous": an_envelope()}
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    def _post(self, server, data: bytes):
        host, port = server.server_address
        request = urllib.request.Request(
            f"http://{host}:{port}/", data=data, method="POST"
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_a_verdict_comes_back_over_the_wire_naming_the_layer(self):
        server = self._serving()
        try:
            status, clean = self._post(
                server, encode_envelope(an_envelope())
            )
            assert (status, clean["kind"]) == (200, NO_DRIFT)

            status, drifted = self._post(
                server, encode_envelope(an_envelope(a_drifted_snapshot()))
            )
            assert status == 200
            assert drifted["kind"] == DRIFT
            assert drifted["changed_layers"] == ["gold"]
            assert drifted["digest_changed"] is True
            # The observable ADR-0004's second box names, verbatim:
            print("verdict over the wire:", json.dumps(drifted, sort_keys=True))
        finally:
            server.shutdown()
            server.server_close()

    def test_a_refusal_is_first_class_over_the_wire_too(self):
        """The decode posture survives the hop: garbage bytes come back as a
        typed refusal in the response body, not a hung connection or a 500."""

        server = self._serving()
        try:
            status, refusal = self._post(server, b"\x00 not an envelope")
            assert status == 422
            assert refusal["control"] == "malformed-envelope"
        finally:
            server.shutdown()
            server.server_close()

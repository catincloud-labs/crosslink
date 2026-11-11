# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The comparer as a process: the traversal re-run through the shipped shell, and every seam it adds.

`test_service.py` proved the drift-watch shape with a harness-only HTTP shell.
This file proves the shipped one, `crosslink.serve`: the same envelope crosses
the same localhost hop, now inside a frame, and the verdict comes back naming
the layer. Around that, the arms `crosslink.serve`'s docstring states:
a corrupted frame answers `crc-mismatch` and a corrupted payload
`digest-mismatch` as two different log fields; a replayed frame is refused
before the envelope is looked at; the
baseline is bytes on disk, and a comparer rebuilt from them answers
`no-drift`, not `baseline`.

Fixtures ride in from test_wire, test_delta and test_service. The frame codec
is the real one, from the `[service]` extra -- a stand-in would prove the
order of this module's own calls and nothing about the codec the process runs.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from ration import frame as framing
from test_delta import a_snapshot
from test_service import a_drifted_snapshot
from test_wire import an_envelope

from crosslink import encode_envelope
from crosslink.serve import (
    BODY_TOO_LARGE,
    LAYER_COMPARER,
    LAYER_ENVELOPE,
    LAYER_FRAME,
    LENGTH_REQUIRED,
    UNKNOWN_SENDER,
    Comparer,
    main,
    make_server,
)
from crosslink.service import BASELINE, DRIFT, IDENTITY_MISMATCH, NO_DRIFT
from crosslink.wire import DIGEST_MISMATCH, MALFORMED_ENVELOPE

SENDER = "catalyst"


def framed(body: bytes, epoch: int = 1, count: int = 0, kind: int = framing.FINGERPRINT) -> bytes:
    return framing.encode(kind, framing.Sequence(epoch, count), body)


def a_frame(snapshot=None, *, epoch: int = 1, count: int = 0) -> bytes:
    return framed(encode_envelope(an_envelope(snapshot)), epoch, count)


def flipped_last_byte(data: bytes) -> bytes:
    return data[:-1] + bytes([data[-1] ^ 0x01])


def with_wrong_digest(envelope_bytes: bytes) -> bytes:
    """The envelope re-encoded exactly as the codec would, with its digest replaced."""

    obj = json.loads(envelope_bytes)
    obj["payload_digest"] = "0" * len(obj["payload_digest"])
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def a_comparer(tmp_path: Path, senders=(SENDER,)) -> tuple[Comparer, io.StringIO]:
    out = io.StringIO()
    ledgers = {name: framing.SequenceLedger() for name in senders}
    return Comparer(ledgers, tmp_path / "baseline.json", out), out


def lines(out: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in out.getvalue().splitlines()]


class TestReceive:
    def test_the_first_envelope_is_a_baseline_and_the_next_names_the_layer(self, tmp_path):
        comparer, out = a_comparer(tmp_path)

        first = comparer.receive(SENDER, a_frame(epoch=1, count=0))
        assert (first.status, first.response["kind"]) == (200, BASELINE)

        second = comparer.receive(SENDER, a_frame(a_drifted_snapshot(), epoch=1, count=1))
        assert second.status == 200
        assert second.response["kind"] == DRIFT
        assert second.response["changed_layers"] == ("gold",)
        assert second.response["digest_changed"] is True

        records = lines(out)
        assert [r["event"] for r in records] == ["verdict", "verdict"]
        assert records[1]["kind"] == DRIFT
        assert (records[1]["epoch"], records[1]["count"]) == (1, 1)

    def test_an_unknown_sender_is_refused_before_the_frame_is_read(self, tmp_path):
        """The set of senders is the caller's; a stranger cannot allocate a
        ledger by inventing a name, and the frame is never decoded for one."""

        comparer, out = a_comparer(tmp_path)
        outcome = comparer.receive("stranger", b"\x00 not even a frame")
        assert outcome.status == 404
        assert outcome.response == {
            "layer": LAYER_COMPARER,
            "control": UNKNOWN_SENDER,
            "reason": "the path names no configured sender",
        }
        assert comparer.senders == (SENDER,)
        assert lines(out)[0]["control"] == UNKNOWN_SENDER

    def test_a_sender_name_a_path_cannot_address_is_refused_at_construction(self, tmp_path):
        with pytest.raises(ValueError, match="not one a path can address"):
            Comparer({"Not/A/Segment": framing.SequenceLedger()}, tmp_path / "b.json")

    def test_crc_and_digest_refusals_differ_in_layer_and_in_control(self, tmp_path):
        """The failure this guards against: a CRC failure and a digest
        mismatch landing as one signal in the log record. Two arms, two
        fields."""

        comparer, out = a_comparer(tmp_path)

        corrupted_frame = flipped_last_byte(a_frame(epoch=1, count=0))
        crc = comparer.receive(SENDER, corrupted_frame)
        assert crc.status == 400
        assert (crc.response["layer"], crc.response["control"]) == (LAYER_FRAME, framing.CRC_MISMATCH)

        corrupted_payload = framed(with_wrong_digest(encode_envelope(an_envelope())), 1, 0)
        digest = comparer.receive(SENDER, corrupted_payload)
        assert digest.status == 422
        assert (digest.response["layer"], digest.response["control"]) == (LAYER_ENVELOPE, DIGEST_MISMATCH)

        first, second = lines(out)
        assert (first["layer"], first["control"]) == (LAYER_FRAME, framing.CRC_MISMATCH)
        assert (second["layer"], second["control"]) == (LAYER_ENVELOPE, DIGEST_MISMATCH)
        assert first["layer"] != second["layer"]
        assert first["control"] != second["control"]
        assert comparer.previous is None

    def test_a_replayed_frame_is_refused_before_the_envelope_is_looked_at(self, tmp_path):
        """The order is the contract: a frame at a sequence the ledger has
        moved past carries garbage, and the refusal is the frame's, never
        `malformed-envelope`."""

        comparer, out = a_comparer(tmp_path)
        assert comparer.receive(SENDER, a_frame(epoch=2, count=0)).status == 200

        replayed = comparer.receive(SENDER, framed(b"\x00 not an envelope", epoch=1, count=0))
        assert replayed.status == 400
        assert replayed.response["layer"] == LAYER_FRAME
        assert replayed.response["control"] == framing.SEQUENCE_REPLAYED
        assert replayed.response["control"] != MALFORMED_ENVELOPE

        duplicate = comparer.receive(SENDER, a_frame(epoch=2, count=0))
        assert duplicate.response["control"] == framing.SEQUENCE_DUPLICATE
        assert [r["event"] for r in lines(out)] == ["verdict", "refused", "refused"]

    def test_a_refused_frame_does_not_consume_its_sequence(self, tmp_path):
        """A sender whose frame was corrupted in transit retries at the SAME
        sequence and is accepted; the ledger moved only on acceptance."""

        comparer, _ = a_comparer(tmp_path)
        assert comparer.receive(SENDER, a_frame(epoch=1, count=0)).status == 200
        assert comparer.receive(SENDER, flipped_last_byte(a_frame(epoch=1, count=1))).status == 400
        retried = comparer.receive(SENDER, a_frame(epoch=1, count=1))
        assert (retried.status, retried.response["kind"]) == (200, NO_DRIFT)

    def test_a_registered_kind_this_comparer_does_not_serve_is_refused_and_consumes_its_sequence(self, tmp_path):
        """The one refusal that moves state, as the module docstring states:
        the frame passed, so the frame's rule applies."""

        comparer, out = a_comparer(tmp_path)
        explore = comparer.receive(
            SENDER, framed(encode_envelope(an_envelope()), 1, 0, kind=framing.EXPLORE_QUERY)
        )
        assert explore.status == 422
        assert (explore.response["layer"], explore.response["control"]) == (
            LAYER_COMPARER, framing.UNKNOWN_PAYLOAD_KIND,
        )
        assert comparer.previous is None
        # Consumed: the same count again is now a duplicate, the next count is accepted.
        assert comparer.receive(SENDER, a_frame(epoch=1, count=0)).response["control"] == framing.SEQUENCE_DUPLICATE
        assert comparer.receive(SENDER, a_frame(epoch=1, count=1)).status == 200
        assert lines(out)[0]["layer"] == LAYER_COMPARER

    def test_a_different_project_is_refused_and_the_baseline_stands(self, tmp_path):
        comparer, _ = a_comparer(tmp_path)
        assert comparer.receive(SENDER, a_frame(epoch=1, count=0)).status == 200
        held = (tmp_path / "baseline.json").read_bytes()

        other = comparer.receive(SENDER, a_frame(a_snapshot(name="elsewhere"), epoch=1, count=1))
        assert other.status == 422
        assert (other.response["layer"], other.response["control"]) == (LAYER_COMPARER, IDENTITY_MISMATCH)
        assert (tmp_path / "baseline.json").read_bytes() == held
        assert comparer.previous.project_name != "elsewhere"

    def test_the_accepted_bytes_are_the_baseline_on_disk_and_survive_a_restart(self, tmp_path):
        """The restart observable, in-process: a comparer rebuilt from
        the file answers `no-drift`, never `baseline`."""

        comparer, _ = a_comparer(tmp_path)
        envelope_bytes = encode_envelope(an_envelope())
        assert comparer.receive(SENDER, framed(envelope_bytes, 1, 0)).response["kind"] == BASELINE
        assert (tmp_path / "baseline.json").read_bytes() == envelope_bytes
        assert not list(tmp_path.glob("*.tmp"))

        restarted, out = a_comparer(tmp_path)
        assert restarted.previous == an_envelope()
        after = restarted.receive(SENDER, framed(envelope_bytes, 7, 0))
        assert (after.status, after.response["kind"]) == (200, NO_DRIFT)
        assert lines(out)[0]["previous_emitted_at"] == an_envelope().emitted_at

    def test_a_baseline_that_does_not_decode_refuses_to_start(self, tmp_path):
        """A silent re-baseline is the failure persisting the file exists to
        prevent, so the comparer raises rather than starts."""

        (tmp_path / "baseline.json").write_bytes(b"\x00 not an envelope")
        with pytest.raises(ValueError, match="does not decode"):
            a_comparer(tmp_path)

    def test_a_baseline_directory_that_does_not_exist_refuses_to_start(self, tmp_path):
        with pytest.raises(ValueError, match="does not exist"):
            Comparer({SENDER: framing.SequenceLedger()}, tmp_path / "missing" / "b.json")

    @pytest.mark.skipif(
        sys.platform == "win32" or os.geteuid() == 0,
        reason=(
            "a read-only directory does not refuse file creation here: Windows "
            "ignores the mode on a directory, and root bypasses it"
        ),
    )
    def test_a_baseline_directory_it_cannot_write_refuses_to_start(self, tmp_path):
        """Without this refusal a comparer under a directory it cannot
        write starts and prints `listening`, and its first verdict fails at
        the write, after its sender has published."""

        locked = tmp_path / "locked"
        locked.mkdir()
        locked.chmod(0o500)
        try:
            with pytest.raises(ValueError, match=re.escape(f"{locked} cannot be written")):
                Comparer({SENDER: framing.SequenceLedger()}, locked / "b.json")
        finally:
            locked.chmod(0o700)
        assert list(locked.iterdir()) == []

    def test_the_start_probe_leaves_nothing_behind(self, tmp_path):
        a_comparer(tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_every_request_is_one_json_line_and_the_body_is_never_in_it(self, tmp_path):
        comparer, out = a_comparer(tmp_path)
        comparer.receive(SENDER, a_frame(epoch=1, count=0))
        comparer.receive(SENDER, flipped_last_byte(a_frame(epoch=1, count=1)))
        comparer.receive("stranger", a_frame())

        raw = out.getvalue()
        assert raw.count("\n") == 3
        records = lines(out)
        assert [r["event"] for r in records] == ["verdict", "refused", "refused"]
        assert all("sender" in r and "size" in r for r in records)
        # A model name from the envelope is the body's content; it stays out.
        assert "fact_orders" not in raw
        assert "payload_digest" not in raw


class TestOverTheWire:
    """The traversal ADR-0004's second box named, re-run through the shipped shell."""

    def _serving(self, tmp_path: Path, max_body: int | None = None):
        comparer, out = a_comparer(tmp_path)
        kwargs = {} if max_body is None else {"max_body": max_body}
        server = make_server(("127.0.0.1", 0), comparer, **kwargs)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, comparer, out

    def _post(self, server, path: str, data: bytes, headers: dict | None = None):
        host, port = server.server_address[0], server.server_address[1]
        request = urllib.request.Request(
            f"http://{host}:{port}{path}", data=data, method="POST", headers=headers or {}
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_a_framed_verdict_comes_back_over_the_wire_naming_the_layer(self, tmp_path):
        server, _, out = self._serving(tmp_path)
        try:
            status, first = self._post(server, f"/{SENDER}", a_frame(epoch=1, count=0))
            assert (status, first["kind"]) == (200, BASELINE)

            status, drifted = self._post(
                server, f"/{SENDER}", a_frame(a_drifted_snapshot(), epoch=1, count=1)
            )
            assert status == 200
            assert drifted["kind"] == DRIFT
            assert drifted["changed_layers"] == ["gold"]
            assert drifted["digest_changed"] is True
            print("verdict over the wire, framed:", json.dumps(drifted, sort_keys=True))
            assert [r["event"] for r in lines(out)] == ["verdict", "verdict"]
        finally:
            server.shutdown()
            server.server_close()

    def test_both_refusal_layers_are_first_class_over_the_wire(self, tmp_path):
        server, _, _ = self._serving(tmp_path)
        try:
            status, crc = self._post(server, f"/{SENDER}", flipped_last_byte(a_frame()))
            assert (status, crc["layer"], crc["control"]) == (400, LAYER_FRAME, framing.CRC_MISMATCH)

            tampered = framed(with_wrong_digest(encode_envelope(an_envelope())), 1, 0)
            status, digest = self._post(server, f"/{SENDER}", tampered)
            assert (status, digest["layer"], digest["control"]) == (422, LAYER_ENVELOPE, DIGEST_MISMATCH)
        finally:
            server.shutdown()
            server.server_close()

    def test_a_path_that_is_not_one_sender_segment_is_refused(self, tmp_path):
        server, comparer, out = self._serving(tmp_path)
        try:
            for path in ("/", f"/{SENDER}/extra", f"/{SENDER}?x=1", "/Catalyst"):
                status, body = self._post(server, path, a_frame())
                assert (status, body["control"]) == (404, UNKNOWN_SENDER), path
            assert comparer.previous is None
            assert all(r["sender"] is None for r in lines(out))
        finally:
            server.shutdown()
            server.server_close()

    def test_a_body_above_the_ceiling_is_refused_by_its_declared_length(self, tmp_path):
        server, comparer, out = self._serving(tmp_path, max_body=64)
        try:
            status, body = self._post(server, f"/{SENDER}", bytes(100))
            assert (status, body["control"]) == (413, BODY_TOO_LARGE)
            record = lines(out)[0]
            assert (record["control"], record["size"]) == (BODY_TOO_LARGE, 100)
            assert comparer.previous is None
        finally:
            server.shutdown()
            server.server_close()

    def test_a_request_without_a_length_is_refused(self, tmp_path):
        server, _, _ = self._serving(tmp_path)
        try:
            host, port = server.server_address[0], server.server_address[1]
            request = urllib.request.Request(
                f"http://{host}:{port}/{SENDER}", method="POST",
                headers={"Content-Length": "not-a-number"},
            )
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request)
            assert caught.value.code == 411
            assert json.loads(caught.value.read())["control"] == LENGTH_REQUIRED
        finally:
            server.shutdown()
            server.server_close()


class TestMain:
    def test_the_entry_point_hands_serve_what_it_parsed(self, tmp_path):
        seen = {}

        def run(bind, senders, baseline):
            seen.update(bind=bind, senders=senders, baseline=baseline)

        code = main(
            ["--bind", "10.0.0.2:8100", "--sender", "a", "--sender", "b",
             "--baseline", str(tmp_path / "b.json")],
            run=run,
        )
        assert code == 0
        assert seen == {
            "bind": ("10.0.0.2", 8100),
            "senders": ["a", "b"],
            "baseline": tmp_path / "b.json",
        }

    def test_the_bind_defaults_to_loopback(self, tmp_path):
        seen = {}
        main(["--sender", "a", "--baseline", str(tmp_path / "b.json")],
             run=lambda bind, *_: seen.update(bind=bind))
        assert seen["bind"] == ("127.0.0.1", 8100)

    @pytest.mark.parametrize("bind", ["8100", ":8100", "host:", "host:port", "host:70000"])
    def test_a_bind_that_is_not_host_and_port_is_refused(self, tmp_path, bind):
        with pytest.raises(SystemExit) as caught:
            main(["--bind", bind, "--sender", "a", "--baseline", str(tmp_path / "b.json")],
                 run=lambda *_: None)
        assert caught.value.code == 2

    def test_a_sender_is_required(self, tmp_path):
        with pytest.raises(SystemExit):
            main(["--baseline", str(tmp_path / "b.json")], run=lambda *_: None)

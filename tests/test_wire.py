# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The wire codec, and the arms that make its refusals a closed set.

ADR-0004's first precondition is that envelope v1 "round-trips and refuses
typed", so this file carries both halves: the green arms (round-trip equality,
byte determinism, the digest's permutation invariance) and calibration-style
red arms asserting the EXACT refusal control for each way bytes can be wrong -
a decoder observed only to accept has not been shown to refuse.

Fixtures ride in from test_delta (the test_deliver -> test_verify precedent):
`a_snapshot` populates all six nouns, `permuted` reverses every collection.
"""

from __future__ import annotations

import json
from dataclasses import replace

from test_delta import a_snapshot, permuted

from crosslink import (
    Envelope,
    Freshness,
    WireRefusal,
    decode_envelope,
    encode_envelope,
    fingerprint_envelope,
    snapshot_digest,
)
from crosslink.model import DeclaredKey, Metric, layered_fingerprint
from crosslink.wire import (
    DIGEST_MISMATCH,
    MALFORMED_ENVELOPE,
    UNKNOWN_PAYLOAD_KIND,
    UNKNOWN_SCHEMA_VERSION,
    WIRE_SCHEMA_VERSION,
)

A_MOMENT = "2026-09-01T00:00:00+00:00"


def an_envelope(snapshot=None) -> Envelope:
    snapshot = snapshot if snapshot is not None else a_snapshot()
    fingerprint = layered_fingerprint(snapshot.models, snapshot.sources)
    return fingerprint_envelope(snapshot, fingerprint, emitted_at=A_MOMENT)


def _as_bytes(obj) -> bytes:
    """Re-encode a tampered structure exactly as the codec would."""

    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _tampered(**changes) -> bytes:
    obj = json.loads(encode_envelope(an_envelope()))
    for name, value in changes.items():
        if value is ...:
            del obj[name]
        else:
            obj[name] = value
    return _as_bytes(obj)


class TestRoundTrip:
    def test_encode_then_decode_returns_an_equal_envelope(self):
        envelope = an_envelope()
        assert decode_envelope(encode_envelope(envelope)) == envelope

    def test_encoding_is_byte_for_byte_deterministic(self):
        """Two builds from the same inputs are the same bytes. Without this
        the payload digest would be a claim about one serializer run rather
        than about content."""

        assert encode_envelope(an_envelope()) == encode_envelope(an_envelope())

    def test_non_ascii_content_is_escaped_on_the_wire_and_round_trips(self):
        """Pins the escaping dialect: canonical JSON's ensure_ascii default is
        part of the form (a silent fourth argument), so non-ASCII content must
        travel escaped, produce pure-ASCII bytes, and still decode equal."""

        envelope = an_envelope(a_snapshot(name="caf\u00e9-m\u00e9triques"))
        encoded = encode_envelope(envelope)
        assert encoded == encoded.decode("ascii").encode("ascii")
        assert b"caf\\u00e9" in encoded
        assert decode_envelope(encoded) == envelope

    def test_the_envelope_is_versioned_and_self_described(self):
        envelope = an_envelope()
        assert envelope.schema_version == WIRE_SCHEMA_VERSION
        assert envelope.payload_kind == "fingerprint"
        assert (envelope.project_format, envelope.project_name) == ("dagster", "catalyst")


class TestSnapshotDigest:
    def test_permutation_does_not_move_the_digest(self):
        """Producer order is not content - the same invariance `diff`
        promises, inherited here through `canonical`."""

        assert snapshot_digest(a_snapshot()) == snapshot_digest(permuted(a_snapshot()))

    def test_a_declared_keys_change_moves_the_digest_while_layers_hold_still(self):
        """The blindness cure, observed: the layered fingerprint covers models
        and sources only, so a keys-only change is invisible to it - and the
        snapshot digest is what sees it."""

        base = an_envelope()
        changed = an_envelope(
            a_snapshot(declared_keys=(DeclaredKey(model="dim_date", columns=("date",)),))
        )
        assert changed.payload.layers == base.payload.layers
        assert changed.payload.snapshot_digest != base.payload.snapshot_digest

    def test_every_unlayered_noun_moves_the_digest(self):
        """All four nouns the layered fingerprint cannot see, each observed
        moving the digest on its own."""

        base = an_envelope()
        blind_spots = dict(
            declared_keys=a_snapshot().declared_keys[:1],
            declared_joins=a_snapshot().declared_joins[:1],
            semantic_models=(),
            metrics=(Metric(name="daily_revenue", measure="daily_cost", definition_sha="MOVED"),),
        )
        for noun, value in blind_spots.items():
            changed = an_envelope(a_snapshot(**{noun: value}))
            assert changed.payload.layers == base.payload.layers, noun
            assert changed.payload.snapshot_digest != base.payload.snapshot_digest, noun

    def test_freshness_and_notes_do_not_move_the_digest(self):
        """Check-time properties, not content: including either would make an
        unchanged project digest differently between two observations."""

        base = snapshot_digest(a_snapshot())
        assert snapshot_digest(a_snapshot(freshness=Freshness.STALE)) == base
        assert snapshot_digest(a_snapshot(notes=("observed late",))) == base


class TestDecodeRefusesTyped:
    """The red arms, calibration-style: the exact control per wrong shape, and
    the observed set covering the module's whole closed set."""

    def cases(self) -> dict[str, bytes]:
        flipped = json.loads(encode_envelope(an_envelope()))
        digest = flipped["payload"]["snapshot_digest"]
        flipped["payload"]["snapshot_digest"] = (
            ("0" if digest[0] != "0" else "1") + digest[1:]
        )
        return {
            "bumped-schema-version": _tampered(schema_version=WIRE_SCHEMA_VERSION + 1),
            "unknown-payload-kind": _tampered(payload_kind="proposal"),
            "flipped-payload-byte": _as_bytes(flipped),
            "non-json-bytes": b"\x00 not json at all",
            "top-level-not-an-object": b"[]",
            "missing-field": _tampered(producer_version=...),
            "extra-field": _tampered(sequence=7),
            "float-schema-version": _tampered(schema_version=1.0),
        }

    def test_the_exact_refusal_control_per_case(self):
        observed = {name: decode_envelope(data) for name, data in self.cases().items()}
        assert all(isinstance(r, WireRefusal) for r in observed.values())
        assert {name: r.control for name, r in observed.items()} == {
            "bumped-schema-version": UNKNOWN_SCHEMA_VERSION,
            "unknown-payload-kind": UNKNOWN_PAYLOAD_KIND,
            "flipped-payload-byte": DIGEST_MISMATCH,
            "non-json-bytes": MALFORMED_ENVELOPE,
            "top-level-not-an-object": MALFORMED_ENVELOPE,
            "missing-field": MALFORMED_ENVELOPE,
            "extra-field": MALFORMED_ENVELOPE,
            "float-schema-version": MALFORMED_ENVELOPE,
        }

    def test_the_cases_cover_the_whole_control_set(self):
        """A control no red arm produces is a refusal this suite has never
        observed firing - the decoder equivalent of a check never seen red."""

        observed = {decode_envelope(data).control for data in self.cases().values()}
        assert observed == {
            UNKNOWN_SCHEMA_VERSION,
            UNKNOWN_PAYLOAD_KIND,
            DIGEST_MISMATCH,
            MALFORMED_ENVELOPE,
        }

    def test_a_sequence_field_is_refused_not_read(self):
        """The absence of coordination state is load-bearing (ADR-0004): an
        envelope claiming an ordering is refused as malformed, so a
        consumer-trusted sequence cannot arrive by leniency."""

        refusal = decode_envelope(_tampered(sequence=7))
        assert isinstance(refusal, WireRefusal)
        assert refusal.control == MALFORMED_ENVELOPE

    def test_version_is_checked_before_shape(self):
        """A future v2 with a different shape must refuse as the unknown
        version it is, not as malformed - this ordering is the contract that
        makes a version bump diagnosable from the refusal alone."""

        obj = {"schema_version": WIRE_SCHEMA_VERSION + 1, "an_entirely": "different shape"}
        refusal = decode_envelope(_as_bytes(obj))
        assert isinstance(refusal, WireRefusal)
        assert refusal.control == UNKNOWN_SCHEMA_VERSION

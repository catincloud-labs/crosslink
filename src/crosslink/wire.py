# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The wire layer: a versioned envelope, and the fingerprint that rides in it.

ADR-0004 names the first payload, a fingerprint, and the kind of service it
travels to, and this module is the codec half of that arc: what
an envelope *is*, how it becomes bytes, and how bytes become an envelope or a
typed refusal. What a service *does* with two envelopes lives in
:mod:`crosslink.service`, for the reason ADR-0004's consequences give.

Three decisions shape everything here:

- **The schema version lives beside the codec,** and moves with the types
  it describes in the same commit, as ADR-0004 decides and argues. One
  module, one constant, one commit.

- **Canonical JSON is stdlib ``json.dumps``, and the whole call is the
  spec** - ``sort_keys=True``, ``separators=(",", ":")``,
  ``allow_nan=False``, plus the ``ensure_ascii=True`` *default*, which is a
  silent fourth participant: it decides how every non-ASCII character
  escapes, so a second producer that copies the three named arguments but
  not the default would emit a dialect. ``_canonical_json`` below is the
  one authoritative statement of the form. It is not yaml, though the
  tree's one earlier hash of a serialized value is over yaml (ADR-0004 says
  why that one is): yaml as an output has presentation freedom a wire
  digest must not inherit.

- **Decode returns, never raises,** as ADR-0004 decides for refusals -
  the same posture the tier-2 ``fingerprint()`` contract takes. Every way
  the bytes can be wrong maps to a :class:`WireRefusal` carrying a control
  from the closed set below.

What is deliberately absent: any monotonic sequence, generation, or fencing
field, which ADR-0004 keeps off the wire and says why. Also absent: any
minted identity. The envelope's
``project_format`` / ``project_name`` are self-description copied from the
declarations - addressing data a reader may use to refuse a comparison, not a
credential anything should trust.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields as dataclass_fields
from datetime import datetime, timezone
from typing import Any

from .delta import canonical
from .model import Fingerprint, ProjectDeclarations, definition_hash

__all__ = [
    "DIGEST_MISMATCH",
    "Envelope",
    "FINGERPRINT_KIND",
    "FingerprintPayload",
    "MALFORMED_ENVELOPE",
    "UNKNOWN_PAYLOAD_KIND",
    "UNKNOWN_SCHEMA_VERSION",
    "WIRE_SCHEMA_VERSION",
    "WireRefusal",
    "decode_envelope",
    "encode_envelope",
    "fingerprint_envelope",
    "snapshot_digest",
]

# Bump this ONLY when the envelope's own shape changes, and in the same commit
# as the change. A new payload kind is not a new envelope version: delta and
# proposal, when their gates open (ADR-0004's consequences), arrive as new
# `payload_kind` values inside this schema.
WIRE_SCHEMA_VERSION = 1

FINGERPRINT_KIND = "fingerprint"

# The closed control set a decode can refuse with. `identity-mismatch` is
# deliberately NOT here: each envelope in a mismatched pair is individually
# valid, so only the comparer can see that refusal, and the comparer owns it.
UNKNOWN_SCHEMA_VERSION = "unknown-schema-version"
UNKNOWN_PAYLOAD_KIND = "unknown-payload-kind"
MALFORMED_ENVELOPE = "malformed-envelope"
DIGEST_MISMATCH = "digest-mismatch"


@dataclass(frozen=True)
class WireRefusal:
    """A decode (or, downstream, a compare) that declines, saying why.

    ``control`` is machine-readable and drawn from a closed set; ``reason`` is
    for the human reading a log.
    """

    control: str
    reason: str


@dataclass(frozen=True)
class FingerprintPayload:
    """Both halves of the drift question, deliberately.

    ``layers`` and ``models`` are the shipped layered fingerprint - the
    conformance-pinned semantics that answer *which part* changed.
    ``snapshot_digest`` hashes the whole canonical snapshot, which reaches
    the four nouns the layers never read. ADR-0004 decides to carry both,
    says why one half alone fails, and prices the overlap. The comparer pays
    that price by giving a digest-only difference a verdict shape of its own
    rather than folding it away.
    """

    layers: dict[str, str]
    models: tuple[str, ...]
    snapshot_digest: str


@dataclass(frozen=True)
class Envelope:
    """One wire message: self-described, versioned, digest-checked.

    ``emitted_at`` and ``producer_version`` are informational only - no reader
    may branch on them, because a claim about time or software at the other
    end of a wire is not verifiable from here. They exist for the log line, not
    the verdict.
    """

    schema_version: int
    payload_kind: str
    project_format: str
    project_name: str
    emitted_at: str
    producer_version: str
    payload: FingerprintPayload
    payload_digest: str


def _canonical_json(obj: object) -> str:
    # This call IS the canonical form - the named arguments AND the
    # ensure_ascii=True default; see the module docstring.
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def snapshot_digest(declarations: ProjectDeclarations) -> str:
    """A content hash over everything the project declares.

    Canonicalized first (:func:`crosslink.delta.canonical`), so producer
    ordering cannot move the digest - the same permutation-invariance `diff`
    promises. Covers ``format``, ``name``, and all six declaration nouns;
    excludes ``freshness`` and ``notes``, which are check-time properties
    rather than content - including either would make an unchanged project
    digest differently between two observations.

    The exclusions are a drop-list rather than an include-list on purpose: a
    noun added to :class:`ProjectDeclarations` joins the digest by default, so
    the failure direction is a reported change, never a silent blind spot -
    the defect this digest exists to cure in the layered fingerprint.

    Inherits ``canonical``'s refusal of a conflicting duplicate identity,
    which raises ``ValueError``. That is the builder side's input contract -
    a snapshot is the caller's own data, not bytes off a network - so the
    decode posture ("returns, never raises") does not apply here.
    """

    body = asdict(canonical(declarations))
    del body["freshness"], body["notes"]
    return definition_hash(_canonical_json(body))


def _payload_digest(payload: FingerprintPayload) -> str:
    return definition_hash(_canonical_json(asdict(payload)))


def fingerprint_envelope(
    declarations: ProjectDeclarations,
    fingerprint: Fingerprint,
    *,
    emitted_at: str | None = None,
) -> Envelope:
    """Build the v1 envelope for a project's current fingerprint.

    ``emitted_at`` is injectable so a test (or any caller that already knows
    the time) gets byte-identical output; left ``None`` it is stamped now, in
    UTC, RFC3339.
    """

    # Lazy on purpose: the package root imports this module, so a top-level
    # import of `crosslink` would be circular. By the time anything builds an
    # envelope, the root is fully initialized.
    from crosslink import __version__

    when = (
        emitted_at
        if emitted_at is not None
        else datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    payload = FingerprintPayload(
        layers=dict(fingerprint.layers),
        models=tuple(fingerprint.models),
        snapshot_digest=snapshot_digest(declarations),
    )
    return Envelope(
        schema_version=WIRE_SCHEMA_VERSION,
        payload_kind=FINGERPRINT_KIND,
        project_format=declarations.format,
        project_name=declarations.name,
        emitted_at=when,
        producer_version=__version__,
        payload=payload,
        payload_digest=_payload_digest(payload),
    )


def encode_envelope(envelope: Envelope) -> bytes:
    """The envelope as canonical JSON bytes - deterministic, UTF-8."""

    return _canonical_json(asdict(envelope)).encode("utf-8")


def _is_str(value: object) -> bool:
    return isinstance(value, str)


def _is_int(value: object) -> bool:
    # bool is an int subclass and 1.0 == 1; both would smuggle a wrong type
    # through an equality check, so the type is checked before the value.
    return isinstance(value, int) and not isinstance(value, bool)


# Derived, not declared: a second copy of the field lists would be a schema
# beside the schema, agreeing until one was edited. A field added to either
# dataclass joins the strict shape check by itself; what it does NOT join by
# itself is the per-field validation and construction in `decode_envelope`,
# which is the "owes the codec a look, in the same commit" tax the record
# prices - and the round-trip arm fails loudly on a field decode drops.
_ENVELOPE_FIELDS = tuple(f.name for f in dataclass_fields(Envelope))
_PAYLOAD_FIELDS = tuple(f.name for f in dataclass_fields(FingerprintPayload))

# What the names above hold by construction, checked when the module loads.
# An explicit `raise`, never `assert`, which `python -O` strips. Each check
# has a planted wrong fact in `tests/test_load_time_checks.py`.
if len({UNKNOWN_SCHEMA_VERSION, UNKNOWN_PAYLOAD_KIND, MALFORMED_ENVELOPE, DIGEST_MISMATCH}) != 4:
    raise RuntimeError("wire: two decode controls are one string, so a refusal cannot say which check failed")
if set(_ENVELOPE_FIELDS) != {
    "schema_version", "payload_kind", "project_format", "project_name",
    "emitted_at", "producer_version", "payload", "payload_digest",
}:
    raise RuntimeError("wire: the envelope's fields are not the names decode_envelope reads")
if set(_PAYLOAD_FIELDS) != {"layers", "models", "snapshot_digest"}:
    raise RuntimeError("wire: the payload's fields are not the names decode_envelope reads")


def decode_envelope(data: bytes) -> Envelope | WireRefusal:
    """Bytes to envelope, or a typed refusal - never an exception.

    The checks run in a stated order, because the order is the contract a
    future version leans on: parse, then **version before shape** - a v2
    envelope with a different shape must refuse as ``unknown-schema-version``,
    not as malformed - then kind, then shape, then the digest. Strict on
    shape: an extra field in a known version is refused, because leniency is
    how one schema version quietly becomes two dialects.
    """

    obj = _parsed(data)
    if isinstance(obj, WireRefusal):
        return obj
    refused = _header_refusal(obj) or _shape_refusal(obj)
    if refused is not None:
        return refused
    payload = _decoded_payload(obj["payload"])
    if isinstance(payload, WireRefusal):
        return payload
    if _payload_digest(payload) != obj["payload_digest"]:
        return WireRefusal(
            DIGEST_MISMATCH,
            "payload_digest does not match the payload it arrived with",
        )

    return Envelope(
        schema_version=obj["schema_version"],
        payload_kind=obj["payload_kind"],
        project_format=obj["project_format"],
        project_name=obj["project_name"],
        emitted_at=obj["emitted_at"],
        producer_version=obj["producer_version"],
        payload=payload,
        payload_digest=obj["payload_digest"],
    )


# The stages of `decode_envelope`, each run only once the one before it has
# passed, in the order its docstring states: parse, version, kind, shape,
# payload. The digest is checked last, by `decode_envelope` itself.


def _parsed(data: bytes) -> dict[str, Any] | WireRefusal:
    """The top-level JSON object, or the refusal of bytes that are not one."""

    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        return WireRefusal(MALFORMED_ENVELOPE, f"not UTF-8 JSON: {error}")
    if not isinstance(obj, dict):
        return WireRefusal(MALFORMED_ENVELOPE, "the top level is not a JSON object")
    return obj


def _header_refusal(obj: dict[str, Any]) -> WireRefusal | None:
    """Version before kind, and both before shape."""

    if "schema_version" not in obj or not _is_int(obj["schema_version"]):
        return WireRefusal(
            MALFORMED_ENVELOPE, "schema_version is missing or not an integer"
        )
    if obj["schema_version"] != WIRE_SCHEMA_VERSION:
        return WireRefusal(
            UNKNOWN_SCHEMA_VERSION,
            f"schema_version {obj['schema_version']!r} is not the known "
            f"version {WIRE_SCHEMA_VERSION}",
        )

    if "payload_kind" not in obj or not _is_str(obj["payload_kind"]):
        return WireRefusal(
            MALFORMED_ENVELOPE, "payload_kind is missing or not a string"
        )
    if obj["payload_kind"] != FINGERPRINT_KIND:
        return WireRefusal(
            UNKNOWN_PAYLOAD_KIND,
            f"payload_kind {obj['payload_kind']!r} is not a kind this "
            f"version carries",
        )
    return None


def _shape_refusal(obj: dict[str, Any]) -> WireRefusal | None:
    """Exactly the envelope's fields, and a string in each string field."""

    if sorted(obj) != sorted(_ENVELOPE_FIELDS):
        return WireRefusal(
            MALFORMED_ENVELOPE,
            f"envelope fields {sorted(obj)} are not exactly "
            f"{sorted(_ENVELOPE_FIELDS)}",
        )
    for name in ("project_format", "project_name", "emitted_at",
                 "producer_version", "payload_digest"):
        if not _is_str(obj[name]):
            return WireRefusal(MALFORMED_ENVELOPE, f"{name} is not a string")
    return None


def _decoded_payload(raw: object) -> FingerprintPayload | WireRefusal:
    """The payload, or the refusal of one that is not exactly its shape."""

    if not isinstance(raw, dict) or sorted(raw) != sorted(_PAYLOAD_FIELDS):
        return WireRefusal(
            MALFORMED_ENVELOPE,
            f"payload fields are not exactly {sorted(_PAYLOAD_FIELDS)}",
        )
    layers, models = raw["layers"], raw["models"]
    if not isinstance(layers, dict) or not all(
        _is_str(k) and _is_str(v) for k, v in layers.items()
    ):
        return WireRefusal(
            MALFORMED_ENVELOPE, "payload.layers is not a string-to-string map"
        )
    if not isinstance(models, list) or not all(_is_str(m) for m in models):
        return WireRefusal(
            MALFORMED_ENVELOPE, "payload.models is not a list of strings"
        )
    if not _is_str(raw["snapshot_digest"]):
        return WireRefusal(
            MALFORMED_ENVELOPE, "payload.snapshot_digest is not a string"
        )
    return FingerprintPayload(
        layers=dict(layers),
        models=tuple(models),
        snapshot_digest=raw["snapshot_digest"],
    )


# What `__all__` holds by construction, checked when the module loads: every
# name it exports is defined here. An explicit `raise`, never `assert`, which
# `python -O` strips; its plant is in `tests/test_load_time_checks.py`.
if [name for name in __all__ if name not in globals()]:
    raise RuntimeError("wire: a name in __all__ is not defined in the module")

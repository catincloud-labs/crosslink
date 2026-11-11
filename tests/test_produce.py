# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The producer as a process: a graph reduced, published, framed and posted to the shipped comparer.

`test_serve.py` proved the comparer against frames the test built by hand.
This file closes the loop: the producer
builds the frame, the store mints its epoch, and the real `crosslink.serve`
answers it over localhost -- a baseline, then a no-drift at the next epoch,
then a drift naming the layer. Around that, the arms the module docstring
states: the tree's carve is applied, the three declaration directories are
read by stem, a dry run opens nothing even where a store is configured, a
refused publication frames nothing and a store that is gone raises, a
comparer that answers anything is an answer and a listener that answers
nothing, or not in HTTP, is `unreachable`, and the request names no software.

The graph is this module's own attributes, loaded by `--load test_produce:...`
exactly as a deployment loads the tree it reduces, so the import path the
producer takes is the real one. The store is `ration.memory.MemoryStore`, the
frame codec and the publish protocol are the real ones from the `[service]`
extra.
"""

from __future__ import annotations

import io
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from ration import frame as framing
from ration import publish
from ration.contract import Record, Unreachable
from ration.memory import MemoryStore
from test_project import _Definition, _Key
from test_serve import a_comparer, lines

from crosslink import decode_envelope
from crosslink.conformance import a_single_key_declaration, a_source_declaration
from crosslink.produce import (
    EVENT_ANSWERED,
    EVENT_REDUCED,
    EVENT_SUPERSEDED,
    EVENT_UNREACHABLE,
    USER_AGENT,
    main,
    read_declarations,
    resolve,
)
from crosslink.serve import LAYER_COMPARER, UNKNOWN_SENDER, make_server
from crosslink.service import BASELINE, DRIFT, NO_DRIFT

SENDER = "catalyst"
TOPIC = "catalyst-fingerprint"
PUBLISHER = "test-publisher"
DSN = {"RATION_DSN": "postgresql://unused-the-store-is-injected"}

RAW, STAGED, FACT, TENANT = _Key("raw_events"), _Key("stg_events"), _Key("fct_events"), _Key("fct_tenant")

# Four definitions, one of them another project's: one Gold model carries
# `metadata["dbt_project"]`, which is what `carve` below reads.
GRAPH = [
    _Definition([RAW], metadata={RAW: {"layer": "Bronze"}}),
    _Definition([STAGED], deps={STAGED: {RAW}}, metadata={STAGED: {"layer": "Silver"}}),
    _Definition([FACT], deps={FACT: {STAGED}}, metadata={FACT: {"layer": "Gold"}}),
    _Definition(
        [TENANT], deps={TENANT: {STAGED}},
        metadata={TENANT: {"layer": "Gold", "dbt_project": "tenant"}},
    ),
]

# The same graph after a Gold model gained an edge.
DRIFTED = [
    *GRAPH[:2],
    _Definition([FACT], deps={FACT: {STAGED, RAW}}, metadata={FACT: {"layer": "Gold"}}),
    GRAPH[3],
]

NOT_CALLABLE = 3


def carve(definitions):
    """The tree's carve in miniature: drop every definition marked as another project's."""

    return [
        d for d in definitions
        if not any("dbt_project" in (m or {}) for m in d.metadata_by_key.values())
    ]


def argv_for(url: str, *extra: str, load: str = "test_produce:GRAPH", carved: bool = True) -> list[str]:
    argv = ["--load", load, "--name", "catalyst", "--publish-topic", TOPIC,
            "--publisher", PUBLISHER, "--post", url]
    if carved:
        argv += ["--carve", "test_produce:carve"]
    return argv + list(extra)


def run(argv: list[str], store=None, environ=DSN):
    """One invocation: its exit status, its one line, and the DSNs it opened a store for."""

    out, opened = io.StringIO(), []

    def open_store(dsn):
        opened.append(dsn)
        return store

    code = main(argv, environ=environ, open_store=open_store, out=out)
    assert out.getvalue().count("\n") == 1, "a run is exactly one line"
    return code, json.loads(out.getvalue()), opened


def a_closed_port() -> int:
    """A port nothing listens on: bound once, then released."""

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class _Recorder(BaseHTTPRequestHandler):
    """Records what arrived and answers like a comparer's baseline."""

    seen: list

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.seen.append((dict(self.headers), body))
        answer = json.dumps({"kind": BASELINE}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(answer)))
        self.end_headers()
        self.wfile.write(answer)

    def log_message(self, fmt, *args) -> None:
        pass


@pytest.fixture
def comparer(tmp_path):
    """The shipped comparer on a kernel-chosen port, and its log."""

    held, out = a_comparer(tmp_path)
    server = make_server(("127.0.0.1", 0), held)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", out
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def recorder():
    seen: list = []

    class Handler(_Recorder):
        pass

    Handler.seen = seen
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/{SENDER}", seen
    finally:
        server.shutdown()
        server.server_close()


# What a wrong port answers with: a banner, not a status line.
BANNER = b"SSH-2.0-" + b"x" * 1000 + b"\r\n"


@pytest.fixture
def not_http():
    """A listener that reads a whole request, answers in something other than HTTP, and closes cleanly.

    The whole request is read first so the close is a FIN rather than a reset:
    a reset is an `OSError`, which the producer already caught, and would pass
    this test for the wrong reason.
    """

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def answer() -> None:
        conn, _ = listener.accept()
        with conn:
            conn.settimeout(10)
            received = b""
            while b"\r\n\r\n" not in received:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                received += chunk
            head, _, body = received.partition(b"\r\n\r\n")
            length = next(
                int(line.split(b":", 1)[1]) for line in head.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            while len(body) < length:
                chunk = conn.recv(65536)
                if not chunk:
                    return
                body += chunk
            conn.sendall(BANNER)
            conn.shutdown(socket.SHUT_WR)
            while conn.recv(65536):
                pass

    thread = threading.Thread(target=answer, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}/{SENDER}"
    finally:
        listener.close()
        thread.join(timeout=10)


class TestAgainstTheComparer:
    """The loop, closed: producer, store, frame, comparer."""

    def test_a_baseline_then_no_drift_then_drift_naming_the_layer(self, comparer):
        base, log = comparer
        url, store = f"{base}/{SENDER}", MemoryStore()

        code, first, _ = run(argv_for(url), store)
        assert (code, first["event"], first["status"]) == (0, EVENT_ANSWERED, 200)
        assert first["answer"]["kind"] == BASELINE

        code, second, _ = run(argv_for(url), store)
        assert (code, second["answer"]["kind"]) == (0, NO_DRIFT)

        code, third, _ = run(argv_for(url, load="test_produce:DRIFTED"), store)
        assert code == 0, "drift is the comparer's news, not a producer failure"
        assert third["answer"]["kind"] == DRIFT
        assert third["answer"]["changed_layers"] == ["gold"]

        # Each run's epoch is the generation its publication returned, and the
        # comparer ledgered exactly those, each at count zero.
        assert [first["epoch"], second["epoch"], third["epoch"]] == [1, 2, 3]
        verdicts = lines(log)
        assert [(r["epoch"], r["count"]) for r in verdicts] == [(1, 0), (2, 0), (3, 0)]
        assert [r["event"] for r in verdicts] == ["verdict"] * 3

    def test_the_pointer_names_the_payload_digest_and_the_publisher(self, comparer):
        base, _ = comparer
        store = MemoryStore()
        _, line, opened = run(argv_for(f"{base}/{SENDER}"), store)

        standing = publish.current(store, TOPIC)
        assert (standing.artefact, standing.publisher) == (line["payload_digest"], PUBLISHER)
        assert standing.generation == line["epoch"]
        assert opened == [DSN["RATION_DSN"]]

    def test_the_epoch_continues_from_whatever_the_topic_stands_at(self, comparer):
        """A store is not fresh on a deployment's first run; the epoch is its generation, whatever that is."""

        base, log = comparer
        store = MemoryStore()
        for generation in range(4):
            publish.publish(store, TOPIC, f"earlier-{generation}", PUBLISHER, generation=generation)

        _, line, _ = run(argv_for(f"{base}/{SENDER}"), store)
        assert line["epoch"] == 5
        assert lines(log)[0]["epoch"] == 5

    def test_a_refusal_is_an_answer_and_exits_nonzero(self, comparer):
        base, _ = comparer
        code, line, _ = run(argv_for(f"{base}/stranger"), MemoryStore())

        assert (code, line["event"], line["status"]) == (1, EVENT_ANSWERED, 404)
        assert (line["answer"]["layer"], line["answer"]["control"]) == (LAYER_COMPARER, UNKNOWN_SENDER)


class TestWhatCrosses:
    def test_the_frame_is_the_envelope_at_the_start_of_the_publication_epoch(self, recorder):
        url, seen = recorder
        _, line, _ = run(argv_for(url), MemoryStore())

        (_, body), = seen
        frame = framing.decode(body, framing.SequenceLedger())
        assert isinstance(frame, framing.Frame)
        assert frame.kind == framing.FINGERPRINT
        assert frame.sequence == framing.Sequence.start(line["epoch"])
        envelope = decode_envelope(frame.body)
        assert envelope.payload_digest == line["payload_digest"]
        assert len(frame.body) == line["envelope_size"]
        assert (envelope.project_format, envelope.project_name) == ("dagster", "catalyst")

    def test_the_request_names_no_software(self, recorder):
        url, seen = recorder
        run(argv_for(url), MemoryStore())

        (headers, _), = seen
        assert headers["User-Agent"] == USER_AGENT
        assert headers["Content-Type"] == "application/octet-stream"
        assert not any("crosslink" in v.lower() or "python" in v.lower() for v in headers.values())

    def test_the_line_carries_no_model_name(self, recorder):
        url, _ = recorder
        out = io.StringIO()
        main(argv_for(url), environ=DSN, open_store=lambda _: MemoryStore(), out=out)

        assert "fct_events" not in out.getvalue()
        assert "raw_events" not in out.getvalue()
        assert "crosslink" not in out.getvalue()


class TestTheReduction:
    def test_a_dry_run_reduces_and_opens_nothing(self):
        code, line, opened = run(
            argv_for(f"http://127.0.0.1:{a_closed_port()}/{SENDER}", "--dry-run"), environ={}
        )
        assert (code, line["event"], opened) == (0, EVENT_REDUCED, [])
        assert line["models"] == 3
        assert line["layers"] == ["bronze", "gold", "silver"]
        assert "epoch" not in line and "topic" not in line

    def test_a_dry_run_opens_nothing_where_a_store_is_configured(self, recorder):
        """A deployed producer's environment carries `RATION_DSN`, so that is where a dry run is tried."""

        url, seen = recorder
        store = MemoryStore()
        code, line, opened = run(argv_for(url, "--dry-run"), store, environ=DSN)

        assert (code, line["event"], opened, seen) == (0, EVENT_REDUCED, [], [])
        assert publish.current(store, TOPIC) is None

    def test_without_the_carve_the_marked_model_is_reduced_too(self):
        """The carve decides what is reduced: three models with it, four without."""

        url = f"http://127.0.0.1:{a_closed_port()}/{SENDER}"
        _, carved, _ = run(argv_for(url, "--dry-run"), environ={})
        _, uncarved, _ = run(argv_for(url, "--dry-run", carved=False), environ={})

        assert (carved["models"], uncarved["models"]) == (3, 4)
        assert carved["payload_digest"] != uncarved["payload_digest"]

    def test_the_three_directories_are_read_by_stem_and_only_yml(self, tmp_path):
        url = f"http://127.0.0.1:{a_closed_port()}/{SENDER}"
        declared, sources = tmp_path / "declared", tmp_path / "sources"
        declared.mkdir()
        sources.mkdir()
        _, bare, _ = run(argv_for(url, "--dry-run"), environ={})

        # A source is keyed by the model that reads it, which is the filename stem.
        (sources / "fct_events.yml").write_text(a_source_declaration(), encoding="utf-8")
        (sources / "ignored.yaml").write_text("not: read\n", encoding="utf-8")
        _, with_sources, _ = run(
            argv_for(url, "--dry-run", "--sources", str(sources)), environ={}
        )
        assert bare["layers"] == ["bronze", "gold", "silver"]
        assert with_sources["layers"] == ["bronze", "gold", "silver", "sources"]
        # The key is the stem. Nothing on the wire
        # tells a stem from a filename -- a reader the graph does not build is a
        # note, and notes are outside the digest -- so the contract is held here.
        assert read_declarations(sources) == {"fct_events": a_source_declaration()}
        assert read_declarations(None) == {}

        # A declared key moves the snapshot digest and no layer.
        (declared / "fct_events.yml").write_text(
            a_single_key_declaration("fct_events", "event_id"), encoding="utf-8"
        )
        _, with_keys, _ = run(
            argv_for(url, "--dry-run", "--sources", str(sources), "--declared", str(declared)),
            environ={},
        )
        assert with_keys["layers"] == with_sources["layers"]
        assert with_keys["payload_digest"] != with_sources["payload_digest"]

    def test_a_carve_that_is_not_callable_raises(self):
        argv = argv_for("http://127.0.0.1:1/x", "--dry-run", carved=False)
        with pytest.raises(TypeError, match="not a callable"):
            run(argv + ["--carve", "test_produce:NOT_CALLABLE"], environ={})

    def test_resolve_imports_by_path(self):
        assert resolve("test_produce:GRAPH") is GRAPH
        with pytest.raises(ValueError, match="MODULE:NAME"):
            resolve("test_produce.GRAPH")


class TestWhenNothingIsFramed:
    def test_a_publisher_raced_past_is_superseded_and_nothing_is_posted(self, recorder):
        url, seen = recorder

        class Raced(MemoryStore):
            """A second writer lands between this run's reading and its advance."""

            raced = False

            def compare_and_set(self, key, expected_version, record, *, ttl=None):
                if not self.raced:
                    self.raced = True
                    super().compare_and_set(key, expected_version, Record(b"other", "someone-else"))
                return super().compare_and_set(key, expected_version, record, ttl=ttl)

        store = Raced()
        code, line, _ = run(argv_for(url), store)

        assert (code, line["event"], line["read_generation"]) == (1, EVENT_SUPERSEDED, 0)
        assert "epoch" not in line
        assert seen == []
        assert publish.current(store, TOPIC).publisher == "someone-else"

    def test_a_comparer_that_answers_nothing_is_unreachable(self):
        """The publication stands anyway: the pointer is a fact about the
        producer's output, and tomorrow's run is a fresh epoch."""

        store = MemoryStore()
        code, line, _ = run(argv_for(f"http://127.0.0.1:{a_closed_port()}/{SENDER}"), store)

        assert (code, line["event"], line["epoch"]) == (1, EVENT_UNREACHABLE, 1)
        assert line["detail"]
        assert publish.current(store, TOPIC).generation == 1

    def test_a_listener_that_does_not_speak_http_is_unreachable(self, not_http):
        """Something answered, but not the comparer: still the run's one line, not a traceback."""

        store = MemoryStore()
        code, line, _ = run(argv_for(not_http), store)

        assert (code, line["event"], line["epoch"]) == (1, EVENT_UNREACHABLE, 1)
        assert line["detail"].startswith("BadStatusLine")
        assert len(line["detail"]) < len(BANNER), "the listener's text is bounded"
        assert publish.current(store, TOPIC).generation == 1

    def test_a_store_that_is_gone_raises_and_nothing_is_framed(self, recorder):
        """`Unreachable` propagates, as `publish.py` propagates it: no line, no request."""

        url, seen = recorder

        class Gone(MemoryStore):
            def read(self, key):
                raise Unreachable("the store is gone")

        out = io.StringIO()
        with pytest.raises(Unreachable):
            main(argv_for(url), environ=DSN, open_store=lambda _: Gone(), out=out)
        assert (out.getvalue(), seen) == ("", [])


class TestTheCommandLine:
    def test_no_store_refuses_before_the_graph_is_imported(self):
        with pytest.raises(SystemExit) as caught:
            main(argv_for("http://127.0.0.1:1/x", load="no_such_module:anything"),
                 environ={"RATION_DSN": "   "}, open_store=pytest.fail)
        assert caught.value.code == 2

    def test_a_named_directory_that_does_not_exist_is_refused(self, tmp_path):
        with pytest.raises(SystemExit) as caught:
            main(argv_for("http://127.0.0.1:1/x", "--sources", str(tmp_path / "missing")),
                 environ=DSN, open_store=pytest.fail)
        assert caught.value.code == 2

    @pytest.mark.parametrize("flag, value", [
        ("--load", "no_colon"), ("--load", "a:b:c"), ("--carve", "a.b"),
        ("--post", "file:///etc/hosts"), ("--post", "127.0.0.1:8100/x"),
        ("--post", "http://127.0.0.1:81oo/x"), ("--post", "http://127.0.0.1:99999/x"),
        ("--post", "http://127.0.0.1:0/x"),
        ("--name", " "), ("--publisher", ""), ("--publish-topic", ""),
    ])
    def test_a_malformed_argument_is_refused(self, flag, value):
        flags = {"--load": "test_produce:GRAPH", "--name": "catalyst", "--publish-topic": TOPIC,
                 "--publisher": PUBLISHER, "--post": "http://127.0.0.1:1/x", flag: value}
        argv = [part for pair in flags.items() for part in pair]
        with pytest.raises(SystemExit) as caught:
            main(argv, environ=DSN, open_store=pytest.fail)
        assert caught.value.code == 2

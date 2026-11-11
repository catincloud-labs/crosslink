# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Patch generation: search against the oracle, with a model as the searcher.

The write path's last component, and the only swappable one. ADR-0003 fixed
the mechanism before anything here existed: the intended effect of a change is
stated as a :class:`~crosslink.delta.Delta` in advance, and a patch is
accepted only when applying it in a sandbox and re-reducing closes that
delta. Generation therefore is never "a model writes a patch and we hope" -
it is search against an oracle that already knows the answer, and this module
is the search loop. Nothing downstream changes: an accepted attempt carries
the same :class:`~crosslink.verify.Verdict` a hand-written patch would, and
:class:`~crosslink.deliver.PatchObject` neither knows nor asks who wrote the
edits it carries.

Four decisions here are deliberate, each stated rather than absorbed:

**The proposer is a callable, not a client.** The loop receives a
:data:`Proposer` and calls it - the same discipline the delivery adapter used
for its forge half. The core is provable with hand-written proposers, no
network and no credential anywhere near it; :func:`claude_proposer` is one
adapter behind that seam, and a different model, a different vendor, or a
human typing JSON are all the same seam. This is what "the swappable last
component" means made structural rather than promised.

**A proposal is a tree edit, not a patch function.** A model emits data, and
:class:`TreeEdit` is that data given a shape: per-entry set-or-remove over the
tree's models and its three text mappings - the same set-or-``None`` grammar
:class:`~crosslink.deliver.PatchObject` uses for file edits, because both are
statements about a tree rather than about declarations. The edit compiles to
a :data:`~crosslink.verify.Patch` (``TreeEdit.apply``), so the harness judges
a generated proposal by exactly the machinery that judged hand-written ones.

**A crash is feedback here, and only here.** :func:`~crosslink.verify.verify`
is right to let a broken patch raise - dressing a crash as a verdict would
hide it from whoever wrote the patch. But this module *is* whoever wrote the
patch, and retry policy is the generator's to own: an attempt whose edit the
sandbox refuses to apply is recorded with the error verbatim and ``verdict``
``None`` - never dressed as a verdict - and the next attempt sees it. The
oracle's own refusals feed back the same way, disagreements and all, which is
what makes a second attempt a correction rather than a re-roll.

**Exhaustion is an outcome, not an exception.** A model that fails to close a
delta within its budget has produced evidence - every refused attempt, each
with the oracle's stated-versus-observed disagreement or the sandbox's error -
and :class:`Generation` carries that trace whether or not an attempt was
accepted. Raising would discard exactly the artifact a calibration run needs.
:class:`GenerationError` is reserved for the channel failing (a refused or
truncated model response), never for the search failing.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields as dataclass_fields
from textwrap import indent
from typing import Any

from .delta import Delta
from .model import ProjectModel
from .verify import ProjectTree, Verdict, verify

__all__ = [
    "Attempt",
    "Generation",
    "GenerationError",
    "ProposalRequest",
    "Proposer",
    "TreeEdit",
    "claude_proposer",
    "generate",
    "render_request",
]


class GenerationError(RuntimeError):
    """The model channel failed - a refused or truncated response - as
    opposed to the search failing, which is a :class:`Generation` that does
    not close, or the input being wrong, which is a :class:`ValueError`."""


@dataclass(frozen=True)
class TreeEdit:
    """One proposed edit to a :class:`~crosslink.verify.ProjectTree`.

    Each mapping is per-entry set-or-remove: a string (or, for ``models``, a
    :class:`~crosslink.model.ProjectModel`) sets the entry to that full new
    value whether or not it existed, and ``None`` removes it. Setting needs no
    add-versus-change distinction - this is tree space, where writing an entry
    is writing an entry - but removing what is not there is a statement about
    nothing, and refuses at apply time so the refusal can name the tree.

    Two shapes are refused at construction, where they are made: a ``models``
    entry whose value's name differs from its key (an entry keeps its
    identity; a rename is a removal and a set, stated as two entries), and -
    by the mapping type itself - a key stated twice, so a self-contradicting
    edit has no way to exist.
    """

    models: Mapping[str, ProjectModel | None] = field(default_factory=dict)
    declaration_sources: Mapping[str, str | None] = field(default_factory=dict)
    semantic_sources: Mapping[str, str | None] = field(default_factory=dict)
    source_declarations: Mapping[str, str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Copy at the boundary: a frozen edit over a caller's live dict would
        # be frozen in name only.
        for f in dataclass_fields(self):
            object.__setattr__(self, f.name, dict(getattr(self, f.name)))
        for name, value in self.models.items():
            if value is not None and value.name != name:
                raise ValueError(
                    f"a models entry keeps its identity: key {name!r} sets a "
                    f"model named {value.name!r}; a rename is a removal and a "
                    f"set, stated as two entries"
                )

    @property
    def is_empty(self) -> bool:
        return not (
            self.models
            or self.declaration_sources
            or self.semantic_sources
            or self.source_declarations
        )

    def apply(self, tree: ProjectTree) -> ProjectTree:
        """The tree with this edit applied - a :data:`~crosslink.verify.Patch`.

        Refuses - with :class:`ValueError`, never a guess - the removal of an
        entry the tree does not hold. Everything else the tree itself refuses
        (two models whose names collide casefolded, for instance) surfaces
        when the patched tree reduces, at the site that made it.
        """

        models = {m.name: m for m in tree.models}
        for name, value in self.models.items():
            if value is None:
                if name not in models:
                    raise ValueError(
                        f"cannot remove model {name!r}: the tree defines no such model"
                    )
                del models[name]
            else:
                models[name] = value

        def edited(
            edits: Mapping[str, str | None], base: Mapping[str, str] | None, noun: str
        ) -> dict[str, str]:
            current = dict(base or {})
            for key, value in edits.items():
                if value is None:
                    if key not in current:
                        raise ValueError(
                            f"cannot remove {noun} {key!r}: the tree holds no such entry"
                        )
                    del current[key]
                else:
                    current[key] = value
            return current

        return ProjectTree(
            models=tuple(models.values()),
            name=tree.name,
            declaration_sources=edited(
                self.declaration_sources, tree.declaration_sources, "declaration source"
            ),
            semantic_sources=edited(
                self.semantic_sources, tree.semantic_sources, "semantic source"
            ),
            source_declarations=edited(
                self.source_declarations, tree.source_declarations, "source declaration"
            ),
        )


@dataclass(frozen=True)
class Attempt:
    """One proposed edit and what became of it.

    Exactly one of ``verdict`` and ``error`` is set: the oracle judged the
    edit, or the sandbox refused to apply it and the error travels verbatim.
    An attempt with a closing verdict is the accepted one; anything else is a
    refusal with its reason attached. Both invariants are checked here, where
    the value is made, because the trace is the evidence a calibration run
    reads and stored state nothing validates is a place a trace can lie.
    """

    edit: TreeEdit
    verdict: Verdict | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if (self.verdict is None) == (self.error is None):
            raise ValueError(
                "an attempt records exactly one outcome: a verdict from the "
                "oracle or the sandbox's refusal to apply"
            )


@dataclass(frozen=True)
class ProposalRequest:
    """Everything a proposer is entitled to see.

    The tree as it stands, the delta the patch must close, and every refused
    attempt so far - each carrying the oracle's disagreement or the sandbox's
    error, which is what lets a proposer correct rather than re-roll. Nothing
    else: a proposer that needed more than this would be reading state the
    oracle does not judge by.
    """

    tree: ProjectTree
    stated: Delta
    refused: tuple[Attempt, ...] = ()


# The model-facing seam: request in, proposed edit out. Hand-written for the
# loop's own tests; claude_proposer builds the model-backed one.
Proposer = Callable[[ProposalRequest], TreeEdit]


@dataclass(frozen=True)
class Generation:
    """One bounded search, with its full trace.

    ``accepted`` is the attempt whose verdict closed, or ``None`` when the
    budget ran out; ``refused`` is every attempt that did not, in order.
    ``closes`` mirrors :attr:`~crosslink.verify.Verdict.closes` because it is
    the same question asked of the search instead of one patch. The trace is
    complete either way: an exhausted search is evidence about the proposer,
    not an error in the loop.
    """

    accepted: Attempt | None
    refused: tuple[Attempt, ...] = ()

    def __post_init__(self) -> None:
        if self.accepted is not None and (
            self.accepted.verdict is None or not self.accepted.verdict.closes
        ):
            raise ValueError(
                "an accepted attempt carries the closing verdict it was accepted on"
            )
        for attempt in self.refused:
            if attempt.verdict is not None and attempt.verdict.closes:
                raise ValueError(
                    "a refused attempt cannot carry a closing verdict"
                )

    @property
    def closes(self) -> bool:
        return self.accepted is not None


def generate(
    tree: ProjectTree, stated: Delta, proposer: Proposer, *, budget: int = 3
) -> Generation:
    """Search for a patch that closes ``stated``, judged by the oracle.

    Each round asks ``proposer`` for an edit - handing it every refusal so
    far - compiles the edit to a patch, and judges it with
    :func:`~crosslink.verify.verify`, unchanged. A closing verdict ends the
    search accepted; an edit the sandbox refuses to apply, or a verdict that
    does not close, joins the refusals and the next round sees it. At most
    ``budget`` proposals are requested.

    Refuses - with :class:`ValueError`, before any proposal is requested - a
    stated delta bound to a different project than the tree reduces to, and a
    budget below one. Both are the caller's errors, and burning model calls
    against either would manufacture a trace about nothing. Anything the
    *proposer itself* raises propagates: a broken channel is not a refused
    attempt, and :func:`claude_proposer` names its own failures.
    """

    if budget < 1:
        raise ValueError(f"a search needs a budget of at least one proposal, not {budget}")
    before = tree.reduce()
    if (stated.format, stated.name) != (before.format, before.name):
        raise ValueError(
            f"stated delta is bound to {stated.format!r}/{stated.name!r} "
            f"but the tree reduces to {before.format!r}/{before.name!r}: "
            f"a search against the wrong subject would be evidence about nothing"
        )
    refused: list[Attempt] = []
    for _ in range(budget):
        edit = proposer(ProposalRequest(tree, stated, tuple(refused)))
        try:
            verdict = verify(tree, stated, edit.apply)
        except ValueError as error:
            refused.append(Attempt(edit, error=str(error)))
            continue
        if verdict.closes:
            return Generation(accepted=Attempt(edit, verdict=verdict), refused=tuple(refused))
        refused.append(Attempt(edit, verdict=verdict))
    return Generation(accepted=None, refused=tuple(refused))


# -- the model-backed proposer ------------------------------------------------
#
# Everything below is one adapter behind the Proposer seam. The prompt
# rendering and the reply parsing are pure functions, tested without a
# network; the client is injectable, so the tests exercise the adapter with a
# duck-typed stand-in the way the whole package treats orchestrators. The SDK
# import is lazy and the dependency an optional extra: nothing model-side is
# installed for the suite, and the core cannot acquire the coupling by
# accident.

_MODEL_VALUE_SCHEMA = {
    "anyOf": [
        {"type": "null"},
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "depends_on": {"type": "array", "items": {"type": "string"}},
                "relation": {"type": ["string", "null"]},
                "layer": {"type": ["string", "null"]},
            },
            "required": ["name", "depends_on", "relation", "layer"],
            "additionalProperties": False,
        },
    ]
}

# Entries are arrays of {key, value} pairs rather than JSON objects because
# the schema can then state the value shape exactly with additionalProperties
# refused everywhere; the duplicate-key doctrine is enforced in
# _edit_from_json, where a violation can be named rather than silently
# last-write-wins as a JSON object would have it.
_TEXT_ENTRIES_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {"type": ["string", "null"]},
        },
        "required": ["key", "value"],
        "additionalProperties": False,
    },
}

_EDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "models": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"key": {"type": "string"}, "value": _MODEL_VALUE_SCHEMA},
                "required": ["key", "value"],
                "additionalProperties": False,
            },
        },
        "declaration_sources": _TEXT_ENTRIES_SCHEMA,
        "semantic_sources": _TEXT_ENTRIES_SCHEMA,
        "source_declarations": _TEXT_ENTRIES_SCHEMA,
    },
    "required": [
        "models",
        "declaration_sources",
        "semantic_sources",
        "source_declarations",
    ],
    "additionalProperties": False,
}

_SYSTEM = (
    "You propose minimal edits to a data-pipeline project's declaration "
    "tree. The intended effect is stated in advance as a typed delta over "
    "the project's declarations, and your edit is accepted only if applying "
    "it and re-reducing the tree produces exactly that delta - no more, no "
    "less. An edit that does more than the delta states will be refused even "
    "if the extra work looks like an improvement. Edit only what the delta "
    "requires; in a text entry, change the statement at issue and preserve "
    "every other line verbatim."
)


def _entries(pairs, noun: str) -> dict:
    entries: dict = {}
    for pair in pairs:
        key, value = pair["key"], pair["value"]
        if key in entries and entries[key] != value:
            raise ValueError(
                f"proposal states {noun} {key!r} more than once, with different values"
            )
        entries[key] = value
    return entries


def _edit_from_json(data: Mapping[str, object]) -> TreeEdit:
    """A :class:`TreeEdit` from one schema-shaped reply.

    Holds the house duplicate doctrine the schema cannot: an identical
    restatement collapses to one statement, the same key with different
    values refuses. Model values pass through
    :class:`~crosslink.model.ProjectModel`, whose own validation applies -
    a proposal does not get a laxer constructor than a producer.
    """

    models = {
        key: (
            None
            if value is None
            else ProjectModel(
                name=value["name"],
                depends_on=tuple(value["depends_on"]),
                relation=value["relation"],
                layer=value["layer"],
            )
        )
        for key, value in _entries(data["models"], "model entry").items()
    }
    return TreeEdit(
        models=models,
        declaration_sources=_entries(data["declaration_sources"], "declaration source"),
        semantic_sources=_entries(data["semantic_sources"], "semantic source"),
        source_declarations=_entries(data["source_declarations"], "source declaration"),
    )


def _render_mapping(name: str, entries: Mapping[str, str] | None) -> str:
    if not entries:
        return f"{name}: (none)\n"
    rendered = f"{name}:\n"
    for key in sorted(entries):
        rendered += f"- {key!r}:\n{indent(entries[key], '    ')}\n"
    return rendered


def render_request(request: ProposalRequest) -> str:
    """The proposer's one input, rendered - pure, so the tests can hold it.

    Everything the request carries and nothing else: the tree entry by entry
    (declaration text verbatim, because the edit must reproduce what it does
    not change), the stated delta, and each refused attempt with the oracle's
    stated-versus-observed disagreement or the sandbox's error. The reprs are
    the package's own dataclass reprs: the delta vocabulary is the interface,
    already designed to be read.
    """

    rendered = "## The project tree\n\n"
    rendered += f"name: {request.tree.name!r}\n"
    rendered += "models:\n" + (
        "".join(f"- {model!r}\n" for model in request.tree.models) or "(none)\n"
    )
    rendered += _render_mapping("declaration_sources", request.tree.declaration_sources)
    rendered += _render_mapping("semantic_sources", request.tree.semantic_sources)
    rendered += _render_mapping("source_declarations", request.tree.source_declarations)
    rendered += (
        "\n## The stated delta your edit must close, exactly\n\n"
        f"{request.stated!r}\n"
    )
    for number, attempt in enumerate(request.refused, start=1):
        rendered += f"\n## Refused attempt {number}\n\n{attempt.edit!r}\n\n"
        if attempt.error is not None:
            rendered += f"The sandbox refused to apply it: {attempt.error}\n"
        else:
            verdict = attempt.verdict
            assert verdict is not None  # Attempt's constructor holds this
            rendered += "The oracle refused it. Where the deltas disagree:\n"
            for noun in verdict.disagreements:
                rendered += (
                    f"- {noun}: stated {getattr(verdict.stated, noun)!r}, "
                    f"observed {getattr(verdict.observed, noun)!r}\n"
                )
    rendered += (
        "\n## Your task\n\n"
        "Propose the minimal tree edit whose re-reduction closes the stated "
        "delta exactly. Reply with the edit alone, in the required JSON "
        "shape: for each of models, declaration_sources, semantic_sources "
        "and source_declarations, a list of {key, value} entries - value is "
        "the entry's full new content, or null to remove it. Entries you do "
        "not name are untouched; a text value replaces the whole entry, so "
        "carry unchanged lines through verbatim.\n"
    )
    return rendered


def claude_proposer(
    client: Any | None = None,
    *,
    model: str = "claude-opus-5",
    max_tokens: int = 16000,
) -> Proposer:
    """A :data:`Proposer` backed by a Claude model.

    ``client`` is anything shaped like an Anthropic SDK client - injectable
    so the adapter is testable with a stand-in, exactly as the reduction
    treats orchestrators. When omitted, the SDK is imported here and only
    here (the ``generate`` optional extra), and the constructed client
    resolves credentials from the operator's environment: this adapter
    borrows the ambient identity per call and holds nothing, the delivery
    adapter's discipline at the other end of the loop.

    The returned proposer raises :class:`GenerationError` when the channel
    fails - a response that stops for a refusal or for the token ceiling has
    produced no proposal, and pretending otherwise would feed the search loop
    an attempt nobody made.
    """

    if client is None:
        import anthropic  # the optional extra, paid for only on this path

        client = anthropic.Anthropic()

    def propose(request: ProposalRequest) -> TreeEdit:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _EDIT_SCHEMA}},
            messages=[{"role": "user", "content": render_request(request)}],
        )
        if response.stop_reason != "end_turn":
            raise GenerationError(
                f"the model stopped for {response.stop_reason!r} and produced "
                f"no proposal"
            )
        text = next(block.text for block in response.content if block.type == "text")
        return _edit_from_json(json.loads(text))

    return propose

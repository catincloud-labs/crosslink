# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The search loop calibrated: proposals judged, refusals fed back, the
trace complete either way.

Every proposer in this file is hand-written - a scripted stand-in behind the
same seam the model adapter implements - because the loop's correctness must
be provable with no model anywhere near it. The adapter itself is exercised
against a duck-typed client stand-in, the way the whole package treats
orchestrators: the coupling is to a shape, not to a distribution.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from crosslink import (
    DANGLING_DECLARED_KEY,
    Delta,
    PatchObject,
    ProjectModel,
    ProjectTree,
    findings,
    verify,
)
from crosslink.conformance import a_single_key_declaration
from crosslink.generate import (
    Attempt,
    Generation,
    GenerationError,
    ProposalRequest,
    TreeEdit,
    _edit_from_json,
    claude_proposer,
    generate,
    render_request,
)


def a_tree() -> ProjectTree:
    """Two models the graph builds, and a key declared for one it does not.

    The dangling declaration is the tree's one self-contradiction: the
    findings layer proposes its removal, which makes this the natural
    end-to-end subject - the stated delta comes from the product's own
    reading of the tree, not from a test's imagination.
    """

    return ProjectTree(
        models=(
            ProjectModel(name="dim_date", layer="silver"),
            ProjectModel(name="fact_orders", depends_on=("dim_date",), layer="gold"),
        ),
        name="generator",
        declaration_sources={
            "schema_dim_date": a_single_key_declaration(),
            "schema_ghost": a_single_key_declaration(model="dim_ghost", column="ghost_id"),
        },
    )


def the_stated_delta(tree: ProjectTree) -> Delta:
    """The dangling-key finding's own proposal, used unchanged."""

    found = [
        f for f in findings(tree.reduce()) if f.kind == DANGLING_DECLARED_KEY
    ]
    assert len(found) == 1 and found[0].proposal is not None
    return found[0].proposal


# The edit that closes it: the dangling declaration entry holds exactly the
# one stale statement, so removing the entry removes the key and nothing else.
THE_CLOSING_EDIT = TreeEdit(declaration_sources={"schema_ghost": None})


class TestTreeEdit:
    """The proposal's data shape, and where it refuses."""

    def test_apply_sets_replaces_and_removes_text_entries(self):
        tree = a_tree()
        edit = TreeEdit(
            declaration_sources={
                "schema_ghost": None,
                "schema_new": a_single_key_declaration(model="dim_date", column="id"),
            }
        )
        patched = edit.apply(tree)
        assert "schema_ghost" not in patched.declaration_sources
        assert "schema_new" in patched.declaration_sources
        assert patched.declaration_sources["schema_dim_date"] == a_single_key_declaration()

    def test_apply_sets_and_removes_models(self):
        tree = a_tree()
        edit = TreeEdit(
            models={
                "dim_date": None,
                "dim_region": ProjectModel(name="dim_region", layer="silver"),
            }
        )
        patched = edit.apply(tree)
        names = {m.name for m in patched.models}
        assert names == {"fact_orders", "dim_region"}

    def test_apply_replaces_a_model_in_place(self):
        tree = a_tree()
        moved = ProjectModel(name="dim_date", layer="gold")
        patched = TreeEdit(models={"dim_date": moved}).apply(tree)
        assert moved in patched.models

    def test_apply_leaves_the_input_tree_untouched(self):
        tree = a_tree()
        THE_CLOSING_EDIT.apply(tree)
        assert "schema_ghost" in tree.declaration_sources

    def test_removing_an_absent_model_refuses(self):
        with pytest.raises(ValueError, match="no such model"):
            TreeEdit(models={"dim_ghost": None}).apply(a_tree())

    def test_removing_an_absent_text_entry_refuses(self):
        with pytest.raises(ValueError, match="no such entry"):
            TreeEdit(semantic_sources={"nowhere": None}).apply(a_tree())

    def test_a_models_entry_that_changes_identity_refuses_at_construction(self):
        with pytest.raises(ValueError, match="keeps its identity"):
            TreeEdit(models={"dim_date": ProjectModel(name="dim_renamed")})

    def test_is_empty(self):
        assert TreeEdit().is_empty
        assert not THE_CLOSING_EDIT.is_empty


class TestTheSearchLoop:
    """generate(): the oracle unchanged, the refusals fed back, the budget held."""

    def test_a_first_attempt_that_closes_is_accepted_with_an_empty_trace(self):
        tree = a_tree()
        result = generate(tree, the_stated_delta(tree), lambda request: THE_CLOSING_EDIT)
        assert result.closes
        assert result.refused == ()
        assert result.accepted is not None and result.accepted.verdict is not None
        assert result.accepted.verdict.closes
        assert result.accepted.edit == THE_CLOSING_EDIT

    def test_an_oracle_refusal_reaches_the_next_attempt_as_evidence(self):
        """The property that makes this search rather than re-rolling: the
        second request carries the first refusal, disagreements and all."""

        tree = a_tree()
        seen: list[ProposalRequest] = []

        def proposer(request: ProposalRequest) -> TreeEdit:
            seen.append(request)
            return TreeEdit() if len(seen) == 1 else THE_CLOSING_EDIT

        result = generate(tree, the_stated_delta(tree), proposer)
        assert result.closes
        assert len(result.refused) == 1
        refusal = result.refused[0]
        assert refusal.verdict is not None and not refusal.verdict.closes
        assert refusal.verdict.disagreements == ("declared_keys",)
        assert seen[1].refused == (refusal,)

    def test_a_sandbox_crash_is_recorded_verbatim_never_dressed_as_a_verdict(self):
        tree = a_tree()
        attempts = iter(
            (TreeEdit(models={"dim_ghost": None}), THE_CLOSING_EDIT)
        )

        result = generate(tree, the_stated_delta(tree), lambda request: next(attempts))
        assert result.closes
        assert len(result.refused) == 1
        assert result.refused[0].verdict is None
        assert "no such model" in (result.refused[0].error or "")

    def test_an_exhausted_budget_returns_the_full_trace_unaccepted(self):
        tree = a_tree()
        result = generate(tree, the_stated_delta(tree), lambda request: TreeEdit(), budget=2)
        assert not result.closes
        assert result.accepted is None
        assert len(result.refused) == 2

    def test_a_mismatched_stated_delta_refuses_before_any_proposal(self):
        tree = a_tree()
        stated = replace(the_stated_delta(tree), name="someone_else")

        def never_called(request: ProposalRequest) -> TreeEdit:
            raise AssertionError("a proposal was requested against the wrong subject")

        with pytest.raises(ValueError, match="wrong subject"):
            generate(tree, stated, never_called)

    def test_a_budget_below_one_refuses(self):
        tree = a_tree()
        with pytest.raises(ValueError, match="budget"):
            generate(tree, the_stated_delta(tree), lambda request: TreeEdit(), budget=0)

    def test_what_the_proposer_itself_raises_propagates(self):
        """A broken channel is not a refused attempt."""

        tree = a_tree()

        def broken(request: ProposalRequest) -> TreeEdit:
            raise GenerationError("the model stopped for 'refusal' and produced no proposal")

        with pytest.raises(GenerationError):
            generate(tree, the_stated_delta(tree), broken)


class TestTraceValidation:
    """The trace is evidence, so its invariants hold where values are made."""

    def test_an_attempt_records_exactly_one_outcome(self):
        with pytest.raises(ValueError, match="exactly one outcome"):
            Attempt(TreeEdit())
        tree = a_tree()
        verdict = verify(tree, the_stated_delta(tree), THE_CLOSING_EDIT.apply)
        with pytest.raises(ValueError, match="exactly one outcome"):
            Attempt(TreeEdit(), verdict=verdict, error="also this")

    def test_an_accepted_attempt_must_carry_a_closing_verdict(self):
        tree = a_tree()
        refusing = verify(tree, the_stated_delta(tree), lambda t: t)
        with pytest.raises(ValueError, match="closing verdict"):
            Generation(accepted=Attempt(TreeEdit(), verdict=refusing))
        with pytest.raises(ValueError, match="closing verdict"):
            Generation(accepted=Attempt(TreeEdit(), error="crashed"))

    def test_a_refused_attempt_cannot_carry_a_closing_verdict(self):
        tree = a_tree()
        closing = verify(tree, the_stated_delta(tree), THE_CLOSING_EDIT.apply)
        with pytest.raises(ValueError, match="cannot carry a closing verdict"):
            Generation(accepted=None, refused=(Attempt(TreeEdit(), verdict=closing),))


class TestTheLoopClosed:
    """Step 5's arrival: the whole single-node loop, one test.

    The product's own reading finds the contradiction and states the delta;
    the search produces an accepted verdict; the patch object that delivery
    carries is constructable from it unchanged. No stage learned anything
    about the one before it."""

    def test_finding_to_search_to_patch_object(self):
        tree = a_tree()
        stated = the_stated_delta(tree)
        result = generate(tree, stated, lambda request: THE_CLOSING_EDIT)
        assert result.closes and result.accepted is not None

        proposal = PatchObject(
            title="chore(declarations): remove the key declared for a model nothing builds",
            rationale="The declaration entry states a grain for a model the graph does not build.",
            edits={"schema/ghost.yml": None},
            verdict=result.accepted.verdict,
        )
        assert proposal.verdict.closes
        assert proposal.verdict.stated == stated


class FakeBlock:
    def __init__(self, type: str, text: str = "") -> None:
        self.type = type
        self.text = text


class FakeResponse:
    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.stop_reason = stop_reason
        # A thinking block rides first on purpose: the adapter must find the
        # text block by type, not by position.
        self.content = [FakeBlock("thinking"), FakeBlock("text", text)]


class FakeMessages:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.requests: list[dict] = []

    def create(self, **kwargs) -> FakeResponse:
        self.requests.append(kwargs)
        return self.responses.pop(0)


class FakeClient:
    """Anything shaped like an SDK client, which is the adapter's contract."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self.messages = FakeMessages(responses)


THE_CLOSING_REPLY = json.dumps(
    {
        "models": [],
        "declaration_sources": [{"key": "schema_ghost", "value": None}],
        "semantic_sources": [],
        "source_declarations": [],
    }
)


class TestClaudeProposer:
    """The adapter behind the seam, exercised against a client stand-in."""

    def test_a_schema_shaped_reply_becomes_the_tree_edit(self):
        tree = a_tree()
        client = FakeClient([FakeResponse(THE_CLOSING_REPLY)])
        proposer = claude_proposer(client)

        edit = proposer(ProposalRequest(tree, the_stated_delta(tree)))
        assert edit == THE_CLOSING_EDIT

    def test_the_whole_loop_runs_over_the_adapter(self):
        tree = a_tree()
        client = FakeClient([FakeResponse(THE_CLOSING_REPLY)])

        result = generate(tree, the_stated_delta(tree), claude_proposer(client))
        assert result.closes

    def test_the_request_shape_the_adapter_sends(self):
        tree = a_tree()
        client = FakeClient([FakeResponse(THE_CLOSING_REPLY)])
        claude_proposer(client)(ProposalRequest(tree, the_stated_delta(tree)))

        (request,) = client.messages.requests
        assert request["model"] == "claude-opus-5"
        assert request["output_config"]["format"]["type"] == "json_schema"
        assert request["messages"][0]["role"] == "user"
        assert "schema_ghost" in request["messages"][0]["content"]

    def test_a_refusal_stop_is_a_channel_failure_not_a_proposal(self):
        tree = a_tree()
        client = FakeClient([FakeResponse("", stop_reason="refusal")])
        with pytest.raises(GenerationError, match="refusal"):
            claude_proposer(client)(ProposalRequest(tree, the_stated_delta(tree)))

    def test_a_truncated_reply_is_a_channel_failure_not_a_proposal(self):
        tree = a_tree()
        client = FakeClient([FakeResponse("{", stop_reason="max_tokens")])
        with pytest.raises(GenerationError, match="max_tokens"):
            claude_proposer(client)(ProposalRequest(tree, the_stated_delta(tree)))

    def test_a_reply_stating_one_key_twice_with_different_values_refuses(self):
        payload = {
            "models": [],
            "declaration_sources": [
                {"key": "schema_ghost", "value": None},
                {"key": "schema_ghost", "value": "models: []\n"},
            ],
            "semantic_sources": [],
            "source_declarations": [],
        }
        with pytest.raises(ValueError, match="more than once"):
            _edit_from_json(payload)

    def test_an_identical_restatement_collapses_to_one_statement(self):
        payload = {
            "models": [],
            "declaration_sources": [
                {"key": "schema_ghost", "value": None},
                {"key": "schema_ghost", "value": None},
            ],
            "semantic_sources": [],
            "source_declarations": [],
        }
        assert _edit_from_json(payload) == THE_CLOSING_EDIT

    def test_a_model_value_passes_through_the_models_own_validation(self):
        payload = {
            "models": [
                {
                    "key": "",
                    "value": {"name": "", "depends_on": [], "relation": None, "layer": None},
                }
            ],
            "declaration_sources": [],
            "semantic_sources": [],
            "source_declarations": [],
        }
        with pytest.raises(ValueError, match="needs a name"):
            _edit_from_json(payload)


class TestRenderRequest:
    """The prompt is pure over the request, and carries all of it."""

    def test_the_tree_the_delta_and_nothing_invented(self):
        tree = a_tree()
        stated = the_stated_delta(tree)
        rendered = render_request(ProposalRequest(tree, stated))
        assert "'dim_date'" in rendered
        assert "schema_ghost" in rendered
        assert "not_null" in rendered  # declaration text travels verbatim
        assert repr(stated) in rendered
        assert "Refused attempt" not in rendered

    def test_an_oracle_refusal_renders_its_disagreement(self):
        tree = a_tree()
        stated = the_stated_delta(tree)
        refused = Attempt(TreeEdit(), verdict=verify(tree, stated, lambda t: t))
        rendered = render_request(ProposalRequest(tree, stated, (refused,)))
        assert "Refused attempt 1" in rendered
        assert "declared_keys" in rendered
        assert "stated" in rendered and "observed" in rendered

    def test_a_sandbox_error_renders_verbatim(self):
        tree = a_tree()
        stated = the_stated_delta(tree)
        refused = Attempt(TreeEdit(), error="cannot remove model 'dim_ghost'")
        rendered = render_request(ProposalRequest(tree, stated, (refused,)))
        assert "cannot remove model 'dim_ghost'" in rendered

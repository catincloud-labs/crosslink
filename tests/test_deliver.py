# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The delivery adapter, observed against a local bare remote.

No network, no forge, no credential anywhere in this file - which is not a
mocking convenience but the property under test: the adapter's whole git
half runs against a clonable path, and the forge half is a callable these
tests supply and record. The refusal arms matter as much as the happy path;
an adapter only ever observed delivering has not been shown to refuse.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from crosslink import (
    Delta,
    DeliveryError,
    PatchObject,
    PullRequestSpec,
    deliver_pull_request,
    emit_files,
    render_body,
    verify,
)
from crosslink.conformance import a_composite_key_declaration

from test_verify import A_STATED_DELTA, THE_CLAIMED_KEY, a_closing_patch, a_tree

# The declaration text the sandbox patch adds is also the file the delivery
# writes: one authored change, expressed in the sandbox and on disk.
THE_DECLARATION_TEXT = a_composite_key_declaration(
    model="fact_orders", columns=("date", "provider")
)


def a_verdict():
    return verify(a_tree(), A_STATED_DELTA, a_closing_patch)


def a_refusing_verdict():
    return verify(a_tree(), A_STATED_DELTA, lambda tree: tree)


def a_patch_object(**overrides) -> PatchObject:
    given = dict(
        title="declare the combination grain of fact_orders",
        rationale=(
            "The fact table's grain is (date, provider) and nothing "
            "declared it; the sandbox run below shows the declaration "
            "landing and nothing else moving."
        ),
        edits={
            "models/schema_fact.yml": THE_DECLARATION_TEXT,
            "models/stale.sql": None,
        },
        verdict=a_verdict(),
    )
    given.update(overrides)
    return PatchObject(**given)


def run_git(*args: str, cwd: Path) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture(autouse=True)
def a_hermetic_git(monkeypatch):
    """Git with an identity and without the machine's own configuration.

    The identity comes from the environment rather than any config file, and
    the system/global configs are shut out so a developer's ``autocrlf`` or
    template settings cannot leak into what these tests observe.
    """

    monkeypatch.setenv("GIT_AUTHOR_NAME", "A Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "A Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def a_target_repository(tmp_path: Path) -> Path:
    """A bare remote holding one commit: two model files, one to be deleted."""

    seed = tmp_path / "seed"
    run_git("init", "-b", "main", str(seed), cwd=tmp_path)
    (seed / "models").mkdir()
    (seed / "models" / "kept.sql").write_text(
        "select 1\n", encoding="utf-8", newline=""
    )
    (seed / "models" / "stale.sql").write_text(
        "select 2\n", encoding="utf-8", newline=""
    )
    run_git("add", "-A", cwd=seed)
    run_git("commit", "-m", "seed", cwd=seed)
    bare = tmp_path / "origin.git"
    run_git("clone", "--bare", str(seed), str(bare), cwd=tmp_path)
    return bare


class RecordingOpener:
    """The thinnest forge: records the spec, returns an address."""

    def __init__(self) -> None:
        self.specs: list[PullRequestSpec] = []

    def __call__(self, spec: PullRequestSpec) -> str:
        self.specs.append(spec)
        return f"pull-request-{len(self.specs)}"


class TestThePatchObject:
    """Construction is where a proposal is kept from lying."""

    def test_a_refusing_verdict_cannot_be_packaged(self):
        with pytest.raises(ValueError, match="declared_keys"):
            a_patch_object(verdict=a_refusing_verdict())

    def test_no_edits_proposes_nothing(self):
        with pytest.raises(ValueError, match="proposes nothing"):
            a_patch_object(edits={})

    @pytest.mark.parametrize("title", ["", "   ", "two\nlines"])
    def test_a_title_is_one_non_empty_line(self, title):
        with pytest.raises(ValueError, match="one non-empty line"):
            a_patch_object(title=title)

    def test_a_blank_rationale_is_refused(self):
        with pytest.raises(ValueError, match="without a rationale"):
            a_patch_object(rationale=" \n ")

    @pytest.mark.parametrize(
        "text",
        [
            "The grain is (date, provider); this closes #17 for the table.",
            "Fixes: #4 by declaring the key.",
            "resolves owner/repo#9",
            "closes#3",
        ],
    )
    def test_a_closing_keyword_adjacency_in_the_rationale_is_refused(self, text):
        # It would close an issue in the TARGET repo from prose on merge.
        with pytest.raises(ValueError, match="closing keyword"):
            a_patch_object(rationale=text)

    def test_a_closing_keyword_adjacency_in_the_title_is_refused(self):
        with pytest.raises(ValueError, match="closing keyword"):
            a_patch_object(title="declare the grain, closes #17")

    @pytest.mark.parametrize(
        "text",
        [
            "Part of #17; declares the grain.",
            "This fixes the date column and refs #17.",
            "Disclosed #17 as related context.",
        ],
    )
    def test_a_non_adjacent_or_safe_reference_is_allowed(self, text):
        # "part of"/"refs" are safe, and a keyword not adjacent to the number
        # (or embedded in another word) must not trip the guard.
        assert a_patch_object(rationale=text).rationale == text

    @pytest.mark.parametrize(
        "path",
        [
            "/etc/passwd",
            "C:/anywhere.sql",
            "models/../escape.sql",
            "..",
            ".git/hooks/pre-commit",
            "nested/.GIT/config",
            ".git./hooks/pre-commit",
            ".git /hooks/pre-commit",
            "models/.git.../x",
            "",
            "models//double.sql",
            "./models/dot.sql",
            "models/trailing/",
        ],
    )
    def test_an_escaping_path_is_refused(self, path):
        with pytest.raises(ValueError, match="refused|not a relative path"):
            a_patch_object(edits={path: "text"})

    def test_backslashes_normalize_to_the_forward_slash_tree(self):
        patch = a_patch_object(edits={"models\\schema_fact.yml": "text"})
        assert patch.edits == {"models/schema_fact.yml": "text"}

    def test_the_same_path_twice_collapses_or_refuses(self):
        # The house duplicate doctrine: an identical restatement is one
        # statement; a conflicting one has no honest reading.
        patch = a_patch_object(
            edits={"models\\schema_fact.yml": "text", "models/schema_fact.yml": "text"}
        )
        assert list(patch.edits) == ["models/schema_fact.yml"]
        with pytest.raises(ValueError, match="stated twice"):
            a_patch_object(
                edits={
                    "models\\schema_fact.yml": "one",
                    "models/schema_fact.yml": "two",
                }
            )


class TestTheRenderedBody:
    """One rendering, carrying the evidence verbatim."""

    def test_the_body_carries_the_stated_delta_verbatim(self):
        body = render_body(a_patch_object())
        assert repr(THE_CLAIMED_KEY) in body
        assert "The observed delta equals the stated one." in body

    def test_the_body_shows_both_reductions(self):
        body = render_body(a_patch_object())
        # a_tree declares one key before the patch and two after it.
        assert "1 declared key," in body
        assert "2 declared keys," in body

    def test_the_rationale_arrives_in_the_body(self):
        patch = a_patch_object()
        assert patch.rationale in render_body(patch)

    def test_a_declaration_invisible_change_renders_as_exactly_that(self):
        empty = Delta(format="dagster", name="generator")
        patch = a_patch_object(
            verdict=verify(a_tree(), empty, lambda tree: tree),
            edits={"models/kept.sql": "select 1 -- clarified\n"},
        )
        assert "nothing changes in declaration space" in render_body(patch)

    def test_the_rendered_surface_carries_no_package_name(self):
        # The body travels to target repositories and their forums; this
        # package's name stays out of every rendered surface, so the
        # evidence - not a product identifier - is the signature.
        patch = a_patch_object()
        assert "crosslink" not in render_body(patch).casefold()
        assert "crosslink" not in _all_emitted_text(patch).casefold()


def _all_emitted_text(patch: PatchObject) -> str:
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        written = emit_files(patch, Path(scratch) / "out")
        return "\n".join(
            path.read_text(encoding="utf-8") for path in written
        )


class TestDeliveryToARemote:
    """The flagship arm: branch, diff, and evidence against a bare remote."""

    def test_the_branch_arrives_with_the_diff_and_the_evidence(self, tmp_path):
        origin = a_target_repository(tmp_path)
        opener = RecordingOpener()
        patch = a_patch_object()

        receipt = deliver_pull_request(patch, origin, opener)

        assert receipt.base == "main"
        assert receipt.branch.startswith("proposal/")
        assert receipt.pull_request == "pull-request-1"
        # The branch exists on the remote and holds exactly the edits.
        assert receipt.branch in run_git("branch", cwd=origin)
        shown = run_git(
            "show", f"{receipt.branch}:models/schema_fact.yml", cwd=origin
        )
        assert shown == THE_DECLARATION_TEXT.strip()
        listed = run_git("ls-tree", "-r", "--name-only", receipt.branch, cwd=origin)
        assert "models/stale.sql" not in listed
        assert "models/kept.sql" in listed
        # The commit is the receipt's, subject is the title, body the rationale.
        assert run_git("rev-parse", receipt.branch, cwd=origin) == receipt.commit
        assert run_git("log", "-1", "--format=%s", receipt.branch, cwd=origin) == (
            patch.title
        )
        assert patch.rationale in run_git(
            "log", "-1", "--format=%b", receipt.branch, cwd=origin
        )
        # The opener saw the same body render_body produces, and the base.
        (spec,) = opener.specs
        assert spec.body == render_body(patch)
        assert spec.title == patch.title
        assert spec.base == "main"
        assert spec.branch == receipt.branch
        assert spec.repository == str(origin)

    def test_a_branch_that_exists_is_never_overwritten(self, tmp_path):
        origin = a_target_repository(tmp_path)
        deliver_pull_request(a_patch_object(), origin, RecordingOpener())
        second = RecordingOpener()
        with pytest.raises(ValueError, match="never overwrites"):
            deliver_pull_request(a_patch_object(), origin, second)
        assert second.specs == []

    def test_a_colliding_slug_refusal_names_the_collision_not_a_retry(self, tmp_path):
        """Two distinct titles that derive to one branch name: the refusal
        must offer the collision reading and the branch= remedy, not diagnose
        the second proposal as a duplicate retry."""

        origin = a_target_repository(tmp_path)
        deliver_pull_request(
            a_patch_object(title="Declare grain (v2)"), origin, RecordingOpener()
        )
        distinct = a_patch_object(title="Declare grain [v2]")
        with pytest.raises(ValueError, match="derives to the same name"):
            deliver_pull_request(distinct, origin, RecordingOpener())
        # The remedy the message names must actually work.
        receipt = deliver_pull_request(
            distinct, origin, RecordingOpener(), branch="proposal/declare-grain-v2-bracketed"
        )
        assert receipt.branch == "proposal/declare-grain-v2-bracketed"

    def test_an_explicit_branch_collision_keeps_the_plain_refusal(self, tmp_path):
        """A caller-named branch that exists is refused without the derived-name
        diagnosis: the caller chose the name, so no derivation is in play."""

        origin = a_target_repository(tmp_path)
        deliver_pull_request(
            a_patch_object(), origin, RecordingOpener(), branch="proposal/named"
        )
        with pytest.raises(ValueError, match="never overwrites") as caught:
            deliver_pull_request(
                a_patch_object(), origin, RecordingOpener(), branch="proposal/named"
            )
        assert "derives" not in str(caught.value)

    def test_edits_already_true_in_the_target_deliver_nothing(self, tmp_path):
        origin = a_target_repository(tmp_path)
        patch = a_patch_object(edits={"models/kept.sql": "select 1\n"})
        with pytest.raises(ValueError, match="nothing to deliver"):
            deliver_pull_request(patch, origin, RecordingOpener())

    def test_deleting_what_the_target_does_not_hold_is_refused(self, tmp_path):
        origin = a_target_repository(tmp_path)
        patch = a_patch_object(edits={"models/ghost.sql": None})
        with pytest.raises(ValueError, match="does not hold"):
            deliver_pull_request(patch, origin, RecordingOpener())

    def test_a_target_with_no_commits_is_refused(self, tmp_path):
        empty = tmp_path / "empty.git"
        run_git("init", "--bare", str(empty), cwd=tmp_path)
        with pytest.raises(DeliveryError, match="no commits"):
            deliver_pull_request(a_patch_object(), empty, RecordingOpener())

    def test_an_unresolved_target_head_is_not_diagnosed_as_no_commits(self, tmp_path):
        """A mirror whose default was renamed without updating HEAD clones
        with a warning while its branches still carry commits; calling that
        "no commits" is false, and the honest diagnosis names the remedy."""

        origin = a_target_repository(tmp_path)
        run_git("symbolic-ref", "HEAD", "refs/heads/gone", cwd=origin)
        with pytest.raises(DeliveryError, match="does not resolve") as caught:
            deliver_pull_request(a_patch_object(), origin, RecordingOpener())
        assert "no commits" not in str(caught.value)
        assert "main" in str(caught.value)  # the diagnosis names what exists

    def test_the_operator_names_the_base(self, tmp_path):
        """base= recovers the unresolved-HEAD target: the delivery lands on a
        branch cut from the named base, and the spec proposes against it."""

        origin = a_target_repository(tmp_path)
        run_git("symbolic-ref", "HEAD", "refs/heads/gone", cwd=origin)
        opener = RecordingOpener()
        receipt = deliver_pull_request(
            a_patch_object(), origin, opener, base="main"
        )
        assert receipt.base == "main"
        (spec,) = opener.specs
        assert spec.base == "main"

    def test_a_base_the_target_does_not_hold_is_refused(self, tmp_path):
        origin = a_target_repository(tmp_path)
        with pytest.raises(ValueError, match="does not exist on the target"):
            deliver_pull_request(
                a_patch_object(), origin, RecordingOpener(), base="trunk"
            )

    @pytest.mark.parametrize("base", ["--force", "a..b"])
    def test_a_malformed_base_is_refused_as_input(self, base, tmp_path):
        origin = a_target_repository(tmp_path)
        with pytest.raises(ValueError, match="refused"):
            deliver_pull_request(
                a_patch_object(), origin, RecordingOpener(), base=base
            )

    def test_the_operator_names_the_branch(self, tmp_path):
        origin = a_target_repository(tmp_path)
        receipt = deliver_pull_request(
            a_patch_object(), origin, RecordingOpener(), branch="proposal/named"
        )
        assert receipt.branch == "proposal/named"
        with pytest.raises(ValueError, match="reads as an option"):
            deliver_pull_request(
                a_patch_object(), origin, RecordingOpener(), branch="--force"
            )

    @pytest.mark.parametrize("bad", ["a..b", "foo bar", "has~tilde", ""])
    def test_an_invalid_branch_name_is_a_value_error(self, tmp_path, bad):
        # Caller input this module refuses (ValueError), not a git environment
        # failure (DeliveryError) leaking out of `switch`.
        origin = a_target_repository(tmp_path)
        with pytest.raises(ValueError, match="well-formed"):
            deliver_pull_request(
                a_patch_object(), origin, RecordingOpener(), branch=bad
            )

    def test_an_edit_to_a_gitignored_path_is_still_delivered(self, tmp_path):
        # The author naming the path is the deliberate override; `-f` staging
        # keeps deliver and emit_files agreeing on what is deliverable.
        seed = tmp_path / "seed"
        run_git("init", "-b", "main", str(seed), cwd=tmp_path)
        (seed / ".gitignore").write_text(
            "generated/\n", encoding="utf-8", newline=""
        )
        (seed / "models").mkdir()
        (seed / "models" / "kept.sql").write_text(
            "select 1\n", encoding="utf-8", newline=""
        )
        run_git("add", "-A", cwd=seed)
        run_git("commit", "-m", "seed", cwd=seed)
        bare = tmp_path / "origin.git"
        run_git("clone", "--bare", str(seed), str(bare), cwd=tmp_path)

        patch = a_patch_object(edits={"generated/derived.sql": "select 42\n"})
        receipt = deliver_pull_request(patch, bare, RecordingOpener())
        shown = run_git(
            "show", f"{receipt.branch}:generated/derived.sql", cwd=bare
        )
        assert shown == "select 42"

    def test_a_hostile_git_dir_env_does_not_escape_the_clone(
        self, tmp_path, monkeypatch
    ):
        # An inherited GIT_DIR would make deliver commit into this repo instead
        # of the ephemeral clone. Scrubbed, the delivery lands on the target
        # and the operator's own repository is untouched.
        origin = a_target_repository(tmp_path)
        operator = tmp_path / "operator"
        run_git("init", "-b", "main", str(operator), cwd=tmp_path)
        (operator / "keep.txt").write_text("mine\n", encoding="utf-8", newline="")
        run_git("add", "-A", cwd=operator)
        run_git("commit", "-m", "operator seed", cwd=operator)
        before_head = run_git("rev-parse", "HEAD", cwd=operator)
        before_count = run_git("rev-list", "--count", "HEAD", cwd=operator)

        monkeypatch.setenv("GIT_DIR", str(operator / ".git"))
        receipt = deliver_pull_request(a_patch_object(), origin, RecordingOpener())
        monkeypatch.delenv("GIT_DIR", raising=False)

        assert receipt.branch in run_git("branch", cwd=origin)
        assert run_git("rev-parse", "HEAD", cwd=operator) == before_head
        assert run_git("rev-list", "--count", "HEAD", cwd=operator) == before_count
        assert run_git("status", "--porcelain", cwd=operator) == ""

    def test_bytes_arrive_exactly(self, tmp_path):
        # A deliberate CRLF in the patch text must land byte-for-byte: the
        # ephemeral clone turns autocrlf off, so no platform rewrites what
        # the author stated. Read back in binary; text mode would translate.
        origin = a_target_repository(tmp_path)
        patch = a_patch_object(edits={"models/schema_fact.yml": "a\r\nb\n"})
        receipt = deliver_pull_request(patch, origin, RecordingOpener())
        shown = subprocess.run(
            ["git", "show", f"{receipt.branch}:models/schema_fact.yml"],
            cwd=origin,
            capture_output=True,
        )
        assert shown.returncode == 0
        assert shown.stdout == b"a\r\nb\n"

    def test_an_opener_failure_leaves_the_branch_and_no_receipt(self, tmp_path):
        # Honest partial state: the push happened, the opener's exception
        # propagates as itself, and nothing pretends a pull request exists.
        origin = a_target_repository(tmp_path)

        def a_failing_opener(spec: PullRequestSpec) -> str:
            raise RuntimeError("the forge said no")

        with pytest.raises(RuntimeError, match="the forge said no"):
            deliver_pull_request(a_patch_object(), origin, a_failing_opener)
        assert "proposal/" in run_git("branch", cwd=origin)


class TestTheEmittedFloor:
    """The no-privilege mode carries exactly what the pull request would."""

    def test_the_floor_carries_the_same_evidence(self, tmp_path):
        patch = a_patch_object()
        written = emit_files(patch, tmp_path / "out")
        proposal = (tmp_path / "out" / "PROPOSAL.md").read_text(encoding="utf-8")
        assert render_body(patch) in proposal
        assert "- delete `models/stale.sql` from the target" in proposal
        assert (
            "- write `files/models/schema_fact.yml` to `models/schema_fact.yml`"
            in proposal
        )
        emitted = tmp_path / "out" / "files" / "models" / "schema_fact.yml"
        assert emitted.read_text(encoding="utf-8") == THE_DECLARATION_TEXT
        assert set(written) == {tmp_path / "out" / "PROPOSAL.md", emitted}

    def test_an_emission_never_overwrites(self, tmp_path):
        occupied = tmp_path / "out"
        occupied.mkdir()
        (occupied / "already.txt").write_text("here", encoding="utf-8")
        with pytest.raises(ValueError, match="never overwrites"):
            emit_files(a_patch_object(), occupied)

    def test_a_deletion_only_proposal_still_emits_its_evidence(self, tmp_path):
        empty = Delta(format="dagster", name="generator")
        patch = a_patch_object(
            verdict=verify(a_tree(), empty, lambda tree: tree),
            edits={"models/stale.sql": None},
        )
        written = emit_files(patch, tmp_path / "out")
        assert [path.name for path in written] == ["PROPOSAL.md"]
        proposal = written[0].read_text(encoding="utf-8")
        assert "- delete `models/stale.sql` from the target" in proposal

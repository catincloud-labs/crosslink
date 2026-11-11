# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""Delivery: a verified proposal rendered where a human can accept it.

ADR-0003 fixes the seam this module sits on: ``propose_edits`` returns the
patch object - diff, rationale, and the verification evidence from the
sandbox run - and rendering it as a pull request (or anything else) is an
adapter, so the choice of forum never reaches the core. :class:`PatchObject`
is that noun, given a shape; the two delivery modes here are its adapters.
Nothing in this module generates, judges, or amends a proposal - it carries
one, and the carrying is deliberately the least interesting step of the loop.

Five decisions here are deliberate, each stated rather than absorbed:

**A patch object its own verdict refuses cannot be constructed.** Delivery of
a proposal whose evidence says it did not do what it claimed would be a lie
told by packaging, so the refusal happens at construction - the same doctrine
as :class:`~crosslink.delta.Changed`: a value a proposal could lie in is
validated where it is made, not where it is used.

**The deliverer borrows, never holds.** No parameter anywhere in this module
accepts a credential. The git transport runs under whatever ambient identity
the operator's environment already carries, per invocation, and the forge
half of a pull request is a callable the operator supplies - the adapter
cannot hold what its signature never receives. ``docs/ROADMAP.md`` records
the decision (*Delivery*), and the emitted-files mode
(:func:`emit_files`) is the floor that needs no authority at all. A future
long-lived service re-opens the question; that is the wire-layer tripwire,
not this module's business.

**Delivery never overwrites.** A branch that already exists on the target is
refused, an emission into a non-empty directory is refused, and an edit set
already true in the target is refused rather than delivered as an empty
commit - each a statement that a second delivery is a new decision, not a
retry this module makes on its own.

**The link between the file edits and the verdict is the author's claim.**
The verdict was computed in declaration space over a sandbox tree; the edits
are file bytes for a real repository, and this module cannot check that the
one realizes the other - that is the sandbox's job, done before the patch
object exists. Today every patch object is hand-written and the coherence is
hand-guaranteed; tier-3 ``propose_edits`` closes the gap by construction
when it arrives, which is also why the type lives here ready to be returned.

**Rendered output carries no product identifier.** A rendered body or commit
travels to a target repository and whatever forum sits over it; it carries
the rationale and the evidence, and nothing that names the tool that wrote
it. The evidence is the signature.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields as dataclass_fields
from pathlib import Path

from .delta import Delta
from .model import ProjectDeclarations
from .verify import Verdict

__all__ = [
    "Delivered",
    "DeliveryError",
    "OpenPullRequest",
    "PatchObject",
    "PullRequestSpec",
    "deliver_pull_request",
    "emit_files",
    "render_body",
]


class DeliveryError(RuntimeError):
    """A delivery act failed in the environment - a git command, a missing
    base - as opposed to a :class:`ValueError` refusal of the input itself."""


# A closing keyword adjacent to an issue reference. GitHub scores these in a
# merged commit's message, so an unguarded one in a rationale would close an
# issue in the TARGET repository from author prose - the hazard AGENTS.md
# marks, injected into someone else's repo. The keyword must be a whole word
# and the reference must follow it adjacently (optional colon, optional
# owner/repo); a keyword merely appearing in a sentence that also names an
# issue does not match, because only adjacency fires there too.
_CLOSING_REFERENCE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b[ \t]*:?[ \t]*"
    r"(?:[\w.-]+/[\w.-]+)?#\d+",
    re.IGNORECASE,
)


def _contained_path(path: str) -> str:
    """The one normalized spelling of an edit path, or a refusal.

    Backslashes normalize to the forward-slash tree (the same normalization
    :class:`~crosslink.dbt.DbtProject` applies, for the same reason: one
    spelling per file). Everything that could land a write outside the
    target's working tree - an absolute path, a drive letter, a dot or
    dot-dot segment - is refused, and so is any segment spelling the
    repository's own metadata directory: git refuses to track such a path,
    and failing here is the honest version of failing there.
    """

    normalized = path.replace("\\", "/")
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(
            f"edit path {path!r} is not a relative path inside the target"
        )
    segments = normalized.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise ValueError(
            f"edit path {path!r} escapes or re-enters the tree; refused"
        )
    # Windows strips trailing dots and spaces for real file operations, so
    # `.git.` and `.git ` both resolve to `.git` on disk while a naive `==`
    # comparison misses them - the difference between a refused path and a
    # write into the repository's own hooks. Normalize the same way the
    # filesystem will before comparing.
    if any(segment.rstrip(". ").casefold() == ".git" for segment in segments):
        raise ValueError(
            f"edit path {path!r} reaches into the repository's own metadata; refused"
        )
    return normalized


@dataclass(frozen=True)
class PatchObject:
    """ADR-0003's patch object: the product the adapters carry.

    ``edits`` maps target-relative paths to their full new text, or to
    ``None`` for a deletion - plain bytes-to-be, not a diff format, so
    applying one needs nothing but a filesystem. Paths are normalized and
    contained at construction; the same path stated twice with the same text
    collapses to one statement, with different texts refuses - the house
    duplicate doctrine, because a mapping that contradicts itself has no
    honest reading.

    ``verdict`` is the sandbox evidence, and it must close: see the module
    docstring for why a refusing verdict is unconstructable here rather than
    undeliverable later.
    """

    title: str
    rationale: str
    edits: Mapping[str, str | None]
    verdict: Verdict

    def __post_init__(self) -> None:
        if not self.title.strip() or "\n" in self.title:
            raise ValueError("a patch object's title is one non-empty line")
        if not self.rationale.strip():
            raise ValueError(
                "a patch object without a rationale asks for acceptance "
                "without giving a reason"
            )
        for label, text in (("title", self.title), ("rationale", self.rationale)):
            hit = _CLOSING_REFERENCE.search(text)
            if hit:
                raise ValueError(
                    f"the {label} places a closing keyword immediately before "
                    f"{hit.group()!r}: the title and rationale become a commit "
                    "message GitHub scans on merge, so this would close that "
                    "issue in the TARGET repository from prose. Reword it so the "
                    "reference is not a close/fix/resolve adjacency."
                )
        if not self.verdict.closes:
            raise ValueError(
                "a refusing verdict is not deliverable: the sandbox disagrees on "
                + ", ".join(self.verdict.disagreements)
            )
        normalized: dict[str, str | None] = {}
        for path, content in self.edits.items():
            contained = _contained_path(path)
            if contained in normalized and normalized[contained] != content:
                raise ValueError(
                    f"the edit path {contained!r} is stated twice with "
                    "different content"
                )
            normalized[contained] = content
        if not normalized:
            raise ValueError("a patch object with no edits proposes nothing")
        object.__setattr__(self, "edits", normalized)


@dataclass(frozen=True)
class PullRequestSpec:
    """Everything the forge half needs, and nothing it does not.

    ``repository`` is the target as the caller named it, ``branch`` is
    pushed and present on the remote by the time the opener sees this, and
    ``body`` already carries the verification evidence. An opener that needs
    more than this is holding something the seam exists to keep out.
    """

    repository: str
    branch: str
    base: str
    title: str
    body: str


# The forge seam: spec in, the opened pull request's address out. Supplied by
# the operator per act - an inline `gh pr create` wrapper is the expected
# spelling - and never stored: the delivery decision in `docs/ROADMAP.md`,
# expressed as a type.
OpenPullRequest = Callable[[PullRequestSpec], str]


@dataclass(frozen=True)
class Delivered:
    """One delivery's receipt: where the proposal now lives."""

    branch: str
    base: str
    commit: str
    pull_request: str


def _counted(declared: ProjectDeclarations) -> str:
    parts = []
    for noun, items in (
        ("model", declared.models),
        ("source", declared.sources),
        ("declared key", declared.declared_keys),
        ("declared join", declared.declared_joins),
        ("semantic model", declared.semantic_models),
        ("metric", declared.metrics),
    ):
        count = len(items)
        parts.append(f"{count} {noun}" + ("" if count == 1 else "s"))
    return ", ".join(parts)


def _rendered_delta(delta: Delta) -> str:
    """The delta, entry by entry, verbatim - the evidence half of the body.

    Only non-empty buckets render, but what renders is each entry's own
    ``repr``: the reader sees the recorded values, not a paraphrase of them.
    """

    if delta.is_empty:
        return (
            f"format {delta.format!r}, project {delta.name!r}: empty - "
            "nothing changes in declaration space"
        )
    lines = [f"format {delta.format!r}, project {delta.name!r}"]
    for field in dataclass_fields(Delta):
        if field.name in ("format", "name"):
            continue
        edits = getattr(delta, field.name)
        if edits.is_empty:
            continue
        lines.append(f"{field.name}:")
        for item in edits.added:
            lines.append(f"  + {item!r}")
        for item in edits.removed:
            lines.append(f"  - {item!r}")
        for change in getattr(edits, "changed", ()):
            lines.append(f"  ~ {change.before!r}")
            lines.append(f"    -> {change.after!r}")
            lines.append("    fields: " + ", ".join(change.fields))
    return "\n".join(lines)


def render_body(patch: PatchObject) -> str:
    """The proposal's body: rationale, then the evidence, verbatim.

    One rendering for both delivery modes, so the floor mode carries exactly
    what the pull request would - the mode changes who applies the edits,
    never what they are shown. The verification section is the machine's
    answer to the question every serious review template asks: how do we
    know it worked.
    """

    verdict = patch.verdict
    return f"""## What changes

{patch.rationale}

## Verification

Machine-checked in a sandbox, not asserted: the proposed change was applied
to a copy of the project's inputs, the project rebuilt and re-reduced, and
the observed declaration delta compared against the one stated before the
patch existed. The observed delta equals the stated one.

The stated and observed delta (equal, shown once):

```text
{_rendered_delta(verdict.stated)}
```

The reduction before the change held {_counted(verdict.before)}; after it,
{_counted(verdict.after)}.
"""


def _branch_from(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].rstrip("-")
    if not slug:
        raise ValueError(
            f"no branch name is derivable from the title {title!r}; pass one"
        )
    return f"proposal/{slug}"


# git resolves its repository from the environment before it consults cwd, so
# an inherited GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE - exported for the
# duration of any git hook or `git`-launched process - would make every
# command below act on the caller's real repository instead of the ephemeral
# clone. Only the repository-location vars are scrubbed: the identity vars are
# kept, because borrowing the operator's ambient identity is the layer's shape.
_GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
    "GIT_CEILING_DIRECTORIES",
)


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    for name in _GIT_LOCATION_VARS:
        env.pop(name, None)
    return env


def _run_git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    # errors="replace": a localized, non-UTF-8 git message on a failing
    # command must reach the returncode check as text to be wrapped, not raise
    # UnicodeDecodeError past the ValueError/DeliveryError taxonomy.
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_git_env(),
    )


def _git(*args: str, cwd: Path) -> str:
    done = _run_git(*args, cwd=cwd)
    if done.returncode != 0:
        raise DeliveryError(
            f"git {' '.join(args)} failed: "
            + (done.stderr.strip() or done.stdout.strip())
        )
    return done.stdout.strip()


def _apply_edits(patch: PatchObject, root: Path) -> None:
    for path in sorted(patch.edits):
        text = patch.edits[path]
        target = root / path
        if text is None:
            if not target.is_file():
                raise ValueError(
                    f"cannot delete {path!r}: the target does not hold it"
                )
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            # newline="" writes the text byte-for-byte: the patch content is
            # the author's statement, and a platform translating it would be
            # delivering something nobody wrote.
            target.write_text(text, encoding="utf-8", newline="")


def deliver_pull_request(
    patch: PatchObject,
    repository: str | Path,
    open_pull_request: OpenPullRequest,
    *,
    branch: str | None = None,
    base: str | None = None,
) -> Delivered:
    """Render ``patch`` as a branch on ``repository`` plus an opened pull
    request, and return the receipt.

    The git half needs only a clonable address - a local path or bare
    repository works, which is what makes this testable with no network and
    no forge - and runs in an ephemeral clone, so the operator's own
    checkouts are never touched. git's repository-location environment
    (``GIT_DIR`` and kin) is scrubbed for every command, so an invocation
    from inside a hook cannot redirect the work onto the caller's real
    repository. ``core.autocrlf`` is off in that clone: the edits land
    byte-for-byte regardless of the platform delivering them, while the
    target's own ``.gitattributes`` policy still applies.

    The forge half is ``open_pull_request``, called exactly once, after the
    push, with a :class:`PullRequestSpec`. An opener that raises leaves the
    pushed branch in place and no receipt - honest partial state, surfaced
    as the opener's own exception rather than swallowed into a retry.

    ``base`` names the branch the proposal is based on and proposed
    against; it must exist on the target. When omitted, the target's own
    ``HEAD`` decides - and a target whose symbolic ``HEAD`` names a branch
    that no longer exists (a mirror whose default was renamed without
    updating ``HEAD``) is refused with that diagnosis, distinct from the
    no-commits one, because ``base=`` recovers the one and nothing recovers
    the other.

    Refusals (:class:`ValueError`): a branch that already exists on the
    target, an edit set already true in the target, a deletion of something
    the target does not hold, a caller-passed branch or base name that reads
    as an option or is not a well-formed git branch name, a base the target
    does not hold. Environmental failures (:class:`DeliveryError`): git
    itself, a target whose ``HEAD`` does not resolve while ``base`` is not
    given, and a target with no commits - a proposal needs a base to be
    proposed against.

    The patch's own paths are staged with ``-f``, so an edit the author
    stated against a path the target happens to ``.gitignore`` is still
    delivered - the author naming the path is the deliberate override - while
    a genuinely empty change (edits already true in the target) still refuses.
    """

    body = render_body(patch)
    name = branch if branch is not None else _branch_from(patch.title)
    if name.startswith("-"):
        raise ValueError(f"branch name {name!r} reads as an option; refused")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as scratch:
        workspace = Path(scratch)
        clone = workspace / "clone"
        _git(
            "clone", "-c", "core.autocrlf=false", "--",
            str(repository), str(clone), cwd=workspace,
        )
        if base is not None:
            if base.startswith("-"):
                raise ValueError(f"base name {base!r} reads as an option; refused")
            if _run_git("check-ref-format", "--branch", base, cwd=clone).returncode != 0:
                raise ValueError(
                    f"base name {base!r} is not a well-formed git branch name; refused"
                )
            if _run_git(
                "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{base}",
                cwd=clone,
            ).returncode != 0:
                raise ValueError(
                    f"base {base!r} does not exist on the target"
                )
            start_point: tuple[str, ...] = (f"origin/{base}",)
        else:
            try:
                base = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=clone)
            except DeliveryError as error:
                # An unresolvable HEAD and an empty repository fail the same
                # rev-parse, but they are different facts about the target and
                # the remote-tracking refs discriminate: a mirror whose default
                # was renamed without updating HEAD still clones its branches.
                branches = sorted(
                    line.strip().removeprefix("origin/")
                    for line in _run_git(
                        "branch", "--remotes", cwd=clone
                    ).stdout.splitlines()
                    if line.strip() and "->" not in line
                )
                if branches:
                    raise DeliveryError(
                        "the target's HEAD does not resolve to a branch, but "
                        "the target has commits (remote branches: "
                        + ", ".join(branches)
                        + "); pass base= to name the base explicitly"
                    ) from error
                raise DeliveryError(
                    "the target repository has no commits: a proposal needs a "
                    "base to be proposed against"
                ) from error
            start_point = ()
        # Well-formedness before existence: a malformed name (`a..b`, an
        # embedded space) is caller input this module refuses, not a git
        # environment failure, so it must surface as ValueError rather than
        # fall through to `switch` and re-raise as DeliveryError.
        if _run_git("check-ref-format", "--branch", name, cwd=clone).returncode != 0:
            raise ValueError(
                f"branch name {name!r} is not a well-formed git branch name; refused"
            )
        if _run_git(
            "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{name}",
            cwd=clone,
        ).returncode == 0:
            if branch is not None:
                raise ValueError(
                    f"branch {name!r} already exists on the target: a delivery "
                    "never overwrites"
                )
            # A derived name is lossy - punctuation, case, and anything past
            # sixty characters do not survive _branch_from - so an existing
            # branch is not proof of a re-delivery, and diagnosing it as one
            # would tell the author of a distinct change that it is a
            # duplicate. The refusal stands either way; the diagnosis must
            # name both readings.
            raise ValueError(
                f"the derived branch {name!r} already exists on the target: a "
                "delivery never overwrites. That branch may be a prior "
                "delivery of this proposal, or of a different proposal whose "
                "title merely derives to the same name - punctuation, case, "
                "and anything past sixty characters do not survive "
                "derivation. If this is a distinct change, pass branch= to "
                "name it apart."
            )
        _git("switch", "-c", name, *start_point, cwd=clone)
        _apply_edits(patch, clone)
        # -f and the patch's own paths, not `-A -- .`: `git add -A` would honour
        # the target's .gitignore and silently drop an edit the author stated
        # against an ignored path, disagreeing with emit_files about what is
        # deliverable. The `--` guards a path that reads as an option.
        _git("add", "-f", "--", *sorted(patch.edits), cwd=clone)
        if not _run_git("status", "--porcelain", cwd=clone).stdout.strip():
            raise ValueError(
                "the edits change nothing in the target: nothing to deliver"
            )
        _git("commit", "-m", f"{patch.title}\n\n{patch.rationale}", cwd=clone)
        commit = _git("rev-parse", "HEAD", cwd=clone)
        _git("push", "origin", name, cwd=clone)
    spec = PullRequestSpec(
        repository=str(repository), branch=name, base=base,
        title=patch.title, body=body,
    )
    return Delivered(
        branch=name, base=base, commit=commit,
        pull_request=open_pull_request(spec),
    )


def _proposal_document(patch: PatchObject) -> str:
    writes = [path for path in sorted(patch.edits) if patch.edits[path] is not None]
    deletes = [path for path in sorted(patch.edits) if patch.edits[path] is None]
    steps = [f"- write `files/{path}` to `{path}` in the target" for path in writes]
    steps += [f"- delete `{path}` from the target" for path in deletes]
    return (
        f"# {patch.title}\n\n"
        + render_body(patch)
        + "\n## To apply\n\n"
        + "\n".join(steps)
        + "\n\nApply under your own identity and review as you would any"
        " contributor's change: the verification section above is the"
        " machine's evidence, and acceptance stays yours.\n"
    )


def emit_files(patch: PatchObject, directory: str | Path) -> tuple[Path, ...]:
    """The privilege floor: the proposal as files a human applies.

    Writes ``PROPOSAL.md`` - the same rendered body a pull request would
    carry, plus the apply steps - and each edited file's full text under
    ``files/``, into a directory that must be empty or absent. Deletions
    have no file to write; they appear as apply steps only. Returns the
    paths written.
    """

    target = Path(directory)
    if target.exists():
        if not target.is_dir():
            raise ValueError(f"{str(target)!r} is not a directory")
        if any(target.iterdir()):
            raise ValueError(
                f"an emission never overwrites: {str(target)!r} is not empty"
            )
    target.mkdir(parents=True, exist_ok=True)
    written = [target / "PROPOSAL.md"]
    written[0].write_text(_proposal_document(patch), encoding="utf-8", newline="\n")
    for path in sorted(patch.edits):
        text = patch.edits[path]
        if text is None:
            continue
        destination = target / "files" / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8", newline="")
        written.append(destination)
    return tuple(written)

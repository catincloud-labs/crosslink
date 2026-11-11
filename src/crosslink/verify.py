# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""The oracle harness: a patch judged against the delta it claims.

ADR-0003's mechanism, made runnable. A proposal states its intended effect as
a :class:`~crosslink.delta.Delta` before any patch exists; the harness applies
the patch to a copy of the project's inputs, rebuilds, re-reduces, and
compares the observed delta - ``diff(C, C')`` - against the stated one. The
question is never *"is this good code?"* but *"does the re-reduction produce
the delta that was already specified?"*

Three decisions here are deliberate, each stated rather than absorbed:

**The patch is opaque on purpose.** A patch is any callable from tree to
tree, and the harness never inspects it - it applies it and judges the
re-reduction. Understanding a patch is exactly the burden the mechanism
exists to remove; a harness that grew an opinion about patch *content* would
be review wearing a lab coat. Every patch this harness ever meets before the
roadmap's last step is hand-written, which is what makes the verifier
provable before a single prompt exists.

**Closes means equals.** A patch closes its stated delta only when the
observed delta equals it exactly - not contains it, not approximates it. A
patch that did more than it claimed in declaration space did something nobody
stated in advance, and accepting it would put the surplus outside the
mechanism. The refusal names the nouns where the two deltas disagree, so a
drift report can say which claim failed rather than that one did.

**The oracle is necessary, not sufficient, and the blind spot is
structural.** The comparison sees exactly what the reduction sees. A patch
can close its delta while breaking something the reduction does not model -
declaration text the parser deliberately ignores, the compute behind a model -
and this harness will accept it. That is not a defect to fix here: the
target project's own test suite is the second, independent verifier ADR-0003
names, and the calibration suite demonstrates the blind spot with a passing
oracle and a failing stand-in suite rather than describing it in prose.

The sandbox subject is a :class:`ProjectTree`: the plain-data constructor
inputs of a :class:`~crosslink.project.DagsterProject`, which is why applying
a patch needs neither an orchestrator nor a filesystem. A real format's tree
(files on disk, a build step) joins when tier-3 work starts; it changes what
``reduce`` costs, not what the verdict means.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields as dataclass_fields

from .delta import Delta, diff
from .model import ProjectDeclarations, ProjectModel
from .project import DagsterProject

__all__ = [
    "Patch",
    "ProjectTree",
    "Verdict",
    "verify",
]


@dataclass(frozen=True)
class ProjectTree:
    """The plain-data inputs of a synthetic project - the sandbox subject.

    Everything a :class:`~crosslink.project.DagsterProject` is constructed
    from, held as a value so a sandbox copy is a copy of some dictionaries
    rather than a checkout. ``reduce`` is the whole read path: build the
    project, take its declarations.
    """

    models: tuple[ProjectModel, ...] = ()
    name: str = "sandbox"
    declaration_sources: Mapping[str, str] | None = None
    semantic_sources: Mapping[str, str] | None = None
    source_declarations: Mapping[str, str] | None = None

    def reduce(self) -> ProjectDeclarations:
        return DagsterProject(
            self.models,
            name=self.name,
            declaration_sources=self.declaration_sources,
            semantic_sources=self.semantic_sources,
            source_declarations=self.source_declarations,
        ).declarations()


# A patch: tree in, tree out. Hand-written for every step of the roadmap
# before the last one.
Patch = Callable[[ProjectTree], ProjectTree]


@dataclass(frozen=True)
class Verdict:
    """One patch, judged. The verification half of ADR-0003's patch object.

    ``closes`` is the acceptance: the observed delta equals the stated one.
    ``disagreements`` names the collections where they differ - empty exactly
    when ``closes`` - so a refusal arrives naming the failed claim, not just
    the fact of failure. ``before`` and ``after`` are the two reductions the
    verdict was computed from: the evidence travels with the answer, so
    whatever renders a proposal can show what the sandbox actually saw
    rather than asserting that it looked.
    """

    closes: bool
    stated: Delta
    observed: Delta
    before: ProjectDeclarations
    after: ProjectDeclarations
    disagreements: tuple[str, ...]


def _sandbox_copy(tree: ProjectTree) -> ProjectTree:
    # The patch gets its own mappings: "apply the patch to a copy" must hold
    # against a patch that mutates in place, or a refused patch could still
    # have edited the caller's tree on the way to its refusal.
    return ProjectTree(
        models=tree.models,
        name=tree.name,
        declaration_sources=dict(tree.declaration_sources or {}),
        semantic_sources=dict(tree.semantic_sources or {}),
        source_declarations=dict(tree.source_declarations or {}),
    )


def verify(tree: ProjectTree, stated: Delta, patch: Patch) -> Verdict:
    """Apply ``patch`` to a copy of ``tree`` and judge it against ``stated``.

    The three steps of ADR-0003's loop: reduce the tree as it stands (``C``),
    apply the patch to a sandbox copy and reduce again (``C'``), then compare
    ``diff(C, C')`` with the stated delta. Accepted means equal; refused
    means the verdict names the disagreeing collections.

    Refuses - with :class:`ValueError`, never a guess - a stated delta bound
    to a different project than the tree reduces to: a verdict computed
    against the wrong subject would be evidence about nothing. A patch that
    *renames* the project surfaces the same way, because ``diff`` refuses to
    compare across projects and this harness does not catch what it cannot
    interpret. A patch that raises, raises: a broken patch is not a refusal,
    and dressing the crash as a verdict would hide it from whoever wrote the
    patch.
    """

    before = tree.reduce()
    if (stated.format, stated.name) != (before.format, before.name):
        raise ValueError(
            f"stated delta is bound to {stated.format!r}/{stated.name!r} "
            f"but the tree reduces to {before.format!r}/{before.name!r}: "
            f"a verdict against the wrong subject is evidence about nothing"
        )
    after = patch(_sandbox_copy(tree)).reduce()
    observed = diff(before, after)
    disagreements = tuple(
        f.name
        for f in dataclass_fields(Delta)
        if f.name not in ("format", "name")
        and getattr(observed, f.name) != getattr(stated, f.name)
    )
    return Verdict(
        closes=not disagreements,
        stated=stated,
        observed=observed,
        before=before,
        after=after,
        disagreements=disagreements,
    )

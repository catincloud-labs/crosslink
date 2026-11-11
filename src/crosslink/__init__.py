# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""A project format reduced from an orchestrated asset graph, and the seam it uses.

This package does not import an orchestrator anywhere - not lazily, not at all.
``DagsterProject.from_asset_graph`` is **duck-typed**: it accepts anything
shaped like a set of asset definitions, which is why the whole suite runs with
nothing orchestrator-side installed. The coupling is to a *shape*, not to a
distribution, and that is a property worth keeping rather than an accident.

Tier 3 - the write path - is declared in :mod:`crosslink.protocol` and is not
yet implemented. That is the direction this project exists to build, and it is
deliberately the last thing standing.
"""

from .context import ProjectContext
from .dbt import DbtProject
from .deliver import (
    Delivered,
    DeliveryError,
    OpenPullRequest,
    PatchObject,
    PullRequestSpec,
    deliver_pull_request,
    emit_files,
    render_body,
)
from .delta import Changed, Delta, KeyedEdits, SetEdits, canonical, diff
# The kind constants ride along because the `findings` function shadows the
# submodule as a package attribute (`crosslink.findings` resolves to the
# function), so the root is the one place a plain-import consumer can reach
# them.
from .findings import (
    DANGLING_DECLARED_JOIN,
    DANGLING_DECLARED_KEY,
    UNDECLARED_LINEAGE_ROOT,
    UNKNOWN_READER,
    Finding,
    findings,
)
# `generate` the function shadows its submodule the same way `findings` does,
# so its companions ride along to the root for the same reason.
from .generate import (
    Attempt,
    Generation,
    GenerationError,
    ProposalRequest,
    Proposer,
    TreeEdit,
    claude_proposer,
    generate,
    render_request,
)
from .model import (
    DeclaredJoin,
    DeclaredKey,
    ExternalSource,
    Fingerprint,
    Freshness,
    Metric,
    ProjectDeclarations,
    ProjectModel,
    SemanticModel,
)
from .project import DagsterProject
from .protocol import EditableProject, FingerprintedProject, ProjectSource, tier_of
from .service import DriftVerdict, observe
from .verify import Patch, ProjectTree, Verdict, verify
from .wire import (
    Envelope,
    FingerprintPayload,
    WIRE_SCHEMA_VERSION,
    WireRefusal,
    decode_envelope,
    encode_envelope,
    fingerprint_envelope,
    snapshot_digest,
)

__version__ = "0.1.0"

__all__ = [
    "Attempt",
    "Changed",
    "DANGLING_DECLARED_JOIN",
    "DANGLING_DECLARED_KEY",
    "DagsterProject",
    "DbtProject",
    "DeclaredJoin",
    "DeclaredKey",
    "Delivered",
    "DeliveryError",
    "Delta",
    "DriftVerdict",
    "EditableProject",
    "Envelope",
    "ExternalSource",
    "Finding",
    "Fingerprint",
    "FingerprintPayload",
    "FingerprintedProject",
    "Freshness",
    "Generation",
    "GenerationError",
    "KeyedEdits",
    "Metric",
    "OpenPullRequest",
    "Patch",
    "PatchObject",
    "ProjectContext",
    "ProjectDeclarations",
    "ProjectModel",
    "ProjectSource",
    "ProjectTree",
    "ProposalRequest",
    "Proposer",
    "PullRequestSpec",
    "SemanticModel",
    "SetEdits",
    "TreeEdit",
    "UNDECLARED_LINEAGE_ROOT",
    "UNKNOWN_READER",
    "Verdict",
    "WIRE_SCHEMA_VERSION",
    "WireRefusal",
    "__version__",
    "canonical",
    "claude_proposer",
    "decode_envelope",
    "deliver_pull_request",
    "diff",
    "emit_files",
    "encode_envelope",
    "findings",
    "fingerprint_envelope",
    "generate",
    "observe",
    "render_body",
    "render_request",
    "snapshot_digest",
    "tier_of",
    "verify",
]

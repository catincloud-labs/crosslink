# Copyright 2026 David Anaya
# SPDX-License-Identifier: Apache-2.0
"""How a project is located and built - the construction contract.

``protocol.py`` deliberately declines to answer this: it describes what a
project can be *asked*, and states as a non-goal that it does not describe how
one is *constructed*. The formats disagree about what keys them - a directory,
a graph already in memory, a service - and that disagreement does not resolve
by picking whichever the first format happened to use.

This module is that missing half. In ``dagster-dex``, which shares this
package's read side (``PROVENANCE.md``), the same class sits inside the engine
boundary module, ``dex.py``, because it was written as a proposal *to* an
engine; it is not engine-specific, so here it stands on its own.

It is also the load-bearing question for this project. A format built only from
constructor arguments is a library object and is unreachable from anything
running in another process. A format resolved by name against a context is
addressable, which is the precondition for being a peer to a worker and a
scheduler rather than a call inside someone else's process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = ["ProjectContext"]


@dataclass(frozen=True)
class ProjectContext:
    """What a project format gets to build itself from.

    Two fields, because the formats disagree about what keys them and the
    disagreement does not resolve by picking whichever the first one used. A
    directory-backed project takes a path. A project reduced from a graph in
    memory has no path and no repository. A hosted one has service coordinates
    and neither.

    A construction contract shaped around the path-shaped case leaves the rest
    unbuildable, and widening it afterwards is a schema change with a
    deprecation attached - which is why this is worth settling before the second
    format exists rather than after.

    ``repo_root`` is where the caller was pointed, or ``None`` when there is no
    repository in the picture. A format is free to ignore it, and most
    non-filesystem ones will.

    ``options`` is the format's own non-secret coordinates, passed through
    verbatim. Refuse an option you cannot honor rather than accepting and
    ignoring it: a silently dropped setting is indistinguishable from a working
    one until something reads the wrong project.

    **No secret arrives here.** A format named in committed configuration is
    named in a committed file, so a credential in ``options`` would be a
    credential in version control.
    """

    repo_root: str | None = None
    options: Mapping[str, Any] = field(default_factory=dict)

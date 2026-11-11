# Provenance

This package's read side and the public
[`dagster-dex`](https://github.com/catincloud-labs/dagster-dex) come from the
same code. Neither depends on the other: nothing here imports `dagster_dex`,
and `pyproject.toml` names no such requirement. This file says what the two
share and what each left out, so that a port in either direction is a diff
rather than archaeology.

## What is shared, and how to see it

Besides `__init__.py`, five modules carry the same name in both packages:
`model.py`, `protocol.py`, `declarations.py`, `project.py` and
`conformance.py`. The comparison below is against `dagster-dex`'s first tag,
`v0.1.0`:

    git clone https://github.com/catincloud-labs/dagster-dex
    git -C dagster-dex checkout v0.1.0
    git diff --no-index dagster-dex/src/dagster_dex/protocol.py src/crosslink/protocol.py

Run the last command once per module. Both sides have moved since, so the
diffs are not empty; what they show is the same docstrings and the same
names, edited apart.

| here | in `dagster-dex` at `v0.1.0` | what a diff shows |
| --- | --- | --- |
| `protocol.py` | `protocol.py` | the same three tiers, `ProjectSource`, `FingerprintedProject` and `EditableProject`, and the same `tier_of` |
| `model.py` | `model.py` | the same neutral model, from `ProjectModel` to `ProjectDeclarations`. This side added the shared predicates and `layered_fingerprint`; that side has `SemanticField`, which this one does not |
| `declarations.py` | `declarations.py` | the same three parsers: `parse_declarations`, `parse_semantics` and `parse_source_declarations` |
| `project.py` | `project.py` | `DagsterProject` and the two unexported protocols it reads a graph through |
| `conformance.py` | `conformance.py` | `ProjectSourceContract`, `FingerprintedProjectContract` and the fixture builders |
| `context.py` | `dex.py` | `ProjectContext`. There it sits inside the engine boundary module; here it stands alone, because it is not engine-specific |

## What each left out

Not here, and in `dagster-dex`:

- **`dex.py`**, the mapping onto the dex engine's model (`to_transform_layer`,
  `transform_layer_notes`, `to_project_definitions`), and
  `tests/test_dex_bridge.py`, which tests it. Whether this package stays
  interoperable with that engine is an open decision, and an unused mapping
  acquires callers. Re-adding it is a bounded, one-file job.
- **`artifact.py`**, the transport that carries a reduced project as a file.

Here, and not in `dagster-dex`: the second format (`dbt.py`), the write path
(`findings.py`, `delta.py`, `verify.py`, `generate.py`, `deliver.py`), the
wire and its two processes (`wire.py`, `service.py`, `serve.py`,
`produce.py`), and the formats built to fail the contract
(`conformance_calibration.py`).

## Why two packages rather than one dependency

The two are under different constraints, each readable in its own tree.
`dagster-dex` is a plugin for one engine: its `requires-python` is `>=3.10`,
and its `AGENTS.md` keeps the engine import to one module so that everything
else runs with the engine uninstalled. This package targets no engine, has a
3.12 floor, takes `ration` for its two processes, and is built around
verifying a proposal against the reduction it claims to change (ADR-0003).

They also answer tier 3 differently. `dagster-dex`'s `main` reaches it with
`EditableDagsterProject`, whose edits land in hand-written declaration files
(its `AGENTS.md` says why those and not the models). Here no format serves
tier 3 yet, and a change is proposed against code (ADR-0002).

Sharing the read side as a dependency would mean arguing every change to it
against both sets of constraints. A port is still possible in either
direction, as a diff, and it is a decision each time rather than a sync.

## Copyright

Both repositories are Apache-2.0, `Copyright 2026 David Anaya` (each one's
`LICENSE`), so text moves between them without friction. Whether the holder
should become a legal entity is an open question; it would touch the per-file
headers as well as `LICENSE`.

# `schemas/` — the VFP contract (canonical)

This directory is the **single source of truth** for the data contract
shared between the Virtuoso Flow Plugin (SKILL) and VFP Tunnel (Python):

| Schema | Description | Authored in |
|--------|-------------|-------------|
| `context.schema.json` | Design context exported from Virtuoso | _TBD (Milestone 3)_ |
| `proposal.schema.json` | Agent design-modification proposal | _TBD (Milestone 4)_ |
| `transaction.schema.json` | Before/after change record + rollback | _TBD (Milestone 5)_ |
| `result.schema.json` | Simulation metrics + constraint outcome | _TBD (Milestone 6)_ |
| `constraint.schema.json` | Metric limits, DC-op checks, permissions | _TBD (Milestone 6)_ |

The authoritative **prose definitions and worked examples** currently live
in [`project.md`](../project.md) §10. As each milestone lands, the
corresponding JSON Schema file is added here and the Python side
(`tunnel/vfp_tunnel/rpc/schemas.py`) validates against it.

## Why a top-level `schemas/`?

The plugin and tunnel co-evolve this contract. Keeping it in one place
(rather than duplicated under `skill/` and `tunnel/`) means:

- a contract change is one edit, reviewed once;
- if VFP Tunnel is later split into its own repository (via
  `git subtree split`), this directory is the natural shared dependency.

See [`docs/development_notes.md`](../docs/development_notes.md) for the
repository-structure decision.

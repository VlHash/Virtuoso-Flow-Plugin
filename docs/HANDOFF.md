# VFP Handoff & Roadmap

Start here to pick up the **Virtuoso Flow Plugin (VFP)**.

## What VFP is

A bridge that lets an AI agent propose, review, apply, and verify analog
schematic edits inside Cadence Virtuoso — with every change auditable and
reversible. Two halves live in one repo:

- **`skill/`** — the in-Virtuoso plugin (Cadence SKILL). Reads design
  context, shows proposals, applies them as reversible **transactions**,
  audits **connectivity**, lints the **testbench**, and gates simulation on
  a **dirty-check**. Only code running inside Virtuoso can see unsaved
  state, so this half owns everything GUI / cellview.
- **`tunnel/`** — the VFP Tunnel (pure-stdlib Python, 3.6+). A JSON-RPC
  daemon the plugin and the agent talk to: stores proposals / transactions
  / sim jobs / results, runs the **freshness guard** + **sim runner**,
  exposes an **MCP** server of agent tools, and a push-**event** stream.
- **`schemas/`** — JSON schemas shared by both halves (context, proposal,
  transaction, result, job, constraint).

```
 agent ──MCP/RPC──▶  VFP Tunnel (Python)  ◀──RPC/events──  VFP plugin (SKILL)  ──▶ Virtuoso
                      proposals/txns/jobs                   context/apply/lint/sim
```

## Where things are

| Path | What |
|------|------|
| `skill/vfp_*.il` | plugin modules: init, rpc client/server, context, schematic, connectivity, sim, proposal, transaction, ade, menu, dashboard |
| `tunnel/vfp_tunnel/` | daemon, rpc, and the proposal / transaction / session / sim / event / agent stores |
| `schemas/*.schema.json` | the wire contracts |
| `tests/` | pytest, tunnel side |
| `examples/rfc_classab_opa/` | a worked example payload set |
| `docs/plugin_usage.md` | how to load and drive the plugin |
| `docs/development_notes.md` | architecture + dev workflow detail |

## Running & testing

- **Tests**: `pytest tests` — *not* bare `pytest` (that also collects the
  local `gui_test/` scratch dir and fails on import). Pure stdlib + an
  optional `jsonschema`.
- **Tunnel**: `scripts/vfp tunnel start` (the JSON-RPC daemon). `vfp doctor`
  for health; `vfp session|proposal|transaction|job …` subcommands.
- **Plugin**: in the Virtuoso CIW, `load("…/skill/vfp_init.il")` then
  `vfpInit()` — it loads the modules **and** registers the "Virtuoso Flow"
  menu (`vfpLoad()` alone only loads modules).
- More in `docs/plugin_usage.md` and `docs/development_notes.md`.

## Roadmap

The core loop **M1–M7** (context → proposal → review → apply → transaction →
result → constraints) is done. The problem-driven **M8+** plan:

| Milestone | What | Status |
|-----------|------|--------|
| **M8** | Session identity: fingerprint dedup, long-poll heartbeat, reap, `vfp doctor` | done |
| **M9** | Sim job model + freshness guard + runner (tunnel); netlist **dirty-check** + inputs **fingerprint** + real-spectre closed loop (plugin) | done |
| **M10** | Cellview-specific real-spectre + provenance/metric_quality: `session_id` in jobs (M10a); cellview wrapper + **attended in-session netlist** via `maeCreateNetlistForCorner`, reusing the live session's license (M10b, plugin); result schema 0.2 merge (collab F.2) | M10a/b done (plugin), live on Project/inv_tb; collab F.2 pending |
| **M11** | Connectivity snapshot/diff, txn connectivity audit, auto-net risk + `vfpPinNetLabel`, TB lint + pre-apply checkpoint, **parameter blame chain + batch apply + rollback picker** | done |
| **M12** | Approval envelope + experiment ledger | planned (collab-led) |
| **M13** | Transport hardening (errors / UTF-8), deck patch, `doctor --fix` | M13a done; b/c planned |

## Collaboration

Two contributors share one design server; the SKILL (plugin) and Python
(tunnel) sides are split to stay low-conflict. The live scratch state,
coordination protocol, and hard-won gotchas live in the gitignored
`AGENTS.md` and `TODO.md`. All commits keep clean human ownership — no
automated AI attribution in messages or PRs.

## Known debt

- **Transaction actor/author**: a transaction records *what* changed and
  *when*, but not *who* applied or rolled it back, nor in which Virtuoso
  session. The M8 session id could be bound into the txn to close this.
- **Sub-second blame ordering**: transaction timestamps are second-granular;
  a `created_ts` epoch on the txn would let the parameter blame chain order
  bursts of edits precisely.

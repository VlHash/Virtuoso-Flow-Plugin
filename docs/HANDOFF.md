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
| **M10** | Cellview-specific real-spectre + provenance/metric_quality: `session_id` in jobs (M10a); cellview wrapper + **attended in-session netlist** via `maeCreateNetlistForCorner`, reusing the live session's license (M10b, plugin); M10c saved_at; result schema 0.2 = provenance + metric_quality + session (tunnel F.1–F.3) | done — live on Project/inv_tb |
| **M11** | Connectivity snapshot/diff, txn connectivity audit, auto-net risk + `vfpPinNetLabel`, TB lint + pre-apply checkpoint, **parameter blame chain + batch apply + rollback picker** | done |
| **Daemon** | **Delegated netlist + VFP Daemon**: a pluggable delegated backend (`plugin` / vcli / command / `module:callable`), netlisting over VFP's own tunnel↔plugin channel, and a VFP-managed headless `virtuoso -nograph` (`vfp daemon` start/status/stop) so delegated netlisting runs unattended — no GUI, no vcli. `plugin` is the default backend; delegated provenance `saved_at` rides a deck-dir sidecar | done — live on Project/inv_tb |
| **Txn audit** | `created_ts` (precise blame ordering) + `actor` / `session` / `session_fingerprint` bound at apply, closing the two known-debt items below | done |
| **M12** | Approval envelope + experiment ledger | planned |
| **M13** | Transport hardening (errors / UTF-8), deck patch, `doctor --fix` | M13a done; b/c planned |

### Layout track

The layout side mirrors the schematic architecture and reuses the same
context / proposal / transaction machinery.

| Stage | What | Status |
|-------|------|--------|
| **L1** | Layout context export (read-only): cell bbox, instance placement, layer/shape counts, via count → the `layout` context block | done |
| **L2** | Layout geometry lint: unconnected device pins, net-less metal, off-grid shapes → the `lint` block | done |
| **L3** | Layout↔schematic consistency (LVS-lite): device-set + per-terminal net-group diff → the `lvs` block. Connectivity-driven; not a sign-off LVS/DRC | done — live on the Project standard-cell library |
| **L4** | Layout-edit transactions (read-write): reversible geometry edits — geometry snapshot/diff, a pre-edit checkpoint, connectivity diff (reuses L3), and rollback by restoring the checkpoint view | first increment (transaction framework) done — live-verified on a scratch cell, incl. the open-editor GUI case |
| **L5** | Generic layout-primitive mechanics: PDK-agnostic, grid-snapped, transaction-wrapped shape/via/path ops with dry-run (the parameter-driven actuators) | planned |

### Extensibility direction (planned)

VFP is evolving into an **extensible, transaction-safe execution end**: a stable
extension API (register an RPC namespace, menu panels, and actions) plus layout
execution-end hooks (export context / selection, submit proposal, apply /
rollback transaction, run primitive, import / overlay markers, register a signoff
adapter) so that **external extensions can drive VFP's safe layout flow without
forking the core**. The core stays generic and PDK-agnostic; any design-intent
intelligence lives in the consuming extension, not in this repo.

## Collaboration

Two contributors share one design server; the SKILL (plugin) and Python
(tunnel) sides are split to stay low-conflict. The live scratch state,
coordination protocol, and hard-won gotchas live in the gitignored
`AGENTS.md` and `TODO.md`. All commits keep clean human ownership — no
automated AI attribution in messages or PRs.

## Known debt

- ~~Transaction actor/author~~ and ~~sub-second blame ordering~~ — **closed**.
  A transaction now records `created_ts` (epoch, so the blame chain orders
  same-second bursts precisely) and binds `actor` + the originating `session`
  / `session_fingerprint` at apply time — tunnel side (collab) + plugin side
  (`vfpCreateTransaction` sends `session_id` + `actor`).
- **Rollback actor** (remaining): "who *rolled back*" is still not captured —
  the daemon binds the audit on `transaction.create` only. Needs a daemon-side
  bind on rollback + the plugin sending `session_id` there.
- **Apply → audited-txn VNC pass** (remaining): the plugin-side audit params
  are verified, but the full GUI apply flow populating an audited transaction
  still owes a live VNC pass.

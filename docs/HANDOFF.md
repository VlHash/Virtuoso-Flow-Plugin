# Virtuoso Flow Plugin — Handoff

Snapshot for picking up this project (new contributor or AI agent). Pairs
with [`development_notes.md`](development_notes.md) (running log) and
[`../README.md`](../README.md) (user-facing overview).

Last updated: 2026-06-09 · branch `feat/vfp-mvp` · repo
`github.com/VlHash/Virtuoso-Flow-Plugin`.

---

## 1. What this is (30 seconds)

Two cooperating components for **reviewable, auditable AI-assisted analog
IC design** in Cadence Virtuoso:

- **Virtuoso Flow Plugin** (`skill/`, SKILL) — in-Virtuoso menu + dashboard,
  reads design context, shows agent proposals, applies *approved* changes
  as reversible transactions.
- **VFP Tunnel** (`tunnel/`, Python) — localhost JSON-RPC daemon + `vfp`
  CLI; the bridge to agents/CLIs; owns sessions, contexts, proposals,
  transactions, results, constraints, artifacts.

Design principle: the plugin handles what must be *visible and executable
inside Virtuoso*; the tunnel handles what's better *outside*. It must not
become a blind remote-SKILL executor — every change is a reviewed,
reversible transaction.

## 2. Status at handoff

| # | Milestone | Status |
|---|-----------|--------|
| 1 | Plugin skeleton (menu, dashboard, lib/cell/view) | **done** |
| 2 | Tunnel (CLI, JSON-RPC, sessions) + SKILL bridge | **done** |
| 3 | Design context export | **done** |
| 4 | Proposal workflow | **done** |
| 5 | Transactional parameter modification + rollback | **done** |
| 6 | Result + constraint display | not started |
| 7 | ADE/Spectre integration | not started |

**Verified outside the GUI:** 63 pytest tests (4 skip without `jsonschema`);
full CLI + helper smoke tests on the design server (Python 3.6.8); the SKILL
JSON encoder emits schema-conforming context; proposal + transaction
lifecycles verified end-to-end over JSON-RPC via the `vfp` CLI.

**Pending manual GUI checks for M4/M5** (need a real Virtuoso session): the
SKILL apply/rollback path (`vfpApplyProposal` → `vfpApplyTransaction` →
`vfpRollbackTransaction`) reads/writes CDF instance params via
`cdfGetInstCDF` + `dbSave`; confirm the exact CDF calls against IC23.1 and
that before/after capture + rollback restore the original values.

**Pending manual GUI checks** (need a real Virtuoso session; an agent
cannot drive the GUI):
1. **Connect** — click in the dashboard; expect `Connected (s_…)` and a
   session in `vfp session list`. *(Already observed working once —
   session `s_3f3bfab76264` registered — but re-confirm after changes.)*
2. **Export Context** — open a schematic, click **Export**; confirm the
   real instances/params/nets land via `vfp context show`.

## 3. Architecture

```
Cadence Virtuoso (Linux)                       design server (Linux)
┌───────────────────────────┐                 ┌──────────────────────┐
│ Virtuoso Flow Plugin       │  system()       │ VFP Tunnel daemon    │
│  skill/*.il                │  + Python       │  tunnel/vfp_tunnel   │
│  menu · dashboard          │  helper         │  JSON-RPC server     │
│  vfpExtractDesignContext   │ ───────────────▶│  127.0.0.1:47891     │
│  vfpConnect / Export       │  (newline JSON) │  sessions, contexts  │
└───────────────────────────┘                 └──────────┬───────────┘
        ▲  reads response s-expr                          │
        │                                          agents / vfp CLI
        └── skillrpc.py (the bridge helper) ──────────────┘
```

**The bridge (important):** base SKILL has no TCP sockets and no JSON
parser. So each call shells out (`system()`, synchronous) to
`tunnel/vfp_tunnel/skillrpc.py`, which talks JSON-RPC to the tunnel and
writes the response back as a **SKILL s-expression** that SKILL parses with
`read`. SKILL only ever *encodes* JSON (easy) and *reads* s-expressions
(native) — it never parses JSON or evals untrusted code. Big payloads (the
design context) go via a temp file (`--params-file`).

**The contract** lives in [`../schemas/`](../schemas) — five self-contained
JSON Schema (draft 2020-12) files. The tunnel validates against them when
`jsonschema` is installed (optional; no-op otherwise so the daemon stays
stdlib-only).

## 4. Repository map

```
skill/      SKILL plugin
  vfp_init.il        loader/lifecycle (vfpInit/vfpUnload)
  vfp_menu.il        "Virtuoso Flow" menu (CIW + schematic)
  vfp_dashboard.il   dashboard form
  vfp_utils.il       state, logging, cellview, JSON encoder, vfpToStr
  vfp_rpc_client.il  RPC client via the helper (vfpConnect/Ping/Export...)
  vfp_context.il     design-context extraction (M3)
  vfp_{schematic,proposal,transaction,ade,rpc_server}.il   STUBS (M4/M5/M7)
tunnel/vfp_tunnel/
  daemon.py cli.py config.py logging_config.py skillrpc.py
  rpc/{jsonrpc,transport,schemas}.py
  session/{registry,manager}.py
  design/context.py
  proposal/ transaction/ sim/ constraints/ artifact/ agent/   STUBS
schemas/    5 JSON Schema files + README (the contract)
examples/rfc_classab_opa/   context/proposal/constraint fixtures
scripts/    load_vfp.il (Virtuoso loader), vfp (CLI wrapper), start/stop_tunnel.sh
docs/       development_notes.md, plugin_usage.md, HANDOFF.md
tests/      28 pytest tests (conftest puts tunnel/ on sys.path)
```

## 5. How to run

**Tunnel** (on the design server, no install needed — system Python 3.6):
```bash
scripts/vfp tunnel start | status | stop
scripts/vfp session list
scripts/vfp context show
scripts/vfp context import --file examples/rfc_classab_opa/sample_context.json
```

**Plugin** (Virtuoso CIW; reload to pick up changes):
```lisp
load("/path/to/Virtuoso-Flow-Plugin/scripts/load_vfp.il")
```
Then `Virtuoso Flow → Open Dashboard` → Connect → (open schematic) → Export.

**Tests** (repo root): `pytest tests/` (needs `jsonschema`, `pyyaml`,
`pytest` — or `pip install -e tunnel[dev]`).

**Dev loop:** edit on the Windows checkout → `scp` changed `skill/`+`tunnel/`
to the server working copy → restart the tunnel if tunnel code changed →
reload the plugin in the CIW.

## 6. Decisions & gotchas (the stuff that bites)

- **Monorepo** — plugin + tunnel share one fast-changing contract; keep
  them together (split `tunnel/` later via `git subtree split` if ever
  needed). Contract is canonical in `schemas/`.
- **Tunnel is stdlib-only, Python 3.6+** — it must run on the design
  server's system Python. No third-party runtime deps (PyYAML/jsonschema
  are dev/optional). Don't use dataclasses, `X | None`, or `from __future__
  import annotations` in runtime code.
- **Cadence Python pollution** — inside Virtuoso, `PATH`/`LD_LIBRARY_PATH`
  point `python3` at Cadence's bundled 3.9, which dies with
  `undefined symbol: _Py_LegacyLocaleDetected`. Every path that runs Python
  pins the **system** interpreter with a sanitized env:
  `env -u PYTHONHOME LD_LIBRARY_PATH= /usr/bin/python3 …` (override with
  `VFP_PYTHON`). Applied in both `vfp_rpc_client.il` and `scripts/vfp`.
- **GE-2067** — probe the current cellview with the `win->editCellView`
  *property* (quiet), not the `geGetEditCellView` *function* (warns on the
  CIW). `errset` does not suppress warnings.
- **SKILL menu** — post-install trigger is the **4th** arg of
  `deRegUserTriggers`; remove via `hiGetBannerMenus` + `hiDeleteBannerMenu`.
- **Git workflow** — Claude makes the *code* commits (whole, consistent,
  at milestone boundaries; `git commit -F` to avoid the Bash tool's
  here-string mis-parse). The **owner** also pushes README/PR/merge commits
  to `feat/vfp-mvp`, so **always `git fetch` + `git rebase
  origin/feat/vfp-mvp` before pushing** (their README edits and the code
  changes don't overlap, so rebases are clean). Owner merges to `main` via
  PRs.
- **Out of the repo on purpose** (gitignored): `project.md`, `AGENTS.md`,
  `CLAUDE.md` (planning + agent-guidance, may reference internal infra) and
  `docs/IC231_gui_plugin_docs/` (proprietary Cadence docs). Recover from
  git history if needed.

## 7. Infrastructure (kept out of the repo)

The design server (host, SSH access, Virtuoso install, the full IC23.1
SKILL reference, and the server-side working copy) is intentionally not
documented in-repo. AI agents have it in project memory
(`vfp-server-access`); humans should ask the project owner. The authoritative
SKILL API reference is the IC23.1 help tree on that server — prefer it over
guessing signatures.

## 8. TODO / roadmap

### Immediate
- [ ] Run the two pending GUI checks (Connect, Export Context) on a real
      schematic; capture any CIW errors.
- [ ] (Optional) Open a PR `feat/vfp-mvp` → `main` summarizing M1–M3.

### Milestone 4 — Proposal workflow ✅ done
- Tunnel: `proposal/{model,manager,policy}.py`; methods `proposal.create`,
  `proposal.list`, `proposal.get`, `proposal.approve`, `proposal.reject`,
  `proposal.mark_applied`, `proposal.mark_failed`; store under
  `.vfp/proposals/`; validate against `schemas/proposal.schema.json`.
- CLI: `vfp proposal create --file … | list | show | approve | reject`.
- SKILL (`vfp_proposal.il` stub): `vfpFetchPendingProposals`,
  `vfpShowProposal` (render in a form), `vfpApproveProposal`,
  `vfpRejectProposal`. Wire the dashboard "Show Pending Proposals" button.
- Acceptance: `vfp proposal create --file examples/rfc_classab_opa/sample_proposal.json`
  then the proposal shows in the Virtuoso dashboard.

### Milestone 5 — Transactional parameter modification + rollback ✅ done
- SKILL: `vfp_schematic.il` reads/writes CDF instance params
  (`cdfGetInstCDF` → iterate `parameters` → set `value` → `dbSave`);
  `vfp_transaction.il` captures **before**, applies, captures **after**,
  records the transaction, and `vfpRollbackTransaction` restores `before`.
  `vfpApplyProposal` is gated on `approved` and delegates to
  `vfpApplyTransaction`; dashboard/menu **Rollback** rolls back the last
  applied transaction. *(SKILL CDF calls still need a live-GUI confirm.)*
- Tunnel: `transaction/{model,manager,permissions}.py`; methods
  `transaction.create/list/get/rollback/mark_rolled_back/mark_failed`; store
  under `.vfp/transactions/`. `transaction.create` links the proposal
  (approved → applied); `mark_rolled_back` cascades (applied → rolled_back).
  CLI: `vfp transaction list | show`.
- Permission enforcement: `transaction.permissions` matches
  `<instance>.<param>` against `allow_modify`/`deny_modify` globs (deny
  wins); `transaction.create` rejects denied changes (code -32002). The
  tunnel holds `self.permissions` (default empty = allow-all); M6's
  constraint engine will populate it from the constraint file. **No
  unrestricted `evalstring` to agents.**
- Acceptance (CLI, over JSON-RPC): create+approve a proposal → record a
  transaction (proposal → applied) → `transaction.rollback` returns the
  before-recipe → `mark_rolled_back` (proposal → rolled_back). 18 unit/RPC
  tests cover model, permissions, store, and linkage.

### Milestone 6 — Result + constraint display
- Tunnel: `sim/{parser,metrics}.py`, `constraints/engine.py`; methods
  `result.update`, `result.latest`, `constraint.check`; PyYAML returns as a
  real dep; validate against `result`/`constraint` schemas.
- CLI: `vfp result import --file … | latest`, `vfp constraint check --file …`.
- Dashboard: show metrics + pass/fail in the result area.

### Milestone 7 — ADE/Spectre integration
- SKILL (`vfp_ade.il` stub): list/trigger ADE tests if feasible; otherwise
  ingest result files first. Artifact folder per run under `.vfp/runs/`.

### Tech debt / nice-to-haves
- `vfp_rpc_server.il` (push events to the plugin) is a stub — only needed
  if polling becomes insufficient.
- `examples/folded_cascode_opa/` is a placeholder — populate as a 2nd example.
- Consider an MCP server (`agent/mcp_server.py`) once the proposal loop works.
- Per-call helper process is fine for now; revisit a persistent relay if
  call frequency grows.

## 9. Pointers

- Contract: [`../schemas/`](../schemas) (+ its README).
- Running log / deeper notes: [`development_notes.md`](development_notes.md).
- Plugin usage: [`plugin_usage.md`](plugin_usage.md).
- Tunnel details: [`../tunnel/README.md`](../tunnel/README.md).
- Worked example: [`../examples/rfc_classab_opa/`](../examples/rfc_classab_opa).

---
name: vfp
description: >-
  Drive and develop the Virtuoso Flow Plugin (VFP) in this repo — run and inspect
  simulation jobs (attended + delegated netlist), drive the tunnel daemon, verify
  live on the shared design server (ssh / virtuoso-bridge / vcli), and avoid the
  VFP-specific SKILL and shell gotchas. TRIGGER when the task touches sim jobs, the
  netlist worker, the tunnel, the cellview wrapper, or live Virtuoso/Spectre
  verification for Virtuoso-Flow-Plugin.
---

# VFP — Virtuoso Flow Plugin

Two halves sharing the `schemas/` JSON contract:
- **Plugin** (`skill/*.il`, IC23.1 SKILL) — in-Virtuoso menu/dashboard, design-context
  export, proposal review, transactions, and the **sim pre-flight + netlist**
  (`vfp_sim.il`, `vfp_netlist.il`).
- **Tunnel** (`tunnel/vfp_tunnel/`, stdlib Python 3.6+) — daemon, JSON-RPC, session
  registry, sim **job model + freshness guard + runner**, result/provenance store.

`scripts/` = loaders, the `vfp` CLI, the sim wrappers. `tests/` = Python tests.
Local working notes: `AGENTS.md` + `TODO.md` (gitignored). Front door: `docs/HANDOFF.md`.

## Test

- **Local:** `pytest tests` — NOT bare `pytest` (it collects `gui_test/` and fails on
  import). Windows host runs the full suite green.
- **Server** (`meow@192.168.185.231`, no git there — sync via `scp` or
  `git archive | ssh tar`): sanitized env
  `env -i HOME=/home/meow PATH=/usr/local/bin:/usr/bin:/bin /usr/bin/python3 -m pytest -q`.

## Drive a live Virtuoso (three channels — pick the lightest that fits)

- **virtuoso-bridge** (`virtuoso` skill) — GUI/SKILL on the user's live session over a
  TCP tunnel. `virtuoso-bridge start|status|windows`; venv `F:/VBL/virtuoso-bridge-lite/.venv`,
  `~/.virtuoso-bridge/.env` (:65440). It **auto-clicks hi-forms**, so modal flows can't be
  tested through it.
- **vcli** (`vcli-bridge` skill) — headless automation loop, the path for delegated
  netlisting. `F:/VBL/virtuoso-bridge-lite/scripts/vcli_remote.py` (`config|start|smoke|exec`).
  Drives the **same** running Virtuoso (ramic_bridge.il via `.cdsinit`).
- **spectre** skill — standalone netlist → Spectre → PSF, no GUI.

## Simulation jobs (the core loop)

1. **Pre-flight** (`vfp_sim.il`): `vfpSimPreflight(cv test)` — dirty-check refuses a
   cellview with unsaved changes (never sim a stale netlist); a content **fingerprint**
   (test + connectivity + params) keys the tunnel's freshness guard (reuse a done result).
2. `vfpRunSimJob(cv [?attended t] [?corner "Nominal"])` → `job.create` (cellview,
   fingerprint, `session_id`, `saved_at`) → `job.run`.
3. The **runner** runs the optional `VFP_NETLIST_CMD` (delegated netlist), then `VFP_SIM_CMD`
   (the wrapper), then merges `provenance` + `metric_quality` into the result (schema 0.2).
4. Wrapper `scripts/cellview_spectre_job.py` (reuse mode) sims the deck at the **convention
   path** and writes `{metrics, provenance, metric_quality}` (NaN never on the wire).

**Netlist — assemble the deck two ways (same `vfpNetlistCellView` in `vfp_netlist.il`):**
- **Attended (值守):** `vfpRunSimJob(cv ?attended t)` runs `maeCreateNetlistForCorner`
  in the user's **live** session — reuses its framework license.
- **Delegated (代管):** `VFP_NETLIST_CMD=scripts/delegated_netlist.py` → a pluggable
  **backend** (`VFP_DELEGATED_BACKEND`: `vcli` default = persistent headless Virtuoso;
  `command` = any server netlist cmd; `module:callable` = custom) → same `vfpNetlistCellView`.

Both write `$VFP_NETLIST_DIR/<lib>__<cell>__<view>/netlist/input.scs`; the wrapper derives
the same path from the cellview env, so there's no per-job plumbing.

## Key env (server-configured; never from an RPC client)

| var | meaning |
|---|---|
| `VFP_SIM_CMD` | the sim wrapper command (JSON array — preferred — or shlex string) |
| `VFP_NETLIST_CMD` | optional delegated netlist step the runner runs **before** the sim |
| `VFP_NETLIST_DIR` | deck base dir (plugin and wrapper share; default `/tmp/vfp_nl`) |
| `VFP_DELEGATED_BACKEND` | `vcli` (default) / `command` / `module:callable` |
| `VFP_VCLI_TARGET` | empty/`local`/`localhost` → run vcli directly; `user@host` → ssh |
| `VFP_HOME` / `VFP_PORT` | tunnel state dir / port (default `47891`) |

## Gotchas (hard-won)

- SKILL `if(cond then A else B)` keyword form is **fragile in argument position** and does
  not load under vcli's reader — use the 3-arg `if(cond A B)`. The netlist functions live in
  `vfp_netlist.il` (not `vfp_sim.il`) precisely so vcli can load them.
- **git-bash MSYS rewrites `/tmp`** in shell-set env vars to a Windows temp path → run
  server-path scripts via the **PowerShell** tool (or `MSYS_NO_PATHCONV=1`).
- `VFP_SIM_CMD`/`VFP_NETLIST_CMD`: pass a **JSON array** for paths with backslashes (POSIX
  shlex eats them — the old Windows test_runner failures).
- `maeOpenSetup` creates a `.cdslck` — always `maeCloseSession(?forceClose t)`.
- `asiGetCurrentSession` is **global** (last-active ADE window, not the current cellview).
- Tunnel transport pins UTF-8 on the wire + files (M13a); don't rely on the platform codepage.
- **Commits/PRs: clean human ownership, zero AI attribution** (no Co-authored-by / footers).

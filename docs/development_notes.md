# Development Notes

## Repository structure decision

**Monorepo** (both `skill/` and `tunnel/` in this repository), decided
2026-06-09.

Rationale: the SKILL plugin and the Python tunnel share one contract
(the JSON-RPC method set + the five schemas under `schemas/`). During the
MVP this contract changes frequently and must change atomically on both
sides — a monorepo makes that a single reviewed commit and keeps
end-to-end testing/demo to a single checkout.

The door to splitting `tunnel/` into its own repository later stays open:
`git subtree split` (or `git filter-repo`) extracts it with history
cheaply. Splitting first and merging later would be harder. The shared
`schemas/` directory is structured to become the split point's shared
dependency.

## Milestone status

| # | Milestone | Status |
|---|-----------|--------|
| 1 | Virtuoso plugin skeleton (menu, dashboard, lib/cell/view) | **done** |
| 2 | VFP Tunnel (CLI, JSON-RPC, session) + SKILL bridge | **done** (Virtuoso Connect button needs a manual GUI test) |
| 3 | Design context export | **done** (Virtuoso "Export Context" needs a GUI test) |
| 4 | Proposal workflow | not started |
| 5 | Transactional parameter modification + rollback | not started |
| 6 | Result + constraint display | not started |
| 7 | ADE/Spectre integration | not started |

## Milestone 1 — what's implemented

- `skill/vfp_utils.il` — runtime state (DPL), logging, cellview helpers.
- `skill/vfp_init.il` — `vfpLoad` / `vfpInit` / `vfpUnload` / `vfpGetVersion`.
- `skill/vfp_menu.il` — "Virtuoso Flow" menu; CIW + schematic install.
- `skill/vfp_dashboard.il` — dashboard form; live lib/cell/view.
- The remaining `skill/vfp_*.il` files are loadable stubs whose function
  signatures match their planned module API and log "not implemented yet".

## Milestone 2 — what's implemented (tunnel side)

Python daemon + `vfp` CLI, **stdlib-only and Python 3.6+** (the design
server runs CentOS 7 / 3.6.8, and the tunnel must run there so the
in-Virtuoso SKILL client can reach it on localhost).

- `tunnel/vfp_tunnel/rpc/jsonrpc.py` — JSON-RPC 2.0 dispatcher.
- `tunnel/vfp_tunnel/rpc/transport.py` — newline-framed JSON over TCP:
  threaded server + a small blocking client.
- `tunnel/vfp_tunnel/session/registry.py` — session registry (in-memory +
  JSON persistence under `.vfp/sessions/`).
- `tunnel/vfp_tunnel/daemon.py` — `Tunnel`: methods + lifecycle/state file.
  Methods: `session.register/ping/status/list/current`,
  `tunnel.status/shutdown`.
- `tunnel/vfp_tunnel/cli.py` — `vfp tunnel start|stop|status`,
  `vfp session list|current`, `vfp ping`.
- `scripts/vfp` — runs the CLI without installing (sets `PYTHONPATH`);
  the no-install path for the 3.6 server. `start_tunnel.sh`/`stop_tunnel.sh`
  wrap it.

Default endpoint `127.0.0.1:47891` (override via `--host/--port` or
`VFP_HOST/VFP_PORT`); artifact root `./.vfp` (override via `VFP_HOME`);
pending-proposal TTL `300s` (override via `VFP_PROPOSAL_TTL_S`, `0` = off).
`tunnel start` spawns the daemon detached (cross-platform: `start_new_session`
on POSIX, `DETACHED_PROCESS` on Windows) and polls `tunnel.status` until ready.

Verified at this milestone: `pytest tests/` (20 tests then) on Windows
3.14, plus a full CLI smoke test (start→status→register→ping→list→stop) on
**both** Windows 3.14 and the server's Python 3.6.8.

## Milestone 2b — SKILL ↔ tunnel bridge

Base SKILL has no raw TCP sockets and no JSON parser, so the plugin talks
to the tunnel through a helper, chosen for being the simplest reliable MVP
path (synchronous, no long-lived relay):

- `tunnel/vfp_tunnel/skillrpc.py` — runs one JSON-RPC call and prints the
  response as a **SKILL s-expression** (`(t <result>)` / `(nil <error>)`),
  so SKILL parses it with `read` (no JSON parser, no `evalstring`). For
  `session.register` it wraps flat `--param k=v` into a `client` object so
  SKILL never builds JSON. Resolves the endpoint from the daemon state file
  or the default `127.0.0.1:47891`.
- `skill/vfp_rpc_client.il` — `vfpRpcExec` shells out via `system()` (which
  returns the exit code; stdout is redirected to a temp file we then
  `read`). Public ops: `vfpConnect` (→ `session.register`, stores the
  session id), `vfpDisconnect`, `vfpPing`, `vfpTunnelStatus`, and a generic
  `vfpRpcCall`. It invokes the system python at an **absolute path**
  (`/usr/bin/python3`, override via `VFP_PYTHON`) with a **sanitized env**
  (`env -u PYTHONHOME LD_LIBRARY_PATH=`): inside Virtuoso, PATH/LD_LIBRARY_PATH
  point `python3` at Cadence's bundled interpreter
  (`.../tools.lnx86/python/64bit`), which otherwise fails with
  `undefined symbol: _Py_LegacyLocaleDetected`.
- `skill/vfp_dashboard.il` — connection field now shows `Connected (s_…)`;
  `vfpDashboardSetResult` shows a one-line tunnel summary after connect.

Verified end-to-end on the server (3.6.8): the helper emits correct
s-expressions for `tunnel.status`, `session.register`, `session.ping`, a
method-not-found error, and an unreachable-tunnel error. **Not yet tested:**
clicking *Connect* inside Virtuoso (needs the GUI; the SKILL parsing path
is exercised only there).

To test in Virtuoso: on the server `scripts/vfp tunnel start` (binds
`47891`), then reload the plugin and click *Connect* — the helper falls
back to the default port, so it finds the tunnel even if Virtuoso's cwd
differs from the daemon's.

## Milestone 3 — design context export

Extract the current schematic's instances/params/connectivity and send it
to the tunnel as `design.context.update`.

- `skill/vfp_context.il` — `vfpExtractDesignContext` walks `cv~>instances`
  (name, master lib/cell/view, `instTerms`→net map, CDF params via
  `cdfGetInstCDF`), `cv~>nets`, `cv~>terminals`; `vfpExportDesignContext`
  writes the payload to a temp file and sends it via the helper.
- `skill/vfp_utils.il` — a minimal JSON **encoder** (`vfpToJson` + tagged
  `vfpJObj`/`vfpJArr` constructors, `vfpJsonEsc`, `vfpWriteFile`). SKILL has
  no JSON, but encoding is easy and the helper decodes; objects/arrays are
  tagged so object-vs-array-vs-null is unambiguous (booleans use
  `'true`/`'false`; `nil` is JSON null).
- `tunnel/vfp_tunnel/skillrpc.py` — new `--params-file` mode forwards a
  large JSON payload (the context is too big for flat `--param`).
- `tunnel/vfp_tunnel/design/context.py` + daemon methods
  `design.context.update` / `design.context.get`; stores
  `.vfp/contexts/latest_context.json` plus timestamped snapshots; validates
  against `schemas/context.schema.json` when `jsonschema` is installed.
- `tunnel/vfp_tunnel/cli.py` — `vfp context show|export|import`
  (`import --file` loads a context for testing without Virtuoso).

Verified: 28 pytest tests; the encoder algorithm emits JSON that conforms
to the context schema; CLI `context import`/`show` and the helper
`--params-file` path work against a live daemon on both Windows 3.14 and
the server's Python 3.6.8. **Not yet tested:** the in-Virtuoso "Export
Context" button (needs the GUI / a real schematic).

## SKILL implementation notes

- **Self-locating load.** `vfp_init.il` and `scripts/load_vfp.il` resolve
  their own directory via `get_filename(piport)` (the input port of the
  file being loaded), so module loading does not depend on Virtuoso's
  current working directory. Override with the global `VFP_SKILL_DIR` if
  needed.
- **Menu install.** Inserted into the CIW banner with `hiInsertBannerMenu`
  at a large index (append). For schematic windows a post-install trigger
  is registered via `deRegUserTriggers("schematic" nil nil 'fn)` — note
  the post-install trigger is the **4th** argument.
- **Menu removal.** `vfpUnregisterMenu` finds the menu's position with
  `hiGetBannerMenus` and deletes it via `hiDeleteBannerMenu`, per window.
- **Dashboard fields.** Read-only `hiCreateStringField`s for lib/cell/view
  and an `hiCreateMLTextField` for the result/constraint summary; values
  are refreshed by assigning `form->fieldSym->value`.
- **Cellview probing.** Use the `win->editCellView` *property* (quiet,
  nil for non-graphic windows) — not `geGetEditCellView(win)`, which
  emits a `GE-2067` warning when called on the CIW or a form window.
  `errset` does not suppress that warning because it is a warning, not an
  error.

## API reference

The Cadence SKILL reference for IC23.1 is bundled under
`docs/IC231_gui_plugin_docs/` (skuiref = UI, sklangref = language,
skdfref = design framework, etc.). Prefer it over guessing signatures.

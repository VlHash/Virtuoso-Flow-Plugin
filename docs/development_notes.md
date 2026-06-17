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
| 2 | VFP Tunnel (CLI, JSON-RPC, session) + SKILL bridge | **done** |
| 3 | Design context export | **done** |
| 4 | Proposal workflow | **done** |
| 5 | Transactional parameter modification + rollback | **done** |
| 6 | Result + constraint display | **done** |
| 7 | ADE/Spectre integration | **done** |
| 8 | Session identity: fingerprint dedup, heartbeat, reap, doctor | **done** |
| 9 | Sim job model + freshness guard + runner; netlist dirty-check + inputs fingerprint; real-spectre closed loop | **done** |
| 10 | Cellview-specific real-spectre wrapper + attended in-session netlist; result schema 0.2 (provenance + metric_quality + session) | **done** |
| 11 | Connectivity snapshot/diff, txn connectivity audit, auto-net risk + pin, TB lint + pre-apply checkpoint, parameter blame chain + batch apply + rollback picker | parts 1–5 **done** |
| — | **Delegated netlist + VFP Daemon**: pluggable delegated backend (`plugin`/vcli/command/callable), netlist over VFP's own tunnel↔plugin channel, VFP-managed headless `virtuoso -nograph` (`vfp daemon`), `plugin` default backend, delegated `saved_at` via a deck-dir sidecar | **done** |
| — | **Transaction audit**: `created_ts` (precise blame ordering) + `actor` / `session` / `session_fingerprint` bound at apply | **done** |
| 13a | Transport hardening: error taxonomy + UTF-8 audit | **done** |

Milestones verified live in Virtuoso IC23.1: M8 reconnect/heartbeat/reap
(2026-06-13); M11 P3–P5 + the M9 real-spectre closed loop on VNC
(2026-06-14/15); M10b cellview-specific real-spectre + attended in-session
netlist on Project/inv_tb (2026-06-15). M10 is complete: M10a (session_id),
M10b (cellview wrapper + attended netlist), M10c (saved_at) on the plugin side,
and the tunnel half F.1–F.3 (runner cellview pass-through, result schema 0.2
with provenance + metric_quality, session resolution). Since M10, the
**delegated netlist + VFP Daemon** and the **transaction audit** (both below)
shipped — both live-verified on Project/inv_tb. M12 (approval envelope +
experiment ledger) is collab-led and not yet started. The **layout side**
(below) is planned but not started.

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

## Milestone 8 — session identity (fingerprint, heartbeat, reap, doctor)

Make a session a stable identity so a plugin reload reuses its session
instead of piling up duplicates, and so dead sessions can be detected and
dropped. Split across the plugin (PR #21) and the tunnel (PR #23).

Plugin side (`skill/vfp_rpc_client.il`, `scripts/vfp_event_client.py`):

- `vfpProcessFingerprint()` — `pid` plus a kernel start-time token read
  from `/proc/self/stat`. The token is opaque, stable across plugin
  reloads, and distinguishes pid reuse (`""` off Linux).
- `vfpConnect()` registers a composite identity — `virtuoso_pid`,
  `virtuoso_start`, `display`, `cds_lib` alongside `host` — which the
  registry persists verbatim.
- **Heartbeat without timers.** `hiRegTimer` never fires in this build,
  so the event client's long-poll doubles as the liveness signal:
  `vfp_event_client.py` takes `--session-id` and attaches it to every
  `event.list` / `event.wait`. `vfpConnect` restarts the bridge so a
  reconnect's fresh session id reaches the client.

Tunnel side (`tunnel/vfp_tunnel/session/registry.py`, `daemon.py`,
`config.py`, `cli.py`):

- **Fingerprint dedup.** Identity is `(virtuoso_pid, virtuoso_start)`. A
  reload re-registering with the same fingerprint reuses the existing
  session (`reconnects++`); a different pid — or the same pid with a
  different start time — is a new session. Legacy clients (no
  fingerprint) are never deduped.
- **Heartbeat = the long-poll.** `event.list` / `event.wait` touch the
  caller's `session_id`. A live long-poll is the liveness proof; the
  bridge subprocess dies with Virtuoso, so its polling stops on death.
- **Stale reap.** `registry.reap(max_idle_s)` drops dead sessions, via
  the `session.reap` RPC and an opportunistic reap on register.
  `config.session_ttl_s()` reads `VFP_SESSION_TTL_S` (default `0` = off).
- **Observability.** `session.list` adds `idle_s`; new `vfp doctor`
  (tunnel up? sessions with fingerprint / display / idle, flags stale)
  and `vfp session reap` CLI commands.

## Milestone 11 — connectivity snapshot, diff, and transaction audit

Give VFP eyes on connectivity — the most expensive class of silent
schematic failures (a reshaped symbol detaching a wire; manual rewiring
renaming the auto nets automation depends on). Parts 1 (PR #22) and 2
(PR #25); `skill/vfp_connectivity.il` is loaded via `VFP_MODULES`.

Part 1 — snapshot + topology diff:

- `vfpSnapshotConnectivity(cv)` — instance-terminal → net mapping plus
  named / auto net classification (auto = `net<N>`).
- `vfpConnectivityDiff(a b)` — structural diff. Named nets compare by
  name; **auto nets compare by canonical member set**, because their
  names are not stable: deleting and redrawing a wire makes `schCheck`
  renumber (`net4` → `net1`) with the topology bit-for-bit identical. A
  param-only edit diffs nil; a broken wire reports every affected
  `inst.term` with its raw before/after nets.
- `vfpConnAutoRenames(a b)` — pure auto-net renames (same member set,
  new name) surfaced separately: the fragility signal for anything
  referencing those names.
- `vfpConnectivityJson(cv)` / `vfpConnSnapJ(snap)` — JSON forms for
  context export and transaction-record embedding;
  `vfpConnSnapFromJson(j)` rebuilds a snapshot from the stored JSON.
- `vfpInstTermPoint(inst term)` — sheet coordinates of a terminal's pin.

Part 2 — connectivity audit on apply / rollback (`skill/vfp_transaction.il`):

- **Apply** snapshots connectivity before/after the parameter writes and
  stores the verdict in the transaction record as a `connectivity` block
  — `{status: clean|changed, diff, before: <snapshot>}`. (The schema's
  top level has open `additionalProperties`, so existing readers are
  unaffected.) A parameter-only apply that moves any terminal logs the
  exact `inst.term` records and warns in the success dialog; the clean
  case appends `Connectivity: clean`.
- **Rollback** rebuilds the stored pre-apply snapshot and diffs it
  against the post-restore extraction: clean → `Connectivity restored:
  verified.`; divergence (a wire broken between apply and rollback) →
  a warning naming the affected terminals. Pre-M11 transactions without
  the block skip verification silently.

Interface point for the tunnel side: emit an event when
`transaction.create` arrives with `connectivity.status=changed`
(roadmap "Task Marked / Task Push"). The plugin already records
everything that piece needs.

## VFP Daemon — delegated netlist (Phase 1/2) + transaction audit

Two follow-ons after M10/M11, both live on Project/inv_tb.

**Delegated netlist + the VFP Daemon.** M10b's *attended* netlist reuses the
user's live session; the *delegated* path netlists without a GUI:

- `skill/vfp_netlist.il` — the netlist assembler (`vfpNetlistCellView` →
  `maeCreateNetlistForCorner`), split out of `vfp_sim.il` so it loads cleanly
  on its own (e.g. under a vcli reader). It also writes a `saved_at.txt`
  sidecar next to the deck, so the wrapper can stamp `provenance.saved_at` on
  the delegated path (where no `vfpRunSimJob` computed it; the env value still
  wins for attended jobs).
- `scripts/delegated_netlist.py` — a **pluggable backend** worker:
  `VFP_DELEGATED_BACKEND` selects `plugin` (default) / `vcli` / `command` /
  `module:callable`. The `plugin` backend netlists over VFP's **own**
  tunnel↔plugin channel: it posts a `netlist.request`, a connected plugin
  services it (`vfpServiceNetlistRequests` → `vfpNetlistCellView` →
  `netlist.complete`), and the worker polls `netlist.get` for the deck. No
  external netlister; it fast-fails with a clear message if no plugin is
  connected.
- **VFP Daemon** (`tunnel/vfp_tunnel/sim/virtuoso_daemon.py`, `vfp daemon`
  CLI) — a VFP-managed, supervised headless `virtuoso -nograph` that boots the
  plugin (`skill/vfp_daemon_boot.il`: minimal module load → `vfpConnect` →
  poll-service `netlist.request`), so the `plugin` backend runs **unattended**.
  `vfp daemon start|status|stop` spawns a detached supervisor + a state file.
  Launch it from a Cadence-sourced shell at the cds.lib dir; a clean working
  dir (empty `.cdsinit`) avoids pulling in a site vcli/RAMIC bridge.

**Transaction audit.** Closes the M11 blame-chain known debt: a transaction now
carries `created_ts` (epoch — orders same-second edits precisely) and binds
`actor` + the originating `session` / `session_fingerprint` at apply. Tunnel
side (collab): `transaction.create` resolves `params.session_id` to the durable
M8 fingerprint and stores `actor`; `manager.list` orders by `(created_ts,
timestamp)`. Plugin side: `vfpCreateTransaction` sends `session_id` + `actor`
(default `"user"`; an agent can set the `'actor` state to `"agent"`).
Remaining: rollback-actor + a full GUI apply→audited-txn VNC pass.

## Milestone 13a — error taxonomy + UTF-8 audit

Transport hardening (PR #24) so M9's job RPC has a stable, named error
taxonomy to branch on.

- `tunnel/vfp_tunnel/rpc/errors.py` is the single home for error codes.
  It re-exports the standard JSON-RPC codes and defines the application
  codes in the server-reserved range (`-32000..-32099`):
  `NOT_FOUND` `-32001`, `PERMISSION_DENIED` `-32002`, `INVALID_STATE`
  `-32003`, `CONFLICT` `-32004`, `STALE` `-32005`. Reserved (do not
  collide): `-32010..` session/connectivity, `-32020..` sim/job (M9),
  `-32030..` results. `message_for(code)` gives a short label for logs.
- The daemon imports `NOT_FOUND` / `PERMISSION_DENIED` from `errors` in
  place of ad-hoc `-32001` literals — **same wire values**, no behaviour
  change.
- **UTF-8.** Every `open` / `read_text` / `write_text` in `tunnel/`
  already passes `encoding="utf-8"` (and the wire is utf-8), so the
  Windows-GBK risk is closed; a non-ASCII round-trip test guards it.

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

## Layout-side roadmap (planned, not started)

VFP today is schematic-only. The layout side mirrors the schematic
architecture and reuses the same proposal / transaction / context
machinery. Phased by value vs. risk:

- **L1 — Layout context export** (read-only, low risk). `layout_read_summary`
  / `layout_read_geometry` → a layout block in the context payload: instance
  placement (bbox), layer usage, shape/via counts, routed nets. Lets the
  agent see the layout; reuses the context schema + store. The recommended
  starting point.
- **L2 — Layout geometry lint** (read-only analysis). Floating metal (shapes
  on no net), unconnected device pins, off-grid shapes — geometry-based, not
  a full DRC sign-off. The layout analogue of the testbench lint.
- **L3 — Layout ↔ schematic consistency** (the differentiator). Compare the
  layout's extracted nets against the schematic connectivity snapshot
  (`vfpSnapshotConnectivity`) — an LVS-lite the agent can read. Needs layout
  net extraction (geometry → net); medium complexity.
- **L4 — Layout-edit transactions** (read-write, highest risk). Agent-
  proposed routing / via / placement edits applied as reversible
  transactions (layout checkpoint + diff), gated on DRC. Last.

Split: the layout SKILL (read/write geometry) is ours; the tunnel
context/proposal/transaction stores are reused, with any schema extension
coordinated with collab.

## Keeping docs current

When a feature lands or a milestone closes, update the front-door docs in
the SAME change — this file's milestone table sat at M8 while M9 and M11
parts 3–5 shipped. Touch, as relevant: `README.md`, `docs/HANDOFF.md`, the
milestone table above, and `docs/plugin_usage.md` (any new menu item or
command the user invokes). The gitignored `AGENTS.md` / `TODO.md` are live
scratch; the committed docs here are the front door.

# Virtuoso Flow Plugin — Usage

## Requirements

- Cadence Virtuoso (developed against the IC23.1 SKILL API).
- VFP Tunnel running (see the [tunnel README](../tunnel/README.md)) for
  Connect / Export Context.

## Loading

In the Virtuoso **CIW**, either run the one-shot loader:

```lisp
load("/path/to/Virtuoso-Flow-Plugin/scripts/load_vfp.il")
```

or load the entry point and initialize manually:

```lisp
load("/path/to/Virtuoso-Flow-Plugin/skill/vfp_init.il")
vfpInit()
```

> Use forward slashes in SKILL paths, even on Windows.

### What you should see

- The CIW prints:
  `[VFP ...] Virtuoso Flow Plugin 0.1.0 initialized. Menu: "Virtuoso Flow".`
- A **Virtuoso Flow** pulldown menu appears in the CIW banner (and in any
  schematic window you open afterwards).
- `Virtuoso Flow → Open Dashboard` opens a panel showing:
  - VFP Tunnel connection status,
  - the current library / cell / view,
  - placeholders for ADE test and latest result,
  - **Connect / Export / Refresh / Rollback / Proposals / Review / Apply**
    buttons.

Open a schematic, then click **Refresh** on the dashboard — the
lib/cell/view fields update to the schematic you are editing.

## Connect and export context

With the tunnel running:

1. Click **Connect** — registers the Virtuoso session; the status field
   shows `Connected (s_…)` and a one-line tunnel summary.
2. With a schematic open, click **Export** — sends the schematic's
   instances, parameters, and connectivity to the tunnel. Verify on the
   tunnel host with `scripts/vfp context show`.

## Proposals, transactions, and results

With the tunnel running and an agent (or `scripts/vfp proposal create`)
submitting proposals:

- **Show Pending Proposals** lists the pending proposals in the dashboard
  result area.
- **Review Pending Proposal** (menu, or the dashboard **Review** button)
  opens the review form on the first pending proposal, with **Approve /
  Reject / Apply** buttons; each closes the form once it succeeds.
- **Apply Approved Proposal** (menu, or the dashboard **Apply** button)
  applies the first *approved* proposal: it writes the instance
  parameter(s) to the open schematic and records a reversible
  transaction. The usual loop is Review → Approve (form closes) → Apply.
- **Rollback Last Transaction** restores the most recent applied change.
  Apply and rollback now run a **connectivity audit**: apply records a
  before/after connectivity snapshot in the transaction and warns if a
  parameter write moved any terminal (otherwise the dialog shows
  `Connectivity: clean`); rollback re-diffs the restored schematic
  against the stored snapshot and reports `Connectivity restored:
  verified.` or names any terminals that diverged.
- Importing a simulation result (`scripts/vfp result import ...`) and
  clicking **Refresh** renders the metrics and per-constraint pass/fail
  verdict in the dashboard.
- A pending proposal that is never approved is auto-expired tunnel-side
  after `VFP_PROPOSAL_TTL_S` seconds (default 300).

## Run a simulation job

With the tunnel running and a sim runner configured server-side
(`VFP_SIM_CMD` points at a wrapper such as `scripts/cellview_spectre_job.py`),
the **Run Sim Job** menu item — or `vfpRunSimJob(cv)` — pre-flights and runs a
simulation of the current cellview:

- **Pre-flight** refuses a cellview with unsaved changes (it names the cellview
  and asks you to save first), so a sim never runs on a stale netlist. It also
  computes a content **fingerprint** (test + connectivity + parameters); the
  tunnel's freshness guard reuses a prior *done* job for identical inputs
  instead of re-simulating.
- The result carries **provenance** — which cellview the metrics came from, the
  `netlist_hash`, and the netlist source — plus `metric_quality` for
  non-finite/sentinel metrics, so a NaN never crosses as a bare number.

### Attended (in-session) netlist — M10b

`vfpRunSimJob(cv ?attended t)` assembles a *fresh, complete* spectre deck
before running, by triggering `maeCreateNetlistForCorner` inside your live
Virtuoso session via `vfpNetlistCellView(cv)`. This **reuses the running
session's framework license** (no separate `si` / headless-Virtuoso checkout)
and produces a runnable deck (design + PDK models + analyses + options) that a
plain `si` netlist cannot.

The deck is written under `<VFP_NETLIST_DIR>/<lib>__<cell>__<view>/netlist/`
(default base `/tmp/vfp_nl`); the headless wrapper derives the same path from
the job's cellview, so no per-job wiring is needed — set `VFP_NETLIST_DIR` to
the same value for the plugin and the runner. `vfpNetlistCellView(cv ?corner
"Nominal")` can also be called on its own to assemble a deck and return its
path.

## Auto-refresh (event bridge)

After **Connect**, the plugin starts `scripts/vfp_event_client.py` as a
background child of Virtuoso. The helper long-polls the tunnel for
events (`event.wait`, falling back to `event.list`) and streams them to
the plugin, which refreshes the dashboard (and the pending-proposal
list on `proposal.*` events) automatically — no manual **Refresh**
needed. If the tunnel does not provide event RPCs yet, the helper exits
quietly and everything else keeps working. `vfpEventBridgeStart()` /
`vfpEventBridgeStop()` control it manually; it is stopped by
Disconnect and `vfpUnload()`.

The event client also passes the current `--session-id` on every poll,
which doubles as the session **heartbeat** (timers do not fire in this
Virtuoso build, so the long-poll itself is the liveness signal). On
**Connect**, `vfpConnect()` registers a process fingerprint
(`virtuoso_pid` + a kernel start-time token) so a plugin reload reuses
its existing tunnel session instead of creating a duplicate. Use
`scripts/vfp doctor` on the tunnel host to see live sessions, their
idle time, and any that have gone stale, and `scripts/vfp session reap`
to drop dead ones.

## Status

Milestones 1–8, 11 (parts 1–2), and 13a are implemented and covered by
the test suite. The proposal apply → rollback flow (with connectivity
audit), the result/constraint dashboard, and the M8 session
fingerprint / heartbeat / reap path have been verified live in Virtuoso
IC23.1. See
[`development_notes.md`](development_notes.md) for the roadmap and the
proposal/transaction lifecycle.

## Unloading

```lisp
vfpUnload()
```

Removes the menu (from the CIW and schematic windows) and closes the
dashboard.

## Useful entry points

| SKILL | Effect |
|-------|--------|
| `vfpInit()` | Load modules, init state, install menu. |
| `vfpOpenDashboard()` | Open / raise the dashboard. |
| `vfpUpdateDashboard()` | Refresh dashboard fields from the current window. |
| `vfpConnect()` | Register the Virtuoso session with VFP Tunnel. |
| `vfpExportDesignContext()` | Send the current schematic context to the tunnel. |
| `vfpRunSimJob(cv [?attended t])` | Pre-flight + run a sim job; `?attended` assembles a fresh deck in-session first. |
| `vfpNetlistCellView(cv [?corner "Nominal"])` | Assemble a complete deck via the live maestro session; return its path. |
| `vfpEventBridgeStart()` / `vfpEventBridgeStop()` | Start / stop the tunnel event bridge. |
| `vfpUnload()` | Stop the event bridge, remove menu, close dashboard. |
| `vfpGetVersion()` | Plugin version string. |

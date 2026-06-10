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
  - **Connect / Export / Refresh / Rollback** buttons.

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
  result area. `vfpShowProposal` opens a review form with **Approve /
  Reject / Apply** buttons; each closes the form once it succeeds. Applying
  an approved proposal writes the instance parameter(s) to the open
  schematic and records a reversible transaction.
- **Rollback Last Transaction** restores the most recent applied change.
- Importing a simulation result (`scripts/vfp result import ...`) and
  clicking **Refresh** renders the metrics and per-constraint pass/fail
  verdict in the dashboard.
- A pending proposal that is never approved is auto-expired tunnel-side
  after `VFP_PROPOSAL_TTL_S` seconds (default 300).

## Status

Milestones 1–7 are implemented and covered by the test suite (89 passing).
The proposal apply → rollback flow and the result/constraint dashboard
have been verified live in Virtuoso IC23.1. See
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
| `vfpUnload()` | Remove menu and close dashboard. |
| `vfpGetVersion()` | Plugin version string. |

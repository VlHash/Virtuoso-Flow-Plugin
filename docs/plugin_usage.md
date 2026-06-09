# Virtuoso Flow Plugin — Usage

## Requirements

- Cadence Virtuoso (developed against the IC23.1 SKILL API; see the
  bundled reference under `docs/IC231_gui_plugin_docs/`).

## Loading (Milestone 1)

In the Virtuoso **CIW**, either run the one-shot loader:

```lisp
load("F:/VBL/Virtuoso-Flow-Plugin/scripts/load_vfp.il")
```

or load the entry point and initialize manually:

```lisp
load("F:/VBL/Virtuoso-Flow-Plugin/skill/vfp_init.il")
vfpInit()
```

> Use forward slashes in SKILL paths, even on Windows.

### What you should see

- The CIW prints:
  `[VFP ...] Virtuoso Flow Plugin 0.1.0 initialized. Menu: "Virtuoso Flow".`
- A **Virtuoso Flow** pulldown menu appears in the CIW banner (and in any
  schematic window you open afterwards).
- `Virtuoso Flow → Open Dashboard` opens a panel showing:
  - VFP Tunnel connection status (currently always *Disconnected*),
  - the current library / cell / view,
  - placeholders for ADE test and latest result,
  - **Connect / Export / Refresh / Rollback** buttons.

Open a schematic, then click **Refresh** on the dashboard — the
lib/cell/view fields update to the schematic you are editing.

## Status

Milestone 1 (plugin skeleton: menu + dashboard + lib/cell/view) is
implemented. Menu items and buttons for Connect, Export, Proposals,
Apply, Rollback, and Run Test currently log a "not implemented yet"
message; they are wired up in later milestones. See
[`development_notes.md`](development_notes.md) for the roadmap.

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
| `vfpUnload()` | Remove menu and close dashboard. |
| `vfpGetVersion()` | Plugin version string. |

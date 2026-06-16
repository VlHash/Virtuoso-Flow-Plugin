# VFP Architecture

A code/text view of the whole system, including parts not yet built — the goal
is to see the shape of it. Two halves share the `schemas/` JSON contract: the
**plugin** (in Virtuoso, SKILL) owns design state and the netlist; the **tunnel**
(stdlib Python daemon) owns the agent interface, jobs, results, and history.

```
══════════════════════════════════════════════════════════════════════════════
 DRIVERS
   AI agent (MCP)   ·   CLI: scripts/vfp   ·   designer @ Virtuoso GUI
══════════════════════════════════════════════════════════════════════════════
        │  JSON-RPC over TCP  (UTF-8 wire, newline-delimited)
        ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ VFP TUNNEL — daemon (stdlib Python)            transport ─ dispatcher        │
│                                                                              │
│  session registry      proposal / transaction      SIM                      │
│   fingerprint dedup      review → approve            job store               │
│   heartbeat / reap       → apply → rollback          freshness guard (==fp)  │
│   doctor                 connectivity audit          RUNNER                  │
│                          pre-apply checkpoint          ├─ netlist step       │
│  context store           param blame chain             │   (VFP_NETLIST_CMD) │
│  constraint engine       batch apply                   └─ sim step           │
│  run / artifact store                                      (VFP_SIM_CMD)     │
│                                                                              │
│  netlist-request store ──┐        result store: metrics + provenance         │
│  event bus (log + long-poll) ◄─┐    (cellview, netlist_hash, saved_at,        │
│  envelope policy · ledger ·    │     session, source_mode) + metric_quality   │
│  experiment ledger (M12)       │     — schema 0.2                             │
└────────────────────────────────┼─────────────────────────────────────────────┘
   ▲ skillrpc (plugin→tunnel)    │ event bridge (tunnel→plugin, long-poll)
   │                             ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ VFP PLUGIN — in Virtuoso (SKILL)                                             │
│   menu + dashboard      ·   design-context export                            │
│   sim preflight  (dirty-check + inputs fingerprint)                          │
│   proposal review · transaction apply/rollback (connectivity, checkpoint)    │
│   event client → services netlist.request · refreshes dashboard              │
│   NETLIST ASSEMBLER:  vfpNetlistCellView ──► maeCreateNetlistForCorner        │
│                       vfpCvSavedAt (provenance.saved_at)                      │
└────────────────────────────────────────────────────────────────────────────┘

──────────────────────────────────────────────────────────────────────────────
 DECK ASSEMBLY  (a complete spectre deck for a cellview)   — pluggable backend
──────────────────────────────────────────────────────────────────────────────
   attended (zhishou)   the plugin in the user's LIVE Virtuoso session
   delegated (daiguan)  scripts/delegated_netlist.py ──backend──►
                          plugin  ── netlist.request / netlist.complete (own channel)
                          vcli    ── persistent headless Virtuoso over vcli
                          command ── any server netlister (OCEAN / direct-spectre)
                          module:callable ── custom
   VFP Daemon          a VFP-managed persistent  `virtuoso -nograph` + plugin
        │
        ▼  deck written to the CONVENTION PATH
           $VFP_NETLIST_DIR/<lib>__<cell>__<view>/netlist/input.scs
        ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ SIM WRAPPER — scripts/cellview_spectre_job.py  (VFP_SIM_CMD)                 │
│   reads cellview (VFP_JOB_* env) → reuse deck → SPECTRE → parse PSF          │
│   → metrics + provenance + metric_quality  (NaN never on the wire)          │
└────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
──────────────────────────────────────────────────────────────────────────────
 CADENCE     Virtuoso (Maestro/ADE · maeCreateNetlistForCorner)  ·  Spectre  ·  PDK
 CONTRACT    schemas/ :  job · result · proposal · transaction · constraint · context
 AGENT SKILL .claude/skills/vfp/  (sim jobs · netlist · channels · gotchas)
──────────────────────────────────────────────────────────────────────────────
```

## How to read it

- **Drivers → Tunnel.** Everything reaches the tunnel over JSON-RPC; the wire is
  pinned UTF-8 so a host's codepage never corrupts the protocol.
- **Tunnel = the broker.** It holds all durable state (sessions, proposals,
  transactions, results, runs, jobs) and orchestrates simulation: the **runner**
  runs an optional netlist step then the sim wrapper, and merges
  `provenance` + `metric_quality` into a schema-0.2 result.
- **Tunnel ↔ Plugin** is VFP's own bidirectional channel: the plugin calls the
  tunnel (skillrpc) and the tunnel pushes events the plugin long-polls. The
  tunnel asks the plugin for **specific operations** (e.g. netlist a cellview),
  never arbitrary SKILL.
- **Deck assembly is pluggable.** A complete spectre deck (design + PDK models +
  analyses + options) comes from the ADE/maestro netlister. It can be assembled
  by the plugin in the user's live session (attended), by a delegated backend
  (the plugin over our own channel, vcli, an OCEAN/direct-spectre command, or a
  custom callable), or by a VFP-managed headless Virtuoso. Every path writes the
  deck to the same **convention path**, so the wrapper finds it with no per-job
  plumbing.
- **Wrapper → result.** The headless wrapper sims the deck and emits
  metrics + provenance + metric_quality; the tunnel stores it as the result.
- **Schemas** are the shared contract both halves validate against.

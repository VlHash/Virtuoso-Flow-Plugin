# L3 — Layout ↔ Schematic Consistency (LVS-lite) — plan

The differentiator of the layout phase: a cheap, agent-readable check that the
**layout's connectivity matches the schematic's** — an *LVS-lite*, not a sign-off
LVS. Builds on L1 (layout read) and reuses the schematic connectivity snapshot
(`vfpSnapshotConnectivity`, M11). L4 (layout-edit transactions) follows.

## Scope (first increment)

For a cell that has both a `schematic` and a `layout`, compare:
- **devices** present in each (matched by instance name), and
- **per-terminal connectivity** — is each device terminal wired to the same
  net-group in the layout as in the schematic.

Surface the mismatches as an `lvs` block in the context (agent-readable). This is
a *connectivity* consistency check, **not** a geometry/DRC LVS.

## Key insight: most layouts are connectivity-driven

From the L1/L2 probes, `Project/inv` layout is **connectivity-driven** — its
shapes and `instTerm`s already carry nets (`shape~>net`, `it~>net`). So for the
common modern case we **read the layout's connectivity directly** (the same way
`vfpSnapshotConnectivity` reads the schematic) — **no geometry net extraction**.

Raw drawn layouts with no connectivity (geometry → net by shape overlap) are
**deferred** — much harder, a separate increment.

## Approach

1. `vfpLayoutSnapshotConnectivity(cv)` — the layout analogue of
   `vfpSnapshotConnectivity`: walk layout instances' `instTerm`s →
   `it~>net~>name`, plus the layout's nets → `{net → {inst.term}}`.
2. Reuse `vfpSnapshotConnectivity(schematicCv)` for the schematic side.
3. `vfpLayoutVsSchematic(layoutCv schematicCv)` — diff the two by **net
   membership** (reusing M11's canonical-member-set idea, since net *names*
   differ between schematic and layout):
   - **device set:** instances only-in-layout / only-in-schematic (by name);
   - **net consistency:** for each `inst.term` present in both, compare its
     net-group (the set of co-connected `inst.term`s) — mismatch if different.
4. Emit an `lvs` block; ride the context like L1/L2's blocks.

## Split

| Piece | Owner | What |
|---|---|---|
| `vfpLayoutSnapshotConnectivity` + `vfpLayoutVsSchematic` (`vfp_layout.il`) | SKILL (ours) | read layout connectivity + diff vs the schematic snapshot |
| `lvs` block in `context.schema.json` | coordinate w/ collab | additive, optional (mirrors how L1's `layout` landed) |
| context store | tunnel (collab, reused) | carries it; no new RPC |

## Result shape (propose to collab)

```json
"lvs": {
  "schematic": { "$ref": "#/$defs/cellview" },
  "status": "clean | issues",
  "devices": {
    "matched": 0,
    "only_in_layout":    [ "<instName>" ],
    "only_in_schematic": [ "<instName>" ]
  },
  "net_mismatches": [
    { "inst_term": "M0.G",
      "schematic_group": [ "M0.G", "M1.G" ],
      "layout_group":    [ "M0.G" ] }
  ]
}
```
Loose, optional, additive — like the `layout` block. (Placement — a top-level
`lvs` field vs nested under `layout` — is collab's call; top-level mirrors the
schematic `connectivity`.)

## Verification

- Live (Virtuoso IC23.1): `Project/inv` schematic vs layout — expect **clean**
  (matched devices, consistent net-groups). A deliberately mis-wired scratch
  layout would surface a `net_mismatch`.
- Python: schema validation of a sample `lvs` block.

## Open questions / limitations (first increment)

1. **Device-name correspondence.** We match layout↔schematic devices by instance
   name. If the layout names differ (not derived from the schematic), topological
   / master-based device matching is needed — LVS-grade, **deferred**.
2. **Connectivity-driven only.** Raw drawn layouts (no `instTerm` / `shape` nets)
   need geometry net extraction — **deferred** to a later increment.
3. **Hierarchy.** First increment is flat (top-level `instTerm`s). Hierarchical
   LVS (descending into subcells) is later.
4. **Net-group canonicalization** reuses M11's auto-net member-set comparison;
   confirm it generalizes to layout nets.

## Beyond L3

- **L4** — layout-edit transactions (agent-proposed routing / via / placement
  edits applied as reversible transactions, gated on DRC). Highest risk; last.

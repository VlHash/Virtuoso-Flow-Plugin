# L1 — Layout Context Export (plan + field conventions)

The first step of the VFP **layout phase**: let an agent *see* the layout,
read-only, reusing the existing context schema + store. No design writes — the
safe entry point. (L2 geometry lint → L3 layout↔schematic LVS-lite → L4
layout-edit transactions follow.)

## Scope

Read a `layout` cellview and emit a `layout` block in the design-context
payload: cell bbox, instance placement, per-layer shape counts, via count.
Read-only; reuses the proposal/transaction/context machinery (extended later).

## Split

| Piece | Owner | What |
|---|---|---|
| `skill/vfp_layout.il` | SKILL (plugin) | open the layout cellview, read it, build the `layout` JSON block |
| `schemas/context.schema.json` | shared (coordinate) | additive, **optional** `layout` block — existing readers unaffected |
| context store / `design.context.update` | tunnel (reused) | already carries the payload; **no new RPC**; `vfp context show` surfaces it |

## SKILL approach

- `cv = dbOpenCellViewByType(lib cell "layout")`; cell extent `cv~>bBox`.
- **Placement** — `cv~>instances`: master (`inst~>libName/cellName/viewName`),
  `inst~>xy` (origin), `inst~>orient`, `inst~>bBox`.
- **Layer usage** — `cv~>shapes`: bucket by `shape~>layerName` + `shape~>purpose`
  (counts).
- **Vias** — `cv~>vias` (count).
- `vfpExtractLayoutContext(cv)` assembles the block with `vfpJObj`/`vfpJArr`;
  `vfpExtractDesignContext` adds it when the current view is a layout.

## Field-name conventions (owner decisions, 2026-06-17)

Coordinates are numbers in **user units (µm)**; include a `units` field so the
agent isn't guessing scale.

| Field | Form | Rationale |
|---|---|---|
| `bbox` | nested `[[x0,y0],[x1,y1]]` (LL, UR) | direct map of Cadence `bBox` (two points); reuses one `point` def shared with `origin`. Flat-4 loses corner semantics. |
| `vias` | single integer (count) | L1 is a *summary*; per-via position/type belongs in **L3** |
| `origin` | `[x,y]` (a `point`) | same primitive as bbox corners |
| `orient` | string (`"R0"`/`"MX"`/`"R90"`…) | `inst~>orient` is a symbol → string |
| `master` | string `"lib/cell/view"` | matches the connectivity-snapshot convention (`"analogLib/res/symbol"`) |
| `layers` | `[{layer, purpose, shapes:<int>}]` | list-of-objects, matches schematic-context style |
| schema strictness | **loose** (no `additionalProperties:false`) | consistent with the rest of the project; don't special-case `layout` |

### Schema block (to land in `schemas/context.schema.json`)

```json
"point": { "type":"array","items":{"type":"number"},"minItems":2,"maxItems":2 },
"bbox":  { "type":"array","items":{"$ref":"#/$defs/point"},"minItems":2,"maxItems":2 },

"layout": { "type":"object","properties":{
  "cellview":{"$ref":"#/$defs/cellview"}, "bbox":{"$ref":"#/$defs/bbox"}, "units":{"type":"string"},
  "instances":{"type":"array","items":{"type":"object","properties":{
    "name":{"type":"string"},"master":{"type":"string"},
    "origin":{"$ref":"#/$defs/point"},"orient":{"type":"string"},"bbox":{"$ref":"#/$defs/bbox"}}}},
  "layers":{"type":"array","items":{"type":"object","properties":{
    "layer":{"type":"string"},"purpose":{"type":"string"},"shapes":{"type":"integer"}}}},
  "vias":{"type":"integer"} }}
```

## Verification

- Python: schema validation of a sample `layout` context; `vfp context show`
  round-trip.
- Live (Virtuoso IC23.1): extract a real **layout** cellview (TBD which — the
  owner has layout designs; inv/gates are schematic-only) and confirm the block.

## Status

L1 implemented by collab (244 tests green, no regressions, `layout` optional);
held pending these field-name conventions before the PR. Once finalized:
our-side review + the live check.

## Beyond L1

- **L2** — layout geometry lint (floating metal, unconnected pins, off-grid).
- **L3** — layout↔schematic consistency (extracted layout nets vs
  `vfpSnapshotConnectivity`) — an LVS-lite the agent can read.
- **L4** — layout-edit transactions (routing/via/placement edits as reversible
  transactions, gated on DRC). Highest risk; last.

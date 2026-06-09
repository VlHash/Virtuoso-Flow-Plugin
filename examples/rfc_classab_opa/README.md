# Example: RFC Class-AB Op-Amp (`RFCOPA/XOPA`)

A minimal end-to-end example used to exercise the VFP MVP loop. It does
not depend on a real PDK — the JSON/YAML files are illustrative fixtures
that match the schemas in [`project.md`](../../project.md) §10.

## Files

| File | Purpose |
|------|---------|
| `sample_context.json` | Design-context fixture (what the plugin exports). |
| `sample_proposal.json` | Agent proposal: reduce Miller cap `C0` and zero-nulling `RZC0`. |
| `constraints.yaml` | Metric limits, DC-op saturation checks, and modify permissions. |

## Intended demo flow (once milestones land)

```bash
# Milestone 2+: tunnel running
vfp tunnel start

# Milestone 4: submit the proposal
vfp proposal create --file examples/rfc_classab_opa/sample_proposal.json
vfp proposal list
```

Then, inside Virtuoso, the dashboard shows the pending proposal; approving
it applies the parameter changes as a transaction (Milestone 5), and a
result can be ingested and checked against `constraints.yaml` (Milestone 6).

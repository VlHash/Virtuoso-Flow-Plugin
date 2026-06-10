# VFP Tunnel

External bridge daemon for the [Virtuoso Flow Plugin](../README.md). It
exposes a localhost JSON-RPC API (default `127.0.0.1:47891`) and a `vfp`
CLI to AI agents and scripts, and manages sessions, proposals,
transactions, simulation results, constraints, and artifacts.

**Status:** Milestones 2–7 implemented — sessions, design context,
proposals, transactions, results, constraints, and ADE run/artifact
tracking. Pure stdlib, runs on Python **3.6+** (the design server's
system python).

## Run

On the design server (no install needed — Python 3.6):

```bash
scripts/vfp tunnel start
scripts/vfp tunnel status
scripts/vfp session list
scripts/vfp tunnel stop
```

On a dev machine with Python 3.7+ you can also install it:

```bash
cd tunnel
pip install -e .[dev]
vfp tunnel start
```

Configuration via environment: `VFP_HOST`, `VFP_PORT`, `VFP_HOME`
(artifact root, default `./.vfp`), and `VFP_PROPOSAL_TTL_S` (seconds a
pending proposal lives before it is auto-expired; default `300`, `0` =
disabled).

## JSON-RPC methods

| Method | Result |
|--------|--------|
| `session.register` | `{session_id, registered_at}` from `{client}` |
| `session.ping` | `{pong, time, session_id}` (touches the session) |
| `session.status` / `session.list` / `session.current` | session records |
| `design.context.update` / `design.context.get` | store / fetch the latest design context |
| `proposal.create` / `list` / `get` | design-change proposals (stale pendings auto-expire) |
| `proposal.approve` / `reject` / `mark_applied` / `mark_failed` | proposal state machine |
| `transaction.create` / `list` / `get` | reversible before/after parameter changes |
| `transaction.rollback` / `mark_rolled_back` / `mark_failed` | undo an applied change |
| `result.update` / `result.latest` | store / fetch simulation metrics |
| `constraint.check` | evaluate metrics against limits → per-metric pass/fail |
| `run.create` / `list` / `get` / `set_status` / `attach` / `import_result` | ADE run + artifact tracking |
| `tunnel.status` / `tunnel.shutdown` | daemon status / graceful stop |

Messages are JSON-RPC 2.0, one object per line (`\n`-framed) over TCP.

## Layout

```
vfp_tunnel/
  cli.py daemon.py config.py logging_config.py skillrpc.py
  rpc/{jsonrpc,transport,schemas}.py
  session/{registry,manager}.py
  design/context.py
  proposal/ transaction/ sim/ constraints/ artifact/ agent/
```

See [`../schemas/`](../schemas) for the data contract.

## Tests

```bash
cd ..            # repo root
pytest tests/    # 89 passing, 5 skipped (skips need optional jsonschema)
```

# VFP Tunnel

External bridge daemon for the [Virtuoso Flow Plugin](../README.md). It
exposes a localhost JSON-RPC API (default `127.0.0.1:47891`) and a `vfp`
CLI to AI agents and scripts, and manages sessions, proposals,
transactions, simulation results, constraints, and artifacts.

**Status:** Milestones 2–8, 11, and 13a implemented — sessions (with
fingerprint dedup, heartbeat, reap, and `doctor`), design context,
proposals, transactions (with connectivity audit), results, constraints,
ADE run/artifact tracking, and a named error taxonomy. Pure stdlib, runs
on Python **3.6+** (the design server's system python).

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
(artifact root, default `./.vfp`), `VFP_PROPOSAL_TTL_S` (seconds a
pending proposal lives before it is auto-expired; default `300`, `0` =
disabled), and `VFP_SESSION_TTL_S` (seconds an idle session lives before
it is auto-reaped; default `0` = disabled).

Diagnose health and clean up dead sessions:

```bash
scripts/vfp doctor              # tunnel up? sessions, idle time, stale flags
scripts/vfp session reap        # drop idle (dead) sessions now
```

## JSON-RPC methods

| Method | Result |
|--------|--------|
| `session.register` | `{session_id, registered_at}` from `{client}` (dedups on `(virtuoso_pid, virtuoso_start)` fingerprint → `reconnects++`) |
| `session.ping` | `{pong, time, session_id}` (touches the session) |
| `session.status` / `session.list` / `session.current` | session records (`list` includes `idle_s`) |
| `session.reap` | drop sessions idle longer than `max_idle_s` → `{count}` |
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

The event long-poll (`event.list` / `event.wait`) carries the caller's
`session_id` and **touches** it, so a live poll doubles as the session
heartbeat — no separate ping loop is needed.

## Error taxonomy

`rpc/errors.py` is the single source of truth for error codes. It
re-exports the standard JSON-RPC 2.0 codes and defines the application
codes in the server-reserved range (`-32000..-32099`), which clients
branch on, so the values are stable:

| Code | Name | Meaning |
|------|------|---------|
| `-32001` | `NOT_FOUND` | unknown id (proposal/transaction/run/session) |
| `-32002` | `PERMISSION_DENIED` | modify blocked by allow/deny policy |
| `-32003` | `INVALID_STATE` | illegal state transition / precondition unmet |
| `-32004` | `CONFLICT` | duplicate id / already exists |
| `-32005` | `STALE` | data is out of date (freshness guard) |

Ranges `-32010..` (session/connectivity), `-32020..` (sim/job, M9), and
`-32030..` (results) are reserved for forthcoming subsystems.
`message_for(code)` returns a short label for logs.

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
pytest tests/    # 134 passing, 1 skipped (3.14); 129 passing, 6 skipped (3.6.8)
```

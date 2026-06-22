# VFP Extension API

The Extension API turns VFP into an **extensible execution end**: a generic way
for an external controller — a CLI, an MCP/LLM client, or any other process — to
**discover** capabilities and **invoke** them through the tunnel, without the
tunnel knowing the capability in advance.

It is deliberately neutral. VFP ships the *mechanism*; the *capabilities* and any
design-intent logic live in whatever connects to it. Nothing here is tied to a
particular consumer — any number of independent clients (or LLMs) can drive the
same tunnel.

## Model

```
   client (CLI / MCP / LLM / other)            servicer (the plugin, or a worker)
        │                                              │
        │  action.request(namespace, method, params)   │
        ├──────────────────────────────────▶ tunnel ──┤  ◀── extension.register(namespace, methods)
        │  ◀── action_id (pending)                     │
        │                              event: action.request
        │                                              │  pulls action.pending(namespace)
        │                                              │  runs it under its OWN gating
        │  action.get(action_id)                       │  action.complete(action_id, result|error)
        ├──────────────────────────────────▶ tunnel ◀─┤
        │  ◀── {status: done, result}                  │
```

Two roles, both optional and pluggable:

- A **servicer** announces a namespace it can serve (`extension.register`) and
  then services requests for it (`action.pending` → run → `action.complete`).
  The in-Virtuoso plugin is one servicer; a standalone worker could be another.
- A **client** discovers namespaces (`extension.list`) and invokes methods
  (`action.request` → poll `action.get`).

**The tunnel is pure transport — it never executes an action itself.** It routes
the request to whoever registered the namespace; that servicer decides whether
and how to run it. This keeps the trust boundary clear: a client cannot make the
tunnel run code, and a servicer applies its own gating (for example, the plugin
turns a layout edit into a reversible, auditable transaction rather than running
it blind).

## RPC methods

| Method | Role | Purpose |
|---|---|---|
| `extension.register` | servicer | Announce a `namespace`, its `methods[]`, and a `description`. Idempotent (re-announce on reconnect). |
| `extension.unregister` | servicer | Withdraw a namespace. |
| `extension.list` | client | Discover registered namespaces + methods + descriptions. |
| `action.request` | client | Enqueue `{namespace, method, params}`; returns `{action_id, status, serviced}`. `serviced=false` ⇒ no servicer registered that namespace yet. |
| `action.pending` | servicer | Pull pending actions, optionally filtered to one `namespace`. |
| `action.complete` | servicer | Post `{action_id, result}` or `{action_id, error}`. |
| `action.get` | client | Fetch an action record: `status` (pending/done/failed) + `result`/`error`. |

An `action.request` emits an `action.request` **event**, so a servicer using the
event stream (e.g. the plugin's event bridge) wakes immediately instead of
polling. `action.complete` emits `action.complete`.

## MCP tools (for an LLM client)

The MCP server exposes three generic tools so any LLM can drive the loop:

- `extension_list()` — what capabilities are available right now.
- `action_request(namespace, method, params)` — invoke one; returns an
  `action_id`.
- `action_get(action_id)` — poll for the outcome.

These compose with the existing MCP tools (`context_get`, `proposal_create`,
`constraint_check`, `events`, …). An LLM that knows nothing about a specific
capability can still call `extension_list` to learn it, then `action_request` to
use it.

## Example: a "layout" servicer

A servicer (the plugin) announces:

```jsonc
extension.register {
  "namespace": "layout",
  "methods": ["runPrimitive", "exportContext", "lvs"],
  "description": "layout read + parameter-driven geometry primitives"
}
```

A client invokes a primitive (the servicer runs it as a reversible transaction):

```jsonc
action.request {
  "namespace": "layout",
  "method": "runPrimitive",
  "params": { "name": "widen_net", "lib": "L", "cell": "C", "net": "VDD", "width": 0.84 }
}
// -> { "action_id": "act_…", "status": "pending", "serviced": true }

action.get { "action_id": "act_…" }
// -> { "action": { "status": "done", "result": { "status": "applied", "transaction_id": "t_…" } } }
```

The same pattern serves any namespace a future servicer registers — discovery and
invocation never change.

## Design notes

- **Transient by design.** The registry and the action queue are in-memory;
  servicers re-announce on reconnect. The tunnel holds no privileged capability
  list across restarts.
- **Generic over capability.** `params` and `result` are opaque to the tunnel;
  the servicer and client agree on their shape per method. (For the built-in
  layout primitives, the result follows `schemas/layout_primitive.schema.json`.)
- **Gating belongs to the servicer.** Reversibility, approval, and provenance are
  enforced where the action runs (e.g. the L4 transaction engine), not in the
  transport.

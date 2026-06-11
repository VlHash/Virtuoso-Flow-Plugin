# VFP MCP server

Exposes the VFP Tunnel to an AI agent as MCP tools, so the agent can read
design context, propose changes, and inspect results/runs while a human keeps
approval control.

Runs on the **agent host** (not the design server) and connects to a running
VFP Tunnel over its JSON-RPC port. Needs Python 3.10+ and the `mcp` SDK; the
tunnel daemon never imports this, so it stays stdlib-only on 3.6.

## Install & run

```bash
pip install "mcp>=1.0"                 # or: pip install -e tunnel[agent]
vfp tunnel start                        # the tunnel must be running
vfp-mcp                                 # or: python -m vfp_tunnel.agent.mcp_server
```

The endpoint is resolved from the tunnel state file, then `VFP_HOST`/`VFP_PORT`,
then the defaults (`127.0.0.1:47891`).

## Register with Claude

Claude Desktop / Claude Code `mcpServers` entry:

```json
{
  "mcpServers": {
    "vfp": {
      "command": "vfp-mcp",
      "env": { "VFP_PORT": "47891" }
    }
  }
}
```

(Use `"command": "python", "args": ["-m", "vfp_tunnel.agent.mcp_server"]` with
a suitable `PYTHONPATH` if not installed as a script.)

## Tools

| Tool | Purpose |
|------|---------|
| `tunnel_status` | Is the tunnel up; version/uptime/sessions |
| `context_get` | Latest exported design context |
| `proposal_create` | Propose a parameter change (for human review) |
| `proposal_list` / `proposal_get` | Browse proposals |
| `proposal_approve` / `proposal_reject` | Record the human's review decision |
| `transaction_list` | Applied-change transactions (rollback records) |
| `result_latest` | Latest simulation metrics + constraint verdict |
| `constraint_check` | Evaluate metrics against limits |
| `run_list` | Simulation runs + linked results |

Proposals are never auto-applied: the agent proposes, a human approves, and the
plugin applies it as a reversible transaction.

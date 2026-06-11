from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import tools

mcp = FastMCP("vfp-tunnel")


@mcp.tool()
def tunnel_status() -> dict:
    """Check the VFP Tunnel: whether it is running, its version, uptime, and
    how many plugin sessions are connected."""
    return tools.tunnel_status()


@mcp.tool()
def context_get() -> Optional[dict]:
    """Get the latest exported design context (current lib/cell/view plus the
    schematic's instances, parameters, and nets). Returns null if no context
    has been exported from Virtuoso yet."""
    return tools.context_get()


@mcp.tool()
def proposal_create(proposal: dict) -> dict:
    """Create a design-change proposal for the human to review. `proposal`
    must include `cellview` {lib,cell,view}, a `reason`, and `changes`: a list
    of {type:"set_instance_param", instance, param, before, after}. Returns
    the stored proposal with its id and `pending` status. Proposals are never
    auto-applied; a human approves, then it is applied as a reversible
    transaction."""
    return tools.proposal_create(proposal)


@mcp.tool()
def proposal_list(status: Optional[str] = None) -> list:
    """List proposals, optionally filtered by status (pending, approved,
    rejected, applied, failed, rolled_back, expired)."""
    return tools.proposal_list(status)


@mcp.tool()
def proposal_get(proposal_id: str) -> dict:
    """Get one proposal by id (full record incl. changes and status)."""
    return tools.proposal_get(proposal_id)


@mcp.tool()
def proposal_approve(proposal_id: str) -> dict:
    """Approve a pending proposal. This records the human reviewer's decision;
    only approved proposals can be applied to the schematic."""
    return tools.proposal_approve(proposal_id)


@mcp.tool()
def proposal_reject(proposal_id: str) -> dict:
    """Reject a pending proposal (records the human reviewer's decision)."""
    return tools.proposal_reject(proposal_id)


@mcp.tool()
def transaction_list(status: Optional[str] = None) -> list:
    """List applied-change transactions (before/after parameter records used
    for rollback), optionally by status (applied, failed, rolled_back)."""
    return tools.transaction_list(status)


@mcp.tool()
def result_latest() -> Optional[dict]:
    """Get the latest simulation result: its metrics and, if evaluated, the
    constraint pass/fail verdict. Returns null if no result is stored."""
    return tools.result_latest()


@mcp.tool()
def constraint_check(constraints: dict, metrics: Optional[dict] = None) -> dict:
    """Evaluate `constraints` (metric -> {min?, max?}) against `metrics`
    (metric -> number). If `metrics` is omitted, the latest stored result's
    metrics are used. Returns {overall: pass|fail, items: [...], source}."""
    return tools.constraint_check(constraints, metrics)


@mcp.tool()
def run_list(status: Optional[str] = None) -> list:
    """List simulation runs and their linked results, optionally by status
    (created, running, done, failed)."""
    return tools.run_list(status)


@mcp.tool()
def events(since: int = 0) -> dict:
    """List tunnel activity events (proposal.created/approved/rejected/expired,
    transaction.created/rolled_back, result.updated, run.done) with sequence
    number > `since`. Returns {events, latest_seq, oldest_seq, boot_id}; poll
    again with latest_seq to get only what is new."""
    return tools.events(since)


def main():
    mcp.run()


if __name__ == "__main__":
    main()

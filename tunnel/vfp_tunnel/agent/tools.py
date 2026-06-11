import json

from ..config import resolve_host, resolve_port, state_file
from ..rpc.transport import call as _rpc_call

_TIMEOUT = 5.0


def _endpoint(host=None, port=None):
    """Resolve the tunnel endpoint: explicit args, then the daemon state
    file, then env/defaults."""
    if host and port:
        return host, int(port)
    st = {}
    try:
        st = json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    return (host or st.get("host") or resolve_host(),
            int(port or st.get("port") or resolve_port()))


def _call(method, params=None, host=None, port=None):
    h, p = _endpoint(host, port)
    return _rpc_call(method, params or {}, host=h, port=p, timeout=_TIMEOUT)


# ---- read-only / status ---------------------------------------------
def tunnel_status(host=None, port=None):
    """Return the VFP Tunnel's status (version, uptime, session count)."""
    return _call("tunnel.status", {}, host, port)


def context_get(host=None, port=None):
    """Return the latest exported design context (lib/cell/view, instances,
    nets), or None if nothing has been exported yet."""
    return _call("design.context.get", {}, host, port).get("context")


# ---- proposals ------------------------------------------------------
def proposal_create(proposal, host=None, port=None):
    """Create a design-change proposal. *proposal* is an object matching the
    proposal schema (cellview, reason, changes[]). Returns the stored
    proposal with its assigned id and 'pending' status."""
    return _call("proposal.create", {"proposal": proposal}, host, port)["proposal"]


def proposal_list(status=None, host=None, port=None):
    """List proposals, optionally filtered by status (pending/approved/
    rejected/applied/failed/rolled_back/expired)."""
    params = {"status": status} if status else {}
    return _call("proposal.list", params, host, port)["proposals"]


def proposal_get(proposal_id, host=None, port=None):
    """Return a single proposal by id."""
    return _call("proposal.get", {"proposal_id": proposal_id}, host, port)["proposal"]


def proposal_approve(proposal_id, host=None, port=None):
    """Approve a pending proposal. This represents the human reviewer's
    decision; only approved proposals may be applied."""
    return _call("proposal.approve", {"proposal_id": proposal_id}, host, port)["proposal"]


def proposal_reject(proposal_id, host=None, port=None):
    """Reject a pending proposal (the human reviewer's decision)."""
    return _call("proposal.reject", {"proposal_id": proposal_id}, host, port)["proposal"]


# ---- transactions / results / constraints / runs --------------------
def transaction_list(status=None, host=None, port=None):
    """List applied-change transactions (optionally by status: applied/
    failed/rolled_back)."""
    params = {"status": status} if status else {}
    return _call("transaction.list", params, host, port)["transactions"]


def result_latest(host=None, port=None):
    """Return the latest stored simulation result (metrics + any constraint
    verdict), or None."""
    return _call("result.latest", {}, host, port).get("result")


def constraint_check(constraints, metrics=None, host=None, port=None):
    """Evaluate *constraints* (metric -> {min?,max?}) against *metrics*
    (metric -> number); if *metrics* is omitted, the latest stored result's
    metrics are used. Returns {overall, items[], source}."""
    params = {"constraints": constraints}
    if metrics is not None:
        params["metrics"] = metrics
    return _call("constraint.check", params, host, port)


def run_list(status=None, host=None, port=None):
    """List simulation runs (optionally by status: created/running/done/
    failed)."""
    params = {"status": status} if status else {}
    return _call("run.list", params, host, port)["runs"]

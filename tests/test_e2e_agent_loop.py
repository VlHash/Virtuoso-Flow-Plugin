"""End-to-end composition test: the full agent loop over real JSON-RPC.

Exercises milestones 4-7 wired together in one flow, guarding the
cross-cutting invariants that no single-milestone test covers:

  proposal.create -> approve -> transaction.create (links proposal: approved
  -> applied) -> run.create -> run.import_result (stores a result, links it
  to the run, marks the run done) -> constraint.check / result.latest.
"""

import threading

import pytest


@pytest.fixture
def running_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    monkeypatch.setenv("VFP_PROPOSAL_TTL_S", "0")  # no expiry mid-flow
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    for mod in ("vfp_tunnel.proposal.manager",
                "vfp_tunnel.transaction.manager",
                "vfp_tunnel.sim.manager",
                "vfp_tunnel.artifact.manager"):
        importlib.reload(importlib.import_module(mod))
    from vfp_tunnel.daemon import Tunnel
    from vfp_tunnel.rpc.transport import make_server

    tun = Tunnel("127.0.0.1", 0)
    server = make_server("127.0.0.1", 0, tun.dispatcher)
    tun.server = server
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield host, port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


_CV = {"lib": "RFCOPA", "cell": "XOPA", "view": "schematic"}

_PROPOSAL = {
    "schema_version": "0.1",
    "proposal_id": "p_e2e_001",
    "created_by": "agent",
    "status": "pending",
    "cellview": _CV,
    "reason": "Phase margin too high; shrink Cc",
    "changes": [{"type": "set_instance_param", "instance": "C0",
                 "param": "c", "before": "12f", "after": "6f"}],
    "requires_user_approval": True,
}

_TXN = {
    "schema_version": "0.1",
    "proposal_id": "p_e2e_001",
    "status": "applied",
    "cellview": _CV,
    "before": [{"instance": "C0", "param": "c", "value": "12f"}],
    "after": [{"instance": "C0", "param": "c", "value": "6f"}],
}

_LIMITS = {"PM_deg": {"min": 65, "max": 80}, "A0_dB": {"min": 100}}


def test_full_agent_loop(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel

    def rpc(method, params):
        return call(method, params, host=host, port=port)

    # 1. Propose, then approve.
    assert rpc("proposal.create", {"proposal": _PROPOSAL})["proposal"]["status"] == "pending"
    assert rpc("proposal.approve", {"proposal_id": "p_e2e_001"})["proposal"]["status"] == "approved"

    # 2. Record the applied change as a transaction -> proposal becomes applied.
    txn = rpc("transaction.create", {"transaction": _TXN})["transaction"]
    assert txn["status"] == "applied"
    assert txn["before"][0]["value"] == "12f"   # rollback recipe preserved
    assert rpc("proposal.get", {"proposal_id": "p_e2e_001"})["proposal"]["status"] == "applied"

    # 3. Open a run and import the post-change metrics into it.
    run_id = rpc("run.create", {"run": {"test": "ac_loopgain", "cellview": _CV}})["run"]["run_id"]
    imp = rpc("run.import_result", {
        "run_id": run_id,
        "metrics": {"PM_deg": 72.0, "A0_dB": 101.0},
        "constraints": _LIMITS,
    })
    assert imp["run"]["status"] == "done"
    result_id = imp["result"]["result_id"]
    assert imp["run"]["result_id"] == result_id
    assert imp["result"]["constraints"]["overall"] == "pass"

    # 4. The imported result is the latest, and a fresh check agrees.
    latest = rpc("result.latest", {})["result"]
    assert latest["result_id"] == result_id
    assert rpc("constraint.check", {"constraints": _LIMITS})["overall"] == "pass"

    # 5. The run is discoverable and points back at the result.
    run = rpc("run.get", {"run_id": run_id})["run"]
    assert run["status"] == "done"
    assert run["result_id"] == result_id


def test_loop_with_failing_constraint(running_tunnel):
    """Same loop but the post-change metric violates a limit -> overall fail."""
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel

    def rpc(method, params):
        return call(method, params, host=host, port=port)

    p = dict(_PROPOSAL, proposal_id="p_e2e_002")
    rpc("proposal.create", {"proposal": p})
    rpc("proposal.approve", {"proposal_id": "p_e2e_002"})
    rpc("transaction.create", {"transaction": dict(_TXN, proposal_id="p_e2e_002")})

    run_id = rpc("run.create", {"run": {"test": "t", "cellview": _CV}})["run"]["run_id"]
    imp = rpc("run.import_result", {
        "run_id": run_id,
        "metrics": {"PM_deg": 85.0, "A0_dB": 101.0},   # PM_deg > max 80
        "constraints": _LIMITS,
    })
    assert imp["result"]["constraints"]["overall"] == "fail"
    fails = [i for i in imp["result"]["constraints"]["items"] if i["status"] == "fail"]
    assert [i["metric"] for i in fails] == ["PM_deg"]

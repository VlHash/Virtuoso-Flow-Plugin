import threading

import pytest


@pytest.fixture
def running_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    monkeypatch.setenv("VFP_PROPOSAL_TTL_S", "0")
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    for mod in ("vfp_tunnel.proposal.manager", "vfp_tunnel.transaction.manager",
                "vfp_tunnel.sim.manager", "vfp_tunnel.artifact.manager"):
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


_PROPOSAL = {
    "schema_version": "0.1",
    "proposal_id": "p_tool_001",
    "created_by": "agent",
    "status": "pending",
    "cellview": {"lib": "RFCOPA", "cell": "XOPA", "view": "schematic"},
    "reason": "shrink Cc",
    "changes": [{"type": "set_instance_param", "instance": "C0",
                 "param": "c", "before": "12f", "after": "6f"}],
    "requires_user_approval": True,
}


def test_tunnel_status(running_tunnel):
    from vfp_tunnel.agent import tools
    host, port = running_tunnel
    st = tools.tunnel_status(host=host, port=port)
    assert st["running"] is True
    assert "version" in st


def test_context_and_result_empty(running_tunnel):
    from vfp_tunnel.agent import tools
    host, port = running_tunnel
    assert tools.context_get(host=host, port=port) is None
    assert tools.result_latest(host=host, port=port) is None
    assert tools.proposal_list(host=host, port=port) == []
    assert tools.run_list(host=host, port=port) == []
    assert tools.transaction_list(host=host, port=port) == []


def test_proposal_flow(running_tunnel):
    from vfp_tunnel.agent import tools
    host, port = running_tunnel

    created = tools.proposal_create(_PROPOSAL, host=host, port=port)
    assert created["proposal_id"] == "p_tool_001"
    assert created["status"] == "pending"

    listed = tools.proposal_list(status="pending", host=host, port=port)
    assert [p["proposal_id"] for p in listed] == ["p_tool_001"]

    got = tools.proposal_get("p_tool_001", host=host, port=port)
    assert got["reason"] == "shrink Cc"

    approved = tools.proposal_approve("p_tool_001", host=host, port=port)
    assert approved["status"] == "approved"
    assert tools.proposal_list(status="pending", host=host, port=port) == []


def test_proposal_reject(running_tunnel):
    from vfp_tunnel.agent import tools
    host, port = running_tunnel
    tools.proposal_create(dict(_PROPOSAL, proposal_id="p_tool_rej"),
                          host=host, port=port)
    rejected = tools.proposal_reject("p_tool_rej", host=host, port=port)
    assert rejected["status"] == "rejected"


def test_constraint_check_explicit_metrics(running_tunnel):
    from vfp_tunnel.agent import tools
    host, port = running_tunnel
    res = tools.constraint_check(
        {"PM_deg": {"min": 65, "max": 80}},
        metrics={"PM_deg": 85},
        host=host, port=port)
    assert res["overall"] == "fail"
    assert res["source"] == "params"


def test_unknown_proposal_raises(running_tunnel):
    from vfp_tunnel.agent import tools
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError
    host, port = running_tunnel
    with pytest.raises(JsonRpcError):
        tools.proposal_get("p_nope", host=host, port=port)


def test_mcp_server_registers_tools():
    """The FastMCP wrapper imports and exposes every tool (skipped if the mcp
    SDK is not installed)."""
    pytest.importorskip("mcp")
    from vfp_tunnel.agent import mcp_server
    names = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
    expected = {
        "tunnel_status", "context_get", "proposal_create", "proposal_list",
        "proposal_get", "proposal_approve", "proposal_reject",
        "transaction_list", "result_latest", "constraint_check", "run_list",
    }
    assert expected <= names

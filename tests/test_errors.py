import threading

import pytest


# ---- error taxonomy -------------------------------------------------

def test_codes_distinct_and_in_server_range():
    from vfp_tunnel.rpc import errors
    app = [errors.NOT_FOUND, errors.PERMISSION_DENIED, errors.INVALID_STATE,
           errors.CONFLICT, errors.STALE]
    assert len(set(app)) == len(app)                 # all distinct
    for c in app:
        assert -32099 <= c <= -32000                 # server-reserved range


def test_assigned_code_values_are_stable():
    # Clients branch on these; lock the wire values.
    from vfp_tunnel.rpc import errors
    assert errors.NOT_FOUND == -32001
    assert errors.PERMISSION_DENIED == -32002
    assert errors.INVALID_STATE == -32003
    assert errors.CONFLICT == -32004


def test_reserved_ranges_do_not_overlap_assigned():
    from vfp_tunnel.rpc import errors
    assigned = {errors.NOT_FOUND, errors.PERMISSION_DENIED, errors.INVALID_STATE,
                errors.CONFLICT, errors.STALE}
    for base in (errors.SESSION_BASE, errors.JOB_BASE, errors.RESULT_BASE):
        for c in range(base, base - 10, -1):
            assert c not in assigned


def test_message_for():
    from vfp_tunnel.rpc import errors
    assert errors.message_for(errors.NOT_FOUND) == "not found"
    assert errors.message_for(-99999) == "error"


# ---- the daemon emits the taxonomy code over the wire ---------------

@pytest.fixture
def running_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    for mod in ("vfp_tunnel.proposal.manager", "vfp_tunnel.transaction.manager",
                "vfp_tunnel.sim.manager", "vfp_tunnel.artifact.manager",
                "vfp_tunnel.event.manager"):
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


def test_unknown_id_uses_not_found_code(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError
    from vfp_tunnel.rpc import errors
    host, port = running_tunnel
    with pytest.raises(JsonRpcError) as ei:
        call("proposal.get", {"proposal_id": "p_nope"}, host=host, port=port)
    assert ei.value.code == errors.NOT_FOUND
    with pytest.raises(JsonRpcError) as ei2:
        call("transaction.get", {"transaction_id": "t_nope"}, host=host, port=port)
    assert ei2.value.code == errors.NOT_FOUND


# ---- UTF-8 hardening: non-ASCII round-trips through disk -------------

def test_utf8_roundtrip_through_store(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    monkeypatch.setenv("VFP_PROPOSAL_TTL_S", "0")
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.proposal.manager as m
    importlib.reload(m)
    reason = "相位裕度过高 αβ µm — reduce Cc"
    m.ProposalStore().create({"proposal_id": "p_utf", "reason": reason})
    # A fresh store reads the persisted file back; non-ASCII must survive.
    assert m.ProposalStore().get("p_utf")["reason"] == reason

"""Tests for the transaction model, permissions, store, and RPC methods.

Covers:
  - model.make_transaction / model.transition
  - permissions.is_allowed / violations (deny-wins, allow-list semantics)
  - TransactionStore CRUD + state machine + persistence
  - Tunnel RPC over real TCP (transaction.create/list/get/rollback/
    mark_rolled_back/mark_failed) and proposal<->transaction linkage
"""

import threading

import pytest


# ---- model ----------------------------------------------------------

def test_make_transaction_defaults():
    from vfp_tunnel.transaction.model import make_transaction
    t = make_transaction({"proposal_id": "p_1"})
    assert t["status"] == "applied"
    assert t["schema_version"] == "0.1"
    assert t["before"] == []
    assert t["after"] == []
    assert t["transaction_id"].startswith("t_")
    assert "timestamp" in t


def test_make_transaction_preserves_id():
    from vfp_tunnel.transaction.model import make_transaction
    t = make_transaction({"transaction_id": "t_fixed", "proposal_id": "p"})
    assert t["transaction_id"] == "t_fixed"


def test_transition_applied_to_rolled_back():
    from vfp_tunnel.transaction.model import make_transaction, transition
    t = make_transaction({})
    t2 = transition(t, "rolled_back")
    assert t2["status"] == "rolled_back"


def test_transition_invalid():
    from vfp_tunnel.transaction.model import make_transaction, transition
    t = transition(make_transaction({}), "rolled_back")
    with pytest.raises(ValueError):
        transition(t, "applied")


# ---- permissions ----------------------------------------------------

def test_is_allowed_default_allows():
    from vfp_tunnel.transaction.permissions import is_allowed
    ok, _ = is_allowed("M0.w")
    assert ok is True


def test_is_allowed_deny_wins():
    from vfp_tunnel.transaction.permissions import is_allowed
    ok, reason = is_allowed("VDD.dc", allow=["*"], deny=["VDD.*"])
    assert ok is False
    assert "deny" in reason


def test_is_allowed_allow_list_required():
    from vfp_tunnel.transaction.permissions import is_allowed
    ok, _ = is_allowed("X9.foo", allow=["M*.w", "C*.c"])
    assert ok is False
    ok2, _ = is_allowed("M3.w", allow=["M*.w", "C*.c"])
    assert ok2 is True


def test_violations_reports_blocked_only():
    from vfp_tunnel.transaction.permissions import violations
    changes = [
        {"instance": "C0", "param": "c", "value": "6f"},
        {"instance": "VDD", "param": "dc", "value": "1.8"},
    ]
    viol = violations(changes, allow=["C*.c", "M*.w"], deny=["VDD.*"])
    assert len(viol) == 1
    assert viol[0]["target"] == "VDD.dc"


# ---- store ----------------------------------------------------------

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.transaction.manager as m
    importlib.reload(m)
    return m.TransactionStore()


def _txn(tid, proposal="p_1"):
    return {
        "transaction_id": tid,
        "proposal_id": proposal,
        "cellview": {"lib": "L", "cell": "C", "view": "schematic"},
        "before": [{"instance": "C0", "param": "c", "value": "12f"}],
        "after": [{"instance": "C0", "param": "c", "value": "6f"}],
    }


def test_store_create_get(store):
    t = store.create(_txn("t_a"))
    assert t["status"] == "applied"
    assert store.get("t_a")["transaction_id"] == "t_a"


def test_store_duplicate_raises(store):
    store.create(_txn("t_dup"))
    with pytest.raises(ValueError, match="duplicate"):
        store.create(_txn("t_dup"))


def test_store_last_applied(store):
    import time
    store.create(_txn("t_old"))
    time.sleep(1.05)   # timestamp granularity is whole seconds
    store.create(_txn("t_new"))
    assert store.last("applied")["transaction_id"] == "t_new"


def test_store_rollback_and_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.transaction.manager as m
    importlib.reload(m)
    s1 = m.TransactionStore()
    s1.create(_txn("t_persist"))
    s1.mark_rolled_back("t_persist")

    s2 = m.TransactionStore()
    assert s2.get("t_persist")["status"] == "rolled_back"


# ---- RPC over TCP ---------------------------------------------------

@pytest.fixture
def running_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    for mod in ("vfp_tunnel.proposal.manager", "vfp_tunnel.transaction.manager"):
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
        yield host, port, tun
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _create_approved_proposal(call, host, port, pid="p_txn"):
    proposal = {
        "schema_version": "0.1",
        "proposal_id": pid,
        "created_by": "agent",
        "status": "pending",
        "cellview": {"lib": "RFCOPA", "cell": "XOPA", "view": "schematic"},
        "reason": "shrink Cc",
        "changes": [{"type": "set_instance_param", "instance": "C0",
                     "param": "c", "before": "12f", "after": "6f"}],
        "requires_user_approval": True,
    }
    call("proposal.create", {"proposal": proposal}, host=host, port=port)
    call("proposal.approve", {"proposal_id": pid}, host=host, port=port)


def _txn_params(pid="p_txn", tid=None):
    t = {
        "schema_version": "0.1",
        "proposal_id": pid,
        "status": "applied",
        "cellview": {"lib": "RFCOPA", "cell": "XOPA", "view": "schematic"},
        "before": [{"instance": "C0", "param": "c", "value": "12f"}],
        "after": [{"instance": "C0", "param": "c", "value": "6f"}],
    }
    if tid:
        t["transaction_id"] = tid
    return {"transaction": t}


def test_rpc_create_links_proposal(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port, tun = running_tunnel
    _create_approved_proposal(call, host, port, "p_link")

    res = call("transaction.create", _txn_params("p_link"), host=host, port=port)
    tid = res["transaction"]["transaction_id"]
    assert res["transaction"]["status"] == "applied"

    # The approved proposal should now be 'applied'.
    p = call("proposal.get", {"proposal_id": "p_link"}, host=host, port=port)
    assert p["proposal"]["status"] == "applied"

    got = call("transaction.get", {"transaction_id": tid}, host=host, port=port)
    assert got["transaction"]["before"][0]["value"] == "12f"


def test_rpc_rollback_recipe_and_mark(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port, tun = running_tunnel
    _create_approved_proposal(call, host, port, "p_rb")
    res = call("transaction.create", _txn_params("p_rb", tid="t_rb"),
               host=host, port=port)
    assert res["transaction"]["transaction_id"] == "t_rb"

    # rollback returns the restore recipe (before values), state still applied.
    rb = call("transaction.rollback", {"transaction_id": "t_rb"},
              host=host, port=port)
    assert rb["restore"][0]["value"] == "12f"
    assert call("transaction.get", {"transaction_id": "t_rb"},
                host=host, port=port)["transaction"]["status"] == "applied"

    # confirm rollback -> transaction rolled_back, proposal rolled_back.
    done = call("transaction.mark_rolled_back", {"transaction_id": "t_rb"},
                host=host, port=port)
    assert done["transaction"]["status"] == "rolled_back"
    p = call("proposal.get", {"proposal_id": "p_rb"}, host=host, port=port)
    assert p["proposal"]["status"] == "rolled_back"


def test_rpc_rollback_rejects_non_applied(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError
    host, port, tun = running_tunnel
    call("transaction.create", _txn_params(tid="t_x"), host=host, port=port)
    call("transaction.mark_rolled_back", {"transaction_id": "t_x"},
         host=host, port=port)
    with pytest.raises(JsonRpcError):
        call("transaction.rollback", {"transaction_id": "t_x"},
             host=host, port=port)


def test_rpc_permission_denied(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError
    host, port, tun = running_tunnel
    params = _txn_params(tid="t_perm")
    params["permissions"] = {"allow_modify": ["M*.w"], "deny_modify": ["C*.c"]}
    with pytest.raises(JsonRpcError) as ei:
        call("transaction.create", params, host=host, port=port)
    assert ei.value.code == -32002


def test_rpc_list_and_filter(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port, tun = running_tunnel
    call("transaction.create", _txn_params(tid="t_1"), host=host, port=port)
    call("transaction.create", _txn_params(tid="t_2"), host=host, port=port)
    call("transaction.mark_rolled_back", {"transaction_id": "t_1"},
         host=host, port=port)

    applied = call("transaction.list", {"status": "applied"},
                   host=host, port=port)
    assert applied["count"] == 1
    assert applied["transactions"][0]["transaction_id"] == "t_2"

    allt = call("transaction.list", {}, host=host, port=port)
    assert allt["count"] == 2


def test_rpc_unknown_id_raises(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError
    host, port, tun = running_tunnel
    with pytest.raises(JsonRpcError):
        call("transaction.get", {"transaction_id": "t_nope"},
             host=host, port=port)

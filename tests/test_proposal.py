"""Tests for the proposal model, store, and RPC methods.

Covers:
  - model.make_proposal / model.transition
  - ProposalStore CRUD + state machine
  - Tunnel RPC methods over real TCP (proposal.create/list/get/approve/reject/
    mark_applied/mark_failed)
"""

import threading
import time

import pytest


# ---- model tests ----------------------------------------------------

def test_make_proposal_defaults():
    from vfp_tunnel.proposal.model import make_proposal
    p = make_proposal({"reason": "test"})
    assert p["status"] == "pending"
    assert p["schema_version"] == "0.1"
    assert p["created_by"] == "agent"
    assert p["requires_user_approval"] is True
    assert "proposal_id" in p
    assert "created_at" in p
    assert "updated_at" in p


def test_make_proposal_preserves_id():
    from vfp_tunnel.proposal.model import make_proposal
    p = make_proposal({"proposal_id": "p_test001", "reason": "x"})
    assert p["proposal_id"] == "p_test001"


def test_transition_valid():
    from vfp_tunnel.proposal.model import make_proposal, transition
    p = make_proposal({"reason": "x"})
    p2 = transition(p, "approved")
    assert p2["status"] == "approved"
    p3 = transition(p2, "applied")
    assert p3["status"] == "applied"
    p4 = transition(p3, "rolled_back")
    assert p4["status"] == "rolled_back"


def test_transition_invalid():
    from vfp_tunnel.proposal.model import make_proposal, transition
    p = make_proposal({"reason": "x"})
    with pytest.raises(ValueError, match="cannot transition"):
        transition(p, "applied")


def test_transition_reject():
    from vfp_tunnel.proposal.model import make_proposal, transition
    p = make_proposal({"reason": "x"})
    p2 = transition(p, "rejected")
    assert p2["status"] == "rejected"
    with pytest.raises(ValueError):
        transition(p2, "approved")


# ---- store tests ----------------------------------------------------

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    # Re-import manager so it picks up the reloaded config.
    import vfp_tunnel.proposal.manager as m
    importlib.reload(m)
    return m.ProposalStore()


def test_store_create_and_get(store):
    p = store.create({"reason": "phase margin", "cellview": {"lib": "L", "cell": "C", "view": "v"}})
    assert p["status"] == "pending"
    pid = p["proposal_id"]
    fetched = store.get(pid)
    assert fetched["proposal_id"] == pid


def test_store_duplicate_id_raises(store):
    store.create({"proposal_id": "p_dup", "reason": "x"})
    with pytest.raises(ValueError, match="duplicate"):
        store.create({"proposal_id": "p_dup", "reason": "y"})


def test_store_list_and_filter(store):
    store.create({"proposal_id": "p_a", "reason": "a"})
    store.create({"proposal_id": "p_b", "reason": "b"})
    store.approve("p_a")
    pending = store.list(status="pending")
    approved = store.list(status="approved")
    assert len(pending) == 1
    assert pending[0]["proposal_id"] == "p_b"
    assert len(approved) == 1
    assert approved[0]["proposal_id"] == "p_a"


# ---- TTL (auto-expiry of stale pending proposals) -------------------

def _ttl_store(tmp_path, monkeypatch, ttl):
    """Fresh ProposalStore under tmp_path with VFP_PROPOSAL_TTL_S=ttl."""
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    monkeypatch.setenv("VFP_PROPOSAL_TTL_S", str(ttl))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.proposal.manager as m
    importlib.reload(m)
    return m.ProposalStore()


def test_ttl_expires_stale_pending(tmp_path, monkeypatch):
    store = _ttl_store(tmp_path, monkeypatch, ttl=60)
    store.create({"proposal_id": "p_old", "reason": "x"})
    # Backdate so it is already well past the 60s TTL.
    store._proposals["p_old"]["created_ts"] = time.time() - 120

    # A pending query triggers the sweep; the stale one must be gone.
    assert store.list(status="pending") == []
    expired = store.get("p_old")
    assert expired["status"] == "expired"
    assert "expired_reason" in expired


def test_ttl_keeps_fresh_pending(tmp_path, monkeypatch):
    store = _ttl_store(tmp_path, monkeypatch, ttl=60)
    store.create({"proposal_id": "p_fresh", "reason": "x"})
    pending = store.list(status="pending")
    assert [p["proposal_id"] for p in pending] == ["p_fresh"]


def test_ttl_zero_disables_expiry(tmp_path, monkeypatch):
    store = _ttl_store(tmp_path, monkeypatch, ttl=0)
    store.create({"proposal_id": "p_keep", "reason": "x"})
    store._proposals["p_keep"]["created_ts"] = time.time() - 10000
    assert store.expire_stale() == []
    assert store.get("p_keep")["status"] == "pending"


def test_ttl_only_touches_pending(tmp_path, monkeypatch):
    store = _ttl_store(tmp_path, monkeypatch, ttl=60)
    store.create({"proposal_id": "p_appr", "reason": "x"})
    store.approve("p_appr")
    store._proposals["p_appr"]["created_ts"] = time.time() - 120
    assert store.expire_stale() == []
    assert store.get("p_appr")["status"] == "approved"


def test_store_approve_reject_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.proposal.manager as m
    importlib.reload(m)
    store1 = m.ProposalStore()
    store1.create({"proposal_id": "p_persist", "reason": "x"})
    store1.approve("p_persist")

    # Load a second store from the same dir to check persistence.
    store2 = m.ProposalStore()
    p = store2.get("p_persist")
    assert p is not None
    assert p["status"] == "approved"


def test_store_full_lifecycle(store):
    store.create({"proposal_id": "p_life", "reason": "full lifecycle"})
    store.approve("p_life")
    store.mark_applied("p_life")
    store.mark_rolled_back("p_life")
    p = store.get("p_life")
    assert p["status"] == "rolled_back"


def test_store_failed_path(store):
    store.create({"proposal_id": "p_fail", "reason": "fail path"})
    store.approve("p_fail")
    store.mark_failed("p_fail")
    p = store.get("p_fail")
    assert p["status"] == "failed"
    with pytest.raises(ValueError):
        store.mark_applied("p_fail")


# ---- RPC over TCP ---------------------------------------------------

@pytest.fixture
def running_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.proposal.manager as m
    importlib.reload(m)
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


_SAMPLE = {
    "schema_version": "0.1",
    "proposal_id": "p_rpc_001",
    "created_by": "agent",
    "status": "pending",
    "cellview": {"lib": "RFCOPA", "cell": "XOPA", "view": "schematic"},
    "reason": "Phase margin is too high",
    "changes": [
        {"type": "set_instance_param", "instance": "C0",
         "param": "c", "before": "12f", "after": "6f"},
    ],
    "requires_user_approval": True,
}


def test_rpc_create_list_get(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel

    res = call("proposal.create", {"proposal": _SAMPLE}, host=host, port=port)
    assert res["proposal"]["proposal_id"] == "p_rpc_001"
    assert res["proposal"]["status"] == "pending"

    listed = call("proposal.list", {}, host=host, port=port)
    assert listed["count"] == 1
    assert listed["proposals"][0]["proposal_id"] == "p_rpc_001"

    got = call("proposal.get", {"proposal_id": "p_rpc_001"}, host=host, port=port)
    assert got["proposal"]["reason"] == "Phase margin is too high"


def test_rpc_approve_and_apply(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel

    call("proposal.create", {"proposal": dict(_SAMPLE, proposal_id="p_rpc_002")},
         host=host, port=port)

    approved = call("proposal.approve", {"proposal_id": "p_rpc_002"},
                    host=host, port=port)
    assert approved["proposal"]["status"] == "approved"

    applied = call("proposal.mark_applied", {"proposal_id": "p_rpc_002"},
                   host=host, port=port)
    assert applied["proposal"]["status"] == "applied"


def test_rpc_reject(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel

    call("proposal.create", {"proposal": dict(_SAMPLE, proposal_id="p_rpc_003")},
         host=host, port=port)

    rejected = call("proposal.reject", {"proposal_id": "p_rpc_003"},
                    host=host, port=port)
    assert rejected["proposal"]["status"] == "rejected"


def test_rpc_mark_failed(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel

    call("proposal.create", {"proposal": dict(_SAMPLE, proposal_id="p_rpc_004")},
         host=host, port=port)
    call("proposal.approve", {"proposal_id": "p_rpc_004"}, host=host, port=port)

    failed = call("proposal.mark_failed", {"proposal_id": "p_rpc_004"},
                  host=host, port=port)
    assert failed["proposal"]["status"] == "failed"


def test_rpc_unknown_id_raises(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError
    host, port = running_tunnel

    with pytest.raises(JsonRpcError):
        call("proposal.get", {"proposal_id": "p_nosuch"}, host=host, port=port)


def test_rpc_list_status_filter(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel

    call("proposal.create", {"proposal": dict(_SAMPLE, proposal_id="p_flt_1")},
         host=host, port=port)
    call("proposal.create", {"proposal": dict(_SAMPLE, proposal_id="p_flt_2")},
         host=host, port=port)
    call("proposal.approve", {"proposal_id": "p_flt_1"}, host=host, port=port)

    pending = call("proposal.list", {"status": "pending"}, host=host, port=port)
    assert pending["count"] == 1
    assert pending["proposals"][0]["proposal_id"] == "p_flt_2"

    approved = call("proposal.list", {"status": "approved"}, host=host, port=port)
    assert approved["count"] == 1

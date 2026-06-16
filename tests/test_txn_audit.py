import threading

import pytest


# ---- model + store: created_ts precise ordering ---------------------

def test_make_transaction_has_created_ts():
    from vfp_tunnel.transaction.model import make_transaction
    t = make_transaction({"status": "applied"})
    assert isinstance(t["created_ts"], float)


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.transaction.manager as m
    importlib.reload(m)
    return m.TransactionStore()


def test_list_orders_same_second_by_created_ts(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    store.create({"transaction_id": "t_a", "status": "applied"})
    store.create({"transaction_id": "t_b", "status": "applied"})
    # same ISO second, distinct epoch -> created_ts decides the order
    for tid, ct in (("t_a", 100.0), ("t_b", 100.5)):
        store._transactions[tid]["timestamp"] = "2026-01-01T00:00:00"
        store._transactions[tid]["created_ts"] = ct
    assert [t["transaction_id"] for t in store.list()] == ["t_b", "t_a"]


# ---- RPC: actor / session binding -----------------------------------

@pytest.fixture
def running_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    for m in ("vfp_tunnel.transaction.manager", "vfp_tunnel.proposal.manager",
              "vfp_tunnel.session.registry", "vfp_tunnel.event.manager"):
        importlib.reload(importlib.import_module(m))
    from vfp_tunnel.daemon import Tunnel
    from vfp_tunnel.rpc.transport import make_server
    tun = Tunnel("127.0.0.1", 0)
    server = make_server("127.0.0.1", 0, tun.dispatcher)
    tun.server = server
    host, port = server.server_address
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield host, port
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=2)


_TXN = {
    "schema_version": "0.1", "status": "applied",
    "cellview": {"lib": "L", "cell": "C", "view": "schematic"},
    "before": [{"instance": "C0", "param": "c", "value": "12f"}],
    "after": [{"instance": "C0", "param": "c", "value": "6f"}],
}


def test_create_binds_actor_and_session(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    sid = call("session.register", {"client": {
        "client": "vfp", "virtuoso_pid": "3500", "virtuoso_start": "998",
        "display": ":0", "cds_lib": "/proj/cds.lib"}}, host=host, port=port)["session_id"]
    t = call("transaction.create",
             {"transaction": dict(_TXN), "session_id": sid, "actor": "agent"},
             host=host, port=port)["transaction"]
    assert t["actor"] == "agent"
    assert t["session"] == sid
    assert t["session_fingerprint"]["virtuoso_pid"] == "3500"
    assert isinstance(t["created_ts"], float)


def test_create_without_actor_is_unchanged(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    t = call("transaction.create", {"transaction": dict(_TXN)},
             host=host, port=port)["transaction"]
    assert "actor" not in t
    assert "session" not in t
    assert "created_ts" in t

import threading
import time

import pytest


def _fresh_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.session.registry as r
    importlib.reload(r)
    return r.Registry()


def _client(pid="3500", start="111", **kw):
    c = {"client": "virtuoso-flow-plugin", "virtuoso_pid": pid, "virtuoso_start": start}
    c.update(kw)
    return c


# ---- fingerprint dedup ----------------------------------------------

def test_fingerprint_dedup_reuses_session(tmp_path, monkeypatch):
    reg = _fresh_registry(tmp_path, monkeypatch)
    r1 = reg.register(_client())
    r2 = reg.register(_client(lib="L2"))        # same pid+start => plugin reload
    assert r1["session_id"] == r2["session_id"]
    assert r2["reconnects"] == 1
    assert len(reg.list()) == 1
    assert reg.get(r1["session_id"])["client"]["lib"] == "L2"   # client refreshed


def test_different_fingerprint_new_session(tmp_path, monkeypatch):
    reg = _fresh_registry(tmp_path, monkeypatch)
    a = reg.register(_client(pid="1", start="x"))
    b = reg.register(_client(pid="2", start="y"))
    assert a["session_id"] != b["session_id"]
    assert len(reg.list()) == 2


def test_pid_reuse_different_start_is_new(tmp_path, monkeypatch):
    reg = _fresh_registry(tmp_path, monkeypatch)
    a = reg.register(_client(pid="3500", start="100"))
    b = reg.register(_client(pid="3500", start="200"))
    assert a["session_id"] != b["session_id"]


def test_no_fingerprint_always_new(tmp_path, monkeypatch):
    reg = _fresh_registry(tmp_path, monkeypatch)
    a = reg.register({"client": "legacy"})
    b = reg.register({"client": "legacy"})
    assert a["session_id"] != b["session_id"]


# ---- reap -----------------------------------------------------------

def test_reap_removes_idle(tmp_path, monkeypatch):
    reg = _fresh_registry(tmp_path, monkeypatch)
    sid = reg.register(_client())["session_id"]
    reg._sessions[sid]["_last_ts"] = time.time() - 1000
    assert reg.reap(60) == [sid]
    assert reg.get(sid) is None


def test_reap_keeps_fresh_and_off_is_noop(tmp_path, monkeypatch):
    reg = _fresh_registry(tmp_path, monkeypatch)
    reg.register(_client())
    assert reg.reap(60) == []      # fresh
    assert reg.reap(0) == []       # disabled


# ---- RPC over TCP ---------------------------------------------------

@pytest.fixture
def running_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    importlib.reload(importlib.import_module("vfp_tunnel.session.registry"))
    importlib.reload(importlib.import_module("vfp_tunnel.event.manager"))
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


def test_rpc_register_dedup_and_idle_field(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    r1 = call("session.register", {"client": _client()}, host=host, port=port)
    r2 = call("session.register", {"client": _client()}, host=host, port=port)
    assert r2["session_id"] == r1["session_id"]
    assert r2["reconnects"] == 1
    sessions = call("session.list", {}, host=host, port=port)["sessions"]
    assert len(sessions) == 1
    assert "idle_s" in sessions[0]


def test_rpc_heartbeat_via_event_poll(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    sid = call("session.register", {"client": _client()}, host=host, port=port)["session_id"]
    time.sleep(0.5)                                   # let idle grow
    call("event.list", {"session_id": sid}, host=host, port=port)   # heartbeat
    s = call("session.list", {}, host=host, port=port)["sessions"][0]
    assert s["idle_s"] < 0.3                          # the poll reset liveness


def test_rpc_session_reap_plumbing(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    call("session.register", {"client": _client()}, host=host, port=port)
    res = call("session.reap", {"max_idle_s": 9999}, host=host, port=port)
    assert res["count"] == 0                          # fresh session, nothing reaped

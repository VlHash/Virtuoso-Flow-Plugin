import threading
import time

import pytest


# ---- EventLog unit --------------------------------------------------

def _fresh_log(tmp_path, monkeypatch, retain=None):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.event.manager as m
    importlib.reload(m)
    return m.EventLog() if retain is None else m.EventLog(retain=retain)


@pytest.fixture
def log(tmp_path, monkeypatch):
    return _fresh_log(tmp_path, monkeypatch)


def test_emit_seq_and_shape(log):
    e = log.emit("proposal.created", {"proposal_id": "p1"})
    assert set(e) == {"seq", "ts", "type", "payload"}
    assert e["seq"] == 1
    assert e["payload"] == {"proposal_id": "p1"}
    log.emit("b")
    r = log.list(0)
    assert [x["seq"] for x in r["events"]] == [1, 2]
    assert r["latest_seq"] == 2
    assert "boot_id" in r


def test_list_since_filters(log):
    for _ in range(3):
        log.emit("e")
    assert [x["seq"] for x in log.list(1)["events"]] == [2, 3]
    assert log.list(3)["events"] == []


def test_wait_immediate_when_events(log):
    log.emit("a")
    t0 = time.time()
    r = log.wait(0, timeout_s=5)
    assert r["events"] and (time.time() - t0) < 1.0


def test_wait_times_out_empty(log):
    t0 = time.time()
    r = log.wait(0, timeout_s=0.3)
    assert r["events"] == []
    assert (time.time() - t0) >= 0.25


def test_wait_wakes_on_emit(log):
    def emit_later():
        time.sleep(0.2)
        log.emit("late")
    threading.Thread(target=emit_later, daemon=True).start()
    t0 = time.time()
    r = log.wait(0, timeout_s=5)
    assert r["events"] and r["events"][0]["type"] == "late"
    assert (time.time() - t0) < 2.0


def test_persistence_continues_seq(tmp_path, monkeypatch):
    l1 = _fresh_log(tmp_path, monkeypatch)
    l1.emit("a")
    l1.emit("b")
    boot1 = l1.boot_id
    # reload manager again => fresh EventLog from the same VFP_HOME
    import importlib
    import vfp_tunnel.event.manager as m
    importlib.reload(m)
    l2 = m.EventLog()
    assert l2.emit("c")["seq"] == 3                 # seq continues
    assert [x["seq"] for x in l2.list(0)["events"]] == [1, 2, 3]
    assert l2.boot_id != boot1                       # new boot id per start


def test_retention_caps_memory(tmp_path, monkeypatch):
    log = _fresh_log(tmp_path, monkeypatch, retain=5)
    for _ in range(10):
        log.emit("e")
    r = log.list(0)
    assert len(r["events"]) == 5
    assert r["latest_seq"] == 10
    assert r["oldest_seq"] == 6


# ---- RPC over TCP ---------------------------------------------------

@pytest.fixture
def running_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    monkeypatch.setenv("VFP_PROPOSAL_TTL_S", "0")
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


_PROP = {
    "schema_version": "0.1", "proposal_id": "p_ev", "created_by": "agent",
    "status": "pending", "cellview": {"lib": "L", "cell": "C", "view": "schematic"},
    "reason": "r", "changes": [{"type": "set_instance_param", "instance": "C0",
                                "param": "c", "before": "12f", "after": "6f"}],
    "requires_user_approval": True,
}


def test_rpc_event_list_empty(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    r = call("event.list", {}, host=host, port=port)
    assert r["events"] == []
    assert r["latest_seq"] == 0
    assert "boot_id" in r


def test_rpc_emissions_sequence(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel

    call("proposal.create", {"proposal": _PROP}, host=host, port=port)
    call("proposal.approve", {"proposal_id": "p_ev"}, host=host, port=port)
    txn = {"schema_version": "0.1", "proposal_id": "p_ev", "status": "applied",
           "cellview": _PROP["cellview"],
           "before": [{"instance": "C0", "param": "c", "value": "12f"}],
           "after": [{"instance": "C0", "param": "c", "value": "6f"}]}
    call("transaction.create", {"transaction": txn}, host=host, port=port)

    types = [e["type"] for e in call("event.list", {}, host=host, port=port)["events"]]
    assert types == ["proposal.created", "proposal.approved", "transaction.created"]


def test_rpc_run_import_emits_result_and_done(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    rid = call("run.create", {"run": {"test": "t"}}, host=host, port=port)["run"]["run_id"]
    call("run.import_result", {"run_id": rid, "metrics": {"PM_deg": 70}},
         host=host, port=port)
    types = [e["type"] for e in call("event.list", {}, host=host, port=port)["events"]]
    assert "result.updated" in types
    assert "run.done" in types


def test_rpc_event_wait_blocks_then_returns(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel

    def create_later():
        time.sleep(0.3)
        call("proposal.create", {"proposal": _PROP}, host=host, port=port)
    threading.Thread(target=create_later, daemon=True).start()

    t0 = time.time()
    r = call("event.wait", {"since": 0, "timeout_s": 5}, host=host, port=port, timeout=10)
    assert any(e["type"] == "proposal.created" for e in r["events"])
    assert (time.time() - t0) < 4.0


def test_rpc_event_wait_times_out(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    r = call("event.wait", {"since": 0, "timeout_s": 0.4}, host=host, port=port, timeout=5)
    assert r["events"] == []


def test_agent_events_wrapper(running_tunnel):
    from vfp_tunnel.agent import tools
    host, port = running_tunnel
    tools.proposal_create(_PROP, host=host, port=port)
    r = tools.events(host=host, port=port)
    assert r["events"][0]["type"] == "proposal.created"
    assert r["latest_seq"] >= 1

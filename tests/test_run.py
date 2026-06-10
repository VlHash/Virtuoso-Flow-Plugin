import threading

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.artifact.manager as m
    importlib.reload(m)
    return m.RunStore()


def test_create_and_get(store):
    r = store.create({"test": "ac_loopgain", "cellview": {"lib": "L"}})
    assert r["status"] == "created"
    assert r["run_id"].startswith("run_")
    assert store.get(r["run_id"])["test"] == "ac_loopgain"


def test_status_transitions(store):
    r = store.create({})
    store.set_status(r["run_id"], "running")
    store.set_status(r["run_id"], "done")
    assert store.get(r["run_id"])["status"] == "done"
    with pytest.raises(ValueError):
        store.set_status(r["run_id"], "bogus")


def test_attach_text_writes_file(store, tmp_path):
    import os
    r = store.create({})
    store.attach_text(r["run_id"], "log", "sim.log", "hello\nworld\n")
    run = store.get(r["run_id"])
    path = run["artifacts"]["log"]
    assert os.path.exists(path)
    with open(path) as f:
        assert "hello" in f.read()


def test_attach_file_copies(store, tmp_path):
    src = tmp_path / "out.txt"
    src.write_text("metrics here")
    r = store.create({})
    store.attach_file(r["run_id"], "raw", str(src))
    assert "raw" in store.get(r["run_id"])["artifacts"]


def test_persistence_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.artifact.manager as m
    importlib.reload(m)
    s1 = m.RunStore()
    rid = s1.create({"test": "t"})["run_id"]
    s1.set_status(rid, "done")
    s2 = m.RunStore()
    assert s2.get(rid)["status"] == "done"


def test_unknown_run_raises(store):
    with pytest.raises(KeyError):
        store.set_status("run_nope", "done")


# ---- RPC over TCP ---------------------------------------------------

@pytest.fixture
def running_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    for mod in ("vfp_tunnel.sim.manager", "vfp_tunnel.artifact.manager"):
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


def test_rpc_run_lifecycle(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    r = call("run.create", {"run": {"test": "ac_loopgain"}}, host=host, port=port)
    rid = r["run"]["run_id"]
    call("run.set_status", {"run_id": rid, "status": "running"}, host=host, port=port)
    call("run.attach", {"run_id": rid, "label": "log", "text": "sim ok"},
         host=host, port=port)
    got = call("run.get", {"run_id": rid}, host=host, port=port)["run"]
    assert got["status"] == "running"
    assert "log" in got["artifacts"]


def test_rpc_run_import_result_links_and_evaluates(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    rid = call("run.create", {"run": {"test": "t"}}, host=host, port=port)["run"]["run_id"]
    res = call("run.import_result", {
        "run_id": rid,
        "metrics": {"PM_deg": 85},
        "constraints": {"PM_deg": {"max": 80}},
    }, host=host, port=port)
    assert res["run"]["status"] == "done"
    assert res["run"]["result_id"] == res["result"]["result_id"]
    assert res["result"]["constraints"]["overall"] == "fail"
    # the result is now the latest stored result
    latest = call("result.latest", {}, host=host, port=port)["result"]
    assert latest["result_id"] == res["result"]["result_id"]


def test_rpc_run_unknown_raises(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError
    host, port = running_tunnel
    with pytest.raises(JsonRpcError):
        call("run.get", {"run_id": "run_missing"}, host=host, port=port)

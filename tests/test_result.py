import json
import threading

import pytest


# ---- metrics --------------------------------------------------------

def test_extract_from_result_obj():
    from vfp_tunnel.sim.metrics import extract_metrics
    m = extract_metrics({"metrics": {"A0_dB": 100, "note": "x"}})
    assert m == {"A0_dB": 100.0} or m == {"A0_dB": 100}


def test_extract_from_flat_and_coerces():
    from vfp_tunnel.sim.metrics import extract_metrics
    m = extract_metrics({"PM_deg": "70.5", "bad": "n/a", "ok": 3})
    assert m["PM_deg"] == 70.5
    assert "bad" not in m
    assert m["ok"] == 3


def test_make_result_defaults():
    from vfp_tunnel.sim.metrics import make_result
    r = make_result({"metrics": {"x": 1}})
    assert r["schema_version"] == "0.1"
    assert r["source"] == "manual"
    assert r["result_id"].startswith("r_")
    assert r["metrics"] == {"x": 1}


# ---- parser ---------------------------------------------------------

def test_parse_json_file(tmp_path):
    from vfp_tunnel.sim.parser import parse_metrics_file
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"metrics": {"A0_dB": 101.4, "PM_deg": 85.2}}))
    assert parse_metrics_file(str(p)) == {"A0_dB": 101.4, "PM_deg": 85.2}


def test_parse_text_file(tmp_path):
    from vfp_tunnel.sim.parser import parse_metrics_file
    p = tmp_path / "r.txt"
    p.write_text("# header\nA0_dB=101.4\nPM_deg, 85.2\nUGB_MHz 62\n")
    m = parse_metrics_file(str(p))
    assert m == {"A0_dB": 101.4, "PM_deg": 85.2, "UGB_MHz": 62.0}


# ---- store ----------------------------------------------------------

def test_store_update_latest_persist(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.sim.manager as m
    importlib.reload(m)
    s1 = m.ResultStore()
    s1.update({"schema_version": "0.1", "metrics": {"x": 1}})
    s2 = m.ResultStore()
    assert s2.latest()["metrics"] == {"x": 1}


# ---- RPC over TCP ---------------------------------------------------

@pytest.fixture
def running_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.sim.manager as m
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


def test_rpc_result_update_and_latest(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    res = call("result.update",
               {"result": {"metrics": {"A0_dB": 101, "PM_deg": 85}}},
               host=host, port=port)
    assert res["result"]["metrics"]["A0_dB"] == 101
    latest = call("result.latest", {}, host=host, port=port)["result"]
    assert latest["metrics"]["PM_deg"] == 85


def test_rpc_result_update_attaches_constraints(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    res = call("result.update", {
        "result": {"metrics": {"PM_deg": 85}},
        "constraints": {"PM_deg": {"min": 65, "max": 80}},
    }, host=host, port=port)
    assert res["result"]["constraints"]["overall"] == "fail"


def test_rpc_constraint_check_uses_latest(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    call("result.update", {"result": {"metrics": {"A0_dB": 102, "PM_deg": 70}}},
         host=host, port=port)
    res = call("constraint.check",
               {"constraints": {"A0_dB": {"min": 100}, "PM_deg": {"max": 80}}},
               host=host, port=port)
    assert res["overall"] == "pass"
    assert res["source"] == "latest_result"


def test_rpc_constraint_check_explicit_metrics(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    res = call("constraint.check",
               {"constraints": {"UGB_MHz": {"min": 50}},
                "metrics": {"UGB_MHz": 40}},
               host=host, port=port)
    assert res["overall"] == "fail"
    assert res["source"] == "params"


def test_rpc_constraint_check_no_metrics_errors(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError
    host, port = running_tunnel
    with pytest.raises(JsonRpcError):
        call("constraint.check", {"constraints": {"x": {"min": 1}}},
             host=host, port=port)

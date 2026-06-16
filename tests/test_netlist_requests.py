"""Netlist over VFP's own channel (Phase 1): the tunnel stores a netlist request
and emits a `netlist.request` event a connected plugin services; the plugin posts
the deck via `netlist.complete`; the caller polls `netlist.get`. No external
netlister (vcli etc.)."""
import importlib

import pytest


# ---- store ----------------------------------------------------------

def test_store_create_complete_get():
    from vfp_tunnel.sim.netlist_requests import NetlistRequestStore
    s = NetlistRequestStore()
    cv = {"lib": "Project", "cell": "inv_tb", "view": "schematic"}
    req = s.create(cv, "Nominal")
    assert req["status"] == "pending"
    rid = req["request_id"]
    assert s.get(rid)["status"] == "pending"
    done = s.complete(rid, deck="/d.scs")
    assert done["status"] == "done" and done["deck"] == "/d.scs"
    assert s.get(rid)["status"] == "done"


def test_store_complete_error_and_unknown():
    from vfp_tunnel.sim.netlist_requests import NetlistRequestStore
    s = NetlistRequestStore()
    rid = s.create({"lib": "L", "cell": "C", "view": "v"})["request_id"]
    failed = s.complete(rid, error="boom")
    assert failed["status"] == "failed" and failed["error"] == "boom"
    assert s.complete("nope") is None
    assert s.get("nope") is None


# ---- daemon RPC round-trip ------------------------------------------

def _tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    for mod in ("vfp_tunnel.event.manager", "vfp_tunnel.sim.netlist_requests",
                "vfp_tunnel.daemon"):
        importlib.reload(importlib.import_module(mod))
    from vfp_tunnel.daemon import Tunnel
    return Tunnel("127.0.0.1", 0)


def test_netlist_request_emits_event_and_completes(tmp_path, monkeypatch):
    tun = _tunnel(tmp_path, monkeypatch)
    cv = {"lib": "Project", "cell": "inv_tb", "view": "schematic"}
    out = tun._m_netlist_request({"cellview": cv, "corner": "Nominal"})
    rid = out["request_id"]
    assert out["status"] == "pending"
    # a connected plugin would see this via event.wait/list
    req_ev = [e for e in tun.events.list()["events"] if e["type"] == "netlist.request"]
    assert req_ev and req_ev[-1]["payload"]["request_id"] == rid
    assert req_ev[-1]["payload"]["cellview"]["cell"] == "inv_tb"
    # plugin posts the deck back
    tun._m_netlist_complete({"request_id": rid, "deck": "/tmp/d/input.scs"})
    got = tun._m_netlist_get({"request_id": rid})["request"]
    assert got["status"] == "done" and got["deck"] == "/tmp/d/input.scs"


def test_netlist_complete_error(tmp_path, monkeypatch):
    tun = _tunnel(tmp_path, monkeypatch)
    rid = tun._m_netlist_request(
        {"cellview": {"lib": "L", "cell": "C", "view": "v"}})["request_id"]
    tun._m_netlist_complete({"request_id": rid, "error": "no maestro setup"})
    got = tun._m_netlist_get({"request_id": rid})["request"]
    assert got["status"] == "failed" and got["error"] == "no maestro setup"


def test_netlist_pending_lists_unserviced(tmp_path, monkeypatch):
    tun = _tunnel(tmp_path, monkeypatch)
    r1 = tun._m_netlist_request(
        {"cellview": {"lib": "L", "cell": "C1", "view": "v"}})["request_id"]
    tun._m_netlist_request({"cellview": {"lib": "L", "cell": "C2", "view": "v"}})
    assert tun._m_netlist_pending({})["count"] == 2     # what the plugin pulls
    tun._m_netlist_complete({"request_id": r1, "deck": "/d.scs"})
    pend = tun._m_netlist_pending({})
    assert pend["count"] == 1                            # serviced one drops out
    assert pend["requests"][0]["cellview"]["cell"] == "C2"


def test_netlist_bad_params(tmp_path, monkeypatch):
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError
    tun = _tunnel(tmp_path, monkeypatch)
    with pytest.raises(JsonRpcError):
        tun._m_netlist_request({"cellview": "notadict"})
    with pytest.raises(JsonRpcError):
        tun._m_netlist_get({"request_id": "nope"})
    with pytest.raises(JsonRpcError):
        tun._m_netlist_complete({"request_id": "nope", "deck": "/d"})

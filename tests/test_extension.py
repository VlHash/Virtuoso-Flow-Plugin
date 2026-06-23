"""Generic extension API: the namespace registry, the action channel store,
and the RPC roundtrip (discovery + request/service/result over real TCP)."""

import importlib
import threading

import pytest


# ---- registry / store (unit) ----------------------------------------

def test_registry_register_list_get():
    from vfp_tunnel.extension.registry import ExtensionRegistry
    reg = ExtensionRegistry()
    rec = reg.register("layout", ["runPrimitive", "exportContext"],
                       "layout actuators")
    assert rec["namespace"] == "layout"
    assert rec["methods"] == ["runPrimitive", "exportContext"]
    assert reg.knows("layout") is True
    assert reg.knows("nope") is False
    assert reg.get("layout")["description"] == "layout actuators"
    assert len(reg.list()) == 1


def test_registry_reregister_keeps_first_registered_at():
    from vfp_tunnel.extension.registry import ExtensionRegistry
    reg = ExtensionRegistry()
    first = reg.register("layout", ["a"])
    again = reg.register("layout", ["a", "b"], "more")
    assert again["registered_at"] == first["registered_at"]
    assert again["methods"] == ["a", "b"]


def test_registry_rejects_bad_input():
    from vfp_tunnel.extension.registry import ExtensionRegistry
    reg = ExtensionRegistry()
    with pytest.raises(ValueError):
        reg.register("")
    with pytest.raises(ValueError):
        reg.register("ns", methods=[1, 2])


def test_registry_unregister():
    from vfp_tunnel.extension.registry import ExtensionRegistry
    reg = ExtensionRegistry()
    reg.register("layout", [])
    assert reg.unregister("layout") is True
    assert reg.unregister("layout") is False
    assert reg.list() == []


def test_action_store_lifecycle():
    from vfp_tunnel.extension.registry import ActionStore
    st = ActionStore()
    act = st.create("layout", "runPrimitive", {"name": "widen_net"})
    aid = act["action_id"]
    assert act["status"] == "pending"
    assert [a["action_id"] for a in st.pending()] == [aid]
    assert st.pending("other") == []          # namespace filter
    done = st.complete(aid, result={"transaction_id": "t_1"})
    assert done["status"] == "done"
    assert st.pending() == []                 # no longer pending
    assert st.get(aid)["result"]["transaction_id"] == "t_1"


def test_action_store_error_and_unknown():
    from vfp_tunnel.extension.registry import ActionStore
    st = ActionStore()
    act = st.create("layout", "boom")
    err = st.complete(act["action_id"], error="nope")
    assert err["status"] == "failed"
    assert err["error"] == "nope"
    assert st.complete("act_unknown", result={}) is None
    assert st.get("act_unknown") is None


# ---- RPC over TCP ----------------------------------------------------

@pytest.fixture
def running_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
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


def test_rpc_extension_discovery_and_action_roundtrip(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel

    # before anything is registered: empty discovery, unserviced request
    assert call("extension.list", {}, host=host, port=port)["extensions"] == []
    unserviced = call("action.request",
                      {"namespace": "layout", "method": "runPrimitive"},
                      host=host, port=port)
    assert unserviced["serviced"] is False
    assert unserviced["status"] == "pending"

    # a servicer announces the layout namespace
    reg = call("extension.register",
               {"namespace": "layout",
                "methods": ["runPrimitive", "exportContext"],
                "description": "layout actuators"},
               host=host, port=port)
    assert reg["extension"]["methods"] == ["runPrimitive", "exportContext"]

    # discovery now lists it; a request is marked serviced
    exts = call("extension.list", {}, host=host, port=port)["extensions"]
    assert exts[0]["namespace"] == "layout"
    req = call("action.request",
               {"namespace": "layout", "method": "runPrimitive",
                "params": {"name": "widen_net", "net": "VDD", "width": 0.84}},
               host=host, port=port)
    aid = req["action_id"]
    assert req["serviced"] is True

    # the servicer pulls pending (the earlier unserviced request is pending too)
    pend = call("action.pending", {"namespace": "layout"},
                host=host, port=port)["actions"]
    mine = [a for a in pend if a["action_id"] == aid]
    assert mine and mine[0]["params"]["name"] == "widen_net"
    call("action.complete",
         {"action_id": aid, "result": {"status": "applied",
                                       "transaction_id": "t_abc"}},
         host=host, port=port)

    # the client polls the outcome
    act = call("action.get", {"action_id": aid}, host=host, port=port)["action"]
    assert act["status"] == "done"
    assert act["result"]["transaction_id"] == "t_abc"


def test_rpc_action_request_requires_namespace_and_method(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError, INVALID_PARAMS
    host, port = running_tunnel
    with pytest.raises(JsonRpcError) as ei:
        call("action.request", {"namespace": "layout"}, host=host, port=port)
    assert ei.value.code == INVALID_PARAMS


def test_rpc_action_get_unknown_raises(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError
    host, port = running_tunnel
    with pytest.raises(JsonRpcError):
        call("action.get", {"action_id": "act_nope"}, host=host, port=port)


def test_rpc_action_request_emits_event(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    call("action.request", {"namespace": "layout", "method": "exportContext"},
         host=host, port=port)
    evs = call("event.list", {"since": 0}, host=host, port=port)["events"]
    kinds = [e["type"] for e in evs]
    assert "action.request" in kinds

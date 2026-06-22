"""Design-context store + design.context RPC roundtrip."""

import importlib
import threading

import pytest

SAMPLE = {
    "schema_version": "0.1",
    "source": "test",
    "cellview": {"lib": "RFCOPA", "cell": "XOPA", "view": "schematic"},
    "instances": [
        {"name": "M3",
         "master": {"lib": "tsmcN65", "cell": "pmos", "view": "symbol"},
         "params": {"w": "1u", "l": "120n"},
         "nets": {"G": "Vbin", "D": "net_tail"}}
    ],
    "ports": [],
    "nets": [],
}


def _fresh_store(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    import vfp_tunnel.design.context as ctxmod
    importlib.reload(ctxmod)
    return ctxmod


def test_store_update_latest_and_persist(tmp_path, monkeypatch):
    ctxmod = _fresh_store(tmp_path, monkeypatch)
    store = ctxmod.ContextStore()
    assert store.latest() is None
    res = store.update(SAMPLE)
    assert res["stored"] is True
    assert store.latest()["cellview"]["cell"] == "XOPA"
    # a brand-new store recovers the latest from disk
    assert ctxmod.ContextStore().latest()["instances"][0]["name"] == "M3"
    # a timestamped snapshot was written alongside latest
    snaps = list(ctxmod.contexts_dir().glob("context_*.json"))
    assert len(snaps) == 1


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
    host, port = server.server_address[0], server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield host, port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_context_update_get_roundtrip(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    res = call("design.context.update", {"context": SAMPLE}, host=host, port=port)
    assert res["stored"] is True
    got = call("design.context.get", {}, host=host, port=port)["context"]
    assert got["cellview"]["cell"] == "XOPA"
    assert got["instances"][0]["params"]["w"] == "1u"


def test_context_with_layout_roundtrips(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    ctx = dict(SAMPLE)
    ctx["layout"] = {
        "cellview": {"lib": "RFCOPA", "cell": "XOPA", "view": "layout"},
        "bbox": [[0, 0], [12.5, 8.0]],
        "units": "um",
        "layers": [{"layer": "M1", "purpose": "drawing", "shapes": 42}],
        "vias": 31,
    }
    call("design.context.update", {"context": ctx}, host=host, port=port)
    got = call("design.context.get", {}, host=host, port=port)["context"]
    assert got["layout"]["vias"] == 31
    assert got["layout"]["layers"][0]["layer"] == "M1"


def test_context_with_lvs_roundtrips(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    ctx = dict(SAMPLE)
    ctx["cellview"] = {"lib": "Project", "cell": "inv", "view": "layout"}
    ctx["lvs"] = {
        "schema_version": "0.1",
        "schematic": {"lib": "Project", "cell": "inv", "view": "schematic"},
        "layout": {"lib": "Project", "cell": "inv", "view": "layout"},
        "status": "issues",
        "devices": {"matched": 2, "only_in_layout": [],
                    "only_in_schematic": ["PIN0"]},
        "net_mismatches": [
            {"inst_term": "M1.S",
             "schematic_group": ["M1.B", "M1.S"],
             "layout_group": ["M1.S"]},
        ],
    }
    call("design.context.update", {"context": ctx}, host=host, port=port)
    got = call("design.context.get", {}, host=host, port=port)["context"]
    assert got["lvs"]["status"] == "issues"
    assert got["lvs"]["devices"]["matched"] == 2
    assert got["lvs"]["net_mismatches"][0]["inst_term"] == "M1.S"


def test_context_update_rejects_non_object(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError, INVALID_PARAMS
    host, port = running_tunnel
    with pytest.raises(JsonRpcError) as ei:
        call("design.context.update", {"context": "nope"}, host=host, port=port)
    assert ei.value.code == INVALID_PARAMS

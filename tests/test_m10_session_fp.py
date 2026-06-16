import os
import sys
import threading
import time

import pytest

_FAKE = os.path.join(os.path.dirname(__file__), "fixtures", "fake_spectre.py")


@pytest.fixture
def running_tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    monkeypatch.setenv("VFP_SIM_CMD", "%s %s" % (sys.executable, _FAKE))
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    for m in ("vfp_tunnel.sim.job_store", "vfp_tunnel.sim.manager",
              "vfp_tunnel.artifact.manager", "vfp_tunnel.event.manager",
              "vfp_tunnel.session.registry", "vfp_tunnel.sim.runner"):
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


def _wait(call, host, port, jid, statuses, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = call("job.get", {"job_id": jid}, host=host, port=port)["job"]
        if job["status"] in statuses:
            return job
        time.sleep(0.1)
    raise AssertionError("job %s did not reach %s" % (jid, statuses))


_CLIENT = {"client": "vfp", "virtuoso_pid": "3500", "virtuoso_start": "998877",
           "display": ":0", "cds_lib": "/proj/cds.lib"}


def test_fingerprint_snapshotted_at_create(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    sid = call("session.register", {"client": _CLIENT}, host=host, port=port)["session_id"]
    job = call("job.create",
               {"job": {"test": "ac", "cellview": {"lib": "L", "cell": "C", "view": "schematic"}},
                "session_id": sid}, host=host, port=port)["job"]
    # raw id kept (owner's F.3) + durable fingerprint snapshotted onto the job
    assert job["session"] == sid
    assert job["session_fingerprint"]["virtuoso_pid"] == "3500"
    assert job["session_fingerprint"]["cds_lib"] == "/proj/cds.lib"


def test_fingerprint_stamped_into_result(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    sid = call("session.register", {"client": _CLIENT}, host=host, port=port)["session_id"]
    jid = call("job.create",
               {"job": {"test": "ac", "cellview": {"lib": "L", "cell": "C", "view": "schematic"}},
                "session_id": sid}, host=host, port=port)["job"]["job_id"]
    call("job.run", {"job_id": jid}, host=host, port=port)
    _wait(call, host, port, jid, ("done", "failed"))
    prov = call("result.latest", {}, host=host, port=port)["result"]["provenance"]
    assert prov["session"] == sid
    assert prov["session_fingerprint"]["virtuoso_pid"] == "3500"
    assert prov["session_fingerprint"]["display"] == ":0"


def test_no_session_or_unknown_id_is_graceful(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    # unknown session_id: keep the raw id, no fingerprint, no error
    job = call("job.create",
               {"job": {"test": "ac", "cellview": {"lib": "L", "cell": "C", "view": "schematic"}},
                "session_id": "s_ghost"}, host=host, port=port)["job"]
    assert job["session"] == "s_ghost"
    assert "session_fingerprint" not in job

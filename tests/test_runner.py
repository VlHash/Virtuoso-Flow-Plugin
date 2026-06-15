import json
import os
import sys
import threading
import time

import pytest

_FAKE = os.path.join(os.path.dirname(__file__), "fixtures", "fake_spectre.py")
_OK_CMD = json.dumps([sys.executable, _FAKE])


def _reload_sim(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import importlib
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    for mod in ("vfp_tunnel.sim.job_store", "vfp_tunnel.sim.manager",
                "vfp_tunnel.artifact.manager", "vfp_tunnel.event.manager",
                "vfp_tunnel.sim.runner"):
        importlib.reload(importlib.import_module(mod))
    return cfg


# ---- runner unit (direct) -------------------------------------------

def _runner(tmp_path, monkeypatch):
    _reload_sim(tmp_path, monkeypatch)
    from vfp_tunnel.sim.job_store import JobStore
    from vfp_tunnel.sim.manager import ResultStore
    from vfp_tunnel.artifact.manager import RunStore
    from vfp_tunnel.sim.runner import JobRunner
    jobs, results, runs = JobStore(), ResultStore(), RunStore()
    return jobs, results, runs, JobRunner(jobs, results, runs)


def test_runner_drives_job_to_done(tmp_path, monkeypatch):
    jobs, results, runs, runner = _runner(tmp_path, monkeypatch)
    jid = jobs.create({"test": "ac", "cellview": {"lib": "L", "cell": "C", "view": "schematic"}})["job_id"]
    done = runner.run(jid, [sys.executable, _FAKE])
    assert done["status"] == "done"
    assert done["result_id"]
    assert done["run_id"]
    # the result was stored with the parsed metrics
    assert results.latest()["metrics"]["A0_dB"] == 101.2


def test_runner_marks_failed_on_nonzero_exit(tmp_path, monkeypatch):
    jobs, results, runs, runner = _runner(tmp_path, monkeypatch)
    jid = jobs.create({"test": "ac"})["job_id"]
    job = runner.run(jid, [sys.executable, "-c", "import sys; sys.exit(3)"])
    assert job["status"] == "failed"
    assert "exited 3" in job["error"]


def test_runner_marks_failed_when_no_metrics(tmp_path, monkeypatch):
    jobs, results, runs, runner = _runner(tmp_path, monkeypatch)
    jid = jobs.create({"test": "ac"})["job_id"]
    job = runner.run(jid, [sys.executable, "-c", "print('did nothing')"])
    assert job["status"] == "failed"
    assert "metrics" in job["error"]


# ---- config: command is server-side only ----------------------------

def test_sim_cmd_from_env_only(tmp_path, monkeypatch):
    cfg = _reload_sim(tmp_path, monkeypatch, VFP_SIM_CMD=_OK_CMD)
    assert cfg.sim_cmd()[0] == sys.executable
    monkeypatch.delenv("VFP_SIM_CMD", raising=False)
    import importlib
    importlib.reload(cfg)
    assert cfg.sim_cmd() is None


def test_sim_cmd_json_array_preserves_backslashes(tmp_path, monkeypatch):
    # JSON array = exact argv; a Windows path with backslashes survives (POSIX
    # shlex would eat them -> the old "C:\\py\\python.exe" -> "C:pypython.exe").
    cfg = _reload_sim(tmp_path, monkeypatch,
                      VFP_SIM_CMD=json.dumps([r"C:\Py\python.exe", "x.py"]))
    assert cfg.sim_cmd() == [r"C:\Py\python.exe", "x.py"]


def test_sim_cmd_shlex_string_still_works(tmp_path, monkeypatch):
    cfg = _reload_sim(tmp_path, monkeypatch, VFP_SIM_CMD="mysim --flag val")
    assert cfg.sim_cmd() == ["mysim", "--flag", "val"]


# ---- RPC: job.run end-to-end ----------------------------------------

@pytest.fixture
def running_tunnel(tmp_path, monkeypatch):
    _reload_sim(tmp_path, monkeypatch, VFP_SIM_CMD=_OK_CMD)
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


def _wait_status(call, host, port, jid, statuses, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = call("job.get", {"job_id": jid}, host=host, port=port)["job"]
        if job["status"] in statuses:
            return job
        time.sleep(0.1)
    raise AssertionError("job %s did not reach %s" % (jid, statuses))


def test_rpc_job_run_end_to_end(running_tunnel):
    from vfp_tunnel.rpc.transport import call
    host, port = running_tunnel
    jid = call("job.create", {"job": {"test": "ac", "cellview":
              {"lib": "RFCOPA", "cell": "XOPA", "view": "schematic"}}},
              host=host, port=port)["job"]["job_id"]
    started = call("job.run", {"job_id": jid}, host=host, port=port)
    assert started["started"] is True
    job = _wait_status(call, host, port, jid, ("done", "failed"))
    assert job["status"] == "done"
    latest = call("result.latest", {}, host=host, port=port)["result"]
    assert latest["result_id"] == job["result_id"]
    assert latest["metrics"]["PM_deg"] == 72.0


def test_rpc_job_run_requires_configured_sim(tmp_path, monkeypatch):
    # no VFP_SIM_CMD -> job.run refuses
    _reload_sim(tmp_path, monkeypatch)   # VFP_SIM_CMD unset
    monkeypatch.delenv("VFP_SIM_CMD", raising=False)
    from vfp_tunnel.daemon import Tunnel
    from vfp_tunnel.rpc.transport import make_server, call
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError
    tun = Tunnel("127.0.0.1", 0)
    server = make_server("127.0.0.1", 0, tun.dispatcher)
    tun.server = server
    host, port = server.server_address
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        jid = call("job.create", {"job": {"test": "ac"}}, host=host, port=port)["job"]["job_id"]
        with pytest.raises(JsonRpcError):
            call("job.run", {"job_id": jid}, host=host, port=port)
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=2)

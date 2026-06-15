"""M10 F.3: the originating session (M10a's session_id) is bound onto the job at
job.create and stamped into result provenance.session by the runner."""
import importlib
import sys


# ---- daemon: bind session_id onto the job ---------------------------

def _tunnel(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    for mod in ("vfp_tunnel.sim.job_store", "vfp_tunnel.sim.manager",
                "vfp_tunnel.artifact.manager", "vfp_tunnel.event.manager",
                "vfp_tunnel.session.registry", "vfp_tunnel.session.manager",
                "vfp_tunnel.sim.runner", "vfp_tunnel.daemon"):
        importlib.reload(importlib.import_module(mod))
    from vfp_tunnel.daemon import Tunnel
    return Tunnel("127.0.0.1", 0)


def test_job_create_binds_session_from_params(tmp_path, monkeypatch):
    tun = _tunnel(tmp_path, monkeypatch)
    out = tun._m_job_create({
        "job": {"test": "ac",
                "cellview": {"lib": "L", "cell": "C", "view": "schematic"}},
        "session_id": "s_test"})
    assert out["reused"] is False
    assert out["job"]["session"] == "s_test"


def test_job_create_no_session_when_absent(tmp_path, monkeypatch):
    tun = _tunnel(tmp_path, monkeypatch)
    out = tun._m_job_create({"job": {"test": "ac"}})
    assert "session" not in out["job"]


# ---- runner: stamp session into provenance --------------------------

def _stores(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import vfp_tunnel.config as cfg
    importlib.reload(cfg)
    for mod in ("vfp_tunnel.sim.job_store", "vfp_tunnel.sim.manager",
                "vfp_tunnel.artifact.manager", "vfp_tunnel.sim.runner"):
        importlib.reload(importlib.import_module(mod))
    from vfp_tunnel.sim.job_store import JobStore
    from vfp_tunnel.sim.manager import ResultStore
    from vfp_tunnel.artifact.manager import RunStore
    from vfp_tunnel.sim.runner import JobRunner
    jobs, results, runs = JobStore(), ResultStore(), RunStore()
    return jobs, results, runs, JobRunner(jobs, results, runs)


def test_runner_stamps_session_into_provenance(tmp_path, monkeypatch):
    jobs, results, runs, runner = _stores(tmp_path, monkeypatch)
    cv = {"lib": "Project", "cell": "inv_tb", "view": "schematic"}
    jid = jobs.create({"test": "tran", "session": "s_run", "cellview": cv})["job_id"]
    code = (
        "import os, json;"
        "open(os.environ['VFP_METRICS_FILE'], 'w').write(json.dumps({"
        "'metrics': {'V_Y': 3.3},"
        "'provenance': {'netlist_hash': 'h', 'source_mode': 'reuse'}}))"
    )
    done = runner.run(jid, [sys.executable, "-c", code])
    assert done["status"] == "done", done.get("error")
    res = results.latest()
    assert res["provenance"]["session"] == "s_run"
    assert res["provenance"]["source_mode"] == "reuse"   # wrapper block preserved
    assert res["schema_version"] == "0.2"


def test_runner_session_provenance_without_wrapper_block(tmp_path, monkeypatch):
    # session is stamped even when the wrapper wrote no provenance block
    jobs, results, runs, runner = _stores(tmp_path, monkeypatch)
    jid = jobs.create({"test": "ac", "session": "s_only"})["job_id"]
    code = ("import os, json;"
            "open(os.environ['VFP_METRICS_FILE'], 'w').write("
            "json.dumps({'metrics': {'x': 1.0}}))")
    done = runner.run(jid, [sys.executable, "-c", code])
    assert done["status"] == "done", done.get("error")
    assert results.latest()["provenance"]["session"] == "s_only"

"""Delegated routing (代管 increment 2): the job runner runs an optional
server-configured netlist step (VFP_NETLIST_CMD) before the sim, so the wrapper
finds a fresh deck for unattended jobs. delegated_netlist.py reads the cellview
from VFP_JOB_* env when invoked by the runner (no args)."""
import importlib
import json
import pathlib
import sys

_SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import delegated_netlist as dn  # noqa: E402


# ---- config: VFP_NETLIST_CMD ----------------------------------------

def test_netlist_cmd_parsing(monkeypatch):
    import vfp_tunnel.config as cfg
    monkeypatch.setenv("VFP_NETLIST_CMD", json.dumps(["a", "b c"]))
    importlib.reload(cfg)
    assert cfg.netlist_cmd() == ["a", "b c"]
    monkeypatch.setenv("VFP_NETLIST_CMD", "mynl --x")
    importlib.reload(cfg)
    assert cfg.netlist_cmd() == ["mynl", "--x"]
    monkeypatch.delenv("VFP_NETLIST_CMD", raising=False)
    importlib.reload(cfg)
    assert cfg.netlist_cmd() is None


# ---- delegated_netlist.py main reads cellview from env --------------

def test_main_reads_cellview_from_env(monkeypatch):
    seen = {}
    monkeypatch.setattr(dn, "netlist",
                        lambda l, c, v, corner: seen.update(
                            lib=l, cell=c, view=v, corner=corner) or "/d.scs")
    monkeypatch.setenv("VFP_JOB_LIB", "Project")
    monkeypatch.setenv("VFP_JOB_CELL", "inv_tb")
    monkeypatch.setenv("VFP_JOB_VIEW", "schematic")
    monkeypatch.delenv("VFP_JOB_CORNER", raising=False)
    assert dn.main([]) == 0
    assert seen == {"lib": "Project", "cell": "inv_tb",
                    "view": "schematic", "corner": "Nominal"}


def test_main_missing_cellview_returns_2(monkeypatch):
    for k in ("VFP_JOB_LIB", "VFP_JOB_CELL", "VFP_JOB_VIEW"):
        monkeypatch.delenv(k, raising=False)
    assert dn.main([]) == 2


# ---- runner: netlist step before sim --------------------------------

def _runner(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
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


def test_runner_runs_netlist_before_sim(tmp_path, monkeypatch):
    # netlist step writes a marker; the sim requires it -> proves the order.
    nl = json.dumps([sys.executable, "-c", "open('netlisted', 'w').write('1')"])
    jobs, results, runs, runner = _runner(tmp_path, monkeypatch,
                                          VFP_NETLIST_CMD=nl)
    jid = jobs.create({"test": "tran",
                       "cellview": {"lib": "Project", "cell": "inv_tb",
                                    "view": "schematic"}})["job_id"]
    sim = [sys.executable, "-c",
           ("import os, json;"
            "assert os.path.exists('netlisted');"      # netlist ran first
            "open(os.environ['VFP_METRICS_FILE'], 'w').write("
            "json.dumps({'metrics': {'ok': 1}}))")]
    done = runner.run(jid, sim)
    assert done["status"] == "done", done.get("error")


def test_runner_fails_when_netlist_fails(tmp_path, monkeypatch):
    nl = json.dumps([sys.executable, "-c", "import sys; sys.exit(2)"])
    jobs, results, runs, runner = _runner(tmp_path, monkeypatch,
                                          VFP_NETLIST_CMD=nl)
    jid = jobs.create({"test": "ac"})["job_id"]
    sim = [sys.executable, "-c", "raise SystemExit('sim should not run')"]
    done = runner.run(jid, sim)
    assert done["status"] == "failed"
    assert "netlist command exited 2" in done["error"]

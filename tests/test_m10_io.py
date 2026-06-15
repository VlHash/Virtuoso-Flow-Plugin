import json
import os
import sys

import pytest


def _stores(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_HOME", str(tmp_path))
    import importlib
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
    return cfg, jobs, results, runs, JobRunner(jobs, results, runs)


# ---- F.1: runner pass-through ---------------------------------------

def test_runner_passes_cellview_via_env_and_jobjson(tmp_path, monkeypatch):
    cfg, jobs, results, runs, runner = _stores(tmp_path, monkeypatch)
    cv = {"lib": "RFCOPA", "cell": "XOPA", "view": "schematic"}
    jid = jobs.create({"test": "ac", "cellview": cv})["job_id"]
    # The command fails (nonzero) unless every pass-through channel is present.
    code = (
        "import os, json;"
        "assert os.environ['VFP_JOB_CELL'] == 'XOPA';"
        "assert os.environ['VFP_JOB_LIB'] == 'RFCOPA';"
        "assert os.environ['VFP_JOB_FINGERPRINT'];"
        "assert os.environ['VFP_RUN_DIR'];"
        "j = json.load(open('job.json'));"
        "assert j['cellview']['view'] == 'schematic';"
        "open(os.environ['VFP_METRICS_FILE'], 'w').write(json.dumps({'metrics': {'ok': 1}}))"
    )
    done = runner.run(jid, [sys.executable, "-c", code])
    assert done["status"] == "done", done.get("error")
    # job.json is left in the run dir for inspection
    jf = cfg.runs_dir() / done["run_id"] / "job.json"
    assert json.loads(jf.read_text())["cellview"]["cell"] == "XOPA"


def test_runner_forwards_saved_at(tmp_path, monkeypatch):
    # M10c: the cellview's last-saved time rides the job to the wrapper as
    # VFP_JOB_SAVED_AT (and into job.json) -> result provenance.saved_at.
    cfg, jobs, results, runs, runner = _stores(tmp_path, monkeypatch)
    jid = jobs.create({"test": "ac", "saved_at": "Oct 13 08:30:26 2025"})["job_id"]
    code = (
        "import os, json;"
        "assert os.environ['VFP_JOB_SAVED_AT'] == 'Oct 13 08:30:26 2025';"
        "assert json.load(open('job.json'))['saved_at'] == 'Oct 13 08:30:26 2025';"
        "open(os.environ['VFP_METRICS_FILE'], 'w').write(json.dumps({'metrics': {'ok': 1}}))"
    )
    done = runner.run(jid, [sys.executable, "-c", code])
    assert done["status"] == "done", done.get("error")


def test_runner_metrics_file_env_name_honored(tmp_path, monkeypatch):
    monkeypatch.setenv("VFP_SIM_METRICS_FILE", "out.json")
    cfg, jobs, results, runs, runner = _stores(tmp_path, monkeypatch)
    jid = jobs.create({"test": "ac"})["job_id"]
    code = ("import os, json;"
            "open(os.environ['VFP_METRICS_FILE'], 'w').write(json.dumps({'metrics': {'x': 2}}))")
    # runner default metrics_file is 'metrics.json'; pass the configured one
    done = runner.run(jid, [sys.executable, "-c", code], metrics_file="out.json")
    assert done["status"] == "done", done.get("error")
    assert results.latest()["metrics"]["x"] == 2


# ---- D: NaN/Inf guard at the metrics boundary -----------------------

def test_extract_metrics_drops_non_finite():
    from vfp_tunnel.sim.metrics import extract_metrics
    m = extract_metrics({
        "A0_dB": 101.2,
        "PM_deg": float("nan"),
        "UGB": float("inf"),
        "X": "-inf",
        "Y": "nan",
        "Z": "42",
    })
    assert m == {"A0_dB": 101.2, "Z": 42.0}


def test_make_result_has_no_bare_nan():
    import math
    from vfp_tunnel.sim.metrics import make_result
    r = make_result({"metrics": {"good": 1.0, "bad": float("nan")}})
    assert "bad" not in r["metrics"]
    assert all(math.isfinite(v) for v in r["metrics"].values())

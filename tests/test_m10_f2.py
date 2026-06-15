"""M10 F.2: merge the wrapper's provenance / metric_quality blocks into the
stored result (schema 0.2). Parser reads the blocks, make_result bumps the
version, the runner carries them through."""
import importlib
import json
import sys


# ---- parser: read the schema-0.2 blocks -----------------------------

def test_parse_result_file_extracts_blocks(tmp_path):
    from vfp_tunnel.sim.parser import parse_result_file
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({
        "metrics": {"V_Y": 3.3},
        "provenance": {"netlist_hash": "abc", "source_mode": "reuse",
                       "cellview": {"lib": "L", "cell": "C", "view": "schematic"}},
        "metric_quality": {"GM_dB": "unconditional"},
    }), encoding="utf-8")
    out = parse_result_file(str(p))
    assert out["metrics"] == {"V_Y": 3.3}
    assert out["provenance"]["source_mode"] == "reuse"
    assert out["metric_quality"] == {"GM_dB": "unconditional"}


def test_parse_result_file_text_metrics_only(tmp_path):
    from vfp_tunnel.sim.parser import parse_result_file
    p = tmp_path / "m.txt"
    p.write_text("A0_dB=101.2\nPM_deg=72\n", encoding="utf-8")
    out = parse_result_file(str(p))
    assert out["metrics"] == {"A0_dB": 101.2, "PM_deg": 72.0}
    assert "provenance" not in out and "metric_quality" not in out


def test_parse_result_file_drops_empty_blocks(tmp_path):
    from vfp_tunnel.sim.parser import parse_result_file
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({"metrics": {"x": 1}, "metric_quality": {}}),
                 encoding="utf-8")
    assert "metric_quality" not in parse_result_file(str(p))


def test_parse_metrics_file_backcompat(tmp_path):
    from vfp_tunnel.sim.parser import parse_metrics_file
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({"metrics": {"x": 2.0},
                             "provenance": {"source_mode": "reuse"}}),
                 encoding="utf-8")
    assert parse_metrics_file(str(p)) == {"x": 2.0}


# ---- make_result: schema version ------------------------------------

def test_make_result_schema_02_when_provenance():
    from vfp_tunnel.sim.metrics import make_result
    r = make_result({"metrics": {"x": 1.0}, "provenance": {"source_mode": "reuse"}})
    assert r["schema_version"] == "0.2"
    assert r["provenance"]["source_mode"] == "reuse"


def test_make_result_schema_02_when_quality():
    from vfp_tunnel.sim.metrics import make_result
    r = make_result({"metrics": {"x": 1.0}, "metric_quality": {"GM": "unconditional"}})
    assert r["schema_version"] == "0.2"


def test_make_result_schema_01_without_blocks():
    from vfp_tunnel.sim.metrics import make_result
    assert make_result({"metrics": {"x": 1.0}})["schema_version"] == "0.1"


# ---- runner: merge into the stored result ---------------------------

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
    return cfg, jobs, results, runs, JobRunner(jobs, results, runs)


def test_runner_merges_provenance_and_quality(tmp_path, monkeypatch):
    cfg, jobs, results, runs, runner = _stores(tmp_path, monkeypatch)
    cv = {"lib": "Project", "cell": "inv_tb", "view": "schematic"}
    jid = jobs.create({"test": "tran", "cellview": cv})["job_id"]
    code = (
        "import os, json;"
        "open(os.environ['VFP_METRICS_FILE'], 'w').write(json.dumps({"
        "'metrics': {'V_Y': 3.3},"
        "'provenance': {'netlist_hash': 'h1', 'source_mode': 'reuse',"
        " 'cellview': {'lib': 'Project', 'cell': 'inv_tb', 'view': 'schematic'}},"
        "'metric_quality': {'GM_dB': 'unconditional'}}))"
    )
    done = runner.run(jid, [sys.executable, "-c", code])
    assert done["status"] == "done", done.get("error")
    res = results.latest()
    assert res["schema_version"] == "0.2"
    assert res["metrics"]["V_Y"] == 3.3
    assert res["provenance"]["source_mode"] == "reuse"
    assert res["provenance"]["cellview"]["cell"] == "inv_tb"
    assert res["metric_quality"] == {"GM_dB": "unconditional"}


def test_runner_metrics_only_stays_01(tmp_path, monkeypatch):
    cfg, jobs, results, runs, runner = _stores(tmp_path, monkeypatch)
    jid = jobs.create({"test": "ac"})["job_id"]
    code = ("import os, json;"
            "open(os.environ['VFP_METRICS_FILE'], 'w').write("
            "json.dumps({'metrics': {'x': 1.0}}))")
    done = runner.run(jid, [sys.executable, "-c", code])
    assert done["status"] == "done", done.get("error")
    assert results.latest()["schema_version"] == "0.1"

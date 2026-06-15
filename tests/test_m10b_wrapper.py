"""M10b cellview-specific real-spectre wrapper (scripts/cellview_spectre_job.py).

Covers the locally verifiable surface: F.1 env/job.json parsing, reuse-mode
netlisting, the spectre invocation wiring (fake binary), PSF parse, the
metric_quality split, provenance, and NaN-safe output. The `si` netlist path
and real-design measurement extraction are server-verified (Project/inv_tb),
not here.
"""
import json
import os
import pathlib
import subprocess
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / "scripts"
_FAKE_PSF = _ROOT / "tests" / "fixtures" / "fake_spectre_psf.py"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import cellview_spectre_job as cj  # noqa: E402


# ---- pure-function units --------------------------------------------

def test_classify_margin_nan_is_unconditional():
    assert cj.classify("GM_dB", float("nan")) == "unconditional"
    assert cj.classify("PM_deg", float("nan")) == "unconditional"


def test_classify_gain_sentinel_is_saturated():
    assert cj.classify("A0_dB", 999.0) == "saturated"
    # a large but non-gain metric is not a sentinel (UGB can exceed 999 MHz)
    assert cj.classify("UGB_MHz", 1200.0) is None


def test_classify_normal_metric_is_none():
    assert cj.classify("V_mid", 0.5) is None
    assert cj.classify("PM_deg", 72.0) is None


def test_split_metrics_drops_non_finite_keeps_finite():
    raw = {"A0_dB": 101.2, "GM_dB": float("nan"),
           "UGB": float("inf"), "V_mid": 0.5}
    metrics, quality = cj.split_metrics(raw)
    assert metrics == {"A0_dB": 101.2, "V_mid": 0.5}
    assert quality == {"GM_dB": "unconditional", "UGB": "undefined"}


_TRAN_PSF = '''HEADER
"PSFversion" "1.00"
SWEEP
"time" "s" PROP(
"key" "sweep"
)
TRACE
"A" "V"
"VDD" "V"
"Y" "V"
"I0:p" "I"
VALUE
"time" 0.0
"A" 0.0
"VDD" 3.3
"Y" 3.3
"I0:p" 1.0e-09
"time" 6.0e-06
"A" 0.0
"VDD" 3.3
"Y" 3.299999458127076
"I0:p" -1.164e-07
END
'''


def test_parse_tran_final_values_and_units(tmp_path):
    psf = tmp_path / "psf"
    psf.mkdir()
    (psf / "tran.tran.tran").write_text(_TRAN_PSF, encoding="utf-8")
    raw = cj.measure(str(psf), "tran")
    assert raw["V_Y"] == 3.299999458127076   # inverter output settled high
    assert raw["V_VDD"] == 3.3
    assert raw["V_A"] == 0.0
    assert raw["I_I0_p"] == -1.164e-07        # current trace gets the I_ prefix
    assert "time" not in raw                  # the sweep var is not a metric


def test_provenance_hashes_deck_and_records_cellview(tmp_path):
    deck = tmp_path / "input.scs"
    deck.write_text("simulator lang=spectre\n", encoding="utf-8")
    job = {"lib": "L", "cell": "C", "view": "schematic", "fingerprint": "fp1"}
    prov = cj.provenance(job, str(deck), "reuse")
    assert prov["source_mode"] == "reuse"
    assert prov["cellview"] == {"lib": "L", "cell": "C", "view": "schematic"}
    assert len(prov["netlist_hash"]) == 64  # sha256 hex
    assert prov["fingerprint"] == "fp1"


def test_read_job_env_first_then_jobjson(tmp_path, monkeypatch):
    # env carries lib/test; job.json fills the rest (cell/view)
    (tmp_path / "job.json").write_text(json.dumps({
        "job_id": "j1", "test": "ac", "inputs_fingerprint": "fp",
        "cellview": {"lib": "WRONG", "cell": "XOPA", "view": "schematic"}}),
        encoding="utf-8")
    monkeypatch.setenv("VFP_RUN_DIR", str(tmp_path))
    monkeypatch.setenv("VFP_JOB_LIB", "RFCOPA")
    monkeypatch.delenv("VFP_JOB_CELL", raising=False)
    monkeypatch.delenv("VFP_JOB_VIEW", raising=False)
    job = cj.read_job()
    assert job["lib"] == "RFCOPA"          # env wins
    assert job["cell"] == "XOPA"           # filled from job.json
    assert job["view"] == "schematic"


def test_netlist_defaults_to_reuse(tmp_path, monkeypatch):
    deck = tmp_path / "d.scs"
    deck.write_text("simulator lang=spectre\n", encoding="utf-8")
    monkeypatch.delenv("VFP_NETLIST_MODE", raising=False)
    monkeypatch.setenv("VFP_REUSE_NETLIST", str(deck))
    job = {"run_dir": str(tmp_path), "lib": "L", "cell": "C", "view": "v"}
    path, mode = cj.netlist(job)
    assert mode == "reuse"           # deck assembled upstream, wrapper sims it
    assert path == str(deck)


# ---- reuse-mode end to end (fake spectre) ---------------------------

def _run_wrapper(run_dir, env):
    base = dict(os.environ)
    base.update(env)
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "cellview_spectre_job.py")],
        cwd=str(run_dir), env=base,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, (proc.stdout or b"").decode("utf-8", "replace")


def _reuse_env(tmp_path, **extra):
    deck = tmp_path / "tb.scs"
    deck.write_text("simulator lang=spectre\nsave mid\n", encoding="utf-8")
    env = {
        "VFP_RUN_DIR": str(tmp_path),
        "VFP_METRICS_FILE": "metrics.json",
        "VFP_JOB_LIB": "RFCOPA", "VFP_JOB_CELL": "XOPA",
        "VFP_JOB_VIEW": "schematic", "VFP_JOB_TEST": "dc",
        "VFP_JOB_FINGERPRINT": "fp-abc",
        "VFP_NETLIST_MODE": "reuse",
        "VFP_REUSE_NETLIST": str(deck),
        "VFP_SPECTRE_CMD": json.dumps([sys.executable, str(_FAKE_PSF)]),
    }
    env.update(extra)
    return env


def test_reuse_mode_writes_metrics_provenance_quality(tmp_path):
    env = _reuse_env(tmp_path)
    code, out = _run_wrapper(tmp_path, env)
    assert code == 0, out
    res = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert res["metrics"]["V_mid"] == 0.5
    assert res["metrics"]["V_out"] == 0.9
    assert res["provenance"]["source_mode"] == "reuse"
    assert res["provenance"]["cellview"]["cell"] == "XOPA"
    assert len(res["provenance"]["netlist_hash"]) == 64
    assert res["metric_quality"] == {}        # all finite -> no flags


def test_reuse_mode_honors_metrics_file_env(tmp_path):
    env = _reuse_env(tmp_path, VFP_METRICS_FILE="out.json")
    code, out = _run_wrapper(tmp_path, env)
    assert code == 0, out
    assert (tmp_path / "out.json").exists()
    assert not (tmp_path / "metrics.json").exists()


def test_reuse_mode_non_finite_becomes_quality_not_nan(tmp_path):
    env = _reuse_env(tmp_path, VFP_FAKE_VMID="nan")
    code, out = _run_wrapper(tmp_path, env)
    assert code == 0, out
    text = (tmp_path / "metrics.json").read_text(encoding="utf-8")
    assert "NaN" not in text                  # never on the wire
    res = json.loads(text)
    assert "V_mid" not in res["metrics"]      # dropped from numeric metrics
    assert res["metric_quality"]["V_mid"] == "undefined"
    assert res["metrics"]["V_out"] == 0.9


def test_spectre_failure_propagates_nonzero(tmp_path):
    env = _reuse_env(tmp_path, VFP_FAKE_FAIL="1")
    code, out = _run_wrapper(tmp_path, env)
    assert code == 1


def test_reuse_missing_netlist_fails_clearly(tmp_path):
    env = _reuse_env(tmp_path)
    env["VFP_REUSE_NETLIST"] = str(tmp_path / "does_not_exist.scs")
    code, out = _run_wrapper(tmp_path, env)
    assert code == 1
    assert "reuse netlist not found" in out

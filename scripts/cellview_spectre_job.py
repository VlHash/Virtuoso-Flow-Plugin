#!/usr/bin/env python3
"""M10b: cellview-specific real-Spectre VFP_SIM_CMD wrapper.

Unlike scripts/real_spectre_job.py (which sims a FIXED resistive divider to
prove the M9 closed loop drives a *real* Spectre binary), this wrapper
simulates the JOB'S ACTUAL cellview. It consumes the runner job-context
pass-through (collab M10 F.1, PR #39):

  env    VFP_JOB_LIB / VFP_JOB_CELL / VFP_JOB_VIEW / VFP_JOB_TEST,
         VFP_JOB_ID, VFP_JOB_FINGERPRINT, VFP_RUN_DIR, VFP_METRICS_FILE
  file   $VFP_RUN_DIR/job.json  {job_id, test, inputs_fingerprint, cellview}

It writes $VFP_METRICS_FILE (in the run dir) as

  {"metrics": {...}, "provenance": {...}, "metric_quality": {...}}

The runner's parse path takes `metrics` today; collab F.2 merges
`provenance`/`metric_quality` into the result (schema 0.2). Writing them now is
forward-compatible (harmless until F.2 — they are simply ignored).

Netlisting strategy (owner design, 2026-06-15): the wrapper SIMS a deck that
was assembled upstream; it does not assemble one itself. A complete fresh deck
(design + PDK models + analyses + options) only comes from an ADE/OCEAN
netlister (plain `si` emits the design netlist only), so deck assembly is
layered above the wrapper in two modes, both routing netlisting through a
persistent Virtuoso session so its framework license is reused, not re-checked:
  - attended (zhishou):   the VFP plugin triggers createNetlist inside the
                          user's live Virtuoso session (reuses that session's
                          license, no new checkout) and writes the deck.
  - delegated (daiguan):  a persistent headless Virtuoso/OCEAN service netlists
                          (one license checkout, reused across runs).
Either way the assembled deck path is handed to the wrapper:

  VFP_NETLIST_MODE=reuse  (default) sim the provided deck (VFP_REUSE_NETLIST)
  VFP_NETLIST_MODE=si     experimental; wrapper-internal `si` emits only the
                          design netlist (no models/analyses) -> not runnable on
                          its own. Kept for experiments; prefer reuse.

VERIFIED locally (tests/test_m10b_wrapper.py): env/job.json parsing, reuse-mode,
the spectre invocation wiring (fake binary), PSF parse, provenance,
metric_quality split, NaN-safe output.

NEEDS SERVER VERIFICATION (meow@…, against Project/inv_tb, known-good): the `si`
invocation (si.env + PDK model include + corner) and real-design measurement
extraction. The `si` command below is a best guess — run it on the server and
correct it before relying on si-mode.
"""
import glob
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import sys

# Real Spectre is invoked by full path (its rpath supplies the Cadence libs, so
# no LD_LIBRARY_PATH is needed) with CDS_LIC_FILE pointing at the license. Both
# overridable for portability; VFP_SPECTRE_CMD (full command, shell-split or a
# JSON list) takes precedence and is how the tests inject a fake binary.
SPECTRE = os.environ.get("VFP_SPECTRE_BIN",
                         "/opt/cadence/SPECTRE231/tools/bin/spectre")
CDS_LIC = os.environ.get("VFP_CDS_LIC_FILE",
                         "/opt/cadence/IC231/share/license/license.dat")

# Our gain-rail sentinel: a metric like A0_dB=999 means "saturated / clipped to
# the rail", not a literal 999 dB. It crosses as a number but is flagged in
# metric_quality so a consumer never mistakes it for a real measurement.
SENTINEL_DB = 999.0


# ---- job context (F.1 pass-through) ---------------------------------

def read_job():
    """Job context, env first (the guaranteed channel) with run_dir/job.json as
    a fallback (F.1 writes job.json best-effort, so env is authoritative)."""
    run_dir = os.environ.get("VFP_RUN_DIR") or os.getcwd()
    job = {
        "job_id":      os.environ.get("VFP_JOB_ID") or "",
        "test":        os.environ.get("VFP_JOB_TEST") or "",
        "fingerprint": os.environ.get("VFP_JOB_FINGERPRINT") or "",
        "lib":         os.environ.get("VFP_JOB_LIB") or "",
        "cell":        os.environ.get("VFP_JOB_CELL") or "",
        "view":        os.environ.get("VFP_JOB_VIEW") or "",
        "run_dir":     run_dir,
        "metrics_file": os.environ.get("VFP_METRICS_FILE") or "metrics.json",
    }
    if not (job["lib"] and job["cell"] and job["view"]):
        jf = os.path.join(run_dir, "job.json")
        if os.path.exists(jf):
            try:
                with open(jf, encoding="utf-8") as f:
                    data = json.load(f)
                cv = data.get("cellview") or {}
                job["lib"]  = job["lib"]  or cv.get("lib") or ""
                job["cell"] = job["cell"] or cv.get("cell") or ""
                job["view"] = job["view"] or cv.get("view") or ""
                job["test"] = job["test"] or data.get("test") or ""
                job["fingerprint"] = job["fingerprint"] or data.get("inputs_fingerprint") or ""
                job["job_id"] = job["job_id"] or data.get("job_id") or ""
            except (OSError, ValueError):
                pass
    return job


# ---- netlisting (configurable; never from a shell-supplied command) --

def netlist(job):
    """Produce a spectre-runnable deck for job's cellview. Returns (deck, mode).
    Default reuse: the deck is assembled upstream (attended createNetlist or a
    delegated headless service) and handed in via VFP_REUSE_NETLIST."""
    mode = os.environ.get("VFP_NETLIST_MODE", "reuse")
    if mode == "si":
        return netlist_via_si(job), "si"
    return netlist_via_reuse(job), "reuse"


def netlist_via_reuse(job):
    """Sim a complete deck assembled upstream (attended createNetlist or a
    delegated headless service). Resolution order:
      1. VFP_REUSE_NETLIST — an explicit deck path.
      2. attended convention — the in-session netlister (vfpNetlistCellView)
         writes the fresh deck under $VFP_NETLIST_DIR/<lib>__<cell>__<view>/
         netlist/input.scs, so the wrapper derives it from the F.1 cellview env
         with no per-job plumbing (zero collab change).
      3. <run_dir>/input.scs — a deck handed straight into the run dir.
    The deck must already resolve PDK models/corners (ADE/maestro decks do)."""
    p = os.environ.get("VFP_REUSE_NETLIST")
    if p and os.path.exists(p):
        return p
    base = os.environ.get("VFP_NETLIST_DIR")
    if base and job["lib"] and job["cell"] and job["view"]:
        key = "%s__%s__%s" % (job["lib"], job["cell"], job["view"])
        cand = os.path.join(base, key, "netlist", "input.scs")
        if os.path.exists(cand):
            return cand
    cand = os.path.join(job["run_dir"], "input.scs")
    if os.path.exists(cand):
        return cand
    raise RuntimeError("reuse netlist not found (set VFP_REUSE_NETLIST or VFP_NETLIST_DIR)")


def netlist_via_si(job):
    """EXPERIMENTAL standalone `si` netlister. Findings on Project/inv_tb
    (2026-06-15): `si` still checks out a Virtuoso Framework license, and it
    emits only the DESIGN netlist — the PDK model includes, analyses and
    simulatorOptions are ADE-layered, so the `si` deck is not runnable on its
    own. The supported path is upstream deck assembly (attended createNetlist /
    delegated headless service) feeding reuse-mode. Kept for experiments only.
    """
    run_dir = job["run_dir"]
    lib, cell, view = job["lib"], job["cell"], job["view"]
    if not (lib and cell and view):
        raise RuntimeError("no cellview to netlist (lib/cell/view missing)")
    si_bin = os.environ.get("VFP_SI_BIN", "si")
    cmd = [si_bin, run_dir, "-batch", "-command", "netlist",
           "-cellview", lib, cell, view]
    proc = subprocess.run(cmd, cwd=run_dir, env=dict(os.environ),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError("si netlist failed:\n" +
                           (proc.stdout or b"").decode("utf-8", "replace")[-800:])
    for cand in (os.path.join(run_dir, "input.scs"),
                 os.path.join(run_dir, "netlist", "input.scs")):
        if os.path.exists(cand):
            return cand
    raise RuntimeError("si produced no input.scs under %s" % run_dir)


# ---- spectre + measurement ------------------------------------------

def _spectre_base():
    cmd = os.environ.get("VFP_SPECTRE_CMD")
    if cmd:
        cmd = cmd.strip()
        return json.loads(cmd) if cmd.startswith("[") else shlex.split(cmd)
    return [SPECTRE]


def run_spectre(deck_path, run_dir):
    """Run Spectre on the deck; returns the psf dir. rpath supplies the libs
    (no LD_LIBRARY_PATH); CDS_LIC_FILE points at the license."""
    psf_dir = os.path.join(run_dir, "psf")
    env = dict(os.environ, CDS_LIC_FILE=CDS_LIC)
    cmd = _spectre_base() + [deck_path,
                             "+log", os.path.join(run_dir, "spectre.out"),
                             "-format", "psfascii", "-raw", psf_dir]
    proc = subprocess.run(cmd, cwd=run_dir, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        sys.stderr.write((proc.stdout or b"").decode("utf-8", "replace")[-800:])
        raise RuntimeError("spectre exited %d" % proc.returncode)
    return psf_dir


def _san(name):
    return re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_")


def _parse_psf_ascii_final(path):
    """Final-sweep-point values from a sectioned PSF-ASCII analysis file
    (tran/ac/dc sweep). TRACE gives the unit per signal; VALUE is laid out
    point-by-point, so the last value seen for each signal is its final-time
    value. Returns {prefixed_name: float} (V_/I_ from the unit)."""
    units, last = {}, {}
    section = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if line in ("HEADER", "TYPE", "SWEEP", "TRACE", "VALUE", "END"):
                section = line
                continue
            if section == "TRACE":
                m = re.match(r'"([^"]+)"\s+"([^"]+)"', line)
                if m:
                    units[m.group(1)] = m.group(2)
            elif section == "VALUE":
                m = re.match(r'"([^"]+)"\s+(\S+)\s*$', line)
                if m and m.group(1) in units:
                    try:
                        last[m.group(1)] = float(m.group(2))
                    except ValueError:
                        last[m.group(1)] = float("nan")
    out = {}
    for name, val in last.items():
        unit = units.get(name, "")
        prefix = "V_" if unit == "V" else "I_" if unit == "I" else ""
        out[prefix + _san(name)] = val
    return out


def measure(psf_dir, test):
    """Scalar metrics from the PSF output (may include non-finite values, which
    become metric_quality, never a bare NaN).

    Handles two PSF-ASCII shapes: a flat dcOp.dc ("node" "V" value) and a
    sectioned analysis file (tran/ac/dc sweep) whose final sweep point we take.
    Real op-amp measures (A0_dB/PM/UGB) are design-specific post-processing that
    come later (M10c+); these final-time node values prove the path on inv_tb."""
    raw = {}
    dc = os.path.join(psf_dir, "dcOp.dc")
    if os.path.exists(dc):
        with open(dc, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(r'\s*"([^"]+)"\s+"V"\s+(\S+)', line)
                if not m:
                    continue
                try:
                    raw["V_" + _san(m.group(1))] = float(m.group(2))
                except ValueError:
                    raw["V_" + _san(m.group(1))] = float("nan")
    for fn in sorted(glob.glob(os.path.join(psf_dir, "*.tran*")) +
                     glob.glob(os.path.join(psf_dir, "*.ac")) +
                     glob.glob(os.path.join(psf_dir, "*.dc"))):
        if fn.endswith("dcOp.dc"):
            continue
        raw.update(_parse_psf_ascii_final(fn))
    return raw


# ---- metric_quality: non-finite / sentinel -> qualitative tag --------
# Producer-side semantics (owner-owned per M10c); schema 0.2 (collab F.2) will
# formalise the field. Keep these isolated so they are easy to adjust then.

def _is_margin(name):
    return name.upper().startswith(("GM", "PM"))


def _is_gain(name):
    return "dB" in name or name.upper().startswith(("A0", "GAIN"))


def classify(name, value):
    """Qualitative tag for a measurement that should not cross as a bare number,
    or None if it is a normal finite metric."""
    if value is None:
        return "missing"
    if isinstance(value, float) and not math.isfinite(value):
        # a gain/phase margin that never crosses 0 dB is unconditionally stable,
        # not 'missing data'
        return "unconditional" if _is_margin(name) else "undefined"
    if _is_gain(name) and isinstance(value, (int, float)) \
            and not isinstance(value, bool) and abs(value) >= SENTINEL_DB:
        return "saturated"
    return None


def split_metrics(raw):
    """Partition raw measurements into finite numeric metrics + a
    metric_quality map. Non-finite values never cross as bare numbers (matches
    the runner's NaN guard); sentinels stay numeric but are also flagged."""
    metrics, quality = {}, {}
    for name, value in raw.items():
        tag = classify(name, value)
        if tag is not None:
            quality[name] = tag
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and math.isfinite(value):
            metrics[name] = float(value)
    return metrics, quality


# ---- provenance ------------------------------------------------------

def provenance(job, deck_path, mode):
    """What this result actually came from. netlist_hash digests the exact deck
    fed to spectre; cellview closes the content-only-fingerprint gap (identical
    content in two cells reuses one job — record which one it ran on)."""
    netlist_hash = ""
    try:
        with open(deck_path, "rb") as f:
            netlist_hash = hashlib.sha256(f.read()).hexdigest()
    except OSError:
        pass
    return {
        "netlist_hash": netlist_hash,
        "source_mode": mode,                       # "si" | "reuse"
        "cellview": {"lib": job["lib"], "cell": job["cell"], "view": job["view"]},
        # authoritative saved_at comes from SKILL (M10c, ddGetObjLastModify),
        # carried via env when that plumbing lands; null until then.
        "saved_at": os.environ.get("VFP_JOB_SAVED_AT") or None,
        "fingerprint": job["fingerprint"],
    }


def main():
    job = read_job()
    run_dir = job["run_dir"]
    try:
        deck_path, mode = netlist(job)
        run_spectre(deck_path, run_dir)
        raw = measure(os.path.join(run_dir, "psf"), job["test"])
    except RuntimeError as e:
        sys.stderr.write("cellview_spectre_job: %s\n" % e)
        return 1
    if not raw:
        sys.stderr.write("cellview_spectre_job: no measurements parsed\n")
        return 1

    metrics, quality = split_metrics(raw)
    out = {
        "metrics": metrics,
        "provenance": provenance(job, deck_path, mode),
        "metric_quality": quality,
    }
    mpath = os.path.join(run_dir, job["metrics_file"])
    with open(mpath, "w", encoding="utf-8") as f:
        # allow_nan=False enforces "NaN never on the wire" at the producer.
        json.dump(out, f, indent=2, allow_nan=False)
    print("cellview_spectre_job: %s/%s/%s -> %d metric(s), mode=%s" %
          (job["lib"], job["cell"], job["view"], len(metrics), mode))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""A real-Spectre VFP_SIM_CMD wrapper (the production counterpart of
tests/fixtures/fake_spectre.py). The job runner executes this in the job's
run dir; it runs a real Spectre simulation and writes metrics.json there.

This reference build is self-contained — it simulates a fixed resistive
divider — so it proves the runner drives a *real* Spectre binary end to end
(real license, real PSF, real parsed metric) rather than a stub. A
cellview-specific wrapper (netlist the job's actual design) additionally
needs the runner to pass the job's cellview through (see TODO); the divider
here keeps the M9 closed-loop proof independent of that.

Spectre is invoked by full path (its rpath supplies the Cadence libs, so no
LD_LIBRARY_PATH is needed) with CDS_LIC_FILE pointing at the license — both
overridable via env for portability.
"""
import json
import os
import re
import subprocess
import sys

SPECTRE = os.environ.get("VFP_SPECTRE_BIN",
                         "/opt/cadence/SPECTRE231/tools/bin/spectre")
CDS_LIC = os.environ.get("VFP_CDS_LIC_FILE",
                         "/opt/cadence/IC231/share/license/license.dat")

NETLIST = """simulator lang=spectre
save mid
V1 (in 0)   vsource dc=1 type=dc
R1 (in mid) resistor r=1k
R2 (mid 0)  resistor r=1k
dcOp dc
"""


def main():
    cwd = os.getcwd()
    with open(os.path.join(cwd, "tb.scs"), "w") as f:
        f.write(NETLIST)

    env = dict(os.environ, CDS_LIC_FILE=CDS_LIC)
    proc = subprocess.run(
        [SPECTRE, "tb.scs", "+log", "spectre.out",
         "-format", "psfascii", "-raw", "./psf"],
        cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log = (proc.stdout or b"").decode("utf-8", "replace")
    if proc.returncode != 0:
        sys.stderr.write(log[-800:])
        return 1

    # PSF-ASCII dcOp value line:  "mid" "V" 5.0e-01
    vmid = None
    dc = os.path.join(cwd, "psf", "dcOp.dc")
    if os.path.exists(dc):
        with open(dc) as f:
            for line in f:
                m = re.match(r'\s*"mid"\s+"V"\s+([-0-9.eE+]+)', line)
                if m:
                    vmid = float(m.group(1))
                    break
    if vmid is None:
        sys.stderr.write("real_spectre_job: could not parse V(mid) from PSF\n")
        return 1

    with open(os.path.join(cwd, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump({"metrics": {"V_mid": vmid, "spectre_ok": 1.0}}, f)
    print("real spectre: V(mid)=%g, wrote metrics.json" % vmid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

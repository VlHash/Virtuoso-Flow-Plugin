#!/usr/bin/env python3
"""Delegated (代管) netlist worker.

Drive a PERSISTENT headless Virtuoso over vcli to assemble a complete spectre
deck for a cellview, reusing that Virtuoso's already-held framework license (no
new checkout per run). The deck lands at the wrapper convention path
``$VFP_NETLIST_DIR/<lib>__<cell>__<view>/netlist/input.scs``, so the M10b
wrapper (cellview_spectre_job.py, reuse mode) sims it with no per-job plumbing.

This is the unattended counterpart of the attended (值守) path: instead of
running ``vfpNetlistCellView`` in the user's live session, it loads the same
``vfp_netlist.il`` into a separate persistent Virtuoso and calls it over vcli.
One vcli Virtuoso, one license, reused across runs.

Usage:
    python delegated_netlist.py <lib> <cell> <view> [corner]

Prerequisites:
  - A running vcli Virtuoso on the target (start it with the vcli daemon;
    see the vcli-bridge tooling). Key-based SSH.
  - vfp_utils.il + vfp_netlist.il present on the target under
    $VFP_REMOTE_SKILL_DIR.

Config (env, with defaults for the shared lab server):
  VFP_VCLI_TARGET        user@host           (meow@192.168.185.231)
  VFP_VCLI_BIN           remote vcli path    (/home/meow/.cargo/bin/vcli)
  VFP_VCLI_DAEMON        remote daemon path  (/home/meow/.cargo/bin/virtuoso-daemon)
  VFP_VCLI_SPECTRE_CMD   remote spectre      (/opt/cadence/SPECTRE231/bin/spectre)
  VFP_REMOTE_SKILL_DIR   dir with the .il    (/home/meow/Documents/VFP/skill)
"""
import json
import os
import subprocess
import sys

TARGET = os.environ.get("VFP_VCLI_TARGET", "meow@192.168.185.231")
VCLI = os.environ.get("VFP_VCLI_BIN", "/home/meow/.cargo/bin/vcli")
DAEMON = os.environ.get("VFP_VCLI_DAEMON", "/home/meow/.cargo/bin/virtuoso-daemon")
SPECTRE = os.environ.get("VFP_VCLI_SPECTRE_CMD",
                         "/opt/cadence/SPECTRE231/bin/spectre")
SKILL_DIR = os.environ.get("VFP_REMOTE_SKILL_DIR",
                           "/home/meow/Documents/VFP/skill")


def _q(s):
    """POSIX single-quote shell-quoting."""
    return "'" + str(s).replace("'", "'\\''") + "'"


def _vcli_exec(skill_expr, timeout=180):
    """Evaluate one SKILL expression in the persistent Virtuoso via vcli/ssh.
    Returns (ok, value_or_error)."""
    remote = ("RB_DAEMON_PATH=%s VB_SPECTRE_CMD=%s %s --quiet --format json "
              "skill exec %s"
              % (_q(DAEMON), _q(SPECTRE), _q(VCLI), _q(skill_expr)))
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "LogLevel=ERROR",
         "-o", "ConnectTimeout=10", TARGET, remote],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    out = (proc.stdout or b"").decode("utf-8", "replace").strip()
    try:
        res = json.loads(out)
    except ValueError:
        return False, out or ("ssh/vcli failed (exit %d)" % proc.returncode)
    if res.get("status") != "success" or res.get("errors"):
        return False, res.get("errors") or res
    return True, (res.get("output") or "").strip()


def netlist(lib, cell, view, corner="Nominal"):
    """Assemble the deck via the persistent Virtuoso; return the deck path or
    None. Loads the netlist module each call (idempotent; the functions persist
    in the session) then calls vfpNetlistCellView."""
    skill = (
        'progn( '
        'load("%s/vfp_utils.il") '
        'load("%s/vfp_netlist.il") '
        'vfpNetlistCellView(dbOpenCellViewByType("%s" "%s" "%s" "" "r") '
        '?corner "%s") )'
        % (SKILL_DIR, SKILL_DIR, lib, cell, view, corner)
    )
    ok, val = _vcli_exec(skill)
    if not ok:
        sys.stderr.write("delegated_netlist: %s\n" % (val,))
        return None
    deck = val.strip().strip('"')          # vcli returns the SKILL string quoted
    return deck or None


def main(argv):
    if not (3 <= len(argv) <= 4):
        sys.stderr.write(__doc__.split("Usage:")[1].split("\n\n")[0])
        return 2
    lib, cell, view = argv[0], argv[1], argv[2]
    corner = argv[3] if len(argv) == 4 else "Nominal"
    deck = netlist(lib, cell, view, corner)
    if not deck:
        return 1
    print(deck)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

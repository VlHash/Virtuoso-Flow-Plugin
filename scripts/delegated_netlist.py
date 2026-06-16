#!/usr/bin/env python3
"""Delegated (代管) netlist worker.

Assemble a complete spectre deck for a cellview through a PERSISTENT netlister,
for unattended jobs — reusing one already-held framework license (no new
checkout per run). The deck lands at the wrapper convention path
``$VFP_NETLIST_DIR/<lib>__<cell>__<view>/netlist/input.scs``, so the M10b
wrapper (cellview_spectre_job.py, reuse mode) sims it with no per-job plumbing.

This is the unattended counterpart of the attended (值守) path (vfpNetlistCellView
in the user's live session).

Pluggable backend (NOT vcli-only)
---------------------------------
A backend is any callable ``(lib, cell, view, corner) -> deck_path | None``.
Select it with ``VFP_DELEGATED_BACKEND`` (default ``vcli``):

  vcli              drive a persistent headless Virtuoso over vcli (default),
                    loading vfp_netlist.il and calling vfpNetlistCellView.
  command           run a server-configured command (VFP_DELEGATED_NETLIST_CMD,
                    JSON array or shlex string) with the cellview in the env —
                    for any non-vcli netlister (headless OCEAN, a site script).
  <module>:<func>   a custom Python backend (imported and called).

Or pass a callable to ``netlist(..., backend=fn)`` from your own code.

Usage:
    python delegated_netlist.py <lib> <cell> <view> [corner]

vcli backend config (env, shared-lab defaults):
  VFP_VCLI_TARGET / VFP_VCLI_BIN / VFP_VCLI_DAEMON / VFP_VCLI_SPECTRE_CMD
  VFP_REMOTE_SKILL_DIR   dir holding vfp_utils.il + vfp_netlist.il on the target
"""
import importlib
import json
import os
import shlex
import socket
import subprocess
import sys
import time

# ---- vcli backend (default) -----------------------------------------
# VFP_VCLI_TARGET: user@host for ssh, or empty/'local'/'localhost' to run vcli
# directly (co-located -- the common case when the tunnel runs on the vcli host).

TARGET = os.environ.get("VFP_VCLI_TARGET", "meow@192.168.185.231")
VCLI = os.environ.get("VFP_VCLI_BIN", "/home/meow/.cargo/bin/vcli")
DAEMON = os.environ.get("VFP_VCLI_DAEMON", "/home/meow/.cargo/bin/virtuoso-daemon")
SPECTRE = os.environ.get("VFP_VCLI_SPECTRE_CMD",
                         "/opt/cadence/SPECTRE231/bin/spectre")
SKILL_DIR = os.environ.get("VFP_REMOTE_SKILL_DIR",
                           "/home/meow/Documents/VFP/skill")

# ---- plugin backend: VFP's own tunnel <-> plugin channel ------------
TUNNEL_HOST = os.environ.get("VFP_HOST", "127.0.0.1")
TUNNEL_PORT = int(os.environ.get("VFP_PORT", "47891"))
PLUGIN_TIMEOUT = int(os.environ.get("VFP_PLUGIN_NETLIST_TIMEOUT", "120"))


def _q(s):
    """POSIX single-quote shell-quoting."""
    return "'" + str(s).replace("'", "'\\''") + "'"


def _is_local():
    return TARGET.strip().lower() in ("", "local", "localhost")


def _vcli_exec(skill_expr, timeout=180):
    """Evaluate one SKILL expression in the persistent Virtuoso via vcli.

    Local when VFP_VCLI_TARGET is empty/'local'/'localhost' -- vcli is
    co-located with the worker (the common delegated case: the tunnel and vcli
    on one host), so run it directly, no ssh. Otherwise go over ssh (vcli's
    dynamic port is not forwarded off the VM). Returns (ok, value_or_error)."""
    if _is_local():
        argv = [VCLI, "--quiet", "--format", "json", "skill", "exec", skill_expr]
        env = dict(os.environ, RB_DAEMON_PATH=DAEMON, VB_SPECTRE_CMD=SPECTRE)
        proc = subprocess.run(argv, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout)
    else:
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
        return False, out or ("vcli failed (exit %d)" % proc.returncode)
    if res.get("status") != "success" or res.get("errors"):
        return False, res.get("errors") or res
    return True, (res.get("output") or "").strip()


def vcli_backend(lib, cell, view, corner="Nominal"):
    """Default backend: load vfp_netlist.il into the persistent Virtuoso and
    call vfpNetlistCellView over vcli (idempotent load; functions persist)."""
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
        sys.stderr.write("delegated_netlist[vcli]: %s\n" % (val,))
        return None
    return (val.strip().strip('"') or None)   # vcli returns the SKILL string quoted


# ---- command backend (any non-vcli netlister, no code) --------------

def command_backend(lib, cell, view, corner="Nominal"):
    """Run a server-configured netlist command (VFP_DELEGATED_NETLIST_CMD, JSON
    array or shlex string) with the cellview in the env (VFP_JOB_LIB/CELL/VIEW/
    CORNER). The command assembles the deck (e.g. headless OCEAN, a site script)
    and prints the deck path on its last stdout line."""
    raw = os.environ.get("VFP_DELEGATED_NETLIST_CMD")
    if not raw:
        sys.stderr.write("delegated_netlist[command]: set VFP_DELEGATED_NETLIST_CMD\n")
        return None
    raw = raw.strip()
    argv = json.loads(raw) if raw.startswith("[") else shlex.split(raw)
    env = dict(os.environ, VFP_JOB_LIB=lib, VFP_JOB_CELL=cell,
               VFP_JOB_VIEW=view, VFP_JOB_CORNER=corner)
    try:
        proc = subprocess.run(argv, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=600)
    except OSError as e:
        sys.stderr.write("delegated_netlist[command]: %s\n" % e)
        return None
    out = (proc.stdout or b"").decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        sys.stderr.write(out[-800:] + "\n")
        return None
    return out.splitlines()[-1].strip() if out else None


# ---- plugin backend: netlist over VFP's own tunnel <-> plugin channel

def _tunnel_call(method, params=None, timeout=30):
    """Minimal newline-delimited JSON-RPC call to the VFP tunnel."""
    req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    with socket.create_connection((TUNNEL_HOST, TUNNEL_PORT), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall((json.dumps(req) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
    resp = json.loads(buf.split(b"\n", 1)[0].decode("utf-8", "replace"))
    if resp.get("error"):
        raise RuntimeError(resp["error"].get("message") or resp["error"])
    return resp.get("result") or {}


def plugin_backend(lib, cell, view, corner="Nominal"):
    """Netlist over VFP's OWN channel: ask the tunnel to request a netlist from a
    connected plugin (which assembles it via vfpNetlistCellView), then poll for
    the deck. No external netlister."""
    cv = {"lib": lib, "cell": cell, "view": view}
    try:
        rid = _tunnel_call("netlist.request",
                           {"cellview": cv, "corner": corner}).get("request_id")
    except (OSError, ValueError, RuntimeError) as e:
        sys.stderr.write("delegated_netlist[plugin]: %s\n" % e)
        return None
    if not rid:
        return None
    deadline = time.time() + PLUGIN_TIMEOUT
    while time.time() < deadline:
        try:
            r = _tunnel_call("netlist.get", {"request_id": rid}).get("request") or {}
        except (OSError, ValueError, RuntimeError) as e:
            sys.stderr.write("delegated_netlist[plugin]: %s\n" % e)
            return None
        if r.get("status") == "done":
            return r.get("deck") or None
        if r.get("status") == "failed":
            sys.stderr.write("delegated_netlist[plugin]: %s\n" % r.get("error"))
            return None
        time.sleep(0.5)
    sys.stderr.write("delegated_netlist[plugin]: timed out after %ss\n" % PLUGIN_TIMEOUT)
    return None


# ---- backend selection ----------------------------------------------

_BUILTIN_BACKENDS = {"vcli": vcli_backend, "command": command_backend,
                     "plugin": plugin_backend}


def resolve_backend(name=None):
    """Pick a netlist backend by name (default VFP_DELEGATED_BACKEND or 'vcli').
    A built-in name, or 'module:callable' for a custom extension."""
    name = name or os.environ.get("VFP_DELEGATED_BACKEND", "vcli")
    if name in _BUILTIN_BACKENDS:
        return _BUILTIN_BACKENDS[name]
    if ":" in name:
        mod, _, fn = name.partition(":")
        return getattr(importlib.import_module(mod), fn)
    raise ValueError("unknown delegated backend: %r" % name)


def netlist(lib, cell, view, corner="Nominal", backend=None):
    """Assemble the deck via the selected backend; return the deck path or None.
    `backend` is a callable, a backend name, or None (env / default vcli)."""
    fn = backend if callable(backend) else resolve_backend(backend)
    return fn(lib, cell, view, corner)


def main(argv):
    if len(argv) >= 3:
        lib, cell, view = argv[0], argv[1], argv[2]
        corner = argv[3] if len(argv) >= 4 else "Nominal"
    else:
        # runner invocation: the cellview rides VFP_JOB_* env (set by the
        # tunnel's _job_context), so VFP_NETLIST_CMD=delegated_netlist.py works
        # with no args.
        lib = os.environ.get("VFP_JOB_LIB")
        cell = os.environ.get("VFP_JOB_CELL")
        view = os.environ.get("VFP_JOB_VIEW")
        corner = os.environ.get("VFP_JOB_CORNER") or "Nominal"
        if not (lib and cell and view):
            sys.stderr.write("usage: delegated_netlist.py <lib> <cell> <view> "
                             "[corner]  (or set VFP_JOB_LIB/CELL/VIEW)\n")
            return 2
    deck = netlist(lib, cell, view, corner)
    if not deck:
        return 1
    print(deck)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""VFP Tunnel CLI (``vfp``).

Subcommands talk to a running daemon over JSON-RPC; ``tunnel start`` spawns
the daemon (``vfp_tunnel.daemon``) as a detached process. Pure stdlib,
Python 3.6+. See the tunnel README for the command set.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .config import (ensure_dirs, log_dir, resolve_host, resolve_port,
                     state_file)
from .rpc.jsonrpc import JsonRpcError
from .rpc.transport import call


# ---- helpers --------------------------------------------------------
def _read_state():
    p = state_file()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _endpoint(args):
    st = _read_state() or {}
    host = getattr(args, "host", None) or st.get("host") or resolve_host()
    port = getattr(args, "port", None) or st.get("port") or resolve_port()
    return host, int(port)


def _probe(host, port, timeout=1.5):
    """Return tunnel.status result if the daemon answers, else None."""
    try:
        return call("tunnel.status", {}, host=host, port=port, timeout=timeout)
    except (OSError, JsonRpcError):
        return None


def _fail(msg):
    sys.stderr.write("ERROR: %s\n" % msg)
    return 1


# ---- tunnel ---------------------------------------------------------
def cmd_tunnel_start(args):
    host = resolve_host(args.host)
    port = resolve_port(args.port)
    running = _probe(host, port)
    if running:
        print("VFP Tunnel already running on %s:%s (pid %s)"
              % (host, port, running.get("pid")))
        return 0
    ensure_dirs()
    if args.foreground:
        from .daemon import Tunnel
        print("VFP Tunnel starting in foreground on %s:%s (Ctrl-C to stop)"
              % (host, port))
        try:
            Tunnel(host, port).serve()
        except KeyboardInterrupt:
            pass
        return 0

    _spawn_daemon(host, port)
    deadline = time.time() + 8.0
    while time.time() < deadline:
        running = _probe(host, port)
        if running:
            print("VFP Tunnel started on %s:%s (pid %s)"
                  % (host, port, running.get("pid")))
            return 0
        time.sleep(0.2)
    return _fail("VFP Tunnel did not become ready; see %s"
                 % (log_dir() / "daemon.out"))


def _spawn_daemon(host, port):
    cmd = [sys.executable, "-m", "vfp_tunnel.daemon",
           "--host", host, "--port", str(port)]
    out = open(str(log_dir() / "daemon.out"), "ab")
    kwargs = {"stdout": out, "stderr": out, "stdin": subprocess.DEVNULL,
              "close_fds": True}
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def cmd_tunnel_stop(args):
    host, port = _endpoint(args)
    running = _probe(host, port)
    if not running:
        print("VFP Tunnel is not running.")
        return 0
    try:
        call("tunnel.shutdown", {}, host=host, port=port, timeout=2.0)
    except (OSError, JsonRpcError):
        pass
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not _probe(host, port):
            print("VFP Tunnel stopped.")
            return 0
        time.sleep(0.2)
    return _fail("tunnel still responding (pid %s)" % running.get("pid"))


def cmd_tunnel_status(args):
    host, port = _endpoint(args)
    running = _probe(host, port)
    if not running:
        print("VFP Tunnel: not running (endpoint %s:%s)" % (host, port))
        return 1
    print("VFP Tunnel: running")
    for k in ("version", "host", "port", "pid", "started_at", "uptime_s", "sessions"):
        if k in running:
            print("  %-11s %s" % (k + ":", running[k]))
    return 0


# ---- session --------------------------------------------------------
def cmd_session_list(args):
    host, port = _endpoint(args)
    try:
        res = call("session.list", {}, host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    sessions = res.get("sessions", [])
    if not sessions:
        print("No sessions registered.")
        return 0
    for s in sessions:
        client = s.get("client", {})
        label = client.get("client") or client.get("name") or "?"
        print("%s  %-24s  created=%s  last_seen=%s"
              % (s.get("session_id"), label, s.get("created_at"), s.get("last_seen")))
    return 0


def cmd_session_current(args):
    host, port = _endpoint(args)
    try:
        res = call("session.current", {}, host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    s = res.get("session")
    if not s:
        print("No current session.")
        return 0
    print(json.dumps(s, indent=2))
    return 0


def cmd_ping(args):
    host, port = _endpoint(args)
    try:
        res = call("session.ping", {"session_id": args.session_id},
                   host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    print("pong @ %s" % res.get("time"))
    return 0


# ---- context --------------------------------------------------------
def cmd_context_show(args):
    host, port = _endpoint(args)
    try:
        res = call("design.context.get", {}, host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    ctx = res.get("context")
    if not ctx:
        print("No design context stored yet.")
        return 0
    print(json.dumps(ctx, indent=2))
    return 0


def cmd_context_export(args):
    host, port = _endpoint(args)
    try:
        res = call("design.context.get", {}, host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    ctx = res.get("context")
    if not ctx:
        return _fail("no design context stored yet")
    out = args.out or "context.json"
    Path(out).write_text(json.dumps(ctx, indent=2), encoding="utf-8")
    print("wrote %s" % out)
    return 0


def cmd_context_import(args):
    try:
        with open(args.file, encoding="utf-8") as f:
            context = json.load(f)
    except (OSError, ValueError) as e:
        return _fail("could not read %s: %s" % (args.file, e))
    host, port = _endpoint(args)
    try:
        res = call("design.context.update", {"context": context}, host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    print("context stored: %s" % res.get("path"))
    return 0


# ---- parser ---------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(prog="vfp", description="VFP Tunnel CLI")
    p.add_argument("-v", "--version", action="version",
                   version="vfp %s" % __version__)
    groups = p.add_subparsers(dest="group")

    tunnel = groups.add_parser("tunnel", help="manage the tunnel daemon")
    tsub = tunnel.add_subparsers(dest="cmd")
    s = tsub.add_parser("start", help="start the daemon")
    s.add_argument("--host")
    s.add_argument("--port")
    s.add_argument("--foreground", action="store_true",
                   help="run in this process instead of detaching")
    s.set_defaults(func=cmd_tunnel_start)
    s = tsub.add_parser("stop", help="stop the daemon")
    s.add_argument("--host")
    s.add_argument("--port")
    s.set_defaults(func=cmd_tunnel_stop)
    s = tsub.add_parser("status", help="show daemon status")
    s.add_argument("--host")
    s.add_argument("--port")
    s.set_defaults(func=cmd_tunnel_status)

    session = groups.add_parser("session", help="inspect sessions")
    ssub = session.add_subparsers(dest="cmd")
    ssub.add_parser("list", help="list sessions").set_defaults(func=cmd_session_list)
    ssub.add_parser("current", help="show the most recent session").set_defaults(
        func=cmd_session_current)

    context = groups.add_parser("context", help="design context")
    csub = context.add_subparsers(dest="cmd")
    csub.add_parser("show", help="print the latest stored context").set_defaults(
        func=cmd_context_show)
    ce = csub.add_parser("export", help="write the latest context to a file")
    ce.add_argument("--out", default=None)
    ce.set_defaults(func=cmd_context_export)
    ci = csub.add_parser("import", help="load a context from a JSON file (testing)")
    ci.add_argument("--file", required=True)
    ci.set_defaults(func=cmd_context_import)

    ping = groups.add_parser("ping", help="ping the tunnel")
    ping.add_argument("--session-id", dest="session_id")
    ping.set_defaults(func=cmd_ping)

    return p


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())

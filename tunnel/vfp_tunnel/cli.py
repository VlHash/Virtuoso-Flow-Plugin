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


# ---- proposal -------------------------------------------------------
def cmd_proposal_create(args):
    try:
        with open(args.file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return _fail("could not read %s: %s" % (args.file, e))
    host, port = _endpoint(args)
    try:
        res = call("proposal.create", {"proposal": data}, host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    p = res.get("proposal", {})
    print("created  %s  status=%s" % (p.get("proposal_id"), p.get("status")))
    return 0


def cmd_proposal_list(args):
    host, port = _endpoint(args)
    params = {}
    if args.status:
        params["status"] = args.status
    try:
        res = call("proposal.list", params, host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    items = res.get("proposals", [])
    if not items:
        print("No proposals found.")
        return 0
    for p in items:
        cv = p.get("cellview", {})
        print("%-26s  %-12s  %s/%s/%s  %s"
              % (p.get("proposal_id"), p.get("status"),
                 cv.get("lib", "?"), cv.get("cell", "?"), cv.get("view", "?"),
                 p.get("created_at", "")))
    return 0


def cmd_proposal_show(args):
    host, port = _endpoint(args)
    try:
        res = call("proposal.get", {"proposal_id": args.proposal_id},
                   host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    print(json.dumps(res.get("proposal", {}), indent=2))
    return 0


def cmd_proposal_approve(args):
    host, port = _endpoint(args)
    try:
        res = call("proposal.approve", {"proposal_id": args.proposal_id},
                   host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    p = res.get("proposal", {})
    print("approved  %s  status=%s" % (p.get("proposal_id"), p.get("status")))
    return 0


def cmd_proposal_reject(args):
    host, port = _endpoint(args)
    try:
        res = call("proposal.reject", {"proposal_id": args.proposal_id},
                   host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    p = res.get("proposal", {})
    print("rejected  %s  status=%s" % (p.get("proposal_id"), p.get("status")))
    return 0


# ---- transaction ----------------------------------------------------
def cmd_transaction_list(args):
    host, port = _endpoint(args)
    params = {}
    if args.status:
        params["status"] = args.status
    try:
        res = call("transaction.list", params, host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    items = res.get("transactions", [])
    if not items:
        print("No transactions found.")
        return 0
    for t in items:
        cv = t.get("cellview", {})
        print("%-26s  %-12s  %s/%s/%s  proposal=%s  %s"
              % (t.get("transaction_id"), t.get("status"),
                 cv.get("lib", "?"), cv.get("cell", "?"), cv.get("view", "?"),
                 t.get("proposal_id", "-"), t.get("timestamp", "")))
    return 0


def cmd_transaction_show(args):
    host, port = _endpoint(args)
    try:
        res = call("transaction.get", {"transaction_id": args.transaction_id},
                   host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    print(json.dumps(res.get("transaction", {}), indent=2))
    return 0


# ---- result / constraint --------------------------------------------
def _load_struct(path):
    """Load a JSON or YAML file into a Python structure.

    YAML needs PyYAML (optional); JSON is always supported.
    """
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml
        except ImportError:
            raise ValueError("reading %s needs PyYAML (pip install pyyaml) "
                             "or provide a .json file" % path)
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cmd_result_import(args):
    from .sim.parser import parse_metrics_file
    try:
        metrics = parse_metrics_file(args.file)
    except (OSError, ValueError) as e:
        return _fail("could not read %s: %s" % (args.file, e))
    if not metrics:
        return _fail("no metrics found in %s" % args.file)
    result = {"metrics": metrics, "source": args.source}
    if args.test:
        result["test"] = args.test
    payload = {"result": result}
    if args.constraints:
        try:
            limits = (_load_struct(args.constraints) or {}).get("metrics")
        except (OSError, ValueError) as e:
            return _fail(e)
        if limits:
            payload["constraints"] = limits
    host, port = _endpoint(args)
    try:
        res = call("result.update", payload, host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    r = res.get("result", {})
    line = "imported %s  (%d metrics)" % (r.get("result_id"), len(r.get("metrics", {})))
    cons = r.get("constraints")
    if cons:
        line += "  constraints=%s" % cons.get("overall")
    print(line)
    return 0


def cmd_result_latest(args):
    host, port = _endpoint(args)
    try:
        res = call("result.latest", {}, host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    r = res.get("result")
    if not r:
        print("No result stored yet.")
        return 0
    print(json.dumps(r, indent=2))
    return 0


def cmd_constraint_check(args):
    try:
        limits = (_load_struct(args.file) or {}).get("metrics")
    except (OSError, ValueError) as e:
        return _fail(e)
    if not limits:
        return _fail("no 'metrics' limits found in %s" % args.file)
    params = {"constraints": limits}
    if args.result:
        from .sim.parser import parse_metrics_file
        try:
            params["metrics"] = parse_metrics_file(args.result)
        except (OSError, ValueError) as e:
            return _fail(e)
    host, port = _endpoint(args)
    try:
        res = call("constraint.check", params, host=host, port=port)
    except (OSError, JsonRpcError) as e:
        return _fail(e)
    for item in res.get("items", []):
        val = item.get("value", "-")
        mark = "PASS" if item["status"] == "pass" else "FAIL"
        reason = ("  %s" % item["reason"]) if item.get("reason") else ""
        print("  [%s] %-14s %s%s" % (mark, item["metric"], val, reason))
    overall = res.get("overall")
    print("overall: %s (metrics from %s)" % (overall.upper(), res.get("source")))
    return 0 if overall == "pass" else 1


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

    proposal = groups.add_parser("proposal", help="manage design change proposals")
    psub = proposal.add_subparsers(dest="cmd")

    pc = psub.add_parser("create", help="create a proposal from a JSON file")
    pc.add_argument("--file", required=True, help="path to proposal JSON file")
    pc.set_defaults(func=cmd_proposal_create)

    pl = psub.add_parser("list", help="list proposals")
    pl.add_argument("--status", default=None,
                    help="filter by status (pending/approved/rejected/applied/failed/rolled_back)")
    pl.set_defaults(func=cmd_proposal_list)

    ps = psub.add_parser("show", help="show a proposal in full")
    ps.add_argument("proposal_id")
    ps.set_defaults(func=cmd_proposal_show)

    pa = psub.add_parser("approve", help="approve a pending proposal")
    pa.add_argument("proposal_id")
    pa.set_defaults(func=cmd_proposal_approve)

    pr = psub.add_parser("reject", help="reject a pending proposal")
    pr.add_argument("proposal_id")
    pr.set_defaults(func=cmd_proposal_reject)

    transaction = groups.add_parser("transaction",
                                    help="inspect applied-change transactions")
    tsub2 = transaction.add_subparsers(dest="cmd")
    tl = tsub2.add_parser("list", help="list transactions")
    tl.add_argument("--status", default=None,
                    help="filter by status (applied/failed/rolled_back)")
    tl.set_defaults(func=cmd_transaction_list)
    tshow = tsub2.add_parser("show", help="show a transaction in full")
    tshow.add_argument("transaction_id")
    tshow.set_defaults(func=cmd_transaction_show)

    result = groups.add_parser("result", help="simulation results")
    rsub = result.add_subparsers(dest="cmd")
    ri = rsub.add_parser("import", help="import metrics from a result file")
    ri.add_argument("--file", required=True)
    ri.add_argument("--source", default="manual")
    ri.add_argument("--test", default=None)
    ri.add_argument("--constraints", default=None,
                    help="constraint file to evaluate against on import")
    ri.set_defaults(func=cmd_result_import)
    rsub.add_parser("latest", help="print the latest stored result").set_defaults(
        func=cmd_result_latest)

    constraint = groups.add_parser("constraint", help="constraint checking")
    konsub = constraint.add_subparsers(dest="cmd")
    cc = konsub.add_parser("check", help="check a constraint file against metrics")
    cc.add_argument("--file", required=True, help="constraint file (.yaml/.json)")
    cc.add_argument("--result", default=None,
                    help="metrics/result file (defaults to the latest stored result)")
    cc.set_defaults(func=cmd_constraint_check)

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

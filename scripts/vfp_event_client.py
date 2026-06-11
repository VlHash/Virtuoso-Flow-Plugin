#!/usr/bin/env python3
"""VFP event client -- feeds tunnel events to the SKILL ipc event bridge.

``skill/vfp_rpc_server.il`` spawns this script as a persistent child of
Virtuoso (``ipcBeginProcess``) and parses one stdout line per event:

    VFP-EVT <seq> <type>

Lines are flushed immediately -- the SKILL data handler fires per line
while the child is alive. Anything that is not an event goes to stderr,
which the bridge only logs.

Modes:
    --mock        emit synthetic events without a tunnel; exercises the
                  whole SKILL bridge (used by gui_test and pytest).
    (default)     real mode: long-poll ``event.wait(since, timeout_s)``
                  when the tunnel provides it, else poll
                  ``event.list(since)`` every ``--interval`` seconds.
                  If the tunnel has neither (event RPCs not landed yet),
                  print a notice and exit 0 so the bridge stays quiet.

``--since N`` resumes after event seq N. ``--since 0`` (the default)
means "start from the latest event": the client fast-forwards its
cursor and never replays history, so connecting does not trigger a
refresh storm.

Python 3.6 compatible (design-server system python).
"""

import argparse
import sys
import time

MOCK_TYPES = (
    "proposal.created",
    "proposal.approved",
    "transaction.created",
    "result.updated",
    "run.done",
)

METHOD_NOT_FOUND = -32601


def emit(seq, etype):
    sys.stdout.write("VFP-EVT %d %s\n" % (seq, etype))
    sys.stdout.flush()


def note(msg):
    sys.stderr.write("vfp_event_client: %s\n" % msg)
    sys.stderr.flush()


def run_mock(args):
    for i in range(args.mock_count):
        emit(args.since + i + 1, MOCK_TYPES[i % len(MOCK_TYPES)])
        if i + 1 < args.mock_count:
            time.sleep(args.mock_interval)
    note("mock done (%d events)" % args.mock_count)
    return 0


def _endpoint(args):
    """Same resolution as vfp_tunnel.skillrpc: state file, then defaults."""
    import json

    from vfp_tunnel.config import resolve_host, resolve_port, state_file

    host, port = args.host, args.port
    if not host or not port:
        try:
            st = json.loads(state_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        host = host or st.get("host") or resolve_host()
        port = port or st.get("port") or resolve_port()
    return host, int(port)


def run_real(args):
    from vfp_tunnel.rpc.jsonrpc import JsonRpcError
    from vfp_tunnel.rpc.transport import call

    host, port = _endpoint(args)
    since = args.since
    have_wait = True
    failures = 0

    # First contact: learn the cursor. since<=0 fast-forwards to the
    # latest event so a fresh session never replays history.
    while True:
        try:
            resp = call("event.list", {"since": max(since, 0)},
                        host=host, port=port, timeout=10.0)
        except JsonRpcError as e:
            if e.code == METHOD_NOT_FOUND:
                note("tunnel has no event RPCs yet; exiting")
                return 0
            note("event.list failed: %s" % e.message)
            return 1
        except OSError as e:
            failures += 1
            if failures > args.max_failures:
                note("cannot reach tunnel at %s:%s (%s); giving up"
                     % (host, port, e))
                return 1
            time.sleep(args.retry_interval)
            continue
        break

    latest = resp.get("latest_seq", since)
    if since <= 0:
        since = latest
    else:
        for ev in resp.get("events", []):
            emit(ev["seq"], ev.get("type", "?"))
            since = max(since, ev["seq"])

    failures = 0
    while True:
        try:
            if have_wait:
                try:
                    resp = call("event.wait",
                                {"since": since, "timeout_s": args.wait_timeout},
                                host=host, port=port,
                                timeout=args.wait_timeout + 10.0)
                except JsonRpcError as e:
                    if e.code != METHOD_NOT_FOUND:
                        raise
                    have_wait = False
                    note("tunnel has no event.wait; polling event.list")
                    continue
            else:
                resp = call("event.list", {"since": since},
                            host=host, port=port, timeout=10.0)
            failures = 0
            for ev in resp.get("events", []):
                emit(ev["seq"], ev.get("type", "?"))
                since = max(since, ev["seq"])
            if not have_wait:
                time.sleep(args.interval)
        except JsonRpcError as e:
            note("event poll failed: %s" % e.message)
            return 1
        except OSError as e:
            failures += 1
            if failures > args.max_failures:
                note("lost tunnel at %s:%s (%s); giving up" % (host, port, e))
                return 1
            time.sleep(args.retry_interval)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vfp_event_client")
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--since", type=int, default=0,
                    help="resume after this seq; 0 = start from latest")
    ap.add_argument("--interval", type=float, default=5.0,
                    help="event.list poll period when event.wait is unavailable")
    ap.add_argument("--wait-timeout", type=float, default=25.0,
                    help="server-side timeout passed to event.wait")
    ap.add_argument("--retry-interval", type=float, default=5.0)
    ap.add_argument("--max-failures", type=int, default=60,
                    help="consecutive connection failures before giving up")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--mock-count", type=int, default=5)
    ap.add_argument("--mock-interval", type=float, default=1.0)
    args = ap.parse_args(argv)

    if args.mock:
        return run_mock(args)
    return run_real(args)


if __name__ == "__main__":
    raise SystemExit(main())

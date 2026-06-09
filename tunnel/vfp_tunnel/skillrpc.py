"""SKILL bridge helper: run one JSON-RPC call and emit a SKILL s-expression.

Base SKILL has no raw TCP sockets and no JSON parser, so
``skill/vfp_rpc_client.il`` invokes this synchronously (via ``system()``),
redirecting our stdout to a temp file, then parses the result with SKILL
``read``.

Output is always a single top-level s-expression on the first line:

    (t   <result-sexpr>)                       on success
    (nil (("code" N) ("message" "...")))       on failure

so the SKILL side reads ``(ok payload)`` with one ``read`` call. Exit code
is 0 whenever a structured payload was produced (including tunnel errors);
a non-zero exit means the helper itself could not run.

Usage::

    python -m vfp_tunnel.skillrpc [--host H --port P] METHOD \\
        [--param k=v ...] [--param-json k=<json> ...]

For ``session.register`` the flat ``--param`` values are wrapped into a
``client`` object, so the SKILL side never has to build JSON.
"""

import argparse
import json
import sys

from .config import resolve_host, resolve_port, state_file
from .rpc.jsonrpc import JsonRpcError
from .rpc.transport import call


def to_sexpr(obj):
    """Render a JSON-ish value as a SKILL-readable s-expression string."""
    if obj is True:
        return "t"
    if obj is False or obj is None:
        return "nil"
    if isinstance(obj, str):
        esc = obj.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return '"' + esc + '"'
    if isinstance(obj, int):  # bool already handled above
        return str(obj)
    if isinstance(obj, float):
        return repr(obj)
    if isinstance(obj, dict):
        return "(" + " ".join("(%s %s)" % (to_sexpr(str(k)), to_sexpr(v))
                              for k, v in obj.items()) + ")"
    if isinstance(obj, (list, tuple)):
        return "(" + " ".join(to_sexpr(v) for v in obj) + ")"
    return to_sexpr(str(obj))


def _endpoint(args):
    host, port = args.host, args.port
    if not host or not port:
        st = {}
        try:
            st = json.loads(state_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        host = host or st.get("host") or resolve_host()
        port = port or st.get("port") or resolve_port()
    return host, int(port)


def _params(args):
    params = {}
    if args.params_file:
        with open(args.params_file, encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            params.update(loaded)
    for kv in args.param:
        key, _, val = kv.partition("=")
        params[key] = val
    for kv in args.param_json:
        key, _, val = kv.partition("=")
        params[key] = json.loads(val)
    if args.method == "session.register":
        params = {"client": params}
    return params


def main(argv=None):
    ap = argparse.ArgumentParser(prog="vfp-skillrpc")
    ap.add_argument("--host")
    ap.add_argument("--port")
    ap.add_argument("method")
    ap.add_argument("--param", action="append", default=[])
    ap.add_argument("--param-json", dest="param_json", action="append", default=[])
    ap.add_argument("--params-file", dest="params_file",
                    help="JSON file whose object is merged into params (for large payloads)")
    args = ap.parse_args(argv)

    host, port = _endpoint(args)
    try:
        result = call(args.method, _params(args), host=host, port=port, timeout=5.0)
        sys.stdout.write("(t " + to_sexpr(result) + ")\n")
        return 0
    except JsonRpcError as e:
        sys.stdout.write("(nil " + to_sexpr({"code": e.code, "message": e.message}) + ")\n")
        return 0
    except OSError as e:
        msg = "cannot reach tunnel at %s:%s (%s)" % (host, port, e)
        sys.stdout.write("(nil " + to_sexpr({"code": -32000, "message": msg}) + ")\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

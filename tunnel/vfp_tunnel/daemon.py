"""VFP Tunnel daemon: JSON-RPC server, methods, and lifecycle/state file.

Run directly (``python -m vfp_tunnel.daemon``) or, more usually, via
``vfp tunnel start`` which spawns this module as a detached process.
"""

import argparse
import json
import os
import threading
import time

from . import __version__
from .config import ensure_dirs, resolve_host, resolve_port, state_file
from .design.context import ContextStore
from .logging_config import get_logger
from .proposal.manager import ProposalStore
from .rpc import schemas
from .rpc.jsonrpc import Dispatcher, INVALID_PARAMS, JsonRpcError
from .rpc.transport import make_server
from .session.registry import Registry


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


class Tunnel:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.started_ts = time.time()
        self.registry = Registry()
        self.contexts = ContextStore()
        self.proposals = ProposalStore()
        self.dispatcher = Dispatcher()
        self.server = None
        self.log = get_logger()
        self._register_methods()

    def _register_methods(self):
        d = self.dispatcher
        d.register("session.register", self._m_session_register)
        d.register("session.ping", self._m_session_ping)
        d.register("session.status", self._m_session_status)
        d.register("session.list", self._m_session_list)
        d.register("session.current", self._m_session_current)
        d.register("design.context.update", self._m_context_update)
        d.register("design.context.get", self._m_context_get)
        d.register("tunnel.status", self._m_tunnel_status)
        d.register("tunnel.shutdown", self._m_tunnel_shutdown)
        # Proposal methods
        d.register("proposal.create",      self._m_proposal_create)
        d.register("proposal.list",        self._m_proposal_list)
        d.register("proposal.get",         self._m_proposal_get)
        d.register("proposal.approve",     self._m_proposal_approve)
        d.register("proposal.reject",      self._m_proposal_reject)
        d.register("proposal.mark_applied", self._m_proposal_mark_applied)
        d.register("proposal.mark_failed", self._m_proposal_mark_failed)

    def _validate_or_raise(self, name, data):
        """Optional schema validation (no-op if jsonschema absent)."""
        try:
            schemas.validate(name, data)
        except Exception as e:  # noqa: BLE001
            if type(e).__name__ == "ValidationError":
                raise JsonRpcError(INVALID_PARAMS, "%s failed schema validation: %s"
                                   % (name, getattr(e, "message", e)))
            raise

    # ---- RPC methods (each takes a params dict) ----
    def _m_session_register(self, params):
        client = params.get("client", {})
        rec = self.registry.register(client)
        self.log.info("session registered: %s (%s)", rec["session_id"], client)
        return {"session_id": rec["session_id"], "registered_at": rec["created_at"]}

    def _m_session_ping(self, params):
        sid = params.get("session_id")
        if sid:
            self.registry.touch(sid)
        return {"pong": True, "time": _iso(time.time()), "session_id": sid}

    def _m_session_status(self, params):
        sid = params.get("session_id")
        rec = self.registry.get(sid) if sid else None
        if rec is None:
            raise JsonRpcError(INVALID_PARAMS, "unknown session_id: %r" % (sid,))
        return self.registry.public(rec)

    def _m_session_list(self, params):
        return {"sessions": [self.registry.public(r) for r in self.registry.list()]}

    def _m_session_current(self, params):
        return {"session": self.registry.public(self.registry.current())}

    def _m_context_update(self, params):
        context = params.get("context")
        if not isinstance(context, dict):
            raise JsonRpcError(INVALID_PARAMS, "params.context must be an object")
        self._validate_or_raise("context", context)
        sid = params.get("session_id")
        if sid:
            self.registry.touch(sid)
        result = self.contexts.update(context)
        cv = context.get("cellview", {})
        self.log.info("context updated: %s/%s/%s (%d instances)",
                      cv.get("lib"), cv.get("cell"), cv.get("view"),
                      len(context.get("instances", [])))
        return result

    def _m_context_get(self, params):
        return {"context": self.contexts.latest()}

    # ---- proposal RPC methods ----
    def _m_proposal_create(self, params):
        data = params.get("proposal")
        if not isinstance(data, dict):
            raise JsonRpcError(INVALID_PARAMS, "params.proposal must be an object")
        self._validate_or_raise("proposal", data)
        try:
            p = self.proposals.create(data)
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))
        self.log.info("proposal created: %s (%s)", p["proposal_id"], p.get("reason", "")[:60])
        return {"proposal": p}

    def _m_proposal_list(self, params):
        status = params.get("status")
        items = self.proposals.list(status=status)
        return {"proposals": items, "count": len(items)}

    def _m_proposal_get(self, params):
        pid = params.get("proposal_id")
        if not pid:
            raise JsonRpcError(INVALID_PARAMS, "params.proposal_id required")
        p = self.proposals.get(pid)
        if p is None:
            raise JsonRpcError(-32001, "unknown proposal_id: %s" % pid)
        return {"proposal": p}

    def _m_proposal_approve(self, params):
        pid = params.get("proposal_id")
        if not pid:
            raise JsonRpcError(INVALID_PARAMS, "params.proposal_id required")
        try:
            p = self.proposals.approve(pid)
        except KeyError as e:
            raise JsonRpcError(-32001, str(e))
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))
        self.log.info("proposal approved: %s", pid)
        return {"proposal": p}

    def _m_proposal_reject(self, params):
        pid = params.get("proposal_id")
        if not pid:
            raise JsonRpcError(INVALID_PARAMS, "params.proposal_id required")
        try:
            p = self.proposals.reject(pid)
        except KeyError as e:
            raise JsonRpcError(-32001, str(e))
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))
        self.log.info("proposal rejected: %s", pid)
        return {"proposal": p}

    def _m_proposal_mark_applied(self, params):
        pid = params.get("proposal_id")
        if not pid:
            raise JsonRpcError(INVALID_PARAMS, "params.proposal_id required")
        try:
            p = self.proposals.mark_applied(pid)
        except KeyError as e:
            raise JsonRpcError(-32001, str(e))
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))
        self.log.info("proposal applied: %s", pid)
        return {"proposal": p}

    def _m_proposal_mark_failed(self, params):
        pid = params.get("proposal_id")
        if not pid:
            raise JsonRpcError(INVALID_PARAMS, "params.proposal_id required")
        try:
            p = self.proposals.mark_failed(pid)
        except KeyError as e:
            raise JsonRpcError(-32001, str(e))
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))
        self.log.info("proposal failed: %s", pid)
        return {"proposal": p}

    def _m_tunnel_status(self, params):
        return {
            "running": True,
            "version": __version__,
            "host": self.host,
            "port": self.port,
            "pid": os.getpid(),
            "started_at": _iso(self.started_ts),
            "uptime_s": round(time.time() - self.started_ts, 1),
            "sessions": len(self.registry.list()),
        }

    def _m_tunnel_shutdown(self, params):
        self.log.info("shutdown requested via RPC")
        threading.Thread(target=self._shutdown, name="vfp-shutdown").start()
        return {"stopping": True}

    def _shutdown(self):
        time.sleep(0.2)  # let the response flush first
        if self.server is not None:
            self.server.shutdown()

    # ---- lifecycle ----
    def serve(self):
        ensure_dirs()
        self.server = make_server(self.host, self.port, self.dispatcher)
        # Reflect the actually-bound port (in case port 0 was requested).
        self.host, self.port = self.server.server_address[0], self.server.server_address[1]
        self._write_state()
        self.log.info("VFP Tunnel %s listening on %s:%s (pid %s)",
                      __version__, self.host, self.port, os.getpid())
        try:
            self.server.serve_forever()
        finally:
            self.server.server_close()
            self._clear_state()
            self.log.info("VFP Tunnel stopped")

    def _write_state(self):
        try:
            state_file().write_text(json.dumps({
                "pid": os.getpid(),
                "host": self.host,
                "port": self.port,
                "version": __version__,
                "started_at": _iso(self.started_ts),
            }, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _clear_state(self):
        try:
            state_file().unlink()
        except OSError:
            pass


def main(argv=None):
    p = argparse.ArgumentParser(prog="vfp-tunneld", description="VFP Tunnel daemon")
    p.add_argument("--host", default=None)
    p.add_argument("--port", default=None)
    args = p.parse_args(argv)
    Tunnel(resolve_host(args.host), resolve_port(args.port)).serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

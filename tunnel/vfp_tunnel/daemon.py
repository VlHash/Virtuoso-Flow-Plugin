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
from .artifact.manager import RunStore
from .constraints import engine as constraint_engine
from .proposal.manager import ProposalStore
from .rpc import schemas
from .rpc.jsonrpc import Dispatcher, INVALID_PARAMS, JsonRpcError
from .rpc.transport import make_server
from .session.registry import Registry
from .sim.manager import ResultStore
from .sim.metrics import make_result
from .transaction import permissions as txn_permissions
from .transaction.manager import TransactionStore
from .transaction.model import make_transaction

# Custom JSON-RPC error codes (server-defined range -32000..-32099).
UNKNOWN_ID = -32001
PERMISSION_DENIED = -32002


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
        self.transactions = TransactionStore()
        self.results = ResultStore()
        self.runs = RunStore()
        # Default modify-permissions (empty => allow all). Milestone 6's
        # constraint engine will populate this from the constraint file.
        self.permissions = {}
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
        # Transaction methods
        d.register("transaction.create",          self._m_transaction_create)
        d.register("transaction.list",            self._m_transaction_list)
        d.register("transaction.get",             self._m_transaction_get)
        d.register("transaction.rollback",        self._m_transaction_rollback)
        d.register("transaction.mark_rolled_back", self._m_transaction_mark_rolled_back)
        d.register("transaction.mark_failed",     self._m_transaction_mark_failed)
        # Result / constraint methods
        d.register("result.update",   self._m_result_update)
        d.register("result.latest",   self._m_result_latest)
        d.register("constraint.check", self._m_constraint_check)
        # Run / artifact methods
        d.register("run.create",        self._m_run_create)
        d.register("run.list",          self._m_run_list)
        d.register("run.get",           self._m_run_get)
        d.register("run.set_status",    self._m_run_set_status)
        d.register("run.attach",        self._m_run_attach)
        d.register("run.import_result", self._m_run_import_result)

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

    # ---- transaction RPC methods ----
    def _m_transaction_create(self, params):
        data = params.get("transaction")
        if not isinstance(data, dict):
            raise JsonRpcError(INVALID_PARAMS, "params.transaction must be an object")

        # Build the complete record first (assigns transaction_id), then
        # enforce modify-permissions and validate against the schema.
        candidate = make_transaction(data)

        perms = params.get("permissions") or self.permissions or {}
        targets = candidate.get("after") or candidate.get("before") or []
        viol = txn_permissions.violations(
            targets, perms.get("allow_modify"), perms.get("deny_modify"))
        if viol:
            raise JsonRpcError(
                PERMISSION_DENIED,
                "modify not permitted for: %s"
                % ", ".join(v["target"] for v in viol),
                data=viol)

        self._validate_or_raise("transaction", candidate)
        try:
            txn = self.transactions.add(candidate)
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))

        # Link to the originating proposal: an approved proposal becomes
        # applied once its transaction is recorded.
        pid = txn.get("proposal_id")
        if pid:
            p = self.proposals.get(pid)
            if p is not None and p.get("status") == "approved":
                try:
                    self.proposals.mark_applied(pid)
                except (KeyError, ValueError):
                    pass
        self.log.info("transaction created: %s (proposal %s, %d change(s))",
                      txn["transaction_id"], pid, len(txn.get("after", [])))
        return {"transaction": txn}

    def _m_transaction_list(self, params):
        status = params.get("status")
        items = self.transactions.list(status=status)
        return {"transactions": items, "count": len(items)}

    def _m_transaction_get(self, params):
        tid = params.get("transaction_id")
        if not tid:
            raise JsonRpcError(INVALID_PARAMS, "params.transaction_id required")
        t = self.transactions.get(tid)
        if t is None:
            raise JsonRpcError(UNKNOWN_ID, "unknown transaction_id: %s" % tid)
        return {"transaction": t}

    def _m_transaction_rollback(self, params):
        """Pre-flight a rollback: validate state and return the restore recipe.

        The actual schematic restore happens in SKILL; it confirms with
        ``transaction.mark_rolled_back`` afterwards. This keeps the on-disk
        status truthful if the GUI restore fails midway.
        """
        tid = params.get("transaction_id")
        if not tid:
            raise JsonRpcError(INVALID_PARAMS, "params.transaction_id required")
        t = self.transactions.get(tid)
        if t is None:
            raise JsonRpcError(UNKNOWN_ID, "unknown transaction_id: %s" % tid)
        if t.get("status") != "applied":
            raise JsonRpcError(
                INVALID_PARAMS,
                "transaction %s is %s, only 'applied' can be rolled back"
                % (tid, t.get("status")))
        return {"transaction": t, "restore": t.get("before", [])}

    def _m_transaction_mark_rolled_back(self, params):
        tid = params.get("transaction_id")
        if not tid:
            raise JsonRpcError(INVALID_PARAMS, "params.transaction_id required")
        try:
            t = self.transactions.mark_rolled_back(tid)
        except KeyError as e:
            raise JsonRpcError(UNKNOWN_ID, str(e))
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))
        # Reflect the rollback on the originating proposal.
        pid = t.get("proposal_id")
        if pid:
            p = self.proposals.get(pid)
            if p is not None and p.get("status") == "applied":
                try:
                    self.proposals.mark_rolled_back(pid)
                except (KeyError, ValueError):
                    pass
        self.log.info("transaction rolled back: %s", tid)
        return {"transaction": t}

    def _m_transaction_mark_failed(self, params):
        tid = params.get("transaction_id")
        if not tid:
            raise JsonRpcError(INVALID_PARAMS, "params.transaction_id required")
        try:
            t = self.transactions.mark_failed(tid)
        except KeyError as e:
            raise JsonRpcError(UNKNOWN_ID, str(e))
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))
        self.log.info("transaction marked failed: %s", tid)
        return {"transaction": t}

    # ---- result / constraint RPC methods ----
    def _m_result_update(self, params):
        data = params.get("result")
        if not isinstance(data, dict):
            raise JsonRpcError(INVALID_PARAMS, "params.result must be an object")
        result = make_result(data)
        # Optionally evaluate against supplied limits and attach the verdict.
        limits = params.get("constraints")
        if isinstance(limits, dict):
            result["constraints"] = constraint_engine.check(result["metrics"], limits)
        self._validate_or_raise("result", result)
        stored = self.results.update(result)
        self.log.info("result stored: %s (%d metrics)",
                      result["result_id"], len(result["metrics"]))
        return {"result": result, "path": stored.get("path")}

    def _m_result_latest(self, params):
        return {"result": self.results.latest()}

    def _m_constraint_check(self, params):
        limits = params.get("constraints")
        if not isinstance(limits, dict):
            raise JsonRpcError(INVALID_PARAMS, "params.constraints must be an object")
        metrics = params.get("metrics")
        source = "params"
        if not isinstance(metrics, dict):
            latest = self.results.latest()
            if not latest:
                raise JsonRpcError(INVALID_PARAMS,
                                   "no metrics provided and no stored result")
            metrics = latest.get("metrics", {})
            source = "latest_result"
        verdict = constraint_engine.check(metrics, limits)
        verdict["source"] = source
        return verdict

    # ---- run / artifact RPC methods ----
    def _m_run_create(self, params):
        meta = params.get("run") if isinstance(params.get("run"), dict) else {}
        run = self.runs.create(meta)
        self.log.info("run created: %s (%s)", run["run_id"], meta.get("test"))
        return {"run": run}

    def _m_run_list(self, params):
        items = self.runs.list(status=params.get("status"))
        return {"runs": items, "count": len(items)}

    def _m_run_get(self, params):
        rid = params.get("run_id")
        if not rid:
            raise JsonRpcError(INVALID_PARAMS, "params.run_id required")
        run = self.runs.get(rid)
        if run is None:
            raise JsonRpcError(UNKNOWN_ID, "unknown run_id: %s" % rid)
        return {"run": run}

    def _m_run_set_status(self, params):
        rid = params.get("run_id")
        if not rid:
            raise JsonRpcError(INVALID_PARAMS, "params.run_id required")
        try:
            run = self.runs.set_status(rid, params.get("status"))
        except KeyError as e:
            raise JsonRpcError(UNKNOWN_ID, str(e))
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))
        return {"run": run}

    def _m_run_attach(self, params):
        rid = params.get("run_id")
        label = params.get("label")
        if not rid or not label:
            raise JsonRpcError(INVALID_PARAMS, "params.run_id and params.label required")
        text = params.get("text")
        if text is None:
            raise JsonRpcError(INVALID_PARAMS, "params.text required")
        filename = params.get("filename") or (label + ".txt")
        try:
            run = self.runs.attach_text(rid, label, filename, text)
        except KeyError as e:
            raise JsonRpcError(UNKNOWN_ID, str(e))
        return {"run": run}

    def _m_run_import_result(self, params):
        """Store metrics as a result, link it to a run, and mark the run done."""
        rid = params.get("run_id")
        if not rid:
            raise JsonRpcError(INVALID_PARAMS, "params.run_id required")
        if self.runs.get(rid) is None:
            raise JsonRpcError(UNKNOWN_ID, "unknown run_id: %s" % rid)
        metrics = params.get("metrics")
        if not isinstance(metrics, dict):
            raise JsonRpcError(INVALID_PARAMS, "params.metrics must be an object")
        result = make_result({"metrics": metrics, "source": params.get("source", "ade")})
        limits = params.get("constraints")
        if isinstance(limits, dict):
            result["constraints"] = constraint_engine.check(result["metrics"], limits)
        self._validate_or_raise("result", result)
        self.results.update(result)
        self.runs.link_result(rid, result["result_id"])
        run = self.runs.set_status(rid, "done")
        self.log.info("run %s imported result %s", rid, result["result_id"])
        return {"run": run, "result": result}

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

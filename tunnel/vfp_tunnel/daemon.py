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
from .config import (ensure_dirs, resolve_host, resolve_port, session_ttl_s,
                     sim_cmd, sim_metrics_file, sim_timeout_s, state_file)
from .design.context import ContextStore
from .event.manager import EventLog
from .logging_config import get_logger
from .artifact.manager import RunStore
from .constraints import engine as constraint_engine
from .proposal.manager import ProposalStore
from .rpc import schemas
from .rpc.errors import INVALID_STATE, NOT_FOUND, PERMISSION_DENIED
from .rpc.jsonrpc import Dispatcher, INVALID_PARAMS, JsonRpcError
from .rpc.transport import make_server
from .session.registry import Registry
from .sim.job import make_job
from .sim.job_store import JobStore
from .sim.netlist_requests import NetlistRequestStore
from .sim.runner import JobRunner
from .sim.manager import ResultStore
from .sim.metrics import make_result
from .transaction import permissions as txn_permissions
from .transaction.manager import TransactionStore
from .transaction.model import make_transaction


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
        self.jobs = JobStore()
        self.netlist_requests = NetlistRequestStore()
        self.events = EventLog()
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
        d.register("session.reap", self._m_session_reap)
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
        # Simulation jobs
        d.register("job.create",      self._m_job_create)
        d.register("job.list",        self._m_job_list)
        d.register("job.get",         self._m_job_get)
        d.register("job.cancel",      self._m_job_cancel)
        d.register("job.mark_running", self._m_job_mark_running)
        d.register("job.mark_done",   self._m_job_mark_done)
        d.register("job.mark_failed", self._m_job_mark_failed)
        d.register("job.run",         self._m_job_run)
        # Netlist over VFP's own channel: request -> plugin (event) -> deck
        d.register("netlist.request",  self._m_netlist_request)
        d.register("netlist.complete", self._m_netlist_complete)
        d.register("netlist.get",      self._m_netlist_get)
        d.register("netlist.pending",  self._m_netlist_pending)
        # Event stream
        d.register("event.list", self._m_event_list)
        d.register("event.wait", self._m_event_wait)

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
        # Opportunistically drop dead sessions when a new one connects.
        self.registry.reap(session_ttl_s())
        rec = self.registry.register(client)
        self.log.info("session registered: %s (%s)", rec["session_id"], client)
        return {"session_id": rec["session_id"], "registered_at": rec["created_at"],
                "reconnects": rec.get("reconnects", 0)}

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
        now = time.time()
        out = []
        for r in self.registry.list():
            pub = self.registry.public(r)
            pub["idle_s"] = round(now - r.get("_last_ts", now), 1)
            out.append(pub)
        return {"sessions": out}

    def _m_session_current(self, params):
        return {"session": self.registry.public(self.registry.current())}

    def _m_session_reap(self, params):
        max_idle = params.get("max_idle_s")
        if max_idle is None:
            max_idle = session_ttl_s()
        removed = self.registry.reap(float(max_idle) if max_idle else 0)
        if removed:
            self.log.info("reaped %d idle session(s)", len(removed))
        return {"removed": removed, "count": len(removed)}

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
        self.events.emit("proposal.created",
                         {"proposal_id": p["proposal_id"], "cellview": p.get("cellview")})
        return {"proposal": p}

    def _m_proposal_list(self, params):
        # Surface any TTL expirations as events before serving the list.
        for pid in self.proposals.expire_stale():
            self.events.emit("proposal.expired", {"proposal_id": pid})
        status = params.get("status")
        items = self.proposals.list(status=status)
        return {"proposals": items, "count": len(items)}

    def _m_proposal_get(self, params):
        pid = params.get("proposal_id")
        if not pid:
            raise JsonRpcError(INVALID_PARAMS, "params.proposal_id required")
        p = self.proposals.get(pid)
        if p is None:
            raise JsonRpcError(NOT_FOUND, "unknown proposal_id: %s" % pid)
        return {"proposal": p}

    def _m_proposal_approve(self, params):
        pid = params.get("proposal_id")
        if not pid:
            raise JsonRpcError(INVALID_PARAMS, "params.proposal_id required")
        try:
            p = self.proposals.approve(pid)
        except KeyError as e:
            raise JsonRpcError(NOT_FOUND, str(e))
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))
        self.log.info("proposal approved: %s", pid)
        self.events.emit("proposal.approved", {"proposal_id": pid})
        return {"proposal": p}

    def _m_proposal_reject(self, params):
        pid = params.get("proposal_id")
        if not pid:
            raise JsonRpcError(INVALID_PARAMS, "params.proposal_id required")
        try:
            p = self.proposals.reject(pid)
        except KeyError as e:
            raise JsonRpcError(NOT_FOUND, str(e))
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))
        self.log.info("proposal rejected: %s", pid)
        self.events.emit("proposal.rejected", {"proposal_id": pid})
        return {"proposal": p}

    def _m_proposal_mark_applied(self, params):
        pid = params.get("proposal_id")
        if not pid:
            raise JsonRpcError(INVALID_PARAMS, "params.proposal_id required")
        try:
            p = self.proposals.mark_applied(pid)
        except KeyError as e:
            raise JsonRpcError(NOT_FOUND, str(e))
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
            raise JsonRpcError(NOT_FOUND, str(e))
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
        self.events.emit("transaction.created",
                         {"transaction_id": txn["transaction_id"], "proposal_id": pid})
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
            raise JsonRpcError(NOT_FOUND, "unknown transaction_id: %s" % tid)
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
            raise JsonRpcError(NOT_FOUND, "unknown transaction_id: %s" % tid)
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
            raise JsonRpcError(NOT_FOUND, str(e))
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
        self.events.emit("transaction.rolled_back",
                         {"transaction_id": tid, "proposal_id": pid})
        return {"transaction": t}

    def _m_transaction_mark_failed(self, params):
        tid = params.get("transaction_id")
        if not tid:
            raise JsonRpcError(INVALID_PARAMS, "params.transaction_id required")
        try:
            t = self.transactions.mark_failed(tid)
        except KeyError as e:
            raise JsonRpcError(NOT_FOUND, str(e))
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
        self.events.emit("result.updated", {"result_id": result["result_id"]})
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
            raise JsonRpcError(NOT_FOUND, "unknown run_id: %s" % rid)
        return {"run": run}

    def _m_run_set_status(self, params):
        rid = params.get("run_id")
        if not rid:
            raise JsonRpcError(INVALID_PARAMS, "params.run_id required")
        try:
            run = self.runs.set_status(rid, params.get("status"))
        except KeyError as e:
            raise JsonRpcError(NOT_FOUND, str(e))
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))
        if run.get("status") == "done":
            self.events.emit("run.done", {"run_id": rid})
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
            raise JsonRpcError(NOT_FOUND, str(e))
        return {"run": run}

    def _m_run_import_result(self, params):
        """Store metrics as a result, link it to a run, and mark the run done."""
        rid = params.get("run_id")
        if not rid:
            raise JsonRpcError(INVALID_PARAMS, "params.run_id required")
        if self.runs.get(rid) is None:
            raise JsonRpcError(NOT_FOUND, "unknown run_id: %s" % rid)
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
        self.events.emit("result.updated", {"result_id": result["result_id"]})
        self.events.emit("run.done", {"run_id": rid, "result_id": result["result_id"]})
        return {"run": run, "result": result}

    # ---- simulation job RPC methods ----
    def _session_fingerprint(self, sid):
        """Snapshot a session_id's durable Virtuoso fingerprint from the M8
        registry (pid/start/display/cds_lib), or None if unknown."""
        if not sid:
            return None
        client = (self.registry.get(sid) or {}).get("client") or {}
        fp = {k: client[k] for k in
              ("virtuoso_pid", "virtuoso_start", "display", "cds_lib")
              if client.get(k)}
        return fp or None

    def _m_job_create(self, params):
        data = params.get("job")
        if not isinstance(data, dict):
            raise JsonRpcError(INVALID_PARAMS, "params.job must be an object")
        # F.3: bind the originating session (M10a sends it at params.session_id)
        # onto the job for result provenance; touch the registry to resolve it.
        sid = params.get("session_id")
        if sid:
            data = dict(data)
            data["session"] = sid
            self.registry.touch(sid)
            # Snapshot the fingerprint now, while the session is live, so the
            # provenance survives later reaping (the raw id alone does not).
            fp = self._session_fingerprint(sid)
            if fp:
                data["session_fingerprint"] = fp
        candidate = make_job(data)
        # Freshness guard: reuse a done job with the same inputs unless the
        # caller opts out with reuse=false.
        if params.get("reuse", True):
            fresh = self.jobs.fresh_done(candidate["inputs_fingerprint"])
            if fresh is not None:
                return {"job": fresh, "reused": True}
        self._validate_or_raise("job", candidate)
        try:
            job = self.jobs.add(candidate)
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))
        self.events.emit("job.created",
                         {"job_id": job["job_id"], "test": job.get("test")})
        return {"job": job, "reused": False}

    def _m_job_list(self, params):
        items = self.jobs.list(status=params.get("status"))
        return {"jobs": items, "count": len(items)}

    def _m_job_get(self, params):
        jid = params.get("job_id")
        if not jid:
            raise JsonRpcError(INVALID_PARAMS, "params.job_id required")
        job = self.jobs.get(jid)
        if job is None:
            raise JsonRpcError(NOT_FOUND, "unknown job_id: %s" % jid)
        return {"job": job}

    def _m_job_mark_running(self, params):
        return {"job": self._job_set("mark_running", params)}

    def _m_job_mark_done(self, params):
        job = self._job_set("mark_done", params,
                            result_id=params.get("result_id"),
                            run_id=params.get("run_id"))
        self.events.emit("job.done",
                         {"job_id": job["job_id"], "result_id": job.get("result_id")})
        return {"job": job}

    def _m_job_mark_failed(self, params):
        job = self._job_set("mark_failed", params, error=params.get("error"))
        self.events.emit("job.failed", {"job_id": job["job_id"]})
        return {"job": job}

    def _m_job_cancel(self, params):
        job = self._job_set("cancel", params)
        self.events.emit("job.cancelled", {"job_id": job["job_id"]})
        return {"job": job}

    def _m_job_run(self, params):
        """Execute a queued job with the server-configured simulator command.

        The command comes from VFP_SIM_CMD only — never from the client — so
        an agent cannot run arbitrary code. Runs in a background thread; the
        client tracks completion via job.get or the event stream.
        """
        jid = params.get("job_id")
        if not jid:
            raise JsonRpcError(INVALID_PARAMS, "params.job_id required")
        job = self.jobs.get(jid)
        if job is None:
            raise JsonRpcError(NOT_FOUND, "unknown job_id: %s" % jid)
        if job.get("status") != "queued":
            raise JsonRpcError(INVALID_STATE,
                               "job %s is %s; only a queued job can be run"
                               % (jid, job.get("status")))
        cmd = sim_cmd()
        if not cmd:
            raise JsonRpcError(INVALID_PARAMS,
                               "no simulator configured (set VFP_SIM_CMD)")
        runner = JobRunner(self.jobs, self.results, self.runs, self.events)
        threading.Thread(target=self._run_job_bg, args=(runner, jid, cmd),
                         name="vfp-job-%s" % jid, daemon=True).start()
        return {"job_id": jid, "started": True}

    def _run_job_bg(self, runner, jid, cmd):
        try:
            runner.run(jid, cmd, metrics_file=sim_metrics_file(),
                       timeout_s=sim_timeout_s())
        except Exception as e:  # noqa: BLE001 - background thread guard
            self.log.error("job runner crashed for %s: %s", jid, e)

    # ---- netlist over VFP's own channel (request -> plugin -> deck) ------
    def _m_netlist_request(self, params):
        """Request a netlist from a connected plugin: store it pending and emit
        a `netlist.request` event the plugin services (vfpNetlistCellView). The
        caller polls `netlist.get` for the deck. VFP's own channel -- no external
        netlister (vcli etc.)."""
        cv = params.get("cellview")
        if not isinstance(cv, dict):
            raise JsonRpcError(INVALID_PARAMS, "params.cellview must be an object")
        req = self.netlist_requests.create(cv, params.get("corner"))
        self.events.emit("netlist.request",
                         {"request_id": req["request_id"], "cellview": cv,
                          "corner": req["corner"]})
        return {"request_id": req["request_id"], "status": req["status"]}

    def _m_netlist_complete(self, params):
        """A plugin reports the assembled deck (or an error) for a request."""
        rid = params.get("request_id")
        if not rid:
            raise JsonRpcError(INVALID_PARAMS, "params.request_id required")
        req = self.netlist_requests.complete(rid, params.get("deck"),
                                             params.get("error"))
        if req is None:
            raise JsonRpcError(NOT_FOUND, "unknown request_id: %s" % rid)
        self.events.emit("netlist.complete",
                         {"request_id": rid, "status": req["status"]})
        return {"request_id": rid, "status": req["status"]}

    def _m_netlist_get(self, params):
        rid = params.get("request_id")
        req = self.netlist_requests.get(rid) if rid else None
        if req is None:
            raise JsonRpcError(NOT_FOUND, "unknown request_id: %s" % rid)
        return {"request": req}

    def _m_netlist_pending(self, params):
        """Pending requests a connected plugin pulls (on a netlist.request event)
        to service them."""
        reqs = self.netlist_requests.pending()
        return {"requests": reqs, "count": len(reqs)}

    def _job_set(self, method, params, **fields):
        jid = params.get("job_id")
        if not jid:
            raise JsonRpcError(INVALID_PARAMS, "params.job_id required")
        fn = getattr(self.jobs, method)
        try:
            return fn(jid, **{k: v for k, v in fields.items() if v is not None})
        except KeyError as e:
            raise JsonRpcError(NOT_FOUND, str(e))
        except ValueError as e:
            raise JsonRpcError(INVALID_PARAMS, str(e))

    # ---- event stream RPC methods ----
    def _heartbeat(self, params):
        """The event bridge passes its session_id on every poll; treat that as
        the session's liveness heartbeat (timers are unavailable in SKILL)."""
        sid = params.get("session_id")
        if sid:
            self.registry.touch(sid)

    def _m_event_list(self, params):
        self._heartbeat(params)
        since = int(params.get("since") or 0)
        return self.events.list(since)

    def _m_event_wait(self, params):
        """Long-poll: block up to timeout_s for events with seq > since."""
        self._heartbeat(params)
        since = int(params.get("since") or 0)
        timeout = float(params.get("timeout_s") or 25.0)
        timeout = min(max(timeout, 0.0), 55.0)   # clamp to keep threads bounded
        return self.events.wait(since, timeout)

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

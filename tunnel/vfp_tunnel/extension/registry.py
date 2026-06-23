"""Extension namespace registry + action request channel (stdlib, Py 3.6+).

Two small, thread-safe, in-memory stores:

- ``ExtensionRegistry`` — namespaces a servicer announces (``extension.register``)
  so any client can *discover* what is callable (``extension.list``). A namespace
  is a dotted prefix (e.g. ``layout``) with a list of method names and a
  human-readable description.

- ``ActionStore`` — generic action requests routed to whatever services a
  namespace, mirroring the netlist request channel: a request is created
  ``pending`` and emitted as an ``action.request`` event; a servicer pulls it,
  runs it, and posts the result with ``complete()``; the caller polls ``get()``.

Both are intentionally transient (re-announced on reconnect) — the tunnel keeps
no privileged capability list across restarts, and never runs an action itself.
"""

import threading
import time
import uuid


def _iso(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts or time.time()))


class ExtensionRegistry:
    """Namespaces a servicer announces, for client-side capability discovery."""

    def __init__(self):
        self._ns = {}
        self._lock = threading.Lock()

    def register(self, namespace, methods=None, description="", meta=None):
        if not namespace or not isinstance(namespace, str):
            raise ValueError("namespace must be a non-empty string")
        methods = list(methods or [])
        if not all(isinstance(m, str) for m in methods):
            raise ValueError("methods must be a list of strings")
        rec = {
            "namespace": namespace,
            "methods": methods,
            "description": description or "",
            "meta": meta if isinstance(meta, dict) else {},
            "registered_at": _iso(),
            "updated_at": _iso(),
        }
        with self._lock:
            existing = self._ns.get(namespace)
            if existing:
                rec["registered_at"] = existing["registered_at"]
            self._ns[namespace] = rec
            return dict(rec)

    def unregister(self, namespace):
        with self._lock:
            return self._ns.pop(namespace, None) is not None

    def get(self, namespace):
        with self._lock:
            rec = self._ns.get(namespace)
            return dict(rec) if rec else None

    def list(self):
        with self._lock:
            return [dict(r) for r in self._ns.values()]

    def knows(self, namespace):
        with self._lock:
            return namespace in self._ns


class ActionStore:
    """Generic action requests routed to a servicer over the event bus."""

    def __init__(self):
        self._reqs = {}
        self._lock = threading.Lock()

    def create(self, namespace, method, params=None):
        if not namespace or not method:
            raise ValueError("namespace and method are required")
        aid = "act_" + uuid.uuid4().hex[:12]
        rec = {
            "action_id": aid,
            "namespace": namespace,
            "method": method,
            "params": params if isinstance(params, dict) else {},
            "status": "pending",
            "result": None,
            "error": None,
            "created_at": _iso(),
            "updated_at": _iso(),
        }
        with self._lock:
            self._reqs[aid] = rec
            return dict(rec)

    def complete(self, action_id, result=None, error=None):
        """A servicer reports the outcome. Returns the updated record, or None
        if the action is unknown."""
        with self._lock:
            rec = self._reqs.get(action_id)
            if rec is None:
                return None
            rec["status"] = "failed" if error else "done"
            rec["result"] = result
            rec["error"] = error
            rec["updated_at"] = _iso()
            return dict(rec)

    def get(self, action_id):
        with self._lock:
            rec = self._reqs.get(action_id)
            return dict(rec) if rec else None

    def pending(self, namespace=None):
        """Pending actions a servicer pulls (on an action.request event),
        optionally filtered to one namespace."""
        with self._lock:
            return [dict(r) for r in self._reqs.values()
                    if r["status"] == "pending"
                    and (namespace is None or r["namespace"] == namespace)]

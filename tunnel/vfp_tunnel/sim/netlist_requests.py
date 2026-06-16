import threading
import time
import uuid


def _iso(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts or time.time()))


class NetlistRequestStore:
    """In-memory store of netlist requests routed to a connected plugin over the
    event bus -- VFP's own channel for assembling a deck, no external netlister
    (vcli etc.). A request is created `pending` and emitted as a `netlist.request`
    event; a plugin services it (vfpNetlistCellView) and posts the deck via
    `complete()`; the caller polls `get()`. Thread-safe; stdlib-only, Py 3.6+."""

    def __init__(self):
        self._reqs = {}
        self._lock = threading.Lock()

    def create(self, cellview, corner="Nominal"):
        rid = "nlr_" + uuid.uuid4().hex[:12]
        rec = {"request_id": rid, "status": "pending", "cellview": cellview,
               "corner": corner or "Nominal", "deck": None, "error": None,
               "created_at": _iso(), "updated_at": _iso()}
        with self._lock:
            self._reqs[rid] = rec
            return dict(rec)

    def complete(self, request_id, deck=None, error=None):
        """A plugin reports the result. Returns the updated record, or None if
        the request is unknown."""
        with self._lock:
            rec = self._reqs.get(request_id)
            if rec is None:
                return None
            rec["status"] = "failed" if error else "done"
            rec["deck"] = deck
            rec["error"] = error
            rec["updated_at"] = _iso()
            return dict(rec)

    def get(self, request_id):
        with self._lock:
            rec = self._reqs.get(request_id)
            return dict(rec) if rec else None

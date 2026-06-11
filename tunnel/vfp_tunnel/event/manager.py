import json
import threading
import time
import uuid

from ..config import ensure_dirs, events_dir

# How many recent events are kept in memory and served by event.list/wait.
# The on-disk log (events.jsonl) is append-only and authoritative for the
# next seq across restarts; a client whose `since` is older than oldest_seq
# has fallen behind the served window and should resync from latest_seq.
DEFAULT_RETAIN = 2000


def _iso(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts or time.time()))


class EventLog:
    """Append-only event log with a monotonic seq, JSONL persistence, and a
    blocking long-poll (wait). Thread-safe; stdlib-only, Python 3.6+."""

    def __init__(self, retain=DEFAULT_RETAIN):
        self._events = []     # recent events, ascending seq, capped to retain
        self._seq = 0         # last assigned seq (continues across restarts)
        self._retain = retain
        self._cond = threading.Condition()
        self.boot_id = uuid.uuid4().hex[:12]
        self._load()

    # ---- persistence ------------------------------------------------
    def _path(self):
        return events_dir() / "events.jsonl"

    def _load(self):
        p = self._path()
        if not p.exists():
            return
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        tail = lines[-self._retain:] if self._retain else lines
        for ln in tail:
            ln = ln.strip()
            if not ln:
                continue
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if isinstance(e, dict) and isinstance(e.get("seq"), int):
                self._events.append(e)
        # seq continues from the max ever written (scan all, cheap: ints).
        for ln in lines:
            try:
                s = json.loads(ln).get("seq")
            except (ValueError, AttributeError):
                continue
            if isinstance(s, int) and s > self._seq:
                self._seq = s

    def _append_disk(self, e):
        try:
            ensure_dirs()
            with open(str(self._path()), "a", encoding="utf-8") as f:
                f.write(json.dumps(e) + "\n")
        except OSError:
            pass

    # ---- operations -------------------------------------------------
    def emit(self, etype, payload=None):
        """Append an event {seq, ts, type, payload} and wake any waiters."""
        with self._cond:
            self._seq += 1
            e = {"seq": self._seq, "ts": _iso(), "type": etype,
                 "payload": payload or {}}
            self._events.append(e)
            if self._retain and len(self._events) > self._retain:
                self._events = self._events[-self._retain:]
            self._cond.notify_all()
        self._append_disk(e)
        return e

    def _snapshot(self, since):
        evs = [e for e in self._events if e["seq"] > since]
        oldest = self._events[0]["seq"] if self._events else 0
        return {"events": evs, "latest_seq": self._seq,
                "oldest_seq": oldest, "boot_id": self.boot_id}

    def list(self, since=0):
        """Return events with seq > *since* plus latest_seq/oldest_seq/boot_id."""
        with self._cond:
            return self._snapshot(since)

    def wait(self, since=0, timeout_s=25.0):
        """Block until an event with seq > *since* exists or *timeout_s*
        elapses, then return the same shape as list() (events may be empty)."""
        deadline = time.time() + max(0.0, timeout_s)
        with self._cond:
            snap = self._snapshot(since)
            while not snap["events"]:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self._cond.wait(remaining)
                snap = self._snapshot(since)
            return snap

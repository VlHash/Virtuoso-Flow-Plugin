"""In-memory session registry with JSON persistence under ``.vfp/sessions``.

A session represents one connected client (typically a Virtuoso Flow Plugin
instance). Records are kept in memory and mirrored to disk so the daemon can
recover them across restarts.
"""

import json
import threading
import time
import uuid

from ..config import ensure_dirs, sessions_dir


def _now():
    return time.time()


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def _fingerprint(client):
    """Stable identity of a Virtuoso process: (virtuoso_pid, virtuoso_start).

    Returns None if the client did not report both (legacy plugins), in which
    case sessions are never deduplicated.
    """
    if not isinstance(client, dict):
        return None
    pid = str(client.get("virtuoso_pid") or "").strip()
    start = str(client.get("virtuoso_start") or "").strip()
    return (pid, start) if (pid and start) else None


class Registry:
    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()
        self._load()

    # ---- persistence ----
    def _load(self):
        d = sessions_dir()
        if not d.exists():
            return
        for f in d.glob("*.json"):
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
                sid = rec.get("session_id")
                if sid:
                    self._sessions[sid] = rec
            except (OSError, ValueError):
                continue

    def _persist(self, rec):
        try:
            ensure_dirs()
            p = sessions_dir() / (rec["session_id"] + ".json")
            p.write_text(json.dumps(rec, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---- operations ----
    def register(self, client):
        """Register a client. If it carries the same (virtuoso_pid,
        virtuoso_start) fingerprint as an existing session, reuse that session
        (a plugin reload reconnects to the same record) instead of creating a
        new one.
        """
        client = client or {}
        fp = _fingerprint(client)
        ts = _now()
        with self._lock:
            existing = None
            if fp is not None:
                for rec in self._sessions.values():
                    if _fingerprint(rec.get("client")) == fp:
                        existing = rec
                        break
            if existing is not None:
                existing["client"] = client
                existing["last_seen"] = _iso(ts)
                existing["_last_ts"] = ts
                existing["reconnects"] = existing.get("reconnects", 0) + 1
                rec = existing
            else:
                sid = "s_" + uuid.uuid4().hex[:12]
                rec = {
                    "session_id": sid,
                    "client": client,
                    "created_at": _iso(ts),
                    "last_seen": _iso(ts),
                    "reconnects": 0,
                    "_created_ts": ts,
                    "_last_ts": ts,
                }
                self._sessions[sid] = rec
        self._persist(rec)
        return rec

    def reap(self, max_idle_s):
        """Remove sessions idle longer than *max_idle_s* seconds (a dead
        Virtuoso stops heartbeating). Returns the removed session_ids. A
        non-positive *max_idle_s* is a no-op.
        """
        if not max_idle_s or max_idle_s <= 0:
            return []
        cutoff = _now() - max_idle_s
        with self._lock:
            removed = [sid for sid, r in self._sessions.items()
                       if r.get("_last_ts", 0) < cutoff]
            for sid in removed:
                del self._sessions[sid]
        for sid in removed:
            try:
                (sessions_dir() / (sid + ".json")).unlink()
            except OSError:
                pass
        return removed

    def touch(self, sid):
        with self._lock:
            rec = self._sessions.get(sid)
            if rec is None:
                return None
            ts = _now()
            rec["last_seen"] = _iso(ts)
            rec["_last_ts"] = ts
        self._persist(rec)
        return rec

    def get(self, sid):
        return self._sessions.get(sid)

    def list(self):
        return sorted(self._sessions.values(),
                      key=lambda r: r.get("_created_ts", 0))

    def current(self):
        if not self._sessions:
            return None
        return max(self._sessions.values(),
                   key=lambda r: r.get("_last_ts", 0))

    @staticmethod
    def public(rec):
        """Strip internal (underscore-prefixed) keys for the wire."""
        if rec is None:
            return None
        return {k: v for k, v in rec.items() if not k.startswith("_")}

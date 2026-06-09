"""Proposal store: in-memory + on-disk persistence under .vfp/proposals.

Thread-safe, stdlib-only, Python 3.6+.
"""

import json
import threading

from ..config import ensure_dirs, proposals_dir
from .model import make_proposal, transition


class ProposalStore:
    def __init__(self):
        self._proposals = {}   # proposal_id -> proposal dict
        self._lock = threading.Lock()
        self._load()

    # ---- persistence ------------------------------------------------
    def _load(self):
        d = proposals_dir()
        if not d.exists():
            return
        for f in d.glob("*.json"):
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
                pid = p.get("proposal_id")
                if pid:
                    self._proposals[pid] = p
            except (OSError, ValueError):
                continue

    def _persist(self, p):
        try:
            ensure_dirs()
            path = proposals_dir() / (p["proposal_id"] + ".json")
            path.write_text(json.dumps(p, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---- operations -------------------------------------------------
    def create(self, data):
        """Normalise and persist a new proposal. Returns the stored dict."""
        p = make_proposal(data)
        with self._lock:
            if p["proposal_id"] in self._proposals:
                raise ValueError("duplicate proposal_id: %s" % p["proposal_id"])
            self._proposals[p["proposal_id"]] = p
        self._persist(p)
        return p

    def get(self, proposal_id):
        """Return the proposal dict or None."""
        return self._proposals.get(proposal_id)

    def list(self, status=None):
        """Return all proposals (newest-first by created_at), optionally filtered."""
        with self._lock:
            items = list(self._proposals.values())
        if status:
            items = [p for p in items if p.get("status") == status]
        return sorted(items, key=lambda p: p.get("created_at", ""), reverse=True)

    def approve(self, proposal_id):
        return self._set_status(proposal_id, "approved")

    def reject(self, proposal_id):
        return self._set_status(proposal_id, "rejected")

    def mark_applied(self, proposal_id):
        return self._set_status(proposal_id, "applied")

    def mark_failed(self, proposal_id):
        return self._set_status(proposal_id, "failed")

    def mark_rolled_back(self, proposal_id):
        return self._set_status(proposal_id, "rolled_back")

    # ---- helpers ----------------------------------------------------
    def _set_status(self, proposal_id, new_status):
        with self._lock:
            p = self._proposals.get(proposal_id)
            if p is None:
                raise KeyError("unknown proposal_id: %s" % proposal_id)
            updated = transition(p, new_status)
            self._proposals[proposal_id] = updated
        self._persist(updated)
        return updated

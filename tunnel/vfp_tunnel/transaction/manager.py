"""Transaction store: in-memory + on-disk persistence under .vfp/transactions.

Thread-safe, stdlib-only, Python 3.6+. Mirrors the proposal ProposalStore.
"""

import json
import threading

from ..config import ensure_dirs, transactions_dir
from .model import make_transaction, transition


class TransactionStore:
    def __init__(self):
        self._transactions = {}   # transaction_id -> transaction dict
        self._lock = threading.Lock()
        self._load()

    # ---- persistence ------------------------------------------------
    def _load(self):
        d = transactions_dir()
        if not d.exists():
            return
        for f in d.glob("*.json"):
            try:
                t = json.loads(f.read_text(encoding="utf-8"))
                tid = t.get("transaction_id")
                if tid:
                    self._transactions[tid] = t
            except (OSError, ValueError):
                continue

    def _persist(self, t):
        try:
            ensure_dirs()
            path = transactions_dir() / (t["transaction_id"] + ".json")
            path.write_text(json.dumps(t, indent=2), encoding="utf-8")
        except OSError:
            pass

    # ---- operations -------------------------------------------------
    def add(self, transaction):
        """Persist an already-built transaction dict (no rebuild)."""
        tid = transaction.get("transaction_id")
        if not tid:
            raise ValueError("transaction missing transaction_id")
        with self._lock:
            if tid in self._transactions:
                raise ValueError("duplicate transaction_id: %s" % tid)
            self._transactions[tid] = transaction
        self._persist(transaction)
        return transaction

    def create(self, data):
        """Build (normalise) and persist a new transaction. Returns it."""
        return self.add(make_transaction(data))

    def get(self, transaction_id):
        return self._transactions.get(transaction_id)

    def list(self, status=None):
        """Return transactions newest-first (by timestamp), optionally filtered."""
        with self._lock:
            items = list(self._transactions.values())
        if status:
            items = [t for t in items if t.get("status") == status]
        return sorted(items, key=lambda t: t.get("timestamp", ""), reverse=True)

    def last(self, status="applied"):
        """Return the most recent transaction (optionally of *status*) or None."""
        items = self.list(status=status)
        return items[0] if items else None

    def mark_rolled_back(self, transaction_id):
        return self._set_status(transaction_id, "rolled_back")

    def mark_failed(self, transaction_id):
        return self._set_status(transaction_id, "failed")

    # ---- helpers ----------------------------------------------------
    def _set_status(self, transaction_id, new_status):
        with self._lock:
            t = self._transactions.get(transaction_id)
            if t is None:
                raise KeyError("unknown transaction_id: %s" % transaction_id)
            updated = transition(t, new_status)
            self._transactions[transaction_id] = updated
        self._persist(updated)
        return updated

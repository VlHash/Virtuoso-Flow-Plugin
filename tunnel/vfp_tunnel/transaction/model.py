"""Transaction data model and state machine.

A transaction is the before/after record of an applied proposal; it is what
makes a parameter change reversible. Pure stdlib, Python 3.6+.
"""

import time
import uuid

VALID_STATUSES = ("applied", "failed", "rolled_back")

# Allowed status transitions.
TRANSITIONS = {
    "applied":     ("rolled_back", "failed"),
    "failed":      (),
    "rolled_back": (),
}


def _now():
    return time.time()


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def make_transaction(data):
    """Normalise an incoming transaction dict; assign ID + timestamp if absent.

    Returns a new dict (does not mutate *data*). An existing ``transaction_id``
    is preserved so the builder is idempotent.
    """
    t = dict(data)
    if not t.get("transaction_id"):
        t["transaction_id"] = "t_" + uuid.uuid4().hex[:12]
    t.setdefault("schema_version", "0.1")
    t.setdefault("status", "applied")
    t.setdefault("before", [])
    t.setdefault("after", [])
    ts = _now()
    if "timestamp" not in t:
        t["timestamp"] = _iso(ts)
    # Epoch seconds so the blame chain can order same-second bursts precisely
    # (the ISO timestamp is second-granular). Preserved if already present.
    t.setdefault("created_ts", ts)
    return t


def transition(transaction, new_status):
    """Return a copy of *transaction* with status set to *new_status*.

    Raises ValueError if the transition is not permitted.
    """
    current = transaction.get("status", "applied")
    allowed = TRANSITIONS.get(current, ())
    if new_status not in allowed:
        raise ValueError(
            "cannot transition %s -> %s (allowed: %s)"
            % (current, new_status, allowed or "none")
        )
    t = dict(transaction)
    t["status"] = new_status
    return t

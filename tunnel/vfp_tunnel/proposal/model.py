"""Proposal data model and state machine.

Pure stdlib, Python 3.6+.
"""

import time
import uuid

VALID_STATUSES = ("pending", "approved", "rejected", "applied", "failed", "rolled_back")
TERMINAL_STATUSES = ("applied", "failed", "rolled_back")

# Allowed status transitions.
TRANSITIONS = {
    "pending":     ("approved", "rejected"),
    "approved":    ("applied", "failed"),
    "rejected":    (),
    "applied":     ("rolled_back",),
    "failed":      (),
    "rolled_back": (),
}


def _now():
    return time.time()


def _iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def make_proposal(data):
    """Normalise an incoming proposal dict; assign ID + timestamps if absent.

    Returns a new dict (does not mutate *data*).
    """
    ts = _now()
    p = dict(data)
    if not p.get("proposal_id"):
        p["proposal_id"] = "p_" + uuid.uuid4().hex[:12]
    p.setdefault("schema_version", "0.1")
    p.setdefault("status", "pending")
    p.setdefault("created_by", "agent")
    p.setdefault("requires_user_approval", True)
    p.setdefault("changes", [])
    if "created_at" not in p:
        p["created_at"] = _iso(ts)
    p["updated_at"] = _iso(ts)
    return p


def transition(proposal, new_status):
    """Return a copy of *proposal* with status set to *new_status*.

    Raises ValueError if the transition is not permitted.
    """
    current = proposal.get("status", "pending")
    allowed = TRANSITIONS.get(current, ())
    if new_status not in allowed:
        raise ValueError(
            "cannot transition %s -> %s (allowed: %s)"
            % (current, new_status, allowed or "none")
        )
    p = dict(proposal)
    p["status"] = new_status
    p["updated_at"] = _iso(_now())
    return p

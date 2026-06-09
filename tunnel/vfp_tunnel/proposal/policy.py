"""Approval policy for proposals.

Milestone 4: stub implementation — always permits the transition.
Future milestones can check design rules, sign-off lists, etc.

Pure stdlib, Python 3.6+.
"""


def check_approve(proposal):
    """Return (allowed: bool, reason: str).

    Currently always allows approval; extend here for guard-rail logic.
    """
    return True, "ok"


def check_apply(proposal):
    """Return (allowed: bool, reason: str).

    Verifies the proposal is in 'approved' state before applying.
    """
    if proposal.get("status") != "approved":
        return False, "proposal must be in 'approved' state to apply (got %r)" \
                      % proposal.get("status")
    return True, "ok"
